from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "probe_opencode_contract.py"
FIXTURES = ROOT / "tests" / "fixtures" / "opencode"


def _fake_opencode(tmp_path: Path, export: Path) -> Path:
    executable = tmp_path / "opencode"
    executable.write_text(
        """#!/usr/bin/env python3
import json
import os
import sys
import time
from pathlib import Path

if os.environ.get("TANG_FAKE_SLEEP") == "1":
    time.sleep(2)
if "--version" in sys.argv:
    print("1.17.20")
elif "list" in sys.argv:
    if "-n" in sys.argv or "--max-count" in sys.argv:
        raise SystemExit(9)
    project_session = {
        "id": "ses_private_identifier",
        "title": "PRIVATE TITLE",
        "updated": 1784224860000,
        "created": 1784224800000,
        "projectId": "project_private",
        "directory": os.getcwd(),
    }
    foreign = json.loads(os.environ.get("TANG_FAKE_FOREIGN", "[]"))
    print(json.dumps([*foreign, project_session]))
elif "export" in sys.argv:
    document = json.loads(Path(os.environ["TANG_FAKE_EXPORT"]).read_text())
    document["info"]["id"] = "ses_private_identifier"
    document["info"]["directory"] = os.getcwd()
    if isinstance(document["messages"], list):
        for message in document["messages"]:
            message["info"]["sessionID"] = "ses_private_identifier"
            for part in message["parts"]:
                part["sessionID"] = "ses_private_identifier"
    print(json.dumps(document))
else:
    raise SystemExit(2)
""",
        encoding="utf-8",
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    return executable


def test_probe_emits_only_privacy_safe_contract_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
            "--current-session-id",
            "ses_private_identifier",
            "--expect-provider",
            "openai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert "ses_private_identifier" not in result.stdout
    assert "PRIVATE TITLE" not in result.stdout
    assert "TOOL_INPUT_CANARY" not in result.stdout
    assert "TOOL_OUTPUT_CANARY" not in result.stdout
    assert "HIDDEN_REASONING_CANARY" not in result.stdout
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    assert document["result"] == "pass"
    assert document["providers"] == ["openai"]
    assert document["current_session_providers"] == ["openai"]
    assert document["checks"]["current_session_matches"] is True
    assert document["checks"]["all_updated_milliseconds_present"] is True
    assert document["checks"]["current_session_visible_user_and_assistant_text"] is True
    assert document["sessions"][0]["current_session"] is True
    assert document["sessions"][0]["hidden_part_types"] == ["reasoning", "tool"]
    assert "export_sha256" not in document["sessions"][0]
    assert document["sessions"][0]["ordering_inputs_complete"] is True
    assert (
        document["sessions"][0]["ordering_strategy"]
        == "created_milliseconds_then_message_id"
    )
    assert document["sessions"][0]["visible_text_parts"] == 2


def test_probe_fails_closed_without_leaking_invalid_export(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export-malformed.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "ses_private_identifier" not in result.stdout
    assert json.loads(result.stdout) == {
        "error_code": "session_export_invalid_shape",
        "result": "fail",
        "schema_version": 1,
    }


def test_probe_filters_project_before_applying_export_limit(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv(
        "TANG_FAKE_FOREIGN",
        json.dumps(
            [
                {
                    "id": f"ses_foreign_{number}",
                    "title": "PRIVATE FOREIGN TITLE",
                    "updated": 1784224860000 + number,
                    "created": 1784224800000,
                    "projectId": "foreign",
                    "directory": str(tmp_path / "foreign"),
                }
                for number in range(12)
            ]
        ),
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
            "--max-sessions",
            "1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    document = json.loads(result.stdout)
    assert document["checks"]["session_count_positive"] is True
    assert len(document["sessions"]) == 1
    assert "PRIVATE FOREIGN TITLE" not in result.stdout


def test_probe_reports_safe_executable_and_timeout_errors(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    missing = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(tmp_path / "missing-opencode"),
            "--cwd",
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert json.loads(missing.stdout)["error_code"] == "executable_missing"

    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv("TANG_FAKE_SLEEP", "1")
    timed_out = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
            "--timeout",
            "0.05",
            "--overall-timeout",
            "0.1",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert json.loads(timed_out.stdout)["error_code"] == "version_timeout"


def test_probe_fails_when_expected_provider_is_absent(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
            "--expect-provider",
            "xai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    document = json.loads(result.stdout)
    assert document["result"] == "fail"
    assert document["checks"]["missing_expected_providers"] == ["xai"]


def test_probe_checks_expected_provider_on_current_session_only(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    exported["info"]["model"]["providerID"] = "xai"
    for message in exported["messages"]:
        model = message["info"].get("model")
        if isinstance(model, dict):
            model["providerID"] = "xai"
        if "providerID" in message["info"]:
            message["info"]["providerID"] = "xai"
    export = tmp_path / "xai-export.json"
    export.write_text(json.dumps(exported), encoding="utf-8")
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
            "--current-session-id",
            "ses_private_identifier",
            "--expect-provider",
            "openai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    document = json.loads(result.stdout)
    assert document["current_session_providers"] == ["xai"]
    assert document["checks"]["missing_expected_providers"] == ["openai"]


def test_probe_qualifies_missing_message_ordering_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    del exported["messages"][0]["info"]["time"]["created"]
    export = tmp_path / "missing-created.json"
    export.write_text(json.dumps(exported), encoding="utf-8")
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--opencode",
            str(executable),
            "--cwd",
            str(project),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    document = json.loads(result.stdout)
    assert document["checks"]["all_ordering_inputs_complete"] is False
    assert document["sessions"][0]["chronological"] is False


def test_synthetic_fixtures_cover_absent_change_and_hidden_parts() -> None:
    initial = json.loads((FIXTURES / "session-list.json").read_text())
    updated = json.loads((FIXTURES / "session-list-updated.json").read_text())
    exported = json.loads((FIXTURES / "session-export.json").read_text())

    assert json.loads((FIXTURES / "session-list-empty.json").read_text()) == []
    assert initial[0]["id"] == updated[0]["id"]
    assert initial[0]["updated"] < updated[0]["updated"]
    parts = [part for message in exported["messages"] for part in message["parts"]]
    assert {part["type"] for part in parts} == {"text", "reasoning", "tool"}
