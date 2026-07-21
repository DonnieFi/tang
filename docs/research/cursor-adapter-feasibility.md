# Cursor read adapter feasibility (tang-sis.6)

## Recommendation

**In-core read-only Cursor adapter: feasible on Linux, post–v0.2.9, after live
shape verification.** Treat as bead `tang-sis.13`, not a third-party plugin.

## Data sources

| Source | Location | Content |
| --- | --- | --- |
| **Store-backed agent tree** | `~/.cursor/chats/<md5(workspace path)>/<agentId>/` | `store.db` (SQLite blobs + hex meta), `meta.json`, `prompt_history.json` — often **authoritative** for CLI/agent sessions |
| Agent transcripts | `~/.cursor/projects/<slug>/agent-transcripts/<id>/<id>.jsonl` | Read-only JSONL mirror; text + `tool_use` blocks |
| Project artifacts | `~/.cursor/projects/<slug>/` | `repo.json`, `agent-tools/*.txt`, `terminals/` |
| Workspace metadata | `~/.config/Cursor/User/workspaceStorage/*/workspace.json` | Path hash → folder URI |
| Global composer state | `~/.config/Cursor/User/globalStorage/state.vscdb` | `composerData`, `bubbleId`, `composer.composerHeaders`, `agentKv`, … |
| AI tracking (optional) | `~/.cursor/ai-tracking/ai-code-tracking.db` | `conversationId`, `model`, file hashes — not turn text |

On Linux, IDE SQLite lives under **`~/.config/Cursor/User/`**, not under `~/.cursor/`.
Workspace chat index hash under `~/.cursor/chats/` uses **MD5(absolute path)**; `workspaceStorage/` folder names are **opaque**.

See **`docs/research/cursor-storage-inventory.md`** for a live audit and indexable fields.

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
