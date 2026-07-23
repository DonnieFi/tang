"""Privacy-safe native session launch by project-local Tang handle."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID

from tang.project import ProjectIdentity
from tang.repository import TangRepository


_OPENCODE_SESSION_ID = re.compile(r"ses_[A-Za-z0-9_-]+\Z")


class ResumeError(RuntimeError):
    """A fixed, display-safe refusal to launch a native session."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


ResumeRunner = Callable[[Sequence[str], Path], int]


def _run_native(command: Sequence[str], cwd: Path) -> int:
    try:
        result = subprocess.run(command, cwd=cwd, check=False)
    except OSError as error:
        raise ResumeError(
            "resume-launch-failed",
            "The native harness could not be started.",
        ) from error
    return result.returncode


def _executable(
    configured: Path | str | None,
    *,
    environment_name: str,
    default: str,
    harness: str,
) -> str:
    requested = configured or os.environ.get(environment_name) or default
    resolved = shutil.which(str(requested))
    if resolved is None:
        raise ResumeError(
            "resume-executable-missing",
            f"The {harness} executable is unavailable.",
        )
    return resolved


def _codex_native_id(value: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ResumeError(
            "resume-native-id-invalid",
            "The indexed Codex session does not have a supported native identity.",
        ) from error
    if str(parsed) != value.lower():
        raise ResumeError(
            "resume-native-id-invalid",
            "The indexed Codex session does not have a supported native identity.",
        )
    return value


def _uuid_native_id(value: str, harness: str) -> str:
    try:
        parsed = UUID(value)
    except ValueError as error:
        raise ResumeError(
            "resume-native-id-invalid",
            f"The indexed {harness} session does not have a supported native identity.",
        ) from error
    if str(parsed) != value.lower():
        raise ResumeError(
            "resume-native-id-invalid",
            f"The indexed {harness} session does not have a supported native identity.",
        )
    return value


def _opencode_native_id(value: str) -> str:
    if _OPENCODE_SESSION_ID.fullmatch(value) is None:
        raise ResumeError(
            "resume-native-id-invalid",
            "The indexed OpenCode session does not have a supported native identity.",
        )
    return value


class ResumeService:
    """Resolve one safe handle and launch its owning supported harness."""

    def __init__(
        self,
        repository: TangRepository,
        *,
        runner: ResumeRunner | None = None,
    ) -> None:
        self._repository = repository
        self._runner = runner or _run_native

    def resume(
        self,
        handle: str,
        project: ProjectIdentity,
        launch_directory: Path,
        *,
        codex_executable: Path | str | None = None,
        grok_executable: Path | str | None = None,
        opencode_executable: Path | str | None = None,
        cursor_executable: Path | str | None = None,
        claude_executable: Path | str | None = None,
        antigravity_executable: Path | str | None = None,
    ) -> int:
        """Launch an exact native session without exposing its identity."""

        if ":" in handle:
            raise ResumeError(
                "resume-handle-required",
                "Resume requires a displayed Tang handle such as C5 or O1.",
            )
        try:
            source_id = self._repository.resolve_session_token(handle, project.key)
        except ValueError as error:
            raise ResumeError(
                "resume-session-not-found",
                "That Tang handle is not indexed in the current project.",
            ) from error
        stored = self._repository.get_session(source_id)
        if stored is None or stored.project_key != project.key:
            raise ResumeError(
                "resume-session-not-found",
                "That Tang handle is not indexed in the current project.",
            )
        if not stored.native_available:
            raise ResumeError(
                "resume-native-unavailable",
                "The selected Tang session is no longer available in its native harness.",
            )

        adapter = stored.source.identity.adapter
        native_id = stored.source.identity.native_id
        if adapter == "codex":
            native_id = _codex_native_id(native_id)
            executable = _executable(
                codex_executable,
                environment_name="TANG_CODEX_EXECUTABLE",
                default="codex",
                harness="Codex",
            )
            command = (
                executable,
                "resume",
                "-C",
                str(launch_directory),
                native_id,
            )
        elif adapter == "grok":
            native_id = _uuid_native_id(native_id, "Grok")
            self._require_recorded_directory(
                stored.source.project_hint, launch_directory
            )
            executable = _executable(
                grok_executable,
                environment_name="TANG_GROK_EXECUTABLE",
                default="grok",
                harness="Grok",
            )
            command = (
                executable,
                "--cwd",
                str(launch_directory),
                "--resume",
                native_id,
            )
        elif adapter == "opencode":
            native_id = _opencode_native_id(native_id)
            self._require_recorded_directory(
                stored.source.project_hint, launch_directory
            )
            executable = _executable(
                opencode_executable,
                environment_name="TANG_OPENCODE_EXECUTABLE",
                default="opencode",
                harness="OpenCode",
            )
            # Supported OpenCode CLI contract: open the exact recorded project
            # directory and select its private session with ``--session``.
            # Keep this narrow until a live-verified upstream contract changes.
            command = (
                executable,
                str(launch_directory),
                "--session",
                native_id,
            )
        elif adapter == "cursor":
            native_id = _uuid_native_id(native_id, "Cursor")
            self._require_recorded_directory(
                stored.source.project_hint, launch_directory
            )
            executable = _executable(
                cursor_executable,
                environment_name="TANG_CURSOR_EXECUTABLE",
                default="agent",
                harness="Cursor Agent",
            )
            command = (
                executable,
                "--workspace",
                str(launch_directory),
                "--resume",
                native_id,
            )
        elif adapter == "claude":
            native_id = _uuid_native_id(native_id, "Claude")
            self._require_recorded_directory(
                stored.source.project_hint, launch_directory
            )
            executable = _executable(
                claude_executable,
                environment_name="TANG_CLAUDE_EXECUTABLE",
                default="claude",
                harness="Claude Code",
            )
            command = (
                executable,
                "--resume",
                native_id,
            )
        elif adapter == "antigravity":
            native_id = _uuid_native_id(native_id, "Antigravity")
            self._require_recorded_directory(
                stored.source.project_hint, launch_directory
            )
            executable = _executable(
                antigravity_executable,
                environment_name="TANG_ANTIGRAVITY_EXECUTABLE",
                default="agy",
                harness="Antigravity",
            )
            command = (
                executable,
                "--conversation",
                native_id,
            )
        else:
            raise ResumeError(
                "resume-unsupported-harness",
                "That harness is a read-only source and cannot be resumed.",
            )

        result = self._runner(command, launch_directory)
        if result != 0:
            raise ResumeError(
                "resume-launch-failed",
                f"{adapter.title()} exited before the selected Tang session was resumed.",
            )
        return result

    @staticmethod
    def _require_recorded_directory(value: str | None, launch_directory: Path) -> None:
        if not value:
            raise ResumeError(
                "resume-project-unavailable",
                "The indexed session directory is unavailable.",
            )
        try:
            recorded_directory = Path(value).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ResumeError(
                "resume-project-unavailable",
                "The indexed session directory is unavailable.",
            ) from error
        if recorded_directory != launch_directory:
            raise ResumeError(
                "resume-project-mismatch",
                "The selected session belongs to another worktree.",
            )
