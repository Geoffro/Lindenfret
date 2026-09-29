"""Build the notation: one guitar part of single-line notes, no key signature.

Pitches are spelled from their chords and written at sounding pitch under a
treble clef an octave down, as guitar music is. The config's direction, such
as how long notes ring, is written at the start.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from itertools import accumulate, product

from music21 import clef, duration, expressions, instrument, metadata, meter, note, pitch, stream, tempo

from lindenfret.config import Config
from lindenfret.render import Rendering


def build_score(rendering: Rendering, config: Config, title: str) -> stream.Score:
    score = stream.Score()
    score.insert(0, metadata.Metadata(title=title, composer=""))
    part = stream.Part()
    part.partName = "Guitar"
    part.insert(0, instrument.Guitar())
    beat = config.meter.beat_quarters

    for m in rendering.measures:
        measure = stream.Measure(number=m.number)
        if m.number == 1:
            measure.insert(0, clef.Treble8vbClef())
            measure.insert(0, meter.TimeSignature(f"{config.meter.beats}/{config.meter.beat_unit}"))
            metronome = tempo.MetronomeMark(number=round(config.meter.tempo / beat), referent=duration.Duration(beat))
            measure.insert(0, metronome)
            if config.notation.direction:
                measure.insert(0, expressions.TextExpression(config.notation.direction))
        for mark in m.marks:
            measure.insert(0, expressions.TextExpression(mark))
        respelled = _respell_as_chord(m.notes) if m.bar.chord is None else {}
        written = []
        for n in m.notes:
            w = note.Note(respelled.get(n.midi) or _music21_name(n.name))
            w.quarterLength = rendering.note_quarters
            measure.insert(n.onset - m.start, w)
            written.append((n.onset - m.start, w))
        _beam_in_groups(written, config.meter.beam_groups)
        part.append(measure)

    score.append(part)
    return score


def _beam_in_groups(notes: list[tuple[float, note.Note]], groups: Sequence[float]) -> None:
    """Beam the notes of each group, `groups` quarter notes long, together with unbroken beams.

    music21's default for 4/4 splits a beat of 16ths into pairs, which reads
    as eighth-note subgroups.
    """
    ends = list(accumulate(groups))
    beamed: dict[int, list[note.Note]] = {}
    for offset, n in sorted(notes, key=lambda x: x[0]):
        beamed.setdefault(bisect_right(ends, offset), []).append(n)
    for group in beamed.values():
        if len(group) < 2:
            continue
        for i, n in enumerate(group):
            kind = "start" if i == 0 else "stop" if i == len(group) - 1 else "continue"
            n.beams.fill(n.duration.type, type=kind)


def _respell_as_chord(notes) -> dict[int, str]:
    """Spell a planing bar, which has no chord symbol.

    Open strings keep their plain names. The shape's fretted notes try every
    combination of enharmonic spellings. The bar takes the one with the fewest
    letters shared by two different notes (no B-sharp beside an open B), then
    letters stacked in thirds (F#-A-C-Eb for a diminished seventh), then the
    fewest accidentals, then no mix of sharps and flats.
    """
    open_midis = {n.midi for n in notes if n.fret == 0}
    names = {m: pitch.Pitch(midi=m) for m in open_midis}
    fretted = sorted({n.midi for n in notes if n.fret > 0} - open_midis)
    options = [
        [pitch.Pitch(midi=m), *pitch.Pitch(midi=m).getAllCommonEnharmonics(alterLimit=1)] for m in fretted
    ]
    best = min(product(*options), key=lambda spelling: _spelling_cost(spelling, list(names.values())))
    names.update({p.midi: p for p in best})
    return {m: p.nameWithOctave for m, p in names.items()}


_LETTERS = "CDEFGAB"


def _spelling_cost(
    fretted: Sequence[pitch.Pitch], open_strings: Sequence[pitch.Pitch]
) -> tuple[int, int, int, int]:
    pcs_by_letter: dict[str, set[int]] = {}
    for p in [*fretted, *open_strings]:
        pcs_by_letter.setdefault(p.step, set()).add(p.pitchClass)
    clashes = sum(len(pcs) - 1 for pcs in pcs_by_letter.values())
    letters = {_LETTERS.index(p.step) for p in fretted}
    stacked = any(all((letter - s) % 7 in (0, 2, 4, 6) for letter in letters) for s in range(7))
    alters = [p.accidental.alter for p in fretted if p.accidental is not None and p.accidental.alter]
    mixed = int(any(a > 0 for a in alters) and any(a < 0 for a in alters))
    return clashes, int(not stacked), len(alters), mixed


def _music21_name(name: str) -> str:
    # "Bb3" -> "B-3": music21 spells flats with "-".
    return name[0] + name[1:].replace("b", "-")
