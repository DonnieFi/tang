# Project identity and workspace path continuity (tang-sis.5)

## Problem

IDE hosts (especially Cursor) key chat history off **workspace folder paths**.
Renaming, moving, or opening a duplicate checkout can hide prior sessions in the
UI even though files still exist on disk.

Tang keys projects by:

- **Git:** `git rev-parse --git-common-dir` (worktrees share one key).
- **Non-git:** resolved directory path.

The derived database lives at `<project-root>/.tang/tang.db` and does not
automatically follow a renamed directory.

## Threat model

- **Wrong merge:** Aliasing two unrelated directories to one Tang DB would mix
  sessions and graph edges — unacceptable without explicit user consent.
- **Orphan DB:** After `mv old new`, `old/.tang` remains while developers work
  in `new/` with an empty index.

## Options

| Approach | Pros | Cons |
| --- | --- | --- |
| User-run `tang migrate --from OLD --to NEW` | Explicit, auditable | Manual step |
| Detect orphan `.tang` sibling paths | Helpful hint | Heuristic false positives |
| Stable ID file in repo (`.tang/project.id`) | Survives rename inside tree | Needs git commit or local-only file policy |
| Cross-project opt-in catalog | Finds foreign capsules | Spec-deferred (`tang-9nb`) |

## Recommendation

1. **v0.3:** On `tang index`, if `.tang/tang.db` is missing but a sibling path
   with matching git common dir hash exists, print a **non-destructive hint**
   (no auto-migrate).
2. **Defer** global aliases until `tang-9nb` spec approval.
3. **Document** Cursor `workspaceStorage` behavior in judge-facing docs only;
   do not read Cursor workspace DB from Tang core except via Cursor adapter
   transcripts (`tang-sis.13`).

No implementation without approved spec change for automatic migration.
