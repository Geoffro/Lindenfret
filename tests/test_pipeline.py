"""Phase 2's gate, checked over many seeds."""

import dataclasses
from pathlib import Path

import pytest

from lindenfret.chords import build_chord_table
from lindenfret.config import ConfigError, load_config
from lindenfret.fretboard import Voicer, check_fingering
from lindenfret.lsystem import Production
from lindenfret.pipeline import plan_piece

PRESET = Path(__file__).resolve().parent.parent / "configs" / "etude1.toml"
CONFIG = load_config(PRESET)
TABLE = build_chord_table(CONFIG.palette)
VOICER = Voicer(CONFIG.fretboard, CONFIG.pattern.strings, CONFIG.voicer)
SEEDS = range(60)


@pytest.fixture(scope="module")
def pieces():
    return [plan_piece(CONFIG, seed, TABLE, VOICER) for seed in SEEDS]


def summary(piece):
    return [(b.center, b.chord and b.chord.symbol, b.fingering, b.events) for b in piece.bars]


def test_same_seed_same_piece():
    assert summary(plan_piece(CONFIG, 7, TABLE, VOICER)) == summary(plan_piece(CONFIG, 7))


def test_centers_change_only_at_M_brackets_and_section_starts(pieces):
    for piece in pieces:
        previous = None
        for bar in piece.bars:
            starts_section = previous is None or bar.section != previous.section
            if bar.center is not None and starts_section:
                assert bar.events[0].startswith(("start:", "section:", "new center")), bar.events
            elif bar.center is not None and bar.center != previous.center:
                assert any(e.startswith("M ") or e == "]" for e in bar.events), bar.events
            previous = bar


def test_graph_sections_start_on_the_tonic(pieces):
    for piece in pieces:
        firsts = {}
        for bar in piece.bars:
            firsts.setdefault(bar.section, bar)
        for bar in firsts.values():
            if bar.center is not None and not bar.note:
                assert bar.role == "tonic"


def test_every_dominant_resolves_to_a_tonic(pieces):
    for piece in pieces:
        for bar, following in zip(piece.bars, piece.bars[1:]):
            if bar.role == "dominant":
                assert following.role == "tonic" or following.note


def test_every_fingering_passes_the_independent_check(pieces):
    # Planing bars have no chord, so only the physical rules apply to them.
    for piece in pieces:
        for bar in piece.bars:
            assert bar.fingering is not None
            problems = check_fingering(
                bar.fingering, bar.chord, CONFIG.fretboard, CONFIG.pattern.strings, bar.region
            )
            assert problems == [], (piece.seed, bar.role, problems)


def test_sections_have_the_bars_their_derivations_promise(pieces):
    for piece in pieces:
        for plan in piece.sections:
            low, high = plan.section.length
            assert low <= plan.bars <= high
            assert sum(1 for b in piece.bars if b.section == plan.index) == plan.bars


def with_section_a_rule(to):
    section_a = dataclasses.replace(CONFIG.sections["A"], rules={"F": (Production(to, 1),)})
    return dataclasses.replace(CONFIG, sections={**CONFIG.sections, "A": section_a})


def test_changing_one_rule_changes_the_plan():
    changed = with_section_a_rule("FMF")
    before = plan_piece(CONFIG, 3, TABLE, VOICER)
    after = plan_piece(changed, 3, TABLE, VOICER)
    assert [p.word for p in before.sections] != [p.word for p in after.sections]
    assert summary(before) != summary(after)


def test_held_chords_are_revoiced():
    config = with_section_a_rule("FH")
    for seed in range(5):
        bars = plan_piece(config, seed, TABLE, VOICER).bars
        holds = [(a, b) for a, b in zip(bars, bars[1:]) if b.role == "hold"]
        assert holds
        for previous, held in holds:
            assert held.chord == previous.chord
            assert held.fingering != previous.fingering


def test_a_form_that_stops_short_of_its_sections_fails():
    config = dataclasses.replace(CONFIG, form=dataclasses.replace(CONFIG.form, iterations=0))
    with pytest.raises(ConfigError, match="raise form.iterations"):
        plan_piece(config, 0, TABLE, VOICER)
