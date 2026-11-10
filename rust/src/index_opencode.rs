//! Read OpenCode session export JSON into the per-project database.

use crate::error::{Result, TangError};
use crate::index_store::{
    finish_session, load_checkpoint, write_sessions, Checkpoint, IndexScope, SavedSession,
    SessionDraft,
};
use crate::project::ProjectIdentity;
use crate::timeutil::rfc3339_secs;
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

pub struct OpenCodeIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub unchanged: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_opencode(
    opencode_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<OpenCodeIndexResult> {
    let home = opencode_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured OpenCode export directory is unavailable.",
        )
    })?;
    let namespace = opencode_namespace();
    let mut exports = Vec::new();
    collect_exports(&home, &mut exports)?;
    exports.sort();
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let prior = load_checkpoint(database_path, &project.key, "opencode", &namespace)?;
    let mut checkpoint = Checkpoint::default();
    let mut skipped = 0;
    for path in exports {
        if is_symlink(&path) {
            warnings.push(format!(
                "skipped symlinked OpenCode export {}",
                path.display()
            ));
            continue;
        }
        if let Some((source_id, fingerprint)) = export_fingerprint(&path, &namespace) {
            if prior.should_skip(&source_id, &fingerprint) {
                checkpoint.remember(&source_id, &fingerprint, true);
                continue;
            }
        }
        let peeked = fs::read(&path)
            .ok()
            .and_then(|bytes| peek_export_id(&bytes));
        match read_export(&path, &namespace) {
            Ok(Some(record)) => {
                checkpoint.remember(&record.source_id, &record.fingerprint, true);
                saved.push(record);
            }
            Ok(None) => skipped += 1,
            Err(message) => {
                if let Some(native_id) = peeked {
                    let source_id = format!("opencode:{namespace}:{native_id}");
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
            adapter: "opencode",
            namespace: &namespace,
            handle_prefix: "O",
        },
        &saved,
        &protected,
        &mut checkpoint,
        true,
    )?;
    Ok(OpenCodeIndexResult {
        indexed: wrote.indexed,
        deleted: wrote.deleted,
        unchanged: wrote.unchanged,
        skipped,
        warnings,
    })
}

fn opencode_namespace() -> String {
    let executable = find_executable("opencode")
        .map(|path| path.to_string_lossy().into_owned())
        .unwrap_or_else(|| {
            std::env::current_dir()
                .unwrap_or_default()
                .join("opencode")
                .to_string_lossy()
                .into_owned()
        });
    let data_home = std::env::var_os("XDG_DATA_HOME")
        .filter(|value| !value.is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            std::env::var_os("HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."))
                .join(".local")
                .join("share")
        });
    let digest =
        Sha256::digest(format!("{executable}\0{}", data_home.to_string_lossy()).as_bytes());
    format!("store-{:x}", digest)
}

fn find_executable(name: &str) -> Option<PathBuf> {
    let path = std::env::var_os("PATH")?;
    for directory in std::env::split_paths(&path) {
        let candidate = directory.join(name);
        if candidate.is_file() {
            return Some(candidate);
        }
    }
    None
}

fn read_export(path: &Path, namespace: &str) -> std::result::Result<Option<SavedSession>, String> {
    let bytes = fs::read(path).map_err(|_| format!("cannot read {}", path.display()))?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| format!("malformed OpenCode export {}", path.display()))?;
    let info = value
        .get("info")
        .ok_or_else(|| format!("OpenCode export has no info object: {}", path.display()))?;
    let native_id = info
        .get("id")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("OpenCode export has no session id: {}", path.display()))?
        .to_string();
    let hint = info
        .get("directory")
        .and_then(Value::as_str)
        .ok_or_else(|| format!("OpenCode export has no directory: {}", path.display()))?
        .to_string();
    let title = info
        .get("title")
        .and_then(Value::as_str)
        .map(str::to_string);
    let created = millis(info.get("time").and_then(|time| time.get("created")));
    let updated = millis(info.get("time").and_then(|time| time.get("updated"))).or(created.clone());
    let messages = value
        .get("messages")
        .and_then(Value::as_array)
        .ok_or_else(|| format!("OpenCode export has no messages: {}", path.display()))?;
    let mut turns = Vec::new();
    for message in messages {
        let role = match message
            .get("info")
            .and_then(|info| info.get("role"))
            .and_then(Value::as_str)
        {
            Some("user") => "user",
            Some("assistant") => "agent",
            _ => continue,
        };
        let Some(parts) = message.get("parts").and_then(Value::as_array) else {
            continue;
        };
        for part in parts {
            if part.get("type").and_then(Value::as_str) != Some("text") {
                continue;
            }
            if let Some(text) = part.get("text").and_then(Value::as_str) {
                if !text.trim().is_empty() {
                    turns.push((role.to_string(), text.to_string()));
                }
            }
        }
    }
    let fingerprint = format!("{:x}", Sha256::digest(&bytes));
    let locator = path.to_string_lossy();
    let started = created.unwrap_or_else(|| "1970-01-01T00:00:00Z".to_string());
    let revised = updated.unwrap_or_else(|| "1970-01-01T00:00:00Z".to_string());
    finish_session(SessionDraft {
        adapter: "opencode",
        namespace,
        native_id: &native_id,
        locator: locator.as_ref(),
        fingerprint: &fingerprint,
        project_hint: &hint,
        started_at: &started,
        updated_at: &revised,
        health: "unknown",
        title,
        turns,
    })
    .map(Some)
}

fn export_fingerprint(path: &Path, namespace: &str) -> Option<(String, String)> {
    let bytes = fs::read(path).ok()?;
    let native_id = peek_export_id(&bytes)?;
    Some((
        format!("opencode:{namespace}:{native_id}"),
        format!("{:x}", Sha256::digest(&bytes)),
    ))
}

fn peek_export_id(bytes: &[u8]) -> Option<String> {
    let text = String::from_utf8_lossy(bytes);
    let marker = "\"id\"";
    let start = text.find(marker)? + marker.len();
    let rest = text[start..].trim_start();
    let rest = rest.strip_prefix(':')?.trim_start();
    let rest = rest.strip_prefix('"')?;
    let end = rest.find('"')?;
    let native_id = &rest[..end];
    if native_id.is_empty() || native_id.contains('\\') {
        None
    } else {
        Some(native_id.to_string())
    }
}

fn millis(value: Option<&Value>) -> Option<String> {
    let millis = value?.as_i64()?;
    Some(rfc3339_secs((millis / 1000).max(0) as u64))
}

fn collect_exports(dir: &Path, found: &mut Vec<PathBuf>) -> Result<()> {
    if !dir.is_dir() {
        return Err(TangError::new(
            "missing-store",
            "The configured OpenCode export directory is unavailable.",
        ));
    }
    let entries = fs::read_dir(dir).map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured OpenCode export directory cannot be read.",
        )
    })?;
    for entry in entries {
        let path = entry
            .map_err(|_| {
                TangError::new(
                    "missing-store",
                    "The configured OpenCode export directory cannot be read.",
                )
            })?
            .path();
        if is_symlink(&path) {
            continue;
        }
        if path.is_dir() {
            collect_exports(&path, found)?;
        } else if is_export_file(&path) {
            found.push(path);
        }
    }
    Ok(())
}

fn is_export_file(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    name.ends_with(".json") && name.contains("export")
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(true)
}
