//! Shared writer for per-project session rows. Native logs are never modified.

use crate::error::{storage, Result, TangError};
use crate::redact::{redact, ContentKind};
use crate::timeutil::rfc3339_now;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashSet};
use std::fs;
use std::path::Path;
use std::time::Duration;

const GLOBAL_INDEX_SCOPE: &str = "global";

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
    pub unchanged: i64,
}

/// The Python adapter checkpoint shape: source id to native fingerprint, plus
/// the subset that parsed cleanly on the last scan.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct Checkpoint {
    pub fingerprints: BTreeMap<String, String>,
    pub validated: HashSet<String>,
}

impl Checkpoint {
    pub fn should_skip(&self, source_id: &str, fingerprint: &str) -> bool {
        self.fingerprints
            .get(source_id)
            .is_some_and(|stored| stored == fingerprint)
            && self.validated.contains(source_id)
    }

    pub fn remember(&mut self, source_id: &str, fingerprint: &str, valid: bool) {
        self.fingerprints
            .insert(source_id.to_string(), fingerprint.to_string());
        if valid {
            self.validated.insert(source_id.to_string());
        } else {
            self.validated.remove(source_id);
        }
    }

    pub fn forget(&mut self, source_id: &str) {
        self.fingerprints.remove(source_id);
        self.validated.remove(source_id);
    }
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

pub struct IndexScope<'a> {
    pub project_key: &'a str,
    pub adapter: &'a str,
    pub namespace: &'a str,
    pub handle_prefix: &'a str,
}

pub fn write_sessions(
    database_path: &Path,
    scope: IndexScope<'_>,
    sessions: &[SavedSession],
    protected: &HashSet<String>,
    checkpoint: &mut Checkpoint,
    checkpoint_safe: bool,
) -> Result<IndexWrite> {
    let mut database = open_project_database(database_path)?;
    let indexed_at = rfc3339_now();
    let tx = database
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let mut indexed = 0;
    for session in sessions {
        let place = crate::project::place_session(&session.project_hint, scope.project_key);
        upsert(
            &tx,
            scope.adapter,
            scope.handle_prefix,
            session,
            &place.project_key,
            &indexed_at,
        )?;
        replace_directory_tag(&tx, &session.source_id, &place.directory_tag)?;
        checkpoint.remember(&session.source_id, &session.fingerprint, true);
        indexed += 1;
    }
    let deleted = if checkpoint_safe {
        delete_missing(
            &tx,
            scope.project_key,
            scope.adapter,
            scope.namespace,
            checkpoint,
            protected,
        )?
    } else {
        0
    };
    let unchanged = checkpoint.validated.len().saturating_sub(indexed as usize) as i64;
    if checkpoint_safe {
        save_checkpoint(
            &tx,
            scope.adapter,
            scope.namespace,
            scope.project_key,
            checkpoint,
            &indexed_at,
        )?;
    }
    tx.commit().map_err(storage)?;
    Ok(IndexWrite {
        indexed,
        deleted,
        unchanged,
    })
}

pub fn load_checkpoint(
    database_path: &Path,
    _project_key: &str,
    adapter: &str,
    namespace: &str,
) -> Result<Checkpoint> {
    let database = open_project_database(database_path)?;
    load_checkpoint_from(&database, adapter, namespace)
}

