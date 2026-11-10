//! Read Antigravity history and brain transcripts into the project database.

use crate::error::{Result, TangError};
use crate::index_store::{
    file_updated_at, finish_session, load_checkpoint, write_sessions, Checkpoint, IndexScope,
    SessionDraft,
};
use crate::project::{owns_project, ProjectIdentity};
use crate::timeutil::rfc3339_secs;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::Path;

pub struct AntigravityIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub unchanged: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_antigravity(
    antigravity_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<AntigravityIndexResult> {
    let home = antigravity_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured Antigravity home is unavailable.",
        )
    })?;
    let history_path = home.join("history.jsonl");
    if is_symlink(&history_path) {
        return Ok(AntigravityIndexResult {
            indexed: 0,
            deleted: 0,
            unchanged: 0,
            skipped: 0,
            warnings: vec![format!(
                "skipped symlinked Antigravity history {}",
                history_path.display()
            )],
        });
    }
    if !history_path.is_file() {
        return Err(TangError::new(
            "missing-store",
            "No Antigravity history was found.",
        ));
    }
    let namespace = format!(
        "store-{:x}",
        Sha256::digest(home.to_string_lossy().as_bytes())
    );
    let history = fs::read_to_string(&history_path).map_err(|_| {
        TangError::new(
            "missing-store",
            "The Antigravity history could not be read.",
        )
    })?;
    let mut entries: BTreeMap<String, (String, String, String)> = BTreeMap::new();
    let mut skipped = 0;
    for line in history.lines() {
        if line.trim().is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        let Some(conversation_id) = row.get("conversationId").and_then(Value::as_str) else {
            continue;
        };
        let Some(workspace) = row.get("workspace").and_then(Value::as_str) else {
            continue;
        };
        if !owns_project(workspace, project) {
            skipped += 1;
            continue;
        }
        let started =
            millis(row.get("timestamp")).unwrap_or_else(|| "1970-01-01T00:00:00Z".to_string());
        let title = row
            .get("display")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_string();
        entries.insert(
            conversation_id.to_string(),
            (workspace.to_string(), started, title),
        );
    }
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let prior = load_checkpoint(database_path, &project.key, "antigravity", &namespace)?;
    let mut checkpoint = Checkpoint::default();
    for (conversation_id, (workspace, started, title)) in entries {
        let transcript = home
            .join("brain")
            .join(&conversation_id)
            .join(".system_generated/logs/transcript.jsonl");
        if is_symlink(&transcript) {
            protected.insert(format!("antigravity:{namespace}:{conversation_id}"));
            warnings.push(format!(
                "skipped symlinked Antigravity transcript {}",
                transcript.display()
            ));
            continue;
        }
        if !transcript.is_file() {
            skipped += 1;
            continue;
        }
        if let Some((source_id, fingerprint)) = transcript_fingerprint(
            &transcript,
            &namespace,
            &conversation_id,
            &workspace,
            &started,
            &title,
        ) {
            if prior.should_skip(&source_id, &fingerprint) {
                checkpoint.remember(&source_id, &fingerprint, true);
                continue;
            }
        }
        match read_transcript(
            &transcript,
            &namespace,
            &conversation_id,
            &workspace,
            &started,
            &title,
        ) {
            Ok(record) => {
                checkpoint.remember(&record.source_id, &record.fingerprint, true);
                saved.push(record);
            }
            Err(message) => {
                let source_id = format!("antigravity:{namespace}:{conversation_id}");
                if let Some(prior) = prior.fingerprints.get(&source_id).cloned() {
                    checkpoint.remember(&source_id, &prior, false);
                }
                protected.insert(source_id);
                warnings.push(message);
            }
        }
    }
    let wrote = write_sessions(
        database_path,
        IndexScope {
            project_key: &project.key,
            adapter: "antigravity",
            namespace: &namespace,
            handle_prefix: "A",
        },
        &saved,
        &protected,
        &mut checkpoint,
        true,
    )?;
    Ok(AntigravityIndexResult {
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
    native_id: &str,
    workspace: &str,
    started: &str,
    title: &str,
) -> std::result::Result<crate::index_store::SavedSession, String> {
    let bytes = fs::read(path).map_err(|_| format!("cannot read {}", path.display()))?;
    let mut turns = Vec::new();
    let mut updated = started.to_string();
    for line in String::from_utf8_lossy(&bytes).lines() {
        if line.trim().is_empty() {
            continue;
        }
        let Ok(row) = serde_json::from_str::<Value>(line) else {
            continue;
        };
        if let Some(timestamp) = row.get("created_at").and_then(Value::as_str) {
            if timestamp > updated.as_str() {
                updated = timestamp.to_string();
            }
        }
        let source = row.get("source").and_then(Value::as_str);
        let event_type = row.get("type").and_then(Value::as_str);
        let role = match (source, event_type) {
            (Some("USER_EXPLICIT"), Some("USER_INPUT")) => "user",
            (Some("MODEL"), Some("PLANNER_RESPONSE")) => "agent",
            _ => continue,
        };
        let text = visible_text(&row, role);
        if !text.trim().is_empty() {
            turns.push((role.to_string(), text));
        }
    }
    if updated == started {
        let fallback = file_updated_at(path);
        if fallback > updated {
            updated = fallback;
        }
    }
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    hasher.update(workspace.as_bytes());
    hasher.update(started.as_bytes());
    hasher.update(title.as_bytes());
    let fingerprint = format!("{:x}", hasher.finalize());
    let locator = path.to_string_lossy();
    finish_session(SessionDraft {
        adapter: "antigravity",
        namespace,
        native_id,
        locator: locator.as_ref(),
        fingerprint: &fingerprint,
        project_hint: workspace,
        started_at: started,
        updated_at: &updated,
        health: "unknown",
        title: Some(title.to_string()).filter(|value| !value.is_empty()),
        turns,
    })
}

fn transcript_fingerprint(
    path: &Path,
    namespace: &str,
    native_id: &str,
    workspace: &str,
    started: &str,
    title: &str,
) -> Option<(String, String)> {
    let bytes = fs::read(path).ok()?;
    let mut hasher = Sha256::new();
    hasher.update(&bytes);
    hasher.update(workspace.as_bytes());
    hasher.update(started.as_bytes());
    hasher.update(title.as_bytes());
    Some((
        format!("antigravity:{namespace}:{native_id}"),
        format!("{:x}", hasher.finalize()),
    ))
}

fn visible_text(row: &Value, role: &str) -> String {
    let Some(content) = row.get("content").and_then(Value::as_str) else {
        return String::new();
    };
    if role == "user" {
        if let (Some(start), Some(end)) = (
            content.find("<USER_REQUEST>"),
            content.find("</USER_REQUEST>"),
        ) {
            return content[start + "<USER_REQUEST>".len()..end]
                .trim()
                .to_string();
        }
        return content.trim().to_string();
    }
    if is_agent_prose(content) {
        content.trim().to_string()
    } else {
        String::new()
    }
}

pub(crate) fn is_agent_prose(text: &str) -> bool {
    let stripped = text.trim();
    if stripped.is_empty() || stripped.starts_with("Created At:") {
        return false;
    }
    if [
        "Completed At:",
        "File Path:",
        "CommandLine",
        "toolAction",
        "toolSummary",
        "Output:",
    ]
    .iter()
    .any(|marker| stripped.contains(marker))
    {
        return false;
    }
    if stripped.contains("file:///") {
        return false;
    }
    stripped.chars().count() <= 4096
}

fn millis(value: Option<&Value>) -> Option<String> {
    let millis = value?.as_i64()?;
    Some(rfc3339_secs((millis / 1000).max(0) as u64))
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(false)
}
