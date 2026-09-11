from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from tang.adapters import TurnSelection
from tang.adapters.openclaw import OpenClawAdapter
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


def _build_fixture_db(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(destination)
    connection.executescript(
        """
        CREATE TABLE session_nodes (
          session_key TEXT PRIMARY KEY,
          display_name TEXT,
          label TEXT,
          created_at INTEGER,
          updated_at INTEGER,
          last_activity_at INTEGER
        );
        CREATE TABLE session_windows (
          session_id TEXT,
          session_key TEXT,
          started_at INTEGER,
          ended_at INTEGER,
          status TEXT,
          display_name TEXT
        );
        CREATE TABLE transcript_events (
          session_id TEXT,
          seq INTEGER,
          event_json TEXT,
          created_at INTEGER,
          PRIMARY KEY (session_id, seq)
        );
        """
    )
    connection.execute(
        "INSERT INTO session_nodes VALUES (?,?,?,?,?,?)",
        ("agent:main:main", "Main thread", None, 1000, 3000, 3000),
    )
    connection.execute(
        "INSERT INTO session_nodes VALUES (?,?,?,?,?,?)",
        ("agent:main:dashboard:fixture", "Tang naming review", None, 2000, 5000, 5000),
    )
    connection.executemany(
        "INSERT INTO session_windows VALUES (?,?,?,?,?,?)",
        [
            ("old-window", "agent:main:dashboard:fixture", 1000, 2000, "done", "old"),
            (
                "latest-window",
                "agent:main:dashboard:fixture",
                3000,
                5000,
                "done",
                "Tang naming review",
            ),
            ("main-window", "agent:main:main", 1000, 3000, "done", "Main thread"),
        ],
    )

    def msg(session_id: str, seq: int, role: str, text: str, parent: str | None) -> None:
        event = {
            "type": "message",
            "id": f"evt-{session_id}-{seq}",
            "parentId": parent,
            "timestamp": "2026-09-07T14:00:00.000Z",
            "message": {
                "role": role,
                "content": text,
                "timestamp": 1789000000000 + seq,
            },
        }
        connection.execute(
            "INSERT INTO transcript_events VALUES (?,?,?,?)",
            (session_id, seq, json.dumps(event), 1789000000000 + seq),
        )

    msg("main-window", 1, "user", "compare tang session naming", None)
    msg(
        "main-window",
        2,
        "assistant",
        "Tang uses short handles per adapter.",
        "evt-main-window-1",
    )
    msg("latest-window", 1, "user", "review openclaw vs tang naming", None)
    msg(
        "latest-window",
        2,
        "assistant",
        "OpenClaw keeps dashboard titles on session keys.",
        "evt-latest-window-1",
    )
    connection.commit()
    connection.close()


def _layout_openclaw(openclaw_home: Path) -> None:
    destination = (
        openclaw_home / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    )
    _build_fixture_db(destination)
    leftover = openclaw_home / "agents" / "main" / "sessions" / "stale.jsonl"
    leftover.parent.mkdir(parents=True, exist_ok=True)
    leftover.write_text('{"type":"message"}\n', encoding="utf-8")


def test_openclaw_encodes_colon_session_keys() -> None:
    session_key = "agent:main:dashboard:fixture"
    native_id = OpenClawAdapter.encode_native_id(session_key)
    assert ":" not in native_id
    assert OpenClawAdapter.decode_native_id(native_id) == session_key


def test_openclaw_scan_dedupes_session_keys(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    openclaw_home = tmp_path / "openclaw"
    _layout_openclaw(openclaw_home)

    adapter = OpenClawAdapter(project, openclaw_home=openclaw_home)
    batch = adapter.scan(None)
    assert batch.status.name == "COMPLETE"
    assert len(batch.records) == 2
    titles = {record.title for record in batch.records}
    assert "Tang naming review" in titles
    assert "Main thread" in titles
    for record in batch.records:
        assert ":" not in record.identity.native_id
        assert OpenClawAdapter.decode_native_id(record.identity.native_id)


def test_openclaw_read_fixture_transcript(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    openclaw_home = tmp_path / "openclaw"
    _layout_openclaw(openclaw_home)
    adapter = OpenClawAdapter(project, openclaw_home=openclaw_home)
    record = next(
        item for item in adapter.scan(None).records if item.title == "Main thread"
    )

    read = adapter.read(record, TurnSelection())
    assert read.status.name == "COMPLETE"
    assert len(read.turns) == 2
    assert "tang" in read.turns[0].text.lower()
    assert read.turns[1].role.name == "AGENT"


def test_openclaw_scan_is_incremental(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    openclaw_home = tmp_path / "openclaw"
    _layout_openclaw(openclaw_home)
    adapter = OpenClawAdapter(project, openclaw_home=openclaw_home)

    first = adapter.scan(None)
    second = adapter.scan(first.next_checkpoint)
    assert second.records == ()
    assert second.removed == ()

    db_path = (
        openclaw_home / "agents" / "main" / "agent" / "openclaw-agent.sqlite"
    )
    connection = sqlite3.connect(db_path)
    connection.execute(
        """
        INSERT INTO transcript_events (session_id, seq, event_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            "main-window",
            3,
            json.dumps(
                {
                    "type": "message",
                    "id": "evt-main-window-3",
                    "parentId": "evt-main-window-2",
                    "timestamp": "2026-09-07T14:05:00.000Z",
                    "message": {
                        "role": "user",
                        "content": "follow-up question",
                        "timestamp": 1789000000100,
                    },
                }
            ),
            1789000000100,
        ),
    )
    connection.commit()
    connection.close()

    third = adapter.scan(first.next_checkpoint)
    assert len(third.records) == 1


def test_openclaw_indexes_into_project_database(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    openclaw_home = tmp_path / "openclaw"
    _layout_openclaw(openclaw_home)
    database = tmp_path / "tang.db"

    adapter = OpenClawAdapter(project, openclaw_home=openclaw_home)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        result = ProjectIndexer(repository).index((adapter,), resolve_project(project))
    finally:
        connection.close()

    assert result.indexed == 2
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        handles = {
            row["session_handle"]
            for row in connection.execute(
                "SELECT session_handle FROM sessions WHERE adapter = 'openclaw'"
            )
        }
    finally:
        connection.close()
    assert handles == {"W1", "W2"}
