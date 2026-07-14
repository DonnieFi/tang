# AGENTS.md — Tang execution contract

Concise operating rules for coding agents on Tang. Read fully before acting; re-read the **Epic close gate** section whenever an epic completes.

## North star

This is a hackathon (deadline **2026-07-21 17:00 PT**). Judged on four equal criteria — **Technological Implementation, Design, Potential Impact, Quality of Idea**. Every material decision must serve one coherent Grok-to-Codex path over broad-but-incomplete coverage. When material options compete, pick the one that most improves those four criteria on the demo path, and log why in `decision.md`.

## Source of truth (in order)

1. `docs/tangspec.md` — the approved spec. Do not contradict or change it without explicit human approval.
2. Beads (`bd`) — the execution plan (epics + child beads). Gitignored; local state only.
3. This file — how to execute.

If any two conflict, the higher one wins. Never edit the spec to fit code.

## Structure

- 6 epics: `tang-xqa`, `tang-oda`, `tang-d6f`, `tang-7lx`, `tang-0dh`, `tang-2be`. Each blocks the next — do them in order.
- Each epic has a `branch:` in its metadata (e.g. `epic/01-grok-feasibility`) and a final "Verify, commit, and promote" child that is the **close gate**.
- Child beads have their own acceptance criteria and `blocks` dependencies.

## Per-epic loop

1. **Open branch.** From clean `main`, create the epic's branch from its `branch:` metadata (`bd show <epic>`). Claim the epic: `bd update <epic> --claim`.
2. **Work child beads.** Repeat autonomously until only the close-gate child remains, except when the **Stuck protocol** requires human input:
   - `bd ready` → pick the top unblocked child. Review it and record its **Execution profile**, then `bd update <child> --claim`.
   - Implement to the child's acceptance criteria. Write tests for the feature (spec §Verification).
   - Run the full focused test suite; it must pass.
   - **Code review before closing** (see checklist). Fix findings, re-test.
   - Log material decisions: append to `decision.md` when a choice affects scope, architecture, privacy, support claims, release evidence, or a later agent's work. Routine implementation choices do not need entries.
   - `bd close <child>` with a note of what was done + test result: `bd close <child> --reason "<summary; tests: <cmd> pass>"`.
   - Pick the next child. Do **not** pause for approval between children.
3. **Only the close-gate child remains → run its review stage.** Re-read this file's **Epic close gate**, claim the close-gate child, verify the epic, record its evidence, and create the branch milestone commit. Then stop for human review.

## Execution profile (every bead, before claim)

Record the profile in Beads metadata or notes so a later session can reproduce the choice:

- `model`: normally `gpt-5.6-sol` for Tang's high-value implementation and judged surfaces.
- `effort`: use the lowest adequate level—`medium` for bounded implementation, `high` for multi-step logic or edge cases, `xhigh` for difficult architecture/privacy/release reasoning, and `max` only for the hardest indivisible problem.
- `mode`: `single` by default; use `ultra` only when the bead contains meaningful independent workstreams that can be reviewed and integrated safely.
- `rationale`: one sentence tied to ambiguity, risk, parallelism, and acceptance criteria—not prestige.

Do not equate Ultra with quality. It is an orchestration choice and costs more because subagents repeat context and tool work. A narrow bead with difficult reasoning usually needs higher single-agent effort, not Ultra. During code review, check whether the chosen profile was adequate and record a change only when evidence warrants it.

## Epic close gate (requires manual review)

Run only the review stage of the epic's "Verify, commit, and promote" child, then **wait for manual human review — do not merge, close the gate, close the epic, or start the next epic on your own.** On the epic branch:

- Record: completed Bead IDs, decisions (link `decision.md`), test commands + results, and the Codex session/thread ID.
- Create a dated milestone commit on the epic branch and ensure the working tree is clean.
- Present the branch for review and **halt**.

The gate bead stays `in_progress` while awaiting review. Its remaining promotion and closure criteria are completed only after human approval. **Never** run epic-level steps through consensus or autonomously past this halt. Epic transitions are human-gated.

## On human "OK" for the next epic

1. Merge the reviewed epic branch into `main` (fast-forward/merge as the gate specifies); record the branch milestone SHA and resulting `main` SHA in `decision.md` and the gate evidence.
2. Close the gate and epic only after their acceptance criteria are satisfied.
3. Push `main` and the epic branch to the remote when a remote exists and the gate/spec requires it.
4. Create the next epic's branch from updated `main` and resume the per-epic loop.

Push when and where the gate/spec requires; otherwise commit locally per milestone. Never force-push; never push to `main` without a reviewed merge.

## Code review checklist (every child, before close)

- Meets the child's acceptance criteria and does not violate the spec.
- Tests exist for the feature and the full focused suite passes.
- No secrets, no third-party logos, redaction applied at persist/display seams (spec §Privacy).
- Deterministic output, RFC 3339 UTC, `schema_version: 1` where JSON is emitted.
- Scope is minimal — no features beyond the bead.
- The Bead records a justified Sol effort/mode profile; Ultra, Max, or `xhigh` use is proportional to the work.

Prefer an independent review context when practical and permitted; record material findings and the verdict in `decision.md`.

## Stuck protocol (child beads only)

When blocked on a child bead:

1. Re-read the relevant spec section and bead acceptance criteria; record concrete evidence from the code, tests, or environment.
2. When available and permitted, ask one fresh reviewer a narrow question using that same evidence.
3. If the answer would change scope, architecture, privacy posture, support claims, or an epic commitment—or remains uncertain—stop and record the blocker in the bead and `decision.md` for human input.

This escalation applies to **child beads only — never to epics**. Epic decisions are always human-gated (see close gate).

## Decision log — `decision.md`

Append **material** decisions to `decision.md`, newest last. Do not log routine edits, obvious acceptance-criteria implementation, or transient debugging. One entry per decision:

```
## <RFC 3339 UTC timestamp> · <bead id or project> · <short title>
- Context: <what forced a choice>
- Options: <considered>
- Decision: <chosen> — serves: <which of the 4 judging criteria>
- By: <human / agent / reviewer; name the decision authority>
```

## Beads quick reference

```
bd ready                         # next unblocked work
bd show <id>                     # details, acceptance, branch metadata
bd update <id> --claim           # claim (in_progress, assigned to you)
bd update <id> --append-notes "<evidence>"  # progress notes
bd close <id> --reason "<...>"   # close with summary + test result
```

## Hard rules

- Do the differentiating Grok-to-Codex path first (spec §Implementation Order); each slice ships with tests before the next.
- One interactive workflow only: the Codex skill. No second UI.
- Never touch the user's real Tang DB or native logs from `tang demo`.
- Never advance an epic, merge to `main`, or skip review without explicit human OK.
