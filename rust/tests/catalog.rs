use rusqlite::Connection;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tang::catalog::{add_label, open_catalog, recall, sync_project, RecallQuery};
use tang::cli::run_with;
use tang::project::resolve_project;

fn scratch() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("tang-rust-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn project_db(root: &Path) -> (tang::project::ProjectIdentity, Connection) {
    fs::create_dir_all(root).unwrap();
    let project = resolve_project(root).unwrap();
    if let Some(parent) = project.database_path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    let connection = Connection::open(&project.database_path).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                adapter TEXT NOT NULL,
                session_handle TEXT,
                title TEXT,
                health TEXT NOT NULL,
                native_available INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE capsules (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                content_json TEXT NOT NULL,
                search_text TEXT NOT NULL
            );",
        )
        .unwrap();
    (project, connection)
}

#[allow(clippy::too_many_arguments)]
fn insert(
    connection: &Connection,
    project_key: &str,
    source_id: &str,
    adapter: &str,
    handle: &str,
    title: &str,
    search_text: &str,
    native_available: i64,
) {
    let content = format!(r#"{{"display_name":"{title}","schema_version":1}}"#);
    connection
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, session_handle, title, health,
                native_available, started_at, updated_at
             ) VALUES (?1, ?2, ?3, ?4, ?5, 'complete', ?6, '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
            rusqlite::params![source_id, project_key, adapter, handle, title, native_available],
        )
        .unwrap();
    connection
        .execute(
            "INSERT INTO capsules(source_id, project_key, content_json, search_text)
             VALUES (?1, ?2, ?3, ?4)",
            rusqlite::params![source_id, project_key, content, search_text],
        )
        .unwrap();
}

#[test]
fn sync_and_recall_span_projects_and_redact_secrets() {
    let root = scratch();
    let (alpha, alpha_db) = project_db(&root.join("alpha"));
    let (beta, beta_db) = project_db(&root.join("beta"));
    insert(
        &alpha_db,
        &alpha.key,
        "codex:fixture:books",
        "codex",
        "C1",
        "Reading list",
        "five books to bring API_KEY=supersecretvalue",
        1,
    );
    insert(
        &beta_db,
        &beta.key,
        "grok:fixture:zebra",
        "grok",
        "G1",
        "Zebra notes",
        "beta zebra phrase",
        1,
    );
    let catalog_path = root.join("catalog.db");
    let mut catalog = open_catalog(&catalog_path).unwrap();
    sync_project(
        &mut catalog,
        &alpha_db,
        &alpha.key,
        &alpha.display_name,
        &alpha.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    sync_project(
        &mut catalog,
        &beta_db,
        &beta.key,
        &beta.display_name,
        &beta.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    let stored: (String, String, String) = catalog
        .query_row(
            "SELECT body_text, category, summary FROM catalog_sessions WHERE source_id = 'codex:fixture:books'",
            [],
            |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
        )
        .unwrap();
    assert_eq!(
        stored.0,
        "five books to bring API_KEY=[REDACTED:credential]"
    );
    assert_eq!(stored.1, "other");
    assert!(stored.2.starts_with("[other] Reading list"));
    assert!(tang::cli::catalog_file_is_private(&catalog_path));
    let hits = recall(&catalog, &ask("book")).unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].catalog_handle, "C1");
    assert_eq!(hits[0].project_display, "alpha");
    assert!(hits[0].snippet.as_deref().unwrap_or("").contains("book"));
    let zebra = recall(&catalog, &ask("zebra")).unwrap();
    assert_eq!(zebra[0].harness, "grok");
    assert_eq!(zebra[0].project_display, "beta");
    assert!(recall(&catalog, &ask("supersecretvalue"))
        .unwrap()
        .is_empty());
}

fn ask(text: &str) -> RecallQuery<'_> {
    RecallQuery {
        text: Some(text),
        label: None,
        category: None,
        harness: None,
        limit: 20,
        include_unavailable: false,
    }
}

#[test]
fn handles_are_not_reused_and_unavailable_sessions_stay_hidden() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    insert(
        &database,
        &project.key,
        "codex:fixture:secret",
        "codex",
        "C1",
        "Token note",
        "first session",
        1,
    );
    insert(
        &database,
        &project.key,
        "cursor:fixture:gone",
        "cursor",
        "R1",
        "Gone",
        "recover the missing transcript",
        0,
    );
    let mut catalog = open_catalog(&root.join("catalog.db")).unwrap();
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    assert!(recall(&catalog, &ask("transcript")).unwrap().is_empty());
    let mut hidden = ask("transcript");
    hidden.include_unavailable = true;
    assert_eq!(recall(&catalog, &hidden).unwrap()[0].catalog_handle, "R1");
    database
        .execute(
            "DELETE FROM capsules WHERE source_id = 'codex:fixture:secret'",
            [],
        )
        .unwrap();
    database
        .execute(
            "DELETE FROM sessions WHERE source_id = 'codex:fixture:secret'",
            [],
        )
        .unwrap();
    let removed = sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    assert_eq!(removed.removed, 1);
    insert(
        &database,
        &project.key,
        "codex:fixture:next",
        "codex",
        "C1",
        "Next",
        "a later session",
        1,
    );
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    let handle: String = catalog
        .query_row(
            "SELECT catalog_handle FROM catalog_sessions WHERE source_id = 'codex:fixture:next'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(handle, "C2");
}

