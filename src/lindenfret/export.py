"""Write a generated piece: MIDI, MusicXML and a manifest that regenerates it.

MIDI is written with mido, one channel per string, so notes held on two
strings at the same pitch never cut each other off. The manifest carries
the seed and the full config text, so `regenerate` rebuilds the same piece.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import mido

from lindenfret import __version__
from lindenfret.config import Config
from lindenfret.pipeline import Piece, plan_piece
from lindenfret.render import Rendering, render_piece
from lindenfret.score import build_score

TICKS_PER_QUARTER = 480
GUITAR_PROGRAM = 24  # General MIDI "Acoustic Guitar (nylon)", numbered from 0
MIDI_FILE, MUSICXML_FILE, MANIFEST_FILE = "piece.mid", "piece.musicxml", "manifest.json"


@dataclass(frozen=True)
class Written:
    folder: Path
    piece: Piece
    rendering: Rendering


def generate(config: Config, config_text: str, name: str, seed: int, out: Path) -> Written:
    """Plan, render and write one piece to `out/<name>-<seed>/`."""
    piece = plan_piece(config, seed)
    rendering = render_piece(piece, config)
    folder = out / f"{name}-{seed}"
    folder.mkdir(parents=True, exist_ok=True)
    write_midi(rendering, config, folder / MIDI_FILE)
    build_score(rendering, config, f"Etude 1 variant, seed {seed}").write(
        "musicxml", fp=str(folder / MUSICXML_FILE)
    )
    (folder / MANIFEST_FILE).write_text(
        json.dumps(manifest(piece, config_text, name), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return Written(folder, piece, rendering)


def write_midi(rendering: Rendering, config: Config, path: Path) -> None:
    midi = mido.MidiFile(type=1, ticks_per_beat=TICKS_PER_QUARTER)
    conductor = mido.MidiTrack()
    conductor.append(mido.MetaMessage("track_name", name="tempo", time=0))
    conductor.append(
        mido.MetaMessage("time_signature", numerator=config.meter.beats, denominator=config.meter.beat_unit, time=0)
    )
    conductor += _delta(
        [(_ticks(onset), 0, mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm))) for onset, bpm in rendering.tempos]
    )
    midi.tracks.append(conductor)

    strings = config.fretboard.string_count
    for string in range(strings, 0, -1):
        channel = strings - string  # string 6 on channel 0, string 1 on channel 5
        track = mido.MidiTrack()
        track.append(mido.MetaMessage("track_name", name=f"string {string}", time=0))
        track.append(mido.Message("program_change", channel=channel, program=GUITAR_PROGRAM, time=0))
        events = []
        for n in rendering.notes:
            if n.string == string:
                start, end = _ticks(n.onset), _ticks(n.onset + n.duration)
                events.append((start, 1, mido.Message("note_on", channel=channel, note=n.midi, velocity=n.velocity)))
                events.append((end, 0, mido.Message("note_off", channel=channel, note=n.midi, velocity=0)))
        track += _delta(events)
        midi.tracks.append(track)
    midi.save(path)


def manifest(piece: Piece, config_text: str, name: str) -> dict:
    return {
        "generator": f"lindenfret {__version__}",
        "git_commit": _git_commit(),
        "preset": name,
        "seed": piece.seed,
        "config_sha256": config_hash(config_text),
        "config": config_text,
        "form": list(piece.form),
        "sections": [
            {
                "index": plan.index,
                "name": plan.section.name,
                "harmony": plan.section.harmony,
                "derivation": list(plan.derivation),
                "attempts": plan.attempts,
            }
            for plan in piece.sections
        ],
        "bars": [
            {
                "bar": number,
                "section": bar.section,
                "center": piece.graph.name(bar.center) if bar.center else None,
                "chord": bar.chord.symbol if bar.chord else None,
                "frets": list(bar.fingering.frets),
                "region": list(bar.region),
                "role": bar.role,
                "shape": bar.shape or None,
                "offset": bar.offset,
                "events": list(bar.events),
                "note": bar.note,
            }
            for number, bar in enumerate(piece.bars, start=1)
        ],
    }


def config_hash(config_text: str) -> str:
    """Identifies the exact preset text a piece came from, e.g. in curated.toml."""
    return hashlib.sha256(config_text.encode("utf-8")).hexdigest()


def read_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _ticks(quarters: float) -> int:
    return round(quarters * TICKS_PER_QUARTER)


def _delta(events: list[tuple[int, int, mido.Message]]) -> list[mido.Message]:
    """Absolute-tick events to delta times; at equal ticks, note-offs come first."""
    out, now = [], 0
    for tick, order, message in sorted(events, key=lambda e: (e[0], e[1])):
        out.append(message.copy(time=tick - now))
        now = tick
    return out


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None
