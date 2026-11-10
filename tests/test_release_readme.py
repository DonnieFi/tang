from pathlib import Path


ROOT = Path(__file__).parents[1]


def test_readme_is_a_verified_release_candidate_surface() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "Keep the blade, switch the handle." in readme
    assert (
        "Continue one coding agent's work inside another, "
        "with the original sources cited."
    ) in readme
    assert "docs/harness-matrix.md" in readme
    assert "docs/tangspec.md" in readme
    assert "SECURITY.md" in readme
    assert "cargo build --manifest-path rust/Cargo.toml --release" in readme
    for command in (
        "tang index",
        "tang browse",
        "tang search",
        "tang catalog sync",
        "tang recall",
        "tang context",
        "tang join",
        "tang graph",
        "tang demo",
        "tang resume HANDLE",
        "tang doctor",
        "tang skill install codex",
        "tang stats",
        "tang purge --all --yes",
    ):
        assert command in readme
    assert "0600" in readme
    assert "8 KiB" in readme
    assert "not native logs" in readme
    assert "TODO(" not in readme
    assert "<owner>" not in readme
    assert "npx" not in readme.lower()


def test_harness_matrix_matches_release_claims() -> None:
    matrix = (ROOT / "docs" / "harness-matrix.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docs/harness-matrix.md" in readme
    assert "Codex CLI 0.145.0" in matrix
    assert "Grok 0.2.106" in matrix
    assert "OpenCode 1.17.18" in matrix
    assert "Cursor IDE" in matrix
    assert "SUPPORTED_DESTINATION_ADAPTERS" in matrix or "harness_capabilities" in matrix
    assert "never** appends recovered transcript" in matrix
    assert "`tang resume` native session | yes | yes | yes | yes" in matrix
    policy = (ROOT / "docs" / "native-write-policy.md").read_text(encoding="utf-8")
    assert "No silent transcript injection" in policy


def test_supported_install_contract_has_one_skill_path() -> None:
    spec = (ROOT / "docs" / "tangspec.md").read_text(encoding="utf-8")
    guide = (ROOT / "docs" / "getting-started.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    for document in (spec, guide, readme):
        assert "tang skill install codex" in document
        assert "npx" not in document.lower()

    assert "Cursor" in spec
    assert "tang resume HANDLE" in spec
    assert "cargo build --manifest-path rust/Cargo.toml --release" in guide
    assert "tang resume HANDLE" in readme

    codex_skill = (ROOT / "skills" / "tang" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "earlier Codex, Grok, or OpenCode sessions" in codex_skill
