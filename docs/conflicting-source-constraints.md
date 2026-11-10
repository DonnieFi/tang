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

## What the pack does

The Rust Context Pack rereads each selected regular file, drops host envelope
wrappers and Antigravity tool prose, and redacts the remaining text. It does
not emit `constraint_signals` and does not decide which source wins. Host
agents still read the cited excerpts and qualify a conflict in the
Continuation Brief.

A missing or symlinked source keeps that session's stored capsule. The pack
does not print the locator.

## Continuation Brief contract

The Codex skill requires:

- Conflicts and partial evidence in **Evidence and uncertainty**
- No single-source collapse when `constraint_signals` or conflicting excerpts exist
- A focused clarification question when the next action is not jointly supported

See `skills/tang/SKILL.md` and `rust/tests/context_pack.rs`.

## Out of scope

- Automatic conflict clustering or NLP similarity
- Writing conflict outcomes back to the index
- Cross-project constraint mixing (see `plan/research/cross-project-discovery-opt-in.md`, gitignored)
