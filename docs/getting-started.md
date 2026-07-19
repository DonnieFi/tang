# Tang: download, install, test, and use

Tang is a Linux tool for finding earlier Grok, Codex, or OpenCode work from the
project you are currently in and continuing that work inside Codex or OpenCode
with citations. Tang does not copy whole transcripts into a new tool. It builds
a small, redacted, source-cited Context Pack and records a continuation only
after you confirm it.

Tang v0.2.9 is still a release candidate and the **minimum reviewed build**.
The source repository is available, but the final tagged wheel download does
not exist until the release gate is approved and published.

## What you need

- A Linux computer.
- Python 3.11 or newer.
- `uv`, which installs Tang into an isolated environment.
- Codex CLI, OpenCode `>=1.17.18,<2.0.0`, and/or a supported local Grok
  session store if you want to use Tang with your own sessions.

Check the basics:

```bash
python3 --version
uv --version
```

If `uv` is missing, install it using the official Astral instructions. Do not
run an installer copied from this repository; Tang intentionally does not ship
a custom shell installer.

## Download the release candidate for testing

For pre-release functional testing, use a Tang source checkout and the exact
wheel produced from the same reviewed commit.

Clone the repository on the test host if that host can reach GitHub:

```bash
git clone https://github.com/DonnieFi/tang.git
cd tang
git checkout <release-candidate-commit>
```

The wheel is not public yet. Copy
`tang_multiverse-0.2.9-py3-none-any.whl` from the build host to the repository
directory on the test host using your normal secure file-transfer method. Also
record its SHA-256 hash on the build host:

```bash
sha256sum tang_multiverse-0.2.9-py3-none-any.whl
```

After copying, run the same command on the test host. The two hashes must match.
This proves that the host tested the artifact that the build host produced.

## Run isolated functional acceptance

From the source checkout, run:

```bash
python3 scripts/functional_acceptance.py \
  ./tang_multiverse-0.2.9-py3-none-any.whl \
  --output tang-functional-evidence.json
```

To test a particular supported interpreter:

```bash
python3 scripts/functional_acceptance.py \
  ./tang_multiverse-0.2.9-py3-none-any.whl \
  --python python3.11 \
  --output tang-functional-evidence-python311.json
```

The script does all of its product work in a temporary directory. It installs
the wheel into a fresh virtual environment and uses only Tang's synthetic test
sessions. It does not read your real Codex, Grok, or OpenCode history and does
not use your normal project Tang database.

The run checks:

- clean installation from the wheel without rebuilding Tang;
- partial and incremental indexing exit behavior;
- current-project search across Grok and Codex;
- project isolation and redaction of synthetic secret canaries;
- fair, cited multi-source context under the token and timing limits;
- Codex skill installation;
- explicit many-source continuation links;
- ambiguity and cycle refusal;
- wide Unicode and narrow ASCII Multiverse maps;
- readiness reporting and complete derived-data purge; and
- byte-for-byte preservation of the synthetic native inputs.

A successful run exits `0`, prints JSON with `"result": "pass"`, and writes the
same report to the path passed with `--output`. Send that JSON file back for the
release review. It contains the wheel hash, Linux and Python environment, exit
codes, and timings; it does not contain private transcripts.

If the run fails, keep the error text and rerun with a persistent empty work
directory so the temporary database and copied fixtures remain available for
debugging:

```bash
mkdir tang-functional-work
python3 scripts/functional_acceptance.py \
  ./tang_multiverse-0.2.9-py3-none-any.whl \
  --work-dir ./tang-functional-work \
  --output tang-functional-evidence.json
```

Do not edit the fixture data to make a failure pass. Report the command, error,
operating-system details, Python version, and wheel hash so the defect can be
reproduced and fixed.

## Install Tang for normal use

Until the public release exists, install the local wheel:

```bash
uv tool install ./tang_multiverse-0.2.9-py3-none-any.whl
tang skill install codex
```

Once v0.2.9 is approved and published, install the exact version-pinned GitHub
release instead. Do not install an unversioned development build when verifying
the release:

```bash
uv tool install https://github.com/DonnieFi/tang/releases/download/v0.2.9/tang_multiverse-0.2.9-py3-none-any.whl
tang skill install codex
```

Check the installation:

```bash
tang --help
tang --version
tang doctor
```

Start a new Codex session after installing the skill. Invoke `$tang` or ask
Codex in plain English to use Tang. Tang v0.2.9 installs a Codex skill, not a
`/tang` slash command, so it might not appear in a slash-command picker.

