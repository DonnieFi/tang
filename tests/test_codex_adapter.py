from __future__ import annotations

import json
from pathlib import Path

import pytest

from tang.adapters import (
    AdapterCheckpoint,
    BatchStatus,
    CodexAdapter,
    TurnRole,
    TurnSelection,
)


def fixture_adapter(home: Path) -> CodexAdapter:
    return CodexAdapter(home, source_namespace="fixture-codex")


def only_log(home: Path) -> Path:
    return next((home / "sessions").rglob("*.jsonl"))


def test_scan_and_read_representative_visible_turns(codex_fixture_home: Path) -> None:
    adapter = fixture_adapter(codex_fixture_home)

    scan = adapter.scan(None)
    assert scan.status is BatchStatus.COMPLETE
    assert len(scan.records) == 1
    record = scan.records[0]
    assert record.identity.adapter == "codex"
    assert record.project_hint == "/work/tang-demo"
    assert record.started_at.isoformat() == "2026-07-14T20:00:00+00:00"
    assert record.updated_at.isoformat() == "2026-07-14T20:01:02+00:00"

    read = adapter.read(record, TurnSelection())
    assert read.status is BatchStatus.COMPLETE
    assert [turn.role for turn in read.turns] == [
        TurnRole.USER,
        TurnRole.AGENT,
        TurnRole.USER,
        TurnRole.AGENT,
    ]
    assert [turn.ordinal for turn in read.turns] == [0, 1, 2, 3]
    assert all(turn.citation_locator.startswith("jsonl:") for turn in read.turns)
    assert all(turn.timestamp is not None for turn in read.turns)
    assert "agent_message" not in " ".join(turn.text for turn in read.turns)


def test_incremental_scan_is_idempotent(codex_fixture_home: Path) -> None:
    adapter = fixture_adapter(codex_fixture_home)
    first = adapter.scan(None)

    second = adapter.scan(first.next_checkpoint)

    assert second.status is BatchStatus.COMPLETE
    assert second.records == ()
    assert second.next_checkpoint == first.next_checkpoint


