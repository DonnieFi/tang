from __future__ import annotations

import json
from pathlib import Path

from tang.adapters import TurnSelection
from tang.adapters.claude import ClaudeAdapter
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database

FIXTURE_SESSION = "019f6000-c1a0-7000-8000-000000000001"


def _layout_session(
    claude_home: Path,
    project: Path,
    native_id: str = FIXTURE_SESSION,
) -> Path:
    slug = ClaudeAdapter.project_slug(project)
    destination = claude_home / "projects" / slug / f"{native_id}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = (
        Path(__file__).parent
        / "fixtures"
        / "claude"
        / "projects"
        / "-opt-tang-fixture"
        / f"{FIXTURE_SESSION}.jsonl"
    )
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return destination


def test_claude_scan_and_read_fixture(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    claude_home = tmp_path / "claude"
    _layout_session(claude_home, project)

    adapter = ClaudeAdapter(project, claude_home=claude_home)
    batch = adapter.scan(None)
    assert batch.status.name == "COMPLETE"
    assert len(batch.records) == 1
    assert batch.records[0].title == "Indexer review fixture"

    read = adapter.read(batch.records[0], TurnSelection())
    assert read.turns
    assert "indexer" in read.turns[0].text.lower()
    assert read.turns[1].role.name == "AGENT"


def test_claude_project_slug_matches_live_encoding() -> None:
    assert ClaudeAdapter.project_slug(Path("/opt/family-bot")) == "-opt-family-bot"
    assert ClaudeAdapter.project_slug(Path("/home/red")) == "-home-red"


def test_claude_scan_is_incremental(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    claude_home = tmp_path / "claude"
    session_path = _layout_session(claude_home, project)
    adapter = ClaudeAdapter(project, claude_home=claude_home)

    first = adapter.scan(None)
    assert len(first.records) == 1
    second = adapter.scan(first.next_checkpoint)
    assert second.records == ()
    assert second.removed == ()

    payload = json.loads(session_path.read_text(encoding="utf-8").splitlines()[0])
    payload["timestamp"] = "2026-07-02T12:00:00.000Z"
    session_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    third = adapter.scan(second.next_checkpoint)
    assert len(third.records) == 1


def test_claude_indexes_into_project_database(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    claude_home = tmp_path / "claude"
    _layout_session(claude_home, project)
    database = tmp_path / "tang.db"

    adapter = ClaudeAdapter(project, claude_home=claude_home)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        result = ProjectIndexer(repository).index((adapter,), resolve_project(project))
    finally:
        connection.close()

    assert result.indexed == 1
    batch = adapter.scan(None)
    source_id = batch.records[0].identity.canonical
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        stored = repository.get_session(source_id)
    finally:
        connection.close()
    assert stored is not None
    assert stored.source.identity.adapter == "claude"


def test_claude_unavailable_without_project_dir(tmp_path: Path) -> None:
    project = (tmp_path / "missing-project").resolve()
    claude_home = tmp_path / "claude"
    adapter = ClaudeAdapter(project, claude_home=claude_home)
    batch = adapter.scan(None)
    assert batch.status.name == "UNAVAILABLE"
