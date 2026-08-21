# Canary fixtures

Two fixtures, one per canary mode, plus the machinery to run them. Standard
library only: no numpy, no scipy, no `sieve` import. A canary that needs the
numerical stack cannot be used to check the numerical stack, and a canary that
takes seconds to install cannot run on every push.

```
python3 fixtures/canary/run_canary.py            # run every fixture
python3 fixtures/canary/run_canary.py --mint     # re-mint expected values
python3 fixtures/canary/run_canary.py --out DIR  # write CanaryResult documents
```

Exit code is the verdict: `0` MATCH, `1` MISMATCH, `2` UNVERIFIABLE,
`3` PENDING_GENERATION. Both fixtures run in well under a second.

## `tests/golden/fixtures/` is not reused

Not in whole, not in part, not as a seed source. Those fixtures are the parity
harness against the research repository: they go red when the pinned research
commit moves, when the numerical stack changes, or when a metric is
re-derived. A canary sharing their inputs would go red for the same reasons
and add no independent signal — it would be a second thermometer taped to the
first. Everything these fixtures consume (engine, config, seed) is generated
for them and lives beside them.

## Fixture format: three parts

Every `fixture.json` has exactly three normative sections plus a `generation`
block. The three-part split is the point: it keeps "what must be true before
this check means anything" separate from "what the check asserts" separate
from "how much slack the assertion has, and why".

### 1. `precondition` — what makes the assertion applicable

| mode | precondition |
|---|---|
| `exact` | three-layer hash agreement: input, effective config, environment fingerprint |
| `semantic`, same engine / different environment | `behavior_config_hash` agreement |
| `semantic`, different engines | per-field comparison of the common surface (`ext.*` excluded), referenced by digest |

A failed precondition yields **UNVERIFIABLE**, never MISMATCH. That
distinction is not cosmetic: MISMATCH is a statement about the engine,
UNVERIFIABLE is a statement about the harness, and collapsing the two is how a
broken harness gets recorded as a broken model.

### 2. `assertion` — what must hold

`exact`: the canonicalized event log and the canonicalized `stats_vector` each
reproduce their expected sha256.

`semantic`: five families, every one of them computable from the common 8
fields alone — conservation, two-sided equality, no-crossing, sign/domain,
event count — plus element-wise `stats_vector` tolerance. Candidates that were
**not** adopted are listed in the fixture with a one-line reason; the two
rejections both come down to not wanting to freeze an open gap (G1, G5) into
the contract by habit.

### 3. `tolerance` — how much slack, and on what grounds

Every tolerance names a `basis`:

- `structural` — exact by construction (integer counts, integer lot quantities);
- `numerical` — floating-point or summation-order error, **with the magnitude
  stated**;
- `seed_variation` — spread across seeds of one configuration, with the `±`
  convention (SD or SE, ddof, n) stated;
- `provisional` — not yet derived from any of the above. A provisional
  tolerance may exist, but it must be labelled, and it cannot carry a claim.

Nothing here is `provisional`. The one non-trivial tolerance is on
`trade_price_variance`: `min-lob-a` computes the sample variance in two
passes, `min-lob-b` from the sum of squares, and on prices near 1000 the
second form loses about `4e-10 tick²` to cancellation. Observed difference at
minting: `3.82e-11`. Tolerance: `1e-8` — two orders of magnitude above what
was observed, and far below any difference that would mean the statistic
changed.

## The two fixtures are a pair, on purpose

`min-lob-b` is an independent implementation of the same market as
`min-lob-a`: flat list instead of price→FIFO map, sell fill leg emitted first,
snapshot walked in the other order, its own `ext.*` keys. Its log is
deliberately **not** byte-identical.

- the **exact** canary must reject it;
- the **semantic** canary must accept it.

If the semantic canary ever starts rejecting `min-lob-b`, the assertion set has
begun depending on representation rather than behaviour. That is the failure
this pair exists to catch, and it is not detectable with either fixture alone.

## What the fixtures were checked to catch

Verified by mutation on a scratch copy at authoring time (2026-08-21):

| mutation | verdict |
|---|---|
| `seed` changed in `config.json` | exact → UNVERIFIABLE (input + effective-config layers disagree) |
| mid-price rule shifted one tick, config byte-identical | exact → MISMATCH (output digest differs) |
| `min-lob-b` drops one unit of cancelled quantity | semantic → MISMATCH, naming `conservation.buy`, `conservation.sell`, and the two `cancelled_quantity` elements |
| `expected.json` removed | exact → PENDING_GENERATION |

The first row is the one worth keeping: a changed input does **not** report
the engine as wrong.

## Known sharp edge

The cross-engine comparison table records each common field's observed value
**domain** (the enum values seen, or the numeric min/max), and the
`CanaryResult` pins that table by digest so an assertion cannot drift away from
the table it rests on. The cost is that a legitimate change in either engine's
observed range invalidates the precondition rather than any assertion — the
mid-rule mutation above turns the semantic canary UNVERIFIABLE for exactly
that reason. For a fixed-seed, fixed-config canary that is the behaviour we
want. Whether the same table shape is right for a general cross-engine
conformance check is an open question for the 2026-08-22 review, not something
this fixture decided.

## Layout

```
spec/stats_vector_spec.v1.json   ordered element list, dtypes, scales, exclusions
_engine/rng.py                   splitmix64, specified by its arithmetic
_engine/canonical.py             canonicalization + sha256 + decimal quantization
_engine/stats_vector.py          common-surface summary; never reads ext.*
_engine/min_lob_a.py             reference engine
_engine/min_lob_b.py             independent engine, same behaviour
_engine/schema_check.py          dependency-free JSON Schema subset validator
exact-lob-min/                   fixture.json, config.json, expected.json
semantic-lob-min/                + common_surface_comparison.json
examples/                        one CanaryResult per mode, as emitted
run_canary.py                    runner and minter
```
