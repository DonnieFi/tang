//! Read Codex JSONL sessions into the per-project database.

use crate::error::{Result, TangError};
use crate::index_store::{
    finish_session, load_checkpoint, write_sessions, Checkpoint, IndexScope, SavedSession,
    SessionDraft,
};
use crate::project::ProjectIdentity;
use regex::Regex;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodexIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub unchanged: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_codex(
    codex_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<CodexIndexResult> {
    let home = codex_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Codex sessions directory is unavailable.",
        )
    })?;
    let sessions = home.join("sessions");
    if !sessions.is_dir() {
        return Err(TangError::new(
            "missing-store",
            "The configured Codex sessions directory is unavailable.",
        ));
    }
    let namespace = format!(
        "store-{:x}",
        Sha256::digest(home.to_string_lossy().as_bytes())
    );
    let mut logs = Vec::new();
    collect_logs(&sessions, &mut logs)?;
    logs.sort();
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let prior = load_checkpoint(database_path, &project.key, "codex", &namespace)?;
    let mut checkpoint = Checkpoint::default();
    let mut skipped = 0;
    for log in logs {
        if is_symlink(&log) {
            if let Some(source_id) = source_id_for_log(&log, &namespace) {
                protected.insert(source_id);
            }
            warnings.push(format!("skipped symlinked Codex log {}", log.display()));
            continue;
        }
        if let Some((source_id, fingerprint)) = log_fingerprint(&log, &namespace) {
            if prior.should_skip(&source_id, &fingerprint) {
                checkpoint.remember(&source_id, &fingerprint, true);
                continue;
            }
        }
        match read_log(&log, &namespace, &mut warnings) {
            Ok(Some(session)) => {
                checkpoint.remember(&session.source_id, &session.fingerprint, true);
                saved.push(session);
            }
            Ok(None) => skipped += 1,
            Err(message) => {
                if let Some((source_id, _)) = log_fingerprint(&log, &namespace) {
                    if let Some(prior) = prior.fingerprints.get(&source_id).cloned() {
                        checkpoint.remember(&source_id, &prior, false);
                    }
                    protected.insert(source_id);
                }
                warnings.push(message);
            }
        }
    }
    let wrote = write_sessions(
        database_path,
        IndexScope {
            project_key: &project.key,
            adapter: "codex",
            namespace: &namespace,
            handle_prefix: "C",
        },
        &saved,
        &protected,
        &mut checkpoint,
        true,
    )?;
    Ok(CodexIndexResult {
        indexed: wrote.indexed,
        deleted: wrote.deleted,
        unchanged: wrote.unchanged,
        skipped,
        warnings,
    })
}

