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
    let mut rendered = render_project_map(
        &connection,
        "demo",
        &MapOptions {
            width,
            ascii_only,
            anchor: None,
            current_handle: Some("G".to_string()),
        },
    )
    .expect("demo map");
    rendered.push_str("Demo complete; temporary data will now be removed.\n");
    rendered
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

/// Render the demo text as a self-contained SVG. This keeps the checked-in
/// README capture reproducible without a Python or Rich dependency.
pub fn render_svg(text: &str) -> String {
    let lines = text
        .lines()
        .filter(|line| line.trim() != "TANG MULTIVERSE MAP")
        .collect::<Vec<_>>();
    let columns = lines
        .iter()
        .map(|line| line.chars().count())
        .max()
        .unwrap_or(80);
    let width = (columns as f64 * 9.6 + 48.0).max(640.0);
    let height = (lines.len() as f64 * 22.0 + 96.0).max(200.0);
    let mut svg = String::new();
    svg.push_str(&format!(
        r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0} {height:.0}" role="img" aria-labelledby="tang-demo-title">"##
    ));
    svg.push_str(r##"<title id="tang-demo-title">Tang Multiverse Map — isolated demo</title>"##);
    svg.push_str(r##"<rect width="100%" height="100%" fill="#171717"/>"##);
    svg.push_str(r##"<rect x="1.5" y="1.5" width="99%" height="97%" fill="none" stroke="#ff9d3d" stroke-width="3"/>"##);
    svg.push_str(r##"<text x="24" y="38" fill="#ff9d3d" font-family="'Fira Code','DejaVu Sans Mono',monospace" font-size="18" font-weight="bold">TANG MULTIVERSE MAP</text>"##);
    for (index, line) in lines.iter().enumerate() {
        let y = 70.0 + index as f64 * 22.0;
        let escaped = escape_xml(line);
        let color = line_color(line);
        svg.push_str(&format!(
            r##"<text x="24" y="{y:.1}" fill="{color}" xml:space="preserve" font-family="'Fira Code','DejaVu Sans Mono',monospace" font-size="16">{escaped}</text>"##
        ));
    }
    svg.push_str("</svg>\n");
    svg
}

fn line_color(line: &str) -> &'static str {
    if line.contains("ACTIVE") || line.contains('★') {
        "#ff9d3d"
    } else if line.contains('×') || line.contains("unavailable") {
        "#cc555a"
    } else if line.starts_with("MULTIVERSE")
        || line.starts_with("TIMELINE")
        || line.starts_with("SESSION")
        || line.starts_with("Demo complete")
    {
        "#ff9d3d"
    } else {
        "#c5c8c6"
    }
}

fn escape_xml(text: &str) -> String {
    text.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}
