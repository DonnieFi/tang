"""Safe installation of Tang's bundled Codex skill."""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SkillInstallResult:
    status: str
    destination: Path
    message: str


def bundled_skill_path() -> Path:
    """Return the source-tree or installed-package Tang skill directory."""

    module = Path(__file__).resolve()
    packaged = module.parent / "skills" / "tang"
    if packaged.is_dir():
        return packaged
    installed_data = Path(sys.prefix) / "share" / "tang" / "skills" / "tang"
    if installed_data.is_dir():
        return installed_data
    return module.parents[2] / "skills" / "tang"


def bundled_claude_skill_path() -> Path:
    """Return the bundled Claude Code skill directory."""

    module = Path(__file__).resolve()
    packaged = module.parent / "skills" / "claude" / "tang"
    if packaged.is_dir():
        return packaged
    installed_data = Path(sys.prefix) / "share" / "tang" / "skills" / "claude" / "tang"
    if installed_data.is_dir():
        return installed_data
    return module.parents[2] / "skills" / "claude" / "tang"


def codex_skill_root(codex_home: Path | None = None) -> Path:
    configured = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return configured.expanduser().resolve() / "skills"


def claude_skill_root(claude_home: Path | None = None) -> Path:
    configured = claude_home or Path(
        os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")
    )
    return configured.expanduser().resolve() / "skills"


def bundled_opencode_paths() -> tuple[tuple[Path, Path], ...]:
    """Return bundled OpenCode origins paired with install-relative paths."""

    development = Path(__file__).resolve().parents[2]
    if (development / "skills" / "opencode" / "tang" / "SKILL.md").is_file():
        return (
            (development / "skills" / "opencode" / "tang", Path("skills/tang")),
            (
                development / ".opencode" / "commands" / "tang.md",
                Path("commands/tang.md"),
            ),
            (
                development / ".opencode" / "tools" / "tang_current_target.ts",
                Path("tools/tang_current_target.ts"),
            ),
            (
                development / ".opencode" / "tools" / "tang_predecessor_context.ts",
                Path("tools/tang_predecessor_context.ts"),
            ),
        )
    installed = Path(sys.prefix) / "share" / "tang" / "opencode"
    return (
        (installed / "skills" / "tang", Path("skills/tang")),
        (installed / "commands" / "tang.md", Path("commands/tang.md")),
        (
            installed / "tools" / "tang_current_target.ts",
            Path("tools/tang_current_target.ts"),
        ),
        (
            installed / "tools" / "tang_predecessor_context.ts",
            Path("tools/tang_predecessor_context.ts"),
        ),
    )


def install_opencode_skill(
    project_root: Path,
    *,
    force: bool = False,
    sources: tuple[tuple[Path, Path], ...] | None = None,
) -> SkillInstallResult:
    """Install OpenCode skill assets atomically and preserve unrelated config."""

    bundle = sources or bundled_opencode_paths()
    if any(not origin.exists() for origin, _relative in bundle):
        raise FileNotFoundError("the bundled OpenCode Tang integration is unavailable")
    for origin, _relative in bundle:
        _reject_symlinks(origin)
    root = project_root.expanduser().resolve(strict=True)
    destination = root / ".opencode"
    if destination.is_symlink():
        raise OSError("refusing to install into a symlinked OpenCode directory")
    destination.mkdir(mode=0o700, exist_ok=True)

    targets = tuple(
        (origin.resolve(), destination / relative) for origin, relative in bundle
    )
    for _origin, target in targets:
        parent = target.parent
        while parent != destination:
            if parent.is_symlink():
                raise OSError("OpenCode integration parents may not be symlinks")
            parent = parent.parent
        if target.is_symlink():
            raise OSError("OpenCode integration destinations may not be symlinks")

    matching = tuple(_same_content(origin, target) for origin, target in targets)
    if all(matching):
        for _origin, target in targets:
            _harden_target(target)
        return SkillInstallResult(
            "unchanged",
            destination,
            "Tang OpenCode integration is already current; restart OpenCode with tang on PATH.",
        )
    if not force and any(
        target.exists() and not matches
        for (_origin, target), matches in zip(targets, matching, strict=True)
    ):
        raise FileExistsError(
            "the installed OpenCode Tang integration differs; rerun with --force"
        )

    temporary = Path(tempfile.mkdtemp(prefix=".tang-opencode-", dir=root))
    staged = temporary / "staged"
    backups = temporary / "backups"
    installed_targets: list[Path] = []
    moved_backups: list[tuple[Path, Path]] = []
    try:
        for origin, target in targets:
            relative = target.relative_to(destination)
            staged_target = staged / relative
            staged_target.parent.mkdir(parents=True, exist_ok=True)
            if origin.is_dir():
                shutil.copytree(origin, staged_target)
            else:
                shutil.copy2(origin, staged_target)
        for _origin, target in targets:
            relative = target.relative_to(destination)
            staged_target = staged / relative
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if target.exists():
                backup = backups / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                target.rename(backup)
                moved_backups.append((backup, target))
            staged_target.rename(target)
            installed_targets.append(target)
            _harden_target(target)
    except BaseException:
        for target in reversed(installed_targets):
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
        for backup, target in reversed(moved_backups):
            target.parent.mkdir(parents=True, exist_ok=True)
            backup.rename(target)
        raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return SkillInstallResult(
        "installed",
        destination,
        "Tang OpenCode integration installed; start OpenCode with tang on PATH.",
    )


