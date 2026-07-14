from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import tang
from tang.cli import main


def test_package_name_and_version_are_importable() -> None:
    assert tang.__version__ == "0.1.0"


def test_main_prints_concise_help(capsys) -> None:
    assert main([]) == 0

    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.startswith("usage: tang")
    assert "source-cited context" in captured.out
    assert "index, browse, context, link, and graph" in captured.out


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
