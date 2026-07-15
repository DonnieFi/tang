# Combined discovery/context corpus

This synthetic corpus composes the canonical Grok Build 0.2.99 and Codex CLI
0.144.4 fixtures with deterministic Codex additions. The test helper copies all
inputs to a temporary home before expanding the `[LONG_SYNTHETIC_3000]` marker
and renaming the `.jsonl.partial` corruption template. Native fixture files are
never modified.

Current-project sessions use `/work/tang-demo`; the isolated foreign sentinel
uses `/work/foreign-vault`. Memorable phrases and expectations are recorded in
`expectations.json`. No IDs, paths, transcripts, repositories, or credentials
come from native user data.
