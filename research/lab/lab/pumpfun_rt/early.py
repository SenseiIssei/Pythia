"""Early detection and exit timing (X14, results/pumpfun_early_exit_plan.md). PAPER ONLY.

The engine's Tracker, always on (the live books need its features too):

  * market activity (curve trades and creations of all tokens in the last 60 s,
    completions in the last hour), the sniper book (wallets that bought tokens
    within SNIPE_MS of their creation), and per token the flow of the last 10 s
    (curve and pool), its progress history and its top-10 share at 5 s of age;
  * EARLY_FEATURES for a decision at t and STEP_FEATURES for an open position at
    t (the pipeline's hazard exit asks the same function the step rows use).

With rows on (the study's replay) it also records, for every plain token at 5,
10, 20, 30 and 60 s and when its curve first passes 25, 50 and 75 %:

  rows    the features at t and the labels mig1h, peak3x, peak10x, alive5m, with
          the paper buy at t (filled like pipeline.PaperExecutor, latency and the
          cost limit included) and its fill at doubled latency
  paths   for every filled buy, every trade of the token for 30 minutes after the
          landing with the curve or pool state, so any sale is priced exactly, and
          the pipeline's dev-sell and pull triggers at each
  steps   the position's step rows: at the landing and at every trade at least 1 s
          after the step before, for 30 minutes (the exit models train on the
          first 10)

Paths and steps are what exitpol.py simulates exit policies on. Nothing here
can trade.
"""

from __future__ import annotations

import collections
import hashlib
import json
import math
from array import array
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from .tokens import SUPPLY

STAKE = 100_000_000                         # 0.1 SOL, the pipeline's stake
TIME_OFFSETS = (5, 10, 20, 30, 60)
MILESTONES = (0.25, 0.50, 0.75)
KINDS = [f"t{s}" for s in TIME_OFFSETS] + [f"p{int(m * 100)}" for m in MILESTONES]
KIND_ID = {k: i for i, k in enumerate(KINDS)}
MIG_H_MS = 3_600_000
PEAK_H_MS = 3_600_000
ALIVE_H_MS = 300_000
ALIVE_SHARE = 0.5
PEAKS = (3.0, 10.0)
PATH_H_MS = 1_800_000
PATH_PAD_MS = 10_000
STEP_EVERY_MS = 1_000
STEP_TRAIN_S = 600
SNIPE_MS = 2_000
SNIPER_MIN = 5
EARLY_WINDOW_MS = 30_000
SNIPERS_MAX = 400_000
GAP_TAIL_MS = 360_000                       # a row is dropped when (creation, t + 6 min) overlaps a curve gap
MAX_POSITIONS = 400_000                     # paths and steps beyond this are subsampled by token (plan: 3 M steps)
# A label's horizon after the decision, for the purge (seconds).
LABELS = {"mig1h": 3600, "peak3x": 3603, "peak10x": 3603, "alive5m": 300}

EARLY_FEATURES = ["buys_5s", "sells_5s", "net_sol_5s", "buy_accel", "net_accel", "buyers_per_s", "curve_vel",
                  "curve_vel_10s", "holders", "top10_share", "top10_at5", "snipers_2s", "w_sniper_known",
                  "mkt_trades_60s", "mkt_creates_60s", "mkt_complete_1h", "milestone"]
STEP_FEATURES = ["tau_s", "log_v", "log_peak", "dd", "since_peak_s", "age_s", "on_curve", "progress", "buys_5s",
                 "sells_5s", "net_sol_5s", "buys_10s", "sells_10s", "net_sol_10s", "buy_accel", "net_accel",
                 "curve_vel_10s", "out2_share", "big_sell_10s", "dev_hold_share", "dev_sold_frac",
                 "secs_since_dev_sell", "top1_share", "top10_share", "holders", "secs_since_trade", "pool_drop_10s",
                 "mkt_trades_60s", "hour_utc"]
NAN = float("nan")


def early_feature_list() -> list[str]:
    """Every feature an early-detection row carries (the engine's features plus EARLY_FEATURES)."""
    from .sim import ALL_FEATURES
    return list(ALL_FEATURES) + EARLY_FEATURES


def sale(amount: float, venue: int, x: float, y: float, fee: float) -> float:
    """Lamports a sale of `amount` tokens gets at this state (venue 0 curve: x=vs, y=vt; 1 pool: x=base,
    y=quote; 2 no market: nan)."""
    if venue == 0:
        return float(C.curve_sell(int(amount), int(x), int(y), int(fee)))
    if venue == 1:
        return float(C.pool_sell(int(amount), int(x), int(y), int(fee)))
    return NAN


