from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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


def test_confirmed_predecessors_follow_merge_history_by_depth(
    codex_fixture_home: Path, tmp_path: Path
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    left = replace(source(template, "left"), updated_at=NOW)
    right = replace(source(template, "right"), updated_at=NOW + timedelta(seconds=1))
    merge = replace(source(template, "merge"), updated_at=NOW + timedelta(seconds=2))
    target = replace(source(template, "target"), updated_at=NOW + timedelta(seconds=3))
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    try:
        with repository.transaction():
            for item in (left, right, merge, target):
                repository.upsert_session(item, "project", NOW)
            for source_id, target_id in (
                (left.identity.canonical, merge.identity.canonical),
                (right.identity.canonical, merge.identity.canonical),
                (merge.identity.canonical, target.identity.canonical),
            ):
                repository.put_continuation(
                    StoredContinuation(source_id, target_id, "project", "explicit", NOW)
                )

        assert repository.confirmed_predecessors(
            target.identity.canonical, "project"
        ) == (left.identity.canonical, right.identity.canonical, merge.identity.canonical)
        assert repository.confirmed_predecessors(
            target.identity.canonical, "project", max_hops=1
        ) == (merge.identity.canonical,)
        assert repository.confirmed_predecessors(
            target.identity.canonical, "project", max_hops=2
        ) == (left.identity.canonical, right.identity.canonical, merge.identity.canonical)
    finally:
        connection.close()


def test_context_cli_revisits_latest_confirmed_predecessors(
    codex_fixture_home: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    prior = replace(source(template, "prior"), updated_at=NOW)
    target = replace(source(template, "target"), updated_at=NOW + timedelta(seconds=1))
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.upsert_session(prior, project_key, NOW)
            repository.upsert_session(target, project_key, NOW)
            repository.put_continuation(
                StoredContinuation(
                    prior.identity.canonical,
                    target.identity.canonical,
                    project_key,
                    "explicit",
                    NOW,
                )
            )
    finally:
        connection.close()
    adapter = RecordingAdapter(
        {
            prior.identity.canonical: readable(prior, "recovered predecessor"),
            target.identity.canonical: readable(target, "current target"),
        }
    )
    monkeypatch.setattr(
        "tang.cli.configured_adapters", lambda *_args, **_kwargs: (adapter,)
    )
    common = ["--database", str(database), "--cwd", str(project), "--json"]

    assert main(["context", *common]) == 0
    bare = json.loads(capsys.readouterr().out)
    assert [section["source_id"] for section in bare["untrusted_data_envelope"]["sources"]] == [
        prior.identity.canonical
    ]

    assert main(["context", "all", "--for", "C2", *common]) == 0
    named = json.loads(capsys.readouterr().out)
    assert [section["source_id"] for section in named["untrusted_data_envelope"]["sources"]] == [
        prior.identity.canonical
    ]

    assert main(["context", "1", "--for", "C2", *common]) == 0
    depth_one = json.loads(capsys.readouterr().out)
    assert [section["source_id"] for section in depth_one["untrusted_data_envelope"]["sources"]] == [
        prior.identity.canonical
    ]


def test_context_cli_refuses_ambiguous_or_missing_confirmed_anchor(
    codex_fixture_home: Path, tmp_path: Path, capsys
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.upsert_session(source(template, "only"), resolve_project(project).key, NOW)
    finally:
        connection.close()

    assert main(["context", "--database", str(database), "--cwd", str(project)]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "no confirmed target" in refused.err


def test_context_cli_prefers_exact_current_target_over_terminal_history(
    codex_fixture_home: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    prior = replace(source(template, "prior"), updated_at=NOW)
    current = replace(source(template, "current"), updated_at=NOW + timedelta(seconds=1))
    other_prior = replace(source(template, "other-prior"), updated_at=NOW)
    other_target = replace(source(template, "other-target"), updated_at=NOW + timedelta(seconds=2))
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            for item in (prior, current, other_prior, other_target):
                repository.upsert_session(item, project_key, NOW)
            repository.put_continuation(
                StoredContinuation(
                    prior.identity.canonical,
                    current.identity.canonical,
                    project_key,
                    "explicit",
                    NOW,
                )
            )
            repository.put_continuation(
                StoredContinuation(
                    other_prior.identity.canonical,
                    other_target.identity.canonical,
                    project_key,
                    "explicit",
                    NOW + timedelta(seconds=1),
                )
            )
    finally:
        connection.close()
    adapter = RecordingAdapter(
        {
            prior.identity.canonical: readable(prior, "current predecessor"),
            current.identity.canonical: readable(current, "current"),
            other_prior.identity.canonical: readable(other_prior, "other predecessor"),
            other_target.identity.canonical: readable(other_target, "other target"),
        }
    )
    monkeypatch.setattr(
        "tang.cli.configured_adapters", lambda *_args, **_kwargs: (adapter,)
    )

    assert main(
        [
            "context",
            "--current-native-id",
            "current",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--json",
        ]
    ) == 0
    document = json.loads(capsys.readouterr().out)
    assert [section["source_id"] for section in document["untrusted_data_envelope"]["sources"]] == [
        prior.identity.canonical
    ]


def test_confirmed_predecessors_reject_a_foreign_anchor(
    codex_fixture_home: Path, tmp_path: Path
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    foreign = source(template, "foreign")
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    try:
        with repository.transaction():
            repository.upsert_session(foreign, "foreign-project", NOW)
        with pytest.raises(ValueError, match="current project"):
            repository.confirmed_predecessors(foreign.identity.canonical, "project")
    finally:
        connection.close()


def test_context_cli_history_keeps_readable_ancestor_when_one_is_tombstoned(
    codex_fixture_home: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    available = source(template, "available")
    unavailable = source(template, "unavailable")
    target = source(template, "target")
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            for item in (available, unavailable, target):
                repository.upsert_session(item, project_key, NOW)
            for predecessor in (available, unavailable):
                repository.put_continuation(
                    StoredContinuation(
                        predecessor.identity.canonical,
                        target.identity.canonical,
                        project_key,
                        "explicit",
                        NOW,
                    )
                )
            repository.delete_session(unavailable.identity.canonical)
    finally:
        connection.close()
    adapter = RecordingAdapter(
        {available.identity.canonical: readable(available, "available evidence")}
    )
    monkeypatch.setattr(
        "tang.cli.configured_adapters", lambda *_args, **_kwargs: (adapter,)
    )

    assert main(
        ["context", "all", "--database", str(database), "--cwd", str(project), "--json"]
    ) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "partial"
    assert [section["source_id"] for section in document["untrusted_data_envelope"]["sources"]] == [
        available.identity.canonical
    ]
    assert "source-unavailable" in document["warnings"][0]


def test_context_cli_refuses_tied_latest_confirmed_targets(
    codex_fixture_home: Path, tmp_path: Path, capsys
) -> None:
    template = CodexAdapter(codex_fixture_home).scan(None).records[0]
    source_one = source(template, "source-one")
    target_one = source(template, "target-one")
    source_two = source(template, "source-two")
    target_two = source(template, "target-two")
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            for item in (source_one, target_one, source_two, target_two):
                repository.upsert_session(item, project_key, NOW)
            for predecessor, target in (
                (source_one, target_one),
                (source_two, target_two),
            ):
                repository.put_continuation(
                    StoredContinuation(
                        predecessor.identity.canonical,
                        target.identity.canonical,
                        project_key,
                        "explicit",
                        NOW,
                    )
                )
    finally:
        connection.close()

    assert main(["context", "--database", str(database), "--cwd", str(project)]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "multiple targets share the latest confirmation" in refused.err


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
        "c1",
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
