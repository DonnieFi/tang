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
    let path = std::env::temp_dir().join(format!("tang-opencode-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/fixtures/opencode/session-export.json")
}

fn write_export(path: &Path, directory: &Path, session_id: &str, secret: bool) {
    let mut value: Value = serde_json::from_str(&fs::read_to_string(fixture()).unwrap()).unwrap();
    value["info"]["id"] = json!(session_id);
    value["info"]["directory"] = json!(directory.display().to_string());
    if secret {
        value["messages"].as_array_mut().unwrap().push(json!({
            "info": {"role": "user"},
            "parts": [{"type": "text", "text": "API_KEY=supersecretvalue"}]
        }));
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    fs::write(path, serde_json::to_string(&value).unwrap()).unwrap();
}

#[test]
fn index_reads_opencode_export_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&project_dir).unwrap();
    fs::create_dir_all(&foreign_dir).unwrap();
    let home = root.join("opencode");
    let export = home.join("session-export.json");
    let original = fs::read(fixture()).unwrap();
    write_export(
        &export,
        &project_dir,
        "ses_tang00000000000000000000001",
        true,
    );
    write_export(
        &home.join("foreign-export.json"),
        &foreign_dir,
        "ses_tang00000000000000000000099",
        false,
    );
    symlink(&export, home.join("linked-export.json")).unwrap();

    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--database".into(),
            root.join("index.db").display().to_string(),
            "--opencode-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 2);
    assert_eq!(document["skipped"], 0);
    assert_eq!(fs::read(fixture()).unwrap(), original);

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(root.join("index.db")).unwrap();
    let search: String = database
        .query_row(
            "SELECT search_text FROM capsules WHERE project_key = ?1",
            [project.key.clone()],
            |row| row.get(0),
        )
        .unwrap();
    assert!(search.contains("source-cited OpenCode continuation"));
    assert!(search.contains("supported source and destination seams"));
    assert!(!search.contains("HIDDEN_REASONING_CANARY"));
    assert!(!search.contains("TOOL_INPUT_CANARY"));
    assert!(!search.contains("TOOL_OUTPUT_CANARY"));
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
            "--database".into(),
            root.join("index.db").display().to_string(),
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
            "continuation".into(),
            "--database".into(),
            root.join("index.db").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let recall: Value = serde_json::from_slice(&stdout).unwrap();
    assert!(recall["result_count"].as_i64().unwrap() >= 1);
    assert!(recall["results"]
        .as_array()
        .unwrap()
        .iter()
        .any(|result| result["harness"] == "opencode"));
    assert!(recall["results"].as_array().unwrap().iter().all(|result| {
        !result["summary"]
            .as_str()
            .unwrap_or("")
            .contains("supersecretvalue")
    }));

    fs::remove_file(&export).unwrap();
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--database".into(),
            root.join("index.db").display().to_string(),
            "--opencode-home".into(),
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
fn incidental_json_is_ignored_and_a_malformed_export_keeps_its_row() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let home = root.join("opencode");
    let export = home.join("session-export.json");
    let session_id = "ses_tang00000000000000000000001";
    write_export(&export, &project_dir, session_id, false);
    fs::write(home.join("session-list.json"), "{\"items\":[]}").unwrap();
    fs::write(home.join("tool-context.json"), "{\"cwd\":\"/tmp\"}").unwrap();
    let arguments = [
        "index".to_string(),
        "--cwd".to_string(),
        project_dir.display().to_string(),
        "--opencode-home".to_string(),
        home.display().to_string(),
        "--database".to_string(),
        root.join("index.db").display().to_string(),
        "--json".to_string(),
    ];
    let mut stdout = Vec::new();
    run_with(&arguments, &mut stdout).unwrap();
    let first: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(first["indexed"], 1);
    assert!(first["warnings"].as_array().unwrap().is_empty());

    fs::write(
        &export,
        format!("{{\"info\":{{\"id\":\"{session_id}\", \"directory\": \"not closed"),
    )
    .unwrap();
    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let again: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(again["indexed"], 0);
    assert_eq!(again["deleted"], 0);
    assert!(!again["warnings"].as_array().unwrap().is_empty());
    let database = Connection::open(root.join("index.db")).unwrap();
    let count: i64 = database
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(count, 1);
}
