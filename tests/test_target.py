from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tang.adapters import (
    CodexAdapter,
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.project import resolve_project
from tang.repository import StoredSession
from tang.target import (
    HostTargetContextError,
    OpenCodeTargetContext,
    TargetCandidate,
    TargetResolutionCode,
    TargetResolutionKind,
    confirm_target,
    candidates_for_project,
    resolve_current_target,
    resolve_opencode_target,
)


NOW = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)
OPENCODE_FIXTURES = Path(__file__).parent / "fixtures" / "opencode"


def source(
    native_id: str,
    project_hint: str,
    age: int = 0,
    health: SessionHealth = SessionHealth.UNKNOWN,
    *,
    adapter: str = "codex",
    source_namespace: str = "fixture",
    fingerprint: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity(adapter, source_namespace, native_id),
        locator=OpaqueSourceLocator(f"private/{native_id}.jsonl"),
        fingerprint=SourceFingerprint(
            "sha256", fingerprint or f"digest-{native_id}"
        ),
        project_hint=project_hint,
        started_at=NOW - timedelta(minutes=10 + age),
        updated_at=NOW - timedelta(minutes=age),
        health=health,
    )


def candidate(
    native_id: str,
    project_path: Path,
    age: int = 0,
    health: SessionHealth = SessionHealth.UNKNOWN,
) -> TargetCandidate:
    return TargetCandidate.from_source(
        source(native_id, str(project_path), age, health)
    )


def git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def initialized_repository(path: Path) -> Path:
    git("init", "--initial-branch=main", str(path))
    git("config", "user.name", "Tang Fixture", cwd=path)
    git("config", "user.email", "fixture@example.invalid", cwd=path)
    git("commit", "--allow-empty", "-m", "fixture baseline", cwd=path)
    return path


def stored_opencode(
    native_id: str,
    project_path: Path,
    *,
    project_key: str | None = None,
    source_namespace: str = "fixture",
    fingerprint: str | None = None,
    native_available: bool = True,
) -> StoredSession:
    project = resolve_project(project_path)
    return StoredSession(
        source=source(
            native_id,
            str(project_path),
            adapter="opencode",
            source_namespace=source_namespace,
            fingerprint=fingerprint,
        ),
        project_key=project_key or project.key,
        handle="O1",
        indexed_at=NOW,
        native_available=native_available,
    )


def opencode_context(
    native_id: str,
    project_path: Path,
    *,
    worktree: Path | None = None,
    observed_source: SourceRecord | None = None,
) -> OpenCodeTargetContext:
    return OpenCodeTargetContext.from_host(
        session_id=native_id,
        directory=project_path,
        worktree=worktree or project_path,
        observed_source=observed_source
        or source(native_id, str(project_path), adapter="opencode"),
    )


def write_codex_variant(template: Path, native_id: str, cwd: Path) -> Path:
    rows = [json.loads(line) for line in template.read_text().splitlines()]
    metadata = rows[0]["payload"]
    metadata["id"] = metadata["session_id"] = native_id
    metadata["cwd"] = str(cwd)
    destination = template.with_name(
        f"rollout-2026-07-14T20-00-00-{native_id}.jsonl"
    )
    destination.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    return destination


