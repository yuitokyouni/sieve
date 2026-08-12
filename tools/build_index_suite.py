"""Build a single-index confirmatory suite from daily closes.

Derives the same reference structure financial-daily@1.0.0 ships, for ONE
index: log returns (unit-sd scaled), non-overlapping-stride windows of
1000 observations every 250, per-window values of the 8 registered
metrics, and 1450-day calendar blocks for the design-preserving block
bootstrap. Raw closes are NOT copied into the suite — only derived window
statistics plus a source hash (sha256 of the timestamp,close CSV bytes)
travel with it.

Honesty notes, written into the suite manifest:

- the alpha=0.01 decision line inherits financial-daily's calibration,
  which was measured on the SIX-index reference design; it has NOT been
  re-measured for a single index (fewer windows, one market), so the suite
  is versioned 0.1.0 and marked experimental;
- no baseline distributions are shipped (baseline blindness context is
  absent from reports for these suites).

Usage:
    python tools/fetch_index_data.py ^N225 nikkei
    python tools/build_index_suite.py nikkei "Nikkei 225" nikkei-daily
    python tools/build_index_suite.py spx "S&P 500" spx-daily
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sieve.metrics import registry as metric_registry  # noqa: E402

WINDOW = 1000
STRIDE = 250
BLOCK_DAYS = 1450
METRICS = ["excess_kurtosis", "hill_left", "hill_right", "acf_abs_1",
           "acf_abs_20", "leverage", "variance_ratio_20", "drift"]
VERSION = "0.1.0"


def build(key: str, display: str, suite_id: str) -> Path:
    src = ROOT / "data" / "index_cache" / f"{key}_daily.csv"
    if not src.exists():
        sys.exit(f"{src} not found; run tools/fetch_index_data.py first")
    source_hash = hashlib.sha256(src.read_bytes()).hexdigest()

    dates: list[dt.date] = []
    closes: list[float] = []
    with open(src) as f:
        next(f)
        for line in f:
            d, c = line.strip().split(",")
            dates.append(dt.date.fromisoformat(d))
            closes.append(float(c))
    px = np.asarray(closes)
    r = np.diff(np.log(px))                 # log-diff of non-null closes
    r = r / r.std()                         # unit-sd scaled (whole series)
    rd = dates[1:]                          # date of each return

    n_win = (len(r) - WINDOW) // STRIDE + 1
    if n_win < 10:
        sys.exit(f"only {n_win} windows from {len(r)} returns; need >= 10")
    windows, values = [], {m: [] for m in METRICS}
    first_start = rd[0]
    for i in range(n_win):
        a = i * STRIDE
        w = r[a:a + WINDOW]
        start, end = rd[a], rd[a + WINDOW - 1]
        block = (start - first_start).days // BLOCK_DAYS
        windows.append({"index": key, "start": start.isoformat(),
                        "end": end.isoformat(), "block": int(block)})
        for m in METRICS:
            values[m].append(metric_registry.compute(f"{m}@1", w))

    out = ROOT / "suites" / suite_id / VERSION
    out.mkdir(parents=True, exist_ok=True)
    ref = {
        "built_by": "tools/build_index_suite.py",
        "window": WINDOW, "stride": STRIDE, "block_width_days": BLOCK_DAYS,
        "metrics": METRICS, "windows": windows, "values": values,
        "sources": {key: {
            "sha256_timestamp_price_csv": source_hash,
            "provider": "Yahoo Finance chart API (^ symbol daily closes)",
            "span": f"{rd[0].isoformat()}..{rd[-1].isoformat()}",
            "transform": "log-diff of non-null closes, unit-sd scaled "
                         "(whole series)"}},
    }
    (out / "reference_stats.json").write_text(
        json.dumps(ref, indent=1, sort_keys=True) + "\n")
    (out / "baseline_stats.json").write_text(
        json.dumps({"values": {}}, indent=1) + "\n")

    (out / "suite.yaml").write_text(f"""\
# {suite_id}@{VERSION} — descriptive validation of daily {display} returns.
# EXPERIMENTAL single-index suite built by tools/build_index_suite.py.
# Immutable once published: suite_hash covers this file + shipped data.

suite_id: {suite_id}
version: {VERSION}

claim_types:
  - descriptive

reference:
  dataset: >-
    {display} daily log returns, unit-sd scaled; {n_win} derived windows of
    {WINDOW} observations (stride {STRIDE}) spanning
    {windows[0]["start"]} - {windows[-1]["end"]}, with {BLOCK_DAYS}-day
    calendar blocks.
  window_length: {WINDOW}
  stride: {STRIDE}
  n_windows: {n_win}
  calendar_block_days: {BLOCK_DAYS}
  provenance: >-
    Shipped as frozen derived window statistics (reference_stats.json)
    built from Yahoo Finance daily closes. Raw closes are not
    redistributed; the sha256 of the fetched timestamp,close CSV is
    recorded so anyone re-fetching the same span can verify they hold the
    same source.

metrics:
  - excess_kurtosis@1
  - hill_left@1
  - hill_right@1
  - acf_abs_1@1
  - acf_abs_20@1
  - leverage@1
  - variance_ratio_20@1
  - drift@1

baselines: []

inference:
  method: block_bootstrap_calendar
  alpha: 0.01
  alpha_provenance: >-
    INHERITED, NOT RE-MEASURED: the nominal 0.01 line was calibrated on
    financial-daily@1.0.0's six-index reference design (measured true size
    3-5%). This single-index suite has fewer windows and one market; its
    true size has not been measured, so treat decisions as experimental
    until a calibration run is recorded.
  n_draw: 2000
  multiple_testing: holm
""")

    claims = out / "claims"
    claims.mkdir(exist_ok=True)
    (claims / "descriptive-market-dynamics.yaml").write_text(f"""\
claim_id: descriptive-market-dynamics
version: "0.1"
statement: >-
  Simulated daily returns reproduce the descriptive dynamics of {display}
  daily returns: heavy-tailed marginals, power-law tail weight, volatility
  clustering and its persistence, sign-to-volatility asymmetry (leverage),
  near-unit variance ratios, and empirically small drift.
use_case: >-
  Descriptive realism of an unconditional daily return stream against a
  SINGLE market ({display}). NOT forecasting, NOT derivative pricing, NOT
  policy counterfactuals. Experimental suite: the decision line's true
  size is inherited from the six-index design and not re-measured.
scope:
  frequency: daily
  window_length: {WINDOW}
  markets: {display}
required_dimensions:
  - marginal_distribution
  - tail_behavior
  - volatility_dynamics
  - leverage_asymmetry
optional_dimensions:
  - return_dependence
  - drift_nonstationarity
decision_policy: >-
  Per-dimension statuses only. A FAIL on a required dimension is reported
  as a finding with author questions; nothing aggregates across
  dimensions. No baseline-blindness context is available in this suite
  version (no baselines shipped).
""")
    print(f"built {suite_id}@{VERSION}: {n_win} windows, "
          f"blocks 0..{windows[-1]['block']}, source {source_hash[:16]}…")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit("usage: build_index_suite.py KEY DISPLAY SUITE_ID\n"
                 "  e.g.: build_index_suite.py nikkei 'Nikkei 225' "
                 "nikkei-daily")
    build(sys.argv[1], sys.argv[2], sys.argv[3])
