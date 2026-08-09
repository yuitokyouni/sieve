"""Two-sample permutation test for exchangeable window sets.

Used ONLY for simulated-vs-simulated comparisons (model-update regression),
where non-overlapping windows cut from independent generator runs are close
to exchangeable. It is deliberately NOT used against the empirical reference:
real windows share calendar shocks, and the research selftest measured a 56%
rejection rate at nominal 5% for exactly this kind of test on that design —
that is what the calendar-block bootstrap in ``blockboot.py`` exists for.

Residual caveat, stated in every compare report: windows cut from one long
simulated path share that path, so within-path long memory makes the null
slightly liberal; at the suite's alpha=0.01 line this is second-order for
GARCH-class memory at 1000-day window lengths.
"""

from __future__ import annotations

import numpy as np


def perm_ks_test(a, b, rng: np.random.Generator, n_draw: int = 2000):
    """Return (ks, p_value, n_a, n_b) for H0: same distribution."""
    from sieve.inference.ks import ks_stat

    a = np.asarray(a, float)
    b = np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 5 or len(b) < 5:
        return float("nan"), float("nan"), len(a), len(b)
    obs = ks_stat(a, b)
    pool = np.concatenate([a, b])
    na = len(a)
    null = np.empty(n_draw)
    for i in range(n_draw):
        perm = rng.permutation(pool)
        null[i] = ks_stat(perm[:na], perm[na:])
    p = float((1.0 + np.sum(null >= obs)) / (n_draw + 1.0))
    return float(obs), p, len(a), len(b)
