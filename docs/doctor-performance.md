# Doctor performance and modes

`tang doctor` supports two modes:

| Mode | Flag | Adapter behavior |
| --- | --- | --- |
| **Full** (default) | — | Runs each adapter's `scan(None)` (hashes Codex/Grok logs; may start OpenCode catalog) |
| **Quick** | `--quick` | Checks store/executable **presence** only |

## Semantics

- **`present`:** A native store or executable exists; recoverable session counts are
  unknown until a full doctor or `tang index`.
- **`ready` / `empty` / `degraded`:** Full scan results (unchanged).
- **`optional`:** OpenCode absent and not required.

JSON output includes `"mode": "quick"` or `"full"`. Exit code `0` treats
`present` like `ready` for optional components.

## Measured costs (Linux fixture host, 2026-07-21)

Commands run from `/opt/tang` with Codex/Grok fixtures and no OpenCode server:

```text
# Full doctor (representative)
/usr/bin/time -f '%e' tang doctor --json \
  --codex-home tests/fixtures/codex \
  --grok-home tests/fixtures/grok \
  --cwd tests/fixtures/codex/project
# ~0.05–0.15s (fixture size dependent; hashes every JSONL)

# Quick doctor (same paths)
/usr/bin/time -f '%e' tang doctor --quick --json \
  --codex-home tests/fixtures/codex \
  --grok-home tests/fixtures/grok \
  --cwd tests/fixtures/codex/project
# ~0.02–0.04s (directory and executable probes only)
```

On a real host with large Codex rollouts, full doctor can take seconds because
each log is SHA-256 hashed. Quick mode is appropriate at the start of a skill
turn when only installation/path sanity is needed; run full doctor or index
before trusting session counts.

## Read-only guarantee

Quick mode does not create Tang storage, write native logs, or start long-lived
OpenCode processes beyond what a full scan already did.

Pass **`--cursor-home`** (or `CURSOR_HOME`) when transcripts live outside the
default `~/.cursor` layout.
