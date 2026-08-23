"""The two hash domains, pinned as tests rather than as prose.

Two properties are asserted, because they are the two halves of the mechanism
and each is useless without the other:

- adding a key to the free `environment` map must NOT move the digest;
- changing the registered DOMAIN must move it, and must require a version bump.

A registry that only had the first property would be a hash nobody could
tighten; one that only had the second would be a hash anyone could invalidate
by logging their hostname.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CANARY = REPO / "fixtures" / "canary"
CONTRACT = REPO / "docs" / "contract"
sys.path.insert(0, str(CANARY))

from _engine.canonical import digest  # noqa: E402
from _engine.hash_domain import (  # noqa: E402
    environment_fingerprint_digest,
    fingerprint_values,
    load_registry,
)

REGISTRY = load_registry()
EXAMPLE = json.loads(
    (CONTRACT / "examples" / "RunManifest.v2.example.json").read_text())

RUNTIME_KEYS = ["python", "platform", "numpy", "blas", "dependency_lock_digest",
                "rng_algorithm", "rng_version"]
BEHAVIOR_KEYS = ["config", "seed_convention_version", "rng_algorithm",
                 "rng_version"]


def test_registry_lists_exactly_the_approved_runtime_keys():
    """Q2, decision of 2026-08-20. A key silently added or dropped here is a
    changed hash domain, which is why the list is asserted and not just read."""
    assert REGISTRY["runtime_fingerprint_domain"]["keys"] == RUNTIME_KEYS


def test_registry_lists_exactly_the_approved_behaviour_keys():
    """B8: seed_convention_version is inside behavior_config_hash."""
    assert REGISTRY["behavior_config_domain"]["keys"] == BEHAVIOR_KEYS
    assert "seed_convention_version" in REGISTRY["behavior_config_domain"]["keys"]


def test_adding_an_unregistered_environment_key_does_not_move_the_digest():
    before = environment_fingerprint_digest(EXAMPLE, REGISTRY)
    widened = json.loads(json.dumps(EXAMPLE))
    widened["environment"]["ci_job_id"] = "12345"
    widened["environment"]["hostname"] = "some-other-runner"
    assert environment_fingerprint_digest(widened, REGISTRY) == before


def test_changing_a_registered_key_does_move_the_digest():
    before = environment_fingerprint_digest(EXAMPLE, REGISTRY)
    moved = json.loads(json.dumps(EXAMPLE))
    moved["environment"]["blas"] = "openblas 0.3.28"
    assert environment_fingerprint_digest(moved, REGISTRY) != before


def test_a_domain_change_is_visible_and_requires_a_version_bump():
    """Extending the domain changes every digest, so the change cannot be made
    quietly; and a manifest still declaring the old domain version is rejected
    rather than hashed against a domain nobody registered."""
    at_v1 = environment_fingerprint_digest(EXAMPLE, REGISTRY)

    widened = json.loads(json.dumps(REGISTRY))
    widened["runtime_fingerprint_domain"]["version"] = 2
    widened["runtime_fingerprint_domain"]["keys"] = RUNTIME_KEYS + ["hostname"]
    manifest = json.loads(json.dumps(EXAMPLE))
    manifest["environment"]["hostname"] = "example-runner"

    with pytest.raises(ValueError, match="runtime_fingerprint_domain_version"):
        environment_fingerprint_digest(manifest, widened)

    manifest["runtime_fingerprint_domain_version"] = 2
    assert environment_fingerprint_digest(manifest, widened) != at_v1


def test_top_level_rng_fields_are_not_satisfiable_from_the_environment_map():
    """Q2 put rng_algorithm/rng_version at the top level on purpose. If an
    environment entry of the same name could stand in for them, the decision
    would be undone by accident."""
    stripped = json.loads(json.dumps(EXAMPLE))
    stripped.pop("rng_algorithm")
    stripped["environment"]["rng_algorithm"] = "numpy.PCG64"
    values = fingerprint_values(stripped, RUNTIME_KEYS)
    assert values["rng_algorithm"] == "numpy.PCG64"
    assert values != fingerprint_values(EXAMPLE, RUNTIME_KEYS)


def test_seed_convention_version_moves_the_behaviour_hash():
    """At a fixed master_seed, a changed seed convention changes behaviour.
    Recording only master_seed would hide that."""
    def behaviour_hash(manifest, config):
        return digest({"config": config,
                       "seed_convention_version": manifest["seed_convention_version"],
                       "rng_algorithm": manifest["rng_algorithm"],
                       "rng_version": manifest["rng_version"]},
                      "effective_config")

    config = json.loads((CANARY / "exact-lob-min" / "config.json").read_text())
    baseline = behaviour_hash(EXAMPLE, config)
    assert baseline == EXAMPLE["effective_config"]["behavior_config_hash"]

    bumped = json.loads(json.dumps(EXAMPLE))
    bumped["seed_convention_version"] = "2.0.0"
    assert behaviour_hash(bumped, config) != baseline


def test_example_manifest_declares_the_registry_versions_it_was_hashed_under():
    assert (EXAMPLE["runtime_fingerprint_domain_version"]
            == REGISTRY["runtime_fingerprint_domain"]["version"])
    assert (EXAMPLE["effective_config"]["behavior_config_domain_version"]
            == REGISTRY["behavior_config_domain"]["version"])
    assert (EXAMPLE["effective_config"]["environment_fingerprint_digest"]
            == environment_fingerprint_digest(EXAMPLE, REGISTRY))


def test_formula_registry_records_effective_values_not_only_ids():
    """Two rows share a formula_id and differ only in effective values; if the
    effective-values column were dropped, they would be indistinguishable."""
    rows = REGISTRY["formula"]["rows"]
    variance = [r for r in rows if r[0].strip("`") == "stats.sample_variance"]
    assert len(variance) == 2
    assert variance[0][2] != variance[1][2]
