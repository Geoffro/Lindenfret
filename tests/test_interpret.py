import random

import pytest

from etudegen.config import Section
from etudegen.interpret import LengthError, plan_section
from etudegen.lsystem import Production


def section(rules, length, axiom="F"):
    parsed = {symbol: tuple(Production(to, w) for to, w in options) for symbol, options in rules.items()}
    return Section("A", axiom, parsed, length, "graph", (0, 9), {}, None)


def test_uses_the_first_iteration_in_range():
    plan = plan_section(0, section({"F": [("FF", 1)]}, (4, 8)), random.Random(0))
    assert plan.derivation == ("F", "FF", "FFFF")
    assert plan.attempts == 1
    assert plan.bars == 4


def test_overshoot_starts_a_new_attempt():
    # F doubles or quadruples; only a doubling lands on exactly two bars.
    rules = {"F": [("FF", 1), ("FFFF", 1)]}
    plans = [plan_section(0, section(rules, (2, 2)), random.Random(seed)) for seed in range(20)]
    assert all(p.word == "FF" for p in plans)
    assert any(p.attempts > 1 for p in plans)


def test_a_grammar_that_always_overshoots_fails():
    with pytest.raises(LengthError, match="no derivation landed in 2-2 bars"):
        plan_section(0, section({"F": [("FFF", 1)]}, (2, 2)), random.Random(0))


def test_a_grammar_that_never_grows_fails():
    with pytest.raises(LengthError, match="short of 3"):
        plan_section(0, section({"F": [("F+", 1)]}, (3, 4)), random.Random(0))


def test_a_cadence_counts_two_bars():
    plan = plan_section(0, section({"F": [("FK", 1)]}, (3, 3)), random.Random(0))
    assert plan.word == "FK"
    assert plan.bars == 3


def test_same_stream_same_plan():
    rules = {"F": [("F[+F]F", 2), ("FMF", 1), ("FFK", 1)]}
    a = plan_section(0, section(rules, (6, 12)), random.Random(11))
    b = plan_section(0, section(rules, (6, 12)), random.Random(11))
    assert a == b
