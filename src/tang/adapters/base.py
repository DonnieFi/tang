"""Typed contracts shared by all read-only session adapters.

The adapter seam intentionally consists of two operations: ``scan`` discovers
source records and ``read`` returns visible turns for one of those records.
Native formats, paths, fingerprints, and incremental cursors remain adapter
implementation details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Protocol, runtime_checkable
from unicodedata import category


def _identity_segment(value: str, name: str) -> str:
    if (
        not value
        or value.strip() != value
        or ":" in value
        or any(category(character).startswith("C") for character in value)
    ):
        raise ValueError(
            f"{name} must be non-empty, trimmed, contain no colon, and contain no controls"
        )
    return value


def _utc(value: datetime, name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _optional_utc(value: datetime | None, name: str) -> datetime | None:
    return None if value is None else _utc(value, name)


class BatchStatus(StrEnum):
    """Whether an adapter result is complete, degraded, or unavailable."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class SessionHealth(StrEnum):
    """A cautious health signal supported by native session evidence."""

    COMPLETE = "complete"
    POSSIBLY_INTERRUPTED = "possibly_interrupted"
    UNKNOWN = "unknown"


class TurnRole(StrEnum):
    """Visible conversation roles accepted across the adapter seam."""

    USER = "user"
    AGENT = "agent"


@dataclass(frozen=True, slots=True, order=True)
class SessionIdentity:
    """Collision-resistant identity: ``adapter:namespace:native-id``."""

    adapter: str
    source_namespace: str
    native_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _identity_segment(self.adapter, "adapter"))
        object.__setattr__(
            self,
            "source_namespace",
            _identity_segment(self.source_namespace, "source_namespace"),
        )
        object.__setattr__(
            self, "native_id", _identity_segment(self.native_id, "native_id")
        )

    @property
    def canonical(self) -> str:
        return f"{self.adapter}:{self.source_namespace}:{self.native_id}"

    def __str__(self) -> str:
        return self.canonical


@dataclass(frozen=True, slots=True)
class OpaqueSourceLocator:
    """Adapter-owned locator that core code stores but never parses."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("source locator must not be empty")


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """Adapter-owned change token for one native source."""

    algorithm: str
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "algorithm", _identity_segment(self.algorithm, "fingerprint algorithm")
        )
        if not self.value:
            raise ValueError("fingerprint value must not be empty")


@dataclass(frozen=True, slots=True)
class AdapterCheckpoint:
    """Opaque incremental cursor scoped to one adapter namespace."""

    adapter: str
    source_namespace: str
    cursor: str = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter", _identity_segment(self.adapter, "adapter"))
        object.__setattr__(
            self,
            "source_namespace",
            _identity_segment(self.source_namespace, "source_namespace"),
        )
        if not self.cursor:
            raise ValueError("checkpoint cursor must not be empty")


@dataclass(frozen=True, slots=True)
class AdapterWarning:
    """Non-fatal, redaction-boundary warning returned with usable results."""

    code: str
    message: str = field(repr=False)
    identity: SessionIdentity | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _identity_segment(self.code, "warning code"))
        if not self.message:
            raise ValueError("warning message must not be empty")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        identity = self.identity.canonical if self.identity is not None else ""
        return (self.code, identity, self.message)


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Native-format-independent metadata for a discoverable session."""

    identity: SessionIdentity
    locator: OpaqueSourceLocator
    fingerprint: SourceFingerprint
    project_hint: str = field(repr=False)
    started_at: datetime
    updated_at: datetime
    title: str | None = field(default=None, repr=False)
    health: SessionHealth = SessionHealth.UNKNOWN

    def __post_init__(self) -> None:
        if not self.project_hint:
            raise ValueError("project hint must not be empty")
        if not isinstance(self.health, SessionHealth):
            raise TypeError("health must be a SessionHealth")
        started_at = _utc(self.started_at, "started_at")
        updated_at = _utc(self.updated_at, "updated_at")
        if updated_at < started_at:
            raise ValueError("updated_at must not precede started_at")
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "updated_at", updated_at)


