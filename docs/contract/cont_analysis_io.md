# Cont-type analysis harness — I/O and inspection definitions

Version: `0.1.0` · Status: draft for the 2026-08-22 I/O freeze

**Scope.** This document fixes the harness's input types, output types and
inspection definitions. It fixes **no threshold and no acceptance band**:
those are Week 3 preregistration material, and writing one here would
preregister it by accident. Where a definition needs a threshold to produce a
number, the number is left `null` with the reason attached — see
`shock_response.recovery_time` in the output example.

**Positioning.** Not redefined here. The claim this harness serves is
`financial-abm-lab:docs/audit/W1D1_claims_freeze.md` (v1.0) §1 A; the original
scale SESOI it feeds is the calendar §3.4; its place in the schedule is Week 3.
Both documents were recovered and merged to `main` on 2026-08-23, so these are
now live pointers rather than unverified ones.

Two consequences worth stating, because they bound what this harness is for:
the calendar §3.4 puts the first-choice SESOI on the **cumulative price
response (bp) to a one-standard-deviation innovation of the predictive
signal**, with the OFI/return power share and the depth-normalized impact as
auxiliary quantities — so OFI here is an *auxiliary* estimator, not the
headline. And §3.4 says SESOI is **not divided by a standard error**, which is
why nothing in this document turns an SE into a threshold.

**Reference implementation.** `tools/cont_harness_reference.py`. Standard
library only; consumes a conforming `EventLog` and emits the output document
below. Worked examples, regenerated from the committed canary fixture:
`examples/ContHarnessInput.example.json`,
`examples/ContHarnessOutput.example.json`.

---

## 1. Input

### 1.1 Event log

A conforming `EventLog` (`schemas/EventLog.schema.json`): header plus the
common 8 fields per event — `t`, `event_id`, `event_type`, `actor_id`,
`actor_role`, `side`, `price`, `quantity`.

**The unit of `t` is declared by the log header, never assumed.**
`time_unit ∈ {step, event, ns, us, ms, s}`, and `t` is integer-valued in that
unit. `interval` and `window` below are defined in *events* or *steps*, so a
harness run against an `ns` log and one against a `step` log are not
comparable and the output records which it was.

**Ordering.** The harness reads the log in **its own declared total order**
(`ordering.total_order_key`), never in an order the harness assumes. A log
declaring `t` as its total order key while admitting same-`t` ties is
**rejected with an error**, not silently sorted: OFI is defined on consecutive
book states, and an undefined order makes "consecutive" undefined. Gap **G4**,
resolved 2026-08-23.

### 1.2 Level-I state series

Best bid/ask price and size before and after each event.

**Route: whatever the log's `l1_availability` declares.** This harness requires
`inline`, and that is now a profile requirement rather than a preference
(`profile.l1_inline`, gap **G1** resolved 2026-08-23).

`l1` semantics, ratified 2026-08-23: it is the state the book **settled into
after the atomic operation**, shared by every event that operation produced.
Two normative invariants come with it — no silent Level-I change, and no
crossed snapshot — and the quantity of a limit order that comes to rest appears
in the `l1` of its own submit event. For a consecutive-pair estimator this
means one `e_n` per atomic operation rather than per fill leg, which is the
right granularity for a Level-I estimator: a sweep changes the best quote once,
net.

**Missing Level-I is counted, not skipped.** A pair where either side is empty
is excluded from the OFI sum and counted in
`coverage.excluded_missing_l1`. A coverage number that is not printed reads as
full coverage.

### 1.3 Harness parameters (types fixed)

| parameter | type | permitted values | meaning |
|---|---|---|---|
| `interval.kind` | enum | `fixed_event_count`, `fixed_step_count` | what one interval counts |
| `interval.size` | integer ≥ 1 | — | the count |
| `window.intervals` | integer ≥ 2 | — | intervals per window; one OLS fit per window |
| `depth.definition` | string | — | how depth is formed; the reference uses the window mean of `(bid_size + ask_size) / 2` |
| `depth.level` | integer ≥ 1 | `1` today | book level the depth is taken at |
| `shock.protocol` | enum | `market_order` | injection kind |
| `shock.side` | enum | `buy`, `sell` | injection side |
| `shock.size` | number > 0 | — | injected quantity, in the log's `quantity_unit` |
| `shock.injection_time` | integer | — | in the log's `time_unit`, which is restated in the parameter block |
| `shock.profile_events` | integer ≥ 1 | — | how many post-shock events the deviation profile covers |
| `sampling.spread_series` | string | — | sampling rule for the spread series |
| `sampling.depth_series` | string | — | sampling rule for the depth series |

Sampling is **event-driven, not clock-driven**. A clock-driven rule would need
an interpolation rule between events, and this contract does not define one;
declaring the sampling rule as event-driven is cheaper than defining
interpolation and is what the estimators actually want.

The parameter block is echoed verbatim into the output. A harness run whose
parameters are not recoverable from its output is the same failure mode as a
CLI override with no effective-config check.

---

## 2. Output

Every estimate carries a **standard error** and states its ddof and n
(`effective_config.md` §3). Reported uncertainties are SEs, not SDs, and say
so in the field.

### 2.1 Order flow imbalance

Cont, Kukanov and Stoikov (2014), *The price impact of order book events*,
Journal of Financial Econometrics 12(1). For consecutive book states
`n-1, n`:

```
e_n =  1{P^b_n >= P^b_{n-1}} q^b_n  -  1{P^b_n <= P^b_{n-1}} q^b_{n-1}
     - 1{P^a_n <= P^a_{n-1}} q^a_n  +  1{P^a_n >= P^a_{n-1}} q^a_{n-1}

OFI_k = sum of e_n over interval k
```

**Two variants, both retained:**

