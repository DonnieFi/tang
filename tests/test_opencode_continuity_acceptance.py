from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tang.adapters import (
    AdapterCheckpoint,
    BatchStatus,
    OpaqueSourceLocator,
    ScanBatch,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
    TurnBatch,
    TurnRole,
    TurnSelection,
    VisibleTurn,
)
from tang.context_service import ContextPackService
from tang.continuation import ContinuationService
from tang.graph import GraphService
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database
from tang.target import (
    OpenCodeTargetContext,
    TargetResolutionKind,
    confirm_target,
    resolve_opencode_target,
)


NOW = datetime(2026, 7, 16, 23, 30, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FixtureAdapter:
    adapter_key: str
    source_namespace: str
    records: tuple[SourceRecord, ...]
    turns: dict[str, tuple[VisibleTurn, ...]]

    def scan(self, _checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        return ScanBatch(BatchStatus.COMPLETE, records=self.records)

    def read(self, session_ref: SourceRecord, selection: TurnSelection) -> TurnBatch:
        selected = tuple(
            turn
            for turn in self.turns[session_ref.identity.native_id]
            if selection.includes(turn.ordinal)
        )
        return TurnBatch(session_ref.identity, BatchStatus.COMPLETE, selected)


def _record(project: Path, harness: str, native_id: str, minute: int) -> SourceRecord:
    timestamp = NOW + timedelta(minutes=minute)
    return SourceRecord(
        identity=SessionIdentity(harness, f"acceptance-{harness}", native_id),
        locator=OpaqueSourceLocator(f"fixture:{native_id}"),
        fingerprint=SourceFingerprint("sha256", f"digest-{native_id}"),
        project_hint=str(project),
        started_at=timestamp,
        updated_at=timestamp,
        title=f"{harness} continuity fixture",
        health=SessionHealth.COMPLETE,
    )


def _turns(native_id: str) -> tuple[VisibleTurn, ...]:
    return (
        VisibleTurn(
            0,
            TurnRole.USER,
            f"Recover the {native_id} decision with PASSWORD=fixture-secret.",
            f"message:{native_id}:user",
            NOW,
        ),
        VisibleTurn(
            1,
            TurnRole.AGENT,
            f"The evidence-backed next action for {native_id} is ready.",
            f"message:{native_id}:assistant",
            NOW + timedelta(seconds=1),
        ),
    )


def test_clean_database_multisource_context_continues_into_exact_opencode_target(
    tmp_path: Path,
) -> None:
    project_path = tmp_path / "project"
    project_path.mkdir()
    project = resolve_project(project_path)
    sources = (
        _record(project_path, "codex", "codex-source", 0),
        _record(project_path, "grok", "grok-source", 1),
        _record(project_path, "opencode", "opencode-source", 2),
    )
    target_id = "ses_tangAcceptanceTarget00000000000001"
    target = _record(project_path, "opencode", target_id, 3)
    adapters = (
        FixtureAdapter(
            "codex",
            "acceptance-codex",
            (sources[0],),
            {"codex-source": _turns("codex-source")},
        ),
        FixtureAdapter(
            "grok",
            "acceptance-grok",
            (sources[1],),
            {"grok-source": _turns("grok-source")},
        ),
        FixtureAdapter(
            "opencode",
            "acceptance-opencode",
            (sources[2], target),
            {
                "opencode-source": _turns("opencode-source"),
                target_id: _turns(target_id),
            },
        ),
    )
    connection = open_database(project_path / ".tang" / "tang.db")
    repository = TangRepository(connection)
    try:
        indexed = ProjectIndexer(repository).index(adapters, project, now=NOW)
        source_ids = tuple(source.identity.canonical for source in sources)
        pack = ContextPackService(repository, adapters).generate(
            source_ids, project.key
        )
        document = pack.as_dict()

        assert indexed.indexed == 4
        assert indexed.status == pack.status == "complete"
        assert {section.harness for section in pack.sections} == {
            "codex",
            "grok",
            "opencode",
        }
        assert all(section.excerpts for section in pack.sections)
        assert "fixture-secret" not in pack.to_json()
        assert "untrusted" in str(document["untrusted_data_envelope"]).lower()

        context = OpenCodeTargetContext.from_host(
            session_id=target.identity.native_id,
            directory=project_path,
            worktree=project_path,
            observed_source=target,
        )
        pending = resolve_opencode_target(
            repository.sessions_for_project(project.key), project, context
        )
        assert pending.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
        confirmed = confirm_target(pending, target.identity)
        linked = ContinuationService(repository).link_resolved(
            source_ids, confirmed, project.key, NOW
        )

        assert (linked.inserted, linked.existing) == (3, 0)
        graph = GraphService(repository).component(
            target.identity.canonical, current_id=target.identity.canonical
        )
        assert len(graph.edges) == 3
        assert {node.harness for node in graph.nodes} == {
            "codex",
            "grok",
            "opencode",
        }
        assert next(node for node in graph.nodes if node.current).source_id == (
            target.identity.canonical
        )

        with repository.transaction():
            purged = repository.purge_all()
        assert (purged.sessions, purged.capsules, purged.continuations) == (4, 4, 3)
        assert all(adapter.records for adapter in adapters)
    finally:
        connection.close()
