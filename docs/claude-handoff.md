# Continue with Claude Code and Antigravity (handoff)

Post-v0.3.0 harnesses indexed from native stores on Linux. Tang remains
read-only on all native archives.

## Claude Code

Sessions live under `~/.claude/projects/<slug>/*.jsonl` where `<slug>` encodes the
resolved project path (for example `/opt/family-bot` → `-opt-family-bot`).

```bash
tang index --json
tang browse --json --page 1
tang search "phrase" --json --page 1
tang context L1 --json
tang resume L1
```

- **Handles:** `L*` prefix
- **Skill:** `tang skill install claude` installs `~/.claude/skills/tang/SKILL.md`
- **Import:** paste or inject the Markdown Context Pack into the active Claude
  session (untrusted envelope preserved)
- **Link destination:** explicit `tang link --to L*` edges when indexed
- **Native resume:** `tang resume L1` runs `claude --resume <uuid>` from the
  recorded project directory

Directory-only Claude folders without a root JSONL are skipped. Subagent
sidechains are not indexed in v1.

## Antigravity CLI

Sessions are indexed from `~/.gemini/antigravity-cli/history.jsonl` (filtered by
`workspace`) and reread from
`brain/<conversationId>/.system_generated/logs/transcript.jsonl`.

```bash
tang index --json
tang browse --json --page 1
tang context A1 --json
tang resume A1
```

- **Handles:** `A*` prefix
- **Host workflow:** CLI from the project terminal (no bundled skill in v1)
- **Native resume:** `tang resume A1` runs `agy --conversation <id>`
- **Skipped:** encrypted `conversations/*.pb`, nested subagent brains, history
  rows without a transcript file

## Privacy

See [native-write-policy.md](native-write-policy.md). Tang never writes
recovered transcript text back to Claude or Antigravity native stores.
