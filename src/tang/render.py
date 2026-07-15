"""Shared Rich renderer for the terminal Multiverse Map."""

from __future__ import annotations

import io
from collections import Counter

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tang.graph import GraphEdge, GraphNode, MultiverseGraph


STEEL = "#ff9d3d"
TEAL = "#2aa198"
FORGE = "#171717"


def _node_label(node: GraphNode) -> Text:
    label = Text()
    label.append("★ " if node.current else "  ", style=f"bold {STEEL}" if node.current else "")
    label.append(node.native_id, style=f"bold {TEAL}")
    label.append(f" · {node.harness}", style="white")
    if not node.native_available:
        label.append(" · source unavailable", style="bold red")
    return label


def _shape(edge: GraphEdge, incoming: Counter[str], outgoing: Counter[str]) -> str:
    labels = []
    if incoming[edge.target_id] > 1:
        labels.append("MERGE")
    if outgoing[edge.source_id] > 1:
        labels.append("BRANCH")
    return " + ".join(labels) or "CONTINUE"


def render_multiverse(
    graph: MultiverseGraph,
    *,
    width: int = 100,
    color: bool = True,
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

    network = Table.grid(padding=(0, 1))
    network.add_column(no_wrap=True)
    network.add_column(style=STEEL, justify="center", no_wrap=True)
    network.add_column(no_wrap=True)
    network.add_column(style="bold", no_wrap=True)
    if graph.edges:
        for edge in graph.edges:
            network.add_row(
                _node_label(nodes[edge.source_id]),
                "──▶",
                _node_label(nodes[edge.target_id]),
                _shape(edge, incoming, outgoing),
            )
    else:
        network.add_row(_node_label(graph.nodes[0]), "", "", "ISOLATED")

    details = Table(show_header=True, header_style=f"bold {STEEL}", expand=True)
    details.add_column("HANDLE", no_wrap=True)
    details.add_column("UTC", no_wrap=True)
    details.add_column("HEALTH", no_wrap=True)
    details.add_column("TITLE")
    details.add_column("SOURCE ID")
    for node in graph.nodes:
        details.add_row(
            f"{'ACTIVE ' if node.current else ''}{node.harness}",
            node.updated_at.isoformat().replace("+00:00", "Z"),
            node.health.value,
            node.title or "(untitled)",
            node.source_id,
            style=f"bold {TEAL}" if node.current else None,
        )

    body = Table.grid(expand=True)
    body.add_row(Panel(network, title="[bold]CONFIRMED NETWORK[/bold]", border_style=TEAL))
    body.add_row(Panel(details, title="[bold]SESSION DETAIL[/bold]", border_style=STEEL))
    card = Panel(
        body,
        title="[bold]TANG MULTIVERSE MAP[/bold]",
        subtitle="confirmed continuations only · ★ active handle",
        border_style=STEEL,
        style=f"on {FORGE}" if color else "none",
    )
    console.print(card)
    return buffer.getvalue()
