"""The facts in docs/design.md's reference section, checked against the MIDI."""

import importlib.util
import sys
from pathlib import Path

import pytest

from lindenfret.config import load_config

ROOT = Path(__file__).resolve().parent.parent


def load_tool():
    spec = importlib.util.spec_from_file_location("analyze_reference", ROOT / "tools" / "analyze_reference.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def facts():
    tool = load_tool()
    config = load_config(ROOT / "configs" / "etude1.toml")
    return tool.analyze(
        tool.DEFAULT_MIDI, config.pattern.strings, config.pattern.note_quarters, config.fretboard.open_midi
    )


def test_meter_and_length(facts):
    assert facts.bar_count == 62
    assert facts.time_signatures == [(1, "4/4")]
    assert facts.key_signatures == [(1, "Em")]


def test_rhythm(facts):
    assert facts.arpeggio_bars == list(range(1, 60))
    assert facts.off_grid_bars == [60, 61, 62]


def test_pattern_fits_all_but_the_special_bars(facts):
    assert len(facts.matching_bars) == 54
    assert set(facts.mismatches) == {45, 46, 56, 58, 59}


def test_each_bar_is_played_twice(facts):
    pairs = list(range(1, 44, 2)) + list(range(47, 54, 2))
    assert set(pairs) <= set(facts.repeated_bars)


def test_left_hand(facts):
    assert facts.max_fret == 12
    assert facts.max_span == 3
    assert facts.open_low_starts == 34


def test_planing_passage(facts):
    # Bars 23-44: strings 5, 4, 3, 2 at b+1, b+2, b, b+2 with b falling 10..0, strings 6 and 1 open.
    for pair, base in enumerate(range(10, -1, -1)):
        for bar in (23 + 2 * pair, 24 + 2 * pair):
            assert facts.frets[bar] == (0, base + 1, base + 2, base, base + 2, 0)


def test_tempo(facts):
    assert (1, 126) in facts.tempos
    assert (24, 120) in facts.tempos
