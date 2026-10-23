"""Y10 (results/pumpfun_trends_y10_prereg.md): the Trends page's measures as features a decision may use, and the
triggers of the trend strategies. PAPER ONLY.

The engine's part (sim.Engine(trend=True): the paper books, the daily study and the Y10 run; the live service's
engine does not have it). Running counters, no rescans: STEP_MS buckets per token of the last KEEP_MS with the buy
SOL (curve and pool, SOL-quoted coins only), the pool's SOL traded (buys and sales), the unique buyers and the curve's
progress at the bucket's last trade; per window (1, 5, 15 minutes) every coin's buy SOL and the market's total,
added when a bucket closes and taken out when it leaves the window, so a ranking costs one sort per bucket.

No look-ahead, by construction: a value asked at t is the state at B = the last bucket boundary at or before t,
built from the closed buckets only, i.e. from the trades received before B (the bucket open at t is never read).
The record cut at t gives the same numbers (tests/test_pumpfun_trends_y10.py).

  tr_rank_{1,5,15}m   the coin's rank in "hot now" by buy SOL over the window (1 = the most; a coin without a buy
                      ranks after every coin with one); NaN for a coin quoted in another coin
  tr_n_5m             coins with a buy in the last 5 minutes
  tr_share_{1,5}m     the coin's share of all buy SOL of the window
  tr_vol_5m           its buy SOL over 5 minutes
  tr_ubuyers_1m       unique buyers in the last minute; tr_ubuyers_prev_1m in the minute before
  tr_speed_pm         curve progress gained per minute over the last 5 minutes (or since it was first seen)
  mkt_buy_sol_15m     the market's buy SOL over 15 minutes ("heat"); mkt_pools_15m the migrations of 15 minutes
  mkt_heat_rel        the heat over the median of its value at every boundary of the previous HEAT_HIST_MS (NaN
                      with less than HEAT_MIN_MS of them)
  fp_n                pools that migrated in the last FRESH_MS ("fresh"); for a fresh pool fp_rank its rank among
                      them by the pool's SOL traded over 5 minutes, fp_vol_5m that SOL, fp_rel that over the median
                      of the other fresh pools'
  fp_age_s            seconds since its migration (NaN before)
"""

from __future__ import annotations

import bisect
import collections

import numpy as np

from . import curve as C

STEP_MS = 10_000
KEEP_MS = 15 * 60_000
WINDOWS_M = (1, 5, 15)
FRESH_MS = 30 * 60_000
HEAT_HIST_MS = 6 * 3_600_000
HEAT_MIN_MS = 3 * 3_600_000
NAN = float("nan")

TREND_FEATURES = ([f"tr_rank_{w}m" for w in WINDOWS_M] + ["tr_n_5m", "tr_share_1m", "tr_share_5m", "tr_vol_5m",
                                                          "tr_ubuyers_1m", "tr_ubuyers_prev_1m", "tr_speed_pm",
                                                          "mkt_buy_sol_15m", "mkt_pools_15m", "mkt_heat_rel",
                                                          "fp_n", "fp_rank", "fp_vol_5m", "fp_rel", "fp_age_s"])


def boundary(t: float) -> int:
    t = int(t)
    return t - t % STEP_MS


