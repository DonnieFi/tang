# Sanitized Codex fixture

This corpus is synthetic. It preserves the representative JSONL structure
verified read-only against Codex CLI `0.144.4` on Linux on 2026-07-14, including
session metadata, project metadata, RFC 3339 timestamps, visible user and agent
messages, turn context, and task lifecycle events.

No native transcript text, source path, repository URL, session identifier, or
credential was copied. The UUID, `/work/tang-demo` project, Git metadata, and
conversation text are deterministic canaries created only for tests. This
fixture verifies this documented shape; other Codex versions are not
live-verified or included in the support claim unless separately tested.

The second synthetic turn intentionally ends after `task_started` without a
`task_complete` event. It establishes the safe `unknown` health fallback and
must not be “completed” unless that health fixture is replaced deliberately.
