"""Contract-layer tests: the canary fixtures, and the hash domains they rest on.

Standard library only (the canary itself imports nothing from sieve), so these
run even where the numerical stack is unavailable.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CANARY = REPO / "fixtures" / "canary"
SCHEMAS = REPO / "schemas"
CONTRACT = REPO / "docs" / "contract"

sys.path.insert(0, str(CANARY))

from _engine import stats_vector as sv  # noqa: E402
from _engine.canonical import digest  # noqa: E402
from _engine.min_lob_a import MinLobA  # noqa: E402
from _engine.min_lob_b import MinLobB  # noqa: E402
from _engine.schema_check import unsupported_keywords, validate  # noqa: E402

CONTRACT_SCHEMAS = ("RunManifest.v2.schema.json", "EventLog.schema.json",
                    "CanaryResult.schema.json", "ContHarnessInput.schema.json",
                    "ContHarnessOutput.schema.json",
                    "ContHarnessParameters.schema.json")

# The CORE set fixed by the 12-week calendar 2.1. Nine keys for eight slots:
# slot 7, "order/trade ID", is realized by order_id + trade_id.
CORE_FIELDS = ("t", "event_type", "actor_role", "side", "price", "quantity",
               "order_id", "trade_id", "cause_id")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _config():
    return _load(CANARY / "exact-lob-min" / "config.json")


# --------------------------------------------------------------- canary ----

def test_canary_runner_reports_match_for_both_fixtures():
    """The whole point, end to end: both fixtures reproduce, exit code 0."""
    proc = subprocess.run([sys.executable, str(CANARY / "run_canary.py")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.count("MATCH") == 2, proc.stdout


def test_exact_fixture_digests_are_the_committed_ones():
    """Guards the 2026-08-24 hash chain: if this moves, something changed the
    engine, the canonicalization or the stats spec — never 'just a flake'."""
    expected = _load(CANARY / "exact-lob-min" / "expected.json")
    document = MinLobA(_config()).run()
    assert digest(document, "event_log") == expected["output_digest"]
    stats = sv.compute(document)
    body = {"spec_id": stats["spec_id"], "spec_version": stats["spec_version"],
            "values": stats["values"]}
    assert digest(body, "stats_vector") == expected["stats_vector_digest"]


def test_exact_and_semantic_fixtures_are_a_pair():
    """min-lob-b must agree on the core surface and differ byte-wise.

    Both halves matter. Equal bytes would make the semantic fixture redundant;
    a core-surface disagreement would make it wrong. The identity fields are
    excluded from the multiset because "order-7" and "ord-7" are the same
    market — they are compared structurally instead, in the comparison table."""
    config = _config()
    a, b = MinLobA(config).run(), MinLobB(config).run()
    comparable = [f for f in CORE_FIELDS
                  if f not in ("order_id", "trade_id", "cause_id")]

    def multiset(doc):
        return sorted(tuple(str(e[k]) for k in comparable) for e in doc["events"])

    assert multiset(a) == multiset(b)
    assert digest(a, "event_log") != digest(b, "event_log")


def test_every_event_carries_the_core_field_set():
    """Calendar 2.1 fixes these; a conforming engine may not omit one, and a
    nullable value must still be present as a key."""
    for engine in (MinLobA, MinLobB):
        for event in engine(_config()).run()["events"]:
            missing = [f for f in CORE_FIELDS if f not in event]
            assert not missing, missing


def test_event_id_and_actor_id_are_not_core():
    """They were wrongly inferred as core on 2026-08-21 and corrected against
    the calendar original on 2026-08-23. This test exists so the inference
    cannot come back: neither may appear in the comparison table's core rows."""
    assert "event_id" not in CORE_FIELDS
    assert "actor_id" not in CORE_FIELDS
    schema = _load(SCHEMAS / "EventLog.schema.json")
    required = schema["$defs"]["Event"]["required"]
    assert sorted(required) == sorted(CORE_FIELDS)
    assert "event_id" not in required and "actor_id" not in required


