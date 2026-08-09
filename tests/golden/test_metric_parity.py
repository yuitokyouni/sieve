"""Golden regression: the product preserves the sieve-bench science.

Three layers, strongest available first:

1. The suite ships byte-identical copies of the frozen fixtures. Runs
   everywhere, always.
2. Product metric functions equal the research functions bit-for-bit on
   arbitrary synthetic input. Requires the sieve-bench research repo. CI
   checks it out at a pinned commit and sets ``SIEVE_RESEARCH_ROOT`` — with
   that variable set, a missing or unimportable research repo is a FAILURE,
   not a skip. Without it (a standalone clone), these tests skip and say so;
   the CI parity job is where the claim is enforced.
3. Recomputing the 124 reference windows with product metrics reproduces the
   frozen values exactly. Needs the raw index data fetched locally
   (sieve-bench ``fetch.py``); the data is not redistributable, so this
   layer never runs in CI and skips wherever the data is absent.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

PRODUCT = Path(__file__).resolve().parents[2]
# CI pins the research checkout via SIEVE_RESEARCH_ROOT; the fallback covers
# the historical monorepo layout (product/ inside sieve-bench).
RESEARCH = Path(os.environ.get("SIEVE_RESEARCH_ROOT", PRODUCT.parent))
RESEARCH_REQUIRED = "SIEVE_RESEARCH_ROOT" in os.environ
FIX = Path(__file__).resolve().parent / "fixtures"
SUITE = PRODUCT / "suites" / "financial-daily" / "1.0.0"

M1_METRICS = ["excess_kurtosis", "hill_left", "hill_right", "acf_abs_1",
              "acf_abs_20", "leverage", "variance_ratio_20", "drift"]

SKIP_NO_RESEARCH = (
    "research repo not present; the parity claim is enforced by the CI "
    "parity job against a pinned sieve-bench checkout "
    "(SIEVE_RESEARCH_ROOT), see .github/workflows/test.yml")
SKIP_NO_DATA = (
    "raw index data not fetched locally (not redistributable; run "
    "sieve-bench fetch.py to enable this layer — it never runs in CI)")


def product_fn(mid):
    from sieve.metrics import registry
    fn, _, _ = registry.resolve(mid)
    return fn


def _research_available() -> bool:
    return (RESEARCH / "facts.py").exists()


def _require_research():
    """FAIL (not skip) when the pinned research checkout is broken."""
    assert _research_available(), (
        f"SIEVE_RESEARCH_ROOT={RESEARCH} is set but facts.py is not there — "
        "the parity gate must not silently skip")
    if str(RESEARCH) not in sys.path:
        sys.path.insert(0, str(RESEARCH))


# ---- layer 1: the suite ships exactly the frozen fixtures ------------------

@pytest.mark.parametrize("name", ["reference_stats.json",
                                  "baseline_stats.json",
                                  "baseline_params.json"])
def test_suite_ships_frozen_fixture_bytes(name):
    assert (SUITE / name).read_bytes() == (FIX / name).read_bytes()


def test_fixture_shape():
    ref = json.loads((FIX / "reference_stats.json").read_text())
    assert len(ref["windows"]) == 124
    assert set(ref["values"]) == set(M1_METRICS)
    assert all(len(v) == 124 for v in ref["values"].values())
    assert len(ref["sources"]) == 6
    base = json.loads((FIX / "baseline_stats.json").read_text())
    assert set(base["values"]) == {"gaussian", "student_t", "iid_bootstrap",
                                   "block_bootstrap", "garch_norm", "garch_t"}


# ---- layer 2: product == research on synthetic input, bit for bit ----------

@pytest.mark.skipif(not RESEARCH_REQUIRED and not (Path(__file__).resolve()
                    .parents[2].parent / "facts.py").exists(),
                    reason=SKIP_NO_RESEARCH)
@pytest.mark.parametrize("mid", M1_METRICS)
def test_product_metric_equals_research_bit_for_bit(mid):
    _require_research()
    import facts
    rng = np.random.default_rng(2026)
    samples = [rng.standard_normal(1000),
               rng.standard_t(4, 1500),
               np.cumsum(rng.standard_normal(1200)) * 0.01
               + rng.standard_normal(1200)]
    from sieve.baselines.garch import generate_t
    samples.append(generate_t(2000, np.random.default_rng(5),
                              {"garch_t": [0.011, 0.118, 0.875, 6.47]}))
    for x in samples:
        a = product_fn(mid)(x)
        b = float(facts.BATTERY[mid](x))
        assert (np.isnan(a) and np.isnan(b)) or a == b, (mid, a, b)


# ---- layer 3: reference windows recompute exactly (needs local data) -------

@pytest.mark.skipif(not (RESEARCH / "data").is_dir()
                    or not any((RESEARCH / "data").glob("*.json")),
                    reason=SKIP_NO_DATA)
def test_reference_values_recompute_exactly():
    _require_research()
    from windows import load_series, real_windows
    ref = json.loads((FIX / "reference_stats.json").read_text())
    wins = real_windows(load_series())
    assert len(wins) == len(ref["windows"])
    for mid in M1_METRICS:
        fn = product_fn(mid)
        got = [float(fn(w.values)) for w in wins]
        assert got == ref["values"][mid], mid
