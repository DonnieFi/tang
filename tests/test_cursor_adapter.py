from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tang.adapters import TurnSelection
from tang.adapters.cursor import CursorAdapter
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


def _layout_session(
    cursor_home: Path,
    project: Path,
    native_id: str,
    *,
    jsonl_name: str = "fixture-session.jsonl",
    with_meta: bool = False,
    with_store: bool = False,
) -> Path:
    slug = CursorAdapter._project_slug(project)
    jsonl = (
        cursor_home
        / "projects"
        / slug
        / "agent-transcripts"
        / native_id
        / f"{native_id}.jsonl"
    )
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    fixture = (
        Path(__file__).parent
        / "fixtures"
        / "cursor"
        / "agent-transcripts"
        / jsonl_name.replace(".jsonl", "")
        / jsonl_name
    )
    if not fixture.is_file():
        fixture = (
            Path(__file__).parent
            / "fixtures"
            / "cursor"
            / "agent-transcripts"
            / native_id
            / jsonl_name
        )
    jsonl.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")

    if not (with_meta or with_store):
        return jsonl

    chat_dir = (
        cursor_home
        / "chats"
        / CursorAdapter.workspace_chat_hash(project)
        / native_id
    )
    chat_dir.mkdir(parents=True)
    if with_meta:
        meta_fixture = (
            Path(__file__).parent
            / "fixtures"
            / "cursor"
            / "chats"
            / "ws-placeholder"
            / "fixture-session"
            / "meta.json"
        )
        (chat_dir / "meta.json").write_text(
            meta_fixture.read_text(encoding="utf-8"), encoding="utf-8"
        )
    if with_store:
        meta = {
            "agentId": native_id,
            "name": "Store-backed title",
            "lastUsedModel": "composer-2.5",
            "mode": "agent",
            "createdAt": 1784570653707,
        }
        encoded = json.dumps(meta, sort_keys=True).encode("utf-8")
        db_path = chat_dir / "store.db"
        connection = sqlite3.connect(db_path)
        connection.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
        connection.execute(
            "CREATE TABLE blobs (id TEXT PRIMARY KEY, data BLOB)"
        )
        connection.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            ("0", encoded.hex()),
        )
        connection.commit()
        connection.close()
    return jsonl


