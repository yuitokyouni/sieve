"""Model-update regression (`sieve compare`): the change-approval gate.

Uses the committed model_update example story: v2.3.0 (calibrated GARCH-t)
vs v2.4.0 (bad refit: persistence collapsed, nu clipped). Runs are produced
once per module; comparisons must localize the regression to clustering and
tail weight, leave leverage/dependence/drift alone, and refuse unverifiable
or cross-suite inputs.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from sieve.evaluation.compare import CompareInputError, load_compare, run_compare
from sieve.evaluation.runner import run_test

PRODUCT = Path(__file__).resolve().parents[2]
EXAMPLE = PRODUCT / "examples" / "model_update"
SUITE, CLAIM = "financial-daily@1.0", "descriptive-market-dynamics"


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    if not (EXAMPLE / "v1" / "returns.csv").exists():
        subprocess.run([sys.executable, str(EXAMPLE / "generate.py")],
                       check=True)
    root = tmp_path_factory.mktemp("mu")
    ra = run_test(EXAMPLE / "v1", SUITE, CLAIM, out_root=root / "a")
    rb = run_test(EXAMPLE / "v2", SUITE, CLAIM, out_root=root / "b")
    return ra, rb


@pytest.fixture(scope="module")
def compared(runs, tmp_path_factory):
    ra, rb = runs
    return run_compare(ra, rb, out_dir=tmp_path_factory.mktemp("cmp") / "c")


def test_outputs_and_seal(compared):
    assert (compared / "compare.json").exists()
    assert (compared / "compare.sha256").exists()
    assert (compared / "report" / "index.html").exists()
    c = load_compare(compared)
    assert c.compare_hash and len(c.compare_hash) == 64
    html = (compared / "report" / "index.html").read_text()
    assert c.compare_hash[:16] in html


def test_regression_localized(compared):
    c = load_compare(compared)
    v = {r.metric_ref.partition("@")[0]: r.verdict for r in c.results}
    # the bad refit hits clustering and left-tail/kurtosis…
    for mid in ("excess_kurtosis", "acf_abs_1", "acf_abs_20", "hill_left"):
        assert v[mid] == "CHANGED", (mid, v)
    # …and does not touch what it should not touch
    for mid in ("leverage", "variance_ratio_20", "drift"):
        assert v[mid] == "NOT_SEPARATED", (mid, v)


def test_compare_sees_what_reference_gate_misses(compared):
    """acf_abs_1: both versions PASS vs reference (limited power against ~6
    calendar blocks) yet the direct A-vs-B test detects the halved
    clustering — the reason the change-approval gate exists."""
    c = load_compare(compared)
    row = {r.metric_ref.partition("@")[0]: r for r in c.results}["acf_abs_1"]
    assert row.verdict == "CHANGED"
    assert row.status_a_vs_reference.value == "PASS"
    assert row.status_b_vs_reference.value == "PASS"


def test_self_compare_is_not_separated(runs, tmp_path):
    ra, _ = runs
    out = run_compare(ra, ra, out_dir=tmp_path / "self")
    c = load_compare(out)
    assert all(r.verdict == "NOT_SEPARATED" for r in c.results)
    assert all(r.ks_ab == 0.0 for r in c.results)


def test_deterministic_compare(runs, tmp_path):
    ra, rb = runs
    c1 = load_compare(run_compare(ra, rb, out_dir=tmp_path / "c1"))
    c2 = load_compare(run_compare(ra, rb, out_dir=tmp_path / "c2"))
    assert c1.compare_hash == c2.compare_hash
    assert c1.compare_id != c2.compare_id


def test_refuses_tampered_run(runs, tmp_path):
    ra, rb = runs
    bad = tmp_path / "bad"
    shutil.copytree(rb, bad)
    p = bad / "results.json"
    body = json.loads(p.read_text())
    body[0]["p_value"] = 0.5
    p.write_text(json.dumps(body))
    with pytest.raises(CompareInputError, match="verification"):
        run_compare(ra, bad, out_dir=tmp_path / "out")


def test_refuses_suite_mismatch(runs, tmp_path):
    ra, rb = runs
    other = tmp_path / "othersuite"
    shutil.copytree(rb, other)
    bpath = other / "evidence_bundle.json"
    body = json.loads(bpath.read_text())
    body["suite"]["suite_hash"] = "0" * 64
    # keep the copy internally consistent so only the suite check fires
    from sieve.core.hashing import sha256_bytes, sha256_file
    from sieve.core.models import EvidenceBundle
    from sieve.core.serialization import canonical_bytes, hashable_bytes

    b = EvidenceBundle.model_validate(body)
    b.bundle_hash = sha256_bytes(hashable_bytes(b))
    new = canonical_bytes(json.loads(b.model_dump_json()))
    bpath.write_bytes(new)
    (other / "bundle.sha256").write_text(
        f"{sha256_file(bpath)}  evidence_bundle.json\n")
    with pytest.raises(CompareInputError, match="suite_hash"):
        run_compare(ra, other, out_dir=tmp_path / "out")
