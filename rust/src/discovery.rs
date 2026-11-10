//! Current-project browse and full-text search.

use crate::error::{storage, Result, TangError};
use rusqlite::{Connection, OptionalExtension};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DiscoveryQuery<'a> {
    pub text: Option<&'a str>,
    pub harness: Option<&'a str>,
    pub directory: Option<&'a str>,
    pub include_unavailable: bool,
    pub limit: i64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiscoveryRow {
    pub source_id: String,
    pub handle: String,
    pub harness: String,
    pub title: String,
    pub health: String,
    pub updated_at: String,
    pub native_available: bool,
    pub snippet: Option<String>,
    pub directory: String,
}

pub fn browse(
    db: &Connection,
    project_key: Option<&str>,
    query: &DiscoveryQuery<'_>,
) -> Result<Vec<DiscoveryRow>> {
    validate_limit(query.limit)?;
    let overrides = table_exists(db, "session_overrides")?;
    let title_sql = title_expr(overrides);
    let join_sql = override_join(overrides);
    let filters = extra_filters(query);
    let (scope, scope_params) = project_scope(project_key);
    let sql = format!(
        "SELECT s.source_id,
                COALESCE(s.session_handle, ''),
                s.adapter,
                {title_sql},
                s.health,
                s.updated_at,
                s.native_available,
                c.content_json
         FROM sessions AS s
         JOIN capsules AS c ON c.source_id = s.source_id
         {join_sql}
         WHERE {scope}{filters}
         ORDER BY s.updated_at DESC, s.source_id
         LIMIT ?"
    );
    let mut params = scope_params;
    push_filters(&mut params, query);
    params.push(query.limit.to_string());
    let mut rows = query_rows(db, &sql, &params, SnippetSource::Content)?;
    attach_directories(db, &mut rows)?;
    Ok(rows)
}

pub fn search_project(
    db: &Connection,
    project_key: Option<&str>,
    query: &DiscoveryQuery<'_>,
) -> Result<Vec<DiscoveryRow>> {
    validate_limit(query.limit)?;
    let text = query
        .text
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| TangError::new("empty-query", "Search query must not be empty."))?;
    if !table_exists(db, "capsules_fts")? {
        crate::index_store::ensure_capsules_fts(db)?;
        db.execute(
            "INSERT INTO capsules_fts(source_id, project_key, search_text)
             SELECT source_id, project_key, search_text FROM capsules",
            [],
        )
        .map_err(storage)?;
    }
    let overrides = table_exists(db, "session_overrides")?;
    let title_sql = title_expr(overrides);
    let join_sql = override_join(overrides);
    let filters = extra_filters(query);
    let (scope, scope_params) = project_scope(project_key);
    let sql = format!(
        "SELECT s.source_id,
                COALESCE(s.session_handle, ''),
                s.adapter,
                {title_sql},
                s.health,
                s.updated_at,
                s.native_available,
                snippet(capsules_fts, 2, '[', ']', ' … ', 18)
         FROM capsules_fts
         JOIN sessions AS s ON s.source_id = capsules_fts.source_id
         JOIN capsules AS c ON c.source_id = s.source_id
         {join_sql}
         WHERE capsules_fts MATCH ?
           AND {scope}
           AND capsules_fts.project_key = s.project_key{filters}
         ORDER BY rank, s.updated_at DESC, s.source_id
         LIMIT ?"
    );
    let mut params = vec![text.to_string()];
    params.extend(scope_params);
    push_filters(&mut params, query);
    params.push(query.limit.to_string());
    let mut rows = query_rows(db, &sql, &params, SnippetSource::Column).map_err(map_search)?;
    attach_directories(db, &mut rows)?;
    Ok(rows)
}

fn validate_limit(limit: i64) -> Result<()> {
    if !(1..=100).contains(&limit) {
        return Err(TangError::new(
            "invalid-limit",
            "Discovery limit must be between 1 and 100.",
        ));
    }
    Ok(())
}

fn title_expr(overrides: bool) -> &'static str {
    if overrides {
        "COALESCE(NULLIF(o.custom_title, ''), NULLIF(s.title, ''), '')"
    } else {
        "COALESCE(NULLIF(s.title, ''), '')"
    }
}

fn override_join(overrides: bool) -> &'static str {
    if overrides {
        "LEFT JOIN session_overrides AS o
            ON o.source_id = s.source_id AND o.project_key = s.project_key"
    } else {
        ""
    }
}

fn project_scope(project_key: Option<&str>) -> (String, Vec<String>) {
    match project_key.map(str::trim).filter(|value| !value.is_empty()) {
        Some(key) => ("s.project_key = ?".to_string(), vec![key.to_string()]),
        None => ("1 = 1".to_string(), Vec::new()),
    }
}

fn extra_filters(query: &DiscoveryQuery<'_>) -> String {
    let mut sql = String::new();
    if !query.include_unavailable {
        sql.push_str(" AND s.native_available != 0");
    }
    if harness_param(query.harness).is_some() {
        sql.push_str(" AND LOWER(s.adapter) = LOWER(?)");
    }
    if directory_param(query.directory).is_some() {
        sql.push_str(
            " AND EXISTS (
                SELECT 1 FROM session_tags AS t
                WHERE t.source_id = s.source_id AND instr(t.tag, ?) > 0
            )",
        );
    }
    sql
}

fn push_filters(params: &mut Vec<String>, query: &DiscoveryQuery<'_>) {
    if let Some(harness) = harness_param(query.harness) {
        params.push(harness);
    }
    if let Some(directory) = directory_param(query.directory) {
        params.push(directory);
    }
}

