from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tang.adapters import (
    AdapterCheckpoint,
    AdapterWarning,
    BatchStatus,
    CodexAdapter,
    ScanBatch,
    SessionIdentity,
    SourceRecord,
    TurnBatch,
    TurnRole,
    TurnSelection,
    VisibleTurn,
)
from tang.cli import main
from tang.context import UNTRUSTED_NOTICE
from tang.context_service import ContextGenerationError, ContextPackService
from tang.project import resolve_project
from tang.repository import StoredContinuation, TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


class RecordingAdapter:
    adapter_key = "codex"
    source_namespace = "context-test"

    def __init__(self, reads: dict[str, TurnBatch]) -> None:
        self.reads = reads
        self.called: list[str] = []

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        return ScanBatch(BatchStatus.COMPLETE)

    def read(self, session_ref: SourceRecord, selection: TurnSelection) -> TurnBatch:
        canonical = session_ref.identity.canonical
        self.called.append(canonical)
        return self.reads[canonical]


def source(template: SourceRecord, native_id: str) -> SourceRecord:
    return replace(
        template,
        identity=SessionIdentity("codex", "context-test", native_id),
        started_at=NOW,
        updated_at=NOW,
    )


def readable(source_record: SourceRecord, text: str) -> TurnBatch:
    return TurnBatch(
        identity=source_record.identity,
        status=BatchStatus.COMPLETE,
        turns=(
            VisibleTurn(
                ordinal=0,
                role=TurnRole.USER,
                text=text,
                citation_locator="jsonl:1",
                timestamp=NOW,
            ),
        ),
    )


def test_context_validates_all_projects_before_reread(codex_fixture_home: Path, tmp_path: Path) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    current_source = source(template, "current")
    foreign_source = source(template, "foreign")
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    with repository.transaction():
        repository.upsert_session(current_source, "current-project", NOW)
        repository.upsert_session(foreign_source, "foreign-project", NOW)
    adapter = RecordingAdapter(
        {
            current_source.identity.canonical: readable(current_source, "current"),
            foreign_source.identity.canonical: readable(foreign_source, "foreign"),
        }
    )
    try:
        with pytest.raises(ContextGenerationError, match="current project"):
            ContextPackService(repository, (adapter,)).generate(
                (
                    current_source.identity.canonical,
                    foreign_source.identity.canonical,
                ),
                "current-project",
            )
        assert adapter.called == []
    finally:
        connection.close()


def test_context_partial_source_warning_and_no_readable_failure(
    codex_fixture_home: Path, tmp_path: Path
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    available = source(template, "available")
    unavailable = source(template, "unavailable")
    missing = TurnBatch(
        identity=unavailable.identity,
        status=BatchStatus.UNAVAILABLE,
        warnings=(
            AdapterWarning("missing-source", "Synthetic source unavailable", unavailable.identity),
        ),
    )
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    with repository.transaction():
        repository.upsert_session(available, "project", NOW)
        repository.upsert_session(unavailable, "project", NOW)
    adapter = RecordingAdapter(
        {
            available.identity.canonical: readable(available, "evidence"),
            unavailable.identity.canonical: missing,
        }
    )
    service = ContextPackService(repository, (adapter,))
    try:
        pack = service.generate(
            (available.identity.canonical, unavailable.identity.canonical), "project"
        )
        assert pack.status == "partial"
        assert [section.source_id for section in pack.sections] == [
            available.identity.canonical
        ]
        assert unavailable.identity.canonical in pack.warnings[0]
        assert pack.sections[0].excerpts[0].citation.turn_locator == "jsonl:1"
        assert UNTRUSTED_NOTICE in pack.to_markdown()
        assert json.loads(pack.to_json())["status"] == "partial"

        with pytest.raises(ContextGenerationError, match="none"):
            service.generate((unavailable.identity.canonical,), "project")
    finally:
        connection.close()


def test_context_fails_before_reread_when_native_source_is_tombstoned(
    codex_fixture_home: Path, tmp_path: Path
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    unavailable = source(template, "unavailable")
    target = source(template, "target")
    database = tmp_path / "tang.db"
    connection = open_database(database)
    repository = TangRepository(connection)
    with repository.transaction():
        repository.upsert_session(unavailable, "project", NOW)
        repository.upsert_session(target, "project", NOW)
        repository.put_continuation(
            StoredContinuation(
                unavailable.identity.canonical,
                target.identity.canonical,
                "project",
                "explicit",
                NOW,
            )
        )
        repository.delete_session(unavailable.identity.canonical)
    adapter = RecordingAdapter(
        {unavailable.identity.canonical: readable(unavailable, "must not read")}
    )

    try:
        with pytest.raises(ContextGenerationError, match="no longer available"):
            ContextPackService(repository, (adapter,)).generate(
                (unavailable.identity.canonical,), "project"
            )
        assert adapter.called == []
    finally:
        connection.close()


def test_context_cli_renders_deterministic_markdown_and_json(
    copied_codex_home: Path, tmp_path: Path, capsys
) -> None:
    current = tmp_path / "current"
    current.mkdir()
    adapter = CodexAdapter(copied_codex_home)
    native = adapter.scan(None).records[0]
    database = tmp_path / "tang.db"
    connection = open_database(database)
    try:
        with TangRepository(connection).transaction():
            TangRepository(connection).upsert_session(
                native, resolve_project(current).key, NOW
            )
    finally:
        connection.close()
    arguments = [
        "context",
        native.identity.canonical,
        "--database",
        str(database),
        "--cwd",
        str(current),
        "--codex-home",
        str(copied_codex_home),
        "--grok-home",
        str(tmp_path / "missing-grok"),
    ]

    assert main([*arguments, "--json"]) == 0
    first = capsys.readouterr()
    document = json.loads(first.out)
    assert document["schema_version"] == 1
    assert document["status"] == "complete"
    assert document["untrusted_data_envelope"]["notice"] == UNTRUSTED_NOTICE
    assert first.err == ""

    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second.out.startswith("# Tang Multi-Source Context Pack\n")
    assert UNTRUSTED_NOTICE in second.out
    assert second.err == ""
