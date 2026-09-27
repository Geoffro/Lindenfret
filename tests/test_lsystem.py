import random

from hypothesis import given
from hypothesis import strategies as st

from lindenfret.lsystem import Production, derive, iter_words, rewrite
from lindenfret.rng import stage_rng


def single(to):
    return (Production(to, 1.0),)


def test_deterministic_rules_give_known_words():
    # Lindenmayer's algae: A -> AB, B -> A.
    rules = {"A": single("AB"), "B": single("A")}
    words = derive("A", rules, 5, random.Random(0))
    assert words == ["A", "AB", "ABA", "ABAAB", "ABAABABA", "ABAABABAABAAB"]


def test_symbols_without_rules_are_copied():
    assert rewrite("F+[F]-", {"F": single("FF")}, random.Random(0)) == "FF+[FF]-"


def test_deterministic_rules_leave_the_stream_untouched():
    rng = random.Random(7)
    before = rng.getstate()
    derive("F", {"F": single("F[+F]F")}, 3, rng)
    assert rng.getstate() == before


def test_same_seed_gives_the_same_derivation():
    rules = {"F": (Production("F[+F]F", 2), Production("F-F", 1), Production("FF", 1))}
    a = derive("F", rules, 4, stage_rng(99, "section.0"))
    b = derive("F", rules, 4, stage_rng(99, "section.0"))
    assert a == b


def test_weights_bias_the_choice():
    rules = {"X": (Production("a", 9), Production("b", 1))}
    rng = random.Random(1)
    picks = [rewrite("X", rules, rng) for _ in range(2000)]
    assert 0.85 < picks.count("a") / len(picks) < 0.95


def test_iter_words_starts_with_the_axiom():
    words = iter_words("F", {"F": single("FF")}, random.Random(0))
    assert [next(words) for _ in range(4)] == ["F", "FF", "FFFF", "FFFFFFFF"]


@given(seed=st.integers(0, 2**32), iterations=st.integers(0, 4))
def test_balanced_productions_keep_brackets_balanced(seed, iterations):
    rules = {"F": (Production("F[+F]F", 1), Production("F[-F[+F]]", 1), Production("FF", 1))}
    word = derive("F", rules, iterations, random.Random(seed))[-1]
    depth = 0
    for symbol in word:
        depth += {"[": 1, "]": -1}.get(symbol, 0)
        assert depth >= 0
    assert depth == 0
