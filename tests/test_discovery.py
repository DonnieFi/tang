from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

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
from tang.cli import _truncate_discovery_text, main
from tang.discovery import DiscoveryFilter, DiscoveryService, discovery_page
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


def seed_discovery(
    database: Path,
    current: Path,
    foreign: Path,
    fixture_home: Path,
    *,
    extra_count: int = 0,
) -> None:
    adapter = CodexAdapter(fixture_home, source_namespace="discovery")
    template = adapter.scan(None).records[0]
    connection = open_database(database)
    repository = TangRepository(connection)
    builder = DiscoveryCapsuleBuilder()
    project = resolve_project(current)
    foreign_project = resolve_project(foreign)
    records = [
        ("alpha", "codex", SessionHealth.COMPLETE, "Alpha plan", "forge exact phrase", 3, project.key),
        ("beta", "grok", SessionHealth.UNKNOWN, "Beta work", "forge nearby phrase", 2, project.key),
        ("foreign", "codex", SessionHealth.COMPLETE, "Foreign", "forge exact phrase", 4, foreign_project.key),
    ]
    records.extend(
        (
            f"extra-{number}",
            "codex",
            SessionHealth.COMPLETE,
            f"Extra recovery {number}",
            f"extra fixture {number}",
            5 + number,
            project.key,
        )
        for number in range(extra_count)
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
        assert repository.discovery_source_ids(
            project_key, adapter="codex", native_id="alpha"
        ) == ("codex:discovery:alpha",)
        assert repository.discovery_source_ids(
            project_key, adapter="codex", native_id="missing"
        ) == ()

        browsed = service.browse(project_key)
        phrase = service.search(project_key, '"forge exact"')
        excluded_browse = service.browse(
            project_key,
            exclude_source_ids=("codex:discovery:alpha", "codex:discovery:alpha"),
        )
        excluded_phrase = service.search(
            project_key,
            '"forge exact"',
            exclude_source_ids=("codex:discovery:alpha",),
        )
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
        assert [item.display_name for item in browsed] == ["Alpha plan", "Beta work"]
        assert [item.snippet for item in browsed] == [
            "forge exact phrase",
            "forge nearby phrase",
        ]
        assert [item.source_id for item in phrase] == ["codex:discovery:alpha"]
        assert "[forge exact] phrase" in phrase[0].snippet
        assert [item.source_id for item in excluded_browse] == [
            "grok:discovery:beta"
        ]
        assert excluded_phrase == ()
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

        capsule_row = connection.execute(
            "SELECT content_json FROM capsules WHERE source_id = ?",
            ("codex:discovery:alpha",),
        ).fetchone()
        assert capsule_row is not None
        content = json.loads(capsule_row["content_json"])
        content["display_name"] = (
            'Resume codex:discovery:alpha 019f6000-5678-7000-8000-000000000002 '
            'with PASSWORD="display-name-secret"'
        )
        with repository.transaction():
            connection.execute(
                "UPDATE capsules SET content_json = ? WHERE source_id = ?",
                (
                    json.dumps(content, sort_keys=True, separators=(",", ":")),
                    "codex:discovery:alpha",
                ),
            )
        display_item = next(
            item
            for item in service.browse(project_key)
            if item.source_id == "codex:discovery:alpha"
        )
        assert "display-name-secret" not in display_item.display_name
        assert "codex:discovery:alpha" not in display_item.display_name
        assert "019f6000-5678-7000-8000-000000000002" not in display_item.display_name
        assert "[REDACTED:credential]" in display_item.display_name
        assert display_item.display_name.count("[session]") == 2
    finally:
        connection.close()


def test_search_limit_is_explicit_and_bounded(
    codex_fixture_home: Path, tmp_path: Path
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    database = tmp_path / "tang.db"
    seed_discovery(database, current, foreign, codex_fixture_home, extra_count=5)

    connection = open_database(database)
    try:
        service = DiscoveryService(TangRepository(connection))
        results = service.search(resolve_project(current).key, "extra", limit=2)
        assert [item.display_name for item in results] == [
            "Extra recovery 4",
            "Extra recovery 3",
        ]
    finally:
        connection.close()


def test_discovery_previews_keep_a_bounded_redacted_snippet_and_ascii_safe_ellipsis() -> None:
    assert _truncate_discovery_text("x" * 10, 10, ascii_only=False) == "x" * 10
    assert _truncate_discovery_text("x" * 10, 6, ascii_only=False) == "xxxxx…"
    assert _truncate_discovery_text("x" * 10, 6, ascii_only=True) == "xxx..."


def test_cli_json_lines_and_malformed_query_keep_diagnostics_on_stderr(
    codex_fixture_home: Path, tmp_path: Path, monkeypatch, capsys
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
    assert [result["session_handle"] for result in document["results"]] == [
        "C1",
        "G1",
    ]
    assert all(result["updated_at"].endswith("Z") for result in document["results"])
    assert json_result.err == ""

    def unexpected_native_scan(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("current exclusion must use the indexed project database")

    monkeypatch.setattr(
        "tang.adapters.codex.CodexAdapter.scan", unexpected_native_scan
    )
    assert (
        main(
            [
                "search",
                "forge",
                *common,
                "--exclude-current",
                "--current-native-id",
                "alpha",
                "--json",
            ]
        )
        == 0
    )
    excluded = json.loads(capsys.readouterr().out)
    assert [item["source_id"] for item in excluded["results"]] == [
        "grok:discovery:beta"
    ]

    assert main(["browse", *common, "--current-native-id", "alpha"]) == 2
    invalid_exclusion = capsys.readouterr()
    assert invalid_exclusion.out == ""
    assert (
        invalid_exclusion.err
        == "error: --current-native-id requires --exclude-current\n"
    )

    assert main(["search", "forge", *common, "--harness", "grok"]) == 0
    line_result = capsys.readouterr()
    assert all(
        value in line_result.out
        for value in (
            "SELECT",
            "ID",
            "SESSION",
            "[1]",
            "G1",
            "Beta work",
            "grok",
            "2026-07-14T02:00:00Z",
            "unverified",
        )
    )
    assert "\x1b[" not in line_result.out
    assert "Page 1 of 1 (1 results)." in line_result.out
    assert "grok:discovery:beta" not in line_result.out
    assert "codex:discovery:alpha" not in line_result.out
    assert line_result.err == ""

    assert main(["search", '"unterminated', *common]) == 2
    malformed = capsys.readouterr()
    assert malformed.out == ""
    assert malformed.err == "error: malformed FTS query\n"


def test_human_discovery_is_numbered_paged_and_maps_only_current_choices(
    codex_fixture_home: Path, tmp_path: Path, monkeypatch, capsys
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    database = tmp_path / "tang.db"
    seed_discovery(
        database, current, foreign, codex_fixture_home, extra_count=5
    )
    common = ["--database", str(database), "--cwd", str(current)]
    monkeypatch.setattr(
        "tang.cli.shutil.get_terminal_size",
        lambda _fallback=None: os.terminal_size((100, 24)),
    )

    assert main(["browse", *common]) == 0
    first = capsys.readouterr()

    assert all(f"[{number}]" in first.out for number in range(1, 6))
    assert "SELECT" in first.out and "SESSION" in first.out
    assert "Page 1 of 2 (7 results)." in first.out
    assert "Use --page 2 for the next page." in first.out
    assert "Extra recovery" in first.out
    assert "extra fixture" in first.out
    assert "codex:discovery:" not in first.out
    assert "grok:discovery:" not in first.out

    monkeypatch.setattr(
        "tang.cli.shutil.get_terminal_size",
        lambda _fallback=None: os.terminal_size((60, 24)),
    )
    assert main(["browse", *common, "--page", "2"]) == 0
    second = capsys.readouterr()

    assert all(
        value in second.out
        for value in ("[6]", "C1", "Alpha plan", "[7]", "G1", "Beta work")
    )
    assert "HARNESS" not in second.out
    assert "codex" in second.out and "grok" in second.out
    assert "Page 2 of 2 (7 results)." in second.out
    assert "Use --page 1 for the previous page." in second.out

    assert main(["browse", *common, "--page", "3"]) == 2
    out_of_range = capsys.readouterr()
    assert out_of_range.out == ""
    assert out_of_range.err == "error: page 3 is out of range; 2 page(s) available\n"

    assert main(["browse", *common, "--page", "2", "--json"]) == 0
    paged_document = json.loads(capsys.readouterr().out)
    assert paged_document["page"] == 2
    assert paged_document["page_count"] == 2
    assert paged_document["result_count"] == 7
    assert [item["choice_number"] for item in paged_document["results"]] == [6, 7]
    assert [item["source_id"] for item in paged_document["results"]] == [
        "codex:discovery:alpha",
        "grok:discovery:beta",
    ]

    assert main(["browse", *common, "--json"]) == 0
    unpaged_document = json.loads(capsys.readouterr().out)
    assert len(unpaged_document["results"]) == 7
    assert "page" not in unpaged_document
    assert all("choice_number" not in item for item in unpaged_document["results"])

    connection = open_database(database)
    try:
        items = DiscoveryService(TangRepository(connection)).browse(
            resolve_project(current).key
        )
        first_page = discovery_page(items, 1)
        selected = first_page.resolve_numbers((2, 1, 2))

        assert [item.source_id for item in selected] == [
            first_page.choices[0].item.source_id,
            first_page.choices[1].item.source_id,
        ]
        with pytest.raises(ValueError, match="current result page"):
            first_page.resolve_numbers((6,))
        with pytest.raises(ValueError, match="out of range"):
            discovery_page(items, 3)
    finally:
        connection.close()
