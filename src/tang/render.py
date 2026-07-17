"""Shared Rich renderer for the terminal Multiverse Map."""

from __future__ import annotations

import io
from collections import Counter
from heapq import heapify, heappop, heappush

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tang.graph import GraphEdge, GraphNode, MultiverseGraph
from tang.timeutil import rfc3339


STEEL = "#ff9d3d"
TEAL = "#2aa198"
FORGE = "#171717"

_JUNCTIONS = {
    frozenset(("E", "W")): "─",
    frozenset(("N", "S")): "│",
    frozenset(("E", "S")): "┌",
    frozenset(("W", "S")): "┐",
    frozenset(("E", "N")): "└",
    frozenset(("W", "N")): "┘",
    frozenset(("E", "W", "S")): "┬",
    frozenset(("E", "W", "N")): "┴",
    frozenset(("N", "S", "E")): "├",
    frozenset(("N", "S", "W")): "┤",
    frozenset(("N", "S", "E", "W")): "┼",
}


def _safe(value: str, *, ascii_only: bool) -> str:
    if not ascii_only:
        return value
    return value.encode("ascii", errors="replace").decode("ascii")


def _compact_id(value: str, *, ascii_only: bool) -> str:
    safe = _safe(value, ascii_only=ascii_only)
    if len(safe) <= 18:
        return safe
    return ("..." if ascii_only else "…") + safe[-12:]


def _node_label(node: GraphNode, *, ascii_only: bool) -> Text:
    label = Text()
    active = "* " if ascii_only else "★ "
    label.append(
        active if node.current else "  ",
        style=f"bold {STEEL}" if node.current else "",
    )
    label.append(_compact_id(node.handle, ascii_only=ascii_only), style=f"bold {TEAL}")
    separator = " | " if ascii_only else " · "
    label.append(
        f"{separator}{_safe(node.harness, ascii_only=ascii_only)}", style="white"
    )
    if not node.native_available:
        label.append(
            " | source unavailable" if ascii_only else " · source unavailable",
            style="bold red",
        )
    return label


def _shape(edge: GraphEdge, incoming: Counter[str], outgoing: Counter[str]) -> str:
    labels = []
    if incoming[edge.target_id] > 1:
        labels.append("MERGE")
    if outgoing[edge.source_id] > 1:
        labels.append("BRANCH")
    return " + ".join(labels) or "CONTINUE"


def _node_role(
    source_id: str, incoming: Counter[str], outgoing: Counter[str]
) -> str | None:
    labels = []
    if incoming[source_id] > 1:
        labels.append("MERGE")
    if outgoing[source_id] > 1:
        labels.append("BRANCH")
    return "/".join(labels) or None


