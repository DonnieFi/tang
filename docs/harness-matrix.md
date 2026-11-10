# Harness capability matrix

What the Rust CLI in `rust/` does on Linux. There is no separate tagged-binary release claim. macOS and Windows are unsupported.

Legend: **yes** · **no**

| Capability | Codex | Grok | OpenCode | Cursor | Claude | Antigravity | OpenClaw |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Read-only index | yes | yes | yes | yes | yes | yes | yes |
| Incremental checkpoint | no | no | no | no | no | no | no |
| Capsule and project FTS | yes | yes | yes | yes | yes | yes | yes |
| Context reread of a regular file | yes | yes | yes | yes | yes | yes | yes |
| Link as source or destination | yes | yes | yes | yes | yes | yes | yes |
| `tang resume` launches the harness | yes | yes | yes | yes | yes | yes | no |
| `tang skill install` | yes | no | yes | no | yes | no | no |
| Current-target lookup | yes | no | yes | no | no | no | no |
| Writes native logs | no | no | no | no | no | no | no |

`tang index` scans a harness only when its `--*-home` flag is set, except Codex, which is the default when no harness flag is set. Every reader skips other projects and symlinked logs. None of them write `adapter_checkpoints`.

**Notes:**

- **Codex.** `--current --current-native-id` resolves a Codex `native_id` in the project database and uses that session as the link target. Resume runs `codex resume`.
- **Grok.** Resume needs the recorded project directory and runs `grok --resume`. There is no current-target bridge.
- **OpenCode.** The home flag is an export directory. Identity is the SHA-256 of that directory. Resume runs `opencode --session`. Skill install copies the skill and the `/tang` tools.
- **Cursor.** Sidecar `createdAtMs` and `updatedAtMs` are read when present. Resume runs `agent --resume`. There is no skill install.
- **Claude.** A transcript with no `cwd` is indexed when it sits under the project slug directory. Resume runs `claude --resume`.
- **Antigravity.** A symlinked `history.jsonl` is skipped with a warning. Resume runs `agy --conversation`.
- **OpenClaw.** Every `agents/*/agent/openclaw-agent.sqlite` is indexed. Identity is the SHA-256 of the home, shared across agents. Context reread opens that database read-only and keeps only the selected session. Resume is unsupported.

Grok Bot is not a reader. The OpenCode and OpenClaw identity hashes, the missing checkpoints, and Python `user_version` 8 remain open decisions.
