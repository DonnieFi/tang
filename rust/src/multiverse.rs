//! Multiverse Map. One weakly connected component, drawn as left-to-right rails.
//!
//! Timeline lanes are root-to-leaf paths. The woven network places sessions in
//! columns by depth and joins confirmed edges with vertical rails.

use crate::error::{storage, Result, TangError};
use crate::redact::{redact, ContentKind};
use rusqlite::{params, Connection};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, HashMap};

const MAX_TIMELINE_LANES: usize = 8;
const NORTH: u8 = 0b0001;
const SOUTH: u8 = 0b0010;
const EAST: u8 = 0b0100;
const WEST: u8 = 0b1000;

/// Options for one Multiverse Map render.
#[derive(Debug, Clone)]
pub struct MapOptions {
    pub width: usize,
    pub ascii_only: bool,
    pub anchor: Option<String>,
    pub current_handle: Option<String>,
}

#[derive(Debug, Clone)]
struct Node {
    source_id: String,
    handle: String,
    harness: String,
    title: String,
    updated_at: String,
    health: String,
    native_available: bool,
    current: bool,
}

#[derive(Debug, Clone)]
struct Edge {
    source_id: String,
    target_id: String,
    confirmed_at: String,
}

struct Component {
    nodes: Vec<Node>,
    edges: Vec<Edge>,
    paths: Vec<Vec<usize>>,
    truncated: bool,
}

/// Render the project Multiverse Map as terminal text.
pub fn render_project_map(
    database: &Connection,
    project_key: &str,
    options: &MapOptions,
) -> Result<String> {
    let components = load_components(database, project_key, options)?;
    Ok(render_text(&components, options))
}

/// Render the same map as a deterministic `schema_version: 1` JSON document.
pub fn render_project_map_json(
    database: &Connection,
    project_key: &str,
    options: &MapOptions,
) -> Result<String> {
    let components = load_components(database, project_key, options)?;
    render_json(&components)
}

fn load_components(
    database: &Connection,
    project_key: &str,
    options: &MapOptions,
) -> Result<Vec<Component>> {
    let nodes = load_nodes(database, project_key, options)?;
    if let Some(token) = &options.anchor {
        let found = nodes
            .iter()
            .any(|node| node.handle == *token || node.source_id == *token);
        if !found {
            return Err(TangError::new(
                "not-in-project",
                format!("{token} is not an indexed session in this project"),
            ));
        }
    }
    let edges = load_edges(database, project_key)?;
    let mut components = build_components(nodes, edges);
    if let Some(token) = &options.anchor {
        components.retain(|component| {
            component
                .nodes
                .iter()
                .any(|node| node.handle == *token || node.source_id == *token)
        });
    }
    Ok(components)
}

fn load_nodes(database: &Connection, project_key: &str, options: &MapOptions) -> Result<Vec<Node>> {
    let mut statement = database
        .prepare(
            "SELECT source_id, COALESCE(session_handle, ''), adapter,
                    COALESCE(title, ''), updated_at, COALESCE(health, ''),
                    COALESCE(native_available, 1)
             FROM sessions
             WHERE project_key = ?1",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map(params![project_key], |row| {
            Ok(Node {
                source_id: row.get(0)?,
                handle: row.get(1)?,
                harness: row.get(2)?,
                title: row.get(3)?,
                updated_at: row.get(4)?,
                health: row.get(5)?,
                native_available: row.get::<_, i64>(6)? != 0,
                current: false,
            })
        })
        .map_err(storage)?;
    let mut nodes = rows
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    for node in &mut nodes {
        if node.handle.is_empty() {
            node.handle.clone_from(&node.source_id);
        }
        let redacted = redact(&node.title, ContentKind::Title);
        node.title = if redacted.trim().is_empty() {
            "(untitled)".to_string()
        } else {
            redacted
        };
        if let Some(token) = &options.current_handle {
            node.current = node.handle == *token || node.source_id == *token;
        }
    }
    nodes.sort_by(|left, right| {
        left.updated_at
            .cmp(&right.updated_at)
            .then_with(|| left.source_id.cmp(&right.source_id))
    });
    Ok(nodes)
}

