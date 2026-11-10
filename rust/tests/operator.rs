use rusqlite::Connection;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::{SystemTime, UNIX_EPOCH};
use tang::continuity::{continuity, render_continuity};
use tang::doctor::{doctor_json, render_doctor, run_doctor};
use tang::project_purge::purge_project;
use tang::resume::plan_resume;
use tang::skill_install::install_skill;

const CODEX_ID: &str = "019f6000-5678-7000-8000-000000000005";
const GROK_ID: &str = "019f6000-1234-7000-8000-000000000001";
const OPENCODE_ID: &str = "ses_tangResume0000000000000000001";
const CURSOR_ID: &str = "019f6000-abcd-7000-8000-000000000002";
const CLAUDE_ID: &str = "019f6000-c1a0-7000-8000-000000000001";
const ANTIGRAVITY_ID: &str = "019f6000-a017-7000-8000-000000000001";

struct Scratch(PathBuf);

impl Scratch {
    fn new(name: &str) -> Self {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        let path = std::env::temp_dir().join(format!(
            "tang-operator-{name}-{}-{nanos}",
            std::process::id()
        ));
        fs::create_dir_all(&path).unwrap();
        let repo = repo_root().canonicalize().unwrap();
        let created = path.canonicalize().unwrap();
        assert!(
            !created.starts_with(&repo),
            "refusing to create test state in {}",
            created.display()
        );
        Self(path)
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for Scratch {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("crate parent")
        .to_path_buf()
}

fn open_sessions(path: &Path) -> Connection {
    let connection = Connection::open(path).unwrap();
    connection
        .execute_batch(
            "CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                adapter TEXT NOT NULL,
                native_id TEXT NOT NULL,
                native_available INTEGER NOT NULL,
                session_handle TEXT,
                project_hint TEXT
            );",
        )
        .unwrap();
    connection
}

#[allow(clippy::too_many_arguments)]
fn insert_session(
    connection: &Connection,
    project_key: &str,
    source_id: &str,
    adapter: &str,
    native_id: &str,
    handle: &str,
    native_available: i64,
    project_hint: &str,
) {
    connection
        .execute(
            "INSERT INTO sessions(
                source_id, project_key, adapter, native_id, native_available,
                session_handle, project_hint
             ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
            rusqlite::params![
                source_id,
                project_key,
                adapter,
                native_id,
                native_available,
                handle,
                project_hint
            ],
        )
        .unwrap();
}

fn canonical_text(path: &Path) -> String {
    fs::canonicalize(path)
        .unwrap()
        .to_str()
        .expect("utf-8 path")
        .to_string()
}

#[test]
fn resume_codex_argv_uses_the_recorded_native_id() {
    let scratch = Scratch::new("resume-codex");
    let project = scratch.path().join("project");
    fs::create_dir_all(&project).unwrap();
    let hint = canonical_text(&project);
    let database = open_sessions(&scratch.path().join("tang.db"));
    insert_session(
        &database,
        "project-a",
        &format!("codex:resume-fixture:{CODEX_ID}"),
        "codex",
        CODEX_ID,
        "C1",
        1,
        &hint,
    );

    let command = plan_resume(&database, "project-a", "c1", &project).unwrap();
    assert_eq!(command.program, "codex");
    assert_eq!(
        command.args,
        vec![
            "resume".to_string(),
            "-C".to_string(),
            hint.clone(),
            CODEX_ID.to_string()
        ]
    );
    assert_eq!(command.cwd, fs::canonicalize(&project).unwrap());

    let by_source = plan_resume(
        &database,
        "project-a",
        &format!("codex:resume-fixture:{CODEX_ID}"),
        &project,
    )
    .unwrap();
    assert_eq!(by_source.args, command.args);

    let missing = plan_resume(&database, "project-a", "C9", &project).unwrap_err();
    assert_eq!(missing.code, "not-in-project");
    let other_project = plan_resume(&database, "project-b", "C1", &project).unwrap_err();
    assert_eq!(other_project.code, "not-in-project");
}

#[test]
fn resume_unavailable_session_is_refused() {
    let scratch = Scratch::new("resume-unavailable");
    let project = scratch.path().join("project");
    fs::create_dir_all(&project).unwrap();
    let database = open_sessions(&scratch.path().join("tang.db"));
    insert_session(
        &database,
        "project-a",
        &format!("codex:resume-fixture:{CODEX_ID}"),
        "codex",
        CODEX_ID,
        "C1",
        0,
        &canonical_text(&project),
    );
    let error = plan_resume(&database, "project-a", "C1", &project).unwrap_err();
    assert_eq!(error.code, "unavailable-session");
}

#[test]
fn resume_argv_matches_each_supported_harness() {
    let scratch = Scratch::new("resume-harness");
    let project = scratch.path().join("project");
    let elsewhere = scratch.path().join("elsewhere");
    fs::create_dir_all(&project).unwrap();
    fs::create_dir_all(&elsewhere).unwrap();
    let hint = canonical_text(&project);
    let database = open_sessions(&scratch.path().join("tang.db"));
    let rows = [
        ("grok", GROK_ID, "G1", "grok:resume-fixture:"),
        ("opencode", OPENCODE_ID, "O1", "opencode:resume-fixture:"),
        ("cursor", CURSOR_ID, "R1", "cursor:resume-fixture:"),
        ("claude", CLAUDE_ID, "L1", "claude:resume-fixture:"),
        (
            "antigravity",
            ANTIGRAVITY_ID,
            "A1",
            "antigravity:resume-fixture:",
        ),
        ("openclaw", CODEX_ID, "K1", "openclaw:resume-fixture:"),
    ];
    for (adapter, native_id, handle, prefix) in rows {
        insert_session(
            &database,
            "project-a",
            &format!("{prefix}{native_id}"),
            adapter,
            native_id,
            handle,
            1,
            &hint,
        );
    }

    let grok = plan_resume(&database, "project-a", "G1", &project).unwrap();
    assert_eq!(grok.program, "grok");
    assert_eq!(
        grok.args,
        vec![
            "--cwd".to_string(),
            hint.clone(),
            "--resume".to_string(),
            GROK_ID.to_string()
        ]
    );

    let opencode = plan_resume(&database, "project-a", "O1", &project).unwrap();
    assert_eq!(opencode.program, "opencode");
    assert_eq!(
        opencode.args,
        vec![
            hint.clone(),
            "--session".to_string(),
            OPENCODE_ID.to_string()
        ]
    );

    let cursor = plan_resume(&database, "project-a", "R1", &project).unwrap();
    assert_eq!(cursor.program, "agent");
    assert_eq!(
        cursor.args,
        vec![
            "--workspace".to_string(),
            hint.clone(),
            "--resume".to_string(),
            CURSOR_ID.to_string()
        ]
    );

    let claude = plan_resume(&database, "project-a", "L1", &project).unwrap();
    assert_eq!(claude.program, "claude");
    assert_eq!(
        claude.args,
        vec!["--resume".to_string(), CLAUDE_ID.to_string()]
    );

    let antigravity = plan_resume(&database, "project-a", "A1", &project).unwrap();
    assert_eq!(antigravity.program, "agy");
    assert_eq!(
        antigravity.args,
        vec!["--conversation".to_string(), ANTIGRAVITY_ID.to_string()]
    );

    let openclaw = plan_resume(&database, "project-a", "K1", &project).unwrap_err();
    assert_eq!(openclaw.code, "unsupported-resume");

    insert_session(
        &database,
        "project-a",
        "codex:resume-fixture:not-a-uuid",
        "codex",
        "not-a-uuid",
        "C2",
        1,
        &hint,
    );
    let invalid = plan_resume(&database, "project-a", "C2", &project).unwrap_err();
    assert_eq!(invalid.code, "resume-native-id-invalid");

    insert_session(
        &database,
        "project-a",
        &format!("grok:other:{GROK_ID}"),
        "grok",
        GROK_ID,
        "G2",
        1,
        &canonical_text(&elsewhere),
    );
    let mismatch = plan_resume(&database, "project-a", "G2", &project).unwrap_err();
    assert_eq!(mismatch.code, "resume-project-mismatch");
}

#[test]
fn skill_install_copies_into_temp_home_and_refuses_existing() {
    let scratch = Scratch::new("skill");
    let home = scratch.path().join("codex-home");
    fs::create_dir_all(&home).unwrap();
    let repo = repo_root();
    let destination = install_skill(&repo, "codex", &home, false).unwrap();
    let skill = Path::new(&destination);
    assert_eq!(skill, home.join("skills").join("tang"));
    assert_eq!(
        fs::read(skill.join("SKILL.md")).unwrap(),
        fs::read(repo.join("skills").join("tang").join("SKILL.md")).unwrap()
    );
    assert!(skill.join("agents").join("openai.yaml").is_file());
    assert!(destination.starts_with(home.to_str().unwrap()));

    let refused = install_skill(&repo, "codex", &home, false).unwrap_err();
    assert_eq!(refused.code, "skill-exists");

    fs::write(skill.join("SKILL.md"), b"stale").unwrap();
    let replaced = install_skill(&repo, "codex", &home, true).unwrap();
    assert_eq!(replaced, destination);
    assert_eq!(
        fs::read(skill.join("SKILL.md")).unwrap(),
        fs::read(repo.join("skills").join("tang").join("SKILL.md")).unwrap()
    );

    let claude_home = scratch.path().join("claude-home");
    fs::create_dir_all(&claude_home).unwrap();
    let claude = install_skill(&repo, "claude", &claude_home, false).unwrap();
    assert_eq!(Path::new(&claude), claude_home.join("skills").join("tang"));
    let claude_skill = fs::read_to_string(Path::new(&claude).join("SKILL.md")).unwrap();
    assert!(claude_skill.contains("Claude Code"));
    assert_ne!(
        claude_skill,
        fs::read_to_string(repo.join("skills").join("tang").join("SKILL.md")).unwrap()
    );

    let opencode_home = scratch.path().join("opencode-home");
    fs::create_dir_all(&opencode_home).unwrap();
    fs::create_dir_all(opencode_home.join(".opencode").join("commands")).unwrap();
    fs::write(
        opencode_home
            .join(".opencode")
            .join("commands")
            .join("other.md"),
        b"keep",
    )
    .unwrap();
    let opencode = install_skill(&repo, "opencode", &opencode_home, false).unwrap();
    assert_eq!(Path::new(&opencode), opencode_home.join(".opencode"));
    assert_eq!(
        fs::read(opencode_home.join(".opencode/skills/tang/SKILL.md")).unwrap(),
        fs::read(repo.join("skills/opencode/tang/SKILL.md")).unwrap()
    );
    assert_eq!(
        fs::read(opencode_home.join(".opencode/commands/tang.md")).unwrap(),
        fs::read(repo.join(".opencode/commands/tang.md")).unwrap()
    );
    assert_eq!(
        fs::read(opencode_home.join(".opencode/tools/tang_current_target.ts")).unwrap(),
        fs::read(repo.join(".opencode/tools/tang_current_target.ts")).unwrap()
    );
    assert_eq!(
        fs::read(opencode_home.join(".opencode/tools/tang_predecessor_context.ts")).unwrap(),
        fs::read(repo.join(".opencode/tools/tang_predecessor_context.ts")).unwrap()
    );
    assert!(!opencode_home
        .join(".opencode/tools/tang_contract_probe.ts")
        .exists());
    assert_eq!(
        fs::read(opencode_home.join(".opencode/commands/other.md")).unwrap(),
        b"keep"
    );
    let again = install_skill(&repo, "opencode", &opencode_home, false).unwrap_err();
    assert_eq!(again.code, "skill-exists");

    let unknown = install_skill(&repo, "cursor", &home, false).unwrap_err();
    assert_eq!(unknown.code, "invalid-harness");
    assert!(!repo.join(".tang").exists());
}

#[test]
fn doctor_reports_missing_and_temp_sqlite() {
    let scratch = Scratch::new("doctor");
    let missing = scratch.path().join("missing.db");
    let missing_checks = run_doctor(&missing);
    assert_eq!(missing_checks.len(), 2);
    assert_eq!(missing_checks[0].component, "sqlite");
    assert_eq!(missing_checks[0].status, "unavailable");
    assert!(missing_checks[0].message.contains("has not been indexed"));
    assert_eq!(missing_checks[1].component, "fts5");
    assert_eq!(missing_checks[1].status, "ready");
    assert!(!missing.exists());

    let rendered = render_doctor(&missing_checks);
    assert!(rendered.contains("sqlite: unavailable — The project has not been indexed."));
    assert!(rendered.contains("fts5: ready — SQLite FTS5 is available."));
    let document: serde_json::Value = serde_json::from_str(&doctor_json(&missing_checks)).unwrap();
    assert_eq!(document["schema_version"], 1);
    assert_eq!(document["status"], "unavailable");
    assert_eq!(document["checks"][0]["component"], "sqlite");

    let database = scratch.path().join("ready.db");
    {
        let connection = Connection::open(&database).unwrap();
        connection
            .execute_batch("CREATE TABLE example(id INTEGER);")
            .unwrap();
    }
    let ready = run_doctor(&database);
    assert_eq!(ready[0].status, "ready");
    assert_eq!(ready[1].status, "ready");
    let ready_document: serde_json::Value = serde_json::from_str(&doctor_json(&ready)).unwrap();
    assert_eq!(ready_document["schema_version"], 1);
    assert_eq!(ready_document["status"], "ready");
}

#[test]
fn continuity_counts_only_the_requested_project() {
    let scratch = Scratch::new("continuity");
    let project = scratch.path().join("not-a-repo");
    fs::create_dir_all(&project).unwrap();
    let database = Connection::open(scratch.path().join("tang.db")).unwrap();
    database
        .execute_batch(
            "CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL
            );
            INSERT INTO sessions(source_id, project_key) VALUES
                ('a', 'alpha'),
                ('b', 'alpha'),
                ('c', 'beta');",
        )
        .unwrap();
    let brief = continuity(&project, &database, "alpha").unwrap();
    assert_eq!(brief.branch, None);
    assert_eq!(brief.session_count, 2);
    assert_eq!(render_continuity(&brief), "branch: none\nsessions: 2\n");

