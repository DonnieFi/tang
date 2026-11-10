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
    let path = std::env::temp_dir().join(format!("tang-claude-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(
        "../tests/fixtures/claude/projects/-opt-tang-fixture/019f6000-c1a0-7000-8000-000000000001.jsonl",
    )
}

#[test]
fn index_reads_claude_transcript_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&project_dir).unwrap();
    fs::create_dir_all(&foreign_dir).unwrap();
    let project = resolve_project(&project_dir).unwrap();
    let slug = format!(
        "-{}",
        project
            .database_path
            .parent()
            .and_then(|path| path.parent())
            .unwrap()
            .to_string_lossy()
            .trim_start_matches('/')
            .replace('/', "-")
    );
    let home = root.join("claude");
    let transcript = home
        .join("projects")
        .join(&slug)
        .join("019f6000-c1a0-7000-8000-000000000001.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    let original = fs::read(fixture()).unwrap();
    let mut copy = String::from_utf8(original.clone()).unwrap();
    copy = copy.replace(
        "/tmp/tang-fixture-project",
        &project_dir.display().to_string(),
    );
    copy.push_str(&format!(
        "\n{{\"type\":\"user\",\"cwd\":\"{}\",\"message\":{{\"role\":\"user\",\"content\":\"API_KEY=supersecretvalue\"}}}}\n",
        project_dir.display()
    ));
    copy.push_str("{not valid json\n");
    fs::write(&transcript, copy).unwrap();
    fs::write(
        transcript.parent().unwrap().join("foreign.jsonl"),
        format!(
            "{{\"type\":\"user\",\"cwd\":\"{}\",\"message\":{{\"role\":\"user\",\"content\":\"FOREIGN_CLAUDE_CANARY\"}}}}\n",
            foreign_dir.display()
        ),
    )
    .unwrap();
    symlink(
        &transcript,
        transcript.parent().unwrap().join("linked.jsonl"),
    )
    .unwrap();

    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--database".into(),
            root.join("index.db").display().to_string(),
            "--claude-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 2);
    assert_eq!(document["skipped"], 0);
    assert!(document["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .any(|warning| warning.as_str().unwrap().contains("malformed")));
    assert_eq!(fs::read(fixture()).unwrap(), original);

    let database = Connection::open(root.join("index.db")).unwrap();
    let title: String = database
        .query_row(
            "SELECT title FROM sessions WHERE title = 'Indexer review fixture'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(title, "Indexer review fixture");
    let started_at: String = database
        .query_row(
            "SELECT started_at FROM sessions WHERE title = 'Indexer review fixture'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(started_at.starts_with("2026-05-07"));
    let search: String = database
        .query_row(
            "SELECT search_text FROM capsules WHERE search_text LIKE '%Review the Tang indexer module.%'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(search.contains("Review the Tang indexer module."));
    assert!(!search.contains("FOREIGN_CLAUDE_CANARY"));
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
            "indexer".into(),
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
    assert_eq!(recall["result_count"], 1);
    assert_eq!(recall["results"][0]["harness"], "claude");

    fs::remove_file(&transcript).unwrap();
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--database".into(),
            root.join("index.db").display().to_string(),
            "--claude-home".into(),
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
fn index_uses_the_project_slug_when_no_row_has_cwd() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let project = resolve_project(&project_dir).unwrap();
    let slug = format!(
        "-{}",
        project
            .database_path
            .parent()
            .and_then(|path| path.parent())
            .unwrap()
            .to_string_lossy()
            .trim_start_matches('/')
            .replace('/', "-")
    );
    let home = root.join("claude");
    let transcript = home
        .join("projects")
        .join(slug)
        .join("019f6000-c1a0-7000-8000-000000000002.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    fs::write(
        &transcript,
        "{\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":\"slug session without cwd\"}}\n",
    )
    .unwrap();
    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--database".into(),
            root.join("index.db").display().to_string(),
            "--claude-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 1);
    assert_eq!(document["skipped"], 0);
    let database = Connection::open(root.join("index.db")).unwrap();
    let search: String = database
        .query_row("SELECT search_text FROM capsules", [], |row| row.get(0))
        .unwrap();
    assert!(search.contains("slug session without cwd"));
}
