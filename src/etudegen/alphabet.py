"""The bar grammar's alphabet: which symbols exist and how many bars each plays.

See "The L-system alphabet" in docs/design.md for what each symbol does.
"""

from __future__ import annotations

BAR_SYMBOLS = frozenset("FHMK+-[]")

# F and H play one bar; K plays two (dominant, then tonic); the rest play none.
BAR_LENGTHS = {"F": 1, "H": 1, "K": 2}


def bar_count(word: str) -> int:
    """Bars a word plays, before bar repetition."""
    return sum(BAR_LENGTHS.get(symbol, 0) for symbol in word)
