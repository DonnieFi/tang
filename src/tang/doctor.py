"""Minimal, deterministic readiness diagnostics for Tang."""

from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter
from tang.adapters.base import BatchStatus, ScanBatch
from tang.storage import SCHEMA_VERSION


@dataclass(frozen=True)
class DoctorCheck:
    """One stable readiness result suitable for line or JSON output."""

    component: str
    status: str
    message: str


def run_doctor(
    database: Path,
    *,
    codex_home: Path | None = None,
    grok_home: Path | None = None,
) -> tuple[DoctorCheck, ...]:
    """Check the CLI, database, FTS5, and both release adapters."""

    executable = shutil.which("tang")
    checks = [
        DoctorCheck(
            "cli",
            "ready" if executable else "unavailable",
            (
                "The tang command is available."
                if executable
                else "Install the tang-multiverse CLI before using the skill."
            ),
        )
    ]
    database_path = database.expanduser().resolve()
    if not database_path.is_file():
        checks.append(
            DoctorCheck(
                "database",
                "not_initialized",
                "Derived storage is not initialized; tang index will create it.",
            )
        )
    else:
        try:
            wal_path = database_path.with_name(f"{database_path.name}-wal")
            query = "mode=ro" if wal_path.exists() else "mode=ro&immutable=1"
            connection = sqlite3.connect(
                f"{database_path.as_uri()}?{query}", uri=True
            )
            try:
                version = int(
                    connection.execute("PRAGMA user_version").fetchone()[0]
                )
                if version != SCHEMA_VERSION:
                    checks.append(
                        DoctorCheck(
                            "database",
                            "upgrade_required",
                            "Derived storage requires an upgrade; run tang index.",
                        )
                    )
                else:
                    connection.execute("SELECT count(*) FROM sessions").fetchone()
                    checks.append(
                        DoctorCheck("database", "ready", "Derived storage is ready.")
                    )
            finally:
                connection.close()
        except (OSError, RuntimeError, sqlite3.Error) as error:
            checks.append(
                DoctorCheck(
                    "database",
                    "error",
                    f"Derived storage failed: {type(error).__name__}.",
                )
            )

    try:
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE temp.tang_doctor_fts USING fts5(value)"
            )
            checks.append(DoctorCheck("fts5", "ready", "SQLite FTS5 is available."))
        finally:
            connection.close()
    except sqlite3.Error:
        checks.append(
            DoctorCheck("fts5", "unavailable", "SQLite FTS5 is unavailable.")
        )

    checks.extend(
        _adapter_check("codex", CodexAdapter(codex_home).scan(None)),
    )
    checks.extend(
        _adapter_check("grok", GrokAdapter(grok_home).scan(None)),
    )
    return tuple(checks)


def _adapter_check(component: str, batch: ScanBatch) -> tuple[DoctorCheck, ...]:
    if batch.status is BatchStatus.COMPLETE and not batch.records:
        return (
            DoctorCheck(
                component,
                "empty",
                f"The {component.title()} store is readable but contains no sessions.",
            ),
        )
    if batch.status is BatchStatus.COMPLETE:
        count = len(batch.records)
        return (
            DoctorCheck(
                component,
                "ready",
                f"The {component.title()} adapter found {count} "
                f"session{'s' if count != 1 else ''}.",
            ),
        )
    if batch.status is BatchStatus.PARTIAL:
        return (
            DoctorCheck(
                component,
                "degraded",
                f"The {component.title()} adapter found {len(batch.records)} "
                "sessions with warnings.",
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
