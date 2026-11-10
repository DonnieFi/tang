//! Scriptable commands for the global catalog.

use crate::catalog::{
    add_label, default_catalog_path, forget_project, open_catalog, open_project_readonly, recall,
    remove_label, sync_project, RecallHit, RecallQuery, SyncResult,
};
use crate::error::{Result, TangError};
use crate::index_antigravity::index_antigravity;
use crate::index_claude::index_claude;
use crate::index_codex::{index_codex, CodexIndexResult};
use crate::index_cursor::index_cursor;
use crate::index_grok::index_grok;
use crate::index_openclaw::index_openclaw;
use crate::index_opencode::index_opencode;
use crate::join::{link_plan, open_project_readwrite, resolve_join};
use crate::project::resolve_project;
use crate::stats::{counts, render_counts};
use crate::timeutil::rfc3339_now;
use serde_json::{json, Value};
use std::io::Write;
use std::path::{Path, PathBuf};

pub fn run_with(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    if args.is_empty() || args[0] == "--help" || args[0] == "-h" {
        writeln!(stdout, "{HELP}").map_err(io_error)?;
        return Ok(());
    }
    if args[0] == "--version" {
        writeln!(stdout, "tang 2.0.0").map_err(io_error)?;
        return Ok(());
    }
    match args[0].as_str() {
        "index" => index_command(&args[1..], stdout),
        "catalog" => catalog_command(&args[1..], stdout),
        "recall" => recall_command(&args[1..], stdout),
        "label" => label_command(&args[1..], stdout),
        "join" | "link" => join_command(&args[1..], stdout),
        "stats" => stats_command(&args[1..], stdout),
        "graph" | "map" => graph_command(&args[1..], stdout),
        "browse" => browse_command(&args[1..], false, stdout),
        "cards" => browse_command(&args[1..], true, stdout),
        "search" => search_command(&args[1..], stdout),
        "context" => context_command(&args[1..], stdout),
        "title" => title_command(&args[1..], stdout),
        "resume" => resume_command(&args[1..], stdout),
        "doctor" => doctor_command(&args[1..], stdout),
        "continuity" => continuity_command(&args[1..], stdout),
        "skill" => skill_command(&args[1..], stdout),
        "demo" => demo_command(&args[1..], stdout),
        "purge" => purge_command(&args[1..], stdout),
        "help" => {
            writeln!(stdout, "{HELP}").map_err(io_error)?;
            Ok(())
        }
        other => Err(TangError::new(
            "unknown-command",
            format!("{other} is not a Tang 2.0 command. Run tang --help."),
        )),
    }
}

const HELP: &str = "\
Tang 2.0 catalog

Usage:
  tang index [--cwd DIR] [--database PATH] [--codex-home PATH] [--grok-home PATH] [--opencode-home PATH] [--cursor-home PATH] [--claude-home PATH] [--antigravity-home PATH] [--openclaw-home PATH] [--json]
  tang catalog sync [--cwd DIR] [--database PATH] [--catalog PATH] [--json]
  tang recall [QUERY] [--label NAME] [--category NAME] [--harness NAME] [--limit N]
               [--include-unavailable] [--json] [--catalog PATH]
  tang label add|remove HANDLE LABEL [--catalog PATH]
  tang browse [--harness NAME] [--health STATE] [--since TS] [--until TS] [--cards] [--brief]
  tang search QUERY [--harness NAME] [--health STATE] [--since TS] [--until TS]
  tang context HANDLE... | tang context all [--for HANDLE]
  tang join|link --from HANDLE --into HANDLE | --current --current-native-id ID
  tang title HANDLE TITLE | tang title HANDLE --clear
  tang resume HANDLE
  tang graph [HANDLE] [--ascii] [--width N]
  tang demo [--ascii] [--width N]
  tang doctor [--database PATH]
  tang continuity
  tang skill install codex|claude|opencode [--force]
  tang stats [--catalog PATH]
  tang purge --all --yes

Recall searches the global catalog and does not open native logs. Search reads
the project database. Join records a continuation only inside one project.
Graph renders the Multiverse Map. Demo uses an in-memory graph and does not
touch a database.
";

