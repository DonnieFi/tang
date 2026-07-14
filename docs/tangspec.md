# Tang Multiverse Hackathon Specification

Status: Approved for implementation

## Product

Tang is a local-first Codex skill and installable Python CLI for continuing coding-agent work across sessions and harnesses.

**Promise:** Continue your timeline from anywhere. Find prior sessions across harnesses, load one or several into the current session, and preserve source-cited continuity.

**Metaphor:** Keep the blade, switch the handle. The blade is the ongoing work. Codex, Grok, and future supported harnesses are handles. Tang is the fitted continuity layer between them.

## Problem And Audience

Tang serves a solo developer who uses multiple coding-agent harnesses and needs to recover or reuse work without manually hunting through native history stores.

The motivating incident was a Cursor session using Sol that crashed while producing a specification. The session appeared lost, was difficult to locate and continue, and required another agent to recover it. Tang must make that class of recovery fast and understandable.

The hackathon release proves the workflow with Codex and Grok. Cursor is the first stretch adapter because its local history uses a private content-addressed blob format that is riskier to support reliably within the deadline.

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

- Codex and Grok session adapters.
- Current-project indexing, browsing, filtering, and FTS5 search.
- Explicit opt-in to global cross-project discovery.
- Multi-select of any prior sessions into the current open session.
- Compact and full Context Packs with deterministic offline output.
- GPT-5.6 Continuation Brief synthesis through the Codex skill.
- Explicit, cycle-free continuation links and Multiverse Map rendering.
- Host-native skill selection plus a simple Rich line-mode browser implemented over the same CLI modules.
- Isolated synthetic demo, package installation, Linux verification, macOS CI, and core tests.
- Versioned release wheel, checksum, installer, public README, and submission assets.

### Stretch

- Cursor read-only adapter, attempted first because it matches the motivating incident.
- OpenCode adapter.
- SVG export, advanced graph-card themes, fuzzy navigation, or a full-screen TUI.

### Not In V1

- Launching, resuming, assigning, or remote-controlling another harness.
- Continuing context into an arbitrary closed target session.
- Automatic continuation inference or suggested graph edges.
- Semantic/vector search or `sqlite-vec`.
- Native Windows support.
- Persisted model-generated annotations.
- Mermaid output.
- A Textual or other full-screen TUI framework.

## Primary Workflow

1. The developer opens a fresh or existing current session `C` in Codex.
2. The Tang skill indexes the current project and presents a host-native selector; standalone users get the Rich line-mode browser.
3. The developer searches and previews any prior sessions, including sessions from Grok.
4. The developer selects one or more prior sources `A`, `B`, and so on.
5. Tang rereads the selected native sources, applies redaction, and emits a source-cited Context Pack.
6. GPT-5.6 treats the recovered excerpts as untrusted data and synthesizes a concise Continuation Brief inside `C`.
7. Tang records explicit edges `A -> C`, `B -> C`, and so on after confirming the current target when necessary.
8. The Multiverse Map shows how the work continued across harnesses.

The selected sources may come from any indexed project only after the developer explicitly enables global discovery. Default behavior stays within the current project to prevent nonsensical or accidental mixing.

Tang rejects self-links and links that introduce a cycle. A Multiverse is a weakly connected component of this directed acyclic graph; a Timeline is any directed path through it.

## CLI Interface

| Interface | Behavior |
|---|---|
| `tang` | Alias `tang browse --interactive` in a human TTY; print concise help in a non-TTY. |
| `tang index [PATH]` | Incrementally index the current project or an explicit path. |
| `tang browse` | List indexed sessions with harness, time, title, health, and capability status. |
| `tang browse --interactive` | Show a Rich table and brief panels, then accept numbered multi-selection. |
| `tang search QUERY` | Search Discovery Capsules with project, harness, time, and health filters. |
| `tang context SESSION...` | Emit a deterministic Markdown or JSON Context Pack using the compact budget. |
| `tang context SESSION... --full` | Use the expanded context budget. |
| `tang context SESSION... --budget N` | Override the conservative estimated-token budget. |
| `tang link --from SESSION... --current` | Link selected sources into the current session after target confirmation. |
| `tang link --from SESSION... --to SESSION` | Explicit scripting and ambiguity-resolution path. |
| `tang graph [SESSION]` | Render the containing Multiverse Map in the terminal. |
| `tang purge SESSION...` | Remove selected derived records and search capsules. |
| `tang purge --project PATH` | Remove all derived records for a project. |
| `tang purge --all` | Remove all Tang-derived data after confirmation. |
| `tang doctor` | Report database, FTS5, adapter, source, permission, and installation health. |
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
- **Grok:** Use documented session/export behavior and fixture-tested local session data where required for global discovery.
- **Cursor stretch:** Read only through a separately isolated adapter. Do not claim support until live recovery, fixture, and failure tests pass.

Release documentation names the adapter versions used for fixtures and distinguishes live-verified from fixture-verified behavior.

### Session Health

