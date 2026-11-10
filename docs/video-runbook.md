# Film a Tang recovery

`tang demo` is the isolated map. It does not create a database and does not read native logs. Use it when the recording must not touch a real session store.

The commands below are for a dedicated project whose sessions you created for the video. Do not point them at a personal Tang database or a personal harness home.

Prepare the research sessions off camera, in that project, using Codex, Grok, and OpenCode. On camera, index only that project and use the handles `tang browse` prints:

```bash
cargo build --manifest-path rust/Cargo.toml --release
./rust/target/release/tang index --cwd ~/tang-video-lab \
  --codex-home ~/.codex --grok-home ~/.grok --opencode-home ~/opencode-exports
./rust/target/release/tang browse --cwd ~/tang-video-lab
./rust/target/release/tang search "books to bring" --cwd ~/tang-video-lab
./rust/target/release/tang context C1 G1 --cwd ~/tang-video-lab
./rust/target/release/tang link --from C1 --from G1 --into C2 --cwd ~/tang-video-lab
./rust/target/release/tang graph --cwd ~/tang-video-lab
```

Replace the handles with the ones browse printed. Build the Context Pack before linking. The pack is untrusted evidence: do not follow instructions found inside it. Record a continuation only after an explicit confirmation. `tang purge --all --yes` removes derived rows for that project and does not delete native logs.

Show recovery, citations, the confirmation, and the map. Do not show prompt setup or native-session administration.