fn index_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let cwd = flags
        .cwd
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let database = flags
        .database
        .clone()
        .unwrap_or_else(|| project.database_path.clone());
    let mut indexed = 0;
    let mut deleted = 0;
    let mut skipped = 0;
    let mut warnings = Vec::new();
    let explicit = flags.codex_home.is_some()
        || flags.grok_home.is_some()
        || flags.opencode_home.is_some()
        || flags.cursor_home.is_some()
        || flags.claude_home.is_some()
        || flags.antigravity_home.is_some()
        || flags.openclaw_home.is_some();
    if flags.codex_home.is_some() || !explicit {
        let codex_home = flags.codex_home.clone().unwrap_or_else(default_codex_home);
        let result = index_codex(&codex_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    if let Some(grok_home) = &flags.grok_home {
        let result = index_grok(grok_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    if let Some(opencode_home) = &flags.opencode_home {
        let result = index_opencode(opencode_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    if let Some(cursor_home) = &flags.cursor_home {
        let result = index_cursor(cursor_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    if let Some(claude_home) = &flags.claude_home {
        let result = index_claude(claude_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    if let Some(antigravity_home) = &flags.antigravity_home {
        let result = index_antigravity(antigravity_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    if let Some(openclaw_home) = &flags.openclaw_home {
        let result = index_openclaw(openclaw_home, &project, &database)?;
        indexed += result.indexed;
        deleted += result.deleted;
        skipped += result.skipped;
        warnings.extend(result.warnings);
    }
    let result = CodexIndexResult {
        indexed,
        deleted,
        skipped,
        warnings,
    };
    if flags.json {
        writeln!(stdout, "{}", index_json(&result)).map_err(io_error)?;
    } else {
        writeln!(
            stdout,
            "Indexed {} sessions, deleted {}, skipped {}.",
            result.indexed, result.deleted, result.skipped
        )
        .map_err(io_error)?;
    }
    for warning in &result.warnings {
        let _ = writeln!(std::io::stderr(), "warning: {warning}");
    }
    Ok(())
}

fn default_codex_home() -> PathBuf {
    std::env::var_os("CODEX_HOME")
        .map(PathBuf::from)
        .filter(|path| !path.as_os_str().is_empty())
        .unwrap_or_else(|| {
            std::env::var_os("HOME")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("."))
                .join(".codex")
        })
}

fn index_json(result: &CodexIndexResult) -> String {
    compact(&json!({
        "deleted": result.deleted,
        "indexed": result.indexed,
        "schema_version": 1,
        "skipped": result.skipped,
        "warnings": result.warnings,
    }))
}

fn stats_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let cwd = flags
        .cwd
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let database = flags.database.unwrap_or(project.database_path);
    let project_db = open_project_readonly(&database)?;
    let catalog_path = flags.catalog.unwrap_or_else(default_catalog_path);
    let catalog_present = catalog_path.is_file();
    let catalog = if catalog_present {
        Some(open_catalog(&catalog_path)?)
    } else {
        None
    };
    let counted = counts(catalog.as_ref(), &project_db, &project.key)?;
    if flags.json {
        writeln!(stdout, "{}", stats_json(&counted, catalog_present)).map_err(io_error)?;
    } else {
        write!(stdout, "{}", render_counts(&counted, catalog_present)).map_err(io_error)?;
    }
    Ok(())
}

fn graph_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let (cwd, project, project_db) = open_work(&flags)?;
    let _ = cwd;
    let options = crate::multiverse::MapOptions {
        width: flags.width.unwrap_or(100) as usize,
        ascii_only: flags.ascii,
        anchor: flags.query.clone(),
        current_handle: flags.current_native_id.clone(),
    };
    if flags.json {
        writeln!(
            stdout,
            "{}",
            crate::multiverse::render_project_map_json(&project_db, &project.key, &options)?
        )
        .map_err(io_error)?;
    } else {
        write!(
            stdout,
            "{}",
            crate::multiverse::render_project_map(&project_db, &project.key, &options)?
        )
        .map_err(io_error)?;
    }
    Ok(())
}

fn demo_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let rendered = crate::demo::render_demo(flags.width.unwrap_or(100) as usize, flags.ascii);
    write!(stdout, "{rendered}").map_err(io_error)?;
    Ok(())
}

fn browse_command(args: &[String], cards_default: bool, stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let (_cwd, project, project_db) = open_work(&flags)?;
    let query = discovery_query(&flags);
    let rows = narrow_discovery(
        &flags,
        crate::discovery::browse(&project_db, &project.key, &query)?,
    );
    render_discovery(&flags, cards_default || flags.cards, &rows, stdout)
}

fn search_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let (_cwd, project, project_db) = open_work_mut(&flags)?;
    let query = discovery_query(&flags);
    let rows = narrow_discovery(
        &flags,
        crate::discovery::search_project(&project_db, &project.key, &query)?,
    );
    render_discovery(&flags, false, &rows, stdout)
}

fn render_discovery(
    flags: &Flags,
    cards_default: bool,
    rows: &[crate::discovery::DiscoveryRow],
    stdout: &mut dyn Write,
) -> Result<()> {
    if flags.json {
        let payload: Vec<Value> = rows
            .iter()
            .map(|row| {
                json!({
                    "handle": row.handle,
                    "harness": row.harness,
                    "health": row.health,
                    "native_available": row.native_available,
                    "snippet": row.snippet,
                    "source_id": row.source_id,
                    "title": row.title,
                    "updated_at": row.updated_at,
                })
            })
            .collect();
        writeln!(
            stdout,
            "{}",
            compact(&json!({"results": payload, "schema_version": 1}))
        )
        .map_err(io_error)?;
    } else if (flags.cards || cards_default) && !flags.brief {
        write!(stdout, "{}", crate::cards::render_cards(rows)).map_err(io_error)?;
    } else {
        write!(stdout, "{}", crate::cards::render_brief(rows)).map_err(io_error)?;
    }
    Ok(())
}

fn context_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags_many(args)?;
    let (_cwd, project, project_db) = open_work(&flags)?;
    let tokens = if flags.positionals.is_empty() {
        flags.query.clone().into_iter().collect::<Vec<_>>()
    } else {
        flags.positionals.clone()
    };
    let request = if tokens.first().map(String::as_str) == Some("all") {
        let target = flags
            .into
            .as_deref()
            .or(flags.label.as_deref())
            .ok_or_else(|| {
                TangError::new("invalid-session", "tang context all needs --for HANDLE.")
            })?;
        crate::context_pack::ContextRequest::Ancestors {
            target,
            depth: None,
        }
    } else if tokens.len() == 1 && tokens[0].parse::<u32>().is_ok() {
        let target = flags.into.as_deref().ok_or_else(|| {
            TangError::new(
                "invalid-session",
                "A depth-limited context needs --for HANDLE.",
            )
        })?;
        crate::context_pack::ContextRequest::Ancestors {
            target,
            depth: tokens[0].parse().ok(),
        }
    } else {
        crate::context_pack::ContextRequest::Sessions(&tokens)
    };
    let pack = crate::context_pack::build_pack(&project_db, &project.key, request)?;
    if flags.json {
        writeln!(stdout, "{}", crate::context_pack::render_json(&pack)).map_err(io_error)?;
    } else {
        write!(stdout, "{}", crate::context_pack::render_markdown(&pack)).map_err(io_error)?;
    }
    Ok(())
}

fn title_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let clear = args.iter().any(|arg| arg == "--clear");
    let flags = parse_flags_many(args)?;
    let tokens = if flags.positionals.is_empty() {
        flags.query.clone().into_iter().collect::<Vec<_>>()
    } else {
        flags.positionals.clone()
    };
    let (_cwd, project, mut project_db) = open_work_mut(&flags)?;
    let handle = tokens
        .first()
        .cloned()
        .ok_or_else(|| TangError::new("invalid-session", "A session handle is required."))?;
    let written = if clear {
        crate::titles::clear_title(&mut project_db, &project.key, &handle)?
    } else {
        let title = tokens
            .get(1)
            .cloned()
            .ok_or_else(|| TangError::new("invalid-title", "A title is required."))?;
        crate::titles::set_title(&mut project_db, &project.key, &handle, &title)?
    };
    writeln!(stdout, "Updated title for {written}.").map_err(io_error)?;
    Ok(())
}

fn resume_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let (cwd, project, project_db) = open_work(&flags)?;
    let handle = flags
        .query
        .clone()
        .ok_or_else(|| TangError::new("resume-handle-required", "A Tang handle is required."))?;
    let command = crate::resume::plan_resume(&project_db, &project.key, &handle, &cwd)?;
    crate::resume::launch_resume(&command)?;
    writeln!(stdout, "Resumed {handle}.").map_err(io_error)?;
    Ok(())
}

fn doctor_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let cwd = flags
        .cwd
        .clone()
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let database = flags.database.clone().unwrap_or(project.database_path);
    let checks = crate::doctor::run_doctor(&database);
    if flags.json {
        writeln!(stdout, "{}", crate::doctor::doctor_json(&checks)).map_err(io_error)?;
    } else {
        write!(stdout, "{}", crate::doctor::render_doctor(&checks)).map_err(io_error)?;
    }
    if crate::doctor::doctor_failed(&checks) {
        return Err(TangError::new("doctor", "Tang is not ready."));
    }
    Ok(())
}

fn continuity_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    let (cwd, project, project_db) = open_work(&flags)?;
    let report = crate::continuity::continuity(&cwd, &project_db, &project.key)?;
    if flags.json {
        writeln!(stdout, "{}", crate::continuity::continuity_json(&report)).map_err(io_error)?;
    } else {
        write!(stdout, "{}", crate::continuity::render_continuity(&report)).map_err(io_error)?;
    }
    Ok(())
}

fn skill_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    if args.first().map(String::as_str) != Some("install") {
        return Err(TangError::new(
            "unknown-command",
            "Use tang skill install codex, claude, or opencode.",
        ));
    }
    let harness = args
        .get(1)
        .cloned()
        .ok_or_else(|| TangError::new("invalid-harness", "Name the harness to install."))?;
    let flags = parse_flags(&args[2..])?;
    let home = flags
        .cwd
        .clone()
        .or(flags.codex_home.clone())
        .or(flags.claude_home.clone())
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let destination = crate::skill_install::install_skill(
        &crate::skill_install::repo_root(),
        &harness,
        &home,
        flags.force,
    )?;
    writeln!(stdout, "Installed {harness} skill at {destination}.").map_err(io_error)?;
    Ok(())
}

