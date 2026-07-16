from __future__ import annotations

import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from tang.adapters import (
    AdapterCheckpoint,
    BatchStatus,
    GrokAdapter,
    SourceFingerprint,
    TurnRole,
    TurnSelection,
)


FIXTURE_HOME = Path(__file__).parent / "fixtures" / "grok"
SESSION_ID = "019f6000-1234-7000-8000-000000000001"


@pytest.fixture
def fixture_home(tmp_path: Path) -> Path:
    target = tmp_path / "grok-home"
    shutil.copytree(FIXTURE_HOME, target)
    return target


def test_scan_and_read_synthetic_verified_shape(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")

    scanned = adapter.scan(None)
    assert scanned.status is BatchStatus.COMPLETE
    assert len(scanned.records) == 1
    record = scanned.records[0]
    assert record.identity.canonical == f"grok:fixture:{SESSION_ID}"
    assert record.project_hint == "/work/tang-demo"
    assert record.title == "Design the cache boundary"

    read = adapter.read(record, TurnSelection())
    assert read.status is BatchStatus.COMPLETE
    assert [turn.role for turn in read.turns] == [TurnRole.USER, TurnRole.AGENT]
    assert [turn.ordinal for turn in read.turns] == [0, 1]
    assert [turn.citation_locator for turn in read.turns] == [
        "updates.jsonl:1",
        "updates.jsonl:6",
    ]
    assert all(turn.timestamp is not None for turn in read.turns)
    visible_text = "\n".join(turn.text for turn in read.turns)
    assert "HIDDEN_THOUGHT_CANARY" not in visible_text
    assert "TOOL_INPUT_CANARY" not in visible_text
    assert "FILE_BODY_CANARY" not in visible_text
    assert "UNKNOWN_METHOD_CANARY" not in visible_text


def test_repeated_scan_honors_opaque_checkpoint(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")

    first = adapter.scan(None)
    second = adapter.scan(first.next_checkpoint)

    assert first.records
    assert second.status is BatchStatus.COMPLETE
    assert second.records == ()
    assert second.next_checkpoint == first.next_checkpoint


def test_unchanged_valid_session_skips_the_redundant_metadata_parse(
    fixture_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    first = adapter.scan(None)
    calls = 0
    original = adapter._source_record

    def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(adapter, "_source_record", counted)
    second = adapter.scan(first.next_checkpoint)

    assert second.records == ()
    assert calls == 0


def test_legacy_checkpoint_is_revalidated_once_before_fast_skipping(
    fixture_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    first = adapter.scan(None)
    payload = json.loads(first.next_checkpoint.cursor)
    legacy = AdapterCheckpoint(
        "grok",
        "fixture",
        json.dumps({"schema_version": 1, "fingerprints": payload["fingerprints"]}),
    )
    calls = 0
    original = adapter._source_record

    def counted(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(adapter, "_source_record", counted)
    upgraded = adapter.scan(legacy)

    assert upgraded.records == ()
    assert calls == 1
    assert json.loads(upgraded.next_checkpoint.cursor)["schema_version"] == 2


def test_scan_is_stable_and_read_only(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    before = {
        path.relative_to(fixture_home): path.read_bytes()
        for path in fixture_home.rglob("*")
        if path.is_file()
    }

    first = adapter.scan(None)
    second = adapter.scan(None)
    adapter.read(first.records[0], TurnSelection())
    after = {
        path.relative_to(fixture_home): path.read_bytes()
        for path in fixture_home.rglob("*")
        if path.is_file()
    }

    assert first.records == second.records
    assert before == after


def test_malformed_summary_emits_partial_record(fixture_home: Path) -> None:
    summary = next((fixture_home / "sessions").rglob("summary.json"))
    summary.write_text("{broken", encoding="utf-8")
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")

    scanned = adapter.scan(None)

    assert scanned.status is BatchStatus.PARTIAL
    assert len(scanned.records) == 1
    assert {warning.code for warning in scanned.warnings} >= {
        "malformed-summary",
        "created-at-drift",
        "updated-at-drift",
    }


def test_truncated_update_keeps_valid_visible_turns(fixture_home: Path) -> None:
    updates = next((fixture_home / "sessions").rglob("updates.jsonl"))
    with updates.open("a", encoding="utf-8") as stream:
        stream.write('{"truncated":')
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert len(read.turns) == 2
    assert "truncated-update" in {warning.code for warning in read.warnings}


def test_schema_drift_skips_only_the_unsupported_visible_turn(
    fixture_home: Path,
) -> None:
    updates = next((fixture_home / "sessions").rglob("updates.jsonl"))
    drifted = {
        "method": "session/update",
        "params": {
            "sessionId": SESSION_ID,
            "update": {
                "sessionUpdate": "user_message_chunk",
                "content": {"type": "future-rich-content", "parts": []},
            },
        },
        "timestamp": 1784059250,
    }
    with updates.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(drifted) + "\n")
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert len(read.turns) == 2
    assert "visible-turn-schema-drift" in {
        warning.code for warning in read.warnings
    }


def test_missing_source_is_unavailable(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]
    shutil.rmtree(Path(record.locator.value))

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.UNAVAILABLE
    assert read.turns == ()
    assert [warning.code for warning in read.warnings] == ["missing-source"]


def test_changed_source_is_reread_with_warning(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]
    updates = Path(record.locator.value) / "updates.jsonl"
    with updates.open("a", encoding="utf-8") as stream:
        stream.write("\n")

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert len(read.turns) == 2
    assert "source-changed" in {warning.code for warning in read.warnings}


def test_invalid_and_foreign_checkpoints_trigger_full_partial_scan(
    fixture_home: Path,
) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    invalid = AdapterCheckpoint("grok", "fixture", "not-json")
    foreign = AdapterCheckpoint("grok", "another-store", "not-json")

    invalid_result = adapter.scan(invalid)
    foreign_result = adapter.scan(foreign)

    assert len(invalid_result.records) == 1
    assert invalid_result.status is BatchStatus.PARTIAL
    assert [warning.code for warning in invalid_result.warnings] == [
        "checkpoint-invalid"
    ]
    assert len(foreign_result.records) == 1
    assert foreign_result.status is BatchStatus.PARTIAL
    assert [warning.code for warning in foreign_result.warnings] == [
        "checkpoint-scope"
    ]


def test_store_namespace_is_stable_and_separates_profiles(tmp_path: Path) -> None:
    first_home = tmp_path / "profile-a"
    second_home = tmp_path / "profile-b"

    first = GrokAdapter(first_home)
    first_again = GrokAdapter(first_home)
    second = GrokAdapter(second_home)

    assert first.source_namespace == first_again.source_namespace
    assert first.source_namespace != second.source_namespace


def test_symlinked_session_group_is_skipped_without_following(
    fixture_home: Path, tmp_path: Path
) -> None:
    external_group = tmp_path / "external-group"
    external_session = external_group / "019f6000-1234-7000-8000-000000000099"
    external_session.mkdir(parents=True)
    (external_session / "summary.json").write_text(
        '{"created_at":"2026-07-14T20:00:00Z","updated_at":"2026-07-14T20:01:00Z","git_root_dir":"/outside"}',
        encoding="utf-8",
    )
    (external_session / "updates.jsonl").write_text(
        "OUTSIDE_STORE_CANARY", encoding="utf-8"
    )
    (fixture_home / "sessions" / "%2Foutside").symlink_to(
        external_group, target_is_directory=True
    )
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")

    scanned = adapter.scan(None)

    assert scanned.status is BatchStatus.PARTIAL
    assert len(scanned.records) == 1
    assert "unsafe-session-group" in {warning.code for warning in scanned.warnings}


def test_symlinked_native_file_is_not_read(fixture_home: Path, tmp_path: Path) -> None:
    summary = next((fixture_home / "sessions").rglob("summary.json"))
    external = tmp_path / "external-summary.json"
    external.write_text(
        '{"generated_title":"OUTSIDE_FILE_CANARY"}', encoding="utf-8"
    )
    summary.unlink()
    summary.symlink_to(external)
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")

    scanned = adapter.scan(None)

    assert scanned.status is BatchStatus.PARTIAL
    assert scanned.records == ()
    assert "unsafe-session-source" in {
        warning.code for warning in scanned.warnings
    }


def test_unreadable_group_does_not_discard_other_records(
    fixture_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unreadable = fixture_home / "sessions" / "%2Funreadable"
    unreadable.mkdir()
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    original_children = adapter._children

    def controlled_children(directory: Path) -> tuple[Path, ...]:
        if directory == unreadable:
            raise PermissionError("synthetic unreadable group")
        return original_children(directory)

    monkeypatch.setattr(adapter, "_children", controlled_children)

    scanned = adapter.scan(None)

    assert scanned.status is BatchStatus.PARTIAL
    assert len(scanned.records) == 1
    assert "unreadable-session-group" in {
        warning.code for warning in scanned.warnings
    }


def test_corrupt_update_retains_prior_checkpoint_record(
    fixture_home: Path,
) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    first = adapter.scan(None)
    summary = next((fixture_home / "sessions").rglob("summary.json"))
    summary.write_text("{broken", encoding="utf-8")

    second = adapter.scan(first.next_checkpoint)

    assert second.status is BatchStatus.PARTIAL
    assert second.records == ()
    assert second.next_checkpoint == first.next_checkpoint
    assert "last-known-good-retained" in {
        warning.code for warning in second.warnings
    }


def test_healthy_scan_reports_native_deletion(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    first = adapter.scan(None)
    identity = first.records[0].identity
    session_dir = next((fixture_home / "sessions").glob("*/*"))
    for child in session_dir.iterdir():
        child.unlink()
    session_dir.rmdir()

    second = adapter.scan(first.next_checkpoint)

    assert second.status is BatchStatus.COMPLETE
    assert second.records == ()
    assert second.removed == (identity,)
    assert json.loads(second.next_checkpoint.cursor)["fingerprints"] == {}


def test_missing_updates_is_partial_during_scan(fixture_home: Path) -> None:
    updates = next((fixture_home / "sessions").rglob("updates.jsonl"))
    updates.unlink()
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")

    scanned = adapter.scan(None)

    assert scanned.status is BatchStatus.PARTIAL
    assert len(scanned.records) == 1
    assert "missing-updates" in {warning.code for warning in scanned.warnings}


@pytest.mark.parametrize(
    "malformed",
    [
        {"method": "session/update", "params": []},
        {"method": "session/update", "params": {"sessionId": SESSION_ID}},
        {
            "method": "session/update",
            "params": {"sessionId": SESSION_ID, "update": {}},
        },
    ],
)
def test_recognized_malformed_updates_are_partial(
    fixture_home: Path, malformed: object
) -> None:
    updates = next((fixture_home / "sessions").rglob("updates.jsonl"))
    with updates.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(malformed) + "\n")
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert len(read.turns) == 2
    assert "update-schema-drift" in {warning.code for warning in read.warnings}


def test_consecutive_message_chunks_remain_independently_cited_turns(
    fixture_home: Path,
) -> None:
    updates = next((fixture_home / "sessions").rglob("updates.jsonl"))
    adjacent_chunk = {
        "method": "session/update",
        "params": {
            "sessionId": SESSION_ID,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "Second adjacent chunk."},
            },
        },
        "timestamp": 1784059241,
    }
    with updates.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(adjacent_chunk) + "\n")
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection())

    assert [turn.ordinal for turn in read.turns] == [0, 1, 2]
    assert [turn.role for turn in read.turns[-2:]] == [TurnRole.AGENT, TurnRole.AGENT]
    assert read.turns[-2].citation_locator != read.turns[-1].citation_locator


def test_source_change_during_read_is_partial(fixture_home: Path) -> None:
    adapter = GrokAdapter(fixture_home, source_namespace="fixture")
    record = adapter.scan(None).records[0]
    changed = SourceFingerprint("sha256", "changed-during-read")

    with patch.object(
        adapter, "_fingerprint", side_effect=[record.fingerprint, changed]
    ):
        read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert "source-changed-during-read" in {
        warning.code for warning in read.warnings
    }
