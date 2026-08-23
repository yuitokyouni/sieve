"""splitmix64 — a fully specified 64-bit generator.

The contract records `rng_algorithm` and `rng_version` as first-class fields
(Q2). For that to mean anything the canary's generator must be specified by
its arithmetic, not by "whatever the interpreter shipped": `random.Random`
would tie the fixture to CPython's Mersenne Twister seeding, and numpy would
tie it to the stack under test. splitmix64 is 8 lines of integer arithmetic
and reproduces identically on any conforming Python.

Reference: Steele, Lea, Flood (2014), "Fast splittable pseudorandom number
generators", OOPSLA. Constants as published.
"""

from __future__ import annotations

MASK64 = (1 << 64) - 1
GOLDEN_GAMMA = 0x9E3779B97F4A7C15

ALGORITHM = "splitmix64"
VERSION = "1"


class SplitMix64:
    """Deterministic 64-bit stream. `draw()` returns an integer in [0, 2**64)."""

    def __init__(self, seed: int) -> None:
        self._state = seed & MASK64
        self.draws = 0

    def draw(self) -> int:
        self._state = (self._state + GOLDEN_GAMMA) & MASK64
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & MASK64
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & MASK64
        return (z ^ (z >> 31)) & MASK64

    def below(self, n: int) -> int:
        """Uniform-ish integer in [0, n). Modulo bias is accepted and declared:
        n is <= 20 in every fixture and the stream is not being used to make a
        statistical claim, only to make a reproducible one."""
        if n <= 0:
            raise ValueError("n must be positive")
        self.draws += 1
        return self.draw() % n
