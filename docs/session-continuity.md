# Session continuity: Tang vs host compaction

Tang complements host session memory; it does **not** replace it.

## What the host keeps

Coding agents (Codex, OpenCode, Cursor, etc.) store conversation history in
native logs or databases. When context windows fill, hosts may **compact** or
summarize older turns. After compaction:

- `--resume` continues the same native session ID but **does not guarantee** full
  verbatim history.
- Summaries may drop decisions, file paths, or rejected approaches.

## What Tang keeps (project-local)

Under `.tang/tang.db` for the **current project only**:

| Artifact | Survives host compaction? | Purpose |
| --- | --- | --- |
| Discovery Capsules | yes | Find sessions by phrase |
| FTS index | yes | Search capsules |
| Session metadata | yes | Handles, harness, health, timestamps |
| Continuation edges | yes | Multiverse graph |
| Context Pack / Brief | no (not stored) | Generated on demand |

Tang **rereads native logs** when building a Context Pack. If native history was
compacted or deleted, reread returns partial or unavailable status with warnings.

## When to re-index

Run `tang index --json` when:

- You start a **new recovery workflow** after native sessions changed.
- A session you expect is missing from browse/search.
- `tang doctor --json` reports adapter or database degradation.

You do **not** need to index before every browse/search in the same workflow.

## When to use predecessor recall

If you already confirmed continuation links into the **current** Codex or
OpenCode session, use:

```bash
tang context all --current-native-id <id> --json   # Codex skill path
```

or OpenCode `/tang context` one-step recall — this rereads **cited** predecessor
evidence without creating new edges.

## What Tang does not do

- Prevent or inspect host compaction.
- Restore host-deleted native logs.
- Store GPT-generated Continuation Briefs in `.tang`.

See [harness-matrix.md](harness-matrix.md) and [native-write-policy.md](native-write-policy.md).
