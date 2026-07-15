"""Command-line entry point for Tang."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter, SessionHealth, SessionIdentity
from tang.context_service import ContextGenerationError, ContextPackService
from tang.continuation import ContinuationError, ContinuationService, LinkResult
from tang.discovery import DiscoveryFilter, DiscoveryItem, DiscoveryService, rfc3339
from tang.doctor import doctor_exit_code, run_doctor
from tang.indexing import IndexResult, ProjectIndexer
from tang.project import resolve_project
from tang.redaction import ContentKind, DEFAULT_REDACTOR, RedactionSeam
from tang.repository import TangRepository
from tang.storage import open_database
from tang.skill_install import install_codex_skill
from tang.target import candidates_for_project, resolve_current_target


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
    search.add_argument(
        "query",
        help="FTS5 query; simple keywords or quoted phrases are recommended",
    )
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
    link = subparsers.add_parser("link", help="record confirmed continuation edges")
    link.add_argument("--from", dest="source_ids", nargs="+", required=True)
    target = link.add_mutually_exclusive_group(required=True)
    target.add_argument("--current", action="store_true")
    target.add_argument("--to", dest="target_id")
    link.add_argument("--current-native-id")
    link.add_argument("--json", action="store_true", dest="as_json")
    link.add_argument("--database", type=Path)
    link.add_argument("--cwd", type=Path, default=Path.cwd())
    link.add_argument("--codex-home", type=Path)
    doctor = subparsers.add_parser("doctor", help="check Tang readiness")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--database", type=Path)
    doctor.add_argument("--codex-home", type=Path)
    doctor.add_argument("--grok-home", type=Path)
    skill = subparsers.add_parser("skill", help="manage harness skills")
    skill_subparsers = skill.add_subparsers(dest="skill_command")
    install = skill_subparsers.add_parser("install", help="install a harness skill")
    install.add_argument("harness", choices=("codex",))
    install.add_argument("--codex-home", type=Path)
    install.add_argument("--force", action="store_true")
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
    return 1 if result.status == "partial" else 0


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
        f"{result.search_rows} search rows, {result.checkpoints} checkpoints, "
        f"and {result.continuations} continuation edges. "
        "Native harness logs were not modified."
    )
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    checks = run_doctor(
        args.database, codex_home=args.codex_home, grok_home=args.grok_home
    )
    if args.as_json:
        print(
            json.dumps(
                {
                    "checks": [
                        {
                            "component": check.component,
                            "message": check.message,
                            "status": check.status,
                        }
                        for check in checks
                    ],
                    "schema_version": 1,
                    "status": "ready" if doctor_exit_code(checks) == 0 else "degraded",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        for check in checks:
            print(f"{check.component}: {check.status} — {check.message}")
    return doctor_exit_code(checks)


def _run_skill(args: argparse.Namespace) -> int:
    if args.skill_command != "install":
        print("error: skill requires the install subcommand", file=sys.stderr)
        return 2
    try:
        result = install_codex_skill(args.codex_home, force=args.force)
    except (FileExistsError, FileNotFoundError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(result.message)
    return 0


def _link_document(result: LinkResult) -> dict[str, object]:
    return {
        "existing": result.existing,
        "inserted": result.inserted,
        "schema_version": 1,
        "source_ids": list(result.source_ids),
        "target_id": result.target_id,
    }


def _run_link(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    connection = open_database(args.database)
    try:
        repository = TangRepository(connection)
        service = ContinuationService(repository)
        try:
            if args.current:
                scan = CodexAdapter(args.codex_home).scan(None)
                discovery = candidates_for_project(scan.records, project)
                for warning in discovery.warnings:
                    print(f"warning: {warning.code}: {warning.message}", file=sys.stderr)
                excluded = frozenset(
                    SessionIdentity(*source_id.split(":", 2))
                    for source_id in args.source_ids
                )
                resolution = resolve_current_target(
                    discovery.candidates,
                    project,
                    current_native_id=args.current_native_id,
                    exclude=excluded,
                )
                result = service.link_resolved(
                    tuple(args.source_ids),
                    resolution,
                    project.key,
                    datetime.now(timezone.utc),
                )
            else:
                result = service.link(
                    tuple(args.source_ids),
                    args.target_id,
                    project.key,
                    "explicit",
                    datetime.now(timezone.utc),
                )
        except (ContinuationError, ValueError) as error:
            code = error.code if isinstance(error, ContinuationError) else "invalid-session-id"
            print(f"error[{code}]: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()

    if args.as_json:
        print(json.dumps(_link_document(result), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"Linked {len(result.source_ids)} source(s) to {result.target_id}; "
            f"inserted {result.inserted}, existing {result.existing}."
        )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch Tang's scriptable commands, or show top-level help."""
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
    if args.command == "doctor":
        return _run_doctor(args)
    if args.command == "skill":
        return _run_skill(args)
    if args.command == "link":
        return _run_link(args)
    parser.print_help()
    return 0
