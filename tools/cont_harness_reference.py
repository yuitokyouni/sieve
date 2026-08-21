#!/usr/bin/env python3
"""Reference implementation of the Cont-type analysis harness I/O.

This exists to make `docs/contract/cont_analysis_io.md` executable rather than
aspirational: it consumes a conforming EventLog plus a typed harness-parameter
block, and emits the output document the contract describes. It fixes the I/O
SHAPE for the 2026-08-22 freeze. It fixes no threshold and no acceptance band
— those are Week 3 preregistration material and are deliberately absent.

Estimator definitions follow Cont, Kukanov and Stoikov (2014), "The price
impact of order book events", Journal of Financial Econometrics 12(1). The
formula is transcribed in the contract document; the constants they report are
NOT reproduced here — they belong in the preregistration after checking the
primary source.

Standard library only.

    python3 tools/cont_harness_reference.py --out docs/contract/examples
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "fixtures", "canary"))

from _engine.canonical import canonical_bytes, quantize  # noqa: E402
from _engine.min_lob_a import MinLobA  # noqa: E402

SCALE = 9


# --------------------------------------------------------------- helpers ---
def _ols_no_intercept(x: list[float], y: list[float]) -> dict:
    """y = b*x + e. Returns b, its standard error, R^2 and n.

    Conventions, stated because a `+/-` whose definition is not stated is the
    failure this project already recorded: the reported uncertainty is a
    STANDARD ERROR (not an SD), with ddof = 1 for the one estimated parameter,
    over the stated n. R^2 is the uncentred form appropriate to a model with
    no intercept: 1 - RSS / sum(y^2).
    """
    n = len(x)
    sxx = sum(v * v for v in x)
    if n < 2 or sxx == 0:
        return {"beta": None, "standard_error": None, "r_squared": None,
                "n": n, "ddof": 1,
                "note": "not estimable: fewer than 2 points, or zero regressor "
                        "variation"}
    beta = sum(a * b for a, b in zip(x, y)) / sxx
    residuals = [b - beta * a for a, b in zip(x, y)]
    rss = sum(r * r for r in residuals)
    sigma2 = rss / (n - 1)
    syy = sum(v * v for v in y)
    return {
        "beta": quantize(beta, SCALE),
        "standard_error": quantize(math.sqrt(sigma2 / sxx), SCALE),
        "r_squared": quantize(1.0 - rss / syy, SCALE) if syy else None,
        "n": n, "ddof": 1,
        "uncertainty": "standard error of the slope; ddof = 1; n as stated",
    }


def _mid(l1: dict):
    if l1["bid_price"] is None or l1["ask_price"] is None:
        return None
    return (l1["bid_price"] + l1["ask_price"]) / 2.0


def _spread(l1: dict):
    if l1["bid_price"] is None or l1["ask_price"] is None:
        return None
    return l1["ask_price"] - l1["bid_price"]


def _summary(values: list[float]) -> dict:
    live = [v for v in values if v is not None]
    n = len(live)
    if n == 0:
        return {"n": 0, "mean": None, "sd": None, "standard_error": None,
                "min": None, "max": None}
    mean = sum(live) / n
    sd = (math.sqrt(sum((v - mean) ** 2 for v in live) / (n - 1))
          if n > 1 else None)
    return {
        "n": n,
        "mean": quantize(mean, SCALE),
        "sd": quantize(sd, SCALE),
        "standard_error": quantize(sd / math.sqrt(n), SCALE) if sd else None,
        "min": quantize(min(live), SCALE),
        "max": quantize(max(live), SCALE),
        "uncertainty": "sd is the sample SD with ddof = 1; standard_error is "
                       "sd / sqrt(n)",
    }


# ------------------------------------------------------------------ OFI ----
def order_flow_imbalance(events: list[dict]) -> dict:
    """e_n per Cont-Kukanov-Stoikov (2014), both variants.

    `all`: every consecutive pair with Level-I present on both sides.
    `non_price_changing`: pairs where BOTH the best bid price and the best ask
    price are unchanged across the event. The exclusion happens at the e_n
    aggregation stage only; Delta P is computed over every event regardless,
    so the two variants share one dependent variable.
    """
    terms, excluded_missing_l1, price_changing = [], 0, 0
    for previous, current in zip(events, events[1:]):
        a, b = previous.get("l1"), current.get("l1")
        if not a or not b or None in (a["bid_price"], a["ask_price"],
                                      b["bid_price"], b["ask_price"]):
            excluded_missing_l1 += 1
            terms.append(None)
            continue
        e = 0.0
        if b["bid_price"] >= a["bid_price"]:
            e += b["bid_size"] or 0
        if b["bid_price"] <= a["bid_price"]:
            e -= a["bid_size"] or 0
        if b["ask_price"] <= a["ask_price"]:
            e -= b["ask_size"] or 0
        if b["ask_price"] >= a["ask_price"]:
            e += a["ask_size"] or 0
        unchanged = (b["bid_price"] == a["bid_price"]
                     and b["ask_price"] == a["ask_price"])
        if not unchanged:
            price_changing += 1
        terms.append({"e": e, "non_price_changing": unchanged})
    return {"terms": terms, "excluded_missing_l1": excluded_missing_l1,
            "price_changing": price_changing}


def analyse(document: dict, parameters: dict) -> dict:
    events = sorted(document["events"], key=lambda e: e["event_id"])
    ofi = order_flow_imbalance(events)
    terms = ofi["terms"]

    interval = parameters["interval"]["size"]
    per_window = parameters["window"]["intervals"]

    intervals = []
    for start in range(0, len(terms) - interval + 1, interval):
        chunk = terms[start:start + interval]
        window_events = events[start:start + interval + 1]
        mids = [_mid(e["l1"]) for e in window_events if e.get("l1")]
        mids = [m for m in mids if m is not None]
        if len(mids) < 2:
            continue
        depths = []
        for e in window_events:
            l1 = e.get("l1") or {}
            if l1.get("bid_size") is not None and l1.get("ask_size") is not None:
                depths.append((l1["bid_size"] + l1["ask_size"]) / 2.0)
        intervals.append({
            "delta_mid_ticks": mids[-1] - mids[0],
            "ofi_all": sum(c["e"] for c in chunk if c),
            "ofi_non_price_changing": sum(c["e"] for c in chunk
                                          if c and c["non_price_changing"]),
            "mean_depth": (sum(depths) / len(depths)) if depths else None,
        })

    windows = []
    for index in range(0, len(intervals) - per_window + 1, per_window):
        block = intervals[index:index + per_window]
        y = [b["delta_mid_ticks"] for b in block]
        depths = [b["mean_depth"] for b in block if b["mean_depth"] is not None]
        windows.append({
            "window_index": len(windows),
            "n_intervals": len(block),
            "mean_depth": (quantize(sum(depths) / len(depths), SCALE)
                           if depths else None),
            "primary_non_price_changing": _ols_no_intercept(
                [b["ofi_non_price_changing"] for b in block], y),
            "diagnostic_all": _ols_no_intercept(
                [b["ofi_all"] for b in block], y),
        })

    # depth-impact: log beta_i = log c - lambda log D_i + nu_i
    points = [(w["mean_depth"], w["primary_non_price_changing"]["beta"])
              for w in windows]
    usable = [(d, b) for d, b in points
              if d and b and d > 0 and b > 0]
    if len(usable) >= 2:
        log_d = [math.log(d) for d, _ in usable]
        log_b = [math.log(b) for _, b in usable]
        mean_d = sum(log_d) / len(log_d)
        mean_b = sum(log_b) / len(log_b)
        sxx = sum((v - mean_d) ** 2 for v in log_d)
        slope = (sum((a - mean_d) * (b - mean_b) for a, b in zip(log_d, log_b))
                 / sxx) if sxx else None
        if slope is None or len(usable) < 3:
            depth_impact = {"lambda": None, "standard_error": None,
                            "n": len(usable), "log_c": None,
                            "note": "not estimable: fewer than 3 usable windows, "
                                    "or zero variation in log depth"}
        else:
            intercept = mean_b - slope * mean_d
            resid = [b - (intercept + slope * a) for a, b in zip(log_d, log_b)]
            sigma2 = sum(r * r for r in resid) / (len(usable) - 2)
            depth_impact = {
                "lambda": quantize(-slope, SCALE),
                "standard_error": quantize(math.sqrt(sigma2 / sxx), SCALE),
                "log_c": quantize(intercept, SCALE),
                "n": len(usable), "ddof": 2,
                "uncertainty": "standard error of the slope; ddof = 2 "
                               "(intercept and slope); n as stated",
            }
    else:
        depth_impact = {"lambda": None, "standard_error": None,
                        "n": len(usable), "log_c": None,
                        "note": "not estimable: fewer than 2 usable windows "
                                "with positive depth and positive beta"}

    # spread / depth series and shock response
    series = [{"t": e["t"], "event_id": e["event_id"],
               "spread": _spread(e.get("l1") or {}),
               "bid_size": (e.get("l1") or {}).get("bid_size"),
               "ask_size": (e.get("l1") or {}).get("ask_size")}
              for e in events]
    shock = next((e for e in events
                  if e["actor_role"] == "exogenous_harness"
                  and e["event_type"] == "order_submit"), None)
    pre = [s["spread"] for s in series if shock and s["t"] < shock["t"]]
    baseline = _summary(pre)
    profile = []
    if shock:
        post = [s for s in series if s["event_id"] >= shock["event_id"]]
        for offset, point in enumerate(post[:parameters["shock"]["profile_events"]]):
            deviation = (None if point["spread"] is None or baseline["mean"] is None
                         else point["spread"] - baseline["mean"])
            profile.append({"events_since_shock": offset, "t": point["t"],
                            "spread": point["spread"],
                            "spread_deviation": quantize(deviation, SCALE)})

    return {
        "schema_version": "0.1.0-draft",
        "harness_id": "cont-type-lob-harness",
        "harness_version": "0.1.0",
        "source_log": {"log_id": document["log_id"], "engine": document["engine"],
                       "time_unit": document["time_unit"],
                       "n_events": len(events)},
        "parameters": parameters,
        "coverage": {
            "consecutive_pairs": len(terms),
            "excluded_missing_l1": ofi["excluded_missing_l1"],
            "price_changing_pairs": ofi["price_changing"],
            "intervals": len(intervals),
            "windows": len(windows),
            "note": "excluded_missing_l1 counts pairs dropped because one side "
                    "of the book was empty. Reported rather than silently "
                    "skipped: a coverage number that is not printed reads as "
                    "full coverage.",
        },
        "outputs": {
            "ofi_regression_by_window": windows,
            "depth_impact": depth_impact,
            "spread_and_depth_summary": {
                "spread": _summary([s["spread"] for s in series]),
                "bid_size": _summary([s["bid_size"] for s in series]),
                "ask_size": _summary([s["ask_size"] for s in series]),
            },
            "shock_response": {
                "shock_event_id": shock["event_id"] if shock else None,
                "shock_t": shock["t"] if shock else None,
                "identified_by": "actor_role == 'exogenous_harness' (gap G2)",
                "baseline_spread": baseline,
                "deviation_profile": profile,
                "recovery_time": None,
                "recovery_time_note": "NOT COMPUTED HERE BY DESIGN. Recovery "
                                      "time is the first return into a "
                                      "baseline band of +/- epsilon, and "
                                      "epsilon is a threshold. Thresholds and "
                                      "acceptance bands are Week 3 "
                                      "preregistration material; putting one "
                                      "here would preregister it by accident.",
                "half_life": None,
                "half_life_note": "Same reason: the fit needs a declared "
                                  "baseline band to define a deviation to "
                                  "halve.",
            },
        },
        "estimator_definitions": "docs/contract/cont_analysis_io.md",
    }


DEFAULT_PARAMETERS = {
    "interval": {"kind": "fixed_event_count", "size": 4,
                 "note": "an interval is a fixed number of consecutive events; "
                         "'fixed_step_count' is the other permitted kind and "
                         "means a fixed number of engine steps"},
    "window": {"intervals": 20,
               "note": "a window is a fixed number of consecutive intervals; "
                       "one OLS fit is produced per window"},
    "depth": {"definition": "mean over the window of (bid_size + ask_size) / 2 "
                            "at Level-I",
              "level": 1},
    "shock": {"protocol": "market_order", "side": "buy", "size": 5,
              "injection_time": 20, "time_unit": "step",
              "profile_events": 12},
    "sampling": {"spread_series": "every event carrying Level-I",
                 "depth_series": "every event carrying Level-I",
                 "note": "sampling is event-driven, not clock-driven; a "
                         "clock-driven rule would need an interpolation rule "
                         "that this contract does not define"},
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    config = json.load(open(os.path.join(REPO, "fixtures", "canary",
                                         "exact-lob-min", "config.json")))
    document = MinLobA(config).run()
    result = analyse(document, DEFAULT_PARAMETERS)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        with open(os.path.join(args.out, "ContHarnessInput.example.json"),
                  "wb") as fh:
            fh.write(canonical_bytes({
                "event_log_ref": "fixtures/canary/exact-lob-min (min-lob-a, "
                                 "regenerated by run_canary.py)",
                "event_log_header": {k: v for k, v in document.items()
                                     if k != "events"},
                "event_log_first_events": document["events"][:3],
                "parameters": DEFAULT_PARAMETERS,
            }))
        with open(os.path.join(args.out, "ContHarnessOutput.example.json"),
                  "wb") as fh:
            fh.write(canonical_bytes(result))
    print(json.dumps(result["outputs"]["ofi_regression_by_window"], indent=2))
    print(json.dumps(result["depth_impact"] if "depth_impact" in result
                     else result["outputs"]["depth_impact"], indent=2))
    print(json.dumps(result["coverage"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
