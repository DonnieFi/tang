"""Explicit global catalog of redacted session capsules.

The per-project database remains the graph authority. This file is a second,
operator-requested index for cross-project recall. It stores redacted text
only, and it is created by catalog sync rather than by ordinary commands.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from tang.redaction import (
    DEFAULT_REDACTOR,
    ContentKind,
    RedactionSeam,
    required_redaction,
)
from tang.storage import BUSY_TIMEOUT_MS
from tang.timeutil import rfc3339

CATALOG_SCHEMA_VERSION = 1
_RECALL_SNIPPET_MARKERS = ("[", "]", " … ", 18)

_MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (
        1,
        (
            """
            CREATE TABLE catalog_sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                project_display TEXT NOT NULL,
                database_path TEXT NOT NULL,
                adapter TEXT NOT NULL,
                catalog_handle TEXT NOT NULL UNIQUE,
                project_handle TEXT NOT NULL,
                title TEXT,
                health TEXT NOT NULL,
                native_available INTEGER NOT NULL CHECK(native_available IN (0, 1)),
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                synced_at TEXT NOT NULL,
                search_text TEXT NOT NULL
            )
            """,
            """
            CREATE INDEX catalog_sessions_project
            ON catalog_sessions(project_key, updated_at DESC, source_id)
            """,
            """
            CREATE TABLE catalog_handle_counters (
                prefix TEXT PRIMARY KEY,
                next_number INTEGER NOT NULL CHECK(next_number >= 1)
            )
            """,
            """
            CREATE VIRTUAL TABLE catalog_fts USING fts5(
                source_id UNINDEXED,
                project_key UNINDEXED,
                search_text,
                tokenize = 'porter unicode61'
            )
            """,
        ),
    ),
)


class CatalogError(ValueError):
    """A refusal that is safe to show on the CLI."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SyncResult:
    upserted: int
    removed: int
    skipped: int


@dataclass(frozen=True, slots=True)
class RecallHit:
    source_id: str
    catalog_handle: str
    project_handle: str
    project_display: str
    project_key: str
    harness: str
    title: str | None
    updated_at: str
    health: str
    native_available: bool
    snippet: str | None


