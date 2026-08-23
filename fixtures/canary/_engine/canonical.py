"""Canonicalization + digest. One implementation, four declared canonical forms.

The rules mirror `sieve.core.serialization` (sorted keys, compact separators,
UTF-8, trailing newline, non-finite forbidden, volatile fields nulled rather
than removed so the hashed shape is stable). They are restated here without
importing sieve so that the canary stays dependency-free; the normative text
is docs/contract/canonicalization.md, and the two are pinned together by
tests/unit/test_canonicalization_parity.py.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

DIGEST_ALGORITHM = "sha256"

# Volatile fields, per canonical form. Nulled (not removed) before hashing.
HASH_EXCLUDED_PATHS: dict[str, tuple[tuple[str, ...], ...]] = {
    "event_log": (("log_id",),),
    "effective_config": (),
    "stats_vector": (),
    "output_table": (),
}


def _reject_non_finite(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float) and not math.isfinite(obj):
        raise ValueError(f"non-finite float at {path}; encode as null upstream")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_non_finite(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_non_finite(v, f"{path}[{i}]")


def canonical_bytes(data: Any) -> bytes:
    _reject_non_finite(data)
    return (json.dumps(data, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":"), allow_nan=False) + "\n").encode()


def null_out(data: dict, paths: tuple[tuple[str, ...], ...]) -> dict:
    out = copy.deepcopy(data)
    for path in paths:
        node: Any = out
        for key in path[:-1]:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if isinstance(node, dict) and path[-1] in node:
            node[path[-1]] = None
    return out


def digest(data: Any, canonical_form: str) -> str:
    """sha256 of `data` in the named canonical form."""
    if canonical_form not in HASH_EXCLUDED_PATHS:
        raise KeyError(f"unknown canonical form: {canonical_form}")
    payload = data
    if isinstance(data, dict):
        payload = null_out(data, HASH_EXCLUDED_PATHS[canonical_form])
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def digest_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def quantize(value: float | int | None, scale: int) -> float | int | None:
    """Round to `scale` decimal places, half-to-even, via Decimal.

    Floats reach the hash domain only after this call. `repr` round-trips a
    double exactly, so Decimal(repr(x)) is the exact decimal the double
    denotes and the rounding is a pure function of the double — no platform
    dependence enters here.
    """
    if value is None:
        return None
    if scale == 0:
        return int(Decimal(repr(float(value))).quantize(Decimal(1),
                                                        rounding=ROUND_HALF_EVEN))
    q = Decimal(1).scaleb(-scale)
    return float(Decimal(repr(float(value))).quantize(q, rounding=ROUND_HALF_EVEN))
