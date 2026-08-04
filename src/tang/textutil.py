"""SGR-safe terminal text width helpers for card layout."""

from __future__ import annotations

import re
import unicodedata

_SGR_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_sgr(text: str) -> str:
    """Remove ANSI SGR sequences so width math ignores color codes."""

    return _SGR_RE.sub("", text)


def _char_width(character: str) -> int:
    if unicodedata.east_asian_width(character) in {"F", "W"}:
        return 2
    if unicodedata.category(character) in {"Mn", "Me", "Cf"}:
        return 0
    if character in {"\u200b", "\ufeff"}:
        return 0
    return 1


def display_width(text: str) -> int:
    """Return the terminal column width of plain (non-SGR) text."""

    return sum(_char_width(character) for character in text)


def visible_width(text: str) -> int:
    """Return display width after stripping SGR sequences."""

    return display_width(strip_sgr(text))


def truncate_end(text: str, max_width: int, *, ellipsis: str = "…") -> str:
    """Truncate plain text to max_width columns, appending an ellipsis when needed."""

    if max_width <= 0:
        return ""
    if display_width(text) <= max_width:
        return text
    mark = ellipsis
    if display_width(mark) > max_width:
        mark = mark[:1] if max_width else ""
        if display_width(mark) > max_width:
            return ""
    budget = max_width - display_width(mark)
    if budget <= 0:
        return mark
    output: list[str] = []
    width = 0
    for character in text:
        char_w = _char_width(character)
        if width + char_w > budget:
            break
        output.append(character)
        width += char_w
    return "".join(output) + mark


def middle_elide(text: str, max_width: int, *, ellipsis: str = "…") -> str:
    """Elide the middle of plain text to fit max_width columns."""

    if max_width <= 0:
        return ""
    if display_width(text) <= max_width:
        return text
    if max_width <= display_width(ellipsis):
        return ellipsis[:max_width]
    content = max_width - display_width(ellipsis)
    left_budget = content // 2
    right_budget = content - left_budget
    left = _take_prefix(text, left_budget)
    right = _take_suffix(text, right_budget)
    return f"{left}{ellipsis}{right}"


def _take_prefix(text: str, max_width: int) -> str:
    output: list[str] = []
    width = 0
    for character in text:
        char_w = _char_width(character)
        if width + char_w > max_width:
            break
        output.append(character)
        width += char_w
    return "".join(output)


def _take_suffix(text: str, max_width: int) -> str:
    output: list[str] = []
    width = 0
    for character in reversed(text):
        char_w = _char_width(character)
        if width + char_w > max_width:
            break
        output.append(character)
        width += char_w
    output.reverse()
    return "".join(output)


def pad_visible(text: str, width: int, *, ellipsis: str = "…") -> str:
    """Pad or fit a possibly colored string to an exact visible width."""

    current = visible_width(text)
    if current == width:
        return text
    if current < width:
        return text + (" " * (width - current))
    fitted = fit_visible(text, width, ellipsis=ellipsis)
    # Re-pad after fit so wide-glyph truncation cannot leave the line short.
    fitted_width = visible_width(fitted)
    if fitted_width < width:
        return fitted + (" " * (width - fitted_width))
    return fitted


def fit_visible(text: str, width: int, *, ellipsis: str = "…") -> str:
    """Fit a possibly colored string to at most ``width`` visible columns."""

    if width <= 0:
        return ""
    if visible_width(text) <= width:
        return text
    plain = strip_sgr(text)
    prefix = _leading_sgr_prefix(text)
    truncated = truncate_end(plain, width, ellipsis=ellipsis)
    if not prefix:
        return truncated
    return f"{prefix}{truncated}\x1b[0m"


def compose_visible_row(
    left: str, right: str, width: int, *, ellipsis: str = "…"
) -> str:
    """Place left and right content on one row with space between."""

    if not right or width == 0:
        return pad_visible(left, width, ellipsis=ellipsis)
    left_w = visible_width(left)
    right_w = visible_width(right)
    if left_w + 1 + right_w <= width:
        gap = width - left_w - right_w
        return f"{left}{' ' * gap}{right}"
    max_right = max(0, width - 2)
    fitted_right = fit_visible(right, max_right, ellipsis=ellipsis)
    fitted_right_w = visible_width(fitted_right)
    max_left = max(0, width - fitted_right_w - 1)
    fitted_left = fit_visible(left, max_left, ellipsis=ellipsis)
    gap = max(1, width - visible_width(fitted_left) - fitted_right_w)
    return f"{fitted_left}{' ' * gap}{fitted_right}"


def _leading_sgr_prefix(text: str) -> str:
    match = re.match(r"(?:\x1b\[[0-9;]*[A-Za-z])+", text)
    return match.group(0) if match else ""
