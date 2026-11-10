//! Counts over the global catalog and the current project's confirmed graph.

use crate::error::{storage, Result};
use crate::graph::{components, load_multiverse};
use rusqlite::Connection;
use std::collections::BTreeMap;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Counts {
    pub sessions: i64,
    pub projects: i64,
    pub by_harness: BTreeMap<String, i64>,
    pub by_category: BTreeMap<String, i64>,
    pub by_label: BTreeMap<String, i64>,
    pub graph_sessions: i64,
    pub edges: i64,
    pub components: i64,
}

pub fn counts(
    catalog: Option<&Connection>,
    project_db: &Connection,
    project_key: &str,
) -> Result<Counts> {
    let map = load_multiverse(project_db, project_key)?;
    let (sessions, projects, by_harness, by_category, by_label) = if let Some(catalog) = catalog {
        (
            scalar(catalog, "SELECT COUNT(*) FROM catalog_sessions")?,
            scalar(
                catalog,
                "SELECT COUNT(DISTINCT project_key) FROM catalog_sessions",
            )?,
            grouped(
                catalog,
                "SELECT adapter, COUNT(*) FROM catalog_sessions GROUP BY adapter",
            )?,
            grouped(
                catalog,
                "SELECT category, COUNT(*) FROM catalog_sessions GROUP BY category",
            )?,
            grouped(
                catalog,
                "SELECT label, COUNT(*) FROM catalog_labels GROUP BY label",
            )?,
        )
    } else {
        (0, 0, BTreeMap::new(), BTreeMap::new(), BTreeMap::new())
    };
    Ok(Counts {
        sessions,
        projects,
        by_harness,
        by_category,
        by_label,
        graph_sessions: map.nodes.len() as i64,
        edges: map.edges.len() as i64,
        components: components(&map).len() as i64,
    })
}

pub fn render_counts(counts: &Counts, catalog_present: bool) -> String {
    let mut lines = Vec::new();
    if catalog_present {
        lines.push(format!(
            "Catalog: {} {} across {} {}",
            counts.sessions,
            plural(counts.sessions, "session", "sessions"),
            counts.projects,
            plural(counts.projects, "project", "projects")
        ));
        push_groups(&mut lines, "harness", &counts.by_harness);
        push_groups(&mut lines, "category", &counts.by_category);
        push_groups(&mut lines, "label", &counts.by_label);
    } else {
        lines.push("Catalog: absent".to_string());
    }
    lines.push(format!(
        "Graph: {} {}, {} {}, {} {}",
        counts.graph_sessions,
        plural(counts.graph_sessions, "session", "sessions"),
        counts.edges,
        plural(counts.edges, "edge", "edges"),
        counts.components,
        plural(counts.components, "component", "components")
    ));
    lines.push(String::new());
    lines.join("\n")
}

fn push_groups(lines: &mut Vec<String>, name: &str, groups: &BTreeMap<String, i64>) {
    if groups.is_empty() {
        lines.push(format!("  {name}: none"));
        return;
    }
    lines.push(format!("  {name}:"));
    for (key, count) in groups {
        lines.push(format!("    {key}: {count}"));
    }
}

fn plural(count: i64, one: &'static str, many: &'static str) -> &'static str {
    if count == 1 {
        one
    } else {
        many
    }
}

fn scalar(connection: &Connection, sql: &str) -> Result<i64> {
    connection
        .query_row(sql, [], |row| row.get(0))
        .map_err(storage)
}

fn grouped(connection: &Connection, sql: &str) -> Result<BTreeMap<String, i64>> {
    let mut statement = connection.prepare(sql).map_err(storage)?;
    let rows = statement
        .query_map([], |row| {
            Ok((row.get::<_, String>(0)?, row.get::<_, i64>(1)?))
        })
        .map_err(storage)?;
    let mut groups = BTreeMap::new();
    for row in rows {
        let (key, count) = row.map_err(storage)?;
        groups.insert(key, count);
    }
    Ok(groups)
}
