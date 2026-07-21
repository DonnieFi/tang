# Cursor local storage inventory (live Linux audit, 2026-07-21)

Tang’s current adapter reads **only** `~/.cursor/projects/<slug>/agent-transcripts/*/*.jsonl`
(text blocks, mtime timestamps, empty `SessionHeader`). That is one **mirror** of a
larger multi-store layout. This note maps what Cursor actually persists on disk,
what format it uses, and what is safe to index.

Paths below use Linux defaults:

| Root | Role |
| --- | --- |
| `~/.cursor/` | Agent project artifacts, chat SQLite, CLI state |
| `~/.config/Cursor/User/` | VS Code–compatible IDE state (SQLite `state.vscdb`) |

There is **no** Cursor session store under repo `.agent/` or Tang’s `.agents/skills/`
(those are project skills, not chat history).

---

## Architecture: three conversation stacks

Modern Cursor keeps **parallel** representations. They overlap by session UUID but
serve different consumers.

```text
                    ┌─────────────────────────────────────┐
                    │  ~/.config/Cursor/User/             │
                    │  globalStorage/state.vscdb          │
                    │  composerData + bubbleId + …        │  IDE Composer / Agent UI
                    └─────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    │                                   │
┌───────────────────▼──────────────────┐   ┌──────────▼──────────────────────────┐
│ ~/.cursor/chats/<ws-md5>/<agentId>/  │   │ ~/.cursor/projects/<slug>/          │
│ store.db + meta.json + prompt_history│   │ agent-transcripts/<id>/<id>.jsonl   │
│                                      │   │ agent-tools/, terminals/, repo.json │
└──────────────────────────────────────┘   └─────────────────────────────────────┘
         Store-backed agent tree                    Read-only transcript export
```

Public reverse-engineering (cursaves, forum guides, vibe-replay) describes the
**composer** stack; the **`~/.cursor/chats/**/store.db`** stack is newer and holds
**richer** turn data for the same `agentId` as the JSONL file on this host.

