from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_readme_is_a_verified_release_candidate_surface() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Keep the blade, switch the handle." in readme
    assert (
        "Continue one coding agent's work inside another, "
        "with the original sources cited."
    ) in readme
    assert "docs/assets/tang-multiverse-demo.svg" in readme
    hero = (ROOT / "docs" / "assets" / "tang-multiverse-demo.svg").read_text(
        encoding="utf-8"
    )
    assert "cdnjs.cloudflare.com" not in hero
    assert 'url("http' not in hero
    assert "DonnieFi/tang/releases/download/v0.1.0" in readme
    assert "Codex CLI 0.144.4" in readme and "Grok 0.2.99" in readme
    assert "$tang" in readme and "not a `/tang` slash command" in readme
    assert "019f62b2-5a7d-75c3-922d-969b182ec9a2" in readme
    assert "CONTEXT.md" in readme
    assert "TODO(" not in readme
    assert "<owner>" not in readme
    assert "npx" not in readme.lower()


def test_supported_install_contract_has_one_skill_path() -> None:
    spec = (ROOT / "docs" / "tangspec.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")

    for document in (spec, guide):
        assert "tang skill install codex" in document
        assert "npx" not in document.lower()
