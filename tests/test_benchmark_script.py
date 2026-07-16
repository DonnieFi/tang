from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_refresh_benchmark_emits_reproducible_project_local_evidence(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_refresh.py",
            "--sessions",
            "4",
            "--payload-bytes",
            "256",
            "--work-dir",
            str(tmp_path / "benchmark"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert document["schema_version"] == 1
    assert document["corpus"]["sessions"] == 4
    assert document["results"] == {
        "browse_results": 4,
        "cold_indexed": 4,
        "graph_edges": 3,
        "graph_nodes": 4,
        "incremental_indexed": 1,
        "search_results": 4,
        "unchanged_indexed": 0,
    }
    assert document["database"]["path"] == ".tang/tang.db"
    assert document["database"]["journal_mode"] == "wal"
    assert document["database"]["integrity_check"] == "ok"
    assert document["database"]["concurrent_read_during_immediate_write"] is True
    assert document["query_plans"]["browse"]
    assert document["query_plans"]["search"]


def test_refresh_benchmark_refuses_a_nonempty_work_directory(tmp_path: Path) -> None:
    work = tmp_path / "benchmark"
    work.mkdir()
    sentinel = work / "keep.txt"
    sentinel.write_text("unchanged", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/benchmark_refresh.py",
            "--work-dir",
            str(work),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "must be absent or empty" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
