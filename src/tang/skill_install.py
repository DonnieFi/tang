"""Safe installation of Tang's bundled Codex skill."""

from __future__ import annotations

import hashlib
import os
import shutil
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
    return module.parents[2] / "skills" / "tang"


def codex_skill_root(codex_home: Path | None = None) -> Path:
    configured = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    return configured.expanduser().resolve() / "skills"


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
