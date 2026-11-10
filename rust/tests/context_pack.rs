use rusqlite::{params, Connection};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use tang::context_pack::{
    build_pack, render_json, render_markdown, ContextPack, ContextRequest, UNTRUSTED_NOTICE,
};

const PROJECT: &str = "project-key";
const LOCATOR: &str = "/tmp/tang-secret-locator/session.jsonl";
const MARKER: &str = "…[Truncated]";

const SCHEMA: &str = "
CREATE TABLE sessions (
    source_id TEXT PRIMARY KEY,
    project_key TEXT NOT NULL,
    adapter TEXT NOT NULL,
    session_handle TEXT,
    title TEXT,
    updated_at TEXT NOT NULL,
    locator TEXT
);
CREATE TABLE capsules (
    source_id TEXT PRIMARY KEY,
    project_key TEXT NOT NULL,
    content_json TEXT NOT NULL
);
CREATE TABLE continuation_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    project_key TEXT NOT NULL
);
";

fn open_db(name: &str) -> Connection {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "tang-context-{name}-{}-{nanos}",
        std::process::id()
    ));
    let repo = PathBuf::from("/agent/repos/tang");
    assert!(
        dir.starts_with(std::env::temp_dir()),
        "context pack tests must use a temp directory"
    );
    assert!(
        !dir.starts_with(&repo),
        "refusing to touch the repository database"
    );
    fs::create_dir_all(&dir).unwrap();
    let connection = Connection::open(dir.join("pack.db")).unwrap();
    connection.execute_batch(SCHEMA).unwrap();
    connection
}

fn adapter_of(source_id: &str) -> &str {
    source_id.split(':').next().unwrap_or("session")
}

fn insert_session(
    db: &Connection,
    project: &str,
    source_id: &str,
    handle: &str,
    title: &str,
    updated_at: &str,
    excerpts: &[(&str, &str)],
) {
    let adapter = adapter_of(source_id);
    let content = serde_json::json!({
        "schema_version": 1,
        "harness": adapter,
        "source_title": title,
        "display_name": title,
        "locator": LOCATOR,
        "excerpts": excerpts
            .iter()
            .map(|(role, text)| serde_json::json!({"role": role, "text": text}))
            .collect::<Vec<_>>(),
    });
    db.execute(
        "INSERT INTO sessions(
            source_id, project_key, adapter, session_handle, title, updated_at, locator
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![source_id, project, adapter, handle, title, updated_at, LOCATOR],
    )
    .unwrap();
    db.execute(
        "INSERT INTO capsules(source_id, project_key, content_json) VALUES (?1, ?2, ?3)",
        params![source_id, project, content.to_string()],
    )
    .unwrap();
}

fn insert_edge(db: &Connection, project: &str, source_id: &str, target_id: &str) {
    db.execute(
        "INSERT INTO continuation_edges(source_id, target_id, project_key) VALUES (?1, ?2, ?3)",
        params![source_id, target_id, project],
    )
    .unwrap();
}

fn tokens(text: &str) -> u64 {
    u64::try_from(text.chars().count()).unwrap().div_ceil(4)
}

fn assert_pack(pack: &ContextPack) {
    let markdown = render_markdown(pack);
    let json = render_json(pack);
    let estimate = tokens(&markdown).max(tokens(&json));
    assert!(estimate <= 2_000, "estimate {estimate}");
    assert_eq!(pack.estimated_tokens, estimate);
    assert!(markdown.starts_with(UNTRUSTED_NOTICE));
    assert!(markdown.ends_with('\n'));
    assert!(!markdown.ends_with("\n\n"));
    assert!(!markdown.contains(LOCATOR));
    assert!(!json.contains(LOCATOR));
    assert_eq!(render_markdown(pack), markdown);
    assert_eq!(render_json(pack), json);

    let parsed: serde_json::Value = serde_json::from_str(json.trim()).unwrap();
    assert_eq!(parsed["schema_version"].as_u64(), Some(1));
    assert_eq!(
        parsed["estimated_tokens"].as_u64(),
        Some(pack.estimated_tokens)
    );
    assert_eq!(parsed["truncated"].as_bool(), Some(pack.truncated));
    assert_eq!(
        parsed["project_key"].as_str(),
        Some(pack.project_key.as_str())
    );
    assert_eq!(
        parsed["untrusted_data_envelope"]["notice"].as_str(),
        Some(UNTRUSTED_NOTICE)
    );
    let pretty = serde_json::to_string_pretty(&parsed).unwrap();
    assert_eq!(json.trim_end(), pretty);

    let mut offset = 0;
    for source in &pack.sources {
        let heading = format!("## {}\n", source.handle);
        let found = markdown[offset..]
            .find(&heading)
            .unwrap_or_else(|| panic!("missing {heading}"));
        offset += found + heading.len();
        assert!(markdown.contains(&format!("Harness: {}", source.harness)));
        assert!(markdown.contains(&format!("Title: {}", source.title)));
        for excerpt in &source.excerpts {
            let citation = format!(
                "source: {} {} {}\n",
                source.handle, excerpt.role, excerpt.ordinal
            );
            assert!(markdown.contains(&citation), "missing {citation}");
            assert!(markdown.contains(&excerpt.text));
        }
    }
}

