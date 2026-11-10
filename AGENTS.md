# AGENTS.md — Tang execution contract

Concise operating rules for coding agents on Tang. The CLI is the Rust crate in `rust/`.

## Current implementation (2026-11-10)

The Python CLI, pytest suite, and Python release scripts are being replaced by the Rust binary in `rust/`. The release surface is a **100% port** of the Python CLI: index, browse, cards, search, catalog sync/recall, labels, context, join/link, title, graph, demo, resume, doctor, continuity, skill install, stats, and purge. Build and test with `cargo test --manifest-path rust/Cargo.toml`.

Incremental indexing is part of the port. `adapter_checkpoints` stores the schema-4 fingerprint cursor; unchanged sources are skipped, invalid sources retain the last-known-good row, and missing sources are deleted or tombstoned. The Rust writer creates `capsules_fts`, `session_overrides`, and `adapter_checkpoints`, and sets `user_version` 8. OpenCode identity is `sha256(executable + XDG data home)` and OpenClaw identity is `sha256(home:agent_id)`, matching the Python identities.

The Python-era epic, Beads, and pytest workflow is retired; use the Rust build and test commands below.

## Source of truth

1. `docs/tangspec.md` — approved behavior and privacy. Do not rewrite the v1 privacy rules to fit code.
2. This file — how to execute.
3. `decision.md` — material decisions, newest last.

If two conflict, the higher one wins.

## Build and test

```bash
cargo fmt --manifest-path rust/Cargo.toml --check
cargo clippy --manifest-path rust/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path rust/Cargo.toml
```

Linux is the tested platform. Do not claim macOS or Windows support.

## Product boundary

- One binary, `tang`. Commands live in `rust/src/cli.rs`.
- Per-project database: `PROJECT/.tang/tang.db`. The global catalog `~/.tang/catalog.db` is created only by `tang catalog sync`.
- `tang recall` and `tang search` read derived databases. They do not open native logs.
- `tang context` may reread one selected regular native file and must redact it. Symlinked native sources are not read.
- Joins stay inside one project.
- `tang demo` is in memory only. Never point a command at a user's real Tang database or native logs.
- Indexers do not write native harness logs or continuation edges.

## Changes

- Work on a feature branch. Do not merge to `main` without an explicit human request.
- Do not force-push `main`.
- Append a `decision.md` entry when a choice changes scope, architecture, privacy, support claims, or a later agent's work.
- Tests use temporary directories outside this git checkout so project resolution does not write this repo's `.tang/tang.db`.

## Open decisions

- The Python CLI removal is tracked by the stacked removal PR. Until it merges, both trees may exist, but only `rust/` is the supported implementation.
- OpenCode identity is `sha256(executable + XDG data home)` and OpenClaw identity is `sha256(home:agent_id)`, matching the Python namespaces.
- The writer creates `adapter_checkpoints`, `capsules_fts`, and `session_overrides`, and sets `user_version` 8.
