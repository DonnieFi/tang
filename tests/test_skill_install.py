from __future__ import annotations

from pathlib import Path

import pytest

from tang.skill_install import install_codex_skill


def _bundle(root: Path, content: str = "workflow") -> Path:
    source = root / "bundle"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(content)
    (source / "agents").mkdir()
    (source / "agents" / "openai.yaml").write_text("name: Tang\n")
    return source


def test_skill_install_is_idempotent_and_refuses_divergent_content(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    codex_home = tmp_path / "codex"

    first = install_codex_skill(codex_home, source=source)
    second = install_codex_skill(codex_home, source=source)

    assert first.status == "installed"
    assert second.status == "unchanged"
    assert (codex_home / "skills" / "tang" / "SKILL.md").read_text() == "workflow"

    (codex_home / "skills" / "tang" / "SKILL.md").write_text("local change")
    with pytest.raises(FileExistsError, match="--force"):
        install_codex_skill(codex_home, source=source)

    replaced = install_codex_skill(codex_home, source=source, force=True)
    assert replaced.status == "installed"
    assert (codex_home / "skills" / "tang" / "SKILL.md").read_text() == "workflow"


def test_skill_install_refuses_symlinked_destination(tmp_path: Path) -> None:
    source = _bundle(tmp_path)
    codex_home = tmp_path / "codex"
    skills = codex_home / "skills"
    skills.mkdir(parents=True)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (skills / "tang").symlink_to(target, target_is_directory=True)

    with pytest.raises(OSError, match="symlinked"):
        install_codex_skill(codex_home, source=source, force=True)
