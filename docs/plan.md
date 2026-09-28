# Lindenfret: Implementation Plan

Design: [design.md](design.md)

Seven phases, built in order. Each ends in a gate you can check from the command line or by ear. The musical facts the generator needs come from the reference MIDIs, as summarized in the design: the pattern, rhythm, form, palette, planing idiom and left-hand limits. Nothing from the reference is copied into a generated piece. So no phase waits on transcribing the score.

| Phase | Scope | Exit gate |
| --- | --- | --- |
| 0. Foundation | Repo, venv, packaging, reference analysis, config, RNG streams, CLI stub | `analyze_reference.py` reproduces the design's reference facts, and `inspect` prints the same derivation for the same seed on every run |
| 1. Fretboard and voicer | `Fingering`, enumerate / filter / score, span ≤ 5, fret ≤ 13, chord symbols transposed to all 12 centers | Every palette chord, in every center, has a fingering that passes all hard rules somewhere on the neck, apart from exceptions pinned in the playability test (so far only E♭m/G♭ in E♭ minor), and `inspect --center` shows which hand positions each chord can use |
| 2. Grammar and harmony | Two-level bracketed L-system, alphabet, length control, tonal centers and modulation, weighted graph, cadences | Changing one rule visibly changes the section plan in `inspect`. `inspect` shows every bar's center, and centers change only at `M`, `]` and section starts |
| 3. Rendering and export | Pattern with bar repeats and let-ring, ritardandos, music21 score with no key signature, MIDI, MusicXML, manifest | The reference test passes, MusicXML opens in MuseScore with correct notes, spelling and rhythm, and `regenerate` reproduces byte-identical MIDI |
| 4. Villa-Lobos idiom | Planing mode, Etude 1 preset, batch and curation | A listening pass over 20 seeds finds variants worth practicing |
| 5. Etude 2 | Preset-level palette key, optional tones and notation; contour patterns over ladders of stops; Etude 2 reference analysis and preset | Etude 1's plans are unchanged apart from its preset hash, every Etude 2 reference bar is playable under its preset, and a listening pass over 20 Etude 2 seeds finds variants worth practicing |
| 6. Exotic harmony | Polychord symbols; an exotic preset for each étude, with a wider palette and harmony weights | Every added chord is playable in every center, and a listening pass over 20 seeds of each finds variants worth practicing |

## Phase 0: Foundation

- [x] `git init`.
- [x] `.gitignore` for the venv, Python caches, `out/` and `.DS_Store`.
- [x] Reference MIDI in `reference/Villa-Lobos_Etude_No1b.mid`.
- [x] Create the venv with Homebrew's Python 3.14: `python3 -m venv .venv`, then `.venv/bin/pip install -e '.[dev]'`. If a different Python version is ever needed, use a conda env.
- [x] Add `pyproject.toml`: `requires-python = ">=3.11"` (for `tomllib`), depends on music21 and mido, dev extras pytest and hypothesis.
- [x] Write `tools/analyze_reference.py`. It prints the reference facts in the design, reading the pattern and tuning from the config: the pattern check, bar repeats, frets and chord per bar, left-hand limits and tempo changes. `tests/test_reference.py` checks the same facts.
- [x] Write `configs/etude1.toml`: pattern, meter, tempo, bar repeat, center weights and moves, minor and major palettes written in E, chord graph weights, planing shape weights, `max_span = 5`, `max_fret = 13`.
- [x] Add the package skeleton: config dataclasses with a TOML loader that validates every key, the per-stage RNG helper, weighted stochastic L-system rewriting, and `lindenfret inspect`, which prints each section's derivation per iteration with its bar count.

## Phase 1: Fretboard and voicer

- [x] Tuning and `Fingering` model; enumeration with span pruning, hard filter, scoring, and sampling among the top candidates (`fretboard.py`).
- [x] Hard rules from the design: every pattern string sounds, span ≤ 5, no fret above 13, at most 4 fingers with a barre at the lowest fret, required tones and bass present, tensions only on allowed strings.
- [x] Soft preferences from the reference, weighted in `[voicer]`: span of 3 or less, open strings, small hand movement between bars, few doubled tones other than the root and fifth.
- [x] A separate `check_fingering()`, used by the tests and asserted every time the voicer chooses.
- [x] Load the palette's chord symbols and transpose them to all 12 centers with music21 (`chords.py`), with the transposition, spelling and playability tests.
- [x] Text view: `inspect --chord Em7 --region 0-4` lists the top fingerings, and `inspect --center Gm` shows how many fingerings each palette chord has at each hand position.

