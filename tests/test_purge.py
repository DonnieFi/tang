from __future__ import annotations

import io
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tang.adapters import CodexAdapter
from tang.cli import main
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


class TtyInput(io.StringIO):
    def isatty(self) -> bool:
        return True


def indexed_database(copied_codex_home: Path, tmp_path: Path) -> tuple[Path, Path]:
    current = tmp_path / "current"
    current.mkdir()
    log = next((copied_codex_home / "sessions").rglob("*.jsonl"))
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[0]["payload"]["cwd"] = str(current)
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    database = tmp_path / "tang.db"
    connection = open_database(database)
    try:
        ProjectIndexer(TangRepository(connection)).index(
            (CodexAdapter(copied_codex_home),), resolve_project(current), now=NOW
        )
    finally:
        connection.close()
    return database, current


def derived_counts(database: Path) -> tuple[int, int, int, int]:
    connection = open_database(database)
    try:
        return tuple(
            int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
            for table in (
                "sessions",
                "capsules",
                "capsules_fts",
                "adapter_checkpoints",
            )
        )
    finally:
        connection.close()


def test_purge_confirmation_paths_and_native_logs_are_untouched(
    copied_codex_home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
) -> None:
    database, _ = indexed_database(copied_codex_home, tmp_path)
    native_before = {
        path: path.read_bytes()
        for path in (copied_codex_home / "sessions").rglob("*")
        if path.is_file()
    }
    populated = derived_counts(database)
    assert all(count == 1 for count in populated)

    monkeypatch.setattr("sys.stdin", io.StringIO())
    assert main(["purge", "--all", "--database", str(database)]) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert refused.err == "error: non-interactive purge requires --yes\n"
    assert derived_counts(database) == populated

    monkeypatch.setattr("sys.stdin", TtyInput("NO\n"))
    assert main(["purge", "--all", "--database", str(database)]) == 0
    cancelled = capsys.readouterr()
    assert "Purge cancelled" in cancelled.out
    assert cancelled.err == ""
    assert derived_counts(database) == populated

    assert main(["purge", "--all", "--yes", "--database", str(database)]) == 0
    purged = capsys.readouterr()
    assert purged.out == (
        "Purged 1 sessions, 1 capsules, 1 search rows, and 1 checkpoints. "
        "Native harness logs were not modified.\n"
    )
    assert purged.err == ""
    assert derived_counts(database) == (0, 0, 0, 0)
    assert {path: path.read_bytes() for path in native_before} == native_before


def test_purge_all_rolls_back_every_table_on_failure(
    copied_codex_home: Path, tmp_path: Path
) -> None:
    database, _ = indexed_database(copied_codex_home, tmp_path)
    connection = open_database(database)
    repository = TangRepository(connection)
    connection.execute(
        """
        CREATE TRIGGER synthetic_purge_failure BEFORE DELETE ON sessions
        BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END
        """
    )
    try:
        with pytest.raises(sqlite3.IntegrityError, match="synthetic failure"):
            with repository.transaction():
                repository.purge_all()
        assert derived_counts(database) == (1, 1, 1, 1)
    finally:
        connection.close()
