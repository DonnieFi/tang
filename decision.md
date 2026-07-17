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

## 2026-07-16T18:04:09Z · tang-09a.1 · Make live-provider evidence a permanent OpenCode support gate
- Context: The first feasibility probe globally truncated sessions before project filtering, lacked a whole-run deadline, exposed a stable full-export correlator, and could accept an expected provider found in a different session; the human clarified that Epic 7 is full product integration executed early, not a tester-specific experiment.
- Options: (a) retain the lightweight friend-host probe and qualify its limitations; (b) inspect private OpenCode storage for faster project lookup; (c) harden the supported CLI/tool contract and treat external OpenAI and xAI runs as formal acceptance evidence for the permanent adapter.
- Decision: (c) — enumerate the supported catalog before canonical project filtering, cap only exports while preserving the exact current session, enforce per-command and overall deadlines, emit only allow-listed failures, remove export hashes, and require provider plus visible user/assistant evidence from the exact current tool-context session. Private OpenCode databases remain out of scope. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (permanent-integration clarification and feedback approval) and agent (privacy/performance contract implementation)

## 2026-07-16T19:02:02Z · tang-09a.1 · Pin exact invocation evidence and qualify the OpenCode catalog
- Context: Review of the hardened probe and pinned OpenCode `1.17.20` source showed that a semantic-looking but unsupported version/platform could pass, session-wide provider unions could misattribute a mixed-provider run, arbitrary metadata labels could escape the privacy envelope, and the CLI catalog is project-scoped but limited to the latest 100 root sessions.
- Options: (a) accept the report as best-effort and rely on tester narrative; (b) parse OpenCode's private database for complete enumeration; (c) bind acceptance to the exact tool-context message, pin version/platform, use fixed metadata classifications, and expose the supported CLI boundary while requiring a bounded supported server-catalog design in the production adapter.
- Decision: (c) — live evidence now fails closed unless OpenCode `1.17.20` on Linux `x86_64` exports the exact invoking assistant message with the expected fixed provider class; poisoned metadata is never echoed, malformed time/text evidence cannot pass, cancellation terminates the probe, and latest-100-root saturation is reported as incomplete. The adapter must validate the supported directory-filtered server surface and return partial at its explicit bound rather than claiming unlimited discovery. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (requested review remediation) and agent (pinned-contract verification and implementation)

## 2026-07-16T19:21:46Z · tang-09a.1 · Filter OpenCode project identities to the active directory
- Context: The first live functional run showed that OpenCode's project identity can return root sessions from sibling clones or worktrees, making an otherwise valid canonical-directory session report fail merely because foreign-directory entries were present.
- Options: (a) reject every shared OpenCode project identity; (b) accept and export sibling-directory sessions; (c) exclude foreign-directory entries, report that filtering occurred, and retain the conservative latest-100 saturation failure because upstream truncation could still hide active-directory sessions.
- Decision: (c) — keep Tang's project isolation at the canonical directory seam while accurately representing OpenCode's broader project grouping and preserving a fail-visible incomplete boundary. Serves: Technological Implementation, Design, Potential Impact.
- By: human (live functional evidence) and agent (contract correction)

## 2026-07-16T19:29:53Z · tang-09a.1 · Keep OpenCode transcript support provider-agnostic
- Context: Live tool execution matched the exact current session and invoking assistant message but OpenCode exposed the selected model through a provider alias outside the probe's fixed OpenAI/xAI classes. The human clarified that Tang must read supported OpenCode transcripts regardless of model or provider.
- Options: (a) expand model/provider aliases and continue gating readability on them; (b) infer the model vendor from display names; (c) require exact session/message/assistant identity while treating fixed provider classes as non-gating diagnostics and retaining OpenAI/xAI runs only as representative coverage.
- Decision: (c) — remove the expected-provider argument and pass condition; do not limit the permanent adapter by provider or model. Exact invoking-message identity remains mandatory, arbitrary provider metadata remains non-echoing, and separate OpenAI/xAI live runs document breadth without defining eligibility. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (explicit provider-agnostic requirement) and agent (contract implementation)

## 2026-07-16T19:50:42Z · tang-09a.3 · Bind OpenCode targets to exact fresh host evidence
- Context: OpenCode supplies an exact current session ID and project paths through custom-tool context, but those values alone cannot prove that Tang's indexed record still represents the native session; selecting the newest record would violate the ambiguity rule.
- Options: (a) reuse Codex's unique-or-recent candidate behavior; (b) accept an exact session ID without checking index freshness; (c) validate directory, worktree, and adapter-observed project identity together, require the observed fingerprint to match the indexed record, and leave the exact match confirmation-required until the user confirms it.
- Decision: (c) — place raw host metadata and fresh adapter evidence behind one path-safe target interface; refuse malformed, foreign, absent, ambiguous, selected-source, unavailable, and stale cases with fixed codes, and never infer an OpenCode destination from recency, provider, or model. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, applying the approved Epic 7 acceptance criteria and live host-contract evidence

