"""stats_vector: an ordered, versioned summary of an event log.

Three properties matter and are enforced here rather than assumed:

1. It is computed from the COMMON SURFACE ONLY. `ext.*` is never read — a
   cross-engine comparison that touched ext would be comparing engine
   internals while claiming to compare behaviour.
2. Element identity and ORDER are fixed by `spec/stats_vector_spec.v1.json`.
   `values` is positional; the spec is loaded and the length is checked, so a
   silently reordered vector cannot be hashed as if it were the old one.
3. Every element declares a dtype and a decimal `scale`. Floats are quantized
   (half-to-even) before they enter either the vector or its digest.

`variance_method` exists to make one specific difference visible: `two_pass`
computes the sample variance in two passes, `naive` from the sum of squares.
They differ in the last few digits by catastrophic cancellation on prices
around 1000. That difference is the reason the semantic canary's tolerance on
that element carries basis "numerical" with a stated magnitude, rather than a
number someone liked the look of.
"""

from __future__ import annotations

import json
import os
from typing import Any

from _engine.canonical import quantize

SPEC_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "spec", "stats_vector_spec.v1.json")


def load_spec(path: str = SPEC_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _sum_qty(events, event_type, side) -> int:
    return sum(e["quantity"] for e in events
               if e["event_type"] == event_type and e["side"] == side)


def _count(events, event_type) -> int:
    return sum(1 for e in events if e["event_type"] == event_type)


def _variance(values: list[float], method: str) -> float | None:
    n = len(values)
    if n < 2:
        return None
    if method == "two_pass":
        mean = sum(values) / n
        return sum((v - mean) ** 2 for v in values) / (n - 1)
    if method == "naive":
        s1 = sum(values)
        s2 = sum(v * v for v in values)
        return (s2 - s1 * s1 / n) / (n - 1)
    raise ValueError(f"unknown variance method: {method}")


def compute(document: dict[str, Any], *, variance_method: str = "two_pass",
            spec: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = spec or load_spec()
    events = document["events"]

    snapshot_t = max((e["t"] for e in events if e["event_type"] == "book_level"),
                     default=None)
    levels = [e for e in events
              if e["event_type"] == "book_level" and e["t"] == snapshot_t]
    bid_levels = [e["price"] for e in levels if e["side"] == "buy"]
    ask_levels = [e["price"] for e in levels if e["side"] == "sell"]
    best_bid = max(bid_levels) if bid_levels else None
    best_ask = min(ask_levels) if ask_levels else None

    trade_prices = [float(e["price"]) for e in events
                    if e["event_type"] == "order_fill" and e["side"] == "buy"]
    mean = sum(trade_prices) / len(trade_prices) if trade_prices else None

    raw: dict[str, Any] = {
        "n_events_total": len(events),
        "n_order_submit": _count(events, "order_submit"),
        "n_order_cancel": _count(events, "order_cancel"),
        "n_order_fill": _count(events, "order_fill"),
        "n_order_expire": _count(events, "order_expire"),
        "n_book_level": _count(events, "book_level"),
        "n_trades": _count(events, "order_fill") // 2,
        "submitted_quantity_buy": _sum_qty(events, "order_submit", "buy"),
        "submitted_quantity_sell": _sum_qty(events, "order_submit", "sell"),
        "filled_quantity_buy": _sum_qty(events, "order_fill", "buy"),
        "filled_quantity_sell": _sum_qty(events, "order_fill", "sell"),
        "cancelled_quantity_buy": _sum_qty(events, "order_cancel", "buy"),
        "cancelled_quantity_sell": _sum_qty(events, "order_cancel", "sell"),
        "expired_quantity_buy": _sum_qty(events, "order_expire", "buy"),
        "expired_quantity_sell": _sum_qty(events, "order_expire", "sell"),
        "terminal_resting_quantity_buy": _sum_qty(events, "book_level", "buy"),
        "terminal_resting_quantity_sell": _sum_qty(events, "book_level", "sell"),
        "terminal_best_bid": best_bid,
        "terminal_best_ask": best_ask,
        "terminal_spread": (None if best_bid is None or best_ask is None
                            else best_ask - best_bid),
        "trade_price_mean": mean,
        "trade_price_variance": _variance(trade_prices, variance_method),
    }

    values = []
    for element in spec["elements"]:
        name = element["name"]
        if name not in raw:
            raise KeyError(f"spec element not computed: {name}")
        values.append(quantize(raw[name], element["scale"]))
    return {"spec_id": spec["spec_id"], "spec_version": spec["spec_version"],
            "values": values, "raw": raw}
