"""Plain-text reports for `lindenfret inspect`."""

from __future__ import annotations

from lindenfret.alphabet import bar_count
from lindenfret.chords import ChordSpec, ChordTable
from lindenfret.fretboard import Region, Voicer, fret_windows
from lindenfret.harmony import Bar
from lindenfret.pipeline import Piece

WORD_WIDTH = 72


def piece_report(piece: Piece) -> str:
    """The form, each section's derivation, and every bar's center, chord and fingering."""
    lines = [f"seed {piece.seed}", f"form: {' -> '.join(piece.form)}"]
    number = 0
    chord_width = max(11, max(len(_chord(bar)) for bar in piece.bars) + 1)
    fret_width = max(14, max(len(bar.fingering.tab()) for bar in piece.bars) + 2)
    for plan in piece.sections:
        section = plan.section
        low, high = section.length
        tries = "" if plan.attempts == 1 else f", attempt {plan.attempts}"
        lines += [
            "",
            f"section {plan.index + 1}: {section.name}  {section.harmony}, {low}-{high} bars, "
            f"frets {section.region[0]}-{section.region[1]}{tries}",
        ]
        for iteration, word in enumerate(plan.derivation):
            used = "  <- used" if iteration == len(plan.derivation) - 1 else ""
            lines.append(f"  {iteration:>2}  {bar_count(word):>4} bars  {_clip(word)}{used}")
        lines.append(
            f"  {'bar':>4}  {'center':<10}{'chord':<{chord_width}}{'frets 6..1':<{fret_width}}"
            f"{'region':<8}{'role':<10}events"
        )
        for bar in piece.bars:
            if bar.section != plan.index:
                continue
            number += 1
            lines.append(f"  {number:>4}  {_bar_row(piece, bar, chord_width, fret_width)}")
    return "\n".join(lines)


def _chord(bar: Bar) -> str:
    return bar.chord.symbol if bar.chord else f"{bar.shape} shape"


def _bar_row(piece: Piece, bar: Bar, chord_width: int, fret_width: int) -> str:
    center = piece.graph.name(bar.center) if bar.center else "-"
    frets = bar.fingering.tab()
    events = "; ".join(bar.events)
    if bar.note:
        events = f"{events}; {bar.note}" if events else bar.note
    region = f"{bar.region[0]}-{bar.region[1]}"
    return f"{center:<10}{_chord(bar):<{chord_width}}{frets:<{fret_width}}{region:<8}{bar.role:<10}{events}".rstrip()


def fingering_report(voicer: Voicer, spec: ChordSpec, region: Region, top: int) -> str:
    """The best fingerings of one chord in a fret region, by soft score."""
    tones = " ".join(name for _, name in spec.spelling)
    required = " ".join(name for pc, name in spec.spelling if pc in spec.required)
    ranked = voicer.ranked(spec, region)
    lines = [
        f"{spec.symbol}  ({tones}), bass {dict(spec.spelling)[spec.bass]}, "
        f"required {required}, frets {region[0]}-{region[1]}",
    ]
    if not ranked:
        lines.append("no fingering passes the hard rules")
        return "\n".join(lines)
    lines.append(f"{len(ranked)} fingerings pass the hard rules; best {min(top, len(ranked))} by score:")
    best = ranked[:top]
    tab_width = max(16, max(len(f.tab()) for _, f in best) + 2)
    notes = [" ".join(spec.spell(p) for p in f.sounding) for _, f in best]
    notes_width = max(26, max(map(len, notes)) + 2)
    lines.append(f"  {'frets 6..1':<{tab_width}}{'notes':<{notes_width}}span  fingers  shifts  open  score")
    for (s, f), sounding in zip(best, notes):
        lines.append(
            f"  {f.tab():<{tab_width}}{sounding:<{notes_width}}{f.span:>4}  {f.fingers:>7}  "
            f"{f.shifts:>6}  {f.open_strings:>4}  {s.total:>5.2f}"
        )
    return "\n".join(lines)


def center_report(voicer: Voicer, table: ChordTable, mode: str, tonic: int) -> str:
    """How many fingerings each palette chord has at each hand position in one center."""
    windows = fret_windows(voicer.fretboard, voicer.pattern)
    neck = (0, voicer.fretboard.max_fret)
    specs = table.chords[(mode, tonic)]
    width = max(len(s.symbol) for s in specs) + 2
    header = "".join(f"{f'{low}-{high}':>7}" for low, high in windows)
    lines = [
        f"{table.center_name(mode, tonic)}: the {mode} palette transposed from {table.written_in}",
        "fingerings that pass the hard rules, per fret window:",
        f"{'chord':<{width}}{header}",
    ]
    unplayable = []
    for spec in specs:
        counts = [len(voicer.fingerings(spec, region)) for region in windows]
        if not voicer.playable(spec, neck):
            unplayable.append(spec.symbol)
        lines.append(f"{spec.symbol:<{width}}" + "".join(f"{c if c else '.':>7}" for c in counts))
    if unplayable:
        lines.append(f"no fingering anywhere: {', '.join(unplayable)}")
    return "\n".join(lines)


def unplayable_chords(voicer: Voicer, table: ChordTable) -> list[str]:
    """Palette chords, in any center, with no fingering anywhere on the neck."""
    neck = (0, voicer.fretboard.max_fret)
    return [
        f"{spec.symbol} in {table.center_name(mode, tonic)}"
        for (mode, tonic), specs in table.chords.items()
        for spec in specs
        if not voicer.playable(spec, neck)
    ]


def _clip(word: str) -> str:
    return word if len(word) <= WORD_WIDTH else word[: WORD_WIDTH - 1] + "…"