#[test]
fn two_source_pack_contains_both_handles_and_the_notice() {
    let db = open_db("two-source");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:alpha",
        "C1",
        "Codex login",
        "2026-07-01T00:00:00Z",
        &[
            ("user", "remember the codex login"),
            ("agent", "codex kept the trace"),
        ],
    );
    insert_session(
        &db,
        PROJECT,
        "grok:ns:beta",
        "G1",
        "Grok notes",
        "2026-07-02T00:00:00Z",
        &[("user", "beta-unique-phrase")],
    );
    let tokens = vec!["G1".to_string(), "c1".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    assert_pack(&pack);
    assert_eq!(
        pack.sources
            .iter()
            .map(|source| source.handle.as_str())
            .collect::<Vec<_>>(),
        ["G1", "C1"]
    );
    assert!(!pack.truncated);
    let markdown = render_markdown(&pack);
    assert!(markdown.contains(UNTRUSTED_NOTICE));
    assert!(markdown.contains("beta-unique-phrase"));
    assert!(markdown.contains("remember the codex login"));
    assert!(markdown.contains("source: G1 user 1"));
    assert!(markdown.contains("source: C1 user 1"));
    assert!(markdown.contains("source: C1 agent 2"));
    let g1 = markdown.find("## G1\n").unwrap();
    let c1 = markdown.find("## C1\n").unwrap();
    assert!(g1 < c1);

    let parsed: serde_json::Value = serde_json::from_str(render_json(&pack).trim()).unwrap();
    assert_eq!(parsed["schema_version"].as_u64(), Some(1));
    let sources = &parsed["untrusted_data_envelope"]["sources"];
    assert_eq!(sources[0]["handle"].as_str(), Some("G1"));
    assert_eq!(sources[0]["harness"].as_str(), Some("grok"));
    assert_eq!(sources[1]["handle"].as_str(), Some("C1"));
    assert_eq!(sources[1]["source_id"].as_str(), Some("codex:ns:alpha"));
    let citations = &parsed["untrusted_data_envelope"]["citations"];
    assert_eq!(citations[0]["harness"].as_str(), Some("grok"));
    assert_eq!(citations[0]["source_id"].as_str(), Some("grok:ns:beta"));
    assert_eq!(citations[0]["role"].as_str(), Some("user"));
    assert_eq!(citations[0]["ordinal"].as_u64(), Some(1));
    assert_eq!(citations[2]["role"].as_str(), Some("agent"));
    assert_eq!(citations[2]["ordinal"].as_u64(), Some(2));
    assert_eq!(
        sources[1]["excerpts"][0]["citation"]["source_id"].as_str(),
        Some("codex:ns:alpha")
    );
}

