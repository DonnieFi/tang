from __future__ import annotations

import json
from pathlib import Path

from tang.cli import main
from tang.doctor import run_doctor
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

    result = main(
        [
            "doctor",
            "--database",
            str(tmp_path / "tang.db"),
            "--codex-home",
            str(tmp_path / "missing-codex"),
            "--grok-home",
            str(tmp_path / "missing-grok"),
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


def test_doctor_default_path_does_not_create_storage(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    data_home = tmp_path / "data-home"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")

    assert (
        main(
            [
                "doctor",
                "--json",
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
    assert not data_home.exists()


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
