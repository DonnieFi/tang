//! Copy Tang's bundled skill trees into a caller-supplied home directory.
//!
//! Destinations stay under `home`. Codex and Claude land at `home/skills/tang`.
//! OpenCode follows `skill_install.py`: files are placed under `home/.opencode`
//! at `skills/tang`, `commands/tang.md`, and the two Tang tools.

use crate::error::{Result, TangError};
use std::fs;
use std::path::{Component, Path, PathBuf};

pub fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..")
}

pub fn install_skill(repo_root: &Path, harness: &str, home: &Path, force: bool) -> Result<String> {
    ensure_real_directory(home)?;
    match harness {
        "codex" => install_tree(
            &repo_root.join("skills").join("tang"),
            &home.join("skills").join("tang"),
            home,
            force,
        ),
        "claude" => install_tree(
            &repo_root.join("skills").join("claude").join("tang"),
            &home.join("skills").join("tang"),
            home,
            force,
        ),
        "opencode" => install_opencode(repo_root, home, force),
        _ => Err(TangError::new(
            "invalid-harness",
            "Harness must be codex, claude, or opencode.",
        )),
    }
}

fn install_tree(source: &Path, destination: &Path, home: &Path, force: bool) -> Result<String> {
    require_skill_directory(source)?;
    prepare_destination(destination, home, force)?;
    copy_tree(source, destination)?;
    harden_installed_dirs(home, destination)?;
    utf8_path(destination)
}

fn install_opencode(repo_root: &Path, home: &Path, force: bool) -> Result<String> {
    let root = home.join(".opencode");
    let pairs = [
        (
            repo_root.join("skills").join("opencode").join("tang"),
            root.join("skills").join("tang"),
            true,
        ),
        (
            repo_root.join(".opencode").join("commands").join("tang.md"),
            root.join("commands").join("tang.md"),
            false,
        ),
        (
            repo_root
                .join(".opencode")
                .join("tools")
                .join("tang_current_target.ts"),
            root.join("tools").join("tang_current_target.ts"),
            false,
        ),
        (
            repo_root
                .join(".opencode")
                .join("tools")
                .join("tang_predecessor_context.ts"),
            root.join("tools").join("tang_predecessor_context.ts"),
            false,
        ),
    ];
    for (source, _destination, directory) in &pairs {
        if *directory {
            require_skill_directory(source)?;
        } else {
            require_file(source)?;
        }
    }
    for (_source, destination, _directory) in &pairs {
        ensure_inside(home, destination)?;
        reject_symlink_ancestors(home, destination)?;
        if occupied(destination) && !force {
            return Err(skill_exists());
        }
    }
    for (source, destination, directory) in &pairs {
        if occupied(destination) {
            remove_occupied(destination)?;
        }
        if *directory {
            copy_tree(source, destination)?;
        } else {
            copy_file(source, destination)?;
        }
        harden_installed_dirs(home, destination)?;
    }
    if !root.exists() {
        fs::create_dir_all(&root).map_err(skill_io)?;
    }
    harden_installed_dirs(home, &root)?;
    utf8_path(&root)
}

fn prepare_destination(destination: &Path, home: &Path, force: bool) -> Result<()> {
    ensure_inside(home, destination)?;
    reject_symlink_ancestors(home, destination)?;
    if is_symlink(destination) {
        return Err(symlink_refusal());
    }
    if occupied(destination) {
        if !force {
            return Err(skill_exists());
        }
        remove_occupied(destination)?;
    }
    Ok(())
}

fn require_skill_directory(source: &Path) -> Result<()> {
    if !is_symlink(source) && source.is_dir() && source.join("SKILL.md").is_file() {
        Ok(())
    } else {
        Err(TangError::new(
            "skill-missing",
            "The bundled Tang skill is unavailable.",
        ))
    }
}

fn require_file(source: &Path) -> Result<()> {
    if !is_symlink(source) && source.is_file() {
        Ok(())
    } else {
        Err(TangError::new(
            "skill-missing",
            "The bundled OpenCode Tang integration is unavailable.",
        ))
    }
}

