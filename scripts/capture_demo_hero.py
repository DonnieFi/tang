#!/usr/bin/env python3
"""Frame the real Rust `tang demo` as the README Multiverse SVG."""

from __future__ import annotations

import argparse
import io
import re
import subprocess
from pathlib import Path

from rich.console import Console, Group
from rich.panel import Panel
from rich.text import Text

STEEL = "#ff9d3d"
TEAL = "#2aa198"
INK = "#c5c8c6"
RED = "#cc555a"
FORGE = "#171717"

TOKEN = re.compile(
    r"ACTIVE"
    r"|\[(?:MERGE|BRANCH|CONTINUE)\]"
    r"|source unavailable"
    r"|unavailable"
    r"|complete"
    r"|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z"
    r"|[★×][A-Z]"
    r"|\b[A-Z]\b"
    r"|\bgrok\b|\bcodex\b"
    r"|[─│┌┐└┘├┤┬┴┼▶]+"
    r"|Grok research|Codex review|Codex plan|Codex API|Codex CLI|Grok testing"
    r"|Codex hardening|Unavailable source"
    r"|."
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tang", required=True, help="Path to the Rust tang binary")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--width", type=int, default=120)
    return parser.parse_args()


def _demo(executable: str, width: int) -> str:
    completed = subprocess.run(
        [executable, "demo", "--width", str(width)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.replace("\r\n", "\n")


def _style(token: str) -> str:
    if token in {"ACTIVE", "★G"}:
        return f"bold {STEEL}"
    if token == "×U" or "unavailable" in token:
        return f"bold {RED}"
    if token.startswith("["):
        return f"bold {INK}"
    if token in {"A", "B", "C", "D", "E", "F", "G", "U"}:
        return f"bold {TEAL}"
    if token in {
        "Grok research",
        "Codex review",
        "Codex plan",
        "Codex API",
        "Codex CLI",
        "Grok testing",
        "Codex hardening",
        "Unavailable source",
    }:
        return f"bold {TEAL}"
    if token and set(token) <= set("─│┌┐└┘├┤┬┴┼▶"):
        return STEEL
    return INK


def _paint(line: str) -> Text:
    if line.startswith(
        (
            "1 component",
            "confirmed only",
            "MULTIVERSE NETWORK",
            "TIMELINE LANES",
            "SESSION DETAIL",
            "Demo complete",
        )
    ):
        return Text(line, style=f"bold {STEEL}", no_wrap=True, overflow="ignore")
    text = Text(no_wrap=True, overflow="ignore")
    for match in TOKEN.finditer(line):
        token = match.group(0)
        text.append(token, style=_style(token))
    return text


def main() -> int:
    args = _arguments()
    raw = _demo(args.tang, args.width)
    if "TANG MULTIVERSE MAP" not in raw or "Demo complete;" not in raw:
        raise SystemExit("tang demo did not return the Multiverse card")
    lines = [
        line
        for line in raw.splitlines()
        if line != "TANG MULTIVERSE MAP"
    ]
    width = max((len(line) for line in lines), default=80) + 12
    console = Console(
        record=True,
        width=width,
        height=len(lines) + 8,
        force_terminal=True,
        legacy_windows=False,
        safe_box=False,
        color_system="truecolor",
        file=io.StringIO(),
    )
    card = Panel(
        Group(*(_paint(line) for line in lines)),
        title="TANG MULTIVERSE MAP",
        border_style=STEEL,
        style=f"on {FORGE}",
        padding=(1, 2),
    )
    console.print(card)
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
    visible = re.sub(r"<[^>]+>", "", svg)
    visible = (
        visible.replace("&#160;", " ")
        .replace("&gt;", ">")
        .replace("&amp;", "&")
        .replace("&#8203;", "")
    )
    compact = re.sub(r"\s+", "", visible)
    for required in ("Grokresearch", "Codexhardening", "TIMEFLOWS", "LANE02", "★G"):
        if required not in compact:
            raise SystemExit(f"capture is missing {required}")
    if "O1" in compact:
        raise SystemExit("capture still contains the old map")
    print(f"Captured real isolated demo card: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
