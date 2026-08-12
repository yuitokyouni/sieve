# Changelog

## 0.5.0 — 2026-08-12

Comparison against real daily returns, both exploratory and confirmatory.

- **`sieve inspect --reference SERIES`**: overlay an empirical comparator
  (e.g. an index's daily returns; `--reference-derive-return log` for
  price-only files, `--reference-label "Nikkei 225"` to name it) on the
  marginal distribution, tail CCDFs, return/volatility ACFs, aggregation
  profile, leverage kernel and VR(q) figures. The overlay is visual
  context only: it never affects any status, and its identity (content
  hash, label, n_obs) is recorded in the sealed figure parameters plus a
  `reference_summary.json` artifact. Default labels are content-derived
  (no path leaks into the seal); multi-run references and undeclared
  price derivations are refused.
- **Single-index confirmatory suites `nikkei-daily@0.1.0` and
  `spx-daily@0.1.0`** (experimental): ~26/27 derived windows of 1000
  daily observations (stride 250, 1450-day calendar blocks) from Yahoo
  Finance closes of the Nikkei 225 / S&P 500, built by
  `tools/build_index_suite.py` from `tools/fetch_index_data.py` caches.
  Raw closes are not redistributed; the source CSV sha256 is recorded.
  Disclosed honestly in the manifests: the alpha=0.01 line's calibration
  is INHERITED from the six-index design and not re-measured, and no
  baseline distributions ship (no blindness context in reports). Usage:
  `sieve test LONG_SERIES --suite nikkei-daily@0.1 --claim
  descriptive-market-dynamics`.
- Frozen examples re-pinned for the version bump (statuses and KS values
  unchanged; the seal covers `sieve_version`).

## 0.4.0 — 2026-08-10

Direction change: from an outward-facing ERM/ESG-framed product to a
**research-first simulation validation workbench** for financial ABMs and
collaborative research, without breaking the scientific/audit layer. Full
audit and design rationale: `docs/research-workbench-migration.md`.

- **Generalized research inputs.** `SimulationDataset`: multi-run
  (`run_id` long format, directory-of-runs with manifest), step- or
  timestamp-based time, price-only inputs with *explicit* return
  derivation (`log`/`simple`/`diff` — never implicit), burn-in
  (steps/fraction/per-run, dropped counts recorded), extra observables
  (`volume`, user-defined), declared sampling geometry
  (`single_long_series` / `multi_run_ensemble` / `multi_market_panel` /
  `paired_runs` / `short_exploratory_series`). Python API:
  `sieve.from_arrays` / `from_runs` / `from_dataframe`. Runs are never
  concatenated; derived returns never cross run boundaries; nothing is
  resampled, interpolated or frequency-inferred silently.
- **`sieve inspect` — exploratory mode.** Works with no reference data,
  on one short run or an ensemble. Per-run metric observations gated by
  each metric's new declared `MetricRequirements`; figure statuses are
  `OBSERVED` / `INSUFFICIENT` / `NOT_APPLICABLE` / `NOT_TESTED` — no
  PASS/FAIL exists in this mode, and constant/NaN inputs degrade
  individual diagnostics instead of aborting the run.
- **Figure registry + evidence atlas.** Versioned `FigureSpec` registry
  mirroring the metric registry. Nine deterministic, dependency-free SVG
  diagnostics (return path with min-max decimation, marginal distribution
  vs Gaussian, tail CCDF with Hill overlay and marked k region, return
  ACF, |r|/r² ACF with log-log view, aggregation profile κ(Δt), leverage
  kernel c(τ) with the scalar metric's range shaded, drift/VR panel,
  volume-volatility relation), sharing the metric computation code
  (bit-consistency tested). Three registered `NOT_TESTED` roadmap figures
  (conditional tails, time-scale asymmetry, gain/loss first-passage) with
  documented prespecification requirements
  (`docs/stylized-facts-atlas.md`).
- **Sealed exploratory bundles.** `InspectBundle` with the same two-layer
  seal (deterministic `bundle_hash` + `bundle.sha256`), figure SVGs
  included in the artifact index; `sieve verify` handles both bundle
  kinds. Existing `EvidenceBundle` models, serialization and hashes are
  untouched — old bundles verify unchanged, and `financial-daily@1.0.0`
  is not modified.
- **New exploratory suite `financial-stylized-facts@0.1.0`** (default for
  `inspect`): the 8 existing metrics + 12 registered figures, no
  reference, no inference — declared as such in the suite manifest.
- **New example `examples/abm_ensemble`**: a 6-seed mood-herding ABM
  emitting `step,price,volume` (return derivation and burn-in exercised
  via the manifest).
