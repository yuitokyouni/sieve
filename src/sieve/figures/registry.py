"""Figure registry: id → (function, FigureSpec) — the visual twin of the
metric registry. Suites reference ``figure_id@major`` strings; nothing in
the inspect runner or report templates hard-codes figure lists.

Registered-but-unimplemented figures are first-class NOT_TESTED entries:
they appear in reports as roadmap items with references, and become real by
implementation + version bump, never by silently appearing.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sieve.core.dataset import SimulationDataset
from sieve.core.enums import ExploratoryStatus
from sieve.core.models import FigureResult, FigureSpec
from sieve.figures import plots
from sieve.figures.plots import FigureOutput
from sieve.figures.svg import scope_ids

_ENTRIES: dict[str, tuple[Callable | None, FigureSpec]] = {}


def _register(fn: Callable | None, **kw) -> None:
    if fn is not None:
        kw.setdefault("function_path", f"{fn.__module__}.{fn.__name__}")
    spec = FigureSpec(implemented=fn is not None, **kw)
    _ENTRIES[spec.figure_id] = (fn, spec)


_CONT = "Cont (2001), Quantitative Finance 1(2), 223-236"

_register(
    plots.fig_return_path,
    figure_id="return_path", version="1",
    reading_guide=(
        "Look for episodes where large |r| clusters in time (clustering/intermittency) "
        "and for drifts or level shifts in the band of typical returns. Across runs, "
        "textures should vary in detail but not in kind."
    ),
    display_name="Return path / volatility texture",
    stylized_fact="volatility clustering, intermittency",
    minimum_observations_per_run=50,
    parameters={"max_panels": 4, "rolling_window": 25,
                "max_points_per_panel": 1200},
    related_metrics=["acf_abs_1@1", "acf_abs_20@1"],
    known_visual_pitfalls=[
        "naive downsampling erases extreme returns (min-max decimation is "
        "used instead)",
        "showing one hand-picked run of an ensemble is cherry-picking; the "
        "selection rule is fixed and printed"],
    references=[_CONT])

_register(
    plots.fig_marginal_distribution,
    figure_id="marginal_distribution", version="1",
    reading_guide=(
        "On the linear panel the simulated density vs the Gaussian shows peakedness; "
        "the log-y panel shows whether the tails sit above the Gaussian (heavy tails) "
        "and how far out they extend."
    ),
    display_name="Marginal distribution vs Gaussian",
    stylized_fact="heavy tails",
    minimum_observations_per_run=200,
    parameters={"bins": 61, "z_range": 8.0},
    related_metrics=["excess_kurtosis@1"],
    known_visual_pitfalls=[
        "histogram shape is bin-dependent; the CCDF is the primary tail "
        "evidence",
        "linear-scale densities hide tails entirely (a log-y panel is "
        "always included)"],
    references=[_CONT])

_register(
    plots.fig_tail_ccdf,
    figure_id="tail_ccdf", version="1",
    reading_guide=(
        "A roughly straight upper region on log-log axes is consistent with power-law- "
        "like tails; the dashed line shows the Hill fit over the marked k region only. "
        "Compare the two tails for asymmetry."
    ),
    display_name="Tail CCDF with Hill overlay",
    stylized_fact="heavy tails (tail index)",
    minimum_observations_per_run=300,
    parameters={"tail_frac": 0.05},
    related_metrics=["hill_left@1", "hill_right@1"],
    known_visual_pitfalls=[
        "log-log straightness alone is not a power law",
        "the Hill estimate depends on the tail fraction k (recorded ~0.9 "
        "IQR swing); the k region is marked on the plot"],
    references=["Hill (1975), Annals of Statistics 3(5)", _CONT])

_register(
    plots.fig_return_acf,
    figure_id="return_acf", version="1",
    reading_guide=(
        "Values should sit mostly inside the band at all displayed lags if returns are "
        "serially uncorrelated. A slow decay or systematic sign pattern indicates "
        "predictability the model may not intend."
    ),
    display_name="Autocorrelation of returns",
    stylized_fact="absence of autocorrelation in returns",
    minimum_observations_per_run=200,
    parameters={"max_lag": 50},
    related_metrics=[],
    known_visual_pitfalls=[
        "the iid band understates uncertainty under volatility clustering",
        "reading only lag 1 misses slow decay shapes"],
    references=[_CONT])

_register(
    plots.fig_volatility_acf,
    figure_id="volatility_acf", version="1",
    reading_guide=(
        "Positive, slowly decaying ACF(|r|) (and ACF(r^2)) is the "
        "volatility-clustering "
        "signature; compare the decay shape, not one lag. The log-log view helps judge "
        "slow decay but fits nothing."
    ),
    display_name="Autocorrelation of |r| and r^2",
    stylized_fact="volatility clustering; slow decay of volatility "
                  "autocorrelation",
    minimum_observations_per_run=300,
    parameters={"max_lag": 100},
    related_metrics=["acf_abs_1@1", "acf_abs_20@1"],
    known_visual_pitfalls=[
        "declaring a power law from an unfitted log-log plot",
        "GARCH(1,1) reproduces the linear-lag view; matching it says "
        "nothing about mechanism (recorded metric blind spot)"],
    references=[_CONT])

_register(
    plots.fig_aggregation_profile,
    figure_id="aggregation_profile", version="1",
    reading_guide=(
        "Excess kurtosis should fall toward 0 as the horizon grows if aggregational "
        "Gaussianity holds; read the right side with care - the effective sample size "
        "shrinks with the horizon."
    ),
    display_name="Aggregation profile (kurtosis vs horizon)",
    stylized_fact="aggregational Gaussianity",
    minimum_observations_per_run=400,
    parameters={"horizons": [1, 2, 5, 10, 20, 40, 80, 160],
                "min_aggregated_obs": 200},
    related_metrics=["excess_kurtosis@1"],
    known_visual_pitfalls=[
        "kurtosis at large horizons rests on few aggregated observations; "
        "effective n is printed and horizons below the floor are dropped"],
    references=[_CONT])

_register(
    plots.fig_leverage_kernel,
    figure_id="leverage_kernel", version="1",
    reading_guide=(
        "In equity-like data c(tau) is negative for tau>0 (bad returns precede high "
        "volatility) and near 0 for tau<0. A symmetric kernel means the model has no "
        "leverage-type asymmetry."
    ),
    display_name="Leverage kernel c(tau)",
    stylized_fact="leverage effect",
    minimum_observations_per_run=300,
    parameters={"max_tau": 20, "metric_lags": 5},
    related_metrics=["leverage@1"],
    known_visual_pitfalls=[
        "metric and plot must share one definition: the scalar is the mean "
        "of this exact curve over the shaded tau range (tested)",
        "sign conventions for tau differ across papers; the definition is "
        "printed on the figure"],
    references=["Bouchaud, Matacz & Potters (2001), PRL 87(22)"])

_register(
    plots.fig_drift_variance,
    figure_id="drift_variance_diagnostic", version="1",
    reading_guide=(
        "Per-run drift should scatter near the model's intended drift "
        "(often ~0); VR(q) "
        "near 1 at all q means no strong mean reversion (<1) or trending (>1) in "
        "returns."
    ),
    display_name="Drift and variance-ratio diagnostic",
    stylized_fact="drift / return dependence (calibration sanity)",
    minimum_observations_per_run=200,
    parameters={"q_values": [2, 5, 10, 20, 40]},
    related_metrics=["drift@1", "variance_ratio_20@1"],
    known_visual_pitfalls=[
        "drift is in step units; comparing against daily empirical drift "
        "requires a declared time mapping"],
    references=["Lo & MacKinlay (1988), Review of Financial Studies 1(1)"])

_register(
    plots.fig_volume_volatility,
    figure_id="volume_volatility", version="1",
    reading_guide=(
        "A rising binned mean of |r| across volume bins (and positive "
        "rank correlation) "
        "is the volume-volatility relation; the raw scatter is dominated by dense low- "
        "volume regions."
    ),
    display_name="Volume-volatility relation",
    stylized_fact="volume/volatility correlation",
    required_columns=["return", "volume"],
    minimum_observations_per_run=300,
    parameters={"bins": 12, "correlation": "spearman"},
    related_metrics=[],
    known_visual_pitfalls=[
        "a raw scatter of heavy-tailed volume is dominated by outliers; "
        "binned conditional means carry the signal",
        "correlation without a matched time basis across runs is "
        "meaningless; pairs are matched within runs only"],
    references=["Karpoff (1987), JFQA 22(1)", _CONT])

# ---- registered, not implemented: roadmap entries, shown as NOT_TESTED ----

_register(
    None,
    figure_id="conditional_tails", version="1",
    reading_guide=(
        "Planned: compare the tail of raw returns to the tail of conditional- "
        "volatility-standardized residuals; heavy residual tails mean heavy tails "
        "beyond what volatility dynamics explain."
    ),
    display_name="Conditional heavy tails (standardized residuals)",
    stylized_fact="conditional heavy tails",
    minimum_observations_per_run=1000,
    parameters={},
    related_metrics=[],
    known_visual_pitfalls=[
        "standardizing by a fitted GARCH adds an estimation dependency; the "
        "volatility model and its parameters must be recorded",
        "confusing raw-tail and residual-tail evidence"],
    references=[_CONT, "planned: requires an optional dependency for "
                "conditional volatility estimation and a prespecified "
                "estimator; see docs/stylized-facts-atlas.md"])

_register(
    None,
    figure_id="timescale_asymmetry", version="1",
    reading_guide=(
        "Planned: cross-correlation of coarse-grained and fine-grained volatility at "
        "positive vs negative lags; asymmetry indicates information flowing from long "
        "to short horizons."
    ),
    display_name="Coarse-fine volatility lead-lag",
    stylized_fact="asymmetry in time scales",
    minimum_observations_per_run=2000,
    parameters={},
    related_metrics=[],
    known_visual_pitfalls=[
        "lag sign conventions differ across the literature; the aggregation "
        "horizons and lag convention must be printed with the figure"],
    references=["Muller et al. (1997), J. Empirical Finance 4(2-3)",
                "planned: aggregation horizons and estimator to be "
                "prespecified; see docs/stylized-facts-atlas.md"])

_register(
    None,
    figure_id="gain_loss_asymmetry", version="1",
    reading_guide=(
        "Planned: distribution of first-passage times to +theta vs -theta from each "
        "starting point; in equity indices losses of a given size tend to be reached "
        "faster than equal gains."
    ),
    display_name="Gain/loss first-passage distribution",
    stylized_fact="gain/loss asymmetry",
    required_columns=["price"],
    minimum_observations_per_run=5000,
    parameters={},
    related_metrics=[],
    known_visual_pitfalls=[
        "first-passage times are right-censored by the series end; the "
        "handling of non-passages must be explicit",
        "passages must never cross a run boundary"],
    references=["Jensen, Johansen & Simonsen (2003), Physica A 324",
                "planned: threshold theta and censoring rule to be "
                "prespecified; see docs/stylized-facts-atlas.md"])


def resolve(ref: str) -> tuple[Callable | None, FigureSpec]:
    """Resolve ``figure_id@major`` (or bare id) to (fn, spec)."""
    figure_id, _, major = ref.partition("@")
    if figure_id not in _ENTRIES:
        raise KeyError(f"unknown figure: {figure_id}")
    fn, spec = _ENTRIES[figure_id]
    if major and spec.version.split(".")[0] != major:
        raise KeyError(f"figure {figure_id} major version {major} not "
                       f"available (have {spec.version})")
    return fn, spec


def all_specs() -> list[FigureSpec]:
    return [spec for _, spec in _ENTRIES.values()]


def _adequacy(spec: FigureSpec, ds: SimulationDataset
              ) -> tuple[SimulationDataset | None, FigureResult | None,
                         list[str]]:
    """Generic gate: columns, geometry, per-run minimums, run count.

    Returns (filtered dataset, early result, caveats). An inadequate figure
    resolves alone — it never blocks the others (task §3.5).
    """
    def early(status: ExploratoryStatus, note: str) -> FigureResult:
        return FigureResult(
            figure_id=spec.figure_id, version=spec.version,
            display_name=spec.display_name, stylized_fact=spec.stylized_fact,
            reading_guide=spec.reading_guide, status=status,
            related_metrics=spec.related_metrics,
            parameters=spec.parameters, note=note)

    missing = [c for c in spec.required_columns if not ds.has_column(c)]
    if missing:
        return None, early(
            ExploratoryStatus.NOT_APPLICABLE,
            f"input has no '{'/'.join(missing)}' column; add it to the "
            "observables (or derive it explicitly) to enable this figure"), []
    if ds.geometry.value not in spec.supported_geometries:
        return None, early(
            ExploratoryStatus.NOT_APPLICABLE,
            f"geometry '{ds.geometry.value}' is not supported by this "
            "figure"), []
    usable = [r for r in ds.runs
              if r.n_obs >= spec.minimum_observations_per_run]
    caveats = []
    if len(usable) < len(ds.runs):
        excluded = [r.run_id for r in ds.runs if r not in usable]
        caveats.append(
            f"{len(excluded)} run(s) below the figure minimum of "
            f"{spec.minimum_observations_per_run} observations excluded: "
            + ", ".join(excluded[:6])
            + ("…" if len(excluded) > 6 else ""))
    if len(usable) < spec.minimum_runs or not usable:
        return None, early(
            ExploratoryStatus.INSUFFICIENT,
            f"only {len(usable)} run(s) meet the figure minimum of "
            f"{spec.minimum_observations_per_run} observations per run "
            f"(need >= {spec.minimum_runs} run(s))"), caveats
    sub = SimulationDataset(
        runs=usable, geometry=ds.geometry,
        geometry_source=ds.geometry_source, time_basis=ds.time_basis,
        transforms=ds.transforms, caveats=ds.caveats)
    return sub, None, caveats


def render_figures(ds: SimulationDataset, figure_refs: list[str],
                   out_dir: str | Path,
                   reference: dict | None = None) -> list[FigureResult]:
    """Render every suite-declared figure; write SVGs under ``figures/``.

    One figure failing (bad data, bug) degrades that figure to a status —
    it never aborts the report (task §6).

    ``reference`` (optional) is an empirical comparator series
    ``{"r": ndarray, "label": str, "content_hash": str}``; figures that
    support it draw its derived curve as a visual overlay. The overlay
    never affects any status, and its identity is recorded in the sealed
    figure parameters.
    """
    import inspect as _inspect

    out_dir = Path(out_dir)
    fig_dir = out_dir / "figures"
    results: list[FigureResult] = []
    for ref in figure_refs:
        fn, spec = resolve(ref)
        if fn is None:
            results.append(FigureResult(
                figure_id=spec.figure_id, version=spec.version,
                display_name=spec.display_name,
                stylized_fact=spec.stylized_fact,
                reading_guide=spec.reading_guide,
                status=ExploratoryStatus.NOT_TESTED,
                related_metrics=spec.related_metrics,
                parameters=spec.parameters,
                caveats=spec.known_visual_pitfalls,
                note="registered but not implemented in this version; see "
                     "references for the planned method"))
            continue
        sub, early_result, gate_caveats = _adequacy(spec, ds)
        if early_result is not None:
            early_result.caveats = gate_caveats + list(early_result.caveats)
            results.append(early_result)
            continue
        params = dict(spec.parameters)
        kwargs = {}
        if (reference is not None
                and "reference" in _inspect.signature(fn).parameters):
            kwargs["reference"] = reference
        try:
            out: FigureOutput = fn(sub, params, **kwargs)
        except Exception as e:      # degrade to ERROR, never abort the rest
            # An exception out of a figure implementation is a sieve bug,
            # not a data property: it must never be reported as
            # INSUFFICIENT (data inadequacy). The exception type and the
            # figure version are recorded in the sealed result.
            results.append(FigureResult(
                figure_id=spec.figure_id, version=spec.version,
                display_name=spec.display_name,
                stylized_fact=spec.stylized_fact,
                reading_guide=spec.reading_guide,
                status=ExploratoryStatus.ERROR,
                related_metrics=spec.related_metrics,
                parameters={**spec.parameters,
                            "internal_error": {
                                "exception_type": type(e).__name__,
                                "figure_version": spec.version}},
                caveats=gate_caveats,
                note=f"internal error, not a data property "
                     f"({type(e).__name__}: {e}); please report this as a "
                     "sieve bug"))
            continue
        artifact_path = None
        if out.svg is not None:
            fig_dir.mkdir(parents=True, exist_ok=True)
            (fig_dir / f"{spec.figure_id}.svg").write_text(
                scope_ids(out.svg, spec.figure_id))
            artifact_path = f"figures/{spec.figure_id}.svg"
        results.append(FigureResult(
            figure_id=spec.figure_id, version=spec.version,
            display_name=spec.display_name, stylized_fact=spec.stylized_fact,
            reading_guide=spec.reading_guide,
            status=out.status, n_runs_used=out.n_runs_used,
            n_obs_used=out.n_obs_used,
            summary_values={k: v for k, v in out.summary_values.items()},
            parameters={**spec.parameters, **out.parameters},
            related_metrics=spec.related_metrics,
            caveats=gate_caveats + out.caveats,
            artifact_path=artifact_path, note=out.note))
    return results


def figure_map_rows() -> list[dict]:
    """Claim ↔ metric ↔ figure correspondence (task §5.3) for docs/report."""
    rows = []
    for _, spec in _ENTRIES.values():
        rows.append({
            "stylized_fact": spec.stylized_fact,
            "figure_id": spec.figure_id,
            "implemented": spec.implemented,
            "related_metrics": spec.related_metrics,
            "required_columns": spec.required_columns,
            "known_visual_pitfalls": spec.known_visual_pitfalls,
        })
    return rows
