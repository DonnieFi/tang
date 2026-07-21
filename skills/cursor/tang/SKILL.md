---
name: tang
description: Run Tang CLI recovery via JSON from Cursor Agent when terminal access is available. Use for browse, search, context, and link workflows in the current project.
---

# Tang (Cursor CLI bridge)

Cursor does not yet expose a private current-session ID to Tang. Use explicit
handles and terminal commands:

1. `tang index --json`
2. `tang browse --json --page 1` or `tang search "phrase" --json`
3. `tang context <handle>... --json`
4. `tang link --from ... --to <handle> --json` with explicit confirmation

See `docs/cursor-handoff.md` in the Tang repository for limits and privacy rules.

Do not paste canonical source IDs into chat; use displayed handles only.
