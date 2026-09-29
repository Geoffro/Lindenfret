from pathlib import Path

import pytest

from lindenfret.chords import build_chord_table, parse_chord
from lindenfret.config import Meter, load_config
from lindenfret.fretboard import Fingering, Voicer
from lindenfret.pipeline import plan_piece
from lindenfret.render import render_bar, render_piece, ritardando

ROOT = Path(__file__).resolve().parent.parent
CONFIG = load_config(ROOT / "configs" / "etude1.toml")
TABLE = build_chord_table(CONFIG.palette)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern, CONFIG.voicer)
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


def test_ritardando_over_each_sections_last_bar_and_its_repeat(rendering):
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


@pytest.mark.parametrize(
    "time_signature, repeats, onsets",
    [
        ("4/4", 2, [0, 1, 2, 3, 4, 5, 6, 7]),
        ("2/2", 1, [0, 1, 2, 3]),
        ("3/8", 1, [0, 0.5, 1]),
        ("5/8", 1, [0, 0.5, 1, 1.5, 2]),
        ("6/8", 1, [0, 0.5, 1, 1.5, 2, 2.5]),
    ],
)
def test_a_ritardando_slows_through_the_whole_bar(time_signature, repeats, onsets):
    beats, unit = map(int, time_signature.split("/"))
    ramp = ritardando(10.0, Meter(beats, unit, 100.0, repeats, 0.2))
    assert [onset - 10.0 for onset, _ in ramp] == onsets
    bpms = [bpm for _, bpm in ramp]
    assert bpms == sorted(bpms, reverse=True) and bpms[0] < 100 and bpms[-1] == pytest.approx(80)


@pytest.mark.parametrize(
    "symbol, frets, bass", [("E7/G#", (4, None, None, 4, 3, 0), 6), ("Am", (None, 0, None, 2, 1, 0), 5)]
)
def test_a_bass_note_plays_on_the_fingerings_bass_string(symbol, frets, bass):
    config = load_config(ROOT / "configs" / "carulli1.toml")  # 6/8: the bass, then strings 2 1 3 2 1 in 8ths
    fingering = Fingering.from_frets(frets, config.fretboard)
    notes = render_bar(fingering, parse_chord(symbol), config.pattern, 0.0, config.meter.bar_quarters)
    assert [n.string for n in notes] == [bass, 2, 1, 3, 2, 1]
    assert [n.duration for n in notes] == [3.0, 1.5, 1.5, 1.5, 1.0, 0.5]  # each rings until plucked again


def test_the_references_fingerings_render_to_the_reference(etude1_facts):
    facts, _ = etude1_facts
    for bar in range(1, 45):
        fingering = Fingering.from_frets(facts.frets[bar], CONFIG.fretboard)
        notes = render_bar(fingering, None, CONFIG.pattern, 0.0, BAR)
        assert [frozenset({n.midi}) for n in notes] == facts.bar_pitches[bar], bar


def test_etude2_ladders_render_to_the_reference(reference_tool, etude2_facts):
    facts, config = etude2_facts
    for bar in facts.matching_bars[::2]:
        ladder = reference_tool.ladder_fingerings(facts.ladders[bar], config.fretboard, config.pattern)[0]
        notes = render_bar(ladder, None, config.pattern, 0.0, BAR)
        assert [frozenset({n.midi}) for n in notes] == facts.bar_pitches[bar], bar
