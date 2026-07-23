"""Deterministic construction of Tang's configured session adapters."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from tang.adapters import (
    AntigravityAdapter,
    ClaudeAdapter,
    CodexAdapter,
    CursorAdapter,
    GrokAdapter,
    OpenCodeAdapter,
    SessionAdapter,
)


def _default_opencode_executable() -> Path | None:
    """Return OpenCode's standard user-local executable when it is runnable."""

    candidate = Path.home() / ".opencode" / "bin" / "opencode"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    return None


def configured_adapters(
    project_dir: Path | str,
    *,
    codex_home: Path | None = None,
    grok_home: Path | None = None,
    cursor_home: Path | None = None,
    claude_home: Path | None = None,
    antigravity_home: Path | None = None,
    opencode_executable: Path | str | None = None,
    require_opencode: bool = False,
) -> tuple[SessionAdapter, ...]:
    """Build adapters in stable order, adding optional OpenCode when available."""

    configured_opencode = opencode_executable or os.environ.get(
        "TANG_OPENCODE_EXECUTABLE"
    )
    discovered_opencode = (
        configured_opencode
        or shutil.which("opencode")
        or _default_opencode_executable()
    )
    adapters: list[SessionAdapter] = [
        CodexAdapter(codex_home),
        GrokAdapter(grok_home),
    ]
    cursor = CursorAdapter(project_dir, cursor_home=cursor_home)
    if cursor.has_project_transcripts():
        adapters.append(cursor)
    claude = ClaudeAdapter(project_dir, claude_home=claude_home)
    if claude.has_project_sessions():
        adapters.append(claude)
    antigravity = AntigravityAdapter(
        project_dir, antigravity_home=antigravity_home
    )
    if antigravity.has_project_sessions():
        adapters.append(antigravity)
    if discovered_opencode is not None or require_opencode:
        adapters.append(
            OpenCodeAdapter(
                project_dir,
                discovered_opencode or "opencode",
            )
        )
    return tuple(adapters)
