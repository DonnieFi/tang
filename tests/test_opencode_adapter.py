from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tang.adapters import (
    AdapterCheckpoint,
    BatchStatus,
    OpenCodeAdapter,
    OpaqueSourceLocator,
    SessionIdentity,
    SourceRecord,
    TurnRole,
    TurnSelection,
)
from tang.cli import main
from tang.indexing import ProjectIndexer
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.storage import open_database
from tang.target import (
    OpenCodeTargetContext,
    TargetResolutionKind,
    resolve_opencode_target,
)


FIXTURES = Path(__file__).parent / "fixtures" / "opencode"
SESSION_ID = "ses_tang00000000000000000000001"


FAKE_OPENCODE = r'''#!/usr/bin/env python3
import base64
import json
import os
import stat
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

state_path = Path(os.environ["FAKE_OPENCODE_STATE"])
state = json.loads(state_path.read_text())

if sys.argv[1:] == ["--version"]:
    time.sleep(state.get("version_sleep", 0))
    if state.get("version_exit"):
        raise SystemExit(state["version_exit"])
    print(state.get("version", "1.17.20"))
    raise SystemExit(0)

if "serve" in sys.argv:
    time.sleep(state.get("serve_sleep", 0))
    if state.get("serve_exit"):
        raise SystemExit(state["serve_exit"])
    port = int(sys.argv[sys.argv.index("--port") + 1])
    password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    username = os.environ.get("OPENCODE_SERVER_USERNAME", "")
    expected = "Basic " + base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            if self.headers.get("Authorization") != expected:
                self.send_response(401)
                self.end_headers()
                return
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path != "/session" or "roots" in query:
                self.send_response(400)
                self.end_headers()
                return
            catalog = state.get("catalog", [])
            if not isinstance(catalog, list):
                raw = str(catalog).encode()
            else:
                directory = query.get("directory", [""])[0]
                limit = int(query.get("limit", ["100"])[0])
                filtered = [
                    item
                    for item in catalog
                    if not isinstance(item, dict)
                    or item.get("directory") == directory
                ][:limit]
                raw = json.dumps(filtered).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    HTTPServer(("127.0.0.1", port), Handler).serve_forever()

if "export" in sys.argv:
    time.sleep(state.get("export_sleep", 0))
    if state.get("export_exit"):
        raise SystemExit(state["export_exit"])
    stdout_mode = os.fstat(sys.stdout.fileno()).st_mode
    if state.get("require_regular_export_stdout") and (
        not stat.S_ISREG(stdout_mode) or stat.S_IMODE(stdout_mode) & 0o077
    ):
        print("{")
        raise SystemExit(0)
    session_id = sys.argv[-1]
    export = state.get("exports", {}).get(session_id)
    if export is None:
        raise SystemExit(2)
    if isinstance(export, str):
        print(export)
    else:
        print(json.dumps(export))
    raise SystemExit(0)

raise SystemExit(2)
'''


def load(name: str) -> object:
    return json.loads((FIXTURES / name).read_text())


def fixture_documents(project: Path) -> tuple[list[object], dict[str, object]]:
    catalog = load("server-session-list.json")
    export = load("session-export.json")
    assert isinstance(catalog, list)
    assert isinstance(export, dict)
    for item in catalog:
        assert isinstance(item, dict)
        item["directory"] = str(project)
    info = export["info"]
    assert isinstance(info, dict)
    info["directory"] = str(project)
    for message in export["messages"]:
        if isinstance(message, dict) and isinstance(message.get("info"), dict):
            path = message["info"].get("path")
            if isinstance(path, dict):
                path["cwd"] = path["root"] = str(project)
    return catalog, export


def fake_opencode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: dict[str, object],
) -> Path:
    executable = tmp_path / "fake-opencode"
    executable.write_text(FAKE_OPENCODE)
    executable.chmod(0o755)
    state_path = tmp_path / "opencode-state.json"
    state_path.write_text(json.dumps(state))
    monkeypatch.setenv("FAKE_OPENCODE_STATE", str(state_path))
    return executable


