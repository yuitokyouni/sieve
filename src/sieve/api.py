"""Python construction API for research datasets (task §3.1-E).

    import sieve
    ds = sieve.from_arrays(returns=r)                       # one run
    ds = sieve.from_runs([{"run_id": "seed-1", "return": r1, "seed": 1},
                          {"run_id": "seed-2", "return": r2, "seed": 2}])
    ds = sieve.from_dataframe(df)                           # pandas or polars

The same explicitness rules as the file adapters apply: price→return only
with a declared ``derive`` method, burn-in only when requested, and runs are
never concatenated.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from sieve.adapters.dataset import _apply_burn_in, _apply_derivation
from sieve.core.dataset import (
    RESERVED_COLUMNS,
    InputError,
    RunSeries,
    SimulationDataset,
    resolve_geometry,
    validate_run,
)
from sieve.core.models import TransformSpec

__all__ = ["from_arrays", "from_runs", "from_dataframe"]


def _finish(runs: list[RunSeries], *, geometry: str | None,
            derive: str | None, burn_in_steps: int | None,
            burn_in_fraction: float | None, time_basis: str
            ) -> SimulationDataset:
    if not runs:
        raise InputError("no runs given")
    transforms: list[TransformSpec] = []
    for run in runs:
        validate_run(run)
        _apply_burn_in(run, burn_in_steps, burn_in_fraction)
        if derive:
            _apply_derivation(run, derive)
    if any(r.n_burned for r in runs):
        transforms.append(TransformSpec(
            name="burn_in",
            parameters={
                "dropped_per_run": {r.run_id: r.n_burned for r in runs},
                "n_obs_raw_per_run": {r.run_id: r.n_obs_raw for r in runs}}))
    if derive:
        transforms.append(TransformSpec(
            name="derive_return",
            parameters={"method": derive, "source_column": "price"}))
    g, source = resolve_geometry(geometry, runs)
    return SimulationDataset(runs=runs, geometry=g, geometry_source=source,
                             time_basis=time_basis, transforms=transforms)


def _to_array(name: str, values: Any, run_id: str) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise InputError(
            f"run '{run_id}': column '{name}' must be 1-dimensional "
            f"(got shape {arr.shape})")
    if len(arr) == 0:
        raise InputError(f"run '{run_id}': column '{name}' is empty")
    return arr


def from_arrays(*, returns: Any = None, price: Any = None,
                run_id: str = "run-0", seed: int | None = None,
                derive: str | None = None, burn_in_steps: int | None = None,
                burn_in_fraction: float | None = None,
                geometry: str | None = None,
                **observables: Any) -> SimulationDataset:
    """Build a single-run dataset from numpy-compatible arrays.

    Pass ``returns=`` and/or ``price=``; extra keyword arrays (``volume=…``)
    become user-defined observables. ``derive`` is required to turn a
    price-only input into returns.
    """
    columns: dict[str, np.ndarray] = {}
    if returns is not None:
        columns["return"] = _to_array("return", returns, run_id)
    if price is not None:
        columns["price"] = _to_array("price", price, run_id)
    for name, vals in observables.items():
        if name in RESERVED_COLUMNS:
            raise InputError(f"'{name}' is a reserved column name")
        columns[name] = _to_array(name, vals, run_id)
    if not columns:
        raise InputError("from_arrays needs at least returns=, price=, or "
                         "one observable array")
    run = RunSeries(run_id=run_id, columns=columns, seed=seed,
                    n_obs_raw=len(next(iter(columns.values()))))
    return _finish([run], geometry=geometry, derive=derive,
                   burn_in_steps=burn_in_steps,
                   burn_in_fraction=burn_in_fraction, time_basis="step")


def from_runs(runs: list[dict[str, Any]], *, derive: str | None = None,
              burn_in_steps: int | None = None,
              burn_in_fraction: float | None = None,
              geometry: str | None = None) -> SimulationDataset:
    """Build a multi-run dataset from a list of per-run dicts.

    Each dict maps column names (``return``, ``price``, ``volume``, …) to
    1-d arrays, plus optional ``run_id`` (default ``run-<i>``) and ``seed``.
    """
    out: list[RunSeries] = []
    seen: set[str] = set()
    for i, spec in enumerate(runs):
        spec = dict(spec)
        rid = str(spec.pop("run_id", f"run-{i}"))
        if rid in seen:
            raise InputError(f"duplicated run_id '{rid}'; give each run a "
                             "unique id")
        seen.add(rid)
        seed = spec.pop("seed", None)
        columns = {("return" if name == "returns" else name):
                   _to_array(name, vals, rid)
                   for name, vals in spec.items()
                   if name not in RESERVED_COLUMNS}
        if not columns:
            raise InputError(f"run '{rid}': no observable columns given")
        out.append(RunSeries(
            run_id=rid, columns=columns,
            seed=None if seed is None else int(seed),
            n_obs_raw=len(next(iter(columns.values())))))
    return _finish(out, geometry=geometry, derive=derive,
                   burn_in_steps=burn_in_steps,
                   burn_in_fraction=burn_in_fraction, time_basis="step")


def from_dataframe(df: Any, *, derive: str | None = None,
                   burn_in_steps: int | None = None,
                   burn_in_fraction: float | None = None,
                   geometry: str | None = None) -> SimulationDataset:
    """Build a dataset from a pandas or Polars DataFrame.

    Columns: optional ``run_id`` (groups rows into runs; row order within a
    run is preserved), optional ``step``, plus numeric observables
    (``return``/``price``/``volume``/…).
    """
    data = _frame_to_dict(df)
    names = list(data)
    observables = [c for c in names if c not in RESERVED_COLUMNS]
    if not observables:
        raise InputError(
            f"dataframe has no observable columns (got {names}); need at "
            "least one of return, price, or another numeric column")
    if "step" in data and "timestamp" in data:
        raise InputError(
            "dataframe has both 'step' and 'timestamp' columns; declare one "
            "time basis")
    n = len(data[names[0]])
    if any(len(data[c]) != n for c in names):
        raise InputError("dataframe columns have unequal lengths")
    if "run_id" in data:
        order: list[str] = []
        groups: dict[str, list[int]] = {}
        for i, rid in enumerate(str(v) for v in data["run_id"]):
            if rid not in groups:
                groups[rid] = []
                order.append(rid)
            groups[rid].append(i)
    else:
        order, groups = ["run-0"], {"run-0": list(range(n))}

    runs: list[RunSeries] = []
    for rid in order:
        rows = groups[rid]
        columns = {c: _to_array(c, [data[c][i] for i in rows], rid)
                   for c in observables}
        steps = (np.array([int(data["step"][i]) for i in rows],
                          dtype=np.int64) if "step" in data else None)
        timestamps = ([str(data["timestamp"][i]) for i in rows]
                      if "timestamp" in data else None)
        runs.append(RunSeries(run_id=rid, columns=columns, steps=steps,
                              timestamps=timestamps, n_obs_raw=len(rows)))
        validate_run(runs[-1])
    return _finish(runs, geometry=geometry, derive=derive,
                   burn_in_steps=burn_in_steps,
                   burn_in_fraction=burn_in_fraction,
                   time_basis="timestamp" if "timestamp" in data else "step")


def _frame_to_dict(df: Any) -> dict[str, list]:
    mod = type(df).__module__.split(".")[0]
    if mod == "polars":
        return {k: list(v) for k, v in df.to_dict(as_series=False).items()}
    if mod == "pandas":
        return {str(c): list(df[c]) for c in df.columns}
    if isinstance(df, dict):
        return {str(k): list(v) for k, v in df.items()}
    raise InputError(
        f"unsupported dataframe type {type(df).__name__}; pass a pandas or "
        "polars DataFrame (or a dict of columns)")
