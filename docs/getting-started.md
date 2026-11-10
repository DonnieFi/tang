# Tang

Tang 2.0 is the Rust CLI in [`rust/`](../rust). Build it with:

```bash
cargo build --manifest-path rust/Cargo.toml --release
```

The commands, privacy rules, and the Multiverse Map are documented in the [README](../README.md).

Install the bundled skill for a harness with:

```bash
tang skill install codex --cwd "$HOME/.codex"
tang skill install claude --cwd "$HOME/.claude"
tang skill install opencode --cwd "$HOME"
```

`tang demo` prints a sample map and does not create a database or read native logs. `tang index` and `tang recall` do not write native harness logs.
