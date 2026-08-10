# Stylized-facts atlas

The eleven classic stylized facts of asset returns (the canonical list is
Cont 2001), mapped to what Sieve can observe, measure and draw — and to
what it deliberately does not do yet. This file is the correspondence
table required by the workbench design (task §5.3, §10): claim ↔ scalar
metric ↔ functional diagnostic ↔ figure ↔ required input ↔ blind spots.

Ground rules:

- **No scalar metric represents a stylized fact by itself.** `acf_abs_1`
  is one point on the volatility-ACF curve; the curve and the return-path
  texture are shown alongside it. Figures are evidence, but visual
  inspection never decides PASS — and a scalar test can miss what a figure
  shows.
- **Statuses are per-diagnostic**: `OBSERVED` (computed and rendered from
  adequate data), `INSUFFICIENT`, `NOT_APPLICABLE` (input lacks a column
  or geometry), `NOT_TESTED` (registered roadmap entry). No counts, no
  "8/11".
- Figures reuse the metric computation code; consistency is enforced by
  `tests/unit/test_figures.py`.

## The eleven facts

| # | Stylized fact | Observable | Scalar metric | Figure (registry id) | Minimum data | Status |
|---|---|---|---|---|---|---|
| 1 | Volatility clustering | \|r\| dynamics | `acf_abs_1` | `return_path`, `volatility_acf` | 300 obs/run | **implemented** |
| 2 | Intermittency | activity bursts in r | — (visual + `acf_abs_*`) | `return_path` | 50 obs/run | **implemented** (visual) |
| 3 | Heavy tails | marginal of r | `excess_kurtosis`, `hill_left/right` | `marginal_distribution`, `tail_ccdf` | 200–300 obs/run; ≥50 tail points | **implemented** |
| 4 | Absence of return autocorrelation | ACF(r) | — (curve) | `return_acf` | 200 obs/run | **implemented** |
| 5 | Slow decay of volatility ACF | ACF(\|r\|), ACF(r²) | `acf_abs_20` | `volatility_acf` | 300 obs/run | **implemented** |
| 6 | Volume/volatility correlation | (volume, \|r\|) pairs | Spearman ρ (reported, not registered) | `volume_volatility` | volume column; 300 obs/run | **implemented** |
| 7 | Aggregational Gaussianity | κ(Δt) over horizons | `excess_kurtosis` at Δt=1 | `aggregation_profile` | ≥200 aggregated obs per horizon | **implemented** |
| 8 | Conditional heavy tails | standardized residual tails | — | `conditional_tails` | ~1000 obs/run + vol model | **NOT_TESTED** (planned) |
| 9 | Asymmetry in time scales | coarse↔fine vol lead-lag | — | `timescale_asymmetry` | ~2000 obs/run | **NOT_TESTED** (planned) |
| 10 | Leverage effect | corr(r_t, \|r_{t+τ}\|) | `leverage` (mean of c(1..5)) | `leverage_kernel` | 300 obs/run | **implemented** |
| 11 | Gain/loss asymmetry | first-passage times to ±θ | — | `gain_loss_asymmetry` | price column; ~5000 obs/run | **NOT_TESTED** (planned) |

Supporting diagnostics outside the canonical list: `drift_variance_diagnostic`
(per-run drift and VR(q) — calibration sanity; `drift`, `variance_ratio_20`).

## Estimator choices and failure modes (implemented figures)

### return_path
- **Estimators**: raw r_t; rolling mean of |r| (window 25, printed).
- **Display**: min-max decimation per pixel bucket — extremes survive
  downsampling; ensembles show the first ≤4 runs in run_id order (rule
  printed; never a curated pick).
- **Failure modes**: naive decimation would erase spikes; a hand-picked
  "representative run" is cherry-picking.

### marginal_distribution
- **Estimators**: per-run standardization, pooled across runs for the
  marginal view only (disclosed); histogram (61 bins over ±8σ) + standard
  normal comparator, linear and log-y panels.
- **Failure modes**: bin-dependence (the CCDF is the primary tail
  evidence); linear-only densities hide tails; pooling can hide run-to-run
  differences (per-run values are in the metric table).

### tail_ccdf
- **Estimators**: empirical CCDF per tail; Hill estimator at tail fraction
  0.05 (identical code to the `hill_left/right` metrics), k region marked.
- **Failure modes**: k-sensitivity (recorded ~0.9 IQR swing across
  2.5–10%); log-log straightness read as "power law" without a fit range
  and estimator — the figure fits nothing beyond the marked Hill line;
  <50 tail points → tail panel not drawn.

