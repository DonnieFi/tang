from __future__ import annotations

from datetime import datetime, timezone

from tang.adapters import SessionHealth
from tang.graph import GraphEdge, GraphNode, MultiverseGraph
from tang.render import render_multiverse


NOW = datetime(2026, 7, 15, tzinfo=timezone.utc)


def node(native_id: str, harness: str = "codex", *, current: bool = False) -> GraphNode:
    return GraphNode(
        f"{harness}:map:{native_id}",
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
        node("a", "grok"), node("b"), node("c"), node("d"),
        node("e"), node("f", "grok"), node("g", current=True),
    )
    by_id = {item.native_id: item.source_id for item in nodes}
    pairs = (("a", "c"), ("b", "c"), ("c", "d"), ("c", "e"), ("e", "g"), ("f", "g"))
    edges = tuple(GraphEdge(by_id[source], by_id[target], NOW) for source, target in pairs)
    return MultiverseGraph("project", nodes, edges, ())


def test_hero_renderer_shows_connected_branch_merge_and_active_handle() -> None:
    rendered = render_multiverse(hero(), width=120, color=False)
    assert rendered == render_multiverse(hero(), width=120, color=False)
    assert "TANG MULTIVERSE MAP" in rendered
    assert rendered.count("──▶") == 6
    assert "MERGE" in rendered
    assert "BRANCH" in rendered
    assert "★ g · codex" in rendered
    assert "ACTIVE codex" in rendered
    assert "Title G" in rendered
    assert "codex:map:g" in rendered


def test_isolated_renderer_is_truthful() -> None:
    isolated = MultiverseGraph("project", (node("h"),), (), (("codex:map:h",),))
    rendered = render_multiverse(isolated, width=100, color=False)
    assert "ISOLATED" in rendered
    assert "confirmed continuations only" in rendered


def test_linear_renderer_keeps_direction_obvious() -> None:
    first = node("first", "grok")
    second = node("second")
    linear = MultiverseGraph(
        "project",
        (first, second),
        (GraphEdge(first.source_id, second.source_id, NOW),),
        ((first.source_id, second.source_id),),
    )

    rendered = render_multiverse(linear, width=100, color=False)
    assert "first · grok" in rendered
    assert "──▶" in rendered
    assert "second · codex" in rendered
    assert "CONTINUE" in rendered
