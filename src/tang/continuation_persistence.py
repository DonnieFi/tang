"""Single persistence entry for confirmed continuation edges."""

from __future__ import annotations

from tang.repository import StoredContinuation, TangRepository
from tang.timeutil import rfc3339


def insert_continuation(
    repository: TangRepository, continuation: StoredContinuation
) -> bool:
    """Insert one confirmed edge; return false when it already exists."""

    repository._require_transaction()
    cursor = repository._connection.execute(
        """
        INSERT INTO continuation_edges(
            source_id, target_id, project_key, confirmation_mode,
            confirmed_at, schema_version
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(source_id, target_id) DO NOTHING
        """,
        (
            continuation.source_id,
            continuation.target_id,
            continuation.project_key,
            continuation.confirmation_mode,
            rfc3339(continuation.confirmed_at),
            continuation.schema_version,
        ),
    )
    return cursor.rowcount == 1
