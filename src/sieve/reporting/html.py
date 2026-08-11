"""Local HTML report. Section order is fixed by spec §9.1:
claim → scope/reference → profile matrix → critical findings →
what was not tested → provenance. A global score never appears because
none exists anywhere in the system."""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from sieve.core.branding import PRODUCT_NAME, REPORT_FOOTER
from sieve.core.enums import Status
from sieve.core.models import EvidenceBundle

# Autoescape unconditionally: every template here renders HTML, and the
# ``.j2`` suffix does NOT match select_autoescape's default extension list —
# manifest-controlled strings (display names, notes, parameters) must never
# reach the page unescaped. The one intentional raw-markup spot (inlined
# figure SVG) uses an explicit ``|safe``.
_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=True)
_env.filters["compact_json"] = lambda d: json.dumps(
    d, sort_keys=True, ensure_ascii=False)


def _canonical(bundle):
    """Round-trip an artifact through canonical JSON before rendering.

    Dict key order differs between a freshly built bundle (insertion order)
    and one loaded from the canonical file (sorted). Rendering from the
    canonical form makes the first render and any ``sieve report`` re-render
    byte-identical, so re-rendering never trips the artifact-integrity layer.
    """
    from sieve.core.serialization import canonical_bytes, to_jsonable

    return type(bundle).model_validate(
        json.loads(canonical_bytes(to_jsonable(bundle))))


def render_report(out_path: str | Path, bundle: EvidenceBundle,
                  baseline_context: dict[str, list[str]]) -> Path:
    bundle = _canonical(bundle)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tpl = _env.get_template("report.html.j2")
    not_tested = [d for d in bundle.profile.dimensions
                  if d.status is Status.NOT_TESTED]
    insufficient = [d for d in bundle.profile.dimensions
                    if d.status is Status.INSUFFICIENT]
    out_path.write_text(tpl.render(
        b=bundle, product=PRODUCT_NAME, footer=REPORT_FOOTER,
        baseline_context=baseline_context,
        not_tested=not_tested, insufficient=insufficient,
        Status=Status))
    return out_path


def render_inspect_report(out_path: str | Path, bundle,
                          run_dir: str | Path) -> Path:
    """Render the exploratory inspection report (self-contained HTML).

    Figure SVGs are inlined so the report stays readable if the directory
    is moved or the report file is shared alone; the standalone SVG files
    remain sealed artifacts in ``figures/``.
    """
    bundle = _canonical(bundle)
    out_path = Path(out_path)
    run_dir = Path(run_dir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    svgs: dict[str, str] = {}
    for f in bundle.figures:
        if f.artifact_path:
            p = run_dir / f.artifact_path
            if p.exists():
                svgs[f.figure_id] = p.read_text()

    metric_ids = []
    per_metric: dict[str, dict] = {}
    for ob in bundle.metric_observations:
        mid = ob.metric_ref.partition("@")[0]
        if mid not in per_metric:
            per_metric[mid] = {}
            metric_ids.append(mid)
        per_metric[mid][ob.run_id] = ob
    metric_table = [(mid, per_metric[mid]) for mid in metric_ids]

    metric_stats = []
    for mid in metric_ids:
        vals = sorted(ob.value for ob in per_metric[mid].values()
                      if ob.value is not None)
        if not vals:
            metric_stats.append((mid, None))
            continue

        def q(p, vs=vals):
            i = (len(vs) - 1) * p
            lo, hi = int(i), min(int(i) + 1, len(vs) - 1)
            return vs[lo] + (vs[hi] - vs[lo]) * (i - lo)

        metric_stats.append((mid, {
            "min": vals[0], "q25": q(0.25), "median": q(0.5),
            "q75": q(0.75), "max": vals[-1], "n": len(vals)}))

    tpl = _env.get_template("inspect.html.j2")
    out_path.write_text(tpl.render(
        b=bundle, product=PRODUCT_NAME, footer=REPORT_FOOTER,
        svgs=svgs, metric_table=metric_table, metric_stats=metric_stats))
    return out_path


def render_compare(out_path: str | Path, cmp_bundle,
                   link_a: str | None = None,
                   link_b: str | None = None) -> Path:
    cmp_bundle = _canonical(cmp_bundle)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tpl = _env.get_template("compare.html.j2")
    out_path.write_text(tpl.render(
        c=cmp_bundle, product=PRODUCT_NAME, footer=REPORT_FOOTER,
        link_a=link_a, link_b=link_b))
    return out_path