fn open_work(
    flags: &Flags,
) -> Result<(
    PathBuf,
    crate::project::ProjectIdentity,
    rusqlite::Connection,
)> {
    let cwd = flags
        .cwd
        .clone()
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let database = flags
        .database
        .clone()
        .unwrap_or_else(|| project.database_path.clone());
    let project_db = open_project_readonly(&database)?;
    Ok((cwd, project, project_db))
}

fn open_work_mut(
    flags: &Flags,
) -> Result<(
    PathBuf,
    crate::project::ProjectIdentity,
    rusqlite::Connection,
)> {
    let cwd = flags
        .cwd
        .clone()
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let database = flags
        .database
        .clone()
        .unwrap_or_else(|| project.database_path.clone());
    let project_db = crate::join::open_project_readwrite(&database)?;
    Ok((cwd, project, project_db))
}

fn discovery_query(flags: &Flags) -> crate::discovery::DiscoveryQuery<'_> {
    crate::discovery::DiscoveryQuery {
        text: flags.query.as_deref(),
        harness: flags.harness.as_deref(),
        include_unavailable: flags.include_unavailable || flags.exclude_current,
        limit: flags.limit.unwrap_or(20),
    }
}

fn narrow_discovery(
    flags: &Flags,
    rows: Vec<crate::discovery::DiscoveryRow>,
) -> Vec<crate::discovery::DiscoveryRow> {
    rows.into_iter()
        .filter(|row| {
            flags
                .health
                .as_deref()
                .map(|health| row.health.eq_ignore_ascii_case(health.trim()))
                .unwrap_or(true)
        })
        .filter(|row| {
            flags
                .since
                .as_deref()
                .map(|since| row.updated_at.as_str() >= since)
                .unwrap_or(true)
        })
        .filter(|row| {
            flags
                .until
                .as_deref()
                .map(|until| row.updated_at.as_str() <= until)
                .unwrap_or(true)
        })
        .filter(|row| {
            if flags.exclude_current {
                flags
                    .current_native_id
                    .as_deref()
                    .map(|native_id| !row.source_id.contains(native_id))
                    .unwrap_or(true)
            } else {
                true
            }
        })
        .collect()
}

