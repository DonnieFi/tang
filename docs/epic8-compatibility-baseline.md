# CLI compatibility checks

These Rust tests guard the command surface. Run them with `cargo test --manifest-path rust/Cargo.toml`.

| Seam | Tests |
| --- | --- |
| CLI commands | `rust/tests/surface.rs`, `rust/tests/workflow.rs` |
| Link and join | `rust/tests/workflow.rs` |
| Context pack | `rust/tests/context_pack.rs` |
| Index | `rust/tests/index.rs`, `rust/tests/grok_index.rs`, `rust/tests/opencode_index.rs`, `rust/tests/cursor_index.rs`, `rust/tests/claude_index.rs`, `rust/tests/antigravity_index.rs`, `rust/tests/openclaw_index.rs` |
| Map | `rust/tests/multiverse.rs` |
| Resume, doctor, skill, purge | `rust/tests/operator.rs` |
| Search and titles | `rust/tests/discovery.rs` |
| Catalog and recall | `rust/tests/catalog.rs` |
