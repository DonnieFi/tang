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
        opencode_executable: Path | str | None = None,
    ) -> int:
        """Launch a native Codex/OpenCode session without exposing its identity."""

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
        elif adapter == "opencode":
            native_id = _opencode_native_id(native_id)
            try:
                recorded_directory = (
                    Path(stored.source.project_hint).expanduser().resolve(strict=True)
                )
            except (OSError, RuntimeError) as error:
                raise ResumeError(
                    "resume-project-unavailable",
                    "The indexed OpenCode session directory is unavailable.",
                ) from error
            if recorded_directory != launch_directory:
                raise ResumeError(
                    "resume-project-mismatch",
                    "The selected OpenCode session belongs to another worktree.",
                )
            executable = _executable(
                opencode_executable,
                environment_name="TANG_OPENCODE_EXECUTABLE",
                default="opencode",
                harness="OpenCode",
            )
            command = (
                executable,
                str(launch_directory),
                "--session",
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
