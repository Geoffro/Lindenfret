"""Fingerings on the fretboard: enumerate, check, score and choose.

For a string pattern, a fingering gives every string a fret: 0 for open, or
None for muted. The strings the pattern plucks sound and the rest are muted,
except that a "bass" note sounds on exactly one of its bass strings. For a
contour pattern, the voicer uses ladders instead (ladder.py).
Either way it lists every fingering for a chord in a fret region, keeps those
that pass the hard rules, ranks them by a soft score and samples among the
best.

check_fingering() re-checks the hard rules from scratch, written separately
from the enumeration, so the voicer never grades its own work.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NamedTuple

from lindenfret.chords import ChordSpec
from lindenfret.config import Fretboard, Pattern, VoicerSettings
from lindenfret.ladder import Ladder, check_ladder, enumerate_ladders

Region = tuple[int, int]  # lowest and highest fret a fretted note may use


@dataclass(frozen=True)
class Fingering:
    frets: tuple[int | None, ...]  # low string (6) first
    pitches: tuple[int | None, ...]  # MIDI, None where muted

    @classmethod
    def from_frets(cls, frets: Sequence[int | None], fretboard: Fretboard) -> Fingering:
        pitches = tuple(
            None if fret is None else open_pitch + fret
            for open_pitch, fret in zip(fretboard.open_midi, frets)
        )
        return cls(tuple(frets), pitches)

    @property
    def sounding(self) -> list[int]:
        return [p for p in self.pitches if p is not None]

    @property
    def span(self) -> int:
        fretted = [f for f in self.frets if f]
        return max(fretted) - min(fretted) if fretted else 0

    @property
    def position(self) -> int:
        """The lowest fretted fret, or 0 when every sounding string is open."""
        return min((f for f in self.frets if f), default=0)

    @property
    def open_strings(self) -> int:
        return sum(1 for f in self.frets if f == 0)

    @property
    def fingers(self) -> int:
        return fingers_needed(self)

    @property
    def shifts(self) -> int:
        return 0  # the hand holds one position for the whole bar

    @property
    def sort_key(self) -> list[int]:
        return [-1 if f is None else f for f in self.frets]

    def changed(self, previous: Fingering) -> int:
        """Strings whose fret differs from the previous bar's."""
        return sum(1 for a, b in zip(self.frets, previous.frets) if a != b)

    def tab(self) -> str:
        return " ".join("x" if f is None else str(f) for f in self.frets)


class NoFingering(ValueError):
    """No fingering passes the hard rules."""


# --- enumeration ----------------------------------------------------------


def enumerate_fingerings(
    spec: ChordSpec, region: Region, fretboard: Fretboard, pattern: Pattern
) -> tuple[Fingering, ...]:
    """Every fingering of `spec` within `region` that passes the hard rules."""
    low_fret, high_fret = region[0], min(region[1], fretboard.max_fret)
    count = fretboard.string_count
    options: list[list[int | None]] = []
    for index, open_pitch in enumerate(fretboard.open_midi):
        string = count - index
        if string not in pattern.plucked and string not in pattern.bass_strings:
            options.append([None])
            continue
        allowed = spec.pitch_classes
        if string in fretboard.tension_strings:
            allowed = allowed | spec.tensions
        choices: list[int | None] = [None] if string in pattern.bass_strings else []
        if open_pitch % 12 in allowed:
            choices.append(0)
        choices += [
            f for f in range(max(low_fret, 1), high_fret + 1) if (open_pitch + f) % 12 in allowed
        ]
        options.append(choices)

    found: list[Fingering] = []

    def walk(index: int, frets: list[int | None], lowest: int, highest: int) -> None:
        if index == count:
            fingering = Fingering.from_frets(frets, fretboard)
            if _complete(fingering, spec, fretboard, pattern):
                found.append(fingering)
            return
        for fret in options[index]:
            low, high = lowest, highest
            if fret:
                low, high = min(low, fret), max(high, fret)
                if high - low > fretboard.max_span:
                    continue
            frets.append(fret)
            walk(index + 1, frets, low, high)
            frets.pop()

    walk(0, [], fretboard.max_fret + 1, -1)
    return tuple(found)


def _complete(fingering: Fingering, spec: ChordSpec, fretboard: Fretboard, pattern: Pattern) -> bool:
    sounding = fingering.sounding
    if not sounding:
        return False
    if pattern.bass_strings:
        count = fretboard.string_count
        bass = [fingering.pitches[count - s] for s in pattern.bass_strings if fingering.frets[count - s] is not None]
        if len(bass) != 1 or bass[0] != min(sounding):
            return False
    if not spec.required <= {p % 12 for p in sounding}:
        return False
    if min(sounding) % 12 != spec.bass:
        return False
    return _fingers_by_barre(fingering.frets) <= fretboard.max_fingers


