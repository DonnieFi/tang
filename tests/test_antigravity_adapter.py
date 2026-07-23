from __future__ import annotations

import json
from pathlib import Path

from tang.adapters import TurnSelection
from tang.adapters.antigravity import AntigravityAdapter
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database

FIXTURE_SESSION = "019f6000-a017-7000-8000-000000000001"
FIXTURE_PROJECT = "/tmp/tang-fixture-project"


def _layout_antigravity(antigravity_home: Path, project: Path) -> None:
    antigravity_home.mkdir(parents=True, exist_ok=True)
    fixture_root = Path(__file__).parent / "fixtures" / "antigravity"
    (antigravity_home / "history.jsonl").write_text(
        json.dumps(
            {
                "display": "Confirm branch for release",
                "timestamp": 1784570653707,
                "workspace": str(project.resolve()),
                "conversationId": FIXTURE_SESSION,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    transcript_src = (
        fixture_root
        / "brain"
        / FIXTURE_SESSION
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )
    transcript_dest = (
        antigravity_home
        / "brain"
        / FIXTURE_SESSION
        / ".system_generated"
        / "logs"
        / "transcript.jsonl"
    )
    transcript_dest.parent.mkdir(parents=True, exist_ok=True)
    transcript_dest.write_text(
        transcript_src.read_text(encoding="utf-8"), encoding="utf-8"
    )


def test_antigravity_scan_and_read_fixture(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    antigravity_home = tmp_path / "antigravity"
    _layout_antigravity(antigravity_home, project)

    adapter = AntigravityAdapter(project, antigravity_home=antigravity_home)
    batch = adapter.scan(None)
    assert batch.status.name == "COMPLETE"
    assert len(batch.records) == 1
    assert batch.records[0].title == "Confirm branch for release"

    read = adapter.read(batch.records[0], TurnSelection())
    assert read.turns
    assert "branch" in read.turns[0].text.lower()
    assert "epic/11" in read.turns[1].text


def test_antigravity_scan_is_incremental(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    antigravity_home = tmp_path / "antigravity"
    _layout_antigravity(antigravity_home, project)
    adapter = AntigravityAdapter(project, antigravity_home=antigravity_home)

    first = adapter.scan(None)
    second = adapter.scan(first.next_checkpoint)
    assert second.records == ()


def test_antigravity_indexes_into_project_database(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    antigravity_home = tmp_path / "antigravity"
    _layout_antigravity(antigravity_home, project)
    database = tmp_path / "tang.db"

    adapter = AntigravityAdapter(project, antigravity_home=antigravity_home)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        result = ProjectIndexer(repository).index((adapter,), resolve_project(project))
    finally:
        connection.close()

    assert result.indexed == 1


def test_antigravity_skips_history_without_transcript(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    antigravity_home = tmp_path / "antigravity"
    antigravity_home.mkdir()
    (antigravity_home / "history.jsonl").write_text(
        json.dumps(
            {
                "display": "Missing transcript",
                "timestamp": 1784570653707,
                "workspace": str(project.resolve()),
                "conversationId": "00000000-0000-4000-8000-000000000099",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    adapter = AntigravityAdapter(project, antigravity_home=antigravity_home)
    batch = adapter.scan(None)
    assert batch.status.name == "UNAVAILABLE"
    assert batch.records == ()
