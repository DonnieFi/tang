"""Epic 8 characterization: public contracts must not drift during hardening."""

from pathlib import Path

from tang.continuation import SUPPORTED_DESTINATION_ADAPTERS
from tang.harness_capabilities import supported_destination_adapters


def test_destination_adapters_match_harness_registry() -> None:
    assert SUPPORTED_DESTINATION_ADAPTERS == supported_destination_adapters()


def test_compatibility_baseline_doc_exists() -> None:
    doc = Path(__file__).parents[1] / "docs" / "epic8-compatibility-baseline.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    assert "Epic 8" in text
    assert "test_release_cli.py" in text
