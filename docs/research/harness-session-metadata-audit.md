# Harness session metadata audit (2026-07-21)

Re-check of native evidence vs what Tang indexes today. Goal: find
**bounded, identifier-like** facts that improve discovery/browse without
violating read-only privacy rules or `docs/tangspec.md` Capsule limits.

## What Tang stores today

| Layer | Fields |
| --- | --- |
| `SessionHeader` (adapter seam) | `model_provider`, `model_id`, `effort` — validated via `_header_value` (≤128 chars, no whitespace/controls) |
| Capsule `session_header` (v1) | Above + `title_origin`, `visible_turn_count`, `visible_text_bytes`, `version: 1` |
| Discovery JSON / FTS row | Same header fields surfaced in `DiscoveryRow` and CLI browse |

Turn counts and text size are computed **only after `read()`** during indexing,
not at scan time (except where scan already parsed the full native file).

Spec explicitly allows harness-dependent header facts; extending the field set
requires a **spec-approved** `session_header` version bump (currently v1).

---

## Per-harness native evidence

### Codex (`*.jsonl`)

**Scan + read** walk the same log. Today we retain:

| Native source | Tang field | Notes |
| --- | --- | --- |
| `session_meta.payload.model_provider` | `model_provider` | e.g. `openai` |
| Latest `turn_context.payload.model` | `model_id` | Last seen wins on scan |
| Latest `turn_context.payload.effort` | `effort` | e.g. `high` |
| `event_msg` `task_started` / `task_complete` | `health` | `complete` vs `unknown` |

**Available but not indexed** (fixtures: `tests/fixtures/codex/sessions/...`):

| Native field | Suggested Tang use | Risk / notes |
| --- | --- | --- |
| `session_meta.payload.cli_version` | `harness_version` or `cli_version` | Bounded semver-like string; useful for support |
| `session_meta.payload.context_window` | `context_window` (integer) | Safe numeric; not in `_header_value` today — needs new typed field |
| `session_meta.payload.originator` | `originator` | e.g. `codex_cli_rs` |
| `session_meta.payload.source` | `session_source` | e.g. `cli` vs IDE |
| `session_meta.payload.history_mode` | `history_mode` | Identifier |
| `turn_context.payload.collaboration_mode.mode` | `collaboration_mode` | e.g. `default` — not Cursor “Plan mode”; Codex-specific |
| `turn_context.payload.approval_policy` | `approval_policy` | e.g. `never` |
| `turn_context.payload.summary` | — | Auto-summary setting; low discovery value |
| `session_meta.payload.git.branch` | `git_branch` | Short branch name; **redact** URLs in `git.repository_url` — never index URL |
| `session_meta.payload.git.commit_hash` | — | Prefer not index full hash in v1 (long, low UX); optional truncated prefix with spec |

**Not available:** native session title (Codex relies on derived display name).

**Turn count at scan:** Could count visible user/agent rows during the existing
scan pass (same I/O). Would let browse show turn hints **before** re-read on
stale capsules; cost is already paid for fingerprinting.

---

### Grok (`summary.json` + `updates.jsonl`)

**Scan** reads `summary.json`. Today:

| Native | Tang |
| --- | --- |
| `current_model_id` | `model_id` |
| `generated_title` | `SourceRecord.title` → capsule `source_title` |
| `git_root_dir` | `project_hint` |
| `created_at` / `updated_at` | timestamps |

**Available in summary, not in header:**

| Native field | Suggested use | Notes |
| --- | --- | --- |
| `num_chat_messages` | `native_turn_count` or pre-index `visible_turn_count` hint | User/agent chat count without full read |
| `num_messages` | `native_event_count` | Includes non-chat events; label clearly in UI |
| `agent_name` | `agent_name` | e.g. `Grok` — identifier |
| `chat_format_version` | `format_version` | Schema drift signal |
| `last_active_at` | — | Redundant with `updated_at` if consistent |
| `session_summary` | **Do not index** | Model-generated prose; spec forbids persisting generated summaries as discovery primary text |

**Read path:** Parses `updates.jsonl` for visible turns; could merge latest
model from updates if summary drifts (not implemented).

**Effort:** Not present in Grok summary fixture; unknown if live logs expose it.

