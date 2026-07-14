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
