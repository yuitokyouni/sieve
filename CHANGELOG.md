# Changelog

## 0.1.1 — 2026-08-09

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
