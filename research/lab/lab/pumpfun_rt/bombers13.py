"""Y13: the "bombers", pump.fun coins that go 50x, 100x, 1000x from their first trade. Can we see them in their first
seconds and catch them at our speed? PAPER ONLY.

    python -m lab.pumpfun_rt.bombers13                  all three parts, print the report, write bombers13.{json,md}
    python -m lab.pumpfun_rt.bombers13 --out DIR        the same, written into DIR
    python -m lab.pumpfun_rt.bombers13 --no-books       parts 1 and 2 only (no engine replay)

Pre-registered in results/pumpfun_bombers_prereg.md. Three parts on the record up to the cutoff:

  1. labels   every plain SOL curve's price path in chain time (curve trades, then its PumpSwap pool), from the price
              after its first trade (p0): the peak over 6 h and 24 h, the first time it reached 50x, 100x and 1000x,
              and the price 1, 3, 10, 30 and 60 s after creation
  2. signals  what a decision 3 s and 10 s after creation could know (the dev's buy, the early buys and whales, the
              buyers of one slot, the creator's and the early buyers' history in the record, the name, Y10's trend
              tracker), a purged walk-forward of LightGBM and a logistic baseline on "50x within 6 h", precision at
              the top 0.1 % and 1 % against the base rate, and fixed flags (any buy over 1, 3, 10 SOL ...)
  3. books    the engine's paper books (sim.Engine, pipeline.PaperExecutor: the fee, the latency and the failure model
              of every paper book) buying 0.05 SOL on each registered signal at the checkpoint, with the runner exit
              (a third at 3x, a third at 10x, the rest on a 50 % trail from the peak, a stop at -50 %, 24 h), at the
              paper model's latency (1 s), the same scaled to 3 s and 10 s, and Y9's measured live latency

Nothing here holds a wallet, reads a key, signs or sends anything; no existing book, strategy or the live service is
changed (the books here are the run's own).
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import hashlib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from . import reallat as RL
from . import select9 as Y9
from . import trendfeat as TF

# ---------------------------------------------------------------- registered (results/pumpfun_bombers_prereg.md)


def _ms(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


UNTIL_MS = _ms(2026, 10, 23, 18, 0)
LABEL_H_MS = 6 * 3_600_000                      # the label: the peak within 6 h of creation
DESC_H_MS = 24 * 3_600_000                      # part 1 also over 24 h
MULTS = (50, 100, 1000)
AT_S = (1, 3, 10, 30, 60)
DECISIONS = (3, 10)                             # seconds after creation
WHALES = (1.0, 3.0, 10.0)
EARLY_MS = 10_000                               # an "early buyer" bought within 10 s of creation
GAP_HEAD_MS = 60_000                            # a token whose first 60 s overlap a curve gap is not a row
FOLDS = (_ms(2026, 10, 21, 12), _ms(2026, 10, 22, 0), _ms(2026, 10, 22, 12), _ms(2026, 10, 23, 0),
         _ms(2026, 10, 23, 12))                 # test blocks start here; the last ends at the books' entry end
PURGE_MS = LABEL_H_MS                           # a training row's 6 h label must be over before its fold starts
LABEL = "b50"
TOPS = (0.001, 0.01)
BOOK_TOP = 0.01                                 # a G book buys a score in the top 1 % of its training scores
MIN_POS = 5                                     # a fold trains only with this many positives
SEP_AUC, SEP_LIFT, SEP_HITS = 0.75, 10.0, 3     # "separates": at 10 s, for 100x, AUC, top 1 % lift and hits
FLAGS = {"whale1": ("max_buy_sol", 1.0), "whale3": ("max_buy_sol", 3.0), "whale10": ("max_buy_sol", 10.0),
         "bundle3": ("slot0_buyers", 3), "dev1": ("dev_sol", 1.0), "creator_mig": ("cr_prev_mig", 1),
         "smart_buyer": ("eb_b50", 1)}
SIGNALS = {"G3": 3, "G10": 10, "W10": 10}       # the registered book signals and their decision second
RANDOM_MOD = 20                                 # the reference book R: one plain token in 20, at 10 s
STAKE_SOL = 0.05
EXITS = P.Exits(24 * 3600, 0.50, ((2.0, 1 / 3), (9.0, 2 / 3)), trail_after=0.0, trail_gap=0.50, dev_sell=False,
                pull=False)
GROUP = 5                                       # the "every signal" books: an engine per 5 picked tokens
LIMITS = P.Limits(STAKE_SOL, P.HARD_MAX_OPEN, P.HARD_MAX_EXPOSURE_SOL, P.HARD_MAX_DAILY_LOSS_SOL)
ENTRY_TAIL_MS = 60 * 60_000                     # signals stop an hour before the cutoff; open trades are marked
LATENCIES = ("L1", "L3", "L10", "B")
LATENCY_LABEL = {"L1": "1 s (the paper model)", "L3": "3 s (the model x 3)", "L10": "10 s (the model x 10)",
                 "B": "the measured live latency (Y9)"}
KEY = "Y13"                                     # every book's latency key: one draw per token and leg
MIN_HOURS = 10
NAN = float("nan")

FEATURES = ["dev_sol", "dev_share", "dev_sold", "n_buys", "n_sells", "n_buyers", "buy_sol", "sell_sol", "net_sol",
            "max_buy_sol", "top3_buy_sol", "whale1_n", "whale3_n", "whale10_n", "slot0_buyers", "slot0_sol",
            "max_slot_buyers", "mult", "progress",
            "cr_prev_n", "cr_prev_mig", "cr_prev_b50", "cr_prev_1h",
            "eb_n", "eb_bot_mean", "eb_mig", "eb_b50",
            "name_len", "sym_len", "sym_upper", "name_digits", "name_words", "uri_ipfs", "sym_copies_1h",
            "name_copies_1h"] + list(TF.TREND_FEATURES)


# ---------------------------------------------------------------- loading, in chain time

def load(root=None, until_ms: int = UNTIL_MS, log=print) -> dict:
    """The record up to until_ms, every row timed by its slot (store.slot_times, as sim.day_events): creates, curve
    trades, pool trades, migrations and gaps (polars frames; mints and wallets as categoricals)."""
    import polars as pl
    from . import store
    from .events import PUMP, PUMP_AMM
    day = datetime.fromtimestamp(until_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    days = [d for d in store.days(root) if d <= day]
    cat = pl.Categorical
    cr, tr, am, ot = [], [], [], []
    for d in days:                                           # per day, as sim.day_events times them
        c = store.read("creates", [d], root).select(
            "t", "slot", "tx", pl.col("mint").cast(cat), pl.col("creator").cast(cat), pl.col("user").cast(cat),
            "name", "symbol", "uri", "vs", "vt", "rt", "supply", "mayhem", "quote")
        t = store.read("trades", [d], root).select(
            "t", "slot", "tx", pl.col("mint").cast(cat), "buy", "sol", "tok", pl.col("user").cast(cat), "vs", "vt",
            "rt")
        a = store.read("amm", [d], root)
        if "vq" not in a.columns:                            # parts written before vq was recorded
            a = a.with_columns(pl.lit(None, dtype=pl.Int64).alias("vq"))
        a = a.select("t", "slot", "tx", pl.col("mint").cast(cat), "buy", "base", "quote", pl.col("user").cast(cat),
                     "pb", "pq", "vq")
        o = store.read("other", [d], root).select("kind", "t", "slot", pl.col("mint").cast(cat), "user", "t0")
        pairs = pl.concat([f.select("slot", "t") for f in (c, t, a, o)]).drop_nulls()
        first = (pairs.group_by("slot").agg(pl.col("t").min().alias("ct")).sort("slot", descending=True)
                 .with_columns(pl.col("ct").cum_min()))
        del pairs

        def timed(f):
            return (f.join(first, on="slot", how="left").with_columns(pl.coalesce("ct", "t").alias("ct"))
                    .filter(pl.col("ct") <= until_ms).drop("t"))
        cr.append(timed(c))
        tr.append(timed(t))
        am.append(timed(a))
        ot.append(o.join(first, on="slot", how="left").with_columns(pl.coalesce("ct", "t").alias("ct")))
        del c, t, a, o
        log(f"bombers13: read {d}")
    cr, tr, am, ot = (pl.concat(x, how="vertical_relaxed", rechunk=True) for x in (cr, tr, am, ot))
    mig = (ot.filter((pl.col("kind") == "migrate") & (pl.col("ct") <= until_ms)).group_by("mint")
           .agg(pl.col("ct").min().alias("mig_ct")))
    gaps = ot.filter(pl.col("kind") == "gap").select("user", "t0", "t").unique()
    return {"days": days, "creates": cr, "trades": tr, "amm": am, "mig": mig,
            "curve_gaps": _merge(gaps.filter(pl.col("user") == PUMP).select("t0", "t").rows()),
            "pool_gaps": _merge(gaps.filter(pl.col("user") == PUMP_AMM).select("t0", "t").rows())}


def _merge(spans) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted((int(a), int(b)) for a, b in spans if a is not None and b is not None):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def overlaps(spans: list[tuple[int, int]], a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """For each interval [a, b], whether it overlaps any span (merged, sorted)."""
    if not spans:
        return np.zeros(len(a), dtype=bool)
    s0 = np.array([x[0] for x in spans])
    s1 = np.array([x[1] for x in spans])
    i = np.searchsorted(s0, b, side="left")              # spans starting before b: indices < i
    j = np.maximum(i - 1, 0)
    prev_end = np.maximum.accumulate(s1)[j]
    return (i > 0) & (prev_end > a)


# ---------------------------------------------------------------- part 1: the price paths

def plain(cr):
    import polars as pl
    return cr.filter(pl.col("quote").is_null() & ~pl.col("mayhem").fill_null(False) & (pl.col("vs") > 0))


def paths(rec: dict):
    """One row per price state of a plain token in its first 24 h: (mint, ct, m = price / p0, src 0 curve, 1 pool).
    Curve: the reserves after each trade; pool: the effective reserves before each trade."""
    import polars as pl
    cr = plain(rec["creates"]).select("mint", pl.col("ct").alias("t0"), pl.col("slot").alias("slot0"))
    cv = (rec["trades"].join(cr, on="mint").filter((pl.col("vt") > 0) & (pl.col("ct") >= pl.col("t0")))
          .sort("mint", "ct", "slot", "tx")
          .select("mint", "t0", "ct", "slot", "tx", pl.lit(0, dtype=pl.Int8).alias("src"),
                  ((pl.col("vs") / C.LAMPORTS) / (pl.col("vt") / C.TOKEN_UNIT)).alias("price")))
    p0 = cv.group_by("mint", maintain_order=True).agg(pl.col("price").first().alias("p0"))
    eq = pl.max_horizontal(pl.col("pq") + pl.col("vq").fill_null(0), pl.lit(0))
    pool = (rec["amm"].join(cr, on="mint").filter((pl.col("pb") > 0) & (pl.col("ct") >= pl.col("t0")))
            .select("mint", "t0", "ct", "slot", "tx", pl.lit(1, dtype=pl.Int8).alias("src"),
                    ((eq / C.LAMPORTS) / (pl.col("pb") / C.TOKEN_UNIT)).alias("price")))
    path = (pl.concat([cv, pool]).filter(pl.col("ct") <= pl.col("t0") + DESC_H_MS).join(p0, on="mint")
            .filter(pl.col("p0") > 0).with_columns((pl.col("price") / pl.col("p0")).alias("m"),
                                                    (pl.col("ct") - pl.col("t0")).alias("dt"))
            .sort("mint", "ct", "src", "slot", "tx"))
    return path.select("mint", "dt", "m", "src")


def labels(rec: dict, path=None, until_ms: int = UNTIL_MS):
    """Per plain token: t0, p0's multiple path summary: peak6, peak24, t_<k> (s from creation, within 24 h, null if
    never), m_<s>s (the multiple s seconds after creation: the last state at or before it), b<k> (peak6 >= k),
    whether its 6 h and 24 h are in the record, migrated, a pool trade seen, a curve gap in its first 60 s."""
    import polars as pl
    path = paths(rec) if path is None else path
    cr = plain(rec["creates"]).select("mint", pl.col("ct").alias("t0"))
    aggs = [pl.col("m").filter(pl.col("dt") <= LABEL_H_MS).max().alias("peak6"), pl.col("m").max().alias("peak24"),
            (pl.col("src") == 1).any().alias("pool_seen"), pl.len().alias("n_states")]
    for k in MULTS:
        aggs.append((pl.col("dt").filter(pl.col("m") >= k).min() / 1000).alias(f"t_{k}"))
    for s in AT_S:
        aggs.append(pl.col("m").filter(pl.col("dt") <= s * 1000).last().alias(f"m_{s}s"))
    lab = cr.join(path.group_by("mint").agg(aggs), on="mint", how="inner")
    lab = lab.join(rec["mig"], on="mint", how="left").with_columns(
        pl.col("mig_ct").is_not_null().alias("migrated"),
        (pl.col("t0") + LABEL_H_MS <= until_ms).alias("known6"),
        (pl.col("t0") + DESC_H_MS <= until_ms).alias("known24"))
    for k in MULTS:
        lab = lab.with_columns((pl.col("peak6") >= k).alias(f"b{k}"))
    t0 = lab["t0"].to_numpy()
    gap = overlaps(rec["curve_gaps"], t0, t0 + GAP_HEAD_MS)
    return lab.with_columns(pl.Series("gap60", gap))


def describe(lab) -> dict:
    """Part 1's numbers: counts of 50x/100x/1000x within 6 h (tokens with their 6 h in the record) and 24 h, how
    fast, and the multiple left after 1 to 60 s for the bombers."""
    import polars as pl
    out = {}
    k6 = lab.filter(pl.col("known6"))
    out["tokens_6h"] = k6.height
    out["tokens_24h"] = lab.filter(pl.col("known24")).height
    out["migrated_6h"] = int(k6["migrated"].sum())
    out["migrated_no_pool_6h"] = int((k6["migrated"] & ~k6["pool_seen"]).sum())
    days = max((k6["t0"].max() - k6["t0"].min()) / 86_400_000, 1e-9) if k6.height else NAN
    out["days_6h"] = days
    for k in MULTS:
        b = k6.filter(pl.col(f"b{k}"))
        t = b[f"t_{k}"].drop_nulls().to_numpy()
        d = {"n": b.height, "rate": b.height / k6.height if k6.height else NAN, "per_day": b.height / days,
             "t_median_s": float(np.median(t)) if len(t) else NAN,
             "t_q": [float(np.quantile(t, q)) for q in (0.1, 0.25, 0.75, 0.9)] if len(t) else [],
             "n_24h": int(lab.filter(pl.col("known24") & (pl.col("peak24") >= k)).height)}
        left = {}
        for s in AT_S:
            m = b[f"m_{s}s"].to_numpy().astype(float)
            pk = b["peak6"].to_numpy().astype(float)
            ok = np.isfinite(m) & (m > 0)
            left[s] = {"mult_median": float(np.median(m[ok])) if ok.any() else NAN,
                       "left_median": float(np.median(pk[ok] / m[ok])) if ok.any() else NAN,
                       "left_q25": float(np.quantile(pk[ok] / m[ok], 0.25)) if ok.any() else NAN,
                       "share_left_10x": float(np.mean(pk[ok] / m[ok] >= 10)) if ok.any() else NAN}
        d["at"] = left
        out[f"x{k}"] = d
    allm = {s: float(np.nanmedian(k6[f"m_{s}s"].to_numpy().astype(float))) for s in AT_S} if k6.height else {}
    out["all_mult_median"] = allm
    return out


# ---------------------------------------------------------------- part 2: what a decision could know

def window_feats(rec: dict, lab, d: int):
    """The coin's own features from its curve trades timed at or before creation + d s (vectorized)."""
    import polars as pl
    cr = plain(rec["creates"]).select("mint", pl.col("ct").alias("t0"), pl.col("slot").alias("slot0"), "creator",
                                      pl.col("user").alias("payer"), "rt", "supply")
    cr = cr.join(lab.select("mint"), on="mint")
    w = (rec["trades"].join(cr, on="mint")
         .filter((pl.col("ct") >= pl.col("t0")) & (pl.col("ct") <= pl.col("t0") + d * 1000))
         .with_columns(((pl.col("user") == pl.col("creator")) | (pl.col("user") == pl.col("payer"))).fill_null(False)
                       .alias("dev"), (pl.col("sol") / C.LAMPORTS).alias("s")))
    ob = (~pl.col("dev")) & pl.col("buy")
    os_ = (~pl.col("dev")) & ~pl.col("buy")
    agg = w.sort("ct", "slot", "tx").group_by("mint").agg(
        pl.col("s").filter(pl.col("dev") & pl.col("buy")).sum().alias("dev_sol"),
        ((pl.col("tok").filter(pl.col("dev") & pl.col("buy")).sum().fill_null(0)
          - pl.col("tok").filter(pl.col("dev") & ~pl.col("buy")).sum().fill_null(0)) / pl.col("supply").first())
        .alias("dev_share"),
        (pl.col("dev") & ~pl.col("buy")).any().cast(pl.Float64).alias("dev_sold"),
        ob.sum().alias("n_buys"), os_.sum().alias("n_sells"),
        pl.col("user").filter(ob).n_unique().alias("n_buyers"),
        pl.col("s").filter(ob).sum().alias("buy_sol"), pl.col("s").filter(os_).sum().alias("sell_sol"),
        pl.col("s").filter(ob).max().alias("max_buy_sol"),
        pl.col("s").filter(ob).top_k(3).sum().alias("top3_buy_sol"),
        *[(pl.col("s").filter(ob) >= x).sum().alias(f"whale{x:g}_n") for x in WHALES],
        pl.col("user").filter(ob & (pl.col("slot") == pl.col("slot0"))).n_unique().alias("slot0_buyers"),
        pl.col("s").filter(ob & (pl.col("slot") == pl.col("slot0"))).sum().alias("slot0_sol"),
        pl.col("rt").last().alias("rt_last"),
        pl.col("user").filter(ob).unique().alias("buyers"))
    per_slot = (w.filter(ob).group_by("mint", "slot").agg(pl.col("user").n_unique().alias("k"))
                .group_by("mint").agg(pl.col("k").max().alias("max_slot_buyers")))
    f = cr.select("mint", "t0", "rt").join(agg, on="mint", how="left").join(per_slot, on="mint", how="left")
    f = f.with_columns((pl.col("buy_sol").fill_null(0) - pl.col("sell_sol").fill_null(0)).alias("net_sol"),
                       (1 - pl.col("rt_last") / pl.col("rt")).alias("progress"),
                       pl.lit(d, dtype=pl.Int32).alias("d"))
    m = lab.select("mint", pl.col(f"m_{d}s").alias("mult")) if f"m_{d}s" in lab.columns else None
    if m is not None:
        f = f.join(m, on="mint", how="left")
    return f


