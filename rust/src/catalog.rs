//! Explicit global catalog of redacted session capsules.

use crate::error::{storage, Result, TangError};
use crate::redact::{redact, ContentKind};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

const SCHEMA_VERSION: i64 = 1;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncResult {
    pub upserted: i64,
    pub removed: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RecallHit {
    pub source_id: String,
    pub catalog_handle: String,
    pub project_handle: String,
    pub project_display: String,
    pub harness: String,
    pub title: Option<String>,
    pub updated_at: String,
    pub health: String,
    pub native_available: bool,
    pub snippet: Option<String>,
}

pub fn default_catalog_path() -> PathBuf {
    if let Some(value) = std::env::var_os("TANG_CATALOG") {
        if !value.is_empty() {
            return PathBuf::from(value);
        }
    }
    home_dir().join(".tang").join("catalog.db")
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn open_catalog(path: &Path) -> Result<Connection> {
    secure_parent(path)?;
    let mut connection = Connection::open(path).map_err(|error| {
        TangError::new(
            "catalog-unavailable",
            format!("Tang cannot open the global catalog at {}", path.display()),
        )
        .cause(error)
    })?;
    set_private(path);
    prepare_connection(&connection)?;
    migrate(&mut connection)?;
    Ok(connection)
}

pub fn open_project_readonly(path: &Path) -> Result<Connection> {
    if !path.is_file() {
        return Err(TangError::new(
            "index-required",
            format!(
                "Tang has no project database at {}. Index the project before catalog sync.",
                path.display()
            ),
        ));
    }
    let connection =
        Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(storage)?;
    connection
        .busy_timeout(Duration::from_millis(5_000))
        .map_err(storage)?;
    Ok(connection)
}

pub fn sync_project(
    catalog: &mut Connection,
    project_db: &Connection,
    project_key: &str,
    project_display: &str,
    database_path: &Path,
    synced_at: &str,
) -> Result<SyncResult> {
    if project_key.is_empty() {
        return Err(TangError::new(
            "invalid-project",
            "A project key is required.",
        ));
    }
    let display = redact(project_display, ContentKind::DisplayMetadata)
        .trim()
        .to_string();
    if display.is_empty() {
        return Err(TangError::new(
            "invalid-project",
            "A project display name is required.",
        ));
    }
    let keys = distinct_project_keys(project_db)?;
    if !keys.is_empty() && !keys.iter().any(|key| key == project_key) {
        return Err(TangError::new(
            "project-mismatch",
            "The database does not belong to the current project.",
        ));
    }
    if table_count(project_db, "sessions")? == 0 || table_count(project_db, "capsules")? == 0 {
        return Ok(SyncResult {
            upserted: 0,
            removed: 0,
            skipped: 0,
            warnings: vec![
                "project database has no sessions or capsules; catalog rows were left unchanged"
                    .to_string(),
            ],
        });
    }
    let rows = load_capsules(project_db, project_key)?;
    let stored_path = database_path
        .canonicalize()
        .unwrap_or_else(|_| database_path.to_path_buf());
    let stored_path = stored_path.to_string_lossy().to_string();
    let tx = catalog
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let mut upserted = 0;
    let mut skipped = 0;
    let mut kept = Vec::new();
    for row in rows {
        let Some(project_handle) = row.session_handle.filter(|handle| !handle.is_empty()) else {
            skipped += 1;
            continue;
        };
        let search_text = redact(&row.search_text, ContentKind::VisibleText);
        let title = title_from(row.title, &row.content_json);
        upsert_session(
            &tx,
            &SessionRecord {
                source_id: &row.source_id,
                project_key,
                project_display: &display,
                database_path: &stored_path,
                adapter: &row.adapter,
                project_handle: &project_handle,
                title: title.as_deref(),
                health: &row.health,
                native_available: row.native_available,
                started_at: &row.started_at,
                updated_at: &row.updated_at,
                synced_at,
                search_text: &search_text,
            },
        )?;
        kept.push(row.source_id);
        upserted += 1;
    }
    let removed = remove_missing(&tx, project_key, &kept)?;
    tx.commit().map_err(storage)?;
    Ok(SyncResult {
        upserted,
        removed,
        skipped,
        warnings: Vec::new(),
    })
}

struct SessionRecord<'a> {
    source_id: &'a str,
    project_key: &'a str,
    project_display: &'a str,
    database_path: &'a str,
    adapter: &'a str,
    project_handle: &'a str,
    title: Option<&'a str>,
    health: &'a str,
    native_available: bool,
    started_at: &'a str,
    updated_at: &'a str,
    synced_at: &'a str,
    search_text: &'a str,
}

pub fn recall(
    catalog: &Connection,
    query: &str,
    harness: Option<&str>,
    limit: i64,
    include_unavailable: bool,
) -> Result<Vec<RecallHit>> {
    if query.trim().is_empty() {
        return Err(TangError::new("empty-query", "A recall query is required."));
    }
    if !(1..=100).contains(&limit) {
        return Err(TangError::new(
            "invalid-limit",
            "Recall limit must be between 1 and 100.",
        ));
    }
    let available = if include_unavailable {
        ""
    } else {
        "AND s.native_available = 1"
    };
    let sql = if harness.is_some() {
        format!(
            "SELECT s.source_id, s.catalog_handle, s.project_handle, s.project_display,
                    s.adapter, s.title, s.updated_at, s.health, s.native_available,
                    snippet(catalog_fts, 2, '[', ']', ' … ', 18) AS snippet
             FROM catalog_fts
             JOIN catalog_sessions AS s ON s.source_id = catalog_fts.source_id
             WHERE catalog_fts MATCH ?1 AND s.adapter = ?2 {available}
             ORDER BY rank, s.updated_at DESC, s.source_id
             LIMIT ?3"
        )
    } else {
        format!(
            "SELECT s.source_id, s.catalog_handle, s.project_handle, s.project_display,
                    s.adapter, s.title, s.updated_at, s.health, s.native_available,
                    snippet(catalog_fts, 2, '[', ']', ' … ', 18) AS snippet
             FROM catalog_fts
             JOIN catalog_sessions AS s ON s.source_id = catalog_fts.source_id
             WHERE catalog_fts MATCH ?1 {available}
             ORDER BY rank, s.updated_at DESC, s.source_id
             LIMIT ?2"
        )
    };
    let mut statement = catalog.prepare(&sql).map_err(map_recall)?;
    let mut rows = if let Some(harness) = harness {
        statement
            .query(rusqlite::params![query, harness, limit])
            .map_err(map_recall)?
    } else {
        statement
            .query(rusqlite::params![query, limit])
            .map_err(map_recall)?
    };
    let mut hits = Vec::new();
    while let Some(row) = rows.next().map_err(map_recall)? {
        hits.push(hit_from_row(row)?);
    }
    Ok(hits)
}

struct CapsuleRow {
    source_id: String,
    session_handle: Option<String>,
    adapter: String,
    started_at: String,
    updated_at: String,
    health: String,
    native_available: bool,
    title: Option<String>,
    search_text: String,
    content_json: String,
}

fn load_capsules(project_db: &Connection, project_key: &str) -> Result<Vec<CapsuleRow>> {
    let mut statement = project_db
        .prepare(
            "SELECT s.source_id, s.session_handle, s.adapter, s.started_at, s.updated_at,
                    s.health, s.native_available, s.title, c.search_text, c.content_json
             FROM sessions AS s
             JOIN capsules AS c USING(source_id)
             WHERE s.project_key = ?1
             ORDER BY s.started_at, s.source_id",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map([project_key], |row| {
            Ok(CapsuleRow {
                source_id: row.get(0)?,
                session_handle: row.get(1)?,
                adapter: row.get(2)?,
                started_at: row.get(3)?,
                updated_at: row.get(4)?,
                health: row.get(5)?,
                native_available: row.get::<_, i64>(6)? != 0,
                title: row.get(7)?,
                search_text: row.get(8)?,
                content_json: row.get(9)?,
            })
        })
        .map_err(storage)?;
    rows.collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)
}

