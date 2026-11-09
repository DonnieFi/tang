//! Ordered best-effort redaction shared with the spec's persistence seam.

use regex::{Captures, Regex};
use std::sync::OnceLock;

#[derive(Clone, Copy)]
pub enum ContentKind {
    Title,
    VisibleText,
    DisplayMetadata,
}

pub fn redact(text: &str, kind: ContentKind) -> String {
    let _kind = kind;
    let mut redacted = text.to_string();
    for rule in rules() {
        redacted = rule.replace(&redacted);
    }
    redacted
}

struct Rule {
    pattern: Regex,
    replacement: fn(&Captures<'_>) -> String,
}

impl Rule {
    fn replace(&self, text: &str) -> String {
        self.pattern
            .replace_all(text, self.replacement)
            .into_owned()
    }
}

fn rules() -> &'static [Rule] {
    static RULES: OnceLock<Vec<Rule>> = OnceLock::new();
    RULES.get_or_init(|| {
        vec![
            Rule {
                pattern: Regex::new(
                    r"(?s)-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
                )
                .expect("private-key pattern"),
                replacement: |_| "[REDACTED:private-key]".to_string(),
            },
            Rule {
                pattern: Regex::new(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}").expect("bearer"),
                replacement: |_| "Bearer [REDACTED:token]".to_string(),
            },
            Rule {
                pattern: Regex::new(
                    r"\b(?:AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{16,}|eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b",
                )
                .expect("known-token"),
                replacement: |_| "[REDACTED:token]".to_string(),
            },
            Rule {
                pattern: Regex::new(
                    r#"(?i)\b(?P<name>(?:API_KEY|ACCESS_KEY|SECRET_KEY|CLIENT_SECRET|AUTH_TOKEN|TOKEN|PASSWORD|PASSWD|[A-Z][A-Z0-9_]+_(?:KEY|TOKEN|SECRET|PASSWORD)))\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)"#,
                )
                .expect("credential"),
                replacement: |caps| {
                    format!(
                        "{}=[REDACTED:credential]",
                        caps.name("name").map(|m| m.as_str()).unwrap_or("secret")
                    )
                },
            },
            Rule {
                pattern: Regex::new(
                    r"(?i)(?P<scheme>https?://)(?P<user>[^:/\s]+):[^@/\s]+@",
                )
                .expect("uri-password"),
                replacement: |caps| {
                    format!(
                        "{}{}:[REDACTED:password]@",
                        caps.name("scheme").map(|m| m.as_str()).unwrap_or("https://"),
                        caps.name("user").map(|m| m.as_str()).unwrap_or("user")
                    )
                },
            },
            Rule {
                pattern: Regex::new(
                    r"(?i)(^|[^A-Za-z0-9])(/(?:home|Users)/[^/\s]+|/root\b|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)",
                )
                .expect("home-path"),
                replacement: |caps| {
                    format!(
                        "{}~",
                        caps.get(1).map(|item| item.as_str()).unwrap_or("")
                    )
                },
            },
        ]
    })
}

#[cfg(test)]
mod tests {
    use super::{redact, ContentKind};

    #[test]
    fn redacts_credentials_tokens_and_home_paths() {
        assert_eq!(
            redact(
                "API_KEY=supersecretvalue in the note",
                ContentKind::VisibleText
            ),
            "API_KEY=[REDACTED:credential] in the note"
        );
        assert_eq!(
            redact(
                "Authorization Bearer abcdEFGH1234",
                ContentKind::VisibleText
            ),
            "Authorization Bearer [REDACTED:token]"
        );
        assert_eq!(
            redact("see /home/someone/secret", ContentKind::VisibleText),
            "see ~/secret"
        );
    }
}