---

### OpenCode (HTTP catalog + CLI export)

**Scan** uses catalog items only — **no model in header today** (`SessionHeader()`
default on `SourceRecord`).

**Read** (`opencode export`) exposes rich `info`:

| Native (`info`) | Suggested use | Notes |
| --- | --- | --- |
| `model.providerID` / `model.id` | Already on read merge | Discovery stale until re-index |
| `model.variant` | Map to `effort` or new `model_variant` | Fixture: `"high"` — parallels Codex effort |
| `agent` | `agent_mode` | e.g. `build` |
| `version` | OpenCode CLI version | Same class as Codex `cli_version` |
| `cost`, `tokens.*` | Optional aggregates | Integers; privacy-safe but hackathon-low priority |
| `slug` | — | Internal; skip |

**Catalog gap:** If live catalog JSON includes `model` or `agent`, scan could
populate header without export-per-session (verify on live OpenCode 1.17+).

**Effort to fix discovery UX:** One lightweight export during index (already
happens on read) — scan-time header remains empty until first index.

---

### Cursor (`agent-transcripts/*/*.jsonl`)

**Scan:** mtime-only timestamps; empty `SessionHeader`; no title.

**Read:** Text blocks from user/assistant messages only; **tool payloads stripped**
from visible text (by design).

**Available in raw JSONL (not surfaced):**

| Native | Suggested use | Notes |
| --- | --- | --- |
| Assistant `tool_use` blocks (`Task`, etc.) `input.model` | `model_id` on read | e.g. `claude-sonnet-5-thinking-high`; last Task wins |
| `subagent_type` | `agent_mode` | e.g. `generalPurpose` |
| User message `<timestamp>` lines | — | Already in visible text |
| Composer DB / workspaceStorage | Titles, session lists | **Not implemented**; separate store; feasibility doc |

**Effort:** Not in transcript text path; would require parsing tool blocks without
indexing tool arguments (only whitelisted keys).

**Risk:** Indexing model from tool JSON is still identifier-like if we never
persist prompts or tool inputs.

---

## Cross-harness comparison

| Capability | Codex | Grok | OpenCode | Cursor |
| --- | --- | --- | --- | --- |
| Model provider at scan | Yes | No | No* | No |
| Model id at scan | Yes (last turn) | Yes | No* | No |
| Effort / variant | Yes (scan) | No | Read only (`variant`) | No |
| Native title at scan | No | Yes | Yes (catalog) | No |
| Turn count without read | Possible (scan pass) | Yes (`num_chat_messages`) | No | No |
| Health / completion | Yes | Unknown | Unknown | Unknown |
| Harness CLI version | Yes (not indexed) | N/A | Read (`info.version`) | N/A |

\*Unless catalog exposes model — verify live.

---

## Recommended priorities (post–spec approval)

1. **Low risk, high UX**
   - Grok: `num_chat_messages` → discovery hint (rename in JSON as
     `native_chat_message_count` to distinguish from post-read `visible_turn_count`).
   - OpenCode: populate `model_*` + map `model.variant` → `effort` on read merge
     (already have data; ensure discovery refresh).
   - Cursor: extract last `model` from assistant `tool_use` where `type==tool_use`
     and `name` in allowlist (`Task`, …) without storing `input` blob.

2. **Medium value**
   - Codex: `collaboration_mode`, `cli_version`, `approval_policy` as optional
     header strings.
   - Codex: optional `git_branch` from `session_meta` (never repository URL).

3. **Defer / non-goals**
   - Grok `session_summary`, Codex `base_instructions`, any git remote URL.
   - Token/cost totals unless demo needs “heavy session” badges.
   - Cursor composer SQLite titles until path-mapping bead is stable.

4. **Schema work**
   - Bump `session_header.version` to `2` in spec; add typed ints where needed
     (`context_window`, native counts).
   - Extend `needs_label_refresh` / `_SESSION_HEADER_VERSION` in `capsule.py`.
   - Migration: refresh-on-index only (no SQL column change — header lives in JSON).

---

## Bead

Follow-up implementation: **Enrich discovery session_header from harness-native
metadata** (child of `tang-sis`, created 2026-07-21) — blocked on spec delta for
new header fields.
