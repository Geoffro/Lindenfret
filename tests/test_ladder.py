import dataclasses
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from lindenfret.chords import build_chord_table, parse_chord
from lindenfret.config import MODES, load_config
from lindenfret.fretboard import Voicer, fret_windows
from lindenfret.ladder import Ladder, check_ladder, enumerate_ladders
from lindenfret.render import render_bar

CONFIG = load_config(Path(__file__).resolve().parent.parent / "configs" / "etude2.toml")
FRETBOARD = CONFIG.fretboard
PATTERN = CONFIG.pattern
TABLE = build_chord_table(CONFIG.palette)
NECK = (0, FRETBOARD.max_fret)


def ladder(frets, hands=None):
    """A ladder from frets per string, low string first."""
    pitches = tuple(
        open_pitch + fret for open_pitch, string_frets in zip(FRETBOARD.open_midi, frets) for fret in string_frets
    )
    return Ladder(tuple(map(tuple, frets)), pitches, tuple(hands or [0] * len(pitches)))


# The reference's bar 3 (E7/B) in one position, and bar 1 (A) sliding from fret 6 to 9 on string 3.
BAR_3 = ladder([(7,), (5, 7), (6,), (4, 7), (5,), (4, 7)])
BAR_1 = ladder([(5,), (4, 7), (7,), (6, 9), (10,), (9, 12)], hands=[0, 0, 0, 0, 0, 1, 1, 1, 1])


def check(ladder, symbol, pattern=PATTERN, fretboard=FRETBOARD, region=NECK):
    return check_ladder(ladder, parse_chord(symbol), fretboard, pattern, region)


def test_the_references_ladders_pass():
    assert check(BAR_3, "E7/B") == []
    assert check(BAR_1, "A") == []
    assert BAR_1.shifts == 1 and BAR_1.span == 3 and BAR_1.fingers == 4


def test_the_references_ladders_are_found():
    assert BAR_3 in enumerate_ladders(parse_chord("E7/B"), (0, 12), FRETBOARD, PATTERN)
    assert BAR_1 in enumerate_ladders(parse_chord("A"), (0, 12), FRETBOARD, PATTERN)


def test_the_hand_may_slide_before_it_has_to():
    # C4 at fret 5 fits the first position, but only sliding there from A3 leaves room for F4 at fret 6.
    early_slide = ladder([(1,), (0, 3), (3,), (2, 5), (6,), (5, 8)], hands=[0, 0, 0, 0, 0, 1, 1, 1, 1])
    assert check(early_slide, "F") == []
    assert early_slide in enumerate_ladders(parse_chord("F"), NECK, FRETBOARD, PATTERN)


@pytest.mark.parametrize(
    "broken, symbol, changes, problem",
    [
        (ladder([(7,), (5, 7), (6,), (4, 7), (), (0, 4, 7)]), "E7/B", {}, "string 1 has 3 stops"),
        (ladder([(7,), (5, 7), (2,), (4, 7), (5,), (4, 7)]), "E7/B", {}, "doesn't rise"),
        (dataclasses.replace(BAR_3, hands=(0, 0, 0, 0, 1, 1, 1, 1, 1)), "E7/B", {}, "isn't reached by sliding"),
        (BAR_1, "A", {"max_slide": 2}, "the slide to hand position 2 is 3 frets"),
        (BAR_1, "A", {"hand_positions": 1}, "uses 2 hand positions, more than 1"),
        (BAR_3, "E7/B", {"max_span": 2}, "hand position 1 spans 3, more than 2"),
        (BAR_3, "E7/B", {"max_fingers": 3}, "hand position 1 needs 4 fingers"),
        (BAR_3, "E9/B", {}, "missing F#"),
        (BAR_3, "E7", {}, "the lowest stop isn't the bass"),
        (BAR_3, "E/B", {}, "plays a note outside E/B"),
    ],
)
def test_check_names_each_broken_rule(broken, symbol, changes, problem):
    pattern_changes = {k: v for k, v in changes.items() if hasattr(PATTERN, k)}
    fretboard_changes = {k: v for k, v in changes.items() if hasattr(FRETBOARD, k)}
    problems = check(
        broken,
        symbol,
        pattern=dataclasses.replace(PATTERN, **pattern_changes),
        fretboard=dataclasses.replace(FRETBOARD, **fretboard_changes),
    )
    assert any(problem in p for p in problems), problems


def test_region_limits_fretted_stops():
    assert any("outside region 5-12" in p for p in check(BAR_3, "E7/B", region=(5, 12)))


chords = st.sampled_from(
    [(mode, tonic, i) for mode in MODES for tonic in range(12) for i in range(len(TABLE.chords[(mode, tonic)]))]
)


@settings(max_examples=25, deadline=None)
@given(chord=chords, region=st.sampled_from(fret_windows(FRETBOARD, PATTERN)))
def test_every_enumerated_ladder_passes_the_independent_check(chord, region):
    mode, tonic, index = chord
    spec = TABLE.chords[(mode, tonic)][index]
    ladders = enumerate_ladders(spec, region, FRETBOARD, PATTERN)
    for found in ladders:
        assert check_ladder(found, spec, FRETBOARD, PATTERN, region) == [], (spec.symbol, found.tab())
    assert Voicer(FRETBOARD, PATTERN, CONFIG.voicer).playable(spec, region) == bool(ladders)


def test_a_limit_stops_the_search_early():
    assert len(enumerate_ladders(parse_chord("E7/B"), NECK, FRETBOARD, PATTERN, limit=1)) == 1


def test_contour_notes_ring_until_their_string_plays_again_or_the_hand_moves():
    notes = render_bar(BAR_1, None, PATTERN, 0.0, CONFIG.meter.bar_quarters)
    assert [n.midi for n in notes] == [BAR_1.pitches[i] for i in PATTERN.contour]
    steps = [round(n.duration / PATTERN.note_quarters) for n in notes]
    assert steps[0] == 5  # A2 on string 6 stops when the hand slides up at note 6
    assert steps[1] == 1  # C#3 stops when string 5 plays E3
    assert steps[5] == 6  # E4, after the slide, rings until string 3 plays it again
    assert steps[12] == 4  # C#4 on the way down rings to the bar line