fn load_edges(database: &Connection, project_key: &str) -> Result<Vec<Edge>> {
    let mut statement = database
        .prepare(
            "SELECT source_id, target_id, COALESCE(confirmed_at, '')
             FROM continuation_edges
             WHERE project_key = ?1",
        )
        .map_err(storage)?;
    let rows = statement
        .query_map(params![project_key], |row| {
            Ok(Edge {
                source_id: row.get(0)?,
                target_id: row.get(1)?,
                confirmed_at: row.get(2)?,
            })
        })
        .map_err(storage)?;
    let mut edges = rows
        .collect::<std::result::Result<Vec<_>, _>>()
        .map_err(storage)?;
    edges.sort_by(|left, right| {
        left.confirmed_at
            .cmp(&right.confirmed_at)
            .then_with(|| left.source_id.cmp(&right.source_id))
            .then_with(|| left.target_id.cmp(&right.target_id))
    });
    Ok(edges)
}

fn build_components(nodes: Vec<Node>, edges: Vec<Edge>) -> Vec<Component> {
    let index = index_by_source(&nodes);
    let mut neighbors = vec![Vec::new(); nodes.len()];
    let mut clean_edges = Vec::new();
    for edge in edges {
        let Some(&source) = index.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(&target) = index.get(edge.target_id.as_str()) else {
            continue;
        };
        if source == target {
            continue;
        }
        neighbors[source].push(target);
        neighbors[target].push(source);
        clean_edges.push(edge);
    }
    dedupe_edges(&mut clean_edges);

    let mut seen = vec![false; nodes.len()];
    let mut groups = Vec::new();
    for start in 0..nodes.len() {
        if seen[start] {
            continue;
        }
        let mut stack = vec![start];
        seen[start] = true;
        let mut group = Vec::new();
        while let Some(node) = stack.pop() {
            group.push(node);
            for &next in &neighbors[node] {
                if !seen[next] {
                    seen[next] = true;
                    stack.push(next);
                }
            }
        }
        groups.push(group);
    }

    let mut components = Vec::new();
    for group in groups {
        let mut member_nodes: Vec<Node> = group
            .into_iter()
            .map(|index| nodes[index].clone())
            .collect();
        member_nodes.sort_by(|left, right| {
            left.updated_at
                .cmp(&right.updated_at)
                .then_with(|| left.source_id.cmp(&right.source_id))
        });
        let member_ids: BTreeSet<&str> = member_nodes
            .iter()
            .map(|node| node.source_id.as_str())
            .collect();
        let mut member_edges: Vec<Edge> = clean_edges
            .iter()
            .filter(|edge| {
                member_ids.contains(edge.source_id.as_str())
                    && member_ids.contains(edge.target_id.as_str())
            })
            .cloned()
            .collect();
        dedupe_edges(&mut member_edges);
        let (paths, truncated) = root_to_leaf(&member_nodes, &member_edges);
        components.push(Component {
            nodes: member_nodes,
            edges: member_edges,
            paths,
            truncated,
        });
    }
    components.sort_by(|left, right| {
        let left_id = left
            .nodes
            .iter()
            .map(|node| node.source_id.as_str())
            .min()
            .unwrap_or("");
        let right_id = right
            .nodes
            .iter()
            .map(|node| node.source_id.as_str())
            .min()
            .unwrap_or("");
        left_id.cmp(right_id)
    });
    components
}

fn dedupe_edges(edges: &mut Vec<Edge>) {
    edges.sort_by(|left, right| {
        left.source_id
            .cmp(&right.source_id)
            .then_with(|| left.target_id.cmp(&right.target_id))
            .then_with(|| left.confirmed_at.cmp(&right.confirmed_at))
    });
    let mut unique = Vec::new();
    for edge in edges.drain(..) {
        let duplicate = unique.last().is_some_and(|previous: &Edge| {
            previous.source_id == edge.source_id && previous.target_id == edge.target_id
        });
        if !duplicate {
            unique.push(edge);
        }
    }
    unique.sort_by(|left, right| {
        left.confirmed_at
            .cmp(&right.confirmed_at)
            .then_with(|| left.source_id.cmp(&right.source_id))
            .then_with(|| left.target_id.cmp(&right.target_id))
    });
    *edges = unique;
}

