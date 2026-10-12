"""C6 · Does M2 make money long-only on spot, on the coins the paper broker lists?

    python -m lab.experiments.m2_longonly            # --refit retrains every M2 model

The paper account trades 15 coins spot, long-only (ALPACA below), at 25 bps
taker and 15 bps maker per side. M2 (picks.py) ranks coins by next-week return;
its skill is mostly in spotting losers. Three ways to use it long-only:

  a  filter    M2 as an exclusion filter on the two sweep books restricted to
               the 15 coins: tsmom (28d momentum, vol 40 %, regime filter) and
               breakout (Donchian 20/10). A coin is dropped (tsmom) or not
               entered, optionally also sold (breakout), while M2 ranks it low:
               below a percentile of the whole Binance universe that day, or
               among the worst 3 or 5 of the eligible 15.
  b  top-k     every 7 days hold the k best-ranked of the 15 equally (k 3, 5, 7),
               with and without the 200-day BTC regime filter, run as seven
               staggered weekly tranches so no weekday is picked. Baselines: the
               same with plain 28-day momentum, the 15 equally, BTC.
  c  timing    hold the 15 equally (or BTC), go to cash when M2 says the market
               is broadly negative. A LambdaRank score has no level (the features
               are cross-sectional ranks), so two readings are tried: the 15's
               mean M2 percentile in the whole universe (majors expected to lag),
               and M2-abs, a twin of M2 with the same features un-ranked and the
               raw 7-day return as label, whose median prediction over the
               eligible universe (or mean over the 15) is the market call.
               Counted next to them: the 200-day BTC rule on the same books.

M2 is retrained point in time, every month, on everything that ended 7 days
(the label horizon) before the month starts, on the whole survivorship-free
universe (every USDT pair Binance ever listed, delisted ones included). The
deployed book retrains weekly; monthly here is the staler, conservative case.
Scores exist from 2022-01-01.

Pre-registered before the run:
  selection window  2022-01-01 to 2023-12-31: the pick of each sub-family is the
                    M2 variant with the best Sharpe there at the base cost
  holdout           2024-01-01 to the last bar: the pick is judged here
  costs             30 bps per unit of one-way turnover (25 bps taker plus about
                    5 bps half-spread) and 60 bps (doubled)
  pass              holdout deflated p > 0.95 over every variant of this study;
                    Sharpe > 0 at 60 bps; drawdown below BTC's; Sharpe above its
                    no-M2 baseline with a paired stationary bootstrap share above
                    0.90; and the survivorship-free twin (the same rule on the 15
                    most liquid coins of each day instead of today's Alpaca list)
                    also above its own baseline.

Survivorship: the 15 coins are the ones that survived to be listed by the
broker in 2026, which flatters every book on them, baselines included. The
comparisons with a baseline on the same coins are fair; absolute numbers are
not. The twin on the point-in-time top 15 by volume is the honest number and
the one a paper book's evidence quotes.

Timing as in the sweep: a weight decided at the close of day t (00:00 UTC)
earns day t+1; M2's features use that close.
"""

from __future__ import annotations

import json
import sys
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import polars as pl

from . import blend_study as bl
from . import fam_common as fc
from . import picks

NAME = "m2_longonly"
ALPACA = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "BCH", "UNI", "AAVE",
          "PEPE", "FIL")
COSTS = {"30bps": 0.0030, "60bps": 0.0060}
BASE_COST = "30bps"
FIRST_SCORE = datetime(2022, 1, 1, tzinfo=timezone.utc)
HOLDOUT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
SEL_START = int(FIRST_SCORE.timestamp() * 1e6)
ABS_PARAMS = dict(objective="huber", alpha=0.15, n_estimators=400, learning_rate=0.03, num_leaves=31,
                  min_child_samples=200, subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
                  reg_lambda=5.0, n_jobs=4, verbose=-1)
