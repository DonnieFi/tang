"""Reproducible, temporary-data-only Tang demonstration."""

from __future__ import annotations

import io
import json
import shutil
import sysconfig
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.graph import GraphService
from tang.project import resolve_project
from tang.render import render_multiverse
from tang.repository import StoredCapsule, StoredContinuation, TangRepository
from tang.storage import open_database


def _fixture_root() -> Path:
    source = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    if source.is_dir():
        return source
    installed = Path(sysconfig.get_path("data")) / "share" / "tang" / "demo"
    if installed.is_dir():
        return installed
    raise FileNotFoundError("Tang's bundled demo fixtures are unavailable")


def _canonical_json(value: dict[str, object]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _prepare_native_corpus(root: Path, project: Path) -> tuple[Path, Path]:
    fixtures = _fixture_root()
    codex_home = root / "codex"
    grok_home = root / "grok"
    shutil.copytree(fixtures / "codex", codex_home)
    shutil.copytree(fixtures / "grok", grok_home)
    destination = codex_home / "sessions" / "2026" / "07" / "14"
    for template in sorted((fixtures / "discovery" / "codex-extra").iterdir()):
        shutil.copy2(template, destination / template.name.removesuffix(".partial"))

    for path in (codex_home / "sessions").rglob("*.jsonl"):
        lines = path.read_text(encoding="utf-8").splitlines()
        metadata = json.loads(lines[0])
        metadata["payload"]["cwd"] = str(project)
        lines[0] = json.dumps(metadata, separators=(",", ":"))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = next((grok_home / "sessions").rglob("summary.json"))
    payload = json.loads(summary.read_text(encoding="utf-8"))
    payload["git_root_dir"] = str(project)
    summary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return codex_home, grok_home


def _call_cli(arguments: list[str]) -> tuple[int, str, str]:
    from tang.cli import main

    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(arguments)
    return code, stdout.getvalue(), stderr.getvalue()


def _seed_graph(database: Path, project: Path) -> tuple[str, str]:
    document = json.loads(
        (_fixture_root() / "graph" / "multiverse.json").read_text(encoding="utf-8")
    )
    project_key = resolve_project(project).key
    connection = open_database(database)
    repository = TangRepository(connection)
    try:
        with repository.transaction():
            for node in document["nodes"]:
                identity = SessionIdentity.from_canonical(node["source_id"])
                timestamp = datetime.fromisoformat(
                    node["timestamp"].replace("Z", "+00:00")
                )
                repository.upsert_session(
                    SourceRecord(
                        identity,
                        OpaqueSourceLocator(f"demo:{node['native_id']}"),
                        SourceFingerprint("sha256", f"demo-{node['native_id']}"),
                        str(project),
                        timestamp,
                        timestamp,
                        SessionHealth(node["health"]),
                    ),
                    project_key,
                    timestamp,
                )
                content = {
                    "schema_version": 1,
                    "source_title": node["title"],
                }
                repository.put_capsule(
                    StoredCapsule(
                        node["source_id"],
                        project_key,
                        content,
                        str(node["title"]),
                        len(_canonical_json(content)),
                        timestamp,
                    )
                )
            for edge in document["edges"]:
                repository.put_continuation(
                    StoredContinuation(
                        edge["source_id"],
                        edge["target_id"],
                        project_key,
                        edge["confirmation_mode"],
                        datetime.fromisoformat(
                            edge["confirmed_at"].replace("Z", "+00:00")
                        ),
                    )
                )
            unavailable = next(
                node["source_id"]
                for node in document["nodes"]
                if not node["native_available"]
            )
            repository.delete_session(unavailable)
    finally:
        connection.close()
    return "codex:multiverse:g", "codex:multiverse:h"


def run_demo(*, width: int, color: bool, ascii_only: bool) -> int:
    """Run the complete demo against a disposable database and corpus copy."""

    with TemporaryDirectory(prefix="tang-demo-") as temporary:
        root = Path(temporary)
        project = root / "project"
        project.mkdir()
        database = root / "data" / "tang.db"
        codex_home, grok_home = _prepare_native_corpus(root, project)
        common = ["--database", str(database), "--cwd", str(project)]
        adapters = [
            "--codex-home",
            str(codex_home),
            "--grok-home",
            str(grok_home),
        ]

        index_code, index_output, _ = _call_cli(
            ["index", *common, *adapters, "--json"]
        )
        if index_code not in {0, 1}:
            return 2
        index = json.loads(index_output)
        _, search_output, _ = _call_cli(
            ["search", "checkpoint", *common, "--json"]
        )
        results = json.loads(search_output)["results"]
        selected = (
            next(item["source_id"] for item in results if item["harness"] == "grok"),
            next(item["source_id"] for item in results if item["harness"] == "codex"),
        )
        context_code, context_output, _ = _call_cli(
            ["context", *selected, *common, *adapters, "--json"]
        )
        if context_code != 0:
            return 2
        context_document = json.loads(context_output)
        context = context_document["untrusted_data_envelope"]

        source, target = _seed_graph(database, project)
        link_code, link_output, _ = _call_cli(
            ["link", "--from", source, "--to", target, *common, "--json"]
        )
        if link_code != 0:
            return 2
        linked = json.loads(link_output)
        connection = open_database(database)
        try:
            graph = GraphService(TangRepository(connection)).component(
                target, current_id=target
            )
        finally:
            connection.close()

        print("TANG ISOLATED DEMO")
        print(f"Workspace: {root}")
        print("Isolation: temporary database + copied synthetic native fixtures")
        print(
            f"INDEX: {index['indexed']} indexed; status {index['status']} "
            f"({index['warning_count']} synthetic-fixture warning(s))"
        )
        print(f"SEARCH: {len(results)} checkpoint matches across Codex and Grok")
        print("SELECT:")
        for source_id in selected:
            item = next(result for result in results if result["source_id"] == source_id)
            print(f"  {item['harness']}:{source_id.rsplit(':', 1)[-1]}")
        print(
            f"CONTEXT: {len(context['sources'])} cited sources; "
            f"estimated tokens {context_document['estimated_tokens']}"
        )
        grok_source = next(
            section for section in context["sources"] if section["harness"] == "grok"
        )
        evidence = next(
            excerpt
            for excerpt in grok_source["excerpts"]
            if "fingerprint" in excerpt["text"]
        )
        citation = evidence["citation"]
        cited = (
            f"[{citation['harness']}:{citation['session_id']} "
            f"{citation['turn_locator']} @ {citation['timestamp']}]"
        )
        print(
            "RESUME POINT: Recover checkpoint state with a content fingerprint "
            f"and opaque checkpoint {cited}"
        )
        print(
            "NEXT ACTION: Continue in the active Codex handle and verify that "
            f"checkpoint invariant {cited}"
        )
        print(
            f"LINK: {', '.join(linked['source_ids'])} -> {linked['target_id']} "
            "(confirmed)"
        )
        print(render_multiverse(graph, width=width, color=color, ascii_only=ascii_only), end="")
        print("Demo complete; temporary data will now be removed.")
    return 0
