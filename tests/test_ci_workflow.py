from pathlib import Path


def test_ci_is_linux_only_and_covers_the_release_path() -> None:
    workflow = (Path(__file__).parents[1] / ".github/workflows/ci.yml").read_text()
    assert 'python-version: ["3.11", "3.12"]' in workflow
    assert workflow.count("runs-on: ubuntu-24.04") == 2
    assert "macos" not in workflow.lower()
    assert "windows" not in workflow.lower()
    for required in (
        "uv sync --locked",
        "pytest -q",
        "scripts/build_release.py",
        "uv pip install",
        "tang skill install codex",
        "tang demo --ascii --width 100",
        "actions/upload-artifact@v4",
    ):
        assert required in workflow
