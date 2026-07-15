"""Command-line entry point for Tang."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter
from tang.indexing import IndexResult, ProjectIndexer
from tang.project import resolve_project
from tang.redaction import ContentKind, DEFAULT_REDACTOR, RedactionSeam
from tang.repository import TangRepository
from tang.storage import open_database


def build_parser() -> argparse.ArgumentParser:
    """Build Tang's top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="tang",
        description=(
            "Continue coding-agent work across harnesses with source-cited context."
        ),
        epilog="Primary workflow: index, browse, context, link, and graph.",
    )
    subparsers = parser.add_subparsers(dest="command")
    index = subparsers.add_parser("index", help="index the current project")
    index.add_argument("--json", action="store_true", dest="as_json")
    index.add_argument("--database", type=Path)
    index.add_argument("--cwd", type=Path, default=Path.cwd())
    index.add_argument("--codex-home", type=Path)
    index.add_argument("--grok-home", type=Path)
    return parser


def _index_document(result: IndexResult) -> dict[str, object]:
    return {
        "excluded": result.excluded,
        "indexed": result.indexed,
        "schema_version": 1,
        "status": result.status,
        "unchanged": result.unchanged,
        "warning_count": len(result.warnings),
    }


def _show_warnings(result: IndexResult) -> None:
    for warning in result.warnings:
        redacted = DEFAULT_REDACTOR.redact_content(
            RedactionSeam.SNIPPET_DISPLAY,
            ContentKind.WARNING,
            f"{warning.code}: {warning.message}",
        )
        assert redacted is not None
        print(f"warning: {redacted.text}", file=sys.stderr)


def _run_index(args: argparse.Namespace) -> int:
    connection = open_database(args.database)
    try:
        repository = TangRepository(connection)
        result = ProjectIndexer(repository).index(
            (
                CodexAdapter(args.codex_home),
                GrokAdapter(args.grok_home),
            ),
            resolve_project(args.cwd),
        )
    finally:
        connection.close()
    if args.as_json:
        print(json.dumps(_index_document(result), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"Indexed {result.indexed}; unchanged {result.unchanged}; "
            f"excluded {result.excluded}; status {result.status}."
        )
    _show_warnings(result)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Print concise help until the vertical-slice commands are implemented."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "index":
        return _run_index(args)
    parser.print_help()
    return 0