def default_catalog_path() -> Path:
    """Return the explicit catalog path without creating it."""

    override = os.environ.get("TANG_CATALOG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".tang" / "catalog.db"


def open_catalog(path: Path) -> sqlite3.Connection:
    """Open the global catalog, creating it only for an explicit sync path."""

    try:
        database_path = path.expanduser().resolve()
        parent_existed = database_path.parent.exists()
        database_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix" and not parent_existed:
            database_path.parent.chmod(0o700)
        connection = sqlite3.connect(database_path, isolation_level=None)
    except (OSError, sqlite3.Error) as error:
        raise CatalogError(
            "catalog-unavailable",
            f"Tang cannot open the global catalog at {path.expanduser()}",
        ) from error
    try:
        if os.name == "posix":
            database_path.chmod(0o600)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        _migrate(connection)
        return connection
    except BaseException:
        connection.close()
        raise


def sync_project(
    catalog: sqlite3.Connection,
    project_db: sqlite3.Connection,
    *,
    project_key: str,
    project_display: str,
    database_path: Path,
    synced_at: datetime,
) -> SyncResult:
    """Replace one project's catalog rows with its current redacted capsules."""

    if not project_key:
        raise CatalogError("invalid-project", "A project key is required.")
    display = _redact(project_display, ContentKind.DISPLAY_METADATA).strip()
    if not display:
        raise CatalogError("invalid-project", "A project display name is required.")
    keys = {
        str(row["project_key"])
        for row in project_db.execute("SELECT DISTINCT project_key FROM sessions")
    }
    if keys and project_key not in keys:
        raise CatalogError(
            "project-mismatch",
            "The database does not belong to the current project.",
        )

    rows = project_db.execute(
        """
        SELECT s.source_id, s.session_handle, s.adapter, s.started_at, s.updated_at,
               s.health, s.native_available, s.title, c.search_text, c.content_json
        FROM sessions AS s
        JOIN capsules AS c USING(source_id)
        WHERE s.project_key = ?
        ORDER BY s.started_at, s.source_id
        """,
        (project_key,),
    ).fetchall()
    stored_path = str(database_path.expanduser().resolve())
    stamp = rfc3339(synced_at)
    upserted = 0
    skipped = 0
    kept: list[str] = []
    catalog.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            handle = row["session_handle"]
            if not isinstance(handle, str) or not handle:
                skipped += 1
                continue
            source_id = str(row["source_id"])
            search_text = _redact(str(row["search_text"]), ContentKind.VISIBLE_TEXT)
            title = _title_from_row(row)
            _upsert_session(
                catalog,
                source_id=source_id,
                project_key=project_key,
                project_display=display,
                database_path=stored_path,
                adapter=str(row["adapter"]),
                project_handle=handle,
                title=title,
                health=str(row["health"]),
                native_available=1 if int(row["native_available"]) else 0,
                started_at=str(row["started_at"]),
                updated_at=str(row["updated_at"]),
                synced_at=stamp,
                search_text=search_text,
            )
            kept.append(source_id)
            upserted += 1
        removed = _remove_missing(catalog, project_key, kept)
        catalog.execute("COMMIT")
    except BaseException:
        catalog.execute("ROLLBACK")
        raise
    return SyncResult(upserted=upserted, removed=removed, skipped=skipped)


def recall(
    catalog: sqlite3.Connection,
    query: str,
    *,
    harness: str | None = None,
    limit: int = 20,
    include_unavailable: bool = False,
) -> tuple[RecallHit, ...]:
    """Search redacted catalog text. Ranking is FTS5 rank, then recency."""

    if not query or not query.strip():
        raise CatalogError("empty-query", "A recall query is required.")
    if not 1 <= limit <= 100:
        raise CatalogError("invalid-limit", "Recall limit must be between 1 and 100.")
    filters = ["1 = 1"]
    parameters: list[object] = [query]
    if harness is not None:
        filters.append("s.adapter = ?")
        parameters.append(harness)
    if not include_unavailable:
        filters.append("s.native_available = 1")
    parameters.append(limit)
    try:
        rows = catalog.execute(
            f"""
            SELECT s.source_id, s.catalog_handle, s.project_handle, s.project_display,
                   s.project_key, s.adapter, s.title, s.updated_at, s.health,
                   s.native_available,
                   snippet(catalog_fts, 2, ?, ?, ?, ?) AS snippet
            FROM catalog_fts
            JOIN catalog_sessions AS s ON s.source_id = catalog_fts.source_id
            WHERE catalog_fts MATCH ? AND {' AND '.join(filters)}
            ORDER BY rank, s.updated_at DESC, s.source_id
            LIMIT ?
            """,
            (*_RECALL_SNIPPET_MARKERS, *parameters),
        ).fetchall()
    except sqlite3.OperationalError as error:
        raise CatalogError("malformed-query", "The recall query is not valid FTS5.") from error
    return tuple(_hit(row) for row in rows)


def forget_project(path: Path, project_key: str) -> int:
    """Drop one project's catalog rows when a catalog file already exists."""

    if not path.expanduser().is_file():
        return 0
    catalog = open_catalog(path)
    try:
        catalog.execute("BEGIN IMMEDIATE")
        try:
            removed = _remove_missing(catalog, project_key, [])
            catalog.execute("COMMIT")
        except BaseException:
            catalog.execute("ROLLBACK")
            raise
        return removed
    finally:
        catalog.close()


def _migrate(connection: sqlite3.Connection) -> None:
    current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    for version, statements in _MIGRATIONS:
        if version <= current:
            continue
        if version != current + 1:
            raise CatalogError(
                "catalog-schema",
                f"Missing catalog migration between {current} and {version}.",
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
    if current != CATALOG_SCHEMA_VERSION:
        raise CatalogError("catalog-schema", "The global catalog schema is not current.")


def _upsert_session(
    catalog: sqlite3.Connection,
    *,
    source_id: str,
    project_key: str,
    project_display: str,
    database_path: str,
    adapter: str,
    project_handle: str,
    title: str | None,
    health: str,
    native_available: int,
    started_at: str,
    updated_at: str,
    synced_at: str,
    search_text: str,
) -> None:
    existing = catalog.execute(
        "SELECT catalog_handle FROM catalog_sessions WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    handle = (
        str(existing["catalog_handle"])
        if existing is not None
        else _allocate_handle(catalog, adapter)
    )
    catalog.execute(
        """
        INSERT INTO catalog_sessions(
            source_id, project_key, project_display, database_path, adapter,
            catalog_handle, project_handle, title, health, native_available,
            started_at, updated_at, synced_at, search_text
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            project_key=excluded.project_key,
            project_display=excluded.project_display,
            database_path=excluded.database_path,
            adapter=excluded.adapter,
            catalog_handle=excluded.catalog_handle,
            project_handle=excluded.project_handle,
            title=excluded.title,
            health=excluded.health,
            native_available=excluded.native_available,
            started_at=excluded.started_at,
            updated_at=excluded.updated_at,
            synced_at=excluded.synced_at,
            search_text=excluded.search_text
        """,
        (
            source_id,
            project_key,
            project_display,
            database_path,
            adapter,
            handle,
            project_handle,
            title,
            health,
            native_available,
            started_at,
            updated_at,
            synced_at,
            search_text,
        ),
    )
    catalog.execute("DELETE FROM catalog_fts WHERE source_id = ?", (source_id,))
    catalog.execute(
        """
        INSERT INTO catalog_fts(source_id, project_key, search_text)
        VALUES (?, ?, ?)
        """,
        (source_id, project_key, search_text),
    )


def _allocate_handle(catalog: sqlite3.Connection, adapter: str) -> str:
    prefix = {
        "codex": "C",
        "grok": "G",
        "opencode": "O",
        "cursor": "R",
        "claude": "L",
        "antigravity": "A",
        "openclaw": "W",
        "grokbot": "B",
    }.get(adapter, "S")
    row = catalog.execute(
        "SELECT next_number FROM catalog_handle_counters WHERE prefix = ?",
        (prefix,),
    ).fetchone()
    if row is None:
        number = 1
        catalog.execute(
            "INSERT INTO catalog_handle_counters(prefix, next_number) VALUES (?, ?)",
            (prefix, 2),
        )
    else:
        number = int(row["next_number"])
        catalog.execute(
            "UPDATE catalog_handle_counters SET next_number = ? WHERE prefix = ?",
            (number + 1, prefix),
        )
    return f"{prefix}{number}"


def _remove_missing(
    catalog: sqlite3.Connection, project_key: str, kept: Sequence[str]
) -> int:
    rows = catalog.execute(
        "SELECT source_id FROM catalog_sessions WHERE project_key = ? ORDER BY source_id",
        (project_key,),
    ).fetchall()
    keep = set(kept)
    removed = 0
    for row in rows:
        source_id = str(row["source_id"])
        if source_id in keep:
            continue
        catalog.execute("DELETE FROM catalog_fts WHERE source_id = ?", (source_id,))
        catalog.execute(
            "DELETE FROM catalog_sessions WHERE source_id = ?", (source_id,)
        )
        removed += 1
    return removed


def _title_from_row(row: sqlite3.Row) -> str | None:
    raw = row["title"]
    if not isinstance(raw, str) or not raw.strip():
        try:
            content = json.loads(row["content_json"])
        except json.JSONDecodeError:
            content = None
        display = content.get("display_name") if isinstance(content, dict) else None
        raw = display if isinstance(display, str) else None
    if not isinstance(raw, str) or not raw.strip():
        return None
    redacted = _redact(raw, ContentKind.TITLE).strip()
    return redacted[:256] or None


def _redact(text: str, kind: ContentKind) -> str:
    return required_redaction(
        DEFAULT_REDACTOR,
        RedactionSeam.CAPSULE_PERSISTENCE,
        kind,
        text,
    ).text


def _hit(row: sqlite3.Row) -> RecallHit:
    title = row["title"]
    snippet = row["snippet"]
    return RecallHit(
        source_id=str(row["source_id"]),
        catalog_handle=str(row["catalog_handle"]),
        project_handle=str(row["project_handle"]),
        project_display=str(row["project_display"]),
        project_key=str(row["project_key"]),
        harness=str(row["adapter"]),
        title=str(title) if isinstance(title, str) else None,
        updated_at=str(row["updated_at"]),
        health=str(row["health"]),
        native_available=bool(row["native_available"]),
        snippet=str(snippet) if isinstance(snippet, str) else None,
    )
