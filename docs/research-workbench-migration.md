# Research-workbench migration

Audit and migration design for turning Sieve from an outward-facing
ERM/ESG-framed product into a research-first simulation validation
workbench for financial ABMs — without breaking its scientific and audit
properties. Written **before** any code change (task §1); updated with the
final implemented/deferred split at the end of the work.

## 1. Current input contract (audited)

- `sieve test INPUT` accepts a single CSV (`returns.csv`) or a directory
  containing `returns.csv` + optional `manifest.yaml`
  (`src/sieve/adapters/csv.py`).
- Required column: `return`; optional `timestamp` (carried but unused in
  computation). Minimum 50 observations; non-finite values are an
  `InputError`.
- The series is treated as **one** stationary sample. The manifest
  contributes model identity and provenance only.

## 2. Why the current design effectively requires ~20+ years

`evaluation/runner.py` cuts the input into **non-overlapping windows of
length 1000** (the suite's `reference.window_length`, i.e. ~4 trading
years) and requires `MIN_WINDOWS = 5` finite values per metric before any
test is not INSUFFICIENT. 5 × 1000 daily observations ≈ 20 calendar years.
This is not incidental: the shipped reference (`financial-daily@1.0.0`,
124 windows over 2001–2026) is a *distribution over 1000-observation
windows*, and the calibrated calendar-block bootstrap null is designed for
exactly that dependence structure. The 20-year requirement is a property
of the **inference design**, not of the metrics — every metric happily
computes on ~300+ observations.

## 3. Where the single-long-series assumption lives

- `runner.run_test`: `load_input` returns one `np.ndarray`; `cut_windows`
  slices it; `n_simulation` counts windows.
- `adapters/csv.py`: one file, one series, no run identity.
- `DatasetManifest`: `frequency` defaults to `"daily"`; no notion of run,
  seed-per-run, step-based time, or burn-in.
- `TestResult.n_simulation` and the report's "Windows" row both assume
  window counts.
- `compare.py` compares two sealed runs' *window distributions*.

## 4. What touches the sealed bundle and golden parity

Changing any of these breaks verification of already-shipped artifacts
(`docs/example-run`, `docs/example-update`, golden fixtures):

- **Pydantic models serialized inside `EvidenceBundle`** (`core/models.py`):
  adding even an optional field to `DatasetManifest`, `TestSuiteManifest`,
  `TestResult`, … changes `model_dump_json()` shape → changes
  `hashable_bytes` → old `bundle_hash` no longer recomputes. These models
  are therefore **frozen** for this migration.
- **Canonical serialization** (`core/serialization.py`) and
  `HASH_EXCLUDED_PATHS`: frozen.
- **Metric numerics** (`metrics/*`): pinned bit-for-bit by
  `tests/golden/test_metric_parity.py` against the research repo. Any
  refactor must preserve the exact float operation sequence.
- **Suite content** `suites/financial-daily/1.0.0/*`: covered by
  `suite_hash`; immutable.
- `provenance/bundle.py` seal/verify logic: behavior for existing bundles
  must not change (extensions may be added beside it).

Safe additive surfaces: new model classes in `core/models.py`, new enums,
new optional fields on `MetricSpec` (not serialized into bundles — suites
reference metrics as `id@major` strings), new modules, new CLI commands,
new suites under a new id, new schema files.

## 5. Backward-compatibility risks

| Risk | Mitigation |
|---|---|
| Old bundles fail `sieve verify` after model changes | Freeze all bundle-embedded models; new artifacts get **new** models (`InspectBundle`) and their own schema files |
| Golden metric parity breaks | Only additive refactors in `metrics/` (e.g. expose a per-lag curve the scalar already averages), identical op order, parity tests rerun |
| `financial-daily@1.0.0` drift | No file under `suites/financial-daily/` is touched; new suite id `financial-stylized-facts@0.1.0` |
| `sieve test` legacy CLI behavior changes | Legacy path untouched; new geometries are detected and routed, never silently coerced |
| Report template regressions | Legacy `report.html.j2` untouched; inspect gets its own template |
| Schema exports change | Additive only: new `InspectBundle.schema.json`, `FigureSpec.schema.json`, extended `MetricSpec.schema.json` (optional field with default) |

## 6. Old → new architecture map

| Concern | Today | After migration |
|---|---|---|
| Input | single `timestamp,return` CSV | `SimulationDataset`: multi-run, step- or timestamp-indexed, multiple observables; legacy CSV = Tier 0, unchanged |
| Time basis | implicit daily calendar | declared `timestamp` or `step`; no frequency inference |
| Return | required input column | input column **or** explicitly declared derivation from `price` (log/simple/diff), recorded as a transform |
| Burn-in | none | `burn_in_steps` / `burn_in_fraction` / per-run, recorded with before/after counts |
| Sampling unit | non-overlapping 1000-obs windows | declared geometry: `single_long_series`, `multi_run_ensemble`, `multi_market_panel`, `paired_runs`, `short_exploratory_series` |
| Metric gating | global MIN_WINDOWS | per-metric `MetricRequirements` (columns, geometries, min obs/run, min runs) → per-metric NOT_APPLICABLE / INSUFFICIENT |
| Modes | confirmatory `test` only | exploratory `inspect` (no PASS/FAIL) + confirmatory `test` (unchanged) |
| Evidence | numbers + statuses | numbers + statuses + versioned figure registry (static SVG, sealed) |
| Suite | `financial-daily@1.0.0` | plus `financial-stylized-facts@0.1.0` (exploratory, reference-free) |

## 7. Scope of this migration

### Implemented now

