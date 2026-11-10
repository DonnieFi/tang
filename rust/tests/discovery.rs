use std::collections::HashSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;
use tang::cards::{render_brief, render_cards};
use tang::discovery::{browse, search_project, DiscoveryQuery, DiscoveryRow};
use tang::index_store::{
    ensure_project_search, finish_session, open_project_database, write_sessions, SavedSession,
    SessionDraft,
};
use tang::titles::{clear_title, set_title};

const PROJECT: &str = "project-a";
const SECRET: &str = "supersecretvalue";

fn scratch(name: &str) -> PathBuf {
    static NEXT: AtomicU64 = AtomicU64::new(0);
    let n = NEXT.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let dir = std::env::temp_dir().join(format!(
        "tang-discovery-{name}-{}-{nanos}-{n}",
        std::process::id()
    ));
    assert!(
        dir.starts_with(std::env::temp_dir()),
        "tests must stay in the temp directory"
    );
    assert!(!dir.starts_with("/agent/repos/tang"));
    fs::create_dir_all(&dir).unwrap();
    dir.join("tang.db")
}

fn saved(
    adapter: &str,
    native_id: &str,
    updated_at: &str,
    health: &str,
    title: &str,
    turns: &[(&str, &str)],
) -> SavedSession {
    finish_session(SessionDraft {
        adapter,
        namespace: "local",
        native_id,
        locator: native_id,
        fingerprint: native_id,
        project_hint: "project",
        started_at: updated_at,
        updated_at,
        health,
        title: Some(title.to_string()),
        turns: turns
            .iter()
            .map(|(role, text)| ((*role).to_string(), (*text).to_string()))
            .collect(),
    })
    .unwrap_or_else(|error| panic!("finish session: {error}"))
}

fn index(path: &Path, adapter: &str, prefix: &str, sessions: &[SavedSession]) {
    let protected = HashSet::new();
    write_sessions(
        path, PROJECT, adapter, "local", prefix, sessions, &protected,
    )
    .unwrap_or_else(|error| panic!("write sessions: {} {}", error.code, error.message));
}

fn ask<'a>(
    text: Option<&'a str>,
    harness: Option<&'a str>,
    include_unavailable: bool,
    limit: i64,
) -> DiscoveryQuery<'a> {
    DiscoveryQuery {
        text,
        harness,
        include_unavailable,
        limit,
    }
}

fn ids(rows: &[DiscoveryRow]) -> Vec<&str> {
    rows.iter().map(|row| row.source_id.as_str()).collect()
}

fn project_fixture(name: &str) -> (PathBuf, Connection) {
    let path = scratch(name);
    let secret_turn = format!("API_KEY={SECRET}");
    let grok = vec![
        saved(
            "grok",
            "b",
            "2026-01-02T00:00:00Z",
            "unknown",
            "Middle beta",
            &[("user", "beta notes")],
        ),
        saved(
            "grok",
            "a",
            "2026-01-03T00:00:00Z",
            "complete",
            "Newest alpha",
            &[("user", "lighthouse plan"), ("user", secret_turn.as_str())],
        ),
        saved(
            "grok",
            "c",
            "2026-01-02T00:00:00Z",
            "complete",
            "Middle gamma",
            &[("user", "gamma notes")],
        ),
    ];
    index(&path, "grok", "G", &grok);
    index(
        &path,
        "Codex",
        "C",
        &[saved(
            "Codex",
            "z",
            "2026-01-04T00:00:00Z",
            "complete",
            "Codex marigold",
            &[("user", "marigold petals")],
        )],
    );
    let db = Connection::open(&path).unwrap();
    db.execute(
        "UPDATE sessions SET native_available = 0 WHERE source_id = 'grok:local:c'",
        [],
    )
    .unwrap();
    (path, db)
}

