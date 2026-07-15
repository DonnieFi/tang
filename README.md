# Tang Multiverse

> **Keep the blade, switch the handle.**

**Continue one coding agent's work inside another, with the original sources cited.**

Bring one session or many from Grok and Codex into the Codex session you are in. Then let that session feed one future session or many, merge in other sources, and repeat as often as the work changes handles. Tang preserves the resulting many-to-many history in a terminal-native Multiverse Map.

**From Grok to Codex today; from handle to handle as support expands.**

<!--
HERO IMAGE — release blocking

Replace this comment with the real terminal Multiverse Map capture after the
canonical demo and accessibility snapshots pass. The capture must:
- be the first image in the README;
- show plain-text Grok and Codex labels, not third-party logos;
- show a branch or merge and highlight the current Codex session;
- use the forge-black / hot-steel amber / oxidized-teal Tang palette;
- come from real `tang demo` output, not a mockup.
-->

## The Multiverse Map

The graph is the product's proof, not decoration. Every edge means recovered context actually continued into another session. Several sources can merge into a target; any session can later branch into several targets. Across repeated continuations, that creates a many-to-many directed graph. Tang does not invent relationships.

```text
  A · Grok research ──┐                    ┌──▶ D · Codex API
                      ├──▶ C · Codex plan ─┤
  B · Codex review ───┘                    └──▶ E · Codex CLI ──┐
                                                               ├──▶ G · Codex hardening
  F · Grok testing ─────────────────────────────────────────────┘    ACTIVE HANDLE
```

The final terminal view highlights the active handle and remains understandable with `NO_COLOR`, narrow terminals, and ASCII-only connectors.

> **Pre-release:** Tang is being built for OpenAI Build Week. The commands and support claims marked as release targets below are not final until their verification gates pass.

## The work should outlive the tool

A good blade does not become useless because you changed the handle. Your work should not either.

Coding harnesses can usually reopen their own sessions, but the continuity stops at the product boundary. Start a difficult task in Grok, move to Codex, and the decisions, constraints, dead ends, and next action are stranded in the old handle.

Tang is the fitted continuity layer:

- **The blade** is the work itself.
- **The handles** are Codex, Grok, and future supported harnesses.
- **The tang** is the part that lets the same work seat securely in a new handle.

Tang finds the prior session, rereads the native source, redacts it, builds a compact Context Pack with citations, and helps GPT-5.6 establish an evidence-backed resume point inside Codex. It then records only the continuations you confirm.

One source into one target is recovery. Many sources feeding many later sessions become continuity. A later Codex session can merge more Grok or Codex sources, branch into several future sessions, and extend the same Multiverse without flattening its history.

## From Grok to Codex

The Build Week demonstration proves one concrete path without limiting the graph to one hop. Each action selects one source or many into one confirmed current target; repeating that action across later targets creates the many-to-many Multiverse:

1. Open the Tang skill in the current Codex project.
2. Find a prior Grok session by a phrase you remember.
3. Preview its small, redacted Discovery Capsule.
4. Select it and build a compact, source-cited Context Pack.
5. Let GPT-5.6 state the evidence-backed **Resume point** and **Next action**.
6. Confirm the continuation and reveal it in the Multiverse Map.
7. Continue C into D and E, merge another source F into E, and watch the many-to-many graph grow.

No transcript copy-and-paste. No pretending that a generic summary is provenance. No edge until the continuation is confirmed.

## Install on Linux

<!-- TODO(release): Replace <owner>, verify the public wheel URL in a clean Linux environment, and remove the pre-release warning only after tang-2be.6 passes. -->

Release target for Tang `v0.1.0`:

```bash
uv tool install https://github.com/<owner>/tang/releases/download/v0.1.0/tang_multiverse-0.1.0-py3-none-any.whl
tang skill install codex
tang doctor
```

Requirements: Linux and Python 3.11 or later. The hackathon release makes no macOS or Windows compatibility claim.

