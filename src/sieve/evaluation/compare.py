"""Model-update regression: compare two sealed runs of the same suite.

The change-approval workflow: a scenario generator is recalibrated or
replaced; old and new versions are each run through ``sieve test``;
``sieve compare`` then answers three questions a reviewer actually asks:

1. **What moved?** Per metric, a window-permutation test on the two runs'
   window values (verdict CHANGED / NOT_SEPARATED / INSUFFICIENT), with the
   measured size of that test cited from the calibration study.
2. **Which way?** Each move is read against the reference gate as a
   ``transition`` — REGRESSION (A passed, B fails), IMPROVEMENT,
   CHANGED_WITHIN_GATE (moved, but the reference gate cannot see it),
   STABLE, INDETERMINATE — plus the declared manifest parameter diff and
   median shifts, so the report points at causes, not just symptoms.
3. **Does a human need to look?** A versioned approval policy — a rule
   over the claim's required dimensions, never a score — yields
   NO_CHANGE_DETECTED or REVIEW_REQUIRED with the triggering rows listed.

Integrity first: both input runs are verified before anything is computed;
a tampered or unsealed run directory is refused. Both runs must carry the
same ``suite_hash`` — comparing across suite versions would be comparing
different measurements.

The output is a durable artifact: ``compare.json`` (canonical bytes, sealed
as ``compare_hash`` with volatile fields nulled), a sha256 sidecar and an
HTML report. REVIEW_REQUIRED is a result, not an error.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

import numpy as np
import polars as pl

from sieve import __version__
from sieve.core.enums import Status
from sieve.core.hashing import sha256_bytes
from sieve.core.models import (
    COMPARE_HASH_EXCLUDED_PATHS,
    ApprovalAssessment,
    CompareBundle,
    CompareSide,
    MetricComparison,
    ParameterChange,
)
from sieve.core.serialization import canonical_bytes, null_out_excluded
from sieve.inference.multiplicity import ADJUSTMENTS
from sieve.inference.permutation import perm_ks_test
from sieve.metrics import registry as metric_registry
from sieve.provenance import bundle as prov

MIN_WINDOWS = 5

# Measured by tools/calibrate_compare.py (frozen in
# docs/compare-calibration.json); regenerate both together whenever the
# compare design changes. Values are family-wise "any metric flagged" rates
# under H0 (same parameters, independent seeds) at the alpha=0.01 line.
MEASURED_SIZE = {"15v15": 0.005, "6v6": 0.0,
                 "source": "docs/compare-calibration.json"}

POLICY_ID = "required-dims-no-unexplained-change"
POLICY_VERSION = "1"
POLICY_TEXT = (
    "REVIEW_REQUIRED if any metric on one of the claim's required "
    "dimensions has verdict CHANGED or transition REGRESSION or "
    "INDETERMINATE, or if any metric on any dimension has transition "
    "REGRESSION. IMPROVEMENT alone never triggers. Otherwise "
    "NO_CHANGE_DETECTED. This is a routing rule for human review, applied "
    "per metric; nothing is weighted, summed or averaged.")


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
    data = json.loads(cmp_bundle.model_dump_json())
    body = canonical_bytes(null_out_excluded(data,
                                             COMPARE_HASH_EXCLUDED_PATHS))
    cmp_bundle.compare_hash = sha256_bytes(body)
    return cmp_bundle


def _transition(sa: Status, sb: Status, verdict: str) -> str:
    if (verdict == "INSUFFICIENT" or Status.INSUFFICIENT in (sa, sb)
            or Status.NOT_TESTED in (sa, sb)):
        return "INDETERMINATE"
    if sa is Status.PASS and sb is Status.FAIL:
        return "REGRESSION"
    if sa is Status.FAIL and sb is Status.PASS:
        return "IMPROVEMENT"
    return "CHANGED_WITHIN_GATE" if verdict == "CHANGED" else "STABLE"


def _parameter_changes(pa: dict, pb: dict) -> list[ParameterChange]:
    out = []
    for k in sorted(set(pa) | set(pb)):
        va, vb = pa.get(k), pb.get(k)
        if va != vb:
            out.append(ParameterChange(name=k, value_a=va, value_b=vb))
    return out


def _apply_policy(results: list[MetricComparison],
                  required_dims: list[str]) -> ApprovalAssessment:
    triggered = []
    for r in results:
        mid = r.metric_ref.partition("@")[0]
        on_required = r.dimension in required_dims
        if r.transition == "REGRESSION":
            triggered.append(f"{mid}: REGRESSION")
        elif on_required and r.verdict == "CHANGED":
            triggered.append(f"{mid}: CHANGED on required dimension "
                             f"{r.dimension}")
        elif on_required and r.transition == "INDETERMINATE":
            triggered.append(f"{mid}: INDETERMINATE on required dimension "
                             f"{r.dimension}")
    return ApprovalAssessment(
        policy_id=POLICY_ID, policy_version=POLICY_VERSION,
        policy_text=POLICY_TEXT,
        outcome="REVIEW_REQUIRED" if triggered else "NO_CHANGE_DETECTED",
        triggered_by=triggered, required_dimensions=list(required_dims))


def run_compare(run_a: str | Path, run_b: str | Path,
                out_dir: str | Path | None = None,
                master_seed: int = 20260802,
                link_a: str | None = None,
                link_b: str | None = None) -> Path:
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

    size_note = (
        "measured family-wise false-positive rate of this design under H0 "
        f"(same parameters, independent seeds): {MEASURED_SIZE['15v15']} at "
        f"15v15 windows (n=400 pairs), {MEASURED_SIZE['6v6']} at 6v6 "
        f"(n=200) — conservative relative to the nominal alpha "
        f"({MEASURED_SIZE['source']}, tools/calibrate_compare.py)"
        if MEASURED_SIZE["15v15"] is not None else
        "the size of this design has not been measured yet "
        "(tools/calibrate_compare.py)")
    caveats_global = [
        "the A-vs-B null is a permutation over windows, valid for "
        "exchangeable window sets; windows cut from one long simulated path "
        "share that path", size_note,
        "measured power boundary: persistence drifts of |delta beta| <= "
        "0.04 are mostly undetected at 15v15 windows, and a tail-df clip "
        "alone at high persistence is nearly invisible to unconditional "
        "window statistics (docs/compare-calibration.md)",
        "NOT_SEPARATED means no detectable difference at the alpha=%.3g "
        "line with this many windows — it is not a claim of equality"
        % alpha,
        "the approval outcome is a versioned routing rule over required "
        "dimensions, not an aggregate; verdicts remain per-metric",
    ]

    results: list[MetricComparison] = []
    raw_p: list[float] = []
    for mref in ba.suite.metrics:
        mid = mref.partition("@")[0]
        _, _, dim = metric_registry.resolve(mref)
        va = obs_a[mid].to_numpy() if mid in obs_a.columns else np.array([])
        vb = obs_b[mid].to_numpy() if mid in obs_b.columns else np.array([])
        ks, p, na, nb = perm_ks_test(va, vb, rng, n_draw)
        fa, fb = va[np.isfinite(va)], vb[np.isfinite(vb)]
        ma = float(np.median(fa)) if len(fa) else None
        mb = float(np.median(fb)) if len(fb) else None
        pct = (100.0 * (mb - ma) / abs(ma)
               if ma is not None and mb is not None and abs(ma) > 0
               else None)
        results.append(MetricComparison(
            metric_ref=mref, dimension=dim, n_a=na, n_b=nb,
            ks_ab=None if not np.isfinite(ks) else ks,
            p_value=None if not np.isfinite(p) else p,
            median_a=ma, median_b=mb, median_change_pct=pct,
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
        else:
            res.adjusted_p_value = (None if not np.isfinite(ap)
                                    else float(ap))
            res.verdict = "CHANGED" if ap < alpha else "NOT_SEPARATED"
        res.transition = _transition(res.status_a_vs_reference,
                                     res.status_b_vs_reference, res.verdict)

    approval = _apply_policy(results, ba.claim.required_dimensions)

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
                   "null": "window permutation (A/B exchangeable)",
                   "measured_size_familywise": MEASURED_SIZE},
        side_a=_side(ba, "A"), side_b=_side(bb, "B"),
        parameter_changes=_parameter_changes(ba.model.parameters,
                                             bb.model.parameters),
        results=results, approval=approval, caveats=caveats_global)
    seal_compare(cmp_bundle)

    out_dir = Path(out_dir) if out_dir is not None else (
        Path(".sieve/compares") / cmp_bundle.compare_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = canonical_bytes(json.loads(cmp_bundle.model_dump_json()))
    (out_dir / "compare.json").write_bytes(body)
    (out_dir / "compare.sha256").write_text(
        f"{sha256_bytes(body)}  compare.json\n")

    from sieve.reporting.html import render_compare
    render_compare(out_dir / "report" / "index.html", cmp_bundle,
                   link_a=link_a, link_b=link_b)
    return out_dir


def _side(b, label: str) -> CompareSide:
    return CompareSide(
        label=label, bundle_hash=b.bundle_hash,
        model_id=b.model.model_id, model_version=b.model.model_version,
        display_name=b.model.display_name,
        input_hash=b.run_manifest.input_hash,
        n_windows=b.results[0].n_simulation if b.results else 0)


def load_compare(path: str | Path) -> CompareBundle:
    p = Path(path)
    if p.is_dir():
        p = p / "compare.json"
    return CompareBundle.model_validate(json.loads(p.read_text()))