    let repo = scratch.path().join("repo");
    fs::create_dir_all(&repo).unwrap();
    git(&repo, &["init", "-b", "demo"]);
    // rev-parse --abbrev-ref HEAD needs a commit; an unborn HEAD is not a branch name.
    git(
        &repo,
        &[
            "-c",
            "user.email=tang@example.com",
            "-c",
            "user.name=Tang",
            "commit",
            "--allow-empty",
            "-m",
            "init",
        ],
    );
    let branched = continuity(&repo, &database, "beta").unwrap();
    assert_eq!(branched.branch.as_deref(), Some("demo"));
    assert_eq!(branched.session_count, 1);
    assert_eq!(render_continuity(&branched), "branch: demo\nsessions: 1\n");
}

#[test]
fn purge_removes_one_project_and_keeps_the_other() {
    let scratch = Scratch::new("purge");
    let database_path = scratch.path().join("tang.db");
    let mut database = Connection::open(&database_path).unwrap();
    database
        .execute_batch(
            "CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL
            );
            CREATE TABLE capsules (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL
            );
            CREATE TABLE continuation_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                project_key TEXT NOT NULL,
                PRIMARY KEY(source_id, target_id)
            );
            CREATE VIRTUAL TABLE capsules_fts USING fts5(
                source_id,
                project_key,
                search_text
            );
            CREATE TABLE session_overrides (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL,
                custom_title TEXT NOT NULL
            );
            INSERT INTO sessions(source_id, project_key) VALUES
                ('a1', 'alpha'),
                ('a2', 'alpha'),
                ('b1', 'beta');
            INSERT INTO capsules(source_id, project_key) VALUES
                ('a1', 'alpha'),
                ('a2', 'alpha'),
                ('b1', 'beta');
            INSERT INTO continuation_edges(source_id, target_id, project_key) VALUES
                ('a1', 'a2', 'alpha'),
                ('b1', 'b1', 'beta');
            INSERT INTO capsules_fts(source_id, project_key, search_text) VALUES
                ('a1', 'alpha', 'alpha one'),
                ('a2', 'alpha', 'alpha two'),
                ('b1', 'beta', 'beta one');
            INSERT INTO session_overrides(source_id, project_key, custom_title) VALUES
                ('a1', 'alpha', 'Alpha title'),
                ('b1', 'beta', 'Beta title');",
        )
        .unwrap();

    let removed = purge_project(&mut database, "alpha").unwrap();
    assert_eq!(removed, (2, 2, 1));
    assert!(database_path.is_file());
    assert_eq!(count(&database, "sessions", "alpha"), 0);
    assert_eq!(count(&database, "capsules", "alpha"), 0);
    assert_eq!(count(&database, "continuation_edges", "alpha"), 0);
    assert_eq!(count(&database, "capsules_fts", "alpha"), 0);
    assert_eq!(count(&database, "session_overrides", "alpha"), 0);
    assert_eq!(count(&database, "sessions", "beta"), 1);
    assert_eq!(count(&database, "capsules", "beta"), 1);
    assert_eq!(count(&database, "continuation_edges", "beta"), 1);
    assert_eq!(count(&database, "capsules_fts", "beta"), 1);
    assert_eq!(count(&database, "session_overrides", "beta"), 1);

    let untouched = purge_project(&mut database, "missing").unwrap();
    assert_eq!(untouched, (0, 0, 0));
    assert_eq!(count(&database, "sessions", "beta"), 1);
}