fn stats_json(counts: &crate::stats::Counts, catalog_present: bool) -> String {
    let harness = serde_json::Map::from_iter(
        counts
            .by_harness
            .iter()
            .map(|(key, value)| (key.clone(), json!(value))),
    );
    let category = serde_json::Map::from_iter(
        counts
            .by_category
            .iter()
            .map(|(key, value)| (key.clone(), json!(value))),
    );
    let label = serde_json::Map::from_iter(
        counts
            .by_label
            .iter()
            .map(|(key, value)| (key.clone(), json!(value))),
    );
    compact(&json!({
        "catalog_present": catalog_present,
        "categories": category,
        "components": counts.components,
        "edges": counts.edges,
        "graph_sessions": counts.graph_sessions,
        "harnesses": harness,
        "labels": label,
        "projects": counts.projects,
        "schema_version": 1,
        "sessions": counts.sessions,
    }))
}

fn catalog_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    if args.first().map(String::as_str) != Some("sync") {
        return Err(TangError::new("unknown-command", "Use tang catalog sync."));
    }
    let flags = parse_flags(&args[1..])?;
    let cwd = flags
        .cwd
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let database = flags.database.unwrap_or(project.database_path);
    let project_db = open_project_readonly(&database)?;
    let catalog_path = flags.catalog.unwrap_or_else(default_catalog_path);
    let mut catalog = open_catalog(&catalog_path)?;
    let result = sync_project(
        &mut catalog,
        &project_db,
        &project.key,
        &project.display_name,
        &database,
        &rfc3339_now(),
    )?;
    if flags.json {
        writeln!(stdout, "{}", sync_json(&result)).map_err(io_error)?;
    } else {
        writeln!(
            stdout,
            "Catalog sync upserted {}, removed {}, skipped {}.",
            result.upserted, result.removed, result.skipped
        )
        .map_err(io_error)?;
    }
    for warning in &result.warnings {
        let _ = writeln!(std::io::stderr(), "warning: {warning}");
    }
    Ok(())
}

