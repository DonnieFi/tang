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
from tang.multiverse_material import load_multiverse_material


MAX_TIMELINE_LANES = 256


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
    timelines_truncated: bool = False


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
        material = load_multiverse_material(
            self._repository,
            project_key,
            component_ids,
            project_edges=project_edges,
        )
        sessions_by_id = {node.source_id: node for node in material.nodes}
        nodes = tuple(
            GraphNode(
                source_id=source_id,
                handle=sessions_by_id[source_id].handle,
                harness=sessions_by_id[source_id].harness,
                native_id=sessions_by_id[source_id].native_id,
                title=self._title(sessions_by_id[source_id].display_title),
                updated_at=sessions_by_id[source_id].updated_at,
                health=sessions_by_id[source_id].health,
                native_available=sessions_by_id[source_id].native_available,
                current=source_id == current_id,
            )
            for source_id in sorted(
                sessions_by_id,
                key=lambda value: (
                    sessions_by_id[value].updated_at,
                    value,
                ),
            )
        )
        edges = tuple(
            GraphEdge(edge.source_id, edge.target_id, edge.confirmed_at)
            for edge in material.edges
        )
        timelines, timelines_truncated = self._timelines(component_ids, edges)
        return MultiverseGraph(
            project_key,
            nodes,
            edges,
            timelines,
            timelines_truncated,
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
    ) -> tuple[tuple[tuple[str, ...], ...], bool]:
        outgoing = {node: [] for node in component_ids}
        incoming = {node: 0 for node in component_ids}
        for edge in edges:
            outgoing[edge.source_id].append(edge.target_id)
            incoming[edge.target_id] += 1
        roots = sorted(node for node, count in incoming.items() if count == 0)
        paths: list[tuple[str, ...]] = []
        stack = [(root, ()) for root in reversed(roots)]
        while stack and len(paths) <= MAX_TIMELINE_LANES:
            node, path = stack.pop()
            current = (*path, node)
            targets = sorted(outgoing[node])
            if not targets:
                paths.append(current)
                continue
            for target in reversed(targets):
                stack.append((target, current))
        truncated = len(paths) > MAX_TIMELINE_LANES or bool(stack)
        return tuple(sorted(paths[:MAX_TIMELINE_LANES])), truncated
