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

from rich import box
from rich.console import Console
from rich.table import Table
from rich.text import Text

from tang import __version__
from tang.adapter_registry import configured_adapters
from tang.adapters import OpenCodeAdapter, SessionHealth, SessionIdentity
from tang.continuity_brief import build_continuity_brief
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
from tang.health import health_label, health_style
from tang.indexing import IndexResult, ProjectIndexer
from tang.project import ProjectIdentity, resolve_project
from tang.redaction import (
    ContentKind,
    DEFAULT_REDACTOR,
    RedactionSeam,
    required_redaction,
)
from tang.render import STEEL, TEAL, render_multiverse
from tang.repository import TangRepository
from tang.resume import ResumeError, ResumeService
from tang.skill_install import install_codex_skill, install_opencode_skill
from tang.storage import DatabaseOpenError, open_database, project_data_path
from tang.timeutil import rfc3339
from tang.target import (
    HostTargetContextError,
    OpenCodeTargetContext,
    TargetCandidate,
    TargetResolutionCode,
    TargetResolutionKind,
    resolve_current_target,
    resolve_opencode_target,
)


def build_parser() -> argparse.ArgumentParser:
    """Build Tang's top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="tang",
        description=(
            "Continue coding-agent work across harnesses with source-cited context."
        ),
        epilog=(
            "Primary workflow: index, browse, context, link, graph, and resume. "
            "Recovery flow: index; browse or search; build context; explicitly "
            "confirm a target with link; then graph the result. If you looked for "
            "connect, use tang link --help."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"tang-multiverse {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")
    index = subparsers.add_parser("index", help="index the current project")
    index.add_argument("--json", action="store_true", dest="as_json")
    index.add_argument("--database", type=Path)
    index.add_argument("--cwd", type=Path, default=Path.cwd())
    index.add_argument("--codex-home", type=Path)
    index.add_argument("--grok-home", type=Path)
    index.add_argument("--opencode-executable", type=Path)
    browse = subparsers.add_parser("browse", help="list current-project sessions")
    _add_discovery_arguments(browse)
    search = subparsers.add_parser("search", help="search current-project capsules")
    search.add_argument(
        "query",
        help="FTS5 query; simple keywords or quoted phrases are recommended",
    )
    _add_discovery_arguments(search)
    search.add_argument(
        "--limit",
        type=_search_limit,
        default=20,
        help="maximum search results to return (1-100; default: 20)",
    )
    context = subparsers.add_parser("context", help="build a cited Context Pack")
    context.add_argument(
        "sessions",
        nargs="*",
        help=(
            "project handles or exact IDs from JSON; use all or a positive "
            "depth for confirmed predecessor context"
        ),
    )
    context.add_argument(
        "--for",
        dest="anchor",
        help="confirmed target handle for all/depth predecessor context",
    )
    context.add_argument(
        "--current-native-id",
        help="exact current Codex native ID supplied privately by a host",
    )
    context.add_argument("--json", action="store_true", dest="as_json")
    context.add_argument("--database", type=Path)
    context.add_argument("--cwd", type=Path, default=Path.cwd())
    context.add_argument("--codex-home", type=Path)
    context.add_argument("--grok-home", type=Path)
    context.add_argument("--opencode-executable", type=Path)
    resume = subparsers.add_parser(
        "resume",
        help="open an indexed session in its native harness",
        description=(
            "Privately resolve one current-project Tang handle and open the "
            "corresponding Codex or OpenCode session. This does not build "
            "context, create links, or modify native history."
        ),
    )
    resume.add_argument(
        "session",
        help="displayed Tang handle for a Codex or OpenCode session",
    )
    resume.add_argument("--database", type=Path)
    resume.add_argument("--cwd", type=Path, default=Path.cwd())
    resume.add_argument("--codex-executable", type=Path)
    resume.add_argument("--opencode-executable", type=Path)
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
    graph.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="terminal color policy (default: auto)",
    )
    graph_layout = graph.add_mutually_exclusive_group()
    graph_layout.add_argument("--ascii", action="store_true", dest="ascii_only")
    graph_layout.add_argument(
        "--unicode",
        action="store_true",
        dest="force_unicode",
        help="force the woven Unicode graph when capturing redirected output",
    )
    demo = subparsers.add_parser("demo", help="run the isolated synthetic demo")
    demo.add_argument("--width", type=int, default=120)
    demo.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="terminal color policy (default: auto)",
    )
    demo_layout = demo.add_mutually_exclusive_group()
    demo_layout.add_argument(
        "--ascii",
        action="store_true",
        dest="ascii_only",
        help="force the narrow ASCII graph fallback",
    )
    demo_layout.add_argument(
        "--unicode",
        action="store_true",
        dest="force_unicode",
        help="force the woven Unicode graph when capturing redirected output",
    )
    doctor = subparsers.add_parser("doctor", help="check Tang readiness")
    doctor.add_argument("--json", action="store_true", dest="as_json")
    doctor.add_argument("--database", type=Path)
    doctor.add_argument("--cwd", type=Path, default=Path.cwd())
    doctor.add_argument("--codex-home", type=Path)
    doctor.add_argument("--grok-home", type=Path)
    doctor.add_argument("--opencode-executable", type=Path)
    doctor.add_argument(
        "--require-opencode",
        action="store_true",
        help="treat OpenCode readiness as required rather than optional",
    )
    continuity = subparsers.add_parser(
        "continuity",
        help="show git and indexed session-start signals",
    )
    continuity.add_argument("--json", action="store_true", dest="as_json")
    continuity.add_argument("--database", type=Path)
    continuity.add_argument("--cwd", type=Path, default=Path.cwd())
    skill = subparsers.add_parser("skill", help="manage harness skills")
    skill_subparsers = skill.add_subparsers(dest="skill_command")
    install = skill_subparsers.add_parser("install", help="install a harness skill")
    install.add_argument("harness", choices=("codex", "opencode"))
    install.add_argument("--codex-home", type=Path)
    install.add_argument("--project-root", type=Path, default=Path.cwd())
    install.add_argument("--force", action="store_true")
    opencode_target = skill_subparsers.add_parser(
        "opencode-target",
        help="resolve an active OpenCode target for the installed skill",
        description=(
            "Internal machine bridge for the installed OpenCode skill; "
            "do not invoke it manually or supply native session IDs in a shell."
        ),
    )
    opencode_target.add_argument("--json", action="store_true", dest="as_json")
    opencode_target.add_argument("--database", type=Path)
    opencode_target.add_argument("--cwd", type=Path, required=True)
    opencode_target.add_argument("--worktree", type=Path, required=True)
    opencode_target.add_argument(
        "--session-id",
        required=True,
        help="native host context supplied only by the installed OpenCode tool",
    )
    opencode_target.add_argument("--opencode-executable", type=Path)
    return parser


def _add_discovery_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--harness", choices=("codex", "grok", "opencode"))
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


def _search_limit(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("search limit must be an integer") from error
    if not 1 <= parsed <= 100:
        raise argparse.ArgumentTypeError("search limit must be between 1 and 100")
    return parsed


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
        "refreshed": result.refreshed,
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


def _required_database_for(
    args: argparse.Namespace, project: ProjectIdentity
) -> Path | None:
    """Return existing derived storage or emit one stable initialization error."""

    database = _database_for(args, project)
    if database.is_file():
        return database
    print(
        "error[index-required]: Tang has no index for this project; run tang index first.",
        file=sys.stderr,
    )
    return None


def _indexed_codex_candidates(
    repository: TangRepository, project: ProjectIdentity
) -> tuple[TargetCandidate, ...]:
    """Build current-target candidates from the authoritative project index."""

    return tuple(
        TargetCandidate.from_stored(session)
        for session in repository.sessions_for_project(project.key)
        if session.source.identity.adapter == "codex"
    )


def _show_current_target_refusal(code: TargetResolutionCode) -> None:
    if code in {
        TargetResolutionCode.NO_ELIGIBLE_TARGET,
        TargetResolutionCode.HOST_ID_UNKNOWN,
    }:
        print(
            "error[index-required]: The current Codex session is not indexed; "
            "run tang index and retry.",
            file=sys.stderr,
        )
        return
    print(
        "error[target-unconfirmed]: Choose an explicit target or supply the "
        "host's current native session ID.",
        file=sys.stderr,
    )


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
            configured_adapters(
                args.cwd,
                codex_home=args.codex_home,
                grok_home=args.grok_home,
                opencode_executable=args.opencode_executable,
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
            f"refreshed {result.refreshed}; "
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
        "session_header": {
            "effort": item.effort,
            "model_id": item.model_id,
            "model_provider": item.model_provider,
            "title_origin": item.title_origin,
            "visible_text_bytes": item.visible_text_bytes,
            "visible_turn_count": item.visible_turn_count,
        },
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
    width = max(shutil.get_terminal_size((100, 24)).columns, 40)
    ascii_only = not _supports_unicode(sys.stdout)
    color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
    console = Console(
        file=sys.stdout,
        width=width,
        force_terminal=color,
        color_system="truecolor" if color else None,
        legacy_windows=False,
    )
    table = Table(
        box=box.ASCII if ascii_only else box.SIMPLE_HEAD,
        expand=True,
        padding=(0, 1),
        show_edge=False,
    )
    table.add_column("SELECT", style=f"bold {STEEL}", no_wrap=True)
    table.add_column("ID", style=f"bold {TEAL}", no_wrap=True)
    wide = width >= 88
    table.add_column("SESSION", ratio=3, overflow="fold")
    if wide:
        table.add_column("HARNESS", no_wrap=True)
        table.add_column("UPDATED (UTC)", no_wrap=True)
        table.add_column("HEALTH", no_wrap=True)
    for choice in page.choices:
        item = choice.item
        capability_labels = {
            "native-reread": "native reread",
            "visible-user-agent-turns": "visible turns",
        }
        capability = " · ".join(
            capability_labels.get(value, value.replace("-", " "))
            for value in item.capabilities
        ) or "none"
        display_limit = 52 if width >= 120 else 34
        display_name = _truncate_discovery_text(
            item.display_name, display_limit, ascii_only=ascii_only
        )
        session = Text(display_name, style="bold")
        header_label = _header_label(item)
        if header_label:
            session.append(f"\n{header_label}", style="dim")
        session.append(f"\n{capability}", style="dim")
        snippet = " ".join(item.snippet.split())
        if snippet:
            snippet_limit = 96 if width >= 120 else 64
            session.append(
                "\n"
                + _truncate_discovery_text(
                    snippet, snippet_limit, ascii_only=ascii_only
                ),
                style="dim",
            )
        updated = item.updated_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        if wide:
            table.add_row(
                f"[{choice.number}]",
                item.handle,
                session,
                item.harness,
                updated,
                Text(health_label(item.health), style=health_style(item.health)),
            )
        else:
            session.append(
                f"\n{item.harness} · {updated} · ",
                style="dim",
            )
            session.append(health_label(item.health), style=health_style(item.health))
            table.add_row(f"[{choice.number}]", item.handle, session)
    console.print(table)
    print(f"Page {page.number} of {page.page_count} ({page.result_count} results).")
    if page.has_next:
        print(f"Use --page {page.number + 1} for the next page.")
    elif page.has_previous:
        print(f"Use --page {page.number - 1} for the previous page.")


def _truncate_discovery_text(value: str, limit: int, *, ascii_only: bool) -> str:
    """Keep compact human previews readable in Unicode and ASCII terminals."""

    if len(value) <= limit:
        return value
    suffix = "..." if ascii_only else "…"
    return f"{value[: limit - len(suffix)].rstrip()}{suffix}"


def _header_label(item: DiscoveryItem) -> str:
    """Compact, non-sensitive session facts for the human discovery table."""

    parts: list[str] = []
    model = " / ".join(
        value for value in (item.model_provider, item.model_id) if value
    )
    if model:
        parts.append(model)
    if item.effort:
        parts.append(f"effort {item.effort}")
    if item.visible_turn_count is not None:
        parts.append(f"{item.visible_turn_count} turns")
    if item.visible_text_bytes is not None:
        parts.append(f"~{item.visible_text_bytes / 1024:.1f} KiB visible")
    if item.title_origin:
        parts.append(item.title_origin.replace("_", " "))
    return " · ".join(parts)


def _run_discovery(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    database = _required_database_for(args, project)
    if database is None:
        return 2
    connection = open_database(database)
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
                    limit=args.limit,
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
        if args.command == "search" and (
            page is not None and page.result_count == 0
            or page is None and not items
        ):
            document["hints"] = [
                "Try different keywords or a quoted phrase from the session you remember.",
                "Run `tang browse --json --page 1` to list recent sessions by update time.",
                "Run `tang index --json` if native session history changed since the last index.",
            ]
        print(json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    else:
        if page is None:
            raise RuntimeError("human discovery output requires a result page")
        if args.command == "search" and page.result_count == 0:
            print("No matching sessions. Try browse for recency-ordered results:")
            print("  tang browse --page 1")
        _show_discovery_page(page)
    return 0


def _run_context(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    database = _required_database_for(args, project)
    if database is None:
        return 2
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        service = ContextPackService(
            repository,
            configured_adapters(
                args.cwd,
                codex_home=args.codex_home,
                grok_home=args.grok_home,
                opencode_executable=args.opencode_executable,
            ),
        )
        try:
            source_ids = _context_source_ids(args, repository, project)
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


def _context_source_ids(
    args: argparse.Namespace, repository: TangRepository, project: ProjectIdentity
) -> tuple[str, ...]:
    """Resolve explicit sources or confirmed predecessor evidence for context."""

    sessions = tuple(args.sessions)
    history_token: str | None = None
    if len(sessions) == 1 and sessions[0].lower() == "all":
        history_token = "all"
    elif len(sessions) == 1 and sessions[0].isdigit():
        depth = int(sessions[0])
        if depth < 1:
            raise ContextGenerationError("ancestor depth must be at least 1")
        history_token = sessions[0]

    if sessions and history_token is None:
        if args.anchor is not None or args.current_native_id is not None:
            raise ContextGenerationError(
                "--for and --current-native-id apply only to all/depth predecessor context"
            )
        return tuple(
            repository.resolve_session_token(token, project.key) for token in sessions
        )

    anchor_id = _context_anchor(args, repository, project)
    max_hops = None if history_token in (None, "all") else int(history_token)
    source_ids = repository.confirmed_predecessors(
        anchor_id, project.key, max_hops=max_hops
    )
    if not source_ids:
        raise ContextGenerationError(
            "the confirmed target has no predecessor sessions; pass explicit handles "
            "or record a confirmed link first"
        )
    return source_ids


def _context_anchor(
    args: argparse.Namespace, repository: TangRepository, project: ProjectIdentity
) -> str:
    if args.anchor is not None:
        if args.current_native_id is not None:
            raise ContextGenerationError("--for cannot be combined with --current-native-id")
        return repository.resolve_session_token(args.anchor, project.key)

    if args.current_native_id is not None:
        resolution = resolve_current_target(
            _indexed_codex_candidates(repository, project),
            project,
            current_native_id=args.current_native_id,
        )
        if resolution.kind is TargetResolutionKind.RESOLVED and resolution.target:
            return resolution.target.identity.canonical
        raise ContextGenerationError(
            "the supplied current session could not be resolved; run tang index first"
        )

    latest_targets = _latest_confirmed_graph_targets(repository, project.key)
    if len(latest_targets) == 1:
        return latest_targets[0]
    if len(latest_targets) > 1:
        raise ContextGenerationError(
            "multiple targets share the latest confirmation; pass context all --for HANDLE"
        )
    raise ContextGenerationError(
        "no confirmed target is available; pass explicit handles or record a confirmed link first"
    )


def _run_resume(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    database = _required_database_for(args, project)
    if database is None:
        return 2
    launch_directory = args.cwd.expanduser().resolve(strict=True)
    connection = open_database(database)
    try:
        try:
            return ResumeService(TangRepository(connection)).resume(
                args.session,
                project,
                launch_directory,
                codex_executable=args.codex_executable,
                opencode_executable=args.opencode_executable,
            )
        except ResumeError as error:
            print(f"error[{error.code}]: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()


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


def _run_continuity(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    database = _required_database_for(args, project)
    if database is None:
        return 2
    connection = open_database(database)
    try:
        brief = build_continuity_brief(TangRepository(connection), project)
    finally:
        connection.close()
    if args.as_json:
        print(
            json.dumps(
                brief.as_dict(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(f"Project {brief.project_key}")
        if brief.git_available:
            print("Recent git commits:")
            for line in brief.git_log:
                print(f"  {line}")
            if brief.git_status:
                print("Working tree:")
                for line in brief.git_status:
                    print(f"  {line}")
        else:
            print("Git history unavailable; use indexed session handles only.")
        if brief.recent_handles:
            print("Recent indexed handles:", ", ".join(brief.recent_handles))
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    checks = run_doctor(
        _database_for(args, project),
        codex_home=args.codex_home,
        grok_home=args.grok_home,
        opencode_executable=args.opencode_executable,
        project_dir=args.cwd,
        require_opencode=(
            args.require_opencode or args.opencode_executable is not None
        ),
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


def _run_opencode_target(args: argparse.Namespace) -> int:
    """Resolve one host-supplied OpenCode target without exposing its native ID."""
    try:
        project = resolve_project(args.cwd)
        adapter = OpenCodeAdapter(args.cwd, args.opencode_executable or "opencode")
        scan = adapter.scan(None)
        observed = next(
            (
                record
                for record in scan.records
                if record.identity.native_id == args.session_id
            ),
            None,
        )
        if observed is None:
            code = (
                scan.warnings[0].code
                if scan.warnings and not scan.records
                else "host-id-unknown"
            )
            document = {
                "schema_version": 1,
                "kind": "unavailable",
                "code": code,
            }
            print(json.dumps(document, sort_keys=True, separators=(",", ":")))
            return 2
        context = OpenCodeTargetContext.from_host(
            session_id=args.session_id,
            directory=args.cwd,
            worktree=args.worktree,
            observed_source=observed,
        )
        database = _database_for(args, project)
        if not database.is_file():
            document = {
                "schema_version": 1,
                "kind": "unavailable",
                "code": "index-required",
            }
            print(json.dumps(document, sort_keys=True, separators=(",", ":")))
            return 2
        connection = open_database(database)
        try:
            repository = TangRepository(connection)
            stored_target = repository.get_session(observed.identity.canonical)
            if (
                stored_target is not None
                and stored_target.project_key == project.key
            ):
                # The active session advances while this workflow is running.
                # Refresh only its derived identity metadata from the exact,
                # freshly observed host record; no transcript content is read.
                with repository.transaction():
                    repository.upsert_session(
                        observed, project.key, datetime.now(timezone.utc)
                    )
            resolution = resolve_opencode_target(
                repository.sessions_for_project(project.key), project, context
            )
            document = resolution.as_document()
            if (
                resolution.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
                and len(resolution.candidates) == 1
            ):
                try:
                    target_handle = repository.handle_for_source_id(
                        resolution.candidates[0].identity.canonical
                    )
                except ValueError:
                    document = {
                        "schema_version": 1,
                        "kind": "unavailable",
                        "code": "target-handle-missing",
                    }
                else:
                    document["target_handle"] = target_handle
        finally:
            connection.close()
    except HostTargetContextError as error:
        document = {
            "schema_version": 1,
            "kind": "unavailable",
            "code": error.code,
        }
    except (ValueError, OSError):
        document = {
            "schema_version": 1,
            "kind": "unavailable",
            "code": "host-context-invalid",
        }
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))
    return 0 if document.get("kind") == "confirmation_required" else 2


def _run_skill(args: argparse.Namespace) -> int:
    if args.skill_command == "opencode-target":
        return _run_opencode_target(args)
    if args.skill_command != "install":
        print("error: skill requires the install subcommand", file=sys.stderr)
        return 2
    try:
        result = (
            install_codex_skill(args.codex_home, force=args.force)
            if args.harness == "codex"
            else install_opencode_skill(args.project_root, force=args.force)
        )
    except (FileExistsError, FileNotFoundError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(result.message)
    return 0


def _link_document(
    result: LinkResult,
    source_handles: tuple[str, ...],
    target_handle: str,
) -> dict[str, object]:
    return {
        "existing": result.existing,
        "inserted": result.inserted,
        "schema_version": 1,
        "source_handles": list(source_handles),
        "source_ids": list(result.source_ids),
        "target_handle": target_handle,
        "target_id": result.target_id,
    }


def _run_link(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    database = _required_database_for(args, project)
    if database is None:
        return 2
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        service = ContinuationService(repository)
        try:
            source_ids = tuple(
                repository.resolve_session_token(token, project.key)
                for token in args.source_ids
            )
            if args.current:
                excluded = frozenset(
                    SessionIdentity.from_canonical(source_id)
                    for source_id in source_ids
                )
                resolution = resolve_current_target(
                    _indexed_codex_candidates(repository, project),
                    project,
                    current_native_id=args.current_native_id,
                    exclude=excluded,
                )
                if resolution.kind is not TargetResolutionKind.RESOLVED:
                    _show_current_target_refusal(resolution.code)
                    return 2
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
        print(
            json.dumps(
                _link_document(result, source_handles, target_handle),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    else:
        print(
            f"Linked {', '.join(source_handles)} to {target_handle}; "
            f"inserted {result.inserted}, existing {result.existing}."
        )
    return 0


def _run_graph(args: argparse.Namespace) -> int:
    project = resolve_project(args.cwd)
    database = _required_database_for(args, project)
    if database is None:
        return 2
    connection = open_database(database)
    resolution = None
    try:
        repository = TangRepository(connection)
        if args.session is None or args.current_native_id is not None:
            resolution = resolve_current_target(
                _indexed_codex_candidates(repository, project),
                project,
                current_native_id=args.current_native_id,
            )
        if args.session is None:
            if resolution is None:
                raise RuntimeError("graph target resolution was not attempted")
            if resolution.kind is TargetResolutionKind.RESOLVED and resolution.target:
                anchor = resolution.target.identity.canonical
            elif args.current_native_id is None:
                latest_targets = _latest_confirmed_graph_targets(repository, project.key)
                if len(latest_targets) == 1:
                    # A confirmed edge, unlike native-session recency, is durable
                    # user intent. This is a display focus only, not a claim that
                    # its target is the currently active native session.
                    anchor = latest_targets[0]
                elif len(latest_targets) > 1:
                    print(
                        "error[graph-target-unconfirmed]: Multiple targets share "
                        "the latest confirmation; pass a session handle.",
                        file=sys.stderr,
                    )
                    return 2
                else:
                    _show_current_target_refusal(resolution.code)
                    return 2
            else:
                _show_current_target_refusal(resolution.code)
                return 2
        else:
            anchor = args.session
        current_id = (
            resolution.target.identity.canonical
            if resolution is not None
            and resolution.kind is TargetResolutionKind.RESOLVED
            and resolution.target is not None
            else None
        )
        try:
            canonical_anchor = repository.resolve_session_token(anchor, project.key)
            anchor_session = repository.get_session(canonical_anchor)
            if anchor_session is None or anchor_session.project_key != project.key:
                raise ValueError("session is not indexed in the current project")
            graph = GraphService(repository).component(
                canonical_anchor, current_id=current_id
            )
        except ValueError as error:
            print(f"error[unknown-session]: {error}", file=sys.stderr)
            return 2
    finally:
        connection.close()
    width = args.width or shutil.get_terminal_size((100, 24)).columns
    color = _color_enabled(args.color, sys.stdout)
    ascii_only = args.ascii_only or (
        not args.force_unicode and not _supports_unicode(sys.stdout)
    )
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


def _latest_confirmed_graph_targets(
    repository: TangRepository, project_key: str
) -> tuple[str, ...]:
    """Return the deterministic target set from one latest confirmation event."""

    edges = repository.continuations_for_project(project_key)
    if not edges:
        return ()
    latest = max(edge.confirmed_at for edge in edges)
    return tuple(sorted({edge.target_id for edge in edges if edge.confirmed_at == latest}))


def _supports_unicode(stream: object) -> bool:
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        "╭──▶★".encode(encoding)
    except (LookupError, UnicodeEncodeError):
        return False
    return True


def _color_enabled(policy: str, stream: object) -> bool:
    if policy == "always":
        return True
    if policy == "never":
        return False
    return bool(getattr(stream, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ


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
        if args.command == "resume":
            return _run_resume(args)
        if args.command == "purge":
            return _run_purge(args)
        if args.command == "doctor":
            return _run_doctor(args)
        if args.command == "continuity":
            return _run_continuity(args)
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
                color=_color_enabled(args.color, sys.stdout),
                ascii_only=args.ascii_only
                or (
                    not args.force_unicode
                    and not _supports_unicode(sys.stdout)
                ),
            )
    except DatabaseOpenError as error:
        print(f"error[storage-unavailable]: {error}", file=sys.stderr)
        return 2
    parser.print_help()
    return 0
