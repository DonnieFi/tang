---
description: Recover Tang context or continue earlier project work safely
---

Load the `tang` skill and follow it exactly. The user's Tang request is:

`$ARGUMENTS`

If the request is exactly `context` or `context all`, call
`tang_predecessor_context` privately now. When it returns a Context Pack, use
only its cited excerpts to write the skill's three-section Continuation Brief
in this same response. Do not ask the user to supply a Context Pack, re-confirm
an existing link, or create or change any link. If it returns a fixed
unavailable code, explain that code and stop.

For every other request, follow the normal skill workflow. If the skill is
unavailable, stop and tell the user to run `tang skill install opencode
--project-root "$PWD" --force` and restart OpenCode; do not substitute a
repository file or another harness's skill.
