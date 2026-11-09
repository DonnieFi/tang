//! Deterministic categories and extractive summaries. Not model output.

pub const SUMMARY_LIMIT: usize = 480;
const MARKER: &str = "…[Truncated]";

const RULES: &[(&str, &[&str])] = &[
    (
        "bug",
        &[
            "bug",
            "crash",
            "exception",
            "traceback",
            "failing",
            "broken",
        ],
    ),
    (
        "decision",
        &["decision", "decided", "tradeoff", "trade-off", "chose"],
    ),
    ("review", &["review", "nitpick", "lgtm"]),
    ("implementation", &["implement", "refactor", "patch"]),
];

pub fn categories() -> &'static [&'static str] {
    &[
        "bug",
        "decision",
        "goal",
        "implementation",
        "other",
        "review",
    ]
}

pub fn categorize(text: &str, has_user_excerpt: bool) -> &'static str {
    for (name, words) in RULES {
        if words.iter().any(|word| contains_word(text, word)) {
            return name;
        }
    }
    if has_user_excerpt {
        "goal"
    } else {
        "other"
    }
}

pub fn build_summary(category: &str, title: Option<&str>, excerpts: &[(String, String)]) -> String {
    let mut lines = Vec::new();
    if let Some(title) = title.filter(|value| !value.is_empty()) {
        lines.push(format!("[{category}] {title}"));
    } else {
        lines.push(format!("[{category}]"));
    }
    let user = excerpts
        .iter()
        .find(|(role, text)| role == "user" && !text.is_empty())
        .map(|(_, text)| text.as_str());
    let agent = excerpts
        .iter()
        .rev()
        .find(|(role, text)| role == "agent" && !text.is_empty())
        .map(|(_, text)| text.as_str());
    if let Some(user) = user {
        lines.push(user.to_string());
    }
    if let Some(agent) = agent {
        if Some(agent) != user {
            lines.push(agent.to_string());
        }
    }
    let text = lines.join("\n");
    let length = text.chars().count();
    if length <= SUMMARY_LIMIT {
        return text;
    }
    let keep = SUMMARY_LIMIT - MARKER.chars().count();
    let truncated: String = text.chars().take(keep).collect();
    format!("{}{MARKER}", truncated.trim_end())
}

fn contains_word(haystack: &str, word: &str) -> bool {
    let haystack = haystack.to_ascii_lowercase();
    let word = word.to_ascii_lowercase();
    let bytes = haystack.as_bytes();
    let needle = word.as_bytes();
    if needle.is_empty() || bytes.len() < needle.len() {
        return false;
    }
    for start in 0..=bytes.len() - needle.len() {
        if &bytes[start..start + needle.len()] != needle {
            continue;
        }
        let before_ok = start == 0 || !bytes[start - 1].is_ascii_alphanumeric();
        let after = start + needle.len();
        let after_ok = after == bytes.len() || !bytes[after].is_ascii_alphanumeric();
        if before_ok && after_ok {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use super::{build_summary, categorize, SUMMARY_LIMIT};

    #[test]
    fn categories_follow_the_closed_word_list() {
        assert_eq!(categorize("the indexer crash", false), "bug");
        assert_eq!(categorize("crashpad storage", false), "other");
        assert_eq!(categorize("we decided to keep sqlite", false), "decision");
        assert_eq!(categorize("please review the patch", false), "review");
        assert_eq!(categorize("implement the parser", false), "implementation");
        assert_eq!(categorize("ship the catalog", true), "goal");
    }

    #[test]
    fn summaries_are_bounded_extracts() {
        let excerpts = vec![
            ("user".into(), "the indexer crash on empty books".into()),
            ("agent".into(), "guard the empty list before ranking".into()),
        ];
        assert_eq!(
            build_summary("bug", Some("Indexer crash"), &excerpts),
            "[bug] Indexer crash\nthe indexer crash on empty books\nguard the empty list before ranking"
        );
        let long = vec![("user".into(), "x".repeat(600))];
        let summary = build_summary("other", Some("T"), &long);
        assert_eq!(summary.chars().count(), SUMMARY_LIMIT);
        assert!(summary.ends_with("…[Truncated]"));
    }
}