fn copy_tree(source: &Path, destination: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(source).map_err(skill_io)?;
    if metadata.file_type().is_symlink() {
        return Err(TangError::new(
            "skill-unsafe",
            "Skill sources may not contain symlinks.",
        ));
    }
    if metadata.is_dir() {
        fs::create_dir_all(destination).map_err(skill_io)?;
        harden(destination, true)?;
        let mut entries = fs::read_dir(source)
            .map_err(skill_io)?
            .collect::<std::io::Result<Vec<_>>>()
            .map_err(skill_io)?;
        entries.sort_by_key(|entry| entry.file_name());
        for entry in entries {
            copy_tree(&entry.path(), &destination.join(entry.file_name()))?;
        }
        return Ok(());
    }
    if metadata.is_file() {
        copy_file(source, destination)?;
        return Ok(());
    }
    Err(TangError::new(
        "skill-missing",
        "The bundled Tang skill is unavailable.",
    ))
}

fn copy_file(source: &Path, destination: &Path) -> Result<()> {
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent).map_err(skill_io)?;
    }
    fs::copy(source, destination).map_err(skill_io)?;
    harden(destination, false)?;
    Ok(())
}

fn remove_occupied(path: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(path).map_err(skill_io)?;
    if metadata.file_type().is_symlink() {
        return Err(symlink_refusal());
    }
    if metadata.is_dir() {
        fs::remove_dir_all(path).map_err(skill_io)
    } else {
        fs::remove_file(path).map_err(skill_io)
    }
}

fn occupied(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok()
}

fn is_symlink(path: &Path) -> bool {
    fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false)
}

fn ensure_real_directory(home: &Path) -> Result<()> {
    let metadata = fs::symlink_metadata(home)
        .map_err(|_| TangError::new("skill-home", "The skill install directory is unavailable."))?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(TangError::new(
            "skill-unsafe",
            "Refusing to install into a symlinked skill directory.",
        ));
    }
    Ok(())
}

fn ensure_inside(home: &Path, destination: &Path) -> Result<()> {
    let home = normalize_lexical(home);
    let destination = normalize_lexical(destination);
    if destination.starts_with(&home) && destination != home {
        Ok(())
    } else {
        Err(TangError::new(
            "skill-unsafe",
            "Refusing to install outside the provided home.",
        ))
    }
}

fn reject_symlink_ancestors(home: &Path, destination: &Path) -> Result<()> {
    let mut current = destination.to_path_buf();
    while current.starts_with(home) && current != home {
        if is_symlink(&current) {
            return Err(symlink_refusal());
        }
        if !current.pop() {
            break;
        }
    }
    Ok(())
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

fn harden_installed_dirs(home: &Path, start: &Path) -> Result<()> {
    let mut current = if start.is_dir() {
        start.to_path_buf()
    } else {
        start.parent().unwrap_or(start).to_path_buf()
    };
    let mut chain = Vec::new();
    while current.starts_with(home) && current != home {
        chain.push(current.clone());
        if !current.pop() {
            break;
        }
    }
    for directory in chain.iter().rev() {
        if directory.is_dir() && !is_symlink(directory) {
            harden(directory, true)?;
        }
    }
    Ok(())
}

fn harden(path: &Path, directory: bool) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = if directory { 0o700 } else { 0o600 };
        fs::set_permissions(path, fs::Permissions::from_mode(mode)).map_err(skill_io)?;
    }
    #[cfg(not(unix))]
    {
        let _ = (path, directory);
    }
    Ok(())
}

fn utf8_path(path: &Path) -> Result<String> {
    path.to_str()
        .map(ToOwned::to_owned)
        .ok_or_else(|| TangError::new("skill-path", "The skill destination is not valid UTF-8."))
}

fn skill_exists() -> TangError {
    TangError::new("skill-exists", "The skill destination already exists.")
}

fn symlink_refusal() -> TangError {
    TangError::new(
        "skill-unsafe",
        "Refusing to replace a symlinked skill path.",
    )
}

fn skill_io(error: std::io::Error) -> TangError {
    TangError::new(
        "skill-copy",
        format!("The skill could not be copied ({:?}).", error.kind()),
    )
}
