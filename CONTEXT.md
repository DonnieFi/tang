# Tang architecture context

Tang is a local continuity layer for coding-agent sessions. It finds prior work
inside the active project, packages selected evidence with citations, and records
only continuations a person explicitly confirms. The approved behavior and
support boundary live in [`docs/tangspec.md`](docs/tangspec.md); this file records
the architectural reasons behind the main seams.

## Ubiquitous language

- **Native source:** a harness-owned session store that Tang reads but never
  rewrites.
- **Session identity:** the stable adapter, namespace, and native identifier used
  internally. Human surfaces use short project handles such as `C1` and `G1`.
- **Canonical project:** the repository or directory boundary inside which
  discovery, search, storage, and continuations are authorized.
- **Discovery Capsule:** at most 8 KiB of redacted, searchable session evidence.
- **Context Pack:** a bounded, source-cited reread of one or more selected native
  sessions, wrapped as untrusted historical evidence.
- **Continuation:** one atomic operation from one or more exact source sessions
  into one explicitly confirmed target session.
- **Multiverse:** the many-to-many directed acyclic graph created by repeating
  continuations across later targets.

## ADR 1: Native formats stay behind read-only adapters

**Status:** Accepted · **Date:** 2026-07-14

**Context:** Codex and Grok own different native formats and can change them
independently. Letting format details leak into indexing or context assembly
would couple the entire product to every harness revision.

**Decision:** Each adapter exposes two deep operations: checkpointed discovery
and rereading one exact selected session. It returns typed records, visible turns,
partial status, and warnings; callers never query native files directly.

**Consequences:** Tang can add adapters without changing its search, privacy,
context, or graph model. Adapters must reject path escapes, preserve last-known-
good checkpoints, and prove representative native shapes before support claims
expand.

## ADR 2: Canonical project identity is the authorization boundary

**Status:** Accepted · **Date:** 2026-07-14

**Context:** Native stores can contain sessions from many repositories, clones,
worktrees, and unrelated directories. Path-string equality is unstable across
Git worktrees and moves.

**Decision:** Resolve project hints through one trusted project seam. Linked Git
worktrees share the common repository identity; separate clones and non-Git
directories remain distinct. Search, context, target resolution, and graph writes
all require the active canonical project key.

**Consequences:** Tang refuses cross-project reads and links by default. Broader
discovery, if added, must be an explicit opt-in feature rather than weakening
this boundary.

## ADR 3: Derived storage is project-local and disposable

**Status:** Accepted · **Date:** 2026-07-16

**Context:** A user-global database made authority unclear during external-host
testing and allowed one project to be split across durable and temporary stores.
Tang also needs SQLite WAL files beside the database and a precise purge scope.

**Decision:** The canonical project owns `.tang/tang.db`. Tang stores only
derived session metadata, redacted capsules, checkpoints, FTS rows, stable human
handles, and confirmed edges. Native logs remain authoritative and read-only.
`tang demo` is the sole automatic temporary-storage path; `--database` is an
explicit diagnostic override.

**Consequences:** Clones have independent state, linked worktrees share state,
and purge has one understandable project boundary. `tang purge --all` removes
every derived row while retaining an empty permission-hardened SQLite container
for schema and WAL reuse. Tang does not automatically import experimental global
databases because their rows cannot be assigned safely to one project.

## ADR 4: Multi-source context uses one fair allocator

**Status:** Accepted · **Date:** 2026-07-15

**Context:** Concatenating sessions lets the first or longest transcript consume
the entire prompt budget. Persisting a model summary would lose inspectable
provenance and create a second source of truth.

**Decision:** Selected native sources are reread at request time, redacted, and
passed through one deterministic multi-source allocator. It reserves useful
evidence across sources, continues past oversized excerpts, caps the complete
pack near 2,000 estimated tokens, and cites every included excerpt from its
`citation` object.

**Consequences:** One large or damaged source cannot starve the others. The pack
reports omissions and warnings explicitly. GPT-5.6 may synthesize a Resume point
and Next action inside Codex, but Tang v0.1 does not persist that model prose.

## ADR 5: Explicit atomic continuations create the Multiverse DAG

**Status:** Accepted · **Date:** 2026-07-15

**Context:** Similar timestamps or subject matter do not prove that one session
continued another. A flat import log also cannot represent work that branches,
merges, and later becomes a source again.

**Decision:** One atomic operation links one or many exact sources to one
explicitly confirmed current Codex target. Validation checks identity, project,
availability, target support, duplicates, self-links, and cycles before any edge
is inserted. Replaying the same confirmed edge is idempotent. Repeating the
operation lets a target feed several later sessions and lets later targets merge
several earlier sessions, producing the many-to-many Multiverse DAG.

**Consequences:** Every rendered edge is auditable confirmation, never inferred
similarity. Tombstones retain minimal topology when native history disappears,
but unavailable sessions cannot form new links. The graph is continuity history,
not a claim that Tang can reopen or write into every harness.

## ADR 6: The Codex skill is the only interactive workflow

**Status:** Accepted · **Date:** 2026-07-15

**Context:** Source selection, uncertainty, and link confirmation need a
conversation. A second terminal UI would duplicate the host interaction model
and split safety policy between surfaces.

**Decision:** The Codex skill owns the interactive workflow and uses host-native
questions when available. The `tang` CLI remains deterministic and scriptable.
The verified wheel bundles the matching skill, installed with `tang skill install
codex`; `$tang` or a plain-English request invokes it in a new Codex session.

**Consequences:** Human previews hide canonical IDs and expose only redacted
names, page choices, and short stable handles. The skill maintains the exact ID
mapping privately, treats recovered text as untrusted evidence, and asks before
recording links. There is no competing selector and no `/tang` slash-command
support claim.