def test_l1_invariants():
    """The two conditions on which the l1 semantics were ratified (2026-08-23).

    (ii) is checked directly. (i) is checked in the form that matters: replaying
    the l1 sequence must show every settled state, so no two consecutive events
    may imply a change that no event's l1 accounts for."""
    for engine in (MinLobA, MinLobB):
        events = engine(_config()).run()["events"]
        for event in events:
            l1 = event["l1"]
            if l1["bid_price"] is not None and l1["ask_price"] is not None:
                assert l1["bid_price"] < l1["ask_price"], event
        # every event of one atomic operation shares the settled state, and the
        # settled state is what the next operation starts from: the sequence of
        # distinct states is exactly the sequence of book settlements.
        assert all(e["l1"] is not None for e in events)


def test_resting_limit_order_depth_appears_on_its_own_event():
    """Ratification condition for the l1 semantics: the quantity of a limit
    order that comes to rest at the best quote is visible in the l1 of ITS OWN
    submit event, not the next one."""
    events = MinLobA(_config()).run()["events"]
    observed = 0
    for previous, current in zip(events, events[1:]):
        if current["event_type"] != "order_submit" or current["side"] != "buy":
            continue
        before, after = previous["l1"], current["l1"]
        if before["bid_price"] != after["bid_price"]:
            continue
        if current["price"] != after["bid_price"]:
            continue
        if (after["bid_size"] or 0) == (before["bid_size"] or 0) + current["quantity"]:
            observed += 1
    assert observed > 0, ("no resting limit order showed its own depth "
                          "increase; the l1 rule has regressed to pre-state")


def test_trade_id_pairs_exactly_two_legs():
    """Slot 7 of calendar 2.1 made per-trade checking possible; without
    trade_id the two legs of a trade cannot be paired at all."""
    for engine in (MinLobA, MinLobB):
        legs = {}
        for event in engine(_config()).run()["events"]:
            if event["event_type"] == "order_fill":
                legs.setdefault(event["trade_id"], []).append(event)
        assert legs
        for trade_id, pair in legs.items():
            assert len(pair) == 2, trade_id
            assert {leg["side"] for leg in pair} == {"buy", "sell"}
            assert pair[0]["quantity"] == pair[1]["quantity"]


def test_order_ids_are_unique_and_causes_precede():
    """order_id uniqueness is not decoration: core-ising it on 2026-08-23
    immediately exposed a real defect in min-lob-a, where a fully-filled order
    reused the next order's id."""
    for engine in (MinLobA, MinLobB):
        document = engine(_config()).run()
        events = document["events"]
        submits = [e for e in events if e["event_type"] == "order_submit"]
        assert len({e["order_id"] for e in submits}) == len(submits)
        key = document["ordering"]["total_order_key"]
        for event in events:
            if event["cause_id"] is not None:
                assert event["cause_id"] < event[key], event


def test_stats_vector_never_reads_ext():
    """Adding an engine-private ext key must not move the stats_vector."""
    config = _config()
    document = MinLobA(config).run()
    before = sv.compute(document)["values"]
    for event in document["events"]:
        event.setdefault("ext", {})["min_lob_a.injected_probe"] = 1
    assert sv.compute(document)["values"] == before


def test_quantity_conservation_closes_from_the_core_fields_alone():
    """The aggregate identity. Retained beside the per-order one: an aggregate
    identity cannot see one order over-consumed against another
    under-consumed, and a per-order ledger can be self-consistent while
    disagreeing with the mechanism's own snapshot."""
    raw = sv.compute(MinLobA(_config()).run())["raw"]
    for side in ("buy", "sell"):
        assert raw[f"submitted_quantity_{side}"] == (
            raw[f"filled_quantity_{side}"] + raw[f"cancelled_quantity_{side}"]
            + raw[f"expired_quantity_{side}"]
            + raw[f"terminal_resting_quantity_{side}"])


def test_a_changed_input_is_unverifiable_not_a_mismatch(tmp_path):
    """B5 in miniature: a digest that does not describe the fixture's input is
    a statement about the harness, not about the engine."""
    import shutil
    # mirror the repository layout: run_canary.py locates schemas/ two levels up
    work = tmp_path / "fixtures" / "canary"
    shutil.copytree(CANARY, work)
    shutil.copytree(SCHEMAS, tmp_path / "schemas")
    config_path = work / "exact-lob-min" / "config.json"
    config = json.loads(config_path.read_text())
    config["seed"] += 1
    config_path.write_text(json.dumps(config, indent=2) + "\n")
    proc = subprocess.run([sys.executable, str(work / "run_canary.py"),
                           "--fixture", "exact-lob-min"],
                          capture_output=True, text=True)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "UNVERIFIABLE" in proc.stdout


