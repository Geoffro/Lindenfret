"""The Etude 2 preset end to end: a contour pattern over ladders, a palette written in A."""

import json
from pathlib import Path

import pytest
from music21 import converter, expressions

from lindenfret.chords import build_chord_table
from lindenfret.cli import main
from lindenfret.config import parse_config_text
from lindenfret.export import generate
from lindenfret.fretboard import Voicer
from lindenfret.harmony import ChordGraph
from lindenfret.pipeline import plan_piece
from lindenfret.render import render_piece
from lindenfret.report import unplayable_chords

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude2.toml"
TEXT = PRESET.read_text(encoding="utf-8")
CONFIG = parse_config_text(TEXT)
TABLE = build_chord_table(CONFIG.palette)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern, CONFIG.voicer)
A = 9


@pytest.fixture(scope="module")
def pieces():
    return [plan_piece(CONFIG, seed, TABLE, VOICER) for seed in range(8)]


def test_the_palette_is_written_in_A():
    assert [s.symbol for s in TABLE.chords[("major", A)]] == list(CONFIG.palette.major)
    assert TABLE.written_in == "A"
    graph = ChordGraph(TABLE, CONFIG.graph, CONFIG.palette)
    major = CONFIG.palette.major
    assert {major[i] for i in graph.tonics["major"]} == {"A", "AM9/G#"}
    assert {major[i] for i in graph.dominants["major"]} == {"E7/B", "E9/B", "E/B", "E9"}


def test_every_ladder_passes_the_independent_check(pieces):
    for piece in pieces:
        for bar in piece.bars:
            assert VOICER.check(bar.fingering, bar.chord, bar.region) == [], (piece.seed, bar.fingering.tab())


def test_sections_start_on_the_tonic_and_dominants_resolve(pieces):
    for piece in pieces:
        firsts = {}
        for bar in piece.bars:
            firsts.setdefault(bar.section, bar)
        assert all(bar.role == "tonic" or bar.note for bar in firsts.values())
        for bar, following in zip(piece.bars, piece.bars[1:]):
            if bar.role == "dominant":
                assert following.role == "tonic" or following.note


def test_every_measure_plays_the_contour_over_its_ladder(pieces):
    rendering = render_piece(pieces[0], CONFIG)
    for m in rendering.measures:
        assert [n.midi for n in m.notes] == [m.bar.fingering.pitches[i] for i in CONFIG.pattern.contour]
        assert [n.velocity for n in m.notes] == list(CONFIG.pattern.velocities)
        assert all(n.duration > 0 for n in m.notes)


def test_export_uses_the_presets_notation_and_records_ladders(tmp_path):
    written = generate(CONFIG, TEXT, "etude2", 3, tmp_path)
    score = converter.parse(written.folder / "piece.musicxml")
    assert score.metadata.bestTitle == "Etude 2 variant, seed 3"
    words = [e.content for e in score.recurse().getElementsByClass(expressions.TextExpression)]
    assert words[0] == "let ring"
    notes = [n.pitch.midi for n in score.recurse().notes]
    assert notes == [n.midi for n in written.rendering.notes]
    manifest = json.loads((written.folder / "manifest.json").read_text())
    assert all(isinstance(frets, list) for bar in manifest["bars"] for frets in bar["frets"])


def test_inspect_lists_ladders_with_their_shifts(capsys):
    assert main(["inspect", "--config", str(PRESET), "--chord", "A", "--region", "0-12", "--top", "3"]) == 0
    out = capsys.readouterr().out
    assert "shifts" in out and "5 4-7 7 6-9 10 9-12" in out  # the reference's bar 1


def test_inspect_seed_lists_each_bars_ladder(capsys, pieces):
    assert main(["inspect", "--config", str(PRESET), "--seed", "1"]) == 0
    out = capsys.readouterr().out
    assert all(bar.fingering.tab() in out for bar in pieces[1].bars)


def test_inspect_center_windows_cover_the_hands_reach(capsys):
    assert main(["inspect", "--config", str(PRESET), "--center", "A"]) == 0
    out = capsys.readouterr().out
    # E/B, as in the reference's bars 13-14, reaches past 8 frets: two hand positions plus the slide.
    row = next(line for line in out.splitlines() if line.startswith("E/B "))
    assert "0-11" in out and set(row.split()[1:]) != {"."}


def test_every_palette_chord_is_playable_somewhere():
    # Nine stops of a triad span nearly three octaves: above a D, E-flat or
    # C-sharp bass they run past fret 17. The harmony stage routes around them;
    # any new entry here is a regression.
    assert unplayable_chords(VOICER, TABLE) == [
        "G/D in C minor", "Gm/D in C minor", "G#/D# in C# minor", "G#m/D# in C# minor", "Gm/D in D minor",
        "Ebm in Eb minor", "Abm/Eb in Eb minor", "F#/C# in B minor", "G/D in C major", "Gm/D in C major",
        "Ab/Eb in Db major", "Abm/Eb in Db major", "Eb in Eb major", "Ebm in Eb major", "F#/C# in B major",
    ]
