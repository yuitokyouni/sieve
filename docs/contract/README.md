# Evidence Contract v0.1 — contract documents

Normative prose for the schemas approved on 2026-08-20. Work items live in
`financial-abm-lab:docs/audit/BACKLOG.md`; dates and gates live in the
calendar. This directory holds the contract content those two point at, and
duplicates neither.

| document | scope |
|---|---|
| `evidence_contract_v0.1.md` | the package; B5, Q1, Q2, B8; canary placement; the §2.1 → field resolution table |
| `effective_config.md` | the registry — hash domains and their versions, the formula registry, uncertainty and CLI-override conventions |
| `canonicalization.md` | the bytes, per hash target (gap G3, closed) |
| `cont_analysis_io.md` | Cont-type harness input/output types and inspection definitions — no thresholds |
| `contract_gaps.md` | G1–G11: documented, or options + recommendation + grounds |
| `freeze_checklist_2026-08-22.md` | the freeze conditions, ○/× with evidence |

Schemas: `../../schemas/RunManifest.v2.schema.json`,
`EventLog.schema.json`, `CanaryResult.schema.json`.
Fixtures: `../../fixtures/canary/`.
Worked examples: `examples/`.

Reproduce everything runnable in this directory:

```
python3 fixtures/canary/run_canary.py                       # both canaries
python3 tools/cont_harness_reference.py --out docs/contract/examples
python -m pytest tests/unit/test_contract_canary.py \
                tests/unit/test_contract_hash_domain.py \
                tests/unit/test_canonicalization_parity.py -q
```
