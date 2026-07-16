"""Command-line entry point for Tang."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import CodexAdapter, GrokAdapter, SessionHealth, SessionIdentity
from tang.context_service import ContextGenerationError, ContextPackService
from tang.continuation import ContinuationError, ContinuationService, LinkResult
from tang.discovery import (
    DiscoveryFilter,
    DiscoveryItem,
    DiscoveryPage,
    DiscoveryService,
    discovery_page,
)
from tang.doctor import doctor_exit_code, run_doctor
from tang.graph import GraphService
from tang.indexing import IndexResult, ProjectIndexer
from tang.project import ProjectIdentity, resolve_project
from tang.redaction import (
    ContentKind,
    DEFAULT_REDACTOR,
    RedactionSeam,
    required_redaction,
)
from tang.render import render_multiverse
from tang.repository import TangRepository
from tang.skill_install import install_codex_skill
from tang.storage import DatabaseOpenError, open_database, project_data_path
from tang.timeutil import rfc3339
from tang.target import (
    TargetResolutionKind,
    candidates_for_project,
    resolve_current_target,
)


def build_parser() -> argparse.ArgumentParser:
    """Build Tang's top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="tang",
        description=(
            "Continue coding-agent work across harnesses with source-cited context."
        ),
        epilog=(
            "Primary workflow: index, browse, context, link, and graph. Recovery "
            "flow: index; browse or search; build context; explicitly "
            "confirm a target with link; then graph the result. If you looked for "
            "connect, use tang link --help."
        ),
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
    context.add_argument(
        "sessions", nargs="+", help="project handles or exact IDs from JSON"
    )
    context.add_argument("--json", action="store_true", dest="as_json")
    context.add_argument("--database", type=Path)
    context.add_argument("--cwd", type=Path, default=Path.cwd())
    context.add_argument("--codex-home", type=Path)
    context.add_argument("--grok-home", type=Path)
    purge = subparsers.add_parser("purge", help="remove Tang-derived data")
    purge.add_argument("--all", action="store_true", dest="purge_all")
    purge.add_argument("--yes", action="store_true", help="confirm without a prompt")
    purge.add_argument("--database", type=Path)
    purge.add_argument("--cwd", type=Path, default=Path.cwd())
    link = subparsers.add_parser(
        "link",
        help="record explicitly confirmed continuation edges",
        description=(
            "Record selected source sessions as explicitly confirmed predecessors "
            "of one current-project target."
        ),
        epilog=(
            "Select sources with browse or search, build a Context Pack, and ask "
            "for target confirmation before running this command. Re-running the "
            "same confirmed edges is safe and reports existing edges. After a "
            "successful link, run tang graph <target-handle> to show the Multiverse Map."
        ),
    )
    link.add_argument(
        "--from",
        dest="source_ids",
        nargs="+",
        required=True,
        help="project handles or exact selected IDs from JSON",
    )
    target = link.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--current",
        action="store_true",
        help="resolve a host-confirmed current Codex target",
    )
    target.add_argument(
        "--to",
        dest="target_id",
        help="project handle or exact target ID after explicit confirmation",
    )
    link.add_argument(
        "--current-native-id",
        help="host-supplied native ID used to confirm --current",
    )
    link.add_argument("--json", action="store_true", dest="as_json")
    link.add_argument("--database", type=Path)
    link.add_argument("--cwd", type=Path, default=Path.cwd())
    link.add_argument("--codex-home", type=Path)
    graph = subparsers.add_parser("graph", help="render a confirmed Multiverse Map")
    graph.add_argument("session", nargs="?")
    graph.add_argument("--database", type=Path)
    graph.add_argument("--cwd", type=Path, default=Path.cwd())
    graph.add_argument("--codex-home", type=Path)
    graph.add_argument("--current-native-id")
    graph.add_argument("--width", type=int)
    graph.add_argument("--ascii", action="store_true", dest="ascii_only")
    demo = subparsers.add_parser("demo", help="run the isolated synthetic demo")
    demo.add_argument("--width", type=int, default=120)
    demo.add_argument("--ascii", action="store_true", dest="ascii_only")
    doctor = subparsers.add_parser("doctor", help="check Tang readiness")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--database", type=Path)
    doctor.add_argument("--cwd", type=Path, default=Path.cwd())
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
    parser.add_argument(
        "--page",
        type=int,
        help="show one five-result human page; JSON paging is opt-in",
    )
    parser.add_argument(
        "--exclude-current",
        action="store_true",
        help="exclude the exactly resolved current Codex session from results",
    )
    parser.add_argument(
        "--current-native-id",
        help="host-supplied native Codex session ID used with --exclude-current",
    )


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
        "diagnostic_count": len(result.diagnostics),
        "diagnostics": [
            {
                "code": diagnostic.code,
                "message": _redacted_index_message(
                    diagnostic.code, diagnostic.message
                ),
                "scope": diagnostic.scope,
            }
            for diagnostic in result.diagnostics
        ],
        "excluded": result.excluded,
        "indexed": result.indexed,
        "schema_version": 1,
        "status": result.status,
        "unchanged": result.unchanged,
        "warning_count": len(result.warnings),
        "warnings": [
            {
                "code": warning.code,
                "message": _redacted_index_message(warning.code, warning.message),
                "scope": "project",
            }
            for warning in result.warnings
        ],
    }