PCT_CUTS = (0.2, 1 / 3, 0.5)       # drop below this percentile of the whole universe
WORST_N = (3, 5)                   # or among the worst n of the eligible 15
TOP_K = (3, 5, 7)
REL_CUTS = (0.4, 0.5)              # timing: cash when the 15's mean percentile is below this
TRANCHES = 7
BOOT_DRAWS, BOOT_BLOCK = 5_000, 20
YEARS = range(2022, 2027)


# ---------------------------------------------------------------------------
# M2, point in time
# ---------------------------------------------------------------------------

def month_starts(first: datetime, last_us: int) -> list[int]:
    out, y, m = [], first.year, first.month
    while True:
        us = int(datetime(y, m, 1, tzinfo=timezone.utc).timestamp() * 1e6)
        if us > last_us:
            return out
        out.append(us)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def walk_scores(days: np.ndarray, fit, X: np.ndarray, starts: list[int], embargo_d: int = picks.HORIZON,
                log=print) -> np.ndarray:
    """Out-of-sample predictions: the model for [start, next start) is fitted by
    fit(train_mask) on rows whose day is more than embargo_d days before start,
    so no training label reaches into the test period."""
    out = np.full(len(days), np.nan)
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else int(days.max()) + 1
        test = (days >= s) & (days < e)
        if not test.any():
            continue
        train = days < s - embargo_d * fc.DAY_US
        out[test] = fit(train).predict(X[test])
        log(f"  fold {datetime.fromtimestamp(s / 1e6, timezone.utc):%Y-%m} trained on {train.sum():,} rows")
    return out


def fit_rank(days: np.ndarray, X: np.ndarray, y: np.ndarray, fwd: np.ndarray, train: np.ndarray):
    tr = train & np.isfinite(fwd)
    order = np.argsort(days[tr], kind="stable")
    _, group = np.unique(days[tr][order], return_counts=True)
    return lgb.LGBMRanker(**picks.PARAMS).fit(X[tr][order], y[tr][order].astype(np.int32), group=group)


def fit_abs(X: np.ndarray, fwd: np.ndarray, train: np.ndarray):
    tr = train & np.isfinite(fwd)
    return lgb.LGBMRegressor(**ABS_PARAMS).fit(X[tr], np.clip(fwd[tr], -1.0, 1.0))


def m2_scores(refit: bool = False) -> pl.DataFrame:
    """(day, symbol, score, pct, abs_pred) for every eligible coin-day from 2022:
    M2's out-of-sample score, its percentile in that day's whole universe, and
    the M2-abs prediction of the raw 7-day log return."""
    cache = fc.OUT / "cache" / "m2_longonly_scores.parquet"
    if cache.exists() and not refit:
        return pl.read_parquet(cache)
    raw = picks.build_raw()
    P = picks.rank_cross_section(raw, picks.FEATURES)
    raw = raw.join(P.select("day", "symbol"), on=["day", "symbol"], how="semi").sort(["day", "symbol"])
    assert raw.height == P.height
    days = P["day"].to_numpy()
    fwd = P["fwd"].to_numpy()
    starts = month_starts(FIRST_SCORE, int(days.max()))
    Xr = P.select(picks.FEATURES).to_numpy().astype(np.float32)
    y = P["label"].to_numpy()
    print("M2 (LambdaRank), monthly walk-forward", flush=True)
    score = walk_scores(days, lambda tr: fit_rank(days, Xr, y, fwd, tr), Xr, starts)
    Xa = raw.select(picks.FEATURES).to_numpy().astype(np.float32)
    print("M2-abs (raw features, raw label), monthly walk-forward", flush=True)
    absp = walk_scores(days, lambda tr: fit_abs(Xa, fwd, tr), Xa, starts)
    ok = np.isfinite(score)
    out = (pl.DataFrame({"day": days[ok], "symbol": P["symbol"].to_numpy()[ok], "score": score[ok],
                         "abs_pred": absp[ok], "fwd": fwd[ok]})
           .with_columns(pct=(pl.col("score").rank().over("day") - 1) / (pl.len().over("day") - 1).clip(1)))
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(cache)
    return out


