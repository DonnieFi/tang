"""Single persistence entry for confirmed continuation edges."""

from __future__ import annotations

from tang.repository import StoredContinuation, TangRepository


def insert_continuation(
    repository: TangRepository, continuation: StoredContinuation
) -> bool:
    """Insert one confirmed edge; return false when it already exists."""

    return repository.insert_continuation_if_absent(continuation)