fn recall_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    if flags.query.as_deref().unwrap_or("").trim().is_empty()
        && flags.label.is_none()
        && flags.category.is_none()
        && flags.harness.is_none()
    {
        return Err(TangError::new(
            "empty-query",
            "Provide a query or a label, category, or harness filter.",
        ));
    }
    let query = flags.query.clone().unwrap_or_default();
    let limit = flags.limit.unwrap_or(20);
    let catalog_path = flags.catalog.unwrap_or_else(default_catalog_path);
    if !catalog_path.is_file() {
        return Err(TangError::new(
            "catalog-missing",
            "Tang has no global catalog; run tang catalog sync.",
        ));
    }
    let catalog = open_catalog(&catalog_path)?;
    let hits = recall(
        &catalog,
        &RecallQuery {
            text: Some(query.as_str()).filter(|value| !value.is_empty()),
            label: flags.label.as_deref(),
            category: flags.category.as_deref(),
            harness: flags.harness.as_deref(),
            limit,
            include_unavailable: flags.include_unavailable,
        },
    )?;
    if flags.json {
        writeln!(stdout, "{}", recall_json(flags.query.as_deref(), &hits)).map_err(io_error)?;
    } else if hits.is_empty() {
        writeln!(stdout, "No matching sessions.").map_err(io_error)?;
    } else {
        for hit in &hits {
            writeln!(
                stdout,
                "{}\t{}\t{}\t{}\t{}\t{}",
                hit.catalog_handle,
                hit.harness,
                hit.category,
                hit.labels.join(","),
                hit.project_display,
                hit.title.as_deref().unwrap_or("")
            )
            .map_err(io_error)?;
        }
    }
    Ok(())
}

