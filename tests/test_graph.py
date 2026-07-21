from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from tang.adapters import (
    OpaqueSourceLocator,
    SessionHealth,
    SessionIdentity,
    SourceFingerprint,
    SourceRecord,
)
from tang.graph import MAX_TIMELINE_LANES, GraphEdge, GraphService
from tang.multiverse_material import load_multiverse_material
from tang.repository import StoredCapsule, StoredContinuation, TangRepository
from tang.continuation_persistence import insert_continuation
from tang.storage import open_database


FIXTURE = Path(__file__).parent / "fixtures" / "graph" / "multiverse.json"


def seeded(tmp_path: Path) -> tuple[object, TangRepository, dict[str, object]]:
    document = json.loads(FIXTURE.read_text())
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    with repository.transaction():
        for node in document["nodes"]:
            identity = SessionIdentity(*node["source_id"].split(":", 2))
            timestamp = datetime.fromisoformat(node["timestamp"].replace("Z", "+00:00"))
            repository.upsert_session(
                SourceRecord(
                    identity=identity,
                    locator=OpaqueSourceLocator(f"fixture:{node['native_id']}"),
                    fingerprint=SourceFingerprint(
                        "sha256", f"fixture-{node['native_id']}"
                    ),
                    project_hint="/fixture/tang",
                    started_at=timestamp,
                    updated_at=timestamp,
                    title=str(node["title"]),
                    health=SessionHealth(node["health"]),
                ),
                document["project_key"],
                timestamp,
            )
        for edge in document["edges"]:
            insert_continuation(repository, 
                StoredContinuation(
                    edge["source_id"],
                    edge["target_id"],
                    document["project_key"],
                    edge["confirmation_mode"],
                    datetime.fromisoformat(edge["confirmed_at"].replace("Z", "+00:00")),
                )
            )
        unavailable = next(
            node["source_id"] for node in document["nodes"] if not node["native_available"]
        )
        repository.delete_session(unavailable)
    return connection, repository, document


def short(path: tuple[str, ...]) -> str:
    return "".join(source_id.rsplit(":", 1)[-1].upper() for source_id in path)


def test_multiverse_component_preserves_every_branch_and_merge_path(tmp_path: Path) -> None:
    connection, repository, document = seeded(tmp_path)
    try:
        graph = GraphService(repository).component(
            "codex:multiverse:c", current_id=document["active_source_id"]
        )
        assert [node.native_id for node in graph.nodes] == list("abcdefg")
        assert len(graph.edges) == 6
        assert [short(path) for path in graph.timelines] == [
            "BCD",
            "BCEG",
            "ACD",
            "ACEG",
            "FG",
        ]
        assert [node.native_id for node in graph.nodes if node.current] == ["g"]
        assert [node.native_id for node in graph.nodes if not node.native_available] == ["f"]
        assert next(node for node in graph.nodes if node.native_id == "f").health == (
            SessionHealth.POSSIBLY_INTERRUPTED
        )
    finally:
        connection.close()


def test_isolated_and_disconnected_components_are_stable(tmp_path: Path) -> None:
    connection, repository, _ = seeded(tmp_path)
    try:
        isolated = GraphService(repository).component("opencode:multiverse:h")
        assert [node.native_id for node in isolated.nodes] == ["h"]
        assert isolated.nodes[0].harness == "opencode"
        assert isolated.nodes[0].title == "OpenCode continuation target"
        assert isolated.edges == ()
        assert [short(path) for path in isolated.timelines] == ["H"]

        connected = GraphService(repository).component("codex:multiverse:d")
        assert "h" not in {node.native_id for node in connected.nodes}
    finally:
        connection.close()


def test_timeline_enumeration_is_iterative_and_bounded() -> None:
    chain_nodes = frozenset(f"chain-{index}" for index in range(1_501))
    chain_edges = tuple(
        GraphEdge(f"chain-{index}", f"chain-{index + 1}", datetime.now().astimezone())
        for index in range(1_500)
    )

    chain_paths, chain_truncated = GraphService._timelines(chain_nodes, chain_edges)

    assert len(chain_paths) == 1
    assert len(chain_paths[0]) == 1_501
    assert not chain_truncated

    nodes = {"root"}
    edges: list[GraphEdge] = []
    prior = "root"
    timestamp = datetime.now().astimezone()
    for level in range(9):
        left = f"left-{level}"
        right = f"right-{level}"
        merge = f"merge-{level}"
        nodes.update((left, right, merge))
        edges.extend(
            (
                GraphEdge(prior, left, timestamp),
                GraphEdge(prior, right, timestamp),
                GraphEdge(left, merge, timestamp),
                GraphEdge(right, merge, timestamp),
            )
        )
        prior = merge

    paths, truncated = GraphService._timelines(frozenset(nodes), tuple(edges))

    assert len(paths) == MAX_TIMELINE_LANES
    assert truncated


def test_graph_title_is_redacted_again_at_the_display_seam(tmp_path: Path) -> None:
    connection, repository, document = seeded(tmp_path)
    source_id = "codex:multiverse:c"
    content = {
        "schema_version": 1,
        "source_title": 'Release PASSWORD="graph-display-secret"',
    }
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    timestamp = datetime.fromisoformat("2026-07-14T20:10:00+00:00")
    try:
        with repository.transaction():
            repository.put_capsule(
                StoredCapsule(
                    source_id,
                    document["project_key"],
                    content,
                    "display seam fixture",
                    len(encoded),
                    timestamp,
                )
            )

        statements: list[str] = []
        connection.set_trace_callback(statements.append)
        graph = GraphService(repository).component(source_id)
        connection.set_trace_callback(None)
        title = next(node.title for node in graph.nodes if node.source_id == source_id)
        assert title == "Release PASSWORD=[REDACTED:credential]"
        assert "graph-display-secret" not in str(title)
        assert sum("LEFT JOIN capsules AS c" in statement for statement in statements) == 1
        assert not any("SELECT * FROM capsules" in statement for statement in statements)
    finally:
        connection.close()


def test_graph_uses_redacted_capsule_display_name_when_native_title_is_absent(
    tmp_path: Path,
) -> None:
    connection, repository, document = seeded(tmp_path)
    source_id = "codex:multiverse:c"
    content = {"schema_version": 1, "display_name": "Derived recovery title"}
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    timestamp = datetime.fromisoformat("2026-07-14T20:10:00+00:00")
    try:
        with repository.transaction():
            connection.execute("UPDATE sessions SET title = NULL WHERE source_id = ?", (source_id,))
            repository.put_capsule(
                StoredCapsule(
                    source_id,
                    document["project_key"],
                    content,
                    "display fallback fixture",
                    len(encoded),
                    timestamp,
                )
            )

        graph = GraphService(repository).component(source_id)
        title = next(node.title for node in graph.nodes if node.source_id == source_id)
        assert title == "Derived recovery title"
    finally:
        connection.close()


def test_multiverse_material_feeds_graph_without_extra_title_queries(
    tmp_path: Path,
) -> None:
    connection, repository, document = seeded(tmp_path)
    try:
        graph = GraphService(repository).component("codex:multiverse:c")
        component_ids = frozenset(node.source_id for node in graph.nodes)
        material = load_multiverse_material(
            repository, document["project_key"], component_ids
        )
        by_id = {node.source_id: node.title for node in graph.nodes}
        assert len(material.nodes) == len(graph.nodes)
        for node in material.nodes:
            assert node.display_title
            assert by_id[node.source_id] is not None
    finally:
        connection.close()
