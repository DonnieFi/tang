# Claude Code and Antigravity session storage (2026-07-23)

Research for **Epic 11** full harness parity. Separate from global discovery
(`docs/spec-deltas/global-discovery-v0.4.md`): these adapters index **native
session archives** into the project `.tang/tang.db`; they do not implement
phone-home or cross-project catalog mirrors.

Evidence: live paths on Linux (Debian, user `red`), public CLI `--help`,
fixture sampling, and prior art (contextforge Antigravity adapter, recall skill
matrix). Version pins are **provisional** until the feasibility bead captures
live-verified shapes on target hosts.

---

## Executive summary

| Harness | Primary index surface | Primary reread surface | Native resume | Tang v1 scope |
| --- | --- | --- | --- | --- |
| **Claude Code** | `~/.claude/projects/<slug>/*.jsonl` | Same file, append-only JSONL | `claude --resume <uuid>` / `-c` | Flat JSONL + project slug; defer directory-only orphans |
| **Antigravity CLI** | `~/.gemini/antigravity-cli/history.jsonl` | `brain/<id>/.system_generated/logs/transcript.jsonl` | `agy --conversation <id>` / `-c` | History + transcript JSONL; workspace filter; defer `.pb` |

Both harnesses match Tang's existing read-only adapter contract: scan,
incremental checkpoint, `read()` for visible turns, link source/destination,
native resume launcher — **no writes to native stores**.

---

## Claude Code

### Roots and overrides

| Path | Role |
| --- | --- |
| `~/.claude/` | Default config root |
| `CLAUDE_CONFIG_DIR` | Override entire config root (same layout) |
| `~/.claude/projects/` | Per-workspace session storage |
| `~/.claude/skills/` | User-installed skills (Superpowers-style ecosystem) |

Skills install target for Tang: `~/.claude/skills/tang/SKILL.md` (mirror Codex
layout; exact install path verified in implementation bead).

### Project path encoding (verified Linux)

Claude maps the **resolved absolute project directory** to a subdirectory of
`projects/`:

```
slug = "-" + path.lstrip("/").replace("/", "-")
```

Examples from this host:

| Workspace | Slug directory |
| --- | --- |
| `/home/red` | `-home-red` |
| `/opt/family-bot` | `-opt-family-bot` |
| `/home/red/.config/opencode` | `-home-red--config-opencode` |

**Risk:** docs disagree on encoding (some mention hashing). Tang must derive the
slug from the resolved project path and treat mismatch as `UNAVAILABLE`, not
guess alternate encodings silently.

### Session file layouts (version drift)

Two coexisting layouts on one host (Claude Code **2.1.152**):

1. **Flat JSONL (primary, 120 files here):**  
   `~/.claude/projects/<slug>/<session-uuid>.jsonl`

2. **Session directory (67 dirs here):**  
   `~/.claude/projects/<slug>/<session-uuid>/subagents/agent-*.jsonl`  
   Sometimes **no** `<session-uuid>.jsonl` at the directory root (15 UUIDs are
   directory-only with subagent sidechains only). Treat as `possibly_interrupted`
   or skip with a doctor warning until live repro confirms where the main
   transcript lives for current releases.

3. **Global sessions dir:** `~/.claude/sessions/` exists but was empty on this
   host — do not rely on it for v1.

**Subagents:** sidechain JSONL under `subagents/` with `isSidechain` markers in
main logs when present. v1: index **top-level session files** only; subagent
dirs are follow-up research, not release-blocking.

### JSONL record shape (sampled)

Append-only JSONL. Observed `type` values on a flat session file:

`permission-mode`, `file-history-snapshot`, `user`, `assistant`, `attachment`,
`system`, `last-prompt`, `ai-title`

User turn (identifier-safe header fields):

```json
{
  "type": "user",
  "message": { "role": "user", "content": "..." },
  "timestamp": "2026-07-04T23:44:01.137Z",
  "sessionId": "bc474f4d-463b-420f-9c29-dffab197546b",
  "cwd": "/home/red",
  "version": "2.1.142",
  "gitBranch": "HEAD",
  "entrypoint": "cli"
}
```

**Suggested Tang mapping:**