fn index_by_source(nodes: &[Node]) -> HashMap<&str, usize> {
    nodes
        .iter()
        .enumerate()
        .map(|(index, node)| (node.source_id.as_str(), index))
        .collect()
}

/// Depth-first root-to-leaf paths. Discovery prefers smaller source ids, then
/// the kept lanes are sorted. The cap is one past the limit so truncation is
/// visible when another leaf still exists.
fn root_to_leaf(nodes: &[Node], edges: &[Edge]) -> (Vec<Vec<usize>>, bool) {
    let index = index_by_source(nodes);
    let mut outgoing = vec![Vec::new(); nodes.len()];
    for edge in edges {
        let Some(&source) = index.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(&target) = index.get(edge.target_id.as_str()) else {
            continue;
        };
        outgoing[source].push(target);
    }
    for targets in &mut outgoing {
        targets.sort_by(|&left, &right| nodes[left].source_id.cmp(&nodes[right].source_id));
        targets.dedup();
    }
    let mut incoming = vec![0usize; nodes.len()];
    for targets in &outgoing {
        for &target in targets {
            incoming[target] += 1;
        }
    }
    let mut roots: Vec<usize> = (0..nodes.len())
        .filter(|&node| incoming[node] == 0)
        .collect();
    roots.sort_by(|&left, &right| nodes[left].source_id.cmp(&nodes[right].source_id));
    let mut stack: Vec<(usize, Vec<usize>)> = roots
        .into_iter()
        .rev()
        .map(|root| (root, Vec::new()))
        .collect();
    let mut paths = Vec::new();
    while !stack.is_empty() && paths.len() <= MAX_TIMELINE_LANES {
        let (node, path) = stack.pop().expect("stack is non-empty");
        if path.contains(&node) {
            continue;
        }
        let mut current = path;
        current.push(node);
        if outgoing[node].is_empty() {
            paths.push(current);
            continue;
        }
        for &target in outgoing[node].iter().rev() {
            stack.push((target, current.clone()));
        }
    }
    let truncated = paths.len() > MAX_TIMELINE_LANES || !stack.is_empty();
    paths.truncate(MAX_TIMELINE_LANES);
    paths.sort_by(|left, right| {
        left.iter()
            .map(|&node| nodes[node].source_id.as_str())
            .cmp(right.iter().map(|&node| nodes[node].source_id.as_str()))
    });
    (paths, truncated)
}

fn render_text(components: &[Component], options: &MapOptions) -> String {
    let session_count: usize = components
        .iter()
        .map(|component| component.nodes.len())
        .sum();
    if session_count == 0 {
        return "TANG MULTIVERSE MAP\n\nNo indexed sessions.\n".to_string();
    }
    let edge_count: usize = components
        .iter()
        .map(|component| component.edges.len())
        .sum();
    let ascii = ascii_rails(options);
    let mut lines = vec![
        "TANG MULTIVERSE MAP".to_string(),
        format!(
            "{}{}{}{}{}",
            count_phrase(components.len(), "component"),
            if ascii { " | " } else { " · " },
            count_phrase(session_count, "session"),
            if ascii { " | " } else { " · " },
            count_phrase(edge_count, "edge"),
        ),
        if ascii {
            "confirmed only | [ACTIVE]".to_string()
        } else {
            "confirmed only · ★ active".to_string()
        },
        String::new(),
    ];
    for (index, component) in components.iter().enumerate() {
        if components.len() > 1 {
            lines.push(format!("COMPONENT {} OF {}", index + 1, components.len()));
            lines.push(String::new());
        }
        lines.push(network_heading(ascii));
        lines.extend(render_network(component, ascii, options.width));
        lines.push(String::new());
        lines.push(lane_heading(component, ascii));
        lines.extend(render_lanes(component, ascii));
        lines.push(String::new());
        lines.push("SESSION DETAIL".to_string());
        for node in &component.nodes {
            lines.push(detail_line(node, ascii));
        }
        lines.push(String::new());
    }
    let mut text = lines.join("\n");
    if !text.ends_with('\n') {
        text.push('\n');
    }
    text
}

