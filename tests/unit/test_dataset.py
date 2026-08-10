"""Research input contract (task §3, §9 input/geometry tests).

Every acceptance path, every refusal path, and the two structural
invariants: runs are never concatenated, and derived returns never cross a
run boundary.
"""

import numpy as np
import polars as pl
import pytest

import sieve
from sieve.adapters.dataset import load_dataset
from sieve.core.dataset import Geometry, InputError

RNG = np.random.default_rng(20260810)


def _write(path, text):
    path.write_text(text)
    return path


# ------------------------------------------------------------ file formats

def test_legacy_timestamp_return(tmp_path):
    rows = "\n".join(f"2020-01-{i+1:02d},{v:.6f}"
                     for i, v in enumerate(RNG.standard_normal(28)))
    f = _write(tmp_path / "returns.csv", "timestamp,return\n" + rows + "\n")
    ds, model, dsm = load_dataset(f)
    assert ds.n_runs == 1
    assert ds.time_basis == "timestamp"
    assert ds.runs[0].n_obs == 28
    assert dsm.content_hash


def test_step_return(tmp_path):
    rows = "\n".join(f"{i},{v:.6f}" for i, v in
                     enumerate(RNG.standard_normal(30)))
    f = _write(tmp_path / "r.csv", "step,return\n" + rows + "\n")
    ds, _, _ = load_dataset(f)
    assert ds.time_basis == "step"
    assert ds.runs[0].steps is not None
    assert ds.runs[0].n_obs == 30


def test_step_price_with_explicit_log_conversion(tmp_path):
    p = 100 * np.exp(np.cumsum(0.01 * RNG.standard_normal(50)))
    rows = "\n".join(f"{i},{v:.8f}" for i, v in enumerate(p))
    f = _write(tmp_path / "p.csv", "step,price\n" + rows + "\n")
    ds, _, dsm = load_dataset(f, derive="log")
    r = ds.runs[0].columns["return"]
    assert len(r) == 49
    # prices are written with 8 decimals; parsing back perturbs log-returns
    # by up to ~1e-9, so compare at that scale, not machine epsilon
    np.testing.assert_allclose(r, np.diff(np.log(p)), atol=1e-8, rtol=0)
    assert any(t.name == "derive_return" and t.parameters["method"] == "log"
               for t in dsm.transforms)


def test_price_only_without_derivation_has_no_return(tmp_path):
    f = _write(tmp_path / "p.csv", "step,price\n0,100\n1,101\n2,102\n")
    ds, _, _ = load_dataset(f)          # loading is fine; no silent derive
    assert not ds.has_column("return")
    assert ds.has_column("price")


def test_nonpositive_price_log_return_is_input_error(tmp_path):
    f = _write(tmp_path / "p.csv", "step,price\n0,100\n1,-1\n2,102\n")
    with pytest.raises(InputError, match="<= 0"):
        load_dataset(f, derive="log")


def test_simple_and_diff_derivations(tmp_path):
    f = _write(tmp_path / "p.csv", "step,price\n0,100\n1,110\n2,99\n")
    ds, _, _ = load_dataset(f, derive="simple")
    np.testing.assert_allclose(ds.runs[0].columns["return"],
                               [0.1, 99 / 110 - 1])
    ds, _, _ = load_dataset(f, derive="diff")
    np.testing.assert_allclose(ds.runs[0].columns["return"], [10.0, -11.0])


def test_derive_with_existing_return_column_refused(tmp_path):
    f = _write(tmp_path / "x.csv", "step,price,return\n0,100,0\n1,101,0.01\n")
    with pytest.raises(InputError, match="already has a 'return'"):
        load_dataset(f, derive="log")


def test_long_format_multiple_run_ids(tmp_path):
    lines = ["run_id,step,return"]
    for rid in ("s1", "s2", "s3"):
        for i in range(20):
            lines.append(f"{rid},{i},{RNG.standard_normal():.6f}")
    f = _write(tmp_path / "l.csv", "\n".join(lines) + "\n")
    ds, _, _ = load_dataset(f)
    assert ds.n_runs == 3
    assert [r.run_id for r in ds.runs] == ["s1", "s2", "s3"]
    assert ds.geometry is Geometry.MULTI_RUN_ENSEMBLE
    assert all(r.n_obs == 20 for r in ds.runs)


