from __future__ import annotations

import shutil
from pathlib import Path

import pytest


FIXTURES = Path(__file__).parent / "fixtures"


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