#[test]
fn browse_orders_filters_and_hides_unavailable() {
    let (_path, db) = project_fixture("browse");
    let rows = browse(&db, PROJECT, &ask(Some("ignored"), None, false, 20)).unwrap();
    assert_eq!(
        ids(&rows),
        ["Codex:local:z", "grok:local:a", "grok:local:b",]
    );
    assert_eq!(
        rows.iter()
            .map(|row| row.handle.as_str())
            .collect::<Vec<_>>(),
        ["C1", "G2", "G1"]
    );
    assert_eq!(rows[1].title, "Newest alpha");
    assert_eq!(rows[1].health, "complete");
    assert_eq!(rows[1].snippet.as_deref(), Some("lighthouse plan"));
    assert!(!rows[1].snippet.as_deref().unwrap().contains(SECRET));

    let grok = browse(&db, PROJECT, &ask(None, Some("GROK"), false, 20)).unwrap();
    assert_eq!(ids(&grok), ["grok:local:a", "grok:local:b"]);

    let hidden = browse(&db, PROJECT, &ask(None, None, true, 20)).unwrap();
    assert_eq!(
        ids(&hidden),
        [
            "Codex:local:z",
            "grok:local:a",
            "grok:local:b",
            "grok:local:c",
        ]
    );
    assert!(!hidden
        .iter()
        .any(|row| row.source_id.ends_with(":c") && row.native_available));

    let newest = browse(&db, PROJECT, &ask(None, None, false, 1)).unwrap();
    assert_eq!(ids(&newest), ["Codex:local:z"]);
}

