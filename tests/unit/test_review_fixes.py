"""Regression tests for the adversarial-review findings (v0.4.0).

Each test pins one confirmed defect from the pre-release review so it
cannot silently return: path-independent seals, manifest-key refusals,
shared geometry guards, timestamp dataframes, derivation minimums,
metric-consistent Hill overlays, escaped report HTML, and byte-stable
report re-rendering.
"""

import shutil

import numpy as np
import polars as pl
import pytest

import sieve
from sieve.adapters.dataset import load_dataset
from sieve.core.dataset import InputError
from sieve.evaluation.inspect import run_inspect
from sieve.provenance.bundle import load_inspect, verify

RNG = np.random.default_rng(20260811)


def _write_run(path, n=400, seed=0):
    rng = np.random.default_rng(seed)
    rows = "\n".join(f"{i},{v:.6f}" for i, v in
                     enumerate(rng.standard_normal(n)))
    path.write_text("step,return\n" + rows + "\n")


# ------------------------------------------------ path-independent identity

def test_same_bytes_different_directory_name_same_seal(tmp_path):
    a = tmp_path / "experiment_a"
    (a / "runs").mkdir(parents=True)
    for k in range(2):
        _write_run(a / "runs" / f"seed-{k}.csv", seed=k)
    b = tmp_path / "renamed_elsewhere"
    shutil.copytree(a, b)
    ra = run_inspect(a, out_root=tmp_path / "ra")
    rb = run_inspect(b, out_root=tmp_path / "rb")
    ha = load_inspect(ra / "inspect_bundle.json").bundle_hash
    hb = load_inspect(rb / "inspect_bundle.json").bundle_hash
    assert ha == hb


def test_same_bytes_renamed_bare_csv_same_seal(tmp_path):
    f1 = tmp_path / "mydata.csv"
    _write_run(f1, seed=3)
    f2 = tmp_path / "final_v2.csv"
    f2.write_bytes(f1.read_bytes())
    r1 = run_inspect(f1, out_root=tmp_path / "r1")
    r2 = run_inspect(f2, out_root=tmp_path / "r2")
    b1 = load_inspect(r1 / "inspect_bundle.json")
    b2 = load_inspect(r2 / "inspect_bundle.json")
    assert b1.bundle_hash == b2.bundle_hash
    assert b1.geometry.runs[0].run_id == "run-0"       # not the filename


def test_renaming_a_run_file_changes_declared_identity(tmp_path):
    """Run-file names ARE part of directory-input identity (they name the
    runs), so renaming one changes content_hash — declared, not leaked."""
    a = tmp_path / "exp"
    (a / "runs").mkdir(parents=True)
    _write_run(a / "runs" / "seed-1.csv", seed=1)
    _write_run(a / "runs" / "seed-2.csv", seed=2)
    _, _, d1 = load_dataset(a)
    (a / "runs" / "seed-2.csv").rename(a / "runs" / "other.csv")
    _, _, d2 = load_dataset(a)
    assert d1.content_hash != d2.content_hash


# ------------------------------------------------ manifest key refusals

def test_mismatched_manifest_run_id_applies_rename(tmp_path):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    _write_run(d / "runs" / "seed-001.csv", seed=1)
    (d / "manifest.yaml").write_text(
        "runs:\n"
        "  - {file: runs/seed-001.csv, run_id: my-run, seed: 11, "
        "burn_in_steps: 10}\n")
    ds, _, _ = load_dataset(d)
    run = ds.runs[0]
    assert run.run_id == "my-run"
    assert run.seed == 11
    assert run.n_burned == 10          # was silently dropped before the fix


def test_per_entry_settings_on_long_format_file_refused(tmp_path):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    lines = ["run_id,step,return"]
    for rid in ("a", "b"):
        for i in range(20):
            lines.append(f"{rid},{i},0.01")
    (d / "runs" / "multi.csv").write_text("\n".join(lines) + "\n")
    (d / "manifest.yaml").write_text(
        "runs:\n  - {file: runs/multi.csv, seed: 5}\n")
    with pytest.raises(InputError, match="per-run settings"):
        load_dataset(d)


def test_unknown_seed_mapping_key_refused(tmp_path):
    f = tmp_path / "r.csv"
    _write_run(f, seed=4)
    (tmp_path / "manifest.yaml").write_text("seeds: {nonexistent-run: 1}\n")
    with pytest.raises(InputError, match="not present in the input"):
        load_dataset(f)


# ------------------------------------------------ shared geometry guard

