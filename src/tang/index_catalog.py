"""Atomic index write ordering behind one internal catalog seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tang.adapters import AdapterCheckpoint, SessionIdentity, SourceRecord
from tang.repository import StoredCapsule, TangRepository


@dataclass(frozen=True, slots=True)
class IndexWriteBatch:
    pending: tuple[tuple[SourceRecord, StoredCapsule], ...]
    removable: tuple[SessionIdentity, ...]
    checkpoint: AdapterCheckpoint | None
    checkpoint_changed: bool
    project_key: str
    indexed_at: datetime


class IndexCatalog:
    """Commit validated index deltas in one transaction."""

    def __init__(self, repository: TangRepository) -> None:
        self._repository = repository

    def commit(self, batch: IndexWriteBatch) -> None:
        if not (
            batch.pending or batch.removable or batch.checkpoint_changed
        ):
            return
        with self._repository.transaction():
            for source, capsule in batch.pending:
                self._repository.upsert_session(
                    source, batch.project_key, batch.indexed_at
                )
                self._repository.put_capsule(capsule)
            for identity in batch.removable:
                self._repository.delete_session(identity.canonical)
            if batch.checkpoint_changed:
                if batch.checkpoint is None:
                    raise RuntimeError(
                        "checkpoint change requires a next checkpoint"
                    )
                self._repository.put_checkpoint(
                    batch.checkpoint, batch.project_key, batch.indexed_at
                )
