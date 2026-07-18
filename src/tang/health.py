"""Qualified user-facing descriptions for conservative session health."""

from __future__ import annotations

from tang.adapters import SessionHealth


def describe_health(health: SessionHealth) -> str:
    """Describe native evidence without claiming definitive process state.

    ``POSSIBLY_INTERRUPTED`` is reserved for a future evidence-backed native
    pattern. The v0.1 Codex adapter intentionally emits only ``COMPLETE`` or
    ``UNKNOWN`` and the UI must not promise an interruption badge for it.
    """

    return {
        SessionHealth.COMPLETE: "Last observed native task completed",
        SessionHealth.POSSIBLY_INTERRUPTED: "Possibly interrupted; native evidence is incomplete",
        SessionHealth.UNKNOWN: "Unverified; native evidence is insufficient",
    }[health]


def health_label(health: SessionHealth) -> str:
    """Return the concise human label while retaining stable JSON enum values."""

    return {
        SessionHealth.COMPLETE: "complete",
        SessionHealth.POSSIBLY_INTERRUPTED: "possibly interrupted",
        SessionHealth.UNKNOWN: "unverified",
    }[health]


def health_style(health: SessionHealth) -> str:
    """Return an accessible semantic Rich style while preserving text labels."""

    return {
        SessionHealth.COMPLETE: "bold #2aa198",
        SessionHealth.POSSIBLY_INTERRUPTED: "bold red",
        SessionHealth.UNKNOWN: "bold #ff9d3d",
    }[health]