fn load_checkpoint_from(
    connection: &Connection,
    adapter: &str,
    namespace: &str,
) -> Result<Checkpoint> {
    let raw: Option<String> = connection
        .query_row(
            "SELECT cursor FROM adapter_checkpoints
             WHERE adapter = ?1 AND source_namespace = ?2 AND project_key = ?3",
            rusqlite::params![adapter, namespace, GLOBAL_INDEX_SCOPE],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    let Some(raw) = raw else {
        return Ok(Checkpoint::default());
    };
    let Ok(value) = serde_json::from_str::<Value>(&raw) else {
        return Ok(Checkpoint::default());
    };
    if value.get("schema_version").and_then(Value::as_i64) != Some(4) {
        return Ok(Checkpoint::default());
    }
    let Some(fingerprints) = value.get("fingerprints").and_then(Value::as_object) else {
        return Ok(Checkpoint::default());
    };
    let mut checkpoint = Checkpoint::default();
    for (source_id, fingerprint) in fingerprints {
        let Some(fingerprint) = fingerprint.as_str() else {
            return Ok(Checkpoint::default());
        };
        checkpoint
            .fingerprints
            .insert(source_id.clone(), fingerprint.to_string());
    }
    if let Some(validated) = value.get("validated").and_then(Value::as_array) {
        for source_id in validated {
            if let Some(source_id) = source_id.as_str() {
                if checkpoint.fingerprints.contains_key(source_id) {
                    checkpoint.validated.insert(source_id.to_string());
                }
            }
        }
    }
    Ok(checkpoint)
}

fn save_checkpoint(
    connection: &Connection,
    adapter: &str,
    namespace: &str,
    _project_key: &str,
    checkpoint: &Checkpoint,
    updated_at: &str,
) -> Result<()> {
    let mut validated = checkpoint
        .validated
        .iter()
        .filter(|source_id| checkpoint.fingerprints.contains_key(*source_id))
        .cloned()
        .collect::<Vec<_>>();
    validated.sort();
    let cursor = serde_json::to_string(&json!({
        "schema_version": 4,
        "fingerprints": checkpoint.fingerprints,
        "validated": validated,
    }))
    .unwrap_or_else(|_| "{}".to_string());
    connection
        .execute(
            "INSERT INTO adapter_checkpoints(
                adapter, source_namespace, project_key, cursor, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5)
             ON CONFLICT(adapter, source_namespace, project_key) DO UPDATE SET
                cursor = excluded.cursor,
                updated_at = excluded.updated_at",
            rusqlite::params![adapter, namespace, GLOBAL_INDEX_SCOPE, cursor, updated_at],
        )
        .map_err(storage)?;
    Ok(())
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
            CREATE INDEX IF NOT EXISTS sessions_project_updated
                ON sessions(project_key, updated_at DESC, source_id);
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
            );
            CREATE INDEX IF NOT EXISTS continuation_edges_target
                ON continuation_edges(target_id, source_id);
            CREATE INDEX IF NOT EXISTS continuation_edges_project
                ON continuation_edges(project_key, source_id, target_id);
            CREATE TABLE IF NOT EXISTS adapter_checkpoints (
                adapter TEXT NOT NULL,
                source_namespace TEXT NOT NULL,
                project_key TEXT NOT NULL,
                cursor TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(adapter, source_namespace, project_key)
            );",
        )
        .map_err(storage)?;
    ensure_capsules_fts(&connection)?;
    ensure_session_overrides(&connection)?;
    ensure_session_tags(&connection)?;
    let current: i64 = connection
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .map_err(storage)?;
    if current < 8 {
        connection
            .pragma_update(None, "user_version", 8)
            .map_err(storage)?;
    }
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
    // A custom title is user-owned. Reindexing may derive a new label, but an
    // existing session_overrides row keeps that label on the session.
    let title = session_override_title(connection, &record.source_id, project_key)?
        .or_else(|| record.title.clone());
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
                title,
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
    sync_search(
        connection,
        project_key,
        &record.source_id,
        &record.search_text,
    )?;
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
    _project_key: &str,
    adapter: &str,
    namespace: &str,
    checkpoint: &Checkpoint,
    protected: &HashSet<String>,
) -> Result<i64> {
    let mut statement = connection
        .prepare(
            "SELECT source_id FROM sessions
             WHERE adapter = ?1 AND source_namespace = ?2",
        )
        .map_err(storage)?;
    let ids = statement
        .query_map(rusqlite::params![adapter, namespace], |row| {
            row.get::<_, String>(0)
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    let mut deleted = 0;
    for source_id in ids {
        if checkpoint.fingerprints.contains_key(&source_id) || protected.contains(&source_id) {
            continue;
        }
        connection
            .execute("DELETE FROM capsules WHERE source_id = ?1", [&source_id])
            .map_err(storage)?;
        remove_search(connection, &source_id)?;
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
                .execute(
                    "DELETE FROM session_tags WHERE source_id = ?1",
                    [&source_id],
                )
                .map_err(storage)?;
            connection
                .execute("DELETE FROM sessions WHERE source_id = ?1", [&source_id])
                .map_err(storage)?;
        }
        deleted += 1;
    }
    Ok(deleted)
}

pub(crate) fn ensure_capsules_fts(connection: &Connection) -> Result<()> {
    connection
        .execute_batch(
            "CREATE VIRTUAL TABLE IF NOT EXISTS capsules_fts USING fts5(
                source_id UNINDEXED,
                project_key UNINDEXED,
                search_text,
                tokenize = 'porter unicode61'
            );",
        )
        .map_err(storage)
}