fn ascii_rails(options: &MapOptions) -> bool {
    options.ascii_only || options.width < 72
}

fn count_phrase(count: usize, noun: &str) -> String {
    if count == 1 {
        format!("1 {noun}")
    } else {
        format!("{count} {noun}s")
    }
}

fn network_heading(ascii: bool) -> String {
    if ascii {
        "MULTIVERSE NETWORK | TIME FLOWS -->".to_string()
    } else {
        "MULTIVERSE NETWORK · TIME FLOWS →".to_string()
    }
}

fn lane_heading(component: &Component, ascii: bool) -> String {
    let separator = if ascii { " | " } else { " · " };
    let count = component.paths.len();
    if component.truncated {
        format!("TIMELINE LANES{separator}FIRST {count} ROOT-TO-LEAF PATHS (more were omitted)")
    } else {
        format!("TIMELINE LANES{separator}{count} ROOT-TO-LEAF PATHS")
    }
}

fn render_lanes(component: &Component, ascii: bool) -> Vec<String> {
    let (incoming, outgoing) = degrees(&component.nodes, &component.edges);
    let connector = if ascii { "-->" } else { "──▶" };
    let mut lines = Vec::new();
    for (number, path) in component.paths.iter().enumerate() {
        let mut line = format!("LANE {:02}  ", number + 1);
        for (offset, &node) in path.iter().enumerate() {
            if offset > 0 {
                let shape = edge_shape(outgoing[path[offset - 1]], incoming[node]);
                line.push_str(&format!(" {connector} [{shape}] "));
            }
            line.push_str(&lane_label(&component.nodes[node], ascii));
        }
        if component.edges.is_empty() {
            line.push_str(" [ISOLATED]");
        }
        lines.push(line);
    }
    lines
}

fn lane_label(node: &Node, ascii: bool) -> String {
    let separator = if ascii { " | " } else { " · " };
    let mut text = String::new();
    if node.current {
        text.push_str("ACTIVE ");
    }
    text.push_str(&safe(&node.handle, ascii));
    text.push_str(separator);
    text.push_str(&safe(&node.harness, ascii));
    if !node.native_available {
        text.push_str(separator);
        text.push_str("unavailable");
    }
    text
}

fn detail_line(node: &Node, ascii: bool) -> String {
    let health = if node.health.is_empty() {
        "unverified"
    } else {
        node.health.as_str()
    };
    let mut line = String::new();
    if node.current {
        line.push_str("ACTIVE ");
    }
    line.push_str(&safe(&node.handle, ascii));
    line.push_str(" | ");
    line.push_str(&safe(&node.harness, ascii));
    line.push_str(" | ");
    line.push_str(&safe(&node.updated_at, ascii));
    line.push_str(" | ");
    line.push_str(&safe(health, ascii));
    line.push_str(" | ");
    line.push_str(&safe(&node.title, ascii));
    if !node.native_available {
        line.push_str(" | source unavailable");
    }
    line
}

fn edge_shape(outgoing: usize, incoming: usize) -> &'static str {
    match (outgoing > 1, incoming > 1) {
        (true, true) => "MERGE + BRANCH",
        (false, true) => "MERGE",
        (true, false) => "BRANCH",
        (false, false) => "CONTINUE",
    }
}

fn degrees(nodes: &[Node], edges: &[Edge]) -> (Vec<usize>, Vec<usize>) {
    let index = index_by_source(nodes);
    let mut incoming = vec![0usize; nodes.len()];
    let mut outgoing = vec![0usize; nodes.len()];
    for edge in edges {
        let Some(&source) = index.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(&target) = index.get(edge.target_id.as_str()) else {
            continue;
        };
        outgoing[source] += 1;
        incoming[target] += 1;
    }
    (incoming, outgoing)
}

