"""Mode sections: chords generated from Messiaen's modes of limited transposition."""

import dataclasses
import random
from pathlib import Path

import pytest

from lindenfret.chords import ChordError, build_chord_table
from lindenfret.cli import main
from lindenfret.config import MESSIAEN_MODES, Palette, load_config
from lindenfret.fretboard import Voicer
from lindenfret.harmony import MOVES, Center, ChordGraph, Harmonizer, HarmonyError
from lindenfret.lsystem import Production
from lindenfret.pipeline import chord_table, plan_piece

CONFIGS = Path(__file__).resolve().parent.parent / "configs"
PRESET = CONFIGS / "etude1-messiaen.toml"
CONFIG = load_config(PRESET)
TABLE = chord_table(CONFIG)
GRAPH = ChordGraph(TABLE, CONFIG.graph, CONFIG.palette)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern, CONFIG.voicer)
PALETTE = Palette("E", frozenset({7}), ("Em",), ("E",))
C, E, G_SHARP = 0, 4, 8
LOW = (0, 3)  # G# has no playable tonic chord here in mode 2, mode 3, minor or major; E has


def symbols(table, mode, first):
    return [s.symbol for s in table.chords[(mode, first)]]


def test_a_mode_gets_every_chord_of_each_type_that_lies_in_it():
    table = build_chord_table(PALETTE, ["", "7", "dim7"], [2])
    assert symbols(table, "mode 2", C) == [
        "C", "C7", "Cdim7", "C#dim7", "Eb", "Eb7", "D#dim7", "Edim7",
        "F#", "F#7", "F#dim7", "Gdim7", "A", "A7", "Adim7", "A#dim7",
    ]  # C Db Eb E F# G A Bb
    assert table.center_name("mode 2", C) == "C mode 2"


@pytest.mark.parametrize("number", sorted(CONFIG.modes))
def test_every_first_degree_lists_the_same_chords_transposed(number):
    mode = f"mode {number}"
    for first in range(12):
        steps = {(first + step) % 12 for step in MESSIAEN_MODES[number]}
        for home, moved in zip(TABLE.chords[(mode, C)], TABLE.chords[(mode, first)], strict=True):
            assert moved.pitch_classes == {(pc + first) % 12 for pc in home.pitch_classes}
            assert moved.root == (home.root + first) % 12
            assert moved.pitch_classes <= steps, moved.symbol


def test_roots_take_the_simplest_name_and_tones_are_spelled_by_interval():
    in_e = symbols(build_chord_table(PALETTE, ["", "m", "+", "dim7", "7#9"], [2, 3]), "mode 2", E)
    assert {"Db", "C#m", "Fdim7"} <= set(in_e) and not {"C#", "Dbm", "E#dim7"} & set(in_e)
    table = build_chord_table(PALETTE, ["", "+", "7#9"], [2, 3])
    e7_sharp9 = next(s for s in table.chords[("mode 2", E)] if s.symbol == "E7#9")
    assert dict(e7_sharp9.spelling)[7] == "F##"
    assert "B+" in symbols(table, "mode 3", E)  # B D# F##, not Cb Eb G


def test_polychords_spell_shared_tones_one_way():
    in_e = symbols(build_chord_table(PALETTE, ["|"], [2]), "mode 2", E)
    assert "C#|E" in in_e and "Db|E" not in in_e  # C# E# G# over E G# B
    assert "E|C#" in in_e  # E G# B over C# E# G#


def test_polychords_need_an_upper_chord_that_adds_tones():
    table = build_chord_table(PALETTE, ["|", "m|"], [2])
    assert "Cm|C" in symbols(table, "mode 2", C)  # a split third
    assert "C|C" not in symbols(table, "mode 2", C)


@pytest.mark.parametrize(
    "chord_type, message",
    [("xyz", "can't parse"), ("m|m|m", "stacks two types"), ("7/E", "slash chords")],
)
def test_bad_chord_types_raise(chord_type, message):
    with pytest.raises(ChordError, match=f"modal.chord_types: .*{message}"):
        build_chord_table(PALETTE, ["", chord_type], [2])


def test_tonics_are_the_chords_on_the_first_degree():
    assert {TABLE.chords[("mode 2", E)][i].symbol for i in GRAPH.tonics["mode 2"]} >= {"E", "Em", "E7"}
    assert all(TABLE.chords[("mode 3", E)][i].root == E for i in GRAPH.tonics["mode 3"])


def test_a_mode_with_no_chord_on_its_first_degree_fails():
    table = build_chord_table(CONFIG.palette, ["", "m"], [5])  # C Db F Gb G B holds no triad
    with pytest.raises(HarmonyError, match="mode 5: none of"):
        ChordGraph(table, CONFIG.graph, CONFIG.palette)


def harmonizer(moves=None, seed=0):
    config = CONFIG
    if moves is not None:
        config = dataclasses.replace(CONFIG, centers=dataclasses.replace(CONFIG.centers, moves=moves))
    return Harmonizer(config, GRAPH, VOICER, random.Random(seed))


def test_a_mode_section_starts_on_the_previous_tonic():
    center, event = harmonizer().mode_center(Center(E, "minor"), CONFIG.sections["B"])
    assert center.tonic == E and center.mode in ("mode 2", "mode 3")
    assert event == f"section: E {center.mode}"


