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
                    "CanaryResult.schema.json")


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
    """min-lob-b must agree on the common surface and differ byte-wise.

    Both halves matter. Equal bytes would make the semantic fixture redundant;
    a common-surface disagreement would make it wrong."""
    config = _config()
    a, b = MinLobA(config).run(), MinLobB(config).run()
    common = ("t", "event_type", "actor_id", "actor_role", "side", "price",
              "quantity")

    def multiset(doc):
        return sorted(tuple(str(e[k]) for k in common) for e in doc["events"])

    assert multiset(a) == multiset(b)
    assert digest(a, "event_log") != digest(b, "event_log")


def test_stats_vector_never_reads_ext():
    """Adding an engine-private ext key must not move the stats_vector."""
    config = _config()
    document = MinLobA(config).run()
    before = sv.compute(document)["values"]
    for event in document["events"]:
        event.setdefault("ext", {})["min_lob_a.injected_probe"] = 1
    assert sv.compute(document)["values"] == before


def test_quantity_conservation_closes_from_the_common_eight_fields_alone():
    """The identity that makes the semantic canary possible without order_id."""
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


def test_calibration_inputs_require_a_source_reference():
    """BACKLOG 'Evidence Contract v0.1' item 1, as an enforced rule rather than
    a paragraph: a calibration constant without a source reference is rejected."""
    schema_path = str(SCHEMAS / "RunManifest.v2.schema.json")
    base = _load(CONTRACT / "examples" / "RunManifest.v2.example.json")
    assert validate(base, schema_path) == []
    broken = json.loads(json.dumps(base))
    for artifact in broken["input_artifact_digests"]:
        if artifact["artifact_type"] == "calibration":
            artifact.pop("source_reference")
    assert any("source_reference" in e for e in validate(broken, schema_path))
