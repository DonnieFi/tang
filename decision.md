# Decision Log

Material decisions are recorded here, newest last. Routine implementation choices and transient debugging stay out. Format per `AGENTS.md`.

Serves = which of the four equally-weighted judging criteria the decision advances:
Technological Implementation · Design · Potential Impact · Quality of Idea.

---

## 2026-07-14T20:24:40Z · project · Adopt AGENTS.md execution contract
- Context: Multi-epic, agent-driven hackathon build needs consistent, low-token operating rules.
- Options: (a) ad-hoc per-session prompts; (b) a committed AGENTS.md + decision.md contract.
- Decision: (b) — create a tracked `AGENTS.md` and `decision.md` contract with branch-per-epic delivery, autonomous child work, evidence-based escalation, and human-gated epic promotion. Serves: Technological Implementation, Design.
- By: agent

## 2026-07-14T20:24:40Z · project · Separate epic review from promotion
- Context: Each Beads close-gate child includes verification, a branch milestone, promotion to `main`, and closure. The execution contract must provide a real human review point without leaving the Beads acceptance criteria incomplete.
- Options: (a) let the agent complete the entire gate before review; (b) halt before the milestone commit; (c) verify and commit on the epic branch, keep the gate open for human review, then promote and close only after approval.
- Decision: (c) — it preserves a reviewable, tested commit while keeping promotion and epic transition human-controlled. Serves: Technological Implementation, Design.
- By: agent, implementing the human-gated policy established in `AGENTS.md`

## 2026-07-14T20:31:41Z · project · Tell the many-to-many continuity story
- Context: A single Grok-to-Codex recovery sounds like a one-off importer. Tang's atomic action selects many sources into one confirmed current target; repeating it across later targets creates a many-to-many session DAG with branches and merges. The release still has only Codex as a target harness.
- Options: (a) describe only one Grok-to-Codex hop; (b) claim unsupported bidirectional target integration; (c) lead with the many-to-many session graph produced by repeated multi-source continuation into Codex, while stating symmetrical handle-to-handle continuity as product direction.
- Decision: (c) — make the many-to-many Multiverse the product model without overstating v0.1 target-harness support. Serves: Potential Impact, Quality of Idea, Design.
- By: human (product direction) and agent (support-boundary wording)

## 2026-07-14T20:36:17Z · project · Profile Sol effort per Bead
- Context: Tang's Beads range from mechanical packaging to ambiguous adapter research, adversarial privacy work, graph algorithms, visual polish, and compound release gates. One default reasoning level would either waste time or underthink high-risk work.
- Options: (a) use one Sol setting everywhere; (b) assign profiles to all Beads once, before implementation evidence exists; (c) require a recorded model, effort, execution mode, and rationale when each Bead is reviewed before claim.
- Decision: (c) — default to Sol/medium and single-agent execution, escalate effort for demonstrated complexity, and reserve Ultra for genuinely separable workstreams. Serves: Technological Implementation, Design.
- By: human (requirement) and agent (profile rubric based on current Codex guidance)

## 2026-07-14T22:24:51Z · tang-xqa.3 · Proceed with the documented local Grok session store
- Context: The release-blocking feasibility gate had to prove that representative real Grok data exposes stable identity, project association, timestamps, and visible user/agent turns without committing private transcript content. Grok Build 0.2.99 (stable, build `b1b49ccb71`) documents and live-populates `$GROK_HOME/sessions/<percent-encoded-cwd>/<uuidv7>/summary.json` plus authoritative ACP `updates.jsonl`. A schema-only read of one representative real session found one consistent session ID across 955 timestamped updates, including 35 visible user text chunks and 55 visible agent text chunks; metadata supplied RFC 3339 timestamps, model/format fields, and Git-root association.
- Options: (a) proceed against the documented local store; (b) narrow the release to explicit Markdown exports; (c) stop the Grok support claim.
- Decision: (a) — proceed with a read-only adapter for the documented local session store, live-claim Grok Build 0.2.99 on Linux, derive a sanitized fixture from that verified shape, and describe other versions as fixture-verified unless separately live-tested. No private transcript text or source locator is recorded in repository evidence. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, under the approved time-boxed feasibility gate

