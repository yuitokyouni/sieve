# Calibration of the compare gate (test-of-the-test)

The A-vs-B window permutation test in `sieve compare` reuses the suite's
α = 0.01 / Holm line, which was calibrated for a *different* design (real
windows vs model windows under calendar-block dependence). This study
measures what that line actually delivers for the compare design itself.
Raw results: `compare-calibration.json`; regenerate with
`python3 tools/calibrate_compare.py` (~10 min, offline) whenever the
compare design changes.

Design: GARCH(1,1)-t with the shipped S&P 500 joint-MLE parameters,
1000-day non-overlapping windows, permutation KS with 2000 draws, Holm over
the 8 suite metrics, flag = adjusted p < 0.01.

## Size (H0: same parameters, independent seeds)

| windows | null pairs | family-wise false-positive rate |
|---|---|---|
| 15 vs 15 | 400 | **0.005** (2/400) |
| 6 vs 6 | 200 | **0.000** (0/200) |

The gate is *conservative* relative to the nominal line (the earlier
"slightly liberal" guess in the caveat text was wrong in the safe
direction and has been replaced by these measurements). Only the Hill tail
metrics ever produced a false flag (0.25% each at 15v15).

## Power (15 vs 15 windows, 100 pairs per effect)

Per-metric detection rates for one-sided parameter perturbations of the
baseline (β = 0.875, ν = 6.47):

| effect | excess_kurtosis | acf_abs_1 | acf_abs_20 | hill_left | hill_right |
|---|---|---|---|---|---|
| β → 0.86 | 0.00 | 0.00 | 0.03 | 0.00 | 0.00 |
| β → 0.84 | 0.01 | 0.07 | 0.21 | 0.01 | 0.01 |
| β → 0.82 | 0.03 | 0.14 | 0.66 | 0.03 | 0.02 |
| β → 0.80 and ν → 30 (worked example) | **1.00** | 0.60 | **0.98** | 0.78 | 0.84 |
| ν → 30 only | 0.10 | 0.00 | 0.00 | 0.04 | 0.03 |

(leverage / variance_ratio_20 / drift stayed at or near zero for every
effect, as they should — these perturbations do not touch those
mechanisms.)

## What to conclude, and what not to

- The worked example's regression class (persistence collapse + tail-df
  clip) is detected essentially always, led by `excess_kurtosis` and
  `acf_abs_20`.
- **Measured power boundary:** persistence drifts of |Δβ| ≤ 0.04 are
  mostly invisible at 15v15 windows, and a tail-df clip alone at high
  persistence is nearly invisible to unconditional window statistics
  (both fourth-moment conditions diverge either way). A NO_CHANGE_DETECTED
  outcome must not be read as "the versions are equivalent" — it means no
  change *of a detectable size* at this window count.
- More windows buy power cheaply for generators (they can emit arbitrarily
  long paths); the paired common-random-numbers mode sketched in
  `roadmap-esg.md` would buy more for small recalibrations.