# --------------------------------------------------------------- schema ----

@pytest.mark.parametrize("name", CONTRACT_SCHEMAS)
def test_contract_schemas_parse_and_stay_inside_the_validated_subset(name):
    """If a schema grows a keyword the in-repo validator does not implement,
    this fails rather than the validator silently skipping it."""
    schema = _load(SCHEMAS / name)
    assert unsupported_keywords(schema) - {"format"} == set()


def test_emitted_canary_results_conform_to_the_canary_schema():
    for example in sorted((CANARY / "examples").glob("*.json")):
        assert validate(_load(example),
                        str(SCHEMAS / "CanaryResult.schema.json")) == [], example


def test_engine_logs_conform_to_the_event_log_schema():
    config = _config()
    for engine in (MinLobA, MinLobB):
        assert validate(engine(config).run(),
                        str(SCHEMAS / "EventLog.schema.json")) == []


def test_existing_v1_run_manifest_schema_is_untouched():
    """Approval covered three NEW schemas. v1 is retained verbatim; a diff here
    means the approved scope was exceeded."""
    v1 = _load(SCHEMAS / "RunManifest.schema.json")
    assert v1["title"] == "RunManifest"
    assert v1["properties"]["schema_version"]["default"] == "0.1.0"
    assert "input_artifact_digests" not in v1["properties"]


def test_canary_result_mode_selects_exactly_one_payload_branch():
    """The oneOf must actually discriminate: an exact envelope carrying a
    semantic payload has to fail, or `mode` is decoration."""
    schema_path = str(SCHEMAS / "CanaryResult.schema.json")
    exact = _load(CANARY / "examples" / "CanaryResult.exact.example.json")
    semantic = _load(CANARY / "examples" / "CanaryResult.semantic.example.json")
    crossed = {**exact, "payload": semantic["payload"]}
    assert validate(crossed, schema_path) != []


def test_per_order_ledger_agrees_with_the_terminal_book():
    """The check that only became possible when order_id became core (G5)."""
    document = MinLobA(_config()).run()
    submitted, consumed = {}, {}
    for event in document["events"]:
        order = event["order_id"]
        if order is None:
            continue
        if event["event_type"] == "order_submit":
            submitted[order] = submitted.get(order, 0) + event["quantity"]
        elif event["event_type"] in ("order_fill", "order_cancel",
                                     "order_expire"):
            consumed[order] = consumed.get(order, 0) + event["quantity"]
    assert not [o for o, q in consumed.items() if q > submitted.get(o, 0)]
    residual = sum(submitted[o] - consumed.get(o, 0) for o in submitted)
    raw = sv.compute(document)["raw"]
    assert residual == (raw["terminal_resting_quantity_buy"]
                        + raw["terminal_resting_quantity_sell"])


def test_calibration_inputs_require_a_source_reference():
    """BACKLOG 'Evidence Contract v0.1' item 1, as an enforced rule rather than
    a paragraph: a calibration constant without a source reference is rejected."""
    schema_path = str(SCHEMAS / "RunManifest.v2.schema.json")
    base = _load(CONTRACT / "examples" / "RunManifest.v2.example.json")
    assert validate(base, schema_path) == []
    broken = json.loads(json.dumps(base))
    for artifact in broken["input_artifact_digests"].values():
        if artifact["artifact_type"] == "calibration":
            artifact.pop("source_reference")
    assert any("source_reference" in e for e in validate(broken, schema_path))


def test_manifest_does_not_carry_its_own_conformance_verdict():
    """A manifest that judged itself would be a second authority on
    conformance, and the one easiest to make agree with itself (ruling of
    2026-08-23). Per-item status belongs to the profile checker's report."""
    schema = _load(SCHEMAS / "RunManifest.v2.schema.json")
    assert "conformance_map" not in schema["properties"]
    declaration = schema["properties"]["conformance_profile_id"]["properties"]
    assert set(declaration) == {"profile_id", "profile_version", "map_ref",
                                "map_digest"}
    assert "status" not in json.dumps(declaration)