## 2026-07-14T23:02:22Z · tang-xqa.7 · Correct the Epic 1 execution-thread evidence
- Context: The scaffold bead predesignated Codex thread `019f6149-7a69-7351-8c02-101b4288b429` as the intended majority-core thread, but the implementation and gate review actually continued in thread `019f62b2-5a7d-75c3-922d-969b182ec9a2`. Release evidence must distinguish intent and provenance from the thread that performed the recorded work.
- Options: (a) retain the predesignated thread as the majority-core claim; (b) report both without qualification; (c) preserve the earlier thread as baseline/handoff provenance and record the later thread as the actual Epic 1 implementation and review thread.
- Decision: (c) — use `019f62b2-5a7d-75c3-922d-969b182ec9a2` for Epic 1 implementation/review evidence and retain `019f6149-7a69-7351-8c02-101b4288b429` only as the predesignated baseline/handoff thread. Serves: Technological Implementation, Design.
- By: agent, correcting evidence against the observed execution history

## 2026-07-14T23:09:28Z · tang-xqa.6 · Promote the reviewed Epic 1 milestone
- Context: Human review approved the hardened Epic 1 branch milestone for promotion after all privacy and resilience findings were resolved and the renewed gate evidence passed.
- Options: (a) fast-forward the reviewed milestone into `main`; (b) create a merge commit; (c) defer promotion.
- Decision: (a) — fast-forward `epic/01-grok-feasibility` milestone `ef574770b24f417a92976b83ed9d17ad4b735e8a` into `main`, producing promotion SHA `ef574770b24f417a92976b83ed9d17ad4b735e8a`. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (promotion approval) and agent (verified fast-forward execution)

## 2026-07-14T23:16:58Z · tang-oda.2 · Keep Codex native-log identity distinct from thread linkage
- Context: Across 23 live Codex 0.144.4 logs, each metadata `id` matched the UUID in its native filename, while nine valid logs carried a different `session_id` used for thread or parent linkage. Treating `session_id` as the native record identity would collapse or reject independently stored histories.
- Options: (a) require both fields to equal the filename UUID; (b) key records by `session_id`; (c) key records by the filename and matching metadata `id`, retaining `session_id` as non-identity native linkage.
- Decision: (c) — use the one-file/one-`id` UUID as the stable Codex adapter identity and do not reinterpret native `session_id` linkage as record identity. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, based on privacy-safe structural inspection of representative live data

## 2026-07-14T23:19:26Z · tang-oda.5 · Treat recency as ranking, not target proof
- Context: Several Codex sessions can be active or recently updated in one project, including delegated and remote work. Modification recency produces a useful deterministic order but does not prove which session the user intends as the continuation target.
- Options: (a) automatically choose the most recent eligible session; (b) resolve only a host-supplied native ID or the sole eligible session and otherwise require an explicit choice; (c) refuse all automatic resolution.
- Decision: (b) — use recency only to rank confirmation candidates; resolve automatically only from unique native evidence or a single eligible current-project session. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, applying the approved ambiguity-refusal requirement

## 2026-07-14T23:22:54Z · tang-oda.6 · Bound the Codex adapter support claim
- Context: Epic 2 verified the adapter end to end against 23 local Codex CLI 0.144.4 logs on Linux and repeated the representative shape through a fully synthetic fixture. No live evidence was collected for other Codex versions or operating systems.
- Options: (a) claim generic Codex compatibility; (b) claim live verification only for Codex CLI 0.144.4 on Linux and describe the fixture provenance precisely; (c) avoid a Codex support claim.
- Decision: (b) — live-claim Codex CLI 0.144.4 on Linux, use the synthetic corpus as repeatable shape evidence, and require separate live verification before extending the version claim. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, under the approved evidence-based adapter support policy

