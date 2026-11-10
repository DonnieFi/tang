//! Read-only continuity signals: the git branch and indexed session count.

use crate::error::{storage, Result};
use rusqlite::Connection;
use std::path::Path;
use std::process::{Command, Stdio};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Continuity {
    pub branch: Option<String>,
    pub session_count: i64,
}

pub fn continuity(project_dir: &Path, db: &Connection, project_key: &str) -> Result<Continuity> {
    let session_count = db
        .query_row(
            "SELECT COUNT(*) FROM sessions WHERE project_key = ?1",
            [project_key],
            |row| row.get(0),
        )
        .map_err(storage)?;
    Ok(Continuity {
        branch: git_branch(project_dir),
        session_count,
    })
}

pub fn continuity_json(report: &Continuity) -> String {
    serde_json::to_string(&serde_json::json!({
        "branch": report.branch,
        "schema_version": 1,
        "sessions": report.session_count,
    }))
    .unwrap_or_else(|_| "{}".to_string())
}

pub fn render_continuity(continuity: &Continuity) -> String {
    let branch = continuity.branch.as_deref().unwrap_or("none");
    format!("branch: {branch}\nsessions: {}\n", continuity.session_count)
}

fn git_branch(project_dir: &Path) -> Option<String> {
    let mut command = Command::new("git");
    command
        .arg("-C")
        .arg(project_dir)
        .args(["rev-parse", "--abbrev-ref", "HEAD"])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let git_keys: Vec<String> = std::env::vars()
        .map(|(key, _)| key)
        .filter(|key| key.to_ascii_uppercase().starts_with("GIT_"))
        .collect();
    for key in git_keys {
        command.env_remove(key);
    }
    command.env("GIT_TERMINAL_PROMPT", "0");
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8(output.stdout).ok()?;
    let branch = text.trim();
    if branch.is_empty() || branch.chars().any(char::is_control) {
        None
    } else {
        Some(branch.to_string())
    }
}
