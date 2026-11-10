# AGENTS.md — Tang execution contract

Concise operating rules for coding agents on Tang. The CLI is the Rust crate in `rust/`.

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

These stay as implemented until a human changes them:

- OpenCode namespace is the SHA-256 of the export directory.
- OpenClaw namespace is the SHA-256 of the home.
- The writer does not create `adapter_checkpoints` and does not set Python `user_version` 8.
- The writer does create `capsules_fts` and `session_overrides`.
