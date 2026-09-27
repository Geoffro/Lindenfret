"""Chord symbols: parse the palette and transpose it to every tonal center.

Palette chords are written in E. Before planning, each is parsed with music21
and transposed to all 12 centers in both modes, so everything downstream
works with plain ChordSpec values and never touches music21.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from music21 import harmony, interval, key, pitch

from lindenfret.config import MODES, ConfigError, Palette

PALETTE_TONIC = "E"  # palette chords are written relative to E
PERFECT_FIFTH = 7  # the one chord tone a voicing may leave out

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
    required: frozenset[int]  # every chord tone except a perfect fifth, plus the bass
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

    tonic_names: Mapping[tuple[str, int], str]
    chords: Mapping[tuple[str, int], tuple[ChordSpec, ...]]

    def center_name(self, mode: str, tonic: int) -> str:
        return f"{self.tonic_names[(mode, tonic)]} {mode}"


def parse_chord(figure: str) -> ChordSpec:
    """A ChordSpec for a chord symbol exactly as written, e.g. "F#m7b5/E"."""
    symbol = _parse(figure)
    return _spec(figure, symbol.pitches, symbol.root(), symbol.bass(), symbol.chordKind)


def build_chord_table(palette: Palette) -> ChordTable:
    """Transpose each mode's palette to all 12 centers.

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
            options = [_transpose_palette(parsed, name, mode) for name in _names_for(tonic)]
            best = min(options, key=lambda o: (o.key_accidentals, o.doubles))
            tonic_names[(mode, tonic)] = _display(best.tonic)
            chords[(mode, tonic)] = tuple(
                min((o.chords[i] for o in [best, *options]), key=lambda c: c.doubles).spec
                for i in range(len(parsed))
            )
    return ChordTable(tonic_names, chords)


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
    parsed: Sequence[tuple[str, harmony.ChordSymbol]], tonic: str, mode: str
) -> _Option:
    shift = interval.Interval(noteStart=pitch.Pitch(PALETTE_TONIC), noteEnd=pitch.Pitch(tonic))
    spelled = tuple(_transpose(figure, symbol, shift) for figure, symbol in parsed)
    return _Option(
        tonic,
        spelled,
        sum(s.doubles for s in spelled),
        abs(key.Key(tonic, mode).sharps),
    )


def _transpose(figure: str, symbol: harmony.ChordSymbol, shift: interval.Interval) -> _Spelled:
    _, suffix, bass_text = _FIGURE_RE.match(figure).groups()
    pitches = [p.transpose(shift) for p in symbol.pitches]
    root = symbol.root().transpose(shift)
    bass = symbol.bass().transpose(shift)
    text = _display(root.name) + suffix + (f"/{_display(bass.name)}" if bass_text else "")
    doubles = sum(1 for p in pitches if p.accidental is not None and abs(p.accidental.alter) >= 2)
    return _Spelled(_spec(text, pitches, root, bass, symbol.chordKind), doubles)


def _parse(figure: str) -> harmony.ChordSymbol:
    match = _FIGURE_RE.match(figure)
    if not match:
        raise ChordError(f"not a chord symbol: {figure!r}")
    # music21 spells flats with "-": it rejects "Abm" and reads "Bb7" as B7.
    root, suffix, bass = match.groups()
    music21_figure = root.replace("b", "-") + suffix + (f"/{bass.replace('b', '-')}" if bass else "")
    try:
        symbol = harmony.ChordSymbol(music21_figure)
    except Exception as e:  # music21 raises assorted exception types for bad figures
        raise ChordError(f"can't parse chord symbol {figure!r}: {e}") from e
    if not symbol.pitches or symbol.root() is None:
        raise ChordError(f"can't parse chord symbol {figure!r}")
    return symbol


def _spec(text, pitches, root, bass, kind: str) -> ChordSpec:
    pitch_classes = frozenset(p.pitchClass for p in pitches)
    fifth = (root.pitchClass + PERFECT_FIFTH) % 12
    names = {p.pitchClass: _display(p.name) for p in [*pitches, root, bass]}
    return ChordSpec(
        symbol=text,
        kind=kind,
        root=root.pitchClass,
        bass=bass.pitchClass,
        pitch_classes=pitch_classes,
        required=(pitch_classes - {fifth}) | {bass.pitchClass},
        tensions=frozenset(),
        spelling=tuple(sorted(names.items())),
    )


def _names_for(tonic: int) -> list[str]:
    return [name for name in _TONIC_NAMES if pitch.Pitch(name).pitchClass == tonic]


def _display(name: str) -> str:
    return name.replace("-", "b")
