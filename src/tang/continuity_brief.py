"""Read-only session-start continuity signals (git + indexed metadata)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from tang.project import ProjectIdentity
from tang.repository import TangRepository


@dataclass(frozen=True, slots=True)
class ContinuityBrief:
    project_key: str
    git_available: bool
    git_log: tuple[str, ...]
    git_status: tuple[str, ...]
    recent_handles: tuple[str, ...]
    schema_version: int = 1

    def as_dict(self) -> dict[str, object]:
        return {
            "git_available": self.git_available,
            "git_log": list(self.git_log),
            "git_status": list(self.git_status),
            "project_key": self.project_key,
            "recent_handles": list(self.recent_handles),
            "schema_version": self.schema_version,
        }


def build_continuity_brief(
    repository: TangRepository, project: ProjectIdentity
) -> ContinuityBrief:
    git_log: tuple[str, ...] = ()
    git_status: tuple[str, ...] = ()
    git_available = False
    try:
        root = str(project.root_path)
        log = subprocess.run(
            ["git", "-C", root, "log", "-5", "--oneline"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "-C", root, "status", "--short"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if log.returncode == 0:
            git_available = True
            git_log = tuple(line for line in log.stdout.splitlines() if line.strip())
        if status.returncode == 0 and git_available:
            git_status = tuple(
                line for line in status.stdout.splitlines() if line.strip()
            )
    except (OSError, subprocess.TimeoutExpired):
        git_available = False

    rows = repository.browse_discovery(project.key, limit=5)
    recent = tuple(row.handle for row in rows)

    return ContinuityBrief(
        project_key=project.key,
        git_available=git_available,
        git_log=git_log,
        git_status=git_status,
        recent_handles=recent,
    )
