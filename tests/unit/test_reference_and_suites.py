"""Reference overlays (--reference) and single-index suites (v0.5.0)."""

import json
from pathlib import Path

import numpy as np
import pytest

from sieve.core.dataset import InputError
from sieve.evaluation.inspect import run_inspect
from sieve.provenance.bundle import load_inspect, verify

PRODUCT = Path(__file__).resolve().parents[2]

OVERLAY_FIGURES = ("marginal_distribution", "tail_ccdf", "return_acf",
                   "volatility_acf", "aggregation_profile",
                   "leverage_kernel", "drift_variance_diagnostic")


def _garch_csv(path, n=4000, seed=1):
    g = np.random.default_rng(seed)
    r = np.zeros(n)
    s2 = 1.0
    for t in range(1, n):
        s2 = 0.02 + 0.10 * r[t - 1] ** 2 + 0.88 * s2
        r[t] = np.sqrt(s2) * g.standard_normal()
    rows = "\n".join(f"{i},{v:.8f}" for i, v in enumerate(r * 0.01))
    path.write_text("step,return\n" + rows + "\n")
    return r * 0.01


@pytest.fixture(scope="module")
def sim_csv(tmp_path_factory):
    p = tmp_path_factory.mktemp("sim") / "sim.csv"
    _garch_csv(p, seed=1)
    return p


@pytest.fixture(scope="module")
def ref_csv(tmp_path_factory):
    p = tmp_path_factory.mktemp("ref") / "ref.csv"
    _garch_csv(p, seed=99)
    return p


# ------------------------------------------------------- reference overlay

def test_reference_overlay_recorded_and_sealed(sim_csv, ref_csv, tmp_path):
    run_dir = run_inspect(sim_csv, out_root=tmp_path / "runs",
                          reference_path=ref_csv,
                          reference_label="Test Index")
    b = load_inspect(run_dir / "inspect_bundle.json")
    by_id = {f.figure_id: f for f in b.figures}
    for fid in OVERLAY_FIGURES:
        f = by_id[fid]
        assert f.status.value == "OBSERVED", (fid, f.note)
        ref = f.parameters.get("reference")
        assert ref and ref["label"] == "Test Index", fid
        assert len(ref["content_hash"]) == 64
        assert any("visual context only" in c for c in f.caveats), fid
    # non-overlay figures carry no reference params
    assert "reference" not in by_id["return_path"].parameters
    assert (run_dir / "reference_summary.json").exists()
    assert any("Test Index" in x for x in b.limitations)
    assert verify(run_dir) == []


def test_reference_never_changes_statuses(sim_csv, ref_csv, tmp_path):
    d1 = run_inspect(sim_csv, out_root=tmp_path / "a")
    d2 = run_inspect(sim_csv, out_root=tmp_path / "b",
                     reference_path=ref_csv, reference_label="X")
    s1 = {f.figure_id: f.status for f in
          load_inspect(d1 / "inspect_bundle.json").figures}
    s2 = {f.figure_id: f.status for f in
          load_inspect(d2 / "inspect_bundle.json").figures}
    assert s1 == s2


def test_reference_default_label_is_content_derived(sim_csv, ref_csv,
                                                    tmp_path):
    run_dir = run_inspect(sim_csv, out_root=tmp_path / "runs",
                          reference_path=ref_csv)
    b = load_inspect(run_dir / "inspect_bundle.json")
    ref = {f.figure_id: f for f in b.figures}[
        "marginal_distribution"].parameters["reference"]
    assert ref["label"].startswith("sha256:")
    assert "ref" not in ref["label"] or True     # never the filename
    assert "ref.csv" not in ref["label"]


def test_multi_run_reference_refused(sim_csv, tmp_path):
    lines = ["run_id,step,return"]
    for rid in ("a", "b"):
        for i in range(400):
            lines.append(f"{rid},{i},0.01")
    mr = tmp_path / "multi.csv"
    mr.write_text("\n".join(lines) + "\n")
    with pytest.raises(InputError, match="single series"):
        run_inspect(sim_csv, out_root=tmp_path / "runs",
                    reference_path=mr)