- **Guard rails on the legacy path.** `sieve test` now refuses multi-run
  inputs with guidance to `inspect` (the legacy reader would previously
  have concatenated long-format runs into one series). Confirmatory
  ensemble inference vs the shipped window reference is deliberately
  deferred, not faked — see the migration doc.
- **Frozen examples refreshed for v0.4.0.** The seal pins the sieve
  version, so `docs/example-run` and `docs/example-update` are
  regenerated under the pinned environment: statuses, KS values and
  verdicts are byte-identical to v0.3.0; only version-bearing fields and
  seals changed (previous example seal `43b88e5f166bba0f…`, new
  `187519f103a28696…`). Schema exports are additive: `MetricSpec` gains
  optional `requirements`; new schemas for `InspectBundle`, `FigureSpec`,
  `FigureResult`, `GeometrySummary`, `MetricRequirements`;
  `EvidenceBundle.schema.json` is byte-identical.
- README rewritten research-first; ERM/ESG remains a planned domain suite
  (`docs/roadmap-esg.md`), no longer the center of the story.

## 0.3.0 — 2026-08-09

Review of v0.2.0 concluded it was "a change-detection report, not a
change-approval gate", and found a provenance defect in the frozen example.
This release addresses all three findings.

- **Provenance correction (most important).** The frozen v2 manifest
  declared "beta unchanged" while the generator used beta = 0.80: the seal
  was intact but sealed a false declaration. Manifests now state the truth
  (beta 0.875 → 0.80 plus the nu clip), the placeholder `git_commit` values
  are replaced by the real commit pinning the generator code, and every
  frozen artifact is regenerated. The compare report now renders the
  **declared parameter diff next to the measured changes** — a measured
  change with no declared cause is flagged as a provenance question — so
  this exact mismatch class is visible instead of latent.
- **The compare design is now calibrated, not borrowed.**
  `tools/calibrate_compare.py` measured the A/B permutation design itself:
  family-wise false-positive rate **0.005 at 15v15 windows (400 null
  pairs), 0.000 at 6v6 (200)** — conservative, replacing the unmeasured
  "slightly liberal" caveat. Power is mapped per effect size: the worked
  example's regression is detected ~always (kurtosis 1.00, acf_abs_20
  0.95); |Δβ| ≤ 0.04 persistence drifts and a lone tail-df clip are mostly
  invisible, and the reports say so (`docs/compare-calibration.md`). All
  calibration seeds are fixed, so the script reproduces the frozen JSON
  bit for bit.
- **Detection → approval.** Each metric now carries a *transition* read
  against the reference gate (REGRESSION / IMPROVEMENT /
  CHANGED_WITHIN_GATE / STABLE / INDETERMINATE) plus median shifts (Δ%),
  and a **versioned approval policy**
  (`required-dims-no-unexplained-change@1`) routes the comparison to
  REVIEW_REQUIRED or NO_CHANGE_DETECTED with the triggering rows listed.
  A routing rule over required dimensions is not an aggregate score:
  nothing is weighted, summed or averaged, and improvements alone never
  block. Compare reports can link both source runs' full reports.

Pinned by this release (all seals moved with sieve_version):

- suite `financial-daily@1.0.0`, suite_hash unchanged
  `343042f8ceedf18ad2f62eae54501e1e73b8ab59db836804f88fe42105911c9f`
- frozen example run `docs/example-run/`: bundle_hash recorded in
  `docs/reproduce.md`
- frozen comparison `docs/example-update/compare/`: compare_hash recorded
  in the compare report and `compare.sha256`

## 0.2.0 — 2026-08-09 (not tagged; superseded by 0.3.0 the same day)

`sieve compare`: the model-update regression gate. Two sealed runs of the
same suite version are compared directly — per metric, a window-permutation
test answers "did the update change this dimension's distribution?", with
Holm adjustment, both sides' vs-reference statuses juxtaposed, and verdicts
CHANGED / NOT_SEPARATED / INSUFFICIENT that never aggregate. Inputs are
verified before anything is computed; tampered or cross-suite runs are
refused. Output is a sealed `compare.json` (+ sha256 sidecar + HTML report).

Shipped worked example (`examples/model_update`, frozen outputs in
`docs/example-update/`): a bad refit (persistence collapsed, tail df
clipped) is localized to `excess_kurtosis` / `hill_left` / `acf_abs_1` /
`acf_abs_20` CHANGED with leverage/dependence/drift NOT_SEPARATED — and the
`acf_abs_1` row demonstrates the gate's reason to exist: clustering halved
while BOTH versions still PASS the reference test (limited power against ~6
calendar blocks); only the direct comparison detects it. Recorded negative
from the example's first draft: a tail-df clip alone, at 0.993 persistence,
is nearly invisible to unconditional window statistics.

