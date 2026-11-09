//! Project identity compatible with the existing per-project database path.

use crate::error::{Result, TangError};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

pub struct ProjectIdentity {
    pub key: String,
    pub display_name: String,
    pub database_path: PathBuf,
}

pub fn resolve_project(directory: &Path) -> Result<ProjectIdentity> {
    let resolved = directory
        .canonicalize()
        .map_err(|_| TangError::new("invalid-project", "project path must identify a directory"))?;
    if !resolved.is_dir() {
        return Err(TangError::new(
            "invalid-project",
            "project path must identify a directory",
        ));
    }
    if let Some(common) = git_common_dir(&resolved) {
        let root = if common.file_name().and_then(|name| name.to_str()) == Some(".git") {
            common
                .parent()
                .map(Path::to_path_buf)
                .unwrap_or_else(|| common.clone())
        } else {
            common.clone()
        };
        return Ok(ProjectIdentity {
            key: project_key("git", &common)?,
            display_name: display_name(&root),
            database_path: root.join(".tang").join("tang.db"),
        });
    }
    Ok(ProjectIdentity {
        key: project_key("directory", &resolved)?,
        display_name: display_name(&resolved),
        database_path: resolved.join(".tang").join("tang.db"),
    })
}

fn project_key(kind: &str, path: &Path) -> Result<String> {
    let text = path
        .to_str()
        .ok_or_else(|| TangError::new("invalid-project", "project path is not valid UTF-8"))?;
    let digest = Sha256::digest(text.as_bytes());
    Ok(format!("{kind}:sha256:{digest:x}"))
}

fn display_name(path: &Path) -> String {
    let raw = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("unnamed-project");
    let cleaned: String = raw
        .chars()
        .map(|character| {
            if character.is_control() {
                '?'
            } else {
                character
            }
        })
        .collect();
    let trimmed = cleaned.trim();
    let name = if trimmed.is_empty() {
        "unnamed-project"
    } else {
        trimmed
    };
    name.chars().take(80).collect()
}

fn git_common_dir(directory: &Path) -> Option<PathBuf> {
    let mut command = Command::new("git");
    command
        .arg("-C")
        .arg(directory)
        .args(["rev-parse", "--path-format=absolute", "--git-common-dir"])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    for (key, _) in std::env::vars() {
        if key.to_ascii_uppercase().starts_with("GIT_") {
            command.env_remove(&key);
        }
    }
    let output = command.output().ok()?;
    if !output.status.success() {
        return None;
    }
    let value = String::from_utf8(output.stdout).ok()?;
    let value = value.trim();
    if value.is_empty() {
        return None;
    }
    let path = PathBuf::from(value).canonicalize().ok()?;
    path.is_dir().then_some(path)
}
