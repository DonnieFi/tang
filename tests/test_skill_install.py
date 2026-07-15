from __future__ import annotations

from pathlib import Path

import pytest

from tang.cli import main
from tang.skill_install import bundled_skill_path, install_codex_skill


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


def test_skill_install_cli_uses_the_bundled_skill(tmp_path: Path, capsys) -> None:
    codex_home = tmp_path / "codex"

    assert main(["skill", "install", "codex", "--codex-home", str(codex_home)]) == 0
    first = capsys.readouterr()
    assert first.err == ""
    assert first.out == "Tang Codex skill installed.\n"
    assert "name: tang" in (codex_home / "skills" / "tang" / "SKILL.md").read_text()

    assert main(["skill", "install", "codex", "--codex-home", str(codex_home)]) == 0
    second = capsys.readouterr()
    assert second.out == "Tang Codex skill is already current.\n"


def test_bundled_skill_resolves_installed_wheel_data(tmp_path: Path, monkeypatch) -> None:
    installed = tmp_path / "share" / "tang" / "skills" / "tang"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text("installed bundle")
    monkeypatch.setattr("tang.skill_install.sys.prefix", str(tmp_path))
    monkeypatch.setattr(
        "tang.skill_install.__file__",
        str(tmp_path / "site-packages" / "tang" / "skill_install.py"),
    )

    assert bundled_skill_path() == installed
