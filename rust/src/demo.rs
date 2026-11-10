//! Isolated Multiverse Map demo.
//!
//! The story graph is built in an in-memory database and drawn by the same
//! renderer as a project map. This does not open `~/.tang`, the repo `.tang`
//! database, or native harness logs.

use crate::multiverse::{render_project_map, MapOptions};
use rusqlite::{params, Connection};

/// Draw the README story: research and review merge into a plan, the plan
/// branches, and testing merges into the active hardening session.
pub fn render_demo(width: usize, ascii_only: bool) -> String {
    let connection = Connection::open_in_memory().expect("in-memory demo database");
    connection
        .execute_batch(
            "CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                adapter TEXT NOT NULL,
                session_handle TEXT,
                title TEXT,
                updated_at TEXT NOT NULL,
                health TEXT NOT NULL,
                native_available INTEGER NOT NULL
            );
            CREATE TABLE continuation_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                project_key TEXT NOT NULL,
                confirmed_at TEXT NOT NULL
            );",
        )
        .expect("demo schema");
    seed(&connection);
    render_project_map(
        &connection,
        "demo",
        &MapOptions {
            width,
            ascii_only,
            anchor: None,
            current_handle: Some("G".to_string()),
        },
    )
    .expect("demo map")
        + "Demo complete; temporary data will now be removed.\n"
}

fn seed(connection: &Connection) {
    let nodes = [
        (
            "grok:demo:a",
            "A",
            "grok",
            "Grok research",
            "2026-07-14T20:00:00Z",
            1,
        ),
        (
            "codex:demo:b",
            "B",
            "codex",
            "Codex review",
            "2026-07-14T20:05:00Z",
            1,
        ),
        (
            "codex:demo:c",
            "C",
            "codex",
            "Codex plan",
            "2026-07-14T20:10:00Z",
            1,
        ),
        (
            "codex:demo:d",
            "D",
            "codex",
            "Codex API",
            "2026-07-14T20:15:00Z",
            1,
        ),
        (
            "codex:demo:e",
            "E",
            "codex",
            "Codex CLI",
            "2026-07-14T20:20:00Z",
            1,
        ),
        (
            "grok:demo:f",
            "F",
            "grok",
            "Grok testing",
            "2026-07-14T20:25:00Z",
            1,
        ),
        (
            "codex:demo:g",
            "G",
            "codex",
            "Codex hardening",
            "2026-07-14T20:30:00Z",
            1,
        ),
        (
            "grok:demo:u",
            "U",
            "grok",
            "Unavailable source",
            "2026-07-14T20:35:00Z",
            0,
        ),
    ];
    for (source_id, handle, harness, title, updated_at, available) in nodes {
        connection
            .execute(
                "INSERT INTO sessions(
                    source_id, project_key, adapter, session_handle, title,
                    updated_at, health, native_available
                 ) VALUES (?1, 'demo', ?2, ?3, ?4, ?5, 'complete', ?6)",
                params![source_id, harness, handle, title, updated_at, available],
            )
            .expect("demo session");
    }
    let edges = [
        ("grok:demo:a", "codex:demo:c", "2026-07-14T20:11:00Z"),
        ("codex:demo:b", "codex:demo:c", "2026-07-14T20:11:00Z"),
        ("codex:demo:c", "codex:demo:d", "2026-07-14T20:16:00Z"),
        ("codex:demo:c", "codex:demo:e", "2026-07-14T20:21:00Z"),
        ("codex:demo:e", "codex:demo:g", "2026-07-14T20:31:00Z"),
        ("grok:demo:f", "codex:demo:g", "2026-07-14T20:31:00Z"),
        ("grok:demo:u", "codex:demo:g", "2026-07-14T20:32:00Z"),
    ];
    for (source_id, target_id, confirmed_at) in edges {
        connection
            .execute(
                "INSERT INTO continuation_edges(source_id, target_id, project_key, confirmed_at)
                 VALUES (?1, ?2, 'demo', ?3)",
                params![source_id, target_id, confirmed_at],
            )
            .expect("demo edge");
    }
}
