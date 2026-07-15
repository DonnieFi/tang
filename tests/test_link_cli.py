from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import (
    BatchStatus,
    OpaqueSourceLocator,
    ScanBatch,
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
        SessionIdentity(adapter, "cli", native_id),
        OpaqueSourceLocator(f"fixture:{native_id}"),
        SourceFingerprint("sha256", f"digest-{native_id}"),
        str(project),
        NOW,
        NOW,
        SessionHealth.COMPLETE,
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
            first.identity.canonical,
            second.identity.canonical,
            "--to",
            target.identity.canonical,
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
        "source_ids": [first.identity.canonical, second.identity.canonical],
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
    other = record("codex", "other", project)
    seed(database, project, source, target, other)
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

    monkeypatch.setattr(
        "tang.cli.CodexAdapter.scan",
        lambda adapter, checkpoint: ScanBatch(BatchStatus.COMPLETE, (target,)),
    )
    assert main(common) == 0
    linked = capsys.readouterr()
    assert target.identity.canonical in linked.out
    assert linked.err == ""

    second_source = record("grok", "second-source", project)
    seed(database, project, second_source)
    common[2] = second_source.identity.canonical
    monkeypatch.setattr(
        "tang.cli.CodexAdapter.scan",
        lambda adapter, checkpoint: ScanBatch(
            BatchStatus.COMPLETE, (target, other)
        ),
    )
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
