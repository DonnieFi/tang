---
name: tang
description: Run Tang CLI recovery via JSON from Claude Code when terminal access is available. Use for browse, search, context, link, and resume workflows in the current project.
---

# Tang (Claude Code CLI bridge)

Claude Code does not expose a private current-session ID to Tang. Use explicit
handles and terminal commands from the project directory:

1. `tang index --json`
2. `tang browse --json --page 1` or `tang search "phrase" --json`
3. `tang context <handle>... --json`
4. `tang link --from ... --to <handle> --json` with explicit confirmation
5. `tang resume <handle>` to reopen an indexed Claude session natively

Handles for Claude sources use the **`L`** prefix (for example `L1`).

Install with `tang skill install claude` (writes `~/.claude/skills/tang/SKILL.md`).

Do not paste canonical source IDs into chat; use displayed handles only.
See `docs/claude-handoff.md` in the Tang repository for limits and privacy rules.