def adapter_for(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    project: Path,
    *,
    state: dict[str, object] | None = None,
    **kwargs: object,
) -> OpenCodeAdapter:
    catalog, export = fixture_documents(project)
    executable = fake_opencode(
        tmp_path,
        monkeypatch,
        state=state
        or {
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "require_regular_export_stdout": True,
            "version": "1.17.20",
        },
    )
    return OpenCodeAdapter(
        project,
        executable,
        source_namespace="fixture-opencode",
        **kwargs,
    )


def test_scan_and_read_supported_visible_opencode_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("NO_PROXY", "")
    project = tmp_path / "project"
    project.mkdir()
    adapter = adapter_for(tmp_path, monkeypatch, project)

    scan = adapter.scan(None)
    record = scan.records[0]
    read = adapter.read(record, TurnSelection())

    assert scan.status is BatchStatus.COMPLETE
    assert scan.removed == ()
    assert scan.next_checkpoint is not None
    assert record.identity == SessionIdentity(
        "opencode", "fixture-opencode", SESSION_ID
    )
    assert record.project_hint == str(project)
    assert record.title == "Design deterministic OpenCode recovery"
    assert record.fingerprint.algorithm == "opencode-updated-ms-v1"
    assert record.fingerprint.value == "1784224860000"
    assert "opencode-session-v1" not in repr(record.locator)
    assert read.status is BatchStatus.COMPLETE
    assert read.header.model_provider == "openai"
    assert read.header.model_id == "gpt-5.6"
    assert [turn.role for turn in read.turns] == [TurnRole.USER, TurnRole.AGENT]
    assert [turn.ordinal for turn in read.turns] == [0, 1]
    assert [turn.citation_locator for turn in read.turns] == [
        "message:msg_tang_user_0001",
        "message:msg_tang_assistant_0001",
    ]
    visible = " ".join(turn.text for turn in read.turns)
    assert "HIDDEN_REASONING_CANARY" not in visible
    assert "TOOL_INPUT_CANARY" not in visible
    assert "TOOL_OUTPUT_CANARY" not in visible


def test_read_selection_uses_deterministic_created_then_id_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    messages = export["messages"]
    assert isinstance(messages, list)
    messages.reverse()
    for message in messages:
        info = message["info"]
        info["time"]["created"] = 1784224801000
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection(start_at=1, stop_before=2))

    assert len(read.turns) == 1
    assert read.turns[0].ordinal == 1
    assert read.turns[0].role is TurnRole.USER


def test_scan_is_incremental_detects_changes_and_clean_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    state = {
        "catalog": catalog,
        "exports": {SESSION_ID: export},
        "version": "1.17.20",
    }
    adapter = adapter_for(tmp_path, monkeypatch, project, state=state)

    first = adapter.scan(None)
    second = adapter.scan(first.next_checkpoint)
    catalog[0]["time"]["updated"] += 1
    fake_opencode(tmp_path, monkeypatch, state=state)
    changed = adapter.scan(second.next_checkpoint)
    state["catalog"] = []
    fake_opencode(tmp_path, monkeypatch, state=state)
    deleted = adapter.scan(changed.next_checkpoint)

    assert len(first.records) == 1
    assert second.records == ()
    assert len(changed.records) == 1
    assert changed.records[0].fingerprint.value == "1784224860001"
    assert deleted.removed == (first.records[0].identity,)


