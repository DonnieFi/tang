from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.project import resolve_project
from tang.target import (
    TargetCandidate,
    TargetResolutionKind,
    confirm_target,
    resolve_current_target,
)


NOW = datetime(2026, 7, 14, 20, 0, tzinfo=timezone.utc)


def source(native_id: str, project_hint: str, age: int = 0) -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity("codex", "fixture", native_id),
        locator=OpaqueSourceLocator(f"private/{native_id}.jsonl"),
        fingerprint=SourceFingerprint("sha256", f"digest-{native_id}"),
        project_hint=project_hint,
        started_at=NOW - timedelta(minutes=10 + age),
        updated_at=NOW - timedelta(minutes=age),
        health=SessionHealth.UNKNOWN,
    )


def candidate(
    native_id: str, project_path: Path, age: int = 0
) -> TargetCandidate:
    project = resolve_project(project_path)
    return TargetCandidate.from_source(source(native_id, str(project_path), age), project)


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