#[test]
fn sync_refuses_a_foreign_project_database() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    insert(
        &database,
        "directory:sha256:other",
        "codex:fixture:other",
        "codex",
        "C1",
        "Other",
        "other project",
        1,
    );
    let mut catalog = open_catalog(&root.join("catalog.db")).unwrap();
    let error = sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap_err();
    assert_eq!(error.code, "project-mismatch");
}

#[test]
fn cli_recall_is_global_and_does_not_create_a_missing_catalog() {
    let root = scratch();
    let missing = root.join("absent.db");
    let mut output = Vec::new();
    let error = run_with(
        &[
            "recall".into(),
            "book".into(),
            "--catalog".into(),
            missing.display().to_string(),
        ],
        &mut output,
    )
    .unwrap_err();
    assert_eq!(error.code, "catalog-missing");
    assert!(!missing.exists());

    let (alpha, alpha_db) = project_db(&root.join("alpha"));
    let (beta, beta_db) = project_db(&root.join("beta"));
    insert(
        &alpha_db,
        &alpha.key,
        "codex:fixture:alpha",
        "codex",
        "C1",
        "Alpha",
        "alpha only phrase",
        1,
    );
    insert(
        &beta_db,
        &beta.key,
        "grok:fixture:beta",
        "grok",
        "G1",
        "Beta",
        "beta zebra phrase",
        1,
    );
    drop(alpha_db);
    drop(beta_db);
    let catalog = root.join("catalog.db");
    let mut stdout = Vec::new();
    run_with(
        &[
            "catalog".into(),
            "sync".into(),
            "--cwd".into(),
            root.join("alpha").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    run_with(
        &[
            "catalog".into(),
            "sync".into(),
            "--cwd".into(),
            root.join("beta").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    stdout.clear();
    run_with(
        &[
            "recall".into(),
            "zebra".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["schema_version"], 1);
    assert_eq!(document["result_count"], 1);
    assert_eq!(document["results"][0]["catalog_handle"], "G1");
    assert_eq!(document["results"][0]["project_display"], "beta");
    assert!(document["results"][0].get("database_path").is_none());
    assert!(document["results"][0]["summary"]
        .as_str()
        .unwrap()
        .starts_with("[other] Beta"));
}

#[test]
fn labels_filter_recall_and_survive_sync() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    let content = r#"{"display_name":"Auth crash","excerpts":[{"role":"user","text":"the login crash leaves no answer"},{"role":"agent","text":"check the token before the request"}],"schema_version":1}"#;
    database
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, session_handle, title, health,
                native_available, started_at, updated_at
             ) VALUES ('codex:fixture:auth', ?1, 'codex', 'C1', 'Auth crash', 'complete', 1,
                       '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
            [&project.key],
        )
        .unwrap();
    database
        .execute(
            "INSERT INTO capsules(source_id, project_key, content_json, search_text)
             VALUES ('codex:fixture:auth', ?1, ?2, 'the login crash leaves no answer')",
            rusqlite::params![project.key, content],
        )
        .unwrap();
    let catalog_path = root.join("catalog.db");
    let mut catalog = open_catalog(&catalog_path).unwrap();
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    assert_eq!(
        add_label(&mut catalog, "c1", "Auth", "2026-11-09T21:00:00Z").unwrap(),
        "C1"
    );
    let hits = recall(
        &catalog,
        &RecallQuery {
            text: None,
            label: Some("auth"),
            category: None,
            harness: None,
            limit: 20,
            include_unavailable: false,
        },
    )
    .unwrap();
    assert_eq!(hits[0].category, "bug");
    assert_eq!(hits[0].labels, vec!["auth".to_string()]);
    assert!(hits[0].summary.starts_with("[bug] Auth crash"));
    assert!(hits[0].summary.contains("login crash"));
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    let again = recall(
        &catalog,
        &RecallQuery {
            text: None,
            label: Some("auth"),
            category: None,
            harness: None,
            limit: 20,
            include_unavailable: false,
        },
    )
    .unwrap();
    assert_eq!(again[0].labels, vec!["auth".to_string()]);
    let error = add_label(&mut catalog, "C1", "bad label", "2026-11-09T21:00:00Z").unwrap_err();
    assert_eq!(error.code, "invalid-label");
    for index in 0..7 {
        add_label(
            &mut catalog,
            "C1",
            &format!("extra{index}"),
            "2026-11-09T21:00:00Z",
        )
        .unwrap();
    }
    let error = add_label(&mut catalog, "C1", "overflow", "2026-11-09T21:00:00Z").unwrap_err();
    assert_eq!(error.code, "label-limit");
}

#[test]
fn capsule_source_title_wins_over_the_derived_display_name() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    database
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, session_handle, title, health,
                native_available, started_at, updated_at
             ) VALUES ('codex:fixture:title', ?1, 'codex', 'C1', NULL, 'complete', 1,
                       '2026-11-01T00:00:00Z', '2026-11-01T00:00:00Z')",
            [&project.key],
        )
        .unwrap();
    let content = r#"{"source_title":"Native title API_KEY=supersecretvalue","display_name":"Derived label","schema_version":1}"#;
    database
        .execute(
            "INSERT INTO capsules(source_id, project_key, content_json, search_text)
             VALUES ('codex:fixture:title', ?1, ?2, 'native title body')",
            rusqlite::params![project.key, content],
        )
        .unwrap();
    let mut catalog = open_catalog(&root.join("catalog.db")).unwrap();
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    let hits = recall(&catalog, &ask("Native")).unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(
        hits[0].title.as_deref(),
        Some("Native title API_KEY=[REDACTED:credential]")
    );
    assert!(recall(&catalog, &ask("Derived")).unwrap().is_empty());
}