### return_acf / volatility_acf
- **Estimators**: the metric-shared ACF at lags 1..50 / 1..100; across-run
  median + IQR band for ensembles; ±1.96/√n iid band.
- **Failure modes**: the iid band understates uncertainty under volatility
  clustering (printed on every use); nonpositive ACF values cannot appear
  on the log-log panel (count printed); no functional form is fitted —
  power-law vs exponential decay claims would need a prespecified fit
  range and estimator, deliberately not done here.

### aggregation_profile
- **Estimators**: excess kurtosis of non-overlapping Δt-sums per run
  (never across runs), horizons {1,2,5,10,20,40,80,160} filtered to ≥200
  aggregated observations per run.
- **Failure modes**: effective n shrinks as n/Δt (printed); at horizons
  inside the volatility correlation time κ(Δt) can genuinely *rise* before
  decaying — a decay assertion at short horizons tests the wrong thing;
  the profile is consistent with, not a test of, aggregational
  Gaussianity.

### leverage_kernel
- **Estimators**: c(τ) = corr(r_t, |r_{t+τ}|), τ ∈ −20..20; the scalar
  `leverage` metric is the mean of this exact curve over τ = 1..5 (shaded
  on the plot; equality tested).
- **Failure modes**: lag-count sensitivity (~0.94 IQR, recorded metric
  blind spot); sign/lag conventions differ across papers — the definition
  is printed on the figure; metric-vs-plot definition drift is prevented
  by shared code + tests.

### volume_volatility
- **Estimators**: within-run (volume, |r|) pairs; equal-count binned
  conditional means; Spearman ρ per run, median across runs.
- **Failure modes**: heavy-tailed volume makes raw scatters unreadable
  (display clipped at the 99.5th percentile, stated; statistics use all
  points); cross-run pair matching would be meaningless — pairs never
  cross runs; no uncertainty interval is attached in exploratory mode.

## Planned figures — why they are NOT_TESTED, and what they need

These are registered in the figure registry (they render as roadmap cards
with references) but not implemented, because their estimator and sample
requirements must be prespecified first — shipping a plausible-looking
version would violate the workbench's own rules (task §13).

### conditional_tails (fact 8)
Compare raw-return tails to the tails of conditional-volatility-
standardized residuals. Needs: a declared conditional volatility model
(e.g. GARCH(1,1)) as an **optional dependency**, its parameters recorded
in the bundle, and a decision on estimator (MLE vs variance targeting).
Risk: the model fit adds a dependency that changes the evidence; raw-tail
and residual-tail claims must never be conflated.

### timescale_asymmetry (fact 9)
Cross-correlation of coarse-grained and fine-grained volatility at ±lags
(Müller et al. 1997). Needs: prespecified aggregation horizons, a lag-sign
convention printed with the figure, and enough data (~2000 obs/run) for
the coarse series to retain resolution.

### gain_loss_asymmetry (fact 11)
Distribution of first-passage times to +θ vs −θ (Jensen, Johansen &
Simonsen 2003). Needs: a declared threshold θ, an explicit censoring rule
for passages that never occur before the series ends, and long runs
(~5000 obs). Passages must never cross a run boundary. Note: the
inspiration literature reports this as the one fact its speculative-game
model did **not** reproduce — a workbench that cannot show a NOT_TESTED
honestly would be useless exactly here.

## Deferred inference (not figures)

- **Confirmatory multi-run-ensemble testing** against the shipped window
  reference: run-units vs window-units is a different sampling design;
  `sieve test` refuses ensembles with guidance instead of faking it.
- **Paired-seed / control-vs-intervention comparison**: manifest schema
  reserves per-run `pair_id`; the comparison method belongs with the
  ensemble inference above.

## References

- Cont, R. (2001). Empirical properties of asset returns: stylized facts
  and statistical issues. *Quantitative Finance* 1(2), 223–236.
- Hill, B. M. (1975). A simple general approach to inference about the
  tail of a distribution. *Annals of Statistics* 3(5).
- Lo, A. W. & MacKinlay, A. C. (1988). Stock market prices do not follow
  random walks. *Review of Financial Studies* 1(1).
- Bouchaud, J.-P., Matacz, A. & Potters, M. (2001). Leverage effect in
  financial markets. *Physical Review Letters* 87(22).
- Müller, U. A. et al. (1997). Volatilities of different time resolutions.
  *Journal of Empirical Finance* 4(2–3).
- Jensen, M. H., Johansen, A. & Simonsen, I. (2003). Inverse statistics in
  economics: the gain–loss asymmetry. *Physica A* 324.
- Karpoff, J. M. (1987). The relation between price changes and trading
  volume. *Journal of Financial and Quantitative Analysis* 22(1).
