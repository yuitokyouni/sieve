"""Regression tests for the v0.5.0 external audit findings.

Each test pins one confirmed defect so it cannot silently return:

- timestamp inputs must be ISO-8601, non-empty and strictly increasing
  (never silently reordered);
- an internal implementation bug is ERROR, never INSUFFICIENT — data
  inadequacy and sieve defects are different facts;
- manifest typos and malformed YAML are refused as input errors, never
  silently ignored (or turned into tracebacks);
- fractional step values are refused, never truncated;
- rows with extra CSV cells are refused, never trimmed;
- bundle-declared artifact paths are confined to the run directory, and
  only hash-verified SVG bytes are inlined past autoescape;
- every declared MetricRequirements field is actually enforced.
"""

import numpy as np
import pytest
from typer.testing import CliRunner

import sieve
from sieve.adapters.csv import InputError as CsvInputError
from sieve.adapters.csv import read_returns
from sieve.adapters.dataset import load_dataset
from sieve.cli.app import app
from sieve.core.dataset import InputError
from sieve.core.models import MetricRequirements, MetricSpec
from sieve.evaluation.inspect import _metric_observations, run_inspect
from sieve.figures import registry as figure_registry
from sieve.metrics import registry as metric_registry
from sieve.metrics.registry import (
    MetricComputationError,
    MetricNotComputable,
)
from sieve.provenance.bundle import (
    load_inspect,
    safe_artifact_path,
    verify,
)
from sieve.reporting.html import render_inspect_report

RNG = np.random.default_rng(20260812)

runner = CliRunner()


def _write(path, text):
    path.write_text(text)
    return path


def _steps_csv(path, n=400, seed=0):
    rng = np.random.default_rng(seed)
    rows = "\n".join(f"{i},{v:.6f}" for i, v in
                     enumerate(rng.standard_normal(n)))
    return _write(path, "step,return\n" + rows + "\n")


# --------------------------------------------------- timestamp validation

def test_audit_repro_garbage_timestamps_refused(tmp_path):
    """The audit's exact reproduction: unordered, unparseable and empty
    timestamps must not silently produce a 'valid' evidence atlas."""
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n2024-01-03,0.1\nNOT-A-DATE,0.2\n"
               "2024-01-01,0.3\n,0.4\n")
    with pytest.raises(InputError):
        load_dataset(f)


def test_empty_timestamp_refused(tmp_path):
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n2024-01-01,0.1\n,0.2\n")
    with pytest.raises(InputError, match="empty timestamp"):
        load_dataset(f)


def test_non_iso_timestamp_refused(tmp_path):
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n01/03/2024,0.1\n01/04/2024,0.2\n")
    with pytest.raises(InputError, match="ISO-8601"):
        load_dataset(f)


def test_out_of_order_timestamps_refused_not_sorted(tmp_path):
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n2024-01-03,0.1\n2024-01-01,0.2\n")
    with pytest.raises(InputError, match="sort the rows"):
        load_dataset(f)


def test_mixed_aware_and_naive_timestamps_refused(tmp_path):
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n2024-01-01T00:00:00,0.1\n"
               "2024-01-02T00:00:00+09:00,0.2\n")
    with pytest.raises(InputError, match="timezone-aware and naive"):
        load_dataset(f)


def test_aware_iso_datetimes_accepted(tmp_path):
    f = _write(tmp_path / "r.csv",
               "timestamp,return\n2024-01-01T09:00:00+09:00,0.1\n"
               "2024-01-01T10:00:00+09:00,0.2\n"
               "2024-01-01T11:00:00+09:00,0.3\n")
    ds, _, _ = load_dataset(f)
    assert ds.time_basis == "timestamp"
    assert ds.runs[0].n_obs == 3


def test_legacy_test_adapter_validates_timestamps_too(tmp_path):
    rows = [f"2020-01-{i + 1:02d},0.01" for i in range(28)] * 3
    rows[5], rows[6] = rows[6], rows[5]           # scrambled order
    f = _write(tmp_path / "returns.csv",
               "timestamp,return\n" + "\n".join(rows[:60]) + "\n")
    with pytest.raises(CsvInputError):
        read_returns(f)


