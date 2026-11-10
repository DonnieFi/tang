//! Read Claude Code project transcripts into the per-project database.

use crate::error::{Result, TangError};
use crate::index_store::{
    file_updated_at, finish_session, load_checkpoint, write_sessions, Checkpoint, IndexScope,
    SessionDraft,
};
use crate::project::ProjectIdentity;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

pub struct ClaudeIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub unchanged: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_claude(
    claude_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<ClaudeIndexResult> {
    let home = claude_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Claude home is unavailable.",
        )
    })?;
    let namespace = format!(
        "store-{:x}",
        Sha256::digest(home.to_string_lossy().as_bytes())
    );
    let mut logs = collect_claude_logs(&home)?;
    logs.sort();
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let prior = load_checkpoint(database_path, &project.key, "claude", &namespace)?;
    let mut checkpoint = Checkpoint::default();
    let mut skipped = 0;
    for log in logs {
        if is_symlink(&log) {
            if let Some(source_id) = source_id_for_transcript(&log, &namespace) {
                protected.insert(source_id);
            }
            warnings.push(format!(
                "skipped symlinked Claude transcript {}",
                log.display()
            ));
            continue;
        }
        if let Some((source_id, fingerprint)) = transcript_fingerprint(&log, &namespace) {
            if prior.should_skip(&source_id, &fingerprint) {
                checkpoint.remember(&source_id, &fingerprint, true);
                continue;
            }
        }
        match read_transcript(&log, &namespace, &mut warnings) {
            Ok(Some(record)) => {
                checkpoint.remember(&record.source_id, &record.fingerprint, true);
                saved.push(record);
            }
            Ok(None) => {
                if let Some(source_id) = source_id_for_transcript(&log, &namespace) {
                    if let Some(prior) = prior.fingerprints.get(&source_id).cloned() {
                        checkpoint.remember(&source_id, &prior, true);
                    }
                    protected.insert(source_id);
                }
                skipped += 1;
            }
            Err(message) => {
                if let Some(source_id) = source_id_for_transcript(&log, &namespace) {
                    if let Some(prior) = prior.fingerprints.get(&source_id).cloned() {
                        checkpoint.remember(&source_id, &prior, false);
                    }
                    protected.insert(source_id);
                }
                skipped += 1;
                warnings.push(message);
            }
        }
    }
    let wrote = write_sessions(
        database_path,
        IndexScope {
            project_key: &project.key,
            adapter: "claude",
            namespace: &namespace,
            handle_prefix: "L",
        },
        &saved,
        &protected,
        &mut checkpoint,
        true,
    )?;
    Ok(ClaudeIndexResult {
        indexed: wrote.indexed,
        deleted: wrote.deleted,
        unchanged: wrote.unchanged,
        skipped,
        warnings,
    })
}

