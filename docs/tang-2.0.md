# Tang 2.0

Status: implementation plan for the post-hackathon rewrite. This document does not amend [`tangspec.md`](tangspec.md). Donnie Fiander reviews and merges. Privacy and redaction rules in the spec still apply.

The July 2026 hackathon deadline has passed. This plan is Donnie's November 2026 direction: a lightweight Rust CLI for searching, labeling, summarizing, categorizing, and recalling sessions.

## Current technology

Tang 2.0 is the Rust binary in `rust/`. Tests are `cargo test --manifest-path rust/Cargo.toml`. There is no server, no web UI, and no database process.

Derived state is one SQLite file per project at `PROJECT/.tang/tang.db` (mode `0600`, WAL, busy timeout). Search is SQLite FTS5 with the Porter tokenizer over a redacted Discovery Capsule of at most 8 KiB. Readers for Codex, Grok, OpenCode, Cursor, Claude Code, Antigravity, and OpenClaw read native logs and write only that derived database. `tang demo` is in memory and does not touch a user's real Tang DB or native logs.

The commands that matter for recall are `tang index`, `tang search`, `tang context`, and `tang link`. Search is limited to the current project. Handles such as `C1` and `G1` are allocated per project, so the same handle means a different session in a different repo. `tang link` refuses a source or target from another project. Tang does not store user labels, a session category, or a summary it wrote. The v1 spec forbids persisted model-generated annotations and says Tang never writes a generated session summary.

That stack is already light. The gap is not missing infrastructure. A model looking for an answer has to be in the right project, search a short capsule, and then run a separate link flow whose handles are not stable across repos.

## Stack choice

The 2.0 CLI is one native Rust binary. Storage stays SQLite with FTS5. The crate is `rust/`. Donnie chose Rust after an earlier note in this plan said to stay on Python 3.11. The Python package has been removed.

Crates, and nothing larger:

- `rusqlite` with the bundled SQLite build, so FTS5 is in the binary and the machine does not need a system SQLite.
- `regex`, for the same ordered redaction rules the spec already requires.
- `serde_json`, to read capsule excerpts and emit recall JSON.
- `sha2`, so a project key is the same SHA-256 digest the existing CLI uses.

No Postgres, Elasticsearch, vector index, embedding pipeline, daemon, web framework, or second UI. The harness readers live in `rust/src/index_*.rs`. `tang catalog sync` copies capsules that are already in `PROJECT/.tang/tang.db`. Recall does not open native logs.

The catalog is a redacted copy of those capsules. It is not a silent fallback for the Python `tang search`, and it does not replace the per-project database. Continuation edges stay in the project database that already enforces cycles, tombstones, and same-project membership.

Rejected alternatives:

- Continuing the 2.0 catalog in Python. Donnie decided the rewrite is Rust.
- A hosted or multi-process search platform. It would add a service to install, a network or daemon to trust, and a new place private session text could land.
- Replacing `.tang/tang.db` with only the global file. That would rewrite the reviewed graph and privacy boundary in the same change as recall.
- Calling a model to summarize during sync. Output would depend on a key, a network, and a model build, and it could not be pinned by a unit test.

Summaries in this slice are deterministic extracts of the redacted title and visible excerpts, prefixed with a closed category. User labels are short tokens the operator attaches after sync. Both are stored in the catalog and indexed so a later model can filter on them without rereading native logs.

## First slice

The slice lands as a stack of Rust changes on this plan. Each layer is usable on its own. Build and test with `cargo test --manifest-path rust/Cargo.toml`.

1. This plan and the matching `decision.md` entries.
2. Global catalog. `tang catalog sync` copies the current project's redacted capsules into `~/.tang/catalog.db`. `tang recall QUERY` searches that file with FTS5, including sessions from other projects. Recall does not open native logs.
3. Labels, categories, and summaries. Sync assigns one category from a fixed word list (`bug`, `decision`, `review`, `implementation`, `goal`, `other`) and stores the extractive summary. `tang label add|remove` attaches operator labels. `tang recall` filters on `--label`, `--category`, and `--harness`.
4. Faster join. `tang join --from HANDLE --into HANDLE` resolves catalog handles, even when the shell is not in that project, and writes one explicit continuation edge. Both sessions must belong to the same project. Cross-project edges are refused. The command does not append to native transcripts.

Catalog handles are global and are not reused after a session leaves the catalog. They can differ from the project-local handle printed by `tang browse`.

`tang purge --all` removes that project's catalog rows when the catalog file already exists. It does not create a catalog, and it does not modify native logs.

## Deliberately left out

- Model-written summaries and persisted Continuation Briefs.
- Semantic or vector search.
- Continuation edges that cross projects.
- `adapter_checkpoints`, incremental index, and Python `user_version` 8.
- Changing the OpenCode export-directory hash or the OpenClaw home hash.
- A second interactive UI. The Codex skill remains the only interactive workflow; these commands are scriptable.

## Privacy

Catalog text is redacted again at write time. Recall JSON includes handles, category, labels, summary, and the canonical source id. It does not include filesystem paths. The catalog stores the project database path only so `tang join` can open that derived database. Tests and `tang demo` keep using temporary directories. Nothing in this slice reads `~/.tang` or a project's `.tang` unless the command was pointed at it.
