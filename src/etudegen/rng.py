"""Per-stage random streams.

Each pipeline stage draws from its own random.Random, seeded from the piece
seed and the stage name. Changing how one stage uses randomness never
reshuffles another stage's choices.
"""

from __future__ import annotations

import hashlib
import random


def stage_seed(seed: int, stage: str) -> int:
    # hashlib rather than hash(): Python salts str hashes per process, which
    # would make the same seed give different pieces on different runs.
    digest = hashlib.sha256(f"{seed}:{stage}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def stage_rng(seed: int, stage: str) -> random.Random:
    return random.Random(stage_seed(seed, stage))