def test_api_single_long_series_with_multiple_runs_refused():
    with pytest.raises(InputError, match="never concatenates"):
        sieve.from_runs([{"return": RNG.standard_normal(100)},
                         {"return": RNG.standard_normal(100)}],
                        geometry="single_long_series")


# ------------------------------------------------ dataframe timestamp path

def test_from_dataframe_timestamp_supported_not_dropped():
    df = pl.DataFrame({
        "timestamp": [f"2020-01-{i + 1:02d}" for i in range(10)],
        "return": list(RNG.standard_normal(10)),
    })
    ds = sieve.from_dataframe(df)
    assert ds.time_basis == "timestamp"
    assert ds.runs[0].timestamps is not None


def test_from_dataframe_duplicate_timestamp_refused():
    df = pl.DataFrame({"timestamp": ["2020-01-01", "2020-01-01"],
                       "return": [0.1, 0.2]})
    with pytest.raises(InputError, match="duplicated timestamp"):
        sieve.from_dataframe(df)


def test_from_dataframe_step_and_timestamp_refused():
    df = pl.DataFrame({"step": [0, 1], "timestamp": ["a", "b"],
                       "return": [0.1, 0.2]})
    with pytest.raises(InputError, match="both 'step' and 'timestamp'"):
        sieve.from_dataframe(df)


# ------------------------------------------------ derivation minimums

def test_burn_in_plus_derivation_leaving_nothing_refused(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("step,price\n0,100\n1,101\n")
    with pytest.raises(InputError, match="derivation consumes one row"):
        load_dataset(f, derive="log", burn_in_steps=1)


def test_single_price_row_refused(tmp_path):
    f = tmp_path / "p.csv"
    f.write_text("step,price\n0,100\n")
    with pytest.raises(InputError, match="derivation consumes one row"):
        load_dataset(f, derive="log")


# ------------------------------------------------ figure-metric consistency

def test_tail_overlay_alpha_matches_metric_definition():
    """The tail pool is scaled but NOT centered, so a pooled single-run
    Hill equals the registered metric exactly (Hill is scale-invariant)."""
    from sieve.figures.compute import hill_overlay
    from sieve.metrics.registry import compute

    r = RNG.standard_normal(4000) + 0.03      # nonzero mean matters
    z = r / r.std()
    h = hill_overlay(z[z > 0], 0.05)
    assert h["alpha"] == pytest.approx(compute("hill_right@1", r), rel=1e-12)


def test_volume_pooling_does_not_fabricate_cross_run_relation(tmp_path):
    """Two runs with no within-run relation but different levels must not
    produce a rising pooled binned-mean curve (Simpson guard)."""
    from sieve.figures import registry as freg

    runs = []
    for k, (vol_level, r_scale) in enumerate([(100.0, 0.01), (1000.0, 0.05)]):
        g = np.random.default_rng(k)
        runs.append({"run_id": f"s{k}",
                     "return": r_scale * g.standard_normal(2000),
                     "volume": vol_level + g.standard_normal(2000)})
    ds = sieve.from_runs(runs)
    (res,) = freg.render_figures(ds, ["volume_volatility@1"], tmp_path)
    key = "spearman_volume_absret_run_median"
    assert abs(res.summary_values[key]) < 0.1
    # the SVG's binned-mean line must stay flat: parse its polyline y-range
    svg = (tmp_path / "figures" / "volume_volatility.svg").read_text()
    assert "per-run mean = 1" in svg


# ------------------------------------------------ report escaping + re-render

def test_report_escapes_manifest_controlled_html(tmp_path):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    _write_run(d / "runs" / "seed-1.csv", seed=9)
    (d / "manifest.yaml").write_text(
        'display_name: "<script>alert(1)</script>"\n'
        'model_id: injected\n')
    run_dir = run_inspect(d, out_root=tmp_path / "runs-out")
    html = (run_dir / "report" / "index.html").read_text()
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_report_rerender_is_byte_identical_and_verifies(tmp_path):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    for k in range(2):
        _write_run(d / "runs" / f"seed-{k}.csv", seed=k)
    run_dir = run_inspect(d, out_root=tmp_path / "runs-out")
    before = (run_dir / "report" / "index.html").read_bytes()
    from sieve.reporting.html import render_inspect_report

    b = load_inspect(run_dir / "inspect_bundle.json")
    render_inspect_report(run_dir / "report" / "index.html", b, run_dir)
    after = (run_dir / "report" / "index.html").read_bytes()
    assert before == after
    assert verify(run_dir) == []