def score_matrices(P: fc.Panel, s: pl.DataFrame) -> dict[str, np.ndarray]:
    """The scores as (T, N) matrices over the panel, NaN where a coin was not scored."""
    di = {int(d): i for i, d in enumerate(P.days)}
    ni = {n: j for j, n in enumerate(P.names)}
    keep = [(di.get(int(d)), ni.get(n)) for d, n in zip(s["day"].to_numpy(), s["symbol"].to_list())]
    rows = np.array([-1 if a is None or b is None else a for a, b in keep])
    cols = np.array([-1 if a is None or b is None else b for a, b in keep])
    m = rows >= 0
    out = {}
    for c in ("score", "pct", "abs_pred"):
        x = np.full((P.T, P.N), np.nan)
        x[rows[m], cols[m]] = s[c].to_numpy()[m]
        out[c] = x
    return out


# ---------------------------------------------------------------------------
# Universes and books
# ---------------------------------------------------------------------------

def alpaca_mask(P: fc.Panel, coins=ALPACA) -> np.ndarray:
    """Eligible days of the broker's coins (the live segment of each ticker only)."""
    cols = np.array([b in coins and "~" not in n for b, n in zip(P.bases, P.names)])
    return P.eligible & cols[None, :]


def universes(P: fc.Panel) -> dict[str, np.ndarray]:
    return {"alpaca15": alpaca_mask(P), "top15 liquid": P.top_liquid(15)}


def low_mask(U: np.ndarray, S: dict[str, np.ndarray], how: tuple[str, float]) -> np.ndarray:
    """Coins M2 ranks low on day t, among U. ("pct", c): below percentile c of the
    whole universe; ("worst", n): among the n lowest scores of U that day. A coin
    without a score is never low."""
    kind, v = how
    if kind == "pct":
        with np.errstate(invalid="ignore"):
            return U & (S["pct"] < v)
    sc = np.where(U & np.isfinite(S["score"]), S["score"], np.inf)
    rank = np.argsort(np.argsort(sc, axis=1), axis=1)
    n_ok = np.isfinite(np.where(U, S["score"], np.nan)).sum(1, keepdims=True)
    return U & np.isfinite(S["score"]) & (rank < int(v)) & (n_ok > int(v))


def tsmom_weights(P: fc.Panel, U: np.ndarray, drop: np.ndarray | None = None) -> np.ndarray:
    """fam_volmom.base_weights on the universe U (28d momentum, 40 % vol, slots = |U|,
    regime on). Dropped coins keep their slot empty: the book is not re-levered."""
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[28:] = P.px[28:] / P.px[:-28] - 1
    held = U & np.isfinite(past) & (past > 0)
    W = fc.vol_sized(P, held, 0.40, U.sum(1))
    if drop is not None:
        W = np.where(drop, 0.0, W)
    return W * P.btc_on[:, None]


