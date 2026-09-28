from pathlib import Path

import pytest

from lindenfret.chords import ChordError, build_chord_table, parse_chord
from lindenfret.config import MODES, Palette, load_config

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"
E, F_SHARP, G, A, B, C, C_SHARP, D_SHARP = 4, 6, 7, 9, 11, 0, 1, 3


@pytest.fixture(scope="module")
def table():
    return build_chord_table(load_config(PRESET).palette)


def test_triad_leaves_the_fifth_optional():
    em = parse_chord("Em")
    assert em.pitch_classes == {E, G, B}
    assert em.required == {E, G}
    assert em.root == em.bass == E


def test_slash_chord_requires_its_bass():
    em_over_b = parse_chord("Em/B")
    assert em_over_b.bass == B
    assert em_over_b.required == {E, G, B}  # the fifth is required when it's the bass


def test_optional_intervals_choose_the_tones_a_voicing_may_leave_out():
    assert parse_chord("Em", optional=()).required == {E, G, B}
    assert parse_chord("E7", optional=(7, 10)).required == {E, 8}


def test_a_palette_transposes_the_same_from_any_tonic():
    in_e = build_chord_table(Palette("E", frozenset({7}), ("Em", "F#m7b5/E", "B7/F#"), ("E", "A/E")))
    in_b_flat = build_chord_table(Palette("Bb", frozenset({7}), ("Bbm", "Cm7b5/Bb", "F7/C"), ("Bb", "Eb/Bb")))
    assert in_b_flat.written_in == "Bb"
    assert in_b_flat.chords == in_e.chords
    assert in_b_flat.tonic_names == in_e.tonic_names


def test_polychord_stacks_its_parts_over_the_lower_chords_root():
    d_over_c = parse_chord("D|C")
    assert d_over_c.kind == "major|major"
    assert d_over_c.root == d_over_c.bass == C
    assert d_over_c.pitch_classes == {C, 2, E, F_SHARP, G, A}
    assert d_over_c.required == {C, 2, E, F_SHARP, A}  # only the lower chord leaves out its fifth


def test_polychord_requires_its_whole_upper_chord():
    assert parse_chord("G|E").required == {E, G, 8, B, 2}  # D is G's fifth but E's seventh
    assert parse_chord("G|C").required == {C, 2, E, G, B}  # G is C's fifth but G's root


def test_polychord_parts_share_the_lower_chords_spelling():
    assert dict(parse_chord("Ab|E").spelling)[8] == "G#"


def test_polychords_transpose_part_by_part():
    table = build_chord_table(Palette("E", frozenset({7}), ("Em", "D|B"), ("E", "F#|E")))
    assert [s.symbol for s in table.chords[("major", 5)]] == ["F", "G|F"]
    assert [s.symbol for s in table.chords[("minor", 2)]] == ["Dm", "C|A"]


def test_polychord_takes_the_lower_chords_slash_bass():
    d_over_c_over_e = parse_chord("D|C/E")
    assert (d_over_c_over_e.root, d_over_c_over_e.bass) == (C, E)
    table = build_chord_table(Palette("E", frozenset({7}), ("Em",), ("E", "D|C/E")))
    assert table.chords[("major", 5)][1].symbol == "Eb|Db/F"


@pytest.mark.parametrize("figure", ["D|C|E", "D|H", "|C"])
def test_bad_polychords_raise(figure):
    with pytest.raises(ChordError):
        parse_chord(figure)


def test_half_diminished_requires_its_flat_fifth():
    chord = parse_chord("F#m7b5/E")
    assert chord.pitch_classes == {F_SHARP, A, C, E}
    assert chord.required == {F_SHARP, A, C, E}


def test_sixth_chord():
    assert parse_chord("E6").pitch_classes == {E, 8, B, C_SHARP}


def test_spell_uses_the_chord_spelling():
    gm = parse_chord("Gm")
    assert gm.spell(58) == "Bb3"
    assert parse_chord("C#m").spell(56) == "G#3"
    assert parse_chord("Abm").spell(59) == "Cb4"  # Cb4 is MIDI 59, spelled in octave 4


def test_flat_roots_and_basses():
    # music21 itself reads "Bb7" as B7; the parser must not.
    b_flat_7 = parse_chord("Bb7")
    assert b_flat_7.root == 10
    assert b_flat_7.pitch_classes == {10, 2, 5, 8}
    assert parse_chord("Ebm").pitch_classes == {3, 6, 10}
    assert parse_chord("Cm/Eb").bass == 3


def test_bad_symbols_raise():
    with pytest.raises(ChordError):
        parse_chord("Hm7")


def test_every_center_has_the_whole_palette(table):
    palette = load_config(PRESET).palette
    for mode in MODES:
        for tonic in range(12):
            assert len(table.chords[(mode, tonic)]) == len(getattr(palette, mode))


def test_transposition_keeps_quality_and_bass(table):
    for mode in MODES:
        originals = table.chords[(mode, E)]
        for tonic in range(12):
            shift = (tonic - E) % 12
            for original, moved in zip(originals, table.chords[(mode, tonic)]):
                assert moved.kind == original.kind
                assert moved.root == (original.root + shift) % 12
                assert moved.bass == (original.bass + shift) % 12
                assert moved.pitch_classes == {(pc + shift) % 12 for pc in original.pitch_classes}


def test_no_double_sharps_or_flats(table):
    for specs in table.chords.values():
        for spec in specs:
            for _, name in spec.spelling:
                assert name.count("#") < 2 and name.count("b") < 2, spec.symbol


def test_centers_use_the_simpler_key_signature(table):
    assert table.center_name("major", 1) == "Db major"
    assert table.center_name("minor", 1) == "C# minor"
    assert table.center_name("minor", 8) == "G# minor"
    assert table.center_name("major", 6) == "F# major"
    assert table.center_name("minor", D_SHARP) == "Eb minor"  # D# minor would need F## in D#/F##


def test_transposed_chords_are_spelled_from_the_chord(table):
    g_minor = table.chords[("minor", G)]
    assert g_minor[0].symbol == "Gm"
    assert dict(g_minor[0].spelling)[10] == "Bb"