def sale_vec(amount: float, venue: np.ndarray, x: np.ndarray, y: np.ndarray, fee: np.ndarray) -> np.ndarray:
    """sale() over a path (floats; the curve arithmetic in float64, within a lamport of the int version)."""
    a = float(amount)
    with np.errstate(divide="ignore", invalid="ignore"):
        gross = np.where(venue == 0, x * a / (y + a), y * a / (x + a))
        out = np.floor(np.floor(gross) * (1 - fee / 10_000))
    return np.where((venue == 2) | (x <= 0) | (y <= 0), np.nan, out)


def keep_token(mint: str, frac: float) -> bool:
    if frac >= 1:
        return True
    h = hashlib.blake2b(mint.encode(), digest_size=8).digest()
    return int.from_bytes(h, "big") / 2 ** 64 < frac


class SniperBook:
    """Per wallet: how many tokens it bought within SNIPE_MS of their creation (point in time, bounded)."""

    def __init__(self, cap: int = SNIPERS_MAX):
        self.cap = cap
        self.rows: collections.OrderedDict[str, int] = collections.OrderedDict()

    def get(self, w: str) -> int:
        return self.rows.get(w, 0)

    def add(self, w: str) -> None:
        self.rows[w] = self.rows.get(w, 0) + 1
        self.rows.move_to_end(w)
        if len(self.rows) > self.cap:
            self.rows.popitem(last=False)

    def to_json(self) -> dict:
        return {"rows": dict(self.rows)}

    @classmethod
    def from_json(cls, d: dict) -> "SniperBook":
        b = cls()
        for k, v in (d.get("rows") or {}).items():
            b.rows[k] = int(v)
        return b


def warm_snipers(days: list[str], root=None, book: SniperBook | None = None) -> SniperBook:
    """The sniper history from earlier days."""
    import polars as pl
    from . import store
    book = book or SniperBook()
    if not days:
        return book
    cr = store.read("creates", days, root)
    if cr.height == 0:
        return book
    cr = cr.select("mint", pl.col("t").alias("t0"), "creator", pl.col("user").alias("payer"))
    tr = store.read("trades", days, root).filter(pl.col("buy")).select("t", "mint", "user")
    x = (tr.join(cr, on="mint").filter((pl.col("t") - pl.col("t0") <= SNIPE_MS) & (pl.col("user") != pl.col("creator"))
                                       & (pl.col("user") != pl.col("payer").fill_null("")))
         .group_by(["mint", "user"]).agg(pl.col("t").min()).sort("t"))
    for w in x["user"].to_list():
        book.add(w)
    return book


class TokState:
    __slots__ = ("flow", "prog", "prog_base", "top10_5", "snipers", "seen", "known", "next_ms", "id", "rows")

    def __init__(self, tid: int):
        self.flow: collections.deque = collections.deque()      # (t, buy, sol, tok, user), last 10 s, curve and pool
        self.prog: collections.deque = collections.deque()      # (t, progress), last 12 s
        self.prog_base = 0.0
        self.top10_5 = NAN
        self.snipers: set = set()
        self.seen: set = set()
        self.known = 0
        self.next_ms = 0                                          # index of the next curve milestone
        self.id = tid
        self.rows: list[int] = []


class Pos:
    """A paper buy of an early-detection row: its path, peak and steps."""
    __slots__ = ("pid", "row", "mint", "tid", "kind", "tokens", "cost_l", "land", "path", "peak_v", "peak_ms",
                 "last_step", "n_pts", "keep", "gap")

    def __init__(self, pid, row, mint, tid, kind, tokens, cost_l, land, keep):
        self.pid, self.row, self.mint, self.tid, self.kind = pid, row, mint, tid, kind
        self.tokens, self.cost_l, self.land, self.keep = tokens, cost_l, land, keep
        self.path = array("d")
        self.peak_v = -1.0
        self.peak_ms = land
        self.last_step = -10 ** 15
        self.n_pts = 0
        self.gap = False


