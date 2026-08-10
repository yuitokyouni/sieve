"""Directional sanity of the diagnostics on known artificial processes
(task §9 scientific tests).

Fixed seeds, generous sample sizes, loose thresholds: these tests check the
*direction* of each signal, never a theoretical exact value.
"""

import numpy as np

import sieve
from sieve.figures import compute as C
from sieve.metrics.registry import compute

N = 8000
SEED = 42


def _garch(n, seed, alpha=0.10, beta=0.88, gamma=0.0):
    # default persistence alpha+beta = 0.98: strong, unambiguous clustering;
    # tests adding GJR asymmetry pass smaller alpha/beta so that
    # alpha + gamma/2 + beta stays < 1 (else the process explodes)
    g = np.random.default_rng(seed)
    r = np.zeros(n)
    s2 = 1.0
    for t in range(1, n):
        asym = gamma if r[t - 1] < 0 else 0.0
        s2 = 0.02 + (alpha + asym) * r[t - 1] ** 2 + beta * s2
        r[t] = np.sqrt(s2) * g.standard_normal()
    return r


def test_gaussian_iid_is_thin_and_uncorrelated():
    r = np.random.default_rng(SEED).standard_normal(N)
    assert abs(compute("excess_kurtosis@1", r)) < 0.3
    assert abs(C.acf_curve(r, 1)[0]) < 0.04
    assert abs(compute("acf_abs_1@1", r)) < 0.04
    assert 0.9 < compute("variance_ratio_20@1", r) < 1.1


def test_student_t_is_heavy_tailed_without_time_dependence():
    r = np.random.default_rng(SEED).standard_t(4, size=N)
    assert compute("excess_kurtosis@1", r) > 1.0
    assert abs(compute("acf_abs_1@1", r)) < 0.05
    # heavier tail => smaller Hill index than a Gaussian's
    g = np.random.default_rng(SEED + 1).standard_normal(N)
    assert compute("hill_left@1", r) < compute("hill_left@1", g)


def test_garch_shows_volatility_clustering():
    r = _garch(N, SEED)
    assert compute("acf_abs_1@1", r) > 0.1
    assert compute("acf_abs_20@1", r) > 0.02
    assert compute("excess_kurtosis@1", r) > 0.5


def test_gjr_style_asymmetry_shows_leverage():
    r_sym = _garch(N, SEED, alpha=0.04, beta=0.86, gamma=0.0)
    r_asym = _garch(N, SEED, alpha=0.04, beta=0.86, gamma=0.12)
    assert compute("leverage@1", r_asym) < -0.02
    assert compute("leverage@1", r_asym) < compute("leverage@1", r_sym) - 0.01


def test_shuffled_garch_keeps_marginal_breaks_dependence():
    r = _garch(N, SEED)
    shuffled = np.random.default_rng(SEED + 9).permutation(r)
    # identical marginal => identical kurtosis (up to summation order)
    import pytest
    assert compute("excess_kurtosis@1", shuffled) == pytest.approx(
        compute("excess_kurtosis@1", r), rel=1e-9)
    # time dependence destroyed
    assert compute("acf_abs_1@1", r) > 0.1
    assert abs(compute("acf_abs_1@1", shuffled)) < 0.04


def test_known_drift_process_moves_drift_metric():
    g = np.random.default_rng(SEED)
    r = 0.005 + 0.01 * g.standard_normal(N)
    assert compute("drift@1", r) > 0.4
    r0 = 0.01 * np.random.default_rng(SEED + 1).standard_normal(N)
    assert abs(compute("drift@1", r0)) < 0.05


def test_trending_process_raises_variance_ratio():
    g = np.random.default_rng(SEED)
    eps = g.standard_normal(N)
    ar = np.zeros(N)
    for t in range(1, N):
        ar[t] = 0.3 * ar[t - 1] + eps[t]
    assert compute("variance_ratio_20@1", ar) > 1.3


def test_multi_run_input_preserves_per_seed_distributions():
    """Per-run values must survive intact — no mixing, no concatenation."""
    thin = np.random.default_rng(1).standard_normal(3000)
    fat = np.random.default_rng(2).standard_t(3, size=3000)
    ds = sieve.from_runs([{"run_id": "thin", "return": thin},
                          {"run_id": "fat", "return": fat}])
    by_run = ds.returns_by_run()
    k_thin = compute("excess_kurtosis@1", by_run["thin"])
    k_fat = compute("excess_kurtosis@1", by_run["fat"])
    assert k_thin == compute("excess_kurtosis@1", thin)
    assert k_fat == compute("excess_kurtosis@1", fat)
    assert k_fat > k_thin + 1.0


def test_aggregation_profile_direction_on_garch():
    """Aggregated GARCH returns lose kurtosis (aggregational Gaussianity).

    Uses a long series and a horizon well past the volatility correlation
    time: at horizons *within* the cluster length, kappa(dt) can genuinely
    rise before decaying (visible in the aggregation-profile figure too),
    so a short-horizon assertion would test the wrong thing."""
    r = _garch(50_000, SEED, alpha=0.20, beta=0.60)
    k1 = C.excess_kurtosis_value(r)
    k50 = C.excess_kurtosis_value(C.aggregate_returns(r, 50))
    assert k1 > 0.5
    assert k50 < k1 / 2
