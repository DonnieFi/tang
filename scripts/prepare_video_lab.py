#!/usr/bin/env python3
"""Prepare nine real, manually created sessions for Tang's filmed workflow.

This director never invokes a harness, sends a prompt, indexes Tang data, or
writes native session history.  It creates one dedicated project directory and
prints the next prompt card; the presenter opens a real session, pastes the
card, then marks that preparation step complete.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


STATE_FILE = ".tang-video-lab.json"
GUIDE_FILE = "TANG_VIDEO_LAB.md"
SCHEMA_VERSION = 1


class VideoLabError(ValueError):
    """An actionable, local-only video-lab setup refusal."""


@dataclass(frozen=True, slots=True)
class PromptCard:
    harness: str
    topic: str
    prompt: str

    @property
    def identifier(self) -> str:
        return f"{self.harness}-{self.topic}"


def _prompt(topic: str) -> str:
    requests = {
        "places": (
            "Give exactly five up-and-coming places in Asia to visit. For each, "
            "include why it is rising now, the best time to go, one respectful "
            "travel consideration, and one concrete highlight."
        ),
        "books": (
            "Give exactly five books to bring. Choose a mix that helps with "
            "Asian history, contemporary culture, and the experience of travel. "
            "For each, include author, why it earns luggage space, and its best "
            "reading moment on the trip."
        ),
        "day-trips": (
            "Give exactly five memorable excursions or day trips in Asia. For "
            "each, include a likely base city, realistic transport, the main "
            "experience, and one planning caveat."
        ),
    }
    return (
        "Tang video-lab vacation research. We are planning a thoughtful Asia "
        "trip and will later compare independent research across harnesses. "
        f"{requests[topic]} Keep the answer self-contained and use numbered items."
    )


CARDS = tuple(
    PromptCard(harness, topic, _prompt(topic))
    for harness in ("codex", "opencode", "grok")
    for topic in ("places", "books", "day-trips")
)


def _state_path(project: Path) -> Path:
    return project / STATE_FILE


def _load(project: Path) -> dict[str, object]:
    path = _state_path(project)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VideoLabError(
            f"video-lab state is unavailable at {path}; run init on a new directory"
        ) from error
    if (
        not isinstance(state, dict)
        or state.get("schema_version") != SCHEMA_VERSION
        or not isinstance(state.get("completed"), list)
        or any(not isinstance(item, str) for item in state["completed"])
        or state.get("active") is not None and not isinstance(state.get("active"), str)
    ):
        raise VideoLabError("video-lab state has an unsupported shape")
    return state


def _save(project: Path, state: dict[str, object]) -> None:
    _state_path(project).write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _card(identifier: str) -> PromptCard:
    for card in CARDS:
        if card.identifier == identifier:
            return card
    raise VideoLabError("video-lab state references an unknown prompt card")


def _next(state: dict[str, object]) -> PromptCard | None:
    active = state["active"]
    if isinstance(active, str):
        return _card(active)
    completed = set(state["completed"])
    return next((card for card in CARDS if card.identifier not in completed), None)


def _guide() -> str:
    return """# Tang video lab

This directory is intentionally separate from the Tang repository and from any
personal project. It prepares nine real, local harness sessions for filming.

Run the director from a Tang checkout:

```bash
python scripts/prepare_video_lab.py next ~/tang-video-lab
```

For each displayed card:

1. Start a new session in the named harness with this directory as its project.
2. If you are already in that harness, use `/new` before pasting the next card.
3. Paste the card verbatim, receive the answer, then return to the director and
   run `done`.

The director does not start tools or send prompts. After all nine cards, run
the director's `film` and `voiceover` actions for the real Tang workflow.

