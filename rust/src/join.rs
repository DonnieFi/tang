//! Same-project continuation edges resolved from catalog handles.

use crate::error::{storage, Result, TangError};
use rusqlite::{Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::{Path, PathBuf};
use std::time::Duration;

const DESTINATIONS: &[&str] = &[
    "antigravity",
    "claude",
    "codex",
    "cursor",
    "grok",
    "openclaw",
    "opencode",
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct JoinPlan {
    pub source_ids: Vec<String>,
    pub source_handles: Vec<String>,
    pub target_id: String,
    pub target_handle: String,
    pub project_key: String,
    pub database_path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LinkResult {
    pub source_ids: Vec<String>,
    pub target_id: String,
    pub inserted: i64,
    pub existing: i64,
}

pub fn resolve_join(catalog: &Connection, sources: &[String], target: &str) -> Result<JoinPlan> {
    if sources.is_empty() {
        return Err(TangError::new(
            "no-sources",
            "Select at least one source session.",
        ));
    }
    let source_rows: Vec<CatalogSession> = sources
        .iter()
        .map(|token| lookup(catalog, token))
        .collect::<Result<_>>()?;
    let target_row = lookup(catalog, target)?;
    if source_rows
        .iter()
        .any(|row| row.project_key != target_row.project_key)
    {
        return Err(TangError::new(
            "cross-project",
            "Tang joins sessions only when they belong to the same project.",
        ));
    }
    let database_path = PathBuf::from(&target_row.database_path);
    assert_project_database(&database_path)?;
    Ok(JoinPlan {
        source_ids: source_rows
            .iter()
            .map(|row| row.source_id.clone())
            .collect(),
        source_handles: source_rows
            .iter()
            .map(|row| row.catalog_handle.clone())
            .collect(),
        target_id: target_row.source_id,
        target_handle: target_row.catalog_handle,
        project_key: target_row.project_key,
        database_path,
    })
}

pub fn link_plan(
    project_db: &mut Connection,
    plan: &JoinPlan,
    confirmed_at: &str,
) -> Result<LinkResult> {
    if plan.source_ids.is_empty() {
        return Err(TangError::new(
            "no-sources",
            "Select at least one source session.",
        ));
    }
    if plan.source_ids.len() != plan.source_ids.iter().collect::<BTreeSet<_>>().len() {
        return Err(TangError::new(
            "duplicate-source",
            "A source was selected more than once.",
        ));
    }
    if plan
        .source_ids
        .iter()
        .any(|source| source == &plan.target_id)
    {
        return Err(TangError::new(
            "self-link",
            "A session cannot continue into itself.",
        ));
    }
    let tx = project_db
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let target = load_session(&tx, &plan.target_id)?
        .ok_or_else(|| TangError::new("unknown-target", "The target session is not indexed."))?;
    if target.project_key != plan.project_key {
        return Err(TangError::new(
            "foreign-target",
            "The target does not belong to the current project.",
        ));
    }
    if !DESTINATIONS.contains(&target.adapter.as_str()) {
        return Err(TangError::new(
            "unsupported-target",
            "Tang cannot join into that harness.",
        ));
    }
    let mut sources = Vec::new();
    for source_id in &plan.source_ids {
        let source = load_session(&tx, source_id)?.ok_or_else(|| {
            TangError::new(
                "unknown-source",
                "A selected source session is not indexed.",
            )
        })?;
        if source.project_key != plan.project_key {
            return Err(TangError::new(
                "foreign-source",
                "A selected source does not belong to the current project.",
            ));
        }
        sources.push(source);
    }
    let existing = load_edges(&tx, &plan.project_key)?;
    let existing_pairs: BTreeSet<(String, String)> = existing.iter().cloned().collect();
    let new_sources: Vec<&SessionRow> = sources
        .iter()
        .filter(|source| {
            !existing_pairs.contains(&(source.source_id.clone(), plan.target_id.clone()))
        })
        .collect();
    if !new_sources.is_empty() && !target.native_available {
        return Err(TangError::new(
            "unavailable-target",
            "The target native session is unavailable and cannot receive a new continuation.",
        ));
    }
    if new_sources.iter().any(|source| !source.native_available) {
        return Err(TangError::new(
            "unavailable-source",
            "A selected native source is unavailable and cannot form a new continuation.",
        ));
    }
    let candidates: Vec<(String, String)> = plan
        .source_ids
        .iter()
        .map(|source| (source.clone(), plan.target_id.clone()))
        .collect();
    if introduces_cycle(&existing, &candidates) {
        return Err(TangError::new(
            "cycle",
            "The requested continuation would create a cycle.",
        ));
    }
    let mut inserted = 0;
    for source_id in &plan.source_ids {
        let changed = tx
            .execute(
                "INSERT INTO continuation_edges(
                    source_id, target_id, project_key, confirmation_mode, confirmed_at, schema_version
                 ) VALUES (?1, ?2, ?3, 'explicit', ?4, 1)
                 ON CONFLICT(source_id, target_id) DO NOTHING",
                rusqlite::params![source_id, plan.target_id, plan.project_key, confirmed_at],
            )
            .map_err(storage)?;
        inserted += changed as i64;
    }
    tx.commit().map_err(storage)?;
    let total = plan.source_ids.len() as i64;
    Ok(LinkResult {
        source_ids: plan.source_ids.clone(),
        target_id: plan.target_id.clone(),
        inserted,
        existing: total - inserted,
    })
}

pub fn open_project_readwrite(path: &Path) -> Result<Connection> {
    let connection =
        Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE).map_err(storage)?;
    // Foreign-key and lock settings are per connection and must be set before
    // a transaction starts; SQLite ignores PRAGMA foreign_keys inside one.
    connection
        .busy_timeout(Duration::from_millis(5_000))
        .map_err(storage)?;
    connection
        .pragma_update(None, "foreign_keys", "ON")
        .map_err(storage)?;
    connection
        .pragma_update(None, "journal_mode", "WAL")
        .map_err(storage)?;
    Ok(connection)
}

fn catalog_handle(token: &str) -> Result<String> {
    let normalized = token.to_ascii_uppercase();
    let mut chars = normalized.chars();
    let first = chars.next().unwrap_or('\0');
    let rest: String = chars.collect();
    if !first.is_ascii_alphabetic()
        || rest.is_empty()
        || !rest.bytes().all(|byte| byte.is_ascii_digit())
        || rest.starts_with('0')
    {
        return Err(TangError::new(
            "invalid-session",
            "A catalog handle is a letter followed by a number, such as C1.",
        ));
    }
    Ok(normalized)
}

fn assert_project_database(path: &Path) -> Result<()> {
    if !path.is_file() {
        return Err(TangError::new(
            "storage-unavailable",
            "The project database recorded for this session is missing.",
        ));
    }
    let connection =
        Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(storage)?;
    let mut statement = connection
        .prepare("SELECT name FROM sqlite_master WHERE type = 'table'")
        .map_err(storage)?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(0))
        .map_err(storage)?
        .collect::<std::result::Result<BTreeSet<_>, _>>()
        .map_err(storage)?;
    if !["capsules", "continuation_edges", "sessions"]
        .iter()
        .all(|name| names.contains(*name))
    {
        return Err(TangError::new(
            "not-tang-database",
            "The catalog does not point at a Tang project database.",
        ));
    }
    Ok(())
}

