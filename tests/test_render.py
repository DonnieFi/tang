from __future__ import annotations

from datetime import datetime, timezone

from tang.adapters import SessionHealth
from tang.graph import GraphEdge, GraphNode, MultiverseGraph
from tang.render import render_multiverse


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def node(native_id: str, harness: str = "codex", *, current: bool = False) -> GraphNode:
    prefix = {"codex": "C", "grok": "G", "opencode": "O"}[harness]
    return GraphNode(
        f"{harness}:map:{native_id}",
        f"{prefix}{ord(native_id[0])}",
        harness,
        native_id,
        f"Title {native_id.upper()}",
        NOW,
        SessionHealth.COMPLETE,
        True,
        current,
    )


def hero() -> MultiverseGraph:
    nodes = (
        node("a", "grok"),
        node("b"),
        node("c"),
        node("d"),
        node("e"),
        node("f", "grok"),
        node("g", current=True),
    )
    by_id = {item.native_id: item.source_id for item in nodes}
    pairs = (("a", "c"), ("b", "c"), ("c", "d"), ("c", "e"), ("e", "g"), ("f", "g"))
    edges = tuple(
        GraphEdge(by_id[source], by_id[target], NOW) for source, target in pairs
    )
    timelines = tuple(
        tuple(by_id[native_id] for native_id in path)
        for path in ("acd", "aceg", "bcd", "bceg", "fg")
    )
    return MultiverseGraph("project", nodes, edges, timelines)


def test_hero_renderer_shows_connected_branch_merge_and_active_handle() -> None:
    rendered = render_multiverse(hero(), width=120, color=False)
    assert rendered == render_multiverse(hero(), width=120, color=False)
    assert "TANG MULTIVERSE MAP" in rendered
    assert "MULTIVERSE NETWORK · TIME FLOWS →" in rendered
    assert "G97 ────────────────┐" in rendered
    assert "├─▶ C99" in rendered
    assert "└─▶ C101" in rendered
    assert "├─▶ ★C103" in rendered
    assert "TIMELINE LANES · 5 ROOT-TO-LEAF PATHS" in rendered
    assert rendered.count("LANE ") == 5
    assert rendered.count("──▶") == 11
    assert "MERGE" in rendered
    assert "BRANCH" in rendered
    assert "★ C103 · codex" in rendered
    assert "ACTIVE C103" in rendered
    assert "Title G" in rendered
    assert "codex:map:g" not in rendered


def test_isolated_renderer_is_truthful() -> None:
    isolated = MultiverseGraph("project", (node("h"),), (), (("codex:map:h",),))
    rendered = render_multiverse(isolated, width=100, color=False)
    assert "ISOLATED" in rendered
    assert "confirmed only" in rendered


def test_linear_renderer_keeps_direction_obvious() -> None:
    first = node("first", "grok")
    second = node("second")
    linear = MultiverseGraph(
        "project",
        (first, second),
        (GraphEdge(first.source_id, second.source_id, NOW),),
        ((first.source_id, second.source_id),),
    )

    rendered = render_multiverse(linear, width=90, color=False)
    assert "G102 · grok" in rendered
    assert "──▶" in rendered
    assert "C115 · codex" in rendered
    assert "CONTINUE" in rendered


def test_renderer_labels_an_active_opencode_destination_honestly() -> None:
    source = node("source", "grok")
    target = node("target", "opencode", current=True)
    graph = MultiverseGraph(
        "project",
        (source, target),
        (GraphEdge(source.source_id, target.source_id, NOW),),
        ((source.source_id, target.source_id),),
    )

    rendered = render_multiverse(graph, width=90, color=False)

    assert "O116 · opencode" in rendered
    assert "ACTIVE O116" in rendered


def test_color_no_color_narrow_and_ascii_snapshots() -> None:
    graph = hero()
    color = render_multiverse(graph, width=100, color=True)
    no_color = render_multiverse(graph, width=100, color=False)
    narrow = render_multiverse(graph, width=48, color=False)
    ascii_rendered = render_multiverse(graph, width=40, color=False, ascii_only=True)

    assert "\x1b[" in color
    assert "\x1b[" not in no_color
    assert "MULTIVERSE NETWORK" in no_color
    assert color == render_multiverse(graph, width=100, color=True)
    assert no_color == render_multiverse(graph, width=100, color=False)
    assert narrow == render_multiverse(graph, width=48, color=False)
    assert all(
        label in narrow for label in ("HANDLE", "HARNESS", "UTC", "HEALTH", "TITLE")
    )
    assert "[ACTIVE]" in narrow
    assert "MULTIVERSE NETWORK" not in narrow
    assert ascii_rendered.isascii()
    assert "-->" in ascii_rendered
    assert "[ACTIVE]" in ascii_rendered
    assert "MULTIVERSE NETWORK" not in ascii_rendered
    assert ascii_rendered == render_multiverse(
        graph, width=40, color=False, ascii_only=True
    )