def _woven_network(graph: MultiverseGraph, *, width: int) -> Table | None:
    """Lay out a small DAG as deterministic left-to-right terminal rails."""

    nodes = {node.source_id: node for node in graph.nodes}
    order = {node.source_id: index for index, node in enumerate(graph.nodes)}
    parents = {source_id: [] for source_id in nodes}
    children = {source_id: [] for source_id in nodes}
    indegree = {source_id: 0 for source_id in nodes}
    for edge in graph.edges:
        parents[edge.target_id].append(edge.source_id)
        children[edge.source_id].append(edge.target_id)
        indegree[edge.target_id] += 1

    depth = {source_id: 0 for source_id in nodes}
    pending = [
        (order[source_id], source_id)
        for source_id, count in indegree.items()
        if count == 0
    ]
    heapify(pending)
    while pending:
        _, source_id = heappop(pending)
        for target_id in sorted(children[source_id], key=order.__getitem__):
            depth[target_id] = max(depth[target_id], depth[source_id] + 1)
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                heappush(pending, (order[target_id], target_id))

    by_depth: dict[int, list[str]] = {}
    for source_id in nodes:
        by_depth.setdefault(depth[source_id], []).append(source_id)
    y_position: dict[str, int] = {}
    for level in sorted(by_depth):
        group = by_depth[level]
        if level == 0:
            for index, source_id in enumerate(group):
                y_position[source_id] = index * 4
            continue
        desired = {
            source_id: sum(y_position[parent] for parent in parents[source_id])
            / len(parents[source_id])
            for source_id in group
        }
        group.sort(key=lambda source_id: (desired[source_id], order[source_id]))
        target_mean = sum(desired.values()) / len(group)
        base_mean = 2 * (len(group) - 1)
        offset = max(0, round((target_mean - base_mean) / 2) * 2)
        for index, source_id in enumerate(group):
            y_position[source_id] = offset + index * 4

    labels = {
        source_id: (
            f"★{node.handle}"
            if node.current
            else f"×{node.handle}"
            if not node.native_available
            else node.handle
        )
        for source_id, node in nodes.items()
    }
    max_depth = max(depth.values(), default=0)
    canvas_width = max(40, width - 12)
    max_label = max(map(len, labels.values()), default=2)
    available_step = (canvas_width - max_label - 1) // max(1, max_depth)
    if max_depth and available_step < max_label + 5:
        return None
    step = min(24, available_step)
    x_position = {source_id: depth[source_id] * step for source_id in nodes}
    connections: dict[tuple[int, int], set[str]] = {}

    def join(
        first: tuple[int, int],
        second: tuple[int, int],
        first_direction: str,
        second_direction: str,
    ) -> None:
        connections.setdefault(first, set()).add(first_direction)
        connections.setdefault(second, set()).add(second_direction)

    def horizontal(start: int, end: int, y: int) -> None:
        for x in range(start, end):
            join((x, y), (x + 1, y), "E", "W")

    def vertical(x: int, start: int, end: int) -> None:
        low, high = sorted((start, end))
        for y in range(low, high):
            join((x, y), (x, y + 1), "S", "N")

    arrows: set[tuple[int, int]] = set()
    for edge in graph.edges:
        source_x = x_position[edge.source_id] + len(labels[edge.source_id]) + 1
        source_y = y_position[edge.source_id]
        target_x = x_position[edge.target_id]
        target_y = y_position[edge.target_id]
        junction_x = target_x - 4
        horizontal(source_x, junction_x, source_y)
        vertical(junction_x, source_y, target_y)
        horizontal(junction_x, target_x - 2, target_y)
        arrows.add((target_x - 2, target_y))

    height = max(y_position.values(), default=0) + 1
    grid = [[" " for _ in range(canvas_width)] for _ in range(height)]
    for (x, y), directions in connections.items():
        if 0 <= x < canvas_width:
            grid[y][x] = _JUNCTIONS.get(frozenset(directions), "─")
    for x, y in arrows:
        if 0 <= x < canvas_width:
            grid[y][x] = "▶"
    for source_id, label in labels.items():
        x = x_position[source_id]
        y = y_position[source_id]
        grid[y][x : x + len(label)] = label

    network = Table.grid(expand=True)
    network.add_column(overflow="crop", no_wrap=True)
    placements = {
        (y_position[source_id], x_position[source_id], labels[source_id]): nodes[
            source_id
        ]
        for source_id in nodes
    }
    for y, cells in enumerate(grid):
        line = "".join(cells).rstrip()
        rendered = Text(line, style=STEEL)
        for (node_y, node_x, label), node in placements.items():
            if node_y != y:
                continue
            style = "bold red" if not node.native_available else f"bold {TEAL}"
            rendered.stylize(style, node_x, node_x + len(label))
        network.add_row(rendered)
    return network


