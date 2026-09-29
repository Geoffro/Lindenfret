"""Turn planned bars into timed notes, measures and a tempo map.

Every generated bar is played `repeat_bars` times. In each measure the
right-hand pattern plucks one string per note; a note sounds until its
string is plucked again or the measure ends, as a held guitar note would. A
fretted note in a contour pattern also stops when the hand moves to another
position.
"""

from __future__ import annotations

from dataclasses import dataclass

from lindenfret.chords import ChordSpec
from lindenfret.config import BASS, Config, Meter, Pattern
from lindenfret.fretboard import Fingering, Voicing
from lindenfret.harmony import Bar
from lindenfret.ladder import Ladder
from lindenfret.pipeline import Piece


@dataclass(frozen=True)
class NoteEvent:
    onset: float  # quarter notes from the start of the piece
    duration: float
    string: int  # 1 (highest) to 6
    fret: int
    midi: int
    velocity: int
    name: str  # spelled from the chord, e.g. "Bb3"


@dataclass(frozen=True)
class Measure:
    number: int  # 1-based
    start: float  # quarter notes from the start of the piece
    bar: Bar  # the generated bar this measure plays
    notes: tuple[NoteEvent, ...]
    marks: tuple[str, ...]  # performance directions that begin here, e.g. "rit."


@dataclass(frozen=True)
class Rendering:
    measures: tuple[Measure, ...]
    tempos: tuple[tuple[float, float], ...]  # (onset in quarter notes, quarter notes per minute)
    bar_quarters: float
    note_quarters: float

    @property
    def notes(self) -> list[NoteEvent]:
        return [n for m in self.measures for n in m.notes]


def render_bar(
    fingering: Voicing, spec: ChordSpec | None, pattern: Pattern, start: float, bar_quarters: float
) -> list[NoteEvent]:
    """One measure of the pattern over `fingering`, starting at `start`."""
    if pattern.contour:
        return _render_contour(fingering, spec, pattern, start, bar_quarters)
    return _render_strings(fingering, spec, pattern, start, bar_quarters)


def _render_strings(
    fingering: Fingering, spec: ChordSpec | None, pattern: Pattern, start: float, bar_quarters: float
) -> list[NoteEvent]:
    count = len(fingering.frets)
    step = pattern.note_quarters
    bass = [s for s in pattern.bass_strings if fingering.frets[count - s] is not None]
    strings = [bass[0] if s == BASS else s for s in pattern.strings]
    notes = []
    for k, (string, velocity) in enumerate(zip(strings, pattern.velocities)):
        fret, midi = fingering.frets[count - string], fingering.pitches[count - string]
        if fret is None or midi is None:
            continue
        later = [j for j in range(k + 1, len(strings)) if strings[j] == string]
        end = later[0] * step if later else bar_quarters
        name = spec.spell(midi) if spec else _plain_name(midi)
        notes.append(NoteEvent(start + k * step, end - k * step, string, fret, midi, velocity, name))
    return notes


def _render_contour(
    ladder: Ladder, spec: ChordSpec | None, pattern: Pattern, start: float, bar_quarters: float
) -> list[NoteEvent]:
    step = pattern.note_quarters
    notes = []
    for k, (index, velocity) in enumerate(zip(pattern.contour, pattern.velocities)):
        string, fret = ladder.stops[index]
        end = bar_quarters
        for j in range(k + 1, len(pattern.contour)):
            later = pattern.contour[j]
            later_string, later_fret = ladder.stops[later]
            moved = fret > 0 and later_fret > 0 and ladder.hands[later] != ladder.hands[index]
            if later_string == string or moved:
                end = j * step
                break
        midi = ladder.pitches[index]
        name = spec.spell(midi) if spec else _plain_name(midi)
        notes.append(NoteEvent(start + k * step, end - k * step, string, fret, midi, velocity, name))
    return notes


def render_piece(piece: Piece, config: Config) -> Rendering:
    bar_quarters = config.meter.bar_quarters
    repeats = config.meter.repeat_bars
    tempo, slowdown = config.meter.tempo, config.meter.ritardando
    last_of_section = {
        i for i, bar in enumerate(piece.bars)
        if i + 1 == len(piece.bars) or piece.bars[i + 1].section != bar.section
    }

    measures: list[Measure] = []
    tempos: list[tuple[float, float]] = [(0.0, tempo)]
    slowing = False
    for i, bar in enumerate(piece.bars):
        for repeat in range(repeats):
            start = len(measures) * bar_quarters
            marks = []
            if slowing and repeat == 0:
                tempos.append((start, tempo))
                marks.append("a tempo")
                slowing = False
            if i in last_of_section and repeat == 0 and slowdown > 0:
                tempos += ritardando(start, config.meter)
                marks.append("rit.")
                slowing = True
            notes = render_bar(bar.fingering, bar.chord, config.pattern, start, bar_quarters)
            measures.append(Measure(len(measures) + 1, start, bar, tuple(notes), tuple(marks)))
    return Rendering(tuple(measures), tuple(tempos), bar_quarters, config.pattern.note_quarters)


def ritardando(start: float, meter: Meter) -> list[tuple[float, float]]:
    """The tempo map of a section's last bar and its repeats, from `start`, slowing a step at a time."""
    step = min(1.0, 4 / meter.beat_unit)  # a quarter, or an eighth in 6/8
    steps = round(meter.bar_quarters * meter.repeat_bars / step)
    return [
        (start + k * step, round(meter.tempo * (1 - meter.ritardando * (k + 1) / steps), 3)) for k in range(steps)
    ]


_PLAIN_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "G#", "A", "Bb", "B"]


def _plain_name(midi: int) -> str:
    return f"{_PLAIN_NAMES[midi % 12]}{midi // 12 - 1}"