def _fingers_by_barre(frets: Sequence[int | None]) -> int:
    fretted = [(i, f) for i, f in enumerate(frets) if f]
    if not fretted:
        return 0
    lowest = min(f for _, f in fretted)
    at_lowest = [i for i, f in fretted if f == lowest]
    barre = len(at_lowest) > 1 and all(frets[i] != 0 for i in range(at_lowest[0], at_lowest[-1] + 1))
    return len(fretted) - len(at_lowest) + 1 if barre else len(fretted)


# --- the independent check ------------------------------------------------


def check_fingering(
    fingering: Fingering,
    spec: ChordSpec | None,
    fretboard: Fretboard,
    pattern: Pattern,
    region: Region | None = None,
) -> list[str]:
    """Every hard rule `fingering` breaks, as readable messages; empty if none.

    With spec None only the physical rules are checked, as for planing shapes.
    """
    count = fretboard.string_count
    if len(fingering.frets) != count or len(fingering.pitches) != count:
        return [f"expected {count} strings"]
    problems = []
    for index, (fret, midi) in enumerate(zip(fingering.frets, fingering.pitches)):
        string = count - index
        if fret is None:
            if string in pattern.plucked:
                problems.append(f"string {string} is muted but the pattern plays it")
            continue
        if string not in pattern.plucked and string not in pattern.bass_strings:
            problems.append(f"string {string} sounds but the pattern never plays it")
        if not 0 <= fret <= fretboard.max_fret:
            problems.append(f"string {string} fret {fret} is outside frets 0-{fretboard.max_fret}")
        if fret and region is not None and not region[0] <= fret <= region[1]:
            problems.append(f"string {string} fret {fret} is outside region {region[0]}-{region[1]}")
        if midi != fretboard.open_midi[index] + fret:
            problems.append(f"string {string} pitch {midi} doesn't match fret {fret}")
        if spec is not None and midi % 12 not in spec.pitch_classes:
            if midi % 12 not in spec.tensions:
                problems.append(f"string {string} plays a note outside {spec.symbol}")
            elif string not in fretboard.tension_strings:
                problems.append(f"string {string} plays a tension but isn't a tension string")

    by_fret: dict[int, list[int]] = {}
    for index, fret in enumerate(fingering.frets):
        if fret:
            by_fret.setdefault(fret, []).append(index)
    if by_fret and max(by_fret) - min(by_fret) > fretboard.max_span:
        problems.append(f"span {max(by_fret) - min(by_fret)} exceeds {fretboard.max_span}")
    if fingers_needed(fingering) > fretboard.max_fingers:
        problems.append(f"needs {fingers_needed(fingering)} fingers")

    sounding = [p for p in fingering.pitches if p is not None]
    if pattern.bass_strings:
        bass = [s for s in pattern.bass_strings if fingering.frets[count - s] is not None]
        if len(bass) != 1:
            strings = ", ".join(map(str, pattern.bass_strings))
            problems.append(f"the bass sounds on {len(bass)} of strings {strings}, not one")
        elif fingering.pitches[count - bass[0]] != min(sounding):
            problems.append(f"string {bass[0]} plays the bass note but isn't the lowest")
    if not sounding:
        problems.append("no string sounds")
    elif spec is not None:
        missing = spec.required - {p % 12 for p in sounding}
        if missing:
            problems.append(f"missing {', '.join(sorted(_pc_name(spec, pc) for pc in missing))}")
        if min(sounding) % 12 != spec.bass:
            problems.append(f"lowest note isn't the bass {_pc_name(spec, spec.bass)}")
    return problems


def fingers_needed(fingering: Fingering) -> int:
    """Fretting fingers, with the lowest fret barred when no open string lies under the barre."""
    groups: dict[int, list[int]] = {}
    for index, fret in enumerate(fingering.frets):
        if fret:
            groups.setdefault(fret, []).append(index)
    if not groups:
        return 0
    lowest = min(groups)
    first, last = groups[lowest][0], groups[lowest][-1]
    under_barre = fingering.frets[first : last + 1]
    lowest_fingers = 1 if 0 not in under_barre else len(groups[lowest])
    return lowest_fingers + sum(len(strings) for fret, strings in groups.items() if fret != lowest)


def _pc_name(spec: ChordSpec, pc: int) -> str:
    return dict(spec.spelling).get(pc, str(pc))


# --- soft score and choice ------------------------------------------------


Voicing = Fingering | Ladder  # a fingering for a string pattern, a ladder for a contour