def test_unique_fresh_session_resolves_deterministically(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    current = candidate("current", project_path)

    result = resolve_current_target((current,), project)

    assert result.kind is TargetResolutionKind.RESOLVED
    assert result.target == current
    assert "Exactly one" in result.reason


def test_host_native_id_resolves_one_existing_session(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    older = candidate("older", project_path, age=30)
    current = candidate("current", project_path, age=5)

    result = resolve_current_target(
        (older, current), project, current_native_id="older"
    )

    assert result.kind is TargetResolutionKind.RESOLVED
    assert result.target == older


def test_self_and_wrong_project_candidates_are_excluded(tmp_path: Path) -> None:
    active_path = tmp_path / "active"
    other_path = tmp_path / "other"
    active_path.mkdir()
    other_path.mkdir()
    project = resolve_project(active_path)
    source_session = candidate("selected-source", active_path, age=2)
    target = candidate("target", active_path, age=1)
    wrong_project = candidate("wrong-project", other_path)

    result = resolve_current_target(
        (wrong_project, source_session, target),
        project,
        exclude=frozenset({source_session.identity}),
    )

    assert result.kind is TargetResolutionKind.RESOLVED
    assert result.candidates == (target,)


def test_multiple_sessions_are_ranked_but_never_guessed(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    older = candidate("older", project_path, age=30)
    freshest = candidate("freshest", project_path)

    result = resolve_current_target((older, freshest), project)

    assert result.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
    assert result.target is None
    assert result.candidates == (freshest, older)
    assert "recency alone is weak evidence" in result.reason


def test_health_never_breaks_current_target_ambiguity(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    complete = candidate(
        "complete", project_path, health=SessionHealth.COMPLETE
    )
    unknown = candidate("unknown", project_path, health=SessionHealth.UNKNOWN)

    result = resolve_current_target((unknown, complete), project)

    assert result.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
    assert result.target is None
    assert {item.health for item in result.candidates} == {
        SessionHealth.COMPLETE,
        SessionHealth.UNKNOWN,
    }


def test_equal_timestamp_order_is_stable_by_canonical_identity(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    second = candidate("b-session", project_path)
    first = candidate("a-session", project_path)

    result = resolve_current_target((second, first), project)

    assert [item.identity.native_id for item in result.candidates] == [
        "a-session",
        "b-session",
    ]
    assert result.kind is TargetResolutionKind.CONFIRMATION_REQUIRED


def test_unknown_host_id_requires_explicit_confirmation(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    offered = candidate("offered", project_path)

    result = resolve_current_target(
        (offered,), project, current_native_id="not-present"
    )

    assert result.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
    assert result.target is None


def test_explicit_confirmation_reuses_only_offered_candidates(tmp_path: Path) -> None:
    project_path = tmp_path / "active"
    project_path.mkdir()
    project = resolve_project(project_path)
    first = candidate("first", project_path)
    second = candidate("second", project_path, age=1)
    ambiguous = resolve_current_target((first, second), project)

    resolved = confirm_target(ambiguous, second.identity)

    assert resolved.kind is TargetResolutionKind.RESOLVED
    assert resolved.target == second
    with pytest.raises(ValueError, match="not an offered candidate"):
        confirm_target(ambiguous, SessionIdentity("codex", "fixture", "other"))
    with pytest.raises(ValueError, match="confirmation-required"):
        confirm_target(resolved, second.identity)


def test_no_eligible_current_project_session_is_unavailable(tmp_path: Path) -> None:
    active_path = tmp_path / "active"
    other_path = tmp_path / "other"
    active_path.mkdir()
    other_path.mkdir()

    result = resolve_current_target(
        (candidate("other", other_path),), resolve_project(active_path)
    )

    assert result.kind is TargetResolutionKind.UNAVAILABLE
    assert result.candidates == ()
    assert result.target is None


def test_scanned_worktree_records_compose_into_active_project_candidates(
    copied_codex_home: Path, tmp_path: Path
) -> None:
    repository = initialized_repository(tmp_path / "primary-project")
    linked = tmp_path / "linked-worktree"
    clone = tmp_path / "separate-clone"
    git("worktree", "add", "-b", "fixture-linked", str(linked), cwd=repository)
    git("clone", str(repository), str(clone))
    template = next((copied_codex_home / "sessions").rglob("*.jsonl"))
    rows = [json.loads(line) for line in template.read_text().splitlines()]
    rows[0]["payload"]["cwd"] = str(repository)
    template.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    write_codex_variant(
        template, "019f6000-5678-7000-8000-000000000003", linked
    )
    write_codex_variant(
        template, "019f6000-5678-7000-8000-000000000004", clone
    )

    scan = CodexAdapter(
        copied_codex_home, source_namespace="target-integration"
    ).scan(None)
    discovery = candidates_for_project(scan.records, resolve_project(repository))
    resolution = resolve_current_target(
        discovery.candidates, resolve_project(repository)
    )

    assert scan.status.value == "complete"
    assert discovery.warnings == ()
    assert len(discovery.candidates) == 2
    assert {
        candidate.identity.native_id for candidate in discovery.candidates
    } == {
        "019f6000-5678-7000-8000-000000000002",
        "019f6000-5678-7000-8000-000000000003",
    }
    assert resolution.kind is TargetResolutionKind.CONFIRMATION_REQUIRED


def test_unusable_project_hint_returns_path_safe_warning(tmp_path: Path) -> None:
    active_path = tmp_path / "active"
    active_path.mkdir()
    missing = tmp_path / "private-owner" / "missing-project"
    record = source("missing", str(missing))

    discovery = candidates_for_project((record,), resolve_project(active_path))

    assert discovery.candidates == ()
    assert len(discovery.warnings) == 1
    assert discovery.warnings[0].code == "project-hint-unavailable"
    assert str(missing) not in repr(discovery.warnings[0])


def test_exact_opencode_host_match_requires_explicit_confirmation(
    tmp_path: Path,
) -> None:
    host = json.loads((OPENCODE_FIXTURES / "tool-context.json").read_text())
    project_path = tmp_path / "private-project"
    project_path.mkdir()
    project = resolve_project(project_path)
    native_id = host["sessionID"]
    stored = stored_opencode(native_id, project_path)
    context = OpenCodeTargetContext.from_host(
        session_id=native_id,
        directory=project_path,
        worktree=project_path,
        observed_source=source(
            native_id, str(project_path), adapter="opencode"
        ),
    )

    pending = resolve_opencode_target((stored,), project, context)

    assert pending.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
    assert pending.code is TargetResolutionCode.HOST_ID_MATCH
    assert pending.target is None
    assert pending.candidates[0].identity == stored.source.identity
    resolved = confirm_target(pending, stored.source.identity)
    assert resolved.kind is TargetResolutionKind.RESOLVED
    assert resolved.code is TargetResolutionCode.EXPLICIT_CONFIRMATION


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("absent", TargetResolutionCode.NO_ELIGIBLE_TARGET),
        ("selected", TargetResolutionCode.SELECTED_SOURCE),
        ("unavailable", TargetResolutionCode.UNAVAILABLE_TARGET),
        ("stale", TargetResolutionCode.STALE_INDEX),
    ],
)
def test_opencode_target_refuses_ineligible_exact_identity(
    tmp_path: Path, case: str, expected: TargetResolutionCode
) -> None:
    project_path = tmp_path / "private-project"
    project_path.mkdir()
    project = resolve_project(project_path)
    native_id = "ses_fixtureCurrent01"
    stored = stored_opencode(
        native_id,
        project_path,
        fingerprint="stored-fingerprint" if case == "stale" else None,
        native_available=case != "unavailable",
    )
    observed = source(
        native_id,
        str(project_path),
        adapter="opencode",
        fingerprint="observed-fingerprint" if case == "stale" else None,
    )
    context = opencode_context(
        native_id, project_path, observed_source=observed
    )
    sessions = () if case == "absent" else (stored,)
    exclude = (
        frozenset({stored.source.identity})
        if case == "selected"
        else frozenset()
    )

    result = resolve_opencode_target(
        sessions, project, context, exclude=exclude
    )

    assert result.kind is TargetResolutionKind.UNAVAILABLE
    assert result.code is expected
    assert result.target is None


def test_opencode_target_refuses_foreign_and_ambiguous_identity(
    tmp_path: Path,
) -> None:
    active_path = tmp_path / "active"
    foreign_path = tmp_path / "foreign"
    active_path.mkdir()
    foreign_path.mkdir()
    active = resolve_project(active_path)
    native_id = "ses_fixtureCurrent01"

    foreign = resolve_opencode_target(
        (), active, opencode_context(native_id, foreign_path)
    )
    first = stored_opencode(native_id, active_path, source_namespace="one")
    second = stored_opencode(native_id, active_path, source_namespace="two")
    ambiguous = resolve_opencode_target(
        (second, first), active, opencode_context(native_id, active_path)
    )

    assert foreign.code is TargetResolutionCode.FOREIGN_PROJECT
    assert ambiguous.code is TargetResolutionCode.AMBIGUOUS_TARGET
    assert ambiguous.kind is TargetResolutionKind.UNAVAILABLE
    assert [item.identity.source_namespace for item in ambiguous.candidates] == [
        "one",
        "two",
    ]


def test_opencode_context_rejects_malformed_or_inconsistent_host_metadata(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "private-project"
    foreign_path = tmp_path / "private-foreign"
    project_path.mkdir()
    foreign_path.mkdir()
    observed = source(
        "ses_fixtureCurrent01", str(project_path), adapter="opencode"
    )

    with pytest.raises(HostTargetContextError) as malformed:
        OpenCodeTargetContext.from_host(
            session_id="not an opencode id",
            directory=project_path,
            worktree=project_path,
            observed_source=observed,
        )
    with pytest.raises(HostTargetContextError) as mismatched_source:
        OpenCodeTargetContext.from_host(
            session_id="ses_otherCurrent02",
            directory=project_path,
            worktree=project_path,
            observed_source=observed,
        )
    with pytest.raises(HostTargetContextError) as mismatched_project:
        OpenCodeTargetContext.from_host(
            session_id="ses_fixtureCurrent01",
            directory=project_path,
            worktree=foreign_path,
            observed_source=observed,
        )

    assert malformed.value.code == "malformed-host-context"
    assert mismatched_source.value.code == "host-source-mismatch"
    assert mismatched_project.value.code == "host-project-mismatch"


def test_opencode_target_display_and_json_do_not_expose_host_metadata(
    tmp_path: Path,
) -> None:
    private_path = tmp_path / "owner-secret" / "private-project"
    private_path.mkdir(parents=True)
    native_id = "ses_privateCurrent01"
    project = resolve_project(private_path)
    stored = stored_opencode(native_id, private_path)
    context = opencode_context(native_id, private_path)

    result = resolve_opencode_target((stored,), project, context)
    rendered = json.dumps(result.as_document(), sort_keys=True)

    assert str(private_path) not in repr(context)
    assert native_id not in repr(context)
    assert str(private_path) not in rendered
    assert native_id not in rendered
    assert result.as_document() == {
        "candidate_count": 1,
        "code": "host-id-match",
        "kind": "confirmation_required",
        "reason": "The host identified one exact OpenCode target; confirm it explicitly.",
        "schema_version": 1,
    }