def test_linked_worktree_scans_keep_directory_scoped_sessions_and_checkpoints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    primary = tmp_path / "primary"
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(primary)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tang Fixture"],
        cwd=primary,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "fixture@example.invalid"],
        cwd=primary,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "fixture baseline"],
        cwd=primary,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "worktree", "add", "-b", "linked", str(linked)],
        cwd=primary,
        check=True,
        capture_output=True,
        text=True,
    )

    primary_catalog, primary_export = fixture_documents(primary)
    linked_catalog, linked_export = fixture_documents(linked)
    linked_id = "ses_tangLinked00000000000000000002"
    linked_catalog[0]["id"] = linked_id
    linked_export["info"]["id"] = linked_id
    for message in linked_export["messages"]:
        if isinstance(message, dict) and isinstance(message.get("info"), dict):
            message["info"]["sessionID"] = linked_id
    state = {
        "catalog": [*primary_catalog, *linked_catalog],
        "exports": {SESSION_ID: primary_export, linked_id: linked_export},
        "version": "1.17.20",
    }
    executable = fake_opencode(tmp_path, monkeypatch, state=state)
    primary_adapter = OpenCodeAdapter(primary, executable)
    linked_adapter = OpenCodeAdapter(linked, executable)
    project = resolve_project(primary)
    connection = open_database(primary / ".tang" / "tang.db")
    repository = TangRepository(connection)
    indexer = ProjectIndexer(repository)
    try:
        first = indexer.index((primary_adapter,), project)
        second = indexer.index((linked_adapter,), resolve_project(linked))

        assert first.indexed == second.indexed == 1
        assert primary_adapter.source_namespace == linked_adapter.source_namespace
        assert len(repository.sessions_for_project(project.key)) == 2
        checkpoint = repository.get_checkpoint(
            "opencode", primary_adapter.source_namespace, project.key
        )
        assert checkpoint is not None
        checkpoint_document = json.loads(checkpoint.cursor)
        assert checkpoint_document["schema_version"] == 3
        assert len(checkpoint_document["scopes"]) == 2

        state["catalog"] = [*linked_catalog]
        fake_opencode(tmp_path, monkeypatch, state=state)
        removed = indexer.index((primary_adapter,), project)
        retained = repository.sessions_for_project(project.key)

        assert removed.deleted == 1
        assert len(retained) == 1
        assert retained[0].source.identity.native_id == linked_id
        assert retained[0].native_available

        observed = linked_adapter.scan(None).records[0]
        context = OpenCodeTargetContext.from_host(
            session_id=linked_id,
            directory=linked,
            worktree=linked,
            observed_source=observed,
        )
        resolution = resolve_opencode_target(
            retained, resolve_project(linked), context
        )
        assert resolution.kind is TargetResolutionKind.CONFIRMATION_REQUIRED
    finally:
        connection.close()


def test_legacy_checkpoint_forces_safe_full_scan_without_removals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    adapter = adapter_for(tmp_path, monkeypatch, project)
    legacy_identity = SessionIdentity(
        "opencode", "fixture-opencode", "ses_tangLegacy00000000000000000002"
    )
    legacy = AdapterCheckpoint(
        "opencode",
        "fixture-opencode",
        json.dumps(
            {
                "fingerprints": {legacy_identity.canonical: "1"},
                "schema_version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )

    scan = adapter.scan(legacy)

    assert scan.status is BatchStatus.PARTIAL
    assert scan.removed == ()
    assert [warning.code for warning in scan.warnings] == ["checkpoint-upgraded"]
    assert scan.next_checkpoint is not None
    assert json.loads(scan.next_checkpoint.cursor)["schema_version"] == 3


def test_catalog_includes_child_sessions_and_filters_exact_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    foreign = tmp_path / "foreign"
    project.mkdir()
    foreign.mkdir()
    catalog, export = fixture_documents(project)
    child = json.loads(json.dumps(catalog[0]))
    child["id"] = "ses_tangChild000000000000000000002"
    child["parentID"] = SESSION_ID
    child["time"]["updated"] += 1
    outside = json.loads(json.dumps(catalog[0]))
    outside["id"] = "ses_tangForeign0000000000000000003"
    outside["directory"] = str(foreign)
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": [outside, child, *catalog],
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )

    scan = adapter.scan(None)

    assert scan.status is BatchStatus.COMPLETE
    assert [item.identity.native_id for item in scan.records] == [
        SESSION_ID,
        "ses_tangChild000000000000000000002",
    ]


def test_catalog_bound_returns_deterministic_partial_without_deletions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    second = json.loads(json.dumps(catalog[0]))
    second["id"] = "ses_tangSecond00000000000000000002"
    second["time"]["updated"] += 1
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": [*catalog, second],
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
        catalog_limit=1,
    )

    scan = adapter.scan(None)

    assert scan.status is BatchStatus.PARTIAL
    assert [warning.code for warning in scan.warnings] == ["catalog-limit"]
    assert scan.records[0].identity.native_id == second["id"]
    assert scan.removed == ()


def test_identityless_catalog_warning_retains_last_known_good_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )

    first = adapter.scan(None)
    Path(os.environ["FAKE_OPENCODE_STATE"]).write_text(
        json.dumps(
            {
                "catalog": ["malformed-unrelated-item"],
                "exports": {SESSION_ID: export},
                "version": "1.17.20",
            }
        )
    )
    second = adapter.scan(first.next_checkpoint)

    assert second.status is BatchStatus.PARTIAL
    assert [warning.code for warning in second.warnings] == ["catalog-schema-drift"]
    assert second.removed == ()
    assert second.next_checkpoint is not None
    assert first.records[0].identity.canonical in second.next_checkpoint.cursor


