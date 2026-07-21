#!/usr/bin/env python3
"""Measure Tang's isolated project refresh, query, and graph hot paths.

The benchmark synthesizes a contained Codex store under a temporary project.
It never reads a user's native stores or writes outside an explicit work directory.
"""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tang.adapters import CodexAdapter  # noqa: E402
from tang.graph import GraphService  # noqa: E402
from tang.indexing import ProjectIndexer  # noqa: E402
from tang.project import resolve_project  # noqa: E402
from tang.repository import StoredContinuation, TangRepository  # noqa: E402
from tang.continuation_persistence import insert_continuation
from tang.storage import open_database, project_data_path  # noqa: E402


SCHEMA_VERSION = 1
DEFAULT_SESSIONS = 128
DEFAULT_PAYLOAD_BYTES = 32 * 1024
START = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _rfc3339(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _session_id(index: int) -> str:
    # Stable UUIDs preserve the native Codex filename identity contract.
    return str(UUID(int=0x019F_6000_0000_7000_8000_0000_0000_0000 + index))


def _visible_payload(index: int, size: int) -> str:
    seed = (
        f"Session {index} studies LEGO productivity and fidget design; "
        "the tang benchmark checkpoint remains searchable. "
    )
    return (seed * ((size // len(seed)) + 1))[:size]


def _write_session(path: Path, project: Path, index: int, payload_bytes: int) -> None:
    session_id = _session_id(index)
    timestamp = START + timedelta(seconds=index)
    rows = (
        {
            "timestamp": _rfc3339(timestamp),
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "session_id": session_id,
                "timestamp": _rfc3339(timestamp),
                "cwd": str(project),
            },
        },
        {
            "timestamp": _rfc3339(timestamp + timedelta(seconds=1)),
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": _visible_payload(index, payload_bytes)}
                ],
            },
        },
        {
            "timestamp": _rfc3339(timestamp + timedelta(seconds=2)),
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": f"Completed benchmark checkpoint for session {index}.",
                    }
                ],
            },
        },
        {
            "timestamp": _rfc3339(timestamp + timedelta(seconds=3)),
            "type": "event_msg",
            "payload": {"type": "task_complete"},
        },
    )
    path.write_text(
        "\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n",
        encoding="utf-8",
    )


def _append_update(path: Path) -> None:
    update = {
        "timestamp": _rfc3339(START + timedelta(days=1)),
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": "Incremental benchmark refresh marker."}
            ],
        },
    }
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(update, separators=(",", ":")) + "\n")


def _seconds(action) -> tuple[float, object]:  # type: ignore[no-untyped-def]
    started = time.perf_counter()
    result = action()
    return round(time.perf_counter() - started, 6), result


def _database_sizes(database: Path) -> dict[str, int]:
    return {
        suffix or ".db": path.stat().st_size
        for suffix, path in (
            ("", database),
            ("-wal", database.with_name(database.name + "-wal")),
            ("-shm", database.with_name(database.name + "-shm")),
        )
        if path.exists()
    }


def _query_plans(connection: sqlite3.Connection, project_key: str) -> dict[str, list[str]]:
    queries = {
        "browse": (
            """
            EXPLAIN QUERY PLAN
            SELECT s.source_id, s.adapter, s.updated_at, s.health, c.content_json
            FROM sessions AS s JOIN capsules AS c USING(source_id)
            WHERE s.project_key = ?
            ORDER BY s.updated_at DESC, s.source_id
            """,
            (project_key,),
        ),
        "search": (
            """
            EXPLAIN QUERY PLAN
            SELECT s.source_id, s.adapter, s.updated_at, s.health, c.content_json
            FROM capsules_fts
            JOIN sessions AS s USING(source_id)
            JOIN capsules AS c USING(source_id)
            WHERE capsules_fts MATCH ? AND s.project_key = ?
            ORDER BY rank, s.updated_at DESC, s.source_id
            LIMIT ?
            """,
            ("LEGO", project_key, 20),
        ),
    }
    return {
        label: [str(row[3]) for row in connection.execute(statement, parameters)]
        for label, (statement, parameters) in queries.items()
    }


def _concurrent_read(database: Path) -> bool:
    reader = open_database(database)
    writer = open_database(database)
    try:
        writer.execute("BEGIN IMMEDIATE")
        reader.execute("SELECT count(*) FROM sessions").fetchone()
        writer.execute("ROLLBACK")
        return True
    finally:
        reader.close()
        writer.close()


