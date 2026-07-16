from __future__ import annotations

import io
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


class TtyBuffer(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


def record(native_id: str, project: Path) -> SourceRecord:
    return SourceRecord(
        SessionIdentity("codex", "graph", native_id),
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
        repository = TangRepository(connection)
        with repository.transaction():
            for item in records:
                repository.upsert_session(item, resolve_project(project).key, NOW)
    finally:
        connection.close()


def test_graph_accepts_an_explicit_indexed_session(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    item = record("explicit", project)
    seed(database, project, item)
    monkeypatch.setattr(
        "tang.cli.CodexAdapter.scan",
        lambda adapter, checkpoint: (_ for _ in ()).throw(
            AssertionError("explicit graph rendering must not scan native history")
        ),
    )

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
    other = record("other", project)
    seed(database, project, current, other)
    common = ["graph", "--database", str(database), "--cwd", str(project)]

    monkeypatch.setattr(
        "tang.cli.CodexAdapter.scan",
        lambda adapter, checkpoint: ScanBatch(BatchStatus.COMPLETE, (current,)),
    )
    assert main(common) == 0
    inferred = capsys.readouterr()
    assert inferred.err == ""
    assert "★ C1" in inferred.out

    monkeypatch.setattr(
        "tang.cli.CodexAdapter.scan",
        lambda adapter, checkpoint: ScanBatch(
            BatchStatus.COMPLETE, (current, other)
        ),
    )
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
    monkeypatch.setattr(
        "tang.cli.CodexAdapter.scan",
        lambda adapter, checkpoint: ScanBatch(BatchStatus.COMPLETE, (item,)),
    )
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