@pytest.mark.parametrize(
    ("state", "code"),
    [
        ({"version": "9.0.0"}, "unsupported-version"),
        ({"version": "1.17.17"}, "unsupported-version"),
        ({"version": "2.0.0"}, "unsupported-version"),
        ({"version": "1.17.20-dev"}, "unsupported-version"),
        ({"version": "1.017.20"}, "unsupported-version"),
        ({"version_exit": 2}, "version-failed"),
        ({"version": "1.17.20", "serve_exit": 2}, "catalog-unavailable"),
        ({"version": "1.17.20", "catalog": "not-json"}, "catalog-invalid-json"),
    ],
)
def test_scan_fails_closed_for_unsupported_native_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: dict[str, object],
    code: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    adapter = adapter_for(tmp_path, monkeypatch, project, state=state)

    scan = adapter.scan(None)

    assert scan.status is BatchStatus.UNAVAILABLE
    assert scan.records == ()
    assert scan.next_checkpoint is None
    assert scan.warnings[0].code == code


@pytest.mark.parametrize("version", ["1.17.18", "1.17.20", "1.18.0", "1.99.999"])
def test_scan_accepts_supported_opencode_1_x_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "version": version,
        },
    )

    scan = adapter.scan(None)

    assert scan.status is BatchStatus.COMPLETE
    assert scan.records


def test_missing_and_timed_out_executable_are_structured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    missing = OpenCodeAdapter(
        project,
        tmp_path / "missing-opencode",
        source_namespace="missing",
    ).scan(None)
    timed = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={"version_sleep": 1},
        command_timeout=0.05,
    ).scan(None)

    assert missing.status is BatchStatus.UNAVAILABLE
    assert missing.warnings[0].code == "missing-executable"
    assert timed.status is BatchStatus.UNAVAILABLE
    assert timed.warnings[0].code == "version-timeout"


def test_malformed_catalog_item_is_partial_and_checkpoint_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": ["poison", *catalog],
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )

    first = adapter.scan(None)
    second = adapter.scan(first.next_checkpoint)

    assert first.status is BatchStatus.PARTIAL
    assert first.warnings[0].code == "catalog-schema-drift"
    assert len(first.records) == 1
    assert first.next_checkpoint is not None
    assert second.records == ()


def test_poison_export_retries_only_after_catalog_fingerprint_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, _export = fixture_documents(project)
    state = {
        "catalog": catalog,
        "exports": {SESSION_ID: "{broken"},
        "version": "1.17.20",
    }
    adapter = adapter_for(tmp_path, monkeypatch, project, state=state)

    first = adapter.scan(None)
    poison = adapter.read(first.records[0], TurnSelection())
    second = adapter.scan(first.next_checkpoint)
    catalog[0]["time"]["updated"] += 1
    fake_opencode(tmp_path, monkeypatch, state=state)
    changed = adapter.scan(second.next_checkpoint)

    assert poison.status is BatchStatus.UNAVAILABLE
    assert poison.warnings[0].code == "session-export-invalid-json"
    assert second.records == ()
    assert len(changed.records) == 1


