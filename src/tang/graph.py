"""Deterministic Multiverse component and Timeline traversal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tang.adapters import SessionHealth
from tang.redaction import (
    DEFAULT_REDACTOR,
    ContentKind,
    RedactionSeam,
    Redactor,
    required_redaction,
)
from tang.repository import StoredContinuation, TangRepository


@dataclass(frozen=True, slots=True)
class GraphNode:
    source_id: str
    handle: str
    harness: str
    native_id: str
    title: str | None
    updated_at: datetime
    health: SessionHealth
    native_available: bool
    current: bool


@dataclass(frozen=True, slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    confirmed_at: datetime


@dataclass(frozen=True, slots=True)
class MultiverseGraph:
    project_key: str
    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    timelines: tuple[tuple[str, ...], ...]


class GraphService:
    def __init__(
        self, repository: TangRepository, *, redactor: Redactor = DEFAULT_REDACTOR
    ) -> None:
        self._repository = repository
        self._redactor = redactor

    def component(
        self, session_id: str, *, current_id: str | None = None
    ) -> MultiverseGraph:
        anchor = self._repository.get_session(session_id)
        if anchor is None:
            raise ValueError("session is not indexed")
        project_key = anchor.project_key
        project_edges = self._repository.continuations_for_project(project_key)
        component_ids = self._weak_component(session_id, project_edges)
        sessions = {
            item.session.source.identity.canonical: item
            for item in self._repository.graph_sessions(
                project_key, tuple(component_ids)
            )
        }
        nodes = tuple(
            GraphNode(
                source_id=source_id,
                handle=sessions[source_id].session.handle,
                harness=sessions[source_id].session.source.identity.adapter,
                native_id=sessions[source_id].session.source.identity.native_id,
                title=self._title(sessions[source_id].title),
                updated_at=sessions[source_id].session.source.updated_at,
                health=sessions[source_id].session.source.health,
                native_available=sessions[source_id].session.native_available,
                current=source_id == current_id,
            )
            for source_id in sorted(
                sessions,
                key=lambda value: (sessions[value].session.source.updated_at, value),
            )
        )
        edges = tuple(
            GraphEdge(edge.source_id, edge.target_id, edge.confirmed_at)
            for edge in project_edges
            if edge.source_id in component_ids and edge.target_id in component_ids
        )
        return MultiverseGraph(
            project_key,
            nodes,
            edges,
            self._timelines(component_ids, edges),
        )

    def _title(self, title: str | None) -> str | None:
        if title is None:
            return None
        result = required_redaction(
            self._redactor,
            RedactionSeam.GRAPH_LABEL,
            ContentKind.TITLE,
            title,
        )
        return result.text

    @staticmethod
    def _weak_component(
        anchor: str, edges: tuple[StoredContinuation, ...]
    ) -> frozenset[str]:
        neighbors: dict[str, set[str]] = {anchor: set()}
        for edge in edges:
            neighbors.setdefault(edge.source_id, set()).add(edge.target_id)
            neighbors.setdefault(edge.target_id, set()).add(edge.source_id)
        found: set[str] = set()
        pending = [anchor]
        while pending:
            node = pending.pop()
            if node in found:
                continue
            found.add(node)
            pending.extend(sorted(neighbors.get(node, ()), reverse=True))
        return frozenset(found)

    @staticmethod
    def _timelines(
        component_ids: frozenset[str], edges: tuple[GraphEdge, ...]
    ) -> tuple[tuple[str, ...], ...]:
        outgoing = {node: [] for node in component_ids}
        incoming = {node: 0 for node in component_ids}
        for edge in edges:
            outgoing[edge.source_id].append(edge.target_id)
            incoming[edge.target_id] += 1
        roots = sorted(node for node, count in incoming.items() if count == 0)
        paths: list[tuple[str, ...]] = []

        def walk(node: str, path: tuple[str, ...]) -> None:
            targets = sorted(outgoing[node])
            if not targets:
                paths.append((*path, node))
                return
            for target in targets:
                walk(target, (*path, node))

        for root in roots:
            walk(root, ())
        return tuple(sorted(paths))
