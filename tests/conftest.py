from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


@dataclass(frozen=True, slots=True)
class DiscoveryCorpus:
    codex_home: Path
    grok_home: Path
    expectations: dict[str, object]


@pytest.fixture
def codex_fixture_home() -> Path:
    return FIXTURES / "codex"


@pytest.fixture
def codex_fixture_log(codex_fixture_home: Path) -> Path:
    logs = tuple((codex_fixture_home / "sessions").rglob("*.jsonl"))
    assert len(logs) == 1
    return logs[0]


@pytest.fixture
def copied_codex_home(codex_fixture_home: Path, tmp_path: Path) -> Path:
    destination = tmp_path / "codex-home"
    shutil.copytree(codex_fixture_home, destination)
    return destination


@pytest.fixture
def discovery_corpus(tmp_path: Path) -> DiscoveryCorpus:
    root = tmp_path / "discovery-corpus"
    codex_home = root / "codex"
    grok_home = root / "grok"
    shutil.copytree(FIXTURES / "codex", codex_home)
    shutil.copytree(FIXTURES / "grok", grok_home)
    expectations = json.loads(
        (FIXTURES / "discovery" / "expectations.json").read_text()
    )
    destination = codex_home / "sessions" / "2026" / "07" / "14"
    destination.mkdir(parents=True, exist_ok=True)
    for template in sorted((FIXTURES / "discovery" / "codex-extra").iterdir()):
        name = template.name.removesuffix(".partial")
        text = template.read_text().replace(
            str(expectations["long_marker"]),
            "L" * 3_000,
        )
        (destination / name).write_text(text)
    return DiscoveryCorpus(codex_home, grok_home, expectations)
