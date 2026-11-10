use std::fs;
use std::os::unix::fs::symlink;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;
use tang::cli::run_with;
use tang::project::resolve_project;

fn scratch() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("tang-index-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn fixture_copy(destination: &std::path::Path, cwd: &std::path::Path) {
    let source = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../tests/fixtures/codex/sessions/2026/07/14/rollout-2026-07-14T20-00-00-019f6000-5678-7000-8000-000000000002.jsonl");
    let mut lines = fs::read_to_string(&source)
        .unwrap()
        .lines()
        .map(str::to_string)
        .collect::<Vec<_>>();
    let mut meta: serde_json::Value = serde_json::from_str(&lines[0]).unwrap();
    meta["payload"]["cwd"] = serde_json::Value::String(cwd.display().to_string());
    lines[0] = serde_json::to_string(&meta).unwrap();
    lines.insert(
        1,
        r##"{"timestamp":"2026-07-14T20:00:00Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"# AGENTS.md instructions for /work/tang-demo"}]}}"##
            .to_string(),
    );
    lines.push(
        r#"{"timestamp":"2026-07-14T20:02:00Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"API_KEY=supersecretvalue"}]}}"#
            .to_string(),
    );
    lines.push("{not valid json".to_string());
    let parent = destination.parent().unwrap();
    fs::create_dir_all(parent).unwrap();
    fs::write(destination, lines.join("\n") + "\n").unwrap();
}

