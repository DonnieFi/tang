//! Delete one project's derived rows and leave the database file in place.
//!
//! Native logs are never opened. Rows for every other `project_key` stay.

use crate::error::{storage, Result, TangError};
use rusqlite::{Connection, OptionalExtension};

pub fn purge_project(db: &mut Connection, project_key: &str) -> Result<(i64, i64, i64)> {
    let transaction = db.transaction().map_err(storage)?;
    let sessions = count_project(&transaction, "sessions", project_key)?;
    let capsules = count_project(&transaction, "capsules", project_key)?;
    let edges = count_project(&transaction, "continuation_edges", project_key)?;
    delete_project(&transaction, "continuation_edges", project_key)?;
    if table_exists(&transaction, "capsules_fts")? {
        delete_fts(&transaction, project_key)?;
    }
    if table_exists(&transaction, "session_overrides")? {
        delete_overrides(&transaction, project_key)?;
    }
    if table_exists(&transaction, "session_tags")? {
        transaction
            .execute(
                "DELETE FROM session_tags WHERE source_id IN (
                    SELECT source_id FROM sessions WHERE project_key = ?1
                 )",
                [project_key],
            )
            .map_err(storage)?;
    }
    delete_project(&transaction, "capsules", project_key)?;
    delete_project(&transaction, "sessions", project_key)?;
    transaction.commit().map_err(storage)?;
    Ok((sessions, capsules, edges))
}

fn count_project(db: &Connection, table: &str, project_key: &str) -> Result<i64> {
    let sql = match table {
        "sessions" => "SELECT COUNT(*) FROM sessions WHERE project_key = ?1",
        "capsules" => "SELECT COUNT(*) FROM capsules WHERE project_key = ?1",
        "continuation_edges" => "SELECT COUNT(*) FROM continuation_edges WHERE project_key = ?1",
        _ => {
            return Err(TangError::new(
                "storage-unavailable",
                "Unsupported derived-data table.",
            ))
        }
    };
    db.query_row(sql, [project_key], |row| row.get(0))
        .map_err(storage)
}

fn delete_project(db: &Connection, table: &str, project_key: &str) -> Result<()> {
    let sql = match table {
        "sessions" => "DELETE FROM sessions WHERE project_key = ?1",
        "capsules" => "DELETE FROM capsules WHERE project_key = ?1",
        "continuation_edges" => "DELETE FROM continuation_edges WHERE project_key = ?1",
        _ => {
            return Err(TangError::new(
                "storage-unavailable",
                "Unsupported derived-data table.",
            ))
        }
    };
    db.execute(sql, [project_key]).map_err(storage)?;
    Ok(())
}

fn delete_fts(db: &Connection, project_key: &str) -> Result<()> {
    if column_exists(db, "capsules_fts", "project_key")? {
        db.execute(
            "DELETE FROM capsules_fts WHERE project_key = ?1",
            [project_key],
        )
        .map_err(storage)?;
        return Ok(());
    }
    db.execute(
        "DELETE FROM capsules_fts WHERE source_id IN (
            SELECT source_id FROM sessions WHERE project_key = ?1
         )",
        [project_key],
    )
    .map_err(storage)?;
    Ok(())
}

fn delete_overrides(db: &Connection, project_key: &str) -> Result<()> {
    if column_exists(db, "session_overrides", "project_key")? {
        db.execute(
            "DELETE FROM session_overrides WHERE project_key = ?1",
            [project_key],
        )
        .map_err(storage)?;
        return Ok(());
    }
    db.execute(
        "DELETE FROM session_overrides WHERE source_id IN (
            SELECT source_id FROM sessions WHERE project_key = ?1
         )",
        [project_key],
    )
    .map_err(storage)?;
    Ok(())
}

fn table_exists(db: &Connection, table: &str) -> Result<bool> {
    if !matches!(table, "capsules_fts" | "session_overrides") {
        return Ok(false);
    }
    let found: Option<String> = db
        .query_row(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?1",
            [table],
            |row| row.get(0),
        )
        .optional()
        .map_err(storage)?;
    Ok(found.is_some())
}

fn column_exists(db: &Connection, table: &str, column: &str) -> Result<bool> {
    let sql = match table {
        "capsules_fts" => "PRAGMA table_info(capsules_fts)",
        "session_overrides" => "PRAGMA table_info(session_overrides)",
        _ => return Ok(false),
    };
    let mut statement = db.prepare(sql).map_err(storage)?;
    let names = statement
        .query_map([], |row| row.get::<_, String>(1))
        .map_err(storage)?;
    for name in names {
        if name.map_err(storage)? == column {
            return Ok(true);
        }
    }
    Ok(false)
}