def test_runs_are_never_concatenated(tmp_path):
    lines = ["run_id,step,return"]
    for rid in ("a", "b"):
        for i in range(15):
            lines.append(f"{rid},{i},{0.5 if rid == 'a' else -0.5}")
    f = _write(tmp_path / "l.csv", "\n".join(lines) + "\n")
    ds, _, _ = load_dataset(f)
    by_run = ds.returns_by_run()
    assert set(by_run) == {"a", "b"}
    assert all(len(v) == 15 for v in by_run.values())   # no 30-length series


def test_derived_returns_do_not_cross_run_boundary(tmp_path):
    # price jumps massively between runs; a cross-boundary return would show
    lines = ["run_id,step,price"]
    for i in range(10):
        lines.append(f"a,{i},{100 + i}")
    for i in range(10):
        lines.append(f"b,{i},{100000 + i}")
    f = _write(tmp_path / "l.csv", "\n".join(lines) + "\n")
    ds, _, _ = load_dataset(f, derive="log")
    for r in ds.returns_by_run().values():
        assert len(r) == 9                       # n-1 per run, not 19/20
        assert np.abs(r).max() < 0.1             # no inter-run jump return


# ------------------------------------------------------------ directory input

def _make_dir(tmp_path, n_runs=3, n=40, manifest=""):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    for k in range(n_runs):
        rows = "\n".join(f"{i},{v:.6f}" for i, v in
                         enumerate(RNG.standard_normal(n)))
        _write(d / "runs" / f"seed-{k+1:03d}.csv", "step,return\n" + rows + "\n")
    if manifest:
        _write(d / "manifest.yaml", manifest)
    return d


def test_directory_of_runs(tmp_path):
    d = _make_dir(tmp_path, n_runs=4)
    ds, model, dsm = load_dataset(d)
    assert ds.n_runs == 4
    assert ds.geometry is Geometry.MULTI_RUN_ENSEMBLE
    assert [r.run_id for r in ds.runs] == [f"seed-{k:03d}" for k in (1, 2, 3, 4)]


def test_directory_manifest_seeds_and_per_run_burn_in(tmp_path):
    d = _make_dir(tmp_path, n_runs=2, n=40, manifest="""\
model_id: toy-abm
runs:
  - {file: runs/seed-001.csv, seed: 11, burn_in_steps: 10}
  - {file: runs/seed-002.csv, seed: 22, burn_in_steps: 5}
""")
    ds, model, _ = load_dataset(d)
    assert model.model_id == "toy-abm"
    assert [r.seed for r in ds.runs] == [11, 22]
    assert [r.n_burned for r in ds.runs] == [10, 5]
    assert [r.n_obs for r in ds.runs] == [30, 35]


def test_unequal_run_lengths_are_fine(tmp_path):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    for k, n in enumerate((30, 50, 70), start=1):
        rows = "\n".join(f"{i},{v:.6f}" for i, v in
                         enumerate(RNG.standard_normal(n)))
        _write(d / "runs" / f"r{k}.csv", "step,return\n" + rows + "\n")
    ds, _, _ = load_dataset(d)
    assert sorted(r.n_obs for r in ds.runs) == [30, 50, 70]


def test_global_burn_in_fraction(tmp_path):
    d = _make_dir(tmp_path, n_runs=2, n=40, manifest="burn_in: {fraction: 0.25}\n")
    ds, _, dsm = load_dataset(d)
    assert all(r.n_burned == 10 and r.n_obs == 30 for r in ds.runs)
    t = next(t for t in dsm.transforms if t.name == "burn_in")
    assert t.parameters["dropped_per_run"] == {"seed-001": 10, "seed-002": 10}


def test_burn_in_dropping_everything_is_input_error(tmp_path):
    f = _write(tmp_path / "r.csv", "step,return\n0,0.1\n1,0.2\n")
    with pytest.raises(InputError, match="drop all"):
        load_dataset(f, burn_in_steps=2)


# ------------------------------------------------------------ refusal paths

def test_duplicated_steps_refused(tmp_path):
    f = _write(tmp_path / "r.csv", "step,return\n0,0.1\n0,0.2\n1,0.3\n")
    with pytest.raises(InputError, match="duplicated step"):
        load_dataset(f)


