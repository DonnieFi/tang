# Tang visual assets

## `tang-mascot-concept.png`

The samurai mark sits beside the README promise. It is displayed at a reduced width. The hero of the page is the Multiverse Map, not the mark.

## `tang-multiverse-demo.svg`

A framed capture of the real isolated `tang demo`. Regenerate it after the demo story changes:

```bash
cargo build --manifest-path rust/Cargo.toml --release
python3 scripts/capture_demo_hero.py \
  --tang ./rust/target/release/tang \
  --output docs/assets/tang-multiverse-demo.svg
```

The script only draws that command's output. It does not open a user's database or native logs.

## `tang-session-cards.png`

The approved session-card treatment embedded beside the cards section of the README. The source HTML stays outside the repository.