#[test]
fn purge_skips_optional_tables_and_fts_without_project_key() {
    let scratch = Scratch::new("purge-optional");
    let mut database = Connection::open(scratch.path().join("tang.db")).unwrap();
    database
        .execute_batch(
            "CREATE TABLE sessions (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL
            );
            CREATE TABLE capsules (
                source_id TEXT PRIMARY KEY,
                project_key TEXT NOT NULL
            );
            CREATE TABLE continuation_edges (
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                project_key TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE capsules_fts USING fts5(source_id, search_text);
            INSERT INTO sessions(source_id, project_key) VALUES ('a1', 'alpha'), ('b1', 'beta');
            INSERT INTO capsules(source_id, project_key) VALUES ('a1', 'alpha'), ('b1', 'beta');
            INSERT INTO capsules_fts(source_id, search_text) VALUES
                ('a1', 'alpha text'),
                ('b1', 'beta text');",
        )
        .unwrap();
    let removed = purge_project(&mut database, "alpha").unwrap();
    assert_eq!(removed, (1, 1, 0));
    assert_eq!(
        database
            .query_row(
                "SELECT COUNT(*) FROM capsules_fts WHERE source_id = 'a1'",
                [],
                |row| row.get::<_, i64>(0)
            )
            .unwrap(),
        0
    );
    assert_eq!(
        database
            .query_row(
                "SELECT COUNT(*) FROM capsules_fts WHERE source_id = 'b1'",
                [],
                |row| row.get::<_, i64>(0)
            )
            .unwrap(),
        1
    );
    assert_eq!(count(&database, "sessions", "beta"), 1);
}

