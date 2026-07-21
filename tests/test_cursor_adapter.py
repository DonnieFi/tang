from __future__ import annotations

from pathlib import Path

from tang.adapters import TurnSelection
from tang.adapters.cursor import CursorAdapter


def test_cursor_scan_and_read_fixture(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    slug = CursorAdapter._project_slug(project)
    transcript = (
        cursor_home
        / "projects"
        / slug
        / "agent-transcripts"
        / "fixture-session"
        / "fixture-session.jsonl"
    )
    transcript.parent.mkdir(parents=True)
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "cursor"
        / "agent-transcripts"
        / "fixture-session"
        / "fixture-session.jsonl"
    )
    transcript.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    adapter = CursorAdapter(project, cursor_home=cursor_home)
    batch = adapter.scan(None)
    assert batch.status.name == "COMPLETE"
    assert len(batch.records) == 1
    read = adapter.read(batch.records[0], TurnSelection())
    assert read.turns
    assert "indexer" in read.turns[0].text