## 2026-07-16T20:06:51Z · tang-09a.2 · Enumerate OpenCode through a bounded authenticated server
- Context: OpenCode's CLI session list is root-only and capped by service defaults, while pinned `1.17.20` exposes a supported directory-filtered `/session` endpoint that includes child sessions. Reading the private OpenCode database would violate the approved adapter seam.
- Options: (a) support only the latest root sessions; (b) parse the private database for complete discovery; (c) briefly start the documented localhost server, query the exact directory without the roots filter at a `500 + 1` bound, and continue to use the proven export command for selected reads.
- Decision: (c) — use a random per-run Basic Auth credential, bypass proxies, reject redirects, stop the server after the bounded query, and report saturation as partial. Updated-millisecond fingerprints make unchanged scans cheap and retry poison exports only after native change; deterministic visible turns use created milliseconds plus message ID. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, based on pinned OpenCode `v1.17.20` source (`4473fc3c`) and privacy-safe live adapter evidence

## 2026-07-16T20:15:58Z · tang-09a.4 · Make OpenCode first-class without degrading absent installs
- Context: Registering OpenCode unconditionally would make every existing Codex/Grok index partial on hosts where the post-release harness is not installed, while omitting it from doctor would hide whether the new integration is usable.
- Options: (a) require all three harnesses for every command; (b) require an OpenCode-only mode flag; (c) use one stable adapter factory that adds OpenCode to index/context when discovered or explicitly configured, while doctor always instantiates its readiness check.
- Decision: (c) — preserve default Codex/Grok behavior on absent installs; accept `--opencode-executable` and `TANG_OPENCODE_EXECUTABLE`; expose `--harness opencode`; and have doctor report distinct missing, empty, ready, or degraded state without creating Tang storage. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, applying Epic 7's permanent-integration scope and backward-compatibility acceptance criteria

## 2026-07-16T20:27:22Z · tang-09a.5 · Keep continuation policy harness-based
- Context: The pre-Epic 7 continuation service rejected every non-Codex destination even after OpenCode could prove an exact, fresh, explicitly confirmed active target.
- Options: (a) retain Codex-only targets; (b) infer support from any indexed adapter; (c) declare the fixed destination policy `{codex, opencode}` and keep sources adapter-neutral.
- Decision: (c) — authorization remains at the ContinuationService seam; OpenCode target proof remains in its host-context resolver; unsupported targets refuse before mutation. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, under the human-approved Epic 7 scope

## 2026-07-16T22:30:00Z · tang-09a.6 · Install one project-local OpenCode workflow
- Context: OpenCode can discover Agent Skills and `/` commands from a project, but exact destination proof requires private host context that must not be copied into prompts or exposed as a native session ID.
- Options: (a) require users to copy native IDs into the generic CLI; (b) create a separate interactive OpenCode selector; (c) install one Tang Agent Skill with a thin `/tang` loader and private custom-tool bridge that converts exact host context into a safe project-local handle.
- Decision: (c) — keep one workflow, reuse Tang's deterministic JSON CLI and explicit confirmation policy, preserve unrelated OpenCode configuration, and package all version-coupled assets with the wheel. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, applying the human-approved permanent OpenCode integration scope

## 2026-07-16T23:14:36Z · tang-09a.9 · Partition OpenCode checkpoints by physical worktree
- Context: Linked Git worktrees intentionally share one Tang project identity and database, while OpenCode's supported catalog query is scoped to one exact physical directory; sharing one adapter namespace let a refresh in one worktree report another worktree's sessions as removed.
- Options: (a) broaden every OpenCode scan across sibling worktrees; (b) include the physical directory in the public session namespace, changing stable identities and duplicating existing rows; (c) retain the native-store namespace and version the opaque adapter checkpoint so fingerprints and removals are partitioned by a one-way canonical-directory digest.
- Decision: (c) — keep discovery exact-directory and private, preserve stable session identities plus the shared project graph/database, and discard legacy unscoped cursors for one safe removal-free full scan. The change remains behind the adapter interface and requires no storage migration. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, applying the approved worktree-isolation acceptance criteria