struct CatalogSession {
    source_id: String,
    catalog_handle: String,
    project_key: String,
    database_path: String,
}

fn lookup(catalog: &Connection, token: &str) -> Result<CatalogSession> {
    if token.is_empty() || token.trim() != token {
        return Err(TangError::new(
            "invalid-session",
            "The session token must be non-empty and trimmed.",
        ));
    }
    let sql = if token.contains(':') {
        "SELECT source_id, catalog_handle, project_key, database_path
         FROM catalog_sessions WHERE source_id = ?1"
    } else {
        "SELECT source_id, catalog_handle, project_key, database_path
         FROM catalog_sessions WHERE catalog_handle = ?1"
    };
    let key = if token.contains(':') {
        token.to_string()
    } else {
        catalog_handle(token)?
    };
    catalog
        .query_row(sql, [key], |row| {
            Ok(CatalogSession {
                source_id: row.get(0)?,
                catalog_handle: row.get(1)?,
                project_key: row.get(2)?,
                database_path: row.get(3)?,
            })
        })
        .optional()
        .map_err(storage)?
        .ok_or_else(|| {
            TangError::new(
                "not-in-catalog",
                "That session is not in the global catalog. Run tang catalog sync.",
            )
        })
}

struct SessionRow {
    source_id: String,
    adapter: String,
    project_key: String,
    native_available: bool,
}

fn load_session(connection: &Connection, source_id: &str) -> Result<Option<SessionRow>> {
    connection
        .query_row(
            "SELECT source_id, adapter, project_key, native_available FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| {
                Ok(SessionRow {
                    source_id: row.get(0)?,
                    adapter: row.get(1)?,
                    project_key: row.get(2)?,
                    native_available: row.get::<_, i64>(3)? != 0,
                })
            },
        )
        .optional()
        .map_err(storage)
}

fn load_edges(connection: &Connection, project_key: &str) -> Result<Vec<(String, String)>> {
    let mut statement = connection
        .prepare(
            "SELECT source_id, target_id FROM continuation_edges WHERE project_key = ?1 ORDER BY source_id, target_id",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map([project_key], |row| Ok((row.get(0)?, row.get(1)?)))
        .map_err(storage)?;
    rows.collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)
}

fn introduces_cycle(existing: &[(String, String)], candidates: &[(String, String)]) -> bool {
    let mut adjacency: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for (source, target) in existing.iter().chain(candidates.iter()) {
        adjacency
            .entry(source.clone())
            .or_default()
            .insert(target.clone());
        adjacency.entry(target.clone()).or_default();
    }
    let mut state: HashMap<String, u8> = HashMap::new();
    for start in adjacency.keys().cloned().collect::<Vec<_>>() {
        if state.get(&start).copied().unwrap_or(0) != 0 {
            continue;
        }
        state.insert(start.clone(), 1);
        let mut stack = vec![Frame {
            node: start.clone(),
            targets: adjacency
                .get(&start)
                .map(|targets| targets.iter().cloned().collect())
                .unwrap_or_default(),
            index: 0,
        }];
        while let Some(frame) = stack.last_mut() {
            if frame.index >= frame.targets.len() {
                state.insert(frame.node.clone(), 2);
                stack.pop();
                continue;
            }
            let target = frame.targets[frame.index].clone();
            frame.index += 1;
            match state.get(&target).copied().unwrap_or(0) {
                1 => return true,
                0 => {
                    state.insert(target.clone(), 1);
                    let targets = adjacency
                        .get(&target)
                        .map(|values| values.iter().cloned().collect())
                        .unwrap_or_default();
                    stack.push(Frame {
                        node: target,
                        targets,
                        index: 0,
                    });
                }
                _ => {}
            }
        }
    }
    false
}

struct Frame {
    node: String,
    targets: Vec<String>,
    index: usize,
}
