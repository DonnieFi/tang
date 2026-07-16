#!/usr/bin/env python3
"""Emit privacy-safe evidence for Tang's supported OpenCode contract."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = 1
SUPPORTED_OPENCODE_VERSION = "1.17.20"
SUPPORTED_SYSTEM = "Linux"
SUPPORTED_MACHINE = "x86_64"
SUPPORTED_PROVIDERS = frozenset({"openai", "xai"})
SUPPORTED_ROLES = frozenset({"user", "assistant"})
SUPPORTED_PART_TYPES = frozenset(
    {
        "agent",
        "compaction",
        "file",
        "patch",
        "reasoning",
        "retry",
        "snapshot",
        "step-finish",
        "step-start",
        "subtask",
        "text",
        "tool",
    }
)
CATALOG_LIMIT = 100
DEFAULT_COMMAND_TIMEOUT_SECONDS = 30.0
DEFAULT_OVERALL_TIMEOUT_SECONDS = 120.0
ERROR_CODES = frozenset(
    {
        "executable_missing",
        "execution_failed",
        "internal_failure",
        "version_failed",
        "version_invalid",
        "version_timeout",
        "session_list_failed",
        "session_list_invalid_json",
        "session_list_invalid_shape",
        "session_list_timeout",
        "session_export_failed",
        "session_export_invalid_json",
        "session_export_invalid_shape",
        "session_export_timeout",
    }
)


class ProbeFailure(RuntimeError):
    """OpenCode did not satisfy the evidence contract."""

    def __init__(self, code: str) -> None:
        if code not in ERROR_CODES:
            raise ValueError(f"unsupported safe probe error code: {code}")
        self.code = code
        super().__init__(code)


def _nonnegative_integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _nonblank_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _fixed_class(value: object, allowed: frozenset[str]) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return "other"


def _json_document(value: str, error_code: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ProbeFailure(error_code) from error


def _run(
    executable: str,
    arguments: Sequence[str],
    project: Path,
    *,
    operation: str,
    command_timeout: float,
    deadline: float,
) -> str:
    environment = {
        **os.environ,
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
    }
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ProbeFailure(f"{operation}_timeout")
    try:
        result = subprocess.run(
            [executable, *arguments],
            cwd=project,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=min(command_timeout, remaining),
        )
    except FileNotFoundError as error:
        raise ProbeFailure("executable_missing") from error
    except subprocess.TimeoutExpired as error:
        raise ProbeFailure(f"{operation}_timeout") from error
    except OSError as error:
        raise ProbeFailure("execution_failed") from error
    if result.returncode != 0:
        raise ProbeFailure(f"{operation}_failed")
    return result.stdout


def _provider_class(message_info: dict[str, Any]) -> str:
    provider = message_info.get("providerID")
    if not isinstance(provider, str):
        model = message_info.get("model")
        provider = model.get("providerID") if isinstance(model, dict) else None
    return _fixed_class(provider, SUPPORTED_PROVIDERS)


def _session_evidence(
    listed: dict[str, Any] | None,
    exported: dict[str, Any],
    project: Path,
    *,
    expected_session_id: str,
    current_session: bool,
    invoking_message_id: str | None,
    expected_provider: str | None,
) -> dict[str, Any]:
    info = exported.get("info")
    messages = exported.get("messages")
    if not isinstance(info, dict) or not isinstance(messages, list):
        raise ProbeFailure("session_export_invalid_shape")

    created_times: list[int] = []
    ordering_inputs_complete = True
    metadata_shape_valid = True
    role_classes: set[str] = set()
    provider_classes: set[str] = set()
    visible_text_roles: set[str] = set()
    visible_text_parts = 0
    excluded_part_classes: set[str] = set()
    invoking_messages = 0
    invoking_provider_matches = False
    for message in messages:
        if not isinstance(message, dict):
            raise ProbeFailure("session_export_invalid_shape")
        message_info = message.get("info")
        parts = message.get("parts")
        if not isinstance(message_info, dict) or not isinstance(parts, list):
            raise ProbeFailure("session_export_invalid_shape")
        role = _fixed_class(message_info.get("role"), SUPPORTED_ROLES)
        role_classes.add(role)
        if role == "other":
            metadata_shape_valid = False
        provider_class = _provider_class(message_info)
        provider_classes.add(provider_class)
        time = message_info.get("time")
        if isinstance(time, dict) and _nonnegative_integer(time.get("created")):
            created_times.append(time["created"])
        else:
            ordering_inputs_complete = False
        message_id = message_info.get("id")
        if not _nonblank_string(message_id):
            ordering_inputs_complete = False
        if invoking_message_id is not None and message_id == invoking_message_id:
            invoking_messages += 1
            invoking_provider_matches = (
                role == "assistant" and provider_class == expected_provider
            )
        for part in parts:
            if not isinstance(part, dict):
                raise ProbeFailure("session_export_invalid_shape")
            part_type = _fixed_class(part.get("type"), SUPPORTED_PART_TYPES)
            if part_type == "other":
                metadata_shape_valid = False
            if (
                role in {"user", "assistant"}
                and part_type == "text"
                and isinstance(part.get("text"), str)
                and bool(part["text"].strip())
                and not part.get("ignored", False)
            ):
                visible_text_parts += 1
                visible_text_roles.add(role)
            elif part_type not in {"step-start", "step-finish"}:
                excluded_part_classes.add(part_type)

    directory = listed.get("directory") if listed is not None else None
    exported_directory = info.get("directory")
    canonical_project = project.resolve()
    listed_project_match = listed is None or (
        isinstance(directory, str) and Path(directory).resolve() == canonical_project
    )
    export_project_match = (
        isinstance(exported_directory, str)
        and Path(exported_directory).resolve() == canonical_project
    )
    listed_updated = listed.get("updated") if listed is not None else None
    exported_time = info.get("time")
    source_change_present = (
        _nonnegative_integer(listed_updated)
        if listed is not None
        else isinstance(exported_time, dict)
        and _nonnegative_integer(exported_time.get("updated"))
    )
    return {
        "catalog_listed": listed is not None,
        "chronological": ordering_inputs_complete
        and created_times == sorted(created_times),
        "current_session": current_session,
        "excluded_part_classes": sorted(excluded_part_classes),
        "invoking_message_matches_once": (
            None if invoking_message_id is None else invoking_messages == 1
        ),
        "invoking_message_provider_matches": (
            None if invoking_message_id is None else invoking_provider_matches
        ),
        "message_count": len(messages),
        "metadata_shape_valid": metadata_shape_valid,
        "ordering_inputs_complete": ordering_inputs_complete,
        "ordering_strategy": "created_milliseconds_then_message_id",
        "project_match": listed_project_match and export_project_match,
        "provider_classes": sorted(provider_classes),
        "role_classes": sorted(role_classes),
        "stable_identity": info.get("id") == expected_session_id,
        "title_present": _nonblank_string(
            listed.get("title") if listed is not None else info.get("title")
        ),
        "updated_milliseconds_present": source_change_present,
        "visible_text_parts": visible_text_parts,
        "visible_text_roles": sorted(visible_text_roles),
    }


def probe(
    executable: str,
    project: Path,
    *,
    max_sessions: int,
    current_session_id: str | None,
    invoking_message_id: str | None,
    expected_provider: str | None,
    expected_version: str,
    command_timeout: float,
    overall_timeout: float,
    system: str | None = None,
    machine: str | None = None,
) -> dict[str, Any]:
    project = project.resolve()
    system = platform.system() if system is None else system
    machine = platform.machine() if machine is None else machine
    deadline = time.monotonic() + overall_timeout
    version = _run(
        executable,
        ("--version",),
        project,
        operation="version",
        command_timeout=command_timeout,
        deadline=deadline,
    ).strip()
    if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version) is None:
        raise ProbeFailure("version_invalid")
    raw_list = _run(
        executable,
        (
            "--pure",
            "session",
            "list",
            "--format",
            "json",
            "--max-count",
            str(CATALOG_LIMIT),
        ),
        project,
        operation="session_list",
        command_timeout=command_timeout,
        deadline=deadline,
    )
    listed = (
        []
        if not raw_list.strip()
        else _json_document(raw_list, "session_list_invalid_json")
    )
    if not isinstance(listed, list):
        raise ProbeFailure("session_list_invalid_shape")

    project_items: list[dict[str, Any]] = []
    current_item: dict[str, Any] | None = None
    foreign_catalog_items_excluded = False
    for item in listed:
        if not isinstance(item, dict):
            raise ProbeFailure("session_list_invalid_shape")
        source_id = item.get("id")
        directory = item.get("directory")
        created = item.get("created")
        updated = item.get("updated")
        if (
            not _nonblank_string(source_id)
            or not isinstance(directory, str)
            or not _nonnegative_integer(created)
            or not _nonnegative_integer(updated)
        ):
            raise ProbeFailure("session_list_invalid_shape")
        if Path(directory).resolve() != project:
            foreign_catalog_items_excluded = True
            continue
        project_items.append(item)
        if current_session_id is not None and source_id == current_session_id:
            current_item = item

    project_items.sort(key=lambda item: (-item["updated"], item["id"]))

    selected_items = project_items[:max_sessions]
    if current_item is not None and current_item not in selected_items:
        if max_sessions == 1:
            selected_items = [current_item]
        else:
            selected_items = [current_item, *selected_items[: max_sessions - 1]]

    items_to_export: list[tuple[str, dict[str, Any] | None]] = [
        (item["id"], item) for item in selected_items
    ]
    if current_session_id is not None and current_item is None:
        items_to_export.insert(0, (current_session_id, None))

    sessions: list[dict[str, Any]] = []
    for source_id, item in items_to_export:
        raw_export = _run(
            executable,
            ("--pure", "export", source_id),
            project,
            operation="session_export",
            command_timeout=command_timeout,
            deadline=deadline,
        )
        exported = _json_document(raw_export, "session_export_invalid_json")
        if not isinstance(exported, dict):
            raise ProbeFailure("session_export_invalid_shape")
        sessions.append(
            _session_evidence(
                item,
                exported,
                project,
                expected_session_id=source_id,
                current_session=current_session_id == source_id,
                invoking_message_id=(
                    invoking_message_id if current_session_id == source_id else None
                ),
                expected_provider=(
                    expected_provider if current_session_id == source_id else None
                ),
            )
        )

    current_evidence = next(
        (session for session in sessions if session["current_session"]), None
    )
    current_match = (
        None
        if current_session_id is None
        else current_evidence is not None and current_evidence["stable_identity"]
    )
    current_catalog_listed = (
        None if current_session_id is None else current_item is not None
    )
    current_visible_roles = {
        role
        for session in sessions
        if session["current_session"]
        for role in session["visible_text_roles"]
    }
    current_visible_text = (
        None
        if current_session_id is None
        else {"user", "assistant"}.issubset(current_visible_roles)
    )
    invoking_message_matches = (
        None
        if current_evidence is None
        else current_evidence["invoking_message_matches_once"]
    )
    invoking_provider_matches = (
        None
        if current_evidence is None
        else current_evidence["invoking_message_provider_matches"]
    )
    target_evidence_required = current_session_id is not None
    catalog_within_boundary = len(listed) < CATALOG_LIMIT
    version_supported = (
        expected_version == SUPPORTED_OPENCODE_VERSION
        and version == SUPPORTED_OPENCODE_VERSION
    )
    checks = {
        "all_chronological": all(item["chronological"] for item in sessions),
        "all_metadata_shapes_valid": all(
            item["metadata_shape_valid"] for item in sessions
        ),
        "all_ordering_inputs_complete": all(
            item["ordering_inputs_complete"] for item in sessions
        ),
        "all_project_scoped": all(item["project_match"] for item in sessions),
        "all_stable_identities": all(item["stable_identity"] for item in sessions),
        "all_updated_milliseconds_present": all(
            item["updated_milliseconds_present"] for item in sessions
        ),
        "catalog_latest_root_limit": CATALOG_LIMIT,
        "catalog_foreign_items_excluded": foreign_catalog_items_excluded,
        "catalog_project_scoped": all(
            Path(item["directory"]).resolve() == project for item in project_items
        ),
        "catalog_within_supported_boundary": catalog_within_boundary,
        "current_session_catalog_listed": current_catalog_listed,
        "current_session_matches": current_match,
        "current_session_visible_user_and_assistant_text": current_visible_text,
        "invoking_message_matches_once": invoking_message_matches,
        "invoking_message_provider_matches": invoking_provider_matches,
        "platform_supported": system == SUPPORTED_SYSTEM
        and machine == SUPPORTED_MACHINE,
        "session_count_positive": bool(sessions),
        "version_supported": version_supported,
    }
    passed = (
        checks["all_chronological"]
        and checks["all_metadata_shapes_valid"]
        and checks["all_ordering_inputs_complete"]
        and checks["all_project_scoped"]
        and checks["all_stable_identities"]
        and checks["all_updated_milliseconds_present"]
        and checks["catalog_project_scoped"]
        and checks["catalog_within_supported_boundary"]
        and checks["session_count_positive"]
        and checks["platform_supported"]
        and checks["version_supported"]
        and (
            not target_evidence_required
            or (
                current_match is True
                and current_visible_text is True
                and invoking_message_matches is True
                and invoking_provider_matches is True
            )
        )
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result": "pass" if passed else "fail",
        "opencode_version": version if version_supported else "unsupported",
        "platform": {
            "machine": machine,
            "python": platform.python_version(),
            "system": system,
        },
        "checks": checks,
        "expected_provider": expected_provider,
        "expected_version": expected_version,
        "sessions": sessions,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe supported OpenCode session contracts without emitting IDs, paths, "
            "titles, transcript text, tool values, or credentials."
        )
    )
    parser.add_argument("--opencode", default="opencode")
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--max-sessions", type=int, default=10)
    parser.add_argument("--current-session-id")
    parser.add_argument("--current-message-id")
    parser.add_argument("--expect-provider", choices=sorted(SUPPORTED_PROVIDERS))
    parser.add_argument(
        "--expected-version",
        choices=(SUPPORTED_OPENCODE_VERSION,),
        default=SUPPORTED_OPENCODE_VERSION,
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_COMMAND_TIMEOUT_SECONDS
    )
    parser.add_argument(
        "--overall-timeout", type=float, default=DEFAULT_OVERALL_TIMEOUT_SECONDS
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_sessions < 1 or args.timeout <= 0 or args.overall_timeout <= 0:
        print("error: session and timeout limits must be positive", file=sys.stderr)
        return 2
    target_arguments = (
        args.current_session_id,
        args.current_message_id,
        args.expect_provider,
    )
    if any(value is not None for value in target_arguments) and not all(
        value is not None for value in target_arguments
    ):
        document = {
            "schema_version": SCHEMA_VERSION,
            "result": "fail",
            "error_code": "invalid_arguments",
        }
        rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
        print(rendered, end="")
        return 1
    try:
        document = probe(
            args.opencode,
            args.cwd,
            max_sessions=args.max_sessions,
            current_session_id=args.current_session_id,
            invoking_message_id=args.current_message_id,
            expected_provider=args.expect_provider,
            expected_version=args.expected_version,
            command_timeout=args.timeout,
            overall_timeout=args.overall_timeout,
        )
    except ProbeFailure as error:
        document = {
            "schema_version": SCHEMA_VERSION,
            "result": "fail",
            "error_code": error.code,
        }
    except Exception:
        document = {
            "schema_version": SCHEMA_VERSION,
            "result": "fail",
            "error_code": "internal_failure",
        }
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if document["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
