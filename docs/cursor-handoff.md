# Continue into Cursor with Tang (handoff)

Cursor sessions can be indexed when agent transcripts exist under
`~/.cursor/projects/<path-slug>/agent-transcripts/`. When Cursor also writes
`~/.cursor/chats/<md5(project)>/<sessionId>/meta.json` and `store.db`, Tang
reads native **title**, **timestamps**, **lastUsedModel**, and **mode** at scan
time and merges **Task** `model` hints from JSONL on read. Tang does not ship a
Cursor plugin in v0.3.0; use the CLI from the project terminal or invoke the
same commands through a project **Cursor Agent skill** that wraps them.

## CLI workflow

```bash
tang index --json
tang browse --json --page 1
tang search "your phrase" --json --page 1
tang context R1 --json
```

Handles for Cursor sources use the **`R`** prefix (for example `R1`).

## Host integration

A thin project Cursor Agent skill can:

- Runs non-interactive `tang … --json` commands
- Keeps native session IDs private
- Uses host-native multi-select when available

Tang ships the CLI contract rather than silently installing a Cursor plugin.
Run `tang` in a terminal alongside Cursor or add a thin skill that forwards to
the CLI.

## Import and destinations

- **Import:** paste or inject the Markdown Context Pack into the active Agent
  chat (untrusted envelope preserved).
- **Link destination:** explicit `tang link --to R*` edges are supported when
  the Cursor session is indexed; there is no `--current` bridge yet.
- **Native resume:** `tang resume R1` reopens the exact indexed chat through
  Cursor Agent's `--resume` and `--workspace` contract without creating a link.

See [native-write-policy.md](native-write-policy.md).
