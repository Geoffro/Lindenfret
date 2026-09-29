import dataclasses
import random
from pathlib import Path

import pytest

from lindenfret.chords import build_chord_table
from lindenfret.config import load_config
from lindenfret.fretboard import Voicer
from lindenfret.harmony import MOVES, Center, ChordGraph, Harmonizer
from lindenfret.interpret import SectionPlan

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"
CONFIG = load_config(PRESET)
TABLE = build_chord_table(CONFIG.palette)
GRAPH = ChordGraph(TABLE, CONFIG)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern, CONFIG.voicer)
E_MINOR = Center(4, "minor")
LOW = (0, 3)  # E minor has playable chords here; G# minor, a major third up, has none


def harmonizer(moves=None, seed=0):
    config = CONFIG
    if moves is not None:
        config = dataclasses.replace(CONFIG, centers=dataclasses.replace(CONFIG.centers, moves=moves))
    return Harmonizer(config, GRAPH, VOICER, random.Random(seed))


def plan(word, name="A", region=None):
    section = CONFIG.sections[name]
    if region is not None:
        section = dataclasses.replace(section, region=region)
    return SectionPlan(0, section, (word,), 1)


def symbols(indices, mode):
    return {TABLE.chords[(mode, 4)][i].symbol for i in indices}


@pytest.mark.parametrize(
    "move, expected",
    [
        ("stay", Center(4, "minor")),
        ("fifth_up", Center(11, "minor")),
        ("fifth_down", Center(9, "minor")),
        ("relative", Center(7, "major")),
        ("parallel", Center(4, "major")),
        ("third_up", Center(8, "minor")),
        ("third_down", Center(0, "minor")),
        ("semitone_up", Center(5, "minor")),
        ("semitone_down", Center(3, "minor")),
    ],
)
def test_center_moves(move, expected):
    assert MOVES[move](E_MINOR) == expected


def test_relative_goes_both_ways():
    assert MOVES["relative"](MOVES["relative"](E_MINOR)) == E_MINOR


def test_tonic_and_dominant_chords_come_from_the_palette():
    assert symbols(GRAPH.tonics["minor"], "minor") == {"Em", "Em/G", "Em/B"}
    assert symbols(GRAPH.dominants["minor"], "minor") == {"B7/F#", "B7"}  # Bsus4 has no third
    assert symbols(GRAPH.tonics["major"], "major") == {"E", "E/G#"}
    assert symbols(GRAPH.dominants["major"], "major") == {"B7", "B7/F#"}


def test_weights_favor_small_bass_steps_and_reference_changes():
    minor = CONFIG.palette.minor
    em, f_sharp_half_dim, am = minor.index("Em"), minor.index("F#m7b5/E"), minor.index("Am")
    step = CONFIG.graph.bass_step
    # Em -> F#m7b5/E keeps the bass on E and is a change the reference makes.
    assert GRAPH.weight((E_MINOR, em), E_MINOR, f_sharp_half_dim) == step[0] + CONFIG.graph.reference_bonus
    # Em -> Am moves the bass a fourth and isn't in a reference path.
    assert GRAPH.weight((E_MINOR, em), E_MINOR, am) == step[5]


def test_a_section_starts_on_the_tonic_and_K_cadences():
    bars, _ = harmonizer().walk(plan("FK"), E_MINOR, "start")
    assert [b.role for b in bars] == ["tonic", "dominant", "tonic"]
    assert bars[1].chord.symbol in {"B7", "B7/F#"}


def test_M_moves_the_center_and_brackets_restore_it():
    bars, end = harmonizer(moves={"fifth_up": 1}).walk(plan("F[MF]F"), E_MINOR, "start")
    assert [b.center for b in bars] == [E_MINOR, Center(11, "minor"), E_MINOR]
    assert bars[1].events == ("[", "M fifth_up: B minor")
    assert bars[2].events == ("]",)
    assert end == E_MINOR


def test_H_holds_the_chord():
    bars, _ = harmonizer().walk(plan("FH"), E_MINOR, "start")
    assert [b.role for b in bars] == ["tonic", "hold"]
    assert bars[0].chord == bars[1].chord


def test_M_stays_when_no_center_fits_the_region():
    bars, end = harmonizer(moves={"third_up": 1}).walk(plan("FMF", region=LOW), E_MINOR, "start")
    assert bars[1].events == ("M: no center fits frets 0-3; stayed",)
    assert bars[1].center == end == E_MINOR


def test_a_section_draws_a_new_center_when_no_move_fits():
    h = harmonizer(moves={"third_up": 1})
    center, event = h.section_center(E_MINOR, LOW)
    assert event.startswith("new center")
    assert h._tonic_playable(center, LOW)


def test_an_unplayable_tonic_becomes_a_step_with_a_note():
    # In frets 3-5 no E minor tonic chord has a fingering.
    bars, _ = harmonizer().walk(plan("F", region=(3, 5)), E_MINOR, "start")
    assert bars[0].role == "step"
    assert bars[0].note == "no tonic of E minor playable in frets 3-5"


def test_region_shifts_stop_at_the_neck():
    bars, _ = harmonizer().walk(plan("+" * 6 + "F"), E_MINOR, "start")
    assert bars[0].region == (4, 13)  # section A spans 0-9; max_fret is 13
    assert "+ (no room)" in bars[0].events


def test_planing_tracks_the_shapes_slide():
    bars = harmonizer().planing(plan("F-F[-F]F", name="B"))
    assert [b.offset for b in bars] == [0, -1, -2, -1]
    assert all(b.center is None and b.chord is None for b in bars)
