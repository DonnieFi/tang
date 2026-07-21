from tang.harness_capabilities import (
    all_capabilities,
    capability_for,
    supported_destination_adapters,
    supported_resume_adapters,
)


def test_registry_matches_continuation_destinations() -> None:
    assert supported_destination_adapters() == frozenset(
        ("codex", "grok", "opencode", "cursor")
    )


def test_grok_is_destination_not_resume() -> None:
    grok = capability_for("grok")
    assert grok is not None
    assert grok.link_destination is True
    assert grok.native_resume is False
    assert grok.host_skill is False


def test_cursor_is_roadmap_only() -> None:
    cursor = capability_for("cursor")
    assert cursor is not None
    assert cursor.release_claim_linux is False
    assert cursor.link_source is True
    assert cursor.link_destination is True


def test_all_entries_have_display_names() -> None:
    assert len(all_capabilities()) >= 4
    assert all(entry.display_name for entry in all_capabilities())
