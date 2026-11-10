//! End-to-end exercise of index, recall, labels, join, counts, and the map.

use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::Value;
use tang::cli::run_with;

fn scratch() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("tang-workflow-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn codex_log(home: &std::path::Path, project: &std::path::Path, id: &str, text: &str) {
    let path = home.join(format!(
        "sessions/2026/11/09/rollout-2026-11-09T20-00-00-{id}.jsonl"
    ));
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    let meta = serde_json::json!({
        "timestamp": "2026-11-09T20:00:00Z",
        "type": "session_meta",
        "payload": {"id": id, "cwd": project.display().to_string(), "timestamp": "2026-11-09T20:00:00Z"}
    });
    let turn = serde_json::json!({
        "timestamp": "2026-11-09T20:01:00Z",
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": text}]
        }
    });
    fs::write(path, format!("{meta}\n{turn}\n")).unwrap();
}

fn grok_session(home: &std::path::Path, project: &std::path::Path, id: &str, text: &str) {
    let dir = home.join(format!("sessions/project/{id}"));
    fs::create_dir_all(&dir).unwrap();
    fs::write(
        dir.join("summary.json"),
        serde_json::to_string(&serde_json::json!({
            "git_root_dir": project.display().to_string(),
            "created_at": "2026-11-09T20:00:00Z",
            "updated_at": "2026-11-09T20:05:00Z",
            "generated_title": "Grok review"
        }))
        .unwrap(),
    )
    .unwrap();
    fs::write(
        dir.join("updates.jsonl"),
        format!(
            "{}\n",
            serde_json::json!({
                "method": "session/update",
                "params": {
                    "sessionId": id,
                    "update": {
                        "sessionUpdate": "user_message_chunk",
                        "content": {"type": "text", "text": text}
                    }
                }
            })
        ),
    )
    .unwrap();
}

fn run(args: &[&str]) -> String {
    let owned: Vec<String> = args.iter().map(|arg| (*arg).to_string()).collect();
    let mut stdout = Vec::new();
    run_with(&owned, &mut stdout).unwrap_or_else(|error| {
        panic!("{}: {}", error.code, error.message);
    });
    String::from_utf8(stdout).unwrap()
}

#[test]
fn search_tag_join_counts_and_map_one_project() {
    let root = scratch();
    let project = root.join("work");
    fs::create_dir_all(&project).unwrap();
    let codex = root.join("codex");
    let grok = root.join("grok");
    let catalog = root.join("catalog.db");
    codex_log(
        &codex,
        &project,
        "019f6000-1111-7000-8000-000000000001",
        "implement the cache boundary",
    );
    codex_log(
        &codex,
        &project,
        "019f6000-2222-7000-8000-000000000002",
        "we decided the release plan",
    );
    grok_session(
        &grok,
        &project,
        "019f6000-3333-7000-8000-000000000003",
        "please review the implementation notes",
    );
    let project_arg = project.display().to_string();
    let catalog_arg = catalog.display().to_string();
    let index_arg = root.join("index.db").display().to_string();
    let indexed = run(&[
        "index",
        "--cwd",
        &project_arg,
        "--database",
        &index_arg,
        "--codex-home",
        &codex.display().to_string(),
        "--grok-home",
        &grok.display().to_string(),
        "--json",
    ]);
    let indexed: Value = serde_json::from_str(&indexed).unwrap();
    assert_eq!(indexed["indexed"], 3);

    run(&[
        "catalog",
        "sync",
        "--cwd",
        &project_arg,
        "--database",
        &index_arg,
        "--catalog",
        &catalog_arg,
    ]);
    run(&["label", "add", "C2", "release", "--catalog", &catalog_arg]);

    let search = run(&["recall", "cache", "--database", &index_arg, "--json"]);
    let search: Value = serde_json::from_str(&search).unwrap();
    assert_eq!(search["result_count"], 1);
    assert_eq!(search["results"][0]["catalog_handle"], "C1");

    let tagged = run(&[
        "recall",
        "--label",
        "release",
        "--catalog",
        &catalog_arg,
        "--json",
    ]);
    let tagged: Value = serde_json::from_str(&tagged).unwrap();
    assert_eq!(tagged["result_count"], 1);
    assert_eq!(tagged["results"][0]["catalog_handle"], "C2");
    assert_eq!(tagged["results"][0]["labels"][0], "release");

    let joined = run(&[
        "join",
        "--from",
        "C1",
        "--from",
        "G1",
        "--into",
        "C2",
        "--catalog",
        &catalog_arg,
        "--json",
    ]);
    let joined: Value = serde_json::from_str(&joined).unwrap();
    assert_eq!(joined["inserted"], 2);

    let stats = run(&[
        "stats",
        "--cwd",
        &project_arg,
        "--database",
        &index_arg,
        "--catalog",
        &catalog_arg,
        "--json",
    ]);
    let stats: Value = serde_json::from_str(&stats).unwrap();
    assert_eq!(stats["schema_version"], 1);
    assert_eq!(stats["sessions"], 3);
    assert_eq!(stats["projects"], 1);
    assert_eq!(stats["harnesses"]["codex"], 2);
    assert_eq!(stats["harnesses"]["grok"], 1);
    assert_eq!(stats["categories"]["implementation"], 1);
    assert_eq!(stats["categories"]["decision"], 1);
    assert_eq!(stats["categories"]["review"], 1);
    assert_eq!(stats["labels"]["release"], 1);
    assert_eq!(stats["edges"], 2);
    assert_eq!(stats["components"], 1);

    let map = run(&[
        "graph",
        "--cwd",
        &project_arg,
        "--database",
        &index_arg,
        "--ascii",
        "--width",
        "64",
    ]);
    assert!(map.contains("MULTIVERSE NETWORK"));
    assert!(map.contains("MERGE") || map.contains("C1"));
    assert!(map.contains("C1"));
    assert!(map.contains("C2"));
    let alias = run(&[
        "map",
        "--cwd",
        &project_arg,
        "--database",
        &index_arg,
        "--json",
    ]);
    let alias: Value = serde_json::from_str(&alias).unwrap();
    assert_eq!(alias["schema_version"], 1);
    assert_eq!(alias["edges"].as_array().unwrap().len(), 2);
    assert_eq!(alias["component_count"], 1);
    assert!(alias["timelines"].as_array().unwrap().len() >= 2);
}