## 2026-07-14T23:54:46Z · tang-oda.7 · Make native project hints cross one trusted resolution seam
- Context: The adapter correctly exposed native `cwd` hints and target resolution correctly consumed project keys, but a caller could previously attach an unrelated caller-supplied `ProjectIdentity` to a source. Ambient `GIT_*` variables could also redirect Git discovery away from the hinted directory.
- Options: (a) leave composition to each index/link caller; (b) validate caller-supplied identities; (c) make candidate construction resolve the source hint internally, provide one active-project discovery helper with path-safe warnings, and isolate the Git subprocess environment.
- Decision: (c) — all production candidate discovery crosses the same native-hint-to-project-identity seam, ignores ambient Git repository overrides, and refuses unavailable resolution rather than guessing. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, resolving manual gate findings before Epic 3 consumes project identity

## 2026-07-14T23:58:02Z · tang-oda.6 · Promote the reviewed Epic 2 milestone
- Context: Human review approved the renewed Epic 2 adapter milestone after project-resolution integration and environment-isolation findings were resolved with 102 passing tests on both supported Python baselines.
- Options: (a) fast-forward the reviewed milestone into `main`; (b) create a merge commit; (c) defer promotion.
- Decision: (a) — fast-forward `epic/02-codex-adapter` milestone `a30866cd03958f395e3537d41dfa1b0d8e73c966` into `main`, producing promotion SHA `a30866cd03958f395e3537d41dfa1b0d8e73c966`. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (promotion approval) and agent (verified fast-forward execution)

## 2026-07-15T00:24:25Z · tang-d6f.11 · Infer deletions only from healthy complete scans
- Context: Incremental adapter checkpoints must remove derived state when a native session is deleted, but unreadable directories, malformed records, or truncated logs can make an existing session temporarily unseen. Treating absence during a degraded scan as deletion would destroy the last-known-good capsule and FTS record.
- Options: (a) infer deletion whenever a checkpointed identity is unseen; (b) never infer native deletion; (c) emit removals only after a warning-free complete scan and retain all prior fingerprints during partial scans.
- Decision: (c) — synchronize deletions promptly when the native inventory is authoritative while making degraded scans non-destructive and retryable. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, implementing the Epic 3 indexing privacy and resilience contract

## 2026-07-15T00:31:00Z · tang-d6f.7 · Scope incremental checkpoints by project
- Context: Gate review found that one store-global adapter checkpoint lets indexing project A suppress unchanged native sessions when the user later runs Tang from project B. The approved design keeps a global derived database but requires each index operation to discover the resolved current project independently.
- Options: (a) retain one checkpoint per native store; (b) force every index operation to rescan without checkpoints; (c) key checkpoint persistence by adapter, store namespace, and resolved project while keeping the adapter cursor opaque.
- Decision: (c) — preserve incremental scans within each project without allowing one project's indexing history to hide another project's eligible sessions; discard pre-release unscoped cursors during migration so the first scoped run performs a safe full scan. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, resolving an Epic 3 close-gate integration finding

## 2026-07-15T00:34:36Z · tang-d6f.7 · Advance past attempted eligible sources
- Context: A current-project source with a valid identity and project hint but no readable visible turns prevented its adapter checkpoint from advancing, forcing every later index run to rescan and reprocess the entire native store. The adapter fingerprint already changes when native content changes.
- Options: (a) block the whole checkpoint until every eligible source indexes; (b) add a persistent retry queue and backoff schema; (c) warn and advance after a positively project-resolved attempt, retrying automatically when the native fingerprint changes.
- Decision: (c) — contain one poison record without adding premature retry infrastructure, while preserving automatic recovery on native change and continuing to block advancement when project identity itself is unresolved. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, resolving manual Epic 3 review warning 1

## 2026-07-15T00:34:36Z · tang-d6f.7 · Make degraded indexing observable by exit status
- Context: `tang index` exposed partial status in text and JSON but always exited successfully, forcing automation to parse output to distinguish a complete scan from degraded evidence.
- Options: (a) always exit 0; (b) exit 1 for partial results and 0 for complete results; (c) make every warning a fatal exit 2 error.
- Decision: (b) — preserve useful partial output while giving scripts a standard, low-cost degraded-state signal; usage and hard failures retain distinct error behavior. Serves: Technological Implementation, Design.
- By: agent, applying manual Epic 3 review warning 5 as release polish

