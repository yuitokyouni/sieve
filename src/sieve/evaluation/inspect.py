"""The exploratory path: input → dataset → per-run metrics → figures →
sealed inspect bundle + report.

Contract (task §4.1):

- works without any reference data and on a single short run;
- produces descriptive statistics and diagnostic figures only;
- emits no PASS/FAIL and no p-values — statuses are OBSERVED /
  INSUFFICIENT / NOT_APPLICABLE / NOT_TESTED / ERROR (defined in
  ``core.enums.ExploratoryStatus``; ERROR marks a sieve-internal bug,
  never a data fact);
- the report states its exploratory nature on every page;
- inadequate metrics/figures resolve individually; nothing aggregates.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from pathlib import Path

import numpy as np

from sieve import __version__
from sieve.adapters.dataset import load_dataset
from sieve.core.dataset import InputError, SimulationDataset
from sieve.core.enums import ExploratoryStatus
from sieve.core.hashing import sha256_file
from sieve.core.models import (
    ArtifactRef,
    GeometrySummary,
    InspectBundle,
    MetricObservation,
    RunManifest,
    RunSummary,
)
from sieve.figures.registry import render_figures
from sieve.metrics import registry as metric_registry
from sieve.provenance.bundle import seal_inspect, write_inspect
from sieve.provenance.environment import environment_fingerprint, make_rngs
from sieve.reporting.html import render_inspect_report
from sieve.suites.loader import load as load_suite

DEFAULT_SUITE = "financial-stylized-facts@0.1"


def _geometry_summary(ds: SimulationDataset) -> GeometrySummary:
    return GeometrySummary(
        geometry=ds.geometry.value, geometry_source=ds.geometry_source,
        time_basis=ds.time_basis, n_runs=ds.n_runs,
        n_obs_total=ds.n_obs_total, columns=ds.columns(),
        runs=[RunSummary(run_id=r.run_id, seed=r.seed,
                         n_obs_raw=r.n_obs_raw, n_obs=r.n_obs,
                         n_burned=r.n_burned,
                         irregular_spacing=r.irregular_spacing)
              for r in ds.runs])


def _metric_gate(req, ds: SimulationDataset, run) -> tuple[
        ExploratoryStatus, str] | None:
    """Check one (metric, run) pair against the metric's full declared
    :class:`MetricRequirements`; ``None`` means adequate. Every declared
    requirement is enforced here — declaring a requirement without an
    enforcing gate would let future metrics run on inputs they refused."""
    missing = [c for c in req.required_columns if c not in run.columns]
    if missing:
        return (ExploratoryStatus.NOT_APPLICABLE,
                f"run has no '{'/'.join(missing)}' column")
    if ds.geometry.value not in req.supported_geometries:
        return (ExploratoryStatus.NOT_APPLICABLE,
                f"geometry '{ds.geometry.value}' is not supported by this "
                "metric")
    if run.irregular_spacing and (req.requires_regular_spacing
                                  or not req.supports_irregular_time):
        return (ExploratoryStatus.NOT_APPLICABLE,
                "run has irregular step spacing and this metric requires "
                "regular spacing")
    applied = {t.name for t in ds.transforms}
    unmet = [p for p in req.preprocessing_requirements if p not in applied]
    if unmet:
        return (ExploratoryStatus.NOT_APPLICABLE,
                f"declared preprocessing requirement(s) {unmet} were not "
                "applied to this input")
    if run.n_obs < req.minimum_observations_per_run:
        return (ExploratoryStatus.INSUFFICIENT,
                f"{run.n_obs} observations < metric minimum "
                f"{req.minimum_observations_per_run}")
    return None


def _metric_observations(ds: SimulationDataset, metric_refs: list[str]
                         ) -> list[MetricObservation]:
    """Per-run metric values, gated by each metric's declared requirements.

    An inadequate (run, metric) pair becomes its own INSUFFICIENT /
    NOT_APPLICABLE observation; it never blocks other metrics or runs. A
    metric implementation *raising* becomes ERROR — a sieve bug on record,
    never disguised as data inadequacy.
    """
    from sieve.core.models import MetricRequirements

    out: list[MetricObservation] = []
    for mref in metric_refs:
        _, spec, _dim = metric_registry.resolve(mref)
        req = spec.requirements or MetricRequirements()
        gated: dict[str, tuple[ExploratoryStatus, str]] = {}
        adequate = []
        for run in ds.runs:
            verdict = _metric_gate(req, ds, run)
            if verdict is None:
                adequate.append(run)
            else:
                gated[run.run_id] = verdict
        if len(adequate) < req.minimum_runs:
            for run in adequate:
                gated[run.run_id] = (
                    ExploratoryStatus.INSUFFICIENT,
                    f"only {len(adequate)} adequate run(s) < metric minimum "
                    f"of {req.minimum_runs} run(s)")
            adequate = []
        for run in ds.runs:
            if run.run_id in gated:
                status, note = gated[run.run_id]
                out.append(MetricObservation(
                    metric_ref=mref, run_id=run.run_id,
                    status=status, note=note))
                continue
            try:
                v = metric_registry.compute(mref, run.columns["return"])
            except metric_registry.MetricComputationError as e:
                out.append(MetricObservation(
                    metric_ref=mref, run_id=run.run_id,
                    status=ExploratoryStatus.ERROR,
                    note=f"internal error, not a data property — {e}; "
                         "please report this as a sieve bug"))
                continue
            if not np.isfinite(v):
                out.append(MetricObservation(
                    metric_ref=mref, run_id=run.run_id,
                    status=ExploratoryStatus.INSUFFICIENT,
                    note="metric returned a non-finite value on this run"))
            else:
                out.append(MetricObservation(
                    metric_ref=mref, run_id=run.run_id, value=float(v),
                    status=ExploratoryStatus.OBSERVED))
    return out


def _write_observations(run_dir: Path, ds: SimulationDataset,
                        observations: list[MetricObservation],
                        metric_refs: list[str]) -> None:
    import polars as pl

    by_metric: dict[str, dict[str, float | None]] = {}
    for ob in observations:
        mid = ob.metric_ref.partition("@")[0]
        by_metric.setdefault(mid, {})[ob.run_id] = ob.value
    rows: dict[str, list] = {
        "run_id": [r.run_id for r in ds.runs],
        "n_obs": [r.n_obs for r in ds.runs],
    }
    for mref in metric_refs:
        mid = mref.partition("@")[0]
        vals = by_metric.get(mid, {})
        rows[mid] = [vals.get(r.run_id) for r in ds.runs]
    pl.DataFrame(rows).write_parquet(run_dir / "observations.parquet")


def _load_reference(reference_path: str | Path,
                    label: str | None,
                    derive: str | None) -> dict:
    """Load an empirical comparator series for figure overlays.

    The reference must resolve to a SINGLE series (one run) with a return
    column (derivable with an explicit method). Its identity is the content
    hash — the default label is content-derived so no path leaks into the
    sealed figure parameters.
    """
    ref_ds, _model, ref_manifest = load_dataset(reference_path, derive=derive)
    if ref_ds.n_runs != 1:
        raise InputError(
            f"reference input has {ref_ds.n_runs} runs; the overlay "
            "comparator must be a single series (e.g. one index's daily "
            "returns)")
    if not ref_ds.has_column("return"):
        raise InputError(
            "reference input has no 'return' column; pass "
            "--reference-derive-return log|simple|diff for price-only "
            "references")
    r = ref_ds.runs[0].columns["return"]
    content_hash = ref_manifest.content_hash
    return {
        "r": r,
        "label": label or f"sha256:{content_hash[:12]}",
        "content_hash": content_hash,
        "n_obs": int(len(r)),
    }


def run_inspect(input_path: str | Path,
                suite_ref: str = DEFAULT_SUITE,
                out_root: str | Path = ".sieve/runs",
                master_seed: int = 20260802,
                derive: str | None = None,
                burn_in_steps: int | None = None,
                burn_in_fraction: float | None = None,
                reference_path: str | Path | None = None,
                reference_label: str | None = None,
                reference_derive: str | None = None) -> Path:
    """Run the exploratory inspection; return the new run directory."""
    suite = load_suite(suite_ref)
    ds, model, dataset_manifest = load_dataset(
        input_path, derive=derive, burn_in_steps=burn_in_steps,
        burn_in_fraction=burn_in_fraction)
    reference = (None if reference_path is None else
                 _load_reference(reference_path, reference_label,
                                 reference_derive))

    _rngs, seed_tree = make_rngs(master_seed)
    run_id = uuid.uuid4().hex[:12]
    run_dir = Path(out_root) / run_id
    (run_dir / "report").mkdir(parents=True, exist_ok=True)

    observations = _metric_observations(ds, suite.manifest.metrics)
    _write_observations(run_dir, ds, observations, suite.manifest.metrics)
    figures = render_figures(ds, suite.figures, run_dir,
                             reference=reference)

    manifest = RunManifest(
        run_id=run_id, created_at=dt.datetime.now(dt.timezone.utc),
        sieve_version=__version__,
        command=(f"sieve inspect {input_path} --suite {suite_ref}"
                 + (f" --reference {reference_path}"
                    if reference_path is not None else "")),
        master_seed=master_seed, seed_tree=seed_tree,
        environment=environment_fingerprint(),
        input_path=str(input_path),
        input_hash=dataset_manifest.content_hash)

    limitations = [
        "EXPLORATORY: this run makes no confirmatory decision; figures and "
        "descriptive statistics support visual inspection only",
        "no reference comparison was performed; nothing here says the "
        "simulation matches any real market",
        "OBSERVED means the diagnostic was computed and rendered from "
        "adequate data — it does not mean a stylized fact 'holds'",
        "confirmatory claims require `sieve test` against a reference suite "
        "with prespecified inference",
    ]
    for c in ds.caveats:
        limitations.append(f"input caveat: {c}")
    if reference is not None:
        limitations.append(
            f"figures overlay the empirical reference '{reference['label']}' "
            f"(content sha256 {reference['content_hash'][:16]}…, "
            f"{reference['n_obs']} obs) as visual context only; no "
            "statistical comparison against it is performed")

    bundle = InspectBundle(
        bundle_id=uuid.uuid4(),
        created_at=dt.datetime.now(dt.timezone.utc),
        run_manifest=manifest, model=model, dataset=dataset_manifest,
        suite_ref=f"{suite.manifest.suite_id}@{suite.manifest.version}",
        suite_hash=suite.manifest.suite_hash,
        geometry=_geometry_summary(ds),
        figures=figures, metric_observations=observations,
        limitations=limitations, artifact_index=[])

    # Seal first (the report displays the seal); the artifact index is
    # filled afterwards under the file-integrity layer, exactly like the
    # confirmatory bundle.
    seal_inspect(bundle)

    _write_json(run_dir / "manifest.json",
                json.loads(manifest.model_dump_json()))
    _write_json(run_dir / "dataset_summary.json",
                json.loads(bundle.geometry.model_dump_json()))
    _write_json(run_dir / "figures.json",
                [json.loads(f.model_dump_json()) for f in figures])
    if reference is not None:
        _write_json(run_dir / "reference_summary.json", {
            "label": reference["label"],
            "content_hash_sha256": reference["content_hash"],
            "n_obs": reference["n_obs"],
            "source_path_informational": str(reference_path),
            "role": "figure overlay comparator (exploratory; no inference)"})
    # trusted_artifacts: this render inlines the SVG files this very process
    # wrote above; the artifact index (their hashes) is only filled below
    render_inspect_report(run_dir / "report" / "index.html", bundle, run_dir,
                          trusted_artifacts=True)

    rels = ["manifest.json", "dataset_summary.json", "observations.parquet",
            "figures.json", "report/index.html"]
    if reference is not None:
        rels.append("reference_summary.json")
    rels += sorted(f"figures/{p.name}" for p in
                   (run_dir / "figures").glob("*.svg")) \
        if (run_dir / "figures").is_dir() else []
    for rel in rels:
        p = run_dir / rel
        kind = ("report" if rel.startswith("report") else
                "figure" if rel.startswith("figures") else "table")
        bundle.artifact_index.append(
            ArtifactRef(path=rel, sha256=sha256_file(p), kind=kind))

    write_inspect(bundle, run_dir)
    return run_dir


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True,
                               ensure_ascii=False) + "\n")
