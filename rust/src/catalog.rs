//! Explicit global catalog of redacted session capsules.

use crate::error::{storage, Result, TangError};
use crate::redact::{redact, ContentKind};
use crate::summary::{build_summary, categories, categorize};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::Duration;

const SCHEMA_VERSION: i64 = 2;

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
    pub category: String,
    pub summary: String,
    pub labels: Vec<String>,
    pub snippet: Option<String>,
}

pub struct RecallQuery<'a> {
    pub text: Option<&'a str>,
    pub label: Option<&'a str>,
    pub category: Option<&'a str>,
    pub harness: Option<&'a str>,
    pub limit: i64,
    pub include_unavailable: bool,
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
        let body_text = redact(&row.search_text, ContentKind::VisibleText);
        let title = title_from(row.title.clone(), &row.content_json);
        let excerpts = excerpts_from(&row.content_json);
        let mut evidence = Vec::new();
        if let Some(title) = &title {
            evidence.push(title.clone());
        }
        if !body_text.is_empty() {
            evidence.push(body_text.clone());
        }
        evidence.extend(excerpts.iter().map(|(_, text)| text.clone()));
        let category = categorize(
            &evidence.join("\n"),
            excerpts.iter().any(|(role, _)| role == "user"),
        );
        let summary = build_summary(category, title.as_deref(), &excerpts);
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
                body_text: &body_text,
                category,
                summary: &summary,
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
    body_text: &'a str,
    category: &'a str,
    summary: &'a str,
}

pub fn recall(catalog: &Connection, query: &RecallQuery<'_>) -> Result<Vec<RecallHit>> {
    if !(1..=100).contains(&query.limit) {
        return Err(TangError::new(
            "invalid-limit",
            "Recall limit must be between 1 and 100.",
        ));
    }
    let text = query.text.map(str::trim).filter(|value| !value.is_empty());
    let label = match query.label {
        Some(value) => Some(normalize_label(value)?),
        None => None,
    };
    if let Some(category) = query.category {
        if !categories().contains(&category) {
            return Err(TangError::new(
                "invalid-category",
                format!("Category must be one of: {}.", categories().join(", ")),
            ));
        }
    }
    if text.is_none() && label.is_none() && query.category.is_none() && query.harness.is_none() {
        return Err(TangError::new(
            "empty-query",
            "Provide a query or a label, category, or harness filter.",
        ));
    }
    let columns = "s.source_id, s.catalog_handle, s.project_handle, s.project_display,
        s.adapter, s.title, s.updated_at, s.health, s.native_available,
        s.category, s.summary";
    let mut filters = Vec::new();
    let mut params: Vec<Bound> = Vec::new();
    if !query.include_unavailable {
        filters.push("s.native_available = 1".to_string());
    }
    if let Some(harness) = query.harness {
        filters.push("s.adapter = ?".to_string());
        params.push(Bound::Text(harness.to_string()));
    }
    if let Some(category) = query.category {
        filters.push("s.category = ?".to_string());
        params.push(Bound::Text(category.to_string()));
    }
    if let Some(label) = &label {
        filters.push(
            "s.source_id IN (SELECT source_id FROM catalog_labels WHERE label = ?)".to_string(),
        );
        params.push(Bound::Text(label.clone()));
    }
    let where_sql = if filters.is_empty() {
        "1 = 1".to_string()
    } else {
        filters.join(" AND ")
    };
    let sql = if let Some(text) = text {
        params.insert(0, Bound::Text(text.to_string()));
        format!(
            "SELECT {columns}, snippet(catalog_fts, 2, '[', ']', ' … ', 18) AS snippet
             FROM catalog_fts
             JOIN catalog_sessions AS s ON s.source_id = catalog_fts.source_id
             WHERE catalog_fts MATCH ? AND {where_sql}
             ORDER BY rank, s.updated_at DESC, s.source_id
             LIMIT ?"
        )
    } else {
        format!(
            "SELECT {columns}, NULL AS snippet
             FROM catalog_sessions AS s
             WHERE {where_sql}
             ORDER BY s.updated_at DESC, s.source_id
             LIMIT ?"
        )
    };
    params.push(Bound::Int(query.limit));
    let mut statement = catalog.prepare(&sql).map_err(map_recall)?;
    let mut rows = statement
        .query(rusqlite::params_from_iter(params.iter()))
        .map_err(map_recall)?;
    let mut pending = Vec::new();
    while let Some(row) = rows.next().map_err(map_recall)? {
        pending.push(hit_from_row(row)?);
    }
    drop(rows);
    drop(statement);
    let ids: Vec<String> = pending.iter().map(|hit| hit.source_id.clone()).collect();
    let grouped = labels_for(catalog, &ids)?;
    for hit in &mut pending {
        if let Some(labels) = grouped.get(&hit.source_id) {
            hit.labels.clone_from(labels);
        }
    }
    Ok(pending)
}

