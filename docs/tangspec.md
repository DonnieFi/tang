# Tang Multiverse — OpenAI Build Week Specification

Status: Approved for implementation

## Product

Tang is a local-first Codex skill and installable Python CLI for continuing coding-agent work across sessions and harnesses.

**Promise:** Continue one coding agent's work inside another, with the original sources cited. The hackathon demonstration makes this concrete: continue a Grok session inside Codex.

**Metaphor:** Keep the blade, switch the handle. The blade is the ongoing work. Codex, Grok, and future supported harnesses are handles. Tang is the fitted continuity layer between them.

## Problem And Audience

Tang serves a solo developer who uses multiple coding-agent harnesses and needs to recover or reuse work without manually hunting through native history stores.

The motivating incident was a Cursor session using Sol that crashed while producing a specification. The session appeared lost, was difficult to locate and continue, and required another agent to recover it. That incident explains Tang's origin, but it is not the opening claim or demonstrated support path for the hackathon release.

The hackathon release proves one complete Grok-to-Codex workflow. Cursor remains a post-release adapter because its private content-addressed history format is too risky to promise without repeatable recovery from real data.

## Domain Language

- **Harness:** A coding-agent environment such as Codex, Grok, Cursor, or OpenCode.
- **Session:** One native conversation in a harness.
- **Continuation:** A directed relationship showing that selected prior sessions supplied context to the current session. Avoid the term handoff because the work does not stop.
- **Timeline:** One directed path through connected sessions.
- **Multiverse:** The complete branching and merging directed graph containing related timelines.
- **Discovery Capsule:** A brief, redacted, searchable representation used only to find and recognize a session.
- **Context Pack:** A budgeted, source-cited artifact assembled from selected sessions.
- **Continuation Brief:** The concise synthesis GPT-5.6 produces from a Context Pack inside the current session.

## Release Scope

### Release Blocking

- Reliable Codex and Grok read-only session adapters, with support claims distinguishing live verification from fixtures.
- Current-project indexing, browsing, and FTS5 search.
- Selection of one or more prior sessions into the current open Codex session.
- One deterministic, source-cited compact Context Pack.
- One GPT-5.6 Continuation Brief whose headline identifies the resume point and evidence-backed next action.
- Explicit, cycle-free continuation links and a polished terminal Multiverse Map.
- The Codex skill as the primary selection and continuation experience; the standalone CLI remains non-interactive and scriptable.
- An isolated synthetic demo, a tagged installable wheel, Linux verification, focused demo-path tests, a public README, and submission assets.

### Stretch

- Explicit opt-in to global cross-project discovery.
- Expanded or custom-budget Context Packs.
- A richer interactive standalone browser.
- Additional purge scopes and broader diagnostics.
- Cursor read-only adapter only after repeatable recovery from real Cursor data plus fixture and failure tests.
- OpenCode adapter.
- SVG export, advanced graph-card themes, fuzzy navigation, or a full-screen TUI.

### Not In V1

- Launching, resuming, assigning, or remote-controlling another harness.
- Continuing context into an arbitrary closed target session.
- Automatic continuation inference or suggested graph edges.
- Semantic/vector search or `sqlite-vec`.
- macOS support or CI claims.
- Native Windows support.
- Persisted model-generated annotations.
- Mermaid output.
- A Textual or other full-screen TUI framework.

## Primary Workflow

1. The developer opens a fresh or existing current session `C` in Codex.
2. The Tang skill indexes the current project and presents a host-native selector.
3. The developer searches and previews any prior sessions, including sessions from Grok.
4. The developer selects one or more prior sources `A`, `B`, and so on.
5. Tang rereads the selected native sources, applies redaction, and emits a source-cited Context Pack.
6. GPT-5.6 treats the recovered excerpts as untrusted data and synthesizes a concise Continuation Brief inside `C`, led by an evidence-backed resume point and next action.
7. Tang records explicit edges `A -> C`, `B -> C`, and so on after confirming the current target when necessary.
8. The Multiverse Map shows how the work continued across harnesses.

The hackathon release only discovers and selects sources belonging to the current project. Cross-project discovery is deferred to prevent nonsensical or accidental mixing and to protect the primary demo path.

Tang rejects self-links and links that introduce a cycle. A Multiverse is a weakly connected component of this directed acyclic graph; a Timeline is any directed path through it.

## CLI Interface

