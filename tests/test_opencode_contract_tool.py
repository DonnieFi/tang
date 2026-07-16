from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / ".opencode" / "tools" / "tang_contract_probe.ts"


def test_opencode_contract_tool_passes_exact_context_without_exposing_it() -> None:
    source = TOOL.read_text(encoding="utf-8")

    assert '"--current-session-id"' in source
    assert "context.sessionID" in source
    assert '"--cwd"' in source
    assert "context.directory" in source
    assert "context.worktree" in source
    assert "TANG_OPENCODE_EXECUTABLE" in source
    assert "auth.json" not in source
    assert "console.log" not in source