def test_read_retains_visible_turns_across_partial_message_damage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    export["messages"].insert(1, {"info": "poison", "parts": []})
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection())

    assert read.status is BatchStatus.PARTIAL
    assert len(read.turns) == 2
    assert read.warnings[0].code == "message-schema-drift"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("missing-messages", "session-export-schema-drift"),
        ("wrong-id", "identity-mismatch"),
        ("changed", "source-changed-during-read"),
    ],
)
def test_read_refuses_or_qualifies_changed_export_contracts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    code: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    if mutation == "missing-messages":
        export.pop("messages")
    elif mutation == "wrong-id":
        export["info"]["id"] = "ses_other0000000000000000000000001"
    else:
        export["info"]["time"]["updated"] += 1
    adapter = adapter_for(
        tmp_path,
        monkeypatch,
        project,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )
    record = adapter.scan(None).records[0]

    read = adapter.read(record, TurnSelection())

    assert read.warnings[0].code == code
    assert read.status is (
        BatchStatus.PARTIAL if mutation == "changed" else BatchStatus.UNAVAILABLE
    )


def test_read_rejects_tampered_locator_namespace_project_and_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    adapter = adapter_for(tmp_path, monkeypatch, project)
    record = adapter.scan(None).records[0]
    wrong_namespace = SourceRecord(
        identity=SessionIdentity("opencode", "other-store", SESSION_ID),
        locator=record.locator,
        fingerprint=record.fingerprint,
        project_hint=record.project_hint,
        started_at=record.started_at,
        updated_at=record.updated_at,
    )
    wrong_locator = SourceRecord(
        identity=record.identity,
        locator=OpaqueSourceLocator("opencode-session-v1:ses_other"),
        fingerprint=record.fingerprint,
        project_hint=record.project_hint,
        started_at=record.started_at,
        updated_at=record.updated_at,
    )
    missing_project = SourceRecord(
        identity=record.identity,
        locator=record.locator,
        fingerprint=record.fingerprint,
        project_hint=str(tmp_path / "deleted-project"),
        started_at=record.started_at,
        updated_at=record.updated_at,
    )
    catalog, export = fixture_documents(project)
    executable = fake_opencode(
        tmp_path,
        monkeypatch,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "export_sleep": 1,
            "version": "1.17.20",
        },
    )
    timed_adapter = OpenCodeAdapter(
        project,
        executable,
        source_namespace="fixture-opencode",
        command_timeout=0.5,
    )

    assert adapter.read(wrong_namespace, TurnSelection()).warnings[0].code == "wrong-source"
    assert adapter.read(wrong_locator, TurnSelection()).warnings[0].code == "identity-mismatch"
    assert adapter.read(missing_project, TurnSelection()).warnings[0].code == "project-mismatch"
    assert timed_adapter.read(record, TurnSelection()).warnings[0].code == "session-export-timeout"


