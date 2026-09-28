"""Chord symbols: parse the palette and transpose it to every tonal center.

Palette chords are written in the palette's tonic. Before planning, each is
parsed with music21 and transposed to all 12 centers in both modes, so
everything downstream works with plain ChordSpec values and never touches
music21.

A polychord stacks one chord symbol over another, upper first: "D|C" is D
major over C major. The lower chord gives the root and bass, and only it may
leave out its optional intervals: the upper chord's tones are tensions over
the lower root, so a voicing keeps them all.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from music21 import harmony, interval, key, pitch

from lindenfret.config import MODES, ConfigError, Palette

PERFECT_FIFTH = 7

_FIGURE_RE = re.compile(r"^([A-G][#b-]?)(.*?)(?:/([A-G][#b-]?))?$")
_TONIC_NAMES = [step + alter for step in "CDEFGAB" for alter in ("", "#", "-")]


class ChordError(ConfigError):
    """A chord symbol can't be parsed."""


@dataclass(frozen=True)
class ChordSpec:
    symbol: str  # as written for its center, e.g. "Gm/Bb" or "D|C"
    kind: str  # music21's chord kind, e.g. "minor-seventh"; "major|major" for a polychord
    root: int  # pitch class, C = 0
    bass: int
    pitch_classes: frozenset[int]
    required: frozenset[int]  # chord tones minus the optional intervals above the root, plus the bass and any upper chord
    tensions: frozenset[int]  # allowed non-chord tones; none until tensions are enabled
    spelling: tuple[tuple[int, str], ...]  # (pitch class, note name) for each chord tone

    def spell(self, midi: int) -> str:
        """Note name with octave for a MIDI pitch in this chord, e.g. 'Bb3'."""
        name = dict(self.spelling).get(midi % 12)
        if name is None:
            raise ValueError(f"MIDI {midi} is not a tone of {self.symbol}")
        alter = name.count("#") - name.count("b")
        return f"{name}{(midi - alter) // 12 - 1}"


@dataclass(frozen=True)
class ChordTable:
    """The palette transposed to every center, keyed by (mode, tonic pitch class)."""

    written_in: str  # the tonic the palette is written in
    tonic_names: Mapping[tuple[str, int], str]
    chords: Mapping[tuple[str, int], tuple[ChordSpec, ...]]

    def center_name(self, mode: str, tonic: int) -> str:
        return f"{self.tonic_names[(mode, tonic)]} {mode}"


def parse_chord(figure: str, optional: Collection[int] = (PERFECT_FIFTH,)) -> ChordSpec:
    """A ChordSpec for a chord symbol exactly as written, e.g. "F#m7b5/E" or "D|C".

    `optional` lists the semitones above the root that a voicing may leave out.
    """
    return _spec(figure, _parse(figure), optional)


def build_chord_table(palette: Palette) -> ChordTable:
    """Transpose each mode's palette from its tonic to all 12 centers.

    Each center is named with whichever enharmonic tonic has the fewest
    accidentals in its key signature (D-flat major, not C-sharp major); between
    equal key signatures, the one that gives the palette fewer double sharps and
    flats. A chord that still needs a double accidental is respelled on its own
    if another tonic spelling avoids it.
    """
    tonic_names: dict[tuple[str, int], str] = {}
    chords: dict[tuple[str, int], tuple[ChordSpec, ...]] = {}
    for mode in MODES:
        parsed = [_parse(figure) for figure in getattr(palette, mode)]
        for tonic in range(12):
            options = [
                _transpose_palette(parsed, palette, name, mode) for name in _names_for(tonic)
            ]
            best = min(options, key=lambda o: (o.key_accidentals, o.doubles))
            tonic_names[(mode, tonic)] = _display(best.tonic)
            chords[(mode, tonic)] = tuple(
                min((o.chords[i] for o in [best, *options]), key=lambda c: c.doubles).spec
                for i in range(len(parsed))
            )
    return ChordTable(palette.tonic, tonic_names, chords)


@dataclass(frozen=True)
class _Part:
    """One chord symbol of a figure: the whole figure, or one part of a polychord."""

    figure: str  # as written, e.g. "Gm/Bb"
    pitches: tuple[pitch.Pitch, ...]
    root: pitch.Pitch
    bass: pitch.Pitch
    kind: str


