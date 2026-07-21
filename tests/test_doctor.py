from __future__ import annotations

import json
from pathlib import Path

from tang.adapters import AdapterWarning, BatchStatus, CodexAdapter, ScanBatch
from tang.cli import main
from tang.doctor import DoctorCheck, _adapter_check, doctor_exit_code, run_doctor
from tang.storage import open_database


def test_doctor_reports_ready_components_deterministically(
    tmp_path: Path, monkeypatch, capsys, codex_fixture_home: Path
) -> None:
    grok = Path(__file__).parent / "fixtures" / "grok"
    database = tmp_path / "data" / "tang.db"
    open_database(database).close()
    before = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in database.parent.iterdir()
    }
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")
    ready_batch = CodexAdapter(
        codex_fixture_home, source_namespace="doctor-opencode"
    ).scan(None)

    class ReadyOpenCode:
        adapter_key = "opencode"
        source_namespace = "doctor-opencode"

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def scan(self, _checkpoint) -> ScanBatch:
            return ready_batch

    monkeypatch.setattr(
        "tang.adapter_registry.OpenCodeAdapter", ReadyOpenCode
    )

    result = main(
        [
            "doctor",
            "--json",
            "--database",
            str(database),
            "--codex-home",
            str(codex_fixture_home),
            "--grok-home",
            str(grok),
        ]
    )

    captured = capsys.readouterr()
    assert result == 0
    assert captured.err == ""
    document = json.loads(captured.out)
    assert document["schema_version"] == 1
    assert document["status"] == "ready"
    assert [check["component"] for check in document["checks"]] == [
        "cli",
        "database",
        "fts5",
        "codex",
        "grok",
        "opencode",
    ]
    assert {check["status"] for check in document["checks"]} == {"ready"}
    after = {
        path.name: (path.stat().st_size, path.stat().st_mtime_ns)
        for path in database.parent.iterdir()
    }
    assert after == before


