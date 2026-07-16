from __future__ import annotations

import json
import runpy
import stat
import subprocess
import sys
from pathlib import Path

import pytest


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
    print(os.environ.get("TANG_FAKE_VERSION", "1.17.20"))
elif "list" in sys.argv:
    if os.environ.get("TANG_FAKE_EMPTY") == "1":
        raise SystemExit(0)
    project_session = {
        "id": "ses_private_identifier",
        "title": "PRIVATE TITLE",
        "updated": 1784224860000,
        "created": 1784224800000,
        "projectId": "project_private",
        "directory": os.getcwd(),
    }
    listed = json.loads(
        os.environ.get("TANG_FAKE_LIST", json.dumps([project_session]))
    )
    if "--max-count" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--max-count") + 1])
        listed = listed[:limit]
    print(json.dumps(listed))
elif "export" in sys.argv:
    document = json.loads(Path(os.environ["TANG_FAKE_EXPORT"]).read_text())
    source_id = sys.argv[-1]
    document["info"]["id"] = source_id
    document["info"]["directory"] = os.getcwd()
    if isinstance(document["messages"], list):
        for message in document["messages"]:
            message["info"]["sessionID"] = source_id
            for part in message["parts"]:
                part["sessionID"] = source_id
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
            "--current-message-id",
            "msg_tang_assistant_0001",
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
    assert document["expected_provider"] == "openai"
    assert document["expected_version"] == "1.17.20"
    assert document["checks"]["current_session_matches"] is True
    assert document["checks"]["invoking_message_matches_once"] is True
    assert document["checks"]["invoking_message_provider_matches"] is True
    assert document["checks"]["platform_supported"] is True
    assert document["checks"]["version_supported"] is True
    assert document["checks"]["all_updated_milliseconds_present"] is True
    assert document["checks"]["current_session_visible_user_and_assistant_text"] is True
    assert document["sessions"][0]["current_session"] is True
    assert document["sessions"][0]["excluded_part_classes"] == [
        "reasoning",
        "tool",
    ]
    assert "export_sha256" not in document["sessions"][0]
    assert "identity_digest" not in document["sessions"][0]
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


