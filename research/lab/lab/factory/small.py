"""F2: the factory's small-account mode, daily: strategies for a 0 to 100 EUR wallet at the real costs.

    python -m lab.factory small                  search, held-back checks, shadow step and review, report
    python -m lab.factory small --budget 20      a different number of new genomes (default 60,
                                                 PYTHIA_FACTORY_SMALL_BUDGET)
    python -m lab.factory small --offline        the lab's ETF copy only (no Yahoo)
    python -m lab.factory small --export-seed    the ledger and held-back log to results/factory_small_seed

The weekly factory (grammar.py, build.py) searches big coin universes at a
cost in basis points. At 40 or 100 EUR what decides is S1's and S2's
(lab.experiments.smallaccount, smallaccount_s2): the 5 USDC minimum, a fixed
network fee and Sender tip a swap, the SOL reserve, the way in, and that only a
few assets are worth holding. This mode keeps all of that:

  assets     BTC, ETH, SOL (the panel's daily bars), the S&P 500 token SPYx, the
             Nasdaq 100 token QQQx and the gold token PAXG (their underlying's
             adjusted daily close, SPY, QQQ and GLD, times S2's measured drift a
             year, and on the price the wallet trades at a draw of S2's measured
             premium at the close around its mean: the tracking error); USDC is
             the cash. At most MAX_HELD held at once.
  grammar    a named asset set, a signal (hold, momentum, moving average,
             Donchian, low vol), up to 2 filters (BTC or SPY regime, absolute
             momentum, vol cap, the asset's own trend), at most 3 held by signal,
             90-day momentum or low vol, equal or inverse vol, slots or the whole
             book, a vol target, daily or weekly, a rebalance band of 0, 10 or 25 %
             of the book (an asset nearer its target than that is not traded).
  costs      S2's venue: half the recorded Jupiter round trip at the order's size,
             the network fee plus the Sender tip at the day's SOL price, MIN_TRADE
             5 USDC, dust, the SOL reserve held idle and the way in as one SOL to
             USDC swap; every genome as a wallet at 40 and at 100 EUR.
  search     a budget of new genomes a day (random, mutation, crossover of the
             best), in sample 2020-08-01 to 2023-12-31 only; fitness the worse
             in-sample Sharpe of the two wallets, less 0.03 a moving part, less
             a penalty for a drawdown over 20 % or a book almost always in USDC.
  ledger     <data>/factory/small/ledger.jsonl, its own namespace: one line per
             genome ever tried, only grows; the deflation pool is S1's and S2's
             16 trials plus every line, so the bar rises with every run;
             results/factory_small_seed (the first run's trials) is merged first.
  held back  HOLDOUT_PER_RUN genomes a run (best fitness, both halves positive,
             mutually different) see 2024-01-01 to the last fresh ETF close; a
             survivor has a drawdown under 20 % and ends above holding SPYx after
             costs, both at 40 and at 100 EUR, and is still positive filled a
             close late. Holding SPYx and holding BTC are shown everywhere.
  shadows    a survivor runs forward as a 40 EUR paper wallet with the same
             costs (at most MAX_ACTIVE, MAX_NEW_PER_RUN new a run); every recorded
             day is frozen. After SHADOW_DAYS days (and every SHADOW_DAYS after)
             it is retired unless its daily Sharpe beats a 40 EUR SPYx wallet
             started the same day. Nothing is promoted on its own: a shadow that
             keeps beating is a candidate for a hand study.
  report     reports/smallaccount/factory.md and factory.json (next to the S1 and
             S2 paper books' latest.md): trials, the bar, survivors, shadows,
             wallets in EUR.

Resumable: every genome is in the ledger the moment it is evaluated, a rerun on
the same day only does what is left of the budget, the held-back log is keyed
by run and genome, and a shadow appends only the days after its last row.
Nothing here signs, sends or holds a key; nothing reaches the engine or money.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import os
import random
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import report
from ..experiments import fam_common as fc
from ..experiments import smallaccount as s1
from ..experiments import smallaccount_s2 as s2
from . import ledger as lg

NAME = "smallaccount"                       # the report folder, next to the S1 and S2 paper books
ASSETS = ("BTC", "ETH", "SOL", "SPY", "QQQ", "GOLD")
CRYPTO = {"BTC": "BTCUSDT", "ETH": "ETHUSDT", "SOL": "SOLUSDT"}
UNDERLYING = {"SPY": "SPY", "QQQ": "QQQ", "GOLD": "GLD"}
TOKEN = {"BTC": "cbBTC", "ETH": "WETH", "SOL": "SOL", "SPY": "SPYx", "QQQ": "QQQx", "GOLD": "PAXG"}
CAPITALS = (40.0, 100.0)
MAIN = 40.0
MAX_HELD = 3
IS_FROM, OOS_FROM = s1.IS_FROM, s1.OOS_FROM
ETF_STALE_DAYS = 5
VOL_WIN = 60
PREMIUM_SEED = 11
BUDGET = 60
HOLDOUT_PER_RUN = 4
DIVERSITY_CORR = 0.90
COMPLEXITY_COST = 0.03
MIN_EXPOSURE = 0.10
SAFE_DD = s2.SAFE_DD                        # 20 %
DD_PENALTY = 4.0                            # fitness lost per unit of in-sample drawdown above SAFE_DD
PRIOR_TRIALS = s1.TRIALS + s2.TRIALS        # S1's and S2's candidates were trials on the same question
SHADOW_CAPITAL = 40.0
SHADOW_DAYS = 30
MAX_ACTIVE = 4
MAX_NEW_PER_RUN = 2
DUPLICATE_CORR = 0.90
RANDOM_SHARE, FIRST_RANDOM_SHARE, ELITE, TOURNAMENT, CROSSOVER = 0.35, 0.5, 15, 3, 0.3


# ---------------------------------------------------------------- the grammar

UNIVERSES = {
    "btc": ("BTC",), "spy": ("SPY",), "qqq": ("QQQ",), "majors": ("BTC", "ETH"), "crypto": ("BTC", "ETH", "SOL"),
    "btc_spy": ("BTC", "SPY"), "spy_gold": ("SPY", "GOLD"), "etf": ("SPY", "QQQ", "GOLD"),
    "mixed": ("BTC", "SPY", "GOLD"), "growth": ("BTC", "QQQ", "SPY"), "all": ASSETS,
}
SIGNALS = {
    "hold": {},
    "mom": {"lb": [28, 56, 90, 180, 365]},
    "ma": {"fast": [1, 10, 20, 50], "slow": [50, 100, 200]},
    "donchian": {"n": [20, 55, 100], "exit": [0.5]},
    "lowvol": {},
}
FILTERS = {
    "regime": {"on": ["BTC", "SPY"], "ma": [100, 200]},
    "absmom": {"lb": [90, 180, 365]},
    "vol": {"max": [0.3, 0.6, 1.0]},
    "trend": {"ma": [50, 100, 200]},
}
SELECT = {"k": [1, 2, 3], "rank": ["signal", "mom90", "lowvol"]}
WEIGHT = {"scheme": ["equal", "invvol"], "fill": ["slots", "full"], "target": [0.0, 0.10, 0.20]}
REBALANCE = {"every": [1, 7], "band": [0.0, 0.10, 0.25]}
MAX_FILTERS = 2
MAX_COMPLEXITY = 6
PARTS = ("universe", "signal", "filters", "select", "weight", "rebalance")


def _pick(rng: random.Random, space: dict) -> dict:
    return {k: rng.choice(v) for k, v in space.items()}


def _repair(g: dict) -> dict:
    s = g["signal"]
    if s["kind"] == "ma" and s["fast"] >= s["slow"]:
        s["fast"] = max(f for f in SIGNALS["ma"]["fast"] if f < s["slow"])
    n = len(UNIVERSES[g["universe"]["set"]])
    if g["select"]["k"] > n:
        g["select"]["k"] = n
    return g


def canonical(g: dict) -> dict:
    g = copy.deepcopy(g)
    g["filters"] = sorted(g["filters"], key=lambda f: f["kind"])
    return {k: g[k] for k in PARTS}


def key(g: dict) -> str:
    text = json.dumps(canonical(g), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(("small/" + text).encode()).hexdigest()[:12]


def complexity(g: dict) -> int:
    w, r = g["weight"], g["rebalance"]
    return ((g["signal"]["kind"] != "hold") + len(g["filters"]) + (w["scheme"] == "invvol") + (w["target"] > 0)
            + (r["band"] > 0) + (g["select"]["rank"] != "signal"))


def valid(g: dict) -> tuple[bool, str]:
    try:
        if list(g) != list(PARTS):
            return False, "parts missing or out of order"
        if set(g["universe"]) != {"set"} or g["universe"]["set"] not in UNIVERSES:
            return False, f"universe {g['universe']}"
        s = g["signal"]
        if s["kind"] not in SIGNALS or set(s) - {"kind"} != set(SIGNALS[s["kind"]]):
            return False, f"signal {s}"
        if any(s[k] not in v for k, v in SIGNALS[s["kind"]].items()):
            return False, f"signal {s}"
        if s["kind"] == "ma" and s["fast"] >= s["slow"]:
            return False, "ma fast must be below slow"
        kinds = [f["kind"] for f in g["filters"]]
        if len(kinds) > MAX_FILTERS or len(set(kinds)) != len(kinds):
            return False, "too many or repeated filters"
        for f in g["filters"]:
            if f["kind"] not in FILTERS or set(f) - {"kind"} != set(FILTERS[f["kind"]]):
                return False, f"filter {f}"
            if any(f[k] not in v for k, v in FILTERS[f["kind"]].items()):
                return False, f"filter {f}"
        for part, space in (("select", SELECT), ("weight", WEIGHT), ("rebalance", REBALANCE)):
            if set(g[part]) != set(space) or any(g[part][k] not in v for k, v in space.items()):
                return False, f"{part} {g[part]}"
        if g["select"]["k"] > len(UNIVERSES[g["universe"]["set"]]):
            return False, "K larger than the asset set"
        if complexity(g) > MAX_COMPLEXITY:
            return False, f"complexity {complexity(g)} above {MAX_COMPLEXITY}"
    except (KeyError, TypeError, AttributeError) as e:
        return False, f"malformed ({type(e).__name__})"
    return True, ""


def random_genome(rng: random.Random) -> dict:
    while True:
        s = rng.choice(list(SIGNALS))
        kinds = rng.sample(list(FILTERS), rng.choice([0, 0, 1, 1, 2]))
        g = {"universe": {"set": rng.choice(list(UNIVERSES))}, "signal": {"kind": s, **_pick(rng, SIGNALS[s])},
             "filters": [{"kind": k, **_pick(rng, FILTERS[k])} for k in kinds],
             "select": _pick(rng, SELECT), "weight": _pick(rng, WEIGHT), "rebalance": _pick(rng, REBALANCE)}
        g = canonical(_repair(g))
        if valid(g)[0]:
            return g


def mutate(g: dict, rng: random.Random, tries: int = 50) -> dict:
    for _ in range(tries):
        m = copy.deepcopy(g)
        what = rng.choice(["universe", "signal_param", "signal_kind", "filter_param", "filter_add", "filter_drop",
                           "select", "weight", "rebalance"])
        if what == "universe":
            m["universe"] = {"set": rng.choice(list(UNIVERSES))}
        elif what == "signal_kind":
            s = rng.choice([k for k in SIGNALS if k != m["signal"]["kind"]])
            m["signal"] = {"kind": s, **_pick(rng, SIGNALS[s])}
        elif what == "signal_param":
            space = SIGNALS[m["signal"]["kind"]]
            if not space:
                continue
            p = rng.choice(list(space))
            m["signal"][p] = rng.choice(space[p])
        elif what == "filter_param":
            if not m["filters"]:
                continue
            f = rng.choice(m["filters"])
            p = rng.choice(list(FILTERS[f["kind"]]))
            f[p] = rng.choice(FILTERS[f["kind"]][p])
        elif what == "filter_add":
            free = [k for k in FILTERS if k not in {f["kind"] for f in m["filters"]}]
            if not free or len(m["filters"]) >= MAX_FILTERS:
                continue
            k = rng.choice(free)
            m["filters"].append({"kind": k, **_pick(rng, FILTERS[k])})
        elif what == "filter_drop":
            if not m["filters"]:
                continue
            m["filters"].pop(rng.randrange(len(m["filters"])))
        else:
            space = {"select": SELECT, "weight": WEIGHT, "rebalance": REBALANCE}[what]
            p = rng.choice(list(space))
            m[what][p] = rng.choice(space[p])
        m = canonical(_repair(m))
        if valid(m)[0] and key(m) != key(g):
            return m
    return random_genome(rng)


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    for _ in range(20):
        c = canonical(_repair({p: copy.deepcopy(rng.choice((a, b))[p]) for p in PARTS}))
        if valid(c)[0]:
            return c
    return copy.deepcopy(a)


def describe(g: dict) -> str:
    """One line, e.g. "MA 1/200 · BTC, SPY, GOLD · BTC > MA200 · best 2 by signal · equal slots · weekly band 10 %"."""
    s = g["signal"]
    sig = {"hold": lambda: "hold", "mom": lambda: f"mom {s['lb']}d", "lowvol": lambda: "low vol",
           "donchian": lambda: f"Donchian {s['n']}/{max(2, round(s['n'] * s['exit']))}",
           "ma": lambda: f"price > MA{s['slow']}" if s["fast"] == 1 else f"MA {s['fast']}/{s['slow']}"}[s["kind"]]()
    fl = [{"regime": lambda: f"{f['on']} > MA{f['ma']}", "absmom": lambda: f"{f['lb']}d return > 0",
           "vol": lambda: f"vol < {int(f['max'] * 100)} %", "trend": lambda: f"asset > MA{f['ma']}"}[f["kind"]]()
          for f in g["filters"]]
    sel, w, r = g["select"], g["weight"], g["rebalance"]
    tgt = f" vol {int(w['target'] * 100)} %" if w["target"] else ""
    cad = {1: "daily", 7: "weekly"}[r["every"]] + (f" band {int(r['band'] * 100)} %" if r["band"] else "")
    return " · ".join([sig, ", ".join(UNIVERSES[g["universe"]["set"]])] + fl
                      + [f"best {sel['k']} by {sel['rank']}", f"{w['scheme']} {w['fill']}{tgt}", cad])


def hold_genome(asset: str) -> dict:
    """The benchmark as a genome: one asset bought and held."""
    return canonical({"universe": {"set": asset.lower()}, "signal": {"kind": "hold"}, "filters": [],
                      "select": {"k": 1, "rank": "signal"}, "weight": {"scheme": "equal", "fill": "slots", "target": 0.0},
                      "rebalance": {"every": 7, "band": 0.0}})


# ---------------------------------------------------------------- the market

@dataclass
class Ctx:
    """The six assets on the panel's calendar. px: EUR prices the wallet trades at (the tokens with drift and
    premium); sig: the prices the rules read (the underlying with drift, no premium); fresh: the last day every
    ETF has a close at most ETF_STALE_DAYS old."""
    days: np.ndarray
    px: np.ndarray
    sig: np.ndarray
    sol_eur: np.ndarray
    fresh: int
    eurusd: float
    drifts: dict = field(default_factory=dict)
    memo: dict = field(default_factory=dict)

    @property
    def T(self) -> int:
        return len(self.days)

    def feat(self, name: str, fn):
        if name not in self.memo:
            self.memo[name] = fn()
        return self.memo[name]

    def t_of(self, day: str) -> int:
        us = int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
        return int(np.searchsorted(self.days, us))


def ffill_col(x: np.ndarray) -> np.ndarray:
    ok = np.isfinite(x)
    idx = np.maximum.accumulate(np.where(ok, np.arange(len(x)), -1))
    return np.where(idx >= 0, x[np.maximum(idx, 0)], np.nan)


def crypto_closes(frame=None) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """(days, closes in USD by asset) of BTC, ETH and SOL from the sweep's cached daily panel: the current
    segment of each, forward-filled, on one calendar from BTC's first day. Reads three symbols, not the panel."""
    import polars as pl
    p = frame if frame is not None else fc.build_daily_panel()
    p = p.filter(pl.col("symbol").is_in(list(CRYPTO.values())))
    days = np.arange(int(p["day"].min()), int(p["day"].max()) + fc.DAY_US, fc.DAY_US, dtype=np.int64)
    out = {}
    for a, sym in CRYPTO.items():
        q = p.filter(pl.col("symbol") == sym)
        c = np.full(len(days), np.nan)
        c[((q["day"].to_numpy() - days[0]) // fc.DAY_US).astype(int)] = q["close"].to_numpy().astype(float)
        out[a] = ffill_col(c)
    return days, out


def premium_noise(path: Path = s2.PREMIUMS_CSV) -> dict[str, np.ndarray]:
    """S2's measured premiums of SPYx, QQQx and PAXG at the US close, around their mean, in bps."""
    by: dict[str, list] = {}
    if path.exists():
        rev = {TOKEN[a]: a for a in UNDERLYING}
        for r in s1.read_csv(path):
            if r["symbol"] in rev:
                by.setdefault(rev[r["symbol"]], []).append(float(r["premium_bps"]))
    return {a: np.array(v) - np.mean(v) for a, v in by.items() if len(v) > 1}


def drifts(tr: dict[str, dict] | None = None) -> dict[str, float]:
    """S2's drift a year of each token against its underlying (less the withholding on dividends)."""
    tr = s2.tracking() if tr is None else tr
    return {a: s2.drift(tr.get(TOKEN[a]), "GOLD" if a == "GOLD" else a) for a in UNDERLYING}


def make_ctx(days: np.ndarray, crypto: dict[str, np.ndarray], etf: dict[str, tuple[np.ndarray, np.ndarray]],
             eurusd: float, drift: dict[str, float], noise: dict[str, np.ndarray] | None = None,
             seed: int = PREMIUM_SEED) -> Ctx:
    years = (days - days[0]) / (365.25 * fc.DAY_US)
    T = len(days)
    px, sig = np.full((T, len(ASSETS)), np.nan), np.full((T, len(ASSETS)), np.nan)
    rng = np.random.default_rng(seed)
    last_etf = []
    for j, a in enumerate(ASSETS):
        if a in CRYPTO:
            sig[:, j] = px[:, j] = crypto[a] / eurusd
            continue
        dates, closes = etf[UNDERLYING[a]]
        last_etf.append(dates[-1])
        p = s2.etf_on_days(days, dates, closes) * np.exp(drift.get(a, 0.0) * years) / eurusd
        sig[:, j] = p
        n = (noise or {}).get(a)
        px[:, j] = p * (1 + rng.choice(n, T) / 1e4) if n is not None and len(n) else p
    d = (days // fc.DAY_US).astype("datetime64[D]")
    oldest = min(last_etf) if last_etf else d[-1]
    fresh = int(np.flatnonzero(d <= oldest + np.timedelta64(ETF_STALE_DAYS, "D"))[-1])
    sol = ffill_col(px[:, ASSETS.index("SOL")])
    first = np.flatnonzero(np.isfinite(sol))
    sol = np.where(np.isfinite(sol), sol, sol[first[0]] if len(first) else 100.0 / eurusd)
    return Ctx(days=days, px=px, sig=sig, sol_eur=sol, fresh=fresh, eurusd=eurusd, drifts=dict(drift))


def venue(v: s2.S2Venue | None = None) -> s2.S2Venue:
    """S2's venue with QQQx's ladder under QQQ (S2 only aliased its two picks, SPYx and PAXG)."""
    v = v or s2.venue()
    if "QQQx" in v.ladder:
        v.ladder["QQQ"] = v.ladder.pop("QQQx")
    return v


# ---------------------------------------------------------------- features and weights

def _ret_back(c: Ctx, lb: int) -> np.ndarray:
    def f():
        out = np.full_like(c.sig, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[lb:] = c.sig[lb:] / c.sig[:-lb] - 1
        return out
    return c.feat(f"ret{lb}", f)


def _ma(c: Ctx, m: int) -> np.ndarray:
    return c.feat(f"ma{m}", lambda: fc.rolling(c.sig, m, m))


def annvol(c: Ctx) -> np.ndarray:
    def f():
        lr = np.full_like(c.sig, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            lr[1:] = np.log(c.sig[1:] / c.sig[:-1])
        m = fc.rolling(lr, VOL_WIN, VOL_WIN // 2)
        m2 = fc.rolling(lr ** 2, VOL_WIN, VOL_WIN // 2)
        return np.sqrt(np.maximum(m2 - m ** 2, 0.0) * 365)
    return c.feat("annvol", f)


def _donchian(c: Ctx, n: int, exit_frac: float) -> np.ndarray:
    m = max(2, round(n * exit_frac))

    def f():
        hi, lo = fc.rolling_extreme(c.sig, n, "max"), fc.rolling_extreme(c.sig, m, "min")
        with np.errstate(invalid="ignore"):
            enter, leave = c.sig > hi, (c.sig < lo) | ~np.isfinite(c.sig)
        on = np.zeros_like(enter)
        held = np.zeros(enter.shape[1], dtype=bool)
        for t in range(c.T):
            held = (held & ~leave[t]) | (enter[t] & ~leave[t])
            on[t] = held
        return on
    return c.feat(f"don{n}_{m}", f)


def weights(c: Ctx, g: dict) -> np.ndarray:
    """(T, 6) target weights of the trading equity known at each close, the rest USDC. No NaN."""
    s = g["signal"]
    uni = np.array([a in UNIVERSES[g["universe"]["set"]] for a in ASSETS])
    vol = annvol(c)
    with np.errstate(invalid="ignore", divide="ignore"):
        if s["kind"] == "hold":
            on, strength = np.ones_like(c.sig, dtype=bool), np.zeros_like(c.sig)
        elif s["kind"] == "mom":
            r = _ret_back(c, s["lb"])
            on, strength = r > 0, r / vol
        elif s["kind"] == "ma":
            a = c.sig if s["fast"] == 1 else _ma(c, s["fast"])
            b = _ma(c, s["slow"])
            on, strength = a > b, a / b - 1
        elif s["kind"] == "donchian":
            on, strength = _donchian(c, s["n"], s["exit"]), _ret_back(c, s["n"]) / vol
        else:
            on, strength = np.isfinite(vol), -vol
        cand = uni[None, :] & on & np.isfinite(c.px) & np.isfinite(vol) & (vol > 0)
        off = np.zeros(c.T, dtype=bool)
        for f in g["filters"]:
            if f["kind"] == "regime":
                j = ASSETS.index(f["on"])
                off |= ~np.nan_to_num(c.sig[:, j] > _ma(c, f["ma"])[:, j], nan=0.0).astype(bool)
            elif f["kind"] == "absmom":
                cand &= _ret_back(c, f["lb"]) > 0
            elif f["kind"] == "vol":
                cand &= vol < f["max"]
            elif f["kind"] == "trend":
                cand &= c.sig > _ma(c, f["ma"])
        sel = g["select"]
        score = {"signal": strength, "mom90": _ret_back(c, 90), "lowvol": -vol}[sel["rank"]]
    score = np.where(cand & np.isfinite(score), score, -np.inf)
    order = np.argsort(-score, axis=1, kind="stable")
    held = np.zeros_like(cand)
    np.put_along_axis(held, order[:, : sel["k"]], True, axis=1)
    held &= cand
    held[off] = False
    w8 = g["weight"]
    with np.errstate(invalid="ignore", divide="ignore"):
        raw = held.astype(float) if w8["scheme"] == "equal" else np.where(held, 1.0 / vol, 0.0)
        tot = raw.sum(1, keepdims=True)
        W = np.where(tot > 0, raw / np.where(tot > 0, tot, 1.0), 0.0)
        if w8["fill"] == "slots":
            W = W * held.sum(1, keepdims=True) / sel["k"]
        if w8["target"] > 0:
            # The book's vol as if its assets moved together (an upper bound): scaled down only.
            bv = np.nansum(W * np.nan_to_num(vol), axis=1, keepdims=True)
            W = W * np.minimum(1.0, w8["target"] / np.where(bv > 0, bv, np.inf))
    return np.nan_to_num(W)


def due_days(c: Ctx, every: int) -> np.ndarray:
    return np.array([s1.rebalance_day(d, every) for d in c.days])


# ---------------------------------------------------------------- the wallet

def trade(w: s1.Wallet, row: np.ndarray, prices: dict, v: s1.Venue, sol_eur: float, band: float) -> list[dict]:
    """Bring every asset farther than `band` of the book from its target back to it (entries and exits always),
    with S1's wallet: sales first, the minimum, dust, the costs. An asset within the band is not traded."""
    eq = w.trade_equity(prices)
    tg = {}
    for j, a in enumerate(ASSETS):
        if a not in prices:
            continue
        x = float(row[j])
        have = w.units.get(a, 0.0) * prices[a] / eq if eq > 0 else 0.0
        move = abs(x - have)
        if (x > 0) != (have > 0) or (move > band and move > 1e-9):
            w.last.pop(a, None)                 # S1's wallet trades a target that changed; this one did
            tg[a] = x
    return s1.rebalance(w, tg, prices, v, sol_eur)


def prices_at(c: Ctx, t: int) -> dict[str, float]:
    return {a: float(c.px[t, j]) for j, a in enumerate(ASSETS) if np.isfinite(c.px[t, j]) and c.px[t, j] > 0}


def simulate(c: Ctx, W: np.ndarray, g: dict, v: s1.Venue, capital: float, t0: int, t1: int,
             once: bool = False) -> dict:
    """The wallet from the close of t0 (all USDC, the reserve and the way in paid) to the close of t1, trading at
    the closes of due days (and t0). `once`: buy at t0 and never trade again (the benchmarks)."""
    due = due_days(c, g["rebalance"]["every"])
    w = s1.Wallet(cash=capital)
    idle, way = v.setup(capital, MAX_HELD, float(c.sol_eur[t0]))
    w.cash -= idle + way
    w.idle, w.costs = idle, way
    n = t1 - t0 + 1
    eq, expo = np.zeros(n), np.zeros(n)
    for i, t in enumerate(range(t0, t1 + 1)):
        prices = prices_at(c, t)
        if t == t0 or (due[t] and not once):
            trade(w, W[t], prices, v, float(c.sol_eur[t]), g["rebalance"]["band"])
        eq[i] = w.value(prices)
        te = w.trade_equity(prices)
        expo[i] = (te - w.cash) / te if te > 0 else 0.0
    return {"equity": eq, "exposure": expo, "costs": w.costs, "orders": w.orders, "skipped": w.skipped,
            "dust": w.dust}


def measure(res: dict, capital: float) -> dict:
    m = s1.measure(res, capital)
    m["exposure"] = float(res["exposure"].mean()) if len(res["exposure"]) else 0.0
    return m


def returns(res: dict, capital: float) -> np.ndarray:
    return s2.daily_returns(res["equity"], capital)


def sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    sd = x.std() if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0


# ---------------------------------------------------------------- windows and judging

def windows(c: Ctx) -> dict[str, tuple[int, int]]:
    oos = c.t_of(OOS_FROM)
    t0 = c.t_of(IS_FROM)
    mid = (t0 + oos - 1) // 2
    return {"is": (t0, oos - 1), "h1": (t0, mid), "h2": (mid + 1, oos - 1), "oos": (oos, c.fresh)}


def _day(c: Ctx, t: int) -> str:
    return str((c.days[t] // fc.DAY_US).astype("datetime64[D]"))


def in_sample(c: Ctx, g: dict, v: s1.Venue, run_id: str) -> dict:
    """The only numbers the search sees: both wallets over the in-sample window."""
    win = windows(c)
    t0, t1 = win["is"]
    W = weights(c, g)
    row = {"key": key(g), "run": run_id, "name": describe(g), "genome": g, "complexity": complexity(g)}
    for cap in CAPITALS:
        res = simulate(c, W, g, v, cap, t0, t1)
        m = measure(res, cap)
        tag = f"{cap:g}"
        row.update({f"is_sharpe_{tag}": m["sharpe"], f"is_cagr_{tag}": m["cagr"], f"is_max_dd_{tag}": m["max_dd"],
                    f"is_costs_eur_{tag}": m["costs_eur"], f"is_orders_yr_{tag}": m["orders_yr"]})
        if cap == MAIN:
            r = returns(res, cap)
            h = win["h1"][1] - t0 + 1
            row.update({"is_h1": sharpe(r[:h]), "is_h2": sharpe(r[h:]), "is_exposure": m["exposure"]})
    row["is_sharpe"] = min(row[f"is_sharpe_{c_:g}"] for c_ in CAPITALS)
    dd = max(row[f"is_max_dd_{c_:g}"] for c_ in CAPITALS)
    f = row["is_sharpe"] - COMPLEXITY_COST * row["complexity"] - DD_PENALTY * max(dd - SAFE_DD, 0.0)
    if row["is_exposure"] < MIN_EXPOSURE:
        f -= 1.0
    row["fitness"] = f if math.isfinite(f) else -9.0
    return row


def is_series(c: Ctx, g: dict, v: s1.Venue) -> np.ndarray:
    t0, t1 = windows(c)["is"]
    return returns(simulate(c, weights(c, g), g, v, MAIN, t0, t1), MAIN)


def benchmarks(c: Ctx, v: s1.Venue, win: tuple[int, int]) -> dict[str, dict]:
    """Holding SPYx and holding BTC at each capital over a window: {"SPY@40": measure, ...} plus daily returns."""
    out = {}
    for a in ("SPY", "BTC"):
        g = hold_genome(a)
        W = weights(c, g)
        for cap in CAPITALS:
            res = simulate(c, W, g, v, cap, *win, once=True)
            out[f"{a}@{cap:g}"] = {**measure(res, cap), "returns": returns(res, cap)}
    return out


def strip_returns(b: dict) -> dict:
    return {k: {f: x for f, x in m.items() if f != "returns"} for k, m in b.items()}


def holdout(c: Ctx, g: dict, v: s1.Venue, pool: dict, bench: dict) -> dict:
    t0, t1 = windows(c)["oos"]
    W = weights(c, g)
    h = {"key": key(g), "name": describe(g), "oos_from": _day(c, t0), "oos_to": _day(c, t1), "oos_days": t1 - t0 + 1}
    x40 = None
    for cap in CAPITALS:
        res = simulate(c, W, g, v, cap, t0, t1)
        m = measure(res, cap)
        tag = f"{cap:g}"
        h.update({f"oos_{k}_{tag}": m[k] for k in ("cagr", "max_dd", "sharpe", "end_eur", "costs_eur", "orders_yr",
                                                    "skipped_yr", "exposure")})
        for a in ("SPY", "BTC"):
            b = bench[f"{a}@{tag}"]
            h.update({f"{a.lower()}_cagr_{tag}": b["cagr"], f"{a.lower()}_max_dd_{tag}": b["max_dd"],
                      f"{a.lower()}_sharpe_{tag}": b["sharpe"], f"{a.lower()}_end_eur_{tag}": b["end_eur"]})
        if cap == MAIN:
            x40 = returns(res, cap)
    late = np.vstack([np.zeros((1, W.shape[1])), W[:-1]])
    h["oos_late_cagr"] = measure(simulate(c, late, g, v, MAIN, t0, t1), MAIN)["cagr"]
    h.update({"deflated_p": lg.deflated(x40, pool), "pool_trials": pool["n_trials"], "pool_sr0": pool["sr0_annual"],
              "oos_returns_40": [round(float(r), 7) for r in x40]})
    return h


def gates(is_row: dict, h: dict) -> dict[str, dict]:
    caps = [f"{c_:g}" for c_ in CAPITALS]
    dd = max(h[f"oos_max_dd_{t}"] for t in caps)
    beat = all(h[f"oos_cagr_{t}"] > h[f"spy_cagr_{t}"] for t in caps)
    g = {
        "is_stable": (is_row["is_h1"] > 0 and is_row["is_h2"] > 0,
                      f"in-sample halves {is_row['is_h1']:.2f} / {is_row['is_h2']:.2f}"),
        "drawdown": (dd < SAFE_DD, f"held-back drawdown {dd * 100:.1f} % (40 and 100 EUR), needs under "
                                   f"{SAFE_DD * 100:.0f} %"),
        "beats_spy": (beat, " / ".join(f"{t} EUR {h[f'oos_cagr_{t}'] * 100:.1f} % vs SPYx {h[f'spy_cagr_{t}'] * 100:.1f} %"
                                       for t in caps) + " a year after costs"),
        "late_fill": (h["oos_late_cagr"] > 0, f"filled a close late {h['oos_late_cagr'] * 100:.1f} % a year"),
    }
    return {k: {"passed": bool(ok), "why": why} for k, (ok, why) in g.items()}


def failed(gs: dict[str, dict]) -> list[str]:
    return [k for k, x in gs.items() if not x["passed"]]


# ---------------------------------------------------------------- the ledger (its own namespace)

def small_dir() -> Path:
    return Path(os.environ.get("PYTHIA_FACTORY_SMALL_DIR", str(lg.factory_dir() / "small")))


def seed_dir() -> Path:
    """Trials counted elsewhere and committed (results/factory_small_seed: the first search was made in the
    lab's agent container), so they count on the server too and the bar does not start low."""
    default = Path(__file__).resolve().parents[2] / "results" / "factory_small_seed"
    return Path(os.environ.get("PYTHIA_FACTORY_SMALL_SEED", str(default)))


def import_seed(src: Path | None = None) -> dict:
    """Merge the seed's ledger lines by key and its held-back lines by (run, key); a seeded survivor is left out
    of the held-back log so this machine checks it again (the same numbers, not a new trial) and opens its
    shadow wallet here. Idempotent; never removes anything."""
    src = src or seed_dir()
    if not src.is_dir():
        return {"ledger": 0, "holdout": 0}
    n = len(Ledger().add(lg.read_jsonl(src / "ledger.jsonl")))
    hp = small_dir() / "holdout.jsonl"
    have = {(h.get("run"), h.get("key")) for h in lg.read_jsonl(hp)}
    new = [h for h in lg.read_jsonl(src / "holdout.jsonl")
           if (h.get("run"), h.get("key")) not in have and h.get("decision") != "shadow"]
    lg.append_jsonl(hp, new)
    return {"ledger": n, "holdout": len(new)}


def export_seed(dest: Path | None = None) -> dict:
    dest = dest or seed_dir()
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for name in ("ledger.jsonl", "holdout.jsonl"):
        rows = lg.read_jsonl(small_dir() / name)
        (dest / name).write_text("".join(json.dumps(r, separators=(",", ":"), default=float) + "\n" for r in rows),
                                 encoding="utf-8")
        out[name] = len(rows)
    return out


class Ledger(lg.Ledger):
    """The weekly factory's ledger class on small/ledger.jsonl, with its own pool: S1's and S2's trials plus
    every small genome, the variance of trial Sharpes from the small genomes alone."""

    def __init__(self, path: Path | None = None):
        super().__init__(path or small_dir() / "ledger.jsonl")

    def n_trials(self) -> int:
        return PRIOR_TRIALS + len(self.rows)

    def pool(self) -> dict:
        x = np.array([r["is_sharpe"] for r in self.rows if r.get("is_sharpe") is not None
                      and math.isfinite(r["is_sharpe"])])
        x = np.clip(x, -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
        v = float(np.var(x)) if len(x) > 1 else 0.0
        n = PRIOR_TRIALS + len(x)
        return {"prior_trials": PRIOR_TRIALS, "factory_trials": len(x), "n_trials": n, "var": v,
                "sr0_annual": lg.sr0(v, n) * math.sqrt(365)}


@contextmanager
def lock():
    p = small_dir() / ".lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a+") as fh:
        fh.seek(0)
        if not lg._try_lock(fh):
            raise RuntimeError("another small-account factory process holds the lock")
        try:
            yield
        finally:
            lg._unlock(fh)


def seed_of(run_id: str, n: int) -> int:
    return int(hashlib.sha1(f"small/{run_id}/{n}".encode()).hexdigest()[:12], 16)


def search(c: Ctx, v: s1.Venue, led: Ledger, run_id: str, budget: int, log=print) -> dict:
    """`budget` new genomes for this run, less those the run already put in the ledger (a rerun resumes).
    Each is appended the moment it is evaluated."""
    done = [r for r in led.rows if r.get("run") == run_id]
    left = max(0, budget - len(done))
    rng = random.Random(seed_of(run_id, len(led)))
    t0 = time.time()
    rows: list[dict] = []
    origin = {"random": 0, "mutation": 0, "crossover": 0}
    dup = 0
    first = not any(r.get("run") != run_id for r in led.rows)
    n_random = max(1, int(budget * (FIRST_RANDOM_SHARE if first else RANDOM_SHARE))) - sum(
        1 for r in done if r.get("origin") == "random")

    def new(g: dict, how: str) -> None:
        nonlocal dup
        if key(g) in led:
            dup += 1
            return
        r = in_sample(c, g, v, run_id)
        r["origin"] = how
        led.add([r])
        rows.append(r)
        origin[how] += 1
        if len(rows) % 20 == 0:
            log(f"  {len(rows)}/{left} evaluated, {time.time() - t0:.0f} s")

    attempts = 0
    while len(rows) < min(left, max(n_random, 0)) and attempts < 25 * max(left, 1):
        attempts += 1
        new(random_genome(rng), "random")
    while len(rows) < left and attempts < 25 * max(left, 1):
        attempts += 1
        pool = sorted(led.rows, key=lambda r: r["fitness"], reverse=True)[:ELITE]
        if not pool:
            new(random_genome(rng), "random")
            continue
        a = max(rng.sample(pool, min(TOURNAMENT, len(pool))), key=lambda r: r["fitness"])
        if rng.random() < CROSSOVER and len(pool) > 1:
            b = max(rng.sample(pool, min(TOURNAMENT, len(pool))), key=lambda r: r["fitness"])
            child = crossover(a["genome"], b["genome"], rng)
            if rng.random() < 0.5 or key(child) in led:
                child = mutate(child, rng)
            new(child, "crossover")
        else:
            new(mutate(a["genome"], rng), "mutation")
    for r in done:
        origin[r.get("origin", "random")] = origin.get(r.get("origin", "random"), 0) + 1
    return {"rows": done + rows, "resumed": len(done), "origin": origin, "duplicates": dup,
            "seconds": time.time() - t0}


def pick_for_holdout(c: Ctx, v: s1.Venue, led: Ledger, checked: set[str], n: int = HOLDOUT_PER_RUN) -> list[dict]:
    cands = [r for r in led.rows if r["key"] not in checked and r["is_h1"] > 0 and r["is_h2"] > 0
             and r["is_exposure"] >= MIN_EXPOSURE and r["fitness"] > 0]
    cands.sort(key=lambda r: r["fitness"], reverse=True)
    chosen: list[tuple[dict, np.ndarray]] = []
    for r in cands[: n * 10]:
        x = is_series(c, r["genome"], v)
        if any(_corr(x, y) > DIVERSITY_CORR for _, y in chosen):
            continue
        chosen.append((r, x))
        if len(chosen) >= n:
            break
    return [r for r, _ in chosen]


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    if n < 2 or a.std() == 0 or b.std() == 0:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


# ---------------------------------------------------------------- the shadow wallets

def shadow_dir() -> Path:
    return small_dir() / "shadow"


def _wallet_dict(w: s1.Wallet) -> dict:
    return {"cash": w.cash, "units": dict(w.units), "last": dict(w.last), "idle": w.idle, "costs": w.costs,
            "orders": w.orders, "skipped": w.skipped, "dust": w.dust}


def _wallet(d: dict) -> s1.Wallet:
    return s1.Wallet(cash=d["cash"], units=dict(d["units"]), last=dict(d["last"]), idle=d["idle"], costs=d["costs"],
                     orders=d["orders"], skipped=d["skipped"], dust=d["dust"])


def _open(c: Ctx, v: s1.Venue, t: int, capital: float = SHADOW_CAPITAL) -> s1.Wallet:
    w = s1.Wallet(cash=capital)
    idle, way = v.setup(capital, MAX_HELD, float(c.sol_eur[t]))
    w.cash -= idle + way
    w.idle, w.costs = idle, way
    return w


def all_shadows() -> list[dict]:
    d = shadow_dir()
    out = []
    for p in sorted(d.glob("*.json")) if d.exists() else []:
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def active() -> list[dict]:
    return [m for m in all_shadows() if m.get("status") == "active"]


def journal(k: str) -> list[dict]:
    p = shadow_dir() / f"{k}.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def start_shadow(c: Ctx, v: s1.Venue, is_row: dict, h: dict, gs: dict, run_id: str) -> dict:
    """A 40 EUR paper wallet for the genome and one for holding SPYx and BTC, opened at the close of the last fresh
    day (the genome's first trade at that close); the days after it are the forward record."""
    t = c.fresh
    g = is_row["genome"]
    book = _open(c, v, t)
    trade(book, weights(c, g)[t], prices_at(c, t), v, float(c.sol_eur[t]), g["rebalance"]["band"])
    benches = {}
    for a in ("SPY", "BTC"):
        b = _open(c, v, t)
        trade(b, weights(c, hold_genome(a))[t], prices_at(c, t), v, float(c.sol_eur[t]), 0.0)
        benches[a] = _wallet_dict(b)
    meta = {"key": is_row["key"], "name": is_row["name"], "genome": g, "status": "active", "entered_run": run_id,
            "entry_day": _day(c, t), "capital_eur": SHADOW_CAPITAL, "book": f"fsmall_{is_row['key'][:8]}",
            "in_sample": {k: is_row[k] for k in ("is_sharpe", "is_h1", "is_h2", "is_exposure", "complexity", "fitness")},
            "holdout": {k: x for k, x in h.items() if k != "oos_returns_40"}, "gates": gs,
            "oos_returns_40": h.get("oos_returns_40"), "wallet": _wallet_dict(book), "bench": benches,
            "last_day": _day(c, t), "reviews": 0}
    lg.write_json(shadow_dir() / f"{is_row['key']}.json", meta)
    return meta


JOURNAL_COLS = ["date", "equity_eur", "spy_eur", "btc_eur", "held", "orders", "costs_eur"]


def update_shadows(c: Ctx, v: s1.Venue) -> list[dict]:
    """Step every active shadow and its benchmark wallets through each fresh day after its last one; append."""
    out = []
    for m in active():
        g = m["genome"]
        W = weights(c, g)
        due = due_days(c, g["rebalance"]["every"])
        w, bw = _wallet(m["wallet"]), {a: _wallet(d) for a, d in m["bench"].items()}
        new = []
        for t in range(c.t_of(m["last_day"]) + 1, c.fresh + 1):
            prices = prices_at(c, t)
            if due[t]:
                trade(w, W[t], prices, v, float(c.sol_eur[t]), g["rebalance"]["band"])
            new.append({"date": _day(c, t), "equity_eur": f"{w.value(prices):.4f}",
                        "spy_eur": f"{bw['SPY'].value(prices):.4f}", "btc_eur": f"{bw['BTC'].value(prices):.4f}",
                        "held": "+".join(sorted(w.units)) or "USDC", "orders": w.orders, "costs_eur": f"{w.costs:.4f}"})
        if new:
            p = shadow_dir() / f"{m['key']}.csv"
            fresh = not p.exists()
            with p.open("a", newline="", encoding="utf-8") as fh:
                wr = csv.DictWriter(fh, fieldnames=JOURNAL_COLS)
                if fresh:
                    wr.writeheader()
                wr.writerows(new)
            m.update(wallet=_wallet_dict(w), bench={a: _wallet_dict(b) for a, b in bw.items()},
                     last_day=new[-1]["date"])
            lg.write_json(shadow_dir() / f"{m['key']}.json", m)
        out.append({"key": m["key"], "appended": len(new), "days": len(journal(m["key"]))})
    return out


def forward(m: dict) -> dict:
    rows = journal(m["key"])
    cap = m["capital_eur"]
    eq = np.array([float(r["equity_eur"]) for r in rows])
    spy = np.array([float(r["spy_eur"]) for r in rows])
    btc = np.array([float(r["btc_eur"]) for r in rows])
    if not len(eq):
        return {"days": 0, "equity_eur": cap, "spy_eur": cap, "btc_eur": cap, "sharpe": 0.0, "spy_sharpe": 0.0}
    return {"days": len(eq), "equity_eur": float(eq[-1]), "spy_eur": float(spy[-1]), "btc_eur": float(btc[-1]),
            "sharpe": sharpe(s2.daily_returns(eq, cap)), "spy_sharpe": sharpe(s2.daily_returns(spy, cap))}


def review(today: str) -> list[dict]:
    """Every SHADOW_DAYS recorded days: retired unless the book's daily Sharpe beats the SPYx wallet's."""
    out = []
    for m in active():
        fw = forward(m)
        if fw["days"] < SHADOW_DAYS * (m.get("reviews", 0) + 1):
            continue
        beat = fw["sharpe"] > fw["spy_sharpe"]
        m["reviews"] = m.get("reviews", 0) + 1
        why = (f"{fw['days']} shadow days: Sharpe {fw['sharpe']:.2f} vs SPYx {fw['spy_sharpe']:.2f}, "
               f"{fw['equity_eur']:.2f} EUR vs {fw['spy_eur']:.2f}")
        if not beat:
            m.update(status="retired", reason="does not beat holding SPYx risk-adjusted; " + why, retired=today)
        else:
            m["reason"] = "beats holding SPYx risk-adjusted; " + why
        m["reviewed"] = today
        lg.write_json(shadow_dir() / f"{m['key']}.json", m)
        out.append({"key": m["key"], "name": m["name"], "status": m["status"], "reason": m["reason"]})
    return out


def too_close(x: list | None, others: list[tuple[str, list | None]]) -> str | None:
    if not x:
        return None
    a = np.array(x)
    for k, y in others:
        if y and len(y) >= 60 and _corr(a, np.array(y)) > DUPLICATE_CORR:
            return k
    return None


# ---------------------------------------------------------------- the run

def load_market(offline: bool = False) -> tuple[Ctx, s2.S2Venue]:
    v = venue()
    days, crypto = crypto_closes()
    syms = tuple(UNDERLYING.values())
    if offline:
        etf = s2.load_etf(syms)
    else:
        from ..paper.smallaccount import live_etf
        etf = live_etf(syms)
    return make_ctx(days, crypto, etf, v.eurusd, drifts(), premium_noise()), v


def run(c: Ctx, v: s1.Venue, budget: int, run_id: str | None = None, log=print) -> dict:
    t_start = time.time()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    win = windows(c)
    today = _day(c, c.fresh)
    log(f"factory small {run_id}: days to {_day(c, c.T - 1)}, fresh to {today}, budget {budget}")
    seeded = import_seed()
    if any(seeded.values()):
        log(f"  merged from the seed: {seeded}")
    led = Ledger()
    pool_before = led.pool()
    res = search(c, v, led, run_id, budget, log=log)
    pool = led.pool()
    bench_is = benchmarks(c, v, win["is"])
    bench = benchmarks(c, v, win["oos"])
    hp = small_dir() / "holdout.jsonl"
    hold_log = lg.read_jsonl(hp)
    this_run = {h["key"]: h for h in hold_log if h.get("run") == run_id}
    checked = {h["key"] for h in hold_log if h.get("run") != run_id}
    picks = [led.by_key[k] for k in this_run if k in led] or pick_for_holdout(c, v, led, checked)
    act = active()
    ever = {m["key"] for m in all_shadows()}
    others = [(m["key"], m.get("oos_returns_40")) for m in all_shadows() if m.get("status") == "active"]
    slots = max(0, min(MAX_NEW_PER_RUN, MAX_ACTIVE - len(act)))
    rows = []
    for r in picks:
        if r["key"] in this_run:            # a rerun of the day: the decision stands
            rows.append(this_run[r["key"]])
            continue
        h = holdout(c, r["genome"], v, pool, bench)
        gs = gates(r, h)
        bad = failed(gs)
        if bad:
            decision, why = "stopped", "; ".join(f"{k} fails ({gs[k]['why']})" for k in bad)
        elif r["key"] in ever:
            decision, why = "already shadowed", "ran as a shadow wallet before"
        elif (dup := too_close(h["oos_returns_40"], others)) is not None:
            decision, why = "duplicate", f"held-back returns move with shadow {dup}"
        elif slots <= 0:
            decision, why = "waiting", f"passes, but all {MAX_ACTIVE} shadow slots are taken"
        else:
            decision = "shadow"
            why = f"passes every held-back gate; deflated p {h['deflated_p']:.2f} over {h['pool_trials']} trials"
            start_shadow(c, v, r, h, gs, run_id)
            others.append((r["key"], h["oos_returns_40"]))
            slots -= 1
        row = {"run": run_id, "date": today, **{k: x for k, x in h.items() if k != "oos_returns_40"},
               "is_sharpe": r["is_sharpe"], "fitness": r["fitness"], "gates": gs, "decision": decision, "why": why}
        if decision != "waiting":
            lg.append_jsonl(hp, [row])
        rows.append(row)
        log(f"  held back {r['key']} {decision}: {why}")
    upd = update_shadows(c, v)
    decisions = review(today)
    shadows = []
    for m in all_shadows():
        fw = forward(m)
        shadows.append({"key": m["key"], "name": m["name"], "status": m["status"], "entry_day": m["entry_day"],
                        **fw, "reason": m.get("reason")})
    top = sorted(res["rows"], key=lambda r: r["fitness"], reverse=True)[:8]
    d = {"run_id": run_id, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "windows": {k: [_day(c, a), _day(c, b)] for k, (a, b) in win.items()}, "fresh_to": today,
         "eurusd": c.eurusd, "drifts": c.drifts, "budget": budget, "seeded": seeded,
         "search": {"evaluated": len(res["rows"]), "resumed": res["resumed"], "origin": res["origin"],
                    "duplicates": res["duplicates"], "seconds": res["seconds"]},
         "pool_before": pool_before, "pool_after": pool, "ledger": len(led),
         "top": [{k: x for k, x in r.items() if k != "genome"} for r in top],
         "bench_is": strip_returns(bench_is), "bench_oos": strip_returns(bench), "holdout": rows,
         "shadow_update": upd, "decisions": decisions, "shadows": shadows, "seconds": time.time() - t_start}
    d["verdict"] = verdict(d)
    lg.write_json(small_dir() / "runs" / f"{run_id}.json", d)
    return d


def verdict(d: dict) -> str:
    n_sh = sum(1 for h in d["holdout"] if h["decision"] == "shadow")
    act = sum(1 for s in d["shadows"] if s["status"] == "active")
    if n_sh:
        return (f"{n_sh} genome(s) beat holding SPYx held back with a drawdown under 20 % and start a 40 EUR shadow "
                f"wallet; {act} shadow(s) running.")
    return (f"Nothing new survives the held-back window: {len(d['holdout'])} checked, the pool is "
            f"{d['pool_after']['n_trials']} trials; {act} shadow(s) running.")


# ---------------------------------------------------------------- the report

def _pct(x) -> str:
    return "n/a" if x is None else f"{x * 100:.1f} %"


def markdown(d: dict) -> str:
    w, p = d["windows"], d["pool_after"]
    md = ["# Strategy factory, small-account mode (F2), in EUR\n",
          "EXPERIMENT, paper only. Strategies for a 40 and a 100 EUR wallet on BTC, ETH, SOL, SPYx, QQQx and PAXG "
          "with USDC as cash, at most 3 held, with S1's and S2's costs (Jupiter's recorded round trip, network fee "
          "and Sender tip a swap, 5 USDC minimum, the SOL reserve, the way in from SOL). No real money.\n",
          f"Run {d['run_id']}, generated {d['generated']}. In sample {w['is'][0]} to {w['is'][1]}, held back "
          f"{w['oos'][0]} to {w['oos'][1]}. EUR/USD {d['eurusd']:.4f}. Token drift a year: "
          + ", ".join(f"{TOKEN[a]} {x * 100:+.2f} %" for a, x in d["drifts"].items()) + ".\n",
          f"**{d['verdict']}**\n",
          "## Trials and the bar\n",
          f"- this run: {d['search']['evaluated']} genomes of a budget of {d['budget']} ("
          + ", ".join(f"{k} {x}" for k, x in d["search"]["origin"].items())
          + (f"; {d['search']['resumed']} from an earlier attempt today" if d["search"]["resumed"] else "")
          + f"), {d['search']['duplicates']} proposal(s) already tried",
          f"- ledger: {d['ledger']} small-account genomes plus {p['prior_trials']} S1/S2 trials = {p['n_trials']} "
          f"trials; noise bar (the best of that many noise strategies) Sharpe {p['sr0_annual']:.2f}\n",
          "## The benchmarks (bought once and held, same wallet and costs)\n"]
    t = []
    for k in d["bench_oos"]:
        a, cap = k.split("@")
        bi, bo = d["bench_is"][k], d["bench_oos"][k]
        t.append({"hold": TOKEN[a], "EUR": cap, "in sample CAGR / DD / Sharpe":
                  f"{_pct(bi['cagr'])} / {_pct(bi['max_dd'])} / {bi['sharpe']:.2f}",
                  "held back CAGR / DD / Sharpe": f"{_pct(bo['cagr'])} / {_pct(bo['max_dd'])} / {bo['sharpe']:.2f}",
                  "held back end": f"{bo['end_eur']:.2f} EUR"})
    md.append(report.table(t, list(t[0])) if t else "none\n")
    md.append("## Best in sample this run\n")
    t = [{"key": r["key"], "genome": r["name"], "fitness": f"{r['fitness']:.2f}",
          "Sharpe 40 / 100": f"{r['is_sharpe_40']:.2f} / {r['is_sharpe_100']:.2f}",
          "CAGR 40": _pct(r["is_cagr_40"]), "DD 40": _pct(r["is_max_dd_40"]),
          "orders/yr": f"{r['is_orders_yr_40']:.0f}", "costs 40": f"{r['is_costs_eur_40']:.2f} EUR"} for r in d["top"]]
    md.append(report.table(t, list(t[0])) if t else "nothing evaluated\n")
    md.append("## Held back (survivor: drawdown under 20 % and above holding SPYx after costs at 40 and 100 EUR)\n")
    t = [{"key": h["key"], "genome": h["name"], "40 EUR end / CAGR / DD": f"{h['oos_end_eur_40']:.2f} / "
          f"{_pct(h['oos_cagr_40'])} / {_pct(h['oos_max_dd_40'])}", "100 EUR end / CAGR / DD":
          f"{h['oos_end_eur_100']:.2f} / {_pct(h['oos_cagr_100'])} / {_pct(h['oos_max_dd_100'])}",
          "SPYx 40 / 100": f"{h['spy_end_eur_40']:.2f} / {h['spy_end_eur_100']:.2f}",
          "BTC 40 / 100": f"{h['btc_end_eur_40']:.2f} / {h['btc_end_eur_100']:.2f}",
          "Sharpe vs SPYx (40)": f"{h['oos_sharpe_40']:.2f} vs {h['spy_sharpe_40']:.2f}",
          "deflated p": f"{h['deflated_p']:.2f}", "decision": h["decision"], "why": h["why"]} for h in d["holdout"]]
    md.append(report.table(t, list(t[0])) if t else "nothing in sample good enough to check\n")
    md.append("## Shadow wallets (40 EUR each, the same costs; at most 4, retired after 30 days unless they beat "
              "holding SPYx risk-adjusted)\n")
    t = [{"book": f"fsmall_{s['key'][:8]}", "genome": s["name"], "status": s["status"], "since": s["entry_day"],
          "days": s["days"], "wallet": f"{s['equity_eur']:.2f} EUR", "SPYx wallet": f"{s['spy_eur']:.2f} EUR",
          "BTC wallet": f"{s['btc_eur']:.2f} EUR", "Sharpe vs SPYx": f"{s['sharpe']:.2f} vs {s['spy_sharpe']:.2f}",
          "note": s.get("reason") or ""} for s in d["shadows"]]
    md.append(report.table(t, list(t[0])) if t else "none yet\n")
    md.append("Nothing here trades: a shadow that keeps beating is a candidate for a hand study, not a book.\n")
    return "\n".join(md) + "\n"


def publish(d: dict) -> None:
    out = report.REPORTS / NAME
    out.mkdir(parents=True, exist_ok=True)
    ms = int(datetime.fromisoformat(d["generated"]).timestamp() * 1000)
    n_sh = sum(1 for s in d["shadows"] if s["status"] == "active")
    items = [{"label": f"fsmall_{s['key'][:8]}", "value": f"{s['equity_eur']:.2f} EUR (SPYx {s['spy_eur']:.2f})",
              "detail": s["name"], "status": "ok" if s["equity_eur"] >= s["spy_eur"] else "watch"}
             for s in d["shadows"] if s["status"] == "active"]
    head = report.feed_header("Small-account factory (F2)", "ok" if n_sh else "watch", d["verdict"], items=items,
                              updated_ms=ms)
    (out / "factory.md").write_text(markdown(d), encoding="utf-8")
    (out / "factory.json").write_text(json.dumps({**head, **{k: x for k, x in d.items() if k != "verdict"}},
                                                 indent=1, default=float), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m lab.factory small")
    ap.add_argument("--budget", type=int, default=int(os.environ.get("PYTHIA_FACTORY_SMALL_BUDGET", BUDGET)))
    ap.add_argument("--run-id")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--export-seed", action="store_true", help="write the ledger and held-back log as the seed")
    a = ap.parse_args(argv)
    with lock():
        if a.export_seed:
            print(json.dumps(export_seed()))
            return 0
        c, v = load_market(a.offline)
        d = run(c, v, a.budget, a.run_id)
        publish(d)
    print(d["verdict"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
