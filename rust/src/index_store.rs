//! Shared writer for per-project session rows. Native logs are never modified.

use crate::error::{storage, Result, TangError};
use crate::redact::{redact, ContentKind};
use crate::timeutil::rfc3339_now;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior};
use serde_json::json;
use std::collections::HashSet;
use std::fs;
use std::path::Path;
use std::time::Duration;

// Host-provided wrappers that Codex records as visible user messages. They are
// not a session title or recoverable user intent, so they never enter a capsule.
const HOST_ENVELOPE_PREFIXES: &[&str] = &[
    "# agents.md instructions for ",
    "<environment_context>",
    "<permissions instructions>",
    "<skills_instructions>",
    "<apps_instructions>",
    "<plugins_instructions>",
    "<recommended_plugins>",
];

pub fn is_host_envelope(text: &str) -> bool {
    let normalized = text.trim_start().to_lowercase();
    HOST_ENVELOPE_PREFIXES
        .iter()
        .any(|prefix| normalized.starts_with(prefix))
}

/// Fallback timestamp for stores whose transcript rows carry no usable time.
pub fn file_updated_at(path: &Path) -> String {
    fs::metadata(path)
        .and_then(|metadata| metadata.modified())
        .ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map(|duration| crate::timeutil::rfc3339_secs(duration.as_secs()))
        .unwrap_or_else(|| "1970-01-01T00:00:00Z".to_string())
}

#[derive(Debug, Clone)]
pub struct SavedSession {
    pub source_id: String,
    pub native_id: String,
    pub namespace: String,
    pub locator: String,
    pub fingerprint: String,
    pub project_hint: String,
    pub started_at: String,
    pub updated_at: String,
    pub health: String,
    pub title: Option<String>,
    pub search_text: String,
    pub content_json: String,
    pub byte_count: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct IndexWrite {
    pub indexed: i64,
    pub deleted: i64,
}

pub struct SessionDraft<'a> {
    pub adapter: &'a str,
    pub namespace: &'a str,
    pub native_id: &'a str,
    pub locator: &'a str,
    pub fingerprint: &'a str,
    pub project_hint: &'a str,
    pub started_at: &'a str,
    pub updated_at: &'a str,
    pub health: &'a str,
    pub title: Option<String>,
    pub turns: Vec<(String, String)>,
}

pub fn finish_session(draft: SessionDraft<'_>) -> std::result::Result<SavedSession, String> {
    let SessionDraft {
        adapter,
        namespace,
        native_id,
        locator,
        fingerprint,
        project_hint,
        started_at,
        updated_at,
        health,
        title,
        turns,
    } = draft;
    let redacted = turns
        .into_iter()
        .map(|(role, text)| (role, redact(&text, ContentKind::VisibleText)))
        .filter(|(_, text)| !text.trim().is_empty())
        .filter(|(_, text)| !is_host_envelope(text))
        .collect::<Vec<_>>();
    // Match the Python capsule: keep the first user task plus the most recent
    // turns, instead of the oldest four turns of a long session.
    let selected = selected_turns(&redacted);
    let derived = selected
        .iter()
        .find(|&&index| redacted[index].0 == "user")
        .map(|&index| bound_chars(&redacted[index].1, 96));
    let title = title
        .map(|value| redact(&value, ContentKind::Title))
        .filter(|value| !value.trim().is_empty())
        .or(derived);
    let search_text = bound_chars(
        &selected
            .iter()
            .map(|&index| redacted[index].1.as_str())
            .collect::<Vec<_>>()
            .join("\n"),
        6_000,
    );
    let excerpts = selected
        .iter()
        .map(|&index| {
            let (role, text) = &redacted[index];
            json!({
                "role": role,
                "text": bound_chars(text, 500),
            })
        })
        .collect::<Vec<_>>();
    let content = json!({
        "display_name": title.clone().unwrap_or_else(|| format!("{adapter} session")),
        "excerpts": excerpts,
        "harness": adapter,
        "schema_version": 1,
        "source_title": title,
    });
    let encoded = serde_json::to_string(&content).unwrap_or_else(|_| "{}".to_string());
    if encoded.len() > 8_192 {
        return Err(format!("{adapter} capsule exceeds 8 KiB for {locator}"));
    }
    Ok(SavedSession {
        source_id: format!("{adapter}:{namespace}:{native_id}"),
        native_id: native_id.to_string(),
        namespace: namespace.to_string(),
        locator: locator.to_string(),
        fingerprint: fingerprint.to_string(),
        project_hint: project_hint.to_string(),
        started_at: started_at.to_string(),
        updated_at: updated_at.to_string(),
        health: health.to_string(),
        title,
        search_text,
        byte_count: encoded.len() as i64,
        content_json: encoded,
    })
}