def _redacted_index_message(code: str, message: str) -> str:
    redacted = required_redaction(
        DEFAULT_REDACTOR,
        RedactionSeam.SNIPPET_DISPLAY,
        ContentKind.WARNING,
        f"{code}: {message}",
    )
    return redacted.text


def _show_warnings(result: IndexResult) -> None:
    for warning in result.warnings:
        print(
            f"warning: {_redacted_index_message(warning.code, warning.message)}",
            file=sys.stderr,
        )


def _show_diagnostics(result: IndexResult) -> None:
    for diagnostic in result.diagnostics:
        print(
            f"diagnostic[{diagnostic.scope}]: "
            f"{_redacted_index_message(diagnostic.code, diagnostic.message)}",
            file=sys.stderr,
        )


def _database_for(
    args: argparse.Namespace, project: ProjectIdentity
) -> Path:
    """Return an explicit override or the one durable database for a project."""

    database = getattr(args, "database", None)
    return database if database is not None else project_data_path(project)


def _current_source_exclusion(
    args: argparse.Namespace,
    repository: TangRepository,
    project: ProjectIdentity,
) -> tuple[str, ...] | None:
    """Resolve an exact indexed current-session exclusion without native rescans."""

    if not args.exclude_current:
        if args.current_native_id is not None:
            print(
                "error: --current-native-id requires --exclude-current",
                file=sys.stderr,
            )
            return None
        return ()
    candidates = repository.discovery_source_ids(
        project.key,
        adapter="codex",
        native_id=args.current_native_id,
    )
    if len(candidates) == 1:
        return candidates
    if not candidates and args.current_native_id is not None:
        # An unindexed current session cannot be returned as a discovery source.
        return ()
    if not candidates:
        print(
            "warning: current-session exclusion found no indexed Codex source; "
            "no result was excluded.",
            file=sys.stderr,
        )
        return ()
    if args.current_native_id is None:
        print(
            "error[target-unconfirmed]: Several eligible Codex sessions are "
            "indexed; supply a host native session ID rather than guessing.",
            file=sys.stderr,
        )
        return None
    print(
        "error[target-unconfirmed]: The supplied native session ID matched "
        "several indexed Codex identities; choose explicitly.",
        file=sys.stderr,
    )
    return None


