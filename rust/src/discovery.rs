//! Current-project browse and full-text search.

use crate::error::{storage, Result, TangError};
use rusqlite::{Connection, OptionalExtension};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct DiscoveryQuery<'a> {
    pub text: Option<&'a str>,
    pub harness: Option<&'a str>,
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
}

pub fn browse(
    db: &Connection,
    project_key: &str,
    query: &DiscoveryQuery<'_>,
) -> Result<Vec<DiscoveryRow>> {
    validate_limit(query.limit)?;
    let overrides = table_exists(db, "session_overrides")?;
    let title_sql = title_expr(overrides);
    let join_sql = override_join(overrides);
    let filters = extra_filters(query);
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
         WHERE s.project_key = ?{filters}
         ORDER BY s.updated_at DESC, s.source_id
         LIMIT ?"
    );
    let params = bound_params(project_key, query);
    query_rows(db, &sql, &params, SnippetSource::Content)
}

pub fn search_project(
    db: &Connection,
    project_key: &str,
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
           AND s.project_key = ?
           AND capsules_fts.project_key = s.project_key{filters}
         ORDER BY rank, s.updated_at DESC, s.source_id
         LIMIT ?"
    );
    let mut params = vec![text.to_string(), project_key.to_string()];
    push_filters(&mut params, query);
    params.push(query.limit.to_string());
    query_rows(db, &sql, &params, SnippetSource::Column).map_err(map_search)
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

fn extra_filters(query: &DiscoveryQuery<'_>) -> String {
    let mut sql = String::new();
    if !query.include_unavailable {
        sql.push_str(" AND s.native_available != 0");
    }
    if harness_param(query.harness).is_some() {
        sql.push_str(" AND LOWER(s.adapter) = LOWER(?)");
    }
    sql
}

fn bound_params(project_key: &str, query: &DiscoveryQuery<'_>) -> Vec<String> {
    let mut params = vec![project_key.to_string()];
    push_filters(&mut params, query);
    params.push(query.limit.to_string());
    params
}

fn push_filters(params: &mut Vec<String>, query: &DiscoveryQuery<'_>) {
    if let Some(harness) = harness_param(query.harness) {
        params.push(harness);
    }
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