def _norm(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def name_feats(name: str, sym: str, uri: str) -> dict:
    name, sym, uri = name or "", sym or "", uri or ""
    return {"name_len": float(len(name)), "sym_len": float(len(sym)),
            "sym_upper": float(sym.isupper()), "name_digits": float(sum(c.isdigit() for c in name)),
            "name_words": float(len(name.split())), "uri_ipfs": float("ipfs" in uri.lower())}


class _Tok:
    """What trendfeat.Tracker asks of a token."""
    __slots__ = ("mint", "t0", "quote", "rt", "rt0")

    def __init__(self, mint, t0, quote, rt0):
        self.mint, self.t0, self.quote, self.rt, self.rt0 = mint, t0, quote, rt0, rt0 or C.INITIAL_RT

    def progress(self) -> float:
        return C.progress(self.rt, self.rt0)


def history_pass(rec: dict, lab, wins: dict, log=print) -> dict:
    """One pass in chain time over every creation, curve and pool trade, migration and decision: Y10's trend
    tracker, the creator's and the early buyers' history in the record, the copycat names. Returns
    {(mint, d): features}. Ties: trades and creations first, then the decisions, then the outcomes of that moment
    (an early buyer's coin counts for its history from creation + 10 s; a 50x from the moment it was reached)."""
    import polars as pl
    cr = rec["creates"]
    cmint = cr["mint"].to_physical().to_numpy()
    ccre = cr["creator"].to_physical().to_numpy()
    toks = {}
    plain_set = set(plain(cr)["mint"].to_physical().to_list())
    meta = {}
    for m, c, t, q, rt, nm, sy, ur in zip(cmint.tolist(), ccre.tolist(), cr["ct"].to_list(), cr["quote"].to_list(),
                                          cr["rt"].to_list(), cr["name"].to_list(), cr["symbol"].to_list(),
                                          cr["uri"].to_list()):
        if m not in toks:
            toks[m] = _Tok(m, t, q, rt)
            meta[m] = (c, nm, sy, ur)
    ev = []                                                   # (time, order, kind, payload)
    L = lab.select(pl.col("mint").to_physical().alias("m"), "t0", "t_50", "mig_ct")
    for m, t0, t50, mg in L.iter_rows():
        if t50 is not None:
            ev.append((t0 + int(t50 * 1000), 2, "b50", m))
        if mg is not None:
            ev.append((int(mg), 2, "mig", m))
    for m, t0 in zip(cmint.tolist(), cr["ct"].to_list()):
        ev.append((t0, 0, "create", m))
    buyers = {}
    for d, f in wins.items():
        for m, t0, b in f.select(pl.col("mint").to_physical(), "t0", pl.col("buyers").list.eval(
                pl.element().to_physical())).iter_rows():
            ev.append((t0 + d * 1000, 1, "decide", (m, d)))
            buyers[(m, d)] = b or []
    early = (rec["trades"].join(plain(cr).select("mint", pl.col("ct").alias("t0"), "creator",
                                                 pl.col("user").alias("payer")), on="mint")
             .filter(pl.col("buy") & (pl.col("ct") <= pl.col("t0") + EARLY_MS) & (pl.col("ct") >= pl.col("t0"))
                     & (pl.col("user") != pl.col("creator")).fill_null(True)
                     & (pl.col("user") != pl.col("payer")).fill_null(True))
             .group_by("mint").agg(pl.col("t0").first(), pl.col("user").unique().to_physical().alias("u")))
    for m, t0, us in early.select(pl.col("mint").to_physical(), "t0", "u").iter_rows():
        ev.append((t0 + EARLY_MS, 2, "early", (m, us)))
    log(f"bombers13: {len(ev):,} history events")
    # the trades for the trend tracker, merged by time in chunks
    tr = rec["trades"].select("ct", pl.col("mint").to_physical().alias("m"), "buy", "sol",
                              pl.col("user").to_physical().alias("u"), "rt").sort("ct", maintain_order=True)
    am = rec["amm"].select("ct", pl.col("mint").to_physical().alias("m"), "buy", "quote",
                           pl.col("user").to_physical().alias("u")).sort("ct", maintain_order=True)
    ev.sort(key=lambda e: (e[0], e[1]))
    trk = TF.Tracker()
    n_early = collections.Counter()
    n_mig = collections.Counter()
    n_b50 = collections.Counter()
    who = {}                                                  # mint -> early buyers (once their 10 s are over)
    cr_n = collections.Counter()
    cr_mig = collections.Counter()
    cr_b50 = collections.Counter()
    cr_recent: dict[int, collections.deque] = {}
    names = collections.deque()
    sym_c = collections.Counter()
    name_c = collections.Counter()
    out = {}
    ti = ai = ei = 0
    tct = tr["ct"].to_numpy()
    act = am["ct"].to_numpy()
    CH = 500_000
    tbuf = abuf = None
    tb0 = ab0 = -1
    t_start = time.time()
    while ei < len(ev) or ti < len(tct) or ai < len(act):
        te = ev[ei][0] if ei < len(ev) else math.inf
        tt = tct[ti] if ti < len(tct) else math.inf
        ta = act[ai] if ai < len(act) else math.inf
        if tt <= ta and tt <= te:                             # a trade before anything else of its moment
            if tb0 < 0 or ti >= tb0 + CH:
                tb0 = ti
                tbuf = tr.slice(ti, CH).select("m", "buy", "sol", "u", "rt").rows()
            m, buy, sol, u, rt = tbuf[ti - tb0]
            tok = toks.get(m)
            if tok is None:
                tok = toks[m] = _Tok(m, int(tt), None, 0)
            if rt is not None:
                tok.rt = rt
            trk.trade(tok, int(tt), bool(buy), sol or 0, u)
            ti += 1
            continue
        if ta <= te:
            if ab0 < 0 or ai >= ab0 + CH:
                ab0 = ai
                abuf = am.slice(ai, CH).select("m", "buy", "quote", "u").rows()
            m, buy, q, u = abuf[ai - ab0]
            tok = toks.get(m)
            if tok is None:
                tok = toks[m] = _Tok(m, int(ta), None, 0)
            trk.amm(tok, int(ta), bool(buy), q or 0, u)
            ai += 1
            continue
        t, _, kind, x = ev[ei]
        ei += 1
        if kind == "create":
            c, nm, sy, _ = meta[x]
            cr_n[c] += 1
            cr_recent.setdefault(c, collections.deque()).append(t)
            if x in plain_set:
                names.append((t, _norm(sy), _norm(nm)))
                sym_c[_norm(sy)] += 1
                name_c[_norm(nm)] += 1
        elif kind == "decide":
            m, d = x
            c, nm, sy, ur = meta[m]
            while names and names[0][0] < t - 3_600_000:
                _, s0, n0 = names.popleft()
                sym_c[s0] -= 1
                name_c[n0] -= 1
            q = cr_recent.get(c)
            while q and q[0] < t - 3_600_000:
                q.popleft()
            bs = buyers[(m, d)]
            f = {"cr_prev_n": float(cr_n[c] - 1), "cr_prev_mig": float(cr_mig[c]), "cr_prev_b50": float(cr_b50[c]),
                 "cr_prev_1h": float(len(q) - 1 if q else 0),
                 "eb_n": float(len(bs)), "eb_bot_mean": float(np.mean([n_early[u] for u in bs])) if bs else 0.0,
                 "eb_mig": float(sum(1 for u in bs if n_mig[u])), "eb_b50": float(sum(1 for u in bs if n_b50[u])),
                 "sym_copies_1h": float(sym_c[_norm(sy)] - 1), "name_copies_1h": float(name_c[_norm(nm)] - 1)}
            f.update(name_feats(nm, sy, ur))
            f.update(trk.features(toks[m], t))
            out[(m, d)] = f
        elif kind == "early":
            m, us = x
            who[m] = us
            for u in us:
                n_early[u] += 1
        elif kind == "mig":
            trk.migrated(toks.get(x) or _Tok(x, t, None, 0), t)
            cr_mig[meta[x][0]] += 1 if x in meta else 0
            for u in who.get(x, ()):
                n_mig[u] += 1
        elif kind == "b50":
            if x in meta:
                cr_b50[meta[x][0]] += 1
            for u in who.get(x, ()):
                n_b50[u] += 1
    log(f"bombers13: history pass in {time.time() - t_start:.0f} s")
    return out


def table(rec: dict, lab, log=print) -> dict[int, dict[str, np.ndarray]]:
    """Per decision second: the rows (every plain token whose first 60 s are free of a curve gap), FEATURES, the
    labels, t0 and the mint."""
    import polars as pl
    wins = {d: window_feats(rec, lab, d) for d in DECISIONS}
    hist = history_pass(rec, lab, wins, log)
    out = {}
    lab_cols = ["mint", "t0", "known6", "gap60", "peak6", "peak24"] + [f"b{k}" for k in MULTS]
    for d, f in wins.items():
        f = f.join(lab.select(lab_cols).drop("t0"), on="mint").filter(~pl.col("gap60")).sort("t0", "mint")
        mp = f["mint"].to_physical().to_list()
        own = [c for c in FEATURES if c in f.columns]
        cols = {c: f[c].cast(pl.Float64).fill_null(0.0 if c not in ("mult", "progress") else NAN).to_numpy()
                for c in own}
        for c in FEATURES:
            if c not in cols:
                cols[c] = np.array([hist.get((m, d), {}).get(c, NAN) for m in mp], dtype=float)
        cols.update(mint=f["mint"].cast(pl.Utf8).to_numpy(), t0=f["t0"].to_numpy(), known6=f["known6"].to_numpy(),
                    peak6=f["peak6"].to_numpy().astype(float), peak24=f["peak24"].to_numpy().astype(float))
        for k in MULTS:
            cols[f"b{k}"] = f[f"b{k}"].to_numpy().astype(bool)
        out[d] = cols
    return out


# ---------------------------------------------------------------- part 2: the walk-forward

def _gbm_fit(X: np.ndarray, y: np.ndarray):
    import lightgbm as lgb
    from .selmodel import PARAMS
    clf = lgb.LGBMClassifier(**PARAMS)
    clf.fit(X, y)
    return clf.booster_


def _auc(p: np.ndarray, y: np.ndarray) -> float:
    from .model import auc
    return auc(p, y) if 0 < y.sum() < len(y) else NAN


def folds(t0: np.ndarray, until_ms: int = UNTIL_MS) -> list[tuple[int, int, int]]:
    """(train end, test start, test end) per fold: test blocks from FOLDS, the last ends at the books' entry end; the
    training rows are the tokens created before the fold start less the purge."""
    ends = list(FOLDS[1:]) + [until_ms - ENTRY_TAIL_MS]
    return [(s - PURGE_MS, s, e) for s, e in zip(FOLDS, ends) if e > s]


def walk_forward(tab: dict[str, np.ndarray], label: str = LABEL, until_ms: int = UNTIL_MS, log=print) -> dict:
    """GBM and logistic out of fold per fold; scores for every test row (also those whose 6 h are not in the record,
    for the books), the G book's threshold per fold, the gain importance of the last fold."""
    from .model import logistic
    X = np.column_stack([tab[c] for c in FEATURES])
    y = tab[label].astype(int)
    known = tab["known6"].astype(bool)
    t0 = tab["t0"]
    gbm = np.full(len(y), NAN)
    lr = np.full(len(y), NAN)
    thr = np.full(len(y), NAN)
    fold_id = np.full(len(y), -1)
    info = []
    imp = None
    for k, (tr_end, s, e) in enumerate(folds(t0, until_ms)):
        tr = (t0 < tr_end) & known
        te = (t0 >= s) & (t0 < e)
        npos = int(y[tr].sum())
        info.append({"fold": k, "train_rows": int(tr.sum()), "train_pos": npos, "test_rows": int(te.sum())})
        if npos < MIN_POS or not te.any():
            continue
        b = _gbm_fit(X[tr], y[tr])
        gbm[te] = b.predict(X[te])
        thr[te] = float(np.quantile(b.predict(X[tr]), 1 - BOOK_TOP))
        lr[te] = logistic(X[tr], y[tr], X[te])
        fold_id[te] = k
        imp = sorted(zip(FEATURES, b.feature_importance("gain")), key=lambda x: -x[1])
    log(f"bombers13: walk-forward folds {info}")
    return {"gbm": gbm, "lr": lr, "thr": thr, "fold": fold_id, "folds": info,
            "importance": [(f, float(g)) for f, g in (imp or [])[:15]]}


def precision_at(score: np.ndarray, y: np.ndarray, fold: np.ndarray, q: float) -> tuple[int, int]:
    """Hits and picks in the top q of each fold's rows by score (at least one per fold), pooled."""
    hits = n = 0
    for k in np.unique(fold[fold >= 0]):
        i = np.where(fold == k)[0]
        s = score[i]
        ok = np.isfinite(s)
        i, s = i[ok], s[ok]
        if not len(i):
            continue
        top = max(1, math.ceil(q * len(i)))
        pick = i[np.argsort(-s, kind="stable")[:top]]
        hits += int(y[pick].sum())
        n += top
    return hits, n


def evaluate_signals(tabs: dict, wfs: dict) -> dict:
    """Part 2's tables, out of sample (rows with a fold score and their 6 h in the record)."""
    out = {}
    for d, tab in tabs.items():
        wf = wfs[d]
        oos = (wf["fold"] >= 0) & tab["known6"].astype(bool)
        r = {"rows": int(oos.sum()), "folds": wf["folds"], "importance": wf["importance"]}
        for k in MULTS:
            y = tab[f"b{k}"][oos].astype(int)
            base = float(y.mean()) if len(y) else NAN
            rk = {"pos": int(y.sum()), "base": base}
            for name in ("gbm", "lr"):
                s = wf[name][oos]
                rk[name] = {"auc": _auc(s, y)}
                for q in TOPS:
                    h, n = precision_at(s, y, wf["fold"][oos], q)
                    rk[name][f"top{q:g}"] = {"hits": h, "n": n, "prec": h / n if n else NAN,
                                             "lift": (h / n) / base if n and base > 0 else NAN}
            for fl, (col, x) in FLAGS.items():
                on = tab[col][oos] >= x
                rk.setdefault("flags", {})[fl] = {"n": int(on.sum()), "share": float(on.mean()) if len(on) else NAN,
                                                  "hits": int(y[on].sum()),
                                                  "prec": float(y[on].mean()) if on.any() else NAN}
            g = wf["gbm"][oos] >= wf["thr"][oos]
            rk["book_pick"] = {"n": int(g.sum()), "hits": int(y[g].sum()),
                               "prec": float(y[g].mean()) if g.any() else NAN}
            r[f"x{k}"] = rk
        # what the bombers looked like: medians, 100x against the rest, all rows with their 6 h in the record
        kn = tab["known6"].astype(bool)
        b = kn & tab["b100"]
        o = kn & ~tab["b100"]
        r["profile"] = {c: (float(np.nanmedian(tab[c][b])) if b.any() else NAN,
                            float(np.nanmedian(tab[c][o])) if o.any() else NAN,
                            float(np.nanmean(tab[c][b])) if b.any() else NAN,
                            float(np.nanmean(tab[c][o])) if o.any() else NAN)
                        for c in FEATURES if c in PROFILE}
        r["uni_auc"] = {}
        y = tab["b100"][oos].astype(int)
        for c in PROFILE:
            v = tab[c][oos]
            ok = np.isfinite(v)
            a = _auc(v[ok], y[ok]) if ok.any() else NAN
            r["uni_auc"][c] = a
        r["separates"] = {name: separates(r["x100"][name]) for name in ("gbm", "lr")}
        out[d] = r
    return out


PROFILE = ["dev_sol", "dev_share", "n_buys", "n_buyers", "buy_sol", "max_buy_sol", "whale1_n", "whale3_n",
           "slot0_buyers", "slot0_sol", "max_slot_buyers", "mult", "progress", "cr_prev_n", "cr_prev_mig",
           "cr_prev_b50", "eb_bot_mean", "eb_mig", "eb_b50", "name_len", "sym_copies_1h", "tr_rank_1m",
           "mkt_buy_sol_15m", "mkt_heat_rel"]


def picks(tabs: dict, wfs: dict, until_ms: int = UNTIL_MS) -> dict[str, dict[str, int]]:
    """The books' entries: signal -> {mint: decision second}. G<d>: the GBM score at or over its fold's threshold;
    W10: a buy of 3 SOL or more by someone else than the dev within 10 s; R: one plain token in RANDOM_MOD by its
    mint's hash. Only tokens created in a test block (from the first fold to the entry end)."""
    lo, hi = FOLDS[0], until_ms - ENTRY_TAIL_MS
    out = {}
    for name, d in SIGNALS.items():
        tab, wf = tabs[d], wfs[d]
        win = (tab["t0"] >= lo) & (tab["t0"] < hi)
        if name.startswith("G"):
            on = win & (wf["fold"] >= 0) & (wf["gbm"] >= wf["thr"])
        else:
            on = win & (tab["max_buy_sol"] >= 3.0)
        out[name] = {m: d for m in tab["mint"][on]}
    tab = tabs[10]
    win = (tab["t0"] >= lo) & (tab["t0"] < hi)
    out["R"] = {m: 10 for m, w in zip(tab["mint"], win) if w and _h(m) % RANDOM_MOD == 0}
    return out


def _h(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")


# ---------------------------------------------------------------- part 3: the books

@dataclasses.dataclass(frozen=True)
class BomberStrategy(P.Strategy):
    """A checkpoint at creation + w_s seconds that buys the registered signal's picks (p["picks"])."""

    def wants_checkpoint(self, tok, t: int) -> bool:
        return tok.mint in self.p["picks"]


class BomberPipe(P.Pipeline):
    """A paper book whose positions still open at the end of the record are valued at their mark then (what selling
    the rest would bring after the pool's or the curve's fee, less one transaction)."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.marked: list[dict] = []

    def finish(self, t_end: float) -> None:
        eng = self.eng
        for p in list(self.pos.values()):
            if p["state"] != "open":
                continue
            c = eng.cost_of(p["rule"])
            v = eng.sale_value(eng.tokens.get(p["mint"]), p["left"], c) or 0
            pnl = p["proceeds_l"] + v - p["cost_l"] - p["fees_l"] - c.tx_lamports()
            stake = p["stake_l"] or 1
            self.marked.append({"rule": p["rule"], "mint": p["mint"], "signal_ms": p["signal_ms"],
                                "land_ms": p["land_ms"], "exit_ms": int(t_end), "exit_why": "open at the cutoff",
                                "pnl_sol": pnl / C.LAMPORTS, "ret": pnl / stake, "legs": p["legs"],
                                "hold_s": (t_end - p["land_ms"]) / 1000})


def latencies() -> dict[str, C.Costs]:
    """L1: the paper engine's own model (curve.Costs: median 1 s, 0.4 to 3 s); L3 and L10 the same scaled 3 and 10
    times (buys and sales); B: Y9's measured Sender fills (buy median about 10 s, sale about 4 s). 0.001005 SOL a
    transaction everywhere."""
    a = C.Costs(priority_sol=RL.priority_for(Y9.TX_FEE_SOL))
    return {"L1": a, "L3": a.scaled(latency=3.0), "L10": a.scaled(latency=10.0), "B": Y9.scenarios()["B"]}


def books(pk: dict[str, dict[str, int]], only: set | None = None) -> tuple[list[BomberStrategy], dict[str, C.Costs]]:
    """Every signal (and R) once per latency, `Y13_<sig>@<lat>`, buying its picks (those in `only` if given)."""
    lat = latencies()
    out, costs = [], {}
    for sig, ms in pk.items():
        d = SIGNALS.get(sig, 10)
        mine = frozenset(m for m in ms if only is None or m in only)
        if not mine:
            continue
        for a in LATENCIES:
            name = f"Y13_{sig}@{a}"
            out.append(BomberStrategy(name, "B", "checkpoint", EXITS.ladder[-1][0], EXITS.sl, EXITS.time_s,
                                      {"w_s": d, "picks": mine, "base": KEY}, f"Y13 {sig} at creation + {d} s",
                                      exits=EXITS, flt={}, stake_sol=STAKE_SOL))
            costs[name] = lat[a]
    return out, costs


def _engine(strats, costs, until_ms):
    from . import sim
    eng = sim.Engine([], decisions=False, rule_costs=costs, entry_until=until_ms - ENTRY_TAIL_MS)
    pipes = [eng.add_pipe(BomberPipe(eng, [s], P.PaperExecutor(), limits=LIMITS, name=s.name)) for s in strats]
    return eng, pipes


def replay(pk: dict, root=None, until_ms: int = UNTIL_MS, log=print) -> dict:
    """One pass over the record in chain order (sim.day_events) feeding two kinds of engines, each book with the
    code's caps (5 open, 0.6 SOL exposure, 1.0 SOL daily loss):
      U  every signal: the picked tokens in groups of GROUP, one engine per group (a book never holds more than GROUP
         positions, so no cap binds: what every pick would have made)
      C  one engine with every picked token: the books as one bot with the caps would have traded them
    An engine sees only its tokens' rows and the gaps; a position depends on its own token's state only."""
    from . import sim, store
    day = datetime.fromtimestamp(until_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    days = [d for d in store.days(root) if d <= day]
    mints = sorted(set().union(*pk.values()), key=_h)
    group_of = {m: i // GROUP for i, m in enumerate(mints)}
    engines = {}
    for g in range(-(-len(mints) // GROUP)):
        only = set(mints[g * GROUP:(g + 1) * GROUP])
        engines[g] = _engine(*books(pk, only), until_ms)
    engines["C"] = _engine(*books(pk), until_ms)
    t0 = time.time()
    last = 0
    for d in days:
        n = 0
        for table, row in sim.day_events(d, root):
            t = row.get("t") or 0
            if t > until_ms:
                break
            if table == "other" and row.get("kind") == "gap":
                for eng, _ in engines.values():
                    sim.feed_row(eng, table, row)
                continue
            g = group_of.get(row.get("mint"))
            if g is None:
                continue
            sim.feed_row(engines[g][0], table, row)
            sim.feed_row(engines["C"][0], table, row)
            last = max(last, t)
            n += 1
        log(f"bombers13: replayed {d}, {n:,} rows of picked tokens")
    out = collections.defaultdict(list)
    skips = collections.Counter()
    for g, (eng, pipes) in engines.items():
        eng.finish(until_ms)
        kind = "C" if g == "C" else "U"
        for pipe in pipes:
            pipe.finish(until_ms)
            book = f"{kind}:{pipe.name}"
            for t in pipe.closed:
                out[book].append({"mint": t["mint"], "signal_ms": t["signal_ms"], "ret": t["ret"],
                                  "pnl_sol": t["pnl_sol"], "exit_why": t.get("exit_why"), "hold_s": t.get("hold_s"),
                                  "legs": t.get("legs"), "failed": False, "open": False})
            for f in pipe.failed:
                out[book].append({"mint": f["mint"], "signal_ms": f["signal_ms"], "ret": f["pnl_sol"] / STAKE_SOL,
                                  "pnl_sol": f["pnl_sol"], "exit_why": "failed buy: " + f["why"], "hold_s": None,
                                  "legs": 0, "failed": True, "open": False})
            for t in pipe.marked:
                out[book].append(t | {"failed": False, "open": True})
        for (nm, w), c in eng.skipped.items():
            skips[f"{kind}:{nm}: {w}"] += c
    log(f"bombers13: replay in {time.time() - t0:.0f} s, {len(engines) - 1} group engines")
    return {"books": {k: sorted(v, key=lambda e: e["signal_ms"]) for k, v in out.items()}, "skips": dict(skips)}


def book_stats(e: list[dict], big: dict[str, float], days: float) -> dict:
    """One book: entries, mean, median, P&L, band, per day, the trades on coins that went 100x within 6 h of
    creation (by the label) against the rest, and how many of the rest one of them pays for."""
    from .study import boot_mean
    out = {"n": len(e), "failed": sum(1 for x in e if x["failed"]), "open": sum(1 for x in e if x["open"])}
    if not e:
        return out
    r = np.array([x["ret"] for x in e])
    pnl = np.array([x["pnl_sol"] for x in e])
    hrs = len({x["signal_ms"] // 3_600_000 for x in e})
    lo, hi = boot_mean(e) if hrs >= MIN_HOURS else (NAN, NAN)
    hit = np.array([big.get(x["mint"], 0) >= 100 for x in e])
    win_p = pnl[hit]
    rest = pnl[~hit]
    loss = -rest.mean() if len(rest) and rest.mean() < 0 else NAN
    k = max(1, math.ceil(0.05 * len(e)))
    out.update(hours=hrs, mean=float(r.mean()), median=float(np.median(r)), pnl_sol=float(pnl.sum()),
               win=float((pnl > 0).mean()), band=(lo, hi), per_day_sol=float(pnl.sum() / days) if days > 0 else NAN,
               per_day_n=len(e) / days if days > 0 else NAN, best_sol=float(pnl.max()),
               top5_share=float(np.sort(pnl)[::-1][:k].sum() / pnl.sum()) if pnl.sum() > 0 else None,
               exits=dict(collections.Counter((x["exit_why"] or "?").split(":")[0] for x in e)),
               bombers=int(hit.sum()), bomber_mean_sol=float(win_p.mean()) if len(win_p) else NAN,
               bomber_best_ret=float(r[hit].max()) if hit.any() else NAN,
               rest_mean_sol=float(rest.mean()) if len(rest) else NAN,
               losers_per_bomber=float(win_p.mean() / loss) if len(win_p) and loss == loss else NAN,
               x10_trades=int(sum(1 for x in r if x >= 9)), x3_trades=int(sum(1 for x in r if x >= 2)))
    out["pays"] = bool(lo == lo and lo > 0 and pnl.sum() > 0)
    return out


def evaluate_books(rep: dict, lab, until_ms: int = UNTIL_MS) -> dict:
    import polars as pl
    big = dict(zip(lab["mint"].cast(pl.Utf8).to_list(), lab["peak6"].fill_null(0).to_list()))
    days = (until_ms - ENTRY_TAIL_MS - FOLDS[0]) / 86_400_000
    return {"days": days, "books": {k: book_stats(v, big, days) for k, v in sorted(rep["books"].items())},
            "skips": rep["skips"]}


def separates(m: dict) -> bool:
    """The registered rule (at 10 s): AUC for 100x at least 0.75 and the top 1 % at least 10 times the base rate with
    at least 3 hits."""
    top = m["top0.01"]
    return bool(m["auc"] == m["auc"] and m["auc"] >= SEP_AUC and top["hits"] >= SEP_HITS
                and top["lift"] == top["lift"] and top["lift"] >= SEP_LIFT)


def speed(books_: dict, sig: str) -> str | None:
    """The slowest latency at which the signal's U book pays, None if it pays at none."""
    ok = [a for a in LATENCIES if books_.get(f"U:Y13_{sig}@{a}", {}).get("pays")]
    return max(ok, key=lambda a: (a == "B", {"L1": 1, "L3": 3, "L10": 10}.get(a, 0))) if ok else None


def headline(sig_eval: dict) -> str:
    """The registered pick among the book signals: the highest out-of-sample precision for 100x at the book's own
    rule (G: the fold threshold; W10: the flag whale3), ties to G10."""
    prec = {"G3": sig_eval[3]["x100"]["book_pick"]["prec"], "G10": sig_eval[10]["x100"]["book_pick"]["prec"],
            "W10": sig_eval[10]["x100"]["flags"]["whale3"]["prec"]}
    best = max(SIGNALS, key=lambda s: (np.nan_to_num(prec[s], nan=-1.0), s == "G10"))
    return best


# ---------------------------------------------------------------- report

def _p(x, nd=1) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:+.{nd}f} %"


def _r(x, nd=2) -> str:
    return "n/a" if x is None or x != x else f"{x * 100:.{nd}f} %"


def _f(x, nd=1) -> str:
    return "n/a" if x is None or x != x else f"{x:,.{nd}f}"


def report_md(res: dict) -> str:
    d1, sig, bk = res["describe"], res["signals"], res.get("books")
    L = [f"# Y13 bombers: run of {res['run_utc']}", "",
         f"Record {res['days'][0]} to the cutoff {_utc(res['until_ms'])}; {d1['tokens_6h']:,} plain tokens with their "
         f"6 h in the record over {d1['days_6h']:.2f} days, {d1['migrated_6h']:,} migrated "
         f"({d1['migrated_no_pool_6h']} without a pool trade seen).", "",
         "## 1. How many, how fast, how much is left", "",
         "| from the first trade | within 6 h | per day | rate | within 24 h | median time | 25 to 75 % |",
         "|---|---|---|---|---|---|---|"]
    for k in MULTS:
        x = d1[f"x{k}"]
        q = x["t_q"]
        L.append(f"| {k}x | {x['n']} | {_f(x['per_day'])} | {_r(x['rate'], 3)} | {x['n_24h']} | "
                 f"{_f(x['t_median_s'] / 60)} min | {_f(q[1] / 60) if q else 'n/a'} to "
                 f"{_f(q[2] / 60) if q else 'n/a'} min |")
    L += ["", "The multiple of p0 already reached s seconds after creation, and the multiple still ahead to the 6 h "
          "peak (median; share with 10x or more still ahead):", "",
          "| coins | " + " | ".join(f"{s} s" for s in AT_S) + " |", "|---|" + "---|" * len(AT_S)]
    for k in MULTS:
        a = d1[f"x{k}"]["at"]
        L.append(f"| {k}x: reached | " + " | ".join(_f(a[s]['mult_median'], 2) for s in AT_S) + " |")
        L.append(f"| {k}x: ahead | " + " | ".join(f"{_f(a[s]['left_median'])} ({_r(a[s]['share_left_10x'], 0)})"
                                               for s in AT_S) + " |")
    L.append("| all: reached | " + " | ".join(_f(d1["all_mult_median"].get(s), 2) for s in AT_S) + " |")
    L += ["", "## 2. What the first seconds show (out of sample, purged walk-forward)", ""]
    for d in DECISIONS:
        s = sig[d]
        L += [f"### Decision at creation + {d} s ({s['rows']:,} rows out of sample)", "",
              "| label | positives | base | GBM AUC | top 0.1 % | top 1 % | logistic AUC | top 0.1 % | top 1 % | "
              "book rule (top 1 % of training) |", "|---|---|---|---|---|---|---|---|---|---|"]
        for k in MULTS:
            x = s[f"x{k}"]
            g, lr_, bp = x["gbm"], x["lr"], x["book_pick"]

            def pr(z):
                return f"{_r(z['prec'])} ({z['hits']}/{z['n']})"
            L.append(f"| {k}x | {x['pos']} | {_r(x['base'], 3)} | {_f(g['auc'], 3)} | {pr(g['top0.001'])} | "
                     f"{pr(g['top0.01'])} | {_f(lr_['auc'], 3)} | {pr(lr_['top0.001'])} | {pr(lr_['top0.01'])} | "
                     f"{pr(bp)} |")
        L += ["", "| flag | coins | share | 50x | 100x | 1000x |", "|---|---|---|---|---|---|"]
        for fl in FLAGS:
            a = [s[f"x{k}"]["flags"][fl] for k in MULTS]
            L.append(f"| {fl} | {a[0]['n']:,} | {_r(a[0]['share'])} | " +
                     " | ".join(f"{_r(z['prec'])} ({z['hits']})" for z in a) + " |")
        yn = {k: "yes" if v else "no" for k, v in s["separates"].items()}
        L += ["", f"Separates by the registered rule: GBM {yn['gbm']}, logistic {yn['lr']}"
                  + (" (judged at 10 s)." if d == 10 else " (not judged at 3 s)."),
              "", "Folds: " + "; ".join(f"{f['fold']}: {f['train_rows']:,} training rows, {f['train_pos']} positive, "
                                         f"{f['test_rows']:,} test" for f in s["folds"]),
              "Gain importance (last fold): " + ", ".join(f"{a}" for a, _ in s["importance"][:10]), ""]
    s10 = sig[10]
    L += ["What the 100x coins looked like at 10 s against the rest (all rows with their 6 h; median, mean; univariate "
          "AUC out of sample):", "", "| feature | 100x median | rest median | 100x mean | rest mean | AUC |",
          "|---|---|---|---|---|---|"]
    for c, (a, b, ma, mb) in s10["profile"].items():
        L.append(f"| {c} | {_f(a, 2)} | {_f(b, 2)} | {_f(ma, 2)} | {_f(mb, 2)} | {_f(s10['uni_auc'].get(c), 3)} |")
    if bk:
        L += ["", f"## 3. Paper books, 0.05 SOL, runner exit (out of sample, {bk['days']:.2f} days)", "",
              f"Headline signal (registered pick): **{res['headline']}**; the slowest latency at which its U book "
              f"pays: **{res.get('speed') or 'none'}**. U: every pick on its own (no cap binds); "
              "C: one bot with the code's caps (5 open, 0.6 SOL, 1.0 SOL a day).", "",
              "| book | signal | latency | entries | per day | failed | open at end | mean | band | median | win | "
              "P&L SOL | SOL per day | 100x coins | their mean SOL | the rest's mean SOL | losers per 100x | pays |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for kind in ("U", "C"):
            for sig_ in list(SIGNALS) + ["R"]:
                for a in LATENCIES:
                    x = bk["books"].get(f"{kind}:Y13_{sig_}@{a}")
                    if not x or not x.get("n"):
                        L.append(f"| {kind} | {sig_} | {a} | 0 |" + " |" * 14)
                        continue
                    L.append(f"| {kind} | {sig_} | {a} | {x['n']} | {_f(x['per_day_n'])} | {x['failed']} | "
                             f"{x['open']} | {_p(x['mean'])} | {_p(x['band'][0])} to {_p(x['band'][1])} | "
                             f"{_p(x['median'])} | {_r(x['win'], 0)} | {x['pnl_sol']:+.3f} | {x['per_day_sol']:+.3f} | "
                             f"{x['bombers']} | {_f(x['bomber_mean_sol'], 3)} | {_f(x['rest_mean_sol'], 4)} | "
                             f"{_f(x['losers_per_bomber'])} | {'yes' if x['pays'] else 'no'} |")
        sk = {k: v for k, v in bk["skips"].items() if "not in" not in k and "picks" not in k}
        L += ["", "Skips: " + ("; ".join(f"{k} {v}" for k, v in sorted(sk.items())) or "none")]
    return "\n".join(L) + "\n"


def _utc(ms) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------- the run

def run(root=None, until_ms: int = UNTIL_MS, with_books: bool = True, log=print) -> dict:
    rec = load(root, until_ms, log)
    lab = labels(rec, until_ms=until_ms)
    log(f"bombers13: {lab.height:,} plain tokens labelled")
    d1 = describe(lab)
    tabs = table(rec, lab, log)
    wfs = {d: walk_forward(tabs[d], until_ms=until_ms, log=log) for d in DECISIONS}
    sig = evaluate_signals(tabs, wfs)
    res = {"run_utc": _utc(time.time() * 1000), "days": rec["days"], "until_ms": until_ms, "describe": d1,
           "signals": sig, "headline": headline(sig)}
    pk = picks(tabs, wfs, until_ms)
    res["picks_n"] = {k: len(v) for k, v in pk.items()}
    log(f"bombers13: picks {res['picks_n']}")
    del rec, tabs
    if with_books:                                           # in a fresh process: the record's frames are gone
        import gc
        import multiprocessing as mp
        gc.collect()
        with mp.get_context("spawn").Pool(1) as pool:
            rep = pool.apply(replay, (pk, root, until_ms))
        res["books"] = evaluate_books(rep, lab, until_ms)
        res["speed"] = speed(res["books"]["books"], res["headline"])
        res["entries"] = rep["books"]
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--until-ms", type=int, default=UNTIL_MS)
    ap.add_argument("--out", default=None, help="directory for bombers13.json and bombers13.md (default: the reports)")
    ap.add_argument("--no-books", action="store_true", help="parts 1 and 2 only")
    a = ap.parse_args(argv)
    from .. import report as rep
    out = Path(a.out) if a.out else rep.REPORTS / "pumpfun_rt"
    out.mkdir(parents=True, exist_ok=True)
    res = run(until_ms=a.until_ms, with_books=not a.no_books)
    md = report_md(res)
    keep = {k: v for k, v in res.items() if k != "entries"}
    (out / "bombers13.json").write_text(json.dumps(keep, indent=1, default=str), encoding="utf-8")
    (out / "bombers13.md").write_text(md, encoding="utf-8")
    if "entries" in res:
        (out / "bombers13_entries.json").write_text(json.dumps(res["entries"], default=str), encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