#[test]
fn index_reads_codex_fixture_then_recall_redacts_it() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let foreign_dir = root.join("foreign");
    fs::create_dir_all(&foreign_dir).unwrap();
    let home = root.join("codex");
    let log = home.join(
        "sessions/2026/07/14/rollout-2026-07-14T20-00-00-019f6000-5678-7000-8000-000000000002.jsonl",
    );
    let original = fs::read(
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(
            "../tests/fixtures/codex/sessions/2026/07/14/rollout-2026-07-14T20-00-00-019f6000-5678-7000-8000-000000000002.jsonl",
        ),
    )
    .unwrap();
    fixture_copy(&log, &project_dir);
    let foreign_log = home.join(
        "sessions/2026/07/14/rollout-2026-07-14T20-00-00-019f6000-5678-7000-8000-000000000099.jsonl",
    );
    fs::write(
        &foreign_log,
        format!(
            r#"{{"timestamp":"2026-07-14T20:00:00Z","type":"session_meta","payload":{{"id":"019f6000-5678-7000-8000-000000000099","timestamp":"2026-07-14T20:00:00Z","cwd":"{}"}}}}
{{"timestamp":"2026-07-14T20:00:01Z","type":"response_item","payload":{{"type":"message","role":"user","content":[{{"type":"input_text","text":"foreign only"}}]}}}}
"#,
            foreign_dir.display()
        ),
    )
    .unwrap();
    let link = home.join(
        "sessions/2026/07/14/rollout-2026-07-14T20-00-00-019f6000-5678-7000-8000-000000000077.jsonl",
    );
    symlink(&log, &link).unwrap();

    let mut stdout = Vec::new();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--codex-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["schema_version"], 1);
    assert_eq!(document["indexed"], 1);
    assert_eq!(document["skipped"], 1);
    assert!(document["warnings"]
        .as_array()
        .unwrap()
        .iter()
        .any(|warning| warning.as_str().unwrap().contains("malformed")));
    assert_eq!(fs::read(original_path()).unwrap(), original);

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let health: String = database
        .query_row("SELECT health FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(health, "unknown");
    let title: String = database
        .query_row("SELECT title FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(
        title,
        "Implement deterministic checkpoint recovery for the synthetic adapter."
    );
    let search: String = database
        .query_row("SELECT search_text FROM capsules", [], |row| row.get(0))
        .unwrap();
    assert!(search.contains("deterministic checkpoint recovery"));
    assert!(!search.contains("AGENTS.md"));
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
            "checkpoint".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let recall: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(recall["result_count"], 1);
    assert_eq!(recall["results"][0]["harness"], "codex");
    let summary = recall["results"][0]["summary"].as_str().unwrap();
    assert!(!summary.contains("supersecretvalue"));

    fs::remove_file(&log).unwrap();
    stdout.clear();
    run_with(
        &[
            "index".into(),
            "--cwd".into(),
            project_dir.display().to_string(),
            "--codex-home".into(),
            home.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let again: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(again["deleted"], 1);
    assert_eq!(again["indexed"], 0);
}

fn original_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join(
        "../tests/fixtures/codex/sessions/2026/07/14/rollout-2026-07-14T20-00-00-019f6000-5678-7000-8000-000000000002.jsonl",
    )
}

fn write_minimal_log(home: &std::path::Path, cwd: &std::path::Path, native_id: &str) -> PathBuf {
    let log = home
        .join("sessions")
        .join("2026/11/09")
        .join(format!("rollout-2026-11-09T00-00-00-{native_id}.jsonl"));
    fs::create_dir_all(log.parent().unwrap()).unwrap();
    fs::write(
        &log,
        format!(
            r#"{{"timestamp":"2026-11-09T00:00:00Z","type":"session_meta","payload":{{"id":"{native_id}","timestamp":"2026-11-09T00:00:00Z","cwd":"{}"}}}}
{{"timestamp":"2026-11-09T00:00:01Z","type":"response_item","payload":{{"type":"message","role":"user","content":[{{"type":"input_text","text":"trace the tombstone"}}]}}}}
"#,
            cwd.display()
        ),
    )
    .unwrap();
    log
}

#[test]
fn index_keeps_a_graph_referenced_session_as_a_tombstone() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let home = root.join("codex");
    let native_id = "019f6000-5678-7000-8000-000000000123";
    let log = write_minimal_log(&home, &project_dir, native_id);
    let mut stdout = Vec::new();
    let arguments = [
        "index".to_string(),
        "--cwd".to_string(),
        project_dir.display().to_string(),
        "--codex-home".to_string(),
        home.display().to_string(),
        "--json".to_string(),
    ];
    run_with(&arguments, &mut stdout).unwrap();

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let source_id: String = database
        .query_row("SELECT source_id FROM sessions", [], |row| row.get(0))
        .unwrap();
    database
        .execute(
            "INSERT INTO continuation_edges(
                source_id, target_id, project_key, confirmation_mode, confirmed_at, schema_version
             ) VALUES (?1, 'codex:test:target', ?2, 'explicit', '2026-11-09T00:00:02Z', 1)",
            rusqlite::params![source_id, project.key],
        )
        .unwrap();
    drop(database);

    fs::remove_file(&log).unwrap();
    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let document: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["deleted"], 1);

    let database = Connection::open(&project.database_path).unwrap();
    let available: i64 = database
        .query_row(
            "SELECT native_available FROM sessions WHERE source_id = ?1",
            [&source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(available, 0);
    let edges: i64 = database
        .query_row("SELECT COUNT(*) FROM continuation_edges", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(edges, 1);
    let capsules: i64 = database
        .query_row("SELECT COUNT(*) FROM capsules", [], |row| row.get(0))
        .unwrap();
    assert_eq!(capsules, 0);

    database
        .execute("DELETE FROM continuation_edges", [])
        .unwrap();
    drop(database);
    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let sessions: i64 = database
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(sessions, 0);
}

#[test]
fn reindex_skips_unchanged_codex_logs_and_records_a_checkpoint() {
    let root = scratch();
    let project_dir = root.join("work");
    fs::create_dir_all(&project_dir).unwrap();
    let home = root.join("codex");
    let native_id = "019f6000-5678-7000-8000-000000000321";
    let log = write_minimal_log(&home, &project_dir, native_id);
    let arguments = [
        "index".to_string(),
        "--cwd".to_string(),
        project_dir.display().to_string(),
        "--codex-home".to_string(),
        home.display().to_string(),
        "--json".to_string(),
    ];
    let mut stdout = Vec::new();
    run_with(&arguments, &mut stdout).unwrap();
    let first: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(first["indexed"], 1);

    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let second: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(second["indexed"], 0);
    assert_eq!(second["unchanged"], 1);
    assert_eq!(second["deleted"], 0);

    let project = resolve_project(&project_dir).unwrap();
    let database = Connection::open(&project.database_path).unwrap();
    let checkpoints: i64 = database
        .query_row("SELECT COUNT(*) FROM adapter_checkpoints", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(checkpoints, 1);
    let version: i64 = database
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(version, 8);
    drop(database);

    let mut changed = fs::read_to_string(&log).unwrap();
    changed.push_str(
        "{\"timestamp\":\"2026-11-09T00:00:02Z\",\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"a new turn\"}]}}\n",
    );
    fs::write(&log, changed).unwrap();
    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let third: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(third["indexed"], 1);

    fs::remove_file(&log).unwrap();
    stdout.clear();
    run_with(&arguments, &mut stdout).unwrap();
    let fourth: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(fourth["deleted"], 1);
}
