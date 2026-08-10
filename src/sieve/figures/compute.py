"""Shared intermediate computations for figures.

Figures must show the *same* quantities the scalar metrics measure, computed
by the *same* code (task §11: no re-implemented formulas drifting apart).
Everything here either calls the registered metric functions directly or
extends them along an axis (per-lag, per-horizon, per-tau) using identical
operations, verified by tests against ``observations.parquet`` values.
"""

from __future__ import annotations

import numpy as np

from sieve.metrics._shared import acf
from sieve.metrics.tails import _hill


def standardize(r: np.ndarray) -> np.ndarray | None:
    """Unit-variance standardization; ``None`` for constant series."""
    s = r.std()
    if not np.isfinite(s) or s <= 0:
        return None
    return (r - r.mean()) / s


def acf_curve(x: np.ndarray, max_lag: int) -> np.ndarray:
    """ACF at lags 1..max_lag via the metric-shared ``acf`` (so the curve at
    lag 1/20 equals ``acf_abs_1``/``acf_abs_20`` bit for bit)."""
    return np.array([acf(x, k) for k in range(1, max_lag + 1)])


def ccdf_points(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Empirical CCDF P(X >= x_i): sorted values and survival fractions."""
    xs = np.sort(x)
    n = len(xs)
    return xs, (n - np.arange(n)) / n


def hill_overlay(tail: np.ndarray, frac: float = 0.05
                 ) -> dict[str, float] | None:
    """Hill estimate for one tail plus the threshold info the plot marks.

    ``alpha`` is exactly the registered metric's ``_hill`` value; the plot
    additionally needs k (order statistics used) and x_k (threshold).
    """
    if len(tail) == 0:
        return None
    alpha = _hill(tail, frac)
    if not np.isfinite(alpha):
        return None
    xs = np.sort(tail)[::-1]
    k = max(int(len(xs) * frac), 10)
    return {"alpha": float(alpha), "k": int(k), "x_k": float(xs[k]),
            "n_tail": int(len(xs))}


def aggregate_returns(r: np.ndarray, dt: int) -> np.ndarray:
    """Non-overlapping Δt-sums of one run's returns (never crosses runs)."""
    n = (len(r) // dt) * dt
    if n < dt:
        return np.empty(0)
    return r[:n].reshape(-1, dt).sum(axis=1)


def excess_kurtosis_value(r: np.ndarray) -> float:
    """Same operations as ``metrics.distribution.excess_kurtosis``."""
    from sieve.metrics.distribution import excess_kurtosis

    return excess_kurtosis(r)


def leverage_point(r: np.ndarray, tau: int) -> float:
    """corr(r_t, |r_{t+tau}|) with the exact operation sequence of
    ``metrics.asymmetry.leverage`` for positive tau (its per-lag term)."""
    a = np.abs(r)
    if tau == 0 or abs(tau) >= len(r):
        return float("nan")
    if tau > 0:
        x, y = r[:-tau], a[tau:]
    else:
        m = -tau
        x, y = r[m:], a[:-m]
    sx, sy = x.std(), y.std()
    if sx > 0 and sy > 0:
        return float(((x - x.mean()) * (y - y.mean())).mean() / (sx * sy))
    return float("nan")


def leverage_curve(r: np.ndarray, max_tau: int) -> tuple[np.ndarray, np.ndarray]:
    """c(tau) for tau in -max_tau..max_tau (excluding 0)."""
    taus = np.array([t for t in range(-max_tau, max_tau + 1) if t != 0])
    return taus, np.array([leverage_point(r, int(t)) for t in taus])


def leverage_scalar_from_curve(r: np.ndarray, lags: int = 5) -> float:
    """Mean of c(1..lags): identical float ops to ``asymmetry.leverage``."""
    out = []
    for k in range(1, lags + 1):
        v = leverage_point(r, k)
        if not np.isnan(v):
            out.append(v)
    return float(np.mean(out)) if out else float("nan")


def variance_ratio(r: np.ndarray, q: int) -> float:
    """Same operations as ``metrics.dependence.variance_ratio_20`` for any q."""
    from sieve.metrics.dependence import variance_ratio_20

    return variance_ratio_20(r, q=q)


def iid_acf_band(n: int, level: float = 1.96) -> float:
    """Approximate +/- band for the ACF of an iid series of length n.

    This is the classic 1.96/sqrt(n) large-sample band; it UNDERSTATES
    uncertainty for dependent data (volatility clustering widens the true
    band), which every figure using it must say in its caveats.
    """
    return float(level / np.sqrt(n)) if n > 0 else float("nan")


def decimate_minmax(y: np.ndarray, max_points: int
                    ) -> tuple[np.ndarray, np.ndarray]:
    """Extreme-preserving downsampling for path plots.

    Buckets the series and keeps each bucket's min and max in temporal
    order, so spikes survive (task §5.1-A). Returns (indices, values).
    """
    n = len(y)
    if n <= max_points:
        return np.arange(n), y
    n_buckets = max_points // 2
    edges = np.linspace(0, n, n_buckets + 1).astype(int)
    idx: list[int] = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = y[a:b]
        i_min, i_max = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        idx.extend(sorted({i_min, i_max}))
    ia = np.array(sorted(set(idx)))
    return ia, y[ia]


def rolling_mean_abs(r: np.ndarray, window: int) -> np.ndarray:
    """Rolling mean of |r| (valid mode); a simple volatility texture proxy."""
    a = np.abs(r)
    if len(a) < window:
        return np.empty(0)
    kernel = np.ones(window) / window
    return np.convolve(a, kernel, mode="valid")


def pointwise_quantiles(curves: list[np.ndarray], qs=(0.25, 0.5, 0.75)
                        ) -> list[np.ndarray] | None:
    """Per-lag quantiles across runs (curves must share a length; callers
    truncate to the common minimum). This aggregates *derived curves*
    across runs — it never concatenates the underlying series."""
    if not curves:
        return None
    m = min(len(c) for c in curves)
    if m == 0:
        return None
    arr = np.vstack([c[:m] for c in curves])
    with np.errstate(invalid="ignore"):
        return [np.nanquantile(arr, q, axis=0) for q in qs]
