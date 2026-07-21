"""Transactional repositories for Tang-derived session data."""

from __future__ import annotations

import json
import sqlite3
from collections import deque
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
from tang.redaction import (
    DEFAULT_REDACTOR,
    TITLE_CHARACTER_LIMIT,
    ContentKind,
    RedactionSeam,
    required_redaction,
)
from tang.timeutil import rfc3339


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


@dataclass(frozen=True, slots=True)
class StoredSession:
    source: SourceRecord
    project_key: str
    handle: str
    indexed_at: datetime
    native_available: bool = True


@dataclass(frozen=True, slots=True)
class StoredGraphSession:
    """One graph node's session state and cached capsule title."""

    session: StoredSession
    title: str | None


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
    handle: str
    harness: str
    updated_at: datetime
    health: SessionHealth
    title: str | None
    capabilities: tuple[str, ...]
    display_name: str | None = None
    first_user_excerpt: str | None = None
    snippet: str | None = None
    model_provider: str | None = None
    model_id: str | None = None
    effort: str | None = None
    title_origin: str | None = None
    visible_turn_count: int | None = None
    visible_text_bytes: int | None = None


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
        title = self._persisted_title(source.title)
        handle = self._existing_or_next_handle(
            source.identity.canonical, project_key, source.identity.adapter
        )
        self._connection.execute(
            """
            INSERT INTO sessions(
                source_id, project_key, session_handle, adapter, source_namespace, native_id,
                locator, fingerprint_algorithm, fingerprint_value, project_hint,
                started_at, updated_at, health, title, indexed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_id) DO UPDATE SET
                project_key=excluded.project_key,
                session_handle=excluded.session_handle,
                locator=excluded.locator,
                fingerprint_algorithm=excluded.fingerprint_algorithm,
                fingerprint_value=excluded.fingerprint_value,
                project_hint=excluded.project_hint,
                started_at=excluded.started_at,
                updated_at=excluded.updated_at,
                health=excluded.health,
                title=COALESCE(excluded.title, sessions.title),
                indexed_at=excluded.indexed_at,
                native_available=1
            """,
            (
                source.identity.canonical,
                project_key,
                handle,
                source.identity.adapter,
                source.identity.source_namespace,
                source.identity.native_id,
                source.locator.value,
                source.fingerprint.algorithm,
                source.fingerprint.value,
                source.project_hint,
                rfc3339(source.started_at),
                rfc3339(source.updated_at),
                source.health.value,
                title,
                rfc3339(indexed_at),
            ),
        )

    @staticmethod
    def _persisted_title(title: str | None) -> str | None:
        if title is None:
            return None
        redacted = required_redaction(
            DEFAULT_REDACTOR,
            RedactionSeam.CAPSULE_PERSISTENCE,
            ContentKind.TITLE,
            title,
        ).text[:TITLE_CHARACTER_LIMIT]
        return redacted or None

    @staticmethod
    def _handle_prefix(adapter: str) -> str:
        return {
            "codex": "C",
            "grok": "G",
            "opencode": "O",
            "cursor": "R",
        }.get(adapter, "S")

    def _existing_or_next_handle(
        self, source_id: str, project_key: str, adapter: str
    ) -> str:
        existing = self._connection.execute(
            "SELECT project_key, session_handle FROM sessions WHERE source_id = ?",
            (source_id,),
        ).fetchone()
        if (
            existing is not None
            and existing["project_key"] == project_key
            and existing["session_handle"] is not None
        ):
            return str(existing["session_handle"])
        prefix = self._handle_prefix(adapter)
        rows = self._connection.execute(
            """
            SELECT session_handle FROM sessions
            WHERE project_key = ? AND session_handle LIKE ?
            """,
            (project_key, f"{prefix}%"),
        ).fetchall()
        numbers = [
            int(str(row["session_handle"])[1:])
            for row in rows
            if str(row["session_handle"])[1:].isdigit()
        ]
        return f"{prefix}{max(numbers, default=0) + 1}"

    def resolve_session_token(self, token: str, project_key: str) -> str:
        """Resolve a simple project handle while preserving exact canonical IDs."""

        if not token or token.strip() != token:
            raise ValueError("session token must be non-empty and trimmed")
        if ":" in token:
            return SessionIdentity.from_canonical(token).canonical
        normalized = token.upper()
        if (
            len(normalized) < 2
            or not normalized.isascii()
            or not normalized.isalnum()
            or not normalized[0].isalpha()
            or not normalized[1:].isdigit()
            or normalized[1] == "0"
        ):
            raise ValueError("session handle must be a letter followed by a number")
        row = self._connection.execute(
            """
            SELECT source_id FROM sessions
            WHERE project_key = ? AND session_handle = ?
            """,
            (project_key, normalized),
        ).fetchone()
        if row is None:
            raise ValueError("session handle is not indexed in the current project")
        return str(row["source_id"])

    def handle_for_source_id(self, source_id: str) -> str:
        row = self._connection.execute(
            "SELECT session_handle FROM sessions WHERE source_id = ?", (source_id,)
        ).fetchone()
        if row is None or row["session_handle"] is None:
            raise ValueError("session is not indexed")
        return str(row["session_handle"])

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

    def set_derived_title(self, source_id: str, title: str) -> None:
        """Synchronize a refreshed Capsule label for a session without native title."""

        self._require_transaction()
        self._connection.execute(
            "UPDATE sessions SET title = ? WHERE source_id = ?", (title, source_id)
        )

    def graph_sessions(
        self, project_key: str, source_ids: tuple[str, ...]
    ) -> tuple[StoredGraphSession, ...]:
        """Fetch graph-node state and titles in one bounded project query."""

        identities = tuple(sorted(set(source_ids)))
        if not identities:
            return ()
        placeholders = ", ".join("?" for _ in identities)
        rows = self._connection.execute(
            f"""
            SELECT s.*, c.content_json
            FROM sessions AS s
            LEFT JOIN capsules AS c USING(source_id)
            WHERE s.project_key = ? AND s.source_id IN ({placeholders})
            ORDER BY s.source_id
            """,
            (project_key, *identities),
        ).fetchall()
        return tuple(
            StoredGraphSession(
                session=self._stored_session(row),
                title=self._capsule_title(row["content_json"]) or row["title"],
            )
            for row in rows
        )

    @staticmethod
    def _capsule_title(content_json: str | None) -> str | None:
        if content_json is None:
            return None
        content = json.loads(content_json)
        for field in ("source_title", "display_name"):
            title = content.get(field)
            if isinstance(title, str) and title.strip():
                return title
        return None

    def backfill_untitled_sessions(self, project_key: str) -> int:
        """Persist safe Capsule labels for legacy sessions without native titles."""

        self._require_transaction()
        rows = self._connection.execute(
            """
            SELECT s.source_id, c.content_json
            FROM sessions AS s
            JOIN capsules AS c USING(source_id)
            WHERE s.project_key = ? AND (s.title IS NULL OR trim(s.title) = '')
            ORDER BY s.source_id
            """,
            (project_key,),
        ).fetchall()
        backfilled = 0
        for row in rows:
            title = self._persisted_title(self._capsule_title(row["content_json"]))
            if title is None:
                continue
            result = self._connection.execute(
                """
                UPDATE sessions SET title = ?
                WHERE source_id = ? AND (title IS NULL OR trim(title) = '')
                """,
                (title, row["source_id"]),
            )
            backfilled += result.rowcount
        return backfilled

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
                title=row["title"],
            ),
            project_key=row["project_key"],
            handle=row["session_handle"],
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

    def insert_continuation_if_absent(self, continuation: StoredContinuation) -> bool:
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
                rfc3339(continuation.confirmed_at),
                continuation.schema_version,
            ),
        )
        return cursor.rowcount == 1

    def confirmed_predecessors(
        self, anchor_id: str, project_key: str, *, max_hops: int | None = None
    ) -> tuple[str, ...]:
        """Return deterministic confirmed ancestors of one project session.

        ``max_hops`` counts continuation edges backward from ``anchor_id``.
        ``None`` includes the complete confirmed ancestry.  The anchor itself is
        deliberately omitted because a Context Pack contains predecessor
        evidence, not the active continuation target.
        """

        if max_hops is not None and max_hops < 1:
            raise ValueError("ancestor depth must be at least 1")
        anchor = self.get_session(anchor_id)
        if anchor is None or anchor.project_key != project_key:
            raise ValueError("anchor session is not indexed in the current project")

        incoming: dict[str, list[str]] = {}
        for edge in self.continuations_for_project(project_key):
            incoming.setdefault(edge.target_id, []).append(edge.source_id)
        for sources in incoming.values():
            sources.sort()

        found: set[str] = set()
        pending: deque[tuple[str, int]] = deque(((anchor_id, 0),))
        while pending:
            target_id, depth = pending.popleft()
            if max_hops is not None and depth >= max_hops:
                continue
            for source_id in incoming.get(target_id, []):
                if source_id in found:
                    continue
                found.add(source_id)
                pending.append((source_id, depth + 1))

        sessions = {
            session.source.identity.canonical: session
            for session in self.sessions_for_project(project_key)
        }
        return tuple(
            sorted(
                found,
                key=lambda source_id: (
                    sessions[source_id].source.updated_at,
                    source_id,
                ),
            )
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
                rfc3339(updated_at),
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
                rfc3339(capsule.updated_at),
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

    def discovery_source_ids(
        self,
        project_key: str,
        *,
        adapter: str,
        native_id: str | None = None,
    ) -> tuple[str, ...]:
        """Return exact discoverable identities for current-session exclusion."""

        conditions = ["s.project_key = ?", "s.adapter = ?"]
        parameters = [project_key, adapter]
        if native_id is not None:
            conditions.append("s.native_id = ?")
            parameters.append(native_id)
        rows = self._connection.execute(
            f"""
            SELECT s.source_id
            FROM sessions AS s JOIN capsules AS c USING(source_id)
            WHERE {' AND '.join(conditions)}
            ORDER BY s.source_id
            """,
            parameters,
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
        exclude_source_ids: tuple[str, ...] = (),
        limit: int | None = None,
    ) -> tuple[DiscoveryRow, ...]:
        conditions, parameters = self._discovery_filters(
            project_key,
            harness=harness,
            health=health,
            since=since,
            until=until,
            exclude_source_ids=exclude_source_ids,
        )
        query = f"""
            SELECT s.source_id, s.session_handle, s.adapter, s.updated_at, s.health, c.content_json
            FROM sessions AS s JOIN capsules AS c USING(source_id)
            WHERE {' AND '.join(conditions)}
            ORDER BY s.updated_at DESC, s.source_id
            """
        bind: list[object] = list(parameters)
        if limit is not None:
            if limit < 1:
                raise ValueError("browse_discovery limit must be at least 1")
            query += "\n            LIMIT ?"
            bind.append(limit)
        rows = self._connection.execute(query, bind).fetchall()
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
        exclude_source_ids: tuple[str, ...] = (),
    ) -> tuple[DiscoveryRow, ...]:
        if not query.strip():
            raise ValueError("search query must not be empty")
        conditions, parameters = self._discovery_filters(
            project_key,
            harness=harness,
            health=health,
            since=since,
            until=until,
            exclude_source_ids=exclude_source_ids,
        )
        try:
            rows = self._connection.execute(
                f"""
                SELECT s.source_id, s.session_handle, s.adapter, s.updated_at, s.health, c.content_json,
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
        exclude_source_ids: tuple[str, ...] = (),
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
            parameters.append(rfc3339(since))
        if until is not None:
            conditions.append("s.updated_at <= ?")
            parameters.append(rfc3339(until))
        excluded = tuple(sorted(set(exclude_source_ids)))
        if excluded:
            conditions.append(
                f"s.source_id NOT IN ({', '.join('?' for _ in excluded)})"
            )
            parameters.extend(excluded)
        return conditions, parameters

    @staticmethod
    def _discovery_row(row: sqlite3.Row, snippet: str | None = None) -> DiscoveryRow:
        content = json.loads(row["content_json"])
        capabilities = content.get("capabilities", [])
        raw_excerpts = content.get("excerpts", [])
        excerpts = raw_excerpts if isinstance(raw_excerpts, list) else []
        raw_header = content.get("session_header")
        header = raw_header if isinstance(raw_header, dict) else {}

        def optional_text(key: str) -> str | None:
            value = header.get(key)
            return value if isinstance(value, str) else None

        def optional_count(key: str) -> int | None:
            value = header.get(key)
            return value if type(value) is int and value >= 0 else None
        first_user_excerpt = next(
            (
                excerpt.get("text")
                for excerpt in excerpts
                if isinstance(excerpt, dict)
                and excerpt.get("role") == "user"
                and isinstance(excerpt.get("text"), str)
            ),
            None,
        )
        return DiscoveryRow(
            source_id=row["source_id"],
            handle=row["session_handle"],
            harness=row["adapter"],
            updated_at=_datetime(row["updated_at"]),
            health=SessionHealth(row["health"]),
            title=(
                content["source_title"]
                if isinstance(content.get("source_title"), str)
                else None
            ),
            capabilities=tuple(str(value) for value in capabilities),
            display_name=(
                content["display_name"]
                if isinstance(content.get("display_name"), str)
                else None
            ),
            first_user_excerpt=first_user_excerpt,
            snippet=snippet if snippet is not None else first_user_excerpt,
            model_provider=optional_text("model_provider"),
            model_id=optional_text("model_id"),
            effort=optional_text("effort"),
            title_origin=optional_text("title_origin"),
            visible_turn_count=optional_count("visible_turn_count"),
            visible_text_bytes=optional_count("visible_text_bytes"),
        )
