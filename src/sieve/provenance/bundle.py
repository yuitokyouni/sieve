"""Assemble, seal, write and verify EvidenceBundles.

Two integrity layers with different scopes, both checked by ``verify``:

1. **Scientific seal** — ``bundle_hash``: SHA-256 of the canonical bundle
   with volatile fields nulled (IDs, timestamps, artifact index, and
   machine-local facts: platform fingerprint, filesystem paths). It pins WHAT
   was measured — data content hash, suite hash, claim, seed tree, results —
   not when or where. Reproduction contract: same input bytes + same suite +
   same seed + same package versions ⇒ the same seal on any machine. This is
   the hash to quote; third parties check it by rerunning, not by trusting.
2. **File integrity** — ``bundle.sha256``: sha256sum-compatible sidecar over
   the written ``evidence_bundle.json`` bytes (which include the artifact
   index), plus per-artifact hashes inside that index. This pins the run
   directory as shipped; ``sha256sum -c bundle.sha256`` also works.

Threat model: modifying any artifact, the index, or the bundle file trips
layer 2; modifying scientific content trips both. An adversary who regenerates
the entire run directory can of course produce a self-consistent layer 2 —
but then the layer-1 seal no longer matches the one that was quoted.

A verification failure never raises: it returns the list of mismatches,
because "this bundle was modified" is a result, not an exception (spec §8).
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

from sieve.core.hashing import sha256_bytes, sha256_file
from sieve.core.models import (
    INSPECT_HASH_EXCLUDED_PATHS,
    EvidenceBundle,
    InspectBundle,
)
from sieve.core.serialization import canonical_bytes, hashable_bytes, to_jsonable


def safe_artifact_path(base: str | Path, rel: str) -> Path:
    """Resolve a bundle-declared artifact path, confined to ``base``.

    Bundles can come from third parties: a crafted ``artifact_path`` /
    ``artifact_index`` entry like ``../../outside.svg`` (or an absolute
    path, a drive prefix, or a symlink escaping the run directory) must
    never make sieve read outside the run directory. Raises ``ValueError``
    on any escape; callers turn that into a verify problem or skip.
    """
    pp = PurePosixPath(rel)
    if (pp.is_absolute() or "\\" in rel or ".." in pp.parts
            or (pp.parts and pp.parts[0].endswith(":"))):
        raise ValueError(f"unsafe artifact path {rel!r}: absolute, drive or "
                         "parent-directory components are not allowed")
    base = Path(base).resolve()
    target = (base / pp).resolve()      # resolves symlink escapes too
    if not target.is_relative_to(base):
        raise ValueError(f"unsafe artifact path {rel!r}: resolves outside "
                         "the run directory")
    return target


def seal(bundle: EvidenceBundle) -> EvidenceBundle:
    """Compute the deterministic scientific seal. Call before rendering the
    report (the report displays the seal) and before filling artifact_index
    (the index is outside the seal by design)."""
    bundle.bundle_hash = sha256_bytes(hashable_bytes(bundle))
    return bundle


def write(bundle: EvidenceBundle, run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "evidence_bundle.json"
    body = canonical_bytes(to_jsonable(bundle))
    path.write_bytes(body)
    (run_dir / "bundle.sha256").write_text(
        f"{sha256_bytes(body)}  evidence_bundle.json\n")
    return path


def load(path: str | Path) -> EvidenceBundle:
    return EvidenceBundle.model_validate(json.loads(Path(path).read_text()))


# ----------------------------------------------------------- inspect bundle
# The exploratory artifact of ``sieve inspect``. Same two-layer scheme,
# separate schema and exclusion set; nothing here touches how existing
# evidence bundles seal or verify.

def seal_inspect(bundle: InspectBundle) -> InspectBundle:
    bundle.bundle_hash = sha256_bytes(
        hashable_bytes(bundle, INSPECT_HASH_EXCLUDED_PATHS))
    return bundle


def write_inspect(bundle: InspectBundle, run_dir: str | Path) -> Path:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "inspect_bundle.json"
    body = canonical_bytes(to_jsonable(bundle))
    path.write_bytes(body)
    (run_dir / "bundle.sha256").write_text(
        f"{sha256_bytes(body)}  inspect_bundle.json\n")
    return path


def load_inspect(path: str | Path) -> InspectBundle:
    return InspectBundle.model_validate(json.loads(Path(path).read_text()))


def verify(run_dir_or_bundle: str | Path) -> list[str]:
    """Return a list of problems; empty list = intact.

    Handles both artifact kinds: a run directory with
    ``evidence_bundle.json`` (``sieve test``) or ``inspect_bundle.json``
    (``sieve inspect``); a file path may point at either bundle file.
    """
    p = Path(run_dir_or_bundle)
    if p.is_dir():
        if (p / "evidence_bundle.json").exists():
            bundle_path, base = p / "evidence_bundle.json", p
        elif (p / "inspect_bundle.json").exists():
            bundle_path, base = p / "inspect_bundle.json", p
        else:
            return [f"missing {p / 'evidence_bundle.json'} "
                    f"(and no inspect_bundle.json)"]
    else:
        bundle_path, base = p, p.parent
    if bundle_path.name == "inspect_bundle.json":
        return _verify_inspect(bundle_path, base)
    problems: list[str] = []
    if not bundle_path.exists():
        return [f"missing {bundle_path}"]
    try:
        bundle = load(bundle_path)
    except Exception as e:                      # malformed is a verify failure
        return [f"unparseable bundle: {e}"]

    recomputed = sha256_bytes(hashable_bytes(bundle))
    if recomputed != bundle.bundle_hash:
        problems.append(
            f"bundle_hash mismatch: recorded {bundle.bundle_hash[:16]}…, "
            f"recomputed {recomputed[:16]}…")

    sidecar = base / "bundle.sha256"
    if sidecar.exists():
        recorded = sidecar.read_text().split()[0]
        if recorded != sha256_file(bundle_path):
            problems.append(
                "bundle.sha256 sidecar disagrees with evidence_bundle.json "
                "file bytes")
    else:
        problems.append("missing bundle.sha256 sidecar")

    problems += _verify_artifacts(bundle.artifact_index, base)
    return problems


def _verify_artifacts(artifact_index, base: Path) -> list[str]:
    problems: list[str] = []
    for ref in artifact_index:
        try:
            ap = safe_artifact_path(base, ref.path)
        except ValueError as e:
            problems.append(str(e))
            continue
        if not ap.exists():
            problems.append(f"missing artifact {ref.path}")
        elif sha256_file(ap) != ref.sha256:
            problems.append(f"artifact modified: {ref.path}")
    return problems


def _verify_inspect(bundle_path: Path, base: Path) -> list[str]:
    problems: list[str] = []
    try:
        bundle = load_inspect(bundle_path)
    except Exception as e:
        return [f"unparseable bundle: {e}"]

    recomputed = sha256_bytes(
        hashable_bytes(bundle, INSPECT_HASH_EXCLUDED_PATHS))
    if recomputed != bundle.bundle_hash:
        problems.append(
            f"bundle_hash mismatch: recorded {bundle.bundle_hash[:16]}…, "
            f"recomputed {recomputed[:16]}…")

    sidecar = base / "bundle.sha256"
    if sidecar.exists():
        recorded = sidecar.read_text().split()[0]
        if recorded != sha256_file(bundle_path):
            problems.append(
                "bundle.sha256 sidecar disagrees with inspect_bundle.json "
                "file bytes")
    else:
        problems.append("missing bundle.sha256 sidecar")

    problems += _verify_artifacts(bundle.artifact_index, base)
    return problems
