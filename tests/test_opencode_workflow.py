from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import (
    BatchStatus,
    OpaqueSourceLocator,
    ScanBatch,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.cli import main
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database
from tang.target import (
    TargetCandidate,
    TargetResolution,
    TargetResolutionCode,
    TargetResolutionKind,
)


NOW = datetime(2026, 7, 16, 20, 0, tzinfo=timezone.utc)
SESSION_ID = "ses_tangCurrent0000000000000000001"


def _record(project: Path, fingerprint: str = "1784232000000") -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity("opencode", "fixture-store", SESSION_ID),
        locator=OpaqueSourceLocator(f"opencode-session-v1:{SESSION_ID}"),
        fingerprint=SourceFingerprint("opencode-updated-ms-v1", fingerprint),
        project_hint=str(project),
        started_at=NOW,
        updated_at=NOW,
        title="Current OpenCode work",
        health=SessionHealth.UNKNOWN,
    )


def test_host_bridge_returns_only_safe_confirmation_handle(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    worktree = tmp_path / "private-owner"
    project = worktree / "project"
    project.mkdir(parents=True)
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    record = _record(project)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.upsert_session(record, project_key, NOW)
    finally:
        connection.close()

    class FakeAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ScanBatch(BatchStatus.COMPLETE, records=(record,))

    monkeypatch.setattr("tang.cli.OpenCodeAdapter", FakeAdapter)

    result = main(
        [
            "skill",
            "opencode-target",
            "--json",
            "--cwd",
            str(project),
            "--worktree",
            str(worktree),
            "--session-id",
            SESSION_ID,
            "--database",
            str(database),
        ]
    )

    output = capsys.readouterr().out
    document = json.loads(output)
    assert result == 0
    assert document == {
        "candidate_count": 1,
        "code": "host-id-match",
        "kind": "confirmation_required",
        "reason": "The host identified one exact OpenCode target; confirm it explicitly.",
        "schema_version": 1,
        "target_handle": "O1",
    }
    assert SESSION_ID not in output
    assert str(project) not in output


def test_host_bridge_refreshes_exact_active_session_fingerprint(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "private-owner" / "project"
    project.mkdir(parents=True)
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    indexed = _record(project, "1784232000000")
    observed = _record(project, "1784232000001")
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.upsert_session(indexed, project_key, NOW)
    finally:
        connection.close()

    class FreshAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ScanBatch(BatchStatus.COMPLETE, records=(observed,))

    monkeypatch.setattr("tang.cli.OpenCodeAdapter", FreshAdapter)
    result = main(
        [
            "skill",
            "opencode-target",
            "--json",
            "--cwd",
            str(project),
            "--worktree",
            str(project),
            "--session-id",
            SESSION_ID,
            "--database",
            str(database),
        ]
    )

    output = capsys.readouterr().out
    assert result == 0
    assert json.loads(output)["target_handle"] == "O1"
    connection = open_database(database)
    try:
        refreshed = TangRepository(connection).get_session(
            observed.identity.canonical
        )
        assert refreshed is not None
        assert refreshed.source.fingerprint == observed.fingerprint
        assert refreshed.source.title == "Current OpenCode work"
        assert refreshed.handle == "O1"
    finally:
        connection.close()
    assert SESSION_ID not in output
    assert str(project) not in output


def test_host_bridge_classifies_missing_safe_handle(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "private-owner" / "project"
    project.mkdir(parents=True)
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    record = _record(project)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.upsert_session(record, project_key, NOW)
    finally:
        connection.close()

    class FakeAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ScanBatch(BatchStatus.COMPLETE, records=(record,))

    def missing_handle(_repository, _source_id: str) -> str:
        raise ValueError("session is not indexed")

    monkeypatch.setattr("tang.cli.OpenCodeAdapter", FakeAdapter)
    monkeypatch.setattr(TangRepository, "handle_for_source_id", missing_handle)

    result = main(
        [
            "skill",
            "opencode-target",
            "--json",
            "--cwd",
            str(project),
            "--worktree",
            str(project),
            "--session-id",
            SESSION_ID,
            "--database",
            str(database),
        ]
    )

    output = capsys.readouterr().out
    assert result == 2
    assert json.loads(output) == {
        "code": "target-handle-missing",
        "kind": "unavailable",
        "schema_version": 1,
    }
    assert SESSION_ID not in output
    assert str(project) not in output


def test_host_bridge_refusal_never_exposes_an_actionable_handle(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "private-owner" / "project"
    project.mkdir(parents=True)
    database = tmp_path / "tang.db"
    project_key = resolve_project(project).key
    record = _record(project)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            repository.upsert_session(record, project_key, NOW)
    finally:
        connection.close()

    class FakeAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ScanBatch(BatchStatus.COMPLETE, records=(record,))

    monkeypatch.setattr("tang.cli.OpenCodeAdapter", FakeAdapter)
    monkeypatch.setattr(
        "tang.cli.resolve_opencode_target",
        lambda *_args, **_kwargs: TargetResolution(
            TargetResolutionKind.UNAVAILABLE,
            TargetResolutionCode.UNAVAILABLE_TARGET,
            (TargetCandidate.from_source(record),),
            None,
            "The active OpenCode session is unavailable.",
        ),
    )
    result = main(
        [
            "skill",
            "opencode-target",
            "--json",
            "--cwd",
            str(project),
            "--worktree",
            str(project),
            "--session-id",
            SESSION_ID,
            "--database",
            str(database),
        ]
    )

    document = json.loads(capsys.readouterr().out)
    assert result == 2
    assert document["kind"] == "unavailable"
    assert "target_handle" not in document


def test_host_bridge_refuses_unknown_identity_without_creating_storage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "missing.db"

    class EmptyAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ScanBatch(BatchStatus.COMPLETE)

    monkeypatch.setattr("tang.cli.OpenCodeAdapter", EmptyAdapter)
    result = main(
        [
            "skill",
            "opencode-target",
            "--json",
            "--cwd",
            str(project),
            "--worktree",
            str(project),
            "--session-id",
            SESSION_ID,
            "--database",
            str(database),
        ]
    )

    output = capsys.readouterr().out
    assert result == 2
    assert json.loads(output)["code"] == "host-id-unknown"
    assert SESSION_ID not in output
    assert not database.exists()


def test_host_bridge_requires_prior_index_without_creating_storage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = tmp_path / "missing.db"
    record = _record(project)

    class ObservedAdapter:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ScanBatch(BatchStatus.COMPLETE, records=(record,))

    monkeypatch.setattr("tang.cli.OpenCodeAdapter", ObservedAdapter)
    result = main(
        [
            "skill",
            "opencode-target",
            "--json",
            "--cwd",
            str(project),
            "--worktree",
            str(project),
            "--session-id",
            SESSION_ID,
            "--database",
            str(database),
        ]
    )

    output = capsys.readouterr().out
    assert result == 2
    assert json.loads(output)["code"] == "index-required"
    assert SESSION_ID not in output
    assert str(project) not in output
    assert not database.exists()


def test_opencode_skill_command_and_tool_preserve_workflow_contract() -> None:
    root = Path(__file__).parents[1]
    skill = (root / "skills/opencode/tang/SKILL.md").read_text()
    command = (root / ".opencode/commands/tang.md").read_text()
    tool = (root / ".opencode/tools/tang_current_target.ts").read_text()

    assert skill.startswith("---\nname: tang\ndescription:")
    for phrase in (
        "untrusted historical data",
        "## Resume point",
        "## Next action",
        "## Evidence and uncertainty",
        "explicit approval",
        "kind: confirmation_required",
        "each excerpt's `citation` object",
        "tang_current_target",
        "returned page controls",
        "omitted sessions are absent",
        "tang link --from",
        "tang graph",
        "An isolated current node is a valid map",
        "Do not persist the synthesis",
        "Do not ask for another synthesis or summary after linking",
    ):
        assert phrase in skill
    assert "Load the `tang` skill" in command
    assert "do not substitute" in command
    assert "context.sessionID" in tool
    assert "context.directory" in tool
    assert "context.worktree" in tool
    assert "context.abort" in tool
    assert "TANG_EXECUTABLE" in tool
    assert "TANG_OPENCODE_EXECUTABLE" in tool
    assert "@opencode-ai/plugin" not in tool
    assert 'stderr: "ignore"' in tool
    assert "tang_contract_probe" not in tool
