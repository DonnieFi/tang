//! Read OpenClaw agent SQLite sessions into the per-project database.

use crate::error::{storage, Result, TangError};
use crate::index_store::{finish_session, write_sessions, SessionDraft};
use crate::project::{owns_project, ProjectIdentity};
use crate::timeutil::rfc3339_secs;
use rusqlite::{Connection, OpenFlags, OptionalExtension};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};

pub struct OpenClawIndexResult {
    pub indexed: i64,
    pub deleted: i64,
    pub skipped: i64,
    pub warnings: Vec<String>,
}

pub fn index_openclaw(
    openclaw_home: &Path,
    project: &ProjectIdentity,
    database_path: &Path,
) -> Result<OpenClawIndexResult> {
    let home = openclaw_home.canonicalize().map_err(|_| {
        TangError::new(
            "missing-store",
            "The configured OpenClaw home is unavailable.",
        )
    })?;
    let databases = agent_databases(&home)?;
    if databases.iter().all(|path| is_symlink(path)) {
        return Err(TangError::new(
            "unsafe-session-source",
            "The OpenClaw agent database is a symlink and was not read.",
        ));
    }
    let namespace = format!(
        "store-{:x}",
        Sha256::digest(home.to_string_lossy().as_bytes())
    );
    let hint = project_root(project).to_string_lossy().to_string();
    let mut saved = Vec::new();
    let mut warnings = Vec::new();
    let mut protected = HashSet::new();
    let mut skipped = 0;
    for agent_db in databases {
        if is_symlink(&agent_db) {
            warnings.push(format!(
                "skipped symlinked OpenClaw agent database {}",
                agent_db.display()
            ));
            continue;
        }
        read_agent_database(
            &agent_db,
            project,
            &namespace,
            &hint,
            &mut AgentRead {
                saved: &mut saved,
                warnings: &mut warnings,
                protected: &mut protected,
                skipped: &mut skipped,
            },
        )?;
    }
    let wrote = write_sessions(
        database_path,
        &project.key,
        "openclaw",
        &namespace,
        "W",
        &saved,
        &protected,
    )?;
    Ok(OpenClawIndexResult {
        indexed: wrote.indexed,
        deleted: wrote.deleted,
        skipped,
        warnings,
    })
}

fn agent_databases(home: &Path) -> Result<Vec<PathBuf>> {
    let agents = home.join("agents");
    if !agents.is_dir() {
        return Err(TangError::new(
            "missing-store",
            "No OpenClaw agent database was found.",
        ));
    }
    let mut found = Vec::new();
    let entries = fs::read_dir(&agents)
        .map_err(|_| TangError::new("missing-store", "No OpenClaw agent database was found."))?;
    for entry in entries {
        let path = entry
            .map_err(|_| TangError::new("missing-store", "No OpenClaw agent database was found."))?
            .path();
        if is_symlink(&path) {
            continue;
        }
        let database = path.join("agent/openclaw-agent.sqlite");
        if database.is_file() || is_symlink(&database) {
            found.push(database);
        }
    }
    found.sort();
    if found.is_empty() {
        return Err(TangError::new(
            "missing-store",
            "No OpenClaw agent database was found.",
        ));
    }
    Ok(found)
}

fn is_symlink(path: &Path) -> bool {
    path.symlink_metadata()
        .map(|meta| meta.file_type().is_symlink())
        .unwrap_or(false)
}

struct AgentRead<'a> {
    saved: &'a mut Vec<crate::index_store::SavedSession>,
    warnings: &'a mut Vec<String>,
    protected: &'a mut HashSet<String>,
    skipped: &'a mut i64,
}