def test_duplicated_timestamps_refused(tmp_path):
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n2020-01-01,0.1\n2020-01-01,0.2\n")
    with pytest.raises(InputError, match="duplicated timestamp"):
        load_dataset(f)


def test_non_finite_values_refused(tmp_path):
    f = _write(tmp_path / "r.csv", "step,return\n0,0.1\n1,nan\n2,0.3\n")
    with pytest.raises(InputError, match="non-finite"):
        load_dataset(f)


def test_irregular_steps_recorded_not_refused(tmp_path):
    f = _write(tmp_path / "r.csv",
               "step,return\n0,0.1\n1,0.2\n5,0.3\n6,0.4\n")
    ds, _, _ = load_dataset(f)
    assert ds.runs[0].irregular_spacing
    assert any("irregular" in c for c in ds.caveats)


def test_mixed_time_bases_refused(tmp_path):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    _write(d / "runs" / "a.csv", "step,return\n0,0.1\n1,0.2\n")
    _write(d / "runs" / "b.csv", "timestamp,return\n2020-01-01,0.1\n")
    with pytest.raises(InputError, match="mix time bases"):
        load_dataset(d)


def test_declared_single_series_with_multiple_runs_refused(tmp_path):
    d = _make_dir(tmp_path, n_runs=2, manifest="geometry: single_long_series\n")
    with pytest.raises(InputError, match="never concatenates"):
        load_dataset(d)


def test_unknown_geometry_refused(tmp_path):
    d = _make_dir(tmp_path, n_runs=2, manifest="geometry: fancy_new_thing\n")
    with pytest.raises(InputError, match="unknown geometry"):
        load_dataset(d)


# ------------------------------------------------------------ geometry rules

def test_structural_defaults():
    long = sieve.from_arrays(returns=RNG.standard_normal(3000))
    short = sieve.from_arrays(returns=RNG.standard_normal(200))
    multi = sieve.from_runs([{"return": RNG.standard_normal(100)},
                             {"return": RNG.standard_normal(100)}])
    assert long.geometry is Geometry.SINGLE_LONG_SERIES
    assert short.geometry is Geometry.SHORT_EXPLORATORY_SERIES
    assert multi.geometry is Geometry.MULTI_RUN_ENSEMBLE
    assert multi.geometry_source == "structural_default"


def test_declared_geometry_wins():
    ds = sieve.from_runs(
        [{"return": RNG.standard_normal(100)} for _ in range(4)],
        geometry="multi_market_panel")
    assert ds.geometry is Geometry.MULTI_MARKET_PANEL
    assert ds.geometry_source == "declared"


# ------------------------------------------------------------ python API

def test_from_arrays_with_volume():
    ds = sieve.from_arrays(returns=RNG.standard_normal(120),
                           volume=np.abs(RNG.standard_normal(120)))
    assert ds.has_column("volume")


def test_missing_optional_volume_is_simply_absent():
    ds = sieve.from_arrays(returns=RNG.standard_normal(120))
    assert not ds.has_column("volume")
    with pytest.raises(InputError, match="volume"):
        ds.column_by_run("volume")


def test_from_runs_duplicate_run_id_refused():
    with pytest.raises(InputError, match="duplicated run_id"):
        sieve.from_runs([{"run_id": "x", "return": [0.1] * 5},
                         {"run_id": "x", "return": [0.2] * 5}])


def test_from_dataframe_polars_long_format():
    df = pl.DataFrame({
        "run_id": ["a"] * 10 + ["b"] * 10,
        "step": list(range(10)) * 2,
        "return": list(RNG.standard_normal(20)),
    })
    ds = sieve.from_dataframe(df)
    assert ds.n_runs == 2
    assert all(r.n_obs == 10 for r in ds.runs)


def test_from_dataframe_price_with_burn_in():
    p = list(100 * np.exp(np.cumsum(0.01 * RNG.standard_normal(60))))
    ds = sieve.from_dataframe(pl.DataFrame({"price": p}),
                              derive="log", burn_in_steps=10)
    assert ds.runs[0].n_burned == 10
    assert ds.runs[0].n_obs == 49         # 60 - 10 burn-in - 1 derivation