For OpenCode `>=1.17.18,<2.0.0` on Linux, install the integration into the
current project, restart OpenCode there, and invoke `/tang`:

```bash
tang skill install opencode --project-root "$PWD"
```

This installs Tang-owned files only under the project's `.opencode` directory.
The transcript source contract is provider-independent: an OpenCode session can
use OpenAI, xAI, or another model provider without changing how Tang reads its
visible user and assistant turns.

`tang resume O1` uses the tested OpenCode launch contract
`opencode <recorded-project-directory> --session <private-native-id>`. It
therefore requires the same indexed worktree: use Tang from that worktree, or
re-index and link from the other worktree rather than treating sibling checkouts
as interchangeable native session stores.

### Choose where to use Tang

- **Codex:** `tang skill install codex`, then start a new Codex session in the
  project and invoke `$tang` (or ask Codex in plain English).
- **OpenCode:** run the project-local install command above, restart OpenCode
  in that project, and invoke `/tang`.
- **Grok:** no Tang plugin is installed in Grok for v0.2. Its local history is
  a supported read-only source; run the same Tang CLI from the project terminal,
  Codex, or OpenCode to recover it into the current supported target.
- **CLI:** `tang index`, `browse`, `search`, `context`, `link`, `graph`, and
  `resume` work from any of those project terminals. Use a harness skill when
  you want guided, native selection.

From a normal terminal, `tang resume C5` reopens the exact indexed Codex session
behind `C5`; `tang resume O1` does the same for OpenCode. Tang keeps the native
ID private and refuses Grok, missing, foreign-worktree, and unavailable
sessions. Resume is only a native launcher: it does not build context, inject
transcript text, or create a continuation edge. Inside an already-running Codex
or OpenCode session, use `$tang` or `/tang` for cross-harness recovery rather
than starting a nested interactive host.

`tang doctor` is a readiness check. Before your first index it can report that
the derived database is not initialized. An adapter can also be empty or
degraded. If OpenCode is absent, doctor labels it **optional** so a ready
Codex/Grok path remains ready; use `tang doctor --require-opencode` when
preparing the OpenCode workflow. Read the individual messages; a nonzero result
does not necessarily mean the CLI installation itself failed.

`tang index` reports `refreshed` separately from `indexed`: it counts stored
Capsules whose derived display labels changed without rereading native history.

### Separate-host smoke checklist

Before recording or publishing a candidate, test the exact transferred wheel
on a second Linux host—not from a development checkout. Record the source
commit and the wheel's SHA-256 on the build host, compare that hash on the test
host, then install and verify the artifact:

```bash
uv tool install --force ./tang_multiverse-0.2.9-py3-none-any.whl
tang --version
tang doctor
tang demo --ascii
```

Install each available host integration and restart that host before using its
command:

```bash
tang skill install codex --force        # then start Codex and use $tang
tang skill install opencode --project-root "$PWD" --force  # restart, then use /tang
```

In a real project, test `tang index`, `browse`, `search`, `context HANDLE`, an
explicitly confirmed link, `tang graph HANDLE`, and `tang context all --for
HANDLE`; verify its cited predecessors match the displayed graph. Then test
`tang resume HANDLE` for one Codex or OpenCode session, followed by deletion
without touching native history:

```bash
tang purge --all --yes
tang browse                 # no derived sessions remain
tang index                  # rebuilds only the project-local derived database
```

After the rebuild, the same native sessions should be discoverable again. Keep
only privacy-safe command results, version strings, source commit, and wheel
hash in the smoke record—never raw session IDs or transcript content.

### Uninstall or replace the CLI

Tang's uv package name is `tang-multiverse`, even though the command is `tang`:

```bash
uv tool uninstall tang-multiverse
command -v tang  # prints nothing after a successful uninstall
```

This removes the global executable and its isolated uv environment. It does not
delete a project's `.tang/tang.db`, rewrite Codex, Grok, or OpenCode history, or
remove a skill integration installed separately. Reinstall the same or a newer wheel with the
version-pinned `uv tool install ...` command above.

## The recommended way to use Tang

The Codex skill is Tang's interactive workflow. Open Codex in the project whose
history you want to recover, then ask in plain English, for example:

> Use Tang to find the earlier session where we discussed checkpoint recovery.

Tang will index only that current project, show a short redacted list of up to
five numbered session choices at a time, and ask you to select one or more
choices. After selection, it creates a
cited Context Pack. Codex uses that evidence to present:

