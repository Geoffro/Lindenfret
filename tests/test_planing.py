import random
from dataclasses import replace
from pathlib import Path

import pytest

from lindenfret.config import load_config
from lindenfret.fretboard import check_fingering
from lindenfret.harmony import Bar
from lindenfret.planing import all_shapes, plane, shape_kinds

CONFIG = load_config(Path(__file__).resolve().parent.parent / "configs" / "etude1.toml")
FRETBOARD = CONFIG.fretboard
SECTION = CONFIG.sections["B"]
SHAPES = all_shapes(FRETBOARD, SECTION.open_strings)


def planing_bars(offsets):
    return [Bar(0, None, None, SECTION.region, "planing", o, ()) for o in offsets]


def test_the_references_shape_is_a_diminished_seventh():
    # Bars 23-44: strings 5, 4, 3, 2 at b+1, b+2, b, b+2 over open low and high E.
    reference = (None, 1, 2, 0, 2, None)
    assert "dim7" in shape_kinds(reference, FRETBOARD.open_midi)
    assert any(s.offsets == reference for s in SHAPES)


def test_kinds_are_what_the_fretted_notes_form():
    for shape in SHAPES:
        pcs = {(FRETBOARD.open_midi[i] + o) % 12 for i, o in enumerate(shape.offsets) if o is not None}
        assert len(pcs) >= 3
        if "dim7" in shape.kinds:
            assert len(pcs) == 4 and all((b - a) % 3 == 0 for a in pcs for b in pcs)
        if "augmented" in shape.kinds:
            assert len(pcs) == 3 and all((b - a) % 4 == 0 for a in pcs for b in pcs)


def test_every_shape_leaves_the_configured_strings_open():
    assert all(s.offsets.count(None) == SECTION.open_strings for s in SHAPES)


@pytest.mark.parametrize("seed", range(40))
def test_the_slide_follows_the_offsets_and_passes_the_hard_rules(seed):
    offsets = [0, -1, -2, -3, -1, -2, -3, -4, -3, -4, -5]
    planed = plane(planing_bars(offsets), SECTION, CONFIG, random.Random(seed))
    shapes = set()
    for bar, offset in zip(planed, offsets):
        assert check_fingering(bar.fingering, None, FRETBOARD, CONFIG.pattern.strings, SECTION.region) == []
        assert bar.fingering.span <= CONFIG.voicer.comfortable_span
        assert bar.shape in SECTION.shape_types
        assert not bar.note
        # Undo this bar's slide: every bar must then show the same shape. At
        # base 0 a string fretted at the base rings open, so compare only
        # bars where every shape string is still fretted.
        if bar.fingering.frets.count(0) == SECTION.open_strings:
            shapes.add(tuple(f - offset if f else None for f in bar.fingering.frets))
    assert len(shapes) == 1


def test_same_stream_same_shape():
    bars = planing_bars([0, -1, -2])
    assert plane(bars, SECTION, CONFIG, random.Random(3)) == plane(bars, SECTION, CONFIG, random.Random(3))


def test_shape_kinds_follow_the_weights():
    counts = {k: 0 for k in SECTION.shape_types}
    for seed in range(300):
        counts[plane(planing_bars([0, -1]), SECTION, CONFIG, random.Random(seed))[0].shape] += 1
    assert counts["dim7"] > counts["augmented"] > counts["any"]


@pytest.mark.parametrize("region", [SECTION.region, (5, 6)])
def test_a_slide_longer_than_the_region_stops_at_the_edge(region):
    section = replace(SECTION, region=region)
    for seed in range(20):
        planed = plane(planing_bars(range(0, -20, -1)), section, CONFIG, random.Random(seed))
        assert any("no room to slide" in b.note for b in planed)
        for bar in planed:
            assert check_fingering(bar.fingering, None, FRETBOARD, CONFIG.pattern.strings, region) == []


def test_an_empty_section_plans_nothing():
    assert plane([], SECTION, CONFIG, random.Random(0)) == []


def test_the_start_fret_stays_inside_the_region():
    region = (4, 12)
    for seed in range(30):
        planed = plane(planing_bars([0, -1, -2]), replace(SECTION, region=region), CONFIG, random.Random(seed))
        for bar in planed:
            assert all(region[0] <= f <= region[1] for f in bar.fingering.frets if f)