struct Flags {
    catalog: Option<PathBuf>,
    database: Option<PathBuf>,
    cwd: Option<PathBuf>,
    query: Option<String>,
    json: bool,
    harness: Option<String>,
    limit: Option<i64>,
    include_unavailable: bool,
    label: Option<String>,
    category: Option<String>,
    sources: Vec<String>,
    into: Option<String>,
    yes: bool,
    all: bool,
    codex_home: Option<PathBuf>,
    grok_home: Option<PathBuf>,
    opencode_home: Option<PathBuf>,
    cursor_home: Option<PathBuf>,
    claude_home: Option<PathBuf>,
    antigravity_home: Option<PathBuf>,
    openclaw_home: Option<PathBuf>,
    since: Option<String>,
    until: Option<String>,
    health: Option<String>,
    cards: bool,
    brief: bool,
    ascii: bool,
    width: Option<i64>,
    current: bool,
    current_native_id: Option<String>,
    exclude_current: bool,
    force: bool,
    clear: bool,
    positionals: Vec<String>,
}

fn parse_flags(args: &[String]) -> Result<Flags> {
    parse_flags_mode(args, true, false)
}

fn parse_flags_with(args: &[String], allow_positional: bool) -> Result<Flags> {
    parse_flags_mode(args, allow_positional, false)
}

fn parse_flags_many(args: &[String]) -> Result<Flags> {
    parse_flags_mode(args, true, true)
}

fn parse_flags_mode(args: &[String], allow_positional: bool, allow_many: bool) -> Result<Flags> {
    let mut flags = Flags {
        catalog: None,
        database: None,
        cwd: None,
        query: None,
        json: false,
        harness: None,
        limit: None,
        include_unavailable: false,
        label: None,
        category: None,
        sources: Vec::new(),
        into: None,
        yes: false,
        all: false,
        codex_home: None,
        grok_home: None,
        opencode_home: None,
        cursor_home: None,
        claude_home: None,
        antigravity_home: None,
        openclaw_home: None,
        since: None,
        until: None,
        health: None,
        cards: false,
        brief: false,
        ascii: false,
        width: None,
        current: false,
        current_native_id: None,
        exclude_current: false,
        force: false,
        clear: false,
        positionals: Vec::new(),
    };
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        if arg == "--json" {
            flags.json = true;
        } else if arg == "--include-unavailable" {
            flags.include_unavailable = true;
        } else if arg == "--yes" {
            flags.yes = true;
        } else if arg == "--all" {
            flags.all = true;
        } else if arg == "--cards" {
            flags.cards = true;
        } else if arg == "--brief" {
            flags.brief = true;
        } else if arg == "--ascii" {
            flags.ascii = true;
        } else if arg == "--current" {
            flags.current = true;
        } else if arg == "--exclude-current" {
            flags.exclude_current = true;
        } else if arg == "--force" {
            flags.force = true;
        } else if arg == "--clear" {
            flags.clear = true;
        } else if let Some(value) = flag_value(args, &mut index, "--codex-home")? {
            flags.codex_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--grok-home")? {
            flags.grok_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--opencode-home")? {
            flags.opencode_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--cursor-home")? {
            flags.cursor_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--claude-home")? {
            flags.claude_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--antigravity-home")? {
            flags.antigravity_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--openclaw-home")? {
            flags.openclaw_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--catalog")? {
            flags.catalog = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--database")? {
            flags.database = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--cwd")? {
            flags.cwd = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--harness")? {
            flags.harness = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--from")? {
            flags.sources.push(value);
        } else if let Some(value) = flag_value(args, &mut index, "--into")? {
            flags.into = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--to")? {
            flags.into = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--for")? {
            flags.into = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--health")? {
            flags.health = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--since")? {
            flags.since = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--until")? {
            flags.until = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--width")? {
            let parsed: i64 = value
                .parse()
                .map_err(|_| TangError::new("invalid-argument", "--width needs an integer."))?;
            if !(1..=1_000).contains(&parsed) {
                return Err(TangError::new(
                    "invalid-argument",
                    "--width must be between 1 and 1000.",
                ));
            }
            flags.width = Some(parsed);
        } else if let Some(value) = flag_value(args, &mut index, "--current-native-id")? {
            flags.current_native_id = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--label")? {
            flags.label = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--category")? {
            flags.category = Some(value);
        } else if let Some(value) = flag_value(args, &mut index, "--limit")? {
            let parsed: i64 = value.parse().map_err(|_| {
                TangError::new("invalid-limit", "Recall limit must be between 1 and 100.")
            })?;
            flags.limit = Some(parsed);
        } else if arg.starts_with('-') {
            return Err(TangError::new(
                "unknown-flag",
                format!("Unknown flag {arg}."),
            ));
        } else if !allow_positional || (flags.query.is_some() && !allow_many) {
            return Err(TangError::new(
                "unexpected-argument",
                format!("Unexpected argument {arg}."),
            ));
        } else {
            flags.positionals.push(arg.clone());
            if flags.query.is_none() {
                flags.query = Some(arg.clone());
            }
        }
        index += 1;
    }
    Ok(flags)
}

