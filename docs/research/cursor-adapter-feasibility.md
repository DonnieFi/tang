# Cursor read adapter feasibility (tang-sis.6)

## Recommendation

**In-core read-only Cursor adapter: feasible on Linux, post–v0.2.9, after live
shape verification.** Treat as bead `tang-sis.13`, not a third-party plugin.

## Data sources

| Source | Location | Content |
| --- | --- | --- |
| Agent transcripts | `~/.cursor/projects/<slug>/agent-transcripts/*.jsonl` | User/assistant turns; workspace-scoped |
| Workspace metadata | `~/.cursor/User/workspaceStorage/*/workspace.json` | Path hash → folder path |
| Global composer state | `~/.cursor/User/globalStorage/state.vscdb` | Session lists (SQLite; read-only) |

Community precedent: [cursor-chat-browser](https://github.com/snehaendait/cursor-chat-browser)
indexes agent-transcripts with FTS; aligns with Tang's capsule model.

## Fit with Tang invariants

- **Project isolation:** Map transcript paths to `ProjectIdentity` via resolved
  workspace root; never index foreign projects without opt-in (`tang-9nb`).
- **Privacy:** Same redaction seams as Codex (`ContentKind`, capsule byte cap).
- **Read-only:** No writes to Cursor DBs or transcripts.
- **Identity:** `cursor:store-<sha256>:<session-id>` namespace pattern mirroring Codex.

## Risks

- Undocumented schema drift (Cursor updates composer storage).
- Path renames break workspace hash mapping (see `tang-sis.5`).
- macOS/Windows paths excluded from Linux release claim until proven.

## Out of scope for feasibility bead

- Host skill/MCP (`tang-sis.14`) and link destination (`tang-sis.15`).
- Claiming Cursor in README marketing before live verification.

## Draft adapter contract (implementation gate)

```text
CursorAdapter(adapter_key="cursor")
  scan(checkpoint) -> ScanBatch
  read(source, TurnSelection) -> TurnBatch
  source_namespace = sha256(cursor_config_root)
```

Host current-target bridge requires private session ID from Cursor APIs or MCP;
fail closed when absent (same as Codex skill without `--current-native-id`).