#[test]
fn search_finds_visible_words_and_skips_redacted_secrets() {
    let (path, db) = project_fixture("search");
    let definition: String = db
        .query_row(
            "SELECT sql FROM sqlite_master WHERE name = 'capsules_fts'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    let normalized = definition.to_ascii_lowercase();
    assert!(normalized.contains("porter"), "{definition}");
    assert!(normalized.contains("unicode61"), "{definition}");
    assert!(normalized.contains("unindexed"), "{definition}");

    let indexed: String = db
        .query_row(
            "SELECT search_text FROM capsules WHERE source_id = 'grok:local:a'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert!(indexed.contains("lighthouse"));
    assert!(indexed.contains("[REDACTED:credential]"));
    assert!(!indexed.contains(SECRET));

    let found = search_project(&db, PROJECT, &ask(Some("lighthouse"), None, false, 20)).unwrap();
    assert_eq!(ids(&found), ["grok:local:a"]);
    let snippet = found[0].snippet.as_deref().unwrap();
    assert!(snippet.to_ascii_lowercase().contains("lighthouse"));
    assert!(!snippet.contains(SECRET));

    let secret = search_project(&db, PROJECT, &ask(Some(SECRET), None, false, 20)).unwrap();
    assert!(secret.is_empty());

    let wrong_harness = search_project(
        &db,
        PROJECT,
        &ask(Some("marigold"), Some("grok"), false, 20),
    )
    .unwrap();
    assert!(wrong_harness.is_empty());
    let codex = search_project(
        &db,
        PROJECT,
        &ask(Some("marigold"), Some("CODEX"), false, 20),
    )
    .unwrap();
    assert_eq!(ids(&codex), ["Codex:local:z"]);

    db.execute(
        "UPDATE sessions SET native_available = 0 WHERE source_id = 'Codex:local:z'",
        [],
    )
    .unwrap();
    let hidden = search_project(&db, PROJECT, &ask(Some("marigold"), None, false, 20)).unwrap();
    assert!(hidden.is_empty());
    let shown = search_project(&db, PROJECT, &ask(Some("marigold"), None, true, 20)).unwrap();
    assert_eq!(ids(&shown), ["Codex:local:z"]);

    drop(db);
    let removed =
        write_sessions(&path, PROJECT, "grok", "local", "G", &[], &HashSet::new()).unwrap();
    assert_eq!(removed.deleted, 3);
    let db = Connection::open(&path).unwrap();
    let gone = search_project(&db, PROJECT, &ask(Some("lighthouse"), None, true, 20)).unwrap();
    assert!(gone.is_empty());
    let leftover: i64 = db
        .query_row(
            "SELECT COUNT(*) FROM capsules_fts WHERE source_id = 'grok:local:a'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(leftover, 0);
    let still = search_project(&db, PROJECT, &ask(Some("marigold"), None, true, 20)).unwrap();
    assert_eq!(ids(&still), ["Codex:local:z"]);
}

#[test]
fn ensure_project_search_rebuilds_inserted_capsules() {
    let path = scratch("manual");
    let db = open_project_database(&path).unwrap();
    let content = r#"{"display_name":"Orchid note","excerpts":[{"role":"user","text":"orchid bloom"}],"harness":"grok","schema_version":1,"source_title":"Orchid note"}"#;
    let search_text = "orchid bloom API_KEY=[REDACTED:credential]";
    assert!(!search_text.contains(SECRET));
    db.execute(
        "INSERT INTO sessions(
            source_id, project_key, adapter, source_namespace, native_id, locator,
            fingerprint_algorithm, fingerprint_value, project_hint, started_at,
            updated_at, health, indexed_at, native_available, session_handle, title
         ) VALUES (
            'grok:local:manual', ?1, 'grok', 'local', 'manual', 'loc',
            'sha256', 'fp', 'hint', '2026-04-01T00:00:00Z',
            '2026-04-01T00:00:00Z', 'complete', '2026-04-01T00:00:00Z', 1, 'G1',
            'Orchid note'
         )",
        [PROJECT],
    )
    .unwrap();
    db.execute(
        "INSERT INTO capsules(
            source_id, project_key, schema_version, content_json, search_text,
            byte_count, updated_at
         ) VALUES ('grok:local:manual', ?1, 1, ?2, ?3, ?4, '2026-04-01T00:00:00Z')",
        rusqlite::params![PROJECT, content, search_text, content.len() as i64],
    )
    .unwrap();
    let before = search_project(&db, PROJECT, &ask(Some("orchid"), None, false, 20)).unwrap();
    assert!(before.is_empty());
    ensure_project_search(&db).unwrap();
    ensure_project_search(&db).unwrap();
    let found = search_project(&db, PROJECT, &ask(Some("orchid"), None, false, 20)).unwrap();
    assert_eq!(found.len(), 1);
    assert_eq!(found[0].title, "Orchid note");
    assert_eq!(found[0].handle, "G1");
    let secret = search_project(&db, PROJECT, &ask(Some(SECRET), None, false, 20)).unwrap();
    assert!(secret.is_empty());
    let indexed: i64 = db
        .query_row("SELECT COUNT(*) FROM capsules_fts", [], |row| row.get(0))
        .unwrap();
    assert_eq!(indexed, 1);
}

#[test]
fn custom_title_survives_reindex_and_clear_restores_it() {
    let path = scratch("titles");
    let source_id = "grok:local:a";
    index(
        &path,
        "grok",
        "G",
        &[saved(
            "grok",
            "a",
            "2026-01-03T00:00:00Z",
            "complete",
            "Derived lighthouse",
            &[("user", "lighthouse plan")],
        )],
    );
    let mut db = Connection::open(&path).unwrap();
    let handle = set_title(&mut db, PROJECT, "g1", "Custom beacon").unwrap();
    assert_eq!(handle, "G1");
    assert_eq!(
        set_title(&mut db, PROJECT, source_id, "Custom beacon").unwrap(),
        "G1"
    );
    let browsed = browse(&db, PROJECT, &ask(None, None, false, 20)).unwrap();
    assert_eq!(browsed[0].title, "Custom beacon");
    let stored: String = db
        .query_row(
            "SELECT title FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(stored, "Custom beacon");
    let previous: String = db
        .query_row(
            "SELECT previous_title FROM session_overrides WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(previous, "Derived lighthouse");
    drop(db);

    index(
        &path,
        "grok",
        "G",
        &[saved(
            "grok",
            "a",
            "2026-02-02T00:00:00Z",
            "complete",
            "Replacement derived",
            &[("user", "lighthouse plan")],
        )],
    );
    let mut db = Connection::open(&path).unwrap();
    let updated: String = db
        .query_row(
            "SELECT updated_at FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(updated, "2026-02-02T00:00:00Z");
    let kept: String = db
        .query_row(
            "SELECT title FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(kept, "Custom beacon");
    let override_title: String = db
        .query_row(
            "SELECT custom_title FROM session_overrides WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(override_title, "Custom beacon");
    let hits = search_project(&db, PROJECT, &ask(Some("lighthouse"), None, false, 20)).unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].title, "Custom beacon");

    assert_eq!(clear_title(&mut db, PROJECT, source_id).unwrap(), "G1");
    let overrides: i64 = db
        .query_row("SELECT COUNT(*) FROM session_overrides", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(overrides, 0);
    let restored: String = db
        .query_row(
            "SELECT title FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(restored, "Derived lighthouse");
    let browsed = browse(&db, PROJECT, &ask(None, None, false, 20)).unwrap();
    assert_eq!(browsed[0].title, "Derived lighthouse");
    assert!(!browsed[0].title.contains("Custom"));
    assert_eq!(clear_title(&mut db, PROJECT, "g1").unwrap(), "G1");
    let still: String = db
        .query_row(
            "SELECT title FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(still, "Derived lighthouse");

    let missing = set_title(&mut db, PROJECT, "Z9", "Hello").unwrap_err();
    assert_eq!(missing.code, "not-in-project");
    let other = clear_title(&mut db, "other-project", "g1").unwrap_err();
    assert_eq!(other.code, "not-in-project");
    let empty = set_title(&mut db, PROJECT, "g1", "   ").unwrap_err();
    assert_eq!(empty.code, "invalid-title");

    let redacted = set_title(&mut db, PROJECT, "g1", &format!("PASSWORD={SECRET}")).unwrap();
    assert_eq!(redacted, "G1");
    let custom: String = db
        .query_row(
            "SELECT custom_title FROM session_overrides WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(custom, "PASSWORD=[REDACTED:credential]");
    assert!(!custom.contains(SECRET));
    let shown = browse(&db, PROJECT, &ask(None, None, false, 20)).unwrap();
    assert_eq!(shown[0].title, "PASSWORD=[REDACTED:credential]");
    clear_title(&mut db, PROJECT, "g1").unwrap();
    let back: String = db
        .query_row(
            "SELECT title FROM sessions WHERE source_id = ?1",
            [source_id],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(back, "Derived lighthouse");
}

#[test]
fn invalid_limit_and_empty_query_are_rejected() {
    let path = scratch("limits");
    let db = Connection::open(&path).unwrap();
    for limit in [0, -1, 101] {
        let browse_error = browse(&db, PROJECT, &ask(None, None, false, limit)).unwrap_err();
        assert_eq!(browse_error.code, "invalid-limit");
        let search_error =
            search_project(&db, PROJECT, &ask(Some("lighthouse"), None, false, limit)).unwrap_err();
        assert_eq!(search_error.code, "invalid-limit");
    }
    for text in [None, Some(""), Some("   "), Some("\n\t")] {
        let error = search_project(&db, PROJECT, &ask(text, None, false, 20)).unwrap_err();
        assert_eq!(error.code, "empty-query");
    }
    let accepted = browse(&db, PROJECT, &ask(None, None, false, 100));
    assert!(accepted.is_err());
    assert_ne!(accepted.unwrap_err().code, "invalid-limit");
}

#[test]
fn cards_are_plain_deterministic_text() {
    let first = DiscoveryRow {
        source_id: "grok:local:a".into(),
        handle: "G1".into(),
        harness: "grok".into(),
        title: "Custom beacon".into(),
        health: "complete".into(),
        updated_at: "2026-01-03T00:00:00Z".into(),
        native_available: true,
        snippet: None,
    };
    let second = DiscoveryRow {
        source_id: "Codex:local:z".into(),
        handle: "C1".into(),
        harness: "Codex".into(),
        title: "line one\nline two".into(),
        health: "unknown".into(),
        updated_at: "2026-01-04T00:00:00Z".into(),
        native_available: true,
        snippet: Some("hidden".into()),
    };
    assert_eq!(render_brief(&[]), "No indexed sessions.\n");
    assert_eq!(render_cards(&[]), "No indexed sessions.\n");
    assert_eq!(
        render_brief(&[first.clone(), second.clone()]),
        "G1 grok complete Custom beacon\nC1 Codex unknown line one line two\n"
    );
    assert_eq!(
        render_cards(&[first.clone(), second.clone()]),
        "\
HANDLE G1
harness grok
health complete
updated_at 2026-01-03T00:00:00Z
title Custom beacon

HANDLE C1
harness Codex
health unknown
updated_at 2026-01-04T00:00:00Z
title line one line two
"
    );
    assert_eq!(render_cards(&[first.clone()]), render_cards(&[first]));
}
