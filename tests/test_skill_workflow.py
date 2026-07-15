from __future__ import annotations

import json
from pathlib import Path

from tang.cli import main


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
    database = tmp_path / "tang.db"
    common = [
        "--database",
        str(database),
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

    selected = tuple(result["source_id"] for result in results if result["harness"] in {"codex", "grok"})
    assert len(selected) >= 2
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


def test_skill_instructions_require_host_selection_without_invented_ids() -> None:
    text = (Path(__file__).parents[1] / "skills" / "tang" / "SKILL.md").read_text()

    required = (
        "host-native multi-select question",
        "Accept only exact IDs from the current result set",
        "never infer selection",
        "ask for a different phrase instead of inventing a candidate",
        "Stop before recording continuation links",
        "Do not build a second interactive terminal browser",
    )
    assert all(phrase in text for phrase in required)
