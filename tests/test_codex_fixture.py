from __future__ import annotations

import json
from pathlib import Path


SYNTHETIC_SESSION_ID = "019f6000-5678-7000-8000-000000000002"


def test_codex_fixture_is_deterministic_representative_jsonl(
    codex_fixture_log: Path,
) -> None:
    rows = [json.loads(line) for line in codex_fixture_log.read_text().splitlines()]

    assert codex_fixture_log.name.endswith(f"-{SYNTHETIC_SESSION_ID}.jsonl")
    assert {row["type"] for row in rows} >= {
        "session_meta",
        "turn_context",
        "response_item",
        "event_msg",
    }
    metadata = rows[0]["payload"]
    assert metadata["id"] == metadata["session_id"] == SYNTHETIC_SESSION_ID
    assert metadata["cli_version"] == "0.144.4"
    assert metadata["cwd"] == "/work/tang-demo"
    assert metadata["git"]["repository_url"].startswith("https://example.invalid/")

    visible_roles = [
        row["payload"]["role"]
        for row in rows
        if row["type"] == "response_item"
        and row["payload"].get("type") == "message"
    ]
    terminal_events = [
        row
        for row in rows
        if row["type"] == "event_msg"
        and row["payload"].get("type") == "task_complete"
    ]
    assert visible_roles == ["user", "assistant", "user", "assistant"]
    assert len(terminal_events) == 1
    assert all(row["timestamp"].endswith("Z") for row in rows)


def test_fixture_copy_is_isolated_and_mutable(
    codex_fixture_home: Path, copied_codex_home: Path
) -> None:
    copied_log = next((copied_codex_home / "sessions").rglob("*.jsonl"))
    copied_log.write_text(copied_log.read_text() + "\n")

    original_log = next((codex_fixture_home / "sessions").rglob("*.jsonl"))
    assert not original_log.read_text().endswith("\n\n")
