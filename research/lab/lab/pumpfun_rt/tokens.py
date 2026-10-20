"""Per-token state and the features a decision at time t may use.

The same code runs on the live stream (the shadow book) and on recorded days
(the study and the model's training set), so what the model learns from is
what the shadow book sees. Every feature is built only from events received
before the decision time; the creator's history is a snapshot taken when the
token was created.
"""

from __future__ import annotations

import collections
import math

from . import curve as C

SUPPLY = 1_000_000_000 * C.TOKEN_UNIT
WINDOW_MS = 10_000
CREATORS_MAX = 400_000
DUMP_SHARE = 0.5
# Metadata flags are not model features: the public IPFS gateways answer 429 or a
# service-worker page since 2026 (see collector.py), so they would be missing for
# nearly every token. "uri_ipfs" (uploaded the way pump.fun's site does it, or by
# a launch tool with its own metadata host) is known at creation and stays.
META_FEATURES = False


class CreatorBook:
    """What each creator did before: tokens made, how many completed their curve,
    how many the creator dumped (sold half or more of the dev holding), and when the
    last one was made. Bounded: the least recently active creators are forgotten."""

    def __init__(self, cap: int = CREATORS_MAX):
        self.cap = cap
        self.rows: collections.OrderedDict[str, list] = collections.OrderedDict()   # [n, migrated, dumped, last_t]
        self.recent: collections.deque = collections.deque()                          # creation times, 10 minutes

    def snapshot(self, creator: str, t: int) -> dict:
        r = self.rows.get(creator)
        while self.recent and self.recent[0] < t - 600_000:
            self.recent.popleft()
        if r is None:
            return {"n": 0, "migrated": 0, "dumped": 0, "since_s": None, "market_10m": len(self.recent)}
        return {"n": r[0], "migrated": r[1], "dumped": r[2], "since_s": (t - r[3]) / 1000 if r[3] else None,
                "market_10m": len(self.recent)}

    def _row(self, creator: str) -> list:
        r = self.rows.get(creator)
        if r is None:
            r = self.rows[creator] = [0, 0, 0, 0]
            if len(self.rows) > self.cap:
                self.rows.popitem(last=False)
        else:
            self.rows.move_to_end(creator)
        return r

    def created(self, creator: str, t: int) -> None:
        r = self._row(creator)
        r[0] += 1
        r[3] = t
        self.recent.append(t)

    def migrated(self, creator: str) -> None:
        self._row(creator)[1] += 1

    def dumped(self, creator: str) -> None:
        self._row(creator)[2] += 1

    def to_json(self) -> dict:
        return {"rows": {k: v for k, v in self.rows.items()}, "recent": list(self.recent)}

    @classmethod
    def from_json(cls, d: dict) -> "CreatorBook":
        b = cls()
        for k, v in (d.get("rows") or {}).items():
            b.rows[k] = list(v)
        b.recent.extend(d.get("recent") or [])
        return b


