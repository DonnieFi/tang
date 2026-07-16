# Refresh performance evidence

This note records the Epic 6 refresh investigation. It uses only a synthetic
Codex corpus generated in a temporary project; no user history, user project
database, or user native store is read.

## Recommendation

Keep one authoritative database at `PROJECT/.tang/tang.db`. Do not add a
global catalog, capsule cache, shared adapter checkpoint, daemon, or background
scanner for v0.1. The measured release bottleneck was redundant work inside a
project-local refresh, not SQLite search or database location.

The implementation now hashes every native source on refresh, but skips its
second structured JSON parse only when a version-2 checkpoint proves the same
complete SHA-256 content was previously structurally valid. A legacy checkpoint
is structurally revalidated once. Changed, malformed, unreadable, and
last-known-good sources retain the existing retry and warning behavior.

Graph loading now fetches all component titles in one bounded project query
instead of issuing one capsule lookup per node. Neither change alters public
CLI/JSON output, source selection, or which database is authoritative.

## Reproduce

From a checkout with the test environment installed:

```bash
.venv/bin/python scripts/benchmark_refresh.py \
  --sessions 256 --payload-bytes 131072 \
  --work-dir /tmp/tang-refresh-benchmark \
  --output /tmp/tang-refresh-benchmark.json
```

The script requires an empty supplied directory and creates an isolated non-Git
project and synthetic Codex store under it. It records corpus size, interpreter
and SQLite version, cold/unchanged/incremental index timings, browse/search/
graph timings, database sidecar sizes, `integrity_check`, WAL concurrent-read
evidence, and actual `EXPLAIN QUERY PLAN` output. It never uses `$HOME`,
`CODEX_HOME`, or `GROK_HOME`.

## 2026-07-16 measured result

Host: Linux 6.12.90, CPython 3.12.8, SQLite 3.47.1. Corpus: 256 valid Codex
sessions, about 33.7 MiB native JSONL, 128 KiB visible payload per session,
one 255-edge graph chain. The before and after runs used the same generator,
session count, and payload size; their working-directory names differ by one
character, accounting for a 256-byte difference in embedded synthetic `cwd`
strings (under 0.001% of corpus size).

| Path | Before (s) | After (s) | Result |
|---|---:|---:|---|
| Cold index | 4.190 | 4.194 | Expected: every source must parse and build a capsule. |
| Unchanged index | 0.162 | 0.081 | 50% faster; still content-hashes every source. |
| One-session incremental index | 0.179 | 0.098 | 46% faster; only changed source is parsed/capsuled. |
| Browse 256 rows | 0.006 | 0.005 | Already indexed by `sessions_project_updated`. |
| FTS5 search, 20 results | 0.011 | 0.011 | No measured need for a speculative FTS change. |
| 256-node graph | 0.023 | 0.014 | 39% faster; no per-title capsule queries. |

The post-index discovery target is well below the release under-10-second
budget on this corpus. Real host timing remains dependent on native-store size
and filesystem throughput; the skill therefore indexes once at recovery start,
then searches the stable indexed snapshot rather than refreshing before every
query.

The post-change query plans were:

| Query | Evidence |
|---|---|
| Browse | `SEARCH s USING INDEX sessions_project_updated (project_key=?)`; capsule primary-key lookup. |
| Search | FTS5 virtual-table scan for `MATCH`, session and capsule primary-key lookups, and a temporary sort for explicit relevance/timestamp/source ordering. |

`PRAGMA integrity_check` returned `ok`; journal mode was `wal`; a separate
reader completed `SELECT count(*) FROM sessions` while another connection held
`BEGIN IMMEDIATE`.

## Comparative storage research

| Tool/design | Local state | Global state | Useful lesson for Tang |
|---|---|---|---|
| [Ruff cache settings](https://docs.astral.sh/ruff/settings/) | Defaults to `.ruff_cache` at the project root. | An explicit cache-dir can opt into another location. | Keep project-scoped results close to the project and make any alternate path explicit. |
| [mypy incremental mode](https://mypy.readthedocs.io/en/stable/config_file.html#incremental-mode) | Defaults to `.mypy_cache`; it can use SQLite for incremental cache information. | `MYPY_CACHE_DIR` can override the location. | A local incremental database is a normal developer-tool pattern; cache location must be deliberate. |
| [uv caching](https://docs.astral.sh/uv/concepts/cache/) | The target environment remains separate from cache entries. | Uses an XDG/home cache for immutable dependency artifacts; it is append-only, concurrency-safe, and explicitly cleanable. | A global cache is appropriate only for rebuildable, non-private artifacts with clear invalidation—not session metadata or recovered text. |
| [Cargo Home](https://doc.rust-lang.org/cargo/guide/cargo-home.html) and [build cache](https://doc.rust-lang.org/cargo/reference/build-cache.html) | Workspace-root `target` holds build outputs by default. | `$CARGO_HOME` holds downloaded registry/Git sources and metadata. | Hybrid designs separate public/rebuildable dependency downloads from project outputs; they do not justify sharing private Tang capsules or edges. |

SQLite's [WAL documentation](https://www.sqlite.org/wal.html) supports the
existing same-host model: readers can proceed with a writer, while WAL is not a
network-filesystem protocol. Tang keeps its database, WAL, and shared-memory
sidecars together in the canonical project directory.

## Options considered

| Option | Evaluation | Decision |
|---|---|---|
| Project-only authoritative database | Measured bottleneck is redundant parsing, so this removes it with no cross-project state or new deletion surface. Existing Git common-directory resolution preserves worktree sharing; separate clones remain isolated. | Keep. |
| Global non-content catalog or scan cache | Could avoid some cross-project native discovery, but it adds a privacy-sensitive list of projects/sessions, a second purge/revocation path, move/rename rules, and a risk of silently selecting a different project. The benchmark shows no need. | Reject for v0.1; research only under backlog `tang-9nb` with explicit approval. |
| Shared adapter checkpoints across project shards | A native session store spans projects, so a global cursor can suppress another project's eligibility or make removal semantics ambiguous. Per-project opaque checkpoints are intentionally isolated. | Reject. |

Because no global accelerator exists, loss of any hypothetical global cache has
no effect: the project database is rebuilt with `tang index`. `tang purge --all`
removes only that project's derived data; it never changes native logs. The
existing project/worktree, purge, WAL, migration, and adapter retry tests remain
the release regression coverage for those invariants.
