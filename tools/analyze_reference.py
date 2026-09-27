"""Analyze a reference MIDI and print the facts docs/design.md relies on.

The pattern and tuning come from the preset, so this also confirms that the
preset's pattern matches the reference. For a contour pattern it also checks
that every reference bar's ladder has a fingering under the preset's rules.

    .venv/bin/python tools/analyze_reference.py [--midi PATH] [--config PATH]

The defaults are Etude 1's MIDI and preset; for Etude 2, pass
--midi reference/Villa-Lobos_Etude_No2.mid --config configs/etude2.toml.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median

import mido
from music21 import chord, pitch

from lindenfret.chords import ChordSpec
from lindenfret.config import Fretboard, Pattern, load_config
from lindenfret.ladder import Ladder, enumerate_ladders

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MIDI = ROOT / "reference" / "Villa-Lobos_Etude_No1b.mid"
DEFAULT_CONFIG = ROOT / "configs" / "etude1.toml"


@dataclass(frozen=True)
class Note:
    start: int  # ticks from the start of the piece
    duration: int
    midi: int
    velocity: int


@dataclass
class Facts:
    bar_count: int
    time_signatures: list[tuple[int, str]]  # (bar, "4/4")
    key_signatures: list[tuple[int, str]]
    tempos: list[tuple[int, int]]  # (bar, quarter notes per minute)
    onsets_per_bar: dict[int, int]
    off_grid_bars: list[int]  # bars with onsets off the pattern's note grid
    arpeggio_bars: list[int]  # a full bar of pattern notes on the grid
    matching_bars: list[int]  # arpeggio bars that follow the pattern
    mismatches: dict[int, str]  # arpeggio bar -> why it doesn't follow the pattern
    frets: dict[int, tuple[int, ...]]  # string pattern: matching bar -> fret per string, 6 to 1
    ladders: dict[int, tuple[int, ...]]  # contour: matching bar -> its ladder's pitches, rising
    velocities: list[int]  # median MIDI velocity of each pattern note over the matching bars
    repeated_bars: list[int]  # bar n sounds exactly like bar n + 1
    open_low_starts: int  # arpeggio bars whose first note is the open lowest string
    bar_pitches: dict[int, list[frozenset[int]]] = field(repr=False)

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
        sounding: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        for message in track:
            tick += message.time
            if message.type == "note_on" and message.velocity > 0:
                sounding[(message.channel, message.note)].append((tick, message.velocity))
            elif message.type in ("note_off", "note_on"):
                starts = sounding[(message.channel, message.note)]
                if starts:
                    start, velocity = starts.pop(0)
                    notes.append(Note(start, tick - start, message.note, velocity))
    notes.sort(key=lambda n: (n.start, n.midi))
    return midi, notes


def analyze(midi_path: Path, pattern: Pattern, open_midi: tuple[int, ...]) -> Facts:
    """open_midi lists open-string pitches low string first; pattern strings count from 1 (highest)."""
    midi, notes = load_notes(midi_path)
    tpb = midi.ticks_per_beat
    metas = [(tick, m) for tick, m in _absolute(midi) if m.is_meta]
    numerator, denominator = next(
        ((m.numerator, m.denominator) for _, m in metas if m.type == "time_signature"), (4, 4)
    )
    bar_ticks = tpb * numerator * 4 // denominator
    slot_ticks = round(tpb * pattern.note_quarters)
    slots_per_bar = bar_ticks // slot_ticks
    bar_of = lambda tick: tick // bar_ticks + 1  # noqa: E731

    onsets: dict[int, dict[int, set[int]]] = defaultdict(lambda: defaultdict(set))
    velocities: dict[int, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for n in notes:
        onsets[bar_of(n.start)][n.start % bar_ticks].add(n.midi)
        velocities[bar_of(n.start)][n.start % bar_ticks].append(n.velocity)
    bar_count = max(onsets)
    onsets_per_bar = {b: len(onsets[b]) for b in range(1, bar_count + 1)}
    off_grid = [b for b in onsets if any(t % slot_ticks for t in onsets[b])]
    arpeggio = [
        b for b in range(1, bar_count + 1)
        if onsets_per_bar[b] == slots_per_bar and b not in off_grid
    ]
    bar_pitches = {b: [frozenset(onsets[b][t]) for t in sorted(onsets[b])] for b in onsets}

    frets, ladders = {}, {}
    if pattern.contour:
        ladders, mismatches = _fit_contour(arpeggio, bar_pitches, pattern)
    else:
        frets, mismatches = _fit_strings(arpeggio, bar_pitches, pattern, open_midi)
    matching = sorted(ladders or frets)

    repeated = [b for b in range(1, bar_count) if bar_pitches.get(b) == bar_pitches.get(b + 1)]
    lowest = frozenset({open_midi[0]})
    open_low_starts = sum(1 for b in arpeggio if bar_pitches[b][0] == lowest)
    slot_velocities = [
        round(median(v for b in matching for v in velocities[b][sorted(velocities[b])[k]]))
        for k in range(slots_per_bar)
    ]

    return Facts(
        bar_count=bar_count,
        time_signatures=[(bar_of(t), f"{m.numerator}/{m.denominator}") for t, m in metas if m.type == "time_signature"],
        key_signatures=[(bar_of(t), m.key) for t, m in metas if m.type == "key_signature"],
        tempos=[(bar_of(t), round(mido.tempo2bpm(m.tempo))) for t, m in metas if m.type == "set_tempo"],
        onsets_per_bar=onsets_per_bar,
        off_grid_bars=sorted(off_grid),
        arpeggio_bars=arpeggio,
        matching_bars=matching,
        mismatches=mismatches,
        frets=frets,
        ladders=ladders,
        velocities=slot_velocities,
        repeated_bars=repeated,
        open_low_starts=open_low_starts,
        bar_pitches=bar_pitches,
    )


def _fit_strings(arpeggio, bar_pitches, pattern: Pattern, open_midi):
    """Frets for each bar that puts exactly one pitch on each string of the pattern."""
    strings = len(open_midi)
    open_of = {s: open_midi[strings - s] for s in range(1, strings + 1)}
    frets, mismatches = {}, {}
    for b in arpeggio:
        per_string: dict[int, set[int]] = defaultdict(set)
        for s, pitches in zip(pattern.strings, bar_pitches[b]):
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
    return frets, mismatches


def _fit_contour(arpeggio, bar_pitches, pattern: Pattern):
    """The ladder of each bar whose notes step through its pitches in the contour's order."""
    ladders, mismatches = {}, {}
    for b in arpeggio:
        if any(len(p) > 1 for p in bar_pitches[b]):
            mismatches[b] = "plays two pitches at once"
            continue
        played = [min(p) for p in bar_pitches[b]]
        ladder = sorted(set(played))
        contour = tuple(ladder.index(p) for p in played)
        if contour == pattern.contour:
            ladders[b] = tuple(ladder)
        else:
            mismatches[b] = f"contour {' '.join(map(str, contour))}"
    return ladders, mismatches


