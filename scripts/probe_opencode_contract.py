#!/usr/bin/env python3
"""Emit privacy-safe evidence for Tang's supported OpenCode contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = 1


class ProbeFailure(RuntimeError):
    """OpenCode did not satisfy the evidence contract."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _json_document(value: str, label: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise ProbeFailure(f"{label} did not emit valid JSON") from error


def _run(
    executable: str,
    arguments: Sequence[str],
    project: Path,
    timeout: float,
) -> str:
    environment = {
        **os.environ,
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
        "OPENCODE_DISABLE_MODELS_FETCH": "1",
    }
    try:
        result = subprocess.run(
            [executable, *arguments],
            cwd=project,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ProbeFailure(f"OpenCode {arguments[0]} could not be executed") from error
    if result.returncode != 0:
        raise ProbeFailure(
            f"OpenCode {arguments[0]} exited {result.returncode}; raw output withheld"
        )
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
    raw_export: str,
    project: Path,
) -> dict[str, Any]:
    source_id = listed.get("id")
    if not isinstance(source_id, str) or not source_id:
        raise ProbeFailure("session list contained an invalid identity")
    info = exported.get("info")
    messages = exported.get("messages")
    if not isinstance(info, dict) or not isinstance(messages, list):
        raise ProbeFailure("session export omitted info or messages")

    created_times: list[int] = []
    roles: list[str] = []
    visible_text_parts = 0
    hidden_part_types: set[str] = set()
    for message in messages:
        if not isinstance(message, dict):
            raise ProbeFailure("session export contained a malformed message")
        message_info = message.get("info")
        parts = message.get("parts")
        if not isinstance(message_info, dict) or not isinstance(parts, list):
            raise ProbeFailure("session export contained a malformed message envelope")
        role = message_info.get("role")
        if isinstance(role, str):
            roles.append(role)
        time = message_info.get("time")
        if isinstance(time, dict) and isinstance(time.get("created"), int):
            created_times.append(time["created"])
        for part in parts:
            if not isinstance(part, dict) or not isinstance(part.get("type"), str):
                raise ProbeFailure("session export contained a malformed part")
            part_type = part["type"]
            if (
                role in {"user", "assistant"}
                and part_type == "text"
                and isinstance(part.get("text"), str)
                and not part.get("ignored", False)
            ):
                visible_text_parts += 1
            elif part_type not in {"step-start", "step-finish"}:
                hidden_part_types.add(part_type)

    directory = listed.get("directory")
    exported_directory = info.get("directory")
    canonical_project = project.resolve()
    project_match = isinstance(directory, str) and Path(directory).resolve() == canonical_project
    export_project_match = (
        isinstance(exported_directory, str)
        and Path(exported_directory).resolve() == canonical_project
    )
    return {
        "chronological": created_times == sorted(created_times),
        "export_sha256": hashlib.sha256(raw_export.encode("utf-8")).hexdigest(),
        "hidden_part_types": sorted(hidden_part_types),
        "identity_digest": _digest(source_id),
        "message_count": len(messages),
        "project_match": project_match and export_project_match,
        "provider_ids": list(_provider_ids(exported)),
        "roles": sorted(set(roles)),
        "stable_identity": info.get("id") == source_id,
        "title_present": isinstance(listed.get("title"), str)
        and bool(listed["title"].strip()),
        "updated_milliseconds_present": isinstance(listed.get("updated"), int),
        "visible_text_parts": visible_text_parts,
    }


def probe(
    executable: str,
    project: Path,
    *,
    max_sessions: int,
    current_session_id: str | None,
    expected_providers: tuple[str, ...],
    timeout: float,
) -> dict[str, Any]:
    project = project.resolve()
    version = _run(executable, ("--version",), project, timeout).strip()
    raw_list = _run(
        executable,
        ("--pure", "session", "list", "--format", "json", "-n", str(max_sessions)),
        project,
        timeout,
    )
    listed = _json_document(raw_list, "session list")
    if not isinstance(listed, list):
        raise ProbeFailure("session list did not emit an array")

    sessions: list[dict[str, Any]] = []
    raw_ids: list[str] = []
    for item in listed:
        if not isinstance(item, dict):
            raise ProbeFailure("session list contained a non-object item")
        source_id = item.get("id")
        directory = item.get("directory")
        if not isinstance(source_id, str) or not isinstance(directory, str):
            raise ProbeFailure("session list item omitted identity or directory")
        if Path(directory).resolve() != project:
            continue
        raw_export = _run(
            executable,
            ("--pure", "export", source_id),
            project,
            timeout,
        )
        exported = _json_document(raw_export, "session export")
        if not isinstance(exported, dict):
            raise ProbeFailure("session export did not emit an object")
        sessions.append(_session_evidence(item, exported, raw_export, project))
        raw_ids.append(source_id)

    providers = sorted(
        {provider for session in sessions for provider in session["provider_ids"]}
    )
    current_match = (
        None if current_session_id is None else current_session_id in raw_ids
    )
    missing_providers = sorted(set(expected_providers) - set(providers))
    checks = {
        "all_chronological": all(item["chronological"] for item in sessions),
        "all_project_scoped": all(item["project_match"] for item in sessions),
        "all_stable_identities": all(item["stable_identity"] for item in sessions),
        "current_session_matches": current_match,
        "missing_expected_providers": missing_providers,
        "session_count_positive": bool(sessions),
    }
    passed = (
        checks["all_chronological"]
        and checks["all_project_scoped"]
        and checks["all_stable_identities"]
        and checks["session_count_positive"]
        and not missing_providers
        and current_match is not False
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
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_sessions < 1:
        print("error: --max-sessions must be positive", file=sys.stderr)
        return 2
    try:
        document = probe(
            args.opencode,
            args.cwd,
            max_sessions=args.max_sessions,
            current_session_id=args.current_session_id,
            expected_providers=tuple(args.expect_provider),
            timeout=args.timeout,
        )
    except ProbeFailure as error:
        document = {
            "schema_version": SCHEMA_VERSION,
            "result": "fail",
            "error": str(error),
        }
    rendered = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if document["result"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
