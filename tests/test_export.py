import json
from pathlib import Path

import mido
import pytest
from music21 import clef, converter, expressions, key

from lindenfret.cli import main
from lindenfret.config import parse_config_text
from lindenfret.export import GUITAR_PROGRAM, generate
from lindenfret.fretboard import Fingering
from lindenfret.render import render_bar
from lindenfret.score import _respell_as_chord

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"
TEXT = PRESET.read_text(encoding="utf-8")
CONFIG = parse_config_text(TEXT)
SEED = 2026


@pytest.fixture(scope="module")
def written(tmp_path_factory):
    return generate(CONFIG, TEXT, "etude1", SEED, tmp_path_factory.mktemp("out"))


@pytest.fixture(scope="module")
def parsed(written):
    return converter.parse(written.folder / "piece.musicxml")


def test_writes_midi_musicxml_and_a_manifest(written):
    assert written.folder.name == f"etude1-{SEED}"
    for name in ("piece.mid", "piece.musicxml", "manifest.json"):
        assert (written.folder / name).stat().st_size > 0


def test_midi_has_one_channel_per_string(written):
    midi = mido.MidiFile(written.folder / "piece.mid")
    assert len(midi.tracks) == 1 + 6
    for track in midi.tracks[1:]:
        channels = {m.channel for m in track if hasattr(m, "channel")}
        programs = {m.program for m in track if m.type == "program_change"}
        assert len(channels) == 1 and programs == {GUITAR_PROGRAM}
    notes = [m for t in midi.tracks for m in t if m.type == "note_on" and m.velocity > 0]
    assert len(notes) == len(written.rendering.notes)


def test_no_note_is_struck_again_while_still_held_on_its_channel(written):
    midi = mido.MidiFile(written.folder / "piece.mid")
    for track in midi.tracks[1:]:
        held = set()
        for m in track:
            if m.type == "note_on" and m.velocity > 0:
                assert m.note not in held
                held.add(m.note)
            elif m.type in ("note_off", "note_on"):
                held.discard(m.note)


def test_midi_tempo_map_follows_the_rendering(written):
    midi = mido.MidiFile(written.folder / "piece.mid")
    tick, tempos = 0, []
    for m in midi.tracks[0]:
        tick += m.time
        if m.type == "set_tempo":
            tempos.append((tick / midi.ticks_per_beat, mido.tempo2bpm(m.tempo)))
    assert [onset for onset, _ in tempos] == [onset for onset, _ in written.rendering.tempos]
    assert [bpm for _, bpm in tempos] == pytest.approx([bpm for _, bpm in written.rendering.tempos], abs=0.01)
    assert min(bpm for _, bpm in tempos) < CONFIG.meter.tempo  # the ritardandos reach the MIDI


def test_regenerate_gives_byte_identical_midi(written, capsys):
    assert main(["regenerate", str(written.folder / "manifest.json")]) == 0
    assert "MIDI identical to the original: yes" in capsys.readouterr().out


def test_musicxml_round_trip(written, parsed):
    measures = parsed.parts[0].getElementsByClass("Measure")
    assert len(measures) == len(written.rendering.measures)
    assert not parsed.recurse().getElementsByClass(key.KeySignature)
    assert isinstance(parsed.recurse().getElementsByClass(clef.Clef).first(), clef.Treble8vbClef)
    beat = [["start"] * 2, ["continue"] * 2, ["continue"] * 2, ["stop"] * 2]  # 16ths beamed by the beat
    for m, rendered in zip(measures, written.rendering.measures):
        notes = list(m.recurse().notes)
        assert [n.pitch.midi for n in notes] == [n.midi for n in rendered.notes]
        assert all(n.quarterLength == 0.25 for n in notes)
        assert [n.beams.getTypes() for n in notes] == beat * 4
    first = [n.nameWithOctave.replace("-", "b") for n in measures[0].recurse().notes]
    assert first == [n.name for n in written.rendering.measures[0].notes]


def test_musicxml_marks_the_hold_and_the_ritardandos(written, parsed):
    words = [e.content for e in parsed.recurse().getElementsByClass(expressions.TextExpression)]
    marks = [mark for m in written.rendering.measures for mark in m.marks]
    assert words == [CONFIG.notation.direction, *marks]
    assert "rit." in marks and "a tempo" in marks


@pytest.mark.parametrize(
    "base, expected",
    [(10, {"G#", "B", "D", "F"}), (9, {"G", "A#", "C#", "E"}), (8, {"F#", "A", "C", "D#"})],
)
def test_planing_bars_are_spelled_as_stacked_thirds(base, expected):
    # The reference's shape: strings 5, 4, 3, 2 at b+1, b+2, b, b+2 over open E strings.
    frets = (0, base + 1, base + 2, base, base + 2, 0)
    notes = render_bar(Fingering.from_frets(frets, CONFIG.fretboard), None, CONFIG.pattern, 0.0, 4.0)
    names = _respell_as_chord(notes)
    fretted = {names[n.midi][:-1].replace("-", "b") for n in notes if n.fret > 0}
    assert fretted == expected


def test_manifest_records_what_regenerates_the_piece(written):
    data = json.loads((written.folder / "manifest.json").read_text())
    assert data["seed"] == SEED
    assert data["config"] == TEXT
    assert len(data["bars"]) == len(written.piece.bars)
    assert data["bars"][0]["role"] == "tonic"


def test_batch_writes_consecutive_seeds(tmp_path, capsys):
    code = main(["batch", "--config", str(PRESET), "--count", "2", "--first-seed", "10", "--out", str(tmp_path)])
    assert code == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["etude1-10", "etude1-11"]
