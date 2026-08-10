"""Inspect golden path (task §4.1, §9): the exploratory workflow produces a
complete, deterministic, verifiable, PASS/FAIL-free run directory."""

import json
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from sieve.evaluation.inspect import run_inspect
from sieve.provenance.bundle import load_inspect, verify

PRODUCT = Path(__file__).resolve().parents[2]
EXAMPLE = PRODUCT / "examples" / "abm_ensemble"

EXPECTED_FILES = (
    "manifest.json", "dataset_summary.json", "observations.parquet",
    "figures.json", "inspect_bundle.json", "bundle.sha256",
    "report/index.html",
)
IMPLEMENTED_FIGURES = (
    "return_path", "marginal_distribution", "tail_ccdf", "return_acf",
    "volatility_acf", "aggregation_profile", "leverage_kernel",
    "drift_variance_diagnostic", "volume_volatility",
)
PLANNED_FIGURES = ("conditional_tails", "timescale_asymmetry",
                   "gain_loss_asymmetry")


@pytest.fixture(scope="module")
def run_dir(tmp_path_factory) -> Path:
    return run_inspect(EXAMPLE, out_root=tmp_path_factory.mktemp("runs"))


@pytest.fixture(scope="module")
def bundle(run_dir):
    return load_inspect(run_dir / "inspect_bundle.json")


def test_all_outputs_exist(run_dir):
    for rel in EXPECTED_FILES:
        assert (run_dir / rel).exists(), rel
    for fid in IMPLEMENTED_FIGURES:
        assert (run_dir / "figures" / f"{fid}.svg").exists(), fid


def test_verify_intact(run_dir):
    assert verify(run_dir) == []


def test_deterministic_seal(run_dir, bundle, tmp_path_factory):
    d2 = run_inspect(EXAMPLE, out_root=tmp_path_factory.mktemp("runs2"))
    b2 = load_inspect(d2 / "inspect_bundle.json")
    assert bundle.bundle_hash == b2.bundle_hash
    # figure bytes are part of determinism too
    for fid in ("tail_ccdf", "leverage_kernel"):
        a = (run_dir / "figures" / f"{fid}.svg").read_bytes()
        b = (d2 / "figures" / f"{fid}.svg").read_bytes()
        assert a == b, fid


def test_no_pass_fail_anywhere(bundle):
    allowed = {"OBSERVED", "INSUFFICIENT", "NOT_APPLICABLE", "NOT_TESTED"}
    assert {f.status.value for f in bundle.figures} <= allowed
    assert {ob.status.value for ob in bundle.metric_observations} <= allowed
    body = json.dumps(json.loads(
        bundle.model_dump_json()), ensure_ascii=False)
    assert '"PASS"' not in body and '"FAIL"' not in body


def test_geometry_and_preprocessing_recorded(bundle):
    g = bundle.geometry
    assert g.geometry == "multi_run_ensemble"
    assert g.geometry_source == "declared"
    assert g.time_basis == "step"
    assert g.n_runs == 6
    assert all(r.n_burned == 500 for r in g.runs)
    assert all(r.n_obs == 2999 for r in g.runs)      # 3500 - 500 - 1 (derive)
    assert all(r.seed is not None for r in g.runs)
    tnames = [t.name for t in bundle.dataset.transforms]
    assert "burn_in" in tnames and "derive_return" in tnames


def test_planned_figures_are_not_tested(bundle):
    by_id = {f.figure_id: f for f in bundle.figures}
    for fid in PLANNED_FIGURES:
        assert by_id[fid].status.value == "NOT_TESTED"
        assert by_id[fid].artifact_path is None


