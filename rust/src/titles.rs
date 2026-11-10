//! User-owned session titles. Native harness logs are never modified.

use crate::error::{storage, Result, TangError};
use crate::index_store::ensure_session_overrides;
use crate::redact::{redact, ContentKind};
use crate::timeutil::rfc3339_now;
use rusqlite::{params, Connection, OptionalExtension, TransactionBehavior};

pub fn set_title(
    db: &mut Connection,
    project_key: &str,
    token: &str,
    title: &str,
) -> Result<String> {
    let title = persisted_title(title)?;
    ensure_session_overrides(db)?;
    let tx = db
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let resolved = resolve(&tx, project_key, token)?;
    let previous: Option<String> = tx
        .query_row(
            "SELECT title FROM sessions WHERE source_id = ?1 AND project_key = ?2",
            params![resolved.source_id, project_key],
            |row| row.get(0),
        )
        .map_err(storage)?;
    let now = rfc3339_now();
    tx.execute(
        "INSERT INTO session_overrides(
            source_id, project_key, custom_title, previous_title, updated_at
         ) VALUES (?1, ?2, ?3, ?4, ?5)
         ON CONFLICT(source_id) DO UPDATE SET
            project_key = excluded.project_key,
            custom_title = excluded.custom_title,
            updated_at = excluded.updated_at",
        params![resolved.source_id, project_key, title, previous, now],
    )
    .map_err(storage)?;
    tx.execute(
        "UPDATE sessions SET title = ?1 WHERE source_id = ?2 AND project_key = ?3",
        params![title, resolved.source_id, project_key],
    )
    .map_err(storage)?;
    tx.commit().map_err(storage)?;
    Ok(resolved.handle)
}

pub fn clear_title(db: &mut Connection, project_key: &str, token: &str) -> Result<String> {
    ensure_session_overrides(db)?;
    let tx = db
        .transaction_with_behavior(TransactionBehavior::Immediate)
        .map_err(storage)?;
    let resolved = resolve(&tx, project_key, token)?;
    let previous = tx
        .query_row(
            "SELECT previous_title FROM session_overrides
             WHERE source_id = ?1 AND project_key = ?2",
            params![resolved.source_id, project_key],
            |row| row.get::<_, Option<String>>(0),
        )
        .optional()
        .map_err(storage)?;
    if let Some(previous) = previous {
        tx.execute(
            "UPDATE sessions SET title = ?1 WHERE source_id = ?2 AND project_key = ?3",
            params![previous, resolved.source_id, project_key],
        )
        .map_err(storage)?;
        tx.execute(
            "DELETE FROM session_overrides WHERE source_id = ?1 AND project_key = ?2",
            params![resolved.source_id, project_key],
        )
        .map_err(storage)?;
    }
    tx.commit().map_err(storage)?;
    Ok(resolved.handle)
}

fn persisted_title(title: &str) -> Result<String> {
    let trimmed = title.trim();
    if trimmed.is_empty() {
        return Err(TangError::new("invalid-title", "Title must not be empty."));
    }
    let redacted = redact(trimmed, ContentKind::Title);
    let bounded: String = redacted.trim().chars().take(256).collect();
    if bounded.is_empty() {
        return Err(TangError::new("invalid-title", "Title must not be empty."));
    }
    Ok(bounded)
}

struct ResolvedSession {
    source_id: String,
    handle: String,
}

fn resolve(db: &Connection, project_key: &str, token: &str) -> Result<ResolvedSession> {
    if token.is_empty() || token.trim() != token {
        return Err(missing_session());
    }
    if token.contains(':') {
        return resolve_source(db, project_key, token);
    }
    if !valid_handle(token) {
        return Err(missing_session());
    }
    let found = db
        .query_row(
            "SELECT source_id, session_handle
             FROM sessions
             WHERE project_key = ?1 AND LOWER(session_handle) = LOWER(?2)
             ORDER BY session_handle
             LIMIT 1",
            params![project_key, token],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?)),
        )
        .optional()
        .map_err(storage)?;
    match found {
        Some((source_id, handle)) => Ok(resolved(source_id, handle)),
        None => Err(missing_session()),
    }
}

fn resolve_source(db: &Connection, project_key: &str, source_id: &str) -> Result<ResolvedSession> {
    let found = db
        .query_row(
            "SELECT source_id, session_handle
             FROM sessions
             WHERE project_key = ?1 AND source_id = ?2",
            params![project_key, source_id],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<String>>(1)?)),
        )
        .optional()
        .map_err(storage)?;
    match found {
        Some((source_id, handle)) => Ok(resolved(source_id, handle)),
        None => Err(missing_session()),
    }
}

fn resolved(source_id: String, handle: Option<String>) -> ResolvedSession {
    let handle = match handle {
        Some(value) if !value.is_empty() => value,
        _ => source_id.clone(),
    };
    ResolvedSession { source_id, handle }
}

fn valid_handle(token: &str) -> bool {
    let mut chars = token.chars();
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

fn missing_session() -> TangError {
    TangError::new(
        "not-in-project",
        "Session is not indexed in the current project.",
    )
}