## 2026-07-15T00:47:37Z · tang-d6f.7 · Promote the renewed Epic 3 milestone
- Context: Human review approved Epic 3 promotion after checkpoint-liveness, allocation-fairness, index-exit, and documentation remediation; milestone `9afb4b0` predated those fixes, so the renewed tested branch tip was the only valid promotion candidate.
- Options: (a) promote stale milestone `9afb4b0`; (b) fast-forward the renewed milestone; (c) create an unnecessary merge commit.
- Decision: (b) — fast-forward `epic/03-discovery-context` milestone `8b265b8814ff522e8967e4866f88a7891655d2de` into `main`, producing promotion SHA `8b265b8814ff522e8967e4866f88a7891655d2de`. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (promotion approval) and agent (renewed verification and fast-forward execution)

## 2026-07-15T00:58:41Z · tang-7lx.6 · Package one canonical skill tree as wheel data
- Context: Epic 4 gate review proved the source-tree installer but found that a clean wheel omitted `skills/tang`, making the documented installed `tang skill install codex` command fail. The repository-level skill path must also remain directly compatible with skill-only installers.
- Options: (a) defer bundled installation to the release epic; (b) duplicate the skill under the Python package; (c) keep `skills/tang` canonical and install those files into a stable wheel data path resolved by the CLI.
- Decision: (c) — ship one source of truth through setuptools data files and resolve it from the active Python environment, preserving both CLI-installed and skill-only distribution paths without content drift. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, resolving an Epic 4 close-gate clean-wheel finding

## 2026-07-15T01:08:13Z · tang-7lx.6 · Keep doctor observational before first index
- Context: Manual review found that doctor used the normal database bootstrap, so a readiness check created the default data directory and database before the user indexed anything. Existing databases still need a schema/readability check that cooperates with WAL users.
- Options: (a) document doctor as a bootstrap command; (b) report missing storage without creating it, inspect closed databases through an immutable read-only snapshot, and use SQLite's read-only WAL path when an active WAL exists; (c) stop checking database readiness.
- Decision: (b) — keep first-run diagnostics observational while retaining actionable database, schema, FTS5, and concurrent-WAL readiness signals. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, resolving manual Epic 4 review warnings 2 and 3

## 2026-07-15T01:13:13Z · tang-7lx.6 · Promote the renewed Epic 4 milestone
- Context: Human review approved Epic 4 after citation-shape, observational-doctor, and empty-adapter remediation; milestone `c9f3727` predates those fixes.
- Options: (a) promote stale milestone `c9f3727`; (b) fast-forward the renewed milestone; (c) create an unnecessary merge commit.
- Decision: (b) — fast-forward `epic/04-codex-skill` milestone `e1f6a1674f24207f076ce0ab6eb2773496654b0a` into `main`, producing promotion SHA `e1f6a1674f24207f076ce0ab6eb2773496654b0a`. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (promotion approval) and agent (verified fast-forward execution)

## 2026-07-15T01:15:32Z · tang-0dh.1 · Retain graph-referenced session tombstones
- Context: Native history can disappear after a confirmed continuation edge is recorded. Cascading edge deletion would rewrite history, while retaining the searchable capsule would falsely imply the native source remains rereadable.
- Options: (a) cascade-delete edges with sessions; (b) block native-deletion synchronization; (c) remove capsule/search data but retain the minimal session row with `native_available = 0` while any edge references it.
- Decision: (c) — preserve honest confirmed topology and stable identities without presenting unavailable native content as discoverable or rereadable. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, implementing Epic 5 graph persistence

## 2026-07-15T01:42:05Z · tang-0dh.7 · Make wide Multiverse output timeline-first
- Context: Manual gate review found that a deterministic edge list exposed the correct many-to-many graph but underused the already-computed Timelines and read more like diagnostics than the release-blocking hero map.
- Options: (a) retain the edge list at every width; (b) add a separate inferred spatial layout; (c) render confirmed root-to-leaf Timeline lanes with merge/branch annotations at wide Unicode widths while retaining the exact edge list for narrow and ASCII output.
- Decision: (c) — make the judged surface visibly communicate branching and merging without inventing layout edges or weakening accessible fallbacks. Serves: Design, Technological Implementation, Quality of Idea.
- By: agent, resolving manual Epic 5 review warnings 1 and 2

