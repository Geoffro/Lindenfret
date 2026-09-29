"""Tonal centers, the chord graph, and the walk that turns section plans into bars.

A center is a tonic pitch class and a mode. Graph sections walk the chord
graph of the current center, one chord per bar. Mode sections walk the same
way, over the chords of a Messiaen mode whose first degree is the tonic.
Planing sections have no center and only track how far their shape has slid.
Every chord and center offered must be playable in the current fret region,
so the walk routes around what the voicer can't finger there.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace

from lindenfret.chords import ChordSpec, ChordTable
from lindenfret.config import CENTER_MOVES, MODES, Config, Graph, Palette, Section, mode_name, pitch_class
from lindenfret.fretboard import Region, Voicer, Voicing
from lindenfret.interpret import SectionPlan


@dataclass(frozen=True)
class Center:
    tonic: int  # pitch class, C = 0
    mode: str  # "minor", "major", or a Messiaen mode such as "mode 2"


def _other_mode(mode: str) -> str:
    return "major" if mode == "minor" else "minor"


# How each center move changes the center. Thirds are major thirds (chromatic mediants).
MOVES: dict[str, Callable[[Center], Center]] = {
    "stay": lambda c: c,
    "fifth_up": lambda c: Center((c.tonic + 7) % 12, c.mode),
    "fifth_down": lambda c: Center((c.tonic + 5) % 12, c.mode),
    "relative": lambda c: Center((c.tonic + (3 if c.mode == "minor" else 9)) % 12, _other_mode(c.mode)),
    "parallel": lambda c: Center(c.tonic, _other_mode(c.mode)),
    "third_up": lambda c: Center((c.tonic + 4) % 12, c.mode),
    "third_down": lambda c: Center((c.tonic + 8) % 12, c.mode),
    "semitone_up": lambda c: Center((c.tonic + 1) % 12, c.mode),
    "semitone_down": lambda c: Center((c.tonic + 11) % 12, c.mode),
}
assert set(MOVES) == set(CENTER_MOVES)
MODE_CHANGES = ("relative", "parallel")  # moves between minor and major; a mode section keeps its mode


class HarmonyError(ValueError):
    """The walk needs a chord where none is playable."""


@dataclass(frozen=True)
class Bar:
    section: int  # index of the section in the form
    center: Center | None  # None in planing bars
    chord: ChordSpec | None  # None in planing bars
    region: Region  # frets the hand may use this bar
    role: str  # "tonic", "step", "hold", "dominant" or "planing"
    offset: int  # frets the region, or the planing shape, has moved within the section
    events: tuple[str, ...]  # what changed since the previous bar
    note: str = ""  # why the walk departed from its rule, if it had to
    fingering: Voicing | None = None
    shape: str = ""  # a planing bar's shape kind: "dim7", "augmented" or "any"


ChordRef = tuple[Center, int]  # a chord by its center and palette index


class ChordGraph:
    """Every center's chords, and the weight of moving between them."""

    def __init__(self, table: ChordTable, graph: Graph, palette: Palette) -> None:
        self.table = table
        self.bass_step = graph.bass_step
        self.reference_bonus = graph.reference_bonus
        home = pitch_class(palette.tonic)
        self.tonics: dict[str, tuple[int, ...]] = {}
        self.dominants: dict[str, tuple[int, ...]] = {}
        self.reference_edges: dict[str, set[tuple[int, int]]] = {}
        for mode in MODES:
            specs = table.chords[(mode, home)]
            third, other_third = (3, 4) if mode == "minor" else (4, 3)
            self.tonics[mode] = tuple(
                i for i, s in enumerate(specs)
                if s.root == home
                and (home + third) % 12 in s.pitch_classes
                and (home + other_third) % 12 not in s.pitch_classes
            )
            fifth = (home + 7) % 12
            self.dominants[mode] = tuple(
                i for i, s in enumerate(specs) if s.root == fifth and (fifth + 4) % 12 in s.pitch_classes
            )
            if not self.tonics[mode]:
                raise HarmonyError(f"palette.{mode}: no tonic chord (a {mode} chord rooted on {palette.tonic})")
            if not self.dominants[mode]:
                raise HarmonyError(f"palette.{mode}: no dominant chord (a chord on the fifth with a major third)")
            figures = getattr(palette, mode)
            self.reference_edges[mode] = {
                (figures.index(a), figures.index(b))
                for path in graph.reference_paths
                if all(c in figures for c in path)
                for a, b in zip(path, path[1:])
            }
        # A Messiaen mode's chords come in the same order on every first degree; its tonics are those rooted there.
        for mode in sorted({mode for mode, _ in table.chords} - set(MODES)):
            self.tonics[mode] = tuple(i for i, s in enumerate(table.chords[(mode, 0)]) if s.root == 0)
            if not self.tonics[mode]:
                raise HarmonyError(f"{mode}: none of [modal] chord_types gives a chord on the mode's first degree")

    def chords(self, center: Center) -> tuple[ChordSpec, ...]:
        return self.table.chords[(center.mode, center.tonic)]

    def name(self, center: Center) -> str:
        return self.table.center_name(center.mode, center.tonic)

    def weight(self, previous: ChordRef | None, center: Center, index: int) -> float:
        """How strongly the walk favors `index` in `center` after the previous chord."""
        if previous is None:
            return 1.0
        prev_center, prev_index = previous
        a = self.chords(prev_center)[prev_index].bass
        b = self.chords(center)[index].bass
        weight = self.bass_step.get(min((a - b) % 12, (b - a) % 12), 0.0)
        if prev_center == center and (prev_index, index) in self.reference_edges.get(center.mode, ()):
            weight += self.reference_bonus
        return weight