def run_benchmark(work: Path, *, sessions: int, payload_bytes: int) -> dict[str, object]:
    if sessions < 2:
        raise ValueError("--sessions must be at least 2")
    if payload_bytes < 64:
        raise ValueError("--payload-bytes must be at least 64")

    project = work / "project"
    logs = work / "codex-home" / "sessions" / "2026" / "07" / "16"
    project.mkdir(parents=True)
    logs.mkdir(parents=True)
    session_paths: list[Path] = []
    for index in range(sessions):
        path = logs / f"rollout-2026-07-16T12-00-00-{_session_id(index)}.jsonl"
        _write_session(path, project, index, payload_bytes)
        session_paths.append(path)

    identity = resolve_project(project)
    database = project_data_path(identity)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        indexer = ProjectIndexer(repository)
        adapter = CodexAdapter(work / "codex-home", source_namespace="benchmark")

        cold_seconds, cold = _seconds(lambda: indexer.index((adapter,), identity))
        unchanged_seconds, unchanged = _seconds(
            lambda: indexer.index((adapter,), identity)
        )
        _append_update(session_paths[-1])
        incremental_seconds, incremental = _seconds(
            lambda: indexer.index((adapter,), identity)
        )

        source_ids = tuple(
            item.source.identity.canonical
            for item in repository.sessions_for_project(identity.key)
        )
        with repository.transaction():
            for position, (source_id, target_id) in enumerate(
                zip(source_ids, source_ids[1:], strict=False)
            ):
                insert_continuation(repository, 
                    StoredContinuation(
                        source_id=source_id,
                        target_id=target_id,
                        project_key=identity.key,
                        confirmation_mode="explicit",
                        confirmed_at=START + timedelta(seconds=position),
                    )
                )

        browse_seconds, browsed = _seconds(
            lambda: repository.browse_discovery(identity.key)
        )
        search_seconds, searched = _seconds(
            lambda: repository.search_discovery(identity.key, "LEGO")
        )
        graph_seconds, graph = _seconds(
            lambda: GraphService(repository).component(source_ids[0])
        )
        journal_mode = str(connection.execute("PRAGMA journal_mode").fetchone()[0])
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])

        return {
            "schema_version": SCHEMA_VERSION,
            "environment": {
                "platform": platform.platform(),
                "python": sys.version.split()[0],
                "sqlite": sqlite3.sqlite_version,
            },
            "corpus": {
                "sessions": sessions,
                "payload_bytes_per_session": payload_bytes,
                "native_bytes": sum(path.stat().st_size for path in session_paths),
            },
            "measurements_seconds": {
                "cold_index": cold_seconds,
                "unchanged_index": unchanged_seconds,
                "incremental_index": incremental_seconds,
                "browse": browse_seconds,
                "search": search_seconds,
                "graph": graph_seconds,
            },
            "results": {
                "cold_indexed": cold.indexed,
                "unchanged_indexed": unchanged.indexed,
                "incremental_indexed": incremental.indexed,
                "browse_results": len(browsed),
                "search_results": len(searched),
                "graph_nodes": len(graph.nodes),
                "graph_edges": len(graph.edges),
            },
            "database": {
                "path": str(database.relative_to(project)),
                "sizes_bytes": _database_sizes(database),
                "journal_mode": journal_mode,
                "integrity_check": integrity,
                "concurrent_read_during_immediate_write": _concurrent_read(database),
            },
            "query_plans": _query_plans(connection, identity.key),
        }
    finally:
        connection.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=DEFAULT_SESSIONS)
    parser.add_argument("--payload-bytes", type=int, default=DEFAULT_PAYLOAD_BYTES)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if args.sessions < 2:
        parser.error("--sessions must be at least 2")
    if args.payload_bytes < 64:
        parser.error("--payload-bytes must be at least 64")

    if args.work_dir is None:
        with tempfile.TemporaryDirectory(prefix="tang-refresh-benchmark-") as temporary:
            document = run_benchmark(
                Path(temporary), sessions=args.sessions, payload_bytes=args.payload_bytes
            )
    else:
        if args.work_dir.exists():
            if not args.work_dir.is_dir():
                parser.error("--work-dir must identify a directory")
            if any(args.work_dir.iterdir()):
                parser.error(
                    "--work-dir must be absent or empty to avoid stale benchmark state"
                )
        args.work_dir.mkdir(parents=True, exist_ok=True)
        document = run_benchmark(
            args.work_dir, sessions=args.sessions, payload_bytes=args.payload_bytes
        )
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