class Packed:
    """Float rows in chunks (as sim.Rows), with pending dicts until their labels are in."""
    CHUNK = 65_536

    def __init__(self, cols: list[str]):
        self.cols = list(cols)
        self.col = {c: i for i, c in enumerate(self.cols)}
        self.pending: dict[int, dict] = {}
        self.chunks: list[np.ndarray] = []
        self.n = 0

    def new(self, row: dict, pending: bool = True) -> int:
        idx = self.n
        self.n += 1
        if pending:
            self.pending[idx] = row
        else:
            self._put(idx, row)
        return idx

    def get(self, idx: int) -> dict:
        return self.pending.get(idx) or {}

    def _arr(self, idx: int) -> np.ndarray:
        k = idx // self.CHUNK
        while len(self.chunks) <= k:
            self.chunks.append(np.full((self.CHUNK, len(self.cols)), np.nan, dtype=np.float64))
        return self.chunks[k]

    def _put(self, idx: int, row: dict) -> None:
        self._arr(idx)[idx % self.CHUNK] = [float(row[c]) if row.get(c) is not None else np.nan for c in self.cols]

    def set(self, idx: int, col: str, v: float) -> None:
        p = self.pending.get(idx)
        if p is not None:
            p[col] = v
        else:
            self._arr(idx)[idx % self.CHUNK, self.col[col]] = v

    def pack(self, idx: int) -> None:
        row = self.pending.pop(idx, None)
        if row is not None:
            self._put(idx, row)

    def frame(self) -> dict[str, np.ndarray]:
        for idx in list(self.pending):
            self.pack(idx)
        A = np.vstack(self.chunks)[:self.n] if self.chunks else np.zeros((0, len(self.cols)))
        return {c: A[:, i] for c, i in self.col.items()}


ROW_LABELS = list(LABELS)
ROW_R = ["filled_r", "peak3x_r", "peak10x_r"]           # R2: the peaks at the realistic entry (labels_r2.Labels)
ROW_META = ["t", "created_ms", "tid", "kind", "filled", "pos", "tokens", "cost_l", "land_ms", "lat_ms",
            "filled2", "tokens2", "cost2_l", "land2_ms", "dropped"]
STEP_META = ["pos", "t", "pt"]