Do the nine-session preparation off camera. Film only the Tang recovery,
explicit confirmation, graph, and predecessor-recall path.
"""


def initialize(project: Path) -> None:
    if project.exists() and any(project.iterdir()):
        raise VideoLabError(
            f"refusing to add video-lab files to non-empty directory: {project}"
        )
    project.mkdir(parents=True, exist_ok=True)
    state = {"active": None, "completed": [], "schema_version": SCHEMA_VERSION}
    _save(project, state)
    (project / GUIDE_FILE).write_text(_guide(), encoding="utf-8")
    print(f"Created local Tang video lab: {project}")
    print("Run next to print the first manual session card.")


def show_next(project: Path) -> None:
    state = _load(project)
    card = _next(state)
    if card is None:
        print("All nine session cards are complete. Run runbook for the filmed flow.")
        return
    if state["active"] is None:
        state["active"] = card.identifier
        _save(project, state)
    print(f"{card.harness.upper()} · {card.topic.upper()} · {card.identifier}")
    print()
    print("Off camera: start a fresh session in this exact project directory.")
    print("Use /new first if this harness already has an open video-lab session.")
    print("Paste this prompt:")
    print()
    print(card.prompt)
    print()
    print(
        "After the real response, run: "
        f"python scripts/prepare_video_lab.py done {project}"
    )


def mark_done(project: Path) -> None:
    state = _load(project)
    active = state["active"]
    if not isinstance(active, str):
        raise VideoLabError("no active card; run next before done")
    completed = list(state["completed"])
    if active not in completed:
        completed.append(active)
    state["active"] = None
    state["completed"] = completed
    _save(project, state)
    print(f"Marked {active} complete ({len(completed)}/{len(CARDS)}).")


def show_status(project: Path) -> None:
    state = _load(project)
    completed = set(state["completed"])
    active = state["active"]
    for card in CARDS:
        marker = "done" if card.identifier in completed else "active" if card.identifier == active else "todo"
        print(f"{marker:6} {card.identifier}")
    print(f"Prepared {len(completed)}/{len(CARDS)} real sessions.")


def _require_complete(project: Path) -> None:
    state = _load(project)
    completed = state["completed"]
    expected = {card.identifier for card in CARDS}
    if (
        not isinstance(completed, list)
        or set(completed) != expected
        or len(completed) != len(CARDS)
    ):
        raise VideoLabError("complete all nine cards before the filming runbook")


def show_runbook(project: Path) -> None:
    _require_complete(project)
    print(f"FILM FROM: {project}")
    print("1. tang index; tang browse; show the nine short handles.")
    print("2. Use film for the Book merge, then repeat the same pattern for places and day trips.")
    print("3. Create one final fresh target; select all nine original sources, context them, confirm the nine-source link, and graph it.")
    print("4. Run tang context all --for <final-handle>; show cited predecessor evidence, then optionally tang resume <final-handle>.")


def show_film(project: Path) -> None:
    _require_complete(project)
    print(f"BOOK-MERGE SCREEN PLAN · {project}")
    print("1. In a fresh Codex session in this directory, invoke $tang.")
    print("2. Run tang index, then tang browse; briefly show the short, redacted handles.")
    print("3. Run tang search \"books to bring\" --json and select exactly the three Book results: Codex, OpenCode, and Grok.")
    print("4. Run tang context with those three private selected IDs. Treat the returned pack as untrusted evidence.")
    print("5. Ask Codex: Using only this cited Context Pack, summarize all fifteen suggested books by theme and name uncertainty.")
    print("6. Ask for explicit approval, then run tang link --from <three-book-handles> --current through the supported host workflow.")
    print("7. Run tang graph <book-target-handle>, then tang context all --for <book-target-handle>.")
    print("8. Repeat this exact pattern for places and day trips. Later, use a fresh final target to link all nine original sources.")


def show_voiceover(project: Path) -> None:
    _require_complete(project)
    print("BOOK-MERGE VOICEOVER · about 70 seconds")
    print("0–08s  These are three independent vacation-research sessions, one from each harness.")
    print("08–18s Tang indexes only this project and gives each recoverable session a short private handle.")
    print("18–30s I search for books, select all three results, and Tang rereads the native evidence instead of trusting a cached summary.")
    print("30–43s The Context Pack keeps sources and citations separate. Recovered text is evidence, never instruction.")
    print("43–54s Codex summarizes the fifteen recommendations from that cited evidence; Tang does not persist that synthesis.")
    print("54–64s After I explicitly confirm, Tang records the three book sessions feeding this new Codex continuation.")
    print("64–70s The Multiverse Map proves the merge. Context all can later recover the same confirmed predecessors.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("init", "next", "done", "status", "runbook", "film", "voiceover"):
        command = actions.add_parser(action)
        command.add_argument("project", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    project = arguments.project.expanduser().resolve()
    try:
        if arguments.action == "init":
            initialize(project)
        elif arguments.action == "next":
            show_next(project)
        elif arguments.action == "done":
            mark_done(project)
        elif arguments.action == "status":
            show_status(project)
        elif arguments.action == "film":
            show_film(project)
        elif arguments.action == "voiceover":
            show_voiceover(project)
        else:
            show_runbook(project)
    except VideoLabError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