fn selected_turns(turns: &[(String, String)]) -> Vec<usize> {
    let mut selected = (turns.len().saturating_sub(4)..turns.len()).collect::<Vec<_>>();
    if let Some(first_user) = turns.iter().position(|(role, _)| role.as_str() == "user") {
        if !selected.contains(&first_user) {
            selected.push(first_user);
        }
    }
    selected.sort_unstable();
    selected
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

pub fn write_sessions(
    database_path: &Path,
    project_key: &str,
    adapter: &str,
    namespace: &str,
    handle_prefix: &str,
    sessions: &[SavedSession],
    protected: &HashSet<String>,
) -> Result<IndexWrite> {
    let mut database = open_project_database(database_path)?;
    let indexed_at = rfc3339_now();
    let tx = database
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let mut indexed = 0;
    let mut seen = Vec::new();
    for session in sessions {
        upsert(
            &tx,
            adapter,
            handle_prefix,
            session,
            project_key,
            &indexed_at,
        )?;
        seen.push(session.source_id.clone());
        indexed += 1;
    }
    let deleted = delete_missing(&tx, project_key, adapter, namespace, &seen, protected)?;
    tx.commit().map_err(storage)?;
    Ok(IndexWrite { indexed, deleted })
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
        .map_err(storage)?;
    Ok(connection)
}

fn upsert(
    connection: &Connection,
    adapter: &str,
    handle_prefix: &str,
    record: &SavedSession,
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
        None => next_handle(connection, project_key, handle_prefix)?,
    };
    connection
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, source_namespace, native_id, locator,
                fingerprint_algorithm, fingerprint_value, project_hint, started_at,
                updated_at, health, indexed_at, native_available, session_handle, title
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'sha256', ?7, ?8, ?9, ?10, ?11, ?12, 1, ?13, ?14)
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
                title=COALESCE(excluded.title, sessions.title)",
            rusqlite::params![
                record.source_id,
                project_key,
                adapter,
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

fn next_handle(connection: &Connection, project_key: &str, prefix: &str) -> Result<String> {
    let pattern = format!("{prefix}%");
    let mut statement = connection
        .prepare(
            "SELECT session_handle FROM sessions WHERE project_key = ?1 AND session_handle LIKE ?2",
        )
        .map_err(storage)?;
    let handles = statement
        .query_map(rusqlite::params![project_key, pattern], |row| {
            row.get::<_, Option<String>>(0)
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    let max = handles
        .into_iter()
        .flatten()
        .filter_map(|handle| handle.strip_prefix(prefix)?.parse::<i64>().ok())
        .max()
        .unwrap_or(0);
    Ok(format!("{prefix}{}", max + 1))
}

fn delete_missing(
    connection: &Connection,
    project_key: &str,
    adapter: &str,
    namespace: &str,
    seen: &[String],
    protected: &HashSet<String>,
) -> Result<i64> {
    let mut statement = connection
        .prepare(
            "SELECT source_id FROM sessions
             WHERE project_key = ?1 AND adapter = ?2 AND source_namespace = ?3",
        )
        .map_err(storage)?;
    let ids = statement
        .query_map(rusqlite::params![project_key, adapter, namespace], |row| {
            row.get::<_, String>(0)
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    let mut deleted = 0;
    for source_id in ids {
        if seen.iter().any(|id| id == &source_id) || protected.contains(&source_id) {
            continue;
        }
        connection
            .execute("DELETE FROM capsules WHERE source_id = ?1", [&source_id])
            .map_err(storage)?;
        // Match the Python repository: a session referenced by the graph is a
        // tombstone, not a row that may silently take its continuation edges.
        let referenced: Option<i64> = connection
            .query_row(
                "SELECT 1 FROM continuation_edges WHERE source_id = ?1 OR target_id = ?1 LIMIT 1",
                [&source_id],
                |row| row.get(0),
            )
            .optional()
            .map_err(storage)?;
        if referenced.is_some() {
            connection
                .execute(
                    "UPDATE sessions SET native_available = 0 WHERE source_id = ?1",
                    [&source_id],
                )
                .map_err(storage)?;
        } else {
            connection
                .execute("DELETE FROM sessions WHERE source_id = ?1", [&source_id])
                .map_err(storage)?;
        }
        deleted += 1;
    }
    Ok(deleted)
}

#[cfg(test)]
mod tests {
    use super::selected_turns;

    #[test]
    fn keeps_the_first_user_and_the_latest_turns() {
        let turns = (0..8)
            .map(|index| {
                (
                    if index == 0 { "user" } else { "agent" }.to_string(),
                    format!("turn-{index}"),
                )
            })
            .collect::<Vec<_>>();
        assert_eq!(selected_turns(&turns), vec![0, 4, 5, 6, 7]);
    }
}
