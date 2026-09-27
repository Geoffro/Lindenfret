"""The facts in docs/design.md's reference sections, checked against the MIDI."""

import pytest


@pytest.fixture(scope="module")
def etude1(etude1_facts):
    return etude1_facts[0]


@pytest.fixture(scope="module")
def etude2(etude2_facts):
    return etude2_facts[0]


# --- Etude 1 ----------------------------------------------------------------


def test_etude1_meter_and_length(etude1):
    assert etude1.bar_count == 62
    assert etude1.time_signatures == [(1, "4/4")]
    assert etude1.key_signatures == [(1, "Em")]


def test_etude1_rhythm(etude1):
    assert etude1.arpeggio_bars == list(range(1, 60))
    assert etude1.off_grid_bars == [60, 61, 62]


def test_etude1_pattern_fits_all_but_the_special_bars(etude1):
    assert len(etude1.matching_bars) == 54
    assert set(etude1.mismatches) == {45, 46, 56, 58, 59}


def test_etude1_each_bar_is_played_twice(etude1):
    pairs = list(range(1, 44, 2)) + list(range(47, 54, 2))
    assert set(pairs) <= set(etude1.repeated_bars)


def test_etude1_left_hand(etude1):
    assert etude1.max_fret == 12
    assert etude1.max_span == 3
    assert etude1.open_low_starts == 34


def test_etude1_planing_passage(etude1):
    # Bars 23-44: strings 5, 4, 3, 2 at b+1, b+2, b, b+2 with b falling 10..0, strings 6 and 1 open.
    for pair, base in enumerate(range(10, -1, -1)):
        for bar in (23 + 2 * pair, 24 + 2 * pair):
            assert etude1.frets[bar] == (0, base + 1, base + 2, base, base + 2, 0)


def test_etude1_accents_match_the_preset(etude1_facts):
    facts, config = etude1_facts
    assert facts.velocities == list(config.pattern.velocities)


def test_etude1_tempo(etude1):
    assert (1, 126) in etude1.tempos
    assert (24, 120) in etude1.tempos


# --- Etude 2 ----------------------------------------------------------------


def test_etude2_meter_and_length(etude2):
    assert etude2.bar_count == 49
    assert etude2.time_signatures == [(1, "4/4")]
    assert etude2.key_signatures == [(1, "A")]
    assert (1, 126) in etude2.tempos


def test_etude2_rhythm(etude2):
    assert etude2.arpeggio_bars == list(range(1, 48))
    assert etude2.off_grid_bars == [48, 49]


def test_etude2_contour_fits_all_but_the_special_bars(etude2):
    assert len(etude2.matching_bars) == 42
    assert set(etude2.mismatches) == {7, 8, 19, 20, 21}
    assert all(len(ladder) == 9 for ladder in etude2.ladders.values())


def test_etude2_each_bar_is_played_twice(etude2):
    pairs = list(range(1, 18, 2)) + list(range(22, 47, 2))
    assert etude2.repeated_bars == pairs


def test_etude2_accents_match_the_preset(etude2_facts):
    facts, config = etude2_facts
    assert facts.velocities == list(config.pattern.velocities)


def test_etude2_left_hand(reference_tool, etude2_facts):
    facts, config = etude2_facts
    assert max(max(ladder) for ladder in facts.ladders.values()) == config.fretboard.open_midi[-1] + 16  # G#5
    need_slide = set()
    for bar, ladder in sorted(facts.ladders.items()):
        found = reference_tool.ladder_fingerings(ladder, config.fretboard, config.pattern)
        assert found, bar
        if min(f.shifts for f in found):
            need_slide.add(bar)
    # 24 bars need the slide; the other 18 fit in one position.
    assert need_slide == {1, 2, *range(9, 17), *range(22, 28), 30, 31, 40, 41, *range(44, 48)}
