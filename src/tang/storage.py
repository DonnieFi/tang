"""Secure SQLite bootstrap and transactional schema migrations."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from tang.project import ProjectIdentity


BUSY_TIMEOUT_MS = 5_000
Migration = tuple[int, tuple[str, ...]]

MIGRATIONS: tuple[Migration, ...] = (
    (
        1,
        (
            """
            CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                adapter TEXT NOT NULL,
                source_namespace TEXT NOT NULL,
                native_id TEXT NOT NULL,
                locator TEXT NOT NULL,
                fingerprint_algorithm TEXT NOT NULL,
                fingerprint_value TEXT NOT NULL,
                project_hint TEXT NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                health TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                UNIQUE(adapter, source_namespace, native_id)
            )
            """,
            "CREATE INDEX sessions_project_updated ON sessions(project_key, updated_at DESC, source_id)",
            """
            CREATE TABLE adapter_checkpoints (
                adapter TEXT NOT NULL,
                source_namespace TEXT NOT NULL,
                cursor TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(adapter, source_namespace)
            )
            """,
            """
            CREATE TABLE capsules (
                source_id TEXT PRIMARY KEY REFERENCES sessions(source_id) ON DELETE CASCADE,
                project_key TEXT NOT NULL,
                schema_version INTEGER NOT NULL CHECK(schema_version = 1),
                content_json TEXT NOT NULL,
                search_text TEXT NOT NULL,
                byte_count INTEGER NOT NULL CHECK(byte_count <= 8192),
                updated_at TEXT NOT NULL
            )
            """,
        ),
    ),
    (
        2,
        (
            """
            CREATE VIRTUAL TABLE capsules_fts USING fts5(
                source_id UNINDEXED,
                project_key UNINDEXED,
                search_text,
                tokenize = 'unicode61'
            )
            """,
        ),
    ),
    (
        3,
        (
            "ALTER TABLE adapter_checkpoints RENAME TO adapter_checkpoints_v2",
            """
            CREATE TABLE adapter_checkpoints (
                adapter TEXT NOT NULL,
                source_namespace TEXT NOT NULL,
                project_key TEXT NOT NULL,
                cursor TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(adapter, source_namespace, project_key)
            )
            """,
            # Pre-release v2 checkpoints had no project ownership. Discarding
            # them causes one safe full rescan instead of suppressing another
            # project's unchanged native records.
            "DROP TABLE adapter_checkpoints_v2",
        ),
    ),
    (
        4,
        (
            "ALTER TABLE sessions ADD COLUMN native_available INTEGER NOT NULL DEFAULT 1 CHECK(native_available IN (0, 1))",
            """
            CREATE TABLE continuation_edges (
                source_id TEXT NOT NULL REFERENCES sessions(source_id) ON DELETE RESTRICT,
                target_id TEXT NOT NULL REFERENCES sessions(source_id) ON DELETE RESTRICT,
                project_key TEXT NOT NULL,
                confirmation_mode TEXT NOT NULL CHECK(confirmation_mode IN ('current', 'explicit')),
                confirmed_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1 CHECK(schema_version = 1),
                PRIMARY KEY(source_id, target_id)
            )
            """,
            "CREATE INDEX continuation_edges_target ON continuation_edges(target_id, source_id)",
            "CREATE INDEX continuation_edges_project ON continuation_edges(project_key, source_id, target_id)",
        ),
    ),
    (
        5,
        (
            "ALTER TABLE sessions ADD COLUMN session_handle TEXT",
            """
            WITH prefixed AS (
                SELECT
                    source_id,
                    project_key,
                    started_at,
                    adapter,
                    CASE adapter
                        WHEN 'codex' THEN 'C'
                        WHEN 'grok' THEN 'G'
                        WHEN 'opencode' THEN 'O'
                        WHEN 'cursor' THEN 'R'
                        ELSE 'S'
                    END AS prefix
                FROM sessions
            ),
            ranked AS (
                SELECT
                    source_id,
                    prefix || CAST(
                        ROW_NUMBER() OVER (
                            PARTITION BY project_key, prefix
                            ORDER BY started_at, source_id
                        ) AS TEXT
                    ) AS session_handle
                FROM prefixed
            )
            UPDATE sessions
            SET session_handle = (
                SELECT ranked.session_handle
                FROM ranked
                WHERE ranked.source_id = sessions.source_id
            )
            """,
            "CREATE UNIQUE INDEX sessions_project_handle ON sessions(project_key, session_handle)",
        ),
    ),
    (
        6,
        (
            "ALTER TABLE sessions ADD COLUMN title TEXT",
        ),
    ),
)
SCHEMA_VERSION = MIGRATIONS[-1][0]


class DatabaseOpenError(RuntimeError):
    """The configured derived-storage path cannot be opened safely."""


def project_data_path(project: ProjectIdentity) -> Path:
    """Return the canonical project-local database path without creating it."""

    return project.root_path / ".tang" / "tang.db"


def _secure_parent(path: Path) -> None:
    parent_existed = path.parent.exists()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name == "posix" and not parent_existed:
        path.parent.chmod(0o700)


def _migrate(
    connection: sqlite3.Connection,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> None:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    for version, statements in migrations:
        if version <= current:
            continue
        if version != current + 1:
            raise RuntimeError(
                f"missing schema migration between {current} and {version}"
            )
        connection.execute("BEGIN IMMEDIATE")
        try:
            for statement in statements:
                connection.execute(statement)
            connection.execute(f"PRAGMA user_version = {version}")
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        current = version


def open_database(
    path: Path,
    *,
    migrations: Sequence[Migration] = MIGRATIONS,
) -> sqlite3.Connection:
    """Open a configured database and migrate it before returning."""

    try:
        database_path = path.expanduser().resolve()
        _secure_parent(database_path)
        connection = sqlite3.connect(database_path, isolation_level=None)
    except (OSError, sqlite3.Error) as error:
        raise DatabaseOpenError(
            f"Tang cannot open derived storage at {path.expanduser()}"
        ) from error
    try:
        if os.name == "posix":
            database_path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        _migrate(connection, migrations)
        return connection
    except OSError as error:
        connection.close()
        raise DatabaseOpenError(
            f"Tang cannot initialize derived storage at {database_path}"
        ) from error
    except BaseException:
        connection.close()
        raise
