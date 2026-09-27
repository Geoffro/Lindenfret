import importlib.util
import sys
from pathlib import Path

import pytest

from etudegen.chords import build_chord_table
from etudegen.config import load_config
from etudegen.fretboard import Fingering, Voicer
from etudegen.pipeline import plan_piece
from etudegen.render import render_bar, render_piece

ROOT = Path(__file__).resolve().parent.parent
CONFIG = load_config(ROOT / "configs" / "etude1.toml")
TABLE = build_chord_table(CONFIG.palette)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern.strings, CONFIG.voicer)
BAR = CONFIG.meter.bar_quarters


@pytest.fixture(scope="module")
def rendering():
    return render_piece(plan_piece(CONFIG, 2026, TABLE, VOICER), CONFIG)


def test_each_generated_bar_is_played_twice(rendering):
    bars = [m.bar for m in rendering.measures]
    assert len(bars) == 2 * len({id(b) for b in bars})
    for first, second in zip(rendering.measures[::2], rendering.measures[1::2]):
        assert first.bar is second.bar
        assert [n.midi for n in first.notes] == [n.midi for n in second.notes]


def test_every_measure_plays_the_pattern(rendering):
    for m in rendering.measures:
        assert [n.string for n in m.notes] == list(CONFIG.pattern.strings)
        assert [n.onset - m.start for n in m.notes] == [k * 0.25 for k in range(16)]
        assert [n.velocity for n in m.notes] == list(CONFIG.pattern.velocities)


def test_notes_are_held_to_the_next_pluck_or_the_bar_line(rendering):
    for m in rendering.measures:
        for i, n in enumerate(m.notes):
            end = n.onset + n.duration
            later = [x for x in m.notes[i + 1 :] if x.string == n.string]
            assert end == (later[0].onset if later else m.start + BAR)


def test_planing_bars_play_the_pattern_over_their_shape(rendering):
    planing = [m for m in rendering.measures if m.bar.role == "planing"]
    assert planing and all(len(m.notes) == len(CONFIG.pattern.strings) for m in planing)


def test_ritardando_over_each_sections_last_bar_pair(rendering):
    tempo = CONFIG.meter.tempo
    rits = [m for m in rendering.measures if "rit." in m.marks]
    assert len(rits) == len({m.bar.section for m in rendering.measures})
    for m in rits:
        ramp = [bpm for onset, bpm in rendering.tempos if m.start <= onset < m.start + 2 * BAR]
        assert ramp == sorted(ramp, reverse=True)
        assert ramp[-1] == pytest.approx(tempo * (1 - CONFIG.meter.ritardando))
    for m in rendering.measures:
        if "a tempo" in m.marks:
            assert (m.start, tempo) in rendering.tempos


def load_tool():
    spec = importlib.util.spec_from_file_location("analyze_reference", ROOT / "tools" / "analyze_reference.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_references_fingerings_render_to_the_reference():
    tool = load_tool()
    facts = tool.analyze(
        tool.DEFAULT_MIDI, CONFIG.pattern.strings, CONFIG.pattern.note_quarters, CONFIG.fretboard.open_midi
    )
    for bar in range(1, 45):
        fingering = Fingering.from_frets(facts.frets[bar], CONFIG.fretboard)
        notes = render_bar(fingering, None, CONFIG.pattern, 0.0, BAR)
        assert [frozenset({n.midi}) for n in notes] == facts.bar_pitches[bar], bar
