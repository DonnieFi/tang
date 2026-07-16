from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from tang.adapters import (
    AdapterCheckpoint,
    AdapterWarning,
    BatchStatus,
    CodexAdapter,
    GrokAdapter,
    OpaqueSourceLocator,
    ScanBatch,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
    TurnBatch,
    TurnSelection,
)
from tang.cli import main
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


NOW = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
GROK_SESSION_ID = "019f6000-1234-7000-8000-000000000099"


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


def write_grok_session(
    home: Path, project: Path, *, malformed_summary: bool = False
) -> Path:
    group = home / "sessions" / quote(str(project), safe="")
    session = group / GROK_SESSION_ID
    session.mkdir(parents=True)
    (group / ".cwd").write_text(str(project), encoding="utf-8")
    summary = session / "summary.json"
    if malformed_summary:
        summary.write_text("{broken", encoding="utf-8")
    else:
        summary.write_text(
            json.dumps(
                {
                    "created_at": "2026-07-15T00:00:00Z",
                    "updated_at": "2026-07-15T00:01:00Z",
                    "git_root_dir": str(project),
                    "generated_title": "Scoped diagnostic fixture",
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
    (session / "updates.jsonl").write_text(
        json.dumps(
            {
                "method": "session/update",
                "params": {
                    "sessionId": GROK_SESSION_ID,
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": "Scoped warning fixture."},
                    },
                },
                "timestamp": 1784059200,
            },
            separators=(",", ":"),
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def point_codex_at_project(home: Path, project: Path) -> None:
    log = next((home / "sessions").rglob("*.jsonl"))
    rows = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    rows[0]["payload"]["cwd"] = str(project)
    log.write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
    )


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

    assert main([*arguments, "--json"]) == 1
    first = capsys.readouterr()
    document = json.loads(first.out)
    assert document == {
        "deleted": 0,
        "diagnostic_count": 0,
        "diagnostics": [],
        "excluded": 1,
        "indexed": 4,
        "schema_version": 1,
        "status": "partial",
        "unchanged": 0,
        "warning_count": document["warning_count"],
        "warnings": document["warnings"],
    }
    assert document["warning_count"] > 0
    assert {warning["scope"] for warning in document["warnings"]} == {"project"}
    assert "warning:" in first.err
    assert str(tmp_path) not in first.out + first.err

    assert main(arguments) == 1
    second = capsys.readouterr()
    assert second.out == (
        "Indexed 0; deleted 0; unchanged 0; excluded 0; diagnostics 0; "
        "status partial.\n"
    )
    assert "warning:" in second.err
    assert str(tmp_path) not in second.out + second.err


def test_index_advances_past_unreadable_eligible_session_and_retries_on_change(
    copied_codex_home: Path, tmp_path: Path
) -> None:
    current = tmp_path / "current"
    current.mkdir()
    good_log = next((copied_codex_home / "sessions").rglob("*.jsonl"))
    good_rows = [json.loads(line) for line in good_log.read_text().splitlines()]
    good_rows[0]["payload"]["cwd"] = str(current)
    good_log.write_text("\n".join(json.dumps(row) for row in good_rows) + "\n")

    poison_id = "019f6000-5678-7000-8000-000000000099"
    poison_log = good_log.with_name(
        f"rollout-2026-07-14T21-00-00-{poison_id}.jsonl"
    )
    metadata = good_rows[0]
    metadata["timestamp"] = "2026-07-14T21:00:00Z"
    metadata["payload"]["id"] = poison_id
    metadata["payload"]["session_id"] = poison_id
    metadata["payload"]["timestamp"] = "2026-07-14T21:00:00Z"
    poison_log.write_text(json.dumps(metadata) + "\n")

    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    adapter = CodexAdapter(copied_codex_home, source_namespace="poison")
    project = resolve_project(current)
    indexer = ProjectIndexer(repository)
    try:
        first = indexer.index((adapter,), project, now=NOW)
        checkpoint = repository.get_checkpoint("codex", "poison", project.key)
        second = indexer.index((adapter,), project, now=NOW)

        assert first.indexed == 1
        assert first.status == "partial"
        assert checkpoint is not None
        assert second.indexed == 0
        assert second.status == "complete"
        assert repository.get_checkpoint("codex", "poison", project.key) == checkpoint

        with poison_log.open("a", encoding="utf-8") as destination:
            destination.write(
                json.dumps(
                    {
                        "timestamp": "2026-07-14T21:00:01Z",
                        "type": "response_item",
                        "payload": {
                            "type": "message",
                            "role": "user",
                            "content": [
                                {"type": "input_text", "text": "Recovered after change."}
                            ],
                        },
                    }
                )
                + "\n"
            )
        recovered = indexer.index((adapter,), project, now=NOW)

        assert recovered.indexed == 1
        assert len(repository.sessions_for_project(project.key)) == 2
    finally:
        connection.close()


def test_foreign_adapter_damage_is_a_complete_index_with_qualified_diagnostics(
    copied_codex_home: Path, tmp_path: Path, capsys
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    point_codex_at_project(copied_codex_home, current)
    grok_home = tmp_path / "grok-home"
    write_grok_session(grok_home, foreign, malformed_summary=True)
    database = tmp_path / "tang.db"
    arguments = [
        "index",
        "--database",
        str(database),
        "--cwd",
        str(current),
        "--codex-home",
        str(copied_codex_home),
        "--grok-home",
        str(grok_home),
    ]

    assert main([*arguments, "--json"]) == 0
    captured = capsys.readouterr()
    document = json.loads(captured.out)

    assert document["status"] == "complete"
    assert document["indexed"] == 1
    assert document["excluded"] == 1
    assert document["warning_count"] == 0
    assert document["warnings"] == []
    assert document["diagnostic_count"] == 3
    assert [item["code"] for item in document["diagnostics"]] == [
        "created-at-drift",
        "malformed-summary",
        "updated-at-drift",
    ]
    assert {item["scope"] for item in document["diagnostics"]} == {"foreign"}
    assert "diagnostic[foreign]" in captured.err
    assert "warning:" not in captured.err
    assert str(foreign) not in captured.out + captured.err

    assert main(arguments) == 0
    repeated = capsys.readouterr()
    assert repeated.out == (
        "Indexed 0; deleted 0; unchanged 0; excluded 0; diagnostics 4; "
        "status complete.\n"
    )
    assert repeated.err.count("diagnostic[foreign]") == 4


def test_foreign_codex_damage_is_a_qualified_complete_index(
    copied_codex_home: Path, tmp_path: Path
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    point_codex_at_project(copied_codex_home, foreign)
    with next((copied_codex_home / "sessions").rglob("*.jsonl")).open(
        "a", encoding="utf-8"
    ) as log:
        log.write("{malformed\n")
    grok_home = tmp_path / "grok-home"
    write_grok_session(grok_home, current)
    connection = open_database(tmp_path / "tang.db")
    try:
        result = ProjectIndexer(TangRepository(connection)).index(
            (CodexAdapter(copied_codex_home), GrokAdapter(grok_home)),
            resolve_project(current),
            now=NOW,
        )

        assert result.status == "complete"
        assert result.indexed == 1
        assert result.excluded == 1
        assert result.warnings == ()
        assert [diagnostic.code for diagnostic in result.diagnostics] == [
            "malformed-jsonl"
        ]
        assert {diagnostic.scope for diagnostic in result.diagnostics} == {"foreign"}
    finally:
        connection.close()


def test_current_or_unresolved_adapter_damage_remains_partial_and_retryable(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    missing = tmp_path / "missing"
    current.mkdir()
    grok_home = tmp_path / "grok-home"
    summary = write_grok_session(grok_home, current, malformed_summary=True)
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    project = resolve_project(current)
    indexer = ProjectIndexer(repository)
    adapter = GrokAdapter(grok_home, source_namespace="scoped-warning")
    try:
        first = indexer.index((adapter,), project, now=NOW)

        assert first.status == "partial"
        assert first.diagnostics == ()
        assert "malformed-summary" in {warning.code for warning in first.warnings}
        assert first.indexed == 1

        summary.write_text(
            json.dumps(
                {
                    "created_at": "2026-07-15T00:00:00Z",
                    "updated_at": "2026-07-15T00:01:00Z",
                    "git_root_dir": str(current),
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        recovered = indexer.index((adapter,), project, now=NOW)

        assert recovered.status == "complete"
        assert recovered.indexed == 1

        summary.write_text(
            json.dumps(
                {
                    "created_at": "2026-07-15T00:00:00Z",
                    "updated_at": "2026-07-15T00:01:00Z",
                    "git_root_dir": str(missing),
                },
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        unresolved = indexer.index((adapter,), project, now=NOW)

        assert unresolved.status == "partial"
        assert unresolved.diagnostics == ()
        assert {warning.code for warning in unresolved.warnings} == {
            "project-hint-unavailable"
        }
    finally:
        connection.close()


def test_ambiguous_duplicate_warning_is_never_downgraded_by_a_foreign_record(
    tmp_path: Path,
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    identity = SessionIdentity("codex", "duplicate-scope", "foreign")
    source = SourceRecord(
        identity,
        OpaqueSourceLocator("fixture:foreign"),
        SourceFingerprint("sha256", "foreign"),
        str(foreign),
        NOW,
        NOW,
        health=SessionHealth.COMPLETE,
    )

    class DuplicateAdapter:
        adapter_key = "codex"
        source_namespace = "duplicate-scope"

        def scan(self, checkpoint: AdapterCheckpoint | None) -> ScanBatch:
            return ScanBatch(
                BatchStatus.PARTIAL,
                records=(source,),
                warnings=(
                    AdapterWarning(
                        "duplicate-session-id",
                        "A duplicate identity might represent another project.",
                        identity,
                        str(foreign),
                    ),
                ),
            )

        def read(self, session_ref: SourceRecord, selection: TurnSelection) -> TurnBatch:
            raise AssertionError("a foreign record must not be read")

    connection = open_database(tmp_path / "tang.db")
    try:
        result = ProjectIndexer(TangRepository(connection)).index(
            (DuplicateAdapter(),), resolve_project(current), now=NOW
        )

        assert result.status == "partial"
        assert result.excluded == 1
        assert result.diagnostics == ()
        assert [warning.code for warning in result.warnings] == [
            "duplicate-session-id"
        ]
    finally:
        connection.close()


def test_index_cli_returns_zero_for_complete_scan(
    copied_codex_home: Path, tmp_path: Path, capsys
) -> None:
    current = tmp_path / "current"
    current.mkdir()
    log = next((copied_codex_home / "sessions").rglob("*.jsonl"))
    rows = [json.loads(line) for line in log.read_text().splitlines()]
    rows[0]["payload"]["cwd"] = str(current)
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
    grok_home = tmp_path / "grok"
    (grok_home / "sessions").mkdir(parents=True)

    result = main(
        [
            "index",
            "--database",
            str(tmp_path / "tang.db"),
            "--cwd",
            str(current),
            "--codex-home",
            str(copied_codex_home),
            "--grok-home",
            str(grok_home),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert "status complete" in captured.out
    assert captured.err == ""


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