| Interface | Behavior |
|---|---|
| `tang` | Print concise help and the primary recovery commands. |
| `tang index` | Incrementally index the current project. |
| `tang browse` | List indexed sessions with harness, time, title, health, and capability status. |
| `tang search QUERY` | Search Discovery Capsules with project, harness, time, and health filters. |
| `tang context SESSION...` | Emit a deterministic Markdown or JSON Context Pack using the compact budget. |
| `tang link --from SESSION... --current` | Link selected sources into the current session after target confirmation. |
| `tang link --from SESSION... --to SESSION` | Explicit scripting and ambiguity-resolution path. |
| `tang graph [SESSION]` | Render the containing Multiverse Map in the terminal. |
| `tang purge --all` | Remove all Tang-derived data after confirmation. |
| `tang doctor` | Run a minimal installation, database, FTS5, and adapter readiness check. |
| `tang demo` | Launch the isolated branch-and-continuation demonstration without touching user data. |
| `tang skill install codex` | Install the bundled skill into the active Codex skill directory. |

Human-readable primary output goes to `stdout`; diagnostics and warnings go to `stderr`. JSON documents contain `schema_version: 1`, use RFC 3339 UTC timestamps, and preserve deterministic ordering. Noninteractive commands never guess an ambiguous current target.

## Architecture

### Adapter Seam

Keep adapters deep and limited to two core operations:

```python
scan(checkpoint) -> ScanBatch(records, next_checkpoint, warnings)
read(session_ref, selection) -> TurnBatch(turns, warnings)
```

Adapters own native parsing, opaque source locators, source fingerprints, and incremental checkpoints. Core modules own project resolution, current-session ranking, redaction, storage, search, context allocation, graph rules, and presentation.

Session identities use `adapter:source-namespace:native-id` so separate profiles and stores cannot collide. Git worktrees sharing a common Git directory are one project. Separate clones are separate projects in v1. Non-Git projects use their resolved local path.

Adapters return partial results with warnings for malformed or truncated data. A partial scan retains the last known-good record rather than replacing it with corrupt state.

### Supported Adapters

- **Codex:** Read local JSONL session logs, visible user/agent turns, timestamps, project metadata, and terminal event signals.
- **Grok:** Read documented local session or export data. The release claim requires an end-to-end read from representative real data and a fixture derived from the verified shape.
- **Cursor stretch:** Read only through a separately isolated adapter. Do not claim support until live recovery, fixture, and failure tests pass.

Release documentation names the adapter versions used for fixtures and distinguishes live-verified from fixture-verified behavior.

### Session Health

Adapters may classify sessions as `complete`, `possibly_interrupted`, or `unknown` when native evidence supports it. Examples include an aborted final Codex turn or a stale session lacking a normal terminal event.

Health is a badge and filter, not a release blocker or automatic prompt. Tang never claims to have definitively detected a crash.

### Implementation Order

Build the differentiating path first:

1. Time-box a Grok feasibility gate: locate representative real data, recover stable identity and visible turns, generate a cited Context Pack, and repeat the read through a fixture. Adjust the supported source path or demo narrative immediately if this fails.
2. Implement the Codex adapter and current-session resolution through the same adapter seam.
3. Add current-project Discovery Capsules, SQLite/FTS storage, browse/search, and the deterministic compact Context Pack.
4. Implement the Codex skill, host-native selection, and the GPT-5.6 Continuation Brief.
5. Add explicit continuation links and build the terminal Multiverse Map against deterministic demo fixtures early enough to polish it as the hero surface.
6. Finish the isolated demo, tagged wheel, README, focused Linux CI, and submission assets.

Each slice includes focused tests before the next slice starts. Do not create a second interactive workflow outside the Codex skill during the hackathon release.

## Storage, Search, And Privacy

Tang uses one authoritative SQLite database per canonical project at `PROJECT/.tang/tang.db`. Git worktrees that share a Git common directory share the database at that canonical repository root; separate clones and non-Git directories receive separate databases. Create the `.tang` parent with user-only permissions when absent and the database with mode `0600` where the platform supports POSIX permissions. Use WAL, a busy timeout, transactional migrations, and safe concurrent reads. Normal commands never silently fall back to a user-global or temporary database. `--database` is an explicit diagnostic/test override; `tang demo` always uses temporary storage.

### Discovery Capsule

Store at most 8 KiB of redacted visible text per session:

- Native title and summary when available.
- First user goal.
- Several recent visible user and agent excerpts.
- Stable session citation and display metadata.

Index Discovery Capsules with normal FTS5 for reliable search, snippets, updates, and deletion. Do not store system prompts, hidden reasoning, tool payloads/results, file bodies, or full transcripts. Native logs remain the source of truth.

Apply the same best-effort redactor when creating capsules, showing snippets, reading context, producing annotations, and rendering graph labels. Redaction protects against accidental disclosure; it is not encryption and does not guarantee protection against forensic recovery.

Index and browse only the current project in the hackathon release. Provide `tang purge --all` for a clear deletion path for that project's derived database. `tang demo` always uses a temporary data directory.

### Context Packs

Compact packs target 2,000 estimated tokens. Estimate conservatively with `ceil(Unicode character count / 4)` and label the result as an estimate rather than a model-exact count.

