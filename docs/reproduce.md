# Reproduce the example result

This is the protocol we ask independent reproducers to run. It takes about
five minutes, uses no network after install, and ends with two checks: the
statuses and the scientific seal.

## Environment

Any OS. Python ≥ 3.11. `constraints.txt` (committed) pins the exact package
versions the frozen example was sealed with — install with it for the
byte-exact seal check. Key pins:

| package | version |
|---|---|
| numpy | 2.4.6 |
| scipy | 1.17.1 |
| pydantic | 2.13.4 |
| polars | 1.43.2 |

Without the constraints (newer packages), the statuses should still
reproduce; the byte-exact `bundle_hash` is guaranteed only under the pinned
numerical stack. Versions are recorded in the bundle's environment
fingerprint but deliberately not hashed into the seal — a dependency change
is detected exactly when it changes a measured value
(`docs/architecture.md`).

## Steps

```
git clone https://github.com/yuitokyouni/sieve
cd sieve
python -m venv .venv && . .venv/bin/activate
pip install -e . -c constraints.txt      # or: uv pip install -e . -c constraints.txt

# 1. integrity of the shipped example, without running anything
sieve verify docs/example-run

# 2. rerun the golden path from scratch (offline, ~5 s)
sieve test examples/csv_returns --suite financial-daily@1.0 \
      --claim descriptive-market-dynamics --out /tmp/sieve-runs

# 3. verify your own run
sieve verify /tmp/sieve-runs/<run-id>
```

## Expected results

The validation profile printed by step 2 (and in `report/index.html`):

| dimension | status |
|---|---|
| marginal_distribution | PASS |
| tail_behavior | **FAIL** |
| return_dependence | PASS |
| volatility_dynamics | PASS |
| leverage_asymmetry | **FAIL** |
| multiscale_behavior | NOT_TESTED |
| drift_nonstationarity | PASS |
| regime_response | NOT_TESTED |
| intervention_validity | NOT_TESTED |
| reproducibility_provenance | WARN |

The two FAILs are the point of the example: the input is a GARCH(1,1)-t
sample, and `leverage_asymmetry` is exactly the mechanism GARCH does not
contain; the left-tail FAIL shows a single parameter set not spanning the
cross-index reference spread.

The scientific seal in `evidence_bundle.json` (`bundle_hash`) and printed by
`sieve test`:

```
43b88e5f166bba0fe5ede860afdf9b3132c44e4a3cc198e6b5f551d9b9549cd4
```

The suite hash recorded in the same bundle (`suite.suite_hash`):

```
343042f8ceedf18ad2f62eae54501e1e73b8ab59db836804f88fe42105911c9f
```

Your `run_id`, timestamps and machine fingerprint will differ — they are
outside the seal by design (`docs/architecture.md`).

## Reproductions on record

Machine-independent reproductions of the seal above, before any external
request was made:

- **Continuous:** every CI push reruns the golden path on a fresh
  `ubuntu-latest` runner (a machine that never touched the sealing
  environment) and asserts its `bundle_hash` equals the committed example's
  — the "seal reproduces on this machine" step in
  `.github/workflows/test.yml`, visible per-run in the Actions tab.
- **2026-08-09, reproduction #0** (self, pre-outreach): fresh network clone
  + fresh venv + `constraints.txt`; statuses, both integrity layers and the
  byte-exact seal reproduced. Verbatim log:
  [`docs/reproductions/2026-08-09-repro0.md`](reproductions/2026-08-09-repro0.md).
  Performed at v0.1.1 (seal `bad5cb04…` as logged); the seal pins the sieve
  version, so the current expected seal above differs from that run's.
- Named third-party reproductions will be listed here as they happen.

## If something does not match

That is a result, and we want to hear it: please open an issue with your
`results.json`, `manifest.json` (it contains the environment fingerprint)
and OS. A reproduction failure under matching package versions would be a
bug in Sieve's determinism contract, which is exactly what this protocol
exists to catch.
