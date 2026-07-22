"""Document harness parity expectations against the capability registry."""

from tang.harness_capabilities import all_capabilities, capability_for


def test_registry_covers_indexed_adapters() -> None:
    keys = {entry.adapter_key for entry in all_capabilities()}
    assert keys >= {"codex", "grok", "opencode", "cursor"}


def test_destination_adapters_are_cited_in_matrix_docs() -> None:
    from pathlib import Path

    matrix = (Path(__file__).parents[1] / "docs" / "harness-matrix.md").read_text(
        encoding="utf-8"
    )
    for entry in all_capabilities():
        if entry.link_destination:
            assert entry.display_name.split()[0] in matrix or entry.adapter_key in matrix


def test_matrix_release_claim_matches_registry() -> None:
    from pathlib import Path
    import re

    matrix = (Path(__file__).parents[1] / "docs" / "harness-matrix.md").read_text(
        encoding="utf-8"
    )
    cursor = capability_for("cursor")
    assert cursor is not None
    assert cursor.release_claim_linux
    assert "Cursor IDE" in matrix
    assert re.search(
        r"Read-only session adapter\s*\|\s*yes\s*\|\s*yes\s*\|\s*yes\s*\|\s*yes",
        matrix,
    )


def test_resume_requires_native_flag() -> None:
    for key in ("codex", "grok", "opencode", "cursor"):
        entry = capability_for(key)
        assert entry is not None and entry.native_resume
