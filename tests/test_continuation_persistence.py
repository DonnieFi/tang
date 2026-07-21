from datetime import datetime, timezone

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.continuation_persistence import insert_continuation
from tang.repository import StoredContinuation, TangRepository
from tang.storage import open_database


def test_insert_continuation_is_idempotent(tmp_path) -> None:
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    edge = StoredContinuation(
        "codex:ns:a",
        "codex:ns:b",
        "project",
        "explicit",
        now,
    )
    with repository.transaction():
        for native_id in ("a", "b"):
            repository.upsert_session(
                SourceRecord(
                    SessionIdentity("codex", "ns", native_id),
                    OpaqueSourceLocator(f"loc:{native_id}"),
                    SourceFingerprint("sha256", native_id),
                    "/fixture",
                    now,
                    now,
                    SessionHealth.COMPLETE,
                ),
                "project",
                now,
            )
        assert insert_continuation(repository, edge)
        assert not insert_continuation(repository, edge)
    connection.close()
