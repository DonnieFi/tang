from __future__ import annotations

import subprocess
from pathlib import Path

from tang.project import ProjectKind, resolve_project


def git(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def initialized_repository(path: Path) -> Path:
    git("init", "--initial-branch=main", str(path))
    git("config", "user.name", "Tang Fixture", cwd=path)
    git("config", "user.email", "fixture@example.invalid", cwd=path)
    git("commit", "--allow-empty", "-m", "fixture baseline", cwd=path)
    return path


def test_main_and_linked_worktree_share_project_identity(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "primary-project")
    linked = tmp_path / "linked-worktree"
    git("worktree", "add", "-b", "fixture-linked", str(linked), cwd=repository)

    primary = resolve_project(repository)
    worktree = resolve_project(linked)

    assert primary.kind is ProjectKind.GIT
    assert primary.key == worktree.key
    assert primary.identity_path == worktree.identity_path
    assert primary.display_name == worktree.display_name == "primary-project"


def test_separate_clone_has_distinct_identity(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "source-project")
    clone = tmp_path / "separate-clone"
    git("clone", str(repository), str(clone))

    source = resolve_project(repository)
    copied = resolve_project(clone)

    assert source.kind is copied.kind is ProjectKind.GIT
    assert source.key != copied.key
    assert source.identity_path != copied.identity_path


def test_symlink_and_normalized_paths_resolve_to_same_project(tmp_path: Path) -> None:
    repository = initialized_repository(tmp_path / "normalized-project")
    nested = repository / "nested"
    nested.mkdir()
    alias = tmp_path / "project-alias"
    alias.symlink_to(repository, target_is_directory=True)

    assert resolve_project(alias).key == resolve_project(nested / "..").key


def test_non_git_directory_uses_resolved_path_identity(tmp_path: Path) -> None:
    directory = tmp_path / "local-notes"
    directory.mkdir()
    alias = tmp_path / "notes-alias"
    alias.symlink_to(directory, target_is_directory=True)

    direct = resolve_project(directory)
    through_alias = resolve_project(alias)

    assert direct.kind is ProjectKind.DIRECTORY
    assert direct.identity_path == directory.resolve()
    assert direct == through_alias


def test_display_and_repr_do_not_expose_absolute_path(tmp_path: Path) -> None:
    private_parent = tmp_path / "private-owner"
    directory = private_parent / "display-project"
    directory.mkdir(parents=True)

    identity = resolve_project(directory)

    assert identity.display_name == "display-project"
    assert str(private_parent) not in identity.display_name
    assert str(private_parent) not in repr(identity)
