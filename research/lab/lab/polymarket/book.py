"""The Polymarket PAPER book (results/polymarket_prereg.md, P). Play money, no orders.

Rule. With a forecast q of the first outcome (YES) and the asks of both
sides, the edge of buying YES at a is q - a - fee(a), of buying NO at b is
(1 - q) - b - fee(b), with the taker fee per share rate * (a * (1 - a)) **
exponent. Enter the better side when its edge is at least the margin, the ask
is between 3 and 97 cents, the market ends within 90 days and is not an
up-or-down market; one position per market, never both sides, held to
resolution.

Size. Quarter Kelly, 0.25 * (q - a) / (1 - a) of equity (YES; NO alike with
1 - q and b), at most 2 % of equity per market, 10 % per event, 25 % per
category, 60 % invested, at least 5 shares. The fill walks the ask side of
the book level by level while the edge at that level still clears the
margin, and takes no more than the depth shows.

Every number here is a simulation: nothing is sent anywhere.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import store

KELLY = 0.25
CAP_MARKET, CAP_EVENT, CAP_CATEGORY, CAP_INVESTED = 0.02, 0.10, 0.25, 0.60
MIN_SHARES = 5.0
MIN_ASK, MAX_ASK = 0.03, 0.97
MAX_DAYS = 90
START_USD = 10_000.0
DAY_MS = 86_400_000


def fee_per_share(price: float, rate: float, exponent: float = 1.0) -> float:
    if rate <= 0 or not 0.0 < price < 1.0:
        return 0.0
    return rate * (price * (1.0 - price)) ** exponent


def edge(q: float, ask: float, rate: float, exponent: float = 1.0) -> float:
    return q - ask - fee_per_share(ask, rate, exponent)


def kelly_fraction(q: float, ask: float) -> float:
    if not 0.0 < ask < 1.0:
        return 0.0
    return max(0.0, KELLY * (q - ask) / (1.0 - ask))


def walk(levels: list[tuple[float, float]], q: float, margin: float, budget: float, rate: float,
         exponent: float = 1.0) -> dict:
    """Buy along the asks (price, size), cheapest first, while the edge at the level clears
    the margin and the spend (fee included) stays within the budget. Returns shares, cost
    (price paid), fee, average price and the levels used."""
    shares = cost = fee = 0.0
    used = 0
    for px, sz in sorted(levels):
        if sz <= 0 or not MIN_ASK <= px <= MAX_ASK:
            continue
        if edge(q, px, rate, exponent) < margin:
            break
        per = px + fee_per_share(px, rate, exponent)
        room = budget - cost - fee
        if room <= 0:
            break
        take = min(sz, room / per)
        if take <= 0:
            break
        shares += take
        cost += take * px
        fee += take * fee_per_share(px, rate, exponent)
        used += 1
    return {"shares": shares, "cost": cost, "fee": fee, "avg": cost / shares if shares else None, "levels": used}


@dataclass
class Position:
    market_id: str
    side: str            # "yes" or "no"
    shares: float
    cost: float          # price paid, fees apart
    fee: float
    entry_ms: int
    q: float             # the forecast of the held side at entry
    ask: float           # best ask at entry
    edge: float          # edge at the best ask
    event_id: str
    category: str
    end_ms: int | None
    question: str = ""
    mark: float | None = None

    def outlay(self) -> float:
        return self.cost + self.fee


@dataclass
class Book:
    name: str
    margin: float
    cash: float = START_USD
    positions: dict[str, Position] = field(default_factory=dict)
    closed: list[dict] = field(default_factory=list)
    traded: set = field(default_factory=set)

    # ------------------------------------------------------------ state
    def equity(self) -> float:
        return self.cash + sum(p.shares * (p.mark if p.mark is not None else p.cost / max(p.shares, 1e-12))
                               for p in self.positions.values())

    def invested(self) -> float:
        return sum(p.outlay() for p in self.positions.values())

    def by(self, attr: str, key: str) -> float:
        return sum(p.outlay() for p in self.positions.values() if getattr(p, attr) == key)

    def room(self, event_id: str, category: str) -> float:
        eq = self.equity()
        return max(0.0, min(CAP_MARKET * eq, CAP_EVENT * eq - self.by("event_id", event_id),
                            CAP_CATEGORY * eq - self.by("category", category),
                            CAP_INVESTED * eq - self.invested(), self.cash))

    # ------------------------------------------------------------ decisions
    def consider(self, m: dict, q: float, ts: int, yes_asks: list[tuple[float, float]],
                 no_asks: list[tuple[float, float]], max_usd: float | None = None) -> dict | None:
        """One market: open a position if the rule says so. `m` needs id, event_id, category,
        kind, end_ms, fee_rate, fee_exponent (and question). Returns the fill or None."""
        mid = str(m["id"])
        if mid in self.positions or mid in self.traded or m.get("kind") == "updown":
            return None
        end = m.get("end_ms")
        if not end or end <= ts or end > ts + MAX_DAYS * DAY_MS:
            return None
        rate, expo = float(m.get("fee_rate") or 0.0), float(m.get("fee_exponent") or 1.0)
        best = None
        for side, qq, asks in (("yes", q, yes_asks), ("no", 1.0 - q, no_asks)):
            ok = [(px, sz) for px, sz in asks if sz > 0]
            if not ok:
                continue
            a = min(px for px, _ in ok)
            if not MIN_ASK <= a <= MAX_ASK:
                continue
            e = edge(qq, a, rate, expo)
            if e >= self.margin and (best is None or e > best[2]):
                best = (side, qq, e, a, ok)
        if best is None:
            return None
        side, qq, e, a, asks = best
        budget = min(kelly_fraction(qq, a) * self.equity(), self.room(m.get("event_id") or mid, m["category"]))
        if max_usd is not None:
            budget = min(budget, max_usd)
        f = walk(asks, qq, self.margin, budget, rate, expo)
        if f["shares"] < MIN_SHARES:
            return None
        pos = Position(mid, side, f["shares"], f["cost"], f["fee"], ts, qq, a, e, m.get("event_id") or mid,
                       m["category"], end, str(m.get("question") or "")[:200], mark=a)
        self.positions[mid] = pos
        self.traded.add(mid)
        self.cash -= pos.outlay()
        return {"market_id": mid, "side": side, "shares": f["shares"], "avg": f["avg"], "fee": f["fee"],
                "q": qq, "ask": a, "edge": e, "usd": pos.outlay(), "category": m["category"],
                "question": pos.question, "ts_ms": ts, "levels": f["levels"]}

    def settle(self, market_id: str, outcome_yes: float, ts: int) -> dict | None:
        p = self.positions.pop(str(market_id), None)
        if p is None:
            return None
        pay_per = outcome_yes if p.side == "yes" else 1.0 - outcome_yes
        payout = p.shares * pay_per
        self.cash += payout
        rec = {"market_id": p.market_id, "side": p.side, "shares": p.shares, "outlay": p.outlay(),
               "payout": payout, "pnl": payout - p.outlay(), "ret": payout / p.outlay() - 1 if p.outlay() else 0.0,
               "won": pay_per > 0.5, "q": p.q, "ask": p.ask, "edge": p.edge, "entry_ms": p.entry_ms,
               "exit_ms": ts, "category": p.category, "event_id": p.event_id, "question": p.question,
               "outcome": outcome_yes}
        self.closed.append(rec)
        return rec

    def set_mark(self, market_id: str, yes_mid: float | None) -> None:
        p = self.positions.get(str(market_id))
        if p is not None and yes_mid is not None and not math.isnan(yes_mid):
            p.mark = yes_mid if p.side == "yes" else 1.0 - yes_mid

    # ------------------------------------------------------------ persistence
    def to_json(self) -> dict:
        return {"name": self.name, "margin": self.margin, "cash": self.cash,
                "positions": {k: vars(v) for k, v in self.positions.items()},
                "traded": sorted(self.traded), "n_closed": len(self.closed)}

    @classmethod
    def from_json(cls, d: dict) -> "Book":
        b = cls(d["name"], float(d["margin"]), float(d["cash"]))
        b.positions = {k: Position(**v) for k, v in (d.get("positions") or {}).items()}
        b.traded = set(d.get("traded") or [])
        return b


# ---------------------------------------------------------------- the live books' files

def book_dir(name: str) -> Path:
    return store.path("paper", name)


def load(name: str, margin: float) -> Book:
    d = store.read_json(book_dir(name) / "state.json")
    b = Book.from_json(d) if d else Book(name, margin)
    b.closed = read_csv(book_dir(name) / "closed.csv")
    return b


def save(b: Book) -> None:
    store.write_json(book_dir(b.name) / "state.json", b.to_json())


def append_csv(p: Path, rows: list[dict]) -> None:
    if not rows:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    new = not p.exists()
    cols = list(rows[0].keys())
    with p.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        for r in rows:
            w.writerow(r)


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        out = []
        for r in csv.DictReader(fh):
            for k, v in list(r.items()):
                try:
                    r[k] = float(v) if k not in ("market_id", "side", "category", "event_id", "question", "won",
                                                 "day", "book") else v
                except (TypeError, ValueError):
                    pass
            out.append(r)
        return out