def test_probe_rejects_catalog_items_outside_the_current_project(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv(
        "TANG_FAKE_LIST",
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
            + [
                {
                    "id": "ses_private_identifier",
                    "title": "PRIVATE TITLE",
                    "updated": 1784224860000,
                    "created": 1784224800000,
                    "projectId": "project_private",
                    "directory": str(project),
                }
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

    assert result.returncode == 1
    document = json.loads(result.stdout)
    assert document["checks"]["catalog_project_scoped"] is False
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


def test_probe_fails_when_invoking_message_provider_differs(
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
            "--current-message-id",
            "msg_tang_assistant_0001",
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
    assert document["checks"]["invoking_message_provider_matches"] is False


def test_probe_checks_expected_provider_on_exact_invoking_message(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    invoking = exported["messages"][1]
    invoking["info"]["providerID"] = "xai"
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
            "--current-message-id",
            "msg_tang_assistant_0001",
            "--expect-provider",
            "openai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    document = json.loads(result.stdout)
    assert document["sessions"][0]["provider_classes"] == ["openai", "xai"]
    assert document["checks"]["invoking_message_provider_matches"] is False


def test_probe_rejects_duplicate_invoking_message_identity(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    exported["messages"].append(exported["messages"][1])
    export = tmp_path / "duplicate-message.json"
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
            "--current-message-id",
            "msg_tang_assistant_0001",
            "--expect-provider",
            "openai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    document = json.loads(result.stdout)
    assert result.returncode == 1
    assert document["checks"]["invoking_message_matches_once"] is False


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


@pytest.mark.parametrize("created", [True, -1])
def test_probe_rejects_boolean_and_negative_message_timestamps(
    tmp_path: Path, monkeypatch, created: object
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    exported["messages"][0]["info"]["time"]["created"] = created
    export = tmp_path / "invalid-created.json"
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

    document = json.loads(result.stdout)
    assert result.returncode == 1
    assert document["checks"]["all_ordering_inputs_complete"] is False


@pytest.mark.parametrize("updated", [True, -1])
def test_probe_rejects_boolean_and_negative_catalog_timestamps(
    tmp_path: Path, monkeypatch, updated: object
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv(
        "TANG_FAKE_LIST",
        json.dumps(
            [
                {
                    "id": "ses_private_identifier",
                    "title": "PRIVATE TITLE",
                    "updated": updated,
                    "created": 1784224800000,
                    "projectId": "project_private",
                    "directory": str(project),
                }
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
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert json.loads(result.stdout)["error_code"] == "session_list_invalid_shape"


@pytest.mark.parametrize("text", ["", " \t\n"])
def test_probe_requires_meaningful_visible_text(
    tmp_path: Path, monkeypatch, text: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    exported["messages"][1]["parts"][2]["text"] = text
    export = tmp_path / "blank-assistant.json"
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
            "--current-message-id",
            "msg_tang_assistant_0001",
            "--expect-provider",
            "openai",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    document = json.loads(result.stdout)
    assert result.returncode == 1
    assert (
        document["checks"]["current_session_visible_user_and_assistant_text"] is False
    )


def test_probe_classifies_poisoned_metadata_without_echoing_it(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    exported = json.loads((FIXTURES / "session-export.json").read_text())
    poison = "SECRET_/home/private/token"
    exported["messages"][0]["info"]["role"] = poison
    exported["messages"][0]["info"]["model"]["providerID"] = poison
    exported["messages"][0]["parts"][0]["type"] = poison
    export = tmp_path / "poisoned-metadata.json"
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

    document = json.loads(result.stdout)
    assert result.returncode == 1
    assert poison not in result.stdout
    assert document["checks"]["all_metadata_shapes_valid"] is False
    assert document["sessions"][0]["provider_classes"] == ["openai", "other"]
    assert document["sessions"][0]["role_classes"] == ["assistant", "other"]


def test_probe_enforces_pinned_version_and_platform(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv("TANG_FAKE_VERSION", "9.0.0")

    version_result = subprocess.run(
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
    version_document = json.loads(version_result.stdout)
    assert version_result.returncode == 1
    assert version_document["checks"]["version_supported"] is False

    monkeypatch.setenv("TANG_FAKE_VERSION", "1.17.20")
    probe = runpy.run_path(str(SCRIPT))["probe"]
    platform_document = probe(
        str(executable),
        project,
        max_sessions=10,
        current_session_id=None,
        invoking_message_id=None,
        expected_provider=None,
        expected_version="1.17.20",
        command_timeout=30.0,
        overall_timeout=120.0,
        system="Darwin",
        machine="arm64",
    )
    assert platform_document["result"] == "fail"
    assert platform_document["checks"]["platform_supported"] is False


def test_probe_treats_empty_stdout_as_an_empty_catalog(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv("TANG_FAKE_EMPTY", "1")

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

    document = json.loads(result.stdout)
    assert result.returncode == 1
    assert "error_code" not in document
    assert document["checks"]["session_count_positive"] is False


def test_probe_fails_visibly_at_the_latest_root_catalog_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    monkeypatch.setenv(
        "TANG_FAKE_LIST",
        json.dumps(
            [
                {
                    "id": f"ses_{number:03d}",
                    "title": "Synthetic",
                    "updated": 1784224860000 - number,
                    "created": 1784224800000,
                    "projectId": "project_private",
                    "directory": str(project),
                }
                for number in range(100)
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

    document = json.loads(result.stdout)
    assert result.returncode == 1
    assert document["checks"]["catalog_latest_root_limit"] == 100
    assert document["checks"]["catalog_within_supported_boundary"] is False


def test_probe_sorts_equal_timestamps_by_stable_identity_before_slicing(
    tmp_path: Path, monkeypatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    export = FIXTURES / "session-export.json"
    executable = _fake_opencode(tmp_path, export)
    monkeypatch.setenv("TANG_FAKE_EXPORT", str(export))
    items = [
        {
            "id": "ses_b",
            "title": "Has title",
            "updated": 1784224860000,
            "created": 1784224800000,
            "projectId": "project_private",
            "directory": str(project),
        },
        {
            "id": "ses_a",
            "title": "",
            "updated": 1784224860000,
            "created": 1784224800000,
            "projectId": "project_private",
            "directory": str(project),
        },
    ]

    outputs = []
    for listed in (items, list(reversed(items))):
        monkeypatch.setenv("TANG_FAKE_LIST", json.dumps(listed))
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
        outputs.append(result.stdout)

    assert outputs[0] == outputs[1]
    assert json.loads(outputs[0])["sessions"][0]["title_present"] is False


def test_synthetic_fixtures_cover_absent_change_and_hidden_parts() -> None:
    initial = json.loads((FIXTURES / "session-list.json").read_text())
    updated = json.loads((FIXTURES / "session-list-updated.json").read_text())
    exported = json.loads((FIXTURES / "session-export.json").read_text())

    assert (FIXTURES / "session-list-empty.json").read_text() == ""
    assert initial[0]["id"] == updated[0]["id"]
    assert initial[0]["updated"] < updated[0]["updated"]
    parts = [part for message in exported["messages"] for part in message["parts"]]
    assert {part["type"] for part in parts} == {"text", "reasoning", "tool"}
