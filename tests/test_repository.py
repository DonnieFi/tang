from __future__ import annotations

import json
from dataclasses import replace
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
from tang.repository import StoredCapsule, StoredContinuation, TangRepository
from tang.continuation_persistence import insert_continuation
from tang.storage import BUSY_TIMEOUT_MS, open_database


NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)


def source(
    native_id: str, fingerprint: str = "digest-1", title: str | None = None
) -> SourceRecord:
    return SourceRecord(
        identity=SessionIdentity("codex", "fixture", native_id),
        locator=OpaqueSourceLocator(f"/private/{native_id}.jsonl"),
        fingerprint=SourceFingerprint("sha256", fingerprint),
        project_hint="/private/project",
        started_at=NOW,
        updated_at=NOW + timedelta(minutes=1),
        health=SessionHealth.UNKNOWN,
        title=title,
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


def test_session_title_persists_without_capsule_and_survives_empty_refresh(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "titles" / "tang.db")
    repository = TangRepository(connection)
    titled = source("session-title", title="Current OpenCode work")
    try:
        with repository.transaction():
            repository.upsert_session(titled, "project-a", NOW)

        stored = repository.get_session(titled.identity.canonical)
        assert stored is not None
        assert stored.source.title == "Current OpenCode work"
        assert repository.graph_sessions(
            "project-a", (titled.identity.canonical,)
        )[0].title == "Current OpenCode work"

        without_title = replace(
            titled,
            fingerprint=SourceFingerprint("sha256", "digest-2"),
            title=None,
        )
        with repository.transaction():
            repository.upsert_session(
                without_title, "project-a", NOW + timedelta(seconds=1)
            )

        refreshed = repository.get_session(titled.identity.canonical)
        assert refreshed is not None
        assert refreshed.source.title == "Current OpenCode work"
    finally:
        connection.close()


def test_session_title_is_redacted_and_bounded_at_persistence(
    tmp_path: Path,
) -> None:
    connection = open_database(tmp_path / "private-title" / "tang.db")
    repository = TangRepository(connection)
    secret = "graph-title-secret"
    record = source(
        "private-title",
        title=f'Release PASSWORD="{secret}" ' + ("x" * 300),
    )
    try:
        with repository.transaction():
            repository.upsert_session(record, "project-a", NOW)

        stored_title = connection.execute(
            "SELECT title FROM sessions WHERE source_id = ?",
            (record.identity.canonical,),
        ).fetchone()[0]
        assert secret not in stored_title
        assert "PASSWORD=[REDACTED:credential]" in stored_title
        assert len(stored_title) == 256
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
                repository.put_checkpoint(checkpoint, "project-a", NOW)
                raise RuntimeError("abort transaction")

        assert repository.get_session(record.identity.canonical) is None
        assert repository.get_checkpoint("codex", "fixture", "project-a") is None
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
        repository.put_checkpoint(checkpoint, "project-a", NOW)
    first.close()

    second = open_database(path)
    try:
        reopened = TangRepository(second)
        assert reopened.get_session(record.identity.canonical) is not None
        assert reopened.get_checkpoint("codex", "fixture", "project-a") == checkpoint
    finally:
        second.close()


def test_project_handles_are_short_stable_and_case_insensitive(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "handles" / "tang.db")
    repository = TangRepository(connection)
    first = source("first")
    second = source("second")
    grok = replace(
        source("grok"), identity=SessionIdentity("grok", "fixture", "grok")
    )
    foreign = source("foreign")
    try:
        with repository.transaction():
            repository.upsert_session(first, "project-a", NOW)
            repository.upsert_session(second, "project-a", NOW)
            repository.upsert_session(grok, "project-a", NOW)
            repository.upsert_session(foreign, "project-b", NOW)

        assert repository.get_session(first.identity.canonical).handle == "C1"
        assert repository.get_session(second.identity.canonical).handle == "C2"
        assert repository.get_session(grok.identity.canonical).handle == "G1"
        assert repository.get_session(foreign.identity.canonical).handle == "C1"
        assert repository.resolve_session_token("c1", "project-a") == (
            first.identity.canonical
        )
        assert repository.resolve_session_token(
            first.identity.canonical, "project-a"
        ) == first.identity.canonical

        with repository.transaction():
            repository.upsert_session(first, "project-a", NOW + timedelta(seconds=2))
        assert repository.get_session(first.identity.canonical).handle == "C1"

        with pytest.raises(ValueError, match="not indexed"):
            repository.resolve_session_token("C99", "project-a")
        with pytest.raises(ValueError, match="letter followed by a number"):
            repository.resolve_session_token("C-1", "project-a")
        with pytest.raises(ValueError, match="adapter:namespace:native-id"):
            repository.resolve_session_token("C:1", "project-a")
    finally:
        connection.close()


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


def test_continuations_are_idempotent_survive_restart_and_native_deletion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "graph" / "tang.db"
    first = open_database(path)
    repository = TangRepository(first)
    source_record = source("source")
    target_record = source("target")
    continuation = StoredContinuation(
        source_record.identity.canonical,
        target_record.identity.canonical,
        "project-a",
        "current",
        NOW,
    )
    try:
        with repository.transaction():
            repository.upsert_session(source_record, "project-a", NOW)
            repository.upsert_session(target_record, "project-a", NOW)
            assert insert_continuation(repository, continuation)
            assert not insert_continuation(repository, continuation)
        with repository.transaction():
            repository.delete_session(source_record.identity.canonical)
        retained = repository.get_session(source_record.identity.canonical)
        assert retained is not None
        assert not retained.native_available
        assert repository.continuations_for_project("project-a") == (continuation,)
    finally:
        first.close()

    reopened = open_database(path)
    try:
        assert TangRepository(reopened).continuations_for_project("project-a") == (
            continuation,
        )
    finally:
        reopened.close()


def test_purge_removes_edges_before_sessions(tmp_path: Path) -> None:
    connection = open_database(tmp_path / "purge-graph" / "tang.db")
    repository = TangRepository(connection)
    first = source("first")
    second = source("second")
    try:
        with repository.transaction():
            repository.upsert_session(first, "project-a", NOW)
            repository.upsert_session(second, "project-a", NOW)
            insert_continuation(repository, 
                StoredContinuation(
                    first.identity.canonical,
                    second.identity.canonical,
                    "project-a",
                    "explicit",
                    NOW,
                )
            )
        with repository.transaction():
            result = repository.purge_all()
        assert result.continuations == 1
        assert repository.continuations_for_project("project-a") == ()
        assert repository.sessions_for_project("project-a") == ()
    finally:
        connection.close()