def install_codex_skill(
    codex_home: Path | None = None,
    *,
    force: bool = False,
    source: Path | None = None,
) -> SkillInstallResult:
    """Install atomically, refusing divergent content unless force is explicit."""

    bundle = (source or bundled_skill_path()).resolve()
    if not bundle.is_dir() or not (bundle / "SKILL.md").is_file():
        raise FileNotFoundError("the bundled Tang skill is unavailable")

    root = codex_skill_root(codex_home)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = root / "tang"
    if destination.is_symlink():
        raise OSError("refusing to replace a symlinked Tang skill")
    if destination.exists():
        if not destination.is_dir():
            raise OSError("the Tang skill destination is not a directory")
        if _tree_digest(destination) == _tree_digest(bundle):
            return SkillInstallResult("unchanged", destination, "Tang Codex skill is already current.")
        if not force:
            raise FileExistsError(
                "the installed Tang skill differs; rerun with --force to replace it"
            )

    temporary = Path(tempfile.mkdtemp(prefix=".tang-skill-", dir=root))
    staged = temporary / "tang"
    try:
        shutil.copytree(bundle, staged)
        if destination.exists():
            backup = temporary / "previous"
            destination.rename(backup)
            try:
                staged.rename(destination)
            except BaseException:
                backup.rename(destination)
                raise
        else:
            staged.rename(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return SkillInstallResult("installed", destination, "Tang Codex skill installed.")


def install_claude_skill(
    claude_home: Path | None = None,
    *,
    force: bool = False,
    source: Path | None = None,
) -> SkillInstallResult:
    """Install the bundled Claude Code skill into ~/.claude/skills/tang."""

    bundle = (source or bundled_claude_skill_path()).resolve()
    if not bundle.is_dir() or not (bundle / "SKILL.md").is_file():
        raise FileNotFoundError("the bundled Claude Tang skill is unavailable")

    root = claude_skill_root(claude_home)
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = root / "tang"
    if destination.is_symlink():
        raise OSError("refusing to replace a symlinked Tang skill")
    if destination.exists():
        if not destination.is_dir():
            raise OSError("the Tang skill destination is not a directory")
        if _tree_digest(destination) == _tree_digest(bundle):
            return SkillInstallResult(
                "unchanged",
                destination,
                "Tang Claude Code skill is already current.",
            )
        if not force:
            raise FileExistsError(
                "the installed Tang skill differs; rerun with --force to replace it"
            )

    temporary = Path(tempfile.mkdtemp(prefix=".tang-claude-skill-", dir=root))
    staged = temporary / "tang"
    try:
        shutil.copytree(bundle, staged)
        if destination.exists():
            backup = temporary / "previous"
            destination.rename(backup)
            try:
                staged.rename(destination)
            except BaseException:
                backup.rename(destination)
                raise
        else:
            staged.rename(destination)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return SkillInstallResult(
        "installed",
        destination,
        "Tang Claude Code skill installed.",
    )


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        if path.is_symlink():
            raise OSError("skill directories may not contain symlinks")
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _same_content(origin: Path, target: Path) -> bool:
    if origin.is_dir():
        return target.is_dir() and _tree_digest(origin) == _tree_digest(target)
    return target.is_file() and origin.read_bytes() == target.read_bytes()


def _harden_target(target: Path) -> None:
    """Apply user-only modes to Tang-owned installed assets where supported."""

    if os.name != "posix":
        return
    if target.is_dir():
        target.chmod(0o700)
        for path in target.rglob("*"):
            path.chmod(0o700 if path.is_dir() else 0o600)
    else:
        target.chmod(0o600)


def _reject_symlinks(origin: Path) -> None:
    """Reject symlinks in bundled assets before following or copying them."""

    if origin.is_symlink():
        raise OSError("OpenCode integration sources may not be symlinks")
    if origin.is_dir():
        for path in origin.rglob("*"):
            if path.is_symlink():
                raise OSError("OpenCode integration sources may not contain symlinks")
