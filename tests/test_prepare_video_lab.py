from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_video_lab.py"


def _module():
    spec = importlib.util.spec_from_file_location("prepare_video_lab", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_video_lab_director_tracks_manual_cards_without_harness_automation(
    tmp_path: Path, capsys
) -> None:
    module = _module()
    project = tmp_path / "video-lab"

    assert module.main(["init", str(project)]) == 0
    assert (project / "TANG_VIDEO_LAB.md").is_file()
    assert module.main(["next", str(project)]) == 0
    first = capsys.readouterr().out
    assert "CODEX · PLACES · codex-places" in first
    assert "exactly five" in first
    assert "start a fresh session" in first

    assert module.main(["done", str(project)]) == 0
    assert module.main(["next", str(project)]) == 0
    second = capsys.readouterr().out
    assert "CODEX · BOOKS · codex-books" in second

    assert "subprocess" not in SCRIPT.read_text(encoding="utf-8")


def test_video_lab_init_refuses_to_touch_a_nonempty_directory(
    tmp_path: Path, capsys
) -> None:
    module = _module()
    project = tmp_path / "existing"
    project.mkdir()
    (project / "keep.txt").write_text("keep", encoding="utf-8")

    assert module.main(["init", str(project)]) == 2
    assert "non-empty directory" in capsys.readouterr().err
    assert (project / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_video_lab_runbook_requires_nine_manual_sessions(tmp_path: Path, capsys) -> None:
    module = _module()
    project = tmp_path / "video-lab"
    assert module.main(["init", str(project)]) == 0
    capsys.readouterr()
    assert module.main(["runbook", str(project)]) == 2
    assert "complete all nine cards" in capsys.readouterr().err


def test_video_lab_film_and_voiceover_separate_capture_from_narration(
    tmp_path: Path, capsys
) -> None:
    module = _module()
    project = tmp_path / "video-lab"
    assert module.main(["init", str(project)]) == 0
    state_path = project / ".tang-video-lab.json"
    state = module.json.loads(state_path.read_text(encoding="utf-8"))
    state["completed"] = [card.identifier for card in module.CARDS]
    state_path.write_text(module.json.dumps(state), encoding="utf-8")
    capsys.readouterr()

    assert module.main(["film", str(project)]) == 0
    film = capsys.readouterr().out
    assert "BOOK-MERGE SCREEN PLAN" in film
    assert "tang search \"books to bring\"" in film
    assert "Context Pack" in film

    assert module.main(["voiceover", str(project)]) == 0
    voiceover = capsys.readouterr().out
    assert "BOOK-MERGE VOICEOVER" in voiceover
    assert "Tang does not persist that synthesis" in voiceover
