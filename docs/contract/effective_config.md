# Effective config and the hash registry

Version: `0.1.0` · Status: draft for the 2026-08-22 freeze

The **effective config** is the configuration actually in force after
defaults, config files and CLI overrides have been resolved — not the file on
disk, not the defaults in code, and not the flags on the command line, but
what the run really used. This document is the authority for two things:

1. **the registry** — which keys enter which hash, at which domain version,
   and which formula id@version was in force for each formula slot;
2. **the conventions** that make a recorded number readable (uncertainty
   notation, CLI override resolution).

Nothing here duplicates the backlog: work items live in
`financial-abm-lab:docs/audit/BACKLOG.md`, dates live in the calendar, and
this file holds the contract content those two point at.

---

## 1. Why the registry exists

Two failures motivate it, both from the project's own record:

- A calibration constant lived as a code default in nine places. Changing it
  meant changing nine files, and the only trace was `git blame`
  (`BACKLOG.md`, Evidence Contract v0.1 item 1). If the value is an input
  artifact with a digest, the config hash moves and the hash chain detects it
  without anyone remembering to look.
- A fingerprint map that anyone can add a key to is a hash whose domain nobody
  controls: adding `hostname` to the map would silently invalidate every prior
  digest, and *removing* a key that mattered would silently stop detecting a
  real change. So the map is free, and the **domain is registered**.

The rule that follows:

> Adding a key to the `environment` map does **not** change any digest.
> Changing the registered domain **requires** bumping the domain version,
> which changes every downstream digest and is therefore visible.

---

## 2. Registry

### 2.1 Runtime fingerprint hash domain

`runtime_fingerprint_domain_version = 1`

Keys hashed into `effective_config.environment_fingerprint_digest`. Order is
irrelevant (canonical JSON sorts keys); membership is not.

<!-- registry:runtime_fingerprint_domain version=1 -->

| key | source in RunManifest v2 | type | why it is in the domain |
|---|---|---|---|
| `python` | `environment.python` | string | Interpreter version. Changes float formatting, dict ordering guarantees and stdlib behaviour. |
| `platform` | `environment.platform` | string | OS/arch. Changes libm, threading and, through BLAS selection, reduction order. |
| `numpy` | `environment.numpy` | string | The numerical stack under most of the computation. |
| `blas` | `environment.blas` | string | Reduction order in linear algebra; the usual reason a seal reproduces on one machine and not another. |
| `dependency_lock_digest` | `environment.dependency_lock_digest` | sha256 | Everything else, in one value. Reserved key, not a top-level field (Q2). |
| `rng_algorithm` | **top-level** `rng_algorithm` | string | The random stream is behaviour, not environment trivia — so it is a typed top-level field (Q2), and it is in this domain because a changed generator changes the run. |
| `rng_version` | **top-level** `rng_version` | string | Same, for the stream definition of that generator. |

Seven entries: five environment-map keys, two top-level fields. The domain
deliberately spans both — "which keys are hashed" is a question about the
domain, not about where a field happens to live in the document.

**Not in the domain, and why**: `hostname`, `user`, working directory, wall
clock, CI job id. Machine-local facts that do not change the science. They may
be recorded in `environment`; they will not move a digest. This mirrors the
existing seal's exclusion of the platform fingerprint and filesystem paths
(`sieve.core.models.HASH_EXCLUDED_PATHS`).

### 2.2 Behavior config hash domain

`behavior_config_domain_version = 1`

Keys hashed into `effective_config.behavior_config_hash`. Two runs with equal
`behavior_config_hash` are asserted to be behaviourally identical; that
assertion is the precondition of a same-engine semantic canary, so this domain
is the narrower and stricter of the two.

<!-- registry:behavior_config_domain version=1 -->

| key | source in RunManifest v2 | type | why it is in the domain |
|---|---|---|---|
| `config` | the resolved effective config document | object | The configuration itself, after overrides. |
| `seed_convention_version` | top-level `seed_convention_version` | string | B8. The master-seed → named-children derivation. At a fixed `master_seed`, changing the convention changes behaviour, so it must move the hash; recording only `master_seed` would hide it. |
| `rng_algorithm` | top-level `rng_algorithm` | string | A different generator is a different run at the same seed. |
| `rng_version` | top-level `rng_version` | string | Same, for the stream definition. |