Positioning per the scenario-generator reframe: measured objects are
scenario-generating models (ABMs are one kind); real-world vs risk-neutral
ESG validation are deliberately separate future suites. Scoping against the
published NAIC stylized-facts / acceptance-criteria documents:
`docs/roadmap-esg.md`.

Pinned by this release (sieve_version is sealed, so all seals moved):

- suite `financial-daily@1.0.0`, suite_hash unchanged
  `343042f8ceedf18ad2f62eae54501e1e73b8ab59db836804f88fe42105911c9f`
- frozen example run `docs/example-run/`, bundle_hash
  `bafe49e91c2064fd046c8af1f0fc63478803823ca0b13ea6de10d2c32689ac5c`
- frozen comparison `docs/example-update/compare/`, compare_hash
  `2713b5cd3c3c965ab10a3959816dc9cd0f60ce46adc7fdeac275bbd73bd67b0e`

## 0.1.1 — 2026-08-09 (not tagged; superseded by 0.2.0 the same day)

Pre-outreach corrections, all four found by review before any external
reproduction request. Content changes shift the hashes; v0.1.0's pins remain
valid for the v0.1.0 tag.

Pinned by this release:

- suite `financial-daily@1.0.0`, suite_hash
  `343042f8ceedf18ad2f62eae54501e1e73b8ab59db836804f88fe42105911c9f`
- frozen example run `docs/example-run/`, bundle_hash
  `bad5cb0455f78d2603e1a6767209a11eaacc86e5496d56c9cce4aa9cb87a6490`
- reproduction environment: `constraints.txt` (exact pins the example was
  sealed with; transitive closure included)

Changes:

- **Parity claim now enforced, not skipped.** A standalone clone runs 69
  tests and skips the 9 that need the research repo or its raw data. CI
  gained a `parity` job that checks out sieve-bench at a pinned commit and
  sets `SIEVE_RESEARCH_ROOT`, under which a missing or broken research
  checkout is a test failure. Skip messages now say where the claim is
  enforced.
- **Reproduction environment pinned.** `constraints.txt` committed;
  `docs/reproduce.md` and CI install with `-c constraints.txt`. Statuses
  reproduce on newer stacks; the byte-exact seal is guaranteed under the
  pins.
- **Seal vs package versions documented correctly.** `docs/architecture.md`
  claimed the seal covers package versions; it does not — the entire
  environment fingerprint is recorded but unhashed, so a dependency change
  is detected exactly when it changes a measured value. The docs now say
  so, and say why.
- **Reference period label fixed.** The suite manifest said "2001–2025";
  the shipped windows span July 2001 – June 2026. The label now states the
  span of the derived windows, verifiable from `reference_stats.json`
  (suite_hash and all downstream hashes changed accordingly).

## 0.1.0 — 2026-08-09

First public release: M0 (foundations) + M1 (offline golden path) + M1.5
(public credibility release).

Pinned by this release:

- suite `financial-daily@1.0.0`, suite_hash
  `7808f705d610cfde4621d4ea5b46dced75aaa3816558d64b6e9051d24891df61`
- frozen example run `docs/example-run/`, bundle_hash
  `31bda432c319adfcc40a25e137f50dff15446513c886dfc85cbcf61138dbedf5`
- reproduction protocol and environment: `docs/reproduce.md`

Seal scope (M1.5): `bundle_hash` now excludes the platform fingerprint,
filesystem paths and CLI invocation, so the same input bytes + suite + seed +
package versions reproduce the same seal on any machine. Those fields remain
in the bundle under the file-integrity layer. History and rationale:
`docs/architecture.md` ("Audit notes").

- `sieve test <input> --suite financial-daily@1.0 --claim
  descriptive-market-dynamics` produces a complete, deterministic, verifiable
  run directory (report + sealed evidence bundle) locally and offline.
- 8 metrics, 6 mechanism-declared baselines, calibrated calendar-block
  inference — migrated verbatim from the sieve-bench research repository and
  pinned bit-for-bit by golden regression tests.
- Two-layer integrity: deterministic scientific `bundle_hash` (volatile IDs
  excluded) + sha256sum-compatible file sidecar; `sieve verify` reports
  tampering as a result, not a crash.
- Ten-dimension validation profile with first-class NOT_TESTED /
  INSUFFICIENT; POST HOC disclosure; per-row baseline blind-spot context; no
  aggregate score anywhere (enforced by test).
