"""Plan a whole piece from a config and a seed: form, sections, harmony, fingerings.

Each stage draws from its own random stream: "form", "section.<n>",
"harmony", "voicer", and "planing.<n>" for each planing section.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from etudegen.chords import ChordTable, build_chord_table
from etudegen.config import Config, ConfigError
from etudegen.fretboard import Voicer
from etudegen.harmony import Bar, Center, ChordGraph, Harmonizer
from etudegen.interpret import SectionPlan, plan_section
from etudegen.lsystem import derive
from etudegen.planing import plane
from etudegen.rng import stage_rng


@dataclass(frozen=True)
class Piece:
    seed: int
    form: tuple[str, ...]  # the form derivation, axiom first
    sections: tuple[SectionPlan, ...]
    bars: tuple[Bar, ...]  # generated bars, before bar repetition
    graph: ChordGraph


def derive_form(config: Config, seed: int) -> tuple[str, ...]:
    words = derive(config.form.axiom, config.form.rules, config.form.iterations, stage_rng(seed, "form"))
    leftover = sorted({s for s in words[-1] if s not in config.sections})
    if leftover:
        raise ConfigError(
            f"form: after {config.form.iterations} iterations the form still contains "
            f"{', '.join(leftover)}, which aren't sections; raise form.iterations"
        )
    return tuple(words)


def plan_piece(
    config: Config, seed: int, table: ChordTable | None = None, voicer: Voicer | None = None
) -> Piece:
    table = table or build_chord_table(config.palette)
    voicer = voicer or Voicer(config.fretboard, config.pattern.strings, config.voicer)
    graph = ChordGraph(table, config.graph, config.palette)
    form = derive_form(config, seed)
    sections = tuple(
        plan_section(index, config.sections[name], stage_rng(seed, f"section.{index}"))
        for index, name in enumerate(form[-1])
    )

    harmonizer = Harmonizer(config, graph, voicer, stage_rng(seed, "harmony"))
    bars: list[Bar] = []
    center: Center | None = None
    for plan in sections:
        if plan.section.harmony == "planing":
            bars += harmonizer.planing(plan)
        else:
            center, event = harmonizer.section_center(center, plan.section.region)
            section_bars, center = harmonizer.walk(plan, center, event)
            bars += section_bars

    voicer_rng = stage_rng(seed, "voicer")
    voiced: list[Bar] = []
    previous = None
    for plan in sections:
        section_bars = [b for b in bars if b.section == plan.index]
        if plan.section.harmony == "planing":
            planed = plane(section_bars, plan.section, config, stage_rng(seed, f"planing.{plan.index}"))
            voiced += planed
            previous = planed[-1].fingering if planed else previous
            continue
        for bar in section_bars:
            avoid = previous if bar.role == "hold" else None
            fingering = voicer.choose(bar.chord, bar.region, previous, voicer_rng, avoid=avoid)
            voiced.append(replace(bar, fingering=fingering))
            previous = fingering
    return Piece(seed, form, sections, tuple(voiced), graph)
