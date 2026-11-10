use rusqlite::{params, Connection};
use serde_json::json;
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};
use tang::demo::render_demo;
use tang::multiverse::{render_project_map, render_project_map_json, MapOptions};

struct Scratch(PathBuf);

impl Scratch {
    fn new() -> Self {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let path =
            std::env::temp_dir().join(format!("tang-multiverse-{}-{nanos}", std::process::id()));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn open_db(scratch: &Scratch) -> Connection {
    let connection = Connection::open(scratch.0.join("map.db")).unwrap();
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
        .unwrap();
    connection
}

#[allow(clippy::too_many_arguments)]
fn insert_session(
    connection: &Connection,
    project: &str,
    source_id: &str,
    handle: &str,
    harness: &str,
    title: &str,
    updated_at: &str,
    available: i64,
) {
    connection
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, session_handle, title,
                updated_at, health, native_available
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'complete', ?7)",
            params![source_id, project, harness, handle, title, updated_at, available],
        )
        .unwrap();
}

fn insert_edge(
    connection: &Connection,
    project: &str,
    source_id: &str,
    target_id: &str,
    confirmed_at: &str,
) {
    connection
        .execute(
            "INSERT INTO continuation_edges(source_id, target_id, project_key, confirmed_at)
             VALUES (?1, ?2, ?3, ?4)",
            params![source_id, target_id, project, confirmed_at],
        )
        .unwrap();
}

fn seed_story(connection: &Connection) {
    let nodes = [
        (
            "grok:story:a",
            "A",
            "grok",
            "Grok research",
            "2026-07-14T20:00:00Z",
            1,
        ),
        (
            "codex:story:b",
            "B",
            "codex",
            "Codex review",
            "2026-07-14T20:05:00Z",
            1,
        ),
        (
            "codex:story:c",
            "C",
            "codex",
            "Codex plan",
            "2026-07-14T20:10:00Z",
            1,
        ),
        (
            "codex:story:d",
            "D",
            "codex",
            "Codex API",
            "2026-07-14T20:15:00Z",
            1,
        ),
        (
            "codex:story:e",
            "E",
            "codex",
            "Codex CLI",
            "2026-07-14T20:20:00Z",
            1,
        ),
        (
            "grok:story:f",
            "F",
            "grok",
            "Grok testing",
            "2026-07-14T20:25:00Z",
            1,
        ),
        (
            "codex:story:g",
            "G",
            "codex",
            "Codex hardening",
            "2026-07-14T20:30:00Z",
            1,
        ),
        (
            "grok:story:u",
            "U",
            "grok",
            "Unavailable source",
            "2026-07-14T20:35:00Z",
            0,
        ),
    ];
    for (source_id, handle, harness, title, updated_at, available) in nodes {
        insert_session(
            connection, "proj", source_id, handle, harness, title, updated_at, available,
        );
    }
    let edges = [
        ("codex:story:b", "codex:story:c", "2026-07-14T20:11:00Z"),
        ("grok:story:a", "codex:story:c", "2026-07-14T20:11:00Z"),
        ("codex:story:c", "codex:story:d", "2026-07-14T20:16:00Z"),
        ("codex:story:c", "codex:story:e", "2026-07-14T20:21:00Z"),
        ("codex:story:e", "codex:story:g", "2026-07-14T20:31:00Z"),
        ("grok:story:f", "codex:story:g", "2026-07-14T20:31:00Z"),
        ("grok:story:u", "codex:story:g", "2026-07-14T20:32:00Z"),
    ];
    for (source_id, target_id, confirmed_at) in edges {
        insert_edge(connection, "proj", source_id, target_id, confirmed_at);
    }
    insert_session(
        connection,
        "other",
        "codex:foreign:z",
        "foreign-session",
        "codex",
        "Outside the project",
        "2026-07-14T20:00:00Z",
        1,
    );
}

fn map_options(
    width: usize,
    ascii_only: bool,
    anchor: Option<&str>,
    current: Option<&str>,
) -> MapOptions {
    MapOptions {
        width,
        ascii_only,
        anchor: anchor.map(str::to_string),
        current_handle: current.map(str::to_string),
    }
}

