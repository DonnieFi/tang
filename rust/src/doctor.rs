//! Local readiness checks for SQLite and FTS5.
//!
//! This does not scan harness homes or open a network connection. A missing
//! database is reported as not indexed and is not created.

use rusqlite::{Connection, OpenFlags};
use serde_json::json;
use std::path::Path;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DoctorCheck {
    pub component: String,
    pub status: String,
    pub message: String,
}

pub fn run_doctor(database: &Path) -> Vec<DoctorCheck> {
    vec![sqlite_check(database), fts5_check()]
}

pub fn render_doctor(checks: &[DoctorCheck]) -> String {
    let mut lines = Vec::with_capacity(checks.len() + 1);
    for check in checks {
        lines.push(format!(
            "{}: {} — {}",
            check.component, check.status, check.message
        ));
    }
    lines.push(String::new());
    lines.join("\n")
}

pub fn doctor_failed(checks: &[DoctorCheck]) -> bool {
    checks.iter().any(|check| check.status != "ready")
}

pub fn doctor_json(checks: &[DoctorCheck]) -> String {
    let items: Vec<serde_json::Value> = checks
        .iter()
        .map(|check| {
            json!({
                "component": check.component,
                "message": check.message,
                "status": check.status,
            })
        })
        .collect();
    let status = if checks.iter().all(|check| check.status == "ready") {
        "ready"
    } else {
        "unavailable"
    };
    serde_json::to_string(&json!({
        "checks": items,
        "schema_version": 1,
        "status": status,
    }))
    .unwrap_or_else(|_| "{}".to_string())
}

fn sqlite_check(database: &Path) -> DoctorCheck {
    if !database.exists() {
        return check("sqlite", "unavailable", "The project has not been indexed.");
    }
    match Connection::open_with_flags(database, OpenFlags::SQLITE_OPEN_READ_ONLY) {
        Ok(connection) => {
            drop(connection);
            check("sqlite", "ready", "SQLite storage is ready.")
        }
        Err(_) => check("sqlite", "unavailable", "SQLite storage is unavailable."),
    }
}

fn fts5_check() -> DoctorCheck {
    let Ok(connection) = Connection::open_in_memory() else {
        return check("fts5", "unavailable", "SQLite FTS5 is unavailable.");
    };
    match connection
        .execute_batch("CREATE VIRTUAL TABLE IF NOT EXISTS tang_doctor_fts USING fts5(body)")
    {
        Ok(()) => check("fts5", "ready", "SQLite FTS5 is available."),
        Err(_) => check("fts5", "unavailable", "SQLite FTS5 is unavailable."),
    }
}

fn check(component: &str, status: &str, message: &str) -> DoctorCheck {
    DoctorCheck {
        component: component.to_string(),
        status: status.to_string(),
        message: message.to_string(),
    }
}
