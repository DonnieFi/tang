# Native write and import policy

This document defines what Tang may and must not do to harness-native session
stores. It applies to Codex, Grok, OpenCode, and any future Cursor integration.

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
| `tang resume` | launch CLI only | — | — |
| Import from Tang | — | — | inject pack/brief via skill/CLI/MCP |

**Import from Tang** means the developer (or host) places cited context into the
*current* session through supported host channels. It is not a write to disk
inside the source or target harness archive.

## Future destinations (Grok, Cursor)

Before Grok or Cursor become **link destinations** or receive automated import:

- Spec maintainer approves an explicit amendment to `docs/tangspec.md`.
- Live-verified Linux proof for target resolution and confirmation UX.
- Redaction and project-isolation tests match Codex/OpenCode bars.

Until then, Grok remains a **read-only source** in release claims; Cursor
remains **unclaimed**.

## Related documents

- [harness-matrix.md](harness-matrix.md) — capability table
- [getting-started.md](getting-started.md) — operator workflows
- `docs/tangspec.md` §Privacy and §Storage — authoritative product spec