class Score(NamedTuple):  # a tuple, since every candidate of every bar gets one
    movement: float  # hand shift plus changed strings or stops since the previous bar
    span_excess: int  # frets beyond the comfortable span
    open_strings: int
    doubling: int  # extra copies of tones other than the root and fifth
    shifts: int  # hand shifts within the bar
    total: float  # lower is better


def score(
    fingering: Voicing, spec: ChordSpec, previous: Voicing | None, settings: VoicerSettings
) -> Score:
    movement = 0.0
    if previous is not None:
        movement = abs(fingering.position - previous.position) + 0.25 * fingering.changed(previous)
    span_excess = max(0, fingering.span - settings.comfortable_span)
    plain = (spec.root, (spec.root + 7) % 12)
    others = [pc for pc in (p % 12 for p in fingering.sounding) if pc not in plain]
    doubling = len(others) - len(set(others))
    open_strings, shifts = fingering.open_strings, fingering.shifts
    w = settings.weights
    total = (
        w["movement"] * movement
        + w["span"] * span_excess
        - w["open_strings"] * open_strings
        + w["doubling"] * doubling
    )
    if shifts:
        total += w["shift"] * shifts
    return Score(movement, span_excess, open_strings, doubling, shifts, total)


class Voicer:
    def __init__(self, fretboard: Fretboard, pattern: Pattern, settings: VoicerSettings) -> None:
        self.fretboard = fretboard
        self.pattern = pattern
        self.settings = settings
        self._cache: dict[tuple[ChordSpec, Region], tuple[Voicing, ...]] = {}
        self._playable: dict[tuple[ChordSpec, Region], bool] = {}

    def fingerings(self, spec: ChordSpec, region: Region) -> tuple[Voicing, ...]:
        cache_key = (spec, region)
        if cache_key not in self._cache:
            if self.pattern.contour:
                found = enumerate_ladders(spec, region, self.fretboard, self.pattern)
            else:
                found = enumerate_fingerings(spec, region, self.fretboard, self.pattern)
            self._cache[cache_key] = found
        return self._cache[cache_key]

    def playable(self, spec: ChordSpec, region: Region) -> bool:
        """Whether any fingering passes the hard rules; cheaper than listing them all."""
        cache_key = (spec, region)
        if not self.pattern.contour or cache_key in self._cache:
            return bool(self.fingerings(spec, region))
        if cache_key not in self._playable:
            self._playable[cache_key] = bool(
                enumerate_ladders(spec, region, self.fretboard, self.pattern, limit=1)
            )
        return self._playable[cache_key]

    def check(self, fingering: Voicing, spec: ChordSpec, region: Region) -> list[str]:
        """The independent check of the hard rules for this pattern."""
        if self.pattern.contour:
            return check_ladder(fingering, spec, self.fretboard, self.pattern, region)
        return check_fingering(fingering, spec, self.fretboard, self.pattern, region)

    def ranked(
        self, spec: ChordSpec, region: Region, previous: Voicing | None = None
    ) -> list[tuple[Score, Voicing]]:
        scored = [(score(f, spec, previous, self.settings), f) for f in self.fingerings(spec, region)]
        scored.sort(key=lambda sf: (sf[0].total, sf[1].sort_key))
        return scored

    def choose(
        self,
        spec: ChordSpec,
        region: Region,
        previous: Voicing | None,
        rng: random.Random,
        avoid: Voicing | None = None,
    ) -> Voicing:
        """Sample one of the best fingerings; `avoid` is skipped if anything else fits."""
        ranked = self.ranked(spec, region, previous)
        if avoid is not None and len(ranked) > 1:
            ranked = [sf for sf in ranked if sf[1] != avoid]
        if not ranked:
            raise NoFingering(f"no playable fingering of {spec.symbol} in frets {region[0]}-{region[1]}")
        top = ranked[: self.settings.top_candidates]
        if self.settings.temperature == 0:
            chosen = top[0][1]
        else:
            best = top[0][0].total
            weights = [math.exp((best - s.total) / self.settings.temperature) for s, _ in top]
            chosen = rng.choices(top, weights=weights)[0][1]
        problems = self.check(chosen, spec, region)
        assert not problems, f"voicer chose a bad fingering of {spec.symbol}: {problems}"
        return chosen


def fret_windows(fretboard: Fretboard, pattern: Pattern) -> list[Region]:
    """Fret windows as wide as the hand can reach in one bar, from the open position to the highest fret."""
    hands = pattern.hand_positions
    reach = fretboard.max_span * hands + pattern.max_slide * (hands - 1)
    width = min(reach, fretboard.max_fret)
    return [(low, low + width) for low in range(0, fretboard.max_fret - width + 1)]
