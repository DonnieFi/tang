"""Responsive terminal session cards (discovery scan, Option B + branch)."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from tang.adapters import SessionHealth
from tang.discovery import DiscoveryItem
from tang.health import health_label
from tang.render import STEEL, TEAL
from tang.textutil import (
    compose_visible_row,
    fit_visible,
    middle_elide,
    pad_visible,
    truncate_end,
    visible_width,
)

MIN_CARD_WIDTH = 38
MAX_CARD_WIDTH = 42
CARD_GAP = 2
CARD_FOOTER_LINES = 3
DEFAULT_CARDS_LIMIT = 12

_CAPABILITY_LABELS = {
    "native-reread": "native reread",
    "visible-user-agent-turns": "visible turns",
}


@dataclass(frozen=True, slots=True)
class SessionCard:
    """Thin renderer-facing projection of a discovery item (not persisted)."""

    handle: str
    harness: str
    title: str
    snippet: str | None
    updated_at: datetime
    updated_relative: str
    health: SessionHealth
    capabilities: tuple[str, ...]
    model_provider: str | None
    model_id: str | None
    effort: str | None
    visible_turn_count: int | None
    git_branch: str | None
    native_available: bool
    warning: str | None = None


def relative_age(then: datetime, *, now: datetime | None = None) -> str:
    """Compact relative age for card status rows (``14m``, ``2h``, ``3d``)."""

    clock = now or datetime.now(timezone.utc)
    if then.tzinfo is None or then.utcoffset() is None:
        raise ValueError("relative_age requires a timezone-aware timestamp")
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("relative_age clock must be timezone-aware")
    seconds = int((clock.astimezone(timezone.utc) - then.astimezone(timezone.utc)).total_seconds())
    if seconds < 0:
        seconds = 0
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    days = seconds // 86400
    if days < 14:
        return f"{days}d"
    weeks = days // 7
    if weeks < 9:
        return f"{weeks}w"
    return f"{days // 30}mo"


def current_git_branch(cwd: Path | None = None) -> str | None:
    """Return the current HEAD branch name for the grid header, or None."""

    from tang.adapters.base import _header_value

    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=cwd or Path.cwd(),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    branch = result.stdout.strip()
    if not branch or branch == "HEAD":
        return None
    return _header_value(branch)


def project_basename(cwd: Path | None = None) -> str:
    """Basename used once in the cards grid header."""

    path = (cwd or Path.cwd()).resolve()
    return path.name or str(path)


def session_card_from_item(
    item: DiscoveryItem,
    *,
    now: datetime | None = None,
) -> SessionCard:
    """Project a redacted discovery item into a SessionCard."""

    warning = None if item.native_available else "source unavailable"
    return SessionCard(
        handle=item.handle,
        harness=item.harness,
        title=item.display_name or item.title or f"{item.harness} session",
        snippet=item.snippet,
        updated_at=item.updated_at,
        updated_relative=relative_age(item.updated_at, now=now),
        health=item.health,
        capabilities=item.capabilities,
        model_provider=item.model_provider,
        model_id=item.model_id,
        effort=item.effort,
        visible_turn_count=item.visible_turn_count,
        git_branch=item.git_branch,
        native_available=item.native_available,
        warning=warning,
    )


def column_count(terminal_width: int) -> int:
    if terminal_width < MIN_CARD_WIDTH:
        return 1
    return max(1, (terminal_width + CARD_GAP) // (MIN_CARD_WIDTH + CARD_GAP))


def card_width(terminal_width: int, columns: int) -> int:
    columns = max(1, columns)
    total_gaps = (columns - 1) * CARD_GAP
    available = max(MIN_CARD_WIDTH, (terminal_width - total_gaps) // columns)
    return min(MAX_CARD_WIDTH, available)


def render_cards_grid(
    cards: tuple[SessionCard, ...] | list[SessionCard],
    *,
    width: int = 100,
    color: bool = True,
    ascii_only: bool = False,
    project_name: str | None = None,
    current_branch: str | None = None,
) -> str:
    """Render Option B cards with herdr-style row-aligned footers."""

    if not cards:
        return "No indexed sessions.\n"

    theme = _CardTheme(color=color and not ascii_only, ascii_only=ascii_only)
    columns = column_count(width)
    card_w = card_width(width, columns)
    chunks: list[str] = []

    header = _grid_header(project_name, current_branch, theme)
    if header:
        chunks.append(header)
        chunks.append("")

    card_list = list(cards)
    for row_start in range(0, len(card_list), columns):
        row_cards = card_list[row_start : row_start + columns]
        rendered = [
            _split_card_lines(_render_session_card(card, card_w, theme))
            for card in row_cards
        ]
        max_body = max((len(body) for body, _ in rendered), default=0)
        row_height = max_body + CARD_FOOTER_LINES
        ellipsis = _ellipsis(theme)
        for line_index in range(row_height):
            parts: list[str] = []
            for body, footer in rendered:
                if line_index < len(body):
                    parts.append(
                        _normalize_card_line(body[line_index], card_w, ellipsis=ellipsis)
                    )
                elif line_index < max_body:
                    parts.append(_empty_card_line(card_w, theme))
                else:
                    footer_index = line_index - max_body
                    line = footer[footer_index] if footer_index < len(footer) else ""
                    parts.append(
                        _normalize_card_line(line, card_w, ellipsis=ellipsis)
                    )
            chunks.append((" " * CARD_GAP).join(parts))
        if row_start + columns < len(card_list):
            chunks.append("")

    return "\n".join(chunks) + "\n"


def render_cards_brief(
    cards: tuple[SessionCard, ...] | list[SessionCard],
    *,
    width: int = 100,
    color: bool = True,
    ascii_only: bool = False,
    project_name: str | None = None,
    current_branch: str | None = None,
) -> str:
    """Render a fixed-column scan table (Option B brief mode)."""

    theme = _CardTheme(color=color and not ascii_only, ascii_only=ascii_only)
    lines: list[str] = []
    header = _grid_header(project_name, current_branch, theme)
    if header:
        lines.append(header)
        lines.append("")

    col_handle = 6
    col_harness = 10
    col_branch = 12
    col_updated = 8
    col_health = 12
    col_turns = 6
    fixed = col_handle + col_harness + col_branch + col_updated + col_health + col_turns + 6
    col_summary = max(12, width - fixed)

    lines.append(
        " ".join(
            (
                pad_visible(theme.style_label("HANDLE"), col_handle),
                pad_visible(theme.style_label("HARNESS"), col_harness),
                pad_visible(theme.style_label("BRANCH"), col_branch),
                pad_visible(theme.style_label("UPDATED"), col_updated),
                pad_visible(theme.style_label("HEALTH"), col_health),
                pad_visible(theme.style_label("TURNS"), col_turns),
                pad_visible(theme.style_label("SUMMARY"), col_summary),
            )
        )
    )

    ellipsis = "..." if ascii_only else "…"
    dash = "-" if ascii_only else "—"
    if not cards:
        lines.append("No indexed sessions.")
        return "\n".join(lines) + "\n"

    for card in cards:
        branch = (
            truncate_end(card.git_branch, col_branch, ellipsis=ellipsis)
            if card.git_branch
            else dash
        )
        turns = (
            str(card.visible_turn_count)
            if card.visible_turn_count is not None
            else dash
        )
        summary = middle_elide(card.title, col_summary, ellipsis=ellipsis)
        lines.append(
            " ".join(
                (
                    pad_visible(truncate_end(card.handle, col_handle, ellipsis=ellipsis), col_handle),
                    pad_visible(
                        truncate_end(card.harness, col_harness, ellipsis=ellipsis),
                        col_harness,
                    ),
                    pad_visible(branch, col_branch),
                    pad_visible(
                        truncate_end(card.updated_relative, col_updated, ellipsis=ellipsis),
                        col_updated,
                    ),
                    pad_visible(
                        theme.style_health(
                            health_label(card.health),
                            card.health,
                        ),
                        col_health,
                    ),
                    pad_visible(turns, col_turns),
                    pad_visible(summary, col_summary),
                )
            )
        )
    return "\n".join(lines) + "\n"


def _grid_header(
    project_name: str | None,
    current_branch: str | None,
    theme: _CardTheme,
) -> str:
    if not project_name and not current_branch:
        return ""
    name = project_name or "project"
    if current_branch:
        return (
            f"{theme.style_label(name)} · "
            f"{theme.style_muted('branch')} {theme.style_teal(current_branch)}"
        )
    return theme.style_label(name)


@dataclass(frozen=True, slots=True)
class _CardTheme:
    color: bool
    ascii_only: bool

    def style_border(self, text: str) -> str:
        return self._sgr(text, "90") if self.color else text

    def style_label(self, text: str) -> str:
        return self._rgb(text, STEEL, bold=True) if self.color else text

    def style_teal(self, text: str) -> str:
        return self._rgb(text, TEAL, bold=True) if self.color else text

    def style_muted(self, text: str) -> str:
        return self._sgr(text, "90") if self.color else text

    def style_good(self, text: str) -> str:
        return self._rgb(text, TEAL, bold=True) if self.color else text

    def style_warn(self, text: str) -> str:
        return self._rgb(text, STEEL, bold=True) if self.color else text

    def style_fail(self, text: str) -> str:
        return self._sgr(text, "1;31") if self.color else text

    def style_health(self, label: str, health: SessionHealth) -> str:
        if not self.color:
            return label
        if health is SessionHealth.COMPLETE:
            return self.style_good(label)
        if health is SessionHealth.POSSIBLY_INTERRUPTED:
            return self.style_fail(label)
        return self.style_warn(label)

    def style_readable(self, text: str) -> str:
        return text

    @staticmethod
    def _sgr(text: str, code: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m"

    @staticmethod
    def _rgb(text: str, hex_color: str, *, bold: bool = False) -> str:
        value = hex_color.lstrip("#")
        red = int(value[0:2], 16)
        green = int(value[2:4], 16)
        blue = int(value[4:6], 16)
        prefix = "1;" if bold else ""
        return f"\x1b[{prefix}38;2;{red};{green};{blue}m{text}\x1b[0m"


def _dot(theme: _CardTheme) -> str:
    return " | " if theme.ascii_only else " · "


def _ellipsis(theme: _CardTheme) -> str:
    return "..." if theme.ascii_only else "…"


def _render_session_card(card: SessionCard, width: int, theme: _CardTheme) -> list[str]:
    inner = max(1, width - 4)
    ellipsis = _ellipsis(theme)
    lines: list[str] = [
        _box_line_top(inner, theme),
        _header_line(card, inner, theme),
        _separator_line(inner, theme),
        _status_line(card, inner, theme),
        _capability_line(card, inner, theme),
        _focus_line(card, inner, theme),
        _section_label("Context", inner, theme),
    ]
    snippet = " ".join((card.snippet or "").split())
    if snippet:
        for piece in _wrap_plain(snippet, inner, max_lines=2, ellipsis=ellipsis):
            lines.append(_content_line(theme.style_readable(piece), inner, theme, ellipsis=ellipsis))
    else:
        lines.append(
            _content_line(theme.style_muted("(no snippet)"), inner, theme, ellipsis=ellipsis)
        )
    lines.append(_separator_line(inner, theme))
    lines.append(_footer_line(card, inner, theme))
    lines.append(_box_line_bottom(inner, theme))
    return lines


def _header_line(card: SessionCard, inner: int, theme: _CardTheme) -> str:
    ellipsis = _ellipsis(theme)
    left = (
        f"{theme.style_teal(card.handle)}{_dot(theme)}"
        f"{theme.style_label(card.harness.title())}"
    )
    model_bits = [value for value in (card.model_id, card.effort) if value]
    right = theme.style_muted(" ".join(model_bits)) if model_bits else ""
    content = (
        compose_visible_row(left, right, inner, ellipsis=ellipsis)
        if right
        else pad_visible(left, inner, ellipsis=ellipsis)
    )
    return _side_border(content, inner, theme, ellipsis=ellipsis)


def _status_line(card: SessionCard, inner: int, theme: _CardTheme) -> str:
    ellipsis = _ellipsis(theme)
    parts: list[str] = [
        theme.style_health(health_label(card.health), card.health),
    ]
    if card.git_branch:
        parts.append(
            theme.style_teal(truncate_end(card.git_branch, 14, ellipsis=ellipsis))
        )
    parts.append(theme.style_muted(card.updated_relative))
    if card.visible_turn_count is not None:
        parts.append(theme.style_muted(f"{card.visible_turn_count}t"))
    content = fit_visible(_dot(theme).join(parts), inner, ellipsis=ellipsis)
    return _content_line(content, inner, theme, ellipsis=ellipsis)


def _capability_line(card: SessionCard, inner: int, theme: _CardTheme) -> str:
    ellipsis = _ellipsis(theme)
    labels = [
        _CAPABILITY_LABELS.get(value, value.replace("-", " "))
        for value in card.capabilities
    ]
    if card.native_available:
        labels.append("resume ok")
    elif card.warning:
        labels.append(card.warning)
    if not labels:
        labels = ["none"]
    if not card.native_available:
        styled = theme.style_fail(card.warning or "source unavailable")
    else:
        styled = _dot(theme).join(
            theme.style_good(label)
            if "resume" in label or "reread" in label
            else theme.style_muted(label)
            for label in labels
        )
    return _content_line(fit_visible(styled, inner, ellipsis=ellipsis), inner, theme, ellipsis=ellipsis)


def _focus_line(card: SessionCard, inner: int, theme: _CardTheme) -> str:
    ellipsis = _ellipsis(theme)
    label = theme.style_muted("Focus:")
    title = theme.style_teal(
        truncate_end(card.title, max(1, inner - visible_width(label) - 1), ellipsis=ellipsis)
    )
    return _content_line(
        fit_visible(f"{label} {title}", inner, ellipsis=ellipsis),
        inner,
        theme,
        ellipsis=ellipsis,
    )


def _footer_line(card: SessionCard, inner: int, theme: _CardTheme) -> str:
    ellipsis = _ellipsis(theme)
    hint = f"@ tang resume {card.handle}"
    return _content_line(
        theme.style_muted(truncate_end(hint, inner, ellipsis=ellipsis)),
        inner,
        theme,
        ellipsis=ellipsis,
    )


def _section_label(label: str, inner: int, theme: _CardTheme) -> str:
    rule = "=" if theme.ascii_only else "═"
    ellipsis = _ellipsis(theme)
    prefix = theme.style_label(label)
    rest = max(0, inner - visible_width(prefix) - 1)
    content = f"{prefix} {theme.style_border(rule * rest)}" if rest else prefix
    return _content_line(
        fit_visible(content, inner, ellipsis=ellipsis),
        inner,
        theme,
        ellipsis=ellipsis,
    )


def _box_line_top(inner: int, theme: _CardTheme) -> str:
    if theme.ascii_only:
        return theme.style_border("+" + ("-" * (inner + 2)) + "+")
    return theme.style_border("╭" + ("═" * (inner + 2)) + "╮")


def _box_line_bottom(inner: int, theme: _CardTheme) -> str:
    if theme.ascii_only:
        return theme.style_border("+" + ("-" * (inner + 2)) + "+")
    return theme.style_border("╰" + ("═" * (inner + 2)) + "╯")


def _separator_line(inner: int, theme: _CardTheme) -> str:
    if theme.ascii_only:
        return theme.style_border("+" + ("-" * (inner + 2)) + "+")
    return theme.style_border("╠" + ("═" * (inner + 2)) + "╣")


def _side_border(
    content: str, inner: int, theme: _CardTheme, *, ellipsis: str = "…"
) -> str:
    padded = pad_visible(content, inner, ellipsis=ellipsis)
    if theme.ascii_only:
        return f"{theme.style_border('| ')}{padded}{theme.style_border(' |')}"
    return f"{theme.style_border('║ ')}{padded}{theme.style_border(' ║')}"


def _content_line(
    content: str, inner: int, theme: _CardTheme, *, ellipsis: str = "…"
) -> str:
    return _side_border(content, inner, theme, ellipsis=ellipsis)


def _empty_card_line(width: int, theme: _CardTheme) -> str:
    return _side_border("", max(1, width - 4), theme, ellipsis=_ellipsis(theme))


def _normalize_card_line(line: str, width: int, *, ellipsis: str = "…") -> str:
    if not line:
        return " " * width
    current = visible_width(line)
    if current == width:
        return line
    if current < width:
        return pad_visible(line, width, ellipsis=ellipsis)
    return pad_visible(fit_visible(line, width, ellipsis=ellipsis), width, ellipsis=ellipsis)


def _split_card_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    split_at = max(0, len(lines) - CARD_FOOTER_LINES)
    return lines[:split_at], lines[split_at:]


def _wrap_plain(text: str, width: int, *, max_lines: int, ellipsis: str) -> list[str]:
    from tang.textutil import display_width

    if width <= 0 or not text:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    remaining = list(words)
    while remaining and len(lines) < max_lines:
        word = remaining.pop(0)
        candidate = word if not current else f"{current} {word}"
        if display_width(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
            current = ""
            remaining.insert(0, word)
            continue
        lines.append(truncate_end(word, width, ellipsis=ellipsis))
    if current and len(lines) < max_lines:
        lines.append(current)
    elif remaining and lines:
        lines[-1] = truncate_end(lines[-1], width, ellipsis=ellipsis)
    return lines[:max_lines]