fn distinct_project_keys(project_db: &Connection) -> Result<Vec<String>> {
    let mut statement = project_db
        .prepare("SELECT DISTINCT project_key FROM sessions")
        .map_err(storage)?;
    let rows = statement.query_map([], |row| row.get(0)).map_err(storage)?;
    rows.collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)
}

fn upsert_session(catalog: &Connection, record: &SessionRecord<'_>) -> Result<()> {
    let existing: Option<String> = catalog
        .query_row(
            "SELECT catalog_handle FROM catalog_sessions WHERE source_id = ?1",
            [record.source_id],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    let handle = match existing {
        Some(handle) => handle,
        None => allocate_handle(catalog, record.adapter)?,
    };
    catalog
        .execute(
            "INSERT INTO catalog_sessions(
                source_id, project_key, project_display, database_path, adapter,
                catalog_handle, project_handle, title, health, native_available,
                started_at, updated_at, synced_at, search_text
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)
             ON CONFLICT(source_id) DO UPDATE SET
                project_key=excluded.project_key,
                project_display=excluded.project_display,
                database_path=excluded.database_path,
                adapter=excluded.adapter,
                catalog_handle=excluded.catalog_handle,
                project_handle=excluded.project_handle,
                title=excluded.title,
                health=excluded.health,
                native_available=excluded.native_available,
                started_at=excluded.started_at,
                updated_at=excluded.updated_at,
                synced_at=excluded.synced_at,
                search_text=excluded.search_text",
            rusqlite::params![
                record.source_id,
                record.project_key,
                record.project_display,
                record.database_path,
                record.adapter,
                handle,
                record.project_handle,
                record.title,
                record.health,
                i64::from(record.native_available),
                record.started_at,
                record.updated_at,
                record.synced_at,
                record.search_text,
            ],
        )
        .map_err(storage)?;
    catalog
        .execute(
            "DELETE FROM catalog_fts WHERE source_id = ?1",
            [record.source_id],
        )
        .map_err(storage)?;
    catalog
        .execute(
            "INSERT INTO catalog_fts(source_id, project_key, search_text) VALUES (?1, ?2, ?3)",
            rusqlite::params![record.source_id, record.project_key, record.search_text],
        )
        .map_err(storage)?;
    Ok(())
}

