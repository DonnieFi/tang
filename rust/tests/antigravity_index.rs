use std::fs;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
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
    let path =
        std::env::temp_dir().join(format!("tang-antigravity-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn transcript_fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(
        "../tests/fixtures/antigravity/brain/019f6000-a017-7000-8000-000000000001/.system_generated/logs/transcript.jsonl",
    )
}

fn history_fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../tests/fixtures/antigravity/history.jsonl")
}

#[test]
fn index_reads_antigravity_transcript_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&project_dir).unwrap();
    fs::create_dir_all(&foreign_dir).unwrap();
    let home = root.join("antigravity");
    let conversation = "019f6000-antg-7000-8000-000000000001";
    let transcript = home
        .join("brain")
        .join(conversation)
        .join(".system_generated/logs/transcript.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    let original_history = fs::read(history_fixture()).unwrap();
    let original_transcript = fs::read(transcript_fixture()).unwrap();
    let mut copy = String::from_utf8(original_transcript.clone()).unwrap();
    copy.push_str(
        "\n{\"step_index\":2,\"source\":\"USER_EXPLICIT\",\"type\":\"USER_INPUT\",\"status\":\"DONE\",\"created_at\":\"2026-07-01T12:00:02Z\",\"content\":\"API_KEY=supersecretvalue\"}\n",
    );
    copy.push_str(
        "\n{\"step_index\":3,\"source\":\"MODEL\",\"type\":\"PLANNER_RESPONSE\",\"status\":\"DONE\",\"created_at\":\"2026-07-01T12:00:03Z\",\"content\":\"CommandLine: TOOL_OUTPUT_CANARY\"}\n",
    );
    fs::write(&transcript, copy).unwrap();
    fs::write(
        home.join("history.jsonl"),
        format!(
            "{{\"display\":\"Confirm branch for release\",\"timestamp\":1784570653707,\"workspace\":\"{}\",\"conversationId\":\"{conversation}\"}}\n{{\"display\":\"Foreign\",\"timestamp\":1784570653708,\"workspace\":\"{}\",\"conversationId\":\"019f6000-antg-7000-8000-000000000099\"}}\n",
            project_dir.display(),
            foreign_dir.display()
        ),
    )
    .unwrap();
    let linked = home
        .join("brain/019f6000-antg-7000-8000-000000000077/.system_generated/logs/transcript.jsonl");
    fs::create_dir_all(linked.parent().unwrap()).unwrap();
    symlink(&transcript, &linked).unwrap();
    fs::write(
        home.join("history.jsonl"),
        format!(
            "{}\n{{\"display\":\"Linked\",\"timestamp\":1784570653709,\"workspace\":\"{}\",\"conversationId\":\"019f6000-antg-7000-8000-000000000077\"}}\n",
            fs::read_to_string(home.join("history.jsonl")).unwrap().trim_end(),
            project_dir.display()
        ),
    )
    .unwrap();

    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--antigravity-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 1);
    assert!(document["skipped"].as_i64().unwrap() >= 1);
    assert_eq!(fs::read(history_fixture()).unwrap(), original_history);
    assert_eq!(fs::read(transcript_fixture()).unwrap(), original_transcript);

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let search: String = database
        .query_row(
            "SELECT search_text FROM capsules WHERE search_text LIKE '%Confirm the branch for the release.%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(search.contains("Confirm the branch for the release."));
    assert!(search.contains("release branch is still open"));
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
            "branch".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let recall: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(recall["result_count"], 1);
    assert_eq!(recall["results"][0]["harness"], "antigravity");

    fs::remove_file(&transcript).unwrap();
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--antigravity-home".into(),
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
fn a_symlinked_history_warns_and_skips() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let home = root.join("antigravity");
    fs::create_dir_all(&home).unwrap();
    let real = root.join("history.jsonl");
    fs::write(&real, "{\"conversationId\":\"x\"}\n").unwrap();
    symlink(&real, home.join("history.jsonl")).unwrap();
    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--antigravity-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 0);
    assert_eq!(document["deleted"], 0);
    assert!(document["warnings"][0]
        .as_str()
        .unwrap()
        .contains("skipped symlinked Antigravity history"));
}
