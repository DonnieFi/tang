//! Read Grok Build session directories into the per-project database.

use crate::error::{Result, TangError};
use crate::index_store::{finish_session, write_sessions, SavedSession, SessionDraft};
use crate::project::{owns_project, ProjectIdentity};
use crate::timeutil::rfc3339_secs;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;

pub struct GrokIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_grok(
    grok_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<GrokIndexResult> {
    let home = grok_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Grok sessions directory is unavailable.",
        )
    })?;
    let root = home.join("sessions");
    if !root.is_dir() {
        return Err(TangError::new(
            "missing-store",
            "The configured Grok sessions directory is unavailable.",
        ));
    }
    let namespace = format!(
        "store-{:x}",
        Sha256::digest(home.to_string_lossy().as_bytes())
    );
    let mut sessions = Vec::new();
    collect_sessions(&root, &mut sessions)?;
    sessions.sort();
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let mut skipped = 0;
    for session in sessions {
        match read_session(&session, &namespace) {
            Ok(parsed) => {
                warnings.extend(parsed.warnings);
                if parsed.protect {
                    if let Some(source_id) = source_id_for_session(&session, &namespace) {
                        protected.insert(source_id);
                    }
                }
                if let Some(record) = parsed.saved {
                    if !owns_project(&record.project_hint, project) {
                        // A foreign project is not proof that this project's row is
                        // gone; keep the last known row instead of deleting it.
                        protected.insert(record.source_id.clone());
                        skipped += 1;
                        continue;
                    }
                    saved.push(record);
                } else if !parsed.protect {
                    skipped += 1;
                }
            }
            Err(message) => {
                if let Some(source_id) = source_id_for_session(&session, &namespace) {
                    protected.insert(source_id);
                }
                warnings.push(message);
            }
        }
    }
    let wrote = write_sessions(
        database_path,
        &project.key,
        "grok",
        &namespace,
        "G",
        &saved,
        &protected,
    )?;
    Ok(GrokIndexResult {
        indexed: wrote.indexed,
        deleted: wrote.deleted,
        skipped,
        warnings,
    })
}

struct ParsedSession {
    saved: Option<SavedSession>,
    warnings: Vec<String>,
    protect: bool,
}

fn read_session(session_dir: &Path, namespace: &str) -> std::result::Result<ParsedSession, String> {
    if is_symlink(session_dir) {
        return Err(format!(
            "skipped symlinked Grok session {}",
            session_dir.display()
        ));
    }
    let native_id = session_dir
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("")
        .to_string();
    if native_id.is_empty() {
        return Err(format!(
            "Grok session directory has no name: {}",
            session_dir.display()
        ));
    }
    let mut warnings = Vec::new();
    let summary_path = session_dir.join("summary.json");
    let summary_present = present_file(&summary_path, "summary")?;
    let (summary_bytes, summary) = if summary_present {
        let bytes = fs::read(&summary_path)
            .map_err(|_| format!("cannot read {}", summary_path.display()))?;
        let summary: Value = serde_json::from_slice(&bytes)
            .map_err(|_| format!("malformed Grok summary {}", summary_path.display()))?;
        (bytes, Some(summary))
    } else {
        warnings.push(format!(
            "Grok session is missing summary metadata; filesystem times were used: {}",
            session_dir.display()
        ));
        (Vec::new(), None)
    };
    let fallback = directory_mtime(session_dir);
    let hint = summary
        .as_ref()
        .and_then(|summary| {
            summary
                .get("git_root_dir")
                .and_then(Value::as_str)
                .filter(|value| !value.is_empty())
                .map(str::to_string)
        })
        .or_else(|| group_hint(session_dir))
        .ok_or_else(|| {
            format!(
                "Grok session has no project hint: {}",
                session_dir.display()
            )
        })?;
    let started = summary
        .as_ref()
        .and_then(|summary| summary.get("created_at").and_then(Value::as_str))
        .unwrap_or(if summary.is_none() {
            fallback.as_str()
        } else {
            "1970-01-01T00:00:00Z"
        })
        .to_string();
    let updated = summary
        .as_ref()
        .and_then(|summary| summary.get("updated_at").and_then(Value::as_str))
        .unwrap_or(started.as_str())
        .to_string();
    let title = summary
        .as_ref()
        .and_then(|summary| summary.get("generated_title").and_then(Value::as_str))
        .map(str::to_string);
    let updates = session_dir.join("updates.jsonl");
    let updates_present = present_file(&updates, "updates")?;
    let update_bytes = if updates_present {
        fs::read(&updates).map_err(|_| format!("cannot read {}", updates.display()))?
    } else {
        warnings.push(format!(
            "Grok session is missing its update stream: {}",
            updates.display()
        ));
        Vec::new()
    };
    let mut turns = Vec::new();
    for (number, line) in String::from_utf8_lossy(&update_bytes).lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let row: Value = serde_json::from_str(line)
            .map_err(|_| format!("malformed Grok update {}:{}", updates.display(), number + 1))?;
        if let Some(turn) = visible_update(&row, &native_id) {
            turns.push(turn);
        }
    }
    let mut fingerprint = Sha256::new();
    fingerprint.update(&summary_bytes);
    fingerprint.update(&update_bytes);
    let fingerprint = format!("{:x}", fingerprint.finalize());
    let locator = session_dir.to_string_lossy();
    let saved = finish_session(SessionDraft {
        adapter: "grok",
        namespace,
        native_id: &native_id,
        locator: locator.as_ref(),
        fingerprint: &fingerprint,
        project_hint: &hint,
        started_at: &started,
        updated_at: &updated,
        health: "unknown",
        title,
        turns,
    })?;
    Ok(ParsedSession {
        saved: Some(saved),
        warnings,
        protect: false,
    })
}

