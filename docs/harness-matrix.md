# Harness capability matrix

Authoritative comparison of what Tang supports **today (v0.2.9)** versus the
**post-release roadmap** on branch `epic/10-beta-release`. Implementation
truth is defined by `tang.adapter_registry.configured_adapters`,
`ContinuationService.SUPPORTED_DESTINATION_ADAPTERS`, and `ResumeService`.

Legend: **yes** · **no** · **partial** (CLI or source-only) · **planned**

| Capability | Codex CLI 0.144.4 | Grok 0.2.99 | OpenCode 1.17.18–1.x | Cursor IDE |
| --- | --- | --- | --- | --- |
| Linux release claim | yes | yes | yes | no |
| Read-only session adapter | yes | yes | yes | no |
| Incremental index + checkpoint | yes | yes | yes | planned |
| Discovery capsule + FTS search | yes | yes | yes | planned |
| Browse / search (current project) | yes | yes | yes | planned |
| Context pack (cited native reread) | yes | yes | yes | planned |
| Link as **source** | yes | yes | yes | planned |
| Link as **destination** | yes | yes | yes | planned |
| Host current-target resolution | yes (skill) | no | yes (`/tang` tools) | planned |
| Predecessor recall (`context all`) | yes | partial | yes | planned |
| `tang resume` native session | yes | no | yes | planned |
| Host workflow (skill / MCP) | yes (`$tang`) | no | yes (`/tang`) | planned |
| `tang skill install …` | yes | no | yes (project-local) | planned |
| Import from Tang into active session | yes | partial | yes | planned |
| Write recovered transcript to native logs | no | no | no | no |
| Write continuation edges (`.tang`) | yes | yes | yes | planned |
| Multiverse graph node | yes | yes | yes | planned |

**Partial** notes:

- **Grok — predecessor recall:** Grok sessions may be **targets** for explicit
  `tang link --to` edges; there is no Grok host skill for `--current` linking
  or one-step predecessor recall in v0.2.9.
- **Grok — import from Tang:** Developers recover Grok **into** Codex or
  OpenCode via the skill/CLI, or record edges **into** an indexed Grok session
  with explicit `--to`; see [grok-handoff.md](grok-handoff.md). There is no
  Grok-side Tang integration in v0.2.9.

## Version and platform pins

| Harness | Pin | Evidence |
| --- | --- | --- |
| Codex CLI | 0.144.4 | Live-verified local JSONL store (Linux) |
| Grok Build | 0.2.99 | Live-verified local store (Linux); read-only source |
| OpenCode | `>=1.17.18,<2.0.0` | Contract fixtures; 1.17.20 live-verified |
| Cursor | — | Not claimed in v0.2; roadmap only |
| Tang package | v0.2.9 | Tagged wheel + README install URL |

macOS and Windows are **unsupported** for the hackathon release (no CI claim).

## Native write / import policy

Tang **never** appends recovered transcript text to a harness's native session
store. Continuation is:

1. **Discovery and graph** — derived `.tang/tang.db` (capsules, FTS, edges).
2. **Active-session synthesis** — the host agent writes the Continuation Brief
   in the open chat; Tang does not persist that brief in v1.
3. **Import from Tang** — delivering a Context Pack or brief into the **current**
   host context (skill/CLI/MCP injection), with the untrusted-data envelope.
4. **Resume** — launching the harness CLI to reopen an **exact** indexed session
   (Codex/OpenCode only today).

See [native-write-policy.md](native-write-policy.md) for write/import rules.

## Non-goals (v0.2)

- Cross-project discovery without explicit opt-in (research: bead `tang-9nb`).
- Semantic / vector search (`sqlite-vec`).
- Writing instructions from recovered content into native logs.
- Cursor or Grok as shipped, live-verified destinations without spec approval
  and live proof on Linux.

## Roadmap beads (Epic 10)

| Track | Bead |
| --- | --- |
| This matrix + doc guards | `tang-sis.9` |
| Grok destination + import | `tang-sis.10`–`tang-sis.12` |
| Cursor read + host + destination | `tang-sis.6`, `tang-sis.13`–`tang-sis.15` |
| In-code capability registry | `tang-sis.16` |
| Parity integration tests | `tang-sis.17` |
| Native-write spec amendment | `tang-sis.18` |
