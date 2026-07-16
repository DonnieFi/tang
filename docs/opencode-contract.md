# OpenCode contract evidence

Epic 7 pins its initial compatibility claim to OpenCode `1.17.20` on Linux.
Tang treats OpenCode as the harness even when the model provider is OpenAI or
xAI/Grok. Tang never reads OpenCode's provider credential file.

## Supported seams

The source adapter is based on documented, non-interactive CLI contracts:

- `opencode session list --format json` returns stable session identity,
  project directory, title, and millisecond created/updated evidence;
- `opencode export SESSION_ID` returns session metadata and chronological
  message envelopes with typed parts; and
- Tang parses raw export JSON only in memory because the `--sanitize` form
  deliberately removes the visible text needed for source-cited continuation.

The destination integration uses OpenCode's documented custom-tool context.
The context supplies the exact active `sessionID`, invoking `messageID`,
`directory`, and `worktree`.
Tang can therefore require explicit confirmation of a concrete current target
without guessing from modification times or a global “latest session.”

Primary references:

- <https://opencode.ai/docs/cli/#session>
- <https://opencode.ai/docs/cli/#export>
- <https://opencode.ai/docs/custom-tools/#context>
- <https://opencode.ai/docs/server/#sessions>
- <https://opencode.ai/docs/server/#messages>
- <https://opencode.ai/docs/skills/>

## Local feasibility evidence

On 2026-07-16, the installed Linux x86-64 OpenCode `1.17.20` binary was run
with a temporary data, config, and cache home. Model fetching and external
plugins were disabled. A credential-free synthetic session created through the
documented localhost server API proved:

- server-reported version `1.17.20`;
- stable list/export identity;
- project-scoped directory metadata;
- millisecond source-change timestamps;
- chronological user-message timestamps and visible text parts;
- valid small-session raw and sanitized exports; and
- an OpenAPI 3.1 document covering session and message endpoints.

The local user's existing OpenCode IDs, titles, paths, transcript values, and
credentials were not recorded. The checked-in fixtures are deterministic
inventions described in `tests/fixtures/opencode/README.md`.

One large pre-existing local export produced incomplete JSON while being
observed through the host runner despite OpenCode exiting successfully. This is
not promoted into a format claim. The adapter must treat invalid or incomplete
exports as partial source failures and retain the last known good checkpoint;
live-provider acceptance must include a non-trivial export.

## Privacy-safe external-provider acceptance

This is the live acceptance stage for Tang's permanent OpenCode integration,
not a tester-specific product path. From a private Tang checkout, open OpenCode
`1.17.20` in the Tang worktree. Python 3.11 or newer is required by the probe;
OpenCode hosts its custom tool under Bun.
The project-local `tang_contract_probe` custom tool is discovered from
`.opencode/tools/`. In one OpenAI-backed session and one xAI/Grok-backed
session, ask OpenCode to call `tang_contract_probe`. Provider/model choice does
not control whether Tang can read a supported OpenCode transcript; the two runs
establish representative coverage rather than an adapter eligibility rule.
Acceptance is pinned to OpenCode `1.17.20` on Linux `x86_64`; other semantic
versions and platforms cannot produce `result: "pass"` without new validation.

If OpenCode is not on `PATH`, launch it with the executable path exported for
the tool process:

```bash
export TANG_OPENCODE_EXECUTABLE=/absolute/path/to/opencode
opencode .
```

The tool invokes:

```bash
python3 scripts/probe_opencode_contract.py \
  --opencode "$TANG_OPENCODE_EXECUTABLE" \
  --cwd "$PROJECT" \
  --current-session-id "$ACTIVE_OPENCODE_SESSION_ID" \
  --current-message-id "$INVOKING_OPENCODE_MESSAGE_ID" \
  --expected-version 1.17.20 \
  --overall-timeout 120
```

The dynamic IDs above come from OpenCode tool context; do not type or send them
separately. Return only the probe's JSON report. It contains the pinned version,
platform, booleans, counts, and fixed metadata classes.
It cannot contain raw session/message IDs, arbitrary provider/role/part labels,
export hashes, paths, titles, transcript text, reasoning, tool inputs/outputs,
or credentials.

OpenCode `1.17.20`'s CLI `session list` requests root sessions for OpenCode's
project identity and its service defaults to the latest 100. That identity can
span sibling clones or worktrees, so Tang filters the returned entries to the
canonical active directory before export. The probe requests the upstream
boundary explicitly, reports whether foreign-directory entries were excluded,
sorts deterministically before capping exports, and fails visibly if all 100
slots are occupied because truncation could hide local sessions. It does not
claim a complete catalog or non-root discovery.

The production adapter uses OpenCode `1.17.20`'s documented `/session` server
endpoint with the exact active directory, `roots` unset, and an explicit
`500 + 1` bound. This includes root and child sessions. Tang starts the server
on direct localhost with a random per-run Basic Auth credential, disables proxy
and redirect handling for the private directory query, stops the server after
the bounded response, and reports saturation as partial. It never reads
OpenCode's private database or cache. Selected rereads use the supported raw
`opencode export SESSION_ID` command.