For the current local-wheel testing procedure, a plain-English walkthrough,
and early usage FAQs, see [`docs/getting-started.md`](docs/getting-started.md).

The skill-only installation path will also be available:

```bash
npx skills@latest add <owner>/tang
```

That installs the Codex skill, not the `tang` executable. Install the wheel as well before using the workflow.

## Three moves

### 1. Find the work

Tang indexes small Discovery Capsules for the current project. Search by harness, time, health signal, or the half-remembered phrase that is still stuck in your head.

### 2. Continue here

Choose one or more source sessions from Grok or Codex. Tang rereads and redacts the native sources, fairly allocates a compact Context Pack across them, and cites every recovered excerpt. GPT-5.6 uses that evidence inside the current Codex session without treating recovered transcript text as instructions.

### 3. See the timeline

Confirm the continuation. Tang records explicit, cycle-free edges. Repeated many-source operations across later target sessions form a many-to-many DAG, rendered as the Multiverse Map.

## What Tang supports

| Harness or platform | Hackathon release | Claim |
|---|---:|---|
| Codex | Release target | Read-only local session adapter and current continuation target |
| Grok | Release target | Read-only source adapter for the demonstrated Grok-to-Codex path |
| Cursor | Post-hackathon | Origin story and roadmap only; no v0.1 support claim |
| Linux | Supported target | Live-tested release platform |
| macOS | Unsupported | No compatibility or CI claim |
| Windows | Unsupported | No native compatibility claim |

Final adapter claims will distinguish representative live verification from fixture verification.

The longer-term product direction is symmetrical continuity: any supported handle should be able to receive the blade. The focused v0.1 release proves a many-to-many session graph through repeated, multi-source continuation into Codex; it does not claim that Tang can write into or resume Grok, Cursor, or another target harness yet.

## The incident that started it

Tang began after a Cursor session using Sol crashed while producing a specification. The work appeared lost, was difficult to locate, and eventually had to be recovered by another agent.

That incident supplied the question: why is valuable work trapped inside the handle that created it?

It does **not** supply a false product claim. Cursor's private history format remains too risky for the hackathon release. The demonstrated and supported story is Grok work continued inside Codex.

## Local-first, deliberately

Native harness logs remain the source of truth. Tang stores only derived continuity data needed for discovery and the graph.

- The SQLite database is local and created with user-only permissions (`0600`) on supported POSIX systems.
- Discovery Capsules contain at most 8 KiB of redacted visible text per session.
- System prompts, hidden reasoning, tool payloads, tool results, file bodies, and full transcripts are excluded.
- Selected native sources are reread and redacted when a Context Pack is created.
- Recovered content is wrapped as untrusted historical evidence, never executable instruction.
- `tang purge --all` removes Tang-derived records, including stored source paths;
  it never deletes or rewrites the native harness logs that remain the source of truth.
- `tang demo` uses a temporary data directory and must not touch native logs or the user's Tang database.

Redaction reduces accidental disclosure; it is not encryption and does not promise protection against forensic recovery.

## How it fits together

```text
  native Codex logs       native Grok data
          │                      │
          └──── read-only adapters ────┐
                                       ▼
                              redaction boundary
                                       │
                     ┌─────────────────┴─────────────────┐
                     ▼                                   ▼
             Discovery Capsules                 selected source reread
              SQLite + FTS5                              │
                     │                                   ▼
                     └──── find and select ─────▶ Context Pack
                                                         │
                                                         ▼
                                               GPT-5.6 brief in Codex
                                                         │
                                              confirmed continuation
                                                         ▼
                                                  Multiverse Map
```

Adapters own native parsing and expose two deep operations: scan for discoverable sessions, and reread a selected session. Tang's core owns project boundaries, redaction, search, context budgets, continuation rules, and presentation.

## Command line

