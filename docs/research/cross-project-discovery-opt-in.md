# Safe opt-in discovery of non-project sessions (tang-9nb)

Tang v0.1 indexes and discovers **only the active project** (spec §Index).
This document compares designs for an explicit post-release opt-in without
weakening source selection, privacy, or project isolation.

## Problem

Developers sometimes want to find or cite sessions from another checkout,
monorepo sibling, or prior workspace path. Today those sessions may exist in
native stores but never appear in `tang browse` / `tang search` for the active
project.

## Threat model

| Risk | Mitigation principle |
| --- | --- |
| Accidental context mixing | No silent cross-project FTS; explicit scope per query |
| Wrong DB merge | Never alias unrelated `project_key` values without consent |
| Secret leakage via snippets | Same redaction seams; foreign titles still untrusted |
| Stale path after rename | Opt-in registry must handle revoke + purge |
| Prompt injection via foreign excerpts | Untrusted envelope unchanged; user selects sources |

## Design comparison

### A. Project-local shards (status quo + hints)

Each repo keeps `.tang/tang.db`. Foreign work stays invisible until the user
`cd` there and indexes.

- **Pros:** Strong isolation; matches current spec.
- **Cons:** No unified search; duplicate native scans per checkout.

### B. Global non-content catalog

A user-level index (e.g. `~/.tang/catalog.db`) listing `(project_key, source_id,
harness, handle, updated_at, display_name)` **without** capsule bodies or FTS
content until explicitly attached.

- **Pros:** Fast cross-project browse; capsules stay project-local until import.
- **Cons:** Metadata still sensitive; needs purge/revoke UX; checkpoint scope unclear.

### C. User-selected project registry

Config file lists allowed project roots or keys. Index/discovery unions metadata
from registered projects only when `--scope registered` (or skill flag).

- **Pros:** Explicit consent list; auditable.
- **Cons:** Path moves break registry; worktree semantics need git-common-dir keys.

### D. Tool parallels

| Tool | Cross-workspace behavior | Tang takeaway |
| --- | --- | --- |
| Cursor | SQLite workspaceStorage by path hash | Path rename orphans UI history |
| cursor-chat-browser | Per-workspace FTS on transcripts | Read-only; no graph edges |
| Git worktrees | Shared object store, separate dirs | Tang already keys git via common dir |

## Metadata vs capsules vs edges vs checkpoints

| Artifact | May be global? | Recommendation |
| --- | --- | --- |
| Discovery capsules (8 KiB JSON) | **No** by default | Stay project-local; optional **import** copies one session into active project with new source_id policy |
| FTS rows | **No** | Project-scoped; union search only with explicit multi-project mode |
| Continuation edges | **No** | Edges always bind to one `project_key`; cross-project link requires spec + confirmation |
| Adapter checkpoints | **No** | Per `(project_key, adapter, namespace)`; global catalog must not reuse foreign checkpoints |
| Browse metadata only | **Optional** | Candidate for design C registry |

## Proposed user journey (draft)

1. User runs `tang projects register /path/to/other` (explicit; shows resolved
   `project_key` and git identity).
2. `tang index --all-registered` refreshes foreign **metadata shards** or
   read-only catalog entries—never writes foreign `.tang` without user action.
3. `tang browse --scope registered` lists sessions with **project badge**;
   canonical IDs remain private in skill flow.
4. Selecting a foreign source for context either:
   - **Read-through:** ephemeral read from foreign project's indexed capsule (if
     registered and indexed there), or
   - **Import:** copy bounded capsule into active project (new bead; spec delta).
5. `tang projects unregister` + `tang purge` on a registry entry revokes future
   visibility; does not delete foreign `.tang` unless user targets that path.

## Foreign-session warnings

Existing index `diagnostics` with `scope: foreign` prove store-wide issues that
do not affect the active project. Cross-project mode must **upgrade** warnings
when a registered project fails scan (degraded badge on that project only).

## Worktree and rename

- **Git worktrees:** Same `project_key` → same `.tang` at common git dir policy
  is unchanged; registry should dedupe by key.
- **Rename/move:** Registry entries store `project_key` + last resolved path;
  stale paths fail closed with actionable error until user re-registers.

## Recommendation

1. **Do not** implement cross-project FTS or a global capsule database in v0.3
   without an approved spec amendment.
2. **Prefer design C** (registry + metadata union) over a fully global DB.
3. **First spec delta:** `tang projects` subcommands, `--scope` for browse/search,
   and rules for read-through vs import.
4. **Keep** continuation edges project-local; cross-project recovery remains
   compare-and-select, never automatic merge.

## Related

- `docs/research/project-identity-continuity.md`
- `tang-9nb` acceptance: human review before code.