| Native | Tang field |
| --- | --- |
| `message` user/assistant text blocks | Visible turns |
| `timestamp` | Turn time (RFC 3339) |
| `version` | Harness CLI version (header extension) |
| `gitBranch` | Optional `git_branch` header |
| `ai-title` / derived first prompt | `SourceRecord.title` |
| Tool blocks in assistant messages | Strip from visible text (Cursor pattern) |

**Compaction:** `/compact` may truncate native history. Tang capsules remain
point-in-time; stale native files may diverge from indexed capsules (same class
as Codex/Cursor — document in session-continuity notes).

### Native resume contract

From `claude --help` (2.1.152):

| Flag | Behavior |
| --- | --- |
| `-r`, `--resume [value]` | Resume by session UUID, or interactive picker with optional search |
| `-c`, `--continue` | Continue most recent conversation **in current directory** |
| `-n`, `--name <name>` | Display name (picker / title hint) |
| `--fork-session` | New session ID when resuming |
| `--no-session-persistence` | Print mode only; sessions not saved |

Tang `tang resume` should spawn:

```bash
claude --resume <native-uuid>
```

with cwd = owning project directory. Picker mode (`--resume` without value) is
out of scope for non-interactive Tang. Validate UUID belongs to indexed
`SessionIdentity` and project slug matches resolved workspace.

**Project scoping:** resume picker is project-scoped; Tang already refuses
cross-project resume when worktree/path identity differs.

---

## Antigravity (Google Gemini CLI / `agy`)

### Roots

| Path | Role |
| --- | --- |
| `~/.gemini/antigravity-cli/` | **CLI 2.x** primary store (this research) |
| `~/.gemini/antigravity/` | IDE 2.0 parallel layout (same `brain/` patterns per community readers) |
| `~/.gemini/antigravity-cli/history.jsonl` | Conversation index (704 lines on host) |
| `~/.gemini/antigravity-cli/brain/<conversation-id>/` | Per-conversation artifacts + transcripts |
| `~/.gemini/antigravity-cli/conversations/*.pb` | Encrypted protobuf — **out of v1 scope** |

Environment override for log path: `agy --log-file` (per `--help`); default
index path is stable under `antigravity-cli/`.

### Conversation index (`history.jsonl`)

One JSON object per line:

```json
{
  "display": "can you review the last commit...",
  "timestamp": 1779221259972,
  "workspace": "/opt/family-bot",
  "conversationId": "001e3e8e-2bee-40ec-aa2c-3108b2227902"
}
```

**Tang scan:** filter rows where `workspace` resolves to the active Tang
project directory (same rules as Git worktree identity). Use `display` as title
hint, `timestamp` as millis → UTC datetime, `conversationId` as native id.

Fallback: older installs may also write
`~/.gemini/antigravity/history.jsonl` — adapter should probe CLI root first,
then IDE root, never merge duplicates silently (namespace hash per store root).

### Transcript reread (`transcript.jsonl`)

Path:

```
~/.gemini/antigravity-cli/brain/<conversationId>/.system_generated/logs/transcript.jsonl
```

Step-oriented JSONL (not chat-role based):

| source | type | Tang use |
| --- | --- | --- |
| `USER_EXPLICIT` | `USER_INPUT` | User visible text (`<USER_REQUEST>…</USER_REQUEST>`) |
| `MODEL` | `PLANNER_RESPONSE` | Agent planning/thinking + tool_calls — extract bounded prose from `thinking` only if no separate text event |
| `MODEL` | `GENERIC`, `CODE_ACTION`, … | Tool output — generally **exclude** from visible turns |
| `SYSTEM` | `CONVERSATION_HISTORY`, … | Skip |

Sample user row:

```json
{
  "step_index": 0,
  "source": "USER_EXPLICIT",
  "type": "USER_INPUT",
  "created_at": "2026-05-19T20:07:39Z",
  "content": "<USER_REQUEST>\n...\n</USER_REQUEST>\n..."
}
```

**513 lines** in one sampled conversation; dominant MODEL types are
`PLANNER_RESPONSE`, `VIEW_FILE`, `CODE_ACTION`, `RUN_COMMAND`. Visible-turn
policy must mirror Cursor: user requests + bounded agent prose, never persist
full command output blobs.

`transcript_full.jsonl` was **absent** on sampled brain dir — do not require it.

### Brain artifacts (non-transcript)

Under `brain/<id>/`: `task.md`, `implementation_plan.md`, `walkthrough.md`,
`.system_generated/messages/*.json`. Optional future enrichment; **not** v1
capsule primary text.

