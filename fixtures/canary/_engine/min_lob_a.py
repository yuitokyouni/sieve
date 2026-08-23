"""min-lob-a: the reference minimal limit-order-book engine.

Scope: the smallest engine that still exercises everything the Evidence
Contract has to say about an event log — two-sided fills, cancels, an
exogenous shock, a terminal book snapshot, and Level-I state at every event.
Integer prices and integer quantities: no float enters the state, so the
`exact` canary's digest cannot drift on a numerics upgrade. The only floats
in the whole fixture are two derived statistics, and they exist precisely to
give the `semantic` canary a tolerance with a real basis.

Book representation here: price -> FIFO queue of resting orders. `min_lob_b`
implements the same behaviour over a flat list. Both are exercised by the
semantic canary; they must agree on the common surface and may not agree
byte-for-byte, which is the distinction the two canary modes encode.
"""

from __future__ import annotations

from typing import Any

from _engine.rng import ALGORITHM as RNG_ALGORITHM
from _engine.rng import VERSION as RNG_VERSION
from _engine.rng import SplitMix64

ENGINE_ID = "min-lob-a"
ENGINE_VERSION = "1.0.0"

BUY, SELL = "buy", "sell"
MECHANISM_ACTOR = "__mechanism__"


class _Log:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self._next_id = 1
        self._t = None
        self._seq = 0

    def emit(self, t, event_type, actor_id, actor_role, side, price, quantity,
             l1, cause_event_id=None, order_id=None, ext=None) -> int:
        if t != self._t:
            self._t, self._seq = t, 0
        else:
            self._seq += 1
        event = {
            # the common 8, always present, always in this order in source
            "t": t,
            "event_id": self._next_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "side": side,
            "price": price,
            "quantity": quantity,
            # provisional fields (gaps G1/G4/G5) — declared, never smuggled
            "seq": self._seq,
            "cause_event_id": cause_event_id,
            "order_id": order_id,
            "l1": l1,
        }
        if ext:
            event["ext"] = ext
        self.events.append(event)
        self._next_id += 1
        return event["event_id"]


class MinLobA:
    def __init__(self, config: dict[str, Any]) -> None:
        self.cfg = config
        self.rng = SplitMix64(config["seed"])
        # price -> list of [order_id, remaining_qty, arrival, agent]
        self.book: dict[str, dict[int, list]] = {BUY: {}, SELL: {}}
        self.log = _Log()
        self._order_seq = 0

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
    def _match(self, t, taker_side, limit_price, qty, actor_id, actor_role,
               cause_id) -> int:
        """Consume the opposite side; emit two fill legs per trade. Returns the
        unfilled remainder."""
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
            # two legs, one per side, same t, same cause. The buy leg is
            # emitted first by THIS engine; min_lob_b emits the sell leg first.
            # Nothing in the contract fixes leg order — which is why the
            # cross-engine assertion is "the two sides agree in quantity",
            # not "the two logs are equal".
            for leg_side, leg_actor, leg_role in (
                (BUY, actor_id if taker_side == BUY else resting[3],
                 actor_role if taker_side == BUY else "endogenous_agent"),
                (SELL, actor_id if taker_side == SELL else resting[3],
                 actor_role if taker_side == SELL else "endogenous_agent"),
            ):
                self.log.emit(t, "order_fill", leg_actor, leg_role, leg_side,
                              best, traded, self.l1(), cause_event_id=cause_id,
                              order_id=resting[0] if leg_side == other else None)
        return qty

    # ---- run -------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        cfg = self.cfg
        for t in range(1, cfg["n_steps"] + 1):
            for agent_index in range(cfg["n_agents"]):
                agent = f"a{agent_index}"
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
                    self.log.emit(t, "order_cancel", agent, "endogenous_agent",
                                  side, price, qty, self.l1(), order_id=order[0])
                    continue
                side = BUY if self.rng.below(2) == 0 else SELL
                offset = self.rng.below(cfg["max_offset"] + 1)
                qty = 1 + self.rng.below(cfg["max_qty"])
                mid = self._mid()
                price = mid - offset if side == BUY else mid + offset
                order_id = f"o{self._order_seq}"
                submit_id = self.log.emit(
                    t, "order_submit", agent, "endogenous_agent", side, price,
                    qty, self.l1(), order_id=order_id,
                    ext={"min_lob_a.mid_reference": mid})
                remainder = self._match(t, side, price, qty, agent,
                                        "endogenous_agent", submit_id)
                if remainder:
                    self._rest(side, price, remainder, agent, order_id)
            if t == cfg["shock"]["t"]:
                self._shock(t)
        self._snapshot(cfg["n_steps"] + 1)
        return self._document()

    def _shock(self, t) -> None:
        """Exogenous, harness-injected market order. `price` is null: an
        unpriced order. `actor_role` is exogenous_harness — without that value
        this event is indistinguishable from an agent's (gap G2)."""
        s = self.cfg["shock"]
        submit_id = self.log.emit(
            t, "order_submit", s["actor_id"], "exogenous_harness", s["side"],
            None, s["quantity"], self.l1(), order_id="shock",
            ext={"min_lob_a.protocol": s["type"]})
        remainder = self._match(t, s["side"], None, s["quantity"],
                                s["actor_id"], "exogenous_harness", submit_id)
        if remainder:
            # unfilled remainder of a market order leaves the system; recorded,
            # not dropped, or the conservation identity would not close.
            self.log.emit(t, "order_expire", s["actor_id"], "exogenous_harness",
                          s["side"], self.cfg["initial_mid"], remainder,
                          self.l1(), cause_event_id=submit_id, order_id="shock")

    def _snapshot(self, t) -> None:
        """Terminal resting depth, one event per (side, price) level.

        This uses only the common 8 fields — no new field, no ext — and is what
        closes the quantity-conservation identity and makes non-crossing
        assertable. Buy levels descending, then sell levels ascending."""
        for side, reverse in ((BUY, True), (SELL, False)):
            for price in sorted(self.book[side], reverse=reverse):
                qty = sum(o[1] for o in self.book[side][price])
                if qty:
                    self.log.emit(t, "book_level", MECHANISM_ACTOR,
                                  "market_mechanism", side, price, qty, self.l1())

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
            "events": self.log.events,
        }


def rng_identity() -> dict[str, str]:
    return {"rng_algorithm": RNG_ALGORITHM, "rng_version": RNG_VERSION}
