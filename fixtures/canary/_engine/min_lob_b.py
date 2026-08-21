"""min-lob-b: an independent implementation of the same market.

Same declared behaviour as `min_lob_a`, deliberately different internals and
different log surface:

- resting orders live in one flat list, scanned linearly, instead of a
  price -> FIFO-queue map;
- a trade's SELL leg is emitted before its BUY leg (min_lob_a emits buy first);
- the terminal snapshot walks sell levels before buy levels;
- `ext.*` keys are the engine's own and share nothing with min_lob_a's.

None of that is a behaviour difference, and none of it is visible to any
assertion the semantic canary makes — which is the point. The exact canary
would reject this engine; the semantic canary must accept it. If a future
change makes the semantic canary reject min_lob_b, the assertion set has
started depending on representation, and that is the failure the pair of
fixtures exists to catch.
"""

from __future__ import annotations

from typing import Any

from _engine.rng import ALGORITHM as RNG_ALGORITHM
from _engine.rng import VERSION as RNG_VERSION
from _engine.rng import SplitMix64

ENGINE_ID = "min-lob-b"
ENGINE_VERSION = "1.0.0"

BUY, SELL = "buy", "sell"
MECHANISM_ACTOR = "__mechanism__"


class MinLobB:
    def __init__(self, config: dict[str, Any]) -> None:
        self.cfg = config
        self.rng = SplitMix64(config["seed"])
        # flat list of dicts: {id, side, price, qty, arrival, agent}
        self.resting: list[dict[str, Any]] = []
        self.events: list[dict[str, Any]] = []
        self._next_id = 1
        self._t: int | None = None
        self._seq = 0
        self._arrival = 0

    # ---- emission --------------------------------------------------------
    def _emit(self, t, event_type, actor_id, actor_role, side, price, quantity,
              cause_event_id=None, order_id=None, ext=None) -> int:
        if t != self._t:
            self._t, self._seq = t, 0
        else:
            self._seq += 1
        event = {
            "t": t, "event_id": self._next_id, "event_type": event_type,
            "actor_id": actor_id, "actor_role": actor_role, "side": side,
            "price": price, "quantity": quantity, "seq": self._seq,
            "cause_event_id": cause_event_id, "order_id": order_id,
            "l1": self.l1(),
        }
        if ext:
            event["ext"] = ext
        self.events.append(event)
        self._next_id += 1
        return event["event_id"]

    def _emit_pre(self, *args, **kwargs) -> int:
        """Submit events carry the PRE-trade Level-I state (the state the order
        met). Every other event carries the post-event state. Same rule as
        min_lob_a; here it falls out of calling this before the match."""
        return self._emit(*args, **kwargs)

    # ---- book primitives -------------------------------------------------
    def _live(self, side=None):
        return [o for o in self.resting
                if o["qty"] > 0 and (side is None or o["side"] == side)]

    def _best(self, side):
        live = self._live(side)
        if not live:
            return None
        prices = [o["price"] for o in live]
        return max(prices) if side == BUY else min(prices)

    def l1(self) -> dict[str, Any]:
        out = {}
        for side, key in ((BUY, "bid"), (SELL, "ask")):
            best = self._best(side)
            size = sum(o["qty"] for o in self._live(side) if o["price"] == best)
            out[f"{key}_price"] = best
            out[f"{key}_size"] = size or None
        return {"bid_price": out["bid_price"], "bid_size": out["bid_size"],
                "ask_price": out["ask_price"], "ask_size": out["ask_size"]}

    def _mid(self) -> int:
        bid, ask = self._best(BUY), self._best(SELL)
        if bid is not None and ask is not None:
            return (bid + ask) // 2
        if bid is not None:
            return bid + 1
        if ask is not None:
            return ask - 1
        return self.cfg["initial_mid"]

    def _agent_orders(self, agent):
        return sorted((o for o in self._live() if o["agent"] == agent),
                      key=lambda o: o["arrival"])

    # ---- matching --------------------------------------------------------
    def _match(self, t, taker_side, limit_price, qty, actor_id, actor_role,
               cause_id) -> int:
        other = SELL if taker_side == BUY else BUY
        while qty > 0:
            candidates = self._live(other)
            if not candidates:
                break
            best = (max if other == BUY else min)(o["price"] for o in candidates)
            if limit_price is not None:
                if taker_side == BUY and best > limit_price:
                    break
                if taker_side == SELL and best < limit_price:
                    break
            at_best = sorted((o for o in candidates if o["price"] == best),
                             key=lambda o: o["arrival"])
            resting = at_best[0]
            traded = min(qty, resting["qty"])
            resting["qty"] -= traded
            qty -= traded
            # SELL leg first — the representational difference from min_lob_a.
            for leg_side in (SELL, BUY):
                if leg_side == taker_side:
                    leg_actor, leg_role, leg_order = actor_id, actor_role, None
                else:
                    leg_actor, leg_role = resting["agent"], "endogenous_agent"
                    leg_order = resting["id"]
                self._emit(t, "order_fill", leg_actor, leg_role, leg_side, best,
                           traded, cause_event_id=cause_id, order_id=leg_order)
        self.resting = [o for o in self.resting if o["qty"] > 0]
        return qty

    # ---- run -------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        cfg = self.cfg
        for t in range(1, cfg["n_steps"] + 1):
            for agent_index in range(cfg["n_agents"]):
                agent = f"a{agent_index}"
                wants_cancel = (self.rng.below(cfg["cancel_denominator"])
                                < cfg["cancel_numerator"])
                owned = self._agent_orders(agent) if wants_cancel else []
                if wants_cancel and owned:
                    order = owned[self.rng.below(len(owned))]
                    qty = order["qty"]
                    order["qty"] = 0
                    self.resting = [o for o in self.resting if o["qty"] > 0]
                    self._emit(t, "order_cancel", agent, "endogenous_agent",
                               order["side"], order["price"], qty,
                               order_id=order["id"])
                    continue
                side = BUY if self.rng.below(2) == 0 else SELL
                offset = self.rng.below(cfg["max_offset"] + 1)
                qty = 1 + self.rng.below(cfg["max_qty"])
                mid = self._mid()
                price = mid - offset if side == BUY else mid + offset
                order_id = f"ord-{self._arrival}"
                submit_id = self._emit_pre(
                    t, "order_submit", agent, "endogenous_agent", side, price,
                    qty, order_id=order_id,
                    ext={"min_lob_b.impl": "flat-list"})
                remainder = self._match(t, side, price, qty, agent,
                                        "endogenous_agent", submit_id)
                if remainder:
                    self.resting.append({"id": order_id, "side": side,
                                         "price": price, "qty": remainder,
                                         "arrival": self._arrival,
                                         "agent": agent})
                self._arrival += 1
            if t == cfg["shock"]["t"]:
                s = cfg["shock"]
                submit_id = self._emit_pre(
                    t, "order_submit", s["actor_id"], "exogenous_harness",
                    s["side"], None, s["quantity"], order_id="shock",
                    ext={"min_lob_b.injected": True})
                remainder = self._match(t, s["side"], None, s["quantity"],
                                        s["actor_id"], "exogenous_harness",
                                        submit_id)
                if remainder:
                    self._emit(t, "order_expire", s["actor_id"],
                               "exogenous_harness", s["side"],
                               cfg["initial_mid"], remainder,
                               cause_event_id=submit_id, order_id="shock")
        # terminal snapshot: sell side first, then buy side.
        t = cfg["n_steps"] + 1
        for side, reverse in ((SELL, False), (BUY, True)):
            prices = sorted({o["price"] for o in self._live(side)}, reverse=reverse)
            for price in prices:
                qty = sum(o["qty"] for o in self._live(side) if o["price"] == price)
                if qty:
                    self._emit(t, "book_level", MECHANISM_ACTOR,
                               "market_mechanism", side, price, qty)
        return self._document()

    def _document(self) -> dict[str, Any]:
        cfg = self.cfg
        return {
            "schema_version": "1.0.0",
            "log_id": f"{ENGINE_ID}-{cfg['seed']}",
            "engine": {"engine_id": ENGINE_ID, "engine_version": ENGINE_VERSION},
            "time_unit": "step",
            "time_origin": "t=1 is the first agent round; t=n_steps+1 carries "
                           "the terminal book snapshot only",
            "price_unit": {"kind": "tick", "tick_size": cfg["tick_size"]},
            "quantity_unit": {"kind": "lot", "lot_size": 1},
            "ordering": {"total_order_key": "event_id", "t_monotonic": True,
                         "tie_break": "seq", "causality": "complete"},
            "instruments": [cfg["instrument"]],
            "l1_availability": "inline",
            "events": self.events,
        }


def rng_identity() -> dict[str, str]:
    return {"rng_algorithm": RNG_ALGORITHM, "rng_version": RNG_VERSION}
