"""Canonical timestamp formatting shared by persisted and displayed contracts."""

from __future__ import annotations

from datetime import datetime, timezone


def rfc3339(value: datetime) -> str:
    """Render one timezone-aware timestamp as deterministic RFC 3339 UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("RFC 3339 timestamps must be timezone-aware")
    utc = value.astimezone(timezone.utc)
    timespec = "microseconds" if utc.microsecond else "seconds"
    return utc.isoformat(timespec=timespec).replace("+00:00", "Z")


def optional_rfc3339(value: datetime | None) -> str | None:
    """Render an optional timestamp without weakening awareness validation."""

    return None if value is None else rfc3339(value)
