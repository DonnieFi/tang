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
    let path = std::env::temp_dir().join(format!("tang-cursor-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn fixture() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../tests/fixtures/cursor/agent-transcripts/fixture-session/fixture-session.jsonl")
}

#[test]
fn index_reads_cursor_transcript_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let project = resolve_project(&project_dir).unwrap();
    let slug = project
        .database_path
        .parent()
        .and_then(|path| path.parent())
        .unwrap()
        .to_string_lossy()
        .trim_matches('/')
        .replace('/', "-");
    let home = root.join("cursor");
    let transcript = home
        .join("projects")
        .join(&slug)
        .join("agent-transcripts/fixture-session/fixture-session.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    let original = fs::read(fixture()).unwrap();
    let mut copy = String::from_utf8(original.clone()).unwrap();
    copy.push_str(
        "\n{\"role\":\"user\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"API_KEY=supersecretvalue\"}]}}\n",
    );
    copy.push_str(
        "{\"role\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"shell\",\"input\":{\"secret\":\"TOOL_INPUT_CANARY\"}}]}}\n",
    );
    copy.push_str("{not valid json\n");
    fs::write(&transcript, &copy).unwrap();
    let foreign = home.join("projects/other-project/agent-transcripts/other/other.jsonl");
    fs::create_dir_all(foreign.parent().unwrap()).unwrap();
    fs::write(
        &foreign,
        "{\"role\":\"user\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"FOREIGN_CURSOR_CANARY\"}]}}\n",
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
            "--cursor-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["indexed"], 1);
    assert!(document["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .any(|warning| warning.as_str().unwrap().contains("malformed")));
    assert_eq!(fs::read(fixture()).unwrap(), original);

    let database = Connection::open(&project.database_path).unwrap();
    let search: String = database
        .query_row("SELECT search_text FROM capsules", [], |row| row.get(0))
        .unwrap();
    assert!(search.contains("session search bug"));
    assert!(!search.contains("FOREIGN_CURSOR_CANARY"));
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
            "search".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let recall: Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(recall["result_count"], 1);
    assert_eq!(recall["results"][0]["harness"], "cursor");

    fs::remove_file(&transcript).unwrap();
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--cursor-home".into(),
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
fn index_reads_cursor_sidecar_timestamps() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let project = resolve_project(&project_dir).unwrap();
    let project_root = project
        .database_path
        .parent()
        .and_then(|path| path.parent())
        .unwrap();
    let slug = project_root
        .to_string_lossy()
        .trim_matches('/')
        .replace('/', "-");
    let home = root.join("cursor");
    let transcript = home
        .join("projects")
        .join(slug)
        .join("agent-transcripts/fixture-session/fixture-session.jsonl");
    fs::create_dir_all(transcript.parent().unwrap()).unwrap();
    fs::write(
        &transcript,
        "{\"role\":\"user\",\"message\":{\"content\":[{\"type\":\"text\",\"text\":\"sidecar session\"}]}}\n",
    )
    .unwrap();
    let hash = tang::index_cursor::workspace_chat_hash(&project_root.to_string_lossy());
    let meta = home
        .join("chats")
        .join(hash)
        .join("fixture-session")
        .join("meta.json");
    fs::create_dir_all(meta.parent().unwrap()).unwrap();
    fs::write(&meta, r#"{"createdAtMs":86400000,"updatedAtMs":172800000}"#).unwrap();
    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--cursor-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let (started, updated): (String, String) = database
        .query_row("SELECT started_at, updated_at FROM sessions", [], |row| {
            Ok((row.get(0)?, row.get(1)?))
        })
        .unwrap();
    assert_eq!(started, "1970-01-02T00:00:00Z");
    assert_eq!(updated, "1970-01-03T00:00:00Z");
}
