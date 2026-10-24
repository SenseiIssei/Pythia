"""Y9 (results/pumpfun_select_y9_prereg.md): what a buy at the migration may know about the coin, and what that buy
would have returned. PAPER ONLY.

  Tracker    the engine's part (sim.Engine(select=True); the live service's engine does not have it): per token
             its curve trades of the last KEEP_MS, dropped at the completion when the MIG_FEATURES are taken from
             them; the market's curve trades of the last KEEP_MS and completions of the last hour; and the pool's
             trades from the completion for POOL_KEEP_MS. features(tok, t) reads only what was received at or
             before t: the snapshot exists only once the curve has completed (at or before t), the pool part
             counts only trades at or before t.
  LabelPipe  a study book that enters every plain migration the way P_pool0 does, at the migration (entry 0)
             and 5 s after it (entry 5), with no slot, exposure or loss limit (a measurement, not a book), and
             writes one decision row per buy: the features at the signal (decision_features, the same call the
             pipeline's select filter makes) and three labels, `ret` (the trade's return over the stake after
             every cost, a failed buy its fee), `win` (ret > 0) and `rug` (the pool's price at or under half the
             price at the signal within RUG_MS after it).

Nothing here can trade.
"""

from __future__ import annotations

import collections
import dataclasses
from datetime import datetime, timezone

import numpy as np

from . import curve as C
from . import pipeline as P
from .tokens import FEATURES, SUPPLY
from .trendfeat import TREND_FEATURES
from .wallets import WALLET_FEATURES

KEEP_MS = 900_000                            # the longest window before the completion
WINDOWS_S = (60, 300, 900)
TREND_S = (60, 300)
DONE_H_MS = 3_600_000
POOL_KEEP_MS = 60_000
BIG_SELL = 0.02                              # a pool sale of 2 % or more of the pool's SOL before it
RUG_MS = 60_000
RUG_SHARE = 0.5
ENTRIES = (0, 5)                             # the label book's entries: seconds after the migration
NAN = float("nan")

MIG_FEATURES = (["age_at_complete_s", "secs_since_complete"]
                + [f"c_{k}_{w}" for w in WINDOWS_S for k in ("buys", "sells", "buy_sol", "sell_sol", "net_sol",
                                                             "ubuyers")]
                + ["c_unique_sellers", "c_top10_share", "c_dev_hold_share"]
                + [f"trend_{w}" for w in TREND_S] + ["mkt_trades_300", "mkt_complete_1h"])
POOL_FEATURES = ["pool_n", "pool_buys", "pool_sells", "pool_net_sol", "pool_net_share", "pool_max_sell_share",
                 "pool_big_sells", "pool_ret", "pool_first_s"]
SEL0 = list(FEATURES) + WALLET_FEATURES + MIG_FEATURES          # a decision at the migration
SEL5 = SEL0 + POOL_FEATURES                                      # a decision in the pool's first seconds
ROW_COLS = ["t", "entry", "ret", "win", "rug", "exit_ms"] + SEL5 + TREND_FEATURES     # Y10: the trend features too


def _empty_mig() -> dict:
    return {k: NAN for k in MIG_FEATURES}


