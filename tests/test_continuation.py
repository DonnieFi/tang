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
from tang.continuation import (
    SUPPORTED_DESTINATION_ADAPTERS,
    ContinuationError,
    ContinuationService,
)
from tang.graph import GraphService
from tang.repository import StoredContinuation, TangRepository
from tang.storage import open_database
from tang.target import (
    TargetCandidate,
    TargetResolution,
    TargetResolutionCode,
    TargetResolutionKind,
)


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def source(native_id: str, adapter: str = "codex") -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity(adapter, "graph", native_id),
        locator=OpaqueSourceLocator(f"fixture:{native_id}"),
        fingerprint=SourceFingerprint("sha256", f"digest-{native_id}"),
        project_hint="/fixture/project",
        started_at=NOW,
        updated_at=NOW,
        health=SessionHealth.COMPLETE,
    )


def seeded(tmp_path: Path) -> tuple[object, TangRepository, dict[str, str]]:
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    records = {
        name: source(name, "grok" if name in {"a", "b", "f"} else "codex")
        for name in "abcdefgh"
    }
    foreign = source("foreign")
    with repository.transaction():
        for record in records.values():
            repository.upsert_session(record, "project", NOW)
        repository.upsert_session(foreign, "foreign-project", NOW)
    ids = {name: record.identity.canonical for name, record in records.items()}
    ids["foreign"] = foreign.identity.canonical
    return connection, repository, ids


def test_compound_many_to_many_dag_and_cycle_refusal(tmp_path: Path) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    try:
        assert (
            service.link(
                (ids["a"], ids["b"]), ids["c"], "project", "explicit", NOW
            ).inserted
            == 2
        )
        service.link((ids["c"],), ids["d"], "project", "explicit", NOW)
        service.link((ids["c"],), ids["e"], "project", "explicit", NOW)
        service.link((ids["e"], ids["f"]), ids["g"], "project", "explicit", NOW)

        before = repository.continuations_for_project("project")
        with pytest.raises(ContinuationError) as failure:
            service.link((ids["g"], ids["h"]), ids["c"], "project", "explicit", NOW)
        assert failure.value.code == "cycle"
        assert repository.continuations_for_project("project") == before
        assert len(before) == 6
    finally:
        connection.close()


def test_cycle_detection_handles_a_chain_beyond_recursion_depth() -> None:
    edges = tuple(
        StoredContinuation(
            f"codex:graph:n{index}",
            f"codex:graph:n{index + 1}",
            "project",
            "explicit",
            NOW,
        )
        for index in range(1_500)
    )

    assert not ContinuationService._introduces_cycle(edges, ())
    assert ContinuationService._introduces_cycle(
        edges,
        (("codex:graph:n1500", "codex:graph:n0"),),
    )


def test_bad_source_self_and_foreign_requests_are_atomic(tmp_path: Path) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    try:
        cases = (
            ((ids["a"], "codex:graph:missing"), ids["c"], "unknown-source"),
            ((ids["c"],), ids["c"], "self-link"),
            ((ids["a"], ids["foreign"]), ids["c"], "foreign-source"),
        )
        for sources, target, code in cases:
            with pytest.raises(ContinuationError) as failure:
                service.link(sources, target, "project", "explicit", NOW)
            assert failure.value.code == code
            assert repository.continuations_for_project("project") == ()
    finally:
        connection.close()


def test_duplicate_edges_are_idempotent(tmp_path: Path) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    try:
        first = service.link((ids["a"],), ids["c"], "project", "explicit", NOW)
        second = service.link((ids["a"],), ids["c"], "project", "explicit", NOW)
        assert (first.inserted, first.existing) == (1, 0)
        assert (second.inserted, second.existing) == (0, 1)
    finally:
        connection.close()


