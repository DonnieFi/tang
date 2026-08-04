"""Session cards view: Option A layout, metadata, and brief mode."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from tang.adapters import (
    ClaudeAdapter,
    CodexAdapter,
    SessionHealth,
    TurnSelection,
)
from tang.capsule import DiscoveryCapsuleBuilder
from tang.cli import main
from tang.discovery import DiscoveryItem, DiscoveryService
from tang.project import resolve_project
from tang.repository import TangRepository
from tang.session_cards import (
    _ACTION_COLOR,
    _CARD_TEXT_COLOR,
    MAX_CARD_WIDTH,
    MIN_CARD_WIDTH,
    _RISK_COLORS,
    SessionCard,
    _STATUS_COLORS,
    _STRUCTURE_COLOR,
    _TURN_COUNT_COLOR,
    _HARNESS_COLORS,
    _OUTLINE_COLOR,
    card_width,
    column_count,
    current_git_branch,
    current_git_status,
    relative_age,
    render_cards_brief,
    render_cards_grid,
    session_card_from_item,
)
from tang.storage import open_database
from tang.textutil import pad_visible, strip_sgr, visible_width


NOW = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_FIXTURE_SESSION = "019f6000-c1a0-7000-8000-000000000001"


def _card(
    handle: str = "C6",
    *,
    harness: str = "codex",
    title: str = "Graph export and tests",
    snippet: str | None = "Built graph export and tests for OpenCode adapter path.",
    health: SessionHealth = SessionHealth.COMPLETE,
    git_branch: str | None = "main",
    turns: int | None = 187,
    native_available: bool = True,
    model_id: str | None = "gpt-5.6",
    effort: str | None = None,
    minutes_ago: int = 14,
    custom_title: bool = False,
    agent_role: str | None = None,
    compacted: bool | None = None,
) -> SessionCard:
    updated = NOW - timedelta(minutes=minutes_ago)
    return SessionCard(
        handle=handle,
        harness=harness,
        title=title,
        snippet=snippet,
        updated_at=updated,
        updated_relative=relative_age(updated, now=NOW),
        health=health,
        capabilities=("native-reread", "visible-user-agent-turns"),
        model_provider="openai" if harness == "codex" else None,
        model_id=model_id,
        effort=effort,
        visible_turn_count=turns,
        git_branch=git_branch,
        native_available=native_available,
        warning=None if native_available else "source unavailable",
        custom_title=custom_title,
        agent_role=agent_role,
        compacted=compacted,
    )


def _layout_claude_session(claude_home: Path, project: Path) -> None:
    slug = ClaudeAdapter.project_slug(project)
    destination = claude_home / "projects" / slug / f"{CLAUDE_FIXTURE_SESSION}.jsonl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    source = (
        FIXTURES
        / "claude"
        / "projects"
        / "-opt-tang-fixture"
        / f"{CLAUDE_FIXTURE_SESSION}.jsonl"
    )
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def test_column_and_card_width_band() -> None:
    assert column_count(40) == 1
    assert column_count(80) >= 2
    assert MIN_CARD_WIDTH <= card_width(120, 2) <= MAX_CARD_WIDTH
    assert card_width(30, 1) == MIN_CARD_WIDTH


def test_option_a_card_has_status_focus_context_no_graph() -> None:
    rendered = render_cards_grid(
        (
            _card(
                title="Auth refactor",
                snippet="Tightened login session expiry and refresh path.",
            ),
        ),
        width=80,
        color=False,
        project_name="tang",
        current_branch="epic/12-session-cards",
    )
    plain = strip_sgr(rendered)
    assert "tang · branch epic/12-session-cards" in plain
    assert "C6" in plain
    assert "Codex" in plain
    assert "complete · 187 turns · 14m" in plain
    assert "Focus:" in plain
    assert "branch: main" in plain
    assert "Auth refactor" in plain
    assert "Context" in plain
    assert "@ tang resume C6" in plain
    # Section order: Focus before Context; no topology sections
    assert plain.index("Focus:") < plain.index("Context")
    assert "PREDECESSOR" not in plain.upper()
    assert "MULTIVERSE" not in plain.upper()
    assert "\nGraph" not in plain and " Graph " not in plain
    assert "visible_text_bytes" not in plain


def test_card_shows_evidence_qualified_role_and_compaction() -> None:
    plain = strip_sgr(
        render_cards_grid(
            (_card(agent_role="subagent", compacted=True),),
            width=80,
            color=False,
        )
    )

    assert "subagent" in plain
    assert "subagent agent" not in plain
    assert "compacted" in plain


def test_branch_omitted_when_null() -> None:
    with_branch = strip_sgr(
        render_cards_grid(
            (_card(title="Auth work", snippet="snippet", git_branch="main"),),
            width=80,
            color=False,
        )
    )
    without = strip_sgr(
        render_cards_grid(
            (_card(title="Auth work", snippet="snippet", git_branch=None),),
            width=80,
            color=False,
        )
    )
    assert "complete · 187 turns · 14m" in with_branch
    assert "branch: main" in with_branch
    assert "complete · 187 turns · 14m" in without
    assert "main" not in without


def test_minimum_width_keeps_capability_action_readable() -> None:
    plain = strip_sgr(render_cards_grid((_card(),), width=MIN_CARD_WIDTH, color=False))
    assert "reread · turns · resume" in plain


def test_rendered_card_lines_share_exact_width() -> None:
    single = render_cards_grid((_card("C1", title="Short"),), width=42, color=False)
    card_lines = [
        line
        for line in single.splitlines()
        if line.startswith(("╭", "║", "╠", "╰", "+", "|"))
    ]
    assert card_lines
    expected = visible_width(card_lines[0])
    assert MIN_CARD_WIDTH <= expected <= MAX_CARD_WIDTH
    assert all(visible_width(line) == expected for line in card_lines)


def test_grid_pins_footer_across_mixed_heights() -> None:
    short = _card("C1", title="Short", snippet="x")
    tall = _card(
        "C2",
        title="Tall card title",
        snippet="Long context that wraps across two lines for the body section.",
    )
    rendered = render_cards_grid((short, tall), width=100, color=False)
    lines = [line for line in rendered.splitlines() if "tang resume" in line]
    assert len(lines) == 1  # footers share one terminal row
    assert "C1" in lines[0] and "C2" in lines[0]


def test_brief_mode_branch_column() -> None:
    cards = (
        _card("C6", git_branch="main"),
        _card("L1", harness="claude", git_branch=None, title="No branch session"),
    )
    plain = strip_sgr(
        render_cards_brief(cards, width=120, color=False, project_name="tang")
    )
    assert "HANDLE" in plain
    assert "BRANCH" in plain
    assert "TURNS" in plain
    assert "ROLE" in plain
    assert "COMPACT" in plain
    assert "187 turns" in plain
    assert "main" in plain
    assert "compacted" not in plain
    assert "—" in plain or "-" in plain
    assert "C6" in plain and "L1" in plain
    colored = render_cards_brief(cards, width=120, color=True, project_name="tang")
    assert "\x1b[" in colored
    assert "C6" in strip_sgr(colored)
    assert re.search(r"\x1b\[[^m]*mC6\x1b\[0m", colored)
    assert re.search(r"\x1b\[[^m]*mmain\x1b\[0m", colored)


def test_each_harness_has_a_distinct_card_colour() -> None:
    harnesses = ("codex", "grok", "opencode", "cursor", "claude", "antigravity")
    styles = {
        match.group(1)
        for index, harness in enumerate(harnesses)
        if (
            match := re.search(
                rf"(\x1b\[[^m]*m){harness.title()}\x1b\[0m",
                render_cards_grid(
                    (_card(f"H{index}", harness=harness),),
                    width=42,
                    color=True,
                ),
            )
        )
    }
    assert len(styles) == len(harnesses)


def test_card_palette_uses_separate_semantic_lanes() -> None:
    assert len(set(_HARNESS_COLORS.values())) == len(_HARNESS_COLORS)
    assert _HARNESS_COLORS["codex"] == "#7fc6e0"
    assert _HARNESS_COLORS["grok"] == "#93c08b"
    assert _CARD_TEXT_COLOR == "#e8eaed"
    assert _STRUCTURE_COLOR == "#767c8c"
    assert _ACTION_COLOR == "#6e9bc4"
    assert _RISK_COLORS == {
        "low": "#5fbf8f",
        "medium": "#e0a83c",
        "high": "#e0813c",
        "max": "#d9694a",
    }
    assert _STATUS_COLORS == {
        "complete": "#4caf6d",
        "unverified": "#9b8fc0",
        "compacted": "#6b8cae",
        "error": "#d9694a",
    }
    assert set(_HARNESS_COLORS.values()).isdisjoint(
        set(_RISK_COLORS.values()) | set(_STATUS_COLORS.values())
    )


def test_risk_and_status_badges_use_their_assigned_lanes() -> None:
    for effort, color in _RISK_COLORS.items():
        rendered = render_cards_grid(
            (_card(effort=effort),), width=42, color=True
        )
        value = color.lstrip("#")
        assert (
            f"\x1b[1;38;2;{int(value[0:2], 16)};{int(value[2:4], 16)};"
            f"{int(value[4:6], 16)}m{effort}\x1b[0m"
        ) in rendered

    for health, label, color in (
        (SessionHealth.COMPLETE, "complete", _STATUS_COLORS["complete"]),
        (SessionHealth.UNKNOWN, "unverified", _STATUS_COLORS["unverified"]),
        (SessionHealth.POSSIBLY_INTERRUPTED, "possibly interrupted", _STATUS_COLORS["error"]),
    ):
        rendered = render_cards_grid(
            (_card(health=health),), width=42, color=True
        )
        value = color.lstrip("#")
        assert (
            f"\x1b[1;38;2;{int(value[0:2], 16)};{int(value[2:4], 16)};"
            f"{int(value[4:6], 16)}m{label}\x1b[0m"
        ) in rendered

    rendered = render_cards_grid(
        (_card(compacted=True),), width=42, color=True
    )
    value = _STATUS_COLORS["compacted"].lstrip("#")
    assert (
        f"\x1b[1;38;2;{int(value[0:2], 16)};{int(value[2:4], 16)};"
        f"{int(value[4:6], 16)}mcompacted\x1b[0m"
    ) in rendered


def test_structural_labels_and_actions_are_neutral_and_uniform() -> None:
    rendered = render_cards_grid(
        (_card(effort="max", compacted=True),), width=42, color=True
    )
    structure = _STRUCTURE_COLOR.lstrip("#")
    structure_code = (
        f"\x1b[38;2;{int(structure[0:2], 16)};{int(structure[2:4], 16)};"
        f"{int(structure[4:6], 16)}m"
    )
    assert structure_code + "Focus:" in rendered
    assert structure_code + "branch:" in rendered
    assert structure_code + "@ tang resume" in rendered

    action = _ACTION_COLOR.lstrip("#")
    action_code = (
        f"\x1b[38;2;{int(action[0:2], 16)};{int(action[2:4], 16)};"
        f"{int(action[4:6], 16)}m"
    )
    for label in ("reread", "turns", "resume"):
        assert action_code + label in rendered


def test_card_outline_and_turn_count_use_quiet_structure_colors() -> None:
    colored = render_cards_grid((_card(turns=187),), width=42, color=True)
    outline = _OUTLINE_COLOR.lstrip("#")
    turns = _TURN_COUNT_COLOR.lstrip("#")
    assert (
        f"\x1b[38;2;{int(outline[0:2], 16)};{int(outline[2:4], 16)};"
        f"{int(outline[4:6], 16)}m"
    ) in colored
    assert (
        f"\x1b[38;2;{int(turns[0:2], 16)};{int(turns[2:4], 16)};"
        f"{int(turns[4:6], 16)}m187 turns\x1b[0m"
    ) in colored


def test_current_git_branch_redacts_live_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "tang.session_cards.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="feat/sk-abcdefghijklmnop\n",
        ),
    )

    assert current_git_branch(Path(".")) == "feat/[REDACTED:token]"


def test_current_git_status_returns_only_a_bounded_summary(monkeypatch) -> None:
    monkeypatch.setattr(
        "tang.session_cards.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout=" M private.txt\n?? another-private.txt\n",
        ),
    )

    assert current_git_status(Path(".")) == "dirty (2)"


def test_discovery_browse_passes_cards_limit_to_repository() -> None:
    class CapturingRepository:
        seen_limit: int | None = None

        def browse_discovery(self, project_key: str, **kwargs):
            assert project_key == "project"
            self.seen_limit = kwargs["limit"]
            return ()

    repository = CapturingRepository()
    assert DiscoveryService(repository).browse("project", limit=12) == ()
    assert repository.seen_limit == 12


def test_session_card_projection_from_discovery_item() -> None:
    item = DiscoveryItem(
        source_id="codex:ns:id",
        handle="C1",
        display_name="Display",
        harness="codex",
        updated_at=NOW,
        health=SessionHealth.COMPLETE,
        title="Title",
        capabilities=("native-reread",),
        snippet="Snippet",
        model_provider="openai",
        model_id="gpt",
        effort="high",
        title_origin="native",
        visible_turn_count=3,
        visible_text_bytes=100,
        git_branch="epic/12",
        native_available=True,
        custom_title="Custom title",
        agent_role="subagent",
        compacted=True,
    )
    card = session_card_from_item(item, now=NOW)
    assert card.git_branch == "epic/12"
    assert card.visible_turn_count == 3
    assert card.native_available is True
    assert card.title == "Custom title"
    assert card.custom_title is True
    assert card.agent_role == "subagent"
    assert card.compacted is True


def test_codex_indexes_git_branch(tmp_path: Path) -> None:
    home = FIXTURES / "codex"
    adapter = CodexAdapter(home, source_namespace="cards")
    record = adapter.scan(None).records[0]
    assert record.header.git_branch == "main"
    assert record.header.agent_role == "main"

    (tmp_path / "proj").mkdir()
    project = resolve_project(tmp_path / "proj")
    read = adapter.read(record, TurnSelection())
    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    builder = DiscoveryCapsuleBuilder()
    with repository.transaction():
        repository.upsert_session(record, project.key, NOW)
        repository.put_capsule(builder.build(record, read, project.key))
    items = DiscoveryService(repository).browse(project.key)
    assert items
    assert items[0].git_branch == "main"
    assert items[0].compacted is False
    assert items[0].native_available is True
    connection.close()


def test_claude_indexes_git_branch(tmp_path: Path) -> None:
    project = (tmp_path / "work").resolve()
    project.mkdir()
    claude_home = tmp_path / "claude"
    _layout_claude_session(claude_home, project)
    adapter = ClaudeAdapter(project, claude_home=claude_home, source_namespace="cards")
    batch = adapter.scan(None)
    assert batch.records
    record = batch.records[0]
    assert record.header.git_branch == "feat/home-automation-ui"
    assert record.header.agent_role == "main"

    connection = open_database(tmp_path / "tang.db")
    repository = TangRepository(connection)
    read = adapter.read(record, TurnSelection())
    resolved = resolve_project(project)
    with repository.transaction():
        repository.upsert_session(record, resolved.key, NOW)
        repository.put_capsule(
            DiscoveryCapsuleBuilder().build(record, read, resolved.key)
        )
    item = DiscoveryService(repository).browse(resolved.key)[0]
    assert item.git_branch == "feat/home-automation-ui"
    assert item.agent_role == "main"
    assert item.compacted is None
    connection.close()


def test_cli_browse_cards_and_brief(tmp_path: Path, capsys) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    database = tmp_path / "tang.db"
    home = FIXTURES / "codex"
    adapter = CodexAdapter(home, source_namespace="cli-cards")
    record = adapter.scan(None).records[0]
    read = adapter.read(record, TurnSelection())
    connection = open_database(database)
    repository = TangRepository(connection)
    project = resolve_project(project_dir)
    with repository.transaction():
        repository.upsert_session(record, project.key, NOW)
        repository.put_capsule(
            DiscoveryCapsuleBuilder().build(record, read, project.key)
        )
    connection.close()

    assert (
        main(
            [
                "browse",
                "--cards",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
                "--width",
                "100",
                "--color",
                "never",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "@ tang resume" in out
    assert "Context" in out
    assert "main" in out
    assert "main agent" in out
    assert "MULTIVERSE" not in out

    assert (
        main(
            [
                "browse",
                "--cards",
                "--brief",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
                "--width",
                "120",
                "--color",
                "never",
            ]
        )
        == 0
    )
    brief = capsys.readouterr().out
    assert "HANDLE" in brief
    assert "BRANCH" in brief
    assert "main" in brief

    assert (
        main(
            [
                "title",
                "C1",
                "Custom auth recovery",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "cards",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
                "--color",
                "never",
            ]
        )
        == 0
    )
    assert "Title: Custom auth recovery" in capsys.readouterr().out

    assert (
        main(
            [
                "title",
                "C1",
                "--clear",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
            ]
        )
        == 0
    )
    assert "Cleared custom title" in capsys.readouterr().out


def test_cli_rejects_limit_and_page_mismatches(tmp_path: Path, capsys) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    database = tmp_path / "tang.db"
    open_database(database).close()
    assert (
        main(
            [
                "browse",
                "--limit",
                "3",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
            ]
        )
        == 2
    )
    assert "cards view" in capsys.readouterr().err
    assert (
        main(
            [
                "browse",
                "--cards",
                "--page",
                "2",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
            ]
        )
        == 2
    )
    assert "--page" in capsys.readouterr().err
    assert (
        main(
            [
                "cards",
                "--json",
                "--database",
                str(database),
                "--cwd",
                str(project_dir),
            ]
        )
        == 2
    )
    assert "does not support --json" in capsys.readouterr().err


def test_mixed_harness_grid_branch_present_and_absent() -> None:
    plain = strip_sgr(
        render_cards_grid(
            (
                _card("C1", harness="codex", git_branch="main", title="Codex work"),
                _card(
                    "L1",
                    harness="claude",
                    git_branch=None,
                    title="Claude work",
                    model_id="claude-sonnet",
                ),
            ),
            width=100,
            color=False,
        )
    )
    assert "C1" in plain and "L1" in plain
    assert "branch: main" in plain
    # Claude card status has no branch segment
    assert "complete · 187 turns · 14m" in plain


def test_pad_visible_ignores_sgr() -> None:
    colored = "\x1b[31mhi\x1b[0m"
    padded = pad_visible(colored, 6)
    assert visible_width(padded) == 6
    assert "hi" in strip_sgr(padded)


def test_pad_visible_exact_after_overflow() -> None:
    assert visible_width(pad_visible("abcdefghij", 6)) == 6