fn group_hint(session_dir: &Path) -> Option<String> {
    let group = session_dir.parent()?;
    let cwd = group.join(".cwd");
    if cwd.is_file() && !is_symlink(&cwd) {
        if let Ok(text) = fs::read_to_string(&cwd) {
            let trimmed = text.trim();
            if !trimmed.is_empty() {
                return Some(trimmed.to_string());
            }
        }
    }
    group
        .file_name()
        .and_then(|name| name.to_str())
        .map(percent_decode)
        .filter(|value| !value.is_empty())
}

fn directory_mtime(path: &Path) -> String {
    let seconds = fs::metadata(path)
        .and_then(|meta| meta.modified())
        .ok()
        .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
        .map(|duration| duration.as_secs())
        .unwrap_or(0);
    rfc3339_secs(seconds)
}

fn visible_update(row: &Value, native_id: &str) -> Option<(String, String)> {
    let method = row.get("method").and_then(Value::as_str)?;
    if method != "session/update" && method != "_x.ai/session/update" {
        return None;
    }
    let params = row.get("params")?;
    if params.get("sessionId").and_then(Value::as_str) != Some(native_id) {
        return None;
    }
    let body = params.get("update")?;
    let kind = body.get("sessionUpdate").and_then(Value::as_str)?;
    let role = match kind {
        "user_message_chunk" => "user",
        "agent_message_chunk" => "agent",
        _ => return None,
    };
    let content = body.get("content")?;
    if content.get("type").and_then(Value::as_str) != Some("text") {
        return None;
    }
    let text = content.get("text").and_then(Value::as_str)?;
    if text.trim().is_empty() {
        None
    } else {
        Some((role.to_string(), text.to_string()))
    }
}

fn collect_sessions(dir: &Path, found: &mut Vec<PathBuf>) -> Result<()> {
    let entries = fs::read_dir(dir).map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Grok sessions directory cannot be read.",
        )
    })?;
    for entry in entries {
        let path = entry
            .map_err(|_| {
                TangError::new(
                    "missing-store",
                    "The configured Grok sessions directory cannot be read.",
                )
            })?
            .path();
        if is_symlink(&path) {
            continue;
        }
        if path.is_dir() {
            let has_session_file = ["summary.json", "updates.jsonl"].iter().any(|name| {
                path.join(name)
                    .symlink_metadata()
                    .map(|meta| meta.file_type().is_symlink() || meta.is_file())
                    .unwrap_or(false)
            });
            if has_session_file {
                found.push(path);
            } else {
                collect_sessions(&path, found)?;
            }
        }
    }
    Ok(())
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(true)
}

fn present_file(path: &Path, label: &str) -> std::result::Result<bool, String> {
    match path.symlink_metadata() {
        Ok(meta) if meta.file_type().is_symlink() => {
            Err(format!("skipped symlinked Grok {label} {}", path.display()))
        }
        Ok(meta) => Ok(meta.is_file()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(_) => Err(format!("cannot read {}", path.display())),
    }
}

fn source_id_for_session(session_dir: &Path, namespace: &str) -> Option<String> {
    let native_id = session_dir.file_name()?.to_str()?;
    Some(format!("grok:{namespace}:{native_id}"))
}

fn percent_decode(value: &str) -> String {
    let bytes = value.as_bytes();
    let mut out = Vec::new();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' && index + 2 < bytes.len() {
            if let Ok(decoded) = u8::from_str_radix(
                std::str::from_utf8(&bytes[index + 1..index + 3]).unwrap_or(""),
                16,
            ) {
                out.push(decoded);
                index += 3;
                continue;
            }
        }
        out.push(bytes[index]);
        index += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}