# ------------------------------------------------------- step validation

def test_fractional_steps_refused_not_truncated(tmp_path):
    f = _write(tmp_path / "r.csv",
               "step,return\n0.9,0.1\n1.9,0.2\n2.9,0.3\n")
    with pytest.raises(InputError, match="must be integers"):
        load_dataset(f)


def test_float_formatted_integer_steps_accepted(tmp_path):
    f = _write(tmp_path / "r.csv",
               "step,return\n0.0,0.1\n1.0,0.2\n2.0,0.3\n")
    ds, _, _ = load_dataset(f)
    assert list(ds.runs[0].steps) == [0, 1, 2]


def test_row_with_extra_cells_refused(tmp_path):
    f = _write(tmp_path / "r.csv",
               "step,return\n0,0.1,ACCIDENTAL_VALUE\n1,0.2\n")
    with pytest.raises(InputError, match="cells"):
        load_dataset(f)


# ---------------------------------------------------- manifest validation

def _dir_input(tmp_path, manifest):
    d = tmp_path / "exp"
    (d / "runs").mkdir(parents=True)
    _steps_csv(d / "runs" / "seed-001.csv", n=40, seed=1)
    _write(d / "manifest.yaml", manifest)
    return d


def test_manifest_typo_key_refused(tmp_path):
    """The audit's reproduction: burn_in_stpes must not silently mean
    'no burn-in'."""
    d = _dir_input(tmp_path, "geometry: multi_run_ensemble\n"
                             "burn_in_stpes: 500\n")
    with pytest.raises(InputError, match="burn_in_stpes"):
        load_dataset(d)


def test_manifest_nested_burn_in_typo_refused(tmp_path):
    d = _dir_input(tmp_path, "burn_in: {stpes: 500}\n")
    with pytest.raises(InputError, match="stpes"):
        load_dataset(d)


def test_manifest_run_entry_typo_refused(tmp_path):
    d = _dir_input(tmp_path,
                   "runs:\n  - {file: runs/seed-001.csv, sed: 1}\n")
    with pytest.raises(InputError, match="sed"):
        load_dataset(d)


def test_manifest_mistyped_burn_in_value_refused(tmp_path):
    d = _dir_input(tmp_path, "burn_in: {steps: lots}\n")
    with pytest.raises(InputError, match="steps"):
        load_dataset(d)


def test_malformed_yaml_is_input_error_not_traceback(tmp_path):
    d = _dir_input(tmp_path, "runs: [unclosed\n")
    with pytest.raises(InputError, match="malformed YAML"):
        load_dataset(d)


def test_cli_malformed_manifest_exits_2(tmp_path):
    d = _dir_input(tmp_path, "model_id: [unclosed\n")
    res = runner.invoke(app, ["inspect", str(d),
                              "--out", str(tmp_path / "runs_out")])
    assert res.exit_code == 2
    assert "malformed YAML" in res.output


# --------------------------------------- ERROR vs INSUFFICIENT separation

def _broken(_r):
    raise TypeError("intentionally broken metric implementation")


def _break_metric(monkeypatch, metric_id="excess_kurtosis"):
    fn, spec, dim = metric_registry._ENTRIES[metric_id]
    monkeypatch.setitem(metric_registry._ENTRIES, metric_id,
                        (_broken, spec, dim))


def test_broken_metric_raises_typed_internal_error(monkeypatch):
    _break_metric(monkeypatch)
    with pytest.raises(MetricComputationError, match="TypeError"):
        metric_registry.compute("excess_kurtosis@1", RNG.standard_normal(500))


def test_metric_not_computable_stays_nan(monkeypatch):
    def declared_failure(_r):
        raise MetricNotComputable("too few tail points")
    fn, spec, dim = metric_registry._ENTRIES["excess_kurtosis"]
    monkeypatch.setitem(metric_registry._ENTRIES, "excess_kurtosis",
                        (declared_failure, spec, dim))
    v = metric_registry.compute("excess_kurtosis@1", RNG.standard_normal(500))
    assert np.isnan(v)


