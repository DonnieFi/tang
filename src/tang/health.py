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
        SessionHealth.UNKNOWN: "Status unknown; native evidence is insufficient",
    }[health]
