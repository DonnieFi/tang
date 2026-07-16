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
The context supplies the exact active `sessionID`, `directory`, and `worktree`.
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
session, ask OpenCode to call `tang_contract_probe` with the exact expected
provider ID for that run. The report fails closed when that provider is absent.

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
  --expect-provider "$EXPECTED_PROVIDER_ID" \
  --overall-timeout 120
```

The dynamic values above come from OpenCode tool context; do not type or send
them separately. Return only the probe's JSON report. It contains version,
platform, provider IDs, booleans, counts, part-type labels, and one-way identity
digests. It cannot contain raw session IDs, export hashes, paths, titles,
transcript text, reasoning, tool inputs/outputs, or credentials.

OpenCode `1.17.20` exposes no directory filter or pagination option for
`session list`. The probe therefore lists the supported catalog without a
global top-N limit, filters it to the canonical project directory, and only
then caps exports. The active context session is always included in that cap.
Each command has a 30-second deadline and the complete probe has a 120-second
deadline. Failures expose only allow-listed error codes, never stderr.

The production ordering contract is created milliseconds followed by stable
message ID. The probe verifies that both inputs are present and that source
timestamps are non-decreasing; the adapter will apply the deterministic
tie-break. Missing timestamps or IDs qualify the source as incomplete rather
than inviting Tang to guess. Only non-ignored user/assistant text parts are
visible content.

Epic 7's provider claim remains pending until both reports show:

- `result: "pass"`;
- `current_session_matches: true`;
- stable, chronological, project-scoped identities;
- at least one visible user and assistant text part; and
- the intended OpenAI or xAI/Grok provider ID.