#[test]
fn merge_and_branch_layout_includes_lanes() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    seed_story(&connection);
    let rendered = render_project_map(
        &connection,
        "proj",
        &map_options(100, false, None, Some("G")),
    )
    .unwrap();
    assert!(rendered.contains("MERGE"), "{rendered}");
    assert!(rendered.contains("BRANCH"), "{rendered}");
    assert!(rendered.contains("TIMELINE LANES"), "{rendered}");
    assert!(rendered.contains("LANE 01"), "{rendered}");
    assert!(rendered.contains("LANE 02"), "{rendered}");
    assert!(
        rendered.contains('▶') || rendered.contains('├') || rendered.contains('│'),
        "{rendered}"
    );
    assert!(!rendered.contains("foreign-session"), "{rendered}");
}

#[test]
fn unavailable_source_is_visible() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    seed_story(&connection);
    let rendered = render_project_map(
        &connection,
        "proj",
        &map_options(100, true, None, Some("G")),
    )
    .unwrap();
    assert!(rendered.contains("unavailable"), "{rendered}");
    assert!(rendered.contains("source unavailable"), "{rendered}");
    let document = render_project_map_json(
        &connection,
        "proj",
        &map_options(100, true, None, Some("G")),
    )
    .unwrap();
    let value: serde_json::Value = serde_json::from_str(&document).unwrap();
    let unavailable = value["sessions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|session| session["handle"] == "U")
        .unwrap();
    assert_eq!(unavailable["native_available"], false);
    assert_eq!(unavailable["current"], false);
    let active = value["sessions"]
        .as_array()
        .unwrap()
        .iter()
        .find(|session| session["handle"] == "G")
        .unwrap();
    assert_eq!(active["current"], true);
}

#[test]
fn anchor_filters_to_one_component() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    insert_session(
        &connection,
        "proj",
        "codex:left:root",
        "left-root",
        "codex",
        "Left root",
        "2026-07-14T20:00:00Z",
        1,
    );
    insert_session(
        &connection,
        "proj",
        "codex:left:tip",
        "left-tip",
        "codex",
        "Left tip",
        "2026-07-14T20:05:00Z",
        1,
    );
    insert_edge(
        &connection,
        "proj",
        "codex:left:root",
        "codex:left:tip",
        "2026-07-14T20:06:00Z",
    );
    insert_session(
        &connection,
        "proj",
        "grok:right:root",
        "right-root",
        "grok",
        "Right root",
        "2026-07-14T20:00:00Z",
        1,
    );
    insert_session(
        &connection,
        "proj",
        "grok:right:tip",
        "right-tip",
        "grok",
        "Right tip",
        "2026-07-14T20:05:00Z",
        1,
    );
    insert_edge(
        &connection,
        "proj",
        "grok:right:root",
        "grok:right:tip",
        "2026-07-14T20:06:00Z",
    );

    let rendered = render_project_map(
        &connection,
        "proj",
        &map_options(80, true, Some("left-root"), None),
    )
    .unwrap();
    assert!(rendered.contains("left-root"), "{rendered}");
    assert!(rendered.contains("left-tip"), "{rendered}");
    assert!(rendered.contains("CONTINUE"), "{rendered}");
    assert!(!rendered.contains("right-root"), "{rendered}");
    assert!(!rendered.contains("right-tip"), "{rendered}");
    assert!(rendered.contains("1 component"), "{rendered}");

    let by_source = render_project_map_json(
        &connection,
        "proj",
        &map_options(80, true, Some("codex:left:root"), None),
    )
    .unwrap();
    let value: serde_json::Value = serde_json::from_str(&by_source).unwrap();
    assert_eq!(value["component_count"], 1);
    assert_eq!(value["sessions"].as_array().unwrap().len(), 2);
    assert_eq!(value["timelines"], json!([["left-root", "left-tip"]]));
}

#[test]
fn missing_anchor_is_not_in_project() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    insert_session(
        &connection,
        "proj",
        "codex:one",
        "C1",
        "codex",
        "Only session",
        "2026-07-14T20:00:00Z",
        1,
    );
    let options = map_options(80, true, Some("missing-handle"), None);
    let text = render_project_map(&connection, "proj", &options).unwrap_err();
    assert_eq!(text.code, "not-in-project");
    let json = render_project_map_json(&connection, "proj", &options).unwrap_err();
    assert_eq!(json.code, "not-in-project");

    let empty_scratch = Scratch::new();
    let empty = open_db(&empty_scratch);
    let missing =
        render_project_map(&empty, "proj", &map_options(80, false, Some("C1"), None)).unwrap_err();
    assert_eq!(missing.code, "not-in-project");
}

