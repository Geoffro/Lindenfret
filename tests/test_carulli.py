"""The Carulli-style preset end to end: p i m p i m in 6/8, the bass moving between strings."""

from pathlib import Path

import mido
import pytest
from music21 import tempo

from lindenfret.chords import parse_chord
from lindenfret.config import load_config
from lindenfret.export import write_midi
from lindenfret.fretboard import Voicer
from lindenfret.pipeline import chord_table, plan_piece
from lindenfret.render import render_piece
from lindenfret.report import unplayable_chords
from lindenfret.score import build_score

CONFIG = load_config(Path(__file__).resolve().parent.parent / "configs" / "carulli1.toml")
TABLE = chord_table(CONFIG)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern, CONFIG.voicer)


@pytest.fixture(scope="module")
def pieces():
    return [plan_piece(CONFIG, seed, TABLE, VOICER) for seed in range(8)]


def bass_string(fingering):
    return next(len(fingering.frets) - i for i, fret in enumerate(fingering.frets) if fret is not None)


def test_every_palette_chord_is_playable_in_every_center():
    assert unplayable_chords(VOICER, TABLE) == []


def test_the_palette_has_no_plain_triads_or_sevenths():
    plain = [{0, 4}, {0, 3}, {0, 4, 10}, {0, 4, 11}, {0, 3, 10}]  # above the root, leaving out the fifth
    for figure in (*CONFIG.palette.minor, *CONFIG.palette.major):
        spec = parse_chord(figure)
        assert {(pc - spec.root) % 12 for pc in spec.pitch_classes} - {7} not in plain, figure


def test_every_bar_passes_the_independent_check(pieces):
    for piece in pieces:
        for bar in piece.bars:
            assert VOICER.check(bar.fingering, bar.chord, bar.region) == [], (piece.seed, bar.chord.symbol)


def test_the_bass_moves_between_strings(pieces):
    assert {bass_string(bar.fingering) for piece in pieces for bar in piece.bars} == {6, 5, 4}


def test_every_bar_plays_once_the_bass_then_the_upper_strings(pieces):
    for piece in pieces:
        measures = render_piece(piece, CONFIG).measures
        assert [m.bar for m in measures] == list(piece.bars)
        for m in measures:
            assert [n.string for n in m.notes] == [bass_string(m.bar.fingering), 2, 1, 3, 2, 1]
            assert m.notes[0].midi == min(n.midi for n in m.notes)
            assert m.notes[0].midi % 12 == m.bar.chord.bass


def test_every_graph_section_ends_on_a_cadence(pieces):
    for piece in pieces:
        for plan in piece.sections:
            if plan.section.harmony != "graph":
                continue
            roles = [bar.role for bar in piece.bars if bar.section == plan.index]
            assert roles[-2:] == ["dominant", "tonic"], (piece.seed, plan.index)


def test_six_eight_is_beamed_in_threes(pieces):
    score = build_score(render_piece(pieces[0], CONFIG), CONFIG, "test")
    for measure in score.parts[0].getElementsByClass("Measure"):
        assert [n.beams.getTypes() for n in measure.notes] == [["start"], ["continue"], ["stop"]] * 2


def test_six_eight_counts_the_dotted_quarter(pieces, tmp_path):
    rendering = render_piece(pieces[0], CONFIG)
    mark = build_score(rendering, CONFIG, "test").recurse().getElementsByClass(tempo.MetronomeMark).first()
    assert (mark.number, mark.referent.quarterLength) == (64, 1.5)  # tempo = 96 quarter notes
    write_midi(rendering, CONFIG, tmp_path / "piece.mid")
    signature = next(m for m in mido.MidiFile(tmp_path / "piece.mid").tracks[0] if m.type == "time_signature")
    assert (signature.numerator, signature.denominator, signature.clocks_per_click) == (6, 8, 36)