@dataclass
class _State:
    center: Center
    chord: ChordRef | None
    shift: int


class Harmonizer:
    """Chooses centers and chords for each section, from the "harmony" random stream."""

    def __init__(self, config: Config, graph: ChordGraph, voicer: Voicer, rng: random.Random) -> None:
        self.centers = config.centers
        self.max_fret = config.fretboard.max_fret
        self.graph = graph
        self.voicer = voicer
        self.rng = rng

    # --- centers ----------------------------------------------------------

    def start_center(self, region: Region) -> Center:
        options = [
            Center(tonic, mode)
            for mode in MODES
            for tonic in range(12)
            if self.centers.start[tonic] * self.centers.start_mode.get(mode, 0) > 0
        ]
        options = [c for c in options if self._tonic_playable(c, region)]
        if not options:
            raise HarmonyError(f"no starting center has a playable tonic chord in frets {_frets(region)}")
        weights = [self.centers.start[c.tonic] * self.centers.start_mode[c.mode] for c in options]
        return self.rng.choices(options, weights=weights)[0]

    def move(self, center: Center, region: Region, need_tonic: bool) -> tuple[str, Center] | None:
        """One weighted center move whose target is playable in `region`, or None."""
        playable = self._tonic_playable if need_tonic else self._any_playable
        options = [
            (name, MOVES[name](center))
            for name, weight in self.centers.moves.items()
            if weight > 0
            and (center.mode in MODES or name not in MODE_CHANGES)
            and playable(MOVES[name](center), region)
        ]
        if not options:
            return None
        weights = [self.centers.moves[name] for name, _ in options]
        return self.rng.choices(options, weights=weights)[0]

    def section_center(self, previous: Center | None, region: Region) -> tuple[Center, str]:
        """The center a graph section starts in, and the event that describes it.

        After a graph section's center it is one move away. After a mode's, it
        keeps the tonic, in minor or major by the start weights.
        """
        if previous is None:
            center = self.start_center(region)
            return center, f"start: {self.graph.name(center)}"
        if previous.mode in MODES:
            moved = self.move(previous, region, need_tonic=True)
            if moved is not None:
                name, center = moved
                return center, f"section: {name} to {self.graph.name(center)}"
            why = "no move fits"
        else:
            kept = self._keep_tonic(previous.tonic, self.centers.start_mode, region)
            if kept is not None:
                return kept, f"section: {self.graph.name(kept)}"
            why = "no mode on the previous tonic fits"
        center = self.start_center(region)
        return center, f"new center {self.graph.name(center)}: {why} frets {_frets(region)}"

    def mode_center(self, previous: Center | None, section: Section) -> tuple[Center, str]:
        """The center a mode section starts in, and the event that describes it.

        The mode's first degree is `previous`'s tonic if any of the section's
        modes has a chord on it playable in the section's region; otherwise it
        is drawn from the start weights.
        """
        region = section.region
        weights = {mode_name(number): w for number, w in section.modes.items() if w > 0}
        if previous is not None:
            kept = self._keep_tonic(previous.tonic, weights, region)
            if kept is not None:
                return kept, f"section: {self.graph.name(kept)}"
        options = [Center(tonic, mode) for mode in weights for tonic in range(12) if self.centers.start[tonic] > 0]
        options = [c for c in options if self._tonic_playable(c, region)]
        if not options:
            raise HarmonyError(
                f"sections.{section.name}: no mode has a chord on its first degree playable in frets {_frets(region)}"
            )
        center = self.rng.choices(options, weights=[self.centers.start[c.tonic] * weights[c.mode] for c in options])[0]
        if previous is None:
            return center, f"start: {self.graph.name(center)}"
        return center, f"new center {self.graph.name(center)}: no mode on the previous tonic fits frets {_frets(region)}"

    def _keep_tonic(self, tonic: int, weights: Mapping[str, float], region: Region) -> Center | None:
        """A center on `tonic` in a weighted mode whose tonic chord is playable in `region`, or None."""
        options = [Center(tonic, mode) for mode, weight in weights.items() if weight > 0]
        options = [c for c in options if self._tonic_playable(c, region)]
        if not options:
            return None
        return self.rng.choices(options, weights=[weights[c.mode] for c in options])[0]

    # --- sections ---------------------------------------------------------

    def walk(self, plan: SectionPlan, center: Center, event: str) -> tuple[list[Bar], Center]:
        """The bars of a graph or mode section, and the center it ends in."""
        base = plan.section.region
        state = _State(center, None, 0)
        stack: list[_State] = []
        pending = [event]
        bars: list[Bar] = []

        def emit(index: int, role: str, note: str = "") -> None:
            region = _shifted(base, state.shift)
            chord = self.graph.chords(state.center)[index]
            bars.append(
                Bar(plan.index, state.center, chord, region, role, state.shift, tuple(pending), note)
            )
            pending.clear()
            state.chord = (state.center, index)

        for symbol in plan.word:
            region = _shifted(base, state.shift)
            if symbol in "FH":
                if state.chord is None:
                    emit(*self._tonic(state, region))
                elif symbol == "H" and state.chord[0] == state.center and self._playable(*state.chord, region):
                    emit(state.chord[1], "hold")
                else:
                    emit(*self._step(state, region))
            elif symbol == "K":
                emit(*self._dominant(state, region))
                emit(*self._tonic(state, region))
            elif symbol == "M":
                moved = self.move(state.center, region, need_tonic=False)
                if moved is None:
                    pending.append(f"M: no center fits frets {_frets(region)}; stayed")
                else:
                    name, state.center = moved
                    pending.append(f"M {name}: {self.graph.name(state.center)}")
            elif symbol in "+-":
                shift = state.shift + (1 if symbol == "+" else -1)
                if base[0] + shift >= 0 and base[1] + shift <= self.max_fret:
                    state.shift = shift
                    pending.append(symbol)
                else:
                    pending.append(f"{symbol} (no room)")
            elif symbol == "[":
                stack.append(replace(state))
                pending.append("[")
            elif symbol == "]":
                restored = stack.pop()
                state.center, state.chord, state.shift = restored.center, restored.chord, restored.shift
                pending.append("]")
        return bars, state.center

    def planing(self, plan: SectionPlan) -> list[Bar]:
        """The bars of a planing section: where the shape sits relative to its start."""
        offset, stack, pending = 0, [], ["planing"]
        bars: list[Bar] = []
        for symbol in plan.word:
            if symbol in "FH":
                bars.append(
                    Bar(plan.index, None, None, plan.section.region, "planing", offset, tuple(pending))
                )
                pending = []
            elif symbol in "+-":
                offset += 1 if symbol == "+" else -1
                pending.append(symbol)
            elif symbol == "[":
                stack.append(offset)
                pending.append("[")
            elif symbol == "]":
                offset = stack.pop()
                pending.append("]")
        return bars

    # --- chord choices ----------------------------------------------------

    def _tonic(self, state: _State, region: Region) -> tuple[int, str, str]:
        choice = self._pick(state, self.graph.tonics[state.center.mode], region)
        if choice is not None:
            return choice, "tonic", ""
        index, role, _ = self._step(state, region)
        return index, role, f"no tonic of {self.graph.name(state.center)} playable in frets {_frets(region)}"

    def _dominant(self, state: _State, region: Region) -> tuple[int, str, str]:
        choice = self._pick(state, self.graph.dominants[state.center.mode], region)
        if choice is not None:
            return choice, "dominant", ""
        index, role, _ = self._step(state, region)
        return index, role, f"no dominant of {self.graph.name(state.center)} playable in frets {_frets(region)}"

    def _step(self, state: _State, region: Region) -> tuple[int, str, str]:
        count = len(self.graph.chords(state.center))
        current = state.chord[1] if state.chord and state.chord[0] == state.center else None
        choice = self._pick(state, [i for i in range(count) if i != current], region)
        if choice is not None:
            return choice, "step", ""
        if current is not None and self._playable(state.center, current, region):
            return current, "hold", "no other chord playable here"
        raise HarmonyError(f"no chord of {self.graph.name(state.center)} is playable in frets {_frets(region)}")

    def _pick(self, state: _State, indices: Sequence[int], region: Region) -> int | None:
        options = [i for i in indices if self._playable(state.center, i, region)]
        if not options:
            return None
        weights = [self.graph.weight(state.chord, state.center, i) for i in options]
        if not any(weights):
            weights = [1.0] * len(options)
        return self.rng.choices(options, weights=weights)[0]

    # --- playability ------------------------------------------------------

    def _playable(self, center: Center, index: int, region: Region) -> bool:
        return self.voicer.playable(self.graph.chords(center)[index], region)

    def _tonic_playable(self, center: Center, region: Region) -> bool:
        return any(self._playable(center, i, region) for i in self.graph.tonics[center.mode])

    def _any_playable(self, center: Center, region: Region) -> bool:
        return any(self._playable(center, i, region) for i in range(len(self.graph.chords(center))))


def _shifted(region: Region, shift: int) -> Region:
    return (region[0] + shift, region[1] + shift)


def _frets(region: Region) -> str:
    return f"{region[0]}-{region[1]}"