fn flag_value(args: &[String], index: &mut usize, name: &str) -> Result<Option<String>> {
    if args[*index] != name {
        return Ok(None);
    }
    let value = args
        .get(*index + 1)
        .cloned()
        .ok_or_else(|| TangError::new("invalid-argument", format!("{name} needs a value.")))?;
    *index += 1;
    Ok(Some(value))
}

fn sync_json(result: &SyncResult) -> String {
    compact(&json!({
        "removed": result.removed,
        "schema_version": 1,
        "skipped": result.skipped,
        "upserted": result.upserted,
        "warnings": result.warnings,
    }))
}

fn join_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags_with(args, false)?;
    let target = if flags.current {
        let native_id = flags.current_native_id.clone().ok_or_else(|| {
            TangError::new(
                "invalid-session",
                "tang join --current needs --current-native-id.",
            )
        })?;
        let (_cwd, project, project_db) = open_work(&flags)?;
        project_db
            .query_row(
                "SELECT session_handle FROM sessions
                 WHERE project_key = ?1 AND adapter = 'codex' AND native_id = ?2",
                rusqlite::params![project.key, native_id],
                |row| row.get::<_, String>(0),
            )
            .map_err(|_| {
                TangError::new(
                    "not-in-project",
                    "The current Codex session is not indexed in this project.",
                )
            })?
    } else {
        flags
            .into
            .clone()
            .ok_or_else(|| TangError::new("invalid-session", "tang join needs --into HANDLE."))?
    };
    let catalog_path = flags.catalog.unwrap_or_else(default_catalog_path);
    if !catalog_path.is_file() {
        return Err(TangError::new(
            "catalog-missing",
            "Tang has no global catalog; run tang catalog sync.",
        ));
    }
    let catalog = open_catalog(&catalog_path)?;
    let plan = resolve_join(&catalog, &flags.sources, &target)?;
    drop(catalog);
    let mut project_db = open_project_readwrite(&plan.database_path)?;
    let result = link_plan(&mut project_db, &plan, &rfc3339_now())?;
    if flags.json {
        writeln!(
            stdout,
            "{}",
            compact(&json!({
                "existing": result.existing,
                "inserted": result.inserted,
                "schema_version": 1,
                "source_handles": plan.source_handles,
                "source_ids": result.source_ids,
                "target_handle": plan.target_handle,
                "target_id": result.target_id,
            }))
        )
        .map_err(io_error)?;
    } else {
        writeln!(
            stdout,
            "Linked {} to {}; inserted {}, existing {}.",
            plan.source_handles.join(", "),
            plan.target_handle,
            result.inserted,
            result.existing
        )
        .map_err(io_error)?;
    }
    Ok(())
}