@dataclass(frozen=True, slots=True)
class VisibleTurn:
    """One visible user or agent turn; text is sensitive until redacted."""

    ordinal: int
    role: TurnRole
    text: str = field(repr=False)
    citation_locator: str
    timestamp: datetime | None = None

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("turn ordinal must be non-negative")
        if not isinstance(self.role, TurnRole):
            raise TypeError("role must be a TurnRole")
        if not self.text:
            raise ValueError("visible turn text must not be empty")
        if not self.citation_locator:
            raise ValueError("citation locator must not be empty")
        object.__setattr__(
            self, "timestamp", _optional_utc(self.timestamp, "turn timestamp")
        )


@dataclass(frozen=True, slots=True)
class TurnSelection:
    """Adapter-neutral half-open ordinal range of visible turns."""

    start_at: int = 0
    stop_before: int | None = None

    def __post_init__(self) -> None:
        if self.start_at < 0:
            raise ValueError("selection start must be non-negative")
        if self.stop_before is not None and self.stop_before <= self.start_at:
            raise ValueError("selection stop must be greater than its start")

    def includes(self, ordinal: int) -> bool:
        return ordinal >= self.start_at and (
            self.stop_before is None or ordinal < self.stop_before
        )


def _ordered_warnings(
    warnings: tuple[AdapterWarning, ...],
) -> tuple[AdapterWarning, ...]:
    return tuple(sorted(warnings, key=lambda warning: warning.sort_key))


def _validate_status(
    status: BatchStatus,
    warnings: tuple[AdapterWarning, ...],
    item_count: int,
) -> None:
    if not isinstance(status, BatchStatus):
        raise TypeError("status must be a BatchStatus")
    if status is not BatchStatus.COMPLETE and not warnings:
        raise ValueError("partial and unavailable results require at least one warning")
    if status is BatchStatus.UNAVAILABLE and item_count:
        raise ValueError("unavailable results cannot contain usable items")


@dataclass(frozen=True, slots=True)
class ScanBatch:
    """Deterministically ordered records and warnings from ``scan``."""

    status: BatchStatus
    records: tuple[SourceRecord, ...] = ()
    next_checkpoint: AdapterCheckpoint | None = None
    warnings: tuple[AdapterWarning, ...] = ()

    def __post_init__(self) -> None:
        records = tuple(sorted(self.records, key=lambda record: record.identity.canonical))
        identities = [record.identity for record in records]
        if len(set(identities)) != len(identities):
            raise ValueError("scan results cannot contain duplicate session identities")
        warnings = _ordered_warnings(self.warnings)
        _validate_status(self.status, warnings, len(records))
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "warnings", warnings)


@dataclass(frozen=True, slots=True)
class TurnBatch:
    """Chronological visible turns and warnings from ``read``."""

    identity: SessionIdentity
    status: BatchStatus
    turns: tuple[VisibleTurn, ...] = ()
    warnings: tuple[AdapterWarning, ...] = ()

    def __post_init__(self) -> None:
        turns = tuple(sorted(self.turns, key=lambda turn: turn.ordinal))
        ordinals = [turn.ordinal for turn in turns]
        if len(set(ordinals)) != len(ordinals):
            raise ValueError("read results cannot contain duplicate turn ordinals")
        warnings = _ordered_warnings(self.warnings)
        _validate_status(self.status, warnings, len(turns))
        object.__setattr__(self, "turns", turns)
        object.__setattr__(self, "warnings", warnings)


@runtime_checkable
class SessionAdapter(Protocol):
    """Deep adapter interface; implementations own every native-format detail."""

    adapter_key: str
    source_namespace: str

    def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
        """Discover changed sessions, returning partial data with warnings."""
        ...

    def read(
        self, session_ref: SourceRecord, selection: TurnSelection
    ) -> TurnBatch:
        """Read visible turns, returning partial data with warnings."""
        ...
