from pathlib import Path


ROOT = Path(__file__).parents[1]
TOOL = ROOT / ".opencode" / "tools" / "tang_contract_probe.ts"


def test_opencode_contract_tool_passes_exact_context_without_exposing_it() -> None:
    source = TOOL.read_text(encoding="utf-8")

    assert '"--current-session-id"' in source
    assert "context.sessionID" in source
    assert '"--current-message-id"' in source
    assert "context.messageID" in source
    assert '"--cwd"' in source
    assert "context.directory" in source
    assert "context.worktree" in source
    assert "TANG_OPENCODE_EXECUTABLE" in source
    assert "expectedProvider" not in source
    assert '"--expect-provider"' not in source
    assert '"--overall-timeout"' in source
    assert '"--expected-version"' in source
    assert '"1.17.20"' in source
    assert "processResult.kill()" in source
    assert 'addEventListener("abort"' in source
    assert 'removeEventListener("abort"' in source
    assert "context.abort.aborted" in source
    assert 'stderr: "ignore"' in source
    assert "auth.json" not in source
    assert "console.log" not in source
