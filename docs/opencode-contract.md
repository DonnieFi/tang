# OpenCode

Tang indexes OpenCode from export JSON on disk. Pass the export directory with `--opencode-home`. A file is an export when its name contains `export` and ends in `.json`. Symlinked exports are skipped and the previous row for that session is kept when an export is malformed.

The namespace is `store-` plus the SHA-256 of the `opencode` executable, a NUL, and the XDG data home. The `--opencode-home` flag is still the export directory that gets read. It is not part of the identity hash.

Unchanged exports are skipped through `adapter_checkpoints`. The reader does not start the OpenCode server or invoke `opencode export`. Visible text is `messages[].parts` of type `text` whose role is user or assistant. `tang context` rereads that same export when it is a regular file, redacts the turns, and falls back to the stored capsule when the file is missing or symlinked.

Install the host files with:

```bash
tang skill install opencode --cwd "$HOME"
```

That copies the skill, `.opencode/commands/tang.md`, and the two Tang tools under `$HOME/.opencode`.

Tang does not read OpenCode provider credentials and does not write OpenCode session stores. `tang doctor` checks SQLite and FTS5 only. It does not probe OpenCode.
