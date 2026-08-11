"""Research input adapter: files/directories → :class:`SimulationDataset`.

Accepted inputs (task §3.1):

A. legacy single CSV        ``timestamp,return``            (Tier 0, unchanged)
B. step-based single run    ``step,price`` / ``step,return``
C. long format              ``run_id,step,return`` etc. (multiple runs/file)
D. directory of runs        ``manifest.yaml`` + ``runs/*.csv``
E. Python API               :mod:`sieve.api`

Design rules:

- nothing is inferred from the *values*: no frequency inference, no silent
  resampling, no silent price→return conversion;
- runs are parsed, validated, burned-in and returned **separately** — this
  module never concatenates two runs;
- every mutation (burn-in, return derivation) is recorded as a
  :class:`TransformSpec` for the bundle.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np
import yaml

from sieve.core.dataset import (
    RESERVED_COLUMNS,
    InputError,
    RunSeries,
    SimulationDataset,
    burn_in_count,
    derive_return,
    resolve_geometry,
    validate_run,
)
from sieve.core.hashing import sha256_file, sha256_params
from sieve.core.models import DatasetManifest, ModelManifest, TransformSpec

__all__ = ["load_dataset", "InputError"]


# ---------------------------------------------------------------- CSV parsing

def _read_table(path: Path) -> tuple[list[str], list[list[str]]]:
    if not path.exists():
        raise InputError(f"input not found: {path}")
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            raise InputError(f"{path}: empty CSV")
        cols = [c.strip().lower() for c in header]
        rows = [row for row in reader
                if row and any(c.strip() for c in row)]
    if not rows:
        raise InputError(f"{path}: CSV has a header but no data rows")
    return cols, rows


def _parse_float(cell: str, path: Path, ln: int, col: str) -> float:
    try:
        return float(cell)
    except ValueError as e:
        raise InputError(
            f"{path} line {ln}: column '{col}' has non-numeric value "
            f"{cell!r}; fix the row or remove it from the file") from e


def _parse_file(path: Path) -> list[RunSeries]:
    """Parse one CSV into one or more runs (long format via run_id)."""
    cols, rows = _read_table(path)
    if len(set(cols)) != len(cols):
        raise InputError(f"{path}: duplicated column names in header {cols}")
    numeric = [c for c in cols if c not in RESERVED_COLUMNS]
    if not numeric:
        raise InputError(
            f"{path}: no observable columns (header {cols}); need at least "
            "one of return, price, or another numeric observable")
    has_run = "run_id" in cols
    has_step = "step" in cols
    has_ts = "timestamp" in cols
    if has_step and has_ts:
        raise InputError(
            f"{path}: both 'step' and 'timestamp' columns present; declare "
            "one time basis per file")
    idx = {c: cols.index(c) for c in cols}

    groups: dict[str, list[list[str]]] = {}
    order: list[str] = []
    for row in rows:
        if len(row) < len(cols):
            raise InputError(
                f"{path}: a row has {len(row)} cells but the header has "
                f"{len(cols)}; fix the file")
        rid = row[idx["run_id"]].strip() if has_run else path.stem
        if not rid:
            raise InputError(f"{path}: empty run_id value")
        if rid not in groups:
            groups[rid] = []
            order.append(rid)
        groups[rid].append(row)

    runs: list[RunSeries] = []
    for rid in order:
        grows = groups[rid]
        columns: dict[str, np.ndarray] = {}
        for c in numeric:
            columns[c] = np.array(
                [_parse_float(row[idx[c]], path, ln, c)
                 for ln, row in enumerate(grows, start=2)], dtype=float)
        steps = None
        timestamps = None
        if has_step:
            try:
                steps = np.array([int(float(row[idx["step"]]))
                                  for row in grows], dtype=np.int64)
            except ValueError as e:
                raise InputError(
                    f"{path}: run '{rid}': non-integer step value; steps "
                    "must be integers") from e
        elif has_ts:
            timestamps = [row[idx["timestamp"]].strip() for row in grows]
        run = RunSeries(run_id=rid, columns=columns, steps=steps,
                        timestamps=timestamps, n_obs_raw=len(grows))
        validate_run(run)
        runs.append(run)
    return runs


# ------------------------------------------------------------- preprocessing

def _apply_burn_in(run: RunSeries, steps: int | None,
                   fraction: float | None) -> None:
    k = burn_in_count(run.n_obs, steps, fraction, run.run_id)
    if k == 0:
        return
    run.n_burned = k
    run.columns = {c: v[k:] for c, v in run.columns.items()}
    if run.steps is not None:
        run.steps = run.steps[k:]
    if run.timestamps is not None:
        run.timestamps = run.timestamps[k:]


def _apply_derivation(run: RunSeries, method: str) -> None:
    if "return" in run.columns:
        raise InputError(
            f"run '{run.run_id}': derive_return='{method}' requested but the "
            "input already has a 'return' column; remove the declaration or "
            "the column — sieve will not silently overwrite data")
    if "price" not in run.columns:
        raise InputError(
            f"run '{run.run_id}': derive_return='{method}' requested but "
            "there is no 'price' column")
    if run.n_obs < 2:
        raise InputError(
            f"run '{run.run_id}': only {run.n_obs} observation(s) remain "
            "(after any burn-in), but return derivation consumes one row; "
            "provide longer runs or lower the burn-in")
    r = derive_return(run.columns["price"], method, run.run_id)
    # derivation consumes the first row of every aligned observable
    run.columns = {c: v[1:] for c, v in run.columns.items()}
    run.columns["return"] = r
    if run.steps is not None:
        run.steps = run.steps[1:]
    if run.timestamps is not None:
        run.timestamps = run.timestamps[1:]


def _check_spacing(run: RunSeries) -> None:
    if run.steps is not None and len(run.steps) > 1:
        d = np.diff(run.steps)
        run.irregular_spacing = bool(len(np.unique(d)) > 1)


# ----------------------------------------------------------------- assembly

def _assemble(runs: list[RunSeries], *, declared_geometry: str | None,
              time_basis: str, transforms: list[TransformSpec],
              derive: str | None, burn_steps: int | None,
              burn_fraction: float | None,
              per_run_burn: dict[str, int] | None = None,
              seeds: dict[str, int] | None = None) -> SimulationDataset:
    if not runs:
        raise InputError("no runs found in input")
    ids = [r.run_id for r in runs]
    if len(set(ids)) != len(ids):
        dup = sorted({i for i in ids if ids.count(i) > 1})
        raise InputError(
            f"duplicated run_id(s) across input files: {dup}; give each run "
            "a unique id")

    caveats: list[str] = []
    for run in runs:
        if seeds and run.run_id in seeds:
            run.seed = seeds[run.run_id]
        b_steps = burn_steps
        if per_run_burn and run.run_id in per_run_burn:
            b_steps = per_run_burn[run.run_id]
        _apply_burn_in(run, b_steps, burn_fraction if b_steps is None else None)
        if derive:
            _apply_derivation(run, derive)
        _check_spacing(run)
        if run.irregular_spacing:
            caveats.append(
                f"run '{run.run_id}': irregular step spacing; lag-based "
                "diagnostics read lags in rows, not in time units")

    if any(r.n_burned for r in runs):
        transforms.append(TransformSpec(
            name="burn_in",
            parameters={
                "dropped_per_run": {r.run_id: r.n_burned for r in runs},
                "n_obs_raw_per_run": {r.run_id: r.n_obs_raw for r in runs},
            }))
    if derive:
        transforms.append(TransformSpec(
            name="derive_return",
            parameters={"method": derive, "source_column": "price"}))

    geometry, source = resolve_geometry(declared_geometry, runs)

    return SimulationDataset(runs=runs, geometry=geometry,
                             geometry_source=source, time_basis=time_basis,
                             transforms=transforms, caveats=caveats)


def _manifests(meta: dict, *, source: Path,
               content_hash: str, dataset: SimulationDataset,
               ) -> tuple[ModelManifest, DatasetManifest]:
    # Undeclared identity defaults are CONTENT-derived, never path-derived:
    # these fields live inside the sealed bundle, and the seal contract says
    # the same input bytes under another path are the same science.
    content_id = f"sha256:{content_hash[:12]}"
    params = dict(meta.get("parameters", {}))
    model = ModelManifest(
        model_id=str(meta.get("model_id", f"undeclared-model-{content_id}")),
        model_version=str(meta.get("model_version", "unversioned")),
        display_name=str(meta.get("display_name",
                                  meta.get("model_id",
                                           f"undeclared model {content_id}"))),
        model_family=meta.get("model_family"),
        adapter_id="dataset@1",
        code_uri=meta.get("code_uri"),
        git_commit=meta.get("git_commit"),
        parameters=params,
        parameters_hash=sha256_params(params),
        authors=list(meta.get("authors", [])),
        license=meta.get("license"),
        notes=meta.get("notes"))
    ds = DatasetManifest(
        dataset_id=str(meta.get("dataset_id", f"input:{content_id}")),
        source_uri=str(source),
        frequency=str(meta.get("frequency", dataset.time_basis)),
        transforms=dataset.transforms,
        content_hash=content_hash)
    return model, ds


# ------------------------------------------------------------- entry points

def _load_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    meta = yaml.safe_load(path.read_text()) or {}
    if not isinstance(meta, dict):
        raise InputError(f"{path}: manifest must be a YAML mapping")
    return meta


def _burn_config(meta: dict, cli_steps: int | None,
                 cli_fraction: float | None
                 ) -> tuple[int | None, float | None]:
    b = meta.get("burn_in", {}) or {}
    if not isinstance(b, dict):
        raise InputError("manifest burn_in must be a mapping, e.g. "
                         "burn_in: {steps: 500} or {fraction: 0.1}")
    steps = cli_steps if cli_steps is not None else b.get("steps")
    fraction = cli_fraction if cli_fraction is not None else b.get("fraction")
    if steps is not None and fraction is not None:
        raise InputError("both burn-in steps and fraction configured; "
                         "declare exactly one")
    return (None if steps is None else int(steps),
            None if fraction is None else float(fraction))


def _load_directory(root: Path, meta: dict, derive: str | None,
                    burn_steps: int | None, burn_fraction: float | None
                    ) -> tuple[SimulationDataset, str]:
    """Directory-of-runs input: manifest.yaml + runs/*.csv (task §3.1-D)."""
    runs_dir = root / "runs"
    entries = meta.get("runs")
    per_run_burn: dict[str, int] = {}
    seeds: dict[str, int] = {}
    file_entries: list[tuple[Path, dict]] = []
    if entries:
        for e in entries:
            if not isinstance(e, dict) or "file" not in e:
                raise InputError(
                    "manifest runs entries must be mappings with a 'file' "
                    "key, e.g. {file: runs/seed-001.csv, seed: 1}")
            p = root / str(e["file"])
            if not p.exists():
                raise InputError(f"manifest lists {e['file']} but {p} does "
                                 "not exist")
            file_entries.append((p, e))
    else:
        if not runs_dir.is_dir():
            raise InputError(
                f"{root}: directory input needs a runs/ subdirectory or a "
                "manifest.yaml with a 'runs:' list")
        files = sorted(runs_dir.glob("*.csv"))
        if not files:
            raise InputError(f"{runs_dir}: no *.csv run files found")
        file_entries = [(p, {}) for p in files]

    all_runs: list[RunSeries] = []
    bases: set[str] = set()
    hash_parts: dict[str, str] = {}
    for p, e in file_entries:
        runs = _parse_file(p)
        # per-entry declarations bind to the runs actually parsed from that
        # file — a name mismatch is an error, never a silent drop
        if "run_id" in e:
            if len(runs) != 1:
                raise InputError(
                    f"manifest entry {e['file']}: run_id declared but the "
                    f"file contains {len(runs)} runs; per-run settings for "
                    "long-format files need one manifest entry per run_id "
                    "column value, which is not supported — split the file "
                    "or drop the declaration")
            runs[0].run_id = str(e["run_id"])
        if "seed" in e or "burn_in_steps" in e:
            if len(runs) != 1:
                raise InputError(
                    f"manifest entry {e['file']}: seed/burn_in_steps "
                    f"declared but the file contains {len(runs)} runs; "
                    "per-run settings need single-run files")
            if "seed" in e:
                seeds[runs[0].run_id] = int(e["seed"])
            if "burn_in_steps" in e:
                per_run_burn[runs[0].run_id] = int(e["burn_in_steps"])
        # run-file names are part of the declared dataset identity: they are
        # hashed into content_hash, so run ids derived from them stay
        # consistent with the seal contract
        hash_parts[p.relative_to(root).as_posix()] = sha256_file(p)
        for r in runs:
            bases.add("step" if r.steps is not None else
                      "timestamp" if r.timestamps is not None else "none")
        all_runs.extend(runs)
    if len(bases) > 1:
        raise InputError(
            f"run files mix time bases {sorted(bases)}; all runs must share "
            "one of 'step' or 'timestamp'")
    time_basis = bases.pop() if bases and "none" not in bases else "step"

    dataset = _assemble(
        all_runs, declared_geometry=meta.get("geometry"),
        time_basis=time_basis, transforms=[],
        derive=derive, burn_steps=burn_steps, burn_fraction=burn_fraction,
        per_run_burn=per_run_burn or None, seeds=seeds or None)
    content_hash = sha256_params({"files": hash_parts})
    return dataset, content_hash


def load_dataset(
        input_path: str | Path,
        *,
        derive: str | None = None,
        burn_in_steps: int | None = None,
        burn_in_fraction: float | None = None,
) -> tuple[SimulationDataset, ModelManifest, DatasetManifest]:
    """Load any accepted file/directory input into a standardized dataset.

    ``derive``, ``burn_in_steps`` and ``burn_in_fraction`` are CLI-level
    overrides; when ``None`` the manifest values (if any) apply. Returns the
    dataset plus the model/dataset manifests for the evidence bundle.
    """
    input_path = Path(input_path)
    if input_path.is_dir():
        meta = _load_manifest(input_path / "manifest.yaml")
        derive = derive or meta.get("derive_return")
        burn_steps, burn_fraction = _burn_config(meta, burn_in_steps,
                                                 burn_in_fraction)
        legacy_csv = input_path / "returns.csv"
        if (input_path / "runs").is_dir() or meta.get("runs"):
            dataset, content_hash = _load_directory(
                input_path, meta, derive, burn_steps, burn_fraction)
            model, ds = _manifests(meta, source=input_path,
                                   content_hash=content_hash, dataset=dataset)
            return dataset, model, ds
        if legacy_csv.exists():
            return _load_single_file(legacy_csv, meta, derive, burn_steps,
                                     burn_fraction)
        raise InputError(
            f"{input_path}: expected returns.csv (legacy input) or a runs/ "
            "subdirectory / manifest 'runs:' list (research input)")

    meta = _load_manifest(input_path.parent / "manifest.yaml")
    derive = derive or meta.get("derive_return")
    burn_steps, burn_fraction = _burn_config(meta, burn_in_steps,
                                             burn_in_fraction)
    return _load_single_file(input_path, meta, derive, burn_steps,
                             burn_fraction)


def _load_single_file(csv_path: Path, meta: dict, derive: str | None,
                      burn_steps: int | None, burn_fraction: float | None
                      ) -> tuple[SimulationDataset, ModelManifest,
                                 DatasetManifest]:
    runs = _parse_file(csv_path)
    if len(runs) == 1 and runs[0].run_id == csv_path.stem:
        # no run_id column: the id was a filename default. Filenames of bare
        # CSVs are outside the content hash, so a path-derived id would leak
        # into the seal; use a constant instead.
        runs[0].run_id = "run-0"
    time_basis = ("step" if runs[0].steps is not None else
                  "timestamp" if runs[0].timestamps is not None else "step")
    seeds = {str(k): int(v) for k, v in (meta.get("seeds") or {}).items()}
    unknown = sorted(set(seeds) - {r.run_id for r in runs})
    if unknown:
        raise InputError(
            f"manifest seeds name run id(s) {unknown} not present in the "
            f"input (have: {[r.run_id for r in runs]}); fix the mapping — "
            "sieve does not silently drop declared seeds")
    dataset = _assemble(
        runs, declared_geometry=meta.get("geometry"), time_basis=time_basis,
        transforms=[], derive=derive, burn_steps=burn_steps,
        burn_fraction=burn_fraction, seeds=seeds or None)
    model, ds = _manifests(meta, source=csv_path,
                           content_hash=sha256_file(csv_path),
                           dataset=dataset)
    return dataset, model, ds
