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
    conceal_native_session_ids,
    required_redaction,
)
from tang.repository import DiscoveryRow, TangRepository
from tang.timeutil import rfc3339


DISCOVERY_PAGE_SIZE = 5
_DISPLAY_NAME_CHARACTER_LIMIT = 96
_DISPLAY_SNIPPET_CHARACTER_LIMIT = 240
_TRUNCATED_DISPLAY_NAME = "…[Truncated]"


@dataclass(frozen=True, slots=True)
class DiscoveryFilter:
    harness: str | None = None
    health: SessionHealth | None = None
    since: datetime | None = None
    until: datetime | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryItem:
    source_id: str
    handle: str
    display_name: str
    harness: str
    updated_at: datetime
    health: SessionHealth
    title: str | None
    capabilities: tuple[str, ...]
    snippet: str | None
    model_provider: str | None
    model_id: str | None
    effort: str | None
    title_origin: str | None
    visible_turn_count: int | None
    visible_text_bytes: int | None


@dataclass(frozen=True, slots=True)
class DiscoveryChoice:
    """A visible human choice with its authoritative private source."""

    number: int
    item: DiscoveryItem


@dataclass(frozen=True, slots=True)
class DiscoveryPage:
    """A stable bounded page used by human output and host selection."""

    number: int
    page_count: int
    result_count: int
    choices: tuple[DiscoveryChoice, ...]

    @property
    def has_next(self) -> bool:
        return self.number < self.page_count

    @property
    def has_previous(self) -> bool:
        return self.number > 1

    def resolve_numbers(self, numbers: tuple[int, ...]) -> tuple[DiscoveryItem, ...]:
        """Resolve only visible choice numbers in deterministic display order."""

        if not numbers:
            raise ValueError("select at least one visible choice number")
        by_number = {choice.number: choice.item for choice in self.choices}
        selected_numbers: set[int] = set()
        for number in numbers:
            if isinstance(number, bool) or not isinstance(number, int):
                raise ValueError("choice numbers must be integers")
            if number not in by_number:
                raise ValueError("choice number is not on the current result page")
            selected_numbers.add(number)
        return tuple(
            choice.item
            for choice in self.choices
            if choice.number in selected_numbers
        )


def discovery_page(
    items: tuple[DiscoveryItem, ...], page_number: int
) -> DiscoveryPage:
    """Return one deterministic five-item page without inventing a selection."""

    if page_number < 1:
        raise ValueError("page number must be at least 1")
    result_count = len(items)
    page_count = max(1, (result_count + DISCOVERY_PAGE_SIZE - 1) // DISCOVERY_PAGE_SIZE)
    if page_number > page_count:
        raise ValueError(f"page {page_number} is out of range; {page_count} page(s) available")
    start = (page_number - 1) * DISCOVERY_PAGE_SIZE
    return DiscoveryPage(
        number=page_number,
        page_count=page_count,
        result_count=result_count,
        choices=tuple(
            DiscoveryChoice(number, item)
            for number, item in enumerate(
                items[start : start + DISCOVERY_PAGE_SIZE], start=start + 1
            )
        ),
    )


class DiscoveryService:
    def __init__(
        self, repository: TangRepository, *, redactor: Redactor = DEFAULT_REDACTOR
    ) -> None:
        self._repository = repository
        self._redactor = redactor

    def browse(
        self,
        project_key: str,
        filters: DiscoveryFilter = DiscoveryFilter(),
        *,
        exclude_source_ids: tuple[str, ...] = (),
    ) -> tuple[DiscoveryItem, ...]:
        return self._items(
            self._repository.browse_discovery(
                project_key,
                harness=filters.harness,
                health=filters.health,
                since=filters.since,
                until=filters.until,
                exclude_source_ids=exclude_source_ids,
            )
        )

    def search(
        self,
        project_key: str,
        query: str,
        filters: DiscoveryFilter = DiscoveryFilter(),
        *,
        limit: int = 20,
        exclude_source_ids: tuple[str, ...] = (),
    ) -> tuple[DiscoveryItem, ...]:
        return self._items(
            self._repository.search_discovery(
                project_key,
                query,
                harness=filters.harness,
                health=filters.health,
                since=filters.since,
                until=filters.until,
                limit=limit,
                exclude_source_ids=exclude_source_ids,
            )
        )

    def _items(self, rows: tuple[DiscoveryRow, ...]) -> tuple[DiscoveryItem, ...]:
        return tuple(self._item(row) for row in rows)

    def _item(self, row: DiscoveryRow) -> DiscoveryItem:
        title = self._redact(row.title, ContentKind.TITLE, row.source_id)
        snippet = self._redact(row.snippet, ContentKind.VISIBLE_TEXT, row.source_id)
        return DiscoveryItem(
            source_id=row.source_id,
            handle=row.handle,
            display_name=self._display_name(row),
            harness=row.harness,
            updated_at=row.updated_at,
            health=row.health,
            title=title,
            capabilities=row.capabilities,
            snippet=self._bounded_snippet(snippet),
            model_provider=row.model_provider,
            model_id=row.model_id,
            effort=row.effort,
            title_origin=row.title_origin,
            visible_turn_count=row.visible_turn_count,
            visible_text_bytes=row.visible_text_bytes,
        )

    def _display_name(self, row: DiscoveryRow) -> str:
        for value, kind in (
            (row.display_name, ContentKind.DISPLAY_METADATA),
            (row.title, ContentKind.TITLE),
            (row.first_user_excerpt, ContentKind.VISIBLE_TEXT),
        ):
            displayed = self._redact(value, kind, row.source_id)
            if displayed:
                return self._bounded_display_name(displayed)
        return f"{row.harness.title()} session · {rfc3339(row.updated_at)}"

    def _redact(
        self, value: str | None, kind: ContentKind, source_id: str
    ) -> str | None:
        if value is None:
            return None
        result = required_redaction(
            self._redactor,
            RedactionSeam.SNIPPET_DISPLAY, kind, value
        )
        return conceal_native_session_ids(
            " ".join(result.text.replace(source_id, "[session]").split())
        )

    @staticmethod
    def _bounded_display_name(value: str) -> str:
        if len(value) <= _DISPLAY_NAME_CHARACTER_LIMIT:
            return value
        keep = max(1, _DISPLAY_NAME_CHARACTER_LIMIT - len(_TRUNCATED_DISPLAY_NAME))
        return value[:keep].rstrip() + _TRUNCATED_DISPLAY_NAME

    @staticmethod
    def _bounded_snippet(value: str | None) -> str | None:
        if value is None or len(value) <= _DISPLAY_SNIPPET_CHARACTER_LIMIT:
            return value
        keep = max(1, _DISPLAY_SNIPPET_CHARACTER_LIMIT - len(_TRUNCATED_DISPLAY_NAME))
        return value[:keep].rstrip() + _TRUNCATED_DISPLAY_NAME
