from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tang.adapters import (
    AdapterCheckpoint,
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.repository import StoredCapsule, TangRepository
from tang.storage import BUSY_TIMEOUT_MS, open_database


NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)


def source(native_id: str, fingerprint: str = "digest-1") -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity("codex", "fixture", native_id),
        locator=OpaqueSourceLocator(f"/private/{native_id}.jsonl"),
        fingerprint=SourceFingerprint("sha256", fingerprint),
        project_hint="/private/project",
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=1),
        health=SessionHealth.UNKNOWN,
    )


def capsule(record: SourceRecord, text: str = "recover checkpoint") -> StoredCapsule:
    content: dict[str, object] = {
        "schema_version": 1,
        "source_id": record.identity.canonical,
        "excerpts": [text],
    }
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return StoredCapsule(
        source_id=record.identity.canonical,
        project_key="project-a",
        content=content,
        search_text=text,
        byte_count=len(encoded),
        updated_at=NOW,
    )


def test_insert_update_delete_and_fts_synchronization(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "repo" / "tang.db")
    repository = TangRepository(connection)
    original = source("session-1")
    try:
        with repository.transaction():
            repository.upsert_session(original, "project-a", NOW)
            repository.put_capsule(capsule(original))

        stored = repository.get_session(original.identity.canonical)
        assert stored is not None
        assert stored.source == original
        assert stored.project_key == "project-a"
        assert repository.search_capsule_ids("project-a", "checkpoint") == (
            original.identity.canonical,
        )

        changed = source("session-1", "digest-2")
        with repository.transaction():
            repository.upsert_session(changed, "project-a", NOW + timedelta(seconds=1))
            repository.put_capsule(capsule(changed, "updated recovery"))

        assert repository.fingerprint_for(changed.identity.canonical) == changed.fingerprint
        assert repository.search_capsule_ids("project-a", "checkpoint") == ()
        assert repository.search_capsule_ids("project-a", "updated") == (
            changed.identity.canonical,
        )

        with repository.transaction():
            repository.delete_session(changed.identity.canonical)
        assert repository.get_session(changed.identity.canonical) is None
        assert repository.get_capsule(changed.identity.canonical) is None
        assert repository.search_capsule_ids("project-a", "updated") == ()
    finally:
        connection.close()


def test_rollback_leaves_no_partial_session_or_checkpoint(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "rollback" / "tang.db")
    repository = TangRepository(connection)
    record = source("rollback")
    checkpoint = AdapterCheckpoint("codex", "fixture", "cursor")
    try:
        with pytest.raises(RuntimeError, match="abort"):
            with repository.transaction():
                repository.upsert_session(record, "project-a", NOW)
                repository.put_checkpoint(checkpoint, NOW)
                raise RuntimeError("abort transaction")

        assert repository.get_session(record.identity.canonical) is None
        assert repository.get_checkpoint("codex", "fixture") is None
    finally:
        connection.close()


def test_checkpoint_and_rows_survive_restart(tmp_path: Path) -> None:
    path = tmp_path / "restart" / "tang.db"
    record = source("restart")
    checkpoint = AdapterCheckpoint("codex", "fixture", "stable-cursor")
    first = open_database(path)
    repository = TangRepository(first)
    with repository.transaction():
        repository.upsert_session(record, "project-a", NOW)
        repository.put_checkpoint(checkpoint, NOW)
    first.close()

    second = open_database(path)
    try:
        reopened = TangRepository(second)
        assert reopened.get_session(record.identity.canonical) is not None
        assert reopened.get_checkpoint("codex", "fixture") == checkpoint
    finally:
        second.close()


def test_writes_require_boundaries_and_nested_transactions_fail(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "boundaries" / "tang.db")
    repository = TangRepository(connection)
    try:
        with pytest.raises(RuntimeError, match="explicit transaction"):
            repository.upsert_session(source("outside"), "project-a", NOW)
        with repository.transaction():
            with pytest.raises(RuntimeError, match="nested"):
                with repository.transaction():
                    pass
    finally:
        connection.close()


def test_capsule_cannot_cross_its_session_project(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "capsule-project" / "tang.db")
    repository = TangRepository(connection)
    record = source("project-boundary")
    try:
        with repository.transaction():
            repository.upsert_session(record, "project-b", NOW)
            with pytest.raises(ValueError, match="session project"):
                repository.put_capsule(capsule(record))
    finally:
        connection.close()


def test_busy_timeout_and_concurrent_reader_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "concurrent" / "tang.db"
    writer = open_database(path)
    reader = open_database(path)
    writer_repository = TangRepository(writer)
    reader_repository = TangRepository(reader)
    record = source("concurrent")
    try:
        assert writer.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        assert reader.execute("PRAGMA busy_timeout").fetchone()[0] == BUSY_TIMEOUT_MS
        with writer_repository.transaction():
            writer_repository.upsert_session(record, "project-a", NOW)
            assert reader_repository.get_session(record.identity.canonical) is None
        assert reader_repository.get_session(record.identity.canonical) is not None
    finally:
        reader.close()
        writer.close()


def test_adapters_do_not_import_repository_or_sql() -> None:
    adapters = Path("src/tang/adapters")
    combined = "\n".join(path.read_text() for path in adapters.glob("*.py"))

    assert "tang.repository" not in combined
    assert "sqlite3" not in combined