def test_doctor_reports_missing_cli_and_adapters_actionably(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: None)
    monkeypatch.setattr("tang.adapter_registry.shutil.which", lambda command: None)
    missing_opencode = tmp_path / "missing-opencode"

    result = main(
        [
            "doctor",
            "--database",
            str(tmp_path / "tang.db"),
            "--codex-home",
            str(tmp_path / "missing-codex"),
            "--grok-home",
            str(tmp_path / "missing-grok"),
            "--opencode-executable",
            str(missing_opencode),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err == ""
    assert not (tmp_path / "tang.db").exists()
    assert "cli: unavailable" in captured.out
    assert "Install the tang-multiverse CLI" in captured.out
    assert "database: not_initialized" in captured.out
    assert "tang index will create it" in captured.out
    assert "codex: unavailable" in captured.out
    assert "grok: unavailable" in captured.out
    assert "opencode: missing" in captured.out
    assert "configure --opencode-executable" in captured.out


def test_doctor_reports_empty_readable_adapter_stores(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    codex = tmp_path / "codex"
    grok = tmp_path / "grok"
    (codex / "sessions").mkdir(parents=True)
    (grok / "sessions").mkdir(parents=True)
    database = tmp_path / "data" / "tang.db"
    open_database(database).close()
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")

    result = main(
        [
            "doctor",
            "--database",
            str(database),
            "--codex-home",
            str(codex),
            "--grok-home",
            str(grok),
        ]
    )

    captured = capsys.readouterr()
    assert result == 1
    assert "codex: empty" in captured.out
    assert "Codex store is readable but contains no sessions" in captured.out
    assert "grok: empty" in captured.out


def test_doctor_default_project_path_does_not_create_storage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")

    assert (
        main(
            [
                "doctor",
                "--json",
                "--cwd",
                str(project),
                "--codex-home",
                str(tmp_path / "codex"),
                "--grok-home",
                str(tmp_path / "grok"),
            ]
        )
        == 1
    )

    document = json.loads(capsys.readouterr().out)
    database = next(
        check for check in document["checks"] if check["component"] == "database"
    )
    assert database["status"] == "not_initialized"
    assert not (project / ".tang").exists()


def test_doctor_reads_existing_database_while_wal_writer_is_active(
    tmp_path: Path, monkeypatch
) -> None:
    database = tmp_path / "data" / "tang.db"
    writer = open_database(database)
    writer.execute("BEGIN IMMEDIATE")
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")
    try:
        assert database.with_name("tang.db-wal").exists()
        checks = run_doctor(
            database,
            codex_home=tmp_path / "missing-codex",
            grok_home=tmp_path / "missing-grok",
        )
        database_check = next(
            check for check in checks if check.component == "database"
        )
        assert database_check.status == "ready"
    finally:
        writer.execute("ROLLBACK")
        writer.close()


def test_opencode_doctor_distinguishes_empty_ready_and_degraded(
    codex_fixture_home: Path,
) -> None:
    representative = CodexAdapter(
        codex_fixture_home, source_namespace="doctor-state"
    ).scan(None).records[0]
    empty = _adapter_check("opencode", ScanBatch(BatchStatus.COMPLETE))[0]
    ready = _adapter_check(
        "opencode",
        ScanBatch(BatchStatus.COMPLETE, records=(representative,)),
    )[0]
    degraded = _adapter_check(
        "opencode",
        ScanBatch(
            BatchStatus.PARTIAL,
            records=(representative,),
            warnings=(
                AdapterWarning(
                    "catalog-limit", "The bounded catalog was incomplete."
                ),
            ),
        ),
    )[0]

    assert (empty.status, ready.status, degraded.status) == (
        "empty",
        "ready",
        "degraded",
    )


def test_doctor_treats_absent_optional_opencode_as_non_blocking() -> None:
    missing = ScanBatch(
        BatchStatus.UNAVAILABLE,
        warnings=(
            AdapterWarning("missing-executable", "OpenCode was not installed."),
        ),
    )

    optional = _adapter_check("opencode", missing)[0]
    required = _adapter_check("opencode", missing, opencode_required=True)[0]

    assert optional.status == "optional"
    assert "Codex/Grok recovery remains available" in optional.message
    assert required.status == "missing"
    assert doctor_exit_code((DoctorCheck("cli", "ready", "ready"), optional)) == 0


def test_doctor_quick_honors_cursor_home(
    tmp_path: Path, monkeypatch, capsys, codex_fixture_home: Path
) -> None:
    import importlib.util

    helper = Path(__file__).with_name("test_cursor_adapter.py")
    spec = importlib.util.spec_from_file_location("cursor_adapter_test", helper)
    assert spec and spec.loader
    cursor_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cursor_tests)

    grok = Path(__file__).parent / "fixtures" / "grok"
    project = (tmp_path / "work").resolve()
    project.mkdir()
    cursor_home = tmp_path / "cursor"
    cursor_tests._layout_session(cursor_home, project, "fixture-session")
    database = tmp_path / "tang.db"
    open_database(database).close()
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")

    result = main(
        [
            "doctor",
            "--quick",
            "--json",
            "--database",
            str(database),
            "--cwd",
            str(project),
            "--codex-home",
            str(codex_fixture_home),
            "--grok-home",
            str(grok),
            "--cursor-home",
            str(cursor_home),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    statuses = {check["component"]: check["status"] for check in payload["checks"]}
    assert statuses["cursor"] == "present"


def test_doctor_quick_skips_full_scan_but_reports_presence(
    tmp_path: Path, monkeypatch, capsys, codex_fixture_home: Path
) -> None:
    grok = Path(__file__).parent / "fixtures" / "grok"
    database = tmp_path / "tang.db"
    open_database(database).close()
    scans = {"count": 0}

    class CountingCodex(CodexAdapter):
        def scan(self, checkpoint):
            scans["count"] += 1
            return super().scan(checkpoint)

    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")
    monkeypatch.setattr("tang.adapter_registry.CodexAdapter", CountingCodex)

    result = main(
        [
            "doctor",
            "--quick",
            "--json",
            "--database",
            str(database),
            "--codex-home",
            str(codex_fixture_home),
            "--grok-home",
            str(grok),
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["mode"] == "quick"
    assert scans["count"] == 0
    statuses = {check["component"]: check["status"] for check in payload["checks"]}
    assert statuses["codex"] == "present"
    assert statuses["grok"] == "present"
    assert doctor_exit_code(
        tuple(
            DoctorCheck(check["component"], check["status"], check["message"])
            for check in payload["checks"]
        )
    ) == 0