def test_read_reports_deleted_failed_and_missing_native_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    catalog, export = fixture_documents(project)
    initial = {
        "catalog": catalog,
        "exports": {SESSION_ID: export},
        "version": "1.17.20",
    }
    executable = fake_opencode(tmp_path, monkeypatch, state=initial)
    adapter = OpenCodeAdapter(
        project, executable, source_namespace="fixture-opencode"
    )
    record = adapter.scan(None).records[0]

    fake_opencode(
        tmp_path,
        monkeypatch,
        state={"catalog": catalog, "exports": {}, "version": "1.17.20"},
    )
    deleted = adapter.read(record, TurnSelection())
    fake_opencode(
        tmp_path,
        monkeypatch,
        state={
            "catalog": catalog,
            "export_exit": 9,
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )
    failed = adapter.read(record, TurnSelection())
    executable.unlink()
    missing = adapter.read(record, TurnSelection())

    assert deleted.status is BatchStatus.UNAVAILABLE
    assert deleted.warnings[0].code == "session-export-failed"
    assert failed.warnings[0].code == "session-export-failed"
    assert missing.warnings[0].code == "missing-executable"


def test_invalid_checkpoint_runs_full_partial_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    adapter = adapter_for(tmp_path, monkeypatch, project)
    checkpoint = AdapterCheckpoint("opencode", "fixture-opencode", "not-json")

    scan = adapter.scan(checkpoint)

    assert scan.status is BatchStatus.PARTIAL
    assert len(scan.records) == 1
    assert scan.warnings[0].code == "checkpoint-invalid"


def test_checkpoint_with_malformed_or_foreign_identity_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    adapter = adapter_for(tmp_path, monkeypatch, project)
    for fingerprints in (
        {"not-canonical": "1"},
        {f"opencode:another-store:{SESSION_ID}": "1"},
    ):
        checkpoint = AdapterCheckpoint(
            "opencode",
            "fixture-opencode",
            json.dumps({"fingerprints": fingerprints, "schema_version": 1}),
        )

        scan = adapter.scan(checkpoint)

        assert scan.status is BatchStatus.PARTIAL
        assert scan.warnings[0].code == "checkpoint-invalid"


def test_cli_indexes_discovers_rereads_doctors_and_purges_opencode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex_home = tmp_path / "codex"
    grok_home = tmp_path / "grok"
    (codex_home / "sessions").mkdir(parents=True)
    (grok_home / "sessions").mkdir(parents=True)
    catalog, export = fixture_documents(project)
    executable = fake_opencode(
        tmp_path,
        monkeypatch,
        state={
            "catalog": catalog,
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )
    database = tmp_path / "data" / "tang.db"
    adapter_flags = [
        "--cwd",
        str(project),
        "--codex-home",
        str(codex_home),
        "--grok-home",
        str(grok_home),
        "--opencode-executable",
        str(executable),
    ]

    assert main(["index", "--json", "--database", str(database), *adapter_flags]) == 0
    indexed = json.loads(capsys.readouterr().out)
    assert indexed["status"] == "complete"
    assert indexed["indexed"] == 1

    assert main(
        [
            "browse",
            "--json",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--harness",
            "opencode",
        ]
    ) == 0
    browsed = json.loads(capsys.readouterr().out)
    assert len(browsed["results"]) == 1
    assert browsed["results"][0]["harness"] == "opencode"
    assert browsed["results"][0]["session_handle"] == "O1"

    assert main(
        [
            "search",
            "OpenCode",
            "--json",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--harness",
            "opencode",
        ]
    ) == 0
    searched = json.loads(capsys.readouterr().out)
    assert searched["results"][0]["session_handle"] == "O1"

    assert main(
        [
            "context",
            "O1",
            "--json",
            "--database",
            str(database),
            *adapter_flags,
        ]
    ) == 0
    context = json.loads(capsys.readouterr().out)
    sources = context["untrusted_data_envelope"]["sources"]
    assert sources[0]["harness"] == "opencode"
    assert sources[0]["excerpts"]

    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")
    assert main(
        ["doctor", "--json", "--database", str(database), *adapter_flags]
    ) == 1
    doctor = json.loads(capsys.readouterr().out)
    opencode = next(
        check for check in doctor["checks"] if check["component"] == "opencode"
    )
    assert opencode["status"] == "ready"
    assert "1 session" in opencode["message"]

    state_before = (tmp_path / "opencode-state.json").read_bytes()
    assert main(
        [
            "purge",
            "--all",
            "--yes",
            "--database",
            str(database),
            "--cwd",
            str(project),
        ]
    ) == 0
    capsys.readouterr()
    assert (tmp_path / "opencode-state.json").read_bytes() == state_before
    connection = open_database(database)
    try:
        repository = TangRepository(connection)
        assert repository.sessions_for_project(resolve_project(project).key) == ()
    finally:
        connection.close()


def test_cli_partial_opencode_index_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    codex_home = tmp_path / "codex"
    grok_home = tmp_path / "grok"
    (codex_home / "sessions").mkdir(parents=True)
    (grok_home / "sessions").mkdir(parents=True)
    catalog, export = fixture_documents(project)
    executable = fake_opencode(
        tmp_path,
        monkeypatch,
        state={
            "catalog": ["poison", *catalog],
            "exports": {SESSION_ID: export},
            "version": "1.17.20",
        },
    )

    result = main(
        [
            "index",
            "--json",
            "--database",
            str(tmp_path / "tang.db"),
            "--cwd",
            str(project),
            "--codex-home",
            str(codex_home),
            "--grok-home",
            str(grok_home),
            "--opencode-executable",
            str(executable),
        ]
    )

    captured = capsys.readouterr()
    document = json.loads(captured.out)
    assert result == 1
    assert document["status"] == "partial"
    assert document["indexed"] == 1
    assert [warning["code"] for warning in document["warnings"]] == [
        "catalog-schema-drift"
    ]
