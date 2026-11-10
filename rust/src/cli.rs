//! Scriptable commands for the global catalog.

use crate::catalog::{
    add_label, default_catalog_path, forget_project, open_catalog, open_project_readonly, recall,
    remove_label, sync_project, RecallHit, RecallQuery, SyncResult,
};
use crate::error::{Result, TangError};
use crate::index_codex::{index_codex, CodexIndexResult};
use crate::index_grok::index_grok;
use crate::join::{link_plan, open_project_readwrite, resolve_join};
use crate::project::resolve_project;
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
        "join" => join_command(&args[1..], stdout),
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
  tang index [--cwd DIR] [--database PATH] [--codex-home PATH] [--grok-home PATH] [--json]
  tang catalog sync [--cwd DIR] [--database PATH] [--catalog PATH] [--json]
  tang recall [QUERY] [--label NAME] [--category NAME] [--harness NAME] [--limit N]
               [--include-unavailable] [--json] [--catalog PATH]
  tang label add|remove HANDLE LABEL [--catalog PATH]
  tang join --from HANDLE [--from HANDLE] --into HANDLE [--json] [--catalog PATH]
  tang purge --all --yes [--cwd DIR] [--catalog PATH]

Sync copies redacted capsules into ~/.tang/catalog.db and stores a category
plus an extractive summary. Recall searches that catalog and does not open
native logs. Join writes a continuation only when both sessions belong to
the same project.
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
    let explicit = flags.codex_home.is_some() || flags.grok_home.is_some();
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
}

fn parse_flags(args: &[String]) -> Result<Flags> {
    parse_flags_with(args, true)
}

fn parse_flags_with(args: &[String], allow_positional: bool) -> Result<Flags> {
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
        } else if let Some(value) = flag_value(args, &mut index, "--codex-home")? {
            flags.codex_home = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--grok-home")? {
            flags.grok_home = Some(PathBuf::from(value));
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
        } else if !allow_positional || flags.query.is_some() {
            return Err(TangError::new(
                "unexpected-argument",
                format!("Unexpected argument {arg}."),
            ));
        } else {
            flags.query = Some(arg.clone());
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
    let Some(target) = flags.into else {
        return Err(TangError::new(
            "invalid-session",
            "tang join needs --into HANDLE.",
        ));
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
    let mut message = format!(
        "Removed {removed} global catalog rows for {}. Native harness logs were not modified.",
        project.display_name
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