The Codex skill is the primary interactive experience. The CLI stays scriptable and does not introduce a competing selector.

| Command | Purpose |
|---|---|
| `tang index` | Incrementally index sessions for the current project |
| `tang browse` | List indexed sessions and capability status |
| `tang search QUERY` | Search redacted Discovery Capsules; simple keywords or quoted phrases are recommended |
| `tang context SESSION...` | Produce a compact Markdown or JSON Context Pack |
| `tang link --from SESSION... --current` | Confirm links into the current Codex session |
| `tang graph [SESSION]` | Render the containing Multiverse Map |
| `tang purge --all` | Remove Tang-derived data after confirmation |
| `tang doctor` | Check installation, database, FTS5, and adapter readiness without creating absent derived storage |
| `tang skill install codex` | Install or update the bundled Codex skill without silently overwriting changes |
| `tang demo` | Run the isolated synthetic judge demonstration |

Human-readable output goes to `stdout`; diagnostics go to `stderr`. JSON output uses deterministic ordering, RFC 3339 UTC timestamps, and `schema_version: 1`.
`tang index` exits with status 1 when indexing is partial so automation can detect
degraded results without parsing its output.

## Judge path

<!-- TODO(release): Replace this section with the exact clean-wheel commands and recorded timings from tang-2be.6. -->

After installing the tagged wheel:

```bash
tang doctor
tang demo
```

The finished demo will provide a safe, synthetic Grok-to-Codex branch-and-merge corpus and complete the core recovery-to-continuation flow in under 75 seconds.

Release-candidate reviewers can run the isolated clean-wheel acceptance script
from a matching source checkout. It records the wheel hash, environment, exit
codes, privacy checks, and timings as JSON without reading native user history:

```bash
python3 scripts/functional_acceptance.py \
  ./tang_multiverse-0.1.0-py3-none-any.whl \
  --output tang-functional-evidence.json
```

## Built with Codex and GPT-5.6

Codex helped recover and interrogate the session that inspired Tang, pressure-test the product scope, turn the approved specification into a dependency-aware Beads plan, and implement the release through dated, reviewable milestones. Human gates retain control over support claims, privacy tradeoffs, scope changes, and every epic promotion.

GPT-5.6 has two visible roles:

- **Building Tang:** the majority of core implementation is developed in one recorded Codex project thread, with dated commits and a submitted `/feedback` session ID.
- **Inside Tang:** GPT-5.6 turns a deterministic, source-cited Context Pack into the concise resume point and next action a developer needs after changing harnesses. Tang keeps retrieval, redaction, citations, and graph edges deterministic.

<!-- TODO(submission): Add concrete implementation examples, the majority-core /feedback ID, and final human decisions from decision.md. -->

## Why not ordinary session resume?

| Approach | Reopens the same tool's session | Crosses harnesses | Source-cited recovered context | Confirmed continuation graph |
|---|---:|---:|---:|---:|
| Native session resume | Yes | No | Not applicable | No |
| Manual history hunting | Sometimes | By copy/paste | Manual | No |
| Transcript export | As static text | Sometimes | Varies | No |
| Tang | Yes, as evidence in a new session | **Yes** | **Yes** | **Yes** |

Tang does not launch or remote-control another harness, infer edges, or claim to resume an arbitrary closed target. Its wedge is narrower: continue prior work across a harness boundary, with evidence you can inspect.

## Roadmap

After the hackathon path is proven:

- Cursor support, gated on repeatable live recovery and failure tests
- OpenCode adapter
- opt-in cross-project discovery
- custom Context Pack budgets
- richer graph exports and themes
- broader diagnostics and purge scopes

## Contributing and license

Tang is a focused Build Week project. Contribution guidance will land with the public release; until then, the approved scope in [`docs/tangspec.md`](docs/tangspec.md) is authoritative.

Tang will be released under the MIT License with `v0.1.0`.

---

**Keep the blade, switch the handle.**