/// Create the project FTS index if needed and rebuild it from capsule rows.
pub fn ensure_project_search(db: &Connection) -> Result<()> {
    ensure_capsules_fts(db)?;
    db.execute("DELETE FROM capsules_fts", [])
        .map_err(storage)?;
    db.execute(
        "INSERT INTO capsules_fts(source_id, project_key, search_text)
         SELECT source_id, project_key, search_text FROM capsules",
        [],
    )
    .map_err(storage)?;
    Ok(())
}

fn ensure_session_tags(connection: &Connection) -> Result<()> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS session_tags (
                source_id TEXT NOT NULL,
                tag TEXT NOT NULL,
                PRIMARY KEY(source_id, tag)
            );",
        )
        .map_err(storage)
}

fn replace_directory_tag(connection: &Connection, source_id: &str, tag: &str) -> Result<()> {
    connection
        .execute("DELETE FROM session_tags WHERE source_id = ?1", [source_id])
        .map_err(storage)?;
    let tag = tag.trim();
    if tag.is_empty() {
        return Ok(());
    }
    connection
        .execute(
            "INSERT INTO session_tags(source_id, tag) VALUES (?1, ?2)",
            rusqlite::params![source_id, tag],
        )
        .map_err(storage)?;
    Ok(())
}

pub(crate) fn ensure_session_overrides(connection: &Connection) -> Result<()> {
    connection
        .execute_batch(
            "CREATE TABLE IF NOT EXISTS session_overrides (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                custom_title TEXT,
                previous_title TEXT,
                updated_at TEXT NOT NULL
            );",
        )
        .map_err(storage)?;
    let mut statement = connection
        .prepare("PRAGMA table_info(session_overrides)")
        .map_err(storage)?;
    let columns = statement
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    if !columns.iter().any(|column| column == "previous_title") {
        connection
            .execute(
                "ALTER TABLE session_overrides ADD COLUMN previous_title TEXT",
                [],
            )
            .map_err(storage)?;
    }
    connection
        .execute(
            "CREATE INDEX IF NOT EXISTS session_overrides_project
                ON session_overrides(project_key, source_id)",
            [],
        )
        .map_err(storage)?;
    Ok(())
}

fn sync_search(
    connection: &Connection,
    project_key: &str,
    source_id: &str,
    search_text: &str,
) -> Result<()> {
    ensure_capsules_fts(connection)?;
    connection
        .execute("DELETE FROM capsules_fts WHERE source_id = ?1", [source_id])
        .map_err(storage)?;
    connection
        .execute(
            "INSERT INTO capsules_fts(source_id, project_key, search_text) VALUES (?1, ?2, ?3)",
            rusqlite::params![source_id, project_key, search_text],
        )
        .map_err(storage)?;
    Ok(())
}

fn session_override_title(
    connection: &Connection,
    source_id: &str,
    project_key: &str,
) -> Result<Option<String>> {
    ensure_session_overrides(connection)?;
    connection
        .query_row(
            "SELECT custom_title FROM session_overrides
             WHERE source_id = ?1 AND project_key = ?2",
            rusqlite::params![source_id, project_key],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)
}

fn remove_search(connection: &Connection, source_id: &str) -> Result<()> {
    connection
        .execute("DELETE FROM capsules_fts WHERE source_id = ?1", [source_id])
        .map_err(storage)?;
    Ok(())
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
