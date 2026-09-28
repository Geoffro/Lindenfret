"""Ladders: the left hand's stops for a contour pattern.

A stop is a string and a fret. A ladder lists one bar's stops from the lowest
string to the highest, and along each string from the lowest fret up, with
the pitch rising at every stop. The right hand's contour names the stop each
note plays. A string may carry several stops, and the hand may move to a new
position as the ladder climbs: the stops fall into consecutive hand
positions, each within the span and finger limits, and the hand moves only
by sliding up the string it just played, at most `max_slide` frets.

check_ladder() re-checks the hard rules from scratch, written separately from
the enumeration, so the voicer never grades its own work.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

from lindenfret.chords import ChordSpec
from lindenfret.config import Fretboard, Pattern


@dataclass(frozen=True)
class Ladder:
    frets: tuple[tuple[int, ...], ...]  # per string, low string (6) first: its stops' frets, lowest first
    pitches: tuple[int, ...]  # MIDI pitch of each stop, rising
    hands: tuple[int, ...]  # the hand position of each stop, counted from 0

    @cached_property
    def stops(self) -> tuple[tuple[int, int], ...]:
        """(string, fret) for each stop, in ladder order."""
        count = len(self.frets)
        return tuple((count - index, fret) for index, frets in enumerate(self.frets) for fret in frets)

    @property
    def sounding(self) -> tuple[int, ...]:
        return self.pitches

    @cached_property
    def span(self) -> int:
        """The widest stretch of any one hand position."""
        spans = [max(frets) - min(frets) for frets in self._fretted_by_hand() if frets]
        return max(spans, default=0)

    @cached_property
    def position(self) -> int:
        """The lowest fretted fret, or 0 when every stop is open."""
        return min((fret for _, fret in self.stops if fret), default=0)

    @cached_property
    def open_strings(self) -> int:
        """Open stops."""
        return sum(1 for _, fret in self.stops if fret == 0)

    @cached_property
    def shifts(self) -> int:
        return max(self.hands)

    @property
    def fingers(self) -> int:
        """The most fretting fingers any one hand position needs, one per fret."""
        return max((len(frets) for frets in self._fretted_by_hand()), default=0)

    @cached_property
    def sort_key(self) -> list[int]:
        frets = [fret for string_frets in self.frets for fret in string_frets]
        return [len(string_frets) for string_frets in self.frets] + frets + list(self.hands)

    def changed(self, previous: Ladder) -> int:
        """Stops that differ from the previous bar's."""
        return sum(1 for a, b in zip(self.stops, previous.stops) if a != b)

    def tab(self) -> str:
        return " ".join("-".join(map(str, frets)) if frets else "x" for frets in self.frets)

    def _fretted_by_hand(self) -> list[set[int]]:
        by_hand: list[set[int]] = [set() for _ in range(self.shifts + 1)]
        for (_, fret), hand in zip(self.stops, self.hands):
            if fret:
                by_hand[hand].add(fret)
        return by_hand


# --- enumeration ----------------------------------------------------------


def enumerate_ladders(
    spec: ChordSpec,
    region: tuple[int, int],
    fretboard: Fretboard,
    pattern: Pattern,
    limit: int | None = None,
) -> tuple[Ladder, ...]:
    """Every ladder of `spec` within `region` that passes the hard rules, or the first `limit`.

    Each fretted stop joins the current hand position if that stays within the
    span and finger limits, starts the next position if the hand can slide
    there from the previous stop on the same string, or both, as separate
    ladders.
    """
    low_fret, high_fret = region[0], min(region[1], fretboard.max_fret)
    count = fretboard.string_count
    size, per_string_limit = pattern.stops, pattern.notes_per_string
    options: list[list[tuple[int, int]]] = []  # per string, low first: (fret, pitch), rising
    for index, open_pitch in enumerate(fretboard.open_midi):
        allowed = spec.pitch_classes
        if count - index in fretboard.tension_strings:
            allowed = allowed | spec.tensions
        frets = ([0] if open_pitch % 12 in allowed else []) + [
            f for f in range(max(low_fret, 1), high_fret + 1) if (open_pitch + f) % 12 in allowed
        ]
        options.append([(f, open_pitch + f) for f in frets])

    found: list[Ladder] = []
    per_string: list[list[int]] = [[] for _ in range(count)]
    pitches: list[int] = []
    hands: list[int] = []

    def next_string(index: int, hand: int, held: frozenset[int]) -> None:
        if size - len(pitches) > (count - index) * per_string_limit or len(found) == limit:
            return
        if index == count:
            if len(pitches) == size and spec.required <= {p % 12 for p in pitches}:
                found.append(Ladder(tuple(map(tuple, per_string)), tuple(pitches), tuple(hands)))
            return
        on_string(index, 0, hand, held)

    def on_string(index: int, start: int, hand: int, held: frozenset[int]) -> None:
        next_string(index + 1, hand, held)
        if len(per_string[index]) == per_string_limit or len(pitches) == size:
            return
        for k in range(start, len(options[index])):
            fret, pitch = options[index][k]
            if pitches and pitch <= pitches[-1]:
                continue
            if not pitches and pitch % 12 != spec.bass:
                continue
            slide_from = per_string[index][-1] if per_string[index] else None
            for placed in _placements(fret, hand, held, slide_from, fretboard, pattern):
                per_string[index].append(fret)
                pitches.append(pitch)
                hands.append(placed[0])
                on_string(index, k + 1, *placed)
                per_string[index].pop()
                pitches.pop()
                hands.pop()

    next_string(0, 0, frozenset())
    return tuple(found)


