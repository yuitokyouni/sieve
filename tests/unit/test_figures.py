"""Figure registry and figure/metric consistency (task §9 figure tests)."""

import numpy as np
import pytest

import sieve
from sieve.core.enums import ExploratoryStatus
from sieve.figures import compute as C
from sieve.figures import registry as freg
from sieve.metrics.registry import compute as metric_compute

RNG = np.random.default_rng(20260810)


def _garch(n: int, seed: int, gamma: float = 0.0) -> np.ndarray:
    """GARCH(1,1) with optional GJR-style sign asymmetry (gamma)."""
    g = np.random.default_rng(seed)
    r = np.zeros(n)
    s2 = 1.0
    for t in range(1, n):
        asym = gamma if r[t - 1] < 0 else 0.0
        s2 = 0.05 + (0.07 + asym) * r[t - 1] ** 2 + 0.88 * s2
        r[t] = np.sqrt(s2) * g.standard_normal()
    return r


@pytest.fixture(scope="module")
def single_run():
    return sieve.from_arrays(returns=_garch(4000, 5), run_id="only")


@pytest.fixture(scope="module")
def ensemble():
    return sieve.from_runs([{"run_id": f"s{k}", "return": _garch(2000, k),
                             "seed": k} for k in range(1, 5)])


def test_registry_resolves_all_suite_figures():
    from sieve.suites.loader import load

    suite = load("financial-stylized-facts@0.1")
    for ref in suite.figures:
        fn, spec = freg.resolve(ref)
        assert spec.figure_id == ref.partition("@")[0]


def test_unknown_figure_rejected():
    with pytest.raises(KeyError):
        freg.resolve("totally_new_plot@1")


def test_all_figures_render_svg_files(single_run, tmp_path):
    refs = [f"{s.figure_id}@1" for s in freg.all_specs() if s.implemented
            and s.required_columns == ["return"]]
    results = freg.render_figures(single_run, refs, tmp_path)
    for r in results:
        assert r.status is ExploratoryStatus.OBSERVED, (r.figure_id, r.note)
        assert (tmp_path / r.artifact_path).exists()
        svg = (tmp_path / r.artifact_path).read_text()
        assert svg.startswith("<svg ")
        assert "http" not in svg.replace("http://www.w3.org", "")


def test_svg_bytes_deterministic(single_run, tmp_path):
    a = freg.render_figures(single_run, ["tail_ccdf@1"], tmp_path / "a")
    freg.render_figures(single_run, ["tail_ccdf@1"], tmp_path / "b")
    assert a[0].status is ExploratoryStatus.OBSERVED
    assert ((tmp_path / "a" / "figures" / "tail_ccdf.svg").read_bytes()
            == (tmp_path / "b" / "figures" / "tail_ccdf.svg").read_bytes())


def test_missing_volume_is_not_applicable(single_run, tmp_path):
    (r,) = freg.render_figures(single_run, ["volume_volatility@1"], tmp_path)
    assert r.status is ExploratoryStatus.NOT_APPLICABLE
    assert "volume" in r.note


def test_too_few_observations_is_insufficient(tmp_path):
    ds = sieve.from_arrays(returns=RNG.standard_normal(80))
    (r,) = freg.render_figures(ds, ["tail_ccdf@1"], tmp_path)
    assert r.status is ExploratoryStatus.INSUFFICIENT
    assert "minimum" in r.note


def test_unimplemented_figure_is_not_tested(single_run, tmp_path):
    (r,) = freg.render_figures(single_run, ["gain_loss_asymmetry@1"],
                               tmp_path)
    assert r.status is ExploratoryStatus.NOT_TESTED
    assert r.artifact_path is None
    assert r.references if hasattr(r, "references") else True


def test_nan_series_degrades_not_crashes(tmp_path):
    # constant series (ACF undefined) must not abort figure rendering
    ds = sieve.from_arrays(returns=np.zeros(600))
    refs = [f"{s.figure_id}@1" for s in freg.all_specs() if s.implemented
            and s.required_columns == ["return"]]
    results = freg.render_figures(ds, refs, tmp_path)
    assert len(results) == len(refs)
    assert all(r.status in (ExploratoryStatus.INSUFFICIENT,
                            ExploratoryStatus.OBSERVED) for r in results)


# -------------------------------------------- figure/metric consistency

def test_figure_summaries_equal_metric_values_single_run(single_run,
                                                         tmp_path):
    """Single-run summary values must be bit-identical to the registered
    metric outputs (same code path, no re-implementation)."""
    r = single_run.runs[0].columns["return"]
    results = {x.figure_id: x for x in freg.render_figures(
        single_run,
        ["marginal_distribution@1", "tail_ccdf@1", "volatility_acf@1",
         "leverage_kernel@1", "drift_variance_diagnostic@1",
         "aggregation_profile@1"], tmp_path)}
    sv = results["marginal_distribution"].summary_values
    assert sv["excess_kurtosis"] == metric_compute("excess_kurtosis@1", r)
    sv = results["tail_ccdf"].summary_values
    assert sv["hill_left"] == metric_compute("hill_left@1", r)
    assert sv["hill_right"] == metric_compute("hill_right@1", r)
    sv = results["volatility_acf"].summary_values
    assert sv["acf_abs_1"] == metric_compute("acf_abs_1@1", r)
    assert sv["acf_abs_20"] == metric_compute("acf_abs_20@1", r)
    sv = results["leverage_kernel"].summary_values
    assert sv["leverage"] == metric_compute("leverage@1", r)
    sv = results["drift_variance_diagnostic"].summary_values
    assert sv["drift"] == metric_compute("drift@1", r)
    assert sv["variance_ratio_20"] == metric_compute("variance_ratio_20@1", r)


def test_leverage_curve_mean_equals_metric(single_run):
    """The plotted kernel over the shaded range averages to the scalar."""
    r = single_run.runs[0].columns["return"]
    assert C.leverage_scalar_from_curve(r, 5) == metric_compute(
        "leverage@1", r)


def test_acf_curve_matches_metric_lags(single_run):
    r = single_run.runs[0].columns["return"]
    curve = C.acf_curve(np.abs(r), 20)
    assert curve[0] == metric_compute("acf_abs_1@1", r)
    assert curve[19] == metric_compute("acf_abs_20@1", r)


def test_curves_do_not_cross_run_boundaries(tmp_path):
    """Per-run computation: values must be unaffected by other runs."""
    a = _garch(1500, 1)
    b = _garch(1500, 2) * 100.0            # wildly different scale
    ens = sieve.from_runs([{"run_id": "a", "return": a},
                           {"run_id": "b", "return": b}])
    (res,) = freg.render_figures(ens, ["volatility_acf@1"], tmp_path)
    med = res.summary_values["acf_abs_1_run_median"]
    expect = float(np.median([metric_compute("acf_abs_1@1", a),
                              metric_compute("acf_abs_1@1", b)]))
    assert med == pytest.approx(expect, abs=1e-15)


def test_decimation_preserves_extremes():
    y = RNG.standard_normal(50_000)
    y[12_345] = 25.0
    y[40_000] = -25.0
    _, dec = C.decimate_minmax(y, 1000)
    assert dec.max() == 25.0
    assert dec.min() == -25.0
