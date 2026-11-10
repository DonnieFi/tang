//! Plan a native resume command without launching it.
//!
//! Argv matches `src/tang/resume.py`. `cwd` is the launch directory, and the
//! same directory is included in the flags each harness actually requires.

use crate::error::{storage, Result, TangError};
use rusqlite::{Connection, OptionalExtension};
use std::fs;
use std::path::{Component, Path, PathBuf};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResumeCommand {
    pub program: String,
    pub args: Vec<String>,
    pub cwd: PathBuf,
}

enum ProjectHint {
    /// The sessions table has no project_hint column, so the worktree cannot be checked.
    Unstored,
    Stored(Option<String>),
}

struct ResolvedSession {
    adapter: String,
    native_id: String,
    native_available: i64,
    project_hint: ProjectHint,
}

pub fn plan_resume(
    db: &Connection,
    project_key: &str,
    token: &str,
    project_dir: &Path,
) -> Result<ResumeCommand> {
    if token.is_empty() || token.trim() != token {
        return Err(not_in_project());
    }
    let Some(session) = resolve_session(db, project_key, token)? else {
        return Err(not_in_project());
    };
    if session.native_available == 0 {
        return Err(TangError::new(
            "unavailable-session",
            "The selected Tang session is no longer available in its native harness.",
        ));
    }
    let cwd = fs::canonicalize(project_dir).unwrap_or_else(|_| project_dir.to_path_buf());
    command_for(&session, &cwd)
}

fn command_for(session: &ResolvedSession, cwd: &Path) -> Result<ResumeCommand> {
    let directory = path_argument(cwd)?;
    match session.adapter.as_str() {
        "codex" => {
            validate_uuid(&session.native_id, "Codex")?;
            // resume.py: executable, "resume", "-C", launch_directory, native_id
            Ok(ResumeCommand {
                program: "codex".to_string(),
                args: vec![
                    "resume".to_string(),
                    "-C".to_string(),
                    directory,
                    session.native_id.clone(),
                ],
                cwd: cwd.to_path_buf(),
            })
        }
        "grok" => {
            validate_uuid(&session.native_id, "Grok")?;
            require_recorded_directory(&session.project_hint, cwd)?;
            // resume.py: executable, "--cwd", launch_directory, "--resume", native_id
            Ok(ResumeCommand {
                program: "grok".to_string(),
                args: vec![
                    "--cwd".to_string(),
                    directory,
                    "--resume".to_string(),
                    session.native_id.clone(),
                ],
                cwd: cwd.to_path_buf(),
            })
        }
        "opencode" => {
            validate_opencode(&session.native_id)?;
            require_recorded_directory(&session.project_hint, cwd)?;
            // resume.py: executable, launch_directory, "--session", native_id
            Ok(ResumeCommand {
                program: "opencode".to_string(),
                args: vec![
                    directory,
                    "--session".to_string(),
                    session.native_id.clone(),
                ],
                cwd: cwd.to_path_buf(),
            })
        }
        "cursor" => {
            validate_uuid(&session.native_id, "Cursor")?;
            require_recorded_directory(&session.project_hint, cwd)?;
            // resume.py: executable "agent", "--workspace", launch_directory, "--resume", native_id
            Ok(ResumeCommand {
                program: "agent".to_string(),
                args: vec![
                    "--workspace".to_string(),
                    directory,
                    "--resume".to_string(),
                    session.native_id.clone(),
                ],
                cwd: cwd.to_path_buf(),
            })
        }
        "claude" => {
            validate_uuid(&session.native_id, "Claude")?;
            require_recorded_directory(&session.project_hint, cwd)?;
            // resume.py: executable, "--resume", native_id
            Ok(ResumeCommand {
                program: "claude".to_string(),
                args: vec!["--resume".to_string(), session.native_id.clone()],
                cwd: cwd.to_path_buf(),
            })
        }
        "antigravity" => {
            validate_uuid(&session.native_id, "Antigravity")?;
            require_recorded_directory(&session.project_hint, cwd)?;
            // resume.py: executable "agy", "--conversation", native_id
            Ok(ResumeCommand {
                program: "agy".to_string(),
                args: vec!["--conversation".to_string(), session.native_id.clone()],
                cwd: cwd.to_path_buf(),
            })
        }
        _ => Err(unsupported_resume()),
    }
}