## 2026-07-15T01:42:05Z · tang-0dh.7 · Preserve tombstones but refuse new dead-session links
- Context: Minimal unavailable session rows preserve already-confirmed graph history, but accepting new continuation edges from or into those tombstones would imply that missing native evidence can still participate in a fresh handoff.
- Options: (a) allow new links because the identity remains known; (b) reject only unavailable targets; (c) reject unavailable sources and targets while retaining all previously confirmed edges.
- Decision: (c) — keep historical topology honest and make every new continuation depend on native sessions that remain available at confirmation time. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, resolving manual Epic 5 review warning 3

## 2026-07-15T01:46:21Z · tang-0dh.7 · Promote the renewed Epic 5 milestone
- Context: Human review approved Epic 5 after timeline-lane presentation, unavailable-session link refusal, safe database-parent permissions, and explicit-graph scan remediation; milestone `f695b5e` predates those fixes.
- Options: (a) promote stale milestone `f695b5e`; (b) fast-forward the renewed milestone; (c) create an unnecessary merge commit.
- Decision: (b) — push `epic/05-multiverse-map` milestone `cba690190ab428ab209acd6facd3636746d17d20` and fast-forward it into `main`, producing promotion SHA `cba690190ab428ab209acd6facd3636746d17d20`. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (promotion approval) and agent (renewed verification and fast-forward execution)

## 2026-07-15T11:27:45Z · tang-2be.12 · Freeze structure and fix release footguns only
- Context: Pre-release review identified optimization-sensitive asserts, duplicated canonical identity and RFC 3339 logic, and several broad module refactors while the readiness review made clean install, demo, README, and submission evidence the deadline-critical path.
- Options: (a) restructure the CLI, adapters, and indexer before release; (b) defer every quality finding; (c) fix bounded correctness seams now and defer structural refactors until after v0.1.0.
- Decision: (c) — replace production asserts with explicit invariant failures, centralize identity parsing and timestamp formatting, reject tombstoned context reads early, and leave CLI/adapter decomposition, static-tooling expansion, and graph scaling for post-release work. Serves: Technological Implementation, Design, Quality of Idea.
- By: agent, applying human-requested review feedback under the approved readiness priorities

## 2026-07-15T18:56:43Z · tang-2mr · Schedule evidence-backed architectural hardening after release and OpenCode work
- Context: The architecture review identified real seams with duplicate current-target orchestration, a raw continuation-write bypass, duplicated Context Pack and adapter cursor bookkeeping, and storage-detail leaks; Epic 6 is still release-critical and Epic 7 is already the approved next work.
- Options: (a) refactor immediately during release closeout; (b) leave the findings undocumented; (c) create a dependency-ordered post-Epic-7 hardening epic with compatibility gates and a manual close gate.
- Decision: (c) — schedule Epic 8 on `epic/08-architecture-hardening`, blocked by Epic 7, with focused children that preserve approved public behavior while deepening evidenced internal modules. Serves: Technological Implementation, Design, Quality of Idea.
- By: human (requested the epic) and agent (translated the reviewed findings into scoped Beads)

## 2026-07-16T10:16:55Z · tang-2be.14 · Storage authority pending approved-spec decision
- Context: External-host testing split one project between a project database and an ephemeral `/tmp` database. Tang spec §Storage currently mandates one global platform-native database, while the functional-testing direction requests the database stay in the project folder. SQLite WAL requires its sidecars beside the chosen database; XDG distinguishes durable user state from rebuildable cache; comparable local tooling also uses project-local incremental state.
- Options: (a) retain global authoritative storage and eliminate only the unsafe fallback; (b) change the approved contract so `PROJECT/.tang/tang.db` is authoritative; (c) add a hybrid global catalog/cache now.
- Decision: deferred pending explicit human selection under the request to ask before a research-backed spec change; no storage-contract implementation has started. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, following the execution contract and human-requested functional-testing process