def _placements(
    fret: int,
    hand: int,
    held: frozenset[int],
    slide_from: int | None,
    fretboard: Fretboard,
    pattern: Pattern,
) -> list[tuple[int, frozenset[int]]]:
    """Each hand position a new stop can fall in, with the frets that position then covers.

    `slide_from` is the previous stop's fret when it's on the same string, so
    the hand could slide up from it; None otherwise.
    """
    if fret == 0:
        return [(hand, held)]  # an open string doesn't move the hand
    placements = []
    joined = held | {fret}
    if max(joined) - min(joined) <= fretboard.max_span and len(joined) <= fretboard.max_fingers:
        placements.append((hand, joined))
    if slide_from is not None and fret - slide_from <= pattern.max_slide and hand + 1 < pattern.hand_positions:
        placements.append((hand + 1, frozenset({fret})))
    return placements


# --- the independent check ------------------------------------------------


def check_ladder(
    ladder: Ladder,
    spec: ChordSpec,
    fretboard: Fretboard,
    pattern: Pattern,
    region: tuple[int, int] | None = None,
) -> list[str]:
    """Every hard rule `ladder` breaks, as readable messages; empty if none."""
    count = fretboard.string_count
    if len(ladder.frets) != count:
        return [f"expected {count} strings"]
    stops = [(count - index, fret) for index, frets in enumerate(ladder.frets) for fret in frets]
    if not len(stops) == len(ladder.pitches) == len(ladder.hands) == pattern.stops:
        return [f"expected {pattern.stops} stops, pitches and hand positions"]

    problems = []
    for index, frets in enumerate(ladder.frets):
        string = count - index
        if len(frets) > pattern.notes_per_string:
            problems.append(f"string {string} has {len(frets)} stops, more than {pattern.notes_per_string}")
        if any(b <= a for a, b in zip(frets, frets[1:])):
            problems.append(f"string {string}'s frets don't rise")
    for (string, fret), midi in zip(stops, ladder.pitches):
        if not 0 <= fret <= fretboard.max_fret:
            problems.append(f"string {string} fret {fret} is outside frets 0-{fretboard.max_fret}")
        if fret and region is not None and not region[0] <= fret <= region[1]:
            problems.append(f"string {string} fret {fret} is outside region {region[0]}-{region[1]}")
        if midi != fretboard.open_pitch(string) + fret:
            problems.append(f"string {string} pitch {midi} doesn't match fret {fret}")
        if midi % 12 not in spec.pitch_classes:
            if midi % 12 not in spec.tensions:
                problems.append(f"string {string} plays a note outside {spec.symbol}")
            elif string not in fretboard.tension_strings:
                problems.append(f"string {string} plays a tension but isn't a tension string")
    if any(b <= a for a, b in zip(ladder.pitches, ladder.pitches[1:])):
        problems.append("the pitch doesn't rise at every stop")

    if ladder.hands[0] != 0 or any(b - a not in (0, 1) for a, b in zip(ladder.hands, ladder.hands[1:])):
        problems.append("hand positions don't follow the ladder in order")
    for i in range(1, len(stops)):
        if ladder.hands[i] == ladder.hands[i - 1]:
            continue
        (string, fret), (before_string, before_fret) = stops[i], stops[i - 1]
        if string != before_string:
            problems.append(f"hand position {ladder.hands[i] + 1} isn't reached by sliding along a string")
        elif fret - before_fret > pattern.max_slide:
            problems.append(f"the slide to hand position {ladder.hands[i] + 1} is {fret - before_fret} frets")
    if max(ladder.hands) + 1 > pattern.hand_positions:
        problems.append(f"uses {max(ladder.hands) + 1} hand positions, more than {pattern.hand_positions}")
    for hand in sorted(set(ladder.hands)):
        fretted = {fret for (_, fret), h in zip(stops, ladder.hands) if h == hand and fret}
        if fretted and max(fretted) - min(fretted) > fretboard.max_span:
            problems.append(
                f"hand position {hand + 1} spans {max(fretted) - min(fretted)}, more than {fretboard.max_span}"
            )
        if len(fretted) > fretboard.max_fingers:
            problems.append(f"hand position {hand + 1} needs {len(fretted)} fingers")

    missing = spec.required - {p % 12 for p in ladder.pitches}
    if missing:
        spelling = dict(spec.spelling)
        problems.append(f"missing {', '.join(sorted(spelling.get(pc, str(pc)) for pc in missing))}")
    if ladder.pitches[0] % 12 != spec.bass:
        problems.append("the lowest stop isn't the bass")
    return problems
