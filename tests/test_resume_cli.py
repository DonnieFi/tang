from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.cli import main
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.resume import ResumeError, _run_native
from tang.storage import open_database


NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)
CODEX_ID = "019f6000-5678-7000-8000-000000000005"
OPENCODE_ID = "ses_tangResume0000000000000000001"
GROK_ID = "019f6000-1234-7000-8000-000000000001"
CURSOR_ID = "019f6000-abcd-7000-8000-000000000002"


def _record(adapter: str, native_id: str, project: Path) -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity(adapter, "resume-fixture", native_id),
        locator=OpaqueSourceLocator(f"fixture:{native_id}"),
        fingerprint=SourceFingerprint("sha256", f"digest-{native_id}"),
        project_hint=str(project),
        started_at=NOW,
        updated_at=NOW,
        title=f"{adapter.title()} resume fixture",
        health=SessionHealth.COMPLETE,
    )


def _seed(database: Path, project: Path, *records: SourceRecord) -> None:
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            for record in records:
                repository.upsert_session(record, resolve_project(project).key, NOW)
    finally:
        connection.close()


def _capture_runner(monkeypatch) -> list[tuple[tuple[str, ...], Path]]:
    launches: list[tuple[tuple[str, ...], Path]] = []

    def run(command: tuple[str, ...], cwd: Path) -> int:
        launches.append((tuple(command), cwd))
        return 0

    monkeypatch.setattr("tang.resume._run_native", run)
    monkeypatch.setattr(
        "tang.resume.shutil.which",
        lambda executable: f"/tools/{Path(executable).name}",
    )
    return launches