def test_unavailable_sources_and_targets_cannot_form_new_edges(tmp_path: Path) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    try:
        service.link((ids["a"],), ids["c"], "project", "explicit", NOW)
        with repository.transaction():
            repository.delete_session(ids["a"])
            repository.delete_session(ids["c"])
        before = repository.continuations_for_project("project")
        repeated = service.link((ids["a"],), ids["c"], "project", "explicit", NOW)
        assert (repeated.inserted, repeated.existing) == (0, 1)

        cases = (
            ((ids["b"],), ids["c"], "unavailable-target"),
            ((ids["a"],), ids["d"], "unavailable-source"),
        )
        for sources, target, code in cases:
            with pytest.raises(ContinuationError) as failure:
                service.link(sources, target, "project", "explicit", NOW)
            assert failure.value.code == code
            assert repository.continuations_for_project("project") == before
    finally:
        connection.close()


def test_confirmed_opencode_target_accepts_all_supported_source_harnesses_atomically(
    tmp_path: Path,
) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    opencode_source = source("source-opencode", "opencode")
    opencode_target = source("target-opencode", "opencode")
    cursor_target = source("target-cursor", "cursor")
    try:
        with repository.transaction():
            repository.upsert_session(opencode_source, "project", NOW)
            repository.upsert_session(opencode_target, "project", NOW)
            repository.upsert_session(cursor_target, "project", NOW)
        opencode_source_id = opencode_source.identity.canonical
        opencode_target_id = opencode_target.identity.canonical
        cursor_target_id = cursor_target.identity.canonical
        target = repository.get_session(opencode_target_id)
        assert target is not None
        candidate = TargetCandidate.from_stored(target)
        pending = TargetResolution(
            TargetResolutionKind.CONFIRMATION_REQUIRED,
            TargetResolutionCode.HOST_ID_MATCH,
            (candidate,),
            None,
            "The host identified one exact OpenCode target; confirm it explicitly.",
        )
        with pytest.raises(ContinuationError) as failure:
            service.link_resolved((ids["c"],), pending, "project", NOW)
        assert failure.value.code == "target-unconfirmed"
        assert repository.continuations_for_project("project") == ()
        resolution = TargetResolution(
            TargetResolutionKind.RESOLVED,
            TargetResolutionCode.EXPLICIT_CONFIRMATION,
            (candidate,),
            candidate,
            "The active OpenCode target was explicitly confirmed.",
        )

        result = service.link_resolved(
            (ids["c"], ids["a"], opencode_source_id), resolution, "project", NOW
        )

        assert result.source_ids == (ids["c"], ids["a"], opencode_source_id)
        assert (result.target_id, result.inserted, result.existing) == (
            opencode_target_id,
            3,
            0,
        )
        graph = GraphService(repository).component(
            opencode_target_id, current_id=opencode_target_id
        )
        assert {node.harness for node in graph.nodes} == {"codex", "grok", "opencode"}
        assert next(node for node in graph.nodes if node.current).harness == "opencode"

        before = repository.continuations_for_project("project")
        with pytest.raises(ContinuationError) as failure:
            service.link((ids["b"],), cursor_target_id, "project", "explicit", NOW)
        assert failure.value.code == "unsupported-target"
        assert repository.continuations_for_project("project") == before
    finally:
        connection.close()


def test_grok_explicit_destination_link(tmp_path: Path) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    target = source("target-grok", "grok")
    try:
        with repository.transaction():
            repository.upsert_session(target, "project", NOW)
        target_id = target.identity.canonical

        result = service.link((ids["c"],), target_id, "project", "explicit", NOW)

        assert result.inserted == 1
        assert result.target_id == target_id
        graph = GraphService(repository).component(target_id, current_id=target_id)
        assert any(node.harness == "grok" and node.current for node in graph.nodes)
    finally:
        connection.close()


def test_supported_destination_policy_is_explicit_and_idempotent_for_opencode(
    tmp_path: Path,
) -> None:
    connection, repository, ids = seeded(tmp_path)
    service = ContinuationService(repository)
    target = source("target-opencode", "opencode")
    try:
        with repository.transaction():
            repository.upsert_session(target, "project", NOW)
        target_id = target.identity.canonical

        first = service.link((ids["a"],), target_id, "project", "explicit", NOW)
        second = service.link((ids["a"],), target_id, "project", "explicit", NOW)

        assert SUPPORTED_DESTINATION_ADAPTERS == frozenset(
            ("codex", "grok", "opencode")
        )
        assert (first.inserted, first.existing) == (1, 0)
        assert (second.inserted, second.existing) == (0, 1)
    finally:
        connection.close()