class Tracker:
    def __init__(self):
        self.b0: int | None = None                           # the open bucket's start
        self.open: dict[str, list] = {}                      # mint -> [buy_l, pool_l, buyers, progress]
        self.hist: collections.deque = collections.deque()   # (start, {mint: [buy_l, pool_l, buyers, progress]})
        self.nb = {w: w * 60_000 // STEP_MS for w in WINDOWS_M}
        self.vol = {w: {} for w in WINDOWS_M}                # window -> mint -> buy lamports
        self.tot = {w: 0 for w in WINDOWS_M}
        self.pool5: dict[str, int] = {}
        self.prog: dict[str, collections.deque] = {}         # mint -> (bucket start, progress at its close)
        self.first: dict[str, tuple] = {}                    # mint -> (time, progress) when first seen
        self.mig: dict[str, int] = {}                        # mint -> migration time (plain SOL pools), FRESH_MS
        self.mig_t: collections.deque = collections.deque()  # every migration's time, KEEP_MS
        self.heat: collections.deque = collections.deque()   # (boundary, heat), HEAT_HIST_MS
        self._sorted: dict = {}                              # window -> (B, ascending volumes, [(vol, mint)] desc)
        self._med: tuple = (None, NAN)

    # ------------------------------------------------------------ events (after the token's own update)
    def _bucket(self, t: int) -> int:
        self.roll(t)
        if self.b0 is None:
            self.b0 = boundary(t)
        return self.b0

    def trade(self, tok, t: int, buy: bool, sol: int, user: str) -> None:
        """A curve trade."""
        self._bucket(t)
        if tok.mint not in self.first:
            self.first[tok.mint] = (tok.t0, 0.0) if t - tok.t0 <= KEEP_MS else (t, tok.progress())
        x = self.open.get(tok.mint)
        if x is None:
            x = self.open[tok.mint] = [0, 0, set(), None]
        if buy:
            if tok.quote is None:
                x[0] += int(sol or 0)
            if user:
                x[2].add(user)
        x[3] = tok.progress()

    def amm(self, tok, t: int, buy: bool, quote: int, user: str | None) -> None:
        """A pool trade."""
        self._bucket(t)
        if tok.mint not in self.first:
            self.first[tok.mint] = (t, 1.0)
        x = self.open.get(tok.mint)
        if x is None:
            x = self.open[tok.mint] = [0, 0, set(), None]
        if tok.quote is None:
            x[1] += int(quote or 0)
            if buy:
                x[0] += int(quote or 0)
        if buy and user:
            x[2].add(user)

    def migrated(self, tok, t: int) -> None:
        self._bucket(t)
        self.mig_t.append(int(t))
        if tok.quote is None and tok.mint not in self.mig:
            self.mig[tok.mint] = int(t)

    def evict(self, mint: str) -> None:
        for d in (self.prog, self.first, self.mig):
            d.pop(mint, None)

    # ------------------------------------------------------------ the clock
    def roll(self, t: float) -> None:
        """Close every bucket that ended at or before t."""
        if self.b0 is None:
            return
        while self.b0 + STEP_MS <= t:
            self._close()

    def _close(self) -> None:
        b, cur = self.b0, self.open
        B = b + STEP_MS
        self.open = {}
        self.hist.append((b, cur))
        h = self.hist
        for w, n in self.nb.items():
            vol = self.vol[w]
            for m, x in cur.items():
                if x[0]:
                    vol[m] = vol.get(m, 0) + x[0]
                    self.tot[w] += x[0]
            if len(h) > n:
                for m, x in h[-1 - n][1].items():
                    if x[0]:
                        v = vol.get(m, 0) - x[0]
                        if v > 0:
                            vol[m] = v
                        else:
                            vol.pop(m, None)
                        self.tot[w] -= x[0]
        n5 = self.nb[5]
        for m, x in cur.items():
            if x[1]:
                self.pool5[m] = self.pool5.get(m, 0) + x[1]
            if x[3] is not None:
                q = self.prog.get(m)
                if q is None:
                    q = self.prog[m] = collections.deque()
                q.append((b, x[3]))
                while len(q) > 1 and q[1][0] < B - 5 * 60_000:
                    q.popleft()
        if len(h) > n5:
            for m, x in h[-1 - n5][1].items():
                if x[1]:
                    v = self.pool5.get(m, 0) - x[1]
                    if v > 0:
                        self.pool5[m] = v
                    else:
                        self.pool5.pop(m, None)
        while len(h) > self.nb[15]:
            h.popleft()
        while self.mig_t and self.mig_t[0] < B - KEEP_MS:
            self.mig_t.popleft()
        for m in [m for m, tm in self.mig.items() if tm < B - FRESH_MS]:
            del self.mig[m]
        self.heat.append((B, self.tot[15]))
        while self.heat and self.heat[0][0] < B - HEAT_HIST_MS:
            self.heat.popleft()
        self.b0 = B

    # ------------------------------------------------------------ reading (the state at the boundary B <= t)
    def at(self, t: float) -> int:
        """The boundary whose state a question at t gets (the closed buckets before it)."""
        self.roll(t)
        return self.b0 if self.b0 is not None else boundary(t)

    def ranked(self, w: int, B: int) -> tuple:
        c = self._sorted.get(w)
        if c is None or c[0] != B:
            vol = self.vol[w]
            asc = sorted(vol.values())
            desc = sorted(((v, m) for m, v in vol.items()), key=lambda x: (-x[0], x[1]))
            c = self._sorted[w] = (B, asc, desc)
        return c

    def rank(self, mint: str, w: int, B: int) -> int:
        _, asc, _ = self.ranked(w, B)
        v = self.vol[w].get(mint, 0)
        return 1 + len(asc) - bisect.bisect_right(asc, v) if v > 0 else 1 + len(asc)

    def top(self, w: int, n: int, B: int) -> list[str]:
        """The coins ranked n or better (ties included)."""
        _, asc, desc = self.ranked(w, B)
        return [m for v, m in desc if 1 + len(asc) - bisect.bisect_right(asc, v) <= n]

    def buyers(self, mint: str, k0: int, k1: int) -> int:
        """Unique buyers in the closed buckets k0 to k1 - 1 back (0 the newest)."""
        h = self.hist
        s: set = set()
        for k in range(k0, min(k1, len(h))):
            x = h[-1 - k][1].get(mint)
            if x is not None:
                s |= x[2]
        return len(s)

    def speed(self, mint: str, B: int) -> float:
        q = self.prog.get(mint)
        if not q:
            return NAN
        now = q[-1][1]
        lo = B - 5 * 60_000
        p0, t0 = None, lo
        for b, p in q:
            if b < lo:
                p0 = p
        if p0 is None:
            ft, fp = self.first.get(mint, (q[0][0], q[0][1]))
            p0, t0 = fp, max(lo, ft)
        return (now - p0) / max((B - t0) / 60_000, STEP_MS / 60_000)

    def heat_median(self, B: int) -> float:
        """The median heat (SOL) of the boundaries before B in the last HEAT_HIST_MS; NaN under HEAT_MIN_MS."""
        if self._med[0] == B:
            return self._med[1]
        xs = [v for b, v in self.heat if b < B]
        first = next((b for b, _ in self.heat), None)
        med = float(np.median(xs)) / C.LAMPORTS if xs and first is not None and B - first >= HEAT_MIN_MS else NAN
        self._med = (B, med)
        return med

    def heat_now(self, B: int) -> float:
        """The market's buy SOL over 15 minutes at B (the closed buckets)."""
        return self.tot[15] / C.LAMPORTS

    def fresh(self, B: int) -> list[str]:
        """The fresh pools at B, best first: by the pool's SOL traded over 5 minutes, then the newest, then the
        mint (as the Trends page)."""
        ms = [m for m, tm in self.mig.items() if B - FRESH_MS <= tm < B]
        return sorted(ms, key=lambda m: (-self.pool5.get(m, 0), -self.mig[m], m))

    def features(self, tok, t: float) -> dict:
        B = self.at(t)
        m = tok.mint
        f = dict.fromkeys(TREND_FEATURES, NAN)
        sol = tok.quote is None
        for w in WINDOWS_M:
            if sol:
                f[f"tr_rank_{w}m"] = float(self.rank(m, w, B))
        n1 = self.nb[1]
        f["tr_n_5m"] = float(len(self.vol[5]))
        if sol:
            for w in (1, 5):
                f[f"tr_share_{w}m"] = self.vol[w].get(m, 0) / self.tot[w] if self.tot[w] > 0 else 0.0
            f["tr_vol_5m"] = self.vol[5].get(m, 0) / C.LAMPORTS
        f["tr_ubuyers_1m"] = float(self.buyers(m, 0, n1))
        f["tr_ubuyers_prev_1m"] = float(self.buyers(m, n1, 2 * n1))
        f["tr_speed_pm"] = self.speed(m, B)
        f["mkt_buy_sol_15m"] = self.heat_now(B)
        f["mkt_pools_15m"] = float(sum(1 for x in self.mig_t if B - KEEP_MS <= x < B))
        med = self.heat_median(B)
        f["mkt_heat_rel"] = self.heat_now(B) / med if med == med and med > 0 else NAN
        fr = self.fresh(B)
        f["fp_n"] = float(len(fr))
        tm = self.mig.get(m)
        if tm is not None and tm < B:
            f["fp_age_s"] = (B - tm) / 1000
        if m in fr:
            f["fp_rank"] = float(fr.index(m) + 1)
            v = self.pool5.get(m, 0)
            f["fp_vol_5m"] = v / C.LAMPORTS
            others = [self.pool5.get(x, 0) for x in fr if x != m]
            med = float(np.median(others)) if others else 0.0
            f["fp_rel"] = v / med if med > 0 else NAN
        return f

    # ------------------------------------------------------------ the trend strategies' triggers
    def candidates(self, r, eng, B: int) -> list[str]:
        """The mints a trend strategy (entry "trend") wants at the boundary B, in rank order:
          hot    on its curve and plain, ranked p["top"] or better by buy SOL over 5 minutes, and (p["rising"])
                 more unique buyers in the last minute than in the minute before
          fresh  a plain pool ranked p["top"] or better among the fresh pools, migrated p["from_s"] to p["to_s"]
                 seconds before B"""
        p = r.p
        out = []
        if p.get("list") == "hot":
            n1 = self.nb[1]
            for m in self.top(5, p["top"], B):
                tok = eng.tokens.get(m)
                if tok is None or not tok.on_curve or not tok.tradeable():
                    continue
                if p.get("rising") and not self.buyers(m, 0, n1) > self.buyers(m, n1, 2 * n1):
                    continue
                out.append(m)
        elif p.get("list") == "fresh":
            for k, m in enumerate(self.fresh(B)):
                if k >= p["top"]:
                    break
                tok = eng.tokens.get(m)
                age = B - self.mig[m]
                if tok is None or not p["from_s"] * 1000 <= age <= p["to_s"] * 1000:
                    continue
                out.append(m)
        return out

    def heat_ok(self, t: float, k: float) -> bool | None:
        """Y10's heat switch: the market's buy SOL over 15 minutes at least k x its median over the previous
        HEAT_HIST_MS (None with less than HEAT_MIN_MS of history)."""
        B = self.at(t)
        med = self.heat_median(B)
        if med != med:
            return None
        return self.heat_now(B) >= k * med