fn allocate_handle(catalog: &Connection, adapter: &str) -> Result<String> {
    let prefix = handle_prefix(adapter);
    let existing: Option<i64> = catalog
        .query_row(
            "SELECT next_number FROM catalog_handle_counters WHERE prefix = ?1",
            [prefix],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    let number = if let Some(number) = existing {
        catalog
            .execute(
                "UPDATE catalog_handle_counters SET next_number = ?1 WHERE prefix = ?2",
                rusqlite::params![number + 1, prefix],
            )
            .map_err(storage)?;
        number
    } else {
        catalog
            .execute(
                "INSERT INTO catalog_handle_counters(prefix, next_number) VALUES (?1, 2)",
                [prefix],
            )
            .map_err(storage)?;
        1
    };
    Ok(format!("{prefix}{number}"))
}

fn handle_prefix(adapter: &str) -> &'static str {
    match adapter {
        "codex" => "C",
        "grok" => "G",
        "opencode" => "O",
        "cursor" => "R",
        "claude" => "L",
        "antigravity" => "A",
        "openclaw" => "W",
        "grokbot" => "B",
        _ => "S",
    }
}

fn remove_missing(catalog: &Connection, project_key: &str, kept: &[String]) -> Result<i64> {
    let mut statement = catalog
        .prepare("SELECT source_id FROM catalog_sessions WHERE project_key = ?1 ORDER BY source_id")
        .map_err(storage)?;
    let ids = statement
        .query_map([project_key], |row| row.get::<_, String>(0))
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    let keep: HashSet<&str> = kept.iter().map(String::as_str).collect();
    let mut removed = 0;
    for source_id in ids {
        if keep.contains(source_id.as_str()) {
            continue;
        }
        catalog
            .execute("DELETE FROM catalog_fts WHERE source_id = ?1", [&source_id])
            .map_err(storage)?;
        catalog
            .execute(
                "DELETE FROM catalog_sessions WHERE source_id = ?1",
                [&source_id],
            )
            .map_err(storage)?;
        removed += 1;
    }
    Ok(removed)
}

fn title_from(title: Option<String>, content_json: &str) -> Option<String> {
    let raw = title
        .filter(|value| !value.trim().is_empty())
        .or_else(|| capsule_title(content_json))?;
    let redacted = redact(&raw, ContentKind::Title).trim().to_string();
    if redacted.is_empty() {
        None
    } else {
        Some(redacted.chars().take(256).collect())
    }
}

