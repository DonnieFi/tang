"""Session cards view: Option B layout, branch field, and brief mode."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

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
    MAX_CARD_WIDTH,
    MIN_CARD_WIDTH,
    SessionCard,
    card_width,
    column_count,
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
    minutes_ago: int = 14,
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
        effort=None,
        visible_turn_count=turns,
        git_branch=git_branch,
        native_available=native_available,
        warning=None if native_available else "source unavailable",
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


def test_option_b_card_has_status_focus_context_no_graph() -> None:
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
    assert "complete · main · 14m · 187t" in plain
    assert "Focus:" in plain
    assert "Auth refactor" in plain
    assert "Context" in plain
    assert "@ tang resume C6" in plain
    # Section order: Focus before Context; no topology sections
    assert plain.index("Focus:") < plain.index("Context")
    assert "PREDECESSOR" not in plain.upper()
    assert "MULTIVERSE" not in plain.upper()
    assert "\nGraph" not in plain and " Graph " not in plain
    assert "visible_text_bytes" not in plain


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
    assert "complete · main · 14m · 187t" in with_branch
    assert "complete · 14m · 187t" in without
    assert "main" not in without


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
    assert "main" in plain
    assert "—" in plain or "-" in plain
    assert "C6" in plain and "L1" in plain


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
    )
    card = session_card_from_item(item, now=NOW)
    assert card.git_branch == "epic/12"
    assert card.visible_turn_count == 3
    assert card.native_available is True
    assert card.title == "Display"


def test_codex_indexes_git_branch(tmp_path: Path) -> None:
    home = FIXTURES / "codex"
    adapter = CodexAdapter(home, source_namespace="cards")
    record = adapter.scan(None).records[0]
    assert record.header.git_branch == "main"

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
    assert "complete · main ·" in plain
    # Claude card status has no branch segment
    assert "complete · 14m · 187t" in plain


def test_pad_visible_ignores_sgr() -> None:
    colored = "\x1b[31mhi\x1b[0m"
    padded = pad_visible(colored, 6)
    assert visible_width(padded) == 6
    assert "hi" in strip_sgr(padded)


def test_pad_visible_exact_after_overflow() -> None:
    assert visible_width(pad_visible("abcdefghij", 6)) == 6