def test_report_is_offline_and_exploratory(run_dir):
    html = (run_dir / "report" / "index.html").read_text()
    assert "EXPLORATORY REPORT" in html
    # self-contained: no external scripts, stylesheets, images or fonts
    assert "<script" not in html
    assert "<link" not in html
    assert 'src="http' not in html and "src='http" not in html
    assert "@import" not in html
    # the only URLs allowed are XML namespace identifiers inside inline SVG
    import re
    for url in re.findall(r'https?://[^"\'< ]+', html):
        assert url.startswith("http://www.w3.org/"), url
    # figures are inlined, so the report survives being moved alone
    for fid in IMPLEMENTED_FIGURES:
        assert f"fig-{fid}" in html


def test_report_numbers_match_parquet(run_dir, bundle):
    """Figure scalar summaries must equal medians of observations.parquet."""
    df = pl.read_parquet(run_dir / "observations.parquet")
    by_id = {f.figure_id: f for f in bundle.figures}
    lev = by_id["leverage_kernel"].summary_values["leverage_run_median"]
    assert lev == pytest.approx(float(np.median(df["leverage"])), abs=1e-12)
    k = by_id["marginal_distribution"].summary_values[
        "excess_kurtosis_run_median"]
    assert k == pytest.approx(float(np.median(df["excess_kurtosis"])),
                              abs=1e-12)


def test_parquet_matches_direct_metric_computation(run_dir):
    from sieve.adapters.dataset import load_dataset
    from sieve.metrics.registry import compute

    df = pl.read_parquet(run_dir / "observations.parquet")
    ds, _, _ = load_dataset(EXAMPLE)
    by_run = ds.returns_by_run()
    for i, rid in enumerate(df["run_id"]):
        assert df["acf_abs_1"][i] == pytest.approx(
            compute("acf_abs_1@1", by_run[rid]), abs=1e-15)


def test_figures_are_sealed(run_dir, bundle):
    sealed = {a.path for a in bundle.artifact_index}
    for fid in IMPLEMENTED_FIGURES:
        assert f"figures/{fid}.svg" in sealed


def test_tampered_figure_fails_verify(run_dir, tmp_path):
    import shutil

    dst = tmp_path / "copy"
    shutil.copytree(run_dir, dst)
    p = dst / "figures" / "tail_ccdf.svg"
    p.write_text(p.read_text() + "<!-- tampered -->\n")
    problems = verify(dst)
    assert any("figures/tail_ccdf.svg" in x for x in problems)


def test_single_short_run_works(tmp_path):
    """inspect must work on one short exploratory series (task §4.1)."""
    rng = np.random.default_rng(3)
    rows = "\n".join(f"{i},{v:.6f}"
                     for i, v in enumerate(rng.standard_normal(400)))
    f = tmp_path / "short.csv"
    f.write_text("step,return\n" + rows + "\n")
    run_dir = run_inspect(f, out_root=tmp_path / "runs")
    b = load_inspect(run_dir / "inspect_bundle.json")
    assert b.geometry.geometry == "short_exploratory_series"
    by_id = {fig.figure_id: fig for fig in b.figures}
    # 400 obs: path/marginal/return_acf render; aggregation (min 400) too
    assert by_id["return_path"].status.value == "OBSERVED"
    assert by_id["marginal_distribution"].status.value == "OBSERVED"
    # volume is absent → NOT_APPLICABLE, not an error
    assert by_id["volume_volatility"].status.value == "NOT_APPLICABLE"
    assert verify(run_dir) == []


def test_constant_series_degrades_not_crashes(tmp_path):
    rows = "\n".join(f"{i},0.0" for i in range(500))
    f = tmp_path / "const.csv"
    f.write_text("step,return\n" + rows + "\n")
    run_dir = run_inspect(f, out_root=tmp_path / "runs")
    b = load_inspect(run_dir / "inspect_bundle.json")
    assert (run_dir / "report" / "index.html").exists()
    by_id = {fig.figure_id: fig for fig in b.figures}
    assert by_id["marginal_distribution"].status.value == "INSUFFICIENT"
    assert by_id["return_acf"].status.value == "INSUFFICIENT"
    assert verify(run_dir) == []
