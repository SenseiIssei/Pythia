"""SW1: the lab's swing rules and a short hold grid on the rug-free coin universe, at Hyperliquid's costs, for a
50 EUR account.

Pre-registered in results/swing_sw1_prereg.md; results in results/swing_sw1.md.

    PYTHIA_AGENT_OUT=<cache> python -m lab.experiments.swing_sw1 --fetch        # 1-hour klines, 2021-10 to 2026-06
    PYTHIA_AGENT_OUT=<cache> PYTHIA_TRIALS_REGISTRY=<registry> PYTHIA_REPORTS=<reports> \
        flock <heavy lock> python -m lab.experiments.swing_sw1 [--no-register] [--report]

DT1's point-in-time universe (Binance USDT-M perps listed 180 days with a 30-day mean quote volume of 50 M USD, no
stablecoins, commodity, equity, index or leveraged products, delisted coins in), judged on the days Hyperliquid
lists the coin; in sample on the whole Binance universe. Binance's daily klines for the prices, the realised variance
from 1-hour klines (M6's 30-day mean, as fam_common.Panel.sigma). R: the lab's swing rules unchanged on that universe
(smallaccount.candidate's weight functions, trend_shorts' short sides); H: a 27-cell breakout grid with a time stop.
Signals at the close, fills at the next open (and one day late), Hyperliquid taker 4.5 bps plus 1 or 3 bps of
slippage, funding at its real rate (Hyperliquid's hourly where recorded, Binance's otherwise), accounts of 57 and
228 USD with the 10 USD minimum order and at most floor(equity / 10) positions, no leverage above 1, and an ideal
account without a minimum. In sample 2022 to 2024, judged 2025-01-01 to 2026-06-30 against BTC held; nothing after
2026-06-30 is read (the lockbox). Every (rule, account, fill) goes into R5's registry with its in-sample Sharpe
before any out-of-sample number. Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import data as labdata
from .. import metrics
from . import daytrade_dt1 as dt
from . import fam_common as fc

NAME = "swing_sw1"
PREREG = "results/swing_sw1_prereg.md"
IS_FROM, IS_TO, OOS_FROM, OOS_TO, LOCKBOX = dt.IS_FROM, dt.IS_TO, dt.OOS_FROM, dt.OOS_TO, dt.LOCKBOX
FETCH_FROM = "2021-10"
WARM_FROM = "2021-12-01"             # the first decision closes feeding the in-sample book
CACHE = Path(os.environ.get("PYTHIA_AGENT_OUT", str(labdata.ROOT / "agent-strategies"))) / "sw1"
HOUR_MIN = 60

FEE = 4.5e-4
SLIP_TOP, SLIP_REST = 1e-4, 3e-4
MIN_ORDER = 10.0
EURUSD = 1.14
ACCOUNTS = {"57usd": 50 * EURUSD, "228usd": 200 * EURUSD, "ideal": None}
FILLS = ("base", "late")
COIN_VOL = 0.40
BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED = 2000, 10.0, 7
DSR_PASS = 0.95
MIN_ENTRIES = 10
YEAR = 365
STRIP = ("1000000", "1000", "1M")    # Binance's multiplied tickers: 1000PEPE is PEPE

R_RULES = ("breakout_top10", "breakout_btceth", "tsmom1", "tsmom_top20", "breakout_sol3", "breakout_sol10",
           "btc_gated", "memes_rotation", "breakout_top10_ls", "tsmom_top20_ls")
H_N, H_D, H_K = (10, 20, 55), (5, 10, 20), (5, 10, 20)


def rules() -> list[str]:
    return list(R_RULES) + [f"H:N{n}:D{d}:K{k}" for n in H_N for d in H_D for k in H_K]


def base_of(symbol: str) -> str:
    b = symbol[:-4] if symbol.endswith("USDT") else symbol
    for p in STRIP:
        if b.startswith(p) and len(b) > len(p) and b[len(p)].isalpha():
            return b[len(p):]
    return b


# ---------------------------------------------------------------- 1-hour klines (data.binance.vision)

def hdir(symbol: str) -> Path:
    return CACHE / "klines_1h" / f"symbol={symbol}"


def needed_months(Dy: dt.Daily, Q: np.ndarray) -> dict[str, list[str]]:
    """{symbol: months to fetch}: every month with a qualifying day from WARM_FROM and the two months before it."""
    days = (Dy.d0 + np.arange(Dy.D)).astype("datetime64[D]")
    months = days.astype("datetime64[M]")
    keep = (days >= np.datetime64(WARM_FROM)) & (days <= np.datetime64(OOS_TO))
    out = {}
    for j, s in enumerate(Dy.names):
        ms = np.unique(months[keep & Q[:, j]])
        if not len(ms):
            continue
        allm = {str(m - np.timedelta64(k, "M")) for m in ms for k in (0, 1, 2)}
        out[s] = sorted(m for m in allm if FETCH_FROM <= m <= OOS_TO[:7])
    return out


def fetch_month(symbol: str, month: str) -> str:
    """One month of a perp's 1-hour klines into the cache; 'have', 'ok', 'absent' or 'error'."""
    d = hdir(symbol)
    f = d / f"{month}.parquet"
    if f.exists() or (d / f"{month}.absent").exists():
        return "have"
    q = urllib.parse.quote(symbol)
    raw = dt.fm_get(f"{dt.BUCKET}/data/futures/um/monthly/klines/{q}/1h/{q}-1h-{month}.zip")
    d.mkdir(parents=True, exist_ok=True)
    if raw is None:
        (d / f"{month}.absent").write_text("")
        return "absent"
    try:
        dt.parse_klines(raw).write_parquet(f)
    except Exception:
        return "error"
    return "ok"