fn render_network(component: &Component, ascii: bool, width: usize) -> Vec<String> {
    if component.nodes.is_empty() {
        return Vec::new();
    }
    let labels: Vec<String> = component
        .nodes
        .iter()
        .map(|node| network_label(node, ascii))
        .collect();
    let (depth, parents) = column_depth(component);
    let y = column_rows(&depth, &parents);
    let max_depth = depth.iter().copied().max().unwrap_or(0);
    let max_label = labels
        .iter()
        .map(|label| label.chars().count())
        .max()
        .unwrap_or(1);
    let step = column_step(width, max_depth, max_label);
    let x: Vec<i64> = depth
        .iter()
        .map(|&level| i64::try_from(level).unwrap_or(0) * step)
        .collect();

    let mut rails: HashMap<(i64, i64), u8> = HashMap::new();
    let mut arrows = Vec::new();
    let index = index_by_source(&component.nodes);
    for edge in &component.edges {
        let Some(&source) = index.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(&target) = index.get(edge.target_id.as_str()) else {
            continue;
        };
        let source_x = x[source] + i64::try_from(labels[source].chars().count()).unwrap_or(0) + 1;
        let target_x = x[target];
        draw_edge(&mut rails, source_x, y[source], target_x, y[target], ascii);
        arrows.push((target_x - 2, y[target]));
    }
    let label_stamps: Vec<(i64, i64, String)> = component
        .nodes
        .iter()
        .enumerate()
        .map(|(node, _)| (x[node], y[node], labels[node].clone()))
        .collect();
    paint(&rails, &arrows, &label_stamps, ascii)
}

fn network_label(node: &Node, ascii: bool) -> String {
    let mark = if node.current {
        if ascii {
            "*"
        } else {
            "★"
        }
    } else if !node.native_available {
        if ascii {
            "x"
        } else {
            "×"
        }
    } else {
        ""
    };
    format!(
        "{mark}{} {}",
        safe(&node.handle, ascii),
        safe(&node.harness, ascii)
    )
}

fn column_depth(component: &Component) -> (Vec<usize>, Vec<Vec<usize>>) {
    let count = component.nodes.len();
    let index = index_by_source(&component.nodes);
    let mut children = vec![Vec::new(); count];
    for edge in &component.edges {
        let Some(&source) = index.get(edge.source_id.as_str()) else {
            continue;
        };
        let Some(&target) = index.get(edge.target_id.as_str()) else {
            continue;
        };
        children[source].push(target);
    }
    for targets in &mut children {
        targets.sort_unstable();
        targets.dedup();
    }
    let mut parents = vec![Vec::new(); count];
    let mut indegree = vec![0usize; count];
    for (source, targets) in children.iter().enumerate() {
        for &target in targets {
            parents[target].push(source);
            indegree[target] += 1;
        }
    }
    let mut depth = vec![0usize; count];
    let mut pending: BTreeSet<usize> = (0..count).filter(|&node| indegree[node] == 0).collect();
    let mut remaining = indegree;
    while let Some(source) = pending.iter().next().copied() {
        pending.remove(&source);
        for &target in &children[source] {
            depth[target] = depth[target].max(depth[source] + 1);
            remaining[target] = remaining[target].saturating_sub(1);
            if remaining[target] == 0 {
                pending.insert(target);
            }
        }
    }
    (depth, parents)
}