Adapters may classify sessions as `complete`, `possibly_interrupted`, or `unknown` when native evidence supports it. Examples include an aborted final Codex turn or a stale session lacking a normal terminal event.

Health is a badge and filter, not a release blocker or automatic prompt. Tang never claims to have definitively detected a crash.

### Implementation Order

Build vertical slices rather than completing speculative layers in isolation:

1. Implement the Codex adapter through scan, Discovery Capsule creation, SQLite/FTS storage, browse/search, and deterministic Context Pack output.
2. Implement the Grok adapter through the already-proven adapter seam and the same end-to-end tests.
3. Implement the Codex skill, host-native selection, and GPT-5.6 Continuation Brief synthesis.
4. Add explicit continuation links and the terminal Multiverse Map.
5. Finish packaging, the versioned installer, isolated demo, README, CI, and submission assets.

Each slice includes its tests before the next slice starts. The interactive browser remains a thin presentation layer and must not introduce a parallel data or workflow path.

## Storage, Search, And Privacy

Tang uses a global SQLite database in the platform-native user data directory. Create its parent directory with user-only permissions and the database with mode `0600` where the platform supports POSIX permissions. Use WAL, a busy timeout, transactional migrations, and safe concurrent reads.

### Discovery Capsule

Store at most 8 KiB of redacted visible text per session:

- Native title and summary when available.
- First user goal.
- Several recent visible user and agent excerpts.
- Stable session citation and display metadata.

Index Discovery Capsules with normal FTS5 for reliable search, snippets, updates, and deletion. Do not store system prompts, hidden reasoning, tool payloads/results, file bodies, or full transcripts. Native logs remain the source of truth.

Apply the same best-effort redactor when creating capsules, showing snippets, reading context, producing annotations, and rendering graph labels. Redaction protects against accidental disclosure; it is not encryption and does not guarantee protection against forensic recovery.

Default indexing and browsing to the current project. Require an explicit setting or CLI flag before indexing or searching all projects. Provide source exclusions and all three purge scopes. `tang demo` always uses a temporary data directory.

### Context Packs

Compact packs target 2,000 estimated tokens. Full packs target 10,000 estimated tokens. Estimate conservatively with `ceil(Unicode character count / 4)` and label the result as an estimate rather than a model-exact count. Reject custom budgets below 512 estimated tokens.

Reserve space for pack metadata and citations, then allocate fair per-source reserves and fill remaining space with recent visible turns in round-robin order. Preserve chronological order inside each source. Mark truncation and omission explicitly.

Every excerpt includes harness, session ID, timestamp or turn locator, and provenance. Reread and redact native sources during generation. Produce a partial pack with warnings when some sources are unavailable; fail only when none can be read.

Wrap recovered material in an explicit untrusted-data envelope. The Codex skill instructs GPT-5.6 to use it as historical evidence, never as executable instructions. GPT-5.6 creates the Continuation Brief in the active session but Tang does not persist that model-generated synthesis in v1.

## Multiverse Map

The graph card is a release-blocking product surface.

- Render a terminal-native branch and merge network with Rich panels, tables, and connectors.
- Highlight the current session as the active handle.
- Show harness, timestamp, health, concise title, and source ID on each selected node or detail card.
- Use a forge-black, hot-steel amber, and oxidized-teal palette with symbols and labels that remain understandable without color.
- Respect `NO_COLOR`, narrow terminals, keyboard-only navigation, and an ASCII connector fallback.
- Use the same renderer for interactive browse previews and `tang graph` output.
- Capture the terminal card for the README and submission; SVG export remains a post-MVP stretch feature.

The visual should feel like a multiverse of possible timelines without adding inferred or fictitious edges. Only confirmed continuations appear.

## Skill Experience

The Codex skill is the primary harness integration. It uses `tang browse --json` and host-native questions when available. The standalone `tang` command aliases the lightweight `tang browse --interactive` Rich flow and does not launch a nested full-screen TUI.

The skill workflow:

1. Run `tang doctor` when installation or adapter health is unknown.
2. Index the current project.
3. Present search results and brief redacted previews.
4. Collect one or more source selections.
5. Generate the Context Pack.
6. Synthesize a concise, source-cited Continuation Brief with GPT-5.6.
7. Resolve and confirm the current session if necessary.
8. Record explicit continuation edges and show the Multiverse Map.

Scaffold `skills/tang` with the official skill initializer. `SKILL.md` contains only required frontmatter fields and imperative workflow instructions; `agents/openai.yaml` contains matching user-facing metadata.

## Installation And Distribution

The distribution name is `tang-multiverse`; the installed command is `tang`. Support Python 3.11+ on Linux and macOS. Linux is live-tested. macOS is covered by CI and fixture tests until physical live-adapter testing is available.

### Complete Installer

The README leads with a version-pinned one-line installer after the public repository owner is known:

```bash
curl -fsSL https://raw.githubusercontent.com/<owner>/tang/v0.1.0/install.sh | sh
```