def test_unchanged_valid_log_skips_the_redundant_structural_parse(
    codex_fixture_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = fixture_adapter(codex_fixture_home)
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
    codex_fixture_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = fixture_adapter(codex_fixture_home)
    first = adapter.scan(None)
    payload = json.loads(first.next_checkpoint.cursor)
    legacy = AdapterCheckpoint(
        "codex",
        "fixture-codex",
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


def test_thread_session_link_does_not_replace_native_log_identity(
    copied_codex_home: Path,
) -> None:
    log = only_log(copied_codex_home)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[0]["payload"]["session_id"] = "019f6000-9999-7000-8000-000000000009"
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    scan = fixture_adapter(copied_codex_home).scan(None)

    assert scan.status is BatchStatus.COMPLETE
    assert len(scan.records) == 1
    assert scan.records[0].identity.native_id.endswith("000000000002")


def test_selected_read_retains_native_ordinals(codex_fixture_home: Path) -> None:
    adapter = fixture_adapter(codex_fixture_home)
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection(start_at=1, stop_before=3))

    assert [turn.ordinal for turn in read.turns] == [1, 2]
    assert [turn.role for turn in read.turns] == [TurnRole.AGENT, TurnRole.USER]


def test_truncated_later_scan_retains_last_known_good(copied_codex_home: Path) -> None:
    adapter = fixture_adapter(copied_codex_home)
    first = adapter.scan(None)
    original_fingerprint = first.records[0].fingerprint.value
    log = only_log(copied_codex_home)
    with log.open("a", encoding="utf-8") as destination:
        destination.write('{"timestamp":"2026-07-14T20:02:00Z"')

    second = adapter.scan(first.next_checkpoint)

    assert second.status is BatchStatus.PARTIAL
    assert second.records == ()
    assert {warning.code for warning in second.warnings} >= {
        "malformed-jsonl",
        "last-known-good-retained",
    }
    payload = json.loads(second.next_checkpoint.cursor)
    assert next(iter(payload["fingerprints"].values())) == original_fingerprint

    log.write_text(log.read_text().rsplit('{"timestamp"', 1)[0])
    with log.open("a", encoding="utf-8") as destination:
        destination.write(
            '{"timestamp":"2026-07-14T20:03:00Z","type":"response_item",'
            '"payload":{"type":"message","role":"assistant",'
            '"content":[{"type":"output_text","text":"Recovered cleanly."}]}}\n'
        )

    recovered = adapter.scan(second.next_checkpoint)

    assert recovered.status is BatchStatus.COMPLETE
    assert len(recovered.records) == 1
    assert recovered.next_checkpoint != second.next_checkpoint


def test_healthy_scan_reports_native_deletion(copied_codex_home: Path) -> None:
    adapter = fixture_adapter(copied_codex_home)
    first = adapter.scan(None)
    identity = first.records[0].identity
    only_log(copied_codex_home).unlink()

    second = adapter.scan(first.next_checkpoint)

    assert second.status is BatchStatus.COMPLETE
    assert second.records == ()
    assert second.removed == (identity,)
    assert json.loads(second.next_checkpoint.cursor)["fingerprints"] == {}


def test_truncated_read_returns_visible_partial_data(copied_codex_home: Path) -> None:
    adapter = fixture_adapter(copied_codex_home)
    record = adapter.scan(None).records[0]
    with only_log(copied_codex_home).open("a", encoding="utf-8") as destination:
        destination.write("{truncated")

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert len(read.turns) == 4
    assert {warning.code for warning in read.warnings} == {
        "malformed-jsonl",
        "source-changed-during-read",
    }


def test_recognized_visible_schema_drift_is_partial(copied_codex_home: Path) -> None:
    log = only_log(copied_codex_home)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[1]["payload"]["content"] = {"type": "input_text", "text": "invalid"}
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    adapter = fixture_adapter(copied_codex_home)

    scan = adapter.scan(None)
    read = adapter.read(scan.records[0], TurnSelection())

    assert scan.status is BatchStatus.PARTIAL
    assert read.status is BatchStatus.PARTIAL
    assert "visible-turn-schema-drift" in {
        warning.code for warning in scan.warnings
    }
    assert "visible-turn-schema-drift" in {
        warning.code for warning in read.warnings
    }
    assert len(read.turns) == 3


def test_missing_selected_log_is_unavailable(copied_codex_home: Path) -> None:
    adapter = fixture_adapter(copied_codex_home)
    record = adapter.scan(None).records[0]
    only_log(copied_codex_home).unlink()

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.UNAVAILABLE
    assert read.turns == ()
    assert read.warnings[0].code == "missing-source"


def test_missing_store_is_unavailable(tmp_path: Path) -> None:
    scan = fixture_adapter(tmp_path / "missing").scan(None)

    assert scan.status is BatchStatus.UNAVAILABLE
    assert scan.warnings[0].code == "missing-store"


def test_symlinked_log_is_not_scanned(
    copied_codex_home: Path, tmp_path: Path
) -> None:
    original = only_log(copied_codex_home)
    outside = tmp_path / "outside.jsonl"
    outside.write_text(original.read_text())
    original.unlink()
    original.symlink_to(outside)

    scan = fixture_adapter(copied_codex_home).scan(None)

    assert scan.status is BatchStatus.PARTIAL
    assert scan.records == ()
    assert "unsafe-session-source" in {warning.code for warning in scan.warnings}


def test_namespace_distinguishes_codex_stores(tmp_path: Path) -> None:
    first = CodexAdapter(tmp_path / "first")
    first_again = CodexAdapter(tmp_path / "first")
    second = CodexAdapter(tmp_path / "second")

    assert first.source_namespace == first_again.source_namespace
    assert first.source_namespace != second.source_namespace


@pytest.mark.parametrize("bad_timestamp", [None, "not-a-time", "2026-07-14"])
def test_invalid_row_timestamp_warns(
    copied_codex_home: Path, bad_timestamp: object
) -> None:
    log = only_log(copied_codex_home)
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[-1]["timestamp"] = bad_timestamp
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")

    scan = fixture_adapter(copied_codex_home).scan(None)

    assert scan.status is BatchStatus.PARTIAL
    assert "row-timestamp-drift" in {warning.code for warning in scan.warnings}
