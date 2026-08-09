"""Measure the compare gate's actual size and power (test-of-the-test).

The A-vs-B window permutation test reuses the suite's alpha=0.01 line, but
that line was calibrated for a DIFFERENT design (real windows vs model
windows under calendar-block dependence). This script measures what the
line actually delivers for the compare design itself:

- size: generate many (A, B) pairs from the SAME generator parameters with
  different seeds; count per-metric CHANGED verdicts (after Holm) and the
  family-wise rate ("any metric flagged"). Under H0 both should be small
  and near-nominal.
- power: repeat with B's parameters perturbed (the persistence and tail-df
  regressions of the worked example, in decreasing size) and count
  detection per metric.

Runs offline in ~10 minutes; writes docs/compare-calibration.json which
docs/compare-calibration.md summarizes. Regenerate whenever the compare
design (test, alpha, adjustment, window count regime) changes.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parent
sys.path.insert(0, str(PRODUCT / "src"))

from sieve.baselines.garch import generate_t              # noqa: E402
from sieve.inference.multiplicity import holm             # noqa: E402
from sieve.inference.permutation import perm_ks_test      # noqa: E402
from sieve.metrics import registry                       # noqa: E402

METRICS = ["excess_kurtosis", "hill_left", "hill_right", "acf_abs_1",
           "acf_abs_20", "leverage", "variance_ratio_20", "drift"]
WINDOW = 1000
ALPHA = 0.01
N_DRAW = 2000
BASE = [0.011039650497380534, 0.11756950878547939, 0.8751463025418191,
        6.466697865253001]


def windows_stats(params, n_windows, rng):
    r = generate_t(n_windows * WINDOW, rng, {"garch_t": params})
    wins = [r[i * WINDOW:(i + 1) * WINDOW] for i in range(n_windows)]
    return {m: np.array([registry.compute(m, w) for w in wins])
            for m in METRICS}


def one_pair(pa, pb, n_windows, rng):
    """Return per-metric CHANGED flags at the Holm-adjusted alpha line."""
    sa = windows_stats(pa, n_windows, rng)
    sb = windows_stats(pb, n_windows, rng)
    pvals = [perm_ks_test(sa[m], sb[m], rng, N_DRAW)[1] for m in METRICS]
    adj = holm(pvals)
    return {m: bool(np.isfinite(a) and a < ALPHA)
            for m, a in zip(METRICS, adj)}


def experiment(name, pa, pb, n_windows, n_pairs, seed):
    rng = np.random.default_rng(seed)
    per_metric = {m: 0 for m in METRICS}
    any_flag = 0
    t0 = time.time()
    for i in range(n_pairs):
        flags = one_pair(pa, pb, n_windows, rng)
        for m, f in flags.items():
            per_metric[m] += int(f)
        any_flag += int(any(flags.values()))
        if (i + 1) % 25 == 0:
            print(f"  {name}: {i + 1}/{n_pairs} "
                  f"({time.time() - t0:.0f}s)", flush=True)
    return {"n_pairs": n_pairs, "n_windows_per_side": n_windows,
            "familywise_rate": any_flag / n_pairs,
            "per_metric_rate": {m: per_metric[m] / n_pairs for m in METRICS}}


def main():
    out = {"design": {"window": WINDOW, "alpha": ALPHA, "n_draw": N_DRAW,
                      "adjustment": "holm", "test": "window permutation KS",
                      "generator": "garch_t, S&P 500 joint-MLE params",
                      "base_params": BASE},
           "size": {}, "power": {}}

    # ---- size under H0 (identical parameters, independent seeds) ----------
    out["size"]["15v15"] = experiment("null 15v15", BASE, BASE, 15, 400, 1)
    out["size"]["6v6"] = experiment("null 6v6", BASE, BASE, 6, 200, 2)

    # ---- power vs effect size --------------------------------------------
    o, a, b, nu = BASE
    effects = {
        "beta_0.86": [o, a, 0.86, nu],
        "beta_0.84": [o, a, 0.84, nu],
        "beta_0.82": [o, a, 0.82, nu],
        "beta_0.80_nu30": [o, a, 0.80, 30.0],   # the worked example
        "nu30_only": [o, a, b, 30.0],           # known near-invisible
    }
    for name, pb in effects.items():
        out["power"][name] = experiment(f"power {name}", BASE, pb, 15, 100,
                                        hash(name) % 2**31)

    path = PRODUCT / "docs" / "compare-calibration.json"
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {path}")
    print(json.dumps({"size_15v15_fwer": out["size"]["15v15"]["familywise_rate"],
                      "size_6v6_fwer": out["size"]["6v6"]["familywise_rate"]},
                     indent=1))


if __name__ == "__main__":
    main()
