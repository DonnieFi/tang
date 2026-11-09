//! Tang 2.0 catalog. The per-project database stays the graph authority.

#![forbid(unsafe_code)]

pub mod catalog;
pub mod cli;
pub mod error;
pub mod join;
pub mod project;
pub mod redact;
pub mod summary;
pub mod timeutil;

pub use cli::run_with;
pub use error::{Result, TangError};