## 2026-07-17T00:32:33Z · tang-09a.7 · Capture non-trivial OpenCode exports through a private transient
- Context: A live OpenCode `1.17.20` recovery run showed that non-trivial `opencode export` output is truncated nondeterministically when stdout is a pipe even though the command exits zero; regular-file stdout produced complete valid JSON for the same authorized session. The human explicitly preferred local usability over an unnecessarily strict memory-only boundary.
- Options: (a) keep treating affected sessions as unreadable; (b) persist raw exports in the project; (c) capture stdout in a bounded, user-only anonymous temporary file, parse it locally, close it immediately, and continue persisting only redacted Tang data.
- Decision: (c) — work around the pinned upstream pipe-flush bug without writing raw transcripts into the project or Tang database; cap transient output at 8 MiB and preserve fail-closed validation. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (explicit local-privacy tradeoff approval) and agent (live diagnosis and bounded implementation)

## 2026-07-17T00:51:02Z · tang-09a.7 · Refresh exact active-target metadata at the host bridge
- Context: Live graph and link preparation repeatedly returned `stale-index` because the active OpenCode session's documented updated fingerprint advances during the recovery conversation after the initial index. The host bridge already performs an exact-ID, exact-project fresh native scan before target resolution.
- Options: (a) require users to race a manual re-index before every target operation; (b) ignore fingerprint drift; (c) update only the already-indexed exact target's derived identity metadata from the fresh host observation, then retain the resolver's strict equality and explicit-confirmation checks.
- Decision: (c) — eliminate the unavoidable active-session race without creating unindexed targets, rereading transcript content, guessing identity, or weakening link approval. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, based on repeated human live-test evidence and the approved exact-host target policy

## 2026-07-17T01:08:31Z · tang-09a.8 · Promote reviewed Epic 7 OpenCode integration
- Context: The dated Epic 7 milestone passed the manual gate with pinned live OpenCode source/destination evidence, dual-Python and focused suites, clean-wheel installation, green CI, and an explicit human promotion approval.
- Options: (a) retain the reviewed milestone only on the epic branch; (b) fast-forward the reviewed branch into main; (c) create an unnecessary merge commit over a linear branch.
- Decision: (b) — push milestone `4e039ff0fb0708010edcfa42e34bcf4faa6a23a7` and fast-forward `main` from `7a26cb084faf5f40465615ffc0112104fccb71e6` to the same reviewed SHA. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (explicit promotion approval) and agent (gate execution)

## 2026-07-17T01:28:12Z · tang-a9z · Version the completed OpenCode product as v0.2.0
- Context: The private v0.1.0 milestone predates the completed, live-verified OpenCode source and destination integration; publishing another 0.1.0 wheel would make materially different products indistinguishable.
- Options: (a) retain 0.1.0; (b) use a patch version; (c) assign v0.2.0 and present the earlier v0.1.0 behavior only as history.
- Decision: (c) — OpenCode is a backward-compatible new capability, so a semantic-versioning minor bump accurately distinguishes its package, wheel, installation contract, and README story. The supporting samurai asset is a clean derivative with all product names and third-party marks removed. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (version and README direction) and agent (release-contract implementation)

## 2026-07-17T21:30:21Z · tang-xp5 · Bound OpenCode compatibility by contract generation
- Context: Kiritsuke ran Tang v0.2.0 with OpenCode 1.17.18, but the production adapter rejected it solely because Epic 7 had used an exact 1.17.20 evidence pin; the adapter already validates catalog/export shapes and safety boundaries at runtime.
- Options: (a) retain exact 1.17.20; (b) remove version checks; (c) accept stable versions `>=1.17.18,<2.0.0` while retaining strict runtime schema, identity, project, size, and timeout validation.
- Decision: (c) — a bounded floor unblocks compatible installs without admitting known-older contracts or an unknown future major; the privacy-safe evidence probe remains exactly pinned to 1.17.20 so its historical claim stays reproducible. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: human (relax compatibility) and agent (bounded fail-closed policy)

## 2026-07-17T21:30:21Z · tang-gwb · Make OpenCode directory authoritative for target projects
- Context: Kiritsuke returned `host-project-mismatch` for a valid current session because Tang required OpenCode's current project `directory` and its broader `worktree` root to independently produce the same Tang project key; that is false for legitimate nested non-Git projects.
- Options: (a) remove project validation; (b) keep exact equality; (c) require the freshly observed session to match authoritative `directory`, while accepting `worktree` only as an ancestor or a path sharing the same Git project identity.
- Decision: (c) — preserve exact native ID and project isolation while matching OpenCode's documented distinction between a session directory and worktree root; foreign siblings and clones remain rejected. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, based on human Kiritsuke evidence and the installed OpenCode 1.17.20 ToolContext contract

