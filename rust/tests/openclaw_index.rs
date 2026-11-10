use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;
use serde_json::{json, Value};
use tang::cli::run_with;
use tang::project::resolve_project;

fn scratch() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("tang-openclaw-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn build_db(path: &Path, project: &Path, foreign: &Path) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    let connection = Connection::open(path).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE session_nodes (
                session_key TEXT PRIMARY KEY,
                display_name TEXT,
                label TEXT,
                created_at INTEGER,
                updated_at INTEGER,
                last_activity_at INTEGER
            );
            CREATE TABLE session_windows (
                session_id TEXT,
                session_key TEXT,
                started_at INTEGER,
                ended_at INTEGER,
                status TEXT,
                display_name TEXT
            );
            CREATE TABLE transcript_events (
                session_id TEXT,
                seq INTEGER,
                event_json TEXT,
                created_at INTEGER,
                PRIMARY KEY (session_id, seq)
            );",
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO session_nodes VALUES ('agent:main:local', 'Local thread', NULL, 1000, 4000, 4000)",
            [],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO session_nodes VALUES ('agent:main:foreign', 'Foreign thread', NULL, 1000, 4000, 4000)",
            [],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO session_windows VALUES ('local-window', 'agent:main:local', 1000, 4000, 'done', 'Local thread')",
            [],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO session_windows VALUES ('foreign-window', 'agent:main:foreign', 1000, 4000, 'done', 'Foreign thread')",
            [],
        )
        .unwrap();
    let local = json!({
        "type": "message",
        "cwd": project.display().to_string(),
        "message": {"role": "user", "content": "compare tang session naming API_KEY=supersecretvalue"}
    });
    let reply = json!({
        "type": "message",
        "message": {"role": "assistant", "content": [{"type": "text", "text": "Tang uses short handles."}, {"type": "tool_use", "text": "TOOL_INPUT_CANARY"}]}
    });
    let foreign_event = json!({
        "type": "message",
        "cwd": foreign.display().to_string(),
        "message": {"role": "user", "content": "FOREIGN_OPENCLAW_CANARY"}
    });
    connection
        .execute(
            "INSERT INTO transcript_events VALUES ('local-window', 1, ?1, 1000)",
            [local.to_string()],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO transcript_events VALUES ('local-window', 2, ?1, 2000)",
            [reply.to_string()],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO transcript_events VALUES ('foreign-window', 1, ?1, 1000)",
            [foreign_event.to_string()],
        )
        .unwrap();
}

#[test]
fn index_reads_openclaw_sqlite_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&project_dir).unwrap();
    fs::create_dir_all(&foreign_dir).unwrap();
    let home = root.join("openclaw");
    let database_path = home.join("agents/main/agent/openclaw-agent.sqlite");
    build_db(&database_path, &project_dir, &foreign_dir);
    let linked_home = root.join("linked-home");
    let linked_db = linked_home.join("agents/main/agent/openclaw-agent.sqlite");
    fs::create_dir_all(linked_db.parent().unwrap()).unwrap();
    symlink(&database_path, &linked_db).unwrap();

    let mut stdout = Vec::new();
    let error = run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--openclaw-home".into(),
            linked_home.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap_err();
    assert_eq!(error.code, "unsafe-session-source");

    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--openclaw-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 2);
    assert_eq!(document["skipped"], 0);

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let search: String = database
        .query_row(
            "SELECT search_text FROM capsules WHERE search_text LIKE '%session naming%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(search.contains("session naming"));
    assert!(search.contains("short handles"));
    assert!(!search.contains("FOREIGN_OPENCLAW_CANARY"));
    assert!(!search.contains("TOOL_INPUT_CANARY"));
    assert!(!search.contains("supersecretvalue"));
    assert!(search.contains("[REDACTED:credential]"));

    let catalog = root.join("catalog.db");
    stdout.clear();
    run_with(
        &[
            "catalog".into(),
            "sync".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap();
    stdout.clear();
    run_with(
        &[
            "recall".into(),
            "naming".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let recall: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(recall["result_count"], 1);
    assert_eq!(recall["results"][0]["harness"], "openclaw");

    let source = Connection::open(&database_path).unwrap();
    source
        .execute(
            "DELETE FROM session_nodes WHERE session_key = 'agent:main:local'",
            [],
        )
        .unwrap();
    source
        .execute(
            "DELETE FROM session_windows WHERE session_key = 'agent:main:local'",
            [],
        )
        .unwrap();
    drop(source);
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--openclaw-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let again: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(again["deleted"], 1);
    assert_eq!(again["indexed"], 0);
}

#[test]
fn index_reads_openclaw_agents_other_than_main() {
    let root = scratch();
    let project_dir = root.join("work");
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&project_dir).unwrap();
    fs::create_dir_all(&foreign_dir).unwrap();
    let home = root.join("openclaw");
    build_db(
        &home.join("agents/main/agent/openclaw-agent.sqlite"),
        &project_dir,
        &foreign_dir,
    );
    let ops = home.join("agents/ops/agent/openclaw-agent.sqlite");
    build_db(&ops, &project_dir, &foreign_dir);
    let connection = Connection::open(&ops).unwrap();
    connection
        .execute_batch(
            "UPDATE session_nodes SET session_key = replace(session_key, 'agent:main:', 'agent:ops:');
             UPDATE session_windows SET session_key = replace(session_key, 'agent:main:', 'agent:ops:');",
        )
        .unwrap();
    drop(connection);
    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--openclaw-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 4);
    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let count: i64 = database
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 4);
}