def fetch(plan: dict[str, list[str]], par: int = 12) -> dict:
    jobs = [(s, m) for s, ms in sorted(plan.items()) for m in ms]
    t0, done, stat = time.time(), 0, {}
    with ThreadPoolExecutor(par) as ex:
        for r in ex.map(lambda sm: fetch_month(*sm), jobs):
            done += 1
            stat[r] = stat.get(r, 0) + 1
            if done % 500 == 0:
                print(f"fetch {done}/{len(jobs)} {stat} {time.time() - t0:.0f} s", flush=True)
    return stat


def hourly_daily(h: pl.DataFrame) -> pl.DataFrame:
    """day, rv (the sum of the day's squared 1-hour log returns, close to close, the first hour's from the previous
    hour's close when it is the hour before), c (the last close) and qv of one coin's 1-hour bars."""
    h = h.sort("t").unique("t", keep="last")
    t = h["t"].to_numpy()
    c = h["c"].to_numpy().astype(float)
    r = np.full(len(c), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r[1:] = np.where(np.diff(t) == HOUR_MIN, np.log(c[1:] / c[:-1]), np.nan)
    return (pl.DataFrame({"day": t // dt.DAY_MIN, "r2": r ** 2, "c": c, "qv": h["qv"].to_numpy().astype(float)})
            .with_columns(pl.col("r2").fill_nan(None))
            .group_by("day").agg(rv=pl.col("r2").sum(), nr=pl.col("r2").count(), c=pl.col("c").last(),
                                 qv=pl.col("qv").sum())
            .filter((pl.col("day") < dt.dnum(LOCKBOX)) & (pl.col("nr") >= 20)).sort("day"))


def load_rv(Dy: dt.Daily, symbols: list[str]) -> tuple[np.ndarray, dict]:
    """(D, M) daily realised variance from the cache (NaN without 1-hour bars) and the bar check: the share of days
    whose 1-hour close and quote volume agree with the daily kline to 0.1 %."""
    rv = np.full(Dy.c.shape, np.nan)
    col = {s: j for j, s in enumerate(Dy.names)}
    n = ok_c = ok_q = 0
    for s in symbols:
        files = sorted(hdir(s).glob("*.parquet"))
        if not files:
            continue
        g = hourly_daily(pl.concat([pl.read_parquet(f) for f in files]))
        rows = g["day"].to_numpy() - Dy.d0
        k = (rows >= 0) & (rows < Dy.D)
        j = col[s]
        rv[rows[k], j] = g["rv"].to_numpy()[k]
        dc, dq = Dy.c[rows[k], j], Dy.qv[rows[k], j]
        have = np.isfinite(dc) & (dq > 0)
        n += int(have.sum())
        with np.errstate(invalid="ignore", divide="ignore"):
            ok_c += int((np.abs(g["c"].to_numpy()[k][have] / dc[have] - 1) < 1e-3).sum())
            ok_q += int((np.abs(g["qv"].to_numpy()[k][have] / dq[have] - 1) < 1e-3).sum())
    return rv, {"days": n, "close_agree": ok_c / n if n else float("nan"), "qv_agree": ok_q / n if n else float("nan")}


# ---------------------------------------------------------------- funding, daily sums

def funding_daily(path: Path, tcol: str) -> dict[int, float]:
    """{day number: the sum of the day's funding rates} of one source."""
    files = sorted(path.glob("*.parquet")) if path.is_dir() else ([path] if path.exists() else [])
    if not files:
        return {}
    f = (pl.concat([pl.read_parquet(x, columns=[tcol, "funding_rate"]) for x in files], how="vertical_relaxed")
         .unique(tcol).filter(pl.col(tcol) < dt.us(LOCKBOX))
         .group_by(day=pl.col(tcol) // dt.DAY_US).agg(pl.col("funding_rate").fill_nan(0).fill_null(0).sum()))
    return dict(zip(f["day"].to_list(), f["funding_rate"].to_list()))


def funding_tables(Dy: dt.Daily, cols: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(D, M) Binance's and Hyperliquid's daily funding sums (NaN where the source has no record that day)."""
    inv = {dt.hl_to_binance(c): c for c in json.loads((labdata.ROOT / "free" / "perps_all" / "hyperliquid" /
                                                         "listings.json").read_text(encoding="utf-8"))}
    fb, fh = np.full(Dy.c.shape, np.nan), np.full(Dy.c.shape, np.nan)
    for j in cols:
        s = Dy.names[j]
        for tab, src in ((fb, funding_daily(labdata.ROOT / "hist" / "binance_um" / "funding" / f"symbol={s}",
                                            "funding_time_us")),
                         (fh, funding_daily(labdata.ROOT / "free" / "perps_all" / "hyperliquid" / "funding" /
                                            f"{inv[s]}.parquet", "ts_us") if s in inv else {})):
            for d, v in src.items():
                r = d - Dy.d0
                if 0 <= r < Dy.D:
                    tab[r, j] = v
    return fb, fh


# ---------------------------------------------------------------- the panel the lab's rules read

def make_panel(Dy: dt.Daily, cols: np.ndarray, member: np.ndarray, rv: np.ndarray) -> fc.Panel:
    """fam_common.Panel on the daily klines of `cols`, built as fam_common.panel_from does (px forward-filled inside
    a segment, 28-day volume, sigma from the 30-day mean of the daily realised variance, BTC's 200-day filter); its
    eligible coins are the universe `member` ((D, M) bool) on days with a bar."""
    names = [Dy.names[j] for j in cols]
    T, N = Dy.D, len(cols)
    close, high, low, qv = (A[:, cols] for A in (Dy.c, Dy.h, Dy.l, Dy.qv))
    traded = np.isfinite(close)
    alive = Dy.listed[:, cols] >= 0
    idx = np.arange(T)[:, None]
    fidx = np.maximum.accumulate(np.where(traded, idx, 0), axis=0)
    px = np.where(alive, close[fidx, np.arange(N)[None, :]], np.nan)
    ret = np.full((T, N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = np.where(alive[1:] & alive[:-1], px[1:] / px[:-1] - 1, np.nan)
    adv28 = np.where(alive, fc.rolling(np.where(alive, np.nan_to_num(qv), np.nan), 28, 20), np.nan)
    sigma = np.sqrt(fc.rolling(rv[:, cols], 30, 20))
    eligible = member[:, cols] & traded & alive
    btc = names.index("BTCUSDT")
    bpx = px[:, btc]
    ma200 = fc.rolling(bpx[:, None], 200, 200)[:, 0]
    btc_on = np.nan_to_num(bpx > ma200, nan=0.0).astype(bool)
    days = (Dy.d0 + np.arange(T)).astype(np.int64) * dt.DAY_US
    return fc.Panel(days, names, [base_of(s) for s in names], close, px, high, low, ret, alive, traded,
                    np.where(alive, Dy.listed[:, cols], -1), adv28, sigma, eligible, traded.copy(), np.zeros((T, N)),
                    btc_on, btc, extra={"qv": qv})


# ---------------------------------------------------------------- the rules: (T, N) targets, NaN means keep

def h_weights(P: fc.Panel, n: int, d: int, k: int) -> np.ndarray:
    """H: long on a close above the n previous closes' high while among the k most liquid, out on a close below the
    n // 2 previous closes' low or after d days held; a time exit re-enters only after a close at or below the
    channel. Each entry min(0.40 / annual vol, 1) of one slot (the simulator divides by the slots)."""
    allowed = P.top_liquid(k)
    cols = np.flatnonzero(allowed.any(0))
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    with np.errstate(invalid="ignore", divide="ignore"):
        above = px > hi
        enter = above & allowed[:, cols]
        leave = (px < lo) | ~P.alive[:, cols]
        size = np.nan_to_num(np.minimum(COIN_VOL / (P.sigma[:, cols] * math.sqrt(YEAR)), 1.0))
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    age = np.zeros(len(cols), dtype=np.int64)
    blocked = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        blocked &= above[t]
        age[held] += 1
        ex = held & (leave[t] | (age >= d))
        blocked |= held & ~leave[t] & (age >= d)
        en = ~held & ~blocked & enter[t] & (size[t] > 0)
        row[ex] = 0.0
        row[en] = size[t, en]
        held = (held & ~ex) | en
        age[ex | en] = 0
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def rule_weights(P: fc.Panel, rule: str) -> tuple[np.ndarray, int | None]:
    """(targets, slots): the rule's weight matrix and, for H, its slot count K (the simulator sizes by it)."""
    from . import memecoins as w7
    from . import smallaccount as s1
    from . import trend_shorts as ts
    if rule.startswith("H:"):
        n, d, k = (int(x[1:]) for x in rule.split(":")[1:])
        return h_weights(P, n, d, k), k
    if rule == "tsmom1":
        return s1.candidate(P, "tsmom_top20", 1), None
    if rule in ("breakout_sol3", "breakout_sol10"):
        # smallaccount.candidate's breakout_sol, the mint list matched on the panel's bases (1000BONK is BONK)
        from ..onchain import mints
        from . import alpaca_universe as au
        n = int(rule[len("breakout_sol"):])
        member = np.array([b in mints.COINS for b in P.bases])
        return s1._breakout(P, au.top_within(P, member, n), 20, n, False), None
    if rule == "memes_rotation":
        return w7.rotation(P, P.eligible & w7.member(P, w7.ALPACA_MEMES)[None, :], 1), None
    if rule == "breakout_top10_ls":
        top10 = P.top_liquid(10)
        cols = np.flatnonzero(top10.any(0))
        BL = ts.donchian_side(P, cols, top10, 20, 10, +1)
        return ts.combine(BL, ts.donchian_side(P, cols, top10, 20, 10, -1, flat=P.btc_on, size_mult=0.5)), None
    if rule == "tsmom_top20_ls":
        top20 = P.top_liquid(20)
        return ts.tsmom_side(P, top20, +1) * P.btc_on[:, None] + 0.5 * ts.tsmom_side(P, top20, -1), None
    return s1.candidate(P, rule), None


# ---------------------------------------------------------------- the account

@dataclass
class Market:
    """What the simulator reads, (T, N) on the panel's rows: open-to-open returns, the funding of each day, the
    slippage a side, where an order may be sent and where a position must go."""
    O: np.ndarray
    ret: np.ndarray           # open of t to open of t+1 (to the close of t on a coin's last bar)
    last: np.ndarray          # day t is the coin's last bar: closed at its close
    fund: np.ndarray          # the day's funding sum (a long pays it)
    slip: np.ndarray
    tradable: np.ndarray      # a bar on day t and (judged universe) listed on Hyperliquid that day
    vol: np.ndarray           # 28-day volume: the order of new positions when the cap binds
    hl_rec: np.ndarray        # the day's funding is Hyperliquid's own record


def make_market(P: fc.Panel, Dy: dt.Daily, cols: np.ndarray, listed: np.ndarray | None, fund: np.ndarray,
                top: np.ndarray, hl_rec: np.ndarray | None = None) -> Market:
    O = Dy.o[:, cols]
    nxt = np.vstack([O[1:], np.full((1, O.shape[1]), np.nan)])
    last = np.isfinite(O) & ~np.isfinite(nxt)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.where(last, P.close / O - 1, nxt / O - 1)
    ok = np.isfinite(O) & np.isfinite(ret)
    tradable = ok & (listed[:, cols] if listed is not None else True)
    return Market(O, np.where(ok, ret, 0.0), last, np.nan_to_num(fund[:, cols]),
                  np.where(top[:, cols], SLIP_TOP, SLIP_REST), tradable, np.nan_to_num(P.adv28),
                  hl_rec[:, cols] if hl_rec is not None else np.zeros(O.shape, dtype=bool))


def simulate(M: Market, W: np.ndarray, t0: int, t1: int, capital: float | None, slots: int | None = None,
             late: bool = False) -> dict:
    """The account over days t0..t1 (rows): decisions at the close of t, orders at the open of t+1 (t+2 late),
    held over the day at open-to-open returns with the day's funding. capital None: the ideal account (any size,
    no minimum, no position cap, the equity a unit). A target is traded when it differs from the last target sent;
    an order under the minimum, or a new position beyond floor(equity / 10 USD), is not sent and tried again the
    next day; a full close is always sent. Returns the daily returns of days t0..t1 and the counts."""
    T, N = W.shape
    Wd = np.vstack([np.full((1, N), np.nan), W[:-1]]) if late else W
    # The rule's targets as they stand before the first decision: an account starts where the rule stands.
    want = np.zeros(N)
    if t0 > 1:
        have = np.isfinite(Wd[:t0 - 1])
        k = np.where(have.any(0), t0 - 2 - np.argmax(have[::-1], 0), -1)
        want = np.where(k >= 0, Wd[np.maximum(k, 0), np.arange(N)], 0.0)
    last = np.zeros(N)                  # the last target sent
    pos = np.zeros(N)                   # signed notional
    pend = np.zeros(N, dtype=bool)      # an entry decided, not sent yet
    why = np.zeros(N, dtype=np.int8)    # 1 the minimum, 2 the position cap
    eq = float(capital) if capital else 1.0
    out = np.zeros(t1 - t0 + 1)
    c = {"entries": 0, "sent": 0, "skip_min": 0, "skip_cap": 0, "resize_skipped": 0, "orders": 0, "costs": 0.0,
         "funding": 0.0, "traded": 0.0, "forced": 0, "held_days": 0, "held_hl": 0}
    first = want != 0

    def drop(js):
        for j in js:
            if why[j] == 1:
                c["skip_min"] += 1
            elif why[j] == 2:
                c["skip_cap"] += 1
            pend[j] = False
            why[j] = 0

    for t in range(t0 - 1, t1):
        row = Wd[t]
        set_ = np.isfinite(row)
        new = (set_ & (row != 0) & (want == 0)) | first
        first = np.zeros(N, dtype=bool)
        gone = set_ & (row == 0) & (want != 0)
        want = np.where(set_, row, want)
        drop(np.flatnonzero(gone & pend))
        a = t + 1
        start = eq
        cost = 0.0
        # Positions the venue no longer carries go at this open.
        for j in np.flatnonzero((pos != 0) & ~M.tradable[a]):
            cost += abs(pos[j]) * (FEE + M.slip[a, j])
            pos[j] = 0.0
            last[j] = want[j]
            c["forced"] += 1
        new &= (want != 0) & (pos == 0) & ~pend
        pend |= new
        c["entries"] += int(new.sum())
        cap = math.floor(eq / MIN_ORDER) if capital else N
        S = (min(slots, max(cap, 1)) if capital else slots) if slots else 1
        tgt = want / S
        gross = np.abs(tgt).sum()
        scale = 1.0 / gross if gross > 1 else 1.0
        js = np.flatnonzero((want != last) & M.tradable[a])
        # Closes and reductions first (they free room), then the rest by volume.
        js = js[np.lexsort((-M.vol[a, js], np.abs(want[js]) >= np.abs(last[js])))]
        for j in js:
            goal = tgt[j] * scale * eq
            delta = goal - pos[j]
            if capital:
                if goal != 0 and pos[j] == 0:
                    if abs(goal) < MIN_ORDER:
                        why[j] = max(why[j], 1)
                        continue
                    if int((pos != 0).sum()) >= cap:
                        why[j] = 2
                        continue
                elif goal != 0 and abs(delta) < MIN_ORDER:
                    c["resize_skipped"] += 1
                    continue
            if pos[j] == 0 and goal != 0 and pend[j]:
                c["sent"] += 1
                pend[j] = False
                why[j] = 0
            cost += abs(delta) * (FEE + M.slip[a, j])
            c["traded"] += abs(delta)
            c["orders"] += 1
            pos[j] = goal
            last[j] = want[j]
        f = float(np.dot(pos, M.fund[a]))
        c["held_days"] += int((pos != 0).sum())
        c["held_hl"] += int(((pos != 0) & M.hl_rec[a]).sum())
        pnl = float(np.dot(pos, M.ret[a]))
        pos = pos * (1 + M.ret[a])
        ends = (pos != 0) & M.last[a]
        if ends.any():
            cost += float((np.abs(pos[ends]) * (FEE + M.slip[a][ends])).sum())
            last[ends] = want[ends]
            pos[ends] = 0.0
            c["forced"] += int(ends.sum())
        eq = eq + pnl - f - cost
        c["costs"] += cost
        c["funding"] += f
        if eq <= 0:
            out[a - t0] = -1.0
            break
        out[a - t0] = eq / start - 1
    drop(np.flatnonzero(pend))
    c["end"] = eq
    return {"ret": out, **c}


# ---------------------------------------------------------------- the numbers

def ann_sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    return float(x.mean() / x.std() * math.sqrt(YEAR)) if len(x) > 1 and x.std() > 0 else 0.0


def cagr(x: np.ndarray) -> float:
    return float(np.exp(np.sum(np.log1p(np.maximum(x, -0.999)))) ** (YEAR / max(len(x), 1)) - 1)


def max_dd(x: np.ndarray) -> float:
    if not len(x):
        return 0.0
    e = np.cumprod(1 + np.maximum(x, -0.999))
    return float(np.max(1 - e / np.maximum.accumulate(np.r_[1.0, e])[1:]))


def boot_q05(x: np.ndarray, idx: np.ndarray) -> float:
    """5 % quantile of the stationary bootstrap of the mean of x."""
    return float(np.quantile(x[idx].mean(1), 0.05))


def trial_id(rule: str, account: str, fill: str) -> str:
    return f"small:sw1:{rule}:{account}:{fill}"


def trials(is_sharpe: dict) -> list[dict]:
    return [{"id": trial_id(r, a, f), "family": "small", "source": PREREG, "sharpe": is_sharpe.get((r, a, f))}
            for r in rules() for a in ACCOUNTS for f in FILLS]


def judge(res: dict, btc: np.ndarray, pool: dict, pool_small: dict, idx: np.ndarray) -> list[dict]:
    """One row per (rule, account): the out-of-sample numbers on the judged universe against the prereg's pass."""
    btc_s = ann_sharpe(btc)
    rows = []
    for rule in rules():
        for acc in ACCOUNTS:
            b, l, i = res[(rule, acc, "base")], res[(rule, acc, "late")], res[("is", rule, acc, "base")]
            x = b["ret"]
            ex = x - btc
            r = {"rule": rule, "account": acc, "sharpe": ann_sharpe(x), "cagr": cagr(x), "max_dd": max_dd(x),
                 "end": b["end"], "late_sharpe": ann_sharpe(l["ret"]),
                 "late_cagr": cagr(l["ret"]), "btc_sharpe": btc_s, "excess_ann": float(ex.mean() * YEAR),
                 "band05_ann": boot_q05(ex, idx) * YEAR, "dsr": metrics.dsr(x, pool), "dsr_small": metrics.dsr(x, pool_small),
                 "dsr_excess": metrics.dsr(ex, pool), "entries": b["entries"], "sent": b["sent"],
                 "skip_min": b["skip_min"], "skip_cap": b["skip_cap"], "resize_skipped": b["resize_skipped"],
                 "orders": b["orders"], "is_sharpe": ann_sharpe(i["ret"]), "is_cagr": cagr(i["ret"]),
                 "is_max_dd": max_dd(i["ret"]), "is_entries": i["entries"], "is_skip_min": i["skip_min"],
                 "is_skip_cap": i["skip_cap"], "exposure": float(np.mean(x != 0)),
                 "cost_ann": b["costs"] / (ACCOUNTS[acc] or 1.0) * YEAR / len(x),
                 "funding_ann": b["funding"] / (ACCOUNTS[acc] or 1.0) * YEAR / len(x)}
            n = r["entries"]
            r["skip_share"] = (r["skip_min"] + r["skip_cap"]) / n if n else float("nan")
            fails = []
            if acc == "ideal":
                r["pass"], r["why"] = False, "reference, not judged"
                rows.append(r)
                continue
            if not (r["sharpe"] > btc_s):
                fails.append(f"Sharpe {r['sharpe']:.2f} vs BTC {btc_s:.2f}")
            if not r["late_sharpe"] > 0:
                fails.append(f"late {r['late_sharpe']:.2f}")
            if not r["band05_ann"] > 0:
                fails.append(f"band {r['band05_ann'] * 100:.1f} %")
            if not r["dsr"] >= DSR_PASS:
                fails.append(f"DSR {r['dsr']:.3f}")
            if not r["sent"] >= MIN_ENTRIES:
                fails.append(f"{r['sent']} entries")
            r["pass"], r["why"] = not fails, "; ".join(fails)
            rows.append(r)
    return rows


# ---------------------------------------------------------------- the report

HEAD = """# SW1: the lab's swing rules and a short hold grid on the rug-free coin universe, at Hyperliquid's costs

Pre-registered in `results/swing_sw1_prereg.md` (committed before the first run). Code: `lab.experiments.swing_sw1`,
tests `tests/test_swing_sw1.py`. Paper only: nothing a live bot, a wallet or the engine reads changed.
"""


def _f(v, nd: int = 2, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    v = float(v)
    if not math.isfinite(v):
        return "n/a"
    return f"{v * 100:.{nd}f} %" if pct else f"{v:.{nd}f}"


def markdown(o: dict) -> str:
    rows = o["rows"]
    p = o["pool"]
    md = [f"Generated {o['generated']}. Binance USD-M daily klines (and 1-hour klines for the realised variance) "
          f"to 2026-06-30, nothing after it read (the lockbox untouched); in sample 2022-01-01 to 2024-12-31 on the "
          f"whole Binance universe, judged out of sample 2025-01-01 to 2026-06-30 ({o['oos_days']} days) on the coins "
          f"Hyperliquid listed each day. {len(rules())} rules, 3 accounts, 2 fills: {len(o['trials'])} trials in R5's "
          f"registry (small family, each with its in-sample Sharpe, registered before any out-of-sample number); "
          f"pool of all {p['n_trials']} trials, noise bar {p['sr0_annual']:.2f} a year (small family "
          f"{o['pool_small']['n_trials']}, {o['pool_small']['sr0_annual']:.2f}). BTC held (perp, open to open, no cost) "
          f"out of sample: Sharpe {o['btc_sharpe']:.2f}, CAGR {_f(o['btc_cagr'], 1, True)}, drawdown "
          f"{_f(o['btc_dd'], 1, True)}.\n",
          f"Passed: {', '.join(o['passed']) or 'none'}.\n"]
    md.append("## Out of sample at 50 EUR (57 USD), on time\n\nSharpe and CAGR of the account; late: one day late; "
              "band: 5 % quantile of the bootstrap of the mean daily excess over BTC, a year; entries: the rule's "
              "entries out of sample, sent, and the share the 10 USD minimum or the position cap skipped.\n")
    cols = [("rule", "rule"), ("sharpe", "Sharpe"), ("cagr", "CAGR"), ("max_dd", "max DD"), ("end", "end USD"),
            ("late_sharpe", "late"), ("excess_ann", "excess"), ("band05_ann", "band"), ("dsr", "DSR"),
            ("dsr_excess", "DSR excess"), ("entries", "entries"), ("sent", "sent"), ("skip_share", "skipped"),
            ("cost_ann", "costs/yr"), ("funding_ann", "funding/yr"), ("is_sharpe", "IS Sharpe"), ("why", "fails")]
    pct = {"cagr", "max_dd", "excess_ann", "band05_ann", "skip_share", "cost_ann", "funding_ann"}

    def table(acc: str, sel=lambda r: True) -> list[str]:
        out = ["| " + " | ".join(h for _, h in cols) + " |", "|" + "---|" * len(cols)]
        for r in rows:
            if r["account"] == acc and sel(r):
                out.append("| " + " | ".join(
                    (str(r[k]) if k in ("rule", "why") else
                     _f(r[k], 3 if k.startswith("dsr") else (1 if k in pct else 2), k in pct)) for k, _ in cols) + " |")
        return out
    md += table("57usd")
    md.append("\n## Out of sample at 200 EUR (228 USD), on time\n")
    md += table("228usd")
    md.append("\n## The ideal account (any size, no minimum, no position cap): the rules themselves, end as a "
              "multiple of the start\n")
    md += table("ideal")
    md.append("\n## The universe (DT1's rule), coins a day per quarter\n")
    md.append("| quarter | 50 M mean | 50 M max | on Hyperliquid mean | on Hyperliquid max |\n|---|---|---|---|---|")
    for u in o["universe"]:
        md.append(f"| {u['quarter']} | {u['mean_50M']:.1f} | {u['max_50M']} | {u['mean_50M_hl']:.1f} | "
                  f"{u['max_50M_hl']} |")
    b = o["bar_check"]
    md.append(f"\n## Checks\n\n- 1-hour bars against the daily klines: {b['days']} coin-days, close within 0.1 % on "
              f"{_f(b['close_agree'], 1, True)}, quote volume on {_f(b['qv_agree'], 1, True)}.\n"
              f"- Funding out of sample on the judged universe: Hyperliquid's hourly rates on "
              f"{_f(o['fund_hl_share'], 1, True)} of the coin-days the rules held (ideal account), Binance's on the "
              f"rest.\n")
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------- the run

def window(P: fc.Panel, first: str, last: str) -> tuple[int, int]:
    d = P.days // dt.DAY_US
    return int(np.searchsorted(d, dt.dnum(first))), int(np.searchsorted(d, dt.dnum(last)))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .. import report
    from . import director_common as dc
    rep = report.REPORTS / NAME
    Dy = dt.to_daily(dt.load_daily())
    Q = dt.qualifies(Dy)
    if "--fetch" in argv:
        print(fetch(needed_months(Dy, Q)))
        return 0
    if "--report" in argv:
        o = json.loads((rep / "latest.json").read_text(encoding="utf-8"))
        dc.write_results(NAME, markdown(o), HEAD)
        return 0
    register = "--no-register" not in argv
    t_0 = time.time()
    log = lambda s: print(f"[{time.time() - t_0:.0f} s] {s}", flush=True)       # noqa: E731
    hl = dt.listed_mask(Dy, dt.hl_listings())
    names = set(Dy.names[j] for j in np.flatnonzero(Q.any(0))) | {"BTCUSDT", "ETHUSDT"}
    cols = np.array(sorted(Dy.names.index(s) for s in names))
    rv, bar_check = load_rv(Dy, [Dy.names[j] for j in cols])
    fb, fh = funding_tables(Dy, cols)
    vol = dt.trailing_volume(Dy.qv)
    ex = np.array([dt.excluded(s) for s in Dy.names])
    v = np.where(np.isfinite(vol) & ~ex[None, :], vol, -1)
    top = (np.argsort(np.argsort(-v, axis=1), axis=1) < dt.TOP_N) & (v > 0)
    log("data ready")
    P_bn = make_panel(Dy, cols, Q, rv)
    P_hl = make_panel(Dy, cols, Q & hl, rv)
    M_bn = make_market(P_bn, Dy, cols, None, fb, top)
    M_hl = make_market(P_hl, Dy, cols, hl, np.where(np.isfinite(fh), fh, fb), top, np.isfinite(fh))
    i0, i1 = window(P_bn, IS_FROM, IS_TO)
    o0, o1 = window(P_bn, OOS_FROM, OOS_TO)
    res = {}
    for rule in rules():
        W_bn, k = rule_weights(P_bn, rule)
        W_hl, _ = rule_weights(P_hl, rule)
        for acc, cap in ACCOUNTS.items():
            for fill in FILLS:
                late = fill == "late"
                res[("is", rule, acc, fill)] = simulate(M_bn, W_bn, i0, i1, cap, k, late)
                res[(rule, acc, fill)] = simulate(M_hl, W_hl, o0, o1, cap, k, late)
        log(f"{rule} done")
    is_sharpe = {(r, a, f): ann_sharpe(res[("is", r, a, f)]["ret"]) for r in rules() for a in ACCOUNTS for f in FILLS}
    T = trials(is_sharpe)
    if register:
        metrics.register(T)                      # before any out-of-sample number
    pool = metrics.trial_pool(None, extra=T)
    pool_small = metrics.trial_pool("small", extra=T)
    j = P_bn.col("BTCUSDT")
    btc = M_bn.ret[o0:o1 + 1, j]
    idx = metrics.stationary_bootstrap(len(btc), BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED)
    rows = judge(res, btc, pool, pool_small, idx)
    hd = sum(res[(r, "ideal", "base")]["held_days"] for r in rules())
    hh = sum(res[(r, "ideal", "base")]["held_hl"] for r in rules())
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": rows,
           "pool": {k: pool[k] for k in ("n_trials", "var", "sr0_annual")},
           "pool_small": {k: pool_small[k] for k in ("n_trials", "var", "sr0_annual")},
           "oos_days": int(len(btc)), "btc_sharpe": ann_sharpe(btc), "btc_cagr": cagr(btc), "btc_dd": max_dd(btc),
           "universe": dt.universe_counts(Dy, hl), "bar_check": bar_check,
           "fund_hl_share": hh / hd if hd else float("nan"),
           "trials": [t["id"] for t in T],
           "passed": [f"{r['rule']}:{r['account']}" for r in rows if r["pass"]]}
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), HEAD)
    log(f"done; passed: {out['passed'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