## 2026-07-17T21:36:52Z · tang-gxy · Persist redacted session titles independently of capsules
- Context: Newly joined OpenCode targets could be valid indexed graph nodes without a Discovery Capsule, but Tang stored titles only inside capsules, so the Multiverse displayed `(untitled)` even when the native catalog supplied a useful title.
- Options: (a) keep the untitled fallback; (b) create synthetic title-only capsules; (c) add a bounded title column to session metadata, redact it at persistence, preserve it across temporarily titleless refreshes, and use it only as the graph fallback when no capsule title exists.
- Decision: (c) — keep capsules truthful while giving every adapter-neutral graph node its available display metadata; apply the shared 256-character persistence redaction and retain graph-seam redaction as defense in depth. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, based on human Kiritsuke UX evidence and Tang's approved privacy seams

## 2026-07-17T21:41:09Z · tang-bp0 · Ship Kiritsuke refinements as v0.2.1
- Context: Kiritsuke already has v0.2.0 installed, so rebuilding the OpenCode compatibility, project-resolution, and title fixes under the same version would make installation and troubleshooting ambiguous.
- Options: (a) overwrite v0.2.0; (b) assign v0.2.1; (c) defer packaging until a larger release.
- Decision: (b) — issue the backward-compatible fixes as v0.2.1, update current package and installation contracts while retaining historical v0.2.0 evidence, and verify the exact wheel through clean functional acceptance. Serves: Technological Implementation, Design, Potential Impact, Quality of Idea.
- By: agent, applying semantic patch-versioning to the human-approved refinements

## 2026-07-17T21:54:35Z · tang-412 · Resolve Codex targets from the project index
- Context: `tang link --current` and implicit `tang graph` reparsed and rehashed the complete native Codex store even though the recovery workflow already indexes the project and may supply an exact host native ID.
- Options: (a) retain full rescans; (b) pass a checkpoint that would omit unchanged candidate records; (c) resolve only available Codex candidates from the authoritative project index and require a fresh index when the host ID is absent there.
- Decision: (c) — remove native rescans from the reveal path without guessing or weakening exact-ID and ambiguity rules; return a specific `index-required` refusal when host evidence is not indexed. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, based on verified review evidence and the approved index-first skill workflow

## 2026-07-17T21:54:35Z · tang-412 · Bound graph work and scope deletion uncertainty
- Context: recursive cycle/timeline traversal could crash on long DAGs or expand exponentially, while any unrelated adapter warning prevented native deletion detection indefinitely.
- Options: (a) retain conservative but unbounded behavior; (b) weaken deletion safety globally; (c) use iterative cycle detection, cap deterministic rendered timelines at 256 with an explicit omission label, protect warning-identified sources, and suppress removals only when store enumeration itself is incomplete.
- Decision: (c) — bound judge-facing graph work while preserving every confirmed edge and keep last-known-good records only where a warning could actually conceal that identity or subtree. Serves: Technological Implementation, Design, Potential Impact.
- By: agent, based on adversarial long-chain, dense-DAG, malformed-source, and symlink tests

## 2026-07-17T21:54:35Z · tang-412 · Distinguish the reviewed patch as v0.2.2
- Context: a v0.2.1 wheel had already been built before the additional correctness and performance review fixes, so rebuilding different bytes under v0.2.1 would make host testing ambiguous.
- Options: (a) replace v0.2.1 in place; (b) issue v0.2.2; (c) defer the fixes.
- Decision: (b) — version the cumulative pre-submission refinement patch as v0.2.2 while retaining v0.2.1 as historical evidence. Serves: Technological Implementation, Quality of Idea.
- By: agent, applying immutable artifact and semantic patch-versioning discipline

## 2026-07-17T22:03:38Z · tang-369 · Make human discovery scan-friendly
- Context: functional CLI testing found the pipe-delimited human browse output difficult to scan and select from, while the first Rich table draft became too tall when full snippets wrapped.
- Options: (a) retain delimiter lines; (b) render full snippets in a tall table; (c) show a responsive table with selection number, simple handle, bounded session name, compact capability labels, harness, seconds-level UTC, and health while retaining full snippets in JSON.
- Decision: (c) — keep five-result paging compact and readable at wide and narrow widths without altering the deterministic JSON/skill contract. Serves: Design, Potential Impact, Technological Implementation.
- By: human (requested a CLI table) and agent (responsive compact presentation)
