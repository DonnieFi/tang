# Grok full-parity feasibility gate (tang-sis.10)

## Gate outcome: **conditional go** for Tang-side destination edges; **no go** for
native Grok import/resume until a host integration exists.

## Read path (today)

**Pass.** `GrokAdapter` indexes Grok Build 0.2.99 local store on Linux;
capsules, search, context, and source-side links work in v0.2.9.

## Destination links (Tang graph)

**Feasible in core.** Allow `grok` in `SUPPORTED_DESTINATION_ADAPTERS` when:

- Target session is indexed, `native_available`, and same project.
- User confirms with explicit `--to <grok-handle>` (no `--current` until Grok host
  supplies native active session ID).

Cycle, self-link, and project rules unchanged.

## Native resume / import into Grok

**Blocked for v0.3 without new surface:**

- No shipped `tang skill install grok` or Grok plugin in v0.2.
- No verified Grok CLI `resume` contract equivalent to Codex/OpenCode in this
  repository's live evidence.
- **Import** = export Context Pack markdown/JSON for manual paste or future Grok
  skill — not silent native log write (`native-write-policy.md`).

## Recommended sequence

1. `tang-sis.11` — enable Grok as link destination in core + tests.
2. `tang-sis.12` — document/script `tang context … --json` → Grok handoff file
   and skill stub spec for human review.
3. Spec amendment before marketing "symmetrical Grok handle."

## Competitor note

Tools like [rses](https://github.com/yazcaleb/rses) inject handoff text into
Grok/Codex launches. Tang should keep **citations + explicit edges** as the
differentiator, not one-shot transcript copy.