fn count(connection: &Connection, table: &str, project_key: &str) -> i64 {
    let sql = match table {
        "sessions" => "SELECT COUNT(*) FROM sessions WHERE project_key = ?1",
        "capsules" => "SELECT COUNT(*) FROM capsules WHERE project_key = ?1",
        "continuation_edges" => "SELECT COUNT(*) FROM continuation_edges WHERE project_key = ?1",
        "capsules_fts" => "SELECT COUNT(*) FROM capsules_fts WHERE project_key = ?1",
        "session_overrides" => "SELECT COUNT(*) FROM session_overrides WHERE project_key = ?1",
        _ => panic!("unsupported test table"),
    };
    connection
        .query_row(sql, [project_key], |row| row.get(0))
        .unwrap()
}

fn git(directory: &Path, args: &[&str]) {
    let mut command = Command::new("git");
    command
        .arg("-C")
        .arg(directory)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    let keys: Vec<String> = std::env::vars()
        .map(|(key, _)| key)
        .filter(|key| key.to_ascii_uppercase().starts_with("GIT_"))
        .collect();
    for key in keys {
        command.env_remove(key);
    }
    command.env("GIT_TERMINAL_PROMPT", "0");
    let status = command.status().unwrap();
    assert!(status.success(), "git {args:?} failed");
}