### Subagents

`INVOKE_SUBAGENT` / `GENERIC` rows reference nested `conversationId` under
another `brain/` tree. v1: index parent conversation from `history.jsonl` only;
nested brains are follow-up.

### Encrypted stores

`conversations/*.pb` and `*.db` sidecars are not plain JSONL. Community tools
(agy-reader, daemon-assisted decrypt) exist but violate Tang's "no daemon, no
silent global" posture for v1. Revisit only if JSONL path proves incomplete on
live verification.

### Native resume contract

From `agy --help` (changelog **1.1.5**):

| Flag | Behavior |
| --- | --- |
| `--conversation <id>` | Resume previous conversation by ID |
| `-c`, `--continue` | Continue most recent conversation |
| `--project <id>` | Project ID for session (verify vs workspace) |
| `--workspace` via `--add-dir` | Repeatable workspace roots |

Tang `tang resume` should spawn:

```bash
agy --conversation <conversationId>
```

with cwd = indexed workspace. Confirm exact flag stability in feasibility bead
(live `agy --conversation` against indexed fixture).

---

## Recommended adapter architecture

### Claude adapter (mirror Codex/Cursor)

1. Resolve `claude_home` from `CLAUDE_CONFIG_DIR` or `~/.claude`.
2. Map `project_dir` → slug → scan `projects/<slug>/*.jsonl`.
3. Incremental checkpoint: path + size + mtime (same as Cursor).
4. `read()`: walk `type in (user, assistant)` with text blocks; redact at seam.
5. `SessionIdentity`: `claude:store-<sha256(claude_home)>:<uuid>`.
6. Opt-in registry: include when `projects/<slug>/` exists (like Cursor).

### Antigravity adapter (history index + brain reread)

1. Resolve `antigravity_home` → `~/.gemini/antigravity-cli` (configurable).
2. `scan()`: tail/parse `history.jsonl` with workspace filter + checkpoint on
   byte offset or last seen timestamp.
3. `read()`: load matching `brain/<id>/.../transcript.jsonl`.
4. Parse USER_INPUT + selected MODEL prose types; strip tool dumps.
5. `SessionIdentity`: `antigravity:store-<sha256(home)>:<conversationId>`.
6. Opt-in when `history.jsonl` exists and at least one row matches project.

### Full-featured parity target (Epic 11)

Match v0.3 four-harness row where native contracts allow:

| Capability | Claude | Antigravity |
| --- | --- | --- |
| Read-only adapter | yes | yes |
| Incremental index + checkpoint | yes | yes |
| Discovery capsule + FTS | yes | yes |
| Browse / search (current project) | yes | yes |
| Context pack | yes | yes |
| Link source | yes | yes |
| Link destination | yes | yes |
| `tang resume` | yes | yes |
| Host skill / workflow | yes (`tang skill install claude`) | partial (handoff doc or skill if CLI supports) |
| Native store writes | **no** | **no** |

---

## Risks and open verification (feasibility bead)

1. **Claude directory-only sessions** without root JSONL — reproduce on fresh
   2.1.x session; document skip/warn behavior.
2. **Claude path encoding** — confirm on `/opt/tang` once sessions exist.
3. **Antigravity visible-turn policy** — legal review of which MODEL types count
   as agent prose vs tool noise.
4. **Antigravity version pin** — lock `agy` version after live resume smoke.
5. **Dual Gemini roots** — CLI vs IDE store collision policy.
6. **Subagents (both harnesses)** — defer; note in harness matrix as partial.
7. **Spec gate** — tangspec currently lists four harnesses; Epic 11 requires
   human-approved amendment before release claims.

---

## Prior art

- [contextforge Antigravity adapter](https://github.com/contextforge) — history +
  transcript JSONL, `--conversation` resume.
- [recall skill harness matrix](https://github.com/pratikgajjar/recall) — Claude
  `~/.claude/projects/**/*.jsonl`.
- Tang internal: `docs/harness-matrix.md`, `docs/session-continuity.md`,
  `src/tang/adapters/cursor.py` (JSONL + sidecar pattern).

---

## Beads

Epic **tang-wxa** (Epic 11): Claude Code and Antigravity full harness parity.
Children **tang-wxa.1**–**tang-wxa.12** created 2026-07-23; see
`bd show tang-wxa` for dependency graph.
