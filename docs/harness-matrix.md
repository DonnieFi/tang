# Harness capability matrix

Authoritative comparison of what Tang supports on branch `epic/10-beta-release`.
Implementation truth is defined by `tang.harness_capabilities`,
`tang.adapter_registry.configured_adapters`, and `ResumeService`.

The **v0.2.9 Linux release claim** remains Codex + Grok + OpenCode only; Cursor
and expanded Grok destination behavior on this branch are **beta** until spec
reconciliation (see `decision.md`).

Legend: **yes** · **no** · **partial** (CLI or source-only) · **beta** (implemented, not release-claimed)

| Capability | Codex CLI 0.144.4 | Grok 0.2.99 | OpenCode 1.17.18–1.x | Cursor IDE |
| --- | --- | --- | --- | --- |
| Linux release claim | yes | yes | yes | no |
| Read-only session adapter | yes | yes | yes | beta |
| Incremental index + checkpoint | yes | yes | yes | beta |
| Discovery capsule + FTS search | yes | yes | yes | beta |
| Browse / search (current project) | yes | yes | yes | beta |
| Context pack (cited native reread) | yes | yes | yes | beta |
| Link as **source** | yes | yes | yes | beta |
| Link as **destination** | yes | yes | yes | beta |
| Host current-target resolution | yes (skill) | no | yes (`/tang` tools) | no |
| Predecessor recall (`context all`) | yes | partial | yes | no |
| `tang resume` native session | yes | no | yes | no |
| Host workflow (skill / MCP) | yes (`$tang`) | no | yes (`/tang`) | partial |
| `tang skill install …` | yes | no | yes (project-local) | no |
| Import from Tang into active session | yes | partial | yes | partial |
| Write recovered transcript to native logs | no | no | no | no |
| Write continuation edges (`.tang`) | yes | yes | yes | beta |
| Multiverse graph node | yes | yes | yes | beta |

**Partial / beta notes:**

- **Grok — native logs:** Tang never writes Grok transcript stores; sessions may
  still be **link destinations** when indexed (`grok-handoff.md`).
- **Grok — predecessor recall:** explicit `tang link --to` only; no Grok host
  `--current` bridge in v0.2.9.
- **Cursor — beta:** Indexes when `~/.cursor/projects/<slug>/agent-transcripts/`
  exists; enriches from `~/.cursor/chats/<md5(path)>/…` sidecars when present.
  Not in the v0.2.9 wheel claim; composer-only SQLite history is out of scope.
  Discovery maps Cursor **`mode`** into the JSON **`effort`** field (identifier
  only, not Codex effort semantics).
- **Cursor — import:** Context packs and handoff doc; no `--current` link bridge.

## Version and platform pins

| Harness | Pin | Evidence |
| --- | --- | --- |
| Codex CLI | 0.144.4 | Live-verified local JSONL store (Linux) |
| Grok Build | 0.2.99 | Live-verified local store (Linux); read-only native source |
| OpenCode | `>=1.17.18,<2.0.0` | Contract fixtures; 1.17.20 live-verified |
| Cursor | — | Beta on branch; not in v0.2.9 release claim |
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

## Non-goals (v0.2 release claim)

- Cross-project discovery without explicit opt-in (research: bead `tang-9nb`).
- Semantic / vector search (`sqlite-vec`).
- Writing instructions from recovered content into native logs.
- Claiming Cursor in the **v0.2.9** marketing surface without spec approval
  and live proof on Linux (beta code may exist on this branch).

## Roadmap beads (Epic 10)

| Track | Bead |
| --- | --- |
| This matrix + doc guards | `tang-sis.9` |
| Grok destination + import | `tang-sis.10`–`tang-sis.12` |
| Cursor read + host + destination | `tang-sis.6`, `tang-sis.13`–`tang-sis.15` |
| In-code capability registry | `tang-sis.16` |
| Parity integration tests | `tang-sis.17` |
| Native-write spec amendment | `tang-sis.18` |
