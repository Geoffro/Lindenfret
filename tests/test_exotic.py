"""The exotic presets: each base preset's pattern, form and limits, with a wider palette."""

from itertools import takewhile
from pathlib import Path

import pytest

from lindenfret.chords import build_chord_table
from lindenfret.cli import main
from lindenfret.config import load_config
from lindenfret.fretboard import Voicer
from lindenfret.pipeline import plan_piece
from lindenfret.report import piece_report, unplayable_chords

CONFIGS = Path(__file__).resolve().parent.parent / "configs"
PAIRS = [("etude1-exotic", "etude1"), ("etude2-exotic", "etude2")]


def load(name):
    config = load_config(CONFIGS / f"{name}.toml")
    return config, build_chord_table(config.palette), Voicer(config.fretboard, config.pattern, config.voicer)


@pytest.fixture(scope="module", params=PAIRS, ids=[exotic for exotic, _ in PAIRS])
def pair(request):
    exotic, base = request.param
    return load(exotic), load(base)


def test_only_the_harmony_differs_from_the_base(pair):
    (exotic, _, _), (base, _, _) = pair
    for table in ("meter", "pattern", "fretboard", "voicer", "form", "sections"):
        assert getattr(exotic, table) == getattr(base, table), table
    assert (exotic.centers.start, exotic.centers.start_mode) == (base.centers.start, base.centers.start_mode)
    assert (exotic.palette.tonic, exotic.palette.optional_intervals) == (base.palette.tonic, base.palette.optional_intervals)
    assert set(base.palette.minor) < set(exotic.palette.minor)
    assert set(base.palette.major) < set(exotic.palette.major)
    assert exotic.graph.reference_paths == base.graph.reference_paths


def test_every_added_chord_is_playable_in_every_center(pair):
    (_, exotic_table, exotic_voicer), (_, base_table, base_voicer) = pair
    assert unplayable_chords(exotic_voicer, exotic_table) == unplayable_chords(base_voicer, base_table)


@pytest.fixture(scope="module")
def piece(pair):
    (config, table, voicer), _ = pair
    return plan_piece(config, 1, table, voicer)


def test_pieces_use_polychords(piece):
    assert any("|" in bar.chord.symbol for bar in piece.bars if bar.chord)


def test_report_columns_fit_the_longest_chord(piece):  # etude2-exotic seed 1 has Cbmaj7 add #11
    lines = piece_report(piece).splitlines()
    headers = [i for i, line in enumerate(lines) if "frets 6..1" in line]
    chord, frets = lines[headers[0]].index("chord"), lines[headers[0]].index("frets 6..1")
    rows = [row for i in headers for row in takewhile(bool, lines[i + 1 :])]
    for row, bar in zip(rows, piece.bars, strict=True):
        symbol = bar.chord.symbol if bar.chord else f"{bar.shape} shape"
        assert row[chord:frets] == symbol.ljust(frets - chord) and row[frets - 1] == " ", row
        assert row[frets:].startswith(bar.fingering.tab() + "  "), row


def test_inspect_voices_a_polychord(capsys):
    preset = str(CONFIGS / "etude1-exotic.toml")
    assert main(["inspect", "--config", preset, "--chord", "D|C", "--region", "0-9"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("D|C  (C D E F# G A), bass C, required C D E F# A")
    assert "fingerings pass the hard rules" in out
