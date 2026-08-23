# Freeze checklist — 2026-08-22

State at the end of the 2026-08-21 session. `○` met, `×` not met.
Every `○` names the artifact that makes it true; every `×` names what it is
blocked on. Nothing is marked met on the strength of a plan.

| # | item | | evidence / blocker |
|---|---|---|---|
| 1 | every §2.1 item resolved to a concrete field | **×** | **Blocked on a missing source.** The calendar original defining §2.1 is not in either repository, so the ten items are unknown. The *field* side is complete (`evidence_contract_v0.1.md` §7 Table A) and the machine-readable container exists (`RunManifest.v2.conformance_map`); only the item list is missing. Left blank rather than reconstructed. |
| 2 | canonicalization rules | **○** | `canonicalization.md` — base byte rules plus a defined canonical form per hash target (`effective_config`, `event_log`, `stats_vector`, `output_table`), float quantization rule, volatile-field nulling rule. Pinned by `tests/unit/test_canonicalization_parity.py`. Two items explicitly left open there (→ G6). |
| 3 | hash-domain key list + domain version | **○** | `effective_config.md` §2.1 (7 keys, `runtime_fingerprint_domain_version = 1`) and §2.2 (4 keys, `behavior_config_domain_version = 1`), with bump rules in §2.4. Enforced by `tests/unit/test_contract_hash_domain.py`, which parses the registry document rather than restating it. |
| 4 | EventLog types, units, enumerations | **○** | `schemas/EventLog.schema.json`. Common 8 fields required on every event; `time_unit`, `price_unit`, `quantity_unit` and `ordering` declared in the header and required; enumerations for `event_type`, `actor_role`, `side`. Both canary engines validate against it. **Caveat:** the `actor_role` value `exogenous_harness` is a recommendation pending G2, and `l1` / `seq` / `cause_event_id` / `order_id` are marked provisional pending G1/G4/G5. |
| 5 | route to Level-I state | **×** | **Gap G1, open.** Recommendation recorded with costs and consequences (inline `l1` for OFI-bearing logs, `book_level` snapshots otherwise). The 2026-08-19 decision this was to be checked against could not be located in either repository. The header field `l1_availability` lets a log declare its route, so the schema does not block on the decision — but the decision is not made. |
| 6 | CanaryResult `mode` and payloads | **○** | `schemas/CanaryResult.schema.json`. `mode` discriminates a two-branch `oneOf`; the common envelope (fixture ref + version, engine identity, verdict, `stats_vector`) is required in both. Verified to actually discriminate: an exact envelope carrying a semantic payload is rejected (`test_canary_result_mode_selects_exactly_one_payload_branch`). |
| 7 | fixture format | **○** | `fixtures/canary/README.md` — three normative parts (precondition / assertion / tolerance) plus a generation block, with the tolerance-basis vocabulary (`structural`, `numerical`, `seed_variation`, `provisional`). Two fixtures instantiate it; both carry real minted expectations, no placeholders. |
| 8 | Cont harness I/O types | **○** | `cont_analysis_io.md` — input types (event log, Level-I series, twelve typed harness parameters), output types (all estimates with SE, ddof, n), plus a runnable reference implementation (`tools/cont_harness_reference.py`) and two worked example documents. No threshold and no acceptance band anywhere in it, by design. |
| 9 | conformance profile FAIL item list | **×** | **Gap G8, open**, and blocked on the same missing source as item 1: the FAIL list is a statement about the §2.1 items. The schema plumbing is in place (`conformance_map.items[].status ∈ {SATISFIED, WARN, FAIL, UNVERIFIABLE}`), so writing the profile will not reopen the schema. |
| 10 | `tests/golden/fixtures/` exclusion is stated in writing | **○** | Three places: `fixtures/canary/README.md` ("`tests/golden/fixtures/` is not reused"), and a `not_derived_from` field in each of the two `fixture.json` files — so the exclusion is machine-readable and travels with the fixture, not only with the prose. |

**7 of 10 met.** The three that are not met are two distinct blockers:

- **items 1 and 9** — one missing source document. Both are mechanical once the
  §2.1 item list is available; neither needs new design.
- **item 5** — a genuine open decision (G1), with the options, costs and a
  recommendation on the table for the review.

Neither blocker touches the floor: the three schemas and the exact canary
fixture are complete, and the 2026-08-24 hash chain has committed digests to
consume.