fn column_rows(depth: &[usize], parents: &[Vec<usize>]) -> Vec<i64> {
    let mut by_depth: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for (node, &level) in depth.iter().enumerate() {
        by_depth.entry(level).or_default().push(node);
    }
    let mut y = vec![0i64; depth.len()];
    for (&level, group) in &by_depth {
        if level == 0 {
            for (index, &node) in group.iter().enumerate() {
                y[node] = i64::try_from(index).unwrap_or(0) * 4;
            }
            continue;
        }
        let mut ranked: Vec<(f64, usize)> = group
            .iter()
            .map(|&node| {
                let earlier: Vec<usize> = parents[node]
                    .iter()
                    .copied()
                    .filter(|&parent| depth[parent] < level)
                    .collect();
                let desired = if earlier.is_empty() {
                    0.0
                } else {
                    earlier.iter().map(|&parent| y[parent] as f64).sum::<f64>()
                        / earlier.len() as f64
                };
                (desired, node)
            })
            .collect();
        ranked.sort_by(|left, right| left.0.total_cmp(&right.0).then(left.1.cmp(&right.1)));
        let target_mean = ranked.iter().map(|item| item.0).sum::<f64>() / ranked.len() as f64;
        let base_mean = 2.0 * (ranked.len() - 1) as f64;
        let offset = (round_half_even((target_mean - base_mean) / 2.0) * 2).max(0);
        for (index, &(_, node)) in ranked.iter().enumerate() {
            y[node] = offset + i64::try_from(index).unwrap_or(0) * 4;
        }
    }
    y
}

fn column_step(width: usize, max_depth: usize, max_label: usize) -> i64 {
    if max_depth == 0 {
        return 0;
    }
    let min_step = max_label + 6;
    let budget = width.saturating_sub(12).max(40);
    let available = budget.saturating_sub(max_label + 1) / max_depth;
    i64::try_from(available.min(24).max(min_step)).unwrap_or(24)
}

fn draw_edge(
    rails: &mut HashMap<(i64, i64), u8>,
    source_x: i64,
    source_y: i64,
    target_x: i64,
    target_y: i64,
    ascii: bool,
) {
    let arrow_tip = target_x - 2;
    let junction_x = if ascii { target_x - 5 } else { target_x - 4 };
    let split_x = junction_x.max(source_x);
    horizontal(rails, source_x, split_x, source_y);
    vertical(rails, split_x, source_y, target_y);
    horizontal(rails, split_x, arrow_tip, target_y);
}

fn horizontal(rails: &mut HashMap<(i64, i64), u8>, start: i64, end: i64, y: i64) {
    if end <= start {
        return;
    }
    for x in start..end {
        join(rails, (x, y), (x + 1, y), EAST, WEST);
    }
}

fn vertical(rails: &mut HashMap<(i64, i64), u8>, x: i64, start: i64, end: i64) {
    let (low, high) = if start <= end {
        (start, end)
    } else {
        (end, start)
    };
    for y in low..high {
        join(rails, (x, y), (x, y + 1), SOUTH, NORTH);
    }
}

fn join(
    rails: &mut HashMap<(i64, i64), u8>,
    first: (i64, i64),
    second: (i64, i64),
    first_direction: u8,
    second_direction: u8,
) {
    *rails.entry(first).or_default() |= first_direction;
    *rails.entry(second).or_default() |= second_direction;
}

