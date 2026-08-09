"""Model-update regression: compare two sealed runs of the same suite.

The change-approval workflow (the reason this exists): a scenario generator
is recalibrated or replaced; old and new versions are each run through
``sieve test``; ``sieve compare`` then answers, per metric, whether the
update changed that dimension's window distribution — and juxtaposes both
sides' vs-reference statuses so a reviewer sees what the change did to
realism, not just that something moved.

Integrity first: both input runs are verified before anything is computed;
a tampered or unsealed run directory is refused. Both runs must carry the
same ``suite_hash`` — comparing across suite versions would be comparing
different measurements.

The output is a durable artifact: ``compare.json`` (canonical bytes, sealed
as ``compare_hash`` with volatile fields nulled), a sha256 sidecar and an
HTML report. CHANGED is a result, not an error.
"""

from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path

import numpy as np
import polars as pl

from sieve import __version__
from sieve.core.hashing import sha256_bytes
from sieve.core.models import (
    COMPARE_HASH_EXCLUDED_PATHS,
    CompareBundle,
    CompareSide,
    MetricComparison,
)
from sieve.core.serialization import canonical_bytes, null_out_excluded
from sieve.inference.multiplicity import ADJUSTMENTS
from sieve.inference.permutation import perm_ks_test
from sieve.provenance import bundle as prov

MIN_WINDOWS = 5


class CompareInputError(ValueError):
    """Refused input: missing run, tampered run, or suite mismatch."""


def _load_side(run_dir: Path, label: str):
    problems = prov.verify(run_dir)
    if problems:
        raise CompareInputError(
            f"run {label} ({run_dir}) fails verification; refusing to "
            "compare unverifiable evidence: " + "; ".join(problems))
    b = prov.load(run_dir / "evidence_bundle.json")
    obs = pl.read_parquet(run_dir / "observations.parquet")
    return b, obs


def seal_compare(cmp_bundle: CompareBundle) -> CompareBundle:
    import json

    data = json.loads(cmp_bundle.model_dump_json())
    body = canonical_bytes(null_out_excluded(data,
                                             COMPARE_HASH_EXCLUDED_PATHS))
    cmp_bundle.compare_hash = sha256_bytes(body)
    return cmp_bundle


def run_compare(run_a: str | Path, run_b: str | Path,
                out_dir: str | Path | None = None,
                master_seed: int = 20260802) -> Path:
    run_a, run_b = Path(run_a), Path(run_b)
    ba, obs_a = _load_side(run_a, "A")
    bb, obs_b = _load_side(run_b, "B")

    if ba.suite.suite_hash != bb.suite.suite_hash:
        raise CompareInputError(
            "suite_hash differs between runs "
            f"({ba.suite.suite_hash[:12]}… vs {bb.suite.suite_hash[:12]}…); "
            "a comparison is only meaningful within one suite version")
    if ba.claim.claim_id != bb.claim.claim_id:
        raise CompareInputError(
            f"claim differs ({ba.claim.claim_id} vs {bb.claim.claim_id})")

    alpha = float(ba.suite.inference.get("alpha", 0.01))
    n_draw = int(ba.suite.inference.get("n_draw", 2000))
    adjust = ADJUSTMENTS[str(ba.suite.inference.get("multiple_testing",
                                                    "holm"))]
    rng = np.random.default_rng(master_seed)

    status_a = {r.metric_ref: r.status for r in ba.results}
    status_b = {r.metric_ref: r.status for r in bb.results}

    caveats_global = [
        "the A-vs-B null is a permutation over windows, valid for "
        "exchangeable window sets; windows cut from one long simulated path "
        "share that path, so within-path long memory makes it slightly "
        "liberal (second-order at 1000-day windows for GARCH-class memory)",
        "NOT_SEPARATED means no detectable difference at the alpha=%.3g "
        "line with this many windows — it is not a claim of equality" % alpha,
        "verdicts are per-metric; nothing aggregates them",
    ]

    results: list[MetricComparison] = []
    raw_p: list[float] = []
    for mref in ba.suite.metrics:
        mid = mref.partition("@")[0]
        va = obs_a[mid].to_numpy() if mid in obs_a.columns else np.array([])
        vb = obs_b[mid].to_numpy() if mid in obs_b.columns else np.array([])
        ks, p, na, nb = perm_ks_test(va, vb, rng, n_draw)
        fa, fb = va[np.isfinite(va)], vb[np.isfinite(vb)]
        results.append(MetricComparison(
            metric_ref=mref, n_a=na, n_b=nb,
            ks_ab=None if not np.isfinite(ks) else ks,
            p_value=None if not np.isfinite(p) else p,
            median_a=None if not len(fa) else float(np.median(fa)),
            median_b=None if not len(fb) else float(np.median(fb)),
            status_a_vs_reference=status_a[mref],
            status_b_vs_reference=status_b[mref],
            verdict="INSUFFICIENT",     # provisional; set after adjustment
        ))
        raw_p.append(p)

    for res, ap in zip(results, adjust(raw_p)):
        if res.p_value is None:
            res.verdict = "INSUFFICIENT"
            res.caveats.append(
                f"fewer than {MIN_WINDOWS} finite windows on one side")
            continue
        res.adjusted_p_value = None if not np.isfinite(ap) else float(ap)
        res.verdict = "CHANGED" if ap < alpha else "NOT_SEPARATED"

    cmp_bundle = CompareBundle(
        compare_id=uuid.uuid4().hex[:12],
        created_at=dt.datetime.now(dt.timezone.utc),
        sieve_version=__version__, master_seed=master_seed,
        suite_id=ba.suite.suite_id, suite_version=ba.suite.version,
        suite_hash=ba.suite.suite_hash, claim_id=ba.claim.claim_id,
        inference={"alpha": alpha, "n_draw": n_draw,
                   "multiple_testing":
                       str(ba.suite.inference.get("multiple_testing",
                                                  "holm")),
                   "null": "window permutation (A/B exchangeable)"},
        side_a=_side(ba, "A"), side_b=_side(bb, "B"),
        results=results, caveats=caveats_global)
    seal_compare(cmp_bundle)

    out_dir = Path(out_dir) if out_dir is not None else (
        Path(".sieve/compares") / cmp_bundle.compare_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    import json

    body = canonical_bytes(json.loads(cmp_bundle.model_dump_json()))
    (out_dir / "compare.json").write_bytes(body)
    (out_dir / "compare.sha256").write_text(
        f"{sha256_bytes(body)}  compare.json\n")

    from sieve.reporting.html import render_compare
    render_compare(out_dir / "report" / "index.html", cmp_bundle)
    return out_dir


def _side(b, label: str) -> CompareSide:
    return CompareSide(
        label=label, bundle_hash=b.bundle_hash,
        model_id=b.model.model_id, model_version=b.model.model_version,
        display_name=b.model.display_name,
        input_hash=b.run_manifest.input_hash,
        n_windows=b.results[0].n_simulation if b.results else 0)


def load_compare(path: str | Path) -> CompareBundle:
    import json

    p = Path(path)
    if p.is_dir():
        p = p / "compare.json"
    return CompareBundle.model_validate(json.loads(p.read_text()))