def render_multiverse(
    graph: MultiverseGraph,
    *,
    width: int = 100,
    color: bool = True,
    ascii_only: bool = False,
) -> str:
    """Render one deterministic graph card for CLI and skill use."""

    buffer = io.StringIO()
    console = Console(
        file=buffer,
        width=width,
        force_terminal=color,
        color_system="truecolor" if color else None,
        legacy_windows=False,
    )
    nodes = {node.source_id: node for node in graph.nodes}
    incoming = Counter(edge.target_id for edge in graph.edges)
    outgoing = Counter(edge.source_id for edge in graph.edges)
    connector = "-->" if ascii_only else "──▶"
    panel_box = box.ASCII if ascii_only else box.ROUNDED
    table_box = box.ASCII if ascii_only else box.HEAVY_HEAD

    if width >= 100 and not ascii_only and graph.edges and graph.timelines:
        network_title = (
            f"TIMELINE LANES · FIRST {len(graph.timelines)} ROOT-TO-LEAF PATHS "
            "(MORE OMITTED)"
            if graph.timelines_truncated
            else f"TIMELINE LANES · {len(graph.timelines)} ROOT-TO-LEAF PATHS"
        )
        network = Table.grid(expand=True, padding=(0, 1))
        network.add_column(style=f"bold {STEEL}", no_wrap=True)
        network.add_column(overflow="fold")
        for index, timeline in enumerate(graph.timelines, start=1):
            lane = Text()
            for offset, source_id in enumerate(timeline):
                if offset:
                    lane.append(f" {connector} ", style=STEEL)
                lane.append_text(_node_label(nodes[source_id], ascii_only=False))
                role = _node_role(source_id, incoming, outgoing)
                if role:
                    lane.append(f" [{role}]", style="bold")
            network.add_row(f"LANE {index:02}", lane)
    elif width < 64:
        network_title = "CONFIRMED EDGES"
        network = Table.grid(expand=True)
        network.add_column(overflow="fold")
        if graph.edges:
            for edge in graph.edges:
                line = _node_label(nodes[edge.source_id], ascii_only=ascii_only)
                line.append(f" {connector} ", style=STEEL)
                line.append_text(
                    _node_label(nodes[edge.target_id], ascii_only=ascii_only)
                )
                line.append(f" [{_shape(edge, incoming, outgoing)}]", style="bold")
                network.add_row(line)
        else:
            line = _node_label(graph.nodes[0], ascii_only=ascii_only)
            line.append(" [ISOLATED]", style="bold")
            network.add_row(line)
    else:
        network_title = "CONFIRMED EDGES"
        network = Table.grid(padding=(0, 1))
        network.add_column(no_wrap=True)
        network.add_column(style=STEEL, justify="center", no_wrap=True)
        network.add_column(no_wrap=True)
        network.add_column(style="bold", no_wrap=True)
        if graph.edges:
            for edge in graph.edges:
                network.add_row(
                    _node_label(nodes[edge.source_id], ascii_only=ascii_only),
                    connector,
                    _node_label(nodes[edge.target_id], ascii_only=ascii_only),
                    _shape(edge, incoming, outgoing),
                )
        else:
            network.add_row(
                _node_label(graph.nodes[0], ascii_only=ascii_only),
                "",
                "",
                "ISOLATED",
            )

    if width < 80:
        details = Table.grid(expand=True)
        details.add_column(overflow="fold")
        for node in graph.nodes:
            item = Text(overflow="fold")
            item.append("[ACTIVE] " if node.current else "", style=f"bold {STEEL}")
            item.append(
                f"HANDLE {_safe(node.handle, ascii_only=ascii_only)}",
                style=f"bold {TEAL}",
            )
            item.append(
                f" | HARNESS {_safe(node.harness, ascii_only=ascii_only)}"
                f" | UTC {rfc3339(node.updated_at)}"
                f" | HEALTH {node.health.value}\n"
                f"TITLE {_safe(node.title or '(untitled)', ascii_only=ascii_only)}"
            )
            details.add_row(item)
    else:
        details = Table(
            show_header=True,
            header_style=f"bold {STEEL}",
            expand=True,
            box=table_box,
        )
        details.add_column("HANDLE", no_wrap=True)
        details.add_column("HARNESS", no_wrap=True)
        details.add_column("UTC", no_wrap=True)
        details.add_column("HEALTH", no_wrap=True)
        details.add_column("TITLE", overflow="fold")
        for node in graph.nodes:
            details.add_row(
                f"{'ACTIVE ' if node.current else ''}{node.handle}",
                node.harness,
                rfc3339(node.updated_at),
                node.health.value,
                _safe(node.title or "(untitled)", ascii_only=ascii_only),
                style=f"bold {TEAL}" if node.current else None,
            )

    body = Table.grid(expand=True)
    if width >= 100 and not ascii_only and graph.edges:
        woven = _woven_network(graph, width=width)
        if woven is not None:
            body.add_row(
                Panel(
                    woven,
                    title="[bold]MULTIVERSE NETWORK · TIME FLOWS →[/bold]",
                    border_style=STEEL,
                    box=panel_box,
                )
            )
    body.add_row(
        Panel(
            network,
            title=f"[bold]{network_title}[/bold]",
            border_style=TEAL,
            box=panel_box,
        )
    )
    body.add_row(
        Panel(
            details,
            title="[bold]SESSION DETAIL[/bold]",
            border_style=STEEL,
            box=panel_box,
        )
    )
    card = Panel(
        body,
        title="[bold]TANG MULTIVERSE MAP[/bold]",
        subtitle=(
            "confirmed only | [ACTIVE]"
            if ascii_only
            else "confirmed only · ★ active"
        ),
        border_style=STEEL,
        style=f"on {FORGE}" if color else "none",
        box=panel_box,
    )
    console.print(card)
    return buffer.getvalue()
