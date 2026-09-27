"""Turn a section's grammar into its plan, with length control.

A section's grammar is rewritten until its bar count lands inside the
section's length range, and the first iteration that does is used whole. An
iteration that overshoots starts a new attempt from the axiom, continuing
the section's random stream.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from lindenfret.alphabet import bar_count
from lindenfret.config import ConfigError, Section
from lindenfret.lsystem import iter_words

MAX_ITERATIONS = 12  # a grammar still short of its range after this many never grows enough
MAX_ATTEMPTS = 50


class LengthError(ConfigError):
    """A section's grammar can't land inside its length range."""


@dataclass(frozen=True)
class SectionPlan:
    index: int  # position in the form
    section: Section
    derivation: tuple[str, ...]  # the attempt that fit, axiom first
    attempts: int

    @property
    def word(self) -> str:
        return self.derivation[-1]

    @property
    def bars(self) -> int:
        return bar_count(self.word)


def plan_section(index: int, section: Section, rng: random.Random) -> SectionPlan:
    low, high = section.length
    for attempt in range(1, MAX_ATTEMPTS + 1):
        words = []
        for word in iter_words(section.axiom, section.rules, rng):
            words.append(word)
            bars = bar_count(word)
            if low <= bars <= high:
                return SectionPlan(index, section, tuple(words), attempt)
            if bars > high:
                break
            if len(words) > MAX_ITERATIONS:
                raise LengthError(
                    f"sections.{section.name}: after {MAX_ITERATIONS} iterations the grammar "
                    f"reaches only {bars} bars, short of {low}"
                )
    raise LengthError(
        f"sections.{section.name}: no derivation landed in {low}-{high} bars in "
        f"{MAX_ATTEMPTS} attempts; widen the length range or change the rules"
    )