def test_broken_metric_is_error_not_insufficient(monkeypatch):
    _break_metric(monkeypatch)
    ds = sieve.from_arrays(returns=RNG.standard_normal(400))
    obs = _metric_observations(ds, ["excess_kurtosis@1", "acf_abs_1@1"])
    by_metric = {ob.metric_ref.partition("@")[0]: ob for ob in obs}
    broken = by_metric["excess_kurtosis"]
    assert broken.status.value == "ERROR"
    assert broken.value is None
    assert "TypeError" in broken.note and "bug" in broken.note
    # the bug never leaks into other metrics
    assert by_metric["acf_abs_1"].status.value == "OBSERVED"


def test_broken_figure_is_error_with_exception_type(monkeypatch, tmp_path):
    def broken_figure(_ds, _params, **_kw):
        raise IndexError("intentionally broken figure implementation")
    fn, spec = figure_registry._ENTRIES["return_path"]
    monkeypatch.setitem(figure_registry._ENTRIES, "return_path",
                        (broken_figure, spec))
    ds = sieve.from_arrays(returns=RNG.standard_normal(400))
    results = figure_registry.render_figures(ds, ["return_path@1"], tmp_path)
    assert results[0].status.value == "ERROR"
    assert results[0].parameters["internal_error"]["exception_type"] == \
        "IndexError"
    assert "not a data property" in results[0].note


def test_cli_inspect_exits_1_on_internal_error(monkeypatch, tmp_path):
    """A refactoring that breaks a metric must not produce a sealed report
    under exit 0 — the audit's release blocker."""
    _break_metric(monkeypatch)
    f = _steps_csv(tmp_path / "r.csv", n=400)
    res = runner.invoke(app, ["inspect", str(f),
                              "--out", str(tmp_path / "runs_out")])
    assert res.exit_code == 1
    assert "internal" in res.output
    # the report is still written for post-mortem, just not under exit 0
    runs = list((tmp_path / "runs_out").iterdir())
    assert len(runs) == 1
    b = load_inspect(runs[0] / "inspect_bundle.json")
    assert any(ob.status.value == "ERROR" for ob in b.metric_observations)


# ------------------------------------------- MetricRequirements enforcement

def _fake_metric(monkeypatch, requirements):
    spec = MetricSpec(
        metric_id="fake_gated", version="1", display_name="Fake gated",
        function_path="tests.fake", input_contract="test",
        scale_invariant=True, intended_signal="test",
        requirements=requirements)
    monkeypatch.setitem(metric_registry._ENTRIES, "fake_gated",
                        (lambda r: 0.0, spec, "marginal_distribution"))


def test_minimum_runs_requirement_enforced(monkeypatch):
    _fake_metric(monkeypatch, MetricRequirements(
        minimum_observations_per_run=100, minimum_runs=2))
    ds = sieve.from_arrays(returns=RNG.standard_normal(400))
    (ob,) = _metric_observations(ds, ["fake_gated@1"])
    assert ob.status.value == "INSUFFICIENT"
    assert "minimum" in ob.note


def test_supported_geometries_requirement_enforced(monkeypatch):
    _fake_metric(monkeypatch, MetricRequirements(
        minimum_observations_per_run=100,
        supported_geometries=["multi_run_ensemble"]))
    ds = sieve.from_arrays(returns=RNG.standard_normal(400))
    (ob,) = _metric_observations(ds, ["fake_gated@1"])
    assert ob.status.value == "NOT_APPLICABLE"
    assert "geometry" in ob.note


def test_regular_spacing_requirement_enforced(monkeypatch, tmp_path):
    _fake_metric(monkeypatch, MetricRequirements(
        minimum_observations_per_run=2, requires_regular_spacing=True))
    f = _write(tmp_path / "r.csv",
               "step,return\n0,0.1\n1,0.2\n5,0.3\n6,0.4\n")
    ds, _, _ = load_dataset(f)
    assert ds.runs[0].irregular_spacing
    (ob,) = _metric_observations(ds, ["fake_gated@1"])
    assert ob.status.value == "NOT_APPLICABLE"
    assert "regular spacing" in ob.note


