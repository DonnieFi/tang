"""Command-line entry point for Tang."""

from __future__ import annotations

import argparse
from collections.abc import Sequence


def build_parser() -> argparse.ArgumentParser:
    """Build Tang's top-level argument parser."""
    return argparse.ArgumentParser(
        prog="tang",
        description=(
            "Continue coding-agent work across harnesses with source-cited context."
        ),
        epilog="Primary workflow: index, browse, context, link, and graph.",
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Print concise help until the vertical-slice commands are implemented."""
    parser = build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0
