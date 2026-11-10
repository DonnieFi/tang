//! Scriptable commands for the global catalog.

use crate::catalog::{
    default_catalog_path, open_catalog, open_project_readonly, recall, sync_project, RecallHit,
    SyncResult,
};
use crate::error::{Result, TangError};
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
        "catalog" => catalog_command(&args[1..], stdout),
        "recall" => recall_command(&args[1..], stdout),
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
  tang catalog sync [--cwd DIR] [--database PATH] [--catalog PATH] [--json]
  tang recall QUERY [--harness NAME] [--limit N] [--include-unavailable] [--json] [--catalog PATH]

Sync copies redacted capsules from the current project's .tang/tang.db into
~/.tang/catalog.db. Recall searches that catalog and does not open native logs.
";

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
    let Some(query) = flags.query else {
        return Err(TangError::new("empty-query", "A recall query is required."));
    };
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
        &query,
        flags.harness.as_deref(),
        limit,
        flags.include_unavailable,
    )?;
    if flags.json {
        writeln!(stdout, "{}", recall_json(&query, &hits)).map_err(io_error)?;
    } else if hits.is_empty() {
        writeln!(stdout, "No matching sessions.").map_err(io_error)?;
    } else {
        for hit in &hits {
            writeln!(
                stdout,
                "{}\t{}\t{}\t{}",
                hit.catalog_handle,
                hit.harness,
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
}

fn parse_flags(args: &[String]) -> Result<Flags> {
    let mut flags = Flags {
        catalog: None,
        database: None,
        cwd: None,
        query: None,
        json: false,
        harness: None,
        limit: None,
        include_unavailable: false,
    };
    let mut index = 0;
    while index < args.len() {
        let arg = &args[index];
        if arg == "--json" {
            flags.json = true;
        } else if arg == "--include-unavailable" {
            flags.include_unavailable = true;
        } else if let Some(value) = flag_value(args, &mut index, "--catalog")? {
            flags.catalog = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--database")? {
            flags.database = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--cwd")? {
            flags.cwd = Some(PathBuf::from(value));
        } else if let Some(value) = flag_value(args, &mut index, "--harness")? {
            flags.harness = Some(value);
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
        } else if flags.query.is_some() {
            return Err(TangError::new(
                "unknown-argument",
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

fn recall_json(query: &str, hits: &[RecallHit]) -> String {
    let results: Vec<Value> = hits
        .iter()
        .map(|hit| {
            json!({
                "catalog_handle": hit.catalog_handle,
                "harness": hit.harness,
                "health": hit.health,
                "native_available": hit.native_available,
                "project_display": hit.project_display,
                "project_handle": hit.project_handle,
                "snippet": hit.snippet,
                "source_id": hit.source_id,
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
