"""Chord symbols: parse the palette and transpose it to every tonal center.

Palette chords are written in the palette's tonic. Before planning, each is
parsed with music21 and transposed to all 12 centers in both modes, so
everything downstream works with plain ChordSpec values and never touches
music21.
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
    symbol: str  # as written for its center, e.g. "Gm/Bb"
    kind: str  # music21's chord kind, e.g. "minor-seventh"
    root: int  # pitch class, C = 0
    bass: int
    pitch_classes: frozenset[int]
    required: frozenset[int]  # every chord tone except the optional intervals, plus the bass
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
    """A ChordSpec for a chord symbol exactly as written, e.g. "F#m7b5/E".

    `optional` lists the semitones above the root that a voicing may leave out.
    """
    symbol = _parse(figure)
    return _spec(figure, symbol.pitches, symbol.root(), symbol.bass(), symbol.chordKind, optional)


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
        parsed = [(figure, _parse(figure)) for figure in getattr(palette, mode)]
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
    parsed: Sequence[tuple[str, harmony.ChordSymbol]], palette: Palette, tonic: str, mode: str
) -> _Option:
    home = pitch.Pitch(_music21_name(palette.tonic))
    shift = interval.Interval(noteStart=home, noteEnd=pitch.Pitch(tonic))
    spelled = tuple(
        _transpose(figure, symbol, shift, palette.optional_intervals) for figure, symbol in parsed
    )
    return _Option(
        tonic,
        spelled,
        sum(s.doubles for s in spelled),
        abs(key.Key(tonic, mode).sharps),
    )


def _transpose(
    figure: str, symbol: harmony.ChordSymbol, shift: interval.Interval, optional: Collection[int]
) -> _Spelled:
    _, suffix, bass_text = _FIGURE_RE.match(figure).groups()
    pitches = [p.transpose(shift) for p in symbol.pitches]
    root = symbol.root().transpose(shift)
    bass = symbol.bass().transpose(shift)
    text = _display(root.name) + suffix + (f"/{_display(bass.name)}" if bass_text else "")
    doubles = sum(1 for p in pitches if p.accidental is not None and abs(p.accidental.alter) >= 2)
    return _Spelled(_spec(text, pitches, root, bass, symbol.chordKind, optional), doubles)


def _parse(figure: str) -> harmony.ChordSymbol:
    match = _FIGURE_RE.match(figure)
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
    return symbol


def _spec(text, pitches, root, bass, kind: str, optional: Collection[int]) -> ChordSpec:
    pitch_classes = frozenset(p.pitchClass for p in pitches)
    left_out = {(root.pitchClass + i) % 12 for i in optional}
    names = {p.pitchClass: _display(p.name) for p in [*pitches, root, bass]}
    return ChordSpec(
        symbol=text,
        kind=kind,
        root=root.pitchClass,
        bass=bass.pitchClass,
        pitch_classes=pitch_classes,
        required=(pitch_classes - left_out) | {bass.pitchClass},
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
