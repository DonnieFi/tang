from __future__ import annotations

import re
import io
from pathlib import Path

from tang.cli import main


class _CaptureBuffer(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return False


def test_demo_is_reproducible_and_cannot_touch_ambient_user_data(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    user = tmp_path / "user"
    data = user / "data"
    codex = user / "codex"
    grok = user / "grok"
    for root in (data, codex, grok):
        root.mkdir(parents=True)
        (root / "SENTINEL").write_text(f"untouched:{root.name}")
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("CODEX_HOME", str(codex))
    monkeypatch.setenv("GROK_HOME", str(grok))

    assert main(["demo", "--width", "100", "--ascii"]) == 0

    output = capsys.readouterr()
    assert output.err == ""
    assert "TANG ISOLATED DEMO" in output.out
    assert "SEARCH:" in output.out
    assert "INDEX: 4 indexed; status complete (0 warning(s))" in output.out
    assert "CONTEXT: 2 cited sources" in output.out
    assert "RESUME POINT:" in output.out
    assert "NEXT ACTION:" in output.out
    assert "[grok:019f6000-1234-7000-8000-000000000001" in output.out
    assert "SELECT:\n  G1 | grok |" in output.out
    assert "MULTIVERSE: selected sources G1 + C1 merge into C2" in output.out
    assert "confirmed OpenCode O1" in output.out
    assert "LINK: C5 -> O1 (confirmed; inserted 1)" in output.out
    assert "TANG MULTIVERSE MAP" in output.out
    assert "BRANCH" in output.out and "MERGE" in output.out
    assert "possibly interrupted" in output.out
    assert "ACTIVE O1" in output.out and "opencode" in output.out
    assert "codex:multiverse:" not in output.out
    workspace = Path(re.search(r"^Workspace: (.+)$", output.out, re.MULTILINE).group(1))
    assert not workspace.exists()
    for root in (data, codex, grok):
        assert (root / "SENTINEL").read_text() == f"untouched:{root.name}"
    assert not (data / "tang").exists()


def test_demo_output_is_deterministic_except_for_workspace_path(capsys) -> None:
    outputs = []
    for _ in range(2):
        assert main(["demo", "--width", "100", "--ascii"]) == 0
        rendered = capsys.readouterr().out
        outputs.append(re.sub(r"^Workspace: .+$", "Workspace: <temporary>", rendered, flags=re.MULTILINE))
    assert outputs[0] == outputs[1]


def test_demo_wide_unicode_map_includes_the_woven_network(capsys) -> None:
    assert main(["demo", "--width", "120"]) == 0

    output = capsys.readouterr().out
    assert "MULTIVERSE NETWORK · TIME FLOWS →" in output
    assert "×G2" in output and "★O1" in output
    assert "Implement deterministic checkpoint recovery" in output
    assert re.search(r"│ C1\s+│ codex\s+│.*?│ Implement deterministic", output)


def test_demo_unicode_override_preserves_network_when_detection_fails(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr("tang.cli._supports_unicode", lambda _stream: False)

    assert main(["demo", "--width", "120", "--unicode"]) == 0

    output = capsys.readouterr().out
    assert "MULTIVERSE NETWORK · TIME FLOWS →" in output
    assert "TIMELINE LANES · 5 ROOT-TO-LEAF PATHS" in output


def test_demo_can_force_color_for_redirected_capture(monkeypatch) -> None:
    output = _CaptureBuffer()
    monkeypatch.setattr("tang.cli.sys.stdout", output)
    monkeypatch.setenv("NO_COLOR", "1")

    assert main(["demo", "--width", "120", "--unicode", "--color", "always"]) == 0

    assert "MULTIVERSE NETWORK" in output.getvalue()
    assert "\x1b[" in output.getvalue()