/// Read the title the Python indexer prefers, without trusting either field.
fn capsule_title(content_json: &str) -> Option<String> {
    let content: serde_json::Value = serde_json::from_str(content_json).ok()?;
    ["source_title", "display_name"].iter().find_map(|field| {
        content
            .get(*field)
            .and_then(serde_json::Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .map(str::to_string)
    })
}

fn hit_from_row(row: &rusqlite::Row<'_>) -> Result<RecallHit> {
    Ok(RecallHit {
        source_id: row.get(0).map_err(storage)?,
        catalog_handle: row.get(1).map_err(storage)?,
        project_handle: row.get(2).map_err(storage)?,
        project_display: row.get(3).map_err(storage)?,
        harness: row.get(4).map_err(storage)?,
        title: row.get(5).map_err(storage)?,
        updated_at: row.get(6).map_err(storage)?,
        health: row.get(7).map_err(storage)?,
        native_available: row.get::<_, i64>(8).map_err(storage)? != 0,
        snippet: row.get(9).map_err(storage)?,
    })
}

fn map_recall(error: rusqlite::Error) -> TangError {
    let text = error.to_string();
    if text.to_ascii_lowercase().contains("fts") {
        TangError::new("malformed-query", "The recall query is not valid FTS5.")
    } else {
        storage(error)
    }
}

fn prepare_connection(connection: &Connection) -> Result<()> {
    connection
        .busy_timeout(Duration::from_millis(5_000))
        .map_err(storage)?;
    connection
        .pragma_update(None, "foreign_keys", "ON")
        .map_err(storage)?;
    connection
        .pragma_update(None, "journal_mode", "WAL")
        .map_err(storage)?;
    Ok(())
}

fn table_count(project_db: &Connection, table: &str) -> Result<i64> {
    project_db
        .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
            row.get(0)
        })
        .map_err(storage)
}

fn migrate(connection: &mut Connection) -> Result<()> {
    let tx = connection
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let current: i64 = tx
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .map_err(storage)?;
    if current > SCHEMA_VERSION {
        return Err(TangError::new(
            "catalog-schema",
            "The global catalog schema is newer than this binary.",
        ));
    }
    if current == SCHEMA_VERSION {
        tx.commit().map_err(storage)?;
        return Ok(());
    }
    if current != 0 {
        return Err(TangError::new(
            "catalog-schema",
            format!("Missing catalog migration between {current} and {SCHEMA_VERSION}."),
        ));
    }
    tx.execute_batch(
        "CREATE TABLE catalog_sessions (
            source_id TEXT PRIMARY KEY,
            project_key TEXT NOT NULL,
            project_display TEXT NOT NULL,
            database_path TEXT NOT NULL,
            adapter TEXT NOT NULL,
            catalog_handle TEXT NOT NULL UNIQUE,
            project_handle TEXT NOT NULL,
            title TEXT,
            health TEXT NOT NULL,
            native_available INTEGER NOT NULL CHECK(native_available IN (0, 1)),
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            synced_at TEXT NOT NULL,
            search_text TEXT NOT NULL
        );
        CREATE INDEX catalog_sessions_project
            ON catalog_sessions(project_key, updated_at DESC, source_id);
        CREATE TABLE catalog_handle_counters (
            prefix TEXT PRIMARY KEY,
            next_number INTEGER NOT NULL CHECK(next_number >= 1)
        );
        CREATE VIRTUAL TABLE catalog_fts USING fts5(
            source_id UNINDEXED,
            project_key UNINDEXED,
            search_text,
            tokenize = 'porter unicode61'
        );
        PRAGMA user_version = 1;",
    )
    .map_err(storage)?;
    tx.commit().map_err(storage)?;
    Ok(())
}

fn secure_parent(path: &Path) -> Result<()> {
    let Some(parent) = path.parent() else {
        return Err(TangError::new(
            "catalog-unavailable",
            "The catalog path has no parent directory.",
        ));
    };
    if parent.as_os_str().is_empty() {
        return Ok(());
    }
    let existed = parent.exists();
    fs::create_dir_all(parent).map_err(|error| {
        TangError::new(
            "catalog-unavailable",
            format!("Tang cannot create {}: {error}", parent.display()),
        )
    })?;
    if !existed {
        set_mode(parent, 0o700);
    }
    Ok(())
}

fn set_private(path: &Path) {
    set_mode(path, 0o600);
}

fn set_mode(path: &Path, mode: u32) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = fs::set_permissions(path, fs::Permissions::from_mode(mode));
    }
    #[cfg(not(unix))]
    {
        let _ = (path, mode);
    }
}

trait Cause {
    fn cause(self, error: impl std::fmt::Display) -> Self;
}

impl Cause for TangError {
    fn cause(mut self, error: impl std::fmt::Display) -> Self {
        self.message = format!("{} ({error})", self.message);
        self
    }
}
