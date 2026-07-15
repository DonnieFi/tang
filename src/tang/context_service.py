"""Authorize selected sessions, reread native evidence, and build Context Packs."""

from __future__ import annotations

from tang.adapters import BatchStatus, SessionAdapter, TurnSelection
from tang.multicontext import (
    MultiSourceAllocator,
    MultiSourceContextPack,
    ValidatedSourceRead,
)
from tang.redaction import (
    ContentKind,
    DEFAULT_REDACTOR,
    RedactionSeam,
    required_redaction,
)
from tang.repository import TangRepository


class ContextGenerationError(ValueError):
    pass


class ContextPackService:
    def __init__(
        self,
        repository: TangRepository,
        adapters: tuple[SessionAdapter, ...],
        *,
        allocator: MultiSourceAllocator | None = None,
    ) -> None:
        self._repository = repository
        self._adapters = {
            (adapter.adapter_key, adapter.source_namespace): adapter
            for adapter in adapters
        }
        self._allocator = allocator or MultiSourceAllocator()

    def generate(
        self, source_ids: tuple[str, ...], project_key: str
    ) -> MultiSourceContextPack:
        if not source_ids:
            raise ContextGenerationError("at least one session is required")
        if len(set(source_ids)) != len(source_ids):
            raise ContextGenerationError("duplicate session selections are not allowed")

        stored = tuple(
            self._repository.get_session(source_id) for source_id in source_ids
        )
        if any(session is None for session in stored):
            raise ContextGenerationError("one or more selected sessions are not indexed")
        authorized = tuple(session for session in stored if session is not None)
        if any(session.project_key != project_key for session in authorized):
            raise ContextGenerationError(
                "all selected sessions must belong to the current project"
            )

        readable: list[ValidatedSourceRead] = []
        warnings: list[str] = []
        for session in authorized:
            source = session.source
            if not session.native_available:
                warnings.append(
                    f"source-unavailable: {source.identity.canonical} "
                    "native history is no longer available"
                )
                continue
            adapter = self._adapters.get(
                (source.identity.adapter, source.identity.source_namespace)
            )
            if adapter is None:
                warnings.append(
                    f"source-unavailable: {source.identity.canonical} has no configured adapter"
                )
                continue
            read = adapter.read(source, TurnSelection())
            if read.status is BatchStatus.UNAVAILABLE or not read.turns:
                warnings.append(
                    f"source-unavailable: {source.identity.canonical} "
                    "has no readable visible turns"
                )
                continue
            readable.append(ValidatedSourceRead(source, read, project_key))

        if not readable:
            unavailable_count = sum(
                not session.native_available for session in authorized
            )
            if unavailable_count:
                raise ContextGenerationError(
                    "none of the selected sources could be read; "
                    f"{unavailable_count} selected native source(s) are no longer available"
                )
            raise ContextGenerationError("none of the selected sources could be read")
        return self._allocator.allocate(
            tuple(readable), project_key, warnings=self._bounded_warnings(warnings)
        )

    @staticmethod
    def _bounded_warnings(warnings: list[str]) -> tuple[str, ...]:
        ordered = sorted(warnings)
        selected = ordered[:8]
        if len(ordered) > len(selected):
            selected[-1] = (
                f"additional-source-warnings-omitted: {len(ordered) - 7} omitted"
            )
        bounded: list[str] = []
        for warning in selected:
            result = required_redaction(
                DEFAULT_REDACTOR,
                RedactionSeam.CONTEXT_REREAD, ContentKind.WARNING, warning
            )
            text = result.text
            bounded.append(text if len(text) <= 240 else text[:227] + "…[Truncated]")
        return tuple(bounded)
