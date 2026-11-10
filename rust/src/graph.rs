//! Confirmed continuation graph. A Multiverse is one weakly connected component.

use crate::error::{storage, Result};
use rusqlite::Connection;
use std::collections::{BTreeMap, BTreeSet, HashMap};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MapNode {
    pub source_id: String,
    pub handle: String,
    pub harness: String,
    pub title: String,
    pub updated_at: String,
    pub native_available: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MapEdge {
    pub source_id: String,
    pub target_id: String,
    pub confirmed_at: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Multiverse {
    pub nodes: Vec<MapNode>,
    pub edges: Vec<MapEdge>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Component {
    pub nodes: Vec<MapNode>,
    pub edges: Vec<MapEdge>,
    pub timelines: Vec<Vec<String>>,
}

const TIMELINE_LIMIT: usize = 8;

pub fn load_multiverse(database: &Connection, project_key: &str) -> Result<Multiverse> {
    let mut nodes = database
        .prepare(
            "SELECT source_id, COALESCE(session_handle, ''), adapter,
                    COALESCE(title, ''), updated_at, native_available
             FROM sessions
             WHERE project_key = ?1
             ORDER BY session_handle, source_id",
        )
        .map_err(storage)?
        .query_map([project_key], |row| {
            Ok(MapNode {
                source_id: row.get(0)?,
                handle: row.get(1)?,
                harness: row.get(2)?,
                title: row.get(3)?,
                updated_at: row.get(4)?,
                native_available: row.get::<_, i64>(5)? != 0,
            })
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    for node in &mut nodes {
        if node.handle.is_empty() {
            node.handle = node.source_id.clone();
        }
        if node.title.is_empty() {
            node.title = "(untitled)".to_string();
        }
    }
    let edges = database
        .prepare(
            "SELECT source_id, target_id, confirmed_at
             FROM continuation_edges
             WHERE project_key = ?1
             ORDER BY confirmed_at, source_id, target_id",
        )
        .map_err(storage)?
        .query_map([project_key], |row| {
            Ok(MapEdge {
                source_id: row.get(0)?,
                target_id: row.get(1)?,
                confirmed_at: row.get(2)?,
            })
        })
        .map_err(storage)?
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    Ok(Multiverse { nodes, edges })
}

pub fn components(map: &Multiverse) -> Vec<Component> {
    let mut parent: HashMap<&str, &str> = HashMap::new();
    for node in &map.nodes {
        parent.insert(node.source_id.as_str(), node.source_id.as_str());
    }
    fn find<'a>(parent: &mut HashMap<&'a str, &'a str>, id: &'a str) -> &'a str {
        let mut current = id;
        while parent.get(current).copied().unwrap_or(current) != current {
            current = parent[current];
        }
        let root = current;
        let mut current = id;
        while current != root {
            let next = parent[current];
            parent.insert(current, root);
            current = next;
        }
        root
    }
    for edge in &map.edges {
        if !parent.contains_key(edge.source_id.as_str())
            || !parent.contains_key(edge.target_id.as_str())
        {
            continue;
        }
        let left = find(&mut parent, edge.source_id.as_str());
        let right = find(&mut parent, edge.target_id.as_str());
        if left != right {
            parent.insert(left, right);
        }
    }
    let mut grouped: BTreeMap<&str, Vec<&MapNode>> = BTreeMap::new();
    for node in &map.nodes {
        let root = find(&mut parent, node.source_id.as_str());
        grouped.entry(root).or_default().push(node);
    }
    let mut components = grouped
        .into_values()
        .map(|mut nodes| {
            nodes.sort_by(|left, right| {
                left.handle
                    .cmp(&right.handle)
                    .then_with(|| left.source_id.cmp(&right.source_id))
            });
            let ids: BTreeSet<&str> = nodes.iter().map(|node| node.source_id.as_str()).collect();
            let edges: Vec<MapEdge> = map
                .edges
                .iter()
                .filter(|edge| {
                    ids.contains(edge.source_id.as_str()) && ids.contains(edge.target_id.as_str())
                })
                .cloned()
                .collect();
            let timelines = timelines(&nodes, &edges);
            Component {
                nodes: nodes.into_iter().cloned().collect(),
                edges,
                timelines,
            }
        })
        .collect::<Vec<_>>();
    components.sort_by(|left, right| {
        left.nodes[0]
            .handle
            .cmp(&right.nodes[0].handle)
            .then_with(|| left.nodes[0].source_id.cmp(&right.nodes[0].source_id))
    });
    components
}

pub fn render_map(project_display: &str, map: &Multiverse) -> String {
    if map.nodes.is_empty() {
        return format!("Multiverse · {project_display}\n\nNo indexed sessions.\n");
    }
    let parts = components(map);
    let component_word = if parts.len() == 1 {
        "component"
    } else {
        "components"
    };
    let mut lines = vec![format!(
        "Multiverse · {project_display} · {} sessions · {} edges · {} {component_word}",
        map.nodes.len(),
        map.edges.len(),
        parts.len()
    )];
    for (index, component) in parts.iter().enumerate() {
        lines.push(String::new());
        lines.push(format!("Component {}", index + 1));
        if component.edges.is_empty() {
            for node in &component.nodes {
                lines.push(format!("  {}  [ISOLATED]", label(node)));
            }
            continue;
        }
        let incoming = degree(&component.edges, true);
        let outgoing = degree(&component.edges, false);
        let by_id: BTreeMap<&str, &MapNode> = component
            .nodes
            .iter()
            .map(|node| (node.source_id.as_str(), node))
            .collect();
        for edge in &component.edges {
            let Some(source) = by_id.get(edge.source_id.as_str()) else {
                continue;
            };
            let Some(target) = by_id.get(edge.target_id.as_str()) else {
                continue;
            };
            lines.push(format!(
                "  {} --> {}  [{}]",
                label(source),
                label(target),
                shape(
                    outgoing
                        .get(source.source_id.as_str())
                        .copied()
                        .unwrap_or(0),
                    incoming
                        .get(target.source_id.as_str())
                        .copied()
                        .unwrap_or(0)
                )
            ));
        }
        if !component.timelines.is_empty() {
            lines.push("  Timelines".to_string());
            for lane in &component.timelines {
                lines.push(format!("  {}", lane.join(" --> ")));
            }
        }
    }
    lines.push(String::new());
    lines.join("\n")
}

fn label(node: &MapNode) -> String {
    let title: String = node.title.chars().take(42).collect();
    format!("{} {} {title}", node.handle, node.harness)
}

fn degree(edges: &[MapEdge], incoming: bool) -> BTreeMap<&str, usize> {
    let mut counts = BTreeMap::new();
    for edge in edges {
        let id = if incoming {
            edge.target_id.as_str()
        } else {
            edge.source_id.as_str()
        };
        *counts.entry(id).or_insert(0) += 1;
    }
    counts
}

fn shape(outgoing: usize, incoming: usize) -> &'static str {
    match (outgoing > 1, incoming > 1) {
        (true, true) => "BRANCH MERGE",
        (false, true) => "MERGE",
        (true, false) => "BRANCH",
        (false, false) => "LINK",
    }
}

fn timelines(nodes: &[&MapNode], edges: &[MapEdge]) -> Vec<Vec<String>> {
    let handles: BTreeMap<&str, &str> = nodes
        .iter()
        .map(|node| (node.source_id.as_str(), node.handle.as_str()))
        .collect();
    let mut outgoing: BTreeMap<&str, Vec<&str>> = BTreeMap::new();
    let mut incoming = BTreeSet::new();
    for edge in edges {
        outgoing
            .entry(edge.source_id.as_str())
            .or_default()
            .push(edge.target_id.as_str());
        incoming.insert(edge.target_id.as_str());
    }
    for targets in outgoing.values_mut() {
        targets.sort_by_key(|id| handles.get(*id).copied().unwrap_or(""));
    }
    let mut roots: Vec<&str> = nodes
        .iter()
        .map(|node| node.source_id.as_str())
        .filter(|id| !incoming.contains(id))
        .collect();
    roots.sort_by_key(|id| handles.get(*id).copied().unwrap_or(""));
    let mut lanes = Vec::new();
    for root in roots {
        let mut path = Vec::new();
        let mut seen = BTreeSet::new();
        walk(root, &outgoing, &handles, &mut path, &mut seen, &mut lanes);
        if lanes.len() >= TIMELINE_LIMIT {
            break;
        }
    }
    lanes
}

fn walk(
    id: &str,
    outgoing: &BTreeMap<&str, Vec<&str>>,
    handles: &BTreeMap<&str, &str>,
    path: &mut Vec<String>,
    seen: &mut BTreeSet<String>,
    lanes: &mut Vec<Vec<String>>,
) {
    if lanes.len() >= TIMELINE_LIMIT || !seen.insert(id.to_string()) {
        return;
    }
    path.push(handles.get(id).copied().unwrap_or(id).to_string());
    let next = outgoing.get(id).map(Vec::as_slice).unwrap_or(&[]);
    if next.is_empty() && path.len() > 1 {
        lanes.push(path.clone());
    }
    for target in next {
        walk(target, outgoing, handles, path, seen, lanes);
        if lanes.len() >= TIMELINE_LIMIT {
            break;
        }
    }
    path.pop();
    seen.remove(id);
}

#[cfg(test)]
mod tests {
    use super::{components, render_map, MapEdge, MapNode, Multiverse};

    fn node(id: &str, handle: &str) -> MapNode {
        MapNode {
            source_id: id.into(),
            handle: handle.into(),
            harness: "codex".into(),
            title: handle.into(),
            updated_at: "2026-11-09T20:00:00Z".into(),
            native_available: true,
        }
    }

    #[test]
    fn a_merge_is_one_component_with_two_lanes() {
        let map = Multiverse {
            nodes: vec![node("a", "C1"), node("b", "G1"), node("c", "C2")],
            edges: vec![
                MapEdge {
                    source_id: "a".into(),
                    target_id: "c".into(),
                    confirmed_at: "2026-11-09T21:00:00Z".into(),
                },
                MapEdge {
                    source_id: "b".into(),
                    target_id: "c".into(),
                    confirmed_at: "2026-11-09T21:00:00Z".into(),
                },
            ],
        };
        let parts = components(&map);
        assert_eq!(parts.len(), 1);
        assert_eq!(
            parts[0].timelines,
            vec![
                vec!["C1".to_string(), "C2".to_string()],
                vec!["G1".to_string(), "C2".to_string()]
            ]
        );
        let rendered = render_map("work", &map);
        assert!(rendered.contains("[MERGE]"));
        assert!(rendered.contains("C1 codex C1 --> C2 codex C2"));
    }
}
