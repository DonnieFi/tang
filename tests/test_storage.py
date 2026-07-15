from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from tang.storage import (
    BUSY_TIMEOUT_MS,
    MIGRATIONS,
    SCHEMA_VERSION,
    data_path,
    open_database,
)


def test_data_path_prefers_xdg_and_does_not_create_it(tmp_path: Path) -> None:
    xdg = tmp_path / "private-data"

    path = data_path({"XDG_DATA_HOME": str(xdg), "HOME": "/ignored"})

    assert path == xdg / "tang" / "tang.db"
    assert not path.exists()


def test_fresh_database_is_secure_configured_and_migrated(tmp_path: Path) -> None:
    path = tmp_path / "derived" / "tang.db"
    connection = open_database(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        assert {"sessions", "adapter_checkpoints", "capsules", "capsules_fts"} <= tables
    finally:
        connection.close()

    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_existing_database_upgrades_from_first_migration(tmp_path: Path) -> None:
    path = tmp_path / "upgrade" / "tang.db"
    first_only = (MIGRATIONS[0],)
    connection = open_database(path, migrations=first_only)
    connection.close()

    upgraded = open_database(path)
    try:
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert upgraded.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'capsules_fts'"
        ).fetchone()[0] == 1
    finally:
        upgraded.close()


def test_failed_migration_rolls_back_and_can_recover(tmp_path: Path) -> None:
    path = tmp_path / "failure" / "tang.db"
    broken = (
        (1, ("CREATE TABLE partial(value TEXT)", "INVALID SQL")),
    )

    with pytest.raises(sqlite3.OperationalError):
        open_database(path, migrations=broken)

    raw = sqlite3.connect(path)
    try:
        assert raw.execute("PRAGMA user_version").fetchone()[0] == 0
        assert raw.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'partial'"
        ).fetchone() is None
    finally:
        raw.close()

    recovered = open_database(path)
    try:
        assert recovered.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        recovered.close()


def test_explicit_test_path_never_uses_user_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel_root = tmp_path / "must-not-touch"
    monkeypatch.setenv("XDG_DATA_HOME", str(sentinel_root))
    isolated = tmp_path / "isolated" / "test.db"

    connection = open_database(isolated)
    connection.close()

    assert isolated.exists()
    assert not sentinel_root.exists()