fn paint(
    rails: &HashMap<(i64, i64), u8>,
    arrows: &[(i64, i64)],
    labels: &[(i64, i64, String)],
    ascii: bool,
) -> Vec<String> {
    let mut min_x = i64::MAX;
    let mut min_y = i64::MAX;
    let mut max_x = i64::MIN;
    let mut max_y = i64::MIN;
    let mut touch = |x: i64, y: i64| {
        min_x = min_x.min(x);
        min_y = min_y.min(y);
        max_x = max_x.max(x);
        max_y = max_y.max(y);
    };
    for &(x, y) in rails.keys() {
        touch(x, y);
    }
    for &tip in arrows {
        for (x, y) in arrow_cells(tip, ascii) {
            touch(x, y);
        }
    }
    for (x, y, label) in labels {
        let len = i64::try_from(label.chars().count()).unwrap_or(1).max(1);
        for offset in 0..len {
            touch(x + offset, *y);
        }
    }
    if min_x > max_x || min_y > max_y {
        return Vec::new();
    }
    let width = usize::try_from(max_x - min_x + 1).unwrap_or(0);
    let height = usize::try_from(max_y - min_y + 1).unwrap_or(0);
    if width == 0 || height == 0 || width > 4_000 || height > 4_000 {
        return labels
            .iter()
            .map(|(_, _, label)| format!("  {label}"))
            .collect();
    }
    let mut grid = vec![vec![' '; width]; height];
    let place = |grid: &mut [Vec<char>], x: i64, y: i64, glyph: char| {
        let Some(column) = usize::try_from(x - min_x).ok() else {
            return;
        };
        let Some(row) = usize::try_from(y - min_y).ok() else {
            return;
        };
        if row < grid.len() && column < grid[row].len() {
            grid[row][column] = glyph;
        }
    };
    for (&(x, y), mask) in rails {
        place(&mut grid, x, y, rail_char(*mask, ascii));
    }
    for &tip in arrows {
        let glyphs: Vec<char> = if ascii {
            vec!['-', '-', '>']
        } else {
            vec!['▶']
        };
        for ((x, y), glyph) in arrow_cells(tip, ascii).into_iter().zip(glyphs) {
            place(&mut grid, x, y, glyph);
        }
    }
    for (x, y, label) in labels {
        for (offset, glyph) in label.chars().enumerate() {
            place(&mut grid, x + i64::try_from(offset).unwrap_or(0), *y, glyph);
        }
    }
    let mut lines: Vec<String> = grid
        .into_iter()
        .map(|row| {
            let mut line = String::from("  ");
            line.extend(row);
            while line.ends_with(' ') {
                line.pop();
            }
            line
        })
        .collect();
    while lines.first().is_some_and(|line| line.is_empty()) {
        lines.remove(0);
    }
    while lines.last().is_some_and(|line| line.is_empty()) {
        lines.pop();
    }
    lines
}

fn arrow_cells(tip: (i64, i64), ascii: bool) -> Vec<(i64, i64)> {
    if ascii {
        vec![(tip.0 - 2, tip.1), (tip.0 - 1, tip.1), tip]
    } else {
        vec![tip]
    }
}

fn rail_char(mask: u8, ascii: bool) -> char {
    let north = mask & NORTH != 0;
    let south = mask & SOUTH != 0;
    let east = mask & EAST != 0;
    let west = mask & WEST != 0;
    if ascii {
        return match (north, south, east, west) {
            (false, false, true, false)
            | (false, false, false, true)
            | (false, false, true, true) => '-',
            (true, false, false, false)
            | (false, true, false, false)
            | (true, true, false, false) => '|',
            _ => '+',
        };
    }
    match (north, south, east, west) {
        (false, false, true, true) => '─',
        (true, true, false, false) => '│',
        (false, true, true, false) => '┌',
        (false, true, false, true) => '┐',
        (true, false, true, false) => '└',
        (true, false, false, true) => '┘',
        (false, true, true, true) => '┬',
        (true, false, true, true) => '┴',
        (true, true, true, false) => '├',
        (true, true, false, true) => '┤',
        (true, true, true, true) => '┼',
        (false, false, true, false) | (false, false, false, true) => '─',
        (true, false, false, false) | (false, true, false, false) => '│',
        _ => '─',
    }
}

fn safe(value: &str, ascii: bool) -> String {
    value
        .chars()
        .map(|glyph| {
            if glyph.is_control() || (ascii && !glyph.is_ascii()) {
                '?'
            } else {
                glyph
            }
        })
        .collect()
}

fn round_half_even(value: f64) -> i64 {
    if !value.is_finite() {
        return 0;
    }
    let floor = value.floor();
    let fraction = value - floor;
    let rounded = if (fraction - 0.5).abs() < 1e-9 {
        if (floor as i64) % 2 == 0 {
            floor
        } else {
            floor + 1.0
        }
    } else {
        value.round()
    };
    rounded as i64
}

