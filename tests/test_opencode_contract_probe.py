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
from pathlib import Path

if "--version" in sys.argv:
    print("1.17.20")
elif "list" in sys.argv:
    print(json.dumps([{
        "id": "ses_private_identifier",
        "title": "PRIVATE TITLE",
        "updated": 1784224860000,
        "created": 1784224800000,
        "projectId": "project_private",
        "directory": os.getcwd(),
    }]))
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
    assert document["checks"]["current_session_matches"] is True
    assert document["sessions"][0]["hidden_part_types"] == ["reasoning", "tool"]
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
        "error": "session export omitted info or messages",
        "result": "fail",
        "schema_version": 1,
    }


def test_synthetic_fixtures_cover_absent_change_and_hidden_parts() -> None:
    initial = json.loads((FIXTURES / "session-list.json").read_text())
    updated = json.loads((FIXTURES / "session-list-updated.json").read_text())
    exported = json.loads((FIXTURES / "session-export.json").read_text())

    assert json.loads((FIXTURES / "session-list-empty.json").read_text()) == []
    assert initial[0]["id"] == updated[0]["id"]
    assert initial[0]["updated"] < updated[0]["updated"]
    parts = [
        part
        for message in exported["messages"]
        for part in message["parts"]
    ]
    assert {part["type"] for part in parts} == {"text", "reasoning", "tool"}
