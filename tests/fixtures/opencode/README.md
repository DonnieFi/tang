# Synthetic OpenCode 1.17.20 fixtures

These files are entirely synthetic. They preserve the supported JSON shapes
verified on Linux against OpenCode `1.17.20` on 2026-07-16:

- `opencode session list --format json` supplies stable session IDs, titles,
  project IDs, directories, and millisecond created/updated timestamps;
- `opencode export SESSION_ID` supplies one `info` object plus chronological
  message objects containing typed parts; and
- OpenCode custom-tool context supplies the active `sessionID`, `messageID`,
  `directory`, and `worktree` without Tang reading provider authentication.
- `tool-context.json` is an invented host-context envelope used to verify exact,
  path-safe destination resolution. Tests replace its placeholder path with a
  temporary project; it contains no native user metadata.

The local proof used an isolated temporary OpenCode data/config/cache home,
disabled model fetching and plugins, created one credential-free session via
the documented localhost server API, and exported it through the documented
CLI. No native OpenCode transcript, title, path, ID, credential, or tool value
was copied. IDs, paths, timestamps, text, provider labels, and canaries here are
deterministic inventions. The assistant, reasoning, and tool-part shapes are
based on OpenCode's published OpenAPI/SDK contract and must be confirmed by the
privacy-safe live-provider probe before Epic 7 claims provider support.

`session-list-updated.json` represents the same identity after a source change;
the zero-byte `session-list-empty.json` preserves the pinned CLI's actual empty
stdout, and `session-export-malformed.json` establishes the malformed boundary.
Reasoning and tool canaries must never become visible Tang turns or persisted
capsule text.