fn resolve_session(
    db: &Connection,
    project_key: &str,
    token: &str,
) -> Result<Option<ResolvedSession>> {
    let hint_stored = column_exists(db, "sessions", "project_hint")?;
    if token.contains(':') {
        select_session(
            db,
            hint_stored,
            "SELECT adapter, native_id, native_available FROM sessions
             WHERE project_key = ?1 AND source_id = ?2
             ORDER BY source_id
             LIMIT 1",
            "SELECT adapter, native_id, native_available, project_hint FROM sessions
             WHERE project_key = ?1 AND source_id = ?2
             ORDER BY source_id
             LIMIT 1",
            rusqlite::params![project_key, token],
        )
    } else {
        select_session(
            db,
            hint_stored,
            "SELECT adapter, native_id, native_available FROM sessions
             WHERE project_key = ?1 AND session_handle = ?2 COLLATE NOCASE
             ORDER BY source_id
             LIMIT 1",
            "SELECT adapter, native_id, native_available, project_hint FROM sessions
             WHERE project_key = ?1 AND session_handle = ?2 COLLATE NOCASE
             ORDER BY source_id
             LIMIT 1",
            rusqlite::params![project_key, token],
        )
    }
}

fn select_session(
    db: &Connection,
    hint_stored: bool,
    without_hint: &str,
    with_hint: &str,
    params: impl rusqlite::Params,
) -> Result<Option<ResolvedSession>> {
    if hint_stored {
        db.query_row(with_hint, params, |row| {
            Ok(ResolvedSession {
                adapter: row.get(0)?,
                native_id: row.get(1)?,
                native_available: row.get(2)?,
                project_hint: ProjectHint::Stored(row.get(3)?),
            })
        })
    } else {
        db.query_row(without_hint, params, |row| {
            Ok(ResolvedSession {
                adapter: row.get(0)?,
                native_id: row.get(1)?,
                native_available: row.get(2)?,
                project_hint: ProjectHint::Unstored,
            })
        })
    }
    .optional()
    .map_err(storage)
}

fn column_exists(db: &Connection, table: &str, column: &str) -> Result<bool> {
    let sql = match table {
        "sessions" => "PRAGMA table_info(sessions)",
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

fn require_recorded_directory(hint: &ProjectHint, launch: &Path) -> Result<()> {
    let ProjectHint::Stored(value) = hint else {
        return Ok(());
    };
    let Some(value) = value.as_deref().filter(|value| !value.is_empty()) else {
        return Err(unavailable_directory());
    };
    let recorded = canonicalize_hint(value).ok_or_else(unavailable_directory)?;
    let launch = fs::canonicalize(launch).map_err(|_| unavailable_directory())?;
    if recorded == launch {
        Ok(())
    } else {
        Err(TangError::new(
            "resume-project-mismatch",
            "The selected session belongs to another worktree.",
        ))
    }
}

fn canonicalize_hint(value: &str) -> Option<PathBuf> {
    let expanded = if let Some(rest) = value.strip_prefix("~/") {
        home_dir().join(rest)
    } else if value == "~" {
        home_dir()
    } else {
        PathBuf::from(value)
    };
    let canonical = fs::canonicalize(&expanded).ok()?;
    canonical.is_dir().then_some(canonical)
}

fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn path_argument(path: &Path) -> Result<String> {
    let normalized = normalize_lexical(path);
    normalized.to_str().map(ToOwned::to_owned).ok_or_else(|| {
        TangError::new(
            "resume-project-unavailable",
            "The indexed session directory is unavailable.",
        )
    })
}

fn normalize_lexical(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                normalized.pop();
            }
            other => normalized.push(other.as_os_str()),
        }
    }
    normalized
}

fn validate_uuid(native_id: &str, harness: &str) -> Result<()> {
    if is_canonical_uuid(native_id) {
        Ok(())
    } else {
        Err(TangError::new(
            "resume-native-id-invalid",
            format!("The indexed {harness} session does not have a supported native identity."),
        ))
    }
}

fn validate_opencode(native_id: &str) -> Result<()> {
    if is_opencode_session(native_id) {
        Ok(())
    } else {
        Err(TangError::new(
            "resume-native-id-invalid",
            "The indexed OpenCode session does not have a supported native identity.",
        ))
    }
}

/// Hyphenated UUID text. Case is preserved; the shape matches `uuid.UUID`.
fn is_canonical_uuid(value: &str) -> bool {
    let bytes = value.as_bytes();
    if bytes.len() != 36 {
        return false;
    }
    bytes.iter().enumerate().all(|(index, byte)| match index {
        8 | 13 | 18 | 23 => *byte == b'-',
        _ => byte.is_ascii_hexdigit(),
    })
}

fn is_opencode_session(value: &str) -> bool {
    let Some(rest) = value.strip_prefix("ses_") else {
        return false;
    };
    !rest.is_empty()
        && rest.chars().all(|character| {
            character.is_ascii_alphanumeric() || character == '_' || character == '-'
        })
}

fn not_in_project() -> TangError {
    TangError::new(
        "not-in-project",
        "That Tang handle is not indexed in the current project.",
    )
}

fn unsupported_resume() -> TangError {
    TangError::new(
        "unsupported-resume",
        "That harness is a read-only source and cannot be resumed.",
    )
}

fn unavailable_directory() -> TangError {
    TangError::new(
        "resume-project-unavailable",
        "The indexed session directory is unavailable.",
    )
}
