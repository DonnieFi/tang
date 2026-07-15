"""Minimal, deterministic readiness diagnostics for Tang."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter
from tang.adapters.base import BatchStatus
from tang.storage import open_database


@dataclass(frozen=True)
class DoctorCheck:
    """One stable readiness result suitable for line or JSON output."""

    component: str
    status: str
    message: str


def run_doctor(
    database: Path | None = None,
    *,
    codex_home: Path | None = None,
    grok_home: Path | None = None,
) -> tuple[DoctorCheck, ...]:
    """Check the CLI, database, FTS5, and both release adapters."""

    checks = [
        DoctorCheck(
            "cli",
            "ready" if shutil.which("tang") else "unavailable",
            (
                "The tang command is available."
                if shutil.which("tang")
                else "Install the tang-multiverse CLI before using the skill."
            ),
        )
    ]
    try:
        connection = open_database(database)
        try:
            connection.execute("SELECT count(*) FROM sessions").fetchone()
            checks.append(DoctorCheck("database", "ready", "Derived storage is ready."))
            connection.execute(
                "CREATE VIRTUAL TABLE temp.tang_doctor_fts USING fts5(value)"
            )
            checks.append(DoctorCheck("fts5", "ready", "SQLite FTS5 is available."))
        finally:
            connection.close()
    except (OSError, RuntimeError, sqlite3.Error) as error:
        checks.append(
            DoctorCheck("database", "error", f"Derived storage failed: {type(error).__name__}.")
        )
        checks.append(DoctorCheck("fts5", "unknown", "FTS5 was not checked."))

    checks.extend(
        _adapter_check("codex", CodexAdapter(codex_home).scan(None).status),
    )
    checks.extend(
        _adapter_check("grok", GrokAdapter(grok_home).scan(None).status),
    )
    return tuple(checks)


def _adapter_check(component: str, status: BatchStatus) -> tuple[DoctorCheck, ...]:
    if status is BatchStatus.COMPLETE:
        return (DoctorCheck(component, "ready", f"The {component.title()} adapter is ready."),)
    if status is BatchStatus.PARTIAL:
        return (
            DoctorCheck(
                component,
                "degraded",
                f"The {component.title()} adapter found data with warnings.",
            ),
        )
    return (
        DoctorCheck(
            component,
            "unavailable",
            f"Configure a readable {component.title()} session store.",
        ),
    )


def doctor_exit_code(checks: tuple[DoctorCheck, ...]) -> int:
    """Return zero only when every readiness component is ready."""

    return 0 if all(check.status == "ready" for check in checks) else 1
