from __future__ import annotations

import json
from pathlib import Path

from tang.cli import main
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database


def _point_corpus_at_projects(corpus, current: Path, foreign: Path) -> None:
    for path in (corpus.codex_home / "sessions").rglob("*.jsonl"):
        lines = path.read_text().splitlines()
        metadata = json.loads(lines[0])
        original = metadata["payload"]["cwd"]
        metadata["payload"]["cwd"] = str(
            foreign if original == "/work/foreign-vault" else current
        )
        lines[0] = json.dumps(metadata, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n")
    summary = next((corpus.grok_home / "sessions").rglob("summary.json"))
    payload = json.loads(summary.read_text())
    payload["git_root_dir"] = str(current)
    summary.write_text(json.dumps(payload, separators=(",", ":")))


def test_scripted_skill_discovery_and_explicit_multi_select(
    discovery_corpus, tmp_path: Path, capsys
) -> None:
    current = tmp_path / "current"
    foreign = tmp_path / "foreign"
    current.mkdir()
    foreign.mkdir()
    _point_corpus_at_projects(discovery_corpus, current, foreign)
    codex_log = next(
        path
        for path in (discovery_corpus.codex_home / "sessions").rglob("*.jsonl")
        if "deterministic checkpoint recovery" in path.read_text()
    )
    codex_log.write_text(
        codex_log.read_text().replace(
            "deterministic checkpoint recovery",
            'credentialmarker PASSWORD="preview-secret" deterministic checkpoint recovery',
        )
    )
    common = [
        "--cwd",
        str(current),
    ]
    adapter_paths = [
        "--codex-home",
        str(discovery_corpus.codex_home),
        "--grok-home",
        str(discovery_corpus.grok_home),
    ]

    assert main(["index", *common, *adapter_paths, "--json"]) == 1
    capsys.readouterr()

    current_native_id = "019f6000-5678-7000-8000-000000000002"
    assert (
        main(
            [
                "search",
                "checkpoint",
                *common,
                "--exclude-current",
                "--current-native-id",
                current_native_id,
                "--json",
            ]
        )
        == 0
    )
    excluded_search = json.loads(capsys.readouterr().out)
    assert all(
        not result["source_id"].endswith(current_native_id)
        for result in excluded_search["results"]
    )
    assert any(
        result["harness"] == "grok" for result in excluded_search["results"]
    )

    assert (
        main(
            [
                "browse",
                *common,
                "--exclude-current",
            ]
        )
        == 2
    )
    ambiguous_current = capsys.readouterr()
    assert ambiguous_current.out == ""
    assert "error[target-unconfirmed]" in ambiguous_current.err

    assert main(["search", "checkpoint", *common, "--json"]) == 0
    search_output = capsys.readouterr()
    document = json.loads(search_output.out)
    results = document["results"]

    assert {result["harness"] for result in results} == {"codex", "grok"}
    rendered = json.dumps(document)
    assert "preview-secret" not in rendered
    assert "foreign-quasar-secret" not in rendered
    assert "HIDDEN_THOUGHT_CANARY" not in rendered
    assert "TOOL_INPUT_CANARY" not in rendered

    selected = (
        next(result["source_id"] for result in results if result["harness"] == "grok"),
        next(result["source_id"] for result in results if result["harness"] == "codex"),
    )
    assert set(selected) <= {result["source_id"] for result in results}
    assert main(["context", *selected, *common, *adapter_paths, "--json"]) == 0
    context_output = capsys.readouterr()
    pack = json.loads(context_output.out)
    packed_sources = pack["untrusted_data_envelope"]["sources"]
    assert {section["source_id"] for section in packed_sources} == set(selected)
    assert "target" not in pack
    assert "continuations" not in pack
    assert "preview-secret" not in context_output.out
    assert "foreign-quasar-secret" not in context_output.out

    target_native_id = "019f6000-5678-7000-8000-000000000005"
    assert main(["browse", *common, "--json"]) == 0
    browse_results = json.loads(capsys.readouterr().out)["results"]
    target_handle = next(
        result["session_handle"]
        for result in browse_results
        if result["source_id"].endswith(target_native_id)
    )
    link = [
        "link",
        "--from",
        *selected,
        "--current",
        "--current-native-id",
        target_native_id,
        *common,
        "--codex-home",
        str(discovery_corpus.codex_home),
        "--json",
    ]
    assert main(link) == 0
    linked = json.loads(capsys.readouterr().out)
    assert tuple(linked["source_ids"]) == selected
    assert linked["target_id"].endswith(target_native_id)

    ambiguous = link.copy()
    native_flag = ambiguous.index("--current-native-id")
    del ambiguous[native_flag : native_flag + 2]
    assert main(ambiguous) == 2
    refused = capsys.readouterr()
    assert refused.out == ""
    assert "error[target-unconfirmed]" in refused.err

    assert main(
        [
            "link",
            "--from",
            target_handle,
            "--to",
            selected[1],
            *common,
        ]
    ) == 2
    invalid = capsys.readouterr()
    assert invalid.out == ""
    assert "error[cycle]" in invalid.err

    assert main(
        [
            "graph",
            target_handle,
            *common,
            "--codex-home",
            str(discovery_corpus.codex_home),
            "--current-native-id",
            target_native_id,
            "--width",
            "100",
        ]
    ) == 0
    graph_output = capsys.readouterr()
    assert graph_output.err == ""
    assert "TANG MULTIVERSE MAP" in graph_output.out
    assert graph_output.out.count("──▶") == len(selected)
    assert f"★ {target_handle}" in graph_output.out
    assert target_native_id not in graph_output.out
    assert f"ACTIVE {target_handle}" in graph_output.out

    database = current / ".tang" / "tang.db"
    assert database.is_file()
    connection = open_database(database)
    try:
        edges = TangRepository(connection).continuations_for_project(
            resolve_project(current).key
        )
        assert {(edge.source_id, edge.target_id) for edge in edges} == {
            (source_id, linked["target_id"]) for source_id in selected
        }
    finally:
        connection.close()


def test_skill_instructions_require_host_selection_without_invented_ids() -> None:
    text = (Path(__file__).parents[1] / "skills" / "tang" / "SKILL.md").read_text()

    required = (
        "host-native multi-select question",
        "Keep the canonical `source_id` private",
        "displayed choice numbers",
        "Accept only integers visible on the current page",
        "deduplicate selected canonical IDs",
        "--page 1",
        "Next page",
        "Never infer selection",
        "ask for a different phrase instead of inventing a candidate",
        "Stop before recording continuation links",
        "explicit approval",
        "Never guess among candidates",
        "source_ids` exactly match the selection",
        "tang graph <target_id>",
        "one canonical continuation command",
        "idempotent replay",
        "Do not build a second interactive terminal browser",
        "Do not re-index before every follow-up browse or search",
        "--exclude-current",
        "error[target-unconfirmed]",
    )
    assert all(phrase in text for phrase in required)
