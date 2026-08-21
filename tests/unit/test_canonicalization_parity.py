"""The canary's canonicalization must be sieve's canonicalization.

Two implementations of one rule is one implementation too many, but the canary
cannot import sieve (it must run without the numerical stack). So the rule is
pinned from both ends:

- `test_rules_are_pinned_to_fixed_bytes` runs everywhere and fixes the bytes
  the contract text describes, so neither implementation can drift alone;
- `test_agrees_with_sieve_serialization` runs wherever sieve is importable —
  which includes every CI job, since they install the package — and asserts
  the two implementations agree byte for byte.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "fixtures" / "canary"))

from _engine.canonical import canonical_bytes, null_out, quantize  # noqa: E402

CASES = [
    ({"b": 1, "a": 2}, b'{"a":2,"b":1}\n'),
    ({"nested": {"z": 1, "a": [3, 2]}}, b'{"nested":{"a":[3,2],"z":1}}\n'),
    ({"unicode": "日本語"}, '{"unicode":"日本語"}\n'.encode()),
    ({"int": 1, "float": 1.5}, b'{"float":1.5,"int":1}\n'),
    ({"null": None}, b'{"null":null}\n'),
]


@pytest.mark.parametrize("value,expected", CASES)
def test_rules_are_pinned_to_fixed_bytes(value, expected):
    assert canonical_bytes(value) == expected


def test_non_finite_is_refused_rather_than_encoded():
    """NaN is not JSON. Encoding it as `NaN` would produce bytes no conforming
    parser accepts; encoding it as null here would lose the reason."""
    with pytest.raises(ValueError, match="non-finite"):
        canonical_bytes({"x": float("nan")})
    with pytest.raises(ValueError, match="non-finite"):
        canonical_bytes({"x": [1.0, float("inf")]})


def test_volatile_fields_are_nulled_not_removed():
    """If they were removed, a producer could stop emitting the field and no
    digest would move."""
    data = {"log_id": "run-1", "events": []}
    assert null_out(data, (("log_id",),)) == {"log_id": None, "events": []}
    assert canonical_bytes(null_out(data, (("log_id",),))) != canonical_bytes(
        {"events": []})


def test_quantization_is_half_to_even_and_declared_by_scale():
    assert quantize(2.5, 0) == 2
    assert quantize(3.5, 0) == 4
    assert quantize(1.0000000000012345, 12) == 1.000000000001
    assert quantize(None, 12) is None


def test_agrees_with_sieve_serialization():
    serialization = pytest.importorskip(
        "sieve.core.serialization",
        reason="sieve needs numpy; every CI job installs it, so this check is "
               "live there. The bytes themselves are pinned unconditionally by "
               "test_rules_are_pinned_to_fixed_bytes.")
    for value, _ in CASES:
        assert canonical_bytes(value) == serialization.canonical_bytes(value)