#[test]
fn empty_project_database_does_not_wipe_catalog_rows() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    insert(
        &database,
        &project.key,
        "codex:fixture:keep",
        "codex",
        "C1",
        "Keep me",
        "keep this capsule",
        1,
    );
    let mut catalog = open_catalog(&root.join("catalog.db")).unwrap();
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    drop(database);
    let empty_path = root.join("empty.db");
    let empty = Connection::open(&empty_path).unwrap();
    empty
        .execute_batch(
            "CREATE TABLE sessions (project_key TEXT);
             CREATE TABLE capsules (project_key TEXT);",
        )
        .unwrap();
    let result = sync_project(
        &mut catalog,
        &empty,
        &project.key,
        &project.display_name,
        &empty_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    assert_eq!(result.removed, 0);
    assert_eq!(result.warnings.len(), 1);
    let hits = recall(&catalog, &ask("keep")).unwrap();
    assert_eq!(hits.len(), 1);
}

#[test]
fn category_and_harness_filters_are_normalized() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    insert(
        &database,
        &project.key,
        "codex:fixture:crash",
        "codex",
        "C1",
        "Crash report",
        "the indexer crash",
        1,
    );
    insert(
        &database,
        &project.key,
        "grok:fixture:choice",
        "grok",
        "G1",
        "Choice",
        "we decided to keep sqlite",
        1,
    );
    let mut catalog = open_catalog(&root.join("catalog.db")).unwrap();
    sync_project(
        &mut catalog,
        &database,
        &project.key,
        &project.display_name,
        &project.database_path,
        "2026-11-09T21:00:00Z",
    )
    .unwrap();
    let bugs = recall(
        &catalog,
        &RecallQuery {
            text: None,
            label: None,
            category: Some("BUG"),
            harness: None,
            limit: 20,
            include_unavailable: false,
        },
    )
    .unwrap();
    assert_eq!(bugs.len(), 1);
    assert_eq!(bugs[0].category, "bug");
    let codex = recall(
        &catalog,
        &RecallQuery {
            text: None,
            label: None,
            category: None,
            harness: Some("Codex"),
            limit: 20,
            include_unavailable: false,
        },
    )
    .unwrap();
    assert_eq!(codex.len(), 1);
    assert_eq!(codex[0].harness, "codex");
    let error = recall(
        &catalog,
        &RecallQuery {
            text: None,
            label: None,
            category: Some("nonsense"),
            harness: None,
            limit: 20,
            include_unavailable: false,
        },
    )
    .unwrap_err();
    assert_eq!(error.code, "invalid-category");
}
fn continuation_table(connection: &Connection) {
    connection
        .execute_batch(
            "CREATE TABLE continuation_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                project_key TEXT NOT NULL,
                confirmation_mode TEXT NOT NULL,
                confirmed_at TEXT NOT NULL,
                schema_version INTEGER NOT NULL DEFAULT 1,
                PRIMARY KEY(source_id, target_id)
            );",
        )
        .unwrap();
}

