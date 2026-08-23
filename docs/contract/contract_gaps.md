# Contract gaps

Version: `0.1.0` · For the 2026-08-22 review

Each entry is either **documented** (a pointer, nothing restated) or **open**
(options, a recommendation, and one line of grounds). Nothing here is silently
resolved by leaning on `ext.*`: an engine-private extension is not a contract,
and a consumer that reads one has made a private arrangement with one engine.

| id | subject | status |
|---|---|---|
| G1 | Level-I state | **open** — recommendation below, and the 2026-08-19 decision could not be located |
| G2 | `actor_role` for harness injection | **open** — recommended value already emitted by the fixtures |
| G3 | canonicalization | **documented** → `canonicalization.md` |
| G4 | time and ordering | **open** — recommendation below |
| G5 | terminal state / per-order identity | **open (new, found this session)** |
| G6 | binary observation files | **open (new)** |
| G7 | comparison-table strictness | **open (new)** |
| G8 | conformance profile FAIL list | **open** — the schema layer deliberately does not decide it |
| G9 | `MetricSpec` cannot declare estimator parameters | **open (new)** |
| G10 | `TestResult` has no `standard_error`, and holds one scalar | **open (new)** |
| G11 | `MetricRequirements` cannot express an event-log input contract | **open (new)** |

---

## G1 — Level-I state

**Question.** How does a consumer obtain best bid/ask price and size from a
conforming event log? Order-flow imbalance is defined on *consecutive Level-I
states*; without a route from the common 8 fields to L1, the Cont harness has
no input and the semantic canary cannot assert non-crossing per event.

**Status: could not be confirmed.** The brief asks to check the 2026-08-19
decision on "the common fields Level-I OFI needs". That decision is not in
either repository: no calendar original is present, and no document under
`sieve/docs/` or `financial-abm-lab/docs/` states it. Treated as **not
documented** rather than assumed — see the question list.

**Options.**

| | option | cost | consequence |
|---|---|---|---|
| (a) | add the four L1 fields to every event, required by profile | +4 fields on every event; log size grows with event count | O(1) per event; OFI reads directly; **the only option that supports per-event OFI without a replay** |
| (b) | define a reference book reconstruction in the contract and make it a conformance test | no log growth | every consumer replays; the contract now owns matching semantics (price-time priority, self-trade, tie-break) — a large surface, and a bug in it is a silent bug in every estimator |
| (c) | a separate record type for book state | clean separation | a second stream to align; the alignment is G4 again |
| (d) | periodic `book_level` snapshot events, using only the common 8 fields | O(depth) per snapshot | sufficient for conservation and non-crossing **at snapshot times**; not sufficient for per-event OFI |

**Recommendation: (a) for logs that will feed OFI, (d) for everything else.**
Grounds: (a) is the only option whose cost is O(1) per event and whose
correctness does not depend on the contract getting matching semantics right,
and (d) costs nothing new — the canary already closes the quantity-conservation
identity with `book_level` events built from the common 8 fields alone, so (d)
is available today at zero contract surface.

**Provisional state in the schema.** `EventLog.$defs.Event.l1` exists, is
marked provisional, and is emitted by both canary engines; the header field
`l1_availability` declares which of `inline` / `snapshot` / `reconstruct` /
`none` applies. Provisional means: a consumer may not require it until this
gap closes.

**Definition that must close with it** (currently stated only in the schema
description): for `order_submit`, `l1` is the **pre-trade** state the order
met; for every other event type it is the state **after** the event. The
asymmetry is deliberate — causes precede effects in the total order, so a
marketable submit must be emitted before its fills, and at that moment the
book has not yet moved — but it is a decision that has to be ratified rather
than absorbed.

---

## G2 — `actor_role` for harness injection

**Question.** Does `actor_role` have a value meaning "injected by the harness,
exogenous to the model"? Without one, the shock order of a shock-response
protocol is indistinguishable from an agent's order, and the estimator has no
way to condition on the known exogenous input.

**Status: not documented.** No enumeration of `actor_role` values exists in
either repository.