enum Bound {
    Text(String),
    Int(i64),
}

impl rusqlite::ToSql for Bound {
    fn to_sql(&self) -> rusqlite::Result<rusqlite::types::ToSqlOutput<'_>> {
        match self {
            Bound::Text(value) => value.to_sql(),
            Bound::Int(value) => value.to_sql(),
        }
    }
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
                started_at, updated_at, synced_at, search_text, body_text,
                category, summary
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, '', ?14, ?15, ?16)
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
                body_text=excluded.body_text,
                category=excluded.category,
                summary=excluded.summary",
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
                record.body_text,
                record.category,
                record.summary,
            ],
        )
        .map_err(storage)?;
    reindex(catalog, record.source_id)
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

pub fn add_label(
    catalog: &mut Connection,
    token: &str,
    label: &str,
    created_at: &str,
) -> Result<String> {
    let normalized = normalize_label(label)?;
    let tx = catalog
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let (source_id, handle) = resolve_token(&tx, token)?;
    let existing: Option<i64> = tx
        .query_row(
            "SELECT 1 FROM catalog_labels WHERE source_id = ?1 AND label = ?2",
            rusqlite::params![source_id, normalized],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    if existing.is_none() {
        let count: i64 = tx
            .query_row(
                "SELECT COUNT(*) FROM catalog_labels WHERE source_id = ?1",
                [&source_id],
                |row| row.get(0),
            )
            .map_err(storage)?;
        if count >= 8 {
            return Err(TangError::new(
                "label-limit",
                "A session can have at most 8 labels.",
            ));
        }
        tx.execute(
            "INSERT INTO catalog_labels(source_id, label, created_at) VALUES (?1, ?2, ?3)",
            rusqlite::params![source_id, normalized, created_at],
        )
        .map_err(storage)?;
        reindex(&tx, &source_id)?;
    }
    tx.commit().map_err(storage)?;
    Ok(handle)
}

pub fn remove_label(catalog: &mut Connection, token: &str, label: &str) -> Result<String> {
    let normalized = normalize_label(label)?;
    let tx = catalog
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let (source_id, handle) = resolve_token(&tx, token)?;
    let deleted = tx
        .execute(
            "DELETE FROM catalog_labels WHERE source_id = ?1 AND label = ?2",
            rusqlite::params![source_id, normalized],
        )
        .map_err(storage)?;
    if deleted == 0 {
        return Err(TangError::new(
            "missing-label",
            format!("{normalized} is not attached to {handle}."),
        ));
    }
    reindex(&tx, &source_id)?;
    tx.commit().map_err(storage)?;
    Ok(handle)
}

pub fn normalize_label(value: &str) -> Result<String> {
    let label = value.trim().to_ascii_lowercase();
    let mut chars = label.chars();
    let Some(first) = chars.next() else {
        return Err(TangError::new(
            "invalid-label",
            "A label is a lowercase word of at most 32 characters.",
        ));
    };
    if !first.is_ascii_lowercase()
        || label.len() > 32
        || !chars.all(|character| {
            character.is_ascii_lowercase() || character.is_ascii_digit() || character == '-'
        })
    {
        return Err(TangError::new(
            "invalid-label",
            "A label is a lowercase word of at most 32 characters.",
        ));
    }
    Ok(label)
}

fn resolve_token(catalog: &Connection, token: &str) -> Result<(String, String)> {
    if token.is_empty() || token.trim() != token {
        return Err(TangError::new(
            "invalid-session",
            "The session token must be non-empty and trimmed.",
        ));
    }
    let row = if token.contains(':') {
        catalog
            .query_row(
                "SELECT source_id, catalog_handle FROM catalog_sessions WHERE source_id = ?1",
                [token],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(storage)?
    } else {
        let handle = token.to_ascii_uppercase();
        if !valid_handle(&handle) {
            return Err(TangError::new(
                "invalid-session",
                "A catalog handle is a letter followed by a number.",
            ));
        }
        catalog
            .query_row(
                "SELECT source_id, catalog_handle FROM catalog_sessions WHERE catalog_handle = ?1",
                [&handle],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()
            .map_err(storage)?
    };
    row.ok_or_else(|| {
        TangError::new(
            "not-in-catalog",
            "That session is not in the global catalog. Run tang catalog sync.",
        )
    })
}

fn valid_handle(handle: &str) -> bool {
    let mut chars = handle.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !first.is_ascii_alphabetic() {
        return false;
    }
    let rest: String = chars.collect();
    !rest.is_empty()
        && !rest.starts_with('0')
        && rest.chars().all(|character| character.is_ascii_digit())
}

fn reindex(catalog: &Connection, source_id: &str) -> Result<()> {
    let (project_key, body, summary): (String, String, String) = catalog
        .query_row(
            "SELECT project_key, body_text, summary FROM catalog_sessions WHERE source_id = ?1",
            [source_id],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .map_err(storage)?;
    let mut statement = catalog
        .prepare("SELECT label FROM catalog_labels WHERE source_id = ?1 ORDER BY label")
        .map_err(storage)?;
    let labels = statement
        .query_map([source_id], |row| row.get::<_, String>(0))
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    let document = indexed_document(&body, &summary, &labels);
    catalog
        .execute(
            "UPDATE catalog_sessions SET search_text = ?1 WHERE source_id = ?2",
            rusqlite::params![document, source_id],
        )
        .map_err(storage)?;
    catalog
        .execute("DELETE FROM catalog_fts WHERE source_id = ?1", [source_id])
        .map_err(storage)?;
    catalog
        .execute(
            "INSERT INTO catalog_fts(source_id, project_key, search_text) VALUES (?1, ?2, ?3)",
            rusqlite::params![source_id, project_key, document],
        )
        .map_err(storage)?;
    Ok(())
}

fn indexed_document(body: &str, summary: &str, labels: &[String]) -> String {
    let mut parts = Vec::new();
    if !summary.is_empty() {
        parts.push(summary.to_string());
    }
    if !body.is_empty() && !summary.contains(body) {
        parts.push(body.to_string());
    }
    parts.extend(labels.iter().cloned());
    parts.join("\n")
}

fn excerpts_from(content_json: &str) -> Vec<(String, String)> {
    let Ok(content) = serde_json::from_str::<serde_json::Value>(content_json) else {
        return Vec::new();
    };
    let Some(items) = content
        .get("excerpts")
        .and_then(serde_json::Value::as_array)
    else {
        return Vec::new();
    };
    let mut found = Vec::new();
    for item in items {
        let Some(role) = item.get("role").and_then(serde_json::Value::as_str) else {
            continue;
        };
        let Some(text) = item.get("text").and_then(serde_json::Value::as_str) else {
            continue;
        };
        let redacted = redact(text, ContentKind::VisibleText).trim().to_string();
        if !redacted.is_empty() {
            found.push((role.to_string(), redacted));
        }
    }
    found
}

fn labels_for(catalog: &Connection, ids: &[String]) -> Result<HashMap<String, Vec<String>>> {
    let mut grouped = HashMap::new();
    if ids.is_empty() {
        return Ok(grouped);
    }
    let placeholders = vec!["?"; ids.len()].join(", ");
    let sql = format!(
        "SELECT source_id, label FROM catalog_labels WHERE source_id IN ({placeholders}) ORDER BY source_id, label"
    );
    let mut statement = catalog.prepare(&sql).map_err(storage)?;
    let rows = statement
        .query_map(rusqlite::params_from_iter(ids.iter()), |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?))
        })
        .map_err(storage)?;
    for row in rows {
        let (source_id, label) = row.map_err(storage)?;
        grouped
            .entry(source_id)
            .or_insert_with(Vec::new)
            .push(label);
    }
    Ok(grouped)
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
            .execute(
                "DELETE FROM catalog_labels WHERE source_id = ?1",
                [&source_id],
            )
            .map_err(storage)?;
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
        category: row.get(9).map_err(storage)?,
        summary: row.get(10).map_err(storage)?,
        labels: Vec::new(),
        snippet: row.get(11).map_err(storage)?,
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
    let migrations: [&str; 2] = [
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
        );",
        "ALTER TABLE catalog_sessions ADD COLUMN category TEXT NOT NULL DEFAULT 'other';
        ALTER TABLE catalog_sessions ADD COLUMN summary TEXT NOT NULL DEFAULT '';
        ALTER TABLE catalog_sessions ADD COLUMN body_text TEXT NOT NULL DEFAULT '';
        UPDATE catalog_sessions SET body_text = search_text;
        CREATE TABLE catalog_labels (
            source_id TEXT NOT NULL REFERENCES catalog_sessions(source_id) ON DELETE CASCADE,
            label TEXT NOT NULL CHECK(length(label) > 0),
            created_at TEXT NOT NULL,
            PRIMARY KEY(source_id, label)
        );
        CREATE INDEX catalog_labels_label ON catalog_labels(label, source_id);",
    ];
    let mut current = current;
    while (current as usize) < migrations.len() {
        tx.execute_batch(migrations[current as usize])
            .map_err(storage)?;
        current += 1;
        tx.pragma_update(None, "user_version", current)
            .map_err(storage)?;
    }
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
