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
