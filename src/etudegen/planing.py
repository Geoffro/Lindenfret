"""Planing: one generated left-hand shape slid along the neck against open strings.

A shape leaves some strings open and frets the rest at fixed offsets from a
base fret. What its fretted notes form (a diminished seventh, an augmented
triad, or any chord of three or more notes) doesn't change as it slides, so
the shape's kind is fixed when it is chosen. Each planing section generates
its own shape and start fret; every position it reaches passes the physical
hard rules.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import cache
from itertools import combinations, product

from etudegen.config import Config, ConfigError, Fretboard, Section
from etudegen.fretboard import Fingering, check_fingering, fingers_needed
from etudegen.harmony import Bar

DIM7 = frozenset({0, 3, 6, 9})
AUGMENTED = frozenset({0, 4, 8})


@dataclass(frozen=True)
class Shape:
    offsets: tuple[int | None, ...]  # per string, low string first: frets above the base, None = open
    kinds: frozenset[str]  # every kind it qualifies as: "dim7", "augmented", "any"

    @property
    def reach(self) -> int:
        return max(o for o in self.offsets if o is not None)

    def frets(self, base: int) -> tuple[int, ...]:
        return tuple(0 if o is None else base + o for o in self.offsets)


def shape_kinds(offsets: Sequence[int | None], open_midi: Sequence[int]) -> frozenset[str]:
    pcs = {(open_midi[i] + o) % 12 for i, o in enumerate(offsets) if o is not None}
    kinds = set()
    if len(pcs) >= 3:
        kinds.add("any")
    for root in pcs:
        relative = frozenset((pc - root) % 12 for pc in pcs)
        if relative == DIM7:
            kinds.add("dim7")
        if relative == AUGMENTED:
            kinds.add("augmented")
    return frozenset(kinds)


@cache
def all_shapes(fretboard: Fretboard, open_count: int) -> tuple[Shape, ...]:
    """Every shape with `open_count` open strings that the hard rules allow."""
    n = fretboard.string_count
    shapes = []
    for open_strings in combinations(range(n), open_count):
        fretted = [i for i in range(n) if i not in open_strings]
        for offs in product(range(fretboard.max_span + 1), repeat=len(fretted)):
            if min(offs) != 0:
                continue  # the base fret is the lowest fretted fret
            offsets: list[int | None] = [None] * n
            for i, o in zip(fretted, offs):
                offsets[i] = o
            kinds = shape_kinds(offsets, fretboard.open_midi)
            if not kinds:
                continue
            shape = Shape(tuple(offsets), kinds)
            if fingers_needed(Fingering.from_frets(shape.frets(1), fretboard)) <= fretboard.max_fingers:
                shapes.append(shape)
    return tuple(shapes)


def plane(bars: Sequence[Bar], section: Section, config: Config, rng: random.Random) -> list[Bar]:
    """Choose a shape and start fret for a planing section and finger each bar."""
    if not bars:
        return []
    fretboard = config.fretboard
    low_offset = min(b.offset for b in bars)
    high_offset = max(b.offset for b in bars)
    lowest, highest = section.region[0], min(section.region[1], fretboard.max_fret)

    def start_range(shape: Shape) -> range:
        return range(lowest - low_offset, highest - shape.reach - high_offset + 1)

    shapes = all_shapes(fretboard, section.open_strings)
    # Shapes whose whole slide fits; failing that, shapes that fit the region
    # at all, which stop at its edges.
    fitting = [s for s in shapes if len(start_range(s)) > 0]
    pool = fitting or [s for s in shapes if s.reach <= highest - lowest]
    if not pool:
        raise ConfigError(f"sections.{section.name}: no planing shape fits frets {lowest}-{highest}")
    kinds = [k for k, w in section.shape_types.items() if w > 0 and any(k in s.kinds for s in pool)]
    if not kinds:
        kinds = ["any"]
    kind = rng.choices(kinds, weights=[section.shape_types.get(k, 1.0) for k in kinds])[0]
    candidates = [s for s in pool if kind in s.kinds]
    # A stretch held through a whole slide should be comfortable; wider shapes
    # vastly outnumber narrow ones, so a weight alone wouldn't keep them out.
    comfortable = [s for s in candidates if s.reach <= config.voicer.comfortable_span]
    shape = rng.choice(comfortable or candidates)

    starts = start_range(shape)
    if len(starts) > 0:
        start = rng.choice(starts)
    else:  # the slide is longer than the region; center it and stop at the edges
        start = (lowest - low_offset + highest - shape.reach - high_offset) // 2

    planed = []
    for bar in bars:
        base = start + bar.offset
        note = ""
        if not lowest <= base <= highest - shape.reach:
            base = min(max(base, lowest), highest - shape.reach)
            note = f"shape held at fret {base}: no room to slide further"
        fingering = Fingering.from_frets(shape.frets(base), fretboard)
        problems = check_fingering(fingering, None, fretboard, config.pattern.strings, section.region)
        assert not problems, f"planing shape at fret {base} breaks a hard rule: {problems}"
        planed.append(replace(bar, fingering=fingering, shape=kind, note=note or bar.note))
    return planed
