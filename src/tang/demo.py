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
from tang.continuation import ContinuationService
from tang.graph import GraphService
from tang.project import resolve_project
from tang.render import render_multiverse
from tang.repository import StoredCapsule, TangRepository
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


def _seed_graph(
    database: Path, project: Path, selected: tuple[str, str]
) -> tuple[str, str, dict[str, str]]:
    """Extend selected recovery sources through the validated fixture DAG."""

    document = json.loads(
        (_fixture_root() / "graph" / "multiverse.json").read_text(encoding="utf-8")
    )
    replacements = {
        "grok:multiverse:a": selected[0],
        "codex:multiverse:b": selected[1],
    }

    def mapped(source_id: str) -> str:
        return replacements.get(source_id, source_id)

    project_key = resolve_project(project).key
    connection = open_database(database)
    repository = TangRepository(connection)
    try:
        with repository.transaction():
            for node in document["nodes"]:
                if node["source_id"] in replacements:
                    source_id = mapped(node["source_id"])
                    capsule = repository.get_capsule(source_id)
                    if capsule is None:
                        raise RuntimeError(
                            f"selected demo source has no capsule: {source_id}"
                        )
                    display_name = capsule.content.get("display_name")
                    if not isinstance(display_name, str) or not display_name.strip():
                        raise RuntimeError(
                            f"selected demo source has no display name: {source_id}"
                        )
                    content = dict(capsule.content)
                    content["source_title"] = display_name
                    content["source_title_truncated"] = bool(
                        content.get("display_name_truncated", False)
                    )
                    repository.put_capsule(
                        StoredCapsule(
                            source_id=source_id,
                            project_key=capsule.project_key,
                            content=content,
                            search_text=capsule.search_text,
                            byte_count=len(_canonical_json(content)),
                            updated_at=capsule.updated_at,
                        )
                    )
                    continue
                identity = SessionIdentity.from_canonical(node["source_id"])
                timestamp = datetime.fromisoformat(
                    node["timestamp"].replace("Z", "+00:00")
                )
                repository.upsert_session(
                    SourceRecord(
                        identity=identity,
                        locator=OpaqueSourceLocator(f"demo:{node['native_id']}"),
                        fingerprint=SourceFingerprint(
                            "sha256", f"demo-{node['native_id']}"
                        ),
                        project_hint=str(project),
                        started_at=timestamp,
                        updated_at=timestamp,
                        title=str(node["title"]),
                        health=SessionHealth(node["health"]),
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
        grouped: dict[tuple[str, str, datetime], list[str]] = {}
        for edge in document["edges"]:
            key = (
                mapped(edge["target_id"]),
                edge["confirmation_mode"],
                datetime.fromisoformat(edge["confirmed_at"].replace("Z", "+00:00")),
            )
            grouped.setdefault(key, []).append(mapped(edge["source_id"]))
        continuation = ContinuationService(repository)
        for (target_id, mode, confirmed_at), source_ids in grouped.items():
            continuation.link(
                tuple(source_ids), target_id, project_key, mode, confirmed_at
            )
        with repository.transaction():
            unavailable = next(
                mapped(node["source_id"])
                for node in document["nodes"]
                if not node["native_available"]
            )
            repository.delete_session(unavailable)
        graph_ids = {
            mapped(node["source_id"])
            for node in document["nodes"]
        }
        handles = {
            source_id: repository.handle_for_source_id(source_id)
            for source_id in graph_ids
        }
    finally:
        connection.close()
    return "codex:multiverse:g", "opencode:multiverse:h", handles


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

        source, target, handles = _seed_graph(database, project, selected)
        link_code, link_output, _ = _call_cli(
            [
                "link",
                "--from",
                handles[source],
                "--to",
                handles[target],
                *common,
                "--json",
            ]
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
            f"({index['warning_count']} warning(s))"
        )
        print(f"SEARCH: {len(results)} checkpoint matches across Codex and Grok")
        print("SELECT:")
        for source_id in selected:
            item = next(result for result in results if result["source_id"] == source_id)
            print(
                f"  {item['session_handle']} | {item['harness']} | "
                f"{item['display_name']}"
            )
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
            "NEXT ACTION: Continue in the confirmed OpenCode handle and verify "
            f"that checkpoint invariant {cited}"
        )
        print(
            "MULTIVERSE: selected sources "
            f"{handles[selected[0]]} + {handles[selected[1]]} merge into "
            f"{handles['codex:multiverse:c']}; that work branches to "
            f"{handles['codex:multiverse:d']} and {handles['codex:multiverse:e']}, "
            f"then {handles['codex:multiverse:e']} + "
            f"{handles['grok:multiverse:f']} merge into {handles[source]}, then "
            f"continue into confirmed OpenCode {handles[target]}."
        )
        print(
            f"LINK: {handles[source]} -> {handles[target]} "
            f"(confirmed; inserted {linked['inserted']})"
        )
        print(render_multiverse(graph, width=width, color=color, ascii_only=ascii_only), end="")
        print("Demo complete; temporary data will now be removed.")
    return 0
