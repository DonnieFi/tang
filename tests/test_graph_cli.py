from __future__ import annotations

import io
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
from tang.repository import StoredContinuation, TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


class TtyBuffer(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def record(native_id: str, project: Path) -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity("codex", "graph", native_id),
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
        repository = TangRepository(connection)
        with repository.transaction():
            for item in records:
                repository.upsert_session(item, resolve_project(project).key, NOW)
    finally:
        connection.close()


def test_graph_accepts_an_explicit_indexed_session(
    tmp_path: Path, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    item = record("explicit", project)
    seed(database, project, item)
    result = main(
        [
            "graph",
            "c1",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    assert "ISOLATED" in captured.out
    assert "C1" in captured.out
    assert item.identity.canonical not in captured.out


def test_graph_infers_only_a_unique_current_target(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    current = record("current", project)
    seed(database, project, current)
    common = ["graph", "--database", str(database), "--cwd", str(project)]

    def unexpected_scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("current graphing must use the indexed project database")

    monkeypatch.setattr(
        "tang.adapters.codex.CodexAdapter.scan", unexpected_scan
    )

    assert main(common) == 0
    inferred = capsys.readouterr()
    assert inferred.err == ""
    assert "★ C1" in inferred.out

    other = record("other", project)
    seed(database, project, other)
    assert main(common) == 2
    ambiguous = capsys.readouterr()
    assert ambiguous.out == ""
    assert "error[target-unconfirmed]" in ambiguous.err


def test_graph_respects_no_color_and_explicit_ascii(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    item = record("current", project)
    seed(database, project, item)
    output = TtyBuffer()
    monkeypatch.setattr("tang.cli.sys.stdout", output)
    monkeypatch.setenv("NO_COLOR", "1")

    result = main(
        [
            "graph",
            "C1",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--ascii",
            "--current-native-id",
            "current",
            "--width",
            "60",
        ]
    )

    assert result == 0
    assert "\x1b[" not in output.getvalue()
    assert output.getvalue().isascii()
    assert "* C1 | codex" in output.getvalue()


def test_graph_can_force_capture_unicode_and_color(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    source = record("source", project)
    target = record("target", project)
    seed(database, project, source, target)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.put_continuation(
                StoredContinuation(
                    source.identity.canonical,
                    target.identity.canonical,
                    resolve_project(project).key,
                    "explicit",
                    NOW,
                )
            )
    finally:
        connection.close()
    output = TtyBuffer()
    monkeypatch.setattr("tang.cli.sys.stdout", output)
    monkeypatch.setenv("NO_COLOR", "1")

    result = main(
        [
            "graph",
            "C2",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--width",
            "120",
            "--unicode",
            "--color",
            "always",
        ]
    )

    assert result == 0
    assert "MULTIVERSE NETWORK" in output.getvalue()
    assert "\x1b[" in output.getvalue()


def test_graph_rejects_a_canonical_session_from_another_project(
    tmp_path: Path, capsys
) -> None:
    project = tmp_path / "project"
    foreign = tmp_path / "foreign"
    project.mkdir()
    foreign.mkdir()
    database = tmp_path / "tang.db"
    current = record("current", project)
    foreign_record = record("foreign", foreign)
    seed(database, project, current)
    seed(database, foreign, foreign_record)

    result = main(
        [
            "graph",
            foreign_record.identity.canonical,
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert captured.out == ""
    assert "error[unknown-session]" in captured.err
