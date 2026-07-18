# Security policy

Tang reads local coding-agent history, so privacy and path containment are part
of its security boundary.

## Supported versions

Before the first tagged release, security fixes target the current release
candidate on `main`. After publication, only the latest tagged release is
supported.

## Report a vulnerability

Use GitHub's private vulnerability-reporting flow from this repository's
**Security** tab. If that option is unavailable, open a minimal issue asking the
maintainer to establish a private channel; do not include exploit details,
credentials, native transcripts, session IDs, home-directory paths, or a real
`.tang` database in a public issue.

Include the Tang version, supported Linux and Python versions, the affected
command, and a reproduction built from synthetic data. Tang intentionally
sends no telemetry and does not operate a remote service that receives
diagnostic data.