#[test]
fn ancestor_walk_follows_edges_and_respects_depth() {
    let db = open_db("ancestors");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:alpha",
        "C1",
        "Alpha",
        "2026-07-01T00:00:00Z",
        &[("user", "alpha-root")],
    );
    insert_session(
        &db,
        PROJECT,
        "codex:ns:beta",
        "C2",
        "Beta",
        "2026-07-02T00:00:00Z",
        &[("user", "beta-middle")],
    );
    insert_session(
        &db,
        PROJECT,
        "codex:ns:gamma",
        "C3",
        "Gamma",
        "2026-07-03T00:00:00Z",
        &[("user", "gamma-target")],
    );
    insert_edge(&db, PROJECT, "codex:ns:alpha", "codex:ns:beta");
    insert_edge(&db, PROJECT, "codex:ns:beta", "codex:ns:gamma");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:delta",
        "C4",
        "Delta",
        "2026-07-01T00:00:00Z",
        &[("user", "delta-left")],
    );
    insert_session(
        &db,
        PROJECT,
        "codex:ns:epsilon",
        "C5",
        "Epsilon",
        "2026-07-04T00:00:00Z",
        &[("user", "epsilon-right")],
    );
    insert_session(
        &db,
        PROJECT,
        "codex:ns:focal",
        "C6",
        "Focal",
        "2026-07-05T00:00:00Z",
        &[("user", "focal-target")],
    );
    insert_edge(&db, PROJECT, "codex:ns:delta", "codex:ns:focal");
    insert_edge(&db, PROJECT, "codex:ns:epsilon", "codex:ns:focal");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:left",
        "C7",
        "Left",
        "2026-08-01T00:00:00Z",
        &[("user", "cycle-left")],
    );
    insert_session(
        &db,
        PROJECT,
        "codex:ns:right",
        "C8",
        "Right",
        "2026-08-02T00:00:00Z",
        &[("user", "cycle-right")],
    );
    insert_edge(&db, PROJECT, "codex:ns:left", "codex:ns:right");
    insert_edge(&db, PROJECT, "codex:ns:right", "codex:ns:left");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:iota",
        "C9",
        "Iota",
        "2026-09-01T00:00:00Z",
        &[("user", "iota-alone")],
    );
    insert_edge(&db, "other-project", "codex:ns:alpha", "codex:ns:iota");

    let all = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "C3",
            depth: None,
        },
    )
    .unwrap();
    assert_pack(&all);
    assert_eq!(handles(&all), ["C1", "C2"]);
    assert!(render_markdown(&all).contains("alpha-root"));
    assert!(render_markdown(&all).contains("beta-middle"));
    assert!(!render_markdown(&all).contains("gamma-target"));

    let one = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "codex:ns:gamma",
            depth: Some(1),
        },
    )
    .unwrap();
    assert_pack(&one);
    assert_eq!(handles(&one), ["C2"]);
    assert!(render_markdown(&one).contains("beta-middle"));
    assert!(!render_markdown(&one).contains("alpha-root"));

    let two = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "C3",
            depth: Some(2),
        },
    )
    .unwrap();
    assert_eq!(handles(&two), handles(&all));

    let branch = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "C6",
            depth: Some(1),
        },
    )
    .unwrap();
    assert_pack(&branch);
    assert_eq!(handles(&branch), ["C4", "C5"]);
    assert!(!render_markdown(&branch).contains("focal-target"));

    let cycle = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "C7",
            depth: None,
        },
    )
    .unwrap();
    assert_pack(&cycle);
    assert_eq!(handles(&cycle), ["C8"]);
    assert!(!render_markdown(&cycle).contains("cycle-left"));

    let alone = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "C9",
            depth: None,
        },
    )
    .unwrap();
    assert_pack(&alone);
    assert_eq!(handles(&alone), ["C9"]);
    assert!(alone.sources[0].excerpts.is_empty());
    assert!(!render_markdown(&alone).contains("iota-alone"));
    assert!(!render_markdown(&alone).contains("source: "));
}