Reference: [how-cursor-stores-chats.md](https://github.com/Callum-Ward/cursaves/blob/main/docs/how-cursor-stores-chats.md),
[vibe-replay storage blog](https://vibe-replay.com/blog/cursor-local-storage/).

---

## 1. Store-backed sessions (`~/.cursor/chats/`)

### Layout

```text
~/.cursor/chats/
  <workspace-md5>/          # MD5 of absolute workspace path, e.g. md5("/opt/tang")
    <agentId>/              # Same UUID as agent-transcripts folder name
      store.db              # SQLite: conversation blobs
      meta.json             # Small JSON sidecar
      prompt_history.json   # Ordered list of user prompt strings
```

Verified on `/opt/tang`: workspace folder `59624ba325c8a24250ae2e0eea0375f0` ==
`md5("/opt/tang")`. Session `d63a860c-bf04-40da-a044-4dd2800a628c` exists in both
`chats/.../` and `projects/opt-tang/agent-transcripts/.../`.

### `meta.json` (text)

Example fields:

| Field | Example | Index use |
| --- | --- | --- |
| `schemaVersion` | `1` | Drift detection |
| `title` | `"Codebase Review And Research"` | Native title (like Grok `generated_title`) |
| `cwd` | `"/opt/tang"` | Project hint / isolation |
| `createdAtMs` / `updatedAtMs` | epoch ms | Timestamps (better than JSONL mtime) |
| `hasConversation` | `true` | Presence |

### `prompt_history.json` (text)

Array of **user prompt strings** only (newest-first in sample). Useful for discovery
snippets; treat as untrusted; may duplicate first user turn in transcript.

### `store.db` (SQLite)

Tables:

| Table | Content |
| --- | --- |
| `meta` | Single row; **hex-encoded JSON** session record |
| `blobs` | `id` (hash) → JSON message blob |

Decoded `meta` row (representative):

| Field | Example | Tang `SessionHeader` / discovery |
| --- | --- | --- |
| `agentId` | UUID | Native id (matches transcript) |
| `name` | title string | Title |
| `lastUsedModel` | `composer-2.5` | **`model_id`** |
| `mode` | `default` | **`agent_mode`** (spec TBD) |
| `approvalMode` | `unrestricted` | Policy hint |
| `isRunEverything` | `true` | Capability hint |
| `createdAt` | epoch ms | `started_at` |
| `latestRootBlobId` | sha256 | Internal graph pointer |

Blob JSON (representative roles): `system`, `user`, `assistant`, `tool`.

Content block types inside blobs:

| type | Notes |
| --- | --- |
| `text` | Visible user/assistant prose |
| `redacted-reasoning` | Hidden reasoning (do **not** index per Tang spec) |
| `tool-call` / `tool-result` | Tool I/O (privacy-sensitive) |

Model metadata appears in blobs under paths like:

`content[].providerOptions.cursor.modelName` (frequent),

and occasionally `content[].args.model` / `subagent_type` for Task-style subagents.

The JSONL export **flattens** assistant turns into `tool_use` blocks; the store
keeps parallel tool-call/result structure plus provider options.

**Read note:** copy `store.db` + `-wal` + `-shm` for consistent SQLite reads (same
as `state.vscdb`).

---

## 2. Project artifact tree (`~/.cursor/projects/<slug>/`)

Slug rule (Tang adapter): strip leading `/`, replace `/` with `-` → `opt-tang`.

| Path | Format | Purpose |
| --- | --- | --- |
| `agent-transcripts/<id>/<id>.jsonl` | JSONL | Read-only transcript mirror; user/assistant `message.content[]` text + `tool_use` |
| `agent-tools/<uuid>.txt` | UTF-8 text | Large tool outputs (e.g. fetched docs) |
| `terminals/*.txt` | text | Terminal snapshots metadata |
| `repo.json` | JSON | `{"id":"<project-uuid>"}` — Cursor internal project id |
| `worker.log` | log | Local worker |
| `.workspace-trusted` | flag | Trust state |
| `mcps/`, `canvases/` | varies | MCP/canvas state (other projects) |

Tang indexes **only** JSONL **text** blocks today. Same session JSONL contains
`tool_use.input.model`, `subagent_type`, etc., but Tang strips non-text blocks.

---

## 3. IDE composer storage (`~/.config/Cursor/User/`)

### Global DB: `globalStorage/state.vscdb`

SQLite tables: `ItemTable`, `cursorDiskKV` (key → BLOB, usually UTF-8 JSON).

**`cursorDiskKV` key families** (counts on sample host):

| Prefix | Role |
| --- | --- |
| `composerData:{composerId}` | Session metadata, bubble header list, `modelConfig`, `unifiedMode`, `context`, token stats |
| `bubbleId:{composerId}:{bubbleId}` | Per-message body (large) |
| `checkpointId:{composerId}:…` | Agent checkpoint / file snapshots |
| `agentKv:blob:…` / `agentKv:checkpoint:…` | Content-addressable agent context (Merklized) |
| `messageRequestContext:{composerId}:…` | Full request context sent to model |
| `composer.content.{hash}` | Shared content blobs |

**`ItemTable` keys** (selection):

| Key | Role |
| --- | --- |
| `composer.composerHeaders` | Cursor 3.0+ **global sidebar index** (`allComposers[]` with `workspaceIdentifier`, `name`, `unifiedMode`, timestamps) |
| `composer.composerData` | Legacy / UI selection state |
| `glass.localAgentProjects.v1` | Agent project groupings |
| `workbench.panel.composerChatViewPane.*` | Open tab → composerId mapping |

`composerData` metadata (documented externally) includes fields Tang would care about
for discovery **without** reading bubbles:

- `name`, `createdAt`, `unifiedMode` (`agent` | `chat` | `plan` | `edit`)
- `modelConfig.modelName`, `modelConfig.maxMode`
- `context` attachment summaries (files, rules, terminals — mostly paths)
- Branch hints such as `createdOnBranch` (workspace composer entries)
- Usage: `contextUsagePercent`, line add/remove totals (in workspace index entries)

**Important:** `composerId` in the IDE stack may **not** equal `agentId` in
`~/.cursor/chats/` for every workflow. On `/opt/tang`, the active long session
`d63a860c-…` is store+JSONL backed; it did not appear in `composer.composerHeaders`
grep for `tang` (IDE index may list other workspaces only, or CLI-first sessions
skip composer index).

### Workspace DB: `workspaceStorage/<opaque-id>/state.vscdb`

- `workspace.json` → `{ "folder": "file:///path/to/project" }`
- Pre–3.0: `composer.composerData.allComposers[]` held per-project sidebar metadata.
- Post–3.0 migration: often **only** `selectedComposerIds`, `lastFocusedComposerIds`,
  layout keys; canonical list moves to global `composer.composerHeaders`.

**This machine:** only `family-bot` and `career-ops` have `workspaceStorage` folders;
`/opt/tang` has **no** workspace DB yet — chats still live under `~/.cursor/chats/` +
`projects/opt-tang/`.

Workspace directory hash is **opaque** (not MD5 of path). Chats workspace hash **is**
MD5(path) under `~/.cursor/chats/` — two different hashing schemes.

---

## 4. AI code tracking (`~/.cursor/ai-tracking/ai-code-tracking.db`)

Separate SQLite DB (not conversation text):

| Table | Fields |
| --- | --- |
| `ai_code_hashes` | `hash`, `source`, `fileName`, `requestId`, **`conversationId`**, **`model`**, `timestamp` |
| `conversation_summaries` | `title`, `tldr`, `overview`, **`model`**, **`mode`** (often empty) |
| `scored_commits` | AI vs human line attribution |
| `tracked_file_content` | File snapshots tied to `conversationId` |

Useful for **correlating** model id to conversation UUID; not a substitute for turns.
High privacy risk if indexed naively (file paths and content).

---

## 5. Other `~/.cursor/` roots (not chat bodies)

| Path | Format | Notes |
| --- | --- | --- |
| `cli-config.json` | JSON | Cursor CLI settings |
| `agent-cli-state.json` | JSON | CLI worker ids by display name |
| `ide_state.json` | JSON | Recently viewed files (IDE) |
| `skills-cursor/` | skills | Bundled Cursor skills (not session history) |
| `agents/` | empty on sample | Not project `.agents` |
| `plans/` | | Plan artifacts |
| `statsig-cache.json` | JSON | Feature flags |

---

## 6. What Tang should index (recommendation)

Priority for **discovery metadata** (spec-safe, bounded):

| Source | Fields | When |
| --- | --- | --- |
| `chats/.../meta.json` | title, cwd, created/updated ms | Cheap at scan |
| `store.db` `meta` row | `lastUsedModel`, `mode`, `approvalMode`, `name`, `createdAt` | One SQLite read per session |
| `agent-transcripts/*.jsonl` | turns (current), tool `model` allowlist | Reread |
| `composer.composerHeaders` + `composerData` | title, `unifiedMode`, `modelConfig`, branch, usage | When workspace/global DB present |
| JSONL mtime | fallback timestamps | Today |

Do **not** index without explicit spec + redaction review:

- `redacted-reasoning`, full `tool-call`/`tool-result` bodies
- `messageRequestContext`, `agentKv` blobs, `tracked_file_content`
- `prompt_history.json` as authoritative (duplicate/untrusted)

**Identity mapping:** prefer **`agentId` / transcript UUID** as `native_id`; maintain
optional `composerId` alias when both exist (future bead).

**Path correction:** update `docs/research/cursor-adapter-feasibility.md` — on Linux,
IDE DBs live under `~/.config/Cursor/User/`, not `~/.cursor/User/`.

---

## 7. Gap vs current `CursorAdapter` (updated 2026-07-21)

| Capability | Status |
| --- | --- |
| Native title | **Yes** — `meta.json` + store meta `name` |
| Model | **Yes** — store `lastUsedModel`; read merge from Task `input.model` |
| Mode | **Yes** — mapped to `SessionHeader.effort` |
| Timestamps | **Yes** — meta ms fields; JSONL mtime fallback |
| Turn text | JSONL text only (store blobs not used) |
| Composer-only sessions | Still invisible without JSONL |
| Fingerprint | JSONL + `meta.json` + `store.db` |

---

## Follow-up beads (suggested)

1. Extend scan to read `meta.json` + store `meta` row for headers (read-only, WAL-safe).
2. Map `composer.composerHeaders` by `workspaceIdentifier.uri` → project path for IDE-only chats.
3. Document `composerId` vs `agentId` join rules on live hosts.
4. Fixture: synthetic `store.db` + `meta.json` beside JSONL for tests.

Related: [`harness-session-metadata-audit.md`](harness-session-metadata-audit.md),
[`cursor-adapter-feasibility.md`](cursor-adapter-feasibility.md),
[`project-identity-continuity.md`](project-identity-continuity.md).
