# Roadmap: economic-scenario-generator (ESG) suites

Scoping notes for the next suite family. The strategic frame: Sieve
evaluates **scenario-generating models, one versioned suite per use** — the
insurer ESG is the use with the clearest regulatory demand for exactly the
artifact Sieve produces (an independent, reproducible validation report),
and the model-update regression gate (`sieve compare`) is the workflow
bridge that already works today.

## Why insurers, concretely

- **EIOPA** (Solvency II stochastic valuation peer review, 2025): insurers
  carry validation responsibility for economic scenarios *even when the
  generator is externally procured* — named checks include martingale
  tests, comparison against market data, sensitivity and Monte-Carlo-error
  analysis.
- **NAIC** (PBR / GOES): scenario files are published together with
  official *stylized facts* and *acceptance criteria* documents — e.g.
  "AAA Interest Rate Acceptance Criteria", "AAA ESGWG Equity Model Stylized
  Facts", "AAA ESGWG Corporate Stylized Facts and Acceptance Criteria",
  "GEMS Equity and Corporate Model Stylized Facts" — and candidate scenario
  sets are examined against them. That is *institutionally published
  prespecification*: the acceptance criteria exist before the model run,
  which is precisely the `Prespecification.PRE_SPECIFIED` regime Sieve
  already encodes per metric.
- **Japan**: the economic-value-based solvency regime applies from
  2026-03-31 (FSA insurance monitoring report, 2026). Large insurers'
  core engines are built; the entry point is independent validation,
  recalibration monitoring and external-model comparison — not primary
  infrastructure.
- **Banks** (SR 26-2 model risk management): outcome analysis, ongoing
  monitoring, and recalibration/redevelopment decisions are formal
  processes; J.P. Morgan's synthetic-data work publishes the same loop
  (compute statistics on real and synthetic series, compare, iterate) that
  `sieve test` + `sieve compare` mechanize with sealed evidence.

## The two-suite split (do not blur it)

| | `esg-real-world` | `esg-risk-neutral` |
|---|---|---|
| question | do scenario paths behave like the real measure? | is the set arbitrage-consistent with market prices? |
| tests | stylized facts (tails, clustering, dependence), long-horizon distributions, acceptance-criteria percentile bounds, cross-asset dependence, Monte-Carlo error | martingale tests (discounted asset ≈ martingale), initial-curve fit, repricing error on calibration instruments |
| overlap with today's Sieve | metric battery partially transfers | essentially none — new test family |

`financial-daily@1.0` metrics transfer to the real-world suite for the
equity-return component; interest-rate criteria (curve level/slope
distributions at horizons, negative-rate frequency bounds) are new metrics
with the same `MetricSpec` shape.

## Technical gaps, in order

1. **Tier-0.5 multi-path input.** NAIC-style scenario files are monthly,
   30+ year horizon, thousands of paths — not one long daily series. The
   CSV contract gains an optional `path` column (or a scenario-file
   adapter); windows become per-path segments; the exchangeability
   assumption of the compare permutation becomes *exact* across paths
   (better than today's within-path near-independence).
2. **Frequency-aware suites.** `financial-daily` windows are 1000 trading
   days; an ESG suite declares monthly frequency and horizon-indexed
   checks (e.g. year-1 / year-10 / year-30 distributions), so window
   length stops being the only cut.
3. **Acceptance-criteria metrics.** NAIC criteria are largely percentile
   bounds on cumulative returns / rate levels at horizons. These are
   deterministic checks per scenario set (no reference resampling), which
   map to `TestResult` with a different `statistic_name` and a
   PASS/FAIL against published bounds — prespecified by a third party,
   the strongest provenance a metric can have.
4. **Martingale suite** (risk-neutral): new inference (unit-root-free
   drift tests on discounted paths, repricing errors), separate suite id.

## Sequence

1. ~~Model-update regression gate on the current suite~~ — shipped
   (`sieve compare`, `examples/model_update`, frozen case in
   `docs/example-update/`).
2. Prototype `esg-real-world` against the published NAIC scenario files
   and the AAA acceptance criteria for the equity component (Tier-0.5
   adapter + horizon checks). Deliverable: one validation report for a
   public scenario set, in the exact format an appointed actuary would
   attach to filing documentation.
3. Hearings with life-insurance ERM / actuarial and insurance-consulting
   contacts, carrying the two frozen artifacts (update-regression case +
   ESG prototype report).
4. LOB / system-wide suites only with a concrete research partner.
