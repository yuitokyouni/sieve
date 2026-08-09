"""Regenerate the model-update example deterministically.

The story: a market scenario generator is "recalibrated" on a shortened
fit window and ships as v2.4.0 with two silent consequences: volatility
persistence collapses (beta 0.875 -> 0.80, alpha+beta 0.993 -> 0.918) and
the Student-t degrees of freedom hit the fitter's clip bound (nu 6.47 ->
30). This is the class of regression a change-approval gate exists to
catch:

  sieve test examples/model_update/v1 --suite financial-daily@1.0 \
        --claim descriptive-market-dynamics --out /tmp/mu
  sieve test examples/model_update/v2 --suite financial-daily@1.0 \
        --claim descriptive-market-dynamics --out /tmp/mu
  sieve compare /tmp/mu/<run-v1> /tmp/mu/<run-v2>

Expected: clustering and tail-weight metrics come back CHANGED (with B
moving away from the reference where the reference gate has power), while
leverage / variance-ratio / drift stay NOT_SEPARATED. A recorded negative:
the nu clip ALONE (beta unchanged) is nearly invisible to unconditional
window statistics at this persistence — both fourth-moment conditions
diverge either way — which is a power fact this example's first draft
found the hard way.

Run from anywhere:  python3 examples/model_update/generate.py
"""

import datetime as dt
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
PRODUCT = HERE.parents[1]
sys.path.insert(0, str(PRODUCT / "src"))

from sieve.baselines.garch import generate_t  # noqa: E402

N = 15_000                       # 15 non-overlapping 1000-day windows
OMEGA, ALPHA, BETA = 0.011039650497380534, 0.11756950878547939, 0.8751463025418191
V1 = {"garch_t": [OMEGA, ALPHA, BETA, 6.466697865253001], "seed": 11}
V2 = {"garch_t": [OMEGA, ALPHA, 0.80, 30.0], "seed": 12}


def write_csv(dirname: str, params: dict) -> None:
    rng = np.random.default_rng(params["seed"])
    r = generate_t(N, rng, params)
    day = dt.date(2000, 1, 3)
    lines = ["timestamp,return"]
    for x in r:
        while day.weekday() >= 5:
            day += dt.timedelta(days=1)
        lines.append(f"{day.isoformat()},{float(x)!r}")
        day += dt.timedelta(days=1)
    out = HERE / dirname / "returns.csv"
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}: {N} returns, seed {params['seed']}, "
          f"nu={params['garch_t'][3]}")


write_csv("v1", V1)
write_csv("v2", V2)
