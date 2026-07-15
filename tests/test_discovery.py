from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import (
    BatchStatus,
    CodexAdapter,
    SessionHealth,
    SessionIdentity,
    TurnBatch,
    TurnRole,
    VisibleTurn,
)
from tang.capsule import DiscoveryCapsuleBuilder
from tang.cli import main
from tang.discovery import DiscoveryFilter, DiscoveryService
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


def seed_discovery(database: Path, current: Path, foreign: Path, fixture_home: Path) -> None:
    adapter = CodexAdapter(fixture_home, source_namespace="discovery")
    template = adapter.scan(None).records[0]
    connection = open_database(database)
    repository = TangRepository(connection)
    builder = DiscoveryCapsuleBuilder()
    project = resolve_project(current)
    foreign_project = resolve_project(foreign)
    records = (
        ("alpha", "codex", SessionHealth.COMPLETE, "Alpha plan", "forge exact phrase", 3, project.key),
        ("beta", "grok", SessionHealth.UNKNOWN, "Beta work", "forge nearby phrase", 2, project.key),
        ("foreign", "codex", SessionHealth.COMPLETE, "Foreign", "forge exact phrase", 4, foreign_project.key),
    )
    try:
        with repository.transaction():
            for native_id, harness, health, title, text, hour, project_key in records:
                identity = SessionIdentity(harness, "discovery", native_id)
                updated = datetime(2026, 7, 14, hour, tzinfo=timezone.utc)
                source = replace(
                    template,
                    identity=identity,
                    title=title,
                    health=health,
                    started_at=updated,
                    updated_at=updated,
                )
                read = TurnBatch(
                    identity=identity,
                    status=BatchStatus.COMPLETE,
                    turns=(
                        VisibleTurn(
                            ordinal=0,
                            role=TurnRole.USER,
                            text=text,
                            citation_locator="jsonl:1",
                            timestamp=updated,
                        ),
                    ),
                )
                repository.upsert_session(source, project_key, updated)
                repository.put_capsule(builder.build(source, read, project_key))
    finally:
        connection.close()


def test_browse_and_search_are_project_scoped_filtered_and_deterministic(
    codex_fixture_home: Path, tmp_path: Path
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    database = tmp_path / "tang.db"
    seed_discovery(database, current, foreign, codex_fixture_home)
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        service = DiscoveryService(repository)
        project_key = resolve_project(current).key

        browsed = service.browse(project_key)
        phrase = service.search(project_key, '"forge exact"')
        filtered = service.browse(
            project_key,
            DiscoveryFilter(
                harness="grok",
                health=SessionHealth.UNKNOWN,
                since=datetime(2026, 7, 14, 1, tzinfo=timezone.utc),
                until=datetime(2026, 7, 14, 2, tzinfo=timezone.utc),
            ),
        )

        assert [item.source_id for item in browsed] == [
            "codex:discovery:alpha",
            "grok:discovery:beta",
        ]
        assert [item.source_id for item in phrase] == ["codex:discovery:alpha"]
        assert "[forge exact] phrase" in phrase[0].snippet
        assert [item.source_id for item in filtered] == ["grok:discovery:beta"]
        assert service.search(project_key, "absenttoken") == ()

        with repository.transaction():
            connection.execute(
                "UPDATE capsules_fts SET search_text = ? WHERE source_id = ?",
                (
                    'needle PASSWORD="correct horse battery staple"',
                    "codex:discovery:alpha",
                ),
            )
        displayed = service.search(project_key, "needle")
        assert "correct horse" not in displayed[0].snippet
        assert "[REDACTED:credential]" in displayed[0].snippet
    finally:
        connection.close()


def test_cli_json_lines_and_malformed_query_keep_diagnostics_on_stderr(
    codex_fixture_home: Path, tmp_path: Path, capsys
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    database = tmp_path / "tang.db"
    seed_discovery(database, current, foreign, codex_fixture_home)
    common = ["--database", str(database), "--cwd", str(current)]

    assert main(["browse", *common, "--json"]) == 0
    json_result = capsys.readouterr()
    document = json.loads(json_result.out)
    assert document["schema_version"] == 1
    assert [result["source_id"] for result in document["results"]] == [
        "codex:discovery:alpha",
        "grok:discovery:beta",
    ]
    assert all(result["updated_at"].endswith("Z") for result in document["results"])
    assert json_result.err == ""

    assert main(["search", "forge", *common, "--harness", "grok"]) == 0
    line_result = capsys.readouterr()
    assert line_result.out.count("\n") == 1
    assert "grok:discovery:beta" in line_result.out
    assert "codex:discovery:alpha" not in line_result.out
    assert line_result.err == ""

    assert main(["search", '"unterminated', *common]) == 2
    malformed = capsys.readouterr()
    assert malformed.out == ""
    assert malformed.err == "error: malformed FTS query\n"