**Options.** (i) add `exogenous_harness` to the enumeration; (ii) leave
`actor_role` free-text and let each harness pick; (iii) mark injection in
`ext.*`.

**Recommendation: (i).** Grounds: (ii) makes cross-engine comparison
impossible for exactly the field whose purpose is cross-engine comparison, and
(iii) puts the identifiability of the treatment variable inside an
engine-private namespace — the estimator would then depend on an engine's
private convention while claiming to be engine-neutral.

Already emitted: both canary engines tag the injected market order
`actor_role: "exogenous_harness"`, so the recommendation has a worked example
rather than only a paragraph. This also matters beyond the shock: the backlog's
local-projection plan (Week 3) conditions on a **known exogenous** input, and
that plan needs the injected event to be identifiable in the log.

---

## G3 — Canonicalization

**Documented** as of this session: `canonicalization.md`, per hash target
(`effective_config`, `event_log`, `stats_vector`, `output_table`), with the
base byte rules and the float-quantization rule. Two items are explicitly left
open there (binary observation files → G6; JSONL vs document form as a profile
choice).

---

## G4 — Time and ordering

**Question.** How are events sharing a timestamp ordered, and how does that
relate to `cause_event_id`?

**Status: not documented.**

**Options.** (i) `event_id` is the total order, monotone, and same-`t` order is
the `event_id` order; (ii) a separate `seq` field within each `t`;
(iii) leave it undefined and require consumers to sort by a declared key.

**Recommendation: (i), with `seq` retained as an optional, declared
convenience.** Grounds: OFI is defined on *consecutive* states, so the log
must have a total order that survives any transform, and a second ordering key
is a second thing that can disagree with the first. The header's `ordering`
object makes the choice explicit per log (`total_order_key`, `t_monotonic`,
`tie_break`, `causality`) instead of leaving it to be inferred.

**Causality constraint that must close with it**: `cause_event_id` must refer
to a **smaller** `event_id`. Currently stated in the schema description and
satisfied by both engines; not yet enforced by a conformance test.

---

## G5 — Terminal state and per-order identity *(new, found this session)*

**Found by** trying to write the quantity-conservation assertion for the
semantic canary from the common 8 fields alone.

**The problem.** `submitted = filled + cancelled + expired + still-resting` does
not close, because "still resting" is a property of the terminal book, and no
common-surface record carries it. The per-order form of the identity does not
close either: `order_id` is not among the common 8 fields, so `submit` and its
`fill`/`cancel` cannot be linked.

**How the canary works around it, today.** The terminal book is emitted as
`book_level` events — one per (side, price) — which uses only `side`, `price`
and `quantity`, i.e. only the common 8. The aggregate per-side identity then
closes exactly, and it does so for both engines. No new field, no `ext.*`.

**Options.** (i) require a terminal snapshot in the profile (works today);
(ii) promote `order_id` to the common surface, which gives the stronger
per-order identity and also gives cancels an unambiguous referent;
(iii) both.

**Recommendation: (iii), with (i) first.** Grounds: (i) costs nothing and
closes the aggregate identity now; (ii) is what makes "this cancel withdrew
*that* order" checkable, which no aggregate identity can express — but it
widens the common surface, so it deserves the review rather than a default.

---

## G6 — Binary observation files *(new)*

`observations.parquet` and friends are hashed as file bytes only. Two writers
producing semantically identical Parquet — different compression, different row
group size, different writer version — produce different digests, so a
cross-machine reproduction can fail for a reason that is not a scientific
difference. No canonical form is defined. **Recommendation:** either declare
the writer and its settings as part of the environment fingerprint domain, or
define a canonical tabular form (`output_table`) and hash that instead of the
file. Not decided here; recorded so it is not discovered on 2026-08-24.

---

## G7 — Comparison-table strictness *(new)*

The cross-engine comparison table records each common field's observed value
**domain** (enum values seen, or numeric min/max) and the `CanaryResult` pins
the table by digest, so an assertion cannot drift from the table it rests on.
The cost: a legitimate change in either engine's observed range invalidates the
*precondition* rather than any assertion. Verified at authoring time — a
one-tick change to the mid rule turns the semantic canary UNVERIFIABLE, not
MISMATCH.