def test_the_first_mode_section_draws_its_first_degree():
    center, event = harmonizer().mode_center(None, CONFIG.sections["B"])
    assert event.startswith("start: ") and center.mode in ("mode 2", "mode 3")


def test_a_mode_section_draws_a_new_first_degree_when_the_previous_tonic_wont_fit():
    h = harmonizer()
    center, event = h.mode_center(Center(G_SHARP, "minor"), dataclasses.replace(CONFIG.sections["B"], region=LOW))
    assert event == f"new center {GRAPH.name(center)}: no mode on the previous tonic fits frets 0-3"
    assert h._tonic_playable(center, LOW)


def test_a_mode_section_fails_when_no_first_degree_fits():
    only_g_sharp = tuple(1 if pc == G_SHARP else 0 for pc in range(12))
    config = dataclasses.replace(CONFIG, centers=dataclasses.replace(CONFIG.centers, start=only_g_sharp))
    h = Harmonizer(config, GRAPH, VOICER, random.Random(0))
    with pytest.raises(HarmonyError, match="sections.B: no mode has a chord on its first degree playable in frets 0-3"):
        h.mode_center(None, dataclasses.replace(CONFIG.sections["B"], region=LOW))


def test_a_graph_section_draws_a_new_center_when_the_modes_tonic_wont_fit():
    h = harmonizer()
    center, event = h.section_center(Center(G_SHARP, "mode 2"), LOW)
    assert event == f"new center {GRAPH.name(center)}: no mode on the previous tonic fits frets 0-3"
    assert h._tonic_playable(center, LOW)


def test_modulation_keeps_the_mode():
    moves = {"relative": 1, "parallel": 1, "fifth_up": 1}
    for seed in range(5):
        name, center = harmonizer(moves, seed).move(Center(E, "mode 2"), (0, 12), need_tonic=False)
        assert (name, center) == ("fifth_up", Center(11, "mode 2"))
    assert harmonizer({"relative": 1, "parallel": 1}).move(Center(E, "mode 2"), (0, 12), need_tonic=False) is None


@pytest.fixture(scope="module")
def piece():
    return plan_piece(CONFIG, 1, TABLE, VOICER)


def test_mode_section_chords_lie_in_their_mode(piece):
    bars = [bar for bar in piece.bars if piece.sections[bar.section].section.harmony == "mode"]
    assert bars and bars[0].role == "tonic"
    for bar in bars:
        number = int(bar.center.mode.split()[1])
        steps = {(bar.center.tonic + step) % 12 for step in MESSIAEN_MODES[number]}
        assert bar.chord.pitch_classes <= steps, bar.chord.symbol
        assert bar.center.mode == bars[0].center.mode


def test_mode_sections_continue_from_the_previous_section(piece):
    first = {plan.index: next(b for b in piece.bars if b.section == plan.index) for plan in piece.sections}
    last = {plan.index: [b for b in piece.bars if b.section == plan.index][-1] for plan in piece.sections}
    assert [plan.section.harmony for plan in piece.sections] == ["graph", "mode", "graph"]
    assert first[1].center.tonic == last[0].center.tonic
    # The next graph section moves on from the last graph section, not from the mode.
    move = first[2].events[0].split()[1]
    assert first[2].center == MOVES[move](last[0].center)


def test_a_mode_section_continues_from_a_mode_section():
    form = dataclasses.replace(CONFIG.form, rules={"S": (Production("ABB", 1),)})
    bars = plan_piece(dataclasses.replace(CONFIG, form=form), 1, TABLE, VOICER).bars
    a, b, next_b = ([bar for bar in bars if bar.section == i] for i in range(3))
    assert b[-1].center.tonic != a[-1].center.tonic  # M moved the first degree, so the test can tell
    assert next_b[0].center.tonic == b[-1].center.tonic


def test_a_graph_section_keeps_the_tonic_of_a_mode_section_before_it():
    form = dataclasses.replace(CONFIG.form, rules={"S": (Production("BA", 1),)})
    bars = plan_piece(dataclasses.replace(CONFIG, form=form), 5, TABLE, VOICER).bars
    b, a = ([bar for bar in bars if bar.section == i] for i in range(2))
    assert b[-1].center.tonic != b[0].center.tonic  # M moved the first degree, so the test can tell
    assert a[0].center.tonic == b[-1].center.tonic and a[0].center.mode in ("minor", "major")
    assert a[0].events[0] == f"section: {GRAPH.name(a[0].center)}"


def test_inspect_lists_a_modes_chords(capsys):
    assert main(["inspect", "--config", str(PRESET), "--center", "E mode 2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("E mode 2: the [modal] chord types in it")
    assert "\nC#|E " in out


def test_inspect_says_when_no_chord_type_lies_in_a_mode(capsys):
    assert main(["inspect", "--config", str(PRESET), "--center", "E mode 5"]) == 0
    assert capsys.readouterr().out == "E mode 5: none of the [modal] chord types lies in the mode\n"


def test_inspect_needs_a_modal_table_for_a_mode(capsys):
    assert main(["inspect", "--config", str(CONFIGS / "etude1.toml"), "--center", "E mode 2"]) == 2
    assert "needs a [modal] table" in capsys.readouterr().err


def test_inspect_rejects_a_mode_number_messiaen_didnt_write(capsys):
    assert main(["inspect", "--config", str(PRESET), "--center", "E mode 8"]) == 2
    assert "--center" in capsys.readouterr().err
