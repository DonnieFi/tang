"""Qualified user-facing descriptions for conservative session health."""

from __future__ import annotations

from tang.adapters import SessionHealth


def describe_health(health: SessionHealth) -> str:
    """Describe native evidence without claiming definitive process state."""

    return {
        SessionHealth.COMPLETE: "Last observed native task completed",
        SessionHealth.POSSIBLY_INTERRUPTED: "Possibly interrupted; native evidence is incomplete",
        SessionHealth.UNKNOWN: "Status unknown; native evidence is insufficient",
    }[health]