Reserve space for pack metadata and citations, then allocate fair per-source reserves and fill remaining space with recent visible turns in round-robin order. Preserve chronological order inside each source. Mark truncation and omission explicitly.

Every excerpt includes harness, session ID, timestamp or turn locator, and provenance. Reread and redact native sources during generation. Produce a partial pack with warnings when some sources are unavailable; fail only when none can be read.

Wrap recovered material in an explicit untrusted-data envelope. The Codex skill instructs GPT-5.6 to use it as historical evidence, never as executable instructions. GPT-5.6 creates the Continuation Brief in the active session but Tang does not persist that model-generated synthesis in v1. The brief begins with a source-cited **Resume point** and **Next action**. It must qualify uncertainty rather than inventing intent that the recovered evidence does not support.

## Multiverse Map

The graph card is a release-blocking product surface.

- Render a terminal-native branch and merge network with Rich panels, tables, and connectors.
- Highlight the current session as the active handle.
- Show harness, timestamp, health, concise title, and source ID on each selected node or detail card.
- Use a forge-black, hot-steel amber, and oxidized-teal palette with symbols and labels that remain understandable without color.
- Respect `NO_COLOR`, narrow terminals, and an ASCII connector fallback.
- Use the same renderer for Codex skill previews and `tang graph` output.
- Capture the terminal card for the README and submission; SVG export remains a post-MVP stretch feature.

The visual should feel like a multiverse of possible timelines without adding inferred or fictitious edges. Only confirmed continuations appear.

## Skill Experience

The Codex skill is the primary harness integration. It uses `tang browse --json` and host-native questions when available. Standalone commands provide scriptable line and JSON output; an interactive Rich selector is not part of the hackathon release.

The skill workflow:

1. Run the minimal `tang doctor` check when installation or adapter readiness is unknown.
2. Index the current project.
3. Present search results and brief redacted previews.
4. Collect one or more source selections.
5. Generate the Context Pack.
6. Synthesize a concise, source-cited Continuation Brief with GPT-5.6.
7. Resolve and confirm the current session if necessary.
8. Record explicit continuation edges and show the Multiverse Map.

Scaffold `skills/tang` with the official skill initializer. `SKILL.md` contains only required frontmatter fields and imperative workflow instructions; `agents/openai.yaml` contains matching user-facing metadata.

## Installation And Distribution

The distribution name is `tang-multiverse`; the installed command is `tang`. The hackathon release supports Linux only and requires Python 3.11 or later. Linux is live-tested. macOS and Windows are unsupported and receive no compatibility or CI claim for this release.

### Judge Installation

Publish a tagged wheel so judges can install Tang without rebuilding it from source. The README leads with a version-pinned command after the public repository owner is known:

```bash
uv tool install https://github.com/<owner>/tang/releases/download/v0.1.0/tang_multiverse-0.1.0-py3-none-any.whl
tang skill install codex
```

The release does not include a custom shell installer. `uv` supplies the isolated environment; Tang supplies the explicit skill installation and a minimal `tang doctor` readiness check.

### Standard Alternatives

If the package is also published to PyPI, document `uv tool install tang-multiverse==0.1.0` as a convenience rather than making PyPI publication part of the critical path.

Keep the repository compatible with the Agent Skills installer for users who only want the skill package:

```bash
npx skills@latest add <owner>/tang
```

The skill-only path clearly reports that the `tang` CLI must also be installed. Publish a tagged wheel or equivalent release artifact so judges do not need to reconstruct the package from source.

## README

Treat the README as a judged product surface, not auxiliary documentation.

1. Hero capture of the terminal Multiverse Map, the line "Keep the blade, switch the handle," and the literal promise "Continue one coding agent's work inside another, with the original sources cited."
2. The concrete Grok-to-Codex demonstration claim and 30-second version-pinned Linux installation.
3. The Cursor/Sol crash as a clearly separated origin story, without implying Cursor support.
4. A short recorded recovery-to-continuation workflow.
5. Three-step explanation: find, continue here, see the timeline.
6. Codex/Grok support matrix with Linux as the only supported platform and Cursor marked post-hackathon.
7. Discovery Capsule, local data lifecycle, redaction limits, and purge instructions.
8. Architecture diagram and concise CLI reference.
9. Reproducible `tang demo` and judge-testing instructions.
10. How Codex and GPT-5.6 accelerated the project, including key human decisions.
11. Honest comparison with adjacent session-history and continuity tools.
12. Roadmap, contributing guidance, release link, and MIT license.

Do not use third-party logos in the demo or README without permission. Plain-text harness names and Tang's own visual language are sufficient.

## Repository And Tracking