- `all` — every pair with Level-I on both sides. **Diagnostic.**
- `non_price_changing` — **primary**, per the calendar's Week 3 wording.
  Operational definition: a pair is non-price-changing iff, across the event,
  the best bid price **and** the best ask price are both unchanged.

**The exclusion happens at the `e_n` aggregation stage only.** `ΔP_k` is
computed over *every* event in the interval, so the two variants share one
dependent variable and their `β̂` are directly comparable. Excluding events
from `ΔP_k` as well would make them two different regressions with the same
name.

If a definition of either variant already exists in the repository docs, that
one is authoritative and this section is a restatement, not a redefinition. No
such definition was found at the time of writing.

### 2.2 Per-window regression

**Primary specification — with intercept** (ruling of 2026-08-20):

```
ΔP_k = α_i + β_i · OFI_k + ε_k     (ΔP in ticks, mid-price change over interval k)
```

Per window `i`: `α̂_i`, `β̂_i`, standard errors for both, centred `R²_i`, `n`,
`ddof = 2`.

The intercept is there because that is the equation Cont, Kukanov and Stoikov
estimate. Dropping it would make our `β̂` incomparable with theirs, and
comparability with theirs is the only reason to use their estimator rather than
one of our own. CKS report the intercept as small — **check the primary source
before that sentence is repeated anywhere load-bearing**; it is recorded here
as the reason for the specification, not as a result.

**Secondary specification — no intercept**, retained beside the primary one as
the proportionality diagnostic:

```
ΔP_k = β_i · OFI_k + ε_k
```

`ddof = 1`, uncentred `R² = 1 − RSS / Σy²`. It answers a different question —
is the relation proportional through the origin — and a disagreement between
the two specifications is informative about drift rather than about order flow.

Both specifications are reported for **both** OFI variants, so a reader never
has to work out which specification a number came from. The reported
uncertainty is a **standard error**, with its ddof and n in the record.

`ΔP_k` is the change in mid price across the interval, in **ticks**, taken
from the first and last Level-I state in the interval.

### 2.3 Depth-impact

```
D_i    = mean over window i of (q^b + q^a) / 2
β_i    = c / D_i^λ
log β̂_i = log c − λ log D_i + ν_i
```

Output: `λ̂`, its standard error, `log c`, `n`, `ddof = 2`.

Only windows with `D_i > 0` and `β̂_i > 0` enter the fit (the log demands it);
the number that entered is reported as `n`. The value CKS report for `λ` is
**not reproduced here** — it goes into the preregistration after checking the
primary source, not into an I/O document.

### 2.4 Spread and best-depth series and summaries

Series: spread, bid size, ask size, per sampled event. Summaries: `n`, mean,
SD (ddof = 1), SE (`sd/√n`), min, max — per series, with the `±` convention
stated in the field.

### 2.5 Shock response

- the injected event, **identified by `actor_role == "exogenous_harness"`**
  (gap **G2** — without that value the injection is indistinguishable from an
  agent's order and this whole section has no subject);
- `baseline_spread`: summary of the pre-shock spread, with n and SE;
- `deviation_profile`: `spread − baseline mean`, per post-shock event, over
  `shock.profile_events` events;
- `recovery_time`: **`null`, with the reason recorded**. It is the first
  return into a baseline band of `± ε`, and `ε` is a threshold → Week 3
  preregistration;
- `half_life`: **`null`**, same reason — the fit needs a declared band to
  define the deviation being halved.

---

## 3. Can these be expressed as `MetricSpec`? — No, in three specific ways

Checked against `sieve.core.models`. All three are recorded as gaps and as
backlog items; **no existing schema was changed** (that is outside the
approved scope).

**Resolved 2026-08-23 by placement**: the harness lives *beside* the metric
registry, with its own `ContHarnessInput` / `ContHarnessOutput` /
`ContHarnessParameters` schemas. `MetricSpec`, `TestResult` and
`MetricRequirements` are unmodified. The three underlying asymmetries below are
real and stay filed as backlog items — placement solved today's problem, not
the asymmetry.

| # | what does not fit | detail | gap |
|---|---|---|---|
| 1 | estimator parameters | `MetricSpec` has no `parameters` field (`BaselineSpec` does). `interval`, `window`, `depth`, `shock` would be invisible — the same "declared vs actually enforced" divergence the audit already recorded three times. | **G9** |
| 2 | the estimate + its SE | `TestResult` has `statistic_value`, `effect_size`, `ci_low`, `ci_high` — but **no `standard_error`**. The uncertainty convention requires SE with ddof and n; a CI cannot carry them. And one `TestResult` holds one scalar, so a per-window vector of `(β̂, SE, R²)` has no home. | **G10** |
| 3 | the input contract | `MetricRequirements` is column- and geometry-oriented (`required_columns`, `supported_geometries`, `minimum_observations_per_run`). An event log with a header, a declared time unit and a Level-I availability mode cannot be declared in it. | **G11** |

Consequence: the Cont harness outputs are **not** `TestResult`-shaped, and
pretending otherwise would either drop the standard errors or bury them in
`caveats` strings. The harness emits its own schema-validated output document.

---

## 4. Worked examples

- `examples/ContHarnessInput.example.json` — header, first events, parameter
  block.
- `examples/ContHarnessOutput.example.json` — the full output document.

**These numbers are a shape demonstration, not a finding.** The canary fixture
is a 40-step toy whose mid price barely moves: 5 price-changing pairs out of
328, so most `β̂` are exactly 0 and `λ` comes back `"not estimable"` with the
reason attached. That is the honest result for that input, and it exercises
the not-estimable paths — which is the more useful half of an I/O example.
**The canary fixture is not a valid test input for these estimators**, and no
number in the example should be read as one.
