use std::fs;
use std::os::unix::fs::symlink;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;
use serde_json::Value;
use tang::cli::run_with;
use tang::project::resolve_project;

fn scratch() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("tang-grok-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn fixture_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(
        "../tests/fixtures/grok/sessions/%2Fwork%2Ftang-demo/019f6000-1234-7000-8000-000000000001",
    )
}

fn copy_session(destination: &Path, git_root: &Path, with_secret: bool) {
    fs::create_dir_all(destination).unwrap();
    let mut summary: Value =
        serde_json::from_str(&fs::read_to_string(fixture_dir().join("summary.json")).unwrap())
            .unwrap();
    summary["git_root_dir"] = Value::String(git_root.display().to_string());
    fs::write(
        destination.join("summary.json"),
        serde_json::to_string_pretty(&summary).unwrap(),
    )
    .unwrap();
    let mut updates = fs::read_to_string(fixture_dir().join("updates.jsonl")).unwrap();
    if with_secret {
        updates.push_str(
            r#"{"method":"session/update","params":{"sessionId":"019f6000-1234-7000-8000-000000000001","update":{"sessionUpdate":"user_message_chunk","content":{"type":"text","text":"API_KEY=supersecretvalue"}}},"timestamp":1784059250}"#,
        );
        updates.push('\n');
    }
    fs::write(destination.join("updates.jsonl"), updates).unwrap();
}

#[test]
fn index_reads_grok_fixture_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&project_dir).unwrap();
    fs::create_dir_all(&foreign_dir).unwrap();
    let home = root.join("grok");
    let session = home.join("sessions/project/019f6000-1234-7000-8000-000000000001");
    let original_summary = fs::read(fixture_dir().join("summary.json")).unwrap();
    let original_updates = fs::read(fixture_dir().join("updates.jsonl")).unwrap();
    copy_session(&session, &project_dir, true);
    copy_session(
        &home.join("sessions/other/019f6000-1234-7000-8000-000000000099"),
        &foreign_dir,
        false,
    );
    let link = home.join("sessions/linked");
    symlink(&session, &link).unwrap();

    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--grok-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 2);
    assert_eq!(document["skipped"], 0);
    assert_eq!(
        fs::read(fixture_dir().join("summary.json")).unwrap(),
        original_summary
    );
    assert_eq!(
        fs::read(fixture_dir().join("updates.jsonl")).unwrap(),
        original_updates
    );

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let search: String = database
        .query_row(
            "SELECT search_text FROM capsules WHERE search_text LIKE '%deterministic cache boundary%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(search.contains("deterministic cache boundary"));
    assert!(search.contains("content fingerprint"));
    assert!(!search.contains("HIDDEN_THOUGHT_CANARY"));
    assert!(!search.contains("TOOL_INPUT_CANARY"));
    assert!(!search.contains("FILE_BODY_CANARY"));
    assert!(!search.contains("UNKNOWN_METHOD_CANARY"));
    assert!(!search.contains("supersecretvalue"));
    assert!(search.contains("[REDACTED:credential]"));
    let harness: String = database
        .query_row(
            "SELECT adapter FROM sessions WHERE project_key = ?1",
            [project.key.clone()],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(harness, "grok");

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
            "fingerprint".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let recall: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(recall["result_count"], 1);
    assert_eq!(recall["results"][0]["harness"], "grok");
    assert!(!recall["results"][0]["summary"]
        .as_str()
        .unwrap()
        .contains("supersecretvalue"));

    fs::remove_dir_all(&session).unwrap();
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--grok-home".into(),
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
fn index_keeps_a_session_when_the_update_stream_is_malformed() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let home = root.join("grok");
    let session = home.join("sessions/project/019f6000-1234-7000-8000-000000000001");
    copy_session(&session, &project_dir, false);
    let arguments = [
        "index".to_string(),
        "--cwd".to_string(),
        project_dir.display().to_string(),
        "--grok-home".to_string(),
        home.display().to_string(),
        "--json".to_string(),
    ];
    let mut stdout = Vec::new();
    run_with(&arguments, &mut stdout).unwrap();
    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let before: i64 = database
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(before, 1);
    drop(database);

    fs::write(session.join("updates.jsonl"), "{not valid json\n").unwrap();
    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let document: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 0);
    assert_eq!(document["deleted"], 0);

    let database = Connection::open(&project.database_path).unwrap();
    let after: i64 = database
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(after, 1);
}

#[test]
fn index_keeps_a_session_when_summary_or_updates_are_missing() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let home = root.join("grok");
    let missing_summary = home.join("sessions/project/019f6000-1234-7000-8000-000000000001");
    let missing_updates = home.join("sessions/project/019f6000-1234-7000-8000-000000000002");
    copy_session(&missing_summary, &project_dir, false);
    fs::remove_file(missing_summary.join("summary.json")).unwrap();
    fs::create_dir_all(missing_summary.parent().unwrap()).unwrap();
    fs::write(
        missing_summary.parent().unwrap().join(".cwd"),
        project_dir.display().to_string(),
    )
    .unwrap();
    copy_session(&missing_updates, &project_dir, false);
    fs::remove_file(missing_updates.join("updates.jsonl")).unwrap();

    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--grok-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 2);
    assert_eq!(document["skipped"], 0);
    let warnings = document["warnings"].as_array().unwrap();
    assert!(warnings.iter().any(|warning| warning
        .as_str()
        .unwrap()
        .contains("missing summary metadata")));
    assert!(warnings.iter().any(|warning| warning
        .as_str()
        .unwrap()
        .contains("missing its update stream")));
    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let count: i64 = database
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 2);
}
