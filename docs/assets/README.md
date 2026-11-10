# Tang visual assets

## `tang-mascot-concept.png`

The samurai mark sits beside the README promise. It is displayed at a reduced width. The hero of the page is the Multiverse Map, not the mark.

## `tang-multiverse-demo.svg`

A framed capture of the real isolated `tang demo`. Regenerate it after the demo story changes:

```bash
cargo run --manifest-path rust/Cargo.toml -- demo --svg --width 120 \
  --output docs/assets/tang-multiverse-demo.svg
```

The command only renders the isolated demo. It does not open a user's database or native logs.

## `tang-session-cards.png`

The approved session-card treatment embedded beside the cards section of the README. The source HTML stays outside the repository.