## 2026-07-16T10:16:55Z · tang-2be.14 · Make project-local storage authoritative
- Context: The human approved the project-folder storage contract after reviewing the global-state, project-local-state, and SQLite WAL tradeoffs.
- Options: (a) retain a global authoritative database; (b) make `PROJECT/.tang/tang.db` authoritative with explicit overrides; (c) introduce a hybrid global catalog/cache before release.
- Decision: (b) — normal Tang operations share the canonical project-local database; `--database` remains explicit and `tang demo`/isolated tests remain temporary. Defer global cache or cross-project discovery to a separately reviewed backlog item. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (explicit approval) and agent (implementation plan)

## 2026-07-16T10:46:38Z · tang-2be.16 · Optimize project-local refresh, not global state
- Context: A synthetic 256-session, 33.7 MiB corpus showed unchanged refresh spending roughly half its time on redundant structured parsing after complete-content fingerprints had already established the session was unchanged; graph loading also issued one capsule-title lookup per node. Comparative research found project-local incremental caches in Ruff and mypy, global rebuildable artifact caches in uv, and Cargo's deliberate global-download/project-output split.
- Options: (a) add a global Tang catalog/cache or shared adapter checkpoints; (b) retain project-local authority and remove measured duplicate parsing plus graph title N+1 queries; (c) leave the bottlenecks for post-release work.
- Decision: (b) — retain complete SHA-256 validation, skip only a previously validated unchanged source's second structured parse, revalidate legacy checkpoints once, and batch graph titles in one bounded project query. Reject a global accelerator for v0.1 because it adds privacy, purge, move, worktree, and cross-project correctness risk without a measured release-path benefit. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, based on benchmark and source-linked comparative research; human approval remains required for any future global catalog/cache or cross-project behavior.

## 2026-07-16T11:02:00Z · tang-2be.17 · Scope index degradation to eligible project evidence
- Context: Native adapter stores can contain malformed legacy sessions from unrelated projects. Treating every store-wide warning as an active-project failure made a complete current-project refresh exit partial and obscured the result, while suppressing those warnings would hide useful safety evidence.
- Options: (a) retain partial status for every adapter warning; (b) discard foreign warnings; (c) surface only proven-foreign warnings as explicitly scoped diagnostics and preserve partial status for current, unresolved, identityless, and ambiguous warnings.
- Decision: (c) — classify warnings conservatively from a resolved foreign source record or a private resolvable foreign project hint; JSON and stderr make the distinction explicit, and duplicate identities remain project-impacting because their scope is ambiguous. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, based on RFC 4918's per-resource outcome principle and focused cross-adapter regression review.

## 2026-07-16T11:15:17Z · tang-2be.13 · Keep selection human-readable without adding a second interactive UI
- Context: Host testing showed opaque canonical IDs and absent Codex titles made browse unusable, but the approved product has one interactive workflow—the Codex skill—and the standalone CLI must remain scriptable and non-interactive.
- Options: (a) add an interactive terminal selector or short-ID aliases; (b) continue exposing canonical IDs in human output; (c) use redacted non-empty display names and deterministic five-choice pages, retaining canonical IDs only in JSON/private skill maps.
- Decision: (c) — derive a title, first visible user goal, or neutral fallback at the capsule/result seam; hide UUID-shaped handles on discovery displays; page explicit choices; and refuse stale or out-of-range numbers while JSON remains automation-compatible. Serves: Design, Technological Implementation, Potential Impact.
- By: agent, applying external-host evidence and W3C clear-label/instruction guidance; no spec change required.

## 2026-07-16T11:19:19Z · tang-2be.18 · Recover `connect` intent without a second command contract
- Context: External-host testing showed users naturally try `tang connect`, but the approved command and safety model are `tang link` with explicit target confirmation, idempotent storage, and graph follow-up.
- Options: (a) make `connect` a permanent alias; (b) leave the generic unknown-command error; (c) return an exact actionable `connect` recovery message while documenting one canonical `link` workflow.
- Decision: (c) — retain one public continuation verb and provide a direct route to `tang link --help` before any database or edge action. Serves: Design, Technological Implementation, Quality of Idea.
- By: agent, based on Python 3.11 compatibility, established CLI suggestion patterns, and the external-host finding.

