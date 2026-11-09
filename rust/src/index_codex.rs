//! Read Codex JSONL sessions into the per-project database.

use crate::error::{storage, Result, TangError};
use crate::project::ProjectIdentity;
use crate::redact::{redact, ContentKind};
use crate::timeutil::rfc3339_now;
use regex::Regex;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;
use std::time::Duration;

const EXCERPT_CHARS: usize = 500;
const MAX_EXCERPTS: usize = 4;
const SEARCH_CHARS: usize = 6_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CodexIndexResult {
    pub indexed: i64,
    pub deleted: i64,
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
    let mut records = Vec::new();
    let mut warnings = Vec::new();
    let mut skipped = 0;
    for log in logs {
        if log
            .symlink_metadata()
            .map(|meta| meta.file_type().is_symlink())
            .unwrap_or(true)
        {
            warnings.push(format!("skipped symlinked Codex log {}", log.display()));
            continue;
        }
        match read_log(&log, &namespace) {
            Ok(Some(record)) => {
                if !belongs_to_project(&record.project_hint, project) {
                    skipped += 1;
                    continue;
                }
                records.push(record);
            }
            Ok(None) => skipped += 1,
            Err(message) => warnings.push(message),
        }
    }
    let mut database = open_project_database(database_path)?;
    let indexed_at = rfc3339_now();
    let tx = database
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let mut indexed = 0;
    let mut seen = Vec::new();
    for record in &records {
        upsert_record(&tx, record, &project.key, &indexed_at)?;
        seen.push(record.source_id.clone());
        indexed += 1;
    }
    let deleted = delete_missing(&tx, &project.key, &namespace, &seen)?;
    tx.commit().map_err(storage)?;
    Ok(CodexIndexResult {
        indexed,
        deleted,
        skipped,
        warnings,
    })
}

struct CodexRecord {
    source_id: String,
    native_id: String,
    namespace: String,
    locator: String,
    fingerprint: String,
    project_hint: String,
    started_at: String,
    updated_at: String,
    health: String,
    title: Option<String>,
    search_text: String,
    content_json: String,
    byte_count: i64,
}

