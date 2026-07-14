# Synthetic Grok session fixture

This fixture is fully synthetic and contains no copied transcript text, source
locator, credential, tool payload, or file body.

Its directory layout and JSON field shapes were derived from a schema-only
inspection of representative real local data written by Grok Build 0.2.99
(stable, build `b1b49ccb71`) on Linux. Live verification used the documented
`$GROK_HOME/sessions/<percent-encoded-cwd>/<uuidv7>/summary.json` metadata and
authoritative ACP `updates.jsonl` stream. The fixture verifies that shape; it
does not establish live compatibility with other Grok versions.
