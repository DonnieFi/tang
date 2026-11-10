//! Project search, context, map, resume plan, doctor, and purge.

use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

use rusqlite::Connection;
use serde_json::Value;
use tang::cli::run_with;

fn scratch() -> PathBuf {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    let path = std::env::temp_dir().join(format!("tang-surface-{}-{nanos}", std::process::id()));
    fs::create_dir_all(&path).unwrap();
    path
}

fn seed(root: &std::path::Path) -> (PathBuf, PathBuf) {
    let project = root.join("work");
    fs::create_dir_all(&project).unwrap();
    let identity = tang::project::resolve_project(&project).unwrap();
    if let Some(parent) = identity.database_path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    let db = Connection::open(&identity.database_path).unwrap();
    db.execute_batch(
        "CREATE TABLE sessions (
            source_id TEXT PRIMARY KEY, project_key TEXT NOT NULL, adapter TEXT NOT NULL,
            source_namespace TEXT NOT NULL, native_id TEXT NOT NULL, locator TEXT NOT NULL,
            fingerprint_algorithm TEXT NOT NULL, fingerprint_value TEXT NOT NULL,
            project_hint TEXT NOT NULL, started_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            health TEXT NOT NULL, indexed_at TEXT NOT NULL, native_available INTEGER NOT NULL,
            session_handle TEXT, title TEXT
        );
        CREATE TABLE capsules (
            source_id TEXT PRIMARY KEY, project_key TEXT NOT NULL, schema_version INTEGER,
            content_json TEXT, search_text TEXT, byte_count INTEGER, updated_at TEXT
        );
        CREATE TABLE continuation_edges (
            source_id TEXT, target_id TEXT, project_key TEXT, confirmation_mode TEXT,
            confirmed_at TEXT, schema_version INTEGER, PRIMARY KEY(source_id, target_id)
        );",
    )
    .unwrap();
    let key = identity.key.clone();
    let content = r#"{"excerpts":[{"role":"user","text":"implement the cache boundary"}],"schema_version":1}"#;
    db.execute(
        "INSERT INTO sessions VALUES ('codex:ns:1',?1,'codex','ns','019f6000-1111-7000-8000-000000000001','loc','sha256','fp',?2,'2026-11-01T00:00:00Z','2026-11-02T00:00:00Z','complete','2026-11-02T00:00:00Z',1,'C1','Cache')",
        rusqlite::params![key.clone(), project.display().to_string()],
    )
    .unwrap();
    db.execute(
        "INSERT INTO capsules VALUES ('codex:ns:1',?1,1,?2,'implement the cache boundary',40,'2026-11-02T00:00:00Z')",
        rusqlite::params![key.clone(), content],
    )
    .unwrap();
    db.execute(
        "INSERT INTO sessions VALUES ('codex:ns:2',?1,'codex','ns','019f6000-2222-7000-8000-000000000002','loc','sha256','fp',?2,'2026-11-01T00:00:00Z','2026-11-03T00:00:00Z','unknown','2026-11-03T00:00:00Z',0,'C2','Gone')",
        rusqlite::params![key.clone(), project.display().to_string()],
    )
    .unwrap();
    db.execute(
        "INSERT INTO capsules VALUES ('codex:ns:2',?1,1,'{\"excerpts\":[]}','gone',2,'2026-11-03T00:00:00Z')",
        [key.clone()],
    )
    .unwrap();
    db.execute(
        "INSERT INTO continuation_edges VALUES ('codex:ns:1','codex:ns:2',?1,'explicit','2026-11-09T21:00:00Z',1)",
        [key.clone()],
    )
    .unwrap();
    (project, identity.database_path)
}

fn run(args: &[&str]) -> Result<String, tang::TangError> {
    let owned: Vec<String> = args.iter().map(|arg| (*arg).to_string()).collect();
    let mut stdout = Vec::new();
    run_with(&owned, &mut stdout)?;
    Ok(String::from_utf8(stdout).unwrap())
}

#[test]
fn project_commands_cover_search_context_map_resume_and_purge() {
    let root = scratch();
    let (project, database) = seed(&root);
    let project_arg = project.display().to_string();
    let database_arg = database.display().to_string();
    let search = run(&[
        "search",
        "cache",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
        "--health",
        "complete",
        "--since",
        "2026-11-01T00:00:00Z",
        "--json",
    ])
    .unwrap();
    let search: Value = serde_json::from_str(&search).unwrap();
    assert_eq!(search["results"][0]["handle"], "C1");

    let hidden = run(&["browse", "--cwd", &project_arg, "--database", &database_arg]).unwrap();
    assert!(hidden.contains("C1"));
    assert!(!hidden.contains("C2"));

    let cards = run(&[
        "cards",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
        "--include-unavailable",
        "--ascii",
    ])
    .unwrap();
    assert!(cards.contains("HANDLE C2"));

    let context = run(&[
        "context",
        "all",
        "--for",
        "C2",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
    ])
    .unwrap();
    assert!(context.contains("untrusted historical evidence"));
    assert!(context.contains("C1"));

    let map = run(&[
        "graph",
        "C1",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
        "--ascii",
        "--width",
        "100",
    ])
    .unwrap();
    assert!(map.contains("MULTIVERSE NETWORK"));
    assert!(map.contains("C1"));

    let demo = run(&["demo", "--ascii", "--width", "100"]).unwrap();
    assert!(demo.contains("MULTIVERSE NETWORK"));
    assert!(demo.contains("Demo complete"));
    assert!(demo.contains("ACTIVE G"));
    assert!(demo.contains("Codex hardening"));

    let resume = run(&[
        "resume",
        "C1",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
    ])
    .unwrap();
    assert!(resume.contains("codex"));
    assert!(resume.contains("resume"));

    let missing = run(&[
        "doctor",
        "--database",
        &root.join("missing.db").display().to_string(),
    ]);
    assert!(missing.is_err());

    let title = run(&[
        "title",
        "C1",
        "Release cache",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
    ])
    .unwrap();
    assert!(title.contains("C1"));

    run(&[
        "purge",
        "--all",
        "--yes",
        "--cwd",
        &project_arg,
        "--database",
        &database_arg,
        "--catalog",
        &root.join("no-catalog.db").display().to_string(),
    ])
    .unwrap();
    let db = Connection::open(&database).unwrap();
    let left: i64 = db
        .query_row("SELECT COUNT(*) FROM sessions", [], |row| row.get(0))
        .unwrap();
    assert_eq!(left, 0);
}

#[test]
fn skill_install_and_continuity_stay_local() {
    let root = scratch();
    let (project, database) = seed(&root);
    let home = root.join("codex-home");
    fs::create_dir_all(&home).unwrap();
    let installed = run(&[
        "skill",
        "install",
        "codex",
        "--cwd",
        &home.display().to_string(),
    ])
    .unwrap();
    assert!(installed.contains("skills/tang"));
    assert!(home.join("skills/tang/SKILL.md").is_file());
    let again = run(&[
        "skill",
        "install",
        "codex",
        "--cwd",
        &home.display().to_string(),
    ]);
    assert_eq!(again.unwrap_err().code, "skill-exists");
    let report = run(&[
        "continuity",
        "--cwd",
        &project.display().to_string(),
        "--database",
        &database.display().to_string(),
        "--json",
    ])
    .unwrap();
    let report: Value = serde_json::from_str(&report).unwrap();
    assert_eq!(report["sessions"], 2);
}
