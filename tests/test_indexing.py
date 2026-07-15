from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter
from tang.cli import main
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)


def point_corpus_at_projects(discovery_corpus, current: Path, foreign: Path) -> None:
    for path in (discovery_corpus.codex_home / "sessions").rglob("*.jsonl"):
        lines = path.read_text().splitlines()
        first = json.loads(lines[0])
        cwd = first["payload"]["cwd"]
        first["payload"]["cwd"] = str(
            foreign if cwd == "/work/foreign-vault" else current
        )
        lines[0] = json.dumps(first, separators=(",", ":"))
        path.write_text("\n".join(lines) + ("\n" if path.read_text().endswith("\n") else ""))
    summary = next((discovery_corpus.grok_home / "sessions").rglob("summary.json"))
    payload = json.loads(summary.read_text())
    payload["git_root_dir"] = str(current)
    summary.write_text(json.dumps(payload, separators=(",", ":")))


def test_index_is_current_project_scoped_incremental_and_restart_safe(
    discovery_corpus, tmp_path: Path
) -> None:
    current = tmp_path / "current-project"
    foreign = tmp_path / "foreign-project"
    current.mkdir()
    foreign.mkdir()
    point_corpus_at_projects(discovery_corpus, current, foreign)
    path = tmp_path / "data" / "tang.db"
    connection = open_database(path)
    repository = TangRepository(connection)
    indexer = ProjectIndexer(repository)
    adapters = (
        CodexAdapter(discovery_corpus.codex_home, source_namespace="index-codex"),
        GrokAdapter(discovery_corpus.grok_home, source_namespace="index-grok"),
    )
    project = resolve_project(current)
    try:
        first = indexer.index(adapters, project, now=NOW)
        first_changes = connection.total_changes

        assert first.indexed == 4
        assert first.excluded == 1
        assert first.status == "partial"
        assert len(repository.sessions_for_project(project.key)) == 4
        assert all(
            stored.source.project_hint == str(current)
            for stored in repository.sessions_for_project(project.key)
        )
        assert (
            repository.get_checkpoint("codex", "index-codex", project.key)
            is not None
        )
        assert (
            repository.get_checkpoint("grok", "index-grok", project.key)
            is not None
        )

        second = indexer.index(adapters, project, now=NOW)

        assert second.indexed == 0
        assert connection.total_changes == first_changes
    finally:
        connection.close()

    reopened = open_database(path)
    try:
        repository = TangRepository(reopened)
        assert len(repository.sessions_for_project(project.key)) == 4
        assert (
            repository.get_checkpoint("codex", "index-codex", project.key)
            is not None
        )
    finally:
        reopened.close()


def test_adapter_checkpoints_are_scoped_per_project(
    discovery_corpus, tmp_path: Path
) -> None:
    current = tmp_path / "current-project"
    foreign = tmp_path / "foreign-project"
    current.mkdir()
    foreign.mkdir()
    point_corpus_at_projects(discovery_corpus, current, foreign)
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    adapter = CodexAdapter(
        discovery_corpus.codex_home, source_namespace="multi-project"
    )
    current_project = resolve_project(current)
    foreign_project = resolve_project(foreign)
    try:
        first = ProjectIndexer(repository).index((adapter,), current_project, now=NOW)
        second = ProjectIndexer(repository).index((adapter,), foreign_project, now=NOW)

        assert first.indexed >= 1
        assert second.indexed == 1
        assert len(repository.sessions_for_project(foreign_project.key)) == 1
        assert repository.get_checkpoint(
            "codex", "multi-project", current_project.key
        ) is not None
        assert repository.get_checkpoint(
            "codex", "multi-project", foreign_project.key
        ) is not None
    finally:
        connection.close()


def test_index_json_and_human_output_are_deterministic(
    discovery_corpus, tmp_path: Path, capsys
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    point_corpus_at_projects(discovery_corpus, current, foreign)
    database = tmp_path / "cli" / "tang.db"
    arguments = [
        "index",
        "--database",
        str(database),
        "--cwd",
        str(current),
        "--codex-home",
        str(discovery_corpus.codex_home),
        "--grok-home",
        str(discovery_corpus.grok_home),
    ]

    assert main([*arguments, "--json"]) == 0
    first = capsys.readouterr()
    document = json.loads(first.out)
    assert document == {
        "deleted": 0,
        "excluded": 1,
        "indexed": 4,
        "schema_version": 1,
        "status": "partial",
        "unchanged": 0,
        "warning_count": document["warning_count"],
    }
    assert document["warning_count"] > 0
    assert "warning:" in first.err
    assert str(tmp_path) not in first.out + first.err

    assert main(arguments) == 0
    second = capsys.readouterr()
    assert second.out == (
        "Indexed 0; deleted 0; unchanged 0; excluded 0; status partial.\n"
    )
    assert "warning:" in second.err
    assert str(tmp_path) not in second.out + second.err


def test_index_refreshes_capsule_fts_and_removes_deleted_native_session(
    copied_codex_home: Path, tmp_path: Path
) -> None:
    current = tmp_path / "current"
    current.mkdir()
    log = next((copied_codex_home / "sessions").rglob("*.jsonl"))
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[0]["payload"]["cwd"] = str(current)
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    adapter = CodexAdapter(copied_codex_home, source_namespace="updates")
    project = resolve_project(current)
    indexer = ProjectIndexer(repository)
    try:
        first = indexer.index((adapter,), project, now=NOW)
        source_id = (
            repository.sessions_for_project(project.key)[0].source.identity.canonical
        )
        first_checkpoint = repository.get_checkpoint(
            "codex", "updates", project.key
        )
        assert first.indexed == 1

        with log.open("a", encoding="utf-8") as destination:
            destination.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-14T20:03:00Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "assistant",
                            "content": [
                                {"type": "output_text", "text": "Quasarrefresh token."}
                            ],
                        },
                    }
                )
                + "\n"
            )

        refreshed = indexer.index((adapter,), project, now=NOW)
        second_checkpoint = repository.get_checkpoint(
            "codex", "updates", project.key
        )
        assert refreshed.indexed == 1
        assert second_checkpoint != first_checkpoint
        assert repository.search_capsule_ids(project.key, "Quasarrefresh") == (
            source_id,
        )

        log.unlink()
        removed = indexer.index((adapter,), project, now=NOW)

        assert removed.deleted == 1
        assert repository.get_session(source_id) is None
        assert repository.get_capsule(source_id) is None
        assert repository.search_capsule_ids(project.key, "Quasarrefresh") == ()
        assert (
            repository.get_checkpoint("codex", "updates", project.key)
            != second_checkpoint
        )
    finally:
        connection.close()