class Tracker:
    def __init__(self):
        self.flow: dict[str, collections.deque] = {}       # mint -> (t, buy, sol, user), curve, last KEEP_MS
        self.mkt: collections.deque = collections.deque()   # every curve trade's time, last KEEP_MS
        self.done: collections.deque = collections.deque()  # completion times, last hour
        self.snap: dict[str, dict] = {}                      # mint -> MIG_FEATURES taken at the completion
        self.pool: dict[str, list] = {}                      # mint -> [completion t, [(t, buy, quote, before, price)]]

    # ------------------------------------------------------------ events
    def trade(self, tok, t: int, buy: bool, sol: int, user: str) -> None:
        """A curve trade (after the token's own update)."""
        if tok.complete_t is not None:
            return
        lo = t - KEEP_MS
        m = self.mkt
        m.append(t)
        while m and m[0] < lo:
            m.popleft()
        q = self.flow.get(tok.mint)
        if q is None:
            q = self.flow[tok.mint] = collections.deque()
        q.append((t, buy, sol, user))
        while q and q[0][0] < lo:
            q.popleft()

    def completed(self, tok, t: int) -> None:
        """The curve completed at t: the snapshot from the trades before, the pool watched from now."""
        if tok.mint in self.snap:
            return
        q = self.flow.pop(tok.mint, ())
        f = {"age_at_complete_s": (t - tok.t0) / 1000}
        for w in WINDOWS_S:
            lo = t - w * 1000
            b = s = 0
            bl = sl = 0
            users = set()
            for ts, buy, sol, user in q:
                if lo < ts <= t:
                    if buy:
                        b += 1
                        bl += sol
                        users.add(user)
                    else:
                        s += 1
                        sl += sol
            f.update({f"c_buys_{w}": b, f"c_sells_{w}": s, f"c_buy_sol_{w}": bl / C.LAMPORTS,
                      f"c_sell_sol_{w}": sl / C.LAMPORTS, f"c_net_sol_{w}": (bl - sl) / C.LAMPORTS,
                      f"c_ubuyers_{w}": len(users)})
        top = sorted(tok.hold.values(), reverse=True)[:10]
        f.update(c_unique_sellers=len(tok.sold), c_top10_share=sum(top) / SUPPLY,
                 c_dev_hold_share=tok.dev_hold() / SUPPLY)
        m = self.mkt
        for w in TREND_S:
            lo = t - w * 1000
            mine = sum(1 for ts, *_ in q if lo < ts <= t)
            n = 0
            for ts in reversed(m):
                if ts <= lo:
                    break
                n += ts <= t
            f[f"trend_{w}"] = mine / n if n else NAN
            if w == 300:
                f["mkt_trades_300"] = n
        d = self.done
        while d and d[0] < t - DONE_H_MS:
            d.popleft()
        f["mkt_complete_1h"] = len(d)
        d.append(t)
        self.snap[tok.mint] = f
        self.pool[tok.mint] = [t, []]

    def amm(self, tok, t: int, buy: bool, quote: int) -> None:
        """A pool trade (after the token's own update) in the pool's first POOL_KEEP_MS after the completion."""
        w = self.pool.get(tok.mint)
        if w is None or t - w[0] > POOL_KEEP_MS:
            return
        before = (tok.pq - quote if buy else tok.pq + quote) if tok.pq else 0
        w[1].append((t, buy, quote, before, C.price(tok.pq, tok.pb) if tok.pq and tok.pb else 0.0))

    def evict(self, mint: str) -> None:
        self.flow.pop(mint, None)
        self.snap.pop(mint, None)
        self.pool.pop(mint, None)

    # ------------------------------------------------------------ reading
    def features(self, tok, t: int) -> dict:
        """MIG_FEATURES and POOL_FEATURES as known at t (NaN where the curve has not completed by t)."""
        c = tok.complete_t
        snap = self.snap.get(tok.mint)
        f = dict(snap) if snap is not None and c is not None and c <= t else _empty_mig()
        f["secs_since_complete"] = (t - c) / 1000 if c is not None and c <= t else NAN
        f.update(self.pool_features(tok.mint, t))
        return f

    def pool_features(self, mint: str, t: int) -> dict:
        w = self.pool.get(mint)
        xs = [x for x in (w[1] if w is not None else ()) if x[0] <= t]
        if not xs:
            return {k: (0.0 if k in ("pool_n", "pool_buys", "pool_sells", "pool_big_sells") else NAN)
                    for k in POOL_FEATURES}
        buys = sum(1 for x in xs if x[1])
        net = sum(x[2] if x[1] else -x[2] for x in xs)
        ref = next((x[3] for x in xs if x[3] > 0), 0)
        shares = [x[2] / x[3] for x in xs if not x[1] and x[3] > 0]
        p0 = next((x[4] for x in xs if x[4] > 0), 0.0)
        p1 = next((x[4] for x in reversed(xs) if x[4] > 0), 0.0)
        return {"pool_n": float(len(xs)), "pool_buys": float(buys), "pool_sells": float(len(xs) - buys),
                "pool_net_sol": net / C.LAMPORTS, "pool_net_share": net / ref if ref else NAN,
                "pool_max_sell_share": max(shares) if shares else 0.0,
                "pool_big_sells": float(sum(1 for s in shares if s >= BIG_SELL)),
                "pool_ret": p1 / p0 - 1 if p0 > 0 else NAN, "pool_first_s": (xs[0][0] - w[0]) / 1000}


def decision_features(eng, tok, t) -> dict:
    """Everything a select decision at t may use: the engine's features (the token, its early buyers' reputation,
    its name), the Tracker's and, where the engine has the Y10 trend tracker, the trend features (trendfeat.py)."""
    f = eng.features(tok, int(t))
    f.update(eng.sel.features(tok, int(t)))
    if getattr(eng, "trend", None) is not None:
        f.update(eng.trend.features(tok, t))
    return f


# ---------------------------------------------------------------- the label book

