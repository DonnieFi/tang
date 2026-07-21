from __future__ import annotations

import subprocess
import sys

import pytest

from tang.cli import build_parser


RELEASE_COMMANDS = {
    "browse",
    "context",
    "continuity",
    "demo",
    "doctor",
    "graph",
    "index",
    "link",
    "purge",
    "resume",
    "search",
    "skill",
}


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tang", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )


def test_top_level_parser_exposes_exact_release_commands() -> None:
    subparsers = next(
        action for action in build_parser()._actions if action.dest == "command"
    )
    assert set(subparsers.choices) == RELEASE_COMMANDS


@pytest.mark.parametrize(
    "arguments",
    [
        ("--help",),
        *((command, "--help") for command in sorted(RELEASE_COMMANDS - {"skill"})),
        ("skill", "--help"),
        ("skill", "install", "--help"),
    ],
)
def test_every_release_command_has_stdout_only_help(arguments: tuple[str, ...]) -> None:
    result = run(*arguments)
    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.startswith("usage: tang")


@pytest.mark.parametrize(
    "arguments",
    [
        ("search",),
        ("context", "--for"),
        ("link",),
        ("purge", "--all"),
        ("resume",),
        ("skill",),
        ("graph", "--width", "not-an-integer"),
        ("demo", "--width", "not-an-integer"),
    ],
)
def test_invalid_noninteractive_invocations_never_prompt(
    arguments: tuple[str, ...],
) -> None:
    result = run(*arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith(("usage: tang", "error:"))
