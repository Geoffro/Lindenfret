"""Analyze the reference MIDI of Etude 1 and print the facts docs/design.md relies on.

The pattern and tuning come from the config, so this also confirms that the
preset's pattern matches the reference.

    .venv/bin/python tools/analyze_reference.py [--midi PATH] [--config PATH]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import mido
from music21 import chord, pitch

from etudegen.config import load_config

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIDI = ROOT / "reference" / "Villa-Lobos_Etude_No1b.mid"
DEFAULT_CONFIG = ROOT / "configs" / "etude1.toml"


@dataclass(frozen=True)
class Note:
    start: int  # ticks from the start of the piece
    duration: int
    midi: int


@dataclass
class Facts:
    bar_count: int
    time_signatures: list[tuple[int, str]]  # (bar, "4/4")
    key_signatures: list[tuple[int, str]]
    tempos: list[tuple[int, int]]  # (bar, quarter notes per minute)
    onsets_per_bar: dict[int, int]
    off_grid_bars: list[int]  # bars with onsets off the pattern's note grid
    arpeggio_bars: list[int]  # a full bar of pattern notes on the grid
    frets: dict[int, tuple[int, ...]]  # pattern-matching bar -> fret per string, 6 to 1
    mismatches: dict[int, str]  # arpeggio bar -> why it doesn't fit the pattern
    repeated_bars: list[int]  # bar n sounds exactly like bar n + 1
    open_low_starts: int  # arpeggio bars whose first note is the open lowest string
    bar_pitches: dict[int, list[frozenset[int]]] = field(repr=False)

    @property
    def matching_bars(self) -> list[int]:
        return sorted(self.frets)

    @property
    def max_fret(self) -> int:
        return max(max(frets) for frets in self.frets.values())

    @property
    def max_span(self) -> int:
        return max(_span(frets) for frets in self.frets.values())


def load_notes(path: Path) -> tuple[mido.MidiFile, list[Note]]:
    midi = mido.MidiFile(path)
    notes = []
    for track in midi.tracks:
        tick = 0
        sounding: dict[tuple[int, int], list[int]] = defaultdict(list)
        for message in track:
            tick += message.time
            if message.type == "note_on" and message.velocity > 0:
                sounding[(message.channel, message.note)].append(tick)
            elif message.type in ("note_off", "note_on"):
                starts = sounding[(message.channel, message.note)]
                if starts:
                    start = starts.pop(0)
                    notes.append(Note(start, tick - start, message.note))
    notes.sort(key=lambda n: (n.start, n.midi))
    return midi, notes


def analyze(midi_path: Path, pattern: tuple[int, ...], note_quarters: float, open_midi: tuple[int, ...]) -> Facts:
    """open_midi lists open-string pitches low string first; pattern numbers strings from 1 (highest)."""
    midi, notes = load_notes(midi_path)
    tpb = midi.ticks_per_beat
    metas = [(tick, m) for tick, m in _absolute(midi) if m.is_meta]
    numerator, denominator = next(
        ((m.numerator, m.denominator) for _, m in metas if m.type == "time_signature"), (4, 4)
    )
    bar_ticks = tpb * numerator * 4 // denominator
    slot_ticks = round(tpb * note_quarters)
    slots_per_bar = bar_ticks // slot_ticks
    bar_of = lambda tick: tick // bar_ticks + 1  # noqa: E731

    onsets: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    for n in notes:
        onsets[bar_of(n.start)][n.start % bar_ticks].add(n.midi)
    bar_count = max(onsets)
    onsets_per_bar = {b: len(onsets[b]) for b in range(1, bar_count + 1)}
    off_grid = [b for b in onsets if any(t % slot_ticks for t in onsets[b])]
    arpeggio = [
        b for b in range(1, bar_count + 1)
        if onsets_per_bar[b] == slots_per_bar and b not in off_grid
    ]
    bar_pitches = {b: [frozenset(onsets[b][t]) for t in sorted(onsets[b])] for b in onsets}

    strings = len(open_midi)
    open_of = {s: open_midi[strings - s] for s in range(1, strings + 1)}
    frets, mismatches = {}, {}
    for b in arpeggio:
        per_string: dict[int, set[int]] = defaultdict(set)
        for s, pitches in zip(pattern, bar_pitches[b]):
            per_string[s] |= pitches
        several = {s: p for s, p in per_string.items() if len(p) > 1}
        below = {s for s, p in per_string.items() if min(p) < open_of[s]}
        if several:
            mismatches[b] = "; ".join(
                f"string {s} plays {' '.join(_names(p))}" for s, p in sorted(several.items())
            )
        elif below:
            mismatches[b] = f"strings {sorted(below)} would sound below their open pitch"
        else:
            frets[b] = tuple(min(per_string[s]) - open_of[s] for s in range(strings, 0, -1))

    repeated = [b for b in range(1, bar_count) if bar_pitches.get(b) == bar_pitches.get(b + 1)]
    lowest = frozenset({open_midi[0]})
    open_low_starts = sum(1 for b in arpeggio if bar_pitches[b][0] == lowest)

    return Facts(
        bar_count=bar_count,
        time_signatures=[(bar_of(t), f"{m.numerator}/{m.denominator}") for t, m in metas if m.type == "time_signature"],
        key_signatures=[(bar_of(t), m.key) for t, m in metas if m.type == "key_signature"],
        tempos=[(bar_of(t), round(mido.tempo2bpm(m.tempo))) for t, m in metas if m.type == "set_tempo"],
        onsets_per_bar=onsets_per_bar,
        off_grid_bars=sorted(off_grid),
        arpeggio_bars=arpeggio,
        frets=frets,
        mismatches=mismatches,
        repeated_bars=repeated,
        open_low_starts=open_low_starts,
        bar_pitches=bar_pitches,
    )


def report(facts: Facts, pattern: tuple[int, ...], open_midi: tuple[int, ...]) -> str:
    lines = [
        f"bars: {facts.bar_count}",
        f"time signatures: {facts.time_signatures}",
        f"key signatures: {facts.key_signatures}",
        f"tempo changes (bar, bpm): {facts.tempos}",
        "",
        "rhythm",
        f"  arpeggio bars (a full bar of pattern notes): {_ranges(facts.arpeggio_bars)}",
        f"  other bars: "
        + ", ".join(
            f"{b} ({facts.onsets_per_bar[b]} onsets{', off-grid' if b in facts.off_grid_bars else ''})"
            for b in range(1, facts.bar_count + 1)
            if b not in facts.arpeggio_bars
        ),
        f"  bar n repeats as bar n+1 for n in: {_ranges(facts.repeated_bars)}",
        "",
        f"pattern check: strings {' '.join(map(str, pattern))}",
        f"  {len(facts.matching_bars)} of {len(facts.arpeggio_bars)} arpeggio bars put exactly one pitch on each string",
    ]
    for b, why in sorted(facts.mismatches.items()):
        lines.append(f"  bar {b}: {why}")
        lines.append(f"      notes: {' '.join('+'.join(_names(p)) for p in facts.bar_pitches[b])}")
    lines += [
        "",
        "left hand, in the bars that fit the pattern",
        f"  highest fret: {facts.max_fret}",
        f"  largest fretted span: {facts.max_span}",
        f"  arpeggio bars starting on the open low string: {facts.open_low_starts} of {len(facts.arpeggio_bars)}",
        "",
        "bars outside the pattern: highest note and the lowest fret that can stop it",
    ]
    for b in range(1, facts.bar_count + 1):
        if b in facts.frets:
            continue
        top = max(max(p) for p in facts.bar_pitches[b])
        fret = min(top - o for o in open_midi if top >= o)
        lines.append(f"  bar {b}: {_names([top])[0]}, fret {fret}")
    lines += ["", "bar  frets 6..1          chord"]
    for b in range(1, facts.bar_count + 1):
        pitches = sorted(set().union(*facts.bar_pitches[b]))
        name = chord.Chord(pitches).pitchedCommonName
        frets = " ".join(f"{f:>2}" for f in facts.frets[b]) if b in facts.frets else "(outside pattern)"
        lines.append(f"{b:>3}  {frets:<18}  {' '.join(_names(pitches))}  [{name}]")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--midi", type=Path, default=DEFAULT_MIDI)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    config = load_config(args.config)
    pattern, open_midi = config.pattern.strings, config.fretboard.open_midi
    facts = analyze(args.midi, pattern, config.pattern.note_quarters, open_midi)
    print(report(facts, pattern, open_midi))


def _absolute(midi: mido.MidiFile):
    for track in midi.tracks:
        tick = 0
        for message in track:
            tick += message.time
            yield tick, message


def _span(frets: tuple[int, ...]) -> int:
    fretted = [f for f in frets if f > 0]
    return max(fretted) - min(fretted) if fretted else 0


def _names(midis) -> list[str]:
    return [pitch.Pitch(midi=m).nameWithOctave for m in sorted(midis)]


def _ranges(bars: list[int]) -> str:
    if not bars:
        return "none"
    runs, start, prev = [], bars[0], bars[0]
    for b in bars[1:] + [None]:
        if b is not None and b == prev + 1:
            prev = b
            continue
        runs.append(f"{start}" if start == prev else f"{start}-{prev}")
        if b is not None:
            start = prev = b
    return ", ".join(runs)


if __name__ == "__main__":
    main()
