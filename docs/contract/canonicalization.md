# Canonicalization rules

Version: `0.1.0` · Status: draft for the 2026-08-22 freeze · Closes gap **G3**

A digest is a statement about bytes. Two people who agree on the object and
disagree on the bytes will disagree on the digest, and will spend a day
looking for a bug in the model. This document fixes the bytes, per hash
target. It is a prerequisite for the 2026-08-24 hash chain: a chain over
undefined canonical forms links nothing.

---

## 1. The base rules (all targets)

Identical to `sieve.core.serialization`, restated here because the contract
must be readable without reading the implementation, and pinned to it by
`tests/unit/test_canonicalization_parity.py`.

| rule | value | why not the alternative |
|---|---|---|
| encoding | UTF-8, `ensure_ascii=False` | escaping non-ASCII makes the bytes depend on a serializer setting nobody records |
| key order | sorted, recursively | insertion order is a property of the producer, not of the object |
| separators | `,` and `:` — no spaces | pretty-printing is a display choice; it must not reach the hash |
| line ending | one trailing `\n`, no others | a file with no trailing newline is a different file to half the tools that touch it |
| floats | shortest round-tripping repr, after quantization (§2) | full precision makes the digest hostage to the last bit of a division |
| non-finite | **forbidden** — `NaN`/`Inf` raise | they are not JSON; a value that cannot be serialized must become `null` plus a status upstream, where the reason is still known |
| volatile fields | set to `null`, not removed | removing changes the shape, so a nulled and an absent field would hash differently and the difference would mean nothing |
| integers | JSON integers, never floats | `1` and `1.0` are different bytes; quantities and tick prices are integers by contract |

**Nulling, not dropping**, is the rule that surprises people. A run id must
not enter the seal, but the *presence of a run-id field* must, or a producer
could quietly stop emitting it and no digest would move.

---

## 2. Floats: quantize before hashing

Every float that reaches a hash is first rounded to a declared number of
decimal places, half-to-even, through `Decimal(repr(x))`.

`repr` round-trips an IEEE-754 double exactly, so `Decimal(repr(x))` is the
exact decimal the double denotes; the rounding is then a pure function of the
double and no platform dependence enters. The number of places is declared per
element by `stats_vector_spec` (`scale`), never chosen at the call site.

Consequence, stated so nobody is surprised by it later: two runs whose
underlying doubles differ below the declared scale produce the **same** digest.
That is intentional. The scale is the declared resolution of the claim; a
difference below it is not a difference the artifact is asserting anything
about. Where a difference below the scale matters, the answer is to raise the
scale — visibly, with a `spec_version` bump — not to hash raw doubles.

---

## 3. Per-target canonical forms

Four forms. The name is recorded next to every digest
(`RunManifest.v2.outputs[].canonical_form`,
`CanaryResult.payload.observed.output_canonical_form`), so a digest never
travels without saying what it is a digest *of*.

### 3.1 `effective_config`

- **Object**: the resolved effective config, after defaults, files and CLI
  overrides (`effective_config.md` §4).
- **Volatile fields nulled**: none. If it is in the effective config it
  determines the run.
- **Digest field**: `effective_config.effective_config_digest`.
- **Related**: `behavior_config_hash` uses the same rules over the narrower
  domain in `effective_config.md` §2.2, and
  `environment_fingerprint_digest` over the domain in §2.1. Same bytes rules,
  different projections — which is why they are three fields and not one.

### 3.2 `event_log`

- **Object**: the whole `EventLog` document — header **and** events. The
  header is not decoration: `time_unit`, `price_unit`, `quantity_unit` and
  `ordering` are what make the event numbers mean anything, so a digest over
  the events alone would be a digest over ambiguous numbers.
- **Volatile fields nulled**: `log_id`.
- **Order**: the `events` array is hashed in `event_id` order, which is the
  log's declared total order (`ordering.total_order_key`). A producer that
  emits events out of `event_id` order must sort before hashing.
- **`ext.*` is included.** It is part of the log the engine produced, and the
  exact canary is a byte-reproduction check. `ext.*` is excluded from
  *comparison* (`stats_vector`, cross-engine tables), never from the log's own
  digest — those are different questions and it is worth keeping them apart.
- **JSON Lines variant**: line 0 is the header object without `events`, lines
  1..n are the events in `event_id` order, each canonicalized by the base
  rules. The document form and the JSONL form have **different digests**;
  whichever is used must be recorded as the canonical form. They are not
  interchangeable and this contract does not pretend they are.
- **Digest field**: `RunManifest.v2.outputs[].digest` with
  `canonical_form: "event_log"`.

### 3.3 `stats_vector`

- **Object**: exactly `{spec_id, spec_version, values}` — not the enclosing
  `CanaryResult`, and not the `digest` field itself.
- **`values` is positional** and must follow `stats_vector_spec.elements`
  exactly. Reordering requires a `spec_version` bump, which changes the digest.
- **Excluded by construction**: `ext.*`, and the provisional fields `seq`,
  `cause_event_id`, `order_id`, `l1`. A statistic resting on a provisional
  field would freeze an open gap into the contract by habit.
- **Floats**: quantized per element `scale` (§2) before hashing.
- **Digest field**: `CanaryResult.stats_vector.digest`.

### 3.4 `output_table`

- **Object**: a tabular result serialized as
  `{"columns": [...], "rows": [[...], ...]}` — column names in declared order,
  rows in the table's declared sort order.
- **Row order is part of the digest.** A table whose row order is not declared
  cannot be canonicalized; declare a sort key or do not hash it.
- Reserved for the Cont harness outputs (`cont_analysis_io.md`); no artifact
  uses it yet.

### 3.5 `bundle`

Unchanged and out of scope here: `EvidenceBundle` keeps its existing rules and
its existing `HASH_EXCLUDED_PATHS`. This document does not touch the sealed
bundles that already exist.

---

## 4. What is deliberately *not* fixed yet

- **Parquet / binary observation files.** Only their file bytes are hashed
  (`sha256_file`), not a canonical form of their contents. Two writers
  producing semantically identical Parquet will disagree. Recorded as an open
  item rather than papered over.
- **The JSONL vs document choice for event logs.** Both are defined; which one
  a conforming producer must emit is a profile decision, not a bytes decision.
