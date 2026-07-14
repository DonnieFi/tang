"""Deterministic project identity without exposing private paths for display."""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from unicodedata import category


class ProjectKind(StrEnum):
    GIT = "git"
    DIRECTORY = "directory"


class ProjectResolutionError(RuntimeError):
    """Project identity could not be determined without unsafe guessing."""


def _safe_display_name(value: str) -> str:
    cleaned = "".join(
        "?" if category(character).startswith("C") else character
        for character in value
    ).strip()
    return (cleaned or "unnamed-project")[:80]


@dataclass(frozen=True, slots=True)
class ProjectIdentity:
    """A comparable private identity plus a path-safe display label."""

    key: str
    kind: ProjectKind
    display_name: str
    identity_path: Path = field(repr=False)

    def __post_init__(self) -> None:
        if not self.key or not self.display_name or not self.identity_path.is_absolute():
            raise ValueError("project identity must be complete and absolute")


def _key(kind: ProjectKind, identity_path: Path) -> str:
    digest = hashlib.sha256(str(identity_path).encode("utf-8")).hexdigest()
    return f"{kind.value}:sha256:{digest}"


def _git_common_dir(directory: Path) -> Path | None:
    clean_environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("GIT_")
    }
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(directory),
                "rev-parse",
                "--path-format=absolute",
                "--git-common-dir",
            ],
            check=False,
            capture_output=True,
            text=True,
            env=clean_environment,
            timeout=5,
        )
    except subprocess.TimeoutExpired as error:
        raise ProjectResolutionError("Git project resolution timed out") from error
    except OSError as error:
        raise ProjectResolutionError("Git project resolution is unavailable") from error
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    if not value:
        return None
    common_dir = Path(value).resolve(strict=True)
    return common_dir if common_dir.is_dir() else None


def resolve_project(directory: Path | str) -> ProjectIdentity:
    """Resolve Git worktrees together and ordinary directories by real path."""

    resolved = Path(directory).expanduser().resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("project path must identify a directory")

    common_dir = _git_common_dir(resolved)
    if common_dir is not None:
        identity_path = common_dir
        repository_root = common_dir.parent if common_dir.name == ".git" else common_dir
        display_name = _safe_display_name(repository_root.name)
        kind = ProjectKind.GIT
    else:
        identity_path = resolved
        display_name = _safe_display_name(resolved.name)
        kind = ProjectKind.DIRECTORY

    return ProjectIdentity(
        key=_key(kind, identity_path),
        kind=kind,
        display_name=display_name,
        identity_path=identity_path,
    )
