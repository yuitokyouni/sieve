"""min-lob-a: the reference minimal limit-order-book engine.

Scope: the smallest engine that still exercises everything the Evidence
Contract has to say about an event log — two-sided fills, cancels, an
exogenous shock, a terminal book snapshot, and Level-I state at every event.
Integer prices and integer quantities: no float enters the state, so the
`exact` canary's digest cannot drift on a numerics upgrade. The only floats
in the whole fixture are two derived statistics, and they exist to give the
`semantic` canary a tolerance with a real basis.

Emits the CORE field set fixed by the 12-week calendar §2.1 — time, event
type, actor role, side, price, quantity, order/trade ID, cause ID — plus the
optional `event_id` (this log's declared total order key), the optional
`actor_id`, and the profile-required `l1`.

`l1` is stamped per ATOMIC OPERATION: every event a single operation produces
carries the state the book settled into. That is what keeps a marketable
order from ever being recorded in its momentarily crossed state.

Book representation here: price -> FIFO queue of resting orders. `min_lob_b`
implements the same behaviour over a flat list.
"""

from __future__ import annotations

from typing import Any

from _engine.rng import ALGORITHM as RNG_ALGORITHM
from _engine.rng import VERSION as RNG_VERSION
from _engine.rng import SplitMix64

ENGINE_ID = "min-lob-a"
ENGINE_VERSION = "2.0.0"

BUY, SELL = "buy", "sell"
MECHANISM_ACTOR = "__mechanism__"

CORE_FIELDS = ("t", "event_type", "actor_role", "side", "price", "quantity",
               "order_id", "trade_id", "cause_id")


