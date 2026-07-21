"""Project-scoped graph material loaded in one repository pass."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tang.adapters import SessionHealth
from tang.repository import StoredContinuation, TangRepository


@dataclass(frozen=True, slots=True)
class MultiverseMaterialNode:
    source_id: str
    handle: str
    harness: str
    native_id: str
    display_title: str | None
    updated_at: datetime
    health: SessionHealth
    native_available: bool


@dataclass(frozen=True, slots=True)
class MultiverseMaterial:
    project_key: str
    nodes: tuple[MultiverseMaterialNode, ...]
    edges: tuple[StoredContinuation, ...]


def load_multiverse_material(
    repository: TangRepository,
    project_key: str,
    component_ids: frozenset[str],
    *,
    project_edges: tuple[StoredContinuation, ...] | None = None,
) -> MultiverseMaterial:
    """Return graph nodes and project edges without exposing capsule JSON shape.

    Pass ``project_edges`` when the caller already loaded them (e.g. for
    weak-component membership) so the project edge query is not repeated.
    """

    sessions = repository.graph_sessions(project_key, tuple(component_ids))
    edges_all = (
        project_edges
        if project_edges is not None
        else repository.continuations_for_project(project_key)
    )
    edges = tuple(
        edge
        for edge in edges_all
        if edge.source_id in component_ids and edge.target_id in component_ids
    )
    nodes = tuple(
        MultiverseMaterialNode(
            source_id=item.session.source.identity.canonical,
            handle=item.session.handle,
            harness=item.session.source.identity.adapter,
            native_id=item.session.source.identity.native_id,
            display_title=item.title,
            updated_at=item.session.source.updated_at,
            health=item.session.source.health,
            native_available=item.session.native_available,
        )
        for item in sessions
    )
    return MultiverseMaterial(project_key, nodes, edges)