fn read_transcript(
    path: &Path,
    namespace: &str,
    warnings: &mut Vec<String>,
) -> std::result::Result<Option<crate::index_store::SavedSession>, String> {
    let native_id = path
        .file_stem()
        .and_then(|name| name.to_str())
        .unwrap_or("")
        .to_string();
    let bytes = fs::read(path).map_err(|_| format!("cannot read {}", path.display()))?;
    let mut turns = Vec::new();
    let mut title: Option<String> = None;
    let mut started: Option<String> = None;
    let mut updated: Option<String> = None;
    let mut recorded_cwd: Option<String> = None;
    for (number, line) in String::from_utf8_lossy(&bytes).lines().enumerate() {
        if line.trim().is_empty() {
            continue;
        }
        let row: Value = match serde_json::from_str(line) {
            Ok(value) => value,
            Err(_) => {
                warnings.push(format!(
                    "skipped malformed Claude transcript {}:{}",
                    path.display(),
                    number + 1
                ));
                continue;
            }
        };
        if row.get("type").and_then(Value::as_str) == Some("ai-title") {
            if let Some(value) = row.get("aiTitle").and_then(Value::as_str) {
                if !value.trim().is_empty() {
                    title = Some(value.to_string());
                }
            }
        }
        if let Some(timestamp) = row.get("timestamp").and_then(Value::as_str) {
            if started.as_deref().is_none_or(|current| timestamp < current) {
                started = Some(timestamp.to_string());
            }
            if updated.as_deref().is_none_or(|current| timestamp > current) {
                updated = Some(timestamp.to_string());
            }
        }
        if recorded_cwd.is_none() {
            if let Some(cwd) = row.get("cwd").and_then(Value::as_str) {
                if !cwd.trim().is_empty() {
                    recorded_cwd = Some(cwd.to_string());
                }
            }
        }
        let role = match row.get("type").and_then(Value::as_str) {
            Some("user") => "user",
            Some("assistant") => "agent",
            _ => continue,
        };
        let text = visible_text(&row);
        if !text.trim().is_empty() {
            turns.push((role.to_string(), text));
        }
    }
    let hint = recorded_cwd.unwrap_or_else(|| {
        path.parent()
            .map(|parent| parent.to_string_lossy().to_string())
            .unwrap_or_default()
    });
    let fallback = file_updated_at(path);
    let started = started.unwrap_or_else(|| fallback.clone());
    let updated = updated.unwrap_or(fallback);
    let fingerprint = format!("{:x}", Sha256::digest(&bytes));
    let locator = path.to_string_lossy();
    finish_session(SessionDraft {
        adapter: "claude",
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
    })
    .map(Some)
}

fn collect_claude_logs(home: &Path) -> Result<Vec<PathBuf>> {
    let projects = home.join("projects");
    if !projects.is_dir() {
        return Err(TangError::new(
            "missing-store",
            "No Claude transcripts were found.",
        ));
    }
    let mut logs = Vec::new();
    for entry in fs::read_dir(&projects).map_err(|_| {
        TangError::new(
            "missing-store",
            "The Claude project directory could not be listed.",
        )
    })? {
        let path = entry
            .map_err(|_| {
                TangError::new(
                    "missing-store",
                    "The Claude project directory could not be listed.",
                )
            })?
            .path();
        if !path.is_dir() {
            continue;
        }
        for file in fs::read_dir(&path).map_err(|_| {
            TangError::new(
                "missing-store",
                "The Claude project directory could not be listed.",
            )
        })? {
            let file = file
                .map_err(|_| {
                    TangError::new(
                        "missing-store",
                        "The Claude project directory could not be listed.",
                    )
                })?
                .path();
            if file.extension().and_then(|ext| ext.to_str()) == Some("jsonl") {
                logs.push(file);
            }
        }
    }
    if logs.is_empty() {
        return Err(TangError::new(
            "missing-store",
            "No Claude transcripts were found.",
        ));
    }
    Ok(logs)
}

fn source_id_for_transcript(path: &Path, namespace: &str) -> Option<String> {
    let native_id = path.file_stem()?.to_str()?;
    Some(format!("claude:{namespace}:{native_id}"))
}

fn transcript_fingerprint(path: &Path, namespace: &str) -> Option<(String, String)> {
    let source_id = source_id_for_transcript(path, namespace)?;
    let bytes = fs::read(path).ok()?;
    Some((source_id, format!("{:x}", Sha256::digest(&bytes))))
}

fn visible_text(row: &Value) -> String {
    let Some(message) = row.get("message") else {
        return String::new();
    };
    match message.get("content") {
        Some(Value::String(text)) => text.clone(),
        Some(Value::Array(blocks)) => blocks
            .iter()
            .filter(|block| block.get("type").and_then(Value::as_str) == Some("text"))
            .filter_map(|block| block.get("text").and_then(Value::as_str))
            .collect::<Vec<_>>()
            .join("\n"),
        _ => String::new(),
    }
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(true)
}