fn read_agent_database(
    agent_db: &Path,
    project: &ProjectIdentity,
    namespace: &str,
    hint: &str,
    read: &mut AgentRead<'_>,
) -> Result<()> {
    let connection =
        Connection::open_with_flags(agent_db, OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(storage)?;
    let mut statement = connection
        .prepare(
            "SELECT session_key, display_name, created_at, updated_at, last_activity_at
             FROM session_nodes ORDER BY session_key",
        )
        .map_err(storage)?;
    let nodes = statement
        .query_map([], |row| {
            Ok((
                row.get::<_, String>(0)?,
                row.get::<_, Option<String>>(1)?,
                row.get::<_, Option<i64>>(2)?,
                row.get::<_, Option<i64>>(3)?,
                row.get::<_, Option<i64>>(4)?,
            ))
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    drop(statement);
    for (session_key, title, created_at, updated_at, last_activity) in nodes {
        let native_id = urlsafe_b64(session_key.as_bytes());
        let source_id = format!("openclaw:{namespace}:{native_id}");
        let Some((session_id, started_millis)) = latest_window(&connection, &session_key)? else {
            read.protected.insert(source_id);
            *read.skipped += 1;
            continue;
        };
        let events = read_events(&connection, &session_id)?;
        if events_are_foreign(&events, project) {
            read.protected.insert(source_id);
            *read.skipped += 1;
            continue;
        }
        let turns = visible_turns(&events);
        let started =
            rfc3339_secs(((started_millis.or(created_at).unwrap_or(0)).max(0) / 1000) as u64);
        let updated_millis = [updated_at, last_activity, started_millis, created_at]
            .into_iter()
            .flatten()
            .max()
            .unwrap_or(0);
        let updated = rfc3339_secs((updated_millis.max(0) / 1000) as u64);
        let fingerprint = format!("{:x}", Sha256::digest(session_id.as_bytes()));
        let locator = agent_db.to_string_lossy();
        match finish_session(SessionDraft {
            adapter: "openclaw",
            namespace,
            native_id: &native_id,
            locator: locator.as_ref(),
            fingerprint: &fingerprint,
            project_hint: hint,
            started_at: &started,
            updated_at: &updated,
            health: "unknown",
            title,
            turns,
        }) {
            Ok(record) => read.saved.push(record),
            Err(message) => {
                read.protected.insert(source_id);
                read.warnings.push(message);
            }
        }
    }
    Ok(())
}

fn latest_window(
    connection: &Connection,
    session_key: &str,
) -> Result<Option<(String, Option<i64>)>> {
    connection
        .query_row(
            "SELECT session_id, started_at FROM session_windows
             WHERE session_key = ?1
             ORDER BY COALESCE(ended_at, started_at, 0) DESC, session_id DESC
             LIMIT 1",
            [session_key],
            |row| Ok((row.get::<_, String>(0)?, row.get::<_, Option<i64>>(1)?)),
        )
        .optional()
        .map_err(storage)
}

fn read_events(connection: &Connection, session_id: &str) -> Result<Vec<Value>> {
    let mut statement = connection
        .prepare("SELECT event_json FROM transcript_events WHERE session_id = ?1 ORDER BY seq")
        .map_err(storage)?;
    let rows = statement
        .query_map([session_id], |row| row.get::<_, String>(0))
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    Ok(rows
        .into_iter()
        .filter_map(|text| serde_json::from_str(&text).ok())
        .collect())
}

fn events_are_foreign(events: &[Value], project: &ProjectIdentity) -> bool {
    events.iter().any(|event| {
        event
            .get("cwd")
            .and_then(Value::as_str)
            .or_else(|| {
                event
                    .get("message")
                    .and_then(|message| message.get("cwd"))
                    .and_then(Value::as_str)
            })
            .is_some_and(|cwd| Path::new(cwd).is_dir() && !owns_project(cwd, project))
    })
}

fn visible_turns(events: &[Value]) -> Vec<(String, String)> {
    let mut turns = Vec::new();
    for event in events {
        if event.get("type").and_then(Value::as_str) != Some("message") {
            continue;
        }
        let Some(message) = event.get("message") else {
            continue;
        };
        let role = match message.get("role").and_then(Value::as_str) {
            Some("user") => "user",
            Some("assistant") => "agent",
            _ => continue,
        };
        let text = match message.get("content") {
            Some(Value::String(text)) => text.clone(),
            Some(Value::Array(blocks)) => blocks
                .iter()
                .filter(|block| block.get("type").and_then(Value::as_str) == Some("text"))
                .filter_map(|block| block.get("text").and_then(Value::as_str))
                .collect::<Vec<_>>()
                .join("\n"),
            _ => String::new(),
        };
        if !text.trim().is_empty() {
            turns.push((role.to_string(), text));
        }
    }
    turns
}

fn project_root(project: &ProjectIdentity) -> PathBuf {
    project
        .database_path
        .parent()
        .and_then(Path::parent)
        .map(Path::to_path_buf)
        .unwrap_or_else(|| project.database_path.clone())
}

fn urlsafe_b64(input: &[u8]) -> String {
    const TABLE: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    let mut out = String::new();
    let mut index = 0;
    while index + 3 <= input.len() {
        let chunk = ((input[index] as u32) << 16)
            | ((input[index + 1] as u32) << 8)
            | input[index + 2] as u32;
        out.push(TABLE[((chunk >> 18) & 63) as usize] as char);
        out.push(TABLE[((chunk >> 12) & 63) as usize] as char);
        out.push(TABLE[((chunk >> 6) & 63) as usize] as char);
        out.push(TABLE[(chunk & 63) as usize] as char);
        index += 3;
    }
    if index < input.len() {
        let mut chunk = (input[index] as u32) << 16;
        if index + 1 < input.len() {
            chunk |= (input[index + 1] as u32) << 8;
        }
        out.push(TABLE[((chunk >> 18) & 63) as usize] as char);
        out.push(TABLE[((chunk >> 12) & 63) as usize] as char);
        if index + 1 < input.len() {
            out.push(TABLE[((chunk >> 6) & 63) as usize] as char);
        }
    }
    out
}
