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


def test_functional_acceptance_covers_installed_skill_and_demo_contracts() -> None:
    module = _module()
    source = SCRIPT.read_text()

    assert module.PROJECT_VERSION == "0.2.7"
    assert module.EXPECTED_WHEEL_FILENAME == "tang_multiverse-0.2.7-py3-none-any.whl"

    for required in (
        '"Keep the canonical `source_id` private"',
        '"`session_handle`"',
        '["demo", "--ascii", "--width", "100"]',
        '"INDEX: 2 indexed; status complete (0 warning(s))"',
        '"MULTIVERSE: selected sources G1 + C1 merge into C2"',
        '"LINK: C5 -> O1 (confirmed; inserted 1)"',
        '"confirmed OpenCode O1"',
        '"isolated demo modified the normal project database"',
        '"wide graph omitted the woven network"',
        '"demo_seconds"',
    ):
        assert required in source
