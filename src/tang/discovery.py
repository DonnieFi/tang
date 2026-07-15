"""Current-project browse and search rendering models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tang.adapters import SessionHealth
from tang.redaction import (
    ContentKind,
    DEFAULT_REDACTOR,
    RedactionSeam,
    Redactor,
    required_redaction,
)
from tang.repository import DiscoveryRow, TangRepository
from tang.timeutil import rfc3339


@dataclass(frozen=True, slots=True)
class DiscoveryFilter:
    harness: str | None = None
    health: SessionHealth | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryItem:
    source_id: str
    harness: str
    updated_at: datetime
    health: SessionHealth
    title: str | None
    capabilities: tuple[str, ...]
    snippet: str | None


class DiscoveryService:
    def __init__(
        self, repository: TangRepository, *, redactor: Redactor = DEFAULT_REDACTOR
    ) -> None:
        self._repository = repository
        self._redactor = redactor

    def browse(
        self, project_key: str, filters: DiscoveryFilter = DiscoveryFilter()
    ) -> tuple[DiscoveryItem, ...]:
        return self._items(
            self._repository.browse_discovery(
                project_key,
                harness=filters.harness,
                health=filters.health,
                since=filters.since,
                until=filters.until,
            )
        )

    def search(
        self,
        project_key: str,
        query: str,
        filters: DiscoveryFilter = DiscoveryFilter(),
    ) -> tuple[DiscoveryItem, ...]:
        return self._items(
            self._repository.search_discovery(
                project_key,
                query,
                harness=filters.harness,
                health=filters.health,
                since=filters.since,
                until=filters.until,
            )
        )

    def _items(self, rows: tuple[DiscoveryRow, ...]) -> tuple[DiscoveryItem, ...]:
        return tuple(self._item(row) for row in rows)

    def _item(self, row: DiscoveryRow) -> DiscoveryItem:
        title = self._redact(row.title, ContentKind.TITLE)
        snippet = self._redact(row.snippet, ContentKind.VISIBLE_TEXT)
        return DiscoveryItem(
            source_id=row.source_id,
            harness=row.harness,
            updated_at=row.updated_at,
            health=row.health,
            title=title,
            capabilities=row.capabilities,
            snippet=snippet,
        )

    def _redact(self, value: str | None, kind: ContentKind) -> str | None:
        if value is None:
            return None
        result = required_redaction(
            self._redactor,
            RedactionSeam.SNIPPET_DISPLAY, kind, value
        )
        return " ".join(result.text.split())