@dataclass(frozen=True)
class _Spelled:
    spec: ChordSpec
    doubles: int  # notes spelled with a double sharp or double flat


@dataclass(frozen=True)
class _Option:
    tonic: str
    chords: tuple[_Spelled, ...]
    doubles: int
    key_accidentals: int


def _transpose_palette(
    parsed: Sequence[tuple[_Part, ...]], palette: Palette, tonic: str, mode: str
) -> _Option:
    home = pitch.Pitch(_music21_name(palette.tonic))
    shift = interval.Interval(noteStart=home, noteEnd=pitch.Pitch(tonic))
    spelled = tuple(_transpose(parts, shift, palette.optional_intervals) for parts in parsed)
    return _Option(
        tonic,
        spelled,
        sum(s.doubles for s in spelled),
        abs(key.Key(tonic, mode).sharps),
    )


def _transpose(parts: Sequence[_Part], shift: interval.Interval, optional: Collection[int]) -> _Spelled:
    moved = []
    for part in parts:
        _, suffix, bass_text = _FIGURE_RE.match(part.figure).groups()
        root, bass = part.root.transpose(shift), part.bass.transpose(shift)
        text = _display(root.name) + suffix + (f"/{_display(bass.name)}" if bass_text else "")
        moved.append(_Part(text, tuple(p.transpose(shift) for p in part.pitches), root, bass, part.kind))
    pitches = [p for part in moved for p in part.pitches]
    doubles = sum(1 for p in pitches if p.accidental is not None and abs(p.accidental.alter) >= 2)
    return _Spelled(_spec("|".join(part.figure for part in moved), moved, optional), doubles)


def _parse(figure: str) -> tuple[_Part, ...]:
    """The parts of `figure`, upper first: one chord symbol, or two for a polychord."""
    parts = figure.split("|")
    if len(parts) > 2:
        raise ChordError(f"a polychord stacks two chord symbols: {figure!r}")
    return tuple(_parse_part(part, figure) for part in parts)


def _parse_part(text: str, figure: str) -> _Part:
    match = _FIGURE_RE.match(text)
    if not match:
        raise ChordError(f"not a chord symbol: {figure!r}")
    # music21 spells flats with "-": it rejects "Abm" and reads "Bb7" as B7.
    root, suffix, bass = match.groups()
    music21_figure = _music21_name(root) + suffix + (f"/{_music21_name(bass)}" if bass else "")
    try:
        symbol = harmony.ChordSymbol(music21_figure)
    except Exception as e:  # music21 raises assorted exception types for bad figures
        raise ChordError(f"can't parse chord symbol {figure!r}: {e}") from e
    if not symbol.pitches or symbol.root() is None:
        raise ChordError(f"can't parse chord symbol {figure!r}")
    return _Part(text, tuple(symbol.pitches), symbol.root(), symbol.bass(), symbol.chordKind)


def _spec(text: str, parts: Sequence[_Part], optional: Collection[int]) -> ChordSpec:
    *upper, lower = parts
    pitch_classes = frozenset(p.pitchClass for part in parts for p in part.pitches)
    left_out = {(lower.root.pitchClass + i) % 12 for i in optional}
    left_out -= {p.pitchClass for part in upper for p in part.pitches}
    required = (pitch_classes - left_out) | {lower.bass.pitchClass}
    # The lower part comes last, so its spelling wins where the parts share a pitch class.
    names = {p.pitchClass: _display(p.name) for part in parts for p in [*part.pitches, part.root, part.bass]}
    return ChordSpec(
        symbol=text,
        kind="|".join(part.kind for part in parts),
        root=lower.root.pitchClass,
        bass=lower.bass.pitchClass,
        pitch_classes=pitch_classes,
        required=required,
        tensions=frozenset(),
        spelling=tuple(sorted(names.items())),
    )


def _names_for(tonic: int) -> list[str]:
    return [name for name in _TONIC_NAMES if pitch.Pitch(name).pitchClass == tonic]


def _display(name: str) -> str:
    return name.replace("-", "b")


def _music21_name(name: str) -> str:
    # "Bb" -> "B-": the letter is always a capital, so only the accidental changes.
    return name[0] + name[1:].replace("b", "-")