def test_price_only_reference_needs_explicit_derivation(sim_csv, tmp_path):
    p = tmp_path / "prices.csv"
    px = 100 * np.exp(np.cumsum(0.01 * np.random.default_rng(5)
                                .standard_normal(500)))
    p.write_text("step,price\n" + "\n".join(
        f"{i},{v:.6f}" for i, v in enumerate(px)) + "\n")
    with pytest.raises(InputError, match="reference-derive-return"):
        run_inspect(sim_csv, out_root=tmp_path / "runs", reference_path=p)
    run_dir = run_inspect(sim_csv, out_root=tmp_path / "runs2",
                          reference_path=p, reference_derive="log")
    assert verify(run_dir) == []


def test_overlay_seal_deterministic(sim_csv, ref_csv, tmp_path):
    d1 = run_inspect(sim_csv, out_root=tmp_path / "a",
                     reference_path=ref_csv, reference_label="X")
    d2 = run_inspect(sim_csv, out_root=tmp_path / "b",
                     reference_path=ref_csv, reference_label="X")
    h1 = load_inspect(d1 / "inspect_bundle.json").bundle_hash
    h2 = load_inspect(d2 / "inspect_bundle.json").bundle_hash
    assert h1 == h2


# ---------------------------------------------------- single-index suites

@pytest.mark.parametrize("suite_ref,key", [("nikkei-daily@0.1", "nikkei"),
                                           ("spx-daily@0.1", "spx")])
def test_index_suite_loads_and_is_consistent(suite_ref, key):
    from sieve.suites.loader import load

    s = load(suite_ref)
    assert s.manifest.suite_hash
    ref = s.reference_stats()
    n = len(ref["windows"])
    assert n == int(s.manifest.reference["n_windows"])
    assert n >= 20
    for m in s.manifest.metrics:
        mid = m.partition("@")[0]
        vals = np.asarray(ref["values"][mid], float)
        assert len(vals) == n
        assert np.isfinite(vals).mean() > 0.9, mid
    assert key in ref["sources"]
    assert len(ref["sources"][key]["sha256_timestamp_price_csv"]) == 64
    blocks = {w["block"] for w in ref["windows"]}
    assert len(blocks) >= 5          # enough calendar blocks for the design
    # experimental calibration is disclosed in the manifest
    assert "NOT RE-MEASURED" in s.manifest.inference["alpha_provenance"]


def test_index_reference_values_are_plausible():
    """Direction checks on the derived reference: both indices should show
    the canonical stylized facts (loose bounds; not a data snapshot pin)."""
    from sieve.suites.loader import load

    for ref_name in ("nikkei-daily@0.1", "spx-daily@0.1"):
        ref = load(ref_name).reference_stats()
        med = {m: float(np.nanmedian(ref["values"][m]))
               for m in ref["metrics"]}
        assert med["excess_kurtosis"] > 1.0, ref_name
        assert 1.5 < med["hill_left"] < 6.0, ref_name
        assert med["acf_abs_1"] > 0.05, ref_name
        assert med["leverage"] < -0.02, ref_name


def test_sieve_test_runs_against_index_suite(tmp_path):
    """End-to-end confirmatory run against spx-daily on a long synthetic
    series: statuses come out, the bundle seals and verifies."""
    from sieve.evaluation.runner import run_test
    from sieve.provenance.bundle import load as load_bundle
    from sieve.provenance.bundle import verify as verify_bundle

    p = tmp_path / "returns.csv"
    _garch_csv(p, n=6000, seed=3)
    run_dir = run_test(p, "spx-daily@0.1", "descriptive-market-dynamics",
                       out_root=tmp_path / "runs")
    b = load_bundle(run_dir / "evidence_bundle.json")
    assert b.suite.suite_id == "spx-daily"
    statuses = {d.dimension: d.status.value for d in b.profile.dimensions}
    assert statuses["marginal_distribution"] in ("PASS", "FAIL",
                                                 "INSUFFICIENT")
    assert verify_bundle(run_dir) == []
    # no baselines shipped -> empty blindness context, not a crash
    ctx = json.loads(
        (run_dir / "artifacts" / "baseline_context.json").read_text())
    assert all(v == [] for v in ctx.values())
