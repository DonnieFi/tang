from __future__ import annotations

from pathlib import Path

from tang.continuity_brief import build_continuity_brief
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


def test_continuity_brief_reports_recent_handles(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    database = repo_root / ".tang" / "tang.db"
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        project = resolve_project(repo_root)
        brief = build_continuity_brief(repository, project)
        assert brief.project_key == project.key
        assert brief.schema_version == 1
    finally:
        connection.close()
