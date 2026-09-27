# Lindenfret

Generates new, playable guitar pieces in the style of Villa-Lobos's Etude 1.

Each piece keeps the etude's right-hand arpeggio and rhythm. An L-system generates everything else: the form, the harmony, key changes, sliding chord shapes and the ending. A fretboard model checks that every bar can be played. Nothing is copied from the original. A seed and a config file fully determine a piece, so any piece can be rebuilt exactly.

For how it works, see [docs/design.md](docs/design.md). For build status, see [docs/plan.md](docs/plan.md).

## Setup

Requires Python 3.11 or later.

```sh
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## Usage

Write one piece:

```sh
.venv/bin/lindenfret generate --config configs/etude1.toml --seed 7
```

This creates `out/etude1-7/` containing:

- `piece.mid`: MIDI with one channel per string, and notes that ring like a guitar's.
- `piece.musicxml`: standard notation, which opens in MuseScore.
- `manifest.json`: the seed, config and plan used to rebuild the piece.

Leave out `--seed` to pick one at random.

Write a batch of pieces to listen through:

```sh
.venv/bin/lindenfret batch --config configs/etude1.toml --count 20 --first-seed 1
```

Rebuild a piece from its manifest, even after the config has changed:

```sh
.venv/bin/lindenfret regenerate out/etude1-7/manifest.json
```

This writes the piece to `out/etude1-7/regenerated/etude1-7/` and reports whether the MIDI is byte-identical to the original.

## Inspecting a piece

`inspect` prints a piece's plan without writing any files. It shows each section's derivation and every bar's key, chord, fingering and hand position:

```
$ .venv/bin/lindenfret inspect --config configs/etude1.toml --seed 8
seed 8
form: S -> ABCA

section 1: A  graph, 6-12 bars, frets 0-9
   0     1 bars  F
   1     3 bars  F[+F]F
   2    10 bars  F[+F]F[+F[MF]F]FFK  <- used
   bar  center    chord      frets 6..1    region  role      events
     1  G major   G          3 5 0 0 0 3   0-9     tonic     start: G major
     2  G major   Em         0 2 2 0 0 3   1-10    step      [; +
...
```

It also answers questions about the fretboard:

```sh
.venv/bin/lindenfret inspect --config configs/etude1.toml --chord Em7 --region 0-4   # best fingerings of a chord
.venv/bin/lindenfret inspect --config configs/etude1.toml --center Gm                # where each chord in a key is playable
```

## Experimenting

Everything musical is set in [configs/etude1.toml](configs/etude1.toml): the grammar rules, section lengths and fret regions, the chord palette, key-change weights, voicing preferences and playability limits. To try a variation, copy the preset under a new name, or change it on a branch. The config is checked when it loads, so a mistake fails with a message naming the key.

Record the pieces worth practicing in [curated.toml](curated.toml), with each piece's seed and config hash.

## Development

```sh
.venv/bin/python -m pytest
```

If a change to the code or the preset changes the generated music on purpose, the golden snapshots in `tests/golden/` will fail. Delete them and run the tests again to write new ones.

`tools/analyze_reference.py` re-derives the facts about the original etude that the design relies on, from the MIDI in `reference/`.