fn directory_param(directory: Option<&str>) -> Option<String> {
    directory
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn harness_param(harness: Option<&str>) -> Option<String> {
    harness
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(|value| value.to_ascii_lowercase())
}

enum SnippetSource {
    Content,
    Column,
}

fn query_rows(
    db: &Connection,
    sql: &str,
    params: &[String],
    snippets: SnippetSource,
) -> Result<Vec<DiscoveryRow>> {
    let mut statement = db.prepare(sql).map_err(storage)?;
    let mut rows = statement
        .query(rusqlite::params_from_iter(params.iter()))
        .map_err(storage)?;
    let mut found = Vec::new();
    while let Some(row) = rows.next().map_err(storage)? {
        let snippet = match snippets {
            SnippetSource::Content => {
                let content: String = row.get(7).map_err(storage)?;
                first_user_snippet(&content)
            }
            SnippetSource::Column => {
                let snippet: Option<String> = row.get(7).map_err(storage)?;
                snippet.filter(|value| !value.trim().is_empty())
            }
        };
        found.push(DiscoveryRow {
            source_id: row.get(0).map_err(storage)?,
            handle: row.get(1).map_err(storage)?,
            harness: row.get(2).map_err(storage)?,
            title: row.get(3).map_err(storage)?,
            health: row.get(4).map_err(storage)?,
            updated_at: row.get(5).map_err(storage)?,
            native_available: row.get::<_, i64>(6).map_err(storage)? != 0,
            snippet,
            directory: String::new(),
        });
    }
    Ok(found)
}

fn first_user_snippet(content_json: &str) -> Option<String> {
    let content: serde_json::Value = serde_json::from_str(content_json).ok()?;
    let excerpts = content.get("excerpts")?.as_array()?;
    for excerpt in excerpts {
        if excerpt.get("role").and_then(serde_json::Value::as_str) != Some("user") {
            continue;
        }
        let Some(text) = excerpt.get("text").and_then(serde_json::Value::as_str) else {
            continue;
        };
        let collapsed = text.split_whitespace().collect::<Vec<_>>().join(" ");
        if !collapsed.is_empty() {
            return Some(collapsed);
        }
    }
    None
}

fn attach_directories(db: &Connection, rows: &mut [DiscoveryRow]) -> Result<()> {
    if rows.is_empty() || !table_exists(db, "session_tags")? {
        return Ok(());
    }
    for row in rows {
        let tag: Option<String> = db
            .query_row(
                "SELECT tag FROM session_tags WHERE source_id = ?1 ORDER BY tag LIMIT 1",
                [&row.source_id],
                |record| record.get(0),
            )
            .optional()
            .map_err(storage)?;
        if let Some(tag) = tag {
            row.directory = tag;
        }
    }
    Ok(())
}

pub struct IndexRecall {
    pub handle: String,
    pub harness: String,
    pub title: String,
    pub summary: String,
    pub directory: String,
    pub source_id: String,
}

pub fn recall_index(db: &Connection, text: &str, limit: i64) -> Result<Vec<IndexRecall>> {
    validate_limit(limit)?;
    let text = text.trim();
    if text.is_empty() {
        return Err(TangError::new(
            "empty-query",
            "Provide a query or a label, category, or harness filter.",
        ));
    }
    let sql = if table_exists(db, "capsules_fts")? {
        "SELECT COALESCE(s.session_handle, ''),
                s.adapter,
                COALESCE(s.title, ''),
                c.search_text,
                s.source_id
         FROM capsules_fts
         JOIN sessions AS s ON s.source_id = capsules_fts.source_id
         JOIN capsules AS c ON c.source_id = s.source_id
         WHERE capsules_fts MATCH ?
         ORDER BY rank, s.updated_at DESC, s.source_id
         LIMIT ?"
    } else {
        "SELECT COALESCE(s.session_handle, ''),
                s.adapter,
                COALESCE(s.title, ''),
                c.search_text,
                s.source_id
         FROM sessions AS s
         JOIN capsules AS c ON c.source_id = s.source_id
         WHERE c.search_text LIKE '%' || ?1 || '%'
         ORDER BY s.updated_at DESC, s.source_id
         LIMIT ?2"
    };
    let mut statement = db.prepare(sql).map_err(storage)?;
    let mut rows = statement
        .query(rusqlite::params![text, limit])
        .map_err(|error| map_search(storage(error)))?;
    let mut found = Vec::new();
    while let Some(row) = rows.next().map_err(|error| map_search(storage(error)))? {
        let source_id: String = row.get(4).map_err(storage)?;
        let summary: String = row.get(3).map_err(storage)?;
        found.push(IndexRecall {
            handle: row.get(0).map_err(storage)?,
            harness: row.get(1).map_err(storage)?,
            title: row.get(2).map_err(storage)?,
            summary,
            directory: String::new(),
            source_id,
        });
    }
    drop(rows);
    drop(statement);
    if table_exists(db, "session_tags")? {
        for hit in &mut found {
            let tag: Option<String> = db
                .query_row(
                    "SELECT tag FROM session_tags WHERE source_id = ?1 ORDER BY tag LIMIT 1",
                    [&hit.source_id],
                    |record| record.get(0),
                )
                .optional()
                .map_err(storage)?;
            if let Some(tag) = tag {
                hit.directory = tag;
            }
        }
    }
    Ok(found)
}

fn table_exists(db: &Connection, name: &str) -> Result<bool> {
    let found: Option<i64> = db
        .query_row(
            "SELECT 1 FROM sqlite_master WHERE name = ?1",
            [name],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    Ok(found.is_some())
}

fn map_search(error: TangError) -> TangError {
    let text = error.message.to_ascii_lowercase();
    if error.code == "storage-unavailable" && text.contains("fts5") {
        TangError::new("malformed-query", "The search query is not valid FTS5.")
    } else {
        error
    }
}
