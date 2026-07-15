"""Command-line entry point for Tang."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter, SessionHealth
from tang.context_service import ContextGenerationError, ContextPackService
from tang.discovery import DiscoveryFilter, DiscoveryItem, DiscoveryService, rfc3339
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
    browse = subparsers.add_parser("browse", help="list current-project sessions")
    _add_discovery_arguments(browse)
    search = subparsers.add_parser("search", help="search current-project capsules")
    search.add_argument("query")
    _add_discovery_arguments(search)
    context = subparsers.add_parser("context", help="build a cited Context Pack")
    context.add_argument("sessions", nargs="+")
    context.add_argument("--json", action="store_true", dest="as_json")
    context.add_argument("--database", type=Path)
    context.add_argument("--cwd", type=Path, default=Path.cwd())
    context.add_argument("--codex-home", type=Path)
    context.add_argument("--grok-home", type=Path)
    purge = subparsers.add_parser("purge", help="remove Tang-derived data")
    purge.add_argument("--all", action="store_true", dest="purge_all")
    purge.add_argument("--yes", action="store_true", help="confirm without a prompt")
    purge.add_argument("--database", type=Path)
    return parser


def _add_discovery_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--harness", choices=("codex", "grok"))
    parser.add_argument("--health", choices=tuple(health.value for health in SessionHealth))
    parser.add_argument("--since", type=_timestamp)
    parser.add_argument("--until", type=_timestamp)


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected an RFC 3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a UTC offset")
    return parsed


def _index_document(result: IndexResult) -> dict[str, object]:
    return {
        "deleted": result.deleted,
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
            f"Indexed {result.indexed}; deleted {result.deleted}; "
            f"unchanged {result.unchanged}; "
            f"excluded {result.excluded}; status {result.status}."
        )
    _show_warnings(result)
    return 0


def _discovery_document(item: DiscoveryItem) -> dict[str, object]:
    return {
        "capabilities": list(item.capabilities),
        "harness": item.harness,
        "health": item.health.value,
        "snippet": item.snippet,
        "source_id": item.source_id,
        "title": item.title,
        "updated_at": rfc3339(item.updated_at),
    }


def _run_discovery(args: argparse.Namespace) -> int:
    connection = open_database(args.database)
    try:
        service = DiscoveryService(TangRepository(connection))
        filters = DiscoveryFilter(
            harness=args.harness,
            health=SessionHealth(args.health) if args.health else None,
            since=args.since,
            until=args.until,
        )
        project_key = resolve_project(args.cwd).key
        try:
            items = (
                service.search(project_key, args.query, filters)
                if args.command == "search"
                else service.browse(project_key, filters)
            )
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()
    if args.as_json:
        document = {
            "results": [_discovery_document(item) for item in items],
            "schema_version": 1,
        }
        print(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        for item in items:
            capability = ",".join(item.capabilities) or "none"
            title = item.title or "(untitled)"
            snippet = f" | {item.snippet}" if item.snippet else ""
            print(
                f"{rfc3339(item.updated_at)} | {item.harness} | "
                f"{item.health.value} | {capability} | {item.source_id} | "
                f"{title}{snippet}"
            )
    return 0


def _run_context(args: argparse.Namespace) -> int:
    connection = open_database(args.database)
    try:
        service = ContextPackService(
            TangRepository(connection),
            (CodexAdapter(args.codex_home), GrokAdapter(args.grok_home)),
        )
        try:
            pack = service.generate(
                tuple(args.sessions), resolve_project(args.cwd).key
            )
        except ContextGenerationError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()
    print(pack.to_json() if args.as_json else pack.to_markdown(), end="")
    return 0


def _run_purge(args: argparse.Namespace) -> int:
    if not args.purge_all:
        print("error: purge currently requires --all", file=sys.stderr)
        return 2
    if not args.yes:
        if not sys.stdin.isatty():
            print("error: non-interactive purge requires --yes", file=sys.stderr)
            return 2
        confirmation = input(
            "Delete all Tang-derived sessions, capsules, search rows, and checkpoints? "
            "Type PURGE to continue: "
        )
        if confirmation != "PURGE":
            print("Purge cancelled; no derived data was changed.")
            return 0

    connection = open_database(args.database)
    try:
        repository = TangRepository(connection)
        with repository.transaction():
            result = repository.purge_all()
    finally:
        connection.close()
    print(
        f"Purged {result.sessions} sessions, {result.capsules} capsules, "
        f"{result.search_rows} search rows, and {result.checkpoints} checkpoints. "
        "Native harness logs were not modified."
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Print concise help until the vertical-slice commands are implemented."""
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "index":
        return _run_index(args)
    if args.command in {"browse", "search"}:
        return _run_discovery(args)
    if args.command == "context":
        return _run_context(args)
    if args.command == "purge":
        return _run_purge(args)
    parser.print_help()
    return 0
