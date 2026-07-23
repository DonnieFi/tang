"""Minimal, deterministic readiness diagnostics for Tang."""

from __future__ import annotations

import os
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from tang.adapter_registry import configured_adapters
from tang.adapters.base import BatchStatus, ScanBatch
from tang.adapters.antigravity import AntigravityAdapter
from tang.adapters.claude import ClaudeAdapter
from tang.adapters.cursor import CursorAdapter
from tang.storage import SCHEMA_VERSION


def _default_codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()


def _default_antigravity_home() -> Path:
    configured = os.environ.get("ANTIGRAVITY_HOME")
    if configured:
        return Path(configured).expanduser()
    cli_home = Path.home() / ".gemini" / "antigravity-cli"
    if cli_home.is_dir():
        return cli_home
    return Path.home() / ".gemini" / "antigravity"


def _default_claude_home() -> Path:
    return Path(
        os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")
    ).expanduser()


def _default_grok_home() -> Path:
    return Path(os.environ.get("GROK_HOME", Path.home() / ".grok")).expanduser()


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
    cursor_home: Path | None = None,
    claude_home: Path | None = None,
    antigravity_home: Path | None = None,
    opencode_executable: Path | str | None = None,
    project_dir: Path | str | None = None,
    require_opencode: bool = False,
    quick: bool = False,
) -> tuple[DoctorCheck, ...]:
    """Check the CLI, database, FTS5, and configured harness adapters."""

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

    adapter_project = project_dir or Path.cwd()
    if quick:
        checks.extend(
            _quick_adapter_checks(
                adapter_project,
                codex_home=codex_home,
                grok_home=grok_home,
                cursor_home=cursor_home,
                claude_home=claude_home,
                antigravity_home=antigravity_home,
                opencode_executable=opencode_executable,
                require_opencode=require_opencode,
            )
        )
        return tuple(checks)

    for adapter in configured_adapters(
        adapter_project,
        codex_home=codex_home,
        grok_home=grok_home,
        cursor_home=cursor_home,
        claude_home=claude_home,
        antigravity_home=antigravity_home,
        opencode_executable=opencode_executable,
        require_opencode=True,
    ):
        checks.extend(
            _adapter_check(
                adapter.adapter_key,
                adapter.scan(None),
                opencode_required=require_opencode,
            )
        )
    return tuple(checks)


def _quick_adapter_checks(
    project_dir: Path | str,
    *,
    codex_home: Path | None,
    grok_home: Path | None,
    cursor_home: Path | None,
    claude_home: Path | None,
    antigravity_home: Path | None,
    opencode_executable: Path | str | None,
    require_opencode: bool,
) -> tuple[DoctorCheck, ...]:
    """Presence-only harness checks without hashing logs or starting OpenCode."""

    checks: list[DoctorCheck] = []
    codex_root = (codex_home or _default_codex_home()) / "sessions"
    if codex_root.is_dir():
        checks.append(
            DoctorCheck(
                "codex",
                "present",
                "Codex session store is present; omit --quick to count recoverable sessions.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "codex",
                "unavailable",
                "Configure a readable Codex session store.",
            )
        )
    grok_root = (grok_home or _default_grok_home()) / "sessions"
    if grok_root.is_dir():
        checks.append(
            DoctorCheck(
                "grok",
                "present",
                "Grok session store is present; omit --quick to count recoverable sessions.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "grok",
                "unavailable",
                "Configure a readable Grok session store.",
            )
        )
    if CursorAdapter(project_dir, cursor_home=cursor_home).has_project_transcripts():
        checks.append(
            DoctorCheck(
                "cursor",
                "present",
                "Cursor agent transcripts are present; omit --quick to count recoverable sessions.",
            )
        )
    if ClaudeAdapter(project_dir, claude_home=claude_home).has_project_sessions():
        checks.append(
            DoctorCheck(
                "claude",
                "present",
                "Claude Code session logs are present; omit --quick to count recoverable sessions.",
            )
        )
    if AntigravityAdapter(
        project_dir, antigravity_home=antigravity_home
    ).has_project_sessions():
        checks.append(
            DoctorCheck(
                "antigravity",
                "present",
                "Antigravity history is present; omit --quick to count recoverable sessions.",
            )
        )
    configured = opencode_executable or os.environ.get("TANG_OPENCODE_EXECUTABLE")
    discovered = configured or shutil.which("opencode")
    if discovered:
        checks.append(
            DoctorCheck(
                "opencode",
                "present",
                "OpenCode executable is available; omit --quick to probe the session catalog.",
            )
        )
    elif require_opencode:
        checks.append(
            DoctorCheck(
                "opencode",
                "missing",
                "Install OpenCode >=1.17.18,<2.0.0 or configure --opencode-executable.",
            )
        )
    else:
        checks.append(
            DoctorCheck(
                "opencode",
                "optional",
                "OpenCode is not installed; Codex/Grok recovery remains available.",
            )
        )
    return tuple(checks)


def _adapter_check(
    component: str,
    batch: ScanBatch,
    *,
    opencode_required: bool = False,
) -> tuple[DoctorCheck, ...]:
    warning_codes = {warning.code for warning in batch.warnings}
    if component == "opencode" and "missing-executable" in warning_codes:
        return (
            DoctorCheck(
                component,
                "missing" if opencode_required else "optional",
                (
                    "Install OpenCode >=1.17.18,<2.0.0 or configure "
                    "--opencode-executable."
                    if opencode_required
                    else "OpenCode is not installed; Codex/Grok recovery remains available."
                ),
            ),
        )
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
    if component == "opencode":
        return (
            DoctorCheck(
                component,
                "degraded",
                "The OpenCode adapter could not read the supported session catalog.",
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

    ok = {"ready", "optional", "present"}
    return 0 if all(check.status in ok for check in checks) else 1
