"""Atomic validation and insertion of explicit continuation edges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tang.repository import StoredContinuation, TangRepository
from tang.target import TargetResolution, TargetResolutionKind


class ContinuationError(ValueError):
    """A structured refusal that is safe to expose through CLI surfaces."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class LinkResult:
    source_ids: tuple[str, ...]
    target_id: str
    inserted: int
    existing: int


class ContinuationService:
    def __init__(self, repository: TangRepository) -> None:
        self._repository = repository

    def link_resolved(
        self,
        source_ids: tuple[str, ...],
        resolution: TargetResolution,
        project_key: str,
        confirmed_at: datetime,
    ) -> LinkResult:
        """Link only through a uniquely resolved or explicitly confirmed target."""

        if resolution.kind is not TargetResolutionKind.RESOLVED or resolution.target is None:
            raise ContinuationError(
                "target-unconfirmed",
                "The current Codex target must be confirmed before linking.",
            )
        return self.link(
            source_ids,
            resolution.target.identity.canonical,
            project_key,
            "current",
            confirmed_at,
        )

    def link(
        self,
        source_ids: tuple[str, ...],
        target_id: str,
        project_key: str,
        confirmation_mode: str,
        confirmed_at: datetime,
    ) -> LinkResult:
        if not source_ids:
            raise ContinuationError("no-sources", "Select at least one source session.")
        ordered = tuple(dict.fromkeys(source_ids))
        if len(ordered) != len(source_ids):
            raise ContinuationError("duplicate-source", "A source was selected more than once.")
        if target_id in ordered:
            raise ContinuationError("self-link", "A session cannot continue into itself.")

        with self._repository.transaction():
            target = self._repository.get_session(target_id)
            if target is None:
                raise ContinuationError("unknown-target", "The target session is not indexed.")
            if target.project_key != project_key:
                raise ContinuationError(
                    "foreign-target", "The target does not belong to the current project."
                )
            if target.source.identity.adapter != "codex":
                raise ContinuationError(
                    "unsupported-target", "The release target must be a Codex session."
                )

            sources = {}
            for source_id in ordered:
                source = self._repository.get_session(source_id)
                if source is None:
                    raise ContinuationError(
                        "unknown-source", "A selected source session is not indexed."
                    )
                if source.project_key != project_key:
                    raise ContinuationError(
                        "foreign-source",
                        "A selected source does not belong to the current project.",
                    )
                sources[source_id] = source

            existing = self._repository.continuations_for_project(project_key)
            existing_pairs = {
                (edge.source_id, edge.target_id) for edge in existing
            }
            new_sources = tuple(
                source_id
                for source_id in ordered
                if (source_id, target_id) not in existing_pairs
            )
            if new_sources and not target.native_available:
                raise ContinuationError(
                    "unavailable-target",
                    "The target native session is unavailable and cannot receive a new continuation.",
                )
            for source_id in new_sources:
                if not sources[source_id].native_available:
                    raise ContinuationError(
                        "unavailable-source",
                        "A selected native source is unavailable and cannot form a new continuation.",
                    )

            candidates = tuple((source_id, target_id) for source_id in ordered)
            if self._introduces_cycle(existing, candidates):
                raise ContinuationError(
                    "cycle", "The requested continuation would create a cycle."
                )

            inserted = 0
            for source_id in ordered:
                inserted += int(
                    self._repository.put_continuation(
                        StoredContinuation(
                            source_id,
                            target_id,
                            project_key,
                            confirmation_mode,
                            confirmed_at,
                        )
                    )
                )
        return LinkResult(ordered, target_id, inserted, len(ordered) - inserted)

    @staticmethod
    def _introduces_cycle(
        existing: tuple[StoredContinuation, ...],
        candidates: tuple[tuple[str, str], ...],
    ) -> bool:
        adjacency: dict[str, set[str]] = {}
        for source, target in (
            *((edge.source_id, edge.target_id) for edge in existing),
            *candidates,
        ):
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set())

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(node: str) -> bool:
            if node in visiting:
                return True
            if node in visited:
                return False
            visiting.add(node)
            if any(visit(target) for target in sorted(adjacency[node])):
                return True
            visiting.remove(node)
            visited.add(node)
            return False

        return any(visit(node) for node in sorted(adjacency))
