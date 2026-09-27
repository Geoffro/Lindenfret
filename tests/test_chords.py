from pathlib import Path

import pytest

from lindenfret.chords import ChordError, build_chord_table, parse_chord
from lindenfret.config import MODES, load_config

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
