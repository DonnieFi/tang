//! Project identity compatible with the existing per-project database path.

use crate::error::{Result, TangError};
use crate::redact::{redact, ContentKind};
use sha2::{Digest, Sha256};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

/// Where a session belongs. The key preserves the join boundary. The tag is the
/// redacted directory shown on the session.
pub struct SessionPlace {
    pub project_key: String,
    pub directory_tag: String,
}

pub fn place_session(hint: &str, fallback_key: &str) -> SessionPlace {
    let trimmed = hint.trim();
    if trimmed.is_empty() {
        return SessionPlace {
            project_key: fallback_key.to_string(),
            directory_tag: String::new(),
        };
    }
    let path = Path::new(trimmed);
    if path.is_dir() {
        if let Ok(identity) = resolve_project(path) {
            let root = identity
                .database_path
                .parent()
                .and_then(Path::parent)
                .map(Path::to_path_buf)
                .unwrap_or_else(|| path.to_path_buf());
            return SessionPlace {
                project_key: identity.key,
                directory_tag: redact(&root.to_string_lossy(), ContentKind::DisplayMetadata),
            };
        }
    }
    if trimmed.contains('/') || trimmed.contains('\\') {
        return SessionPlace {
            project_key: format!("directory:sha256:{:x}", Sha256::digest(trimmed.as_bytes())),
            directory_tag: redact(trimmed, ContentKind::DisplayMetadata),
        };
    }
    SessionPlace {
        project_key: fallback_key.to_string(),
        directory_tag: String::new(),
    }
}

pub struct ProjectIdentity {
    pub key: String,
    pub display_name: String,
    pub database_path: PathBuf,
}

pub fn owns_project(hint: &str, project: &ProjectIdentity) -> bool {
    let path = Path::new(hint);
    if !path.is_dir() {
        return false;
    }
    resolve_project(path)
        .map(|resolved| resolved.key == project.key)
        .unwrap_or(false)
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