def test_preprocessing_requirement_enforced(monkeypatch):
    _fake_metric(monkeypatch, MetricRequirements(
        minimum_observations_per_run=100,
        preprocessing_requirements=["burn_in"]))
    ds = sieve.from_arrays(returns=RNG.standard_normal(400))
    (ob,) = _metric_observations(ds, ["fake_gated@1"])
    assert ob.status.value == "NOT_APPLICABLE"
    assert "burn_in" in ob.note


# ------------------------------------------------ artifact path confinement

@pytest.mark.parametrize("bad", [
    "../outside.svg",
    "figures/../../outside.svg",
    "/etc/hostname",
    "C:\\evil.svg",
])
def test_unsafe_artifact_paths_rejected(tmp_path, bad):
    with pytest.raises(ValueError, match="unsafe artifact path"):
        safe_artifact_path(tmp_path, bad)


def test_symlink_escape_rejected(tmp_path):
    base = tmp_path / "run"
    base.mkdir()
    outside = tmp_path / "outside.svg"
    outside.write_text("<svg/>")
    (base / "figures").mkdir()
    (base / "figures" / "link.svg").symlink_to(outside)
    with pytest.raises(ValueError, match="outside the run directory"):
        safe_artifact_path(base, "figures/link.svg")


@pytest.fixture(scope="module")
def inspect_run(tmp_path_factory):
    f = _steps_csv(tmp_path_factory.mktemp("in") / "r.csv", n=400)
    return run_inspect(f, out_root=tmp_path_factory.mktemp("runs"))


def test_verify_flags_traversal_artifact_path(inspect_run, tmp_path):
    import json
    import shutil
    run_dir = tmp_path / "run"
    shutil.copytree(inspect_run, run_dir)
    body = json.loads((run_dir / "inspect_bundle.json").read_text())
    body["artifact_index"][0]["path"] = "../../outside.svg"
    (run_dir / "inspect_bundle.json").write_text(json.dumps(body))
    problems = verify(run_dir)
    assert any("unsafe artifact path" in p for p in problems)


def test_report_never_inlines_traversal_svg(inspect_run, tmp_path):
    evil = tmp_path / "evil.svg"
    evil.write_text("<svg><text>EVIL_MARKER</text></svg>")
    bundle = load_inspect(inspect_run / "inspect_bundle.json")
    target = next(f for f in bundle.figures if f.artifact_path)
    target.artifact_path = "../../../" + evil.name
    out = tmp_path / "report.html"
    render_inspect_report(out, bundle, inspect_run)
    assert "EVIL_MARKER" not in out.read_text()


def test_report_never_inlines_tampered_svg(inspect_run, tmp_path):
    import shutil
    run_dir = tmp_path / "run"
    shutil.copytree(inspect_run, run_dir)
    bundle = load_inspect(run_dir / "inspect_bundle.json")
    target = next(f for f in bundle.figures if f.artifact_path)
    svg = run_dir / target.artifact_path
    svg.write_text(svg.read_text().replace(
        "</svg>", "<text>TAMPERED_MARKER</text></svg>", 1))
    out = tmp_path / "report.html"
    render_inspect_report(out, bundle, run_dir)
    html = out.read_text()
    assert "TAMPERED_MARKER" not in html
    # untampered figures still inline fine
    others = [f.figure_id for f in bundle.figures
              if f.artifact_path and f.figure_id != target.figure_id]
    assert any(f'id="fig-{fid}"' in html for fid in others)


# ------------------------------------------------- reference overlay in HTML

def test_report_shows_reference_overlay_identity(tmp_path):
    sim = _steps_csv(tmp_path / "sim.csv", n=1500, seed=1)
    ref = _steps_csv(tmp_path / "ref.csv", n=1500, seed=2)
    run_dir = run_inspect(sim, out_root=tmp_path / "runs",
                          reference_path=ref, reference_label="Test Index")
    html = (run_dir / "report" / "index.html").read_text()
    assert "overlay &#39;Test Index&#39;" in html or \
        "overlay 'Test Index'" in html
    assert "not used for any inference" in html
    # figures without overlay support still honestly say "none"
    assert "none — exploratory suite ships no" in html


def test_report_without_reference_still_says_none(inspect_run):
    html = (inspect_run / "report" / "index.html").read_text()
    assert "not used for any inference" not in html
    assert "none — exploratory suite ships no" in html