fn purge_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let flags = parse_flags(args)?;
    if !flags.all {
        return Err(TangError::new(
            "invalid-argument",
            "purge currently requires --all.",
        ));
    }
    if !flags.yes {
        return Err(TangError::new(
            "invalid-argument",
            "non-interactive purge requires --yes.",
        ));
    }
    let cwd = flags
        .cwd
        .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")));
    let project = resolve_project(&cwd)?;
    let catalog_path = flags.catalog.unwrap_or_else(default_catalog_path);
    let removed = forget_project(&catalog_path, &project.key)?;
    let database = flags
        .database
        .clone()
        .unwrap_or(project.database_path.clone());
    let project_removed = if database.is_file() {
        let mut project_db = crate::join::open_project_readwrite(&database)?;
        crate::project_purge::purge_project(&mut project_db, &project.key)?
    } else {
        (0, 0, 0)
    };
    let mut message = format!(
        "Removed {removed} global catalog rows and {} project sessions for {}. Native harness logs were not modified.",
        project_removed.0, project.display_name
    );
    if removed == 0 {
        message = format!(
            "Removed 0 global catalog rows for {}. Native harness logs were not modified.",
            project.display_name
        );
    }
    writeln!(stdout, "{message}").map_err(io_error)?;
    Ok(())
}

fn label_command(args: &[String], stdout: &mut dyn Write) -> Result<()> {
    let action = args.first().map(String::as_str).unwrap_or("");
    if action != "add" && action != "remove" {
        return Err(TangError::new(
            "unknown-command",
            "Use tang label add or tang label remove.",
        ));
    }
    let session = args
        .get(1)
        .cloned()
        .ok_or_else(|| TangError::new("invalid-session", "A catalog handle is required."))?;
    let label = args
        .get(2)
        .cloned()
        .ok_or_else(|| TangError::new("invalid-label", "A label is required."))?;
    let flags = parse_flags(&args[3..])?;
    let catalog_path = flags.catalog.unwrap_or_else(default_catalog_path);
    if !catalog_path.is_file() {
        return Err(TangError::new(
            "catalog-missing",
            "Tang has no global catalog; run tang catalog sync.",
        ));
    }
    let mut catalog = open_catalog(&catalog_path)?;
    let stamp = rfc3339_now();
    let handle = if action == "add" {
        add_label(&mut catalog, &session, &label, &stamp)?
    } else {
        remove_label(&mut catalog, &session, &label)?
    };
    let verb = if action == "add" {
        "Attached"
    } else {
        "Removed"
    };
    writeln!(stdout, "{verb} {label} on {handle}.").map_err(io_error)?;
    Ok(())
}

fn recall_json(query: Option<&str>, hits: &[RecallHit]) -> String {
    let results: Vec<Value> = hits
        .iter()
        .map(|hit| {
            json!({
                "catalog_handle": hit.catalog_handle,
                "category": hit.category,
                "harness": hit.harness,
                "health": hit.health,
                "labels": hit.labels,
                "native_available": hit.native_available,
                "project_display": hit.project_display,
                "project_handle": hit.project_handle,
                "snippet": hit.snippet,
                "source_id": hit.source_id,
                "summary": hit.summary,
                "title": hit.title,
                "updated_at": hit.updated_at,
            })
        })
        .collect();
    compact(&json!({
        "query": query,
        "result_count": hits.len(),
        "results": results,
        "schema_version": 1,
    }))
}

fn compact(value: &Value) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "{}".to_string())
}

fn io_error(error: std::io::Error) -> TangError {
    TangError::new("output", error.to_string())
}

pub fn catalog_file_is_private(path: &Path) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        path.metadata()
            .map(|metadata| metadata.permissions().mode() & 0o777 == 0o600)
            .unwrap_or(false)
    }
    #[cfg(not(unix))]
    {
        let _ = path;
        true
    }
}