#[test]
fn huge_excerpt_is_truncated_with_marker() {
    let db = open_db("truncate");
    let huge = "x".repeat(20_000);
    insert_session(
        &db,
        PROJECT,
        "codex:ns:huge",
        "C1",
        "Huge",
        "2026-07-01T00:00:00Z",
        &[("user", &huge)],
    );
    let tokens = vec!["C1".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    assert_pack(&pack);
    assert!(pack.truncated);
    assert!(pack.sources[0].truncated);
    assert!(pack.sources[0].excerpts[0].truncated);
    let text = &pack.sources[0].excerpts[0].text;
    assert!(text.ends_with(MARKER));
    assert!(text.len() < huge.len());
    let markdown = render_markdown(&pack);
    assert!(markdown.contains(MARKER));
    assert!(!markdown.contains(&huge));
    let parsed: serde_json::Value = serde_json::from_str(render_json(&pack).trim()).unwrap();
    assert_eq!(parsed["schema_version"].as_u64(), Some(1));
    assert_eq!(parsed["truncated"].as_bool(), Some(true));
    assert_eq!(
        parsed["untrusted_data_envelope"]["sources"][0]["excerpts"][0]["truncated"].as_bool(),
        Some(true)
    );
}

#[test]
fn two_long_sources_receive_equal_character_budgets() {
    let db = open_db("fair");
    let long_a = "a".repeat(30_000);
    let long_b = "b".repeat(30_000);
    insert_session(
        &db,
        PROJECT,
        "codex:ns:aaa",
        "C1",
        "Alpha",
        "2026-07-01T00:00:00Z",
        &[("user", &long_a)],
    );
    insert_session(
        &db,
        PROJECT,
        "grok:ns:bbb",
        "G1",
        "Bravo",
        "2026-07-02T00:00:00Z",
        &[("user", &long_b)],
    );
    let tokens = vec!["C1".to_string(), "G1".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    assert_pack(&pack);
    assert_eq!(handles(&pack), ["C1", "G1"]);
    let left = &pack.sources[0].excerpts[0].text;
    let right = &pack.sources[1].excerpts[0].text;
    assert_eq!(left.chars().count(), right.chars().count());
    assert!(left.ends_with(MARKER));
    assert!(right.ends_with(MARKER));
    assert!(left.strip_suffix(MARKER).unwrap().chars().all(|c| c == 'a'));
    assert!(right
        .strip_suffix(MARKER)
        .unwrap()
        .chars()
        .all(|c| c == 'b'));
    assert!(render_markdown(&pack).contains(UNTRUSTED_NOTICE));
}

#[test]
fn unknown_handle_and_wrong_project_are_not_in_project() {
    let db = open_db("unknown");
    insert_session(
        &db,
        "other-project",
        "codex:ns:foreign",
        "C1",
        "Foreign",
        "2026-07-01T00:00:00Z",
        &[("user", "foreign-only")],
    );
    for token in ["C9", "codex:missing:nope", "C1", "codex:ns:foreign", ""] {
        let tokens = vec![token.to_string()];
        let error = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap_err();
        assert_eq!(error.code, "not-in-project", "{token}");
        assert!(error.message.contains("not in this project"));
    }
    let error = build_pack(
        &db,
        PROJECT,
        ContextRequest::Ancestors {
            target: "C9",
            depth: Some(1),
        },
    )
    .unwrap_err();
    assert_eq!(error.code, "not-in-project");
    let empty: [String; 0] = [];
    let error = build_pack(&db, PROJECT, ContextRequest::Sessions(&empty)).unwrap_err();
    assert_eq!(error.code, "invalid-argument");
}

#[test]
fn json_parses_and_schema_version_is_one() {
    let db = open_db("json");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:one",
        "C1",
        "One",
        "2026-07-01T00:00:00Z",
        &[("agent", "one cited turn")],
    );
    let tokens = vec!["codex:ns:one".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    assert_pack(&pack);
    let json = render_json(&pack);
    let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
    assert_eq!(parsed["schema_version"], 1);
    assert_eq!(
        parsed["untrusted_data_envelope"]["notice"].as_str(),
        Some(UNTRUSTED_NOTICE)
    );
    assert_eq!(
        parsed["untrusted_data_envelope"]["sources"][0]["excerpts"][0]["text"].as_str(),
        Some("one cited turn")
    );
}

#[test]
fn redacts_secrets_and_drops_path_titles() {
    let db = open_db("redact");
    insert_session(
        &db,
        PROJECT,
        "codex:ns:secret",
        "C1",
        LOCATOR,
        "2026-07-01T00:00:00Z",
        &[(
            "user",
            "API_KEY=supersecretvalue and see /home/someone/notes",
        )],
    );
    let tokens = vec!["C1".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    assert_pack(&pack);
    assert_eq!(pack.sources[0].title, "untitled");
    let markdown = render_markdown(&pack);
    assert!(markdown.contains("API_KEY=[REDACTED:credential]"));
    assert!(markdown.contains("see ~/notes"));
    assert!(!markdown.contains("supersecretvalue"));
    assert!(!markdown.contains("/home/someone"));
    assert!(!render_json(&pack).contains("supersecretvalue"));
    assert!(!render_json(&pack).contains("/home/someone"));
}

#[test]
fn context_rereads_a_regular_native_file() {
    let db = open_db("reread");
    let log = std::env::temp_dir().join(format!(
        "tang-context-reread-{}-{}.jsonl",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::write(
        &log,
        "{\"type\":\"response_item\",\"payload\":{\"type\":\"message\",\"role\":\"user\",\"content\":[{\"type\":\"input_text\",\"text\":\"FRESH_REREAD_CANARY\"}]}}\n",
    )
    .unwrap();
    db.execute(
        "INSERT INTO sessions(source_id, project_key, adapter, session_handle, title, updated_at, locator)
         VALUES ('codex:ns:fresh', ?1, 'codex', 'C9', 'Fresh', '2026-07-01T00:00:00Z', ?2)",
        params![PROJECT, log.display().to_string()],
    )
    .unwrap();
    db.execute(
        "INSERT INTO capsules(source_id, project_key, content_json) VALUES ('codex:ns:fresh', ?1, ?2)",
        params![PROJECT, r#"{"excerpts":[{"role":"user","text":"STALE_CAPSULE"}],"source_title":"Fresh","schema_version":1}"#],
    )
    .unwrap();
    let tokens = vec!["C9".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    let markdown = render_markdown(&pack);
    assert!(markdown.contains("FRESH_REREAD_CANARY"));
    assert!(!markdown.contains("STALE_CAPSULE"));
    assert!(!markdown.contains(&log.display().to_string()));
    let _ = std::fs::remove_file(log);
}

fn handles(pack: &ContextPack) -> Vec<&str> {
    pack.sources
        .iter()
        .map(|source| source.handle.as_str())
        .collect()
}

#[test]
fn context_rereads_only_the_selected_openclaw_session() {
    let db = open_db("openclaw");
    let agent_db = std::env::temp_dir().join(format!(
        "tang-context-openclaw-{}-{}.sqlite",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let connection = Connection::open(&agent_db).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE session_windows (
                session_id TEXT, session_key TEXT, started_at INTEGER, ended_at INTEGER
            );
            CREATE TABLE transcript_events (
                session_id TEXT, seq INTEGER, event_json TEXT
            );",
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO session_windows VALUES ('local-window', 'agent:main:local', 1, 2)",
            [],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO session_windows VALUES ('other-window', 'agent:main:other', 1, 2)",
            [],
        )
        .unwrap();
    for (session_id, seq, role, content) in [
        (
            "local-window",
            1,
            "user",
            serde_json::json!("OPENCLAW_FRESH_CANARY"),
        ),
        (
            "local-window",
            2,
            "assistant",
            serde_json::json!([
                {"type": "text", "text": "OPENCLAW_AGENT_REPLY"},
                {"type": "tool_use", "text": "OPENCLAW_TOOL_CANARY"}
            ]),
        ),
        (
            "other-window",
            1,
            "user",
            serde_json::json!("OPENCLAW_OTHER_CANARY"),
        ),
    ] {
        let event = serde_json::json!({
            "type": "message",
            "message": {"role": role, "content": content}
        });
        connection
            .execute(
                "INSERT INTO transcript_events VALUES (?1, ?2, ?3)",
                params![session_id, seq, event.to_string()],
            )
            .unwrap();
    }
    drop(connection);

    db.execute(
        "INSERT INTO sessions(source_id, project_key, adapter, session_handle, title, updated_at, locator)
         VALUES ('openclaw:ns:YWdlbnQ6bWFpbjpsb2NhbA', ?1, 'openclaw', 'W1', 'Local', '2026-07-01T00:00:00Z', ?2)",
        params![PROJECT, agent_db.display().to_string()],
    )
    .unwrap();
    db.execute(
        "INSERT INTO capsules(source_id, project_key, content_json) VALUES ('openclaw:ns:YWdlbnQ6bWFpbjpsb2NhbA', ?1, ?2)",
        params![PROJECT, r#"{"excerpts":[{"role":"user","text":"OPENCLAW_STALE_CAPSULE"}],"source_title":"Local","schema_version":1}"#],
    )
    .unwrap();

    let tokens = vec!["W1".to_string()];
    let pack = build_pack(&db, PROJECT, ContextRequest::Sessions(&tokens)).unwrap();
    let markdown = render_markdown(&pack);
    assert!(markdown.contains("OPENCLAW_FRESH_CANARY"));
    assert!(markdown.contains("OPENCLAW_AGENT_REPLY"));
    assert!(!markdown.contains("OPENCLAW_OTHER_CANARY"));
    assert!(!markdown.contains("OPENCLAW_TOOL_CANARY"));
    assert!(!markdown.contains("OPENCLAW_STALE_CAPSULE"));
    assert!(!markdown.contains(&agent_db.display().to_string()));
    let _ = std::fs::remove_file(agent_db);
}
