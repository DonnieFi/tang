from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.cli import main
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def record(adapter: str, native_id: str, project: Path) -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity(adapter, "cli", native_id),
        locator=OpaqueSourceLocator(f"fixture:{native_id}"),
        fingerprint=SourceFingerprint("sha256", f"digest-{native_id}"),
        project_hint=str(project),
        started_at=NOW,
        updated_at=NOW,
        health=SessionHealth.COMPLETE,
    )


def seed(database: Path, project: Path, *records: SourceRecord) -> None:
    connection = open_database(database)
    try:
        with TangRepository(connection).transaction():
            for item in records:
                TangRepository(connection).upsert_session(
                    item, resolve_project(project).key, NOW
                )
    finally:
        connection.close()


def test_explicit_link_json_is_deterministic(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    first = record("grok", "first", project)
    second = record("codex", "second", project)
    target = record("codex", "target", project)
    seed(database, project, first, second, target)

    result = main(
        [
            "link",
            "--from",
            "G1",
            "c1",
            "--to",
            "C2",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--json",
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "existing": 0,
        "inserted": 2,
        "schema_version": 1,
        "source_handles": ["G1", "C1"],
        "source_ids": [first.identity.canonical, second.identity.canonical],
        "target_handle": "C2",
        "target_id": target.identity.canonical,
    }


def test_unique_current_target_links_and_ambiguity_refuses(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    source = record("grok", "source", project)
    target = record("codex", "target", project)
    seed(database, project, source, target)
    common = [
        "link",
        "--from",
        source.identity.canonical,
        "--current",
        "--database",
        str(database),
        "--cwd",
        str(project),
    ]

    def unexpected_scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("current linking must use the indexed project database")

    monkeypatch.setattr(
        "tang.adapters.codex.CodexAdapter.scan", unexpected_scan
    )

    assert main(common) == 0
    linked = capsys.readouterr()
    assert linked.out == "Linked G1 to C1; inserted 1, existing 0.\n"
    assert linked.err == ""

    second_source = record("grok", "second-source", project)
    other = record("codex", "other", project)
    seed(database, project, second_source, other)
    common[2] = second_source.identity.canonical
    assert main(common) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "error[target-unconfirmed]" in refused.err

    connection = open_database(database)
    try:
        edges = TangRepository(connection).continuations_for_project(
            resolve_project(project).key
        )
        assert len(edges) == 1
    finally:
        connection.close()


def test_unindexed_current_target_reports_index_required(
    tmp_path: Path, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    source = record("grok", "source", project)
    seed(database, project, source)

    result = main(
        [
            "link",
            "--from",
            "G1",
            "--current",
            "--current-native-id",
            "not-indexed",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "error[index-required]" in captured.err


def test_link_errors_stay_on_stderr(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    item = record("codex", "same", project)
    seed(database, project, item)

    assert main([
        "link", "--from", item.identity.canonical, "--to", item.identity.canonical,
        "--database", str(database), "--cwd", str(project)
    ]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error[self-link]" in captured.err


def test_link_rejects_malformed_canonical_ids(tmp_path: Path, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    seed(database, project, record("codex", "target", project))

    assert main(
        [
            "link",
            "--from",
            "not-a-canonical-id",
            "--to",
            "codex:cli:target",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    ) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error[invalid-session-id]" in captured.err


def test_link_reports_an_unavailable_target_without_mutating_edges(
    tmp_path: Path, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    first = record("grok", "first", project)
    second = record("grok", "second", project)
    target = record("codex", "target", project)
    seed(database, project, first, second, target)
    common = ["--database", str(database), "--cwd", str(project)]

    assert main(
        [
            "link",
            "--from",
            first.identity.canonical,
            "--to",
            target.identity.canonical,
            *common,
        ]
    ) == 0
    capsys.readouterr()
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.delete_session(target.identity.canonical)
    finally:
        connection.close()

    assert main(
        [
            "link",
            "--from",
            second.identity.canonical,
            "--to",
            target.identity.canonical,
            *common,
        ]
    ) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "error[unavailable-target]" in refused.err
