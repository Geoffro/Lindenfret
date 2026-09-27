import dataclasses
import random
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lindenfret.chords import build_chord_table, parse_chord
from lindenfret.config import MODES, load_config
from lindenfret.fretboard import (
    Fingering,
    NoFingering,
    Voicer,
    check_fingering,
    enumerate_fingerings,
    fingers_needed,
    hand_positions,
)
from lindenfret.report import unplayable_chords

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"
CONFIG = load_config(PRESET)
FRETBOARD = CONFIG.fretboard
PATTERN = CONFIG.pattern.strings
TABLE = build_chord_table(CONFIG.palette)
NECK = (0, FRETBOARD.max_fret)


def fingering(*frets):
    return Fingering.from_frets(frets, FRETBOARD)


def voicer(**overrides):
    return Voicer(FRETBOARD, PATTERN, dataclasses.replace(CONFIG.voicer, **overrides))


# Fingerings the reference itself plays, from tools/analyze_reference.py.
REFERENCE = [
    ("Em", (0, 2, 2, 0, 0, 0)),  # bar 1
    ("F#m7b5/E", (0, 3, 4, 2, 1, 0)),  # bar 3
    ("B7/F#", (2, 0, 1, 2, 0, 2)),  # bar 7
    ("Em/G", (3, 2, 2, 0, 0, 0)),  # bar 9
    ("E/G#", (4, 2, 2, 1, 0, 0)),  # bar 11
    ("Am", (5, 7, 7, 5, 5, 5)),  # bar 13, a barre at fret 5
    ("B7", (7, 9, 7, 8, 7, 7)),  # bar 21
]


@pytest.mark.parametrize("symbol, frets", REFERENCE)
def test_the_references_fingerings_are_found(symbol, frets):
    spec = parse_chord(symbol)
    found = enumerate_fingerings(spec, NECK, FRETBOARD, PATTERN)
    assert fingering(*frets) in found
    assert check_fingering(fingering(*frets), spec, FRETBOARD, PATTERN, NECK) == []


def test_barre_counts_as_one_finger():
    assert fingers_needed(fingering(5, 7, 7, 5, 5, 5)) == 3  # barre + two
    assert fingers_needed(fingering(1, 3, 3, 2, 1, 1)) == 4  # the F major barre


def test_open_string_under_the_barre_breaks_it():
    assert fingers_needed(fingering(2, 0, 2, 2, 3, 3)) == 5


@pytest.mark.parametrize(
    "symbol, frets, problem",
    [
        ("Em", (0, 2, 2, 0, 0, 12), "span 10 exceeds 5"),
        ("Em", (0, 2, 2, 0, 0, 15), "outside frets 0-13"),
        ("Em", (None, 2, 2, 0, 0, 0), "string 6 is muted but the pattern plays it"),
        ("Em", (0, 2, 2, 0, 1, 0), "plays a note outside Em"),
        ("Em", (0, 2, 2, 4, 0, 0), "missing G"),
        ("Em/G", (0, 2, 2, 0, 0, 0), "lowest note isn't the bass G"),
        ("E/G#", (4, 7, 6, 4, 0, 4), "needs 5 fingers"),  # the open B3 breaks the barre
    ],
)
def test_check_names_each_broken_rule(symbol, frets, problem):
    problems = check_fingering(fingering(*frets), parse_chord(symbol), FRETBOARD, PATTERN, NECK)
    assert any(problem in p for p in problems), problems


def test_region_limits_fretted_notes_only():
    spec = parse_chord("Em")
    assert fingering(0, 2, 2, 0, 0, 0) in enumerate_fingerings(spec, (0, 4), FRETBOARD, PATTERN)
    assert all(
        f.position >= 5 or f.position == 0
        for f in enumerate_fingerings(spec, (5, 10), FRETBOARD, PATTERN)
    )


chords = st.sampled_from(
    [(mode, tonic, i) for mode in MODES for tonic in range(12) for i in range(len(TABLE.chords[(mode, tonic)]))]
)


@settings(max_examples=150, deadline=None)
@given(chord=chords, region=st.sampled_from(hand_positions(FRETBOARD) + [NECK]))
def test_every_enumerated_fingering_passes_the_independent_check(chord, region):
    mode, tonic, index = chord
    spec = TABLE.chords[(mode, tonic)][index]
    for f in enumerate_fingerings(spec, region, FRETBOARD, PATTERN):
        assert check_fingering(f, spec, FRETBOARD, PATTERN, region) == [], (spec.symbol, f.tab())


def test_every_palette_chord_is_playable_somewhere():
    # Eb minor's Ebm/Gb has no open-string tone, so all six strings are fretted
    # with the Gb bass at fret 2 on string 6, which takes five fingers. The
    # harmony stage routes around it; any new entry here is a regression.
    assert unplayable_chords(voicer(), TABLE) == ["Ebm/Gb in Eb minor"]


def test_choose_is_deterministic_for_a_stream():
    spec = parse_chord("Am")
    a = voicer().choose(spec, NECK, None, random.Random(5))
    b = voicer().choose(spec, NECK, None, random.Random(5))
    assert a == b


def test_zero_temperature_takes_the_best():
    v = voicer(temperature=0.0)
    spec = parse_chord("Em")
    assert v.choose(spec, (0, 4), None, random.Random(1)) == v.ranked(spec, (0, 4))[0][1]


def test_choice_comes_from_the_top_candidates():
    v = voicer(top_candidates=3)
    spec = parse_chord("B7")
    top = [f for _, f in v.ranked(spec, NECK)[:3]]
    rng = random.Random(0)
    assert all(v.choose(spec, NECK, None, rng) in top for _ in range(50))


def test_choose_skips_the_avoided_fingering():
    v = voicer(temperature=0.0)
    spec = parse_chord("Em")
    best = v.choose(spec, (0, 4), None, random.Random(0))
    assert v.choose(spec, (0, 4), None, random.Random(0), avoid=best) != best


def test_movement_prefers_staying_near_the_previous_bar():
    v = voicer()
    spec = parse_chord("Am")
    near = v.ranked(spec, NECK, previous=fingering(5, 7, 7, 5, 5, 5))[0][1]
    far = v.ranked(spec, NECK, previous=fingering(0, 0, 2, 2, 1, 0))[0][1]
    assert near.position >= 4
    assert far.position <= 2


def test_no_fingering_raises():
    spec = parse_chord("Em/G")
    with pytest.raises(NoFingering):
        voicer().choose(spec, (5, 10), None, random.Random(0))  # the G bass is at fret 3
