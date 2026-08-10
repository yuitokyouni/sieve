"""Core stylized-fact diagnostic figures (task §5.1 A–J, R2 set + volume).

Conventions shared by every figure function:

- input is a :class:`SimulationDataset` already filtered by the registry to
  runs that meet the figure's declared minimum size;
- no PASS/FAIL anywhere — outputs are drawings plus disclosed parameters,
  sample sizes and caveats;
- scalar values reported in ``summary_values`` are computed by the
  *registered metric functions* (single run) or as the across-run median of
  per-run metric values (ensemble) — never by a re-implementation;
- pooling across runs happens only for *marginal* quantities (histograms,
  CCDFs) and is disclosed in the caveats; time-indexed quantities (paths,
  ACFs, kernels) are computed per run and aggregated pointwise;
- every non-finite number becomes ``None`` before it reaches a bundle.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from sieve.core.dataset import SimulationDataset
from sieve.core.enums import ExploratoryStatus
from sieve.figures import compute as C
from sieve.figures.svg import ACCENT_GRAY, SERIES, Plot, fmt_num, panel_grid
from sieve.metrics import registry as metric_registry

OBSERVED = ExploratoryStatus.OBSERVED
INSUFFICIENT = ExploratoryStatus.INSUFFICIENT

_POOL_CAVEAT = ("standardized per run, then pooled across runs for this "
                "marginal view; pooling is disclosed here and never applied "
                "to time-indexed quantities")
_IID_BAND_CAVEAT = ("the +/-1.96/sqrt(n) band assumes an iid series and "
                    "UNDERSTATES uncertainty under volatility clustering")


@dataclass
class FigureOutput:
    svg: str | None
    status: ExploratoryStatus
    n_runs_used: int = 0
    n_obs_used: int = 0
    summary_values: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    caveats: list = field(default_factory=list)
    note: str | None = None


def _fin(v) -> float | None:
    v = float(v)
    return v if np.isfinite(v) else None


def _insufficient(note: str, **kw) -> FigureOutput:
    return FigureOutput(svg=None, status=INSUFFICIENT, note=note, **kw)


def _metric_summary(ds: SimulationDataset, metric_ids: list[str]
                    ) -> dict[str, float | None]:
    """Per-metric summary via the registered metric functions.

    Single run → the exact metric value (bit-identical to
    observations.parquet). Ensemble → across-run median, suffixed so nobody
    mistakes it for a single-series value.
    """
    by_run = ds.returns_by_run()
    out: dict[str, float | None] = {}
    for m in metric_ids:
        vals = np.array([metric_registry.compute(f"{m}@1", r)
                         for r in by_run.values()], dtype=float)
        if ds.n_runs == 1:
            out[m] = _fin(vals[0])
        else:
            with np.errstate(invalid="ignore"):
                med = np.nanmedian(vals) if np.isfinite(vals).any() else np.nan
            out[f"{m}_run_median"] = _fin(med)
    return out


def _all_degenerate(ds: SimulationDataset) -> bool:
    """True when no run has any variation (ACF/correlations undefined)."""
    return all(r.columns["return"].std() <= 0 for r in ds.runs)


def _standardized_pool(ds: SimulationDataset
                       ) -> tuple[np.ndarray, list[str], list[str]]:
    """Per-run standardized returns pooled for marginal views only."""
    zs, skipped, caveats = [], [], []
    for rid, r in ds.returns_by_run().items():
        z = C.standardize(r)
        if z is None:
            skipped.append(rid)
        else:
            zs.append(z)
    if skipped:
        caveats.append(f"constant-return run(s) excluded: {', '.join(skipped)}")
    pool = np.concatenate(zs) if zs else np.empty(0)
    return pool, skipped, caveats


# ------------------------------------------------------------ A. return path

def fig_return_path(ds: SimulationDataset, params: dict) -> FigureOutput:
    max_panels = int(params.get("max_panels", 4))
    max_points = int(params.get("max_points_per_panel", 1200))
    roll_w = int(params.get("rolling_window", 25))
    shown = ds.runs[:max_panels]
    caveats = ["min-max decimation per pixel bucket: extremes are preserved, "
               "point density is not"]
    if ds.n_runs > len(shown):
        caveats.append(
            f"showing the first {len(shown)} of {ds.n_runs} runs in run_id "
            "order — a fixed selection rule, not a curated pick")
    panels = []
    for run in shown:
        r = run.columns["return"]
        idx, vals = C.decimate_minmax(r, max_points)
        p = Plot(title=f"run {run.run_id} — return path", xlabel="step",
                 ylabel="return", height=250,
                 note=f"n={len(r)}" + (f", burn-in dropped {run.n_burned}"
                                       if run.n_burned else ""))
        p.line(list(idx), list(vals), width=1.0, label="return",
               opacity=0.9)
        rm = C.rolling_mean_abs(r, roll_w)
        if len(rm):
            ridx, rvals = C.decimate_minmax(rm, max_points)
            p.line(list(ridx + roll_w - 1), list(rvals), color=SERIES[1],
                   width=1.6, label=f"|r| rolling mean (w={roll_w})")
        p.hline(0)
        panels.append(p.render())
    svg = panels[0] if len(panels) == 1 else panel_grid(
        panels, ncols=1 if len(panels) <= 2 else 2, panel_h=250)
    return FigureOutput(
        svg=svg, status=OBSERVED, n_runs_used=len(shown),
        n_obs_used=sum(run.n_obs for run in shown),
        parameters={"max_panels": max_panels, "rolling_window": roll_w,
                    "max_points_per_panel": max_points,
                    "run_selection": "first runs in run_id order"},
        caveats=caveats)


# ------------------------------------- B. marginal distribution (heavy tails)

def fig_marginal_distribution(ds: SimulationDataset, params: dict
                              ) -> FigureOutput:
    bins = int(params.get("bins", 61))
    z_max = float(params.get("z_range", 8.0))
    pool, skipped, caveats = _standardized_pool(ds)
    if len(pool) < 200:
        return _insufficient(
            f"only {len(pool)} standardized observations "
            f"(need >= 200 for a stable histogram)", caveats=caveats)
    clipped = int((np.abs(pool) > z_max).sum())
    edges = np.linspace(-z_max, z_max, bins + 1)
    dens, _ = np.histogram(pool, bins=edges, density=True)
    centers = (edges[:-1] + edges[1:]) / 2
    gx = np.linspace(-z_max, z_max, 241)
    gpdf = np.exp(-gx ** 2 / 2) / np.sqrt(2 * np.pi)

    p1 = Plot(title="standardized returns — density", xlabel="z",
              ylabel="density", note=f"n={len(pool)}, bins={bins}")
    p1.bars(list(centers), list(dens), label="simulated", opacity=0.75)
    p1.line(list(gx), list(gpdf), color=SERIES[1], width=2.0,
            label="Gaussian", dash="6,3")

    pos = dens > 0
    p2 = Plot(title="standardized returns — density (log y)", xlabel="z",
              ylabel="density", yscale="log",
              note="log y exaggerates nothing in the center; read the tails")
    p2.scatter(list(centers[pos]), list(dens[pos]), label="simulated",
               radius=2.6)
    gpos = gpdf > 1e-12
    p2.line(list(gx[gpos]), list(gpdf[gpos]), color=SERIES[1], width=2.0,
            label="Gaussian", dash="6,3")

    caveats += [
        _POOL_CAVEAT,
        "histogram shape depends on binning; the tail CCDF figure is the "
        "primary tail evidence",
    ]
    if clipped:
        caveats.append(
            f"{clipped} observation(s) beyond |z|={fmt_num(z_max)} are "
            "outside the histogram range — they are NOT dropped from the "
            "tail CCDF figure")
    if ds.n_runs > 1:
        caveats.append("pooled histogram can hide run-to-run differences; "
                       "per-run tail indices are in the metric table")
    return FigureOutput(
        svg=panel_grid([p1.render(), p2.render()], ncols=2),
        status=OBSERVED, n_runs_used=ds.n_runs - len(skipped),
        n_obs_used=int(len(pool)),
        summary_values=_metric_summary(ds, ["excess_kurtosis"]),
        parameters={"bins": bins, "z_range": z_max,
                    "comparator": "standard normal pdf"},
        caveats=caveats)


# ------------------------------------------------- C. tail CCDF + Hill overlay

def _tail_panel(tail: np.ndarray, side: str, frac: float
                ) -> tuple[str | None, dict | None, list[str]]:
    caveats: list[str] = []
    if len(tail) < 50:
        return None, None, [f"{side} tail has only {len(tail)} points "
                            "(need >= 50); tail panel not drawn"]
    xs, sv = C.ccdf_points(tail)
    keep = xs > 0
    dropped = int(len(xs) - keep.sum())
    if dropped:
        caveats.append(f"{side} tail: {dropped} zero value(s) cannot appear "
                       "on log axes and were left out of the panel")
    xs, sv = xs[keep], sv[keep]
    if len(xs) < 50:
        return None, None, [f"{side} tail has only {len(xs)} positive "
                            "points; tail panel not drawn"]
    # deterministic log-rank thinning for display only
    if len(xs) > 500:
        ranks = np.unique(np.geomspace(1, len(xs), 400).astype(int)) - 1
        xs_d, sv_d = xs[::-1][ranks], sv[::-1][ranks]
    else:
        xs_d, sv_d = xs, sv
    h = C.hill_overlay(tail, frac)
    p = Plot(title=f"{side} tail CCDF", xlabel="|z|", ylabel="P(|Z| >= x)",
             xscale="log", yscale="log",
             note=f"tail n={len(tail)}" + (f", Hill k={h['k']}" if h else ""))
    p.scatter(list(xs_d), list(sv_d), radius=2.2, opacity=0.8,
              label="empirical CCDF")
    if h:
        # slope -alpha through the Hill threshold point in log-log space
        sv_at_k = h["k"] / h["n_tail"]
        x_line = np.geomspace(h["x_k"], xs.max(), 40)
        y_line = sv_at_k * (x_line / h["x_k"]) ** (-h["alpha"])
        p.line(list(x_line), list(np.maximum(y_line, 1e-12)),
               color=SERIES[1], width=2.0, dash="6,3",
               label=f"Hill fit alpha={fmt_num(h['alpha'])}")
        p.vline(h["x_k"], color=ACCENT_GRAY, dash="2,3")
        caveats.append(
            f"{side} tail: Hill uses the top {h['k']} order statistics "
            f"(frac={frac}); the estimate is k-sensitive (recorded blind "
            "spot: ~0.9 IQR swing across frac 2.5-10%)")
    else:
        caveats.append(f"{side} tail: Hill estimate not finite; no fit drawn")
    return p.render(), h, caveats


def fig_tail_ccdf(ds: SimulationDataset, params: dict) -> FigureOutput:
    frac = float(params.get("tail_frac", 0.05))
    pool, skipped, caveats = _standardized_pool(ds)
    if len(pool) < 300:
        return _insufficient(
            f"only {len(pool)} standardized observations (need >= 300 for "
            "tail evidence)", caveats=caveats)
    panels = []
    for side, tail in (("positive", pool[pool > 0]),
                       ("negative (|z|)", -pool[pool < 0])):
        svg, _h, cv = _tail_panel(tail, side, frac)
        caveats += cv
        if svg:
            panels.append(svg)
    if not panels:
        return _insufficient("neither tail has enough points (>= 50 each)",
                             caveats=caveats)
    caveats += [_POOL_CAVEAT,
                "log-log straightness alone does not establish a power law; "
                "the Hill line is an estimate over the marked k region only"]
    return FigureOutput(
        svg=panels[0] if len(panels) == 1 else panel_grid(panels, ncols=2),
        status=OBSERVED, n_runs_used=ds.n_runs - len(skipped),
        n_obs_used=int(len(pool)),
        summary_values=_metric_summary(ds, ["hill_left", "hill_right"]),
        parameters={"tail_frac": frac, "min_tail_points": 50,
                    "display_thinning": "log-rank, display only"},
        caveats=caveats)


# ------------------------------------------------------------ D. return ACF

def _acf_figure(ds: SimulationDataset, transform, title: str, ylabel: str,
                max_lag: int) -> tuple[Plot, list[np.ndarray], int]:
    by_run = ds.returns_by_run()
    lag_cap = min(max_lag, min(len(r) for r in by_run.values()) // 4)
    curves = [C.acf_curve(transform(r), lag_cap) for r in by_run.values()]
    lags = list(range(1, lag_cap + 1))
    n_med = int(np.median([len(r) for r in by_run.values()]))
    p = Plot(title=title, xlabel="lag", ylabel=ylabel,
             note=f"runs={ds.n_runs}, median n={n_med}, lags 1..{lag_cap}")
    band = C.iid_acf_band(n_med)
    p.band(lags, [-band] * len(lags), [band] * len(lags),
           color=ACCENT_GRAY, opacity=0.18, label="approx. iid 95% band")
    if len(curves) >= 3:
        qs = C.pointwise_quantiles(curves)
        p.band(lags, list(qs[0]), list(qs[2]), opacity=0.22,
               label="across-run IQR")
        p.line(lags, list(qs[1]), width=2.2, label="across-run median")
    else:
        for c in curves:
            p.line(lags, list(c), width=1.8,
                   label="per-run ACF" if len(curves) > 1 else None,
                   opacity=0.9)
    p.hline(0, color="#8a94a3", dash=None, width=1.0)
    return p, curves, lag_cap


def fig_return_acf(ds: SimulationDataset, params: dict) -> FigureOutput:
    if _all_degenerate(ds):
        return _insufficient("every run is constant; the ACF is undefined")
    max_lag = int(params.get("max_lag", 50))
    p, curves, lag_cap = _acf_figure(ds, lambda r: r,
                                     "autocorrelation of returns",
                                     "ACF(r)", max_lag)
    med_lag1 = float(np.median([c[0] for c in curves]))
    return FigureOutput(
        svg=p.render(), status=OBSERVED, n_runs_used=ds.n_runs,
        n_obs_used=ds.n_obs_total,
        summary_values={"acf_return_lag1" + ("_run_median"
                                             if ds.n_runs > 1 else ""):
                        _fin(med_lag1)},
        parameters={"max_lag": max_lag, "effective_max_lag": lag_cap},
        caveats=[_IID_BAND_CAVEAT,
                 "read the decay shape across lags, not a single lag"])


# -------------------------------------------------------- E. volatility ACF

def fig_volatility_acf(ds: SimulationDataset, params: dict) -> FigureOutput:
    if _all_degenerate(ds):
        return _insufficient("every run is constant; the ACF is undefined")
    max_lag = int(params.get("max_lag", 100))
    p1, curves_abs, lag_cap = _acf_figure(
        ds, np.abs, "autocorrelation of |r|", "ACF(|r|)", max_lag)
    p2, _c2, _ = _acf_figure(
        ds, lambda r: r ** 2, "autocorrelation of r^2", "ACF(r^2)", max_lag)
    for p in (p1, p2):
        p.vline(20, color=ACCENT_GRAY, dash="2,3")
    caveats = ["vertical mark at lag 20: the acf_abs_20 metric's lag",
               _IID_BAND_CAVEAT]

    # log-log view of ACF(|r|); nonpositive values cannot be shown
    med = (C.pointwise_quantiles(curves_abs)[1] if len(curves_abs) >= 3
           else curves_abs[0])
    lags = np.arange(1, len(med) + 1)
    pos = np.isfinite(med) & (med > 0)
    dropped = int(len(med) - pos.sum())
    p3 = Plot(title="ACF(|r|) — log-log view", xlabel="lag", ylabel="ACF(|r|)",
              xscale="log", yscale="log",
              note=f"{dropped} nonpositive value(s) not shown"
              if dropped else "all values positive")
    if pos.sum() >= 5:
        p3.scatter(list(lags[pos]), list(med[pos]), radius=2.4)
        panels = [p1.render(), p2.render(), p3.render()]
        caveats.append(
            "no functional form is fitted: apparent straightness on log-log "
            "is NOT evidence of a power law (fit range and estimator would "
            "have to be prespecified)")
    else:
        panels = [p1.render(), p2.render()]
        caveats.append("log-log view omitted: fewer than 5 positive ACF "
                       "values")
    return FigureOutput(
        svg=panel_grid(panels, ncols=2), status=OBSERVED,
        n_runs_used=ds.n_runs, n_obs_used=ds.n_obs_total,
        summary_values=_metric_summary(ds, ["acf_abs_1", "acf_abs_20"]),
        parameters={"max_lag": max_lag, "effective_max_lag": lag_cap},
        caveats=caveats)


# --------------------------------------------------- G. aggregation profile

def fig_aggregation_profile(ds: SimulationDataset, params: dict
                            ) -> FigureOutput:
    horizons = list(params.get("horizons", (1, 2, 5, 10, 20, 40, 80, 160)))
    min_agg = int(params.get("min_aggregated_obs", 200))
    by_run = ds.returns_by_run()
    per_run: dict[str, dict[int, float]] = {}
    for rid, r in by_run.items():
        vals: dict[int, float] = {}
        for dt in horizons:
            agg = r if dt == 1 else C.aggregate_returns(r, dt)
            if len(agg) >= min_agg:
                k = C.excess_kurtosis_value(agg)
                if np.isfinite(k):
                    vals[dt] = float(k)
        per_run[rid] = vals
    common = [dt for dt in horizons
              if all(dt in v for v in per_run.values())]
    if not common:
        return _insufficient(
            f"no aggregation horizon keeps >= {min_agg} aggregated "
            "observations in every run; runs are too short for this profile")
    n_eff = {dt: min(len(by_run[rid]) // dt for rid in by_run)
             for dt in common}
    p = Plot(title="aggregation profile — excess kurtosis vs horizon",
             xlabel="aggregation horizon (steps)", ylabel="excess kurtosis",
             xscale="log",
             note=f"runs={ds.n_runs}; n at largest horizon: "
             f"{n_eff[common[-1]]}")
    for rid, vals in per_run.items():
        dts = [dt for dt in common if dt in vals]
        p.scatter(dts, [vals[dt] for dt in dts], color=ACCENT_GRAY,
                  radius=2.2, opacity=0.55,
                  label="per-run" if ds.n_runs > 1 else None)
    med = [float(np.median([v[dt] for v in per_run.values() if dt in v]))
           for dt in common]
    p.line(common, med, width=2.2,
           label="across-run median" if ds.n_runs > 1 else "kurtosis")
    p.hline(0, color="#8a94a3", dash="4,3")
    caveats = [
        "the effective sample size shrinks with the horizon "
        "(n/dt aggregated observations); rightmost points are the noisiest",
        f"horizons shown only where every run keeps >= {min_agg} aggregated "
        "observations",
        "kurtosis -> 0 with growing horizon is consistent with aggregational "
        "Gaussianity but is not a test of it",
    ]
    return FigureOutput(
        svg=p.render(), status=OBSERVED, n_runs_used=ds.n_runs,
        n_obs_used=ds.n_obs_total,
        summary_values=_metric_summary(ds, ["excess_kurtosis"]),
        parameters={"horizons": horizons, "min_aggregated_obs": min_agg,
                    "n_effective": {str(k): v for k, v in n_eff.items()}},
        caveats=caveats)


# ------------------------------------------------------ J. leverage kernel

def fig_leverage_kernel(ds: SimulationDataset, params: dict) -> FigureOutput:
    if _all_degenerate(ds):
        return _insufficient("every run is constant; correlations are "
                             "undefined")
    max_tau = int(params.get("max_tau", 20))
    metric_lags = int(params.get("metric_lags", 5))
    by_run = ds.returns_by_run()
    taus = None
    curves = []
    for r in by_run.values():
        t, c = C.leverage_curve(r, max_tau)
        taus, _ = t, curves.append(c)
    p = Plot(title="leverage kernel c(tau) = corr(r_t, |r_(t+tau)|)",
             xlabel="tau (steps)", ylabel="c(tau)",
             note=f"runs={ds.n_runs}; shaded: metric range 1..{metric_lags}")
    p.vspan(0.5, metric_lags + 0.5, color="#f0d9c8", opacity=0.7)
    tl = list(taus)
    if len(curves) >= 3:
        qs = C.pointwise_quantiles(curves)
        p.band(tl, list(qs[0]), list(qs[2]), opacity=0.22,
               label="across-run IQR")
        p.line(tl, list(qs[1]), width=2.2, label="across-run median")
    else:
        for c in curves:
            p.line(tl, list(c), width=1.8,
                   label="per-run c(tau)" if len(curves) > 1 else None)
    p.hline(0, color="#8a94a3", dash=None, width=1.0)
    p.vline(0, color=ACCENT_GRAY, dash="2,3")
    caveats = [
        f"the scalar 'leverage' metric is the mean of c(tau) over tau=1.."
        f"{metric_lags} (shaded region) — same per-tau computation as this "
        "curve, verified by tests",
        "c(tau) for tau<0 (future return vs past volatility) is shown for "
        "the time-arrow contrast; equity data typically show c(tau)<0 only "
        "for tau>0",
        "recorded metric blind spot: the lag-count knob moves the scalar "
        "level by ~0.94 IQR",
    ]
    return FigureOutput(
        svg=p.render(), status=OBSERVED, n_runs_used=ds.n_runs,
        n_obs_used=ds.n_obs_total,
        summary_values=_metric_summary(ds, ["leverage"]),
        parameters={"max_tau": max_tau, "metric_lags": metric_lags,
                    "definition": "corr(r_t, |r_(t+tau)|)"},
        caveats=caveats)


# ------------------------------------- drift / variance-ratio diagnostic

def fig_drift_variance(ds: SimulationDataset, params: dict) -> FigureOutput:
    if _all_degenerate(ds):
        return _insufficient("every run is constant; drift/VR are undefined")
    qs = list(params.get("q_values", (2, 5, 10, 20, 40)))
    by_run = ds.returns_by_run()
    drift_vals = {rid: metric_registry.compute("drift@1", r)
                  for rid, r in by_run.items()}
    p1 = Plot(title="drift per run (mean/sd)", xlabel="run",
              ylabel="drift", note=f"runs={ds.n_runs}")
    xs = list(range(1, len(drift_vals) + 1))
    p1.scatter(xs, [drift_vals[rid] for rid in by_run], radius=3.2,
               label=None)
    p1.hline(0, color="#8a94a3", dash=None, width=1.0)

    p2 = Plot(title="variance ratio VR(q)", xlabel="q (steps)",
              ylabel="VR(q)",
              note="VR=1 under independence; <1 mean reversion, >1 trend")
    vr_curves = []
    for rid, r in by_run.items():
        vr = [C.variance_ratio(r, q) for q in qs]
        vr_curves.append(np.array(vr, dtype=float))
    if len(vr_curves) >= 3:
        qq = C.pointwise_quantiles(vr_curves)
        p2.band(qs, list(qq[0]), list(qq[2]), opacity=0.22,
                label="across-run IQR")
        p2.line(qs, list(qq[1]), width=2.2, label="across-run median")
    else:
        for c in vr_curves:
            p2.line(qs, list(c), width=1.8,
                    label="per-run VR" if len(vr_curves) > 1 else None)
    p2.hline(1.0, color="#8a94a3", dash="4,3")
    caveats = [
        "drift here is per-run mean/sd in step units — compare against "
        "your model's intended drift, not against an absolute standard",
        "VR(q) needs q*10 observations per point; short runs drop the "
        "largest q values to NaN",
    ]
    return FigureOutput(
        svg=panel_grid([p1.render(), p2.render()], ncols=2),
        status=OBSERVED, n_runs_used=ds.n_runs, n_obs_used=ds.n_obs_total,
        summary_values=_metric_summary(ds, ["drift", "variance_ratio_20"]),
        parameters={"q_values": qs},
        caveats=caveats)


# ------------------------------------------ F. volume-volatility relation

def fig_volume_volatility(ds: SimulationDataset, params: dict
                          ) -> FigureOutput:
    from scipy.stats import spearmanr

    n_bins = int(params.get("bins", 12))
    max_scatter = int(params.get("max_scatter_points", 2500))
    vol_by_run = ds.column_by_run("volume")
    ret_by_run = ds.returns_by_run()
    pairs_v, pairs_a, rhos = [], [], {}
    for rid in ret_by_run:
        v, a = vol_by_run[rid], np.abs(ret_by_run[rid])
        if v.std() <= 0 or a.std() <= 0:
            rhos[rid] = None
            continue
        rho = spearmanr(v, a).statistic
        rhos[rid] = _fin(rho)
        pairs_v.append(v)
        pairs_a.append(a)
    if not pairs_v:
        return _insufficient(
            "volume or |return| is constant in every run; no relation to "
            "draw")
    v_all = np.concatenate(pairs_v)
    a_all = np.concatenate(pairs_a)
    # deterministic stride thinning for the scatter display
    stride = max(1, len(v_all) // max_scatter)
    v_show, a_show = v_all[::stride], a_all[::stride]
    clip = float(np.quantile(v_all, 0.995))
    shown = v_show <= clip
    edges = np.quantile(v_all, np.linspace(0, 1, n_bins + 1))
    edges = np.unique(edges)
    bin_x, bin_y = [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (v_all >= lo) & (v_all <= hi if hi == edges[-1]
                             else v_all < hi)
        if m.sum() >= 20:
            bin_x.append(float(v_all[m].mean()))
            bin_y.append(float(a_all[m].mean()))
    p = Plot(title="volume vs |return|", xlabel="volume", ylabel="|return|",
             note=f"{int(shown.sum())} of {len(v_all)} points shown")
    p.scatter(list(v_show[shown]), list(a_show[shown]), radius=1.8,
              opacity=0.28, label="per-step pairs")
    if bin_x:
        p.line(bin_x, bin_y, color=SERIES[1], width=2.4,
               label="binned mean |r| (equal-count bins)")
    finite_rhos = [x for x in rhos.values() if x is not None]
    med_rho = float(np.median(finite_rhos)) if finite_rhos else None
    if med_rho is not None:
        p.annotate(float(np.quantile(v_all, 0.65)),
                   float(np.quantile(a_all, 0.999)),
                   f"Spearman rho (run median) = {fmt_num(med_rho)}")
    caveats = [
        "pairs are matched within each run; runs are pooled only for this "
        "marginal scatter (disclosed)",
        "display: stride thinning and volume clipped at the 99.5th "
        "percentile; the binned means and rho use ALL points",
        "Spearman rho is reported per run (median across runs); no "
        "uncertainty interval is attached in exploratory mode",
    ]
    key = "spearman_volume_absret" + ("_run_median" if ds.n_runs > 1 else "")
    return FigureOutput(
        svg=p.render(), status=OBSERVED,
        n_runs_used=len(pairs_v), n_obs_used=int(len(v_all)),
        summary_values={key: med_rho},
        parameters={"bins": n_bins, "correlation": "spearman",
                    "display_clip_quantile": 0.995},
        caveats=caveats)