fn read_log(path: &Path, namespace: &str) -> std::result::Result<Option<CodexRecord>, String> {
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
                return Err(format!(
                    "malformed JSON at {}:{}",
                    path.display(),
                    number + 1
                ));
            }
        };
        if let Some(timestamp) = row.get("timestamp").and_then(Value::as_str) {
            latest = Some(match latest {
                Some(current) if current > timestamp.to_string() => current,
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
    let redacted_turns: Vec<(String, String)> = turns
        .into_iter()
        .map(|(role, text)| (role, redact(&text, ContentKind::VisibleText)))
        .filter(|(_, text)| !text.trim().is_empty())
        .collect();
    let title = redacted_turns
        .iter()
        .find(|(role, _)| role == "user")
        .map(|(_, text)| text.chars().take(96).collect::<String>());
    let search_text = bound_chars(
        &redacted_turns
            .iter()
            .map(|(_, text)| text.as_str())
            .collect::<Vec<_>>()
            .join("\n"),
        SEARCH_CHARS,
    );
    let excerpts: Vec<Value> = redacted_turns
        .iter()
        .take(MAX_EXCERPTS)
        .map(|(role, text)| {
            json!({
                "role": role,
                "text": bound_chars(text, EXCERPT_CHARS),
            })
        })
        .collect();
    let content = json!({
        "display_name": title.clone().unwrap_or_else(|| "Codex session".to_string()),
        "excerpts": excerpts,
        "harness": "codex",
        "schema_version": 1,
        "source_title": title,
    });
    let encoded = serde_json::to_string(&content).unwrap_or_else(|_| "{}".to_string());
    if encoded.len() > 8_192 {
        return Err(format!(
            "Codex capsule exceeds 8 KiB for {}",
            path.display()
        ));
    }
    let byte_count = encoded.len() as i64;
    Ok(Some(CodexRecord {
        source_id: format!("codex:{namespace}:{native_id}"),
        native_id,
        namespace: namespace.to_string(),
        locator: path.to_string_lossy().to_string(),
        fingerprint: format!("{:x}", Sha256::digest(&bytes)),
        project_hint: cwd.to_string(),
        started_at: started,
        updated_at: updated,
        health: health.to_string(),
        title,
        search_text,
        content_json: encoded,
        byte_count,
    }))
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
        .join("");
    if text.trim().is_empty() {
        None
    } else {
        Some((role.to_string(), text))
    }
}

fn belongs_to_project(hint: &str, project: &ProjectIdentity) -> bool {
    let path = Path::new(hint);
    if !path.is_dir() {
        return false;
    }
    crate::project::resolve_project(path)
        .map(|resolved| resolved.key == project.key)
        .unwrap_or(false)
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
        if path
            .symlink_metadata()
            .map(|meta| meta.file_type().is_symlink())
            .unwrap_or(true)
        {
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

fn bound_chars(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit {
        return text.to_string();
    }
    let keep = limit.saturating_sub("…[Truncated]".chars().count());
    format!(
        "{}…[Truncated]",
        text.chars().take(keep).collect::<String>().trim_end()
    )
}

pub fn open_project_database(path: &Path) -> Result<Connection> {
    if let Some(parent) = path.parent() {
        let existed = parent.exists();
        fs::create_dir_all(parent)
            .map_err(|error| TangError::new("storage-unavailable", error.to_string()))?;
        if !existed {
            #[cfg(unix)]
            {
                use std::os::unix::fs::PermissionsExt;
                let _ = fs::set_permissions(parent, fs::Permissions::from_mode(0o700));
            }
        }
    }
    let connection = Connection::open(path).map_err(storage)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
    }
    connection
        .busy_timeout(Duration::from_millis(5_000))
        .map_err(storage)?;
    connection
        .pragma_update(None, "foreign_keys", "ON")
        .map_err(storage)?;
    connection
        .pragma_update(None, "journal_mode", "WAL")
        .map_err(storage)?;
    ensure_schema(&connection)?;
    Ok(connection)
}

fn ensure_schema(connection: &Connection) -> Result<()> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                adapter TEXT NOT NULL,
                source_namespace TEXT NOT NULL,
                native_id TEXT NOT NULL,
                locator TEXT NOT NULL,
                fingerprint_algorithm TEXT NOT NULL,
                fingerprint_value TEXT NOT NULL,
                project_hint TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                health TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                native_available INTEGER NOT NULL DEFAULT 1,
                session_handle TEXT,
                title TEXT,
                UNIQUE(adapter, source_namespace, native_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS sessions_project_handle
                ON sessions(project_key, session_handle);
            CREATE TABLE IF NOT EXISTS capsules (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                schema_version INTEGER NOT NULL,
                content_json TEXT NOT NULL,
                search_text TEXT NOT NULL,
                byte_count INTEGER NOT NULL CHECK(byte_count <= 8192),
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS continuation_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                project_key TEXT NOT NULL,
                confirmation_mode TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(source_id, target_id)
            );",
        )
        .map_err(storage)
}

fn upsert_record(
    connection: &Connection,
    record: &CodexRecord,
    project_key: &str,
    indexed_at: &str,
) -> Result<()> {
    let existing: Option<String> = connection
        .query_row(
            "SELECT session_handle FROM sessions WHERE source_id = ?1",
            [&record.source_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    let handle = match existing {
        Some(handle) => handle,
        None => next_codex_handle(connection, project_key)?,
    };
    connection
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, source_namespace, native_id, locator,
                fingerprint_algorithm, fingerprint_value, project_hint, started_at,
                updated_at, health, indexed_at, native_available, session_handle, title
             ) VALUES (?1, ?2, 'codex', ?3, ?4, ?5, 'sha256', ?6, ?7, ?8, ?9, ?10, ?11, 1, ?12, ?13)
             ON CONFLICT(source_id) DO UPDATE SET
                project_key=excluded.project_key,
                locator=excluded.locator,
                fingerprint_value=excluded.fingerprint_value,
                project_hint=excluded.project_hint,
                started_at=excluded.started_at,
                updated_at=excluded.updated_at,
                health=excluded.health,
                indexed_at=excluded.indexed_at,
                native_available=1,
                title=excluded.title",
            rusqlite::params![
                record.source_id,
                project_key,
                record.namespace,
                record.native_id,
                record.locator,
                record.fingerprint,
                record.project_hint,
                record.started_at,
                record.updated_at,
                record.health,
                indexed_at,
                handle,
                record.title,
            ],
        )
        .map_err(storage)?;
    connection
        .execute(
            "INSERT INTO capsules(
                source_id, project_key, schema_version, content_json, search_text,
                byte_count, updated_at
             ) VALUES (?1, ?2, 1, ?3, ?4, ?5, ?6)
             ON CONFLICT(source_id) DO UPDATE SET
                project_key=excluded.project_key,
                content_json=excluded.content_json,
                search_text=excluded.search_text,
                byte_count=excluded.byte_count,
                updated_at=excluded.updated_at",
            rusqlite::params![
                record.source_id,
                project_key,
                record.content_json,
                record.search_text,
                record.byte_count,
                record.updated_at,
            ],
        )
        .map_err(storage)?;
    Ok(())
}

fn next_codex_handle(connection: &Connection, project_key: &str) -> Result<String> {
    let mut statement = connection
        .prepare(
            "SELECT session_handle FROM sessions WHERE project_key = ?1 AND session_handle LIKE 'C%'",
        )
        .map_err(storage)?;
    let handles = statement
        .query_map([project_key], |row| row.get::<_, Option<String>>(0))
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    let max = handles
        .into_iter()
        .flatten()
        .filter_map(|handle| handle.strip_prefix('C')?.parse::<i64>().ok())
        .max()
        .unwrap_or(0);
    Ok(format!("C{}", max + 1))
}

fn delete_missing(
    connection: &Connection,
    project_key: &str,
    namespace: &str,
    seen: &[String],
) -> Result<i64> {
    let mut statement = connection
        .prepare(
            "SELECT source_id FROM sessions
             WHERE project_key = ?1 AND adapter = 'codex' AND source_namespace = ?2",
        )
        .map_err(storage)?;
    let ids = statement
        .query_map(rusqlite::params![project_key, namespace], |row| {
            row.get::<_, String>(0)
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    let mut deleted = 0;
    for source_id in ids {
        if seen.iter().any(|id| id == &source_id) {
            continue;
        }
        connection
            .execute("DELETE FROM capsules WHERE source_id = ?1", [&source_id])
            .map_err(storage)?;
        connection
            .execute(
                "DELETE FROM continuation_edges WHERE source_id = ?1 OR target_id = ?1",
                [&source_id],
            )
            .map_err(storage)?;
        connection
            .execute("DELETE FROM sessions WHERE source_id = ?1", [&source_id])
            .map_err(storage)?;
        deleted += 1;
    }
    Ok(deleted)
}
