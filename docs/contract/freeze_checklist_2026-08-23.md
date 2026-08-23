# Freeze checklist — 2026-08-23

Planned for 2026-08-22; slipped one day (the 8/22 session was not run). State
at the end of the 2026-08-23 session. `○` met, `×` not met. Every `○` names the
artifact that makes it true; every `×` names what it is blocked on. Nothing is
marked met on the strength of a plan.

| # | item | | evidence / blocker |
|---|---|---|---|
| 1 | every §2.1 item resolved to a concrete field | **○** | `conformance_map.v1.json` — 26 items, `2.1-1a` … `2.1-9b`, each with an RFC 6901 pointer into `RunManifest` v2. Nine fields were new (`/engine/*`, `/effective_config/resolution_sources`, `/event_log_schema_version`, `/metric_suite/*`). Pinned by `test_resolution_map_covers_exactly_the_calendar_items` and `test_every_mapped_item_resolves_to_a_field_that_exists`. |
| 2 | canonicalization rules | **○** | `canonicalization.md` — four canonical forms, base byte rules, float quantization, volatile-field nulling, and the contract-digest / byte-digest split (G6). Pinned by `test_canonicalization_parity.py`. |
| 3 | hash-domain key list + domain version | **○** | `effective_config.md` §2.1 (7 keys) and §2.2 (2 keys, `rng_*` removed per the 2026-08-20 ruling), bump rules in §2.4. Enforced by `test_contract_hash_domain.py`, which parses the registry document rather than restating it. |
| 4 | EventLog types, units, enumerations | **○** | `EventLog.schema.json` `1.1.0`. The core set is the calendar's, not ours; header declares time/price/quantity units and the ordering guarantee; `if`/`then` per event type. Both engines validate. |
| 5 | route to Level-I state | **○** | G1 resolved: inline `l1`, profile-required for OFI/canary logs; `book_level` snapshots otherwise; reference reconstruction as an optional conformance check. Two normative `l1` invariants, both tested. |
| 6 | CanaryResult `mode` and payloads | **○** | `mode` discriminates a two-branch `oneOf`; verified to actually discriminate (an exact envelope carrying a semantic payload is rejected). |
| 7 | fixture format | **○** | `fixtures/canary/README.md` — three normative parts plus the tolerance-basis vocabulary. Two fixtures instantiate it; both carry real minted expectations. |
| 8 | Cont harness I/O types | **○** | `cont_analysis_io.md` + `ContHarnessInput` / `ContHarnessOutput` / `ContHarnessParameters` schemas + a self-validating reference implementation + two worked examples. No threshold anywhere; `recovery_time` and `half_life` are pinned to `null` by a schema `const`. |
| 9 | conformance profile FAIL item list | **○** | FAIL = every §2.1 item (26), no WARN items, in `conformance_map.v1.json`. Plus two profile requirements (`l1_inline`, `terminal_snapshot`) and one deliberately optional check (`reconstruction_agreement`). |
| 10 | `tests/golden/fixtures/` exclusion is stated in writing | **○** | Three places: the canary README, and a `not_derived_from` field in each `fixture.json` — machine-readable, travelling with the fixture rather than only with the prose. Also now in the contract's Scope section as an explicit exclusion. |

**10 of 10 met.** Yesterday's three blockers all cleared: items 1 and 9 were
blocked on the calendar original, which was recovered from
`origin/claude/w1d1-claims-freeze-revision-wubnix` and merged to `main` this
morning; item 5 was an open decision, now taken.

## What is knowingly *not* closed at the freeze

Recorded here so that "10 of 10" is not read as "nothing is open".

| | |
|---|---|
| **G7** — comparison-table strictness | deferred post-G0, with a reason. The canary keeps the strict table. |
| **Parquet content canonicalization** | no canonical form; a Parquet artifact cannot carry a contract digest. Costs nothing today because nothing binds to a byte digest. |
| **8/18 quarantine table** (`F8-R1`–`R3`) | absent from both repositories, every branch. The verification-scope note is preserved verbatim and applied nowhere. |
| **8/19 comparison table**, 20 items | absent. The 20-item check against this freeze could not be performed. |
| **The 2026-08-19 Level-I decision** | not located. G1 was resolved on the options as stated, not against it. |
| **Engine 1 exact fixture** | `pending_generation` by design — minted 2026-08-24 in a fixed container against the full runtime fingerprint domain. |
