#!/usr/bin/env python3
"""Emit privacy-safe evidence for Tang's supported OpenCode contract."""

from __future__ import annotations

import argparse
import hashlib
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


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


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


def _provider_ids(document: dict[str, Any]) -> tuple[str, ...]:
    providers: set[str] = set()
    info = document.get("info")
    if isinstance(info, dict):
        model = info.get("model")
        if isinstance(model, dict) and isinstance(model.get("providerID"), str):
            providers.add(model["providerID"])
    messages = document.get("messages")
    if not isinstance(messages, list):
        return tuple(sorted(providers))
    for message in messages:
        if not isinstance(message, dict) or not isinstance(message.get("info"), dict):
            continue
        message_info = message["info"]
        provider = message_info.get("providerID")
        if isinstance(provider, str):
            providers.add(provider)
        model = message_info.get("model")
        if isinstance(model, dict) and isinstance(model.get("providerID"), str):
            providers.add(model["providerID"])
    return tuple(sorted(providers))


def _session_evidence(
    listed: dict[str, Any],
    exported: dict[str, Any],
    project: Path,
    *,
    current_session: bool,
) -> dict[str, Any]:
    source_id = listed.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ProbeFailure("session_list_invalid_shape")
    info = exported.get("info")
    messages = exported.get("messages")
    if not isinstance(info, dict) or not isinstance(messages, list):
        raise ProbeFailure("session_export_invalid_shape")

    created_times: list[int] = []
    ordering_inputs_complete = True
    roles: list[str] = []
    visible_text_roles: set[str] = set()
    visible_text_parts = 0
    hidden_part_types: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ProbeFailure("session_export_invalid_shape")
        message_info = message.get("info")
        parts = message.get("parts")
        if not isinstance(message_info, dict) or not isinstance(parts, list):
            raise ProbeFailure("session_export_invalid_shape")
        role = message_info.get("role")
        if isinstance(role, str):
            roles.append(role)
        time = message_info.get("time")
        if isinstance(time, dict) and isinstance(time.get("created"), int):
            created_times.append(time["created"])
        else:
            ordering_inputs_complete = False
        if not isinstance(message_info.get("id"), str) or not message_info["id"]:
            ordering_inputs_complete = False
        for part in parts:
            if not isinstance(part, dict) or not isinstance(part.get("type"), str):
                raise ProbeFailure("session_export_invalid_shape")
            part_type = part["type"]
            if (
                role in {"user", "assistant"}
                and part_type == "text"
                and isinstance(part.get("text"), str)
                and not part.get("ignored", False)
            ):
                visible_text_parts += 1
                visible_text_roles.add(role)
            elif part_type not in {"step-start", "step-finish"}:
                hidden_part_types.add(part_type)

    directory = listed.get("directory")
    exported_directory = info.get("directory")
    canonical_project = project.resolve()
    project_match = (
        isinstance(directory, str) and Path(directory).resolve() == canonical_project
    )
    export_project_match = (
        isinstance(exported_directory, str)
        and Path(exported_directory).resolve() == canonical_project
    )
    return {
        "chronological": ordering_inputs_complete
        and created_times == sorted(created_times),
        "current_session": current_session,
        "hidden_part_types": sorted(hidden_part_types),
        "identity_digest": _digest(source_id),
        "message_count": len(messages),
        "ordering_inputs_complete": ordering_inputs_complete,
        "ordering_strategy": "created_milliseconds_then_message_id",
        "project_match": project_match and export_project_match,
        "provider_ids": list(_provider_ids(exported)),
        "roles": sorted(set(roles)),
        "stable_identity": info.get("id") == source_id,
        "title_present": isinstance(listed.get("title"), str)
        and bool(listed["title"].strip()),
        "updated_milliseconds_present": isinstance(listed.get("updated"), int),
        "visible_text_parts": visible_text_parts,
        "visible_text_roles": sorted(visible_text_roles),
    }


def probe(
    executable: str,
    project: Path,
    *,
    max_sessions: int,
    current_session_id: str | None,
    expected_providers: tuple[str, ...],
    command_timeout: float,
    overall_timeout: float,
) -> dict[str, Any]:
    project = project.resolve()
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
        ("--pure", "session", "list", "--format", "json"),
        project,
        operation="session_list",
        command_timeout=command_timeout,
        deadline=deadline,
    )
    listed = _json_document(raw_list, "session_list_invalid_json")
    if not isinstance(listed, list):
        raise ProbeFailure("session_list_invalid_shape")

    project_items: list[dict[str, Any]] = []
    current_item: dict[str, Any] | None = None
    current_list_match = False
    for item in listed:
        if not isinstance(item, dict):
            raise ProbeFailure("session_list_invalid_shape")
        source_id = item.get("id")
        directory = item.get("directory")
        if not isinstance(source_id, str) or not isinstance(directory, str):
            raise ProbeFailure("session_list_invalid_shape")
        if Path(directory).resolve() != project:
            continue
        project_items.append(item)
        if current_session_id is not None and source_id == current_session_id:
            current_item = item
            current_list_match = True

    selected_items = project_items[:max_sessions]
    if current_item is not None and current_item not in selected_items:
        if max_sessions == 1:
            selected_items = [current_item]
        else:
            selected_items = [current_item, *selected_items[: max_sessions - 1]]

    sessions: list[dict[str, Any]] = []
    for item in selected_items:
        source_id = item.get("id")
        if not isinstance(source_id, str):
            raise ProbeFailure("session_list_invalid_shape")
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
                current_session=current_session_id == source_id,
            )
        )

    providers = sorted(
        {provider for session in sessions for provider in session["provider_ids"]}
    )
    current_match = None if current_session_id is None else current_list_match
    current_providers = sorted(
        {
            provider
            for session in sessions
            if session["current_session"]
            for provider in session["provider_ids"]
        }
    )
    provider_evidence = (
        current_providers if current_session_id is not None else providers
    )
    missing_providers = sorted(set(expected_providers) - set(provider_evidence))
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
    checks = {
        "all_chronological": all(item["chronological"] for item in sessions),
        "all_ordering_inputs_complete": all(
            item["ordering_inputs_complete"] for item in sessions
        ),
        "all_project_scoped": all(item["project_match"] for item in sessions),
        "all_stable_identities": all(item["stable_identity"] for item in sessions),
        "all_updated_milliseconds_present": all(
            item["updated_milliseconds_present"] for item in sessions
        ),
        "current_session_matches": current_match,
        "current_session_visible_user_and_assistant_text": current_visible_text,
        "missing_expected_providers": missing_providers,
        "session_count_positive": bool(sessions),
    }
    passed = (
        checks["all_chronological"]
        and checks["all_ordering_inputs_complete"]
        and checks["all_project_scoped"]
        and checks["all_stable_identities"]
        and checks["all_updated_milliseconds_present"]
        and checks["session_count_positive"]
        and not missing_providers
        and current_match is not False
        and current_visible_text is not False
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "result": "pass" if passed else "fail",
        "opencode_version": version,
        "platform": {
            "machine": platform.machine(),
            "python": platform.python_version(),
            "system": platform.system(),
        },
        "checks": checks,
        "current_session_providers": current_providers,
        "providers": providers,
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
    parser.add_argument("--expect-provider", action="append", default=[])
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
    try:
        document = probe(
            args.opencode,
            args.cwd,
            max_sessions=args.max_sessions,
            current_session_id=args.current_session_id,
            expected_providers=tuple(args.expect_provider),
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
