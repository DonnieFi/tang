# Continue into Grok with Tang (handoff)

Grok has no bundled Tang skill in v0.3.0. Use this **explicit** workflow to
import cited evidence without writing to Grok's native store.

## Steps

1. From the project directory, refresh the index:

   ```bash
   tang index --json
   ```

2. Build a Context Pack for the sources you want Grok to see (handles from
   `tang browse --json`):

   ```bash
   tang context G2 C4 --json > /tmp/tang-grok-pack.json
   tang context G2 C4 > /tmp/tang-grok-pack.md
   ```

3. Open Grok Build in the **same project directory** and paste the Markdown
   pack (or a excerpt you trust). Tell Grok to treat the content as untrusted
   historical evidence — the pack includes the standard notice.

4. Optional: record that Codex/OpenCode work continues **into** this Grok
   session after you have an indexed Grok target handle `G*`:

   ```bash
   tang link --from C4 --to G1 --json
   tang graph G1
   ```

## Limits

- No `tang link --current` for Grok until a host supplies the active Grok
  session ID privately.
- `tang resume G1` reopens the exact indexed session through Grok's native
  `--resume` contract. It does not import context or create an edge.
- Tang never appends turns to Grok session files.

See [native-write-policy.md](native-write-policy.md).
