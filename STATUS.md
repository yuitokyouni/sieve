# Status

Updated: 2026-08-09. Spec: `SIEVE_PRODUCT_IMPLEMENTATION_SPEC` v0.1 (§16
acceptance criteria; §22 ordered M0 → M1 only), then M1.5 (public
credibility release) inserted before M2.

## M0 — foundations: DONE

- [x] Package skeleton (`src/sieve`, `pyproject.toml`, `sieve` entry point)
- [x] Versioned schemas for every durable artifact (`core/models.py`,
      exported to `schemas/*.schema.json`)
- [x] Canonical serialization: sorted keys, compact, `\n`, non-finite
      forbidden, volatile fields nulled shape-preserving
      (`core/serialization.py`)
- [x] Two-layer seal + verify (`provenance/bundle.py`): deterministic
      scientific `bundle_hash` and sha256sum-compatible file sidecar
- [x] Seed protocol: master `SeedSequence` → named children, recorded in the
      run manifest (`provenance/environment.py`)
- [x] `sieve --help`, `sieve doctor`, `sieve schemas export`
- [x] M0 exit test: hand-authored bundle → seal → write → load → verify
      (`tests/unit/test_serialization.py`)

## M1 — offline golden path: DONE

`sieve test examples/csv_returns --suite financial-daily@1.0 --claim
descriptive-market-dynamics` deterministically produces `manifest.json`,
`observations.parquet`, `results.json`, `findings.json`,
`evidence_bundle.json`, `report/index.html`, `artifacts/`, `bundle.sha256` —
locally, offline, ~5 s.

- [x] Tier-0 CSV adapter with provenance-gap recording (`adapters/csv.py`)
- [x] 8 metrics migrated verbatim, with dimensions, known blind spots and
      POST_HOC disclosure (`metrics/`)
- [x] 6 baselines with declared mechanisms; frozen distributions shipped,
      parametric generators runnable from shipped per-index MLE parameters;
      bootstrap pair refuses to run without a local pool, explicitly
      (`baselines/`)
- [x] Calibrated inference: calendar-block bootstrap null, α = 0.01 line,
      Holm (suite-declared; BH also implemented) (`inference/`)
- [x] `financial-daily@1.0.0` suite: immutable content hash over manifest +
      shipped data; claim `descriptive-market-dynamics`
- [x] Ten-dimension profile with first-class NOT_TESTED / INSUFFICIENT;
      reproducibility scored from manifest completeness (`evaluation/profile.py`)
- [x] FAIL → findings with author questions (`evaluation/findings.py`)
- [x] HTML report in the spec §9.1 section order, POST HOC badges,
      baseline-context column, no aggregate anywhere (`reporting/`)
- [x] `sieve test/verify/report`, exit-code contract (eval ≠ exec failure)

## M1.5 — public credibility release: DONE (v0.1.0)

The bottleneck after M1 was no longer functionality; it was that nothing was
citable or inspectable by a third party without installing anything.

- [x] Standalone repository: `github.com/yuitokyouni/sieve`, canonical branch
      `main`, extracted from the research repo with full product history
      (`git subtree split`); sieve-bench linked as the research provenance
- [x] Seal scope corrected for cross-machine reproduction: platform
      fingerprint, filesystem paths and CLI invocation moved outside
      `bundle_hash` (they remain in the bundle under the file-integrity
      layer). Found by preparing the reproduction protocol, recorded in
      `docs/architecture.md`; regression tests added
- [x] Frozen browsable example: `docs/example-run/` (full run directory,
      committed; `sieve verify docs/example-run` passes in a fresh clone),
      report screenshot at the top of README
- [x] README leads with the result, not the install
- [x] Scope stated precisely: `financial-daily@1.0` assesses long-horizon
      daily return simulations; microstructure simulations need their own
      future suite (`market-microstructure@0.x`), not an adapter
- [x] `docs/reproduce.md`: the independent-reproduction protocol with
      expected statuses, `bundle_hash` and `suite_hash`
- [x] Tagged `v0.1.0` (source commit, suite hash, example bundle hash pinned
      in the tag annotation and CHANGELOG)

## v0.1.1 — pre-outreach corrections: DONE

Four review findings fixed before any external reproduction request; see
CHANGELOG 0.1.1. Notables: the parity claim is now CI-enforced against a
pinned sieve-bench checkout (`parity` job; skip → failure under
`SIEVE_RESEARCH_ROOT`), `constraints.txt` pins the reproduction
environment, the seal/package-version relationship is documented as
implemented, and the reference-period label matches the shipped windows.

### Acceptance criteria → tests

Test counts drift with every release, so no fixed number is pinned here —
`pytest` collects the authoritative set and CI runs it on every push (see
the CI workflow / badge). Skipped-by-design groups: parity tests run in
the CI `parity` job against a pinned sieve-bench checkout, and a small
number require locally fetched raw data. Compare gate:
`tests/integration/test_compare.py`.

| Criterion | Test |
|---|---|
| Determinism (same input+suite+seed → same seal) | `test_golden_path.py::test_deterministic_rerun` |
| Verification fails after modification | `::test_verify_detects_{artifact,bundle}_tamper` |
| Seed lineage recorded | `::test_seed_lineage_recorded` |
| Metrics reproduce research values bit-for-bit | `tests/golden/test_metric_parity.py` (synthetic + 124 real windows) |
| Suite ships frozen fixture bytes | `test_metric_parity.py::test_suite_ships_frozen_fixture_bytes` |
| Known-case metric behavior | `tests/unit/test_metrics.py` |
| Baseline mechanism smoke | `tests/unit/test_baselines.py` |
| No aggregate score | `tests/unit/test_no_score.py` |
| NOT_TESTED / INSUFFICIENT first-class | `::test_profile_has_first_class_not_tested`, `::test_insufficient_on_short_input` |
| POST_HOC visible in results + report | `::test_post_hoc_disclosure_reaches_results_and_report` |
| Offline | `::test_offline_no_network_modules_in_product` |
| CLI exit-code contract | `tests/unit/test_cli.py` |

