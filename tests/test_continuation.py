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
from tang.continuation import ContinuationError, ContinuationService
from tang.repository import TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def source(native_id: str, adapter: str = "codex") -> SourceRecord:
    return SourceRecord(
        SessionIdentity(adapter, "graph", native_id),
        OpaqueSourceLocator(f"fixture:{native_id}"),
        SourceFingerprint("sha256", f"digest-{native_id}"),
        "/fixture/project",
        NOW,
        NOW,
        SessionHealth.COMPLETE,
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
        assert service.link((ids["a"], ids["b"]), ids["c"], "project", "explicit", NOW).inserted == 2
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