class Tracker:
    """Market activity, snipers, per-token flow; with rows on, the early rows, paths and steps."""

    def __init__(self, eng, rows: bool = False, snipers: SniperBook | None = None, keep_frac: float = 1.0):
        self.eng = eng
        self.rows_on = rows
        self.snipers = snipers if snipers is not None else SniperBook()
        self.mkt_trades: collections.deque = collections.deque()
        self.mkt_creates: collections.deque = collections.deque()
        self.mkt_done: collections.deque = collections.deque()
        self.st: dict[str, TokState] = {}
        self.next_tid = 0
        self.mints: list[str] = []
        self.keep_frac = keep_frac
        self.features_cache: tuple | None = None
        if rows:
            from .socialfeat import SOCIAL_FEATURES              # Y14: the social link features (the same)
            from .trendfeat import TREND_FEATURES                # Y10: the trend features (NaN without the tracker)
            self.row_cols = (ROW_META + early_feature_list() + TREND_FEATURES + SOCIAL_FEATURES + ROW_LABELS
                             + ROW_R)                         # R2: the peaks at the realistic entry
            self.rows = Packed(self.row_cols)
            self.steps = Packed(STEP_META + STEP_FEATURES)
        self.pos: dict[int, Pos] = {}
        self.by_mint: dict[str, list[Pos]] = {}
        self.next_pid = 0
        self.paths: list[tuple] = []                                 # (pid, row, tid, kind, tokens, cost_l, land, gap, path)
        self.gaps: dict[str, list[tuple[int, int]]] = {"curve": [], "pool": []}
        self.max_watch: dict[tuple, list] = {}                       # (book, pid) -> [mint, tokens, cost, land, max_v]
        self.max_by_mint: dict[str, list] = {}
        self.max_done: dict[tuple, dict] = {}
        self.t_end = 0

    # ------------------------------------------------------------ events
    def created(self, tok, t: int) -> None:
        self._mkt(t)
        self.mkt_creates.append(t)
        tid = self.next_tid
        self.next_tid += 1
        self.st[tok.mint] = TokState(tid)
        if self.rows_on:
            self.mints.append(tok.mint)
        eng = self.eng
        eng.push(t + 5_000, "pipe", (self, "_snap5", tok.mint))
        if self.rows_on:
            for s in TIME_OFFSETS:
                eng.push(t + s * 1000, "pipe", (self, "_decide_at", (tok.mint, f"t{s}")))
            eng.push(t + MIG_H_MS, "pipe", (self, "_mig", tok.mint))

    def _mkt(self, t: int) -> None:
        for dq, span in ((self.mkt_trades, 60_000), (self.mkt_creates, 60_000), (self.mkt_done, 3_600_000)):
            while dq and dq[0] < t - span:
                dq.popleft()

    def completed(self, tok, t: int) -> None:
        self._mkt(t)
        self.mkt_done.append(t)
        self._event(tok, t, 0)

    def trade(self, tok, t: int, buy: bool, sol: int, amt: int, user: str, venue: str) -> None:
        st = self.st.get(tok.mint)
        if st is None:
            return
        self.features_cache = None
        curve = venue == "curve"
        if curve:
            self._mkt(t)
            self.mkt_trades.append(t)
            st.prog.append((t, tok.progress()))
            while st.prog and st.prog[0][0] < t - 12_000:
                st.prog_base = st.prog.popleft()[1]
            if buy and user not in tok.devs and t - tok.t0 <= EARLY_WINDOW_MS and user not in st.seen:
                st.seen.add(user)
                if self.snipers.get(user) >= SNIPER_MIN:
                    st.known += 1
                if t - tok.t0 <= SNIPE_MS:
                    st.snipers.add(user)
                    self.snipers.add(user)
        st.flow.append((t, buy, sol, amt, user))
        while st.flow and st.flow[0][0] < t - 10_000:
            st.flow.popleft()
        if curve and self.rows_on:
            prog = tok.progress()
            while st.next_ms < len(MILESTONES) and prog >= MILESTONES[st.next_ms]:
                k = st.next_ms
                st.next_ms += 1
                if prog < 1.0 and tok.on_curve:
                    self.decide(tok, t, f"p{int(MILESTONES[k] * 100)}", MILESTONES[k])
        flags = 0
        if not buy and tok.mint in self.by_mint:              # the triggers only where a path records them
            if P.dev_sell_trigger(tok, user, amt):
                flags |= 1
            elif P.pull_trigger(tok, t, user, amt, venue):
                flags |= 2
        self._event(tok, t, flags)

    def gap(self, t0: int, t1: int, prog: str | None) -> None:
        from .events import PUMP_AMM
        self.gaps["pool" if prog == PUMP_AMM else "curve"].append((int(t0), int(t1)))
        if prog != PUMP_AMM:                                  # a position whose 30-minute path it falls in
            for p in self.pos.values():
                if t0 < p.land + PATH_H_MS:
                    p.gap = True

    # ------------------------------------------------------------ features
    def _flow(self, st: TokState, a: float, b: float) -> tuple[int, int, float, float]:
        """Buys, sells, net SOL and the largest sale (tokens) in (a, b]."""
        nb = ns = 0
        net = 0
        big = 0
        for ts, buy, sol, amt, _ in st.flow:
            if a < ts <= b:
                if buy:
                    nb += 1
                    net += sol
                else:
                    ns += 1
                    net -= sol
                    big = max(big, amt)
        return nb, ns, net / C.LAMPORTS, big

    @staticmethod
    def _prog_at(st: TokState, x: float) -> float:
        v = st.prog_base
        for ts, p in st.prog:
            if ts > x:
                break
            v = p
        return v

    @staticmethod
    def top10(tok) -> tuple[int, float]:
        held = [v for v in tok.hold.values() if v > 0]
        top = sorted(held, reverse=True)[:10]
        return len(held), sum(top) / SUPPLY

    def _snap5(self, at: float, mint: str) -> None:
        tok, st = self.eng.tokens.get(mint), self.st.get(mint)
        if tok is not None and st is not None and st.top10_5 != st.top10_5:      # once (see due)
            st.top10_5 = self.top10(tok)[1]

    def due(self, tok, t: float) -> None:
        """The 5 s snapshot before a row of the coin past it (called before the token takes the row): a coin whose
        rows came late (live.Hold) has its snapshot due at the clock, after them; in chain order it ran first."""
        st = self.st.get(tok.mint)
        if st is not None and t > tok.t0 + 5_000 and st.top10_5 != st.top10_5:
            st.top10_5 = self.top10(tok)[1]

    def early_features(self, tok, t: float, milestone: float = 0.0, prune: bool = True) -> dict:
        """prune=False (the trends view, trends.py) counts the market without dropping old entries, so a reader
        outside the engine's own clock changes nothing a later decision sees."""
        st = self.st.get(tok.mint)
        if prune:
            self._mkt(t)
        age = max((t - tok.t0) / 1000, 1e-3)
        prog = tok.progress()
        if st is None:
            return {k: NAN for k in EARLY_FEATURES} | {"milestone": milestone}
        b5, s5, n5, _ = self._flow(st, t - 5_000, t)
        bp, _, np_, _ = self._flow(st, t - 10_000, t - 5_000)
        holders, top10 = self.top10(tok)
        return {"buys_5s": b5, "sells_5s": s5, "net_sol_5s": n5, "buy_accel": b5 - bp, "net_accel": n5 - np_,
                "buyers_per_s": tok.outside_buyers() / max(age, 1.0), "curve_vel": prog / max(age, 1.0),
                "curve_vel_10s": prog - self._prog_at(st, t - 10_000), "holders": holders, "top10_share": top10,
                "top10_at5": st.top10_5, "snipers_2s": len(st.snipers), "w_sniper_known": st.known,
                "mkt_trades_60s": self._mkt_n(self.mkt_trades, t, 60_000, prune),
                "mkt_creates_60s": self._mkt_n(self.mkt_creates, t, 60_000, prune),
                "mkt_complete_1h": self._mkt_n(self.mkt_done, t, 3_600_000, prune), "milestone": milestone}

    @staticmethod
    def _mkt_n(dq: collections.deque, t: float, span: int, pruned: bool) -> int:
        if pruned:
            return len(dq)
        old = 0                                               # what _mkt would drop: the head older than the span
        for x in dq:
            if x >= t - span:
                break
            old += 1
        return len(dq) - old

    def step_features(self, tok, t: float, v: float, cost: float, peak_v: float, land_ms: float,
                      peak_ms: float) -> dict:
        """What the exit models see at t for a position worth v (net lamports) that cost `cost`."""
        key = (tok.mint, t)
        if self.features_cache is not None and self.features_cache[0] == key:
            f = dict(self.features_cache[1])
        else:
            f = self._token_step(tok, t)
            self.features_cache = (key, f)
            f = dict(f)
        lv = math.log(v / cost) if v > 0 and cost > 0 else math.log(1e-4)
        lp = math.log(peak_v / cost) if peak_v > 0 and cost > 0 else lv
        f.update(tau_s=(t - land_ms) / 1000, log_v=lv, log_peak=lp,
                 dd=(v / peak_v - 1) if peak_v > 0 else 0.0, since_peak_s=(t - peak_ms) / 1000)
        return f

    def _token_step(self, tok, t: float) -> dict:
        st = self.st.get(tok.mint)
        self._mkt(t)
        if st is None:
            return {k: NAN for k in STEP_FEATURES}
        b5, s5, n5, _ = self._flow(st, t - 5_000, t)
        bp, _, np_, _ = self._flow(st, t - 10_000, t - 5_000)
        b10, s10, n10, big = self._flow(st, t - 10_000, t)
        on = tok.on_curve
        depth = tok.rs if on else tok.pq
        out2 = -self._flow(st, t - 2_000, t)[2] * C.LAMPORTS
        holders, top10 = self.top10(tok)
        top1 = max(tok.hold.values(), default=0) / SUPPLY
        return {"age_s": (t - tok.t0) / 1000, "on_curve": float(on), "progress": tok.progress(),
                "buys_5s": b5, "sells_5s": s5, "net_sol_5s": n5, "buys_10s": b10, "sells_10s": s10,
                "net_sol_10s": n10, "buy_accel": b5 - bp, "net_accel": n5 - np_,
                "curve_vel_10s": tok.progress() - self._prog_at(st, t - 10_000) if on else 0.0,
                "out2_share": out2 / (depth + max(out2, 0)) if depth and depth + max(out2, 0) > 0 else 0.0,
                "big_sell_10s": big / SUPPLY, "dev_hold_share": tok.dev_hold() / SUPPLY,
                "dev_sold_frac": tok.dev_sold / tok.dev_bought if tok.dev_bought else 0.0,
                "secs_since_dev_sell": (t - tok.dev_sell_t) / 1000 if tok.dev_sell_t is not None else NAN,
                "top1_share": top1, "top10_share": top10, "holders": holders,
                "secs_since_trade": (t - tok.last_t) / 1000, "pool_drop_10s": 0.0 if on else tok.pool_drop(t, 10_000),
                "mkt_trades_60s": len(self.mkt_trades), "hour_utc": (int(t) // 3_600_000) % 24}

    # ------------------------------------------------------------ the early rows
    def _decide_at(self, at: float, data) -> None:
        mint, kind = data
        tok = self.eng.tokens.get(mint)
        if tok is not None:
            self.decide(tok, at, kind, 0.0)

    def decide(self, tok, t: float, kind: str, milestone: float) -> None:
        if not tok.on_curve or not tok.tradeable():
            return
        st = self.st.get(tok.mint)
        if st is None:
            return
        eng = self.eng
        want = C.curve_buy(STAKE, tok.vs, tok.vt, tok.rt, tok.fee_bps)
        if want <= 0:
            return
        f = eng.features(tok, int(t))
        f.update(self.early_features(tok, t, milestone))
        if getattr(eng, "trend", None) is not None:
            f.update(eng.trend.features(tok, t))
        if getattr(eng, "social", None) is not None:
            f.update(eng.social.features(tok, t))
        lat = eng.costs.latency("early", tok.mint, kind, "buy")
        row = {"t": int(t), "created_ms": tok.t0, "tid": st.id, "kind": KIND_ID[kind], "filled": 0.0, "pos": -1.0,
               "lat_ms": lat, "filled2": 0.0, "dropped": 0.0, **f,
               "_want": want, "_watch": tok.sell_watch(), "_mint": tok.mint, "_kind": kind}
        idx = self.rows.new(row)
        st.rows.append(idx)
        eng.push(t + lat, "pipe", (self, "_land", (idx, 1)))
        eng.push(t + 2 * lat, "pipe", (self, "_land", (idx, 2)))
        eng.push(t + ALIVE_H_MS, "pipe", (self, "_alive", idx))
        eng.push(t + 2 * lat + PEAK_H_MS + 2_000, "pipe", (self, "_pack", idx))
        if getattr(eng, "r2", None) is not None:             # R2: the peaks at the realistic entry
            eng.r2.early(self, idx, tok.mint, kind, want, t)

    def _cost(self, tok, want: int) -> tuple[int, int, str | None]:
        """(tokens, cost lamports, why not) of buying `want` now, as the paper executor fills it."""
        from .pipeline import curve_cost
        if tok is None:
            return 0, 0, "token gone"
        if not tok.on_curve:
            return 0, 0, "completed"
        n = min(want, tok.rt)
        if n <= 0:
            return 0, 0, "nothing"
        cost = curve_cost(n, tok.vs, tok.vt, tok.fee_bps)
        if cost > int(STAKE * (1 + C.SLIP_TOL)):
            return 0, 0, "slippage"
        return n, cost, None

    def _land(self, at: float, data) -> None:
        idx, leg = data
        row = self.rows.get(idx)
        if not row:
            return
        tok = self.eng.tokens.get(row["_mint"])
        n, cost, why = self._cost(tok, row["_want"])
        if leg == 2:
            if why is None:
                row.update(filled2=1.0, tokens2=float(n), cost2_l=float(cost), land2_ms=float(at))
            return
        if why is not None:
            for k in PEAKS:
                row[f"peak{int(k)}x"] = 0.0
            return
        row.update(filled=1.0, tokens=float(n), cost_l=float(cost), land_ms=float(at))
        pid = self.next_pid
        self.next_pid += 1
        row["pos"] = float(pid)
        st = self.st.get(tok.mint)
        p = Pos(pid, idx, tok.mint, st.id if st else -1, row["_kind"], n, cost, int(at),
                keep_token(tok.mint, self.keep_frac))
        self.pos[pid] = p
        self.by_mint.setdefault(tok.mint, []).append(p)
        self._point(p, tok, at, 0)
        self.eng.push(at + PEAK_H_MS, "pipe", (self, "_peak_end", pid))

    def _event(self, tok, t: float, flags: int) -> None:
        ps = self.by_mint.get(tok.mint)
        if ps:
            for p in ps:
                self._point(p, tok, t, flags)
        ws = self.max_by_mint.get(tok.mint)
        if ws:
            v = self.eng.sale_value(tok, 1)                    # cheap check that a market exists
            for w in ws:
                if t <= w[3] + PATH_H_MS and v is not None:
                    w[4] = max(w[4], float(self.eng.sale_value(tok, w[1]) or 0))

    def _point(self, p: Pos, tok, t: float, flags: int) -> None:
        if tok.on_curve:
            venue, x, y, fee = 0, tok.vs, tok.vt, tok.fee_bps
        elif tok.pq and tok.pb:
            venue, x, y, fee = 1, tok.pb, tok.pq, tok.amm_fee_bps
        else:
            venue, x, y, fee = 2, 0, 0, 0
        v = sale(p.tokens, venue, x, y, fee)
        tx = self.eng.costs.tx_lamports()
        vn = v - tx if v == v else NAN
        if vn == vn and t <= p.land + PEAK_H_MS and vn > p.peak_v:
            p.peak_v, p.peak_ms = vn, t
        if t > p.land + PATH_H_MS + PATH_PAD_MS:
            return
        if p.keep:
            p.path.extend((t, venue, x, y, fee, flags))
            p.n_pts += 1
            if t - p.last_step >= STEP_EVERY_MS and t <= p.land + PATH_H_MS and vn == vn:
                p.last_step = t
                cost = p.cost_l + tx
                f = self.step_features(tok, t, vn, cost, max(p.peak_v, vn), p.land, p.peak_ms)
                self.steps.new({"pos": p.pid, "t": t, "pt": p.n_pts - 1, **f}, pending=False)

    def _peak_end(self, at: float, pid: int) -> None:
        p = self.pos.pop(pid, None)
        if p is None:
            return
        ps = self.by_mint.get(p.mint)
        if ps is not None:
            ps.remove(p)
            if not ps:
                self.by_mint.pop(p.mint, None)
        self._settle(p, complete=True)

    def _settle(self, p: Pos, complete: bool) -> None:
        tx = self.eng.costs.tx_lamports()
        cost = p.cost_l + tx
        row_idx = p.row
        for k in PEAKS:
            hit = p.peak_v >= k * cost
            self.rows.set(row_idx, f"peak{int(k)}x", 1.0 if hit else (0.0 if complete else NAN))
        full = complete or self.t_end >= p.land + PATH_H_MS + PATH_PAD_MS
        if p.keep:
            self.paths.append((p.pid, row_idx, p.tid, KIND_ID[p.kind], p.tokens, p.cost_l, p.land,
                               p.gap or self._gapped(p), full, np.frombuffer(p.path, dtype=np.float64).copy()))
        p.path = array("d")

    def _gapped(self, p: Pos) -> bool:
        a, b = p.land, p.land + PATH_H_MS
        return any(g0 < b and a < g1 for g0, g1 in self.gaps["curve"])

    def _alive(self, at: float, idx: int) -> None:
        row = self.rows.get(idx)
        tok = self.eng.tokens.get(row.get("_mint")) if row else None
        if tok is None:
            return
        watch = row.get("_watch") or {}
        dumped = any(tok.sold.get(w, 0) - s0 >= ALIVE_SHARE * h0 for w, (h0, s0) in watch.items())
        row["alive5m"] = 0.0 if dumped else 1.0

    def _mig(self, at: float, mint: str) -> None:
        tok, st = self.eng.tokens.get(mint), self.st.get(mint)
        if tok is None or st is None:
            return
        done = tok.complete_t is not None and tok.complete_t <= tok.t0 + MIG_H_MS
        for idx in st.rows:
            self.rows.set(idx, "mig1h", 1.0 if done else 0.0)

    def _pack(self, at: float, idx: int) -> None:
        self.rows.pack(idx)

    # ------------------------------------------------------------ the pipeline's positions (capture)
    def watch_max(self, book: str, pid: int, mint: str, tokens: int, cost_l: int, land: float) -> None:
        w = [mint, tokens, cost_l, land, float(self.eng.sale_value(self.eng.tokens.get(mint), tokens) or 0)]
        self.max_watch[(book, pid)] = w
        self.max_by_mint.setdefault(mint, []).append(w)
        self.eng.push(land + PATH_H_MS + 1, "pipe", (self, "_max_end", (book, pid)))

    def _max_end(self, at: float, key) -> None:
        w = self.max_watch.pop(key, None)
        if w is None:
            return
        ws = self.max_by_mint.get(w[0])
        if ws is not None:
            ws.remove(w)
            if not ws:
                self.max_by_mint.pop(w[0], None)
        self.max_done[key] = {"max_l": w[4], "cost_l": w[2], "complete": True}

    # ------------------------------------------------------------ housekeeping
    def evict(self, mint: str) -> None:
        self.st.pop(mint, None)

    def finish(self, t_end: float) -> None:
        """End of data: settle open positions (labels known only where already reached)."""
        self.t_end = t_end
        for p in list(self.pos.values()):
            self._settle(p, complete=False)
        self.pos.clear()
        self.by_mint.clear()
        for key, w in list(self.max_watch.items()):
            self.max_done[key] = {"max_l": w[4], "cost_l": w[2], "complete": t_end >= w[3] + PATH_H_MS}
        if self.rows_on:
            for row in self.rows.pending.values():
                tok = self.eng.tokens.get(row.get("_mint"))
                if row.get("mig1h") is None and tok is not None and tok.complete_t is not None \
                        and tok.complete_t <= tok.t0 + MIG_H_MS:
                    row["mig1h"] = 1.0

    # ------------------------------------------------------------ output
    def tables(self) -> dict:
        """rows (columns), steps (columns), paths (arrays and an index), mints, gaps."""
        fr = self.rows.frame()
        if self.gaps["curve"] and len(fr["t"]):
            a, b = fr["created_ms"], fr["t"] + GAP_TAIL_MS
            bad = np.zeros(len(a), dtype=bool)
            for g0, g1 in self.gaps["curve"]:
                bad |= (g0 < b) & (a < g1)
            fr["dropped"] = bad.astype(float)
        st = self.steps.frame()
        return {"rows": fr, "steps": st, "paths": pack_paths(self.paths), "mints": list(self.mints),
                "gaps": self.gaps}


def pack_paths(paths: list[tuple]) -> dict[str, np.ndarray]:
    """The positions' paths as flat arrays and an index (start, end into the points)."""
    n = len(paths)
    idx = {k: np.zeros(n, dtype=np.float64) for k in ("pos", "row", "tid", "kind", "tokens", "cost_l", "land",
                                                        "gap", "full", "start", "end")}
    pts = []
    at = 0
    for i, (pid, row, tid, kind, tokens, cost, land, gap, full, arr) in enumerate(paths):
        m = arr.reshape(-1, 6) if len(arr) else np.zeros((0, 6))
        for k, v in (("pos", pid), ("row", row), ("tid", tid), ("kind", kind), ("tokens", tokens), ("cost_l", cost),
                     ("land", land), ("gap", float(gap)), ("full", float(full)), ("start", at)):
            idx[k][i] = v
        at += len(m)
        idx["end"][i] = at
        pts.append(m)
    P = np.vstack(pts) if pts else np.zeros((0, 6))
    order = np.argsort(idx["pos"], kind="stable")
    idx = {k: v[order] for k, v in idx.items()}
    return {**{f"i_{k}": v for k, v in idx.items()}, "p_t": P[:, 0], "p_venue": P[:, 1].astype(np.int8),
            "p_x": P[:, 2], "p_y": P[:, 3], "p_fee": P[:, 4], "p_flag": P[:, 5].astype(np.int8)}


# ---------------------------------------------------------------- files

def save(tables: dict, d: Path, meta: dict) -> None:
    """rows/early.parquet, rows/steps.parquet, rows/paths.npz, rows/early.json (mints, gaps, meta)."""
    import polars as pl
    d.mkdir(parents=True, exist_ok=True)
    for name, fr in (("early", tables["rows"]), ("steps", tables["steps"])):
        cols = {k: (v.astype(np.float64) if k in ("t", "created_ms", "land_ms", "land2_ms") else v.astype(np.float32))
                for k, v in fr.items()}
        tmp = d / f"{name}.parquet.tmp"
        pl.DataFrame(cols).write_parquet(tmp, compression="zstd")
        tmp.replace(d / f"{name}.parquet")
    tmp = d / "paths.tmp.npz"
    np.savez_compressed(tmp, **tables["paths"])
    tmp.replace(d / "paths.npz")
    (d / "early.json").write_text(json.dumps({**meta, "mints": tables["mints"], "gaps": tables["gaps"]},
                                             default=str), encoding="utf-8")


def load(d: Path) -> dict:
    import polars as pl
    out = {}
    for name in ("early", "steps"):
        df = pl.read_parquet(d / f"{name}.parquet")
        out["rows" if name == "early" else "steps"] = {c: df[c].to_numpy().astype(np.float64) for c in df.columns}
    with np.load(d / "paths.npz") as z:
        out["paths"] = {k: z[k] for k in z.files}
    meta = json.loads((d / "early.json").read_text(encoding="utf-8"))
    out["mints"], out["gaps"], out["meta"] = meta.pop("mints"), meta.pop("gaps"), meta
    return out
