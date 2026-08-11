"""Generalized simulation dataset: the research-workbench input contract.

A :class:`SimulationDataset` is the standardized internal representation of
simulation output for the research workflow (task §3.1):

- one or more **runs**, each an independent realization (seed, market,
  arm, …) — runs are never concatenated into one series;
- per-run numeric **observables** (``return``, ``price``, ``volume``,
  user-defined columns), aligned on a declared time basis (``step`` or
  ``timestamp``) — no calendar or frequency is ever inferred;
- explicit, recorded preprocessing: price→return derivation only when the
  method is declared, burn-in with before/after counts per run.

Everything that changed the data on its way in is a :class:`TransformSpec`
so the evidence bundle can replay the exact pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from sieve.core.models import TransformSpec


class InputError(ValueError):
    """User-facing input problem. The message always says how to fix it."""


class Geometry(str, Enum):
    """How the runs relate to each other as sampling units (task §3.4).

    The geometry decides which inference designs are honest for the data;
    it is declared (manifest) or defaulted structurally from the run count
    and length — never inferred from the statistics of the values.
    """

    SINGLE_LONG_SERIES = "single_long_series"
    MULTI_RUN_ENSEMBLE = "multi_run_ensemble"
    MULTI_MARKET_PANEL = "multi_market_panel"
    PAIRED_RUNS = "paired_runs"
    SHORT_EXPLORATORY_SERIES = "short_exploratory_series"


# a single run below this length is treated as exploratory by default
SHORT_SERIES_THRESHOLD = 1000

RESERVED_COLUMNS = ("run_id", "step", "timestamp")


@dataclass
class RunSeries:
    """One independent realization: its observables and time axis."""

    run_id: str
    columns: dict[str, np.ndarray]          # name -> 1d float array
    steps: np.ndarray | None = None         # int step index, if step-based
    timestamps: list[str] | None = None     # raw strings, if timestamp-based
    seed: int | None = None
    pair_id: str | None = None              # reserved for paired_runs (R4)
    n_obs_raw: int = 0                      # rows before burn-in
    n_burned: int = 0                       # rows dropped by burn-in
    irregular_spacing: bool = False

    @property
    def n_obs(self) -> int:
        return len(next(iter(self.columns.values()))) if self.columns else 0


@dataclass
class SimulationDataset:
    """Standardized multi-run dataset plus everything done to build it."""

    runs: list[RunSeries]
    geometry: Geometry
    geometry_source: str                    # "declared" | "structural_default"
    time_basis: str                         # "step" | "timestamp"
    transforms: list[TransformSpec] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    @property
    def n_runs(self) -> int:
        return len(self.runs)

    @property
    def n_obs_total(self) -> int:
        return sum(r.n_obs for r in self.runs)

    def columns(self) -> list[str]:
        """Observable names present in every run (order-stable)."""
        if not self.runs:
            return []
        common = set(self.runs[0].columns)
        for r in self.runs[1:]:
            common &= set(r.columns)
        return [c for c in self.runs[0].columns if c in common]

    def has_column(self, name: str) -> bool:
        return bool(self.runs) and all(name in r.columns for r in self.runs)

    def column_by_run(self, name: str) -> dict[str, np.ndarray]:
        """``{run_id: values}`` for one observable. Runs stay separate —
        callers must never concatenate them into a single series."""
        if not self.has_column(name):
            have = ", ".join(self.columns()) or "none"
            raise InputError(
                f"column '{name}' is not present in every run (have: {have}); "
                "add it to the input files or declare a derivation")
        return {r.run_id: r.columns[name] for r in self.runs}

    def returns_by_run(self) -> dict[str, np.ndarray]:
        return self.column_by_run("return")


def validate_run(run: RunSeries) -> None:
    """Structural validation of one run. Raises :class:`InputError` with a
    fix suggestion; never repairs data silently (invariants §2-12/13)."""
    lengths = {name: len(v) for name, v in run.columns.items()}
    if len(set(lengths.values())) > 1:
        raise InputError(
            f"run '{run.run_id}': observable columns have unequal lengths "
            f"{lengths}; every column in a run must cover the same rows")
    for name, v in run.columns.items():
        if not np.isfinite(v).all():
            bad = int(np.flatnonzero(~np.isfinite(v))[0])
            raise InputError(
                f"run '{run.run_id}': non-finite value in column '{name}' at "
                f"row {bad + 1}; remove or re-generate the run — sieve does "
                "not interpolate or drop values silently")
    if run.steps is not None:
        if len(np.unique(run.steps)) != len(run.steps):
            raise InputError(
                f"run '{run.run_id}': duplicated step values; each row must "
                "have a unique step (did two runs end up in one file without "
                "a run_id column?)")
        if np.any(np.diff(run.steps) <= 0):
            raise InputError(
                f"run '{run.run_id}': step values are not strictly "
                "increasing; sort the rows or fix the generator output")
    if run.timestamps is not None:
        seen: set[str] = set()
        for t in run.timestamps:
            if t and t in seen:
                raise InputError(
                    f"run '{run.run_id}': duplicated timestamp '{t}'; each "
                    "row must have a unique timestamp (multiple runs in one "
                    "file need a run_id column)")
            seen.add(t)


def derive_return(price: np.ndarray, method: str, run_id: str) -> np.ndarray:
    """Explicit price→return conversion (task §3.2). Never applied unless
    the method was declared in a manifest, CLI flag or API argument."""
    if method == "log":
        if np.any(price <= 0):
            bad = int(np.flatnonzero(price <= 0)[0])
            raise InputError(
                f"run '{run_id}': log-return requested but price at row "
                f"{bad + 1} is <= 0; use derive_return 'diff' or 'simple', "
                "or fix the price series")
        return np.diff(np.log(price))
    if method == "simple":
        if np.any(price[:-1] == 0):
            raise InputError(
                f"run '{run_id}': simple-return requested but a price is 0; "
                "use derive_return 'diff' or fix the price series")
        return price[1:] / price[:-1] - 1.0
    if method == "diff":
        return np.diff(price)
    raise InputError(
        f"unknown return derivation '{method}'; choose one of: log, simple, "
        "diff")


def burn_in_count(n_obs: int, steps: int | None, fraction: float | None,
                  run_id: str) -> int:
    """Number of leading observations to drop for one run (task §3.3)."""
    if steps is not None and fraction is not None:
        raise InputError(
            f"run '{run_id}': both burn_in steps and fraction given; "
            "declare exactly one")
    if steps is not None:
        if steps < 0:
            raise InputError(f"run '{run_id}': negative burn_in steps")
        k = int(steps)
    elif fraction is not None:
        if not 0 <= fraction < 1:
            raise InputError(
                f"run '{run_id}': burn_in fraction must be in [0, 1)")
        k = int(round(n_obs * float(fraction)))
    else:
        return 0
    if k >= n_obs:
        raise InputError(
            f"run '{run_id}': burn-in of {k} rows would drop all {n_obs} "
            "observations; lower the burn-in or provide longer runs")
    return k


def default_geometry(runs: list[RunSeries]) -> Geometry:
    """Structural default when no geometry is declared: run count and
    length only, never the values themselves."""
    if len(runs) > 1:
        return Geometry.MULTI_RUN_ENSEMBLE
    if runs and runs[0].n_obs < SHORT_SERIES_THRESHOLD:
        return Geometry.SHORT_EXPLORATORY_SERIES
    return Geometry.SINGLE_LONG_SERIES


def resolve_geometry(declared: str | None, runs: list[RunSeries]
                     ) -> tuple[Geometry, str]:
    """Resolve a (possibly declared) geometry against the actual runs.

    Shared by the file adapter and the Python API so both enforce the same
    rules: unknown names are errors, and ``single_long_series`` with more
    than one run is refused — sieve never concatenates runs.
    """
    if declared is None:
        return default_geometry(runs), "structural_default"
    try:
        geometry = Geometry(declared)
    except ValueError:
        raise InputError(
            f"unknown geometry '{declared}'; choose one of: "
            + ", ".join(g.value for g in Geometry)) from None
    if geometry is Geometry.SINGLE_LONG_SERIES and len(runs) > 1:
        raise InputError(
            f"geometry 'single_long_series' declared but the input has "
            f"{len(runs)} runs; declare multi_run_ensemble or provide "
            "one run — sieve never concatenates runs into one series")
    return geometry, "declared"
