#!/usr/bin/env python3
"""Run a canary fixture and emit a CanaryResult.

    python3 fixtures/canary/run_canary.py --all
    python3 fixtures/canary/run_canary.py --fixture exact-lob-min --out /tmp/c
    python3 fixtures/canary/run_canary.py --fixture semantic-lob-min --mint

Standard library only. Exit codes are the verdict, so CI needs no parsing:
0 every fixture MATCH, 1 some MISMATCH, 2 some UNVERIFIABLE, 3 some fixture
still at PENDING_GENERATION.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

from _engine import stats_vector as sv                       # noqa: E402
from _engine.canonical import canonical_bytes, digest, digest_file  # noqa: E402
from _engine.min_lob_a import MinLobA                        # noqa: E402
from _engine.min_lob_b import MinLobB                        # noqa: E402
from _engine.rng import ALGORITHM as RNG_ALGORITHM           # noqa: E402
from _engine.rng import VERSION as RNG_VERSION               # noqa: E402
from _engine.schema_check import validate                    # noqa: E402

ENGINES = {"min-lob-a": MinLobA, "min-lob-b": MinLobB}
COMMON_FIELDS = ("t", "event_id", "event_type", "actor_id", "actor_role",
                 "side", "price", "quantity")
CANARY_SCHEMA = os.path.join(REPO, "schemas", "CanaryResult.schema.json")
EVENTLOG_SCHEMA = os.path.join(REPO, "schemas", "EventLog.schema.json")
MINTED_ON = "2026-08-21"


def _load(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path: str, data) -> None:
    with open(path, "wb") as fh:
        fh.write(canonical_bytes(data))


def _environment_fingerprint(engine_id: str, engine_version: str) -> dict:
    """The REGISTERED domain for these fixtures, and only that.

    The interpreter version is deliberately outside it: the engines are exact
    integer arithmetic plus Decimal quantization, so no interpreter-version
    dependence should exist. That is a claim, not an assumption — the CI
    matrix runs 3.11 and 3.12 against one expected digest, so if the claim is
    wrong the exact canary says MISMATCH and we find out.
    """
    return {"engine_id": engine_id, "engine_version": engine_version,
            "rng_algorithm": RNG_ALGORITHM, "rng_version": RNG_VERSION}


def _run_engine(spec: dict, config: dict):
    engine = ENGINES[spec["engine_id"]](config)
    document = engine.run()
    errors = validate(document, EVENTLOG_SCHEMA)
    if errors:
        raise AssertionError("engine produced a non-conforming EventLog:\n"
                             + "\n".join(errors))
    stats = sv.compute(document,
                       variance_method=spec.get("stats_variance_method",
                                                "two_pass"))
    return document, stats


def _stats_payload(stats: dict) -> dict:
    body = {"spec_id": stats["spec_id"], "spec_version": stats["spec_version"],
            "values": stats["values"]}
    return {**body, "digest": digest(body, "stats_vector")}


# ---------------------------------------------------------------- exact ----
def run_exact(directory: str, mint: bool) -> dict:
    fixture = _load(os.path.join(directory, "fixture.json"))
    config_path = os.path.join(directory, fixture["subject"]["config_path"])
    config = _load(config_path)
    subject = fixture["subject"]

    document, stats = _run_engine(subject, config)
    stats_body = _stats_payload(stats)
    observed = {
        "input": digest_file(config_path),
        "effective_config": digest(config, "effective_config"),
        "environment_fingerprint": digest(
            _environment_fingerprint(subject["engine_id"],
                                     subject["engine_version"]),
            "effective_config"),
    }
    output_digest = digest(document, "event_log")

    expected_path = os.path.join(directory, "expected.json")
    if mint:
        _write(expected_path, {
            "fixture_id": fixture["fixture_id"],
            "fixture_version": fixture["fixture_version"],
            "fixture_digest": digest(fixture, "effective_config"),
            "minted_on": MINTED_ON,
            "engine": {"engine_id": subject["engine_id"],
                       "engine_version": subject["engine_version"]},
            "precondition_digests": observed,
            "output_canonical_form": "event_log",
            "output_digest": output_digest,
            "stats_vector": {"spec_id": stats_body["spec_id"],
                             "spec_version": stats_body["spec_version"],
                             "values": stats_body["values"]},
            "stats_vector_digest": stats_body["digest"],
        })
    expected = _load(expected_path) if os.path.exists(expected_path) else None

    layers = {}
    for layer in ("input", "effective_config", "environment_fingerprint"):
        if expected is None:
            layers[layer] = {"status": "unverifiable",
                             "observed_digest": observed[layer],
                             "reason": "no expected.json: the fixture has never "
                                       "been minted, so there is nothing to "
                                       "compare against"}
            continue
        want = expected["precondition_digests"][layer]
        entry = {"status": "match" if want == observed[layer] else "mismatch",
                 "observed_digest": observed[layer], "expected_digest": want}
        if layer == "environment_fingerprint":
            entry["reason"] = (
                f"observed interpreter {sys.version.split()[0]}; the "
                f"interpreter version is outside this fixture's registered "
                f"domain by declaration (fixture.json precondition.layers)")
        layers[layer] = entry

    if expected is None:
        verdict, reason = "PENDING_GENERATION", "expected.json absent"
        exp_body = {"output_digest": None, "stats_vector_digest": None}
    elif any(v["status"] == "unverifiable" for v in layers.values()):
        verdict, reason = "UNVERIFIABLE", "a precondition layer could not be computed"
        exp_body = {"output_digest": expected["output_digest"],
                    "stats_vector_digest": expected["stats_vector_digest"]}
    else:
        exp_body = {"output_digest": expected["output_digest"],
                    "stats_vector_digest": expected["stats_vector_digest"]}
        failed_layers = [k for k, v in layers.items() if v["status"] != "match"]
        digests_match = (output_digest == exp_body["output_digest"]
                         and stats_body["digest"] == exp_body["stats_vector_digest"])
        if failed_layers:
            verdict = "UNVERIFIABLE"
            reason = ("precondition layers disagree (" + ", ".join(failed_layers)
                      + "): the exact assertion does not apply to a run whose "
                        "inputs are not the fixture's inputs")
        elif digests_match:
            verdict, reason = "MATCH", "both digests reproduce exactly"
        else:
            verdict = "MISMATCH"
            reason = ("output digest differs" if output_digest != exp_body["output_digest"]
                      else "stats_vector digest differs")

    result = {
        "schema_version": "1.0.0",
        "canary_result_id": f"{fixture['fixture_id']}@{fixture['fixture_version']}",
        "created_at": f"{MINTED_ON}T00:00:00Z",
        "mode": "exact",
        "fixture": {"fixture_id": fixture["fixture_id"],
                    "fixture_version": fixture["fixture_version"],
                    "fixture_digest": digest(fixture, "effective_config")},
        "engine": {"engine_id": subject["engine_id"],
                   "engine_version": subject["engine_version"]},
        "stats_vector": stats_body,
        "verdict": verdict,
        "verdict_reason": reason,
        "payload": {
            "precondition": layers,
            "observed": {"output_digest": output_digest,
                         "output_canonical_form": "event_log",
                         "stats_vector_digest": stats_body["digest"]},
            "expected": exp_body,
        },
    }
    return result


# ------------------------------------------------------------- semantic ----
def _common_surface_table(reference_doc: dict, subject_doc: dict) -> dict:
    """Per-field comparison of the common surface. ext.* is never read."""
    rows = []
    for field in COMMON_FIELDS:
        row = {"field": field}
        for label, doc in (("reference", reference_doc), ("subject", subject_doc)):
            values = [e[field] for e in doc["events"] if field in e]
            present = len(values) == len(doc["events"])
            types = sorted({type(v).__name__ for v in values})
            if field in ("event_type", "actor_role", "side"):
                domain = sorted({str(v) for v in values})
            else:
                numeric = [v for v in values if isinstance(v, (int, float))]
                domain = [min(numeric), max(numeric)] if numeric else []
            row[label] = {"present_on_every_event": present, "types": types,
                          "domain": domain}
        row["agrees"] = row["reference"] == row["subject"]
        rows.append(row)
    return {
        "table_id": "common-surface/lob",
        "table_version": "1.0.0",
        "excluded": ["ext.*", "seq", "cause_event_id", "order_id", "l1"],
        "excluded_reason": "ext.* is engine-private. seq / cause_event_id / "
                           "order_id / l1 are provisional fields owned by open "
                           "gaps (G1, G4, G5); comparing them would freeze a "
                           "gap into the contract by habit.",
        "engines": {"reference": reference_doc["engine"],
                    "subject": subject_doc["engine"]},
        "rows": rows,
    }


def _assertions(reference: dict, subject: dict, ref_stats: dict,
                sub_stats: dict, tolerances: list) -> list[dict]:
    spec = sv.load_spec()
    raw = sub_stats["raw"]
    out = []

    for side in ("buy", "sell"):
        lhs = raw[f"submitted_quantity_{side}"]
        rhs = (raw[f"filled_quantity_{side}"] + raw[f"cancelled_quantity_{side}"]
               + raw[f"expired_quantity_{side}"]
               + raw[f"terminal_resting_quantity_{side}"])
        out.append({
            "assertion_id": f"semantic.conservation.{side}",
            "kind": "conservation", "observed": lhs, "expected": rhs,
            "status": "held" if lhs == rhs else "violated",
            "note": f"submitted({side}) = filled + cancelled + expired + resting",
        })

    imbalance = {}
    for event in subject["events"]:
        if event["event_type"] == "order_fill":
            sign = 1 if event["side"] == "buy" else -1
            imbalance[event["t"]] = imbalance.get(event["t"], 0) + sign * event["quantity"]
    worst = max((abs(v) for v in imbalance.values()), default=0)
    out.append({
        "assertion_id": "semantic.two_sided_equality", "kind": "two_sided_equality",
        "observed": worst, "expected": 0,
        "status": "held" if worst == 0 else "violated",
        "note": "max over t of |buy fill quantity - sell fill quantity|",
    })

    spread = raw["terminal_spread"]
    out.append({
        "assertion_id": "semantic.no_crossing", "kind": "no_crossing",
        "observed": spread, "expected": None,
        "status": ("unverifiable" if spread is None
                   else "held" if spread > 0 else "violated"),
        "note": "terminal snapshot only; the per-event form needs gap G1 closed",
    })

    priced = [e for e in subject["events"]
              if e["event_type"] in ("order_fill", "order_cancel",
                                     "order_expire", "book_level")]
    bad = sum(1 for e in priced
              if not (e["price"] > 0 and e["quantity"] > 0
                      and e["side"] in ("buy", "sell")))
    out.append({
        "assertion_id": "semantic.sign_domain", "kind": "sign_domain",
        "observed": bad, "expected": 0,
        "status": "held" if bad == 0 else "violated",
        "note": "count of priced events outside the declared domain",
    })

    out.append({
        "assertion_id": "semantic.event_count", "kind": "event_count",
        "observed": len(subject["events"]), "expected": len(reference["events"]),
        "status": ("held" if len(subject["events"]) == len(reference["events"])
                   else "violated"),
        "note": "the two engines emit the same events in a different order",
    })

    for element, got, want in zip(spec["elements"], sub_stats["values"],
                                  ref_stats["values"]):
        tolerance = tolerances[element["index"]]
        if got is None or want is None:
            status = "unverifiable" if got != want else "held"
            deviation = None
        else:
            deviation = abs(got - want)
            status = "held" if deviation <= tolerance["value"] else "violated"
        out.append({
            "assertion_id": f"semantic.stats.{element['name']}",
            "kind": "statistic_tolerance", "observed": got, "expected": want,
            "tolerance": tolerance, "status": status,
            "note": f"|observed - reference| = {deviation!r} {element['unit']}",
        })
    return out


def _tolerance_table(fixture: dict) -> list[dict]:
    """Expand fixture.tolerance.entries into one entry per stats_vector index."""
    spec = sv.load_spec()
    by_name = {}
    default = None
    for entry in fixture["tolerance"]["entries"]:
        body = {k: entry[k] for k in ("value", "kind", "basis", "basis_note")}
        target = entry["applies_to"]
        if target.startswith("every integer-valued"):
            default = body
        else:
            by_name[target.split(" (")[0]] = body
    return [by_name.get(e["name"], default) for e in spec["elements"]]


def run_semantic(directory: str, mint: bool) -> dict:
    fixture = _load(os.path.join(directory, "fixture.json"))
    config = _load(os.path.join(directory, fixture["subject"]["config_path"]))
    reference_doc, ref_stats = _run_engine(fixture["reference"], config)
    subject_doc, sub_stats = _run_engine(fixture["subject"], config)

    table = _common_surface_table(reference_doc, subject_doc)
    table_path = os.path.join(directory, fixture["precondition"]["table_path"])
    if mint:
        _write(table_path, table)
    table_digest = digest(table, "effective_config")

    expected_path = os.path.join(directory, "expected.json")
    if mint:
        _write(expected_path, {
            "fixture_id": fixture["fixture_id"],
            "fixture_version": fixture["fixture_version"],
            "fixture_digest": digest(fixture, "effective_config"),
            "minted_on": MINTED_ON,
            "reference_engine": reference_doc["engine"],
            "reference_stats_vector": {
                "spec_id": ref_stats["spec_id"],
                "spec_version": ref_stats["spec_version"],
                "values": ref_stats["values"]},
            "reference_event_count": len(reference_doc["events"]),
            "common_surface_comparison_digest": table_digest,
        })
    expected = _load(expected_path) if os.path.exists(expected_path) else None

    agreeing = sum(1 for row in table["rows"] if row["agrees"])
    if expected is None:
        precondition_status = "unverifiable"
    elif table_digest != expected["common_surface_comparison_digest"]:
        precondition_status = "mismatch"
    else:
        precondition_status = "match" if agreeing == len(table["rows"]) else "mismatch"

    assertions = _assertions(reference_doc, subject_doc, ref_stats, sub_stats,
                             _tolerance_table(fixture))
    stats_body = _stats_payload(sub_stats)

    if expected is None:
        verdict, reason = "PENDING_GENERATION", "expected.json absent"
    elif precondition_status != "match":
        verdict = "UNVERIFIABLE"
        reason = ("the common-surface comparison table does not hold, so the "
                  "two logs are not comparable on the common surface and no "
                  "assertion about behaviour can be read from them")
    elif any(a["status"] == "unverifiable" for a in assertions):
        verdict, reason = "UNVERIFIABLE", "an assertion could not be evaluated"
    elif any(a["status"] == "violated" for a in assertions):
        verdict = "MISMATCH"
        reason = "violated: " + ", ".join(a["assertion_id"] for a in assertions
                                          if a["status"] == "violated")
    else:
        verdict = "MATCH"
        reason = f"{len(assertions)} assertions held"

    return {
        "schema_version": "1.0.0",
        "canary_result_id": f"{fixture['fixture_id']}@{fixture['fixture_version']}",
        "created_at": f"{MINTED_ON}T00:00:00Z",
        "mode": "semantic",
        "fixture": {"fixture_id": fixture["fixture_id"],
                    "fixture_version": fixture["fixture_version"],
                    "fixture_digest": digest(fixture, "effective_config")},
        "engine": {"engine_id": fixture["subject"]["engine_id"],
                   "engine_version": fixture["subject"]["engine_version"]},
        "stats_vector": stats_body,
        "verdict": verdict,
        "verdict_reason": reason,
        "payload": {
            "precondition_evidence": {
                "kind": "common_surface_comparison",
                "status": precondition_status,
                "table_ref": fixture["precondition"]["table_path"],
                "table_digest": table_digest,
                "fields_compared": len(table["rows"]),
                "fields_agreeing": agreeing,
            },
            "assertions": assertions,
        },
    }


RUNNERS = {"exact": run_exact, "semantic": run_semantic}
EXIT = {"MATCH": 0, "MISMATCH": 1, "UNVERIFIABLE": 2, "PENDING_GENERATION": 3}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="append", default=[])
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--mint", action="store_true",
                        help="write expected.json from this run (fixture minting)")
    parser.add_argument("--out", help="directory to write CanaryResult documents to")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    names = args.fixture or []
    if args.all or not names:
        names = sorted(d for d in os.listdir(HERE)
                       if os.path.exists(os.path.join(HERE, d, "fixture.json")))

    worst = 0
    for name in names:
        directory = os.path.join(HERE, name)
        fixture = _load(os.path.join(directory, "fixture.json"))
        result = RUNNERS[fixture["mode"]](directory, args.mint)
        errors = validate(result, CANARY_SCHEMA)
        if errors:
            raise AssertionError("CanaryResult does not conform to its own "
                                 "schema:\n" + "\n".join(errors))
        if args.out:
            os.makedirs(args.out, exist_ok=True)
            _write(os.path.join(args.out, f"{name}.CanaryResult.json"), result)
        if not args.quiet:
            print(f"{name:<20} {fixture['mode']:<9} {result['verdict']:<19} "
                  f"{result['verdict_reason']}")
        worst = max(worst, EXIT[result["verdict"]])
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
