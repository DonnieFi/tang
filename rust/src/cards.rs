//! Plain-text session cards for the current project.

use crate::discovery::DiscoveryRow;

const EMPTY: &str = "No indexed sessions.\n";

pub fn render_brief(rows: &[DiscoveryRow]) -> String {
    if rows.is_empty() {
        return EMPTY.to_string();
    }
    let mut lines = Vec::with_capacity(rows.len());
    for row in rows {
        lines.push(brief_line(row));
    }
    lines.join("\n") + "\n"
}

pub fn render_cards(rows: &[DiscoveryRow]) -> String {
    if rows.is_empty() {
        return EMPTY.to_string();
    }
    let blocks = rows.iter().map(card_block).collect::<Vec<_>>();
    blocks.join("\n\n") + "\n"
}

fn brief_line(row: &DiscoveryRow) -> String {
    let title = single_line(&row.title);
    if title.is_empty() {
        format!("{} {} {}", row.handle, row.harness, row.health)
    } else {
        format!("{} {} {} {title}", row.handle, row.harness, row.health)
    }
}

fn card_block(row: &DiscoveryRow) -> String {
    [
        labeled("HANDLE", &row.handle),
        labeled("harness", &row.harness),
        labeled("health", &row.health),
        labeled("updated_at", &row.updated_at),
        labeled("title", &row.title),
    ]
    .join("\n")
}

fn labeled(label: &str, value: &str) -> String {
    let value = single_line(value);
    if value.is_empty() {
        label.to_string()
    } else {
        format!("{label} {value}")
    }
}

fn single_line(value: &str) -> String {
    let cleaned = value
        .chars()
        .map(|character| {
            if character.is_control() {
                ' '
            } else {
                character
            }
        })
        .collect::<String>();
    cleaned.split_whitespace().collect::<Vec<_>>().join(" ")
}