class Token:
    """One token's state, updated event by event."""

    __slots__ = ("mint", "creator", "t0", "tx0", "name", "symbol", "uri", "mayhem", "cashback", "quote", "vs", "vt",
                 "rs", "rt", "rt0", "p0", "fee_bps", "n_buys", "n_sells", "buy_l", "sell_l", "buyers", "traders",
                 "hold", "dev_buy_l", "dev_bought", "dev_sold", "dev_sell_t", "dev_dumped", "win", "peak", "last_t",
                 "complete_t", "migrate_t", "pool", "pb", "pq", "amm_fee_bps", "meta", "meta_t", "hist",
                 "irregular", "first_buyers", "first_tok", "last_slot", "amm_slot", "slot_start", "slot_moves",
                 "breaks", "slot_ok", "slot_flow", "devs")

    def __init__(self, mint: str, creator: str, t: int, tx: int, vs: int, vt: int, rt: int, hist: dict,
                 name: str = "", symbol: str = "", uri: str = "", mayhem: bool = False, cashback: bool = False,
                 quote: str | None = None, user: str | None = None):
        self.mint, self.creator, self.t0, self.tx0 = mint, creator, t, tx
        # "The dev": the creator, and the wallet that paid for the creation when a launch tool set
        # another creator (about a fifth of tokens; the dev buy then comes from the payer).
        self.devs = {d for d in (creator, user) if d}
        self.name, self.symbol, self.uri = name or "", symbol or "", uri or ""
        self.mayhem, self.cashback, self.quote = bool(mayhem), bool(cashback), quote
        self.vs, self.vt, self.rs, self.rt = vs or 0, vt or 0, 0, rt or 0
        self.rt0 = rt or C.INITIAL_RT
        self.p0 = C.price(self.vs, self.vt)
        self.fee_bps = C.DEFAULT_FEE_BPS
        self.n_buys = self.n_sells = 0
        self.buy_l = self.sell_l = 0
        self.buyers: set = set()
        self.traders: set = set()
        self.hold: dict[str, int] = {}
        self.dev_buy_l = 0
        self.dev_bought = self.dev_sold = 0
        self.dev_sell_t = None
        self.dev_dumped = False
        self.win: collections.deque = collections.deque()
        self.peak = self.p0
        self.last_t = t
        self.complete_t = self.migrate_t = None
        self.pool = None
        self.pb = self.pq = 0
        self.amm_fee_bps = C.DEFAULT_FEE_BPS
        self.meta = None
        self.meta_t = None
        self.hist = hist
        self.irregular = False
        self.first_buyers: list[str] = []
        self.first_tok = 0
        self.last_slot = 0
        self.amm_slot = 0
        self.slot_start = (self.vs, self.vt, self.rs, self.rt)
        self.slot_moves: dict[int, tuple] = {}
        self.slot_ok = True
        self.slot_flow = 0
        self.breaks = 0

    # ------------------------------------------------------------ events
    def _move(self, slot, buy: bool, sol: int, vs: int, vt: int, rs: int, rt: int) -> None:
        """The curve after a trade. Trades of one slot may arrive in any order (and volume bots buy
        and sell the same amount back and forth, so states repeat), so the state after the slot is
        the received state whose virtual SOL equals the slot's starting SOL plus every received
        trade's SOL: conservation, which holds in any order. When no received state matches, a
        trade of the slot was missed: `breaks` counts it at the end of the slot and the latest
        state is taken as is. A late delivery of an older slot never rewinds the curve."""
        post = (vs, vt, rs, rt)
        if slot and slot < self.last_slot:
            return
        if not slot or slot > self.last_slot:
            if not self.slot_ok:
                self.breaks += 1
            self.slot_start = (self.vs, self.vt, self.rs, self.rt)
            self.slot_moves = {}
            self.slot_flow = 0
            self.last_slot = slot or self.last_slot
        self.slot_flow += sol if buy else -sol
        self.slot_moves[vs] = post
        hit = self.slot_moves.get(self.slot_start[0] + self.slot_flow)
        self.slot_ok = hit is not None
        self.vs, self.vt, self.rs, self.rt = hit if hit is not None else post

    def trade(self, t: int, tx: int, buy: bool, sol: int, tok: int, user: str, vs: int, vt: int, rs: int, rt: int,
              fb: int | None, cfb: int | None, book: CreatorBook | None = None, slot: int | None = None) -> None:
        if vs and self.vs and fb == 0:
            self.irregular = True                         # fee-free trades with erratic reserves: not a plain curve
        self._move(slot, buy, sol, vs, vt, rs, rt)
        if fb is not None:
            self.fee_bps = int(fb) + int(cfb or 0)
        self.last_t = t
        self.traders.add(user)
        h = self.hold.get(user, 0)
        if buy:
            self.n_buys += 1
            self.buy_l += sol
            self.buyers.add(user)
            self.hold[user] = h + tok
            if user not in self.devs and len(self.first_buyers) < 5 and user not in self.first_buyers:
                self.first_buyers.append(user)
                self.first_tok += tok
        else:
            self.n_sells += 1
            self.sell_l += sol
            self.hold[user] = max(0, h - tok)
        if user in self.devs:
            if buy:
                self.dev_bought += tok
                if tx == self.tx0:
                    self.dev_buy_l += sol
            else:
                self.dev_sold += tok
                if self.dev_sell_t is None:
                    self.dev_sell_t = t
                if not self.dev_dumped and self.dev_bought and self.dev_sold >= DUMP_SHARE * self.dev_bought:
                    self.dev_dumped = True
                    if book is not None:
                        book.dumped(self.creator)
        self.win.append((t, buy, sol, user))
        while self.win and self.win[0][0] < t - WINDOW_MS:
            self.win.popleft()
        p = C.price(self.vs, self.vt)
        if p > self.peak:
            self.peak = p

    def completed(self, t: int, book: CreatorBook | None = None) -> None:
        if self.complete_t is None:
            self.complete_t = t
            if book is not None:
                book.migrated(self.creator)

    def migrated(self, t: int, pool: str, sol: int | None, tok: int | None) -> None:
        """The curve moved into a PumpSwap pool. The pool's state comes only from its own trades:
        the migration's amounts are before the migration fee (the pool opens with about 67 of the
        85 SOL the event names), so they would overstate what a sale there pays."""
        self.migrate_t = t
        self.pool = pool

    def amm(self, buy: bool, base: int, quote: int, pb: int | None, pq: int | None, lpb, pfb, cfb,
            slot: int | None = None) -> None:
        """A PumpSwap trade; the event's reserves are before it, so the state after is moved by it."""
        if slot and slot < self.amm_slot:
            return
        self.amm_slot = slot or self.amm_slot
        if pb and pq:
            self.pb, self.pq = (pb - base, pq + quote) if buy else (pb + base, pq - quote)
        fee = sum(int(x) for x in (lpb, pfb, cfb) if x is not None)
        if fee:
            self.amm_fee_bps = fee

    def set_meta(self, t: int, flags: dict) -> None:
        if self.meta is None:
            self.meta, self.meta_t = flags, t

    # ------------------------------------------------------------ reading
    @property
    def on_curve(self) -> bool:
        return self.complete_t is None

    def price(self) -> float:
        return C.price(self.vs, self.vt) if self.on_curve or not self.pq else C.price(self.pq, self.pb)

    def progress(self) -> float:
        return C.progress(self.rt, self.rt0)

    def tradeable(self) -> bool:
        """A plain SOL curve the study and the book may trade."""
        return self.quote is None and not self.mayhem and not self.irregular and self.vs > 0

    def dev_hold(self) -> int:
        return sum(self.hold.get(d, 0) for d in self.devs)

    def outside_buyers(self) -> int:
        """Unique buyers, the dev not counted."""
        return len(self.buyers) - sum(1 for d in self.devs if d in self.buyers)

    def window(self, t: int) -> tuple[int, int, float, int]:
        """Buys, sells, net SOL and unique buyers in the last 10 s before t."""
        b = s = 0
        net = 0
        users = set()
        for ts, buy, sol, user in self.win:
            if ts < t - WINDOW_MS or ts >= t:
                continue
            if buy:
                b += 1
                net += sol
                users.add(user)
            else:
                s += 1
                net -= sol
        return b, s, net / C.LAMPORTS, len(users)

    def top_shares(self) -> tuple[float, float]:
        """The largest holder's share of the supply, and the top five's (the dev included)."""
        top = sorted(self.hold.values(), reverse=True)[:5]
        return (top[0] / SUPPLY if top else 0.0), sum(top) / SUPPLY

    def features(self, t: int) -> dict:
        """What a decision at time t may know (state built from events before t)."""
        h = self.hist or {}
        b10, s10, net10, ub10 = self.window(t)
        top1, top5 = self.top_shares()
        p = self.price()
        m = self.meta if self.meta is not None and self.meta_t is not None and self.meta_t <= t else None
        nan = float("nan")
        since = h.get("since_s")
        return {
            "age_s": (t - self.t0) / 1000,
            "n_buys": self.n_buys, "n_sells": self.n_sells, "unique_buyers": len(self.buyers),
            "unique_traders": len(self.traders),
            "buy_sol": self.buy_l / C.LAMPORTS, "sell_sol": self.sell_l / C.LAMPORTS,
            "net_sol": (self.buy_l - self.sell_l) / C.LAMPORTS,
            "buys_10s": b10, "sells_10s": s10, "net_sol_10s": net10, "unique_buyers_10s": ub10,
            "progress": self.progress(),
            "log_price_ratio": math.log(p / self.p0) if p > 0 and self.p0 > 0 else nan,
            "from_peak": p / self.peak - 1 if self.peak > 0 else nan,
            "secs_since_trade": (t - self.last_t) / 1000,
            "dev_buy_sol": self.dev_buy_l / C.LAMPORTS,
            "dev_hold_share": self.dev_hold() / SUPPLY,
            "dev_sold_frac": self.dev_sold / self.dev_bought if self.dev_bought else 0.0,
            "dev_sold": float(self.dev_sold > 0),
            "secs_since_dev_sell": (t - self.dev_sell_t) / 1000 if self.dev_sell_t is not None else nan,
            "top1_share": top1, "top5_share": top5,
            "first5_share": self.first_tok / SUPPLY,
            "creator_prior": h.get("n", 0), "creator_prior_migrated": h.get("migrated", 0),
            "creator_prior_dumped": h.get("dumped", 0),
            "creator_migrate_rate": h.get("migrated", 0) / h["n"] if h.get("n") else nan,
            "creator_dump_rate": h.get("dumped", 0) / h["n"] if h.get("n") else nan,
            "creator_log_since": math.log1p(since) if since is not None else nan,
            "market_10m": h.get("market_10m", 0),
            "name_len": len(self.name), "symbol_len": len(self.symbol),
            "symbol_upper": float(self.symbol.isupper()), "uri_ipfs": float("ipfs" in self.uri),
            "cashback": float(self.cashback), "fee_bps": self.fee_bps,
            "hour_utc": (t // 3_600_000) % 24,
            **({"meta_known": 1.0, "twitter": float(bool(m.get("twitter"))), "telegram": float(bool(m.get("telegram"))),
                "website": float(bool(m.get("website")))} if m and m.get("ok") and META_FEATURES else {}),
        }


FEATURES = list(Token("x", "y", 0, 0, 30 * C.LAMPORTS, 1_073_000_000 * C.TOKEN_UNIT, C.INITIAL_RT, {}).features(1))
