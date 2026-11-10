//! Tang 2.0 catalog. The per-project database stays the graph authority.

#![forbid(unsafe_code)]

pub mod catalog;
pub mod cli;
pub mod error;
pub mod index_antigravity;
pub mod index_claude;
pub mod index_codex;
pub mod index_cursor;
pub mod index_grok;
pub mod index_openclaw;
pub mod index_opencode;
pub mod index_store;
pub mod join;
pub mod project;
pub mod redact;
pub mod summary;
pub mod timeutil;

pub use cli::run_with;
pub use error::{Result, TangError};
