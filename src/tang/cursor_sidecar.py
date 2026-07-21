"""Read Cursor chat sidecars without pulling SQLite into adapter modules."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_store_session_meta(chat_dir: Path) -> dict[str, Any] | None:
    """Return decoded store.db meta row when present and readable."""

    db_path = chat_dir / "store.db"
    if not db_path.is_file():
        return None
    wal_path = db_path.with_name(f"{db_path.name}-wal")
    query = "mode=ro" if wal_path.is_file() else "mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(f"file:{db_path}?{query}", uri=True)
    except sqlite3.Error:
        return None
    try:
        row = connection.execute(
            "SELECT value FROM meta WHERE key = ?", ("0",)
        ).fetchone()
        if row is None:
            return None
        raw = row[0]
        if not isinstance(raw, str):
            return None
        decoded = json.loads(bytes.fromhex(raw).decode("utf-8"))
        return decoded if isinstance(decoded, dict) else None
    except (json.JSONDecodeError, UnicodeError, ValueError, sqlite3.Error):
        return None
    finally:
        connection.close()


def epoch_millis(value: object) -> datetime | None:
    # bool is a subclass of int; reject it so True/False never become timestamps.
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        millis = value
    elif isinstance(value, float) and value.is_integer():
        millis = int(value)
    else:
        return None
    if millis < 0:
        return None
    return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
