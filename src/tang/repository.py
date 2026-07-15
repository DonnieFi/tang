"""Transactional repositories for Tang-derived session data."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

from tang.adapters import (
    AdapterCheckpoint,
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("repository timestamps must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


@dataclass(frozen=True, slots=True)
class StoredSession:
    source: SourceRecord
    project_key: str
    indexed_at: datetime
    native_available: bool = True


@dataclass(frozen=True, slots=True)
class StoredContinuation:
    source_id: str
    target_id: str
    project_key: str
    confirmation_mode: str
    confirmed_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.source_id == self.target_id:
            raise ValueError("continuation source and target must differ")
        if self.confirmation_mode not in {"current", "explicit"}:
            raise ValueError("unsupported confirmation mode")
        if self.schema_version != 1:
            raise ValueError("continuation schema_version must be 1")
        if self.confirmed_at.tzinfo is None or self.confirmed_at.utcoffset() is None:
            raise ValueError("continuation timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class StoredCapsule:
    source_id: str
    project_key: str
    content: dict[str, object]
    search_text: str
    byte_count: int
    updated_at: datetime
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("capsule schema_version must be 1")
        if self.byte_count != len(
            json.dumps(
                self.content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ):
            raise ValueError("capsule byte_count must match canonical JSON")
        if self.byte_count > 8_192:
            raise ValueError("capsule exceeds 8 KiB")


@dataclass(frozen=True, slots=True)
class DiscoveryRow:
    source_id: str
    harness: str
    updated_at: datetime
    health: SessionHealth
    title: str | None
    capabilities: tuple[str, ...]
    snippet: str | None = None


@dataclass(frozen=True, slots=True)
class PurgeResult:
    sessions: int
    capsules: int
    search_rows: int
    checkpoints: int
    continuations: int = 0


class TangRepository:
    """Own SQL and transaction mechanics behind typed operations."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @contextmanager
    def transaction(self) -> Iterator[None]:
        if self._connection.in_transaction:
            raise RuntimeError("nested repository transactions are unsupported")
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._connection.execute("ROLLBACK")
            raise
        else:
            self._connection.execute("COMMIT")

    def _require_transaction(self) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("repository writes require an explicit transaction")

    def upsert_session(
        self, source: SourceRecord, project_key: str, indexed_at: datetime
    ) -> None:
        self._require_transaction()
        self._connection.execute(
            """
            INSERT INTO sessions(
                source_id, project_key, adapter, source_namespace, native_id,
                locator, fingerprint_algorithm, fingerprint_value, project_hint,
                started_at, updated_at, health, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                project_key=excluded.project_key,
                locator=excluded.locator,
                fingerprint_algorithm=excluded.fingerprint_algorithm,
                fingerprint_value=excluded.fingerprint_value,
                project_hint=excluded.project_hint,
                started_at=excluded.started_at,
                updated_at=excluded.updated_at,
                health=excluded.health,
                indexed_at=excluded.indexed_at,
                native_available=1
            """,
            (
                source.identity.canonical,
                project_key,
                source.identity.adapter,
                source.identity.source_namespace,
                source.identity.native_id,
                source.locator.value,
                source.fingerprint.algorithm,
                source.fingerprint.value,
                source.project_hint,
                _rfc3339(source.started_at),
                _rfc3339(source.updated_at),
                source.health.value,
                _rfc3339(indexed_at),
            ),
        )

    def get_session(self, source_id: str) -> StoredSession | None:
        row = self._connection.execute(
            "SELECT * FROM sessions WHERE source_id = ?", (source_id,)
        ).fetchone()
        return None if row is None else self._stored_session(row)

    def sessions_for_project(self, project_key: str) -> tuple[StoredSession, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM sessions
            WHERE project_key = ?
            ORDER BY updated_at DESC, source_id
            """,
            (project_key,),
        ).fetchall()
        return tuple(self._stored_session(row) for row in rows)

    @staticmethod
    def _stored_session(row: sqlite3.Row) -> StoredSession:
        identity = SessionIdentity(
            row["adapter"], row["source_namespace"], row["native_id"]
        )
        return StoredSession(
            source=SourceRecord(
                identity=identity,
                locator=OpaqueSourceLocator(row["locator"]),
                fingerprint=SourceFingerprint(
                    row["fingerprint_algorithm"], row["fingerprint_value"]
                ),
                project_hint=row["project_hint"],
                started_at=_datetime(row["started_at"]),
                updated_at=_datetime(row["updated_at"]),
                health=SessionHealth(row["health"]),
            ),
            project_key=row["project_key"],
            indexed_at=_datetime(row["indexed_at"]),
            native_available=bool(row["native_available"]),
        )

    def delete_session(self, source_id: str) -> None:
        self._require_transaction()
        self._connection.execute("DELETE FROM capsules_fts WHERE source_id = ?", (source_id,))
        self._connection.execute("DELETE FROM capsules WHERE source_id = ?", (source_id,))
        referenced = self._connection.execute(
            """
            SELECT 1 FROM continuation_edges
            WHERE source_id = ? OR target_id = ? LIMIT 1
            """,
            (source_id, source_id),
        ).fetchone()
        if referenced is None:
            self._connection.execute("DELETE FROM sessions WHERE source_id = ?", (source_id,))
        else:
            self._connection.execute(
                "UPDATE sessions SET native_available = 0 WHERE source_id = ?",
                (source_id,),
            )

    def put_continuation(self, continuation: StoredContinuation) -> bool:
        """Insert one confirmed edge; return false when it already exists."""

        self._require_transaction()
        cursor = self._connection.execute(
            """
            INSERT INTO continuation_edges(
                source_id, target_id, project_key, confirmation_mode,
                confirmed_at, schema_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id, target_id) DO NOTHING
            """,
            (
                continuation.source_id,
                continuation.target_id,
                continuation.project_key,
                continuation.confirmation_mode,
                _rfc3339(continuation.confirmed_at),
                continuation.schema_version,
            ),
        )
        return cursor.rowcount == 1

    def continuations_for_project(
        self, project_key: str
    ) -> tuple[StoredContinuation, ...]:
        rows = self._connection.execute(
            """
            SELECT * FROM continuation_edges WHERE project_key = ?
            ORDER BY confirmed_at, source_id, target_id
            """,
            (project_key,),
        ).fetchall()
        return tuple(
            StoredContinuation(
                source_id=row["source_id"],
                target_id=row["target_id"],
                project_key=row["project_key"],
                confirmation_mode=row["confirmation_mode"],
                confirmed_at=_datetime(row["confirmed_at"]),
                schema_version=row["schema_version"],
            )
            for row in rows
        )

    def purge_all(self) -> PurgeResult:
        """Delete every currently defined Tang-derived row in one transaction."""

        self._require_transaction()
        result = PurgeResult(
            sessions=self._count("sessions"),
            capsules=self._count("capsules"),
            search_rows=self._count("capsules_fts"),
            checkpoints=self._count("adapter_checkpoints"),
            continuations=self._count("continuation_edges"),
        )
        self._connection.execute("DELETE FROM continuation_edges")
        self._connection.execute("DELETE FROM capsules_fts")
        self._connection.execute("DELETE FROM capsules")
        self._connection.execute("DELETE FROM sessions")
        self._connection.execute("DELETE FROM adapter_checkpoints")
        return result

    def _count(self, table: str) -> int:
        if table not in {
            "sessions",
            "capsules",
            "capsules_fts",
            "adapter_checkpoints",
            "continuation_edges",
        }:
            raise ValueError("unsupported derived-data table")
        row = self._connection.execute(f"SELECT count(*) FROM {table}").fetchone()
        return int(row[0])

    def fingerprint_for(self, source_id: str) -> SourceFingerprint | None:
        row = self._connection.execute(
            """
            SELECT fingerprint_algorithm, fingerprint_value
            FROM sessions WHERE source_id = ?
            """,
            (source_id,),
        ).fetchone()
        if row is None:
            return None
        return SourceFingerprint(row["fingerprint_algorithm"], row["fingerprint_value"])

    def put_checkpoint(
        self, checkpoint: AdapterCheckpoint, project_key: str, updated_at: datetime
    ) -> None:
        self._require_transaction()
        self._connection.execute(
            """
            INSERT INTO adapter_checkpoints(
                adapter, source_namespace, project_key, cursor, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(adapter, source_namespace, project_key) DO UPDATE SET
                cursor=excluded.cursor, updated_at=excluded.updated_at
            """,
            (
                checkpoint.adapter,
                checkpoint.source_namespace,
                project_key,
                checkpoint.cursor,
                _rfc3339(updated_at),
            ),
        )

    def get_checkpoint(
        self, adapter: str, source_namespace: str, project_key: str
    ) -> AdapterCheckpoint | None:
        row = self._connection.execute(
            """
            SELECT cursor FROM adapter_checkpoints
            WHERE adapter = ? AND source_namespace = ? AND project_key = ?
            """,
            (adapter, source_namespace, project_key),
        ).fetchone()
        if row is None:
            return None
        return AdapterCheckpoint(adapter, source_namespace, row["cursor"])

    def put_capsule(self, capsule: StoredCapsule) -> None:
        self._require_transaction()
        parent = self._connection.execute(
            "SELECT project_key FROM sessions WHERE source_id = ?",
            (capsule.source_id,),
        ).fetchone()
        if parent is None or parent["project_key"] != capsule.project_key:
            raise ValueError("capsule must match an existing session project")
        content_json = json.dumps(
            capsule.content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        self._connection.execute(
            """
            INSERT INTO capsules(
                source_id, project_key, schema_version, content_json,
                search_text, byte_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                project_key=excluded.project_key,
                schema_version=excluded.schema_version,
                content_json=excluded.content_json,
                search_text=excluded.search_text,
                byte_count=excluded.byte_count,
                updated_at=excluded.updated_at
            """,
            (
                capsule.source_id,
                capsule.project_key,
                capsule.schema_version,
                content_json,
                capsule.search_text,
                capsule.byte_count,
                _rfc3339(capsule.updated_at),
            ),
        )
        self._connection.execute(
            "DELETE FROM capsules_fts WHERE source_id = ?", (capsule.source_id,)
        )
        self._connection.execute(
            "INSERT INTO capsules_fts(source_id, project_key, search_text) VALUES (?, ?, ?)",
            (capsule.source_id, capsule.project_key, capsule.search_text),
        )

    def get_capsule(self, source_id: str) -> StoredCapsule | None:
        row = self._connection.execute(
            "SELECT * FROM capsules WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None:
            return None
        return StoredCapsule(
            source_id=row["source_id"],
            project_key=row["project_key"],
            content=json.loads(row["content_json"]),
            search_text=row["search_text"],
            byte_count=row["byte_count"],
            updated_at=_datetime(row["updated_at"]),
            schema_version=row["schema_version"],
        )

    def search_capsule_ids(
        self, project_key: str, query: str, limit: int = 20
    ) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT source_id FROM capsules_fts
            WHERE capsules_fts MATCH ? AND project_key = ?
            ORDER BY rank, source_id
            LIMIT ?
            """,
            (query, project_key, limit),
        ).fetchall()
        return tuple(row["source_id"] for row in rows)

    def browse_discovery(
        self,
        project_key: str,
        *,
        harness: str | None = None,
        health: SessionHealth | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> tuple[DiscoveryRow, ...]:
        conditions, parameters = self._discovery_filters(
            project_key, harness=harness, health=health, since=since, until=until
        )
        rows = self._connection.execute(
            f"""
            SELECT s.source_id, s.adapter, s.updated_at, s.health, c.content_json
            FROM sessions AS s JOIN capsules AS c USING(source_id)
            WHERE {' AND '.join(conditions)}
            ORDER BY s.updated_at DESC, s.source_id
            """,
            parameters,
        ).fetchall()
        return tuple(self._discovery_row(row) for row in rows)

    def search_discovery(
        self,
        project_key: str,
        query: str,
        *,
        harness: str | None = None,
        health: SessionHealth | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 20,
    ) -> tuple[DiscoveryRow, ...]:
        if not query.strip():
            raise ValueError("search query must not be empty")
        conditions, parameters = self._discovery_filters(
            project_key, harness=harness, health=health, since=since, until=until
        )
        try:
            rows = self._connection.execute(
                f"""
                SELECT s.source_id, s.adapter, s.updated_at, s.health, c.content_json,
                       snippet(capsules_fts, 2, '[', ']', ' … ', 18) AS snippet
                FROM capsules_fts
                JOIN sessions AS s USING(source_id)
                JOIN capsules AS c USING(source_id)
                WHERE capsules_fts MATCH ? AND {' AND '.join(conditions)}
                ORDER BY rank, s.updated_at DESC, s.source_id
                LIMIT ?
                """,
                (query, *parameters, limit),
            ).fetchall()
        except sqlite3.OperationalError as error:
            raise ValueError("malformed FTS query") from error
        return tuple(self._discovery_row(row, row["snippet"]) for row in rows)

    @staticmethod
    def _discovery_filters(
        project_key: str,
        *,
        harness: str | None,
        health: SessionHealth | None,
        since: datetime | None,
        until: datetime | None,
    ) -> tuple[list[str], list[str]]:
        conditions = ["s.project_key = ?"]
        parameters = [project_key]
        if harness is not None:
            conditions.append("s.adapter = ?")
            parameters.append(harness)
        if health is not None:
            conditions.append("s.health = ?")
            parameters.append(health.value)
        if since is not None:
            conditions.append("s.updated_at >= ?")
            parameters.append(_rfc3339(since))
        if until is not None:
            conditions.append("s.updated_at <= ?")
            parameters.append(_rfc3339(until))
        return conditions, parameters

    @staticmethod
    def _discovery_row(row: sqlite3.Row, snippet: str | None = None) -> DiscoveryRow:
        content = json.loads(row["content_json"])
        capabilities = content.get("capabilities", [])
        return DiscoveryRow(
            source_id=row["source_id"],
            harness=row["adapter"],
            updated_at=_datetime(row["updated_at"]),
            health=SessionHealth(row["health"]),
            title=content.get("source_title"),
            capabilities=tuple(str(value) for value in capabilities),
            snippet=snippet,
        )