## Phase 2: Grammar and harmony

- [x] Length control (`interpret.py`): each section uses its first iteration inside its length range, and re-derives from its RNG stream on overshoot, up to 50 attempts.
- [x] The walk (`harmony.py`): each section's symbol string becomes bars, with brackets saving and restoring chord, center and fret region, and `+`/`-` stopping at the ends of the neck.
- [x] `Center` model and center graph: start weights, `M` moves (thirds are major thirds), one move at each graph section's start, and only centers playable in the current region.
- [x] Weighted chord graph per mode that favors stepwise bass motion and offers only chords playable in the current region. Tonic and dominant chords come from the palette, and `K` plays dominant then tonic, falling back to a step with a note when neither fits.
- [x] `pipeline.py` plans a whole piece and voices every graph bar; `lindenfret inspect --seed N` prints every bar's center, chord, fingering, region, role and events.

## Phase 3: Rendering and export

- [x] Renderer (`render.py`) that plays the fixed pattern over each bar's fingering, repeats each bar, and holds every note to the bar line or its string's next pluck, with the reference's accents as velocities.
- [x] Reference test: the reference's own fingerings for bars 1–44 render to the reference MIDI's pitch in every 16th-note slot.
- [x] Ritardando over the last bar pair of each section in the MIDI, marked "rit." and "a tempo" in the notation.
- [x] music21 score builder (`score.py`): one guitar part of single-line 16ths beamed by beat, treble clef an octave down, a "hold every note" direction, no key signature, pitches spelled from their chords. Checked by rendering with MuseScore 4.
- [x] MIDI (mido, one channel per string), MusicXML and manifest export (`export.py`), plus the `generate`, `batch` and `regenerate` commands.

## Phase 4: Villa-Lobos idiom

- [x] Planing mode (`planing.py`): a shape generated per sequence (four fretted strings, two open, kind drawn by weight, comfortable span, whole slide in the region), checked against the hard rules at every fret it reaches, and moved by `+` and `-`.
- [x] Planing bars spelled in the notation without letter clashes, in stacked thirds where possible.
- [x] Etude 1 preset: graph-mode sections open and close the piece, with planing sequences between them.
- [x] Batch of 20 generated: `lindenfret batch --config configs/etude1.toml --count 20 --first-seed 1` wrote `out/etude1-1` to `out/etude1-20`.
- [ ] Listen, and record the keepers with their config hash in `curated.toml`.

## Phase 5: Etude 2

- [x] Move Etude 1 assumptions into the config: `[palette] tonic` and `optional_intervals`, and a `[notation]` table for the title and opening direction.
- [x] Pattern kinds: a preset sets either `strings` (Etude 1) or `contour` (Etude 2). A contour also sets `notes_per_string`, `hand_positions` and `max_slide`, and the voicer's `shift` weight.
- [x] Ladders (`ladder.py`): enumeration with slides along a string, an independent `check_ladder()`, a fast existence check for the harmony stage, and rendering that stops a fretted note when the hand slides.
- [x] `analyze_reference.py` handles contours: the bars that follow the pattern, their ladders, median accents, and whether each ladder is playable under the preset.
- [x] Etude 2 preset (`configs/etude2.toml`): palette in A from bars 1–18 and 22–47, left-hand limits measured from the reference, reference tests and golden snapshots.
- [x] Both presets' velocities are the reference's medians, which `analyze_reference.py` now computes.
- [x] Batch of 20 generated: `lindenfret batch --config configs/etude2.toml --count 20 --first-seed 1` wrote `out/etude2-1` to `out/etude2-20`.
- [ ] Listen to a batch of 20 Etude 2 seeds, tune the minor palette, form rules and `shift` weight by ear, and record keepers in `curated.toml`.

## Phase 6: Exotic harmony

- [x] Polychords in palettes: `D|C` stacks D major over C major; only the lower chord may leave out its optional intervals.
- [x] `configs/etude1-exotic.toml` and `configs/etude2-exotic.toml`: each base palette plus added-tone tonics, Lydian, Dorian and Phrygian polychords, altered dominants and a tritone substitute. Held basses and tritone moves weigh double, moves by a major third are twice as likely, and the reference bonus is halved.
- [x] Batches of 20 generated: `lindenfret batch --config configs/etude1-exotic.toml --count 20 --first-seed 1`, and the same for `etude2-exotic.toml`, wrote `out/etude1-exotic-1` to `-20` and `out/etude2-exotic-1` to `-20`.
- [ ] Listen to 20 seeds of each, prune chords that don't fit by ear, and record keepers in `curated.toml`.