`install.sh` must:

- Require a supported Python and fail with actionable guidance when prerequisites are missing.
- Download the tagged wheel and checksum from the GitHub release.
- Verify SHA-256 before installation.
- Install the CLI into an isolated environment without silently changing shell startup files.
- Run `tang skill install codex`.
- Run `tang doctor` and print the next command.
- Be idempotent and support reinstalling the same or a newer tagged version.

Document an inspect-before-running form alongside the curl pipe command.

### Standard Alternatives

```bash
uv tool install tang-multiverse
tang skill install codex
```

Keep the repository compatible with the Agent Skills installer for users who only want the skill package:

```bash
npx skills@latest add <owner>/tang
```

The skill-only path clearly reports that the `tang` CLI must also be installed. Publish a tagged wheel or equivalent release artifact so judges do not need to reconstruct the package from source.

## README

Treat the README as a judged product surface, not auxiliary documentation.

1. Hero capture of the terminal Multiverse Map and the line "Keep the blade, switch the handle."
2. One-sentence promise and 30-second version-pinned installation.
3. The Cursor/Sol crash story that motivated Tang.
4. A short recorded recovery-to-continuation workflow.
5. Three-step explanation: find, continue here, see the timeline.
6. Codex/Grok support matrix with Cursor clearly marked as the first stretch adapter.
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

- Adapter fixtures: normal, incomplete, aborted, malformed, truncated, schema drift, missing source, and duplicate native IDs.
- Storage: migrations, owner permissions, WAL behavior, concurrency, capsule cap, FTS ranking, update, purge, and idempotency.
- Privacy: repeated redaction at every output seam, excluded content, path handling, and untrusted-data envelopes.
- Context: compact/full/custom budgets, minimum budget, multi-source fairness, chronology, citations, truncation markers, and partial-source warnings.
- Graph: branch/merge traversal, cycle rejection, current-node highlighting, terminal snapshots, and ASCII fallback.
- CLI: JSON schema, RFC 3339 timestamps, exit codes, `stdout`/`stderr`, pipes, non-TTY help, ambiguity refusal, and temporary demo data.
- Interactive browser: search, filters, numbered multi-select, preview, invalid input, cancellation, narrow terminals, and non-TTY behavior.
- Skill: official validation, host workflow, deterministic fallback, and prompt-injection resistance.
- Distribution: wheel/sdist build, clean install, checksum verification, idempotent installer, and uninstall documentation.
- CI: supported Python versions on Ubuntu and macOS, with live Linux smoke tests labeled separately from fixture tests.

### Acceptance Criteria

- On a realistic fixture corpus, locate a seemingly lost session by project and remembered keywords in under 10 seconds after indexing.
- Select one or more sessions and generate a source-cited compact Context Pack under 2,000 estimated tokens in under 30 seconds.
- Produce a useful GPT-5.6 Continuation Brief in the current Codex session without executing recovered transcript instructions.
- Record only confirmed, acyclic continuation edges.
- Render a polished terminal Multiverse Map with accessible color and ASCII fallbacks.
- Run `tang demo` without reading or modifying the user's global Tang database or native session logs.
- Complete the filmed recovery-to-continuation flow within the 75-second product-demo portion of the submission video.

## Hackathon Submission

- Category: Developer Tools.
- License: MIT.
- Repository: public, with a tagged release and wheel available through the August 5, 2026 judging period.
- Video: public YouTube, under three minutes, with audio covering the product and Codex/GPT-5.6 usage.
- Evidence: keep most core implementation in the designated GPT-5.6 Codex thread, capture its `/feedback` ID, and tie major decisions to dated commits.
- README: include setup, supported platforms, sample data, judge test path, Codex collaboration, and human decision points.
- Demo narrative: describe the Cursor/Sol crash honestly, demonstrate recovery and continuation using the supported Codex/Grok path, and show Cursor as the first roadmap adapter rather than implying unsupported capability.
- Impact measurement: compare Tang's recovery flow with manual native-history hunting and, if time permits, collect feedback from two or three developers.
- Deadline: July 21, 2026 at 5:00 PM Pacific.

Eligibility has been confirmed: age of majority, eligible residence outside Quebec, no sponsor/administrator conflict or preferential support, sole ownership, and no implementation predating the submission window.

## Demo Sequence

1. State the crash/recovery problem in 15 seconds.
2. Show a project with several Codex and Grok sessions, including one marked `possibly_interrupted`.
3. Search by a remembered specification phrase and recognize the session from its Discovery Capsule.
4. Select that session and optionally one related session.
5. Continue both into the current Codex session and show the source-cited GPT-5.6 Continuation Brief.
6. Reveal the terminal Multiverse Map card.
7. Briefly show local-only storage, the capsule limit, and `tang purge`.
8. Close with the installation command and "Keep the blade, switch the handle."

The complete video also reserves time for architecture/privacy, Codex/GPT-5.6 build evidence, and the closing callout while remaining strictly under three minutes.