#[test]
fn join_links_one_project_and_refuses_a_cycle_or_another_project() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    continuation_table(&database);
    insert(
        &database,
        &project.key,
        "codex:fixture:aaa",
        "codex",
        "C1",
        "Source",
        "source session",
        1,
    );
    insert(
        &database,
        &project.key,
        "codex:fixture:bbb",
        "codex",
        "C2",
        "Target",
        "target session",
        1,
    );
    let catalog = root.join("catalog.db");
    let mut stdout = Vec::new();
    run_with(
        &[
            "catalog".into(),
            "sync".into(),
            "--cwd".into(),
            root.join("work").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap();
    stdout.clear();
    run_with(
        &[
            "join".into(),
            "--from".into(),
            "C1".into(),
            "--into".into(),
            "C2".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["schema_version"], 1);
    assert_eq!(document["inserted"], 1);
    assert_eq!(document["source_handles"][0], "C1");
    assert_eq!(document["target_handle"], "C2");
    stdout.clear();
    run_with(
        &[
            "join".into(),
            "--from".into(),
            "C1".into(),
            "--into".into(),
            "C2".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    assert_eq!(
        serde_json::from_slice::<serde_json::Value>(&stdout).unwrap()["existing"],
        1
    );
    let error = run_with(
        &[
            "join".into(),
            "--from".into(),
            "C2".into(),
            "--into".into(),
            "C1".into(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap_err();
    assert_eq!(error.code, "cycle");
    let error = run_with(
        &[
            "join".into(),
            "--from".into(),
            "C1".into(),
            "--into".into(),
            "C1".into(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap_err();
    assert_eq!(error.code, "self-link");

    let (other, other_db) = project_db(&root.join("other"));
    continuation_table(&other_db);
    insert(
        &other_db,
        &other.key,
        "grok:fixture:beta",
        "grok",
        "G1",
        "Beta",
        "beta session",
        1,
    );
    drop(other_db);
    run_with(
        &[
            "catalog".into(),
            "sync".into(),
            "--cwd".into(),
            root.join("other").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap();
    let error = run_with(
        &[
            "join".into(),
            "--from".into(),
            "C1".into(),
            "--into".into(),
            "G1".into(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap_err();
    assert_eq!(error.code, "cross-project");
    let saved = Connection::open(other.database_path).unwrap();
    let count: i64 = saved
        .query_row("SELECT COUNT(*) FROM continuation_edges", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(count, 0);

    stdout.clear();
    run_with(
        &[
            "purge".into(),
            "--all".into(),
            "--yes".into(),
            "--cwd".into(),
            root.join("work").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap();
    let text = String::from_utf8(stdout).unwrap();
    assert!(text.contains("Removed 2 global catalog rows"));
    let saved = Connection::open(&catalog).unwrap();
    let remaining: i64 = saved
        .query_row(
            "SELECT COUNT(*) FROM catalog_sessions WHERE project_key = ?1",
            [project.key],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(remaining, 0);
    let kept: i64 = saved
        .query_row(
            "SELECT COUNT(*) FROM catalog_sessions WHERE project_key = ?1",
            [other.key],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(kept, 1);
}
#[test]
fn join_accepts_multiple_sources_in_one_command() {
    let root = scratch();
    let (project, database) = project_db(&root.join("work"));
    continuation_table(&database);
    for (source_id, handle) in [
        ("codex:fixture:aaa", "C1"),
        ("codex:fixture:bbb", "C2"),
        ("codex:fixture:ccc", "C3"),
    ] {
        insert(
            &database,
            &project.key,
            source_id,
            "codex",
            handle,
            handle,
            "session body",
            1,
        );
    }
    drop(database);
    let catalog = root.join("catalog.db");
    let mut stdout = Vec::new();
    run_with(
        &[
            "catalog".into(),
            "sync".into(),
            "--cwd".into(),
            root.join("work").display().to_string(),
            "--catalog".into(),
            catalog.display().to_string(),
        ],
        &mut stdout,
    )
    .unwrap();
    stdout.clear();
    run_with(
        &[
            "join".into(),
            "--from".into(),
            "C1".into(),
            "--from".into(),
            "C2".into(),
            "--into".into(),
            "C3".into(),
            "--catalog".into(),
            catalog.display().to_string(),
            "--json".into(),
        ],
        &mut stdout,
    )
    .unwrap();
    let document: serde_json::Value = serde_json::from_slice(&stdout).unwrap();
    assert_eq!(document["inserted"], 2);
    assert_eq!(document["source_handles"].as_array().unwrap().len(), 2);
    let saved = Connection::open(project.database_path).unwrap();
    let count: i64 = saved
        .query_row("SELECT COUNT(*) FROM continuation_edges", [], |row| {
            row.get(0)
        })
        .unwrap();
    assert_eq!(count, 2);
}
