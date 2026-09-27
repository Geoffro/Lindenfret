"""Weighted stochastic L-system rewriting.

Each iteration replaces every symbol that has productions, in parallel, with
one of its productions drawn by weight. Symbols without productions are
copied unchanged.
"""

from __future__ import annotations

import random
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Production:
    to: str
    weight: float


Rules = Mapping[str, Sequence[Production]]


def rewrite(word: str, rules: Rules, rng: random.Random) -> str:
    parts = []
    for symbol in word:
        productions = rules.get(symbol)
        parts.append(_choose(productions, rng) if productions else symbol)
    return "".join(parts)


def iter_words(axiom: str, rules: Rules, rng: random.Random) -> Iterator[str]:
    """Yield the axiom, then the word after each further iteration, forever."""
    word = axiom
    while True:
        yield word
        word = rewrite(word, rules, rng)


def derive(axiom: str, rules: Rules, iterations: int, rng: random.Random) -> list[str]:
    """Return the axiom followed by the word after each of `iterations` rewrites."""
    words = iter_words(axiom, rules, rng)
    return [next(words) for _ in range(iterations + 1)]


def _choose(productions: Sequence[Production], rng: random.Random) -> str:
    # A symbol with a single production doesn't consume randomness, so
    # deterministic rules leave the stream untouched.
    if len(productions) == 1:
        return productions[0].to
    return rng.choices(productions, weights=[p.weight for p in productions])[0].to
