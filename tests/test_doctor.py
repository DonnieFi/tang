from __future__ import annotations

import json
from pathlib import Path

from tang.cli import main


def test_doctor_reports_ready_components_deterministically(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    codex = tmp_path / "codex"
    grok = tmp_path / "grok"
    (codex / "sessions").mkdir(parents=True)
    (grok / "sessions").mkdir(parents=True)
    monkeypatch.setattr("tang.doctor.shutil.which", lambda command: "/bin/tang")

    result = main(
        [
            "doctor",
            "--json",
            "--database",
            str(tmp_path / "data" / "tang.db"),
            "--codex-home",
            str(codex),
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
    assert "cli: unavailable" in captured.out
    assert "Install the tang-multiverse CLI" in captured.out
    assert "codex: unavailable" in captured.out
    assert "grok: unavailable" in captured.out