The incremental fingerprint is the documented per-session `updated` millisecond
field (`opencode-updated-ms-v1`). Tang treats an unchanged value as unchanged
native evidence; if a future OpenCode version can alter export content without
updating that field, it requires a new adapter contract and live verification.

The active tool-context session is exported directly even when it is absent
from the root catalog. Each command has a 30-second deadline and the complete
probe has a 120-second deadline. Cancelling the OpenCode tool terminates the
subprocess. Failures expose only allow-listed error codes, never stderr.

The production ordering contract is created milliseconds followed by stable
message ID. The probe verifies that both inputs are present and that source
timestamps are non-decreasing; the adapter applies the deterministic tie-break.
Missing timestamps or IDs qualify the source as incomplete rather than inviting
Tang to guess. Only non-ignored user/assistant text parts are visible content.

A privacy-safe live adapter smoke on 2026-07-16 scanned six exact-directory
sessions completely and reread one representative session as four visible
user/agent turns with no warnings. Only counts, role classes, statuses, and
fixed warning codes were observed; no IDs, paths, titles, transcript text,
reasoning, tool data, hashes, or credentials were retained.

Normal `tang index` and `tang context` add OpenCode when `opencode` is on
`PATH`, `TANG_OPENCODE_EXECUTABLE` names the binary, or
`--opencode-executable PATH` is supplied. If OpenCode is absent and was not
configured, existing Codex/Grok indexing remains unchanged. `tang doctor`
always checks the OpenCode surface and distinguishes `missing`, `empty`,
`ready`, and `degraded` without creating an absent Tang database or modifying
native sessions. Indexed OpenCode sessions use `O1`, `O2`, and later
project-local handles and can be filtered with `--harness opencode`.

Continuation policy is deliberately harness-based rather than provider-based:
Codex and OpenCode are supported destinations; Codex, Grok, and OpenCode can
be sources. An OpenCode destination must come from the exact, fresh host
context described above and receive explicit confirmation before Tang records
any derived edge. Tang neither writes transcript content into OpenCode nor
reads provider credentials.

## Product workflow installation

Install the version-coupled OpenCode integration from the Tang CLI at the
project root:

```bash
tang skill install opencode --project-root "$PWD"
```

This change-safe installer adds only `.opencode/skills/tang`, the `/tang`
custom command, and the private `tang_current_target` custom tool. It preserves
unrelated OpenCode configuration, is idempotent, refuses divergent Tang-owned
files unless `--force` is explicit, and applies user-only file modes on POSIX.
The bridge is dependency-free and does not alter the project's package manifest.
Start a new OpenCode process after installation so it discovers the assets.

The installed-product path expects `tang` and OpenCode `1.17.20` on `PATH`.
Source-checkout testing may instead set `TANG_EXECUTABLE` to the checkout's
virtual-environment script and `TANG_OPENCODE_EXECUTABLE` to the pinned OpenCode
binary before launching OpenCode. `/tang` loads the one Tang Agent Skill;
the custom tool supplies exact active-session context privately and emits only
a project-local handle or a fixed error code. The user must still approve the
selected source handles and target handle before `tang link` records edges.

On 2026-07-16, privacy-safe live reports passed from one direct OpenAI-backed
session and one direct xAI/Grok-backed session on the pinned host. Both reports
showed:

- `result: "pass"`;
- `current_session_matches: true`;
- `invoking_message_matches_once: true` and
  `invoking_message_is_assistant: true`;
- `version_supported: true` and `platform_supported: true`;
- stable, chronological, project-scoped identities;
- at least one visible user and assistant text part; and
- a fixed `openai` or `xai` provider classification for the representative run.

Provider and model remain diagnostics, not transcript-eligibility rules. A
supported OpenCode transcript can be recovered regardless of which provider or
model produced it, provided the same host, identity, ordering, visibility, and
privacy contracts hold. No native IDs, paths, transcript text, hashes, or raw
reports are retained as project evidence.

## Functional acceptance procedure

Use a clean checkout of `epic/07-opencode-integration`. The Tang CLI does not
need to be globally installed for this contract probe; the OpenCode tool calls
the standard-library Python script directly. Confirm the host reports OpenCode
`1.17.20`, Linux, and `x86_64` before starting.

For the OpenAI report, open a fresh top-level OpenCode session in the Tang
worktree with an OpenAI model. First request and receive one normal short text
answer. Then ask:

> Call `tang_contract_probe`. Return only the tool's JSON object with no
> commentary.

Save only that JSON object. Do not send native OpenCode logs or exports. Repeat
the same sequence in a separate fresh top-level session backed by an xAI/Grok
model. The probe may report a fixed `other` provider class when OpenCode uses a
provider alias; that diagnostic does not affect transcript readability.

A successful report has `result: "pass"` and true checks for version, platform,
catalog boundary, stable/project-scoped identities, ordering inputs, meaningful
user/assistant text, the exact current session, and the exact invoking message.
Provider classes are fixed diagnostics only. If a report fails, return its JSON
unchanged; its fixed error/check fields are the safe diagnostic evidence.
