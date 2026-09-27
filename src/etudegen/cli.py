"""Command-line interface: generate, batch, regenerate and inspect."""

from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

from etudegen.chords import build_chord_table, parse_chord
from etudegen.config import ConfigError, load_config, parse_config_text, parse_region, pitch_class
from etudegen.export import MIDI_FILE, generate, read_manifest
from etudegen.fretboard import Voicer
from etudegen.harmony import HarmonyError
from etudegen.pipeline import plan_piece
from etudegen.report import center_report, fingering_report, piece_report

_CENTER_RE = re.compile(r"^([A-G][#b]?)(m?)$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="etudegen", description="Generate Etude 1 variants.")
    commands = parser.add_subparsers(dest="command", required=True)

    gen = commands.add_parser("generate", help="write one piece: MIDI, MusicXML and a manifest")
    gen.add_argument("--config", type=Path, required=True, help="preset TOML file")
    gen.add_argument("--seed", type=int, help="piece seed; random if omitted")
    gen.add_argument("--out", type=Path, default=Path("out"), help="output folder (default: out)")

    batch = commands.add_parser("batch", help="write several pieces")
    batch.add_argument("--config", type=Path, required=True, help="preset TOML file")
    batch.add_argument("--count", type=int, required=True, help="how many pieces")
    batch.add_argument("--first-seed", type=int, help="use consecutive seeds from here; random if omitted")
    batch.add_argument("--out", type=Path, default=Path("out"), help="output folder (default: out)")

    regen = commands.add_parser("regenerate", help="rebuild a piece from its manifest")
    regen.add_argument("manifest", type=Path, help="a piece's manifest.json")
    regen.add_argument("--out", type=Path, help="output folder (default: 'regenerated' beside the manifest)")

    inspect = commands.add_parser(
        "inspect", help="print a seed's plan, a chord's fingerings, or a key's playable chords"
    )
    inspect.add_argument("--config", type=Path, required=True, help="preset TOML file")
    inspect.add_argument("--seed", type=int, help="piece seed; random if omitted")
    view = inspect.add_mutually_exclusive_group()
    view.add_argument("--chord", help="list the best fingerings of a chord symbol, e.g. Em7")
    view.add_argument("--center", help="list where each palette chord is playable in a key, e.g. Gm or Bb")
    inspect.add_argument("--region", help="fret range for --chord, e.g. 0-4 (default: the whole neck)")
    inspect.add_argument("--top", type=int, default=10, help="how many fingerings --chord lists")

    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            _generate(args.config, [_seed(args.seed)], args.out)
        elif args.command == "batch":
            first = args.first_seed
            seeds = [first + i for i in range(args.count)] if first is not None else [_seed(None) for _ in range(args.count)]
            _generate(args.config, seeds, args.out)
        elif args.command == "regenerate":
            _regenerate(args.manifest, args.out)
        else:
            _inspect(args)
    except (ConfigError, HarmonyError, OSError) as e:
        print(f"etudegen: {e}", file=sys.stderr)
        return 2
    return 0


def _generate(config_path: Path, seeds: list[int], out: Path) -> None:
    text = config_path.read_text(encoding="utf-8")
    config = parse_config_text(text, str(config_path))
    for seed in seeds:
        written = generate(config, text, config_path.stem, seed, out)
        print(f"seed {seed}: {written.folder} ({len(written.rendering.measures)} bars)")


def _regenerate(manifest_path: Path, out: Path | None) -> None:
    try:
        data = read_manifest(manifest_path)
        text, preset, seed = data["config"], data["preset"], data["seed"]
    except (ValueError, KeyError, TypeError) as e:
        raise ConfigError(f"{manifest_path}: not a piece manifest ({e!r})") from e
    config = parse_config_text(text, f"{manifest_path} config")
    out = out or manifest_path.parent / "regenerated"
    written = generate(config, text, preset, seed, out)
    original = manifest_path.parent / MIDI_FILE
    print(f"seed {seed}: {written.folder}")
    if original.exists():
        same = original.read_bytes() == (written.folder / MIDI_FILE).read_bytes()
        print(f"MIDI identical to the original: {'yes' if same else 'no'}")


def _inspect(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    voicer = Voicer(config.fretboard, config.pattern.strings, config.voicer)
    if args.chord:
        region = (0, config.fretboard.max_fret)
        if args.region:
            region = parse_region(args.region, config.fretboard.max_fret, "--region")
        print(fingering_report(voicer, parse_chord(args.chord), region, args.top))
    elif args.center:
        mode, tonic = _parse_center(args.center)
        print(center_report(voicer, build_chord_table(config.palette), mode, tonic))
    else:
        print(piece_report(plan_piece(config, _seed(args.seed), voicer=voicer)))


def _seed(seed: int | None) -> int:
    return seed if seed is not None else secrets.randbelow(2**31)


def _parse_center(text: str) -> tuple[str, int]:
    match = _CENTER_RE.match(text)
    if not match:
        raise ConfigError(f"--center: expected a key like 'Gm' (minor) or 'Bb' (major), got {text!r}")
    return ("minor" if match[2] else "major"), pitch_class(match[1])


if __name__ == "__main__":
    sys.exit(main())