`master_seed` is **inside** `config` and therefore inside this hash. Two runs
of one model at different seeds have different `behavior_config_hash` values —
which is correct: they are not expected to be identical, and a same-engine
exact canary between them would be a category error.

### 2.3 Formula registry

Formula slot → the id@version in force → the effective values it resolved to.
The point is that "which formula was used" is recorded as data, next to the
values it produced, rather than being recoverable only by reading the code at
the right commit.

<!-- registry:formula version=1 -->

| formula_id | version | effective values | defined in |
|---|---|---|---|
| `lob.mid_reference` | `1.0.0` | `floor((best_bid + best_ask) / 2)`; one-sided book → `best ± 1`; empty book → `initial_mid` | `fixtures/canary/_engine/min_lob_a.py::MinLobA._mid` |
| `stats.sample_variance` | `1.0.0` | `ddof = 1`, `method = two_pass` | `fixtures/canary/_engine/stats_vector.py::_variance` |
| `stats.sample_variance` | `1.0.0-naive` | `ddof = 1`, `method = naive` | same; used by `min-lob-b` to give the semantic fixture a real numerical tolerance |
| `lob.conservation_identity` | `1.0.0` | `submitted(side) = filled + cancelled + expired + terminal_resting` | `fixtures/canary/semantic-lob-min/fixture.json` |

A formula whose *effective values* differ between two runs is a difference in
what was computed, even when the `formula_id` matches. That is why the column
exists: `stats.sample_variance` at `ddof = 1` and at `ddof = 0` are not the
same estimator, and only the effective-values column says which one ran.

### 2.4 Bump rules

| change | required action | what makes it visible |
|---|---|---|
| add or remove a key in 2.1 | `runtime_fingerprint_domain_version` += 1 | every `environment_fingerprint_digest` changes |
| add or remove a key in 2.2 | `behavior_config_domain_version` += 1 | every `behavior_config_hash` changes |
| add a key to the `environment` map that is **not** in 2.1 | none | no digest moves — by design |
| change a formula's effective values | new `formula_version` | `formula_bindings` differs run to run |
| change the canonicalization rules | `schema_version` of the affected artifact | see `canonicalization.md` |

The asymmetry in rows 1–3 is the whole mechanism: the map is open, the domain
is closed, and only the closed part can move a hash.

---

## 3. Uncertainty convention

`BACKLOG.md`, Evidence Contract v0.1 item 2. Every `±` and every interval
must state, in the output **and** in the prose:

- whether it is an **SD** or an **SE**;
- the **ddof**;
- the **n**.

The failure this comes from: a `±` in an aggregate table was SD with
`ddof = 1`, discoverable only by reading the script, and a review nearly drew
the wrong identifiability conclusion from it.

`stats_vector_spec` carries this rule as `uncertainty_convention`, and the one
variance element in the canary declares `ddof = 1` in its element definition.

Corollary already in force in the audit prompts (rule 8b): **ratios and
percentages are more dangerous than differences**. If the difference is not
significant, the ratio is not reported; a reported ratio carries a CI.

---

## 4. CLI overrides resolve into the effective config

`BACKLOG.md`, Evidence Contract v0.1 item 3. An override flag such as
`--phi-ar1` creates a run that is off-spec with nothing checking it. Under
this contract:

1. every override resolves into the effective config **before** the config is
   hashed, so an overridden run has a different `effective_config_digest` and
   a different `behavior_config_hash` than the unoverridden one;
2. the full argv is recorded in `RunManifest.command` (outside the seal — it is
   machine-local — but **required to be present**);
3. the conformance profile compares the effective config against the spec's
   declared expectations; that comparison is the check that was missing.

Until the profile layer lands, the interim rule from the backlog stands: any
run that went through an override path keeps its argv-bearing output JSON.
