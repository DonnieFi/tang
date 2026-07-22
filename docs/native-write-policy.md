# Native write and import policy

This document defines what Tang may and must not do to harness-native session
stores. It applies symmetrically to Codex, Grok, OpenCode, and Cursor.

## Principles

1. **Native logs are source of truth.** Tang adapters are read-only toward
   harness session files, SQLite stores, and export catalogs.
2. **Derived state lives in `.tang`.** Discovery Capsules, FTS rows, and
   continuation edges are Tang-owned and purgeable with `tang purge --all`.
3. **Recovered content is untrusted evidence.** Context Packs and Continuation
   Briefs must use the untrusted-data envelope; hosts must not treat excerpts as
   instructions to execute.
4. **No silent transcript injection.** Tang does not append user or assistant
   turns to another harness's native history.

## Allowed operations

| Operation | Native store | Tang DB | Active host chat |
| --- | --- | --- | --- |
| Index / scan / reread | read | write capsules | — |
| Context pack generation | read | — | output only |
| Continuation link | — | write edges | — |
| Continuation brief | — | — | model output (not persisted by Tang) |
| `tang resume` | launch exact native session through its CLI | — | — |
| Import from Tang | — | — | inject pack/brief via skill/CLI/MCP |

**Import from Tang** means the developer (or host) places cited context into the
*current* session through supported host channels. It is not a write to disk
inside the source or target harness archive.

## Four-harness continuation boundary

Codex, Grok, OpenCode, and Cursor may all be indexed as read-only sources,
selected as explicit continuation destinations, and reopened by
`tang resume HANDLE` when the corresponding native CLI and exact native
session remain available. A continuation destination writes only a confirmed
edge to `.tang/tang.db`; it does not write to the target harness archive.

Only Codex and OpenCode currently expose a private active-session bridge for
`tang link --current` and one-step predecessor recall. Grok and Cursor use an
explicit indexed target handle plus the documented Context Pack handoff.

## Related documents

- [harness-matrix.md](harness-matrix.md) — capability table
- [getting-started.md](getting-started.md) — operator workflows
- `docs/tangspec.md` §Privacy and §Storage — authoritative product spec