fn read_log(
    path: &Path,
    namespace: &str,
    warnings: &mut Vec<String>,
) -> std::result::Result<Option<SavedSession>, String> {
    let native_id = filename_id(path).ok_or_else(|| {
        format!(
            "skipped Codex log without a terminal UUID: {}",
            path.display()
        )
    })?;
    let bytes = fs::read(path).map_err(|_| format!("cannot read {}", path.display()))?;
    let text = String::from_utf8_lossy(&bytes);
    let mut metadata: Option<Value> = None;
    let mut latest: Option<String> = None;
    let mut last_lifecycle: Option<&str> = None;
    let mut turns: Vec<(String, String)> = Vec::new();
    for (number, line) in text.lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let row: Value = match serde_json::from_str(line) {
            Ok(value) => value,
            Err(_) => {
                warnings.push(format!(
                    "skipped malformed Codex JSON at {}:{}",
                    path.display(),
                    number + 1
                ));
                continue;
            }
        };
        if let Some(timestamp) = row.get("timestamp").and_then(Value::as_str) {
            latest = Some(match latest {
                Some(current) if current.as_str() > timestamp => current,
                _ => timestamp.to_string(),
            });
        }
        if row.get("type").and_then(Value::as_str) == Some("session_meta") && metadata.is_none() {
            metadata = row.get("payload").cloned();
        }
        if row.get("type").and_then(Value::as_str) == Some("event_msg") {
            let event = row
                .get("payload")
                .and_then(|payload| payload.get("type"))
                .and_then(Value::as_str);
            if event == Some("task_started") || event == Some("task_complete") {
                last_lifecycle = if event == Some("task_complete") {
                    Some("task_complete")
                } else {
                    Some("task_started")
                };
            }
        }
        if let Some(turn) = visible_turn(&row) {
            turns.push(turn);
        }
    }
    let Some(metadata) = metadata else {
        return Err(format!(
            "Codex log has no session metadata: {}",
            path.display()
        ));
    };
    let metadata_id = metadata.get("id").and_then(Value::as_str).unwrap_or("");
    if metadata_id != native_id {
        return Err(format!(
            "Codex metadata id does not match {} ",
            path.display()
        ));
    }
    let Some(cwd) = metadata.get("cwd").and_then(Value::as_str) else {
        return Err(format!(
            "Codex log has no project directory: {}",
            path.display()
        ));
    };
    let started = metadata
        .get("timestamp")
        .and_then(Value::as_str)
        .unwrap_or("1970-01-01T00:00:00Z")
        .to_string();
    let updated = latest.unwrap_or_else(|| started.clone());
    let health = if last_lifecycle == Some("task_complete") {
        "complete"
    } else {
        "unknown"
    };
    let fingerprint = format!("{:x}", Sha256::digest(&bytes));
    let locator = path.to_string_lossy();
    finish_session(SessionDraft {
        adapter: "codex",
        namespace,
        native_id: &native_id,
        locator: locator.as_ref(),
        fingerprint: &fingerprint,
        project_hint: cwd,
        started_at: &started,
        updated_at: &updated,
        health,
        title: None,
        turns,
    })
    .map(Some)
}

fn visible_turn(row: &Value) -> Option<(String, String)> {
    if row.get("type").and_then(Value::as_str) != Some("response_item") {
        return None;
    }
    let payload = row.get("payload")?;
    if payload.get("type").and_then(Value::as_str) != Some("message") {
        return None;
    }
    let role = match payload.get("role").and_then(Value::as_str) {
        Some("user") => "user",
        Some("assistant") => "agent",
        _ => return None,
    };
    let expected = if role == "user" {
        "input_text"
    } else {
        "output_text"
    };
    let text = payload
        .get("content")
        .and_then(Value::as_array)?
        .iter()
        .filter_map(|item| {
            if item.get("type").and_then(Value::as_str) == Some(expected) {
                item.get("text").and_then(Value::as_str)
            } else {
                None
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    if text.trim().is_empty() {
        None
    } else {
        Some((role.to_string(), text))
    }
}

fn collect_logs(dir: &Path, logs: &mut Vec<PathBuf>) -> Result<()> {
    let entries = fs::read_dir(dir).map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Codex sessions directory cannot be read.",
        )
    })?;
    for entry in entries {
        let entry = entry.map_err(|_| {
            TangError::new(
                "missing-store",
                "The configured Codex sessions directory cannot be read.",
            )
        })?;
        let path = entry.path();
        if is_symlink(&path) {
            continue;
        }
        if path.is_dir() {
            collect_logs(&path, logs)?;
        } else if path.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
            logs.push(path);
        }
    }
    Ok(())
}

fn filename_id(path: &Path) -> Option<String> {
    let name = path.file_name()?.to_str()?;
    static ID: OnceLock<Regex> = OnceLock::new();
    let id = ID.get_or_init(|| {
        Regex::new(r"(?i)([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\.jsonl$")
            .expect("codex id")
    });
    id.captures(name)
        .and_then(|caps| caps.get(1))
        .map(|item| item.as_str().to_ascii_lowercase())
}

fn source_id_for_log(path: &Path, namespace: &str) -> Option<String> {
    filename_id(path).map(|native_id| format!("codex:{namespace}:{native_id}"))
}

fn log_fingerprint(path: &Path, namespace: &str) -> Option<(String, String)> {
    let source_id = source_id_for_log(path, namespace)?;
    let bytes = fs::read(path).ok()?;
    Some((source_id, format!("{:x}", Sha256::digest(&bytes))))
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(true)
}