def breakout_weights(P: fc.Panel, U: np.ndarray, block: np.ndarray | None = None, sell: bool = False,
                     n: int = 20, slots: int = 15) -> np.ndarray:
    """fam_breakout.breakout_weights (Donchian n/n/2, no regime) on U, with M2:
    no entry while `block`, and if `sell`, a held coin is also sold when blocked."""
    cols = np.flatnonzero(U.any(0))
    px = P.px[:, cols]
    hi = fc.rolling_extreme(px, n, "max")
    lo = fc.rolling_extreme(px, n // 2, "min")
    b = np.zeros_like(px, dtype=bool) if block is None else block[:, cols]
    with np.errstate(invalid="ignore"):
        enter = (px > hi) & U[:, cols] & ~b
        leave = (px < lo) | ~P.alive[:, cols] | (b if sell else False)
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.nan_to_num(np.minimum(0.40 / (P.sigma[:, cols] * np.sqrt(365)) / slots, 1.0 / slots))
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        ex = held & leave[t]
        en = ~held & enter[t] & (size[t] > 0)
        row[ex] = 0.0
        row[en] = size[t, en]
        held = (held & ~ex) | en
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def sticky_equal(mask: np.ndarray) -> np.ndarray:
    """Equal weight on mask[t], traded only when the set changes (NaN rows: drift)."""
    W = fc.equal_weight(mask)
    same = np.r_[False, (mask[1:] == mask[:-1]).all(1)]
    W[same] = np.nan
    return W


def topk_mask(score: np.ndarray, U: np.ndarray, k: int) -> np.ndarray:
    """The k highest scores among U each day (empty on days with fewer than k scored)."""
    s = np.where(U & np.isfinite(score), score, -np.inf)
    rank = np.argsort(np.argsort(-s, axis=1), axis=1)
    ok = np.isfinite(np.where(U, score, np.nan)).sum(1, keepdims=True) >= k
    return U & np.isfinite(score) & (rank < k) & ok


def tranche_book(P: fc.Panel, W: np.ndarray, start: int, name: str, n: int = TRANCHES) -> bl.Book:
    """n sub-accounts with 1/n of the capital each, tranche j trading W on days
    t = j mod n only. The same as weekly rebalancing with no weekday picked."""
    books = [bl.sim_long(P, W, rebalance=(np.arange(P.T) % n) == j, start=start) for j in range(n)]
    return bl.Book(name, np.mean([b.gross for b in books], 0), np.mean([b.turnover for b in books], 0),
                   np.mean([b.expo for b in books], 0))


def timing_signals(P: fc.Panel, U: np.ndarray, S: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Risk-on flags (True = invested) decided at the close of day t."""
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # days with nothing scored
        rel = np.nanmean(np.where(U, S["pct"], np.nan), 1)
        med = np.nanmedian(np.where(P.eligible, S["abs_pred"], np.nan), 1)
        mean15 = np.nanmean(np.where(U, S["abs_pred"], np.nan), 1)
    scored = np.isfinite(S["score"]).any(1)
    out = {f"15 mean pct >= {c:.1f}": scored & (np.nan_to_num(rel, nan=1.0) >= c) for c in REL_CUTS}
    out["M2-abs universe median >= 0"] = scored & (np.nan_to_num(med, nan=1.0) >= 0)
    out["M2-abs mean of the 15 >= 0"] = scored & (np.nan_to_num(mean15, nan=1.0) >= 0)
    return out


# ---------------------------------------------------------------------------
# Variants
# ---------------------------------------------------------------------------

@dataclass
class Variant:
    book: bl.Book
    sub: str            # sub-family: the pick is made per sub-family
    universe: str
    baseline: str       # name of the no-M2 book it has to beat
    m2: bool            # an M2 trial (pickable) or a baseline


def build_variants(P: fc.Panel, S: dict[str, np.ndarray], start: int) -> list[Variant]:
    out: list[Variant] = []
    btc_w = np.full((P.T, P.N), np.nan)                     # buy once at the start, then hold
    btc_w[start] = 0.0
    btc_w[start, P.btc] = 1.0
    btc = bl.sim_long(P, btc_w, "BTC buy and hold", start=start)
    out.append(Variant(btc, "benchmark", "BTC", "", False))
    for uname, U in universes(P).items():
        tag = f" · {uname}"
        # a: filters
        base = f"tsmom{tag}"
        out.append(Variant(bl.sim_long(P, tsmom_weights(P, U), base, start=start), "filter tsmom", uname, "", False))
        for how in [("pct", c) for c in PCT_CUTS] + [("worst", n) for n in WORST_N]:
            lbl = f"below p{how[1] * 100:.0f}" if how[0] == "pct" else f"worst {how[1]}"
            W = tsmom_weights(P, U, low_mask(U, S, how))
            out.append(Variant(bl.sim_long(P, W, f"tsmom drop {lbl}{tag}", start=start), "filter tsmom", uname,
                               base, True))
        base = f"breakout{tag}"
        out.append(Variant(bl.sim_long(P, breakout_weights(P, U), base, start=start), "filter breakout", uname,
                           "", False))
        for how in [("pct", c) for c in PCT_CUTS] + [("worst", n) for n in WORST_N]:
            lbl = f"below p{how[1] * 100:.0f}" if how[0] == "pct" else f"worst {how[1]}"
            low = low_mask(U, S, how)
            for sell in (False, True):
                W = breakout_weights(P, U, low, sell)
                nm = f"breakout {'block and sell' if sell else 'block entry'} {lbl}{tag}"
                out.append(Variant(bl.sim_long(P, W, nm, start=start), "filter breakout", uname, base, True))
        # b: top-k
        ew_name = f"equal weight{tag}"
        ew = bl.sim_long(P, sticky_equal(U), ew_name, start=start)
        out.append(Variant(ew, "benchmark", uname, "", False))
        mom = np.full_like(P.px, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            mom[28:] = P.px[28:] / P.px[:-28] - 1
        for k in TOP_K:
            mk = topk_mask(mom, U, k)
            mname = f"28d momentum top {k}{tag}"
            out.append(Variant(tranche_book(P, fc.equal_weight(mk), start, mname), "top-k", uname, "", False))
            for regime in (False, True):
                mk = topk_mask(S["score"], U, k)
                W = fc.equal_weight(mk) * (P.btc_on[:, None] if regime else 1.0)
                nm = f"M2 top {k}{' · regime' if regime else ''}{tag}"
                out.append(Variant(tranche_book(P, W, start, nm), "top-k", uname, ew_name, True))
        # c: timing on the 15 equally and on BTC
        on200 = P.btc_on
        for bname, mask in ((ew_name, U), ("BTC", None)):
            sub = "timing equal weight" if mask is not None else "timing BTC"
            if mask is None and uname != "alpaca15":
                break
            onm = np.zeros(P.N, dtype=bool)
            onm[P.btc] = True
            Ubook = mask if mask is not None else (P.eligible & onm[None, :])
            sigs = {"BTC 200d rule": on200, **timing_signals(P, U, S)}
            base_name = ew_name if mask is not None else "BTC buy and hold"
            for sname, on in sigs.items():
                W = sticky_equal(Ubook & on[:, None])
                nm = f"{'equal weight' if mask is not None else 'BTC'} · cash unless {sname}{tag}"
                out.append(Variant(bl.sim_long(P, W, nm, start=start), sub, uname, base_name,
                                   sname != "BTC 200d rule"))
    return out


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def windows(P: fc.Panel, start: int) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(P.T)
    sel = (t > start) & (P.days < HOLDOUT)
    hold = (t > start) & (P.days >= HOLDOUT)
    return sel, hold


def describe(P: fc.Panel, b: bl.Book, start: int) -> dict:
    sel, hold = windows(P, start)
    row = {"variant": b.name}
    for k, c in COSTS.items():
        n = b.net(c)
        row[f"sel_{k}"] = fc.perf(n[sel])["sharpe"]
        po = fc.perf(n[hold])
        row[f"hold_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    row["turnover_yr"] = float(b.turnover[hold].sum() / (hold.sum() / 365))
    row["expo"] = float(b.expo[hold].mean())
    x = b.net(COSTS[BASE_COST])[hold]
    row.update({k: v for k, v in bl.trial_row(x, BASE_COST).items() if k != "variant"})
    return row


def per_year(P: fc.Panel, b: bl.Book, start: int) -> dict:
    yr = bl.years(P)
    n = b.net(COSTS[BASE_COST])
    live = np.arange(P.T) > start
    return {f"y{y}": fc.perf(n[live & (yr == y)])["sharpe"] for y in YEARS}


def deflate(rows: list[dict]) -> dict:
    """Deflated Sharpe of every row against all M2 trials and baselines of this study."""
    key = f"hold_{BASE_COST}"
    pool = [{"oos_sharpe": r[key], "oos_skew": r["oos_skew"], "oos_kurt": r["oos_kurt"],
             "oos_days": r["oos_days"]} for r in rows]
    info = fc.deflate(pool, key="oos_sharpe")
    for r, p in zip(rows, pool):
        r["deflated_p"] = p["deflated_p"]
    return info


def judge(v: dict, base: dict | None, twin: dict | None, twin_base: dict | None, btc_dd: float,
          boot: dict | None) -> tuple[bool, list[str]]:
    why = []
    if v["deflated_p"] <= 0.95:
        why.append(f"deflated p {v['deflated_p']:.2f} <= 0.95")
    if v["hold_60bps"] <= 0:
        why.append(f"Sharpe at 60 bps {v['hold_60bps']:.2f} <= 0")
    if v["dd_30bps"] >= btc_dd:
        why.append(f"drawdown {v['dd_30bps'] * 100:.0f} % not below BTC's {btc_dd * 100:.0f} %")
    if base is not None and v["hold_30bps"] <= base["hold_30bps"]:
        why.append(f"holdout Sharpe {v['hold_30bps']:.2f} not above its baseline's {base['hold_30bps']:.2f}")
    if boot is not None and boot["share_above_0"] <= 0.90:
        why.append(f"bootstrap share above the baseline {boot['share_above_0']:.2f} <= 0.90")
    if twin is not None and twin_base is not None and twin["hold_30bps"] <= twin_base["hold_30bps"]:
        why.append(f"survivorship-free twin {twin['hold_30bps']:.2f} not above its baseline "
                   f"{twin_base['hold_30bps']:.2f}")
    return not why, why


def twin_name(name: str) -> str:
    return name.replace(" · alpaca15", " · top15 liquid")


def run(refit: bool = False) -> dict:
    t0 = time.time()
    P = fc.load_panel()
    S = score_matrices(P, m2_scores(refit))
    start = int(np.searchsorted(P.days, SEL_START))         # first decision at the close of the first scored day
    vs = build_variants(P, S, start)
    rows = [{**describe(P, v.book, start), "sub": v.sub, "universe": v.universe, "baseline": v.baseline,
             "m2": v.m2, **per_year(P, v.book, start)} for v in vs]
    info = deflate(rows)
    by = {r["variant"]: r for r in rows}
    books = {v.book.name: v.book for v in vs}
    btc_dd = by["BTC buy and hold"]["dd_30bps"]
    _, hold = windows(P, start)
    idx = bl.boot_idx(int(hold.sum()), BOOT_BLOCK, BOOT_DRAWS, np.random.default_rng(6))
    picks_out = []
    for sub in sorted({r["sub"] for r in rows if r["m2"]}):
        cands = [r for r in rows if r["m2"] and r["sub"] == sub and r["universe"] == "alpaca15"]
        pick = max(cands, key=lambda r: r[f"sel_{BASE_COST}"])
        base = by.get(pick["baseline"])
        twin = by.get(twin_name(pick["variant"]))
        twin_base = by.get(twin["baseline"]) if twin else None
        net = lambda name: books[name].net(COSTS[BASE_COST])[hold]  # noqa: E731
        boot = bl.boot_diff(net(pick["variant"]), net(base["variant"]), idx) if base else None
        boot_abs = bl.boot_sharpe(net(pick["variant"]), idx)
        ok, why = judge(pick, base, twin, twin_base, btc_dd, boot)
        picks_out.append({"sub": sub, "pick": pick["variant"], "baseline": pick["baseline"], "passes": ok,
                          "why_not": why, "boot_vs_baseline": boot, "boot_sharpe": boot_abs,
                          "twin": twin["variant"] if twin else None})
    return {"rows": rows, "picks": picks_out, "deflation": info, "btc_dd": btc_dd,
            "start": datetime.fromtimestamp(P.days[start + 1] / 1e6, timezone.utc).strftime("%Y-%m-%d"),
            "end": datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc).strftime("%Y-%m-%d"),
            "minutes": (time.time() - t0) / 60}


def main() -> None:
    res = run("--refit" in sys.argv)
    fc.OUT.joinpath("reports").mkdir(parents=True, exist_ok=True)
    (fc.OUT / "reports" / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
    cols = ["variant", "sel_30bps", "hold_30bps", "hold_60bps", "cagr_30bps", "dd_30bps", "turnover_yr", "expo",
            "deflated_p"]
    print(fc.table(res["rows"], cols))
    for p in res["picks"]:
        print(json.dumps(p, default=str))


if __name__ == "__main__":
    main()
