# Continue with Antigravity (handoff)

Antigravity CLI (`agy`) sessions are indexed when `history.jsonl` contains rows
for the active project `workspace` and a readable
`brain/<conversationId>/.system_generated/logs/transcript.jsonl` exists.

## CLI workflow

```bash
tang index --json
tang browse --json --page 1
tang search "your phrase" --json --page 1
tang context A1 --json
tang resume A1
```

Handles for Antigravity sources use the **`A`** prefix (for example `A1`).

Run these from the indexed project directory (for example `/opt/family-bot`).

## Host integration

Tang does not ship an Antigravity plugin in Epic 11. Use the CLI from a project
terminal alongside `agy`, or wrap the same `--json` commands in a project skill
you maintain locally.

## Import and destinations

- **Import:** paste or inject the Markdown Context Pack into the active Agent
  chat (untrusted envelope preserved).
- **Link destination:** explicit `tang link --to A*` edges when the conversation
  is indexed; there is no `--current` bridge.
- **Native resume:** `tang resume A1` runs `agy --conversation <id>` without
  creating a link or mutating native logs.

Encrypted protobuf stores and nested subagent brains are out of scope. See
[claude-handoff.md](claude-handoff.md) for the paired Claude Code workflow and
[native-write-policy.md](native-write-policy.md).
