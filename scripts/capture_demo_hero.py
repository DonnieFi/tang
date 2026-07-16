#!/usr/bin/env python3
"""Capture the real isolated demo's Multiverse card as a README SVG."""

from __future__ import annotations

import argparse
import errno
import os
import pty
import re
import subprocess
from pathlib import Path

from rich.ansi import AnsiDecoder
from rich.console import Console


ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tang", default="tang", help="Tang executable to capture")
    parser.add_argument("--output", type=Path, required=True, help="Destination SVG")
    return parser.parse_args()


def _multiverse_card(output: str) -> str:
    lines = output.splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if "TANG MULTIVERSE MAP" in ANSI.sub("", line)
    )
    end = next(
        index
        for index in range(start, len(lines))
        if ANSI.sub("", lines[index]).startswith("Demo complete;")
    )
    return "\n".join(lines[start:end])


def _run_demo(executable: str) -> str:
    """Run the demo on a pseudo-terminal so its real color policy applies."""

    master, slave = pty.openpty()
    environment = os.environ.copy()
    environment.pop("NO_COLOR", None)
    environment["TERM"] = "xterm-256color"
    process = subprocess.Popen(
        [executable, "demo", "--width", "120"],
        stdout=slave,
        stderr=subprocess.PIPE,
        env=environment,
    )
    os.close(slave)
    chunks: list[bytes] = []
    try:
        while True:
            try:
                chunk = os.read(master, 65_536)
            except OSError as error:
                if error.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(master)
    stderr = process.communicate()[1]
    if process.returncode:
        raise subprocess.CalledProcessError(
            process.returncode,
            process.args,
            output=b"".join(chunks),
            stderr=stderr,
        )
    return b"".join(chunks).decode("utf-8").replace("\r\n", "\n")


def main() -> int:
    args = _arguments()
    card = _multiverse_card(_run_demo(args.tang))
    console = Console(
        record=True,
        width=120,
        force_terminal=True,
        color_system="truecolor",
    )
    console.print(*AnsiDecoder().decode(card), sep="\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    console.save_svg(
        str(args.output),
        title="Tang Multiverse Map — isolated demo",
        theme=None,
        clear=False,
    )
    svg = args.output.read_text(encoding="utf-8")
    svg = re.sub(r"\s*@font-face\s*\{.*?\}\s*", "\n", svg, flags=re.DOTALL)
    svg = "\n".join(line.rstrip() for line in svg.splitlines()) + "\n"
    args.output.write_text(svg, encoding="utf-8")
    print(f"Captured real isolated demo card: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