For a fixed-seed, fixed-config canary that is the behaviour we want. Whether
the same table shape is right for a general cross-engine conformance check is
open. **Options:** (i) keep domains in the table, accept re-minting;
(ii) split the table into a *compatibility* half (field presence, type, unit —
stable) and an *observed* half (domains — informational, not hashed);
(iii) hash only the compatibility half. **Recommendation: (ii)**, deferred —
it changes what "precondition" means, which is a review decision.

---

## G8 — Conformance profile FAIL list

Q1 settles that the schema stays permissive and the profile decides severity.
The profile itself does not exist yet: which items are FAIL, which are WARN,
and which profiles there are (`strict` / `research` / …) is undecided. The
schema already carries the plumbing — `conformance_map.items[].status ∈
{SATISFIED, WARN, FAIL, UNVERIFIABLE}` — so the profile can be written without
touching the schema again.

**This is a hard blocker for the 2026-08-22 freeze checklist item "conformance
profile FAIL item list", and it is blocked on the same missing source as the
§2.1 resolution table.** See the question list.

---

## G9 — `MetricSpec` cannot declare estimator parameters *(new)*

**Found by** checking whether the Cont harness outputs are expressible as
`MetricSpec` (`cont_analysis_io.md` §3).

`MetricSpec` has no `parameters` field; `BaselineSpec` does. So `interval`,
`window`, `depth` and the shock protocol — every knob that changes what the
estimator computes — would be invisible in the spec while being very much
present in the run. That is the project's recurring failure shape: a declared
standard and an enforced standard drifting apart, with only the code knowing
which one ran.

**Options.** (i) add `parameters: dict[str, JsonValue]` to `MetricSpec`,
mirroring `BaselineSpec`; (ii) keep harness parameters in the harness output
document only; (iii) model the harness as a suite-level object rather than a
metric.

**Recommendation: (i).** Grounds: it is the smallest change, it makes the
parameters enter `suite_hash` the way baseline parameters already do, and the
asymmetry between `MetricSpec` and `BaselineSpec` looks like an oversight
rather than a decision. **Not done here** — modifying an existing schema is
outside the approved scope. Filed to the backlog.

---

## G10 — `TestResult` cannot carry an SE, or a per-window vector *(new)*

`TestResult` has `statistic_value`, `effect_size`, `ci_low`, `ci_high` — and
no `standard_error`. The uncertainty convention (`effective_config.md` §3)
requires an SE with its ddof and n; a confidence interval carries neither.
Separately, one `TestResult` holds one scalar, so the per-window vector of
`(β̂_i, SE_i, R²_i)` has no home: it would have to be flattened into one
`TestResult` per window with the window index hidden in `test_id`, or
serialized into `caveats` as a string.

**Options.** (i) add `standard_error`, `ddof` and `n_estimate` to
`TestResult`; (ii) let the harness emit its own output document and reference
it from `artifact_refs`; (iii) both.

**Recommendation: (iii), with (ii) already in force.** The harness emits its
own document today, which is what makes the 2026-08-22 I/O freeze possible
without touching a sealed schema. (i) is the durable fix and belongs to the
same review as G9.

---

## G11 — `MetricRequirements` cannot express an event-log input *(new)*

`MetricRequirements` is column- and geometry-oriented: `required_columns`,
`supported_geometries`, `minimum_observations_per_run`,
`requires_regular_spacing`. An `EventLog` input contract is none of those — it
is a header (declared time unit, price unit, ordering guarantee, Level-I
availability) plus a typed event stream. Declaring "this metric needs a log
whose `ordering.tie_break` is not `undefined` and whose `l1_availability` is
`inline`" is not expressible.

**Options.** (i) add an `input_kind` discriminator to `MetricRequirements`
with an event-log branch; (ii) a separate requirements type for event-stream
metrics; (iii) leave event-stream estimators outside the metric registry
entirely.

**Recommendation: (i) or (ii), decided together with G9/G10** — they are one
question about whether event-stream estimators live inside the metric registry
or beside it, and answering them separately will produce three
half-compatible answers.
