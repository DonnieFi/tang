# Harness capability matrix

Authoritative comparison of what Tang supports in v0.3.0. Implementation truth
is defined by `tang.harness_capabilities`,
`tang.adapter_registry.configured_adapters`, and `ResumeService`.

The v0.3.0 Linux release covers all four read-only adapters, explicit Tang-owned
continuation destinations, and exact native resume. Native session archives
remain read-only.

Legend: **yes** · **no** · **partial** (manual or source-only)

| Capability | Codex CLI 0.145.0 | Grok 0.2.106 | OpenCode 1.17.18–1.x | Cursor IDE / Agent 2026.07.17 |
| --- | --- | --- | --- | --- |
| Linux release claim | yes | yes | yes | yes |
| Read-only session adapter | yes | yes | yes | yes |
| Incremental index + checkpoint | yes | yes | yes | yes |
| Discovery capsule + FTS search | yes | yes | yes | yes |
| Browse / search (current project) | yes | yes | yes | yes |
| Context pack (cited native reread) | yes | yes | yes | yes |
| Link as **source** | yes | yes | yes | yes |
| Link as **destination** | yes | yes | yes | yes |
| Host current-target resolution | yes (skill) | no | yes (`/tang` tools) | no |
| Predecessor recall (`context all`) | yes | partial | yes | partial |
| `tang resume` native session | yes | yes | yes | yes |
| Host workflow (skill / MCP) | yes (`$tang`) | no | yes (`/tang`) | partial |
| `tang skill install …` | yes | no | yes (project-local) | no |
| Import from Tang into active session | yes | partial | yes | partial |
| Write recovered transcript to native logs | no | no | no | no |
| Write continuation edges (`.tang`) | yes | yes | yes | yes |
| Multiverse graph node | yes | yes | yes | yes |

**Partial notes:**

- **Grok:** Tang never writes Grok transcript stores. An indexed `G*` session
  can be an explicit link destination and can be reopened through Grok's native
  `--resume` contract. Context import remains a deliberate cited-pack handoff;
  there is no `--current` bridge.
- **Cursor:** Tang indexes project-scoped agent transcripts and enriches them
  from `~/.cursor/chats/<md5(path)>/…` sidecars when present. Composer-only
  SQLite history is out of scope. An indexed `R*` session can be an explicit
  link destination and can be reopened through Cursor Agent's `--resume` and
  `--workspace` contract. Context import remains a deliberate cited-pack
  handoff; there is no `--current` bridge.
- Cursor discovery maps native **`mode`** into the JSON **`effort`** field as
  an identifier only, not as Codex effort semantics.

## Version and platform pins

| Harness | Pin | Evidence |
| --- | --- | --- |
| Codex CLI | 0.145.0 | Live-verified local JSONL store and native resume contract (Linux) |
| Grok Build | 0.2.106 | Live-verified local store and native resume contract (Linux) |
| OpenCode | `>=1.17.18,<2.0.0` | Contract fixtures; 1.17.20 live-verified |
| Cursor Agent | 2026.07.17 | Live-verified local agent transcripts and native resume contract (Linux) |
| Tang package | v0.3.0 | Tagged wheel + README install URL |

macOS and Windows are unsupported for v0.3.0 (no CI claim).

## Native write / import policy

Tang **never** appends recovered transcript text to a harness's native session
store. Continuation is:

1. **Discovery and graph** — derived `.tang/tang.db` (capsules, FTS, edges).
2. **Active-session synthesis** — the host agent writes the Continuation Brief
   in the open chat; Tang does not persist that brief.
3. **Import from Tang** — delivering a Context Pack or brief into the **current**
   host context, with the untrusted-data envelope.
4. **Resume** — launching the owning harness CLI to reopen one **exact** indexed
   native session; no context or edge is added.

See [native-write-policy.md](native-write-policy.md) for write/import rules.

## Non-goals (v0.3 release claim)

- Cross-project discovery without explicit opt-in (research: bead `tang-9nb`).
- Semantic / vector search (`sqlite-vec`).
- Writing recovered transcript content to any native harness archive.
- Guessing an active Grok or Cursor target without a private host bridge.

## Delivery evidence

| Track | Bead |
| --- | --- |
| This matrix + doc guards | `tang-sis.9` |
| Grok destination + import | `tang-sis.10`–`tang-sis.12` |
| Cursor read + host + destination | `tang-sis.6`, `tang-sis.13`–`tang-sis.15` |
| In-code capability registry | `tang-sis.16` |
| Parity integration tests | `tang-sis.17` |
| Native-write spec amendment | `tang-sis.18` |

## Epic 11 extension (in progress — not a v0.3.0 release claim)

Implementation on branch `epic/11-claude-antigravity`. Fixture-verified on Linux;
live smoke uses `/opt/family-bot` Antigravity history and Claude Code JSONL.

| Capability | Claude Code 2.1.x | Antigravity CLI (`agy`) 1.1.x |
| --- | --- | --- |
| Linux release claim | no | no |
| Read-only session adapter | yes | yes |
| Incremental index + checkpoint | yes | yes |
| Discovery capsule + FTS search | yes | yes |
| Browse / search (current project) | yes | yes |
| Context pack (cited native reread) | yes | yes |
| Link as **source** | yes | yes |
| Link as **destination** | yes | yes |
| `tang resume` native session | yes (`claude --resume`) | yes (`agy --conversation`) |
| Host workflow (skill / handoff) | partial | partial |
| `tang skill install …` | no | no |

**Notes:**

- **Claude Code:** indexes flat `~/.claude/projects/<slug>/*.jsonl` for the
  resolved project path. Directory-only session folders without a root JSONL are
  skipped. Subagent sidechains are deferred.
- **Antigravity:** indexes `history.jsonl` rows filtered by `workspace`, rereads
  `brain/<id>/.system_generated/logs/transcript.jsonl`. Encrypted `conversations/*.pb`
  stores and nested subagent brains are out of scope for v1.
- **`/opt/tang`:** no native sessions on the dev host; use `/opt/family-bot` for
  live verification until Claude sessions exist under `-opt-tang`.

| Track | Bead |
| --- | --- |
| Session storage research | `tang-wxa.1` |
| Claude adapter + resume | `tang-wxa.3`, `tang-wxa.4` |
| Antigravity adapter + resume | `tang-wxa.6`, `tang-wxa.7` |
| Registry + matrix | `tang-wxa.9` |
