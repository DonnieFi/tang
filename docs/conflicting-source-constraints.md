# Conflicting recovered source constraints

When a user selects multiple indexed sessions for one Context Pack, native
histories may disagree about goals, constraints, or next steps. Tang treats
every recovered excerpt as **untrusted historical evidence**. It never merges,
ranks, executes, or persists one source's instruction as the winner.

## Policy

1. **No autonomous resolution.** Tang does not choose a resume point or next
   action when sources conflict. The active host agent must name the conflict,
   keep each cited path visible, and ask the user which constraint to follow
   before acting.
2. **Preserve provenance.** Multi-source allocation keeps at least one cited
   excerpt per selected source when the token budget allows. Budget-driven
   omissions are disclosed via `omitted_turns` and pack warnings; they are not
   silent drops of a disagreeing source.
3. **Graph edges unchanged.** Conflicting evidence in a Context Pack does not
   mutate, delete, or collapse confirmed continuation edges. `tang graph`
   continues to show each predecessor independently.
4. **No persisted synthesis.** Tang does not store conflict resolutions,
   merged briefs, or model-authored reconciliations in `.tang` or native logs.

## Deterministic signals (trusted core)

When two or more sources expose a first visible user turn with different
normalized text, the Context Pack JSON includes a non-model
`constraint_signals` entry:

- `kind`: `first_user_goal_mismatch`
- `sources`: per-source `source_id`, `harness`, and `turn_locator` only

Normalization strips only known host envelope tags (for example Cursor
`<timestamp>` / `<user_query>` wrappers). It is **host-envelope hygiene**,
not semantic equivalence; other harness prefixes or literal tag-like user text
can still produce false matches or misses.

This is a **hint**, not semantic inference. Host agents must still read excerpts
and qualify uncertainty in the Continuation Brief.

Multi-source packs remain **`status: complete`** when every source read is
complete and the only pack-level warning is the deterministic conflict hint.

## Continuation Brief contract

The Codex skill requires:

- Conflicts and partial evidence in **Evidence and uncertainty**
- No single-source collapse when `constraint_signals` or conflicting excerpts exist
- A focused clarification question when the next action is not jointly supported

See `skills/tang/SKILL.md` and `tests/test_continuation_brief.py`.

## Out of scope

- Automatic conflict clustering or NLP similarity
- Writing conflict outcomes back to the index
- Cross-project constraint mixing (see `plan/research/cross-project-discovery-opt-in.md`, gitignored)