def _run_index(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    connection = open_database(_database_for(args, project))
    try:
        repository = TangRepository(connection)
        result = ProjectIndexer(repository).index(
            (
                CodexAdapter(args.codex_home),
                GrokAdapter(args.grok_home),
            ),
            project,
        )
    finally:
        connection.close()
    if args.as_json:
        print(json.dumps(_index_document(result), sort_keys=True, separators=(",", ":")))
    else:
        print(
            f"Indexed {result.indexed}; deleted {result.deleted}; "
            f"unchanged {result.unchanged}; "
            f"excluded {result.excluded}; diagnostics {len(result.diagnostics)}; "
            f"status {result.status}."
        )
    _show_warnings(result)
    _show_diagnostics(result)
    return 1 if result.status == "partial" else 0


def _discovery_document(
    item: DiscoveryItem, *, choice_number: int | None = None
) -> dict[str, object]:
    document: dict[str, object] = {
        "capabilities": list(item.capabilities),
        "display_name": item.display_name,
        "harness": item.harness,
        "health": item.health.value,
        "session_handle": item.handle,
        "snippet": item.snippet,
        "source_id": item.source_id,
        "title": item.title,
        "updated_at": rfc3339(item.updated_at),
    }
    if choice_number is not None:
        document["choice_number"] = choice_number
    return document


def _show_discovery_page(page: DiscoveryPage) -> None:
    if not page.choices:
        print("No indexed sessions.")
        return
    for choice in page.choices:
        item = choice.item
        capability = ",".join(item.capabilities) or "none"
        snippet = f" | {item.snippet}" if item.snippet else ""
        print(
            f"[{choice.number}] {item.handle} | {item.display_name} | {item.harness} | "
            f"{rfc3339(item.updated_at)} | {item.health.value} | {capability}"
            f"{snippet}"
        )
    print(f"Page {page.number} of {page.page_count} ({page.result_count} results).")
    if page.has_next:
        print(f"Use --page {page.number + 1} for the next page.")
    elif page.has_previous:
        print(f"Use --page {page.number - 1} for the previous page.")


def _run_discovery(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    connection = open_database(_database_for(args, project))
    try:
        repository = TangRepository(connection)
        excluded_source_ids = _current_source_exclusion(args, repository, project)
        if excluded_source_ids is None:
            return 2
        service = DiscoveryService(repository)
        filters = DiscoveryFilter(
            harness=args.harness,
            health=SessionHealth(args.health) if args.health else None,
            since=args.since,
            until=args.until,
        )
        project_key = project.key
        try:
            items = (
                service.search(
                    project_key,
                    args.query,
                    filters,
                    exclude_source_ids=excluded_source_ids,
                )
                if args.command == "search"
                else service.browse(
                    project_key,
                    filters,
                    exclude_source_ids=excluded_source_ids,
                )
            )
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()
    page: DiscoveryPage | None = None
    if not args.as_json or args.page is not None:
        try:
            page = discovery_page(items, args.page or 1)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    if args.as_json:
        document = {
            "results": (
                [
                    _discovery_document(
                        choice.item, choice_number=choice.number
                    )
                    for choice in page.choices
                ]
                if page is not None
                else [_discovery_document(item) for item in items]
            ),
            "schema_version": 1,
        }
        if page is not None:
            document.update(
                {
                    "page": page.number,
                    "page_count": page.page_count,
                    "result_count": page.result_count,
                }
            )
        print(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        if page is None:
            raise RuntimeError("human discovery output requires a result page")
        _show_discovery_page(page)
    return 0


def _run_context(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    connection = open_database(_database_for(args, project))
    try:
        repository = TangRepository(connection)
        service = ContextPackService(
            repository,
            (CodexAdapter(args.codex_home), GrokAdapter(args.grok_home)),
        )
        try:
            source_ids = tuple(
                repository.resolve_session_token(token, project.key)
                for token in args.sessions
            )
            pack = service.generate(
                source_ids, project.key
            )
        except (ContextGenerationError, ValueError) as error:
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

    project = resolve_project(args.cwd)
    connection = open_database(_database_for(args, project))
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
    project = resolve_project(args.cwd)
    checks = run_doctor(
        _database_for(args, project),
        codex_home=args.codex_home,
        grok_home=args.grok_home,
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
    connection = open_database(_database_for(args, project))
    try:
        repository = TangRepository(connection)
        service = ContinuationService(repository)
        try:
            source_ids = tuple(
                repository.resolve_session_token(token, project.key)
                for token in args.source_ids
            )
            if args.current:
                scan = CodexAdapter(args.codex_home).scan(None)
                discovery = candidates_for_project(scan.records, project)
                for warning in discovery.warnings:
                    print(f"warning: {warning.code}: {warning.message}", file=sys.stderr)
                excluded = frozenset(
                    SessionIdentity.from_canonical(source_id)
                    for source_id in source_ids
                )
                resolution = resolve_current_target(
                    discovery.candidates,
                    project,
                    current_native_id=args.current_native_id,
                    exclude=excluded,
                )
                result = service.link_resolved(
                    source_ids,
                    resolution,
                    project.key,
                    datetime.now(timezone.utc),
                )
            else:
                target_id = repository.resolve_session_token(
                    args.target_id, project.key
                )
                result = service.link(
                    source_ids,
                    target_id,
                    project.key,
                    "explicit",
                    datetime.now(timezone.utc),
                )
            source_handles = tuple(
                repository.handle_for_source_id(source_id)
                for source_id in result.source_ids
            )
            target_handle = repository.handle_for_source_id(result.target_id)
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
            f"Linked {', '.join(source_handles)} to {target_handle}; "
            f"inserted {result.inserted}, existing {result.existing}."
        )
    return 0


def _run_graph(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    resolution = None
    if args.session is None or args.current_native_id is not None:
        scan = CodexAdapter(args.codex_home).scan(None)
        resolution = resolve_current_target(
            candidates_for_project(scan.records, project).candidates,
            project,
            current_native_id=args.current_native_id,
        )
    if args.session is None:
        if resolution is None:
            raise RuntimeError("graph target resolution was not attempted")
        if resolution.kind is not TargetResolutionKind.RESOLVED or resolution.target is None:
            print(
                "error[target-unconfirmed]: Choose an explicit graph session or confirm the current target.",
                file=sys.stderr,
            )
            return 2
        anchor = resolution.target.identity.canonical
    else:
        anchor = args.session
    current_id = (
        resolution.target.identity.canonical
        if resolution is not None
        and resolution.kind is TargetResolutionKind.RESOLVED
        and resolution.target is not None
        else None
    )
    connection = open_database(_database_for(args, project))
    try:
        repository = TangRepository(connection)
        try:
            canonical_anchor = repository.resolve_session_token(anchor, project.key)
            graph = GraphService(repository).component(
                canonical_anchor, current_id=current_id
            )
        except ValueError as error:
            print(f"error[unknown-session]: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()
    width = args.width or shutil.get_terminal_size((100, 24)).columns
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    ascii_only = args.ascii_only or not _supports_unicode(sys.stdout)
    print(
        render_multiverse(
            graph,
            width=max(width, 40),
            color=color,
            ascii_only=ascii_only,
        ),
        end="",
    )
    return 0


def _supports_unicode(stream: object) -> bool:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "╭──▶★".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch Tang's scriptable commands, or show top-level help."""
    arguments = tuple(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "connect":
        print(
            "error[unknown-command]: connect is not a Tang command. "
            "Use tang link after selecting source session(s) and explicitly "
            "confirming a target; run tang link --help for the safe continuation flow.",
            file=sys.stderr,
        )
        return 2
    parser = build_parser()
    args = parser.parse_args(arguments)
    try:
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
        if args.command == "graph":
            return _run_graph(args)
        if args.command == "demo":
            from tang.demo import run_demo

            return run_demo(
                width=max(args.width, 40),
                color=sys.stdout.isatty() and "NO_COLOR" not in os.environ,
                ascii_only=args.ascii_only or not _supports_unicode(sys.stdout),
            )
    except DatabaseOpenError as error:
        print(f"error[storage-unavailable]: {error}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0
