use rusqlite::Connection;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tang::catalog::{open_catalog, recall, sync_project};
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
    let stored: String = catalog
        .query_row(
            "SELECT search_text FROM catalog_sessions WHERE source_id = 'codex:fixture:books'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(stored, "five books to bring API_KEY=[REDACTED:credential]");
    assert!(tang::cli::catalog_file_is_private(&catalog_path));
    let hits = recall(&catalog, "book", None, 20, false).unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].catalog_handle, "C1");
    assert_eq!(hits[0].project_display, "alpha");
    assert!(hits[0].snippet.as_deref().unwrap_or("").contains("book"));
    let zebra = recall(&catalog, "zebra", None, 20, false).unwrap();
    assert_eq!(zebra[0].harness, "grok");
    assert_eq!(zebra[0].project_display, "beta");
    assert!(recall(&catalog, "supersecretvalue", None, 20, false)
        .unwrap()
        .is_empty());
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
    assert!(recall(&catalog, "transcript", None, 20, false)
        .unwrap()
        .is_empty());
    assert_eq!(
        recall(&catalog, "transcript", None, 20, true).unwrap()[0].catalog_handle,
        "R1"
    );
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
    let hits = recall(&catalog, "Native", None, 20, false).unwrap();
    assert_eq!(hits.len(), 1);
    assert_eq!(
        hits[0].title.as_deref(),
        Some("Native title API_KEY=[REDACTED:credential]")
    );
    assert!(recall(&catalog, "Derived", None, 20, false)
        .unwrap()
        .is_empty());
}