class Unlimited(P.Risk):
    """The label book's risk: no slot, exposure or loss limit (it measures every migration); the kill switch only.
    Study code: no live book ever uses it."""

    def why_not(self, t: float, cost_l: int) -> str | None:
        self._roll(t)
        return "kill switch" if self.kill() else None


def label_strategies(base: str = "P_pool0", tag: str = "y9lab") -> list[P.Strategy]:
    """P_pool0 at the migration and 5 s after it, drawing its latency with P_pool0's key."""
    s = P.BY_NAME[base]
    return [dataclasses.replace(s, name=f"{base}_e{d}@{tag}", p={**s.p, "delay_s": d, "base": base}, stake_sol=0.1)
            for d in ENTRIES]


def day_of(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


class LabelPipe(P.Pipeline):
    """The decision rows and their labels. Its own pid space and no engine record, so the books next to it are
    unchanged (the engine's pid counter and signal count are put back after each of its signals)."""

    PID0 = 1 << 40

    def __init__(self, eng, costs=None, name: str = "y9lab", tag: str = "y9lab", executor=None):
        strats = label_strategies(tag=tag)                   # R2's realistic book: its own names and executor
        super().__init__(eng, strats, executor or P.PaperExecutor(), name=name, record=False)
        self.risk = {s.name: Unlimited(None, self.kill) for s in strats}
        if costs is not None:
            for s in strats:
                eng.rule_costs[s.name] = costs
        self.rows: list[dict] = []
        self.row_of: dict[int, dict] = {}
        self.rug: dict[str, list] = {}                         # mint -> [[row, price at the signal, until, low]]
        self.next = self.PID0

    def signal(self, s, tok, t: float) -> None:
        eng = self.eng
        f = None
        if tok.pq and tok.pb and tok.quote is None and not tok.mayhem and not tok.irregular and eng.sel is not None:
            f = decision_features(eng, tok, t)
        saved, had, sig = eng.next_pid, "pipe_signals" in eng.counts, eng.counts["pipe_signals"]
        eng.next_pid = self.next
        try:
            super().signal(s, tok, t)
        finally:
            pid, got = self.next, eng.next_pid != self.next
            self.next = eng.next_pid
            eng.next_pid = saved
            if had:
                eng.counts["pipe_signals"] = sig
            else:
                eng.counts.pop("pipe_signals", None)
        if f is None or not got:
            return
        row = {"t": int(t), "entry": int(s.p["delay_s"]), "mint": tok.mint, "ret": NAN, "win": NAN, "rug": NAN,
               "exit_ms": NAN, **{k: f.get(k, NAN) for k in SEL5 + TREND_FEATURES}}
        self.rows.append(row)
        self.row_of[pid] = row
        price = C.price(tok.pq, tok.pb)
        self.rug.setdefault(tok.mint, []).append([row, price, t + RUG_MS, price])
        eng.push(t + RUG_MS, "pipe", (self, "_rug_end", (tok.mint, row)))

    def on_trade(self, tok, t: float, buy: bool, user: str, tok_amt: int, venue: str) -> None:
        ws = self.rug.get(tok.mint) if self.rug else None
        if ws and venue == "pool" and tok.pq and tok.pb:
            p = C.price(tok.pq, tok.pb)
            for w in ws:
                if t <= w[2] and p < w[3]:
                    w[3] = p
        super().on_trade(tok, t, buy, user, tok_amt, venue)

    def _rug_end(self, at: float, data) -> None:
        mint, row = data
        ws = self.rug.get(mint) or []
        for w in [w for w in ws if w[0] is row]:
            row["rug"] = float(w[1] > 0 and w[3] <= RUG_SHARE * w[1])
            ws.remove(w)
        if not ws:
            self.rug.pop(mint, None)

    def _close(self, p: dict, at: float) -> None:
        super()._close(p, at)
        row = self.row_of.pop(p["pid"], None)
        rec = self.closed.pop()                                  # the row keeps what it needs
        if row is not None:
            row.update(ret=rec["ret"], win=float(rec["pnl_sol"] > 0), exit_ms=rec["exit_ms"])

    def buy_failed(self, pid: int, at: float, why: str, fee_l: int) -> None:
        stake = (self.pos.get(pid) or {}).get("stake_l") or 1
        super().buy_failed(pid, at, why, fee_l)
        self.failed.clear()
        row = self.row_of.pop(pid, None)
        if row is not None:
            row.update(ret=-fee_l / stake, win=0.0, exit_ms=at)

    def table(self) -> dict[str, np.ndarray]:
        """The rows as float columns (ROW_COLS), in signal order."""
        return {c: np.array([float(r[c]) if r.get(c) is not None else NAN for r in self.rows], dtype=float)
                for c in ROW_COLS}