def ladder_fingerings(pitches: tuple[int, ...], fretboard: Fretboard, pattern: Pattern) -> list[Ladder]:
    """Every ladder that plays exactly these pitches under the preset's rules, anywhere on the neck."""
    pcs = frozenset(p % 12 for p in pitches)
    spec = ChordSpec("ladder", "", pitches[0] % 12, pitches[0] % 12, pcs, pcs, frozenset(), ())
    found = enumerate_ladders(spec, (0, fretboard.max_fret), fretboard, pattern)
    return [ladder for ladder in found if ladder.pitches == pitches]


def report(facts: Facts, pattern: Pattern, fretboard: Fretboard) -> str:
    open_midi = fretboard.open_midi
    notes = pattern.strings or pattern.contour
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
        f"pattern check: {'strings' if pattern.strings else 'contour'} {' '.join(map(str, notes))}",
        f"  {len(facts.matching_bars)} of {len(facts.arpeggio_bars)} arpeggio bars follow it",
    ]
    for b, why in sorted(facts.mismatches.items()):
        lines.append(f"  bar {b}: {why}")
        lines.append(f"      notes: {' '.join('+'.join(_names(p)) for p in facts.bar_pitches[b])}")
    lines.append(f"  median velocity per note: {' '.join(map(str, facts.velocities))}")
    lines += ["", "left hand, in the bars that follow the pattern"]
    if pattern.strings:
        lines += [
            f"  highest fret: {facts.max_fret}",
            f"  largest fretted span: {facts.max_span}",
            f"  arpeggio bars starting on the open low string: {facts.open_low_starts} of {len(facts.arpeggio_bars)}",
        ]
    else:
        top = max(max(ladder) for ladder in facts.ladders.values())
        lines.append(f"  highest note: {_names([top])[0]}, fret {top - open_midi[-1]} on string 1")
        shifts: dict[str, list[int]] = defaultdict(list)
        for b, ladder in sorted(facts.ladders.items()):
            found = ladder_fingerings(ladder, fretboard, pattern)
            key = "no fingering" if not found else "one position" if min(f.shifts for f in found) == 0 else "a slide"
            shifts[key].append(b)
        for key in ("one position", "a slide", "no fingering"):
            lines.append(f"  bars playable with {key} under the preset's rules: {_ranges(shifts[key])}")
    lines += ["", "bars outside the pattern: highest note and the lowest fret that can stop it"]
    for b in range(1, facts.bar_count + 1):
        if b in facts.matching_bars:
            continue
        top = max(max(p) for p in facts.bar_pitches[b])
        fret = min(top - o for o in open_midi if top >= o)
        lines.append(f"  bar {b}: {_names([top])[0]}, fret {fret}")
    lines += ["", f"bar  {'frets 6..1' if pattern.strings else 'ladder':<18}  chord"]
    for b in range(1, facts.bar_count + 1):
        pitches = sorted(set().union(*facts.bar_pitches[b]))
        name = chord.Chord(pitches).pitchedCommonName
        if b in facts.frets:
            shape = " ".join(f"{f:>2}" for f in facts.frets[b])
        elif b in facts.ladders:
            shape = "follows the contour"
        else:
            shape = "(outside pattern)"
        lines.append(f"{b:>3}  {shape:<18}  {' '.join(_names(pitches))}  [{name}]")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--midi", type=Path, default=DEFAULT_MIDI)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    config = load_config(args.config)
    facts = analyze(args.midi, config.pattern, config.fretboard.open_midi)
    print(report(facts, config.pattern, config.fretboard))


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
