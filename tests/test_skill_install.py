from __future__ import annotations

import os
from pathlib import Path

import pytest

from tang.cli import main
from tang.skill_install import (
    bundled_opencode_paths,
    bundled_skill_path,
    install_codex_skill,
    install_opencode_skill,
)


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


def test_opencode_install_is_idempotent_change_safe_and_cli_accessible(
    tmp_path: Path, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()

    first = install_opencode_skill(project)
    second = install_opencode_skill(project)

    assert (first.status, second.status) == ("installed", "unchanged")
    config = project / ".opencode"
    assert (config / "skills/tang/SKILL.md").is_file()
    assert (config / "commands/tang.md").is_file()
    assert (config / "tools/tang_current_target.ts").is_file()
    unrelated = config / "package.json"
    unrelated.write_text('{"dependencies":{"user-owned":"1.0.0"}}')
    if os.name == "posix":
        assert (config / "skills/tang").stat().st_mode & 0o777 == 0o700
        assert (config / "skills/tang/SKILL.md").stat().st_mode & 0o777 == 0o600
        assert (config / "commands/tang.md").stat().st_mode & 0o777 == 0o600
        assert (config / "tools/tang_current_target.ts").stat().st_mode & 0o777 == 0o600

    command = config / "commands/tang.md"
    command.write_text("local customization")
    skill_before = (config / "skills/tang/SKILL.md").read_bytes()
    with pytest.raises(FileExistsError, match="--force"):
        install_opencode_skill(project)
    assert (config / "skills/tang/SKILL.md").read_bytes() == skill_before

    replaced = install_opencode_skill(project, force=True)
    assert replaced.status == "installed"
    assert command.read_text() != "local customization"
    assert unrelated.read_text() == '{"dependencies":{"user-owned":"1.0.0"}}'

    assert main(["skill", "install", "opencode", "--project-root", str(project)]) == 0
    assert capsys.readouterr().out == "Tang OpenCode integration is already current.\n"


def test_opencode_install_refuses_symlinked_config(tmp_path: Path) -> None:
    project = tmp_path / "project"
    elsewhere = tmp_path / "elsewhere"
    project.mkdir()
    elsewhere.mkdir()
    (project / ".opencode").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(OSError, match="symlinked"):
        install_opencode_skill(project, force=True)


def test_opencode_install_repairs_a_missing_owned_asset_without_force(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    install_opencode_skill(project)
    command = project / ".opencode/commands/tang.md"
    command.unlink()

    repaired = install_opencode_skill(project)

    assert repaired.status == "installed"
    assert command.is_file()


def test_opencode_install_refuses_symlinked_source(tmp_path: Path) -> None:
    project = tmp_path / "project"
    source = tmp_path / "source"
    real = tmp_path / "real.md"
    project.mkdir()
    source.mkdir()
    real.write_text("private")
    (source / "SKILL.md").symlink_to(real)

    with pytest.raises(OSError, match="sources may not contain symlinks"):
        install_opencode_skill(
            project,
            sources=((source, Path("skills/tang")),),
        )


def test_bundled_opencode_paths_resolve_installed_wheel_data(
    tmp_path: Path, monkeypatch
) -> None:
    installed = tmp_path / "share" / "tang" / "opencode"
    (installed / "skills/tang").mkdir(parents=True)
    (installed / "commands").mkdir()
    (installed / "tools").mkdir()
    (installed / "skills/tang/SKILL.md").write_text("installed")
    (installed / "commands/tang.md").write_text("installed")
    (installed / "tools/tang_current_target.ts").write_text("installed")
    monkeypatch.setattr("tang.skill_install.sys.prefix", str(tmp_path))
    monkeypatch.setattr(
        "tang.skill_install.__file__",
        str(tmp_path / "site-packages" / "tang" / "skill_install.py"),
    )

    assert bundled_opencode_paths() == (
        (installed / "skills/tang", Path("skills/tang")),
        (installed / "commands/tang.md", Path("commands/tang.md")),
        (
            installed / "tools/tang_current_target.ts",
            Path("tools/tang_current_target.ts"),
        ),
    )
