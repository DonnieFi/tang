"""Read-only helpers for OpenClaw agent SQLite session stores."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters.base import SessionHeader, SourceFingerprint


@dataclass(frozen=True, slots=True)
class OpenClawSession:
    session_key: str
    session_id: str
    title: str | None
    started_at: datetime
    updated_at: datetime
    header: SessionHeader


def load_sessions(agent_db: Path) -> tuple[OpenClawSession, ...]:
    with _connect(agent_db) as connection:
        windows = {
            row["session_key"]: row
            for row in connection.execute(
                """
                SELECT session_key, session_id, started_at, ended_at
                FROM (
                    SELECT session_key, session_id, started_at, ended_at,
                           ROW_NUMBER() OVER (
                               PARTITION BY session_key
                               ORDER BY COALESCE(ended_at, started_at, 0) DESC,
                                        session_id DESC
                           ) AS rn
                    FROM session_windows
                )
                WHERE rn = 1
                """
            )
        }
        rows = connection.execute(
            """
            SELECT session_key, display_name, label, created_at,
                   updated_at, last_activity_at
            FROM session_nodes
            ORDER BY session_key
            """
        ).fetchall()

    sessions: list[OpenClawSession] = []
    for row in rows:
        session_key = str(row["session_key"])
        window = windows.get(session_key)
        if window is None:
            continue
        title = _title(row["display_name"], row["label"])
        started_at = _epoch_millis(window["started_at"]) or _epoch_millis(
            row["created_at"]
        ) or datetime.fromtimestamp(0, tz=timezone.utc)
        updated_at = (
            _epoch_millis(row["last_activity_at"])
            or _epoch_millis(row["updated_at"])
            or _epoch_millis(window["ended_at"])
            or started_at
        )
        sessions.append(
            OpenClawSession(
                session_key=session_key,
                session_id=str(window["session_id"]),
                title=title,
                started_at=started_at,
                updated_at=updated_at,
                header=SessionHeader(),
            )
        )
    return tuple(sessions)


def fingerprint_session(agent_db: Path, session_id: str) -> SourceFingerprint:
    digest = hashlib.sha256()
    digest.update(session_id.encode("utf-8"))
    with _connect(agent_db) as connection:
        row = connection.execute(
            """
            SELECT MAX(seq) AS max_seq, COUNT(*) AS event_count
            FROM transcript_events
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
    if row is not None:
        digest.update(str(row["max_seq"] or 0).encode())
        digest.update(str(row["event_count"] or 0).encode())
    return SourceFingerprint("sha256", digest.hexdigest())


def has_sessions(agent_db: Path) -> bool:
    if not agent_db.is_file():
        return False
    try:
        with _connect(agent_db) as connection:
            row = connection.execute("SELECT 1 FROM session_nodes LIMIT 1").fetchone()
    except (OSError, sqlite3.Error):
        return False
    return row is not None


def read_message_events(
    agent_db: Path, session_id: str
) -> tuple[tuple[int, dict[str, object]], ...]:
    with _connect(agent_db) as connection:
        rows = connection.execute(
            """
            SELECT seq, event_json
            FROM transcript_events
            WHERE session_id = ?
            ORDER BY seq
            """,
            (session_id,),
        ).fetchall()
    events: list[tuple[int, dict[str, object]]] = []
    for row in rows:
        try:
            payload = json.loads(row["event_json"])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append((int(row["seq"]), payload))
    return tuple(events)


def _connect(agent_db: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{agent_db}?mode=ro", uri=True, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    return connection


def _title(display_name: object, label: object) -> str | None:
    for candidate in (display_name, label):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _epoch_millis(value: object) -> datetime | None:
    if value is None or not isinstance(value, int):
        return None
    seconds = value / 1000 if value > 10**12 else value
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None