#[test]
fn empty_project_is_explicit() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    let rendered =
        render_project_map(&connection, "proj", &map_options(100, false, None, None)).unwrap();
    assert_eq!(rendered, "TANG MULTIVERSE MAP\n\nNo indexed sessions.\n");
    let document =
        render_project_map_json(&connection, "proj", &map_options(100, true, None, None)).unwrap();
    assert_eq!(
        document,
        "{\"component_count\":0,\"edges\":[],\"schema_version\":1,\"sessions\":[],\"timelines\":[],\"timelines_truncated\":false}"
    );
}

#[test]
fn story_json_is_deterministic() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    seed_story(&connection);
    let options = map_options(100, false, None, Some("G"));
    let first = render_project_map_json(&connection, "proj", &options).unwrap();
    let second = render_project_map_json(&connection, "proj", &options).unwrap();
    assert_eq!(first, second);
    assert!(first.starts_with("{\"component_count\":1,"));
    let value: serde_json::Value = serde_json::from_str(&first).unwrap();
    assert_eq!(value["schema_version"], 1);
    assert_eq!(value["sessions"].as_array().unwrap().len(), 8);
    assert_eq!(value["edges"].as_array().unwrap().len(), 7);
    assert_eq!(value["timelines_truncated"], false);
    assert_eq!(
        value["timelines"],
        json!([
            ["B", "C", "D"],
            ["B", "C", "E", "G"],
            ["A", "C", "D"],
            ["A", "C", "E", "G"],
            ["F", "G"],
            ["U", "G"]
        ])
    );
    assert_eq!(value["sessions"][0]["handle"], "A");
    assert_eq!(value["sessions"][0]["updated_at"], "2026-07-14T20:00:00Z");
    assert_eq!(value["edges"][0]["source_id"], "codex:story:b");
    assert_eq!(value["edges"][0]["target_id"], "codex:story:c");
}

#[test]
fn extra_lanes_say_more_were_omitted() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    insert_session(
        &connection,
        "proj",
        "codex:root",
        "root",
        "codex",
        "Root",
        "2026-07-14T20:00:00Z",
        1,
    );
    for index in 0..9 {
        let source_id = format!("codex:leaf:{index}");
        let handle = format!("L{index}");
        insert_session(
            &connection,
            "proj",
            &source_id,
            &handle,
            "codex",
            "Leaf",
            &format!("2026-07-14T20:{index:02}:00Z"),
            1,
        );
        insert_edge(
            &connection,
            "proj",
            "codex:root",
            &source_id,
            "2026-07-14T21:00:00Z",
        );
    }
    let rendered =
        render_project_map(&connection, "proj", &map_options(90, true, None, None)).unwrap();
    assert!(rendered.contains("more were omitted"), "{rendered}");
    assert!(rendered.contains("BRANCH"), "{rendered}");
    let lanes = rendered
        .lines()
        .filter(|line| line.starts_with("LANE "))
        .count();
    assert_eq!(lanes, 8);
    let document =
        render_project_map_json(&connection, "proj", &map_options(90, true, None, None)).unwrap();
    let value: serde_json::Value = serde_json::from_str(&document).unwrap();
    assert_eq!(value["timelines"].as_array().unwrap().len(), 8);
    assert_eq!(value["timelines_truncated"], true);
}

#[test]
fn demo_marks_the_active_hardening_handle() {
    let rendered = render_demo(100, true);
    assert!(rendered.contains("ACTIVE G"), "{rendered}");
    assert!(rendered.contains("Codex hardening"), "{rendered}");
    assert!(rendered.contains("Grok research"), "{rendered}");
    assert!(rendered.contains("MERGE"), "{rendered}");
    assert!(rendered.contains("BRANCH"), "{rendered}");
    assert!(rendered.is_ascii(), "{rendered}");
}

#[test]
fn ascii_rails_use_arrow_and_plus() {
    let scratch = Scratch::new();
    let connection = open_db(&scratch);
    seed_story(&connection);
    let rendered = render_project_map(
        &connection,
        "proj",
        &map_options(100, true, None, Some("G")),
    )
    .unwrap();
    assert!(rendered.contains("-->"), "{rendered}");
    assert!(rendered.contains('+'), "{rendered}");
    assert!(!rendered.contains('▶'), "{rendered}");
    assert!(!rendered.contains('─'), "{rendered}");
    assert!(!rendered.contains('→'), "{rendered}");
    assert!(rendered.is_ascii(), "{rendered}");

    let narrow = render_project_map(
        &connection,
        "proj",
        &map_options(60, false, None, Some("G")),
    )
    .unwrap();
    assert!(narrow.contains("-->"), "{narrow}");
    assert!(narrow.contains('+'), "{narrow}");
    assert!(!narrow.contains('▶'), "{narrow}");
}
