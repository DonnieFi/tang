#!/usr/bin/env python3
"""Run Tang's clean-host functional acceptance against synthetic fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TARGET_NATIVE_ID = "019f6000-5678-7000-8000-000000000005"
PRIVATE_SENTINELS = (
    "preview-secret",
    "foreign-quasar-secret",
    "HIDDEN_THOUGHT_CANARY",
    "TOOL_INPUT_CANARY",
)


class AcceptanceFailure(RuntimeError):
    """A release-candidate behavior did not satisfy the acceptance contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): _sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _json(stdout: str, label: str) -> dict[str, Any]:
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError as error:
        raise AcceptanceFailure(f"{label} did not emit valid JSON: {error}") from error
    _require(document.get("schema_version") == 1, f"{label} schema_version is not 1")
    return document


def _prepare_corpus(work: Path) -> tuple[Path, Path, Path, Path]:
    current = work / "current-project"
    foreign = work / "foreign-project"
    codex_home = work / "native" / "codex"
    grok_home = work / "native" / "grok"
    current.mkdir(parents=True)
    foreign.mkdir()
    shutil.copytree(FIXTURES / "codex", codex_home)
    shutil.copytree(FIXTURES / "grok", grok_home)

    destination = codex_home / "sessions" / "2026" / "07" / "14"
    destination.mkdir(parents=True, exist_ok=True)
    for template in sorted((FIXTURES / "discovery" / "codex-extra").iterdir()):
        target = destination / template.name.removesuffix(".partial")
        target.write_text(
            template.read_text(encoding="utf-8").replace(
                "[LONG_SYNTHETIC_3000]", "L" * 3_000
            ),
            encoding="utf-8",
        )

    for path in (codex_home / "sessions").rglob("*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines()
        metadata = json.loads(lines[0])
        original = metadata["payload"]["cwd"]
        metadata["payload"]["cwd"] = str(
            foreign if original == "/work/foreign-vault" else current
        )
        lines[0] = json.dumps(metadata, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    summary = next((grok_home / "sessions").rglob("summary.json"))
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["git_root_dir"] = str(current)
    summary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    secret_log = next(
        path
        for path in (codex_home / "sessions").rglob("*.jsonl")
        if "deterministic checkpoint recovery" in path.read_text(encoding="utf-8")
    )
    secret_log.write_text(
        secret_log.read_text(encoding="utf-8").replace(
            "deterministic checkpoint recovery",
            'credentialmarker PASSWORD="preview-secret" deterministic checkpoint recovery',
        ),
        encoding="utf-8",
    )
    return current, foreign, codex_home, grok_home


def _install_wheel(wheel: Path, work: Path, python: str) -> tuple[Path, Path]:
    uv = shutil.which("uv")
    _require(uv is not None, "uv is required for the clean wheel installation")
    environment = work / "venv"
    subprocess.run(
        [uv, "venv", "--python", python, str(environment)],
        check=True,
        text=True,
    )
    interpreter = environment / "bin" / "python"
    executable = environment / "bin" / "tang"
    subprocess.run(
        [uv, "pip", "install", "--python", str(interpreter), str(wheel)],
        check=True,
        text=True,
    )
    _require(executable.is_file(), "wheel installation did not create the tang command")
    return executable, interpreter


class Runner:
    def __init__(self, executable: Path, environment: dict[str, str]) -> None:
        self.executable = executable
        self.environment = environment
        self.results: list[dict[str, Any]] = []

    def run(
        self,
        label: str,
        arguments: list[str],
        *,
        expected: int | tuple[int, ...] = 0,
        timeout: float = 30,
    ) -> subprocess.CompletedProcess[str]:
        allowed = (expected,) if isinstance(expected, int) else expected
        started = time.perf_counter()
        result = subprocess.run(
            [str(self.executable), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=self.environment,
            timeout=timeout,
        )
        elapsed = time.perf_counter() - started
        self.results.append(
            {
                "command": label,
                "elapsed_seconds": round(elapsed, 3),
                "exit_code": result.returncode,
            }
        )
        if result.returncode not in allowed:
            raise AcceptanceFailure(
                f"{label} exited {result.returncode}, expected {allowed}; "
                f"stdout={result.stdout!r}; stderr={result.stderr!r}"
            )
        combined = result.stdout + result.stderr
        if any(value in combined for value in PRIVATE_SENTINELS):
            raise AcceptanceFailure(f"{label} exposed excluded or private fixture content")
        return result


def run_acceptance(wheel: Path, work: Path, python: str) -> dict[str, Any]:
    _require(platform.system() == "Linux", "the v0.1.0 acceptance host must be Linux")
    _require(sys.version_info >= (3, 11), "the driver requires Python 3.11 or newer")
    _require(wheel.is_file(), f"wheel not found: {wheel}")
    _require(
        wheel.name == "tang_multiverse-0.1.0-py3-none-any.whl",
        "expected the version-pinned v0.1.0 wheel filename",
    )

    current, _foreign, codex_home, grok_home = _prepare_corpus(work)
    native_before = _tree_hashes(work / "native")
    executable, interpreter = _install_wheel(wheel, work, python)
    database = work / "data" / "tang.db"
    skill_home = work / "codex-skill-home"
    environment = {
        **os.environ,
        "HOME": str(work / "home"),
        "XDG_DATA_HOME": str(work / "xdg-data"),
        "NO_COLOR": "1",
        "PYTHONUTF8": "1",
    }
    runner = Runner(executable, environment)
    common = ["--database", str(database), "--cwd", str(current)]
    adapters = ["--codex-home", str(codex_home), "--grok-home", str(grok_home)]

    help_result = runner.run("help", ["--help"])
    _require("source-cited context" in help_result.stdout, "help omitted the product contract")

    index = runner.run("index", ["index", *common, *adapters, "--json"], expected=1)
    index_doc = _json(index.stdout, "index")
    _require(index_doc["status"] == "partial", "fixture index should report partial")
    _require(index_doc["indexed"] == 4, "fixture index should index four current-project sessions")
    _require(index_doc["excluded"] == 1, "fixture index should exclude one foreign session")
    _require(database.is_file(), "index did not create the configured database")
    if os.name == "posix":
        _require(stat.S_IMODE(database.stat().st_mode) == 0o600, "database mode is not 0600")

    repeat = runner.run(
        "index-repeat", ["index", *common, *adapters, "--json"], expected=1
    )
    repeat_doc = _json(repeat.stdout, "repeat index")
    _require(repeat_doc["indexed"] == 0, "repeat index was not incremental")

    search = runner.run(
        "search", ["search", "checkpoint", *common, "--json"], timeout=10
    )
    search_doc = _json(search.stdout, "search")
    results = search_doc["results"]
    _require(
        {item["harness"] for item in results} == {"codex", "grok"},
        "search did not find both harnesses",
    )
    _require(runner.results[-1]["elapsed_seconds"] < 10, "search exceeded 10 seconds")

    selected = [
        next(item["source_id"] for item in results if item["harness"] == harness)
        for harness in ("grok", "codex")
    ]
    context = runner.run(
        "context",
        ["context", *selected, *common, *adapters, "--json"],
        timeout=30,
    )
    pack = _json(context.stdout, "context")
    packed_sources = pack["untrusted_data_envelope"]["sources"]
    _require(
        {section["source_id"] for section in packed_sources} == set(selected),
        "context did not fairly include both selected sources",
    )
    _require(pack["estimated_tokens"] <= 2_000, "context exceeded the 2,000-token budget")
    _require(runner.results[-1]["elapsed_seconds"] < 30, "context exceeded 30 seconds")

    skill = runner.run(
        "skill-install", ["skill", "install", "codex", "--codex-home", str(skill_home)]
    )
    _require("installed" in skill.stdout.lower(), "Codex skill was not installed")
    _require(
        (skill_home / "skills" / "tang" / "SKILL.md").is_file(),
        "installed skill is incomplete",
    )

    target_suffix = TARGET_NATIVE_ID
    link = runner.run(
        "link",
        [
            "link",
            "--from",
            *selected,
            "--current",
            "--current-native-id",
            target_suffix,
            *common,
            "--codex-home",
            str(codex_home),
            "--json",
        ],
    )
    link_doc = _json(link.stdout, "link")
    _require(
        link_doc["source_ids"] == selected,
        "link sources changed from the explicit selection",
    )
    _require(link_doc["target_id"].endswith(TARGET_NATIVE_ID), "link resolved the wrong target")

    ambiguous = runner.run(
        "ambiguous-link-refusal",
        [
            "link",
            "--from",
            *selected,
            "--current",
            *common,
            "--codex-home",
            str(codex_home),
            "--json",
        ],
        expected=2,
    )
    _require(
        "error[target-unconfirmed]" in ambiguous.stderr,
        "ambiguous target was not explicitly refused",
    )

    cycle = runner.run(
        "cycle-refusal",
        ["link", "--from", link_doc["target_id"], "--to", selected[1], *common],
        expected=2,
    )
    _require("error[cycle]" in cycle.stderr, "cycle was not rejected")

    graph = runner.run(
        "graph-wide",
        [
            "graph", link_doc["target_id"], *common, "--codex-home", str(codex_home),
            "--current-native-id", TARGET_NATIVE_ID, "--width", "120",
        ],
    )
    _require("TANG MULTIVERSE MAP" in graph.stdout, "wide graph omitted its title")
    _require(
        graph.stdout.count("──▶") == 2,
        "wide graph did not render both confirmed edges",
    )

    narrow = runner.run(
        "graph-narrow-ascii",
        ["graph", link_doc["target_id"], *common, "--width", "40", "--ascii"],
    )
    _require(narrow.stdout.isascii(), "ASCII graph emitted non-ASCII output")
    _require("TANG MULTIVERSE MAP" in narrow.stdout, "narrow graph omitted its title")

    doctor = runner.run(
        "doctor", ["doctor", "--database", str(database), *adapters, "--json"], expected=1
    )
    doctor_doc = _json(doctor.stdout, "doctor")
    _require(doctor_doc["status"] == "degraded", "partial fixture should make doctor degraded")

    purge = runner.run("purge", ["purge", "--all", "--yes", "--database", str(database)])
    _require(
        "Native harness logs were not modified" in purge.stdout,
        "purge omitted its native-data guarantee",
    )
    browse = runner.run("browse-after-purge", ["browse", *common, "--json"])
    _require(
        _json(browse.stdout, "browse after purge")["results"] == [],
        "purge left derived sessions",
    )
    _require(
        _tree_hashes(work / "native") == native_before,
        "Tang modified synthetic native history",
    )

    core_seconds = sum(
        item["elapsed_seconds"]
        for item in runner.results
        if item["command"] in {"search", "context", "link", "graph-wide"}
    )
    _require(core_seconds < 75, "core recovery-to-continuation flow exceeded 75 seconds")
    installed_python = subprocess.run(
        [str(interpreter), "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "artifact": {"filename": wheel.name, "sha256": _sha256(wheel)},
        "environment": {
            "machine": platform.machine(),
            "platform": platform.platform(),
            "driver_python": platform.python_version(),
            "installed_python": installed_python,
            "tang_executable": str(executable),
        },
        "result": "pass",
        "schema_version": 1,
        "steps": runner.results,
        "timings": {
            "core_flow_seconds": round(core_seconds, 3),
            "context_seconds": next(
                item["elapsed_seconds"]
                for item in runner.results
                if item["command"] == "context"
            ),
            "search_seconds": next(
                item["elapsed_seconds"]
                for item in runner.results
                if item["command"] == "search"
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install a Tang v0.1.0 wheel and run isolated Linux functional acceptance."
    )
    parser.add_argument("wheel", type=Path, help="path to tang_multiverse-0.1.0-py3-none-any.whl")
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python 3.11+ interpreter for the clean environment",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="persistent empty work directory (default: temporary)",
    )
    parser.add_argument("--output", type=Path, help="also write the JSON evidence to this path")
    args = parser.parse_args()

    temporary: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.work_dir is None:
            temporary = tempfile.TemporaryDirectory(prefix="tang-functional-")
            work = Path(temporary.name)
        else:
            work = args.work_dir.expanduser().resolve()
            _require(not work.exists() or not any(work.iterdir()), "--work-dir must be empty")
            work.mkdir(parents=True, exist_ok=True)
        report = run_acceptance(args.wheel.expanduser().resolve(), work, args.python)
        rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.expanduser().resolve().write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0
    except (AcceptanceFailure, OSError, subprocess.SubprocessError) as error:
        print(f"functional acceptance failed: {error}", file=sys.stderr)
        return 1
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
