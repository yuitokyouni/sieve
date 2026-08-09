# Changelog

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
  0.98); |Δβ| ≤ 0.04 persistence drifts and a lone tail-df clip are mostly
  invisible, and the reports say so (`docs/compare-calibration.md`).
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
