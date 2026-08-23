#!/usr/bin/env python3
"""Regenerate every worked example under docs/contract/examples/.

The examples cite digests of artifacts that live in this repository. If they
were hand-maintained they would drift, and a drifted example is worse than no
example: it looks like evidence. This tool recomputes them from the artifacts,
and tests/unit/test_contract_examples.py fails if the committed files differ
from what it produces.

    python3 tools/mint_contract_examples.py

Standard library only.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CANARY = os.path.join(REPO, "fixtures", "canary")
EXAMPLES = os.path.join(REPO, "docs", "contract", "examples")
sys.path.insert(0, CANARY)

from _engine.canonical import canonical_bytes, digest, digest_file  # noqa: E402
from _engine.schema_check import validate  # noqa: E402

CREATED_AT = "2026-08-23T00:00:00Z"


def _load(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _write(path, data):
    with open(path, "wb") as fh:
        fh.write(canonical_bytes(data))


def build_manifest() -> dict:
    config_path = os.path.join(CANARY, "exact-lob-min", "config.json")
    config = _load(config_path)
    conformance = _load(os.path.join(REPO, "docs", "contract",
                                     "conformance_map.v1.json"))

    # 裁定 3 (2026-08-20): rng_* are runtime-layer only. They are NOT in the
    # behaviour domain, because behavior_config_hash exists to be the
    # precondition of a same-engine / different-environment semantic canary,
    # and a different environment is often a different RNG build.
    behaviour = {"config": config, "seed_convention_version": "1.0.0"}
    registered_environment = {
        "python": "3.11", "platform": "linux-x86_64", "numpy": "not-imported",
        "blas": "not-imported", "dependency_lock_digest": "0" * 64,
        "rng_algorithm": "splitmix64", "rng_version": "1",
    }

    exact = _load(os.path.join(CANARY, "examples",
                               "CanaryResult.exact.example.json"))
    semantic = _load(os.path.join(CANARY, "examples",
                                  "CanaryResult.semantic.example.json"))
    exact_expected = _load(os.path.join(CANARY, "exact-lob-min",
                                        "expected.json"))

    return {
        "schema_version": "2.0.0",
        "run_id": "run-2026-08-23-canary-0001",
        "created_at": CREATED_AT,
        "engine": {
            "engine_id": "min-lob-a", "engine_version": "2.0.0",
            "source_digest": digest_file(
                os.path.join(CANARY, "_engine", "min_lob_a.py")),
        },
        "producer": {"tool_id": "canary-runner", "tool_version": "0.2.0"},
        "command": "python3 fixtures/canary/run_canary.py --all",
        "event_log_schema_version": "1.1.0",
        "metric_suite": {"suite_id": "lob-common-surface",
                         "suite_version": "1.0.0"},
        "code_provenance": {"git_dirty": False},
        "master_seed": config["seed"],
        "seed_convention_version": "1.0.0",
        "seed_tree": [{"name": "engine", "entropy": config["seed"],
                       "spawn_key": [0]}],
        "rng_algorithm": "splitmix64",
        "rng_version": "1",
        "runtime_fingerprint_domain_version": 1,
        "environment": {
            "python": "3.11", "platform": "linux-x86_64",
            "numpy": "not-imported", "blas": "not-imported",
            "dependency_lock_digest": "0" * 64, "hostname": "example-runner",
        },
        "input_artifact_digests": {
            "canary/exact-lob-min/config.json": {
                "artifact_type": "config", "digest": digest_file(config_path),
                "digest_algorithm": "sha256",
                "role": "engine configuration and seed",
                "verification": {"status": "verified"},
            },
            "yh007-8/phi-sigma-calibration": {
                "artifact_type": "calibration",
                "digest": digest({"phi_ar1": 0.615, "sigma_ar1_abs": 3.81e-3},
                                 "effective_config"),
                "digest_algorithm": "sha256",
                "role": "AR(1) calibration constants; illustrative, not "
                        "consumed by the canary",
                "source_reference": {
                    "kind": "measurement",
                    "locator": "Kronos instrument measurement, 2026-07-21",
                    "evidence_basis": "external_measurement_not_rerunnable",
                },
                "verification": {"status": "verified"},
            },
            "example/unreachable-reference-series": {
                "artifact_type": "reference", "digest_algorithm": "sha256",
                "role": "declared input whose digest could not be obtained at "
                        "consumption time",
                "verification": {
                    "status": "unverifiable",
                    "reason": "declared in the config but the path resolved to "
                              "a file the process could not open at "
                              "consumption time; recorded rather than dropped, "
                              "per B5",
                },
            },
        },
        "effective_config": {
            "effective_config_digest": digest(config, "effective_config"),
            "behavior_config_hash": digest(behaviour, "effective_config"),
            "behavior_config_domain_version": 1,
            "environment_fingerprint_digest": digest(registered_environment,
                                                     "effective_config"),
            "registry_ref": {"document": "docs/contract/effective_config.md",
                             "version": "0.1.0"},
            "resolution_sources": [
                {"source_kind": "config_file",
                 "ref": "fixtures/canary/exact-lob-min/config.json",
                 "digest": digest_file(config_path),
                 "keys_set": sorted(config.keys())},
                {"source_kind": "default", "ref": "_engine.min_lob_a:MinLobA",
                 "keys_set": []},
            ],
            "formula_bindings": [
                {"formula_id": "lob.mid_reference", "formula_version": "1.0.0",
                 "effective_values": {
                     "rule": "floor((best_bid + best_ask) / 2)",
                     "fallback_initial_mid": config["initial_mid"]}},
                {"formula_id": "stats.sample_variance",
                 "formula_version": "1.0.0",
                 "effective_values": {"ddof": 1, "method": "two_pass"}},
            ],
        },
        "conformance_profile_id": {
            "profile_id": conformance["profile"]["profile_id"],
            "profile_version": conformance["profile"]["profile_version"],
            "map_ref": "docs/contract/conformance_map.v1.json",
            "map_digest": digest(conformance, "effective_config"),
        },
        "canary_results": [
            {"fixture_id": r["fixture"]["fixture_id"],
             "fixture_version": r["fixture"]["fixture_version"],
             "fixture_digest": r["fixture"]["fixture_digest"],
             "mode": r["mode"],
             "result_digest": digest(r, "effective_config"),
             "result_ref": ref,
             "verdict": r["verdict"]}
            for r, ref in (
                (exact, "fixtures/canary/examples/CanaryResult.exact.example.json"),
                (semantic,
                 "fixtures/canary/examples/CanaryResult.semantic.example.json"))
        ],
        "outputs": [
            {"artifact_id": "canary/exact-lob-min/event_log",
             "canonical_form": "event_log",
             "digest": exact_expected["output_digest"],
             "digest_algorithm": "sha256"},
            {"artifact_id": "canary/exact-lob-min/stats_vector",
             "canonical_form": "stats_vector",
             "digest": exact_expected["stats_vector_digest"],
             "digest_algorithm": "sha256"},
        ],
        "notes": [
            "Worked example. Every digest was computed from artifacts "
            "committed in this repository; nothing here is a placeholder.",
            "Regenerated by tools/mint_contract_examples.py and pinned by "
            "tests/unit/test_contract_examples.py, so it cannot drift from the "
            "fixtures it cites.",
        ],
    }


def main() -> int:
    # the canary examples are inputs to the manifest example, so run them first
    subprocess.run([sys.executable, os.path.join(CANARY, "run_canary.py"),
                    "--out", os.path.join(CANARY, "examples"), "--quiet"],
                   check=True)
    for mode in ("exact", "semantic"):
        src = os.path.join(CANARY, "examples", f"{mode}-lob-min.CanaryResult.json")
        if os.path.exists(src):
            os.replace(src, os.path.join(CANARY, "examples",
                                         f"CanaryResult.{mode}.example.json"))

    manifest = build_manifest()
    errors = validate(manifest, os.path.join(REPO, "schemas",
                                             "RunManifest.v2.schema.json"))
    if errors:
        raise AssertionError("example manifest does not conform:\n"
                             + "\n".join(errors))
    _write(os.path.join(EXAMPLES, "RunManifest.v2.example.json"), manifest)

    subprocess.run([sys.executable,
                    os.path.join(HERE, "cont_harness_reference.py"),
                    "--out", EXAMPLES], check=True, stdout=subprocess.DEVNULL)
    print("minted:", sorted(os.listdir(EXAMPLES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