- the best-supported resume point;
- one evidence-backed next action; and
- important uncertainty or missing context.

Recovered transcript text is treated as untrusted historical evidence, not as
instructions. Tang does not save Codex's synthesized brief. Before writing a
continuation edge, Codex must show the sources and target and ask for explicit
confirmation.

## Using the command line directly

Run these commands from the project you care about.

First, index supported local history:

```bash
tang index
```

Exit code `0` means indexing completed. Exit code `1` means Tang retained useful
results but encountered warnings, such as a malformed or unavailable session.
Read the warnings before deciding whether to continue.

Run `tang index` at the start of a recovery workflow or after eligible native
history changes. It is incremental: unchanged sessions are not reread. It also
backfills a missing Tang display title from an already-redacted Discovery
Capsule, so a normal refresh upgrades older titleless graph rows without a
destructive rebuild.

Browse everything indexed for this project, or search using words you remember:

```bash
tang browse
tang search "checkpoint recovery"
tang browse --page 2
```

Search matches ordinary word forms, so `tang search book` also finds a capsule
containing `books`; quoted phrases retain their normal FTS phrase semantics.

The human list intentionally hides long implementation IDs. It shows a redacted
name, harness, time, health, capability status, a page choice such as `[2]`,
and a short project handle such as `C1` (Codex) or `G1` (Grok).
`--page 2` shows the next five choices. In Codex, Tang maps a selected number
to its exact canonical ID privately and will refuse a stale or out-of-range
number rather than guessing.

When Codex supplies the active session identity, the skill excludes it from
these results. Some Codex hosts do not provide that identity. In that case the
skill continues with the same explicit selection flow and clearly says that the
active session may appear; it never guesses which result is active. Link-time
self-link rejection and explicit target confirmation still apply.
This does not relax direct terminal use of `--exclude-current`: without a
supplied native ID, that flag still requires one unambiguous indexed Codex
candidate and otherwise refuses rather than guessing.

Use the short handle directly in human commands. Handles are case-insensitive,
remain stable across refreshes in the project's `.tang/tang.db`, and reset only
when `tang purge --all` removes all derived project data:

```bash
tang context G1 C2
tang context all
tang context 2 --for C2
tang graph C2
tang resume C2
```

For scripts, request JSON to obtain an exact canonical source ID. JSON is also
where Tang keeps the authoritative mapping used by the Codex skill:

```bash
tang browse --json
```

Pass one or more handles—or exact IDs from JSON—to build a Context Pack:

```bash
tang context <handle-or-source-id> [<another-handle-or-source-id> ...]
```

After an explicitly confirmed continuation, `tang context` (or `tang context
all`) recalls every confirmed predecessor of the one latest confirmed target.
Use `tang context N` to include at most `N` predecessor-link hops, or add
`--for HANDLE` when you want a particular confirmed target. This rereads the
same cited source evidence; it deliberately excludes the target's own turns.
Pass that target handle explicitly alongside the predecessors if you need it.
Tang never stores a generated session summary.

Inside a linked current host session, `$tang context` in Codex or `/tang
context` in OpenCode performs that predecessor recall and writes the cited
brief in one request. Neither shorthand records nor changes a continuation
edge.

For scripts, add `--json` to `index`, `browse`, `search`, or `context`. Add an
explicit `--page N` to page JSON results in five-choice groups; otherwise JSON
returns the complete deterministic result set for automation. Tang JSON uses
`schema_version: 1` and RFC 3339 timestamps.

Continuation links should normally be confirmed through the Codex skill because
the skill verifies the active target with you. The canonical command is
`tang link`, not `tang connect`. After you have selected source IDs, reviewed
their Context Pack, and explicitly confirmed one target, use either a
host-confirmed current Codex target:

```bash
tang link --from <handle> [<another-handle> ...] \
  --current --current-native-id <native-id>
```

or an explicitly chosen current-project target:

```bash
tang link --from <handle> [<another-handle> ...] \
  --to <target-handle>
```

Tang never infers the target. A successful repeat is safe: it reports existing
edges instead of adding duplicates. After a confirmed link, render the
connected component containing the returned target ID:

```bash
tang graph <source-or-target-handle>
```

Inside the Codex host skill, a supplied native current-session ID means the
confirmed target is the active session only. If you deliberately need to
connect two already indexed historical handles, use the explicit normal-terminal
`tang link --from <source-handle> --to <target-handle>` path after reviewing the
sources and confirming that exact edge set.