- **R1**: `SimulationDataset` + adapters (legacy CSV; `step,price` /
  `step,return`; long-format `run_id,...`; directory-of-runs with
  manifest; Python API `from_arrays` / `from_dataframe` / `from_runs`),
  explicit price→return conversion, burn-in, geometry declaration and
  validation, `MetricRequirements`, `sieve inspect`, sealed
  `InspectBundle` (+ `sieve verify` support), tests.
- **R2**: figure registry (`FigureSpec`) + 8 core diagnostic figures as
  dependency-free deterministic SVG (return/|return| path, marginal
  distribution, tail CCDF + Hill overlay, return ACF, volatility ACF,
  aggregation profile, leverage kernel, drift/variance-ratio diagnostic),
  sharing the *same* computation code as the scalar metrics.
- **R3 (partial)**: volume–volatility relation (implemented; NOT_APPLICABLE
  without a `volume` column). Conditional heavy tails, time-scale
  asymmetry and gain/loss first-passage are **registered as
  NOT_TESTED/planned** in the figure registry and the atlas doc — their
  estimator and sample-size requirements need scientific sign-off first
  (task §13: do not ship plausible-looking statistics).
- New exploratory suite `financial-stylized-facts@0.1.0`; multi-run ABM
  example `examples/abm_ensemble`; inspect HTML report (evidence atlas);
  research-first README; `docs/stylized-facts-atlas.md`; CHANGELOG.

### Deferred, with reasons

- **Confirmatory inference for `multi_run_ensemble` vs the shipped
  reference.** The reference is a distribution over 1000-obs *windows* of
  real indices; ensemble runs are a different sampling unit. Testing one
  against the other needs either a re-derived run-unit reference or an
  explicit hierarchical design. Faking it with the existing block-bootstrap
  would violate invariant §2-15. `sieve test` now *detects* ensembles and
  refuses with guidance to `sieve inspect`, recording why.
- **R4 paired-seed / intervention comparison.** Needs the ensemble
  confirmatory layer above as its substrate; manifest schema reserves
  `pair_id`/declared pairing so data collected now remains usable.
  (`sieve compare` for sealed window-runs is unchanged and keeps working.)
- **Conditional heavy tails (GARCH-standardized residuals)**: adds a model
  fit (new dependency + estimator risk); deferred behind an optional extra.
- **Time-scale asymmetry, gain/loss asymmetry**: definitions (aggregation
  horizons, threshold θ, censoring of non-passages) must be prespecified;
  registered as planned figures with references, not implemented ad hoc.
- **Interactive plots**: static SVG first (sealed, offline, deterministic);
  any future interactivity must remain CDN-free.

## 8. Status vocabulary for exploratory mode

`inspect` never emits PASS/FAIL. Its figure statuses are:

- `OBSERVED` — the diagnostic was computed and rendered from adequate data.
  It asserts *only* that the figure exists and what data it used — not that
  a stylized fact "holds".
- `INSUFFICIENT` — data volume below the figure's declared minimum; the
  card renders with the reason instead of a plot.
- `NOT_APPLICABLE` — a required column or geometry is absent (e.g. no
  `volume`).
- `NOT_TESTED` — the figure is registered but not implemented/enabled.
- `ERROR` — the diagnostic's *implementation* raised: a bug in sieve, never
  a statement about the data. The report is still written, the exception
  type is recorded in the sealed bundle, and `sieve inspect` exits 1.

No count, fraction, or aggregate over figure statuses appears anywhere.

## 9. Pre-release adversarial review (v0.4.0)

Before release, the full diff was reviewed by a five-dimension adversarial
workflow (seal compatibility, scientific correctness, input contract,
report/HTML, tests/invariants), each finding independently verified by a
refutation-first agent. Outcomes, all fixed and regression-tested in
`tests/unit/test_review_fixes.py`:

- **Seal**: undeclared identity defaults (dataset/model/run ids) were
  path-derived and leaked into the InspectBundle seal → now content-derived
  (`input:sha256:…`, constant `run-0` for bare CSVs); directory run-file
  names are hashed into `content_hash`, making run ids from filenames part
  of the *declared* identity.
- **Seal**: `sieve report` re-rendering differed byte-wise from the sealed
  report (dict key order) → all renders now go through the canonical
  (sorted-key) form; re-render is byte-identical and `verify` stays green.
- **Security**: report templates end in `.j2`, which
  `select_autoescape(["html"])` does not match — autoescape was OFF for all
  report templates (including the pre-existing confirmatory ones) → now
  unconditionally on; the inlined SVG keeps its explicit `|safe`.
- **Science**: the tail-CCDF pool was mean-centered while the Hill metrics
  run on raw returns (≈7% shift on the test fixture) → the tail figure now
  scales by sd only, so the overlay estimates the metric's quantity; y-axis
  labels corrected to the per-sign conditional survival actually plotted.
- **Science**: pooled volume–volatility bins could fabricate a cross-run
  relation from level differences (Simpson's paradox, demonstrated) → runs
  are per-run mean-normalized before pooling, disclosed on the figure.
- **Inputs**: manifest per-run `run_id`/`seed`/`burn_in_steps` that did not
  match a parsed run were silently dropped → declared run_ids now rename
  the run (single-run files only), unmatched keys are `InputError`s;
  `from_runs`/`from_arrays` gained the same `single_long_series` guard as
  the file adapter; `from_dataframe` supports `timestamp` columns instead
  of silently discarding them; burn-in + derivation that would leave zero
  rows is refused.

Refuted (no change): the Hill overlay's Weissman-form anchor is the
textbook estimator; timestamp-spacing irregularity detection would require
calendar inference (banned by invariant); pre-pivot sealed bundles were
demonstrated to verify byte-identically under the new code.