## Not in M1/M1.5 (deliberately)

Tier-1/2 adapters, multiscale/regime/intervention dimensions (they appear as
NOT_TESTED, honestly), suite update tooling, any service component.
(`sieve compare` was also deferred here and later shipped in v0.2.0 — the
scenario-generator strategy supplied the concrete demand the deferral was
waiting for.)

## v0.2.0 — the change-approval gate (strategy: scenario generators)

Reframe adopted: Sieve evaluates scenario-generating models, one versioned
suite per use; ABMs are one kind of generator. Priority order and status:

1. **DONE — model-update regression case** (`sieve compare` +
   `examples/model_update` + frozen evidence in `docs/example-update/`).
   The case shows the gate catching a bad refit the reference test alone
   would have approved (acf_abs_1: halved, both versions PASS vs
   reference, CHANGED in direct comparison). v0.3.0 turned detection into
   approval: declared-parameter diff, per-metric transitions
   (REGRESSION / IMPROVEMENT / CHANGED_WITHIN_GATE / STABLE), a versioned
   routing policy over required dimensions (REVIEW_REQUIRED /
   NO_CHANGE_DETECTED — a rule, never a score), and a measured size for
   the A/B permutation design (tools/calibrate_compare.py,
   docs/compare-calibration.md) instead of a borrowed alpha claim. A
   provenance defect found by review is on record: the frozen v2 manifest
   declared beta unchanged while the generator used beta=0.80 — the seal
   was intact but sealed a false declaration; manifests and all frozen
   artifacts were regenerated, and the compare report now shows the
   declared diff next to the measured changes precisely so this class of
   mismatch is visible.
2. **NEXT — `esg-real-world` prototype** against the published NAIC
   scenario files and AAA acceptance criteria (needs the Tier-0.5
   multi-path monthly adapter; scoping in `docs/roadmap-esg.md`).
3. Hearings with life-insurance ERM/actuarial and insurance consultants,
   carrying both frozen artifacts.
4. LOB / system-wide ABM suites only with a concrete research partner.

## Next milestone: Independent reproduction #1 — not M2

Spec §13 orders M2 (compare + more claims) next, but a comparison feature
nobody external has touched adds no information. The open question is whether
an external researcher trusts this product contract, and code cannot answer
it. The milestone is therefore: one named third party, in a clean
environment, runs `docs/reproduce.md` end to end — clone, golden command,
`leverage_asymmetry = FAIL`, `sieve verify`, seal comparison — and we record
"Independently reproduced by X on YYYY-MM-DD" in the README. The sequence
after that stays credibility-first: external model evaluation #1 → external
author response #1 → community contribution #1 → private pilot #1.
(`compare` itself shipped in v0.2.0 once the scenario-generator strategy
made its user concrete; the reproduction milestone is unchanged.)

## Known limitations on record

- Reference dependence leaves ~6 independent calendar blocks: power against
  modest differences is limited, and every PASS carries that caveat.
- The example input FAILs `hill_left` as well as `leverage`: a single
  parameter set does not span the cross-index spread of the reference. Kept
  as-is — it demonstrates that distribution-over-windows testing is stricter
  than moment matching.
- `polars` writes `observations.parquet`; parquet bytes are not asserted
  byte-stable across polars versions (values are, via frame equality in
  tests; the deterministic seal covers results, not parquet bytes).

## M2 — research workbench (v0.4.0): DONE

Direction change to a research-first simulation validation workbench
(`docs/research-workbench-migration.md` records the audit, the freeze
surface, and the implemented/deferred split).

- [x] Generalized dataset contract: multi-run, step/timestamp time,
      explicit price→return, burn-in, sampling geometry, extra
      observables; Python API (`tests/unit/test_dataset.py`)
- [x] Per-metric input requirements (`MetricRequirements`), per-metric
      NOT_APPLICABLE/INSUFFICIENT without cross-contamination
- [x] `sieve inspect`: exploratory runs with sealed `InspectBundle`,
      no PASS/FAIL anywhere (`tests/integration/test_inspect.py`)
- [x] Figure registry + 9 deterministic SVG diagnostics sharing metric
      computation code, bit-consistency tested
      (`tests/unit/test_figures.py`); 3 registered NOT_TESTED roadmap
      figures (`docs/stylized-facts-atlas.md`)
- [x] Evidence-atlas HTML report: self-contained, offline, inlined SVG,
      per-card reading guides/caveats/parameters, no aggregate anywhere
- [x] Directional scientific tests on known processes
      (`tests/unit/test_scientific.py`)
- [x] New suite `financial-stylized-facts@0.1.0`; `financial-daily@1.0.0`
      untouched; old bundles verify unchanged; frozen examples
      regenerated for the version bump with byte-identical statuses
- [ ] Deferred (declared, not faked): confirmatory multi-run-ensemble
      inference vs the window reference; paired-seed/intervention
      comparison; conditional tails, time-scale asymmetry, gain/loss
      first-passage figures
