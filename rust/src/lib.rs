//! Tang 2.0 catalog. The per-project database stays the graph authority.

#![forbid(unsafe_code)]

pub mod cards;
pub mod catalog;
pub mod cli;
pub mod context_pack;
pub mod continuity;
pub mod demo;
pub mod discovery;
pub mod doctor;
pub mod error;
pub mod graph;
pub mod index_antigravity;
pub mod index_claude;
pub mod index_codex;
pub mod index_cursor;
pub mod index_grok;
pub mod index_openclaw;
pub mod index_opencode;
pub mod index_store;
pub mod join;
pub mod multiverse;
pub mod project;
pub mod project_purge;
pub mod redact;
pub mod resume;
pub mod skill_install;
pub mod stats;
pub mod summary;
pub mod timeutil;
pub mod titles;

pub use cli::run_with;
pub use error::{Result, TangError};
