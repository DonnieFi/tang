from __future__ import annotations

import re
from pathlib import Path

from tang.cli import main


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
    assert "CONTEXT: 2 cited sources" in output.out
    assert "RESUME POINT:" in output.out
    assert "NEXT ACTION:" in output.out
    assert "[grok:019f6000-1234-7000-8000-000000000001" in output.out
    assert "LINK: codex:multiverse:g -> codex:multiverse:h (confirmed)" in output.out
    assert "TANG MULTIVERSE MAP" in output.out
    assert "BRANCH" in output.out and "MERGE" in output.out
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