def test_resume_launches_codex_by_private_native_identity(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    record = _record("codex", CODEX_ID, project)
    _seed(database, project, record)
    launches = _capture_runner(monkeypatch)

    result = main(
        [
            "resume",
            "c1",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == captured.err == ""
    assert launches == [
        (
            (
                "/tools/codex",
                "resume",
                "-C",
                str(project.resolve()),
                CODEX_ID,
            ),
            project.resolve(),
        )
    ]
    connection = open_database(database)
    try:
        assert TangRepository(connection).continuations_for_project(
            resolve_project(project).key
        ) == ()
    finally:
        connection.close()


def test_resume_launches_opencode_in_the_exact_worktree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    _seed(database, project, _record("opencode", OPENCODE_ID, project))
    launches = _capture_runner(monkeypatch)

    result = main(
        [
            "resume",
            "O1",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == captured.err == ""
    assert launches == [
        (
            (
                "/tools/opencode",
                str(project.resolve()),
                "--session",
                OPENCODE_ID,
            ),
            project.resolve(),
        )
    ]


@pytest.mark.parametrize(
    ("adapter", "native_id", "expected_command"),
    (
        (
            "grok",
            GROK_ID,
            ("/tools/grok", "--cwd", "{project}", "--resume", GROK_ID),
        ),
        (
            "cursor",
            CURSOR_ID,
            ("/tools/agent", "--workspace", "{project}", "--resume", CURSOR_ID),
        ),
    ),
)
def test_resume_launches_grok_and_cursor_by_private_native_identity(
    adapter: str,
    native_id: str,
    expected_command: tuple[str, ...],
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    _seed(database, project, _record(adapter, native_id, project))
    launches = _capture_runner(monkeypatch)

    result = main(
        [
            "resume",
            "R1" if adapter == "cursor" else f"{adapter[0]}1",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.out == captured.err == ""
    rendered = tuple(
        str(project.resolve()) if part == "{project}" else part
        for part in expected_command
    )
    assert launches == [(rendered, project.resolve())]


@pytest.mark.parametrize(
    ("adapter", "native_id", "expected_code"),
    (
        ("grok", "grok-source", "resume-native-id-invalid"),
        ("cursor", "cursor-source", "resume-native-id-invalid"),
        ("codex", "not-a-uuid", "resume-native-id-invalid"),
        ("opencode", "not-a-session", "resume-native-id-invalid"),
    ),
)
def test_resume_rejects_unsupported_or_malformed_native_targets(
    adapter: str,
    native_id: str,
    expected_code: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    _seed(database, project, _record(adapter, native_id, project))
    monkeypatch.setattr(
        "tang.resume._run_native",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a refused target must not launch a harness")
        ),
    )

    assert (
        main(
            [
                "resume",
                "R1" if adapter == "cursor" else f"{adapter[0]}1",
                "--database",
                str(database),
                "--cwd",
                str(project),
            ]
        )
        == 2
    )

    captured = capsys.readouterr()
    assert captured.out == ""
    assert f"error[{expected_code}]" in captured.err
    assert native_id not in captured.err


def test_resume_requires_a_safe_current_project_handle(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    record = _record("codex", CODEX_ID, project)
    _seed(database, project, record)
    monkeypatch.setattr(
        "tang.resume._run_native",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("an invalid token must not launch a harness")
        ),
    )

    for token, code in (
        (record.identity.canonical, "resume-handle-required"),
        ("C9", "resume-session-not-found"),
    ):
        assert (
            main(
                [
                    "resume",
                    token,
                    "--database",
                    str(database),
                    "--cwd",
                    str(project),
                ]
            )
            == 2
        )
        captured = capsys.readouterr()
        assert captured.out == ""
        assert f"error[{code}]" in captured.err
        assert CODEX_ID not in captured.err


def test_resume_rejects_tombstones_and_cross_worktree_opencode(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other-worktree"
    project.mkdir()
    other.mkdir()
    database = tmp_path / "tang.db"
    codex = _record("codex", CODEX_ID, project)
    opencode = _record("opencode", OPENCODE_ID, other)
    _seed(database, project, codex, opencode)
    connection = open_database(database)
    try:
        with TangRepository(connection).transaction():
            connection.execute(
                "UPDATE sessions SET native_available = 0 WHERE source_id = ?",
                (codex.identity.canonical,),
            )
    finally:
        connection.close()
    monkeypatch.setattr(
        "tang.resume._run_native",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a refused target must not launch a harness")
        ),
    )

    common = ["--database", str(database), "--cwd", str(project)]
    assert main(["resume", "C1", *common]) == 2
    unavailable = capsys.readouterr()
    assert "error[resume-native-unavailable]" in unavailable.err
    assert main(["resume", "O1", *common]) == 2
    mismatch = capsys.readouterr()
    assert "error[resume-project-mismatch]" in mismatch.err


@pytest.mark.parametrize(
    ("adapter", "native_id", "handle"),
    (
        ("grok", GROK_ID, "G1"),
        ("cursor", CURSOR_ID, "R1"),
    ),
)
def test_resume_rejects_cross_worktree_grok_and_cursor(
    adapter: str,
    native_id: str,
    handle: str,
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    project = tmp_path / "project"
    other = tmp_path / "other-worktree"
    project.mkdir()
    other.mkdir()
    database = tmp_path / "tang.db"
    _seed(database, project, _record(adapter, native_id, other))
    monkeypatch.setattr(
        "tang.resume._run_native",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a foreign-worktree target must not launch a harness")
        ),
    )

    assert (
        main(
            [
                "resume",
                handle,
                "--database",
                str(database),
                "--cwd",
                str(project),
            ]
        )
        == 2
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "error[resume-project-mismatch]" in captured.err
    assert native_id not in captured.err


def test_resume_reports_missing_executable_and_safe_launch_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "tang.db"
    _seed(database, project, _record("codex", CODEX_ID, project))
    common = ["resume", "C1", "--database", str(database), "--cwd", str(project)]
    monkeypatch.setattr("tang.resume.shutil.which", lambda _executable: None)

    assert main(common) == 2
    missing = capsys.readouterr()
    assert missing.out == ""
    assert "error[resume-executable-missing]" in missing.err

    monkeypatch.setattr("tang.resume.shutil.which", lambda _executable: "/tools/codex")

    def fail(_command: tuple[str, ...], _cwd: Path) -> int:
        raise ResumeError(
            "resume-launch-failed",
            "The native harness could not be started.",
        )

    monkeypatch.setattr("tang.resume._run_native", fail)
    assert main(common) == 2
    failed = capsys.readouterr()
    assert failed.out == ""
    assert "error[resume-launch-failed]" in failed.err
    assert "private launch detail" not in failed.err

    monkeypatch.setattr("tang.resume._run_native", lambda *_args: 17)
    assert main(common) == 2
    nonzero = capsys.readouterr()
    assert nonzero.out == ""
    assert "error[resume-launch-failed]" in nonzero.err
    assert CODEX_ID not in nonzero.err


def test_native_runner_converts_os_errors_to_safe_resume_error(
    tmp_path: Path, monkeypatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        raise OSError("private process detail")

    monkeypatch.setattr("tang.resume.subprocess.run", fail)

    with pytest.raises(ResumeError) as error:
        _run_native(("/tools/codex", "resume"), tmp_path)

    assert error.value.code == "resume-launch-failed"
    assert "private process detail" not in str(error.value)