1. Initialize the existing empty `.git` directory with `git init --initial-branch=main` without deleting it.
2. Ignore `/plan/`, `/.agents/`, `/.codex/`, `/.beads/`, `/.tang/`, virtual environments, Python caches, build output, coverage, local demo output, and OS metadata.
3. Track this approved specification at `docs/tangspec.md`; `/plan/` remains private scratch material.
4. Initialize Beads with `bd init --non-interactive --skip-agents`; treat it as local execution state rather than public project history.
5. Track `README.md`, `CONTEXT.md`, concise ADRs, `LICENSE`, package code, tests, fixtures, and submission assets.
6. Create dated milestone commits linking decisions, Beads work, tests, and Codex sessions so post-July 13 work is auditable.

## Verification

### Automated Tests

- Adapters: representative Codex and Grok reads, malformed or truncated input, schema drift, missing sources, and stable identities.
- Storage and search: migrations, owner permissions, capsule cap, FTS discovery, update, purge-all, and idempotent indexing.
- Privacy: redaction at persisted and displayed seams, excluded content, path handling, and the untrusted-data envelope.
- Context: compact budget, multi-source fairness, chronology, citations, truncation markers, and partial-source warnings.
- Graph: branch/merge traversal, cycle rejection, current-node highlighting, terminal snapshots, and ASCII fallback.
- CLI and demo: JSON schema, exit behavior, ambiguity refusal, current-project boundaries, and proof that temporary demo data cannot touch native logs or the user's normal project Tang database.
- Skill: official validation, host workflow, evidence-backed Continuation Brief shape, and prompt-injection resistance.
- Distribution: tagged wheel build and clean installation on Linux without rebuilding from source.
- CI: one focused Ubuntu workflow covering the supported demo path. There is no macOS job or compatibility claim.

### Acceptance Criteria

- On a realistic fixture corpus, locate a seemingly lost session by project and remembered keywords in under 10 seconds after indexing.
- Select one or more sessions and generate a source-cited compact Context Pack under 2,000 estimated tokens in under 30 seconds.
- Produce a useful, source-cited GPT-5.6 Continuation Brief with a defensible resume point and next action, without executing recovered transcript instructions or inventing unsupported intent.
- Record only confirmed, acyclic continuation edges.
- Render a polished terminal Multiverse Map with accessible color and ASCII fallbacks.
- Run `tang demo` without reading or modifying the user's normal project Tang database or native session logs.
- Complete the filmed recovery-to-continuation flow within the 75-second product-demo portion of the submission video.

## Hackathon Submission

- Category: Developer Tools.
- License: MIT.
- Repository: public, with a tagged release and wheel available through the August 5, 2026 judging period.
- Video: public YouTube, under three minutes, with audio covering the product and Codex/GPT-5.6 usage.
- Evidence: keep most core implementation in the designated GPT-5.6 Codex thread, capture its `/feedback` ID, and tie major decisions to dated commits.
- README: include setup, supported platforms, sample data, judge test path, Codex collaboration, and human decision points.
- Demo narrative: open on the cross-harness gap and demonstrate a Grok session continuing inside Codex. Mention the Cursor/Sol crash later as the origin story, without implying Cursor support.
- Impact measurement: compare Tang's recovery flow with manual native-history hunting and, if time permits, collect feedback from two or three developers.
- Deadline: July 21, 2026 at 5:00 PM Pacific.

Eligibility has been confirmed: age of majority, eligible residence outside Quebec, no sponsor/administrator conflict or preferential support, sole ownership, and no implementation predating the submission window.

### Official Judging Priorities

The official rules weight four criteria equally:

- **Technological Implementation:** skillful Codex use and a working, non-trivial implementation.
- **Design:** a complete, coherent, runnable product experience rather than only a technical proof of concept.
- **Potential Impact:** a credible solution to a specific real problem for a real audience, supported by what the demonstration proves.
- **Quality of the Idea:** creativity, novelty, and differentiation from existing concepts.

The video and README must explain how Codex and GPT-5.6 contributed, but model usage is not a separate fifth scoring category. The product strategy therefore prioritizes one coherent cross-harness path over broad but incomplete feature coverage. Source: `https://openai.devpost.com/rules`.

## Demo Sequence

1. State the cross-harness gap: coding agents can resume their own sessions, but they cannot continue each other's work.
2. Show a project with several Codex and Grok sessions and identify the Grok work that needs to continue in Codex.
3. Search by a remembered specification phrase and recognize the session from its Discovery Capsule.
4. Select that session and optionally one related session.
5. Continue the selected work into the current Codex session and show the GPT-5.6 **Resume point**, **Next action**, and source citations.
6. Reveal the terminal Multiverse Map card.
7. Briefly show local-only storage, demo isolation, and `tang purge --all`.
8. Close with the installation command and "Keep the blade, switch the handle."

The complete video also reserves time for architecture/privacy, Codex/GPT-5.6 build evidence, and the closing callout while remaining strictly under three minutes.