def test_cursor_scan_and_read_fixture(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(cursor_home, project, "fixture-session")

    adapter = CursorAdapter(project, cursor_home=cursor_home)
    batch = adapter.scan(None)
    assert batch.status.name == "COMPLETE"
    assert len(batch.records) == 1
    read = adapter.read(batch.records[0], TurnSelection())
    assert read.turns
    assert "indexer" in read.turns[0].text


def test_cursor_scan_uses_meta_json_title_and_timestamps(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(
        cursor_home, project, "fixture-session", with_meta=True
    )

    record = CursorAdapter(project, cursor_home=cursor_home).scan(None).records[0]

    assert record.title == "Fixture Cursor session title"
    assert record.started_at == datetime(2026, 7, 20, 18, 4, 13, 707000, tzinfo=timezone.utc)
    assert record.updated_at == datetime(2026, 7, 20, 18, 4, 20, tzinfo=timezone.utc)


def test_cursor_scan_merges_store_db_model_and_mode(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(
        cursor_home, project, "fixture-session", with_meta=True, with_store=True
    )

    record = CursorAdapter(project, cursor_home=cursor_home).scan(None).records[0]

    assert record.title == "Fixture Cursor session title"
    assert record.header.model_id == "composer-2.5"
    assert record.header.effort == "agent"


def test_cursor_read_extracts_task_model_into_header(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(
        cursor_home,
        project,
        "task-model-session",
        jsonl_name="task-model-session.jsonl",
    )

    adapter = CursorAdapter(project, cursor_home=cursor_home)
    record = adapter.scan(None).records[0]
    read = adapter.read(record, TurnSelection())

    assert read.header.model_id == "claude-sonnet-5-thinking-high"


def test_cursor_fingerprint_includes_sidecars(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(cursor_home, project, "fixture-session")
    adapter = CursorAdapter(project, cursor_home=cursor_home)
    first = adapter.scan(None).records[0].fingerprint.value

    _layout_session(
        cursor_home, project, "fixture-session", with_meta=True
    )
    second = adapter.scan(None).records[0].fingerprint.value

    assert first != second


def test_cursor_indexing_surfaces_session_header_in_capsule(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(
        cursor_home,
        project,
        "fixture-session",
        with_meta=True,
        with_store=True,
    )
    adapter = CursorAdapter(project, cursor_home=cursor_home)
    database = project / ".tang" / "tang.db"
    connection = open_database(database)
    repository = TangRepository(connection)
    project_identity = resolve_project(project)
    indexed = ProjectIndexer(repository).index((adapter,), project_identity)
    assert indexed.indexed == 1
    row = repository.search_discovery(project_identity.key, "Fixture", limit=5)[0]
    assert row.title == "Fixture Cursor session title"
    assert row.model_id == "composer-2.5"
    assert row.effort == "agent"
    capsule = repository.get_capsule(row.source_id)
    assert capsule is not None
    header = capsule.content["session_header"]
    assert header["model_id"] == "composer-2.5"
    assert header["title_origin"] == "native"
    connection.close()


def test_workspace_chat_hash_matches_cursor_layout() -> None:
    project = Path("/opt/tang")
    assert CursorAdapter.workspace_chat_hash(project) == hashlib.md5(
        b"/opt/tang"
    ).hexdigest()


def test_cursor_scan_reports_removed_sessions(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(cursor_home, project, "fixture-session")
    _layout_session(
        cursor_home,
        project,
        "task-model-session",
        jsonl_name="task-model-session.jsonl",
    )

    adapter = CursorAdapter(project, cursor_home=cursor_home)
    first = adapter.scan(None)
    assert len(first.records) == 2
    assert first.next_checkpoint is not None

    # Delete one native transcript directory; the next incremental scan must
    # emit a removal rather than leaving a stale checkpoint fingerprint.
    gone = (
        cursor_home
        / "projects"
        / CursorAdapter._project_slug(project)
        / "agent-transcripts"
        / "task-model-session"
    )
    for path in sorted(gone.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
        else:
            path.rmdir()
    gone.rmdir()

    second = adapter.scan(first.next_checkpoint)
    assert len(second.records) == 0
    assert len(second.removed) == 1
    assert second.removed[0].native_id == "task-model-session"
    assert second.next_checkpoint is not None
    assert second.next_checkpoint != first.next_checkpoint

    third = adapter.scan(second.next_checkpoint)
    assert third.records == ()
    assert third.removed == ()


def test_cursor_read_citation_uses_file_line_number(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    jsonl = _layout_session(cursor_home, project, "fixture-session")
    adapter = CursorAdapter(project, cursor_home=cursor_home)
    record = adapter.scan(None).records[0]
    read = adapter.read(record, TurnSelection())
    assert read.turns
    # Fixture line 1 is the first user turn; citation must match file lines.
    first_line = jsonl.read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(first_line)["role"] == "user"
    assert read.turns[0].citation_locator == "line:1"


def test_cursor_scan_retains_checkpoint_when_session_unreadable(
    tmp_path: Path,
) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(cursor_home, project, "fixture-session")
    adapter = CursorAdapter(project, cursor_home=cursor_home)
    first = adapter.scan(None)
    assert first.next_checkpoint is not None
    prior_fp = json.loads(first.next_checkpoint.cursor)["fingerprints"]

    jsonl = (
        cursor_home
        / "projects"
        / CursorAdapter._project_slug(project)
        / "agent-transcripts"
        / "fixture-session"
        / "fixture-session.jsonl"
    )
    jsonl.chmod(0o000)
    try:
        second = adapter.scan(first.next_checkpoint)
    finally:
        jsonl.chmod(0o644)

    assert second.removed == ()
    assert second.next_checkpoint is None
    assert any(
        warning.code == "session-checkpoint-retained" for warning in second.warnings
    )
    assert json.loads(first.next_checkpoint.cursor)["fingerprints"] == prior_fp


def test_cursor_scan_enumerate_oserror_does_not_require_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(cursor_home, project, "fixture-session")
    trap = (
        cursor_home
        / "projects"
        / CursorAdapter._project_slug(project)
        / "agent-transcripts"
        / "trap-session"
    )
    trap.mkdir()
    (trap / "trap-session.jsonl").write_text("{}", encoding="utf-8")

    original_is_dir = Path.is_dir

    def is_dir(self: Path) -> bool:
        if self.name == "trap-session":
            raise OSError("simulated enumerate failure")
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    batch = CursorAdapter(project, cursor_home=cursor_home).scan(None)
    skipped = [
        warning
        for warning in batch.warnings
        if warning.code == "cursor-session-enumerate-skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0].identity is None
    assert len(batch.records) == 1


def test_index_cli_honors_cursor_home(tmp_path: Path, capsys) -> None:
    from tang.cli import main

    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    _layout_session(cursor_home, project, "fixture-session")

    result = main(
        [
            "index",
            "--json",
            "--cwd",
            str(project),
            "--cursor-home",
            str(cursor_home),
        ]
    )
    assert result in {0, 1}
    payload = json.loads(capsys.readouterr().out)
    assert payload["indexed"] == 1
    connection = open_database(project / ".tang" / "tang.db")
    try:
        row = connection.execute(
            "SELECT adapter FROM sessions LIMIT 1"
        ).fetchone()
        assert row is not None and row[0] == "cursor"
    finally:
        connection.close()
