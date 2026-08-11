"""Generate the abm_ensemble example: a minimal mood-herding ABM, 6 seeds.

Mechanism (deliberately small, honestly agent-based):

- the market's crowd of N agents is either CALM or EXCITED (a shared mood);
  in the calm mood few agents trade each step, in the excited mood many do;
- the mood is persistent (herding: agents keep trading while others do) and
  turns excited more easily after a *negative* return (a leverage-style
  asymmetry in crowd behavior);
- each active agent buys or sells one unit at random; the net order flow
  moves the log price; volume is the number of active agents.

What this buys the example: volatility clustering and heavy tails from the
persistent activity mixture, near-unit variance ratios from iid order-flow
signs, a volume-|return| relation because both are driven by activity, and
a small negative leverage kernel from the asymmetric mood trigger. The
model exists to demonstrate the research workflow on multi-seed, price+
volume output — it claims no realism beyond that.

Regenerate:  python examples/abm_ensemble/generate.py
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

N_AGENTS = 200
N_STEPS = 3500            # rows written per run; manifest burn-in drops 500
SEEDS = (11, 12, 13, 14, 15, 16)
A_CALM = 0.02             # fraction of agents trading per step, calm mood
A_EXCITED = 0.12          # fraction trading per step, excited mood
P_CALM_TO_EXC = 0.006     # baseline chance the mood turns excited
P_EXC_TO_CALM = 0.02      # chance the excitement dies down
LEV_BIAS = 25.0           # negative returns raise the excitement trigger
LEV_SCALE = 0.01          # return scale for the trigger amplification
LAMBDA = 0.5              # price impact of net order flow


def simulate(seed: int) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    excited = False
    log_p = 0.0
    r = 0.0
    prices = np.empty(N_STEPS)
    volumes = np.empty(N_STEPS, dtype=np.int64)
    for t in range(N_STEPS):
        if excited:
            if rng.random() < P_EXC_TO_CALM:
                excited = False
        else:
            p = P_CALM_TO_EXC * (1 + LEV_BIAS * max(-r, 0.0) / LEV_SCALE)
            if rng.random() < min(p, 0.5):
                excited = True
        a = A_EXCITED if excited else A_CALM
        n_active = max(4, rng.binomial(N_AGENTS, a))
        flow = int(rng.choice([-1, 1], n_active).sum())
        r = LAMBDA * flow / N_AGENTS
        log_p += r
        prices[t] = np.exp(log_p)
        volumes[t] = n_active
    return prices, volumes


def main() -> None:
    root = Path(__file__).parent
    runs = root / "runs"
    runs.mkdir(exist_ok=True)
    for seed in SEEDS:
        prices, volumes = simulate(seed)
        lines = ["step,price,volume"]
        lines += [f"{t},{p:.10g},{v}"
                  for t, (p, v) in enumerate(zip(prices, volumes))]
        (runs / f"seed-{seed:03d}.csv").write_text("\n".join(lines) + "\n")
        print(f"seed {seed}: {len(prices)} steps")


if __name__ == "__main__":
    main()