fn render_json(components: &[Component]) -> Result<String> {
    let mut nodes: Vec<&Node> = components
        .iter()
        .flat_map(|component| component.nodes.iter())
        .collect();
    nodes.sort_by(|left, right| {
        left.updated_at
            .cmp(&right.updated_at)
            .then_with(|| left.source_id.cmp(&right.source_id))
    });
    let sessions: Vec<Value> = nodes
        .iter()
        .map(|node| {
            json!({
                "current": node.current,
                "handle": node.handle,
                "harness": node.harness,
                "native_available": node.native_available,
                "source_id": node.source_id,
                "title": node.title,
                "updated_at": node.updated_at,
            })
        })
        .collect();
    let mut edge_refs: Vec<&Edge> = components
        .iter()
        .flat_map(|component| component.edges.iter())
        .collect();
    edge_refs.sort_by(|left, right| {
        left.confirmed_at
            .cmp(&right.confirmed_at)
            .then_with(|| left.source_id.cmp(&right.source_id))
            .then_with(|| left.target_id.cmp(&right.target_id))
    });
    let edges: Vec<Value> = edge_refs
        .iter()
        .map(|edge| {
            json!({
                "confirmed_at": edge.confirmed_at,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
            })
        })
        .collect();
    let mut timelines = Vec::new();
    let mut truncated = false;
    for component in components {
        truncated |= component.truncated;
        for path in &component.paths {
            let handles: Vec<&str> = path
                .iter()
                .map(|&index| component.nodes[index].handle.as_str())
                .collect();
            timelines.push(json!(handles));
        }
    }
    let document = json!({
        "component_count": components.len(),
        "edges": edges,
        "schema_version": 1,
        "sessions": sessions,
        "timelines": timelines,
        "timelines_truncated": truncated,
    });
    serde_json::to_string(&document).map_err(|error| TangError::new("output", error.to_string()))
}

#[cfg(test)]
mod tests {
    use super::{edge_shape, root_to_leaf, round_half_even, Edge, Node};

    fn node(source_id: &str, handle: &str) -> Node {
        Node {
            source_id: source_id.into(),
            handle: handle.into(),
            harness: "codex".into(),
            title: handle.into(),
            updated_at: "2026-07-14T20:00:00Z".into(),
            health: "complete".into(),
            native_available: true,
            current: false,
        }
    }

    fn edge(source: &str, target: &str) -> Edge {
        Edge {
            source_id: source.into(),
            target_id: target.into(),
            confirmed_at: "2026-07-14T21:00:00Z".into(),
        }
    }

    #[test]
    fn edge_shape_merge_branch_and_continue() {
        assert_eq!(edge_shape(1, 2), "MERGE");
        assert_eq!(edge_shape(2, 1), "BRANCH");
        assert_eq!(edge_shape(2, 2), "MERGE + BRANCH");
        assert_eq!(edge_shape(1, 1), "CONTINUE");
    }

    #[test]
    fn timelines_follow_source_id_and_cap_at_eight() {
        let nodes = vec![
            node("a", "A"),
            node("b", "B"),
            node("c", "C"),
            node("d", "D"),
            node("e", "E"),
        ];
        let edges = vec![
            edge("a", "c"),
            edge("b", "c"),
            edge("c", "d"),
            edge("c", "e"),
        ];
        let (paths, truncated) = root_to_leaf(&nodes, &edges);
        assert!(!truncated);
        let handles: Vec<Vec<&str>> = paths
            .iter()
            .map(|path| {
                path.iter()
                    .map(|&index| nodes[index].handle.as_str())
                    .collect()
            })
            .collect();
        assert_eq!(
            handles,
            vec![
                vec!["A", "C", "D"],
                vec!["A", "C", "E"],
                vec!["B", "C", "D"],
                vec!["B", "C", "E"],
            ]
        );

        let mut wide_nodes = vec![node("root", "R")];
        let mut wide_edges = Vec::new();
        for index in 0..9 {
            let id = format!("leaf-{index}");
            wide_nodes.push(node(&id, &id));
            wide_edges.push(edge("root", &id));
        }
        let (paths, truncated) = root_to_leaf(&wide_nodes, &wide_edges);
        assert!(truncated);
        assert_eq!(paths.len(), 8);
    }

    #[test]
    fn half_rounds_to_even() {
        assert_eq!(round_half_even(0.5), 0);
        assert_eq!(round_half_even(1.5), 2);
        assert_eq!(round_half_even(2.5), 2);
        assert_eq!(round_half_even(-0.5), 0);
        assert_eq!(round_half_even(-1.5), -2);
    }
}