## 2026-07-16T11:40:01Z · tang-2be.20 · Use stored project-local ordinal session handles
- Context: Numbered browse pages hid UUIDs but could not be passed to `context`, `link`, or `graph`; requiring JSON to recover the canonical identity made the human CLI unusable for continuation. The human required very short identifiers containing only letters and digits.
- Options: (a) accept page-local numbers that become stale when results change; (b) expose a shortened UUID/hash; (c) persist simple harness-qualified project ordinals such as `C1` and `G1` while retaining canonical identities internally.
- Decision: (c) — allocate handles transactionally in the authoritative project database, accept them case-insensitively at CLI session boundaries, show them on human browse/link/graph surfaces, migrate existing sessions, and preserve exact canonical IDs in JSON, citations, and graph storage. `purge --all` intentionally resets handles with all other derived data. Serves: Design, Technological Implementation, Potential Impact.
- By: human (handle simplicity requirements) and agent (storage/resolution design and implementation)

## 2026-07-16T12:00:07Z · tang-2be.21 · Make the isolated demo exercise production continuation policy
- Context: Release review found that the demo mis-bound health as a positional title, inserted fixture edges beneath continuation validation, and narrated recovered sources separately from the Multiverse extension.
- Options: (a) fix only the positional argument; (b) retain a privileged raw fixture importer; (c) map the real synthetic search selections into the fixture DAG and seed every confirmed edge through `ContinuationService` before extending it with short handles.
- Decision: (c) — the filmed story now recovers Grok and Codex evidence, uses those exact sessions as the graph roots, preserves fixture health with keyword construction, and demonstrates the same project, availability, identity, and cycle policy as normal links. Serves: Technological Implementation, Design, Quality of Idea.
- By: agent, applying human-requested release review feedback

## 2026-07-16T12:06:20Z · tang-2be.4 · Ship one version-coupled Codex skill installer
- Context: The approved specification carried an unreviewed optional `npx skills` path that installs only instructions, adds a third-party installer, and can drift from the required Tang CLI version.
- Options: (a) retain and promote both installers; (b) document `npx` as an unsupported alternative; (c) remove it and support only the skill bundled with the verified wheel through `tang skill install codex`.
- Decision: (c) — keep installation short, deterministic, and version-coupled to the CLI artifact judges actually test. Serves: Design, Technological Implementation, Quality of Idea.
- By: human (explicit approval to remove `npx`) and agent (documentation/spec implementation)

## 2026-07-16T12:20:32Z · tang-2be.22 · Add an original woven network to the hero map
- Context: The verified Timeline lanes were accurate but repeated complete paths; human visual review requested a git-graph-like network with actual connected lines, informed by the general branching-strand language of multiverse imagery.
- Options: (a) retain lanes only; (b) replace them with a franchise-inspired illustration; (c) add a Tang-owned deterministic layered rail map above the lanes while preserving narrow and ASCII fallbacks.
- Decision: (c) — wide Unicode output now makes merges and branches spatially immediate through left-to-right rails, junctions, unavailable-source marks, and the active handle; it copies no Marvel artwork, names, logos, palette, or proprietary styling. Serves: Design, Technological Implementation, Quality of Idea.
- By: human (requested the network direction) and agent (original terminal layout and accessibility boundaries)

## 2026-07-16T17:40:24Z · tang-09a · Start OpenCode engineering beside external release smoke
- Context: The reviewed Epic 6 implementation is promoted on private `main`, while its final clean-host smoke is being performed independently later; a developer with live OpenCode access is available to validate the next adapter.
- Options: (a) keep all OpenCode work blocked until the external smoke and Epic 6 closure; (b) start OpenCode from the unreviewed release branch; (c) begin Epic 7 from promoted `main` while keeping the external smoke release-blocking for Epic 6 and submission work.
- Decision: (c) — isolate the independent validation lane without delaying evidence-first OpenCode integration or weakening either epic's close gate. Serves: Technological Implementation, Potential Impact, Quality of Idea.
- By: human (explicit sequencing approval) and agent (dependency and branch execution)
