from pathlib import Path


def test_capture_script_uses_the_real_isolated_demo() -> None:
    script = (
        Path(__file__).parents[1] / "scripts" / "capture_demo_hero.py"
    ).read_text(encoding="utf-8")

    assert '[executable, "demo", "--width", "120"]' in script
    assert "TANG MULTIVERSE MAP" in script
    assert "pty.openpty()" in script
    assert "Console(" in script and "save_svg" in script
    assert 'r"\\s*@font-face' in script
    assert "shell=True" not in script
