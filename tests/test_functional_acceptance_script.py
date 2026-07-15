from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "functional_acceptance.py"


def _module():
    spec = importlib.util.spec_from_file_location("functional_acceptance", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_functional_acceptance_help_is_source_checkout_portable() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "clean" in result.stdout
    assert "--output" in result.stdout


def test_functional_acceptance_prepares_only_copied_native_data(tmp_path: Path) -> None:
    module = _module()
    fixture_hashes = module._tree_hashes(module.FIXTURES)

    current, foreign, codex_home, grok_home = module._prepare_corpus(tmp_path)

    assert current.is_dir()
    assert foreign.is_dir()
    assert len(tuple((codex_home / "sessions").rglob("*.jsonl"))) == 4
    assert len(tuple((grok_home / "sessions").rglob("summary.json"))) == 1
    assert module._tree_hashes(module.FIXTURES) == fixture_hashes