In a normal terminal after a confirmation, bare `tang graph` focuses the one
latest confirmed target when there is exactly one. It never chooses a native
session by recency or marks that fallback as the active host session; pass a
handle such as `tang graph O1` whenever you want an exact component.

To reopen an indexed session in its own native harness, pass its displayed
handle from a normal terminal:

```bash
tang resume C5  # launches Codex with the private native ID
tang resume O1  # launches OpenCode with the private native ID
```

Tang never prints the private native ID. Only current-project, native-available
Codex and OpenCode sessions can launch. Resuming does not imply that another
source supplied context and never records a continuation; use `$tang` or
`/tang` inside the active host for that recovery and confirmation workflow.

Use an accessible fallback when needed:

```bash
NO_COLOR=1 tang graph <source-or-target-handle> --ascii --width 40
```

To delete everything Tang derived while leaving native harness history alone:

```bash
tang purge --all
```

Tang asks for confirmation. In a deliberate non-interactive script, use
`tang purge --all --yes`. Purge removes every Tang-derived row but leaves the
empty `.tang/tang.db` SQLite container in place so its secure permissions,
schema, and WAL configuration can be reused. Native history is never removed.

## Where Tang keeps data

Tang reads supported native session stores but does not rewrite them. Its own
derived SQLite database lives in the canonical project folder:

```text
PROJECT/.tang/tang.db
```

Git worktrees that share one Git common directory share that canonical project
database. Separate clones and non-Git directories use separate databases.
Tang creates `.tang` with user-only permissions on supported POSIX systems.
Tang never silently falls back to a temporary or user-global database; use
`--database PATH` only when you deliberately need an isolated diagnostic or
test database. Add `.tang/` to a project `.gitignore` if that project does not
already ignore it; Tang does not edit your project files for you.

Early Tang release candidates used `~/.local/share/tang/tang.db`. v0.1.0 does
not import that experimental global database because its rows cannot be safely
assigned to one canonical project. Run `tang index` in each project to rebuild
the authoritative local data, verify the results, and then remove the obsolete
global file manually if you no longer need it.

The database contains project-scoped session metadata, small redacted Discovery
Capsules, adapter checkpoints, search rows, and explicitly confirmed graph
edges. Capsule headers may retain an evidenced model/provider, Codex effort,
visible-turn count, approximate visible-text size, and title origin. It does
not store Codex's generated Continuation Brief or a Tang-generated session
summary. These header facts are harness-dependent: missing fields mean the
native source did not supply evidence, not that Tang inferred an absence.

The first `tang index` after upgrading to v0.2.9 may reread previously indexed
sessions once to refresh derived labels and these bounded headers. It preserves
handles and confirmed edges, then resumes normal incremental refresh behavior.

## Early FAQ

### Why does search show nothing?

Make sure you ran `tang index` from the same project. Tang v0.2.9 deliberately
does not search across unrelated projects. Try another memorable keyword or a
quoted phrase and inspect indexing warnings.

### Why is `/tang` missing from Codex?

Tang installs a skill rather than a slash command. Start a new Codex session,
invoke `$tang`, or ask Codex to use Tang for recovering earlier work. If Codex
still cannot find it, rerun `tang skill install codex --force`, start another
new session, and confirm that the `tang` CLI itself is available with
`tang --help`.

### Does Tang modify my Codex or Grok sessions?

No. Supported adapters are read-only. `tang purge --all` deletes Tang's derived
database records, not native history.

### Is redaction the same as encryption?

No. Tang excludes hidden/tool content and applies redaction at storage and
display boundaries to reduce accidental disclosure. That is not encryption or
a promise of protection against forensic recovery.

### Can Tang continue work into Grok?

No. Grok is a supported read-only source. Codex and OpenCode are supported
destinations, and Tang requires an exact current target plus explicit approval
before it records a continuation.

### Are macOS and Windows supported?

No compatibility claim is made for v0.2.9. The release is tested and supported
on Linux with Python 3.11 or newer.

### Why did `tang index` exit with code 1 even though search works?

Code `1` means the index is partial, not empty. Tang preserves recoverable
sessions and reports warnings so automation and people can decide whether the
available evidence is adequate. A `diagnostic[foreign]` instead identifies a
store-wide issue Tang proved belongs to another project; it remains visible but
does not turn a complete current-project index into exit code `1`.

### Can Tang automatically choose which sessions to recover or link?

No. Tang can rank search results, but you choose exact sources. It also refuses
to guess an ambiguous continuation target or create a self-link or cycle.
