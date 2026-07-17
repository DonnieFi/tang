from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import tang
from tang.cli import main
from tang.storage import DatabaseOpenError


def test_package_name_and_version_are_importable() -> None:
    assert tang.__version__ == "0.2.2"


def test_main_prints_concise_help(capsys) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("usage: tang")
    assert "source-cited context" in captured.out
    assert "index, browse, context, link, and graph" in captured.out
    assert "connect, use tang link --help" in captured.out


def test_help_flag_exits_successfully(capsys) -> None:
    try:
        main(["--help"])
    except SystemExit as error:
        assert error.code == 0
    else:
        raise AssertionError("argparse did not exit for --help")

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("usage: tang")


def test_python_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tang"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith("usage: tang")


def test_installed_console_script_entry_point() -> None:
    executable = Path(sys.executable).with_name("tang")
    assert executable.is_file(), f"console script is not installed: {executable}"

    result = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith("usage: tang")


def test_storage_setup_failure_is_actionable(tmp_path: Path, monkeypatch, capsys) -> None:
    project = tmp_path / "project"
    project.mkdir()

    def fail_database(_path: Path):
        raise DatabaseOpenError("Tang cannot open derived storage at PROJECT/.tang/tang.db")

    monkeypatch.setattr("tang.cli.open_database", fail_database)

    assert main(["index", "--cwd", str(project)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error[storage-unavailable]: Tang cannot open")


@pytest.mark.parametrize(
    "arguments",
    [
        ("browse",),
        ("search", "checkpoint"),
        ("context", "C1"),
        ("link", "--from", "C1", "--to", "C2"),
        ("graph", "C1"),
    ],
)
def test_index_dependent_commands_do_not_create_absent_storage(
    arguments: tuple[str, ...], tmp_path: Path, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    database = project / ".tang" / "tang.db"

    assert main([*arguments, "--cwd", str(project)]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error[index-required]")
    assert not database.exists()
    assert not database.parent.exists()


def test_connect_is_an_actionable_unknown_command_without_running_link(
    monkeypatch, capsys
) -> None:
    def unexpected_database(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("connect recovery must not open storage or create an edge")

    monkeypatch.setattr("tang.cli.open_database", unexpected_database)

    assert main(["connect", "--from", "codex:fixture:source"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "error[unknown-command]: connect is not a Tang command. Use tang link "
        "after selecting source session(s) and explicitly confirming a target; "
        "run tang link --help for the safe continuation flow.\n"
    )


def test_link_help_explains_the_confirmed_continuation_flow(capsys) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["link", "--help"])

    assert exit_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert "explicitly confirmed predecessors" in captured.out
    assert "Select sources with browse or search" in captured.out
    help_text = " ".join(captured.out.split())
    assert "Re-running the same confirmed edges is safe" in help_text
    assert "tang graph <target-handle>" in help_text