class _Log:
    """Buffers one atomic operation, then stamps every event in it with the
    settled Level-I state."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._pending: list[dict[str, Any]] = []
        self._next_id = 1
        self._t: int | None = None
        self._seq = 0

    def emit(self, t, event_type, actor_role, side, price, quantity, *,
             order_id=None, trade_id=None, cause_id=None, actor_id=None,
             ext=None) -> int:
        if t != self._t:
            self._t, self._seq = t, 0
        else:
            self._seq += 1
        event = {
            # core, calendar §2.1
            "t": t,
            "event_type": event_type,
            "actor_role": actor_role,
            "side": side,
            "price": price,
            "quantity": quantity,
            "order_id": order_id,
            "trade_id": trade_id,
            "cause_id": cause_id,
            # not core: declared total order key, secondary key, actor identity
            "event_id": self._next_id,
            "seq": self._seq,
            "actor_id": actor_id,
        }
        if ext:
            event["ext"] = ext
        self._pending.append(event)
        self._next_id += 1
        return event["event_id"]

    def settle(self, l1: dict[str, Any]) -> None:
        for event in self._pending:
            event["l1"] = dict(l1)
            self.events.append(event)
        self._pending = []


class MinLobA:
    def __init__(self, config: dict[str, Any]) -> None:
        self.cfg = config
        self.rng = SplitMix64(config["seed"])
        # price -> list of [order_id, remaining_qty, arrival, agent]
        self.book: dict[str, dict[int, list]] = {BUY: {}, SELL: {}}
        self.log = _Log()
        self._order_seq = 0     # arrival counter, advanced when an order rests
        self._submit_seq = 0    # order-id counter, advanced on every submit
        self._trade_seq = 0

    # ---- book primitives -------------------------------------------------
    def _best(self, side: str):
        levels = [p for p, q in self.book[side].items() if q]
        if not levels:
            return None
        return max(levels) if side == BUY else min(levels)

    def _size_at(self, side: str, price) -> int | None:
        if price is None:
            return None
        return sum(o[1] for o in self.book[side][price]) or None

    def l1(self) -> dict[str, Any]:
        bid, ask = self._best(BUY), self._best(SELL)
        return {"bid_price": bid, "bid_size": self._size_at(BUY, bid),
                "ask_price": ask, "ask_size": self._size_at(SELL, ask)}

    def _mid(self) -> int:
        bid, ask = self._best(BUY), self._best(SELL)
        if bid is not None and ask is not None:
            return (bid + ask) // 2
        if bid is not None:
            return bid + 1
        if ask is not None:
            return ask - 1
        return self.cfg["initial_mid"]

    def _rest(self, side, price, qty, agent, order_id):
        self.book[side].setdefault(price, []).append(
            [order_id, qty, self._order_seq, agent])
        self._order_seq += 1

    def _resting_of(self, agent) -> list:
        """Agent's resting orders in a canonical order (arrival ascending).
        Canonical, not incidental: min_lob_b stores orders differently and must
        pick the same order for the same draw."""
        out = []
        for side in (BUY, SELL):
            for price, queue in self.book[side].items():
                for o in queue:
                    if o[3] == agent and o[1] > 0:
                        out.append((o[2], side, price, o))
        out.sort(key=lambda r: r[0])
        return out

    # ---- matching --------------------------------------------------------
    def _match(self, t, taker_side, limit_price, qty, taker_order_id,
               actor_id, actor_role, cause_id) -> int:
        other = SELL if taker_side == BUY else BUY
        while qty > 0:
            best = self._best(other)
            if best is None:
                break
            if limit_price is not None:
                if taker_side == BUY and best > limit_price:
                    break
                if taker_side == SELL and best < limit_price:
                    break
            queue = self.book[other][best]
            resting = next((o for o in queue if o[1] > 0), None)
            if resting is None:
                del self.book[other][best]
                continue
            traded = min(qty, resting[1])
            resting[1] -= traded
            qty -= traded
            if resting[1] == 0:
                queue.remove(resting)
                if not queue:
                    del self.book[other][best]
            trade_id = f"trade-{self._trade_seq}"
            self._trade_seq += 1
            # two legs, one per side, sharing t, trade_id and cause_id. This
            # engine emits the buy leg first; min_lob_b emits the sell leg
            # first. Nothing in the contract fixes leg order — which is why the
            # cross-engine assertion is "the two sides agree in quantity", not
            # "the two logs are equal".
            for leg_side in (BUY, SELL):
                if leg_side == taker_side:
                    leg_actor, leg_role = actor_id, actor_role
                    leg_order = taker_order_id
                else:
                    leg_actor, leg_role = resting[3], "endogenous_agent"
                    leg_order = resting[0]
                self.log.emit(t, "order_fill", leg_role, leg_side, best,
                              traded, order_id=leg_order, trade_id=trade_id,
                              cause_id=cause_id, actor_id=leg_actor)
        return qty

    # ---- run -------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        cfg = self.cfg
        for t in range(1, cfg["n_steps"] + 1):
            for agent_index in range(cfg["n_agents"]):
                self._agent_turn(t, f"a{agent_index}")
            if t == cfg["shock"]["t"]:
                self._shock(t)
        self._snapshot(cfg["n_steps"] + 1)
        return self._document()

    def _agent_turn(self, t, agent) -> None:
        cfg = self.cfg
        wants_cancel = (self.rng.below(cfg["cancel_denominator"])
                        < cfg["cancel_numerator"])
        resting = self._resting_of(agent) if wants_cancel else []
        if wants_cancel and resting:
            _, side, price, order = resting[self.rng.below(len(resting))]
            qty = order[1]
            order[1] = 0
            self.book[side][price].remove(order)
            if not self.book[side][price]:
                del self.book[side][price]
            self.log.emit(t, "order_cancel", "endogenous_agent", side, price,
                          qty, order_id=order[0], actor_id=agent)
            self.log.settle(self.l1())
            return
        side = BUY if self.rng.below(2) == 0 else SELL
        offset = self.rng.below(cfg["max_offset"] + 1)
        qty = 1 + self.rng.below(cfg["max_qty"])
        mid = self._mid()
        price = mid - offset if side == BUY else mid + offset
        order_id = f"order-{self._submit_seq}"
        self._submit_seq += 1
        submit_id = self.log.emit(
            t, "order_submit", "endogenous_agent", side, price, qty,
            order_id=order_id, actor_id=agent,
            ext={"min_lob_a.mid_reference": mid})
        remainder = self._match(t, side, price, qty, order_id, agent,
                                "endogenous_agent", submit_id)
        if remainder:
            self._rest(side, price, remainder, agent, order_id)
        self.log.settle(self.l1())

    def _shock(self, t) -> None:
        """Exogenous, harness-injected market order. `price` is null: an
        unpriced order. `actor_role` is exogenous_harness — without that value
        this event is indistinguishable from an agent's (gap G2)."""
        s = self.cfg["shock"]
        submit_id = self.log.emit(
            t, "order_submit", "exogenous_harness", s["side"], None,
            s["quantity"], order_id="order-shock", actor_id=s["actor_id"],
            ext={"min_lob_a.protocol": s["type"]})
        remainder = self._match(t, s["side"], None, s["quantity"],
                                "order-shock", s["actor_id"],
                                "exogenous_harness", submit_id)
        if remainder:
            # unfilled remainder of a market order leaves the system; recorded,
            # not dropped, or the conservation identity would not close.
            self.log.emit(t, "order_expire", "exogenous_harness", s["side"],
                          self.cfg["initial_mid"], remainder,
                          order_id="order-shock", cause_id=submit_id,
                          actor_id=s["actor_id"])
        self.log.settle(self.l1())

    def _snapshot(self, t) -> None:
        """Terminal resting depth, one event per (side, price) level.

        Uses only core fields — no new field, no ext — and is what makes
        non-crossing assertable and the aggregate conservation identity close
        even for a consumer that ignores order_id. Buy levels descending, then
        sell levels ascending."""
        settled = self.l1()
        for side, reverse in ((BUY, True), (SELL, False)):
            for price in sorted(self.book[side], reverse=reverse):
                qty = sum(o[1] for o in self.book[side][price])
                if qty:
                    self.log.emit(t, "book_level", "market_mechanism", side,
                                  price, qty, actor_id=MECHANISM_ACTOR)
        self.log.settle(settled)

    def _document(self) -> dict[str, Any]:
        cfg = self.cfg
        return {
            "schema_version": "1.1.0",
            "log_id": f"{ENGINE_ID}-{cfg['seed']}",
            "engine": {"engine_id": ENGINE_ID, "engine_version": ENGINE_VERSION},
            "time_unit": "step",
            "time_origin": "t=1 is the first agent round; t=n_steps+1 carries "
                           "the terminal book snapshot only",
            "price_unit": {"kind": "tick", "tick_size": cfg["tick_size"]},
            "quantity_unit": {"kind": "lot", "lot_size": 1},
            "ordering": {"total_order_key": "event_id",
                         "t_unique_monotonic": False,
                         "causality": "complete"},
            "instruments": [cfg["instrument"]],
            "l1_availability": "inline",
            "events": self.log.events,
        }


def rng_identity() -> dict[str, str]:
    return {"rng_algorithm": RNG_ALGORITHM, "rng_version": RNG_VERSION}
