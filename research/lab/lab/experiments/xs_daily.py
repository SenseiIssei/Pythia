"""M4 · Daily cross-sectional ranking: next 1 to 3 day returns, every listed coin.

M2 ranks coins by next-week return and its skill sits in the losers. This
asks whether a richer feature set at a daily horizon finds more, and whether
any of it survives the far higher turnover a daily book pays.

Universe: every USDT pair Binance ever listed (hist/universe.json, delisted
ones included), segmented exactly like M2 (a gap over three days or a tenfold
hourly jump starts a new coin). Eligible on a day: 60 days of history and 1 M
USD average daily volume over 28 days.

Timing, the part that decides whether a daily signal is real:
  features  use bars up to the end of UTC day d (known at 00:00 of d+1)
  entry     the close of the first hour of d+1 (one hour later), never the
            close the features were computed from; short-term reversal is
            where bid-ask bounce and same-bar fills manufacture profits
  return    R_d = P(d+1) / P(d) - 1 between consecutive entry prices
  labels    fwdH = log P(d+H) / P(d), H = 1 and 3 calendar days
A coin whose segment ends (delisting, ticker reuse) keeps its last close, so
the losers that vanished are in the labels and in the P&L.

Features (each ranked across coins per day, like M2): returns over 1, 2, 3, 5,
7, 14, 28, 56 and 112 days and two skip-momentum terms; realised, downside
and vol-of-vol from hourly bars; the largest and smallest daily move of the
month; hourly skew and jump share; volume and trade-size shocks, Amihud
illiquidity, taker share; BTC beta, correlation, residual returns and
idiosyncratic volatility over 56 days; distance from 28, 112 and 365 day
highs and the 28 day low; last-day range and close location; age and
liquidity. Where a USDT perpetual exists: funding over 1 and 7 days, basis,
perp volume share, and for the 20 coins with metrics open-interest changes
and the top-trader long/short ratio. Four day-level columns (BTC 1 and 7 day
return, BTC volatility, cross-sectional dispersion) let the trees condition
on the market.

Models (walk-forward by quarter from 2022, embargo = label horizon + 1 day):
  reg1   LightGBM regression on the cross-sectional rank of fwd1
  reg3   the same on fwd3
  rank3  LightGBM LambdaRank on fwd3 quintiles (M2's objective)

Books (every one deflated together, baselines included):
  long-only  top K of the 100 most liquid eligible coins, K = 10 or 20,
             overlapping tranches held 1 or 3 days, with and without the
             BTC 200-day regime filter
  long/short top 10 long, bottom 10 short among coins with a live USDT perp,
             cut to the 50 or 100 most liquid perps, half the capital per
             side, real funding paid and received; price legs use the spot
             entry prices (perp daily bars cannot be lagged by one hour)
  baselines  the same books on plain 1-day reversal and 28-day momentum,
             the equal-weight liquid universe, BTC

Costs: every book at 15 bps and at 41 bps (Kraken taker) per unit of one-way
turnover. Variant choice uses 2022-2023 only; 2024 on is the holdout.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from .. import report
from ..cv import walk_forward
from ..data import HOUR_US, ROOT
from ..metrics import deflated_sharpe
from .picks import hourly_segments
from .picks_ls import perp_base

DAY_US = 24 * HOUR_US
MIN_HISTORY_D = 60
MIN_ADV_USD = 1_000_000
HORIZONS = (1, 3)
EXTEND_D = 10  # calendar days a dead segment is carried at its last close
FIRST_TEST = int(datetime(2022, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
HOLDOUT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
COSTS = {"15bps": 0.0015, "41bps": 0.0041}
CACHE = Path(os.environ.get("PYTHIA_CACHE", report.REPORTS / "_cache"))

RANKED = ["r1", "r2", "r3", "r5", "r7", "r14", "r28", "r56", "r112", "r28_7", "r112_28",
          "vol7", "vol28", "dn_share28", "volvol28", "vratio", "max28", "min28", "skew28", "jump7",
          "qv_shock1", "qv_shock7", "adv28", "amihud28", "tsize_shock", "taker1", "taker7",
          "beta56", "corr56", "resid1", "resid7", "resid28", "ivol56",
          "dist_hi28", "dist_hi112", "dist_hi365", "dist_lo28", "range1", "clv1", "age",
          "fund1", "fund7", "basis", "perp_share", "oi_chg1", "oi_chg7", "ls_top"]
MARKET = ["btc_r1", "btc_r7", "btc_vol28", "disp1"]
FEATURES = RANKED + MARKET

REG_PARAMS = dict(objective="regression", n_estimators=300, learning_rate=0.03, num_leaves=31,
                  min_child_samples=2000, subsample=0.7, subsample_freq=1, colsample_bytree=0.7,
                  reg_lambda=10.0, n_jobs=8, verbose=-1)
RANK_PARAMS = dict(objective="lambdarank", n_estimators=300, learning_rate=0.03, num_leaves=31,
                   min_child_samples=500, subsample=0.7, subsample_freq=1, colsample_bytree=0.7,
                   reg_lambda=10.0, n_jobs=8, verbose=-1, label_gain=list(range(5)))


# ---------------------------------------------------------------- panel

def _segment_frame(seg: pl.DataFrame, name: str, data_end_us: int, last_segment: bool) -> pl.DataFrame | None:
    h = seg.with_columns(
        r=(pl.col("close").log() - pl.col("close").shift(1).log()).fill_null(0.0),
        day=(pl.col("open_time_us") // DAY_US) * DAY_US,
    )
    daily = (h.group_by("day", maintain_order=True)
             .agg(close=pl.col("close").last(), high=pl.col("high").max(), low=pl.col("low").min(),
                  c_first=pl.col("close").first(),
                  rv=(pl.col("r") ** 2).sum(), rv_dn=(pl.col("r").clip(upper_bound=0.0) ** 2).sum(),
                  cube=(pl.col("r") ** 3).sum(), maxr2=(pl.col("r") ** 2).max(),
                  qv=pl.col("quote_volume").sum(), tbq=pl.col("taker_buy_quote_volume").sum(),
                  trades=pl.col("trades").sum(), n=pl.len()))
    if daily.height < MIN_HISTORY_D + 10:
        return None
    first, last = int(daily["day"][0]), int(daily["day"][-1])
    dead = (not last_segment) or last < data_end_us - 3 * DAY_US
    end = last + (EXTEND_D * DAY_US if dead else 0)
    cal = pl.DataFrame({"day": np.arange(first, end + 1, DAY_US, dtype=np.int64)})
    cal = cal.join(daily.select("day", "c_first"), on="day", how="left")
    # Entry price for a decision at the end of day d: the first hourly close of d+1.
    p = cal["c_first"].shift(-1).to_numpy().copy()
    days = cal["day"].to_numpy()
    if dead:
        p[days == last] = float(seg["close"][-1])
        idx = np.flatnonzero(days > last)
        p[idx] = float(seg["close"][-1])
    p = pl.Series(p).fill_nan(None).fill_null(strategy="forward").to_numpy()
    cal = cal.with_columns(P=pl.Series(p)).drop("c_first")
    if not dead:
        # Live coin: the last decision day has no entry price yet.
        cal = cal.with_columns(P=pl.when(pl.col("day") == last).then(None).otherwise(pl.col("P")))
    lp = pl.col("P").log()
    cal = cal.with_columns(
        R1=pl.col("P").shift(-1) / pl.col("P") - 1,
        **{f"fwd{k}": lp.shift(-k) - lp for k in HORIZONS},
    )

    d = daily.filter(pl.col("n") >= 20)
    lc = pl.col("close").log()
    ret = lc - lc.shift(1)
    f = d.with_columns(ret=ret).with_columns(
        **{f"r{k}": lc - lc.shift(k) for k in (1, 2, 3, 5, 7, 14, 28, 56, 112)},
        vol7=pl.col("rv").rolling_mean(7).sqrt(),
        vol28=pl.col("rv").rolling_mean(28).sqrt(),
        dn_share28=pl.col("rv_dn").rolling_sum(28) / (pl.col("rv").rolling_sum(28) + 1e-12),
        volvol28=(pl.col("rv") + 1e-10).log().rolling_std(28),
        max28=pl.col("ret").rolling_max(28),
        min28=pl.col("ret").rolling_min(28),
        skew28=pl.col("cube").rolling_sum(28) / (pl.col("rv").rolling_sum(28) ** 1.5 + 1e-12),
        jump7=pl.col("maxr2").rolling_sum(7) / (pl.col("rv").rolling_sum(7) + 1e-12),
        qv_shock1=(pl.col("qv") + 1).log() - (pl.col("qv").rolling_mean(28) + 1).log(),
        qv_shock7=(pl.col("qv").rolling_mean(7) + 1).log() - (pl.col("qv").rolling_mean(56) + 1).log(),
        adv28=(pl.col("qv").rolling_mean(28) + 1).log(),
        amihud28=((pl.col("ret").abs() / (pl.col("qv") + 1)).rolling_mean(28) + 1e-15).log(),
        tsize_shock=((pl.col("qv").rolling_sum(7) + 1) / (pl.col("trades").rolling_sum(7) + 1)).log()
        - ((pl.col("qv").rolling_sum(56) + 1) / (pl.col("trades").rolling_sum(56) + 1)).log(),
        taker1=pl.col("tbq") / (pl.col("qv") + 1e-9) - 0.5,
        taker7=pl.col("tbq").rolling_sum(7) / (pl.col("qv").rolling_sum(7) + 1e-9) - 0.5,
        dist_hi28=lc - pl.col("high").rolling_max(28).log(),
        dist_hi112=lc - pl.col("high").rolling_max(112, min_samples=28).log(),
        dist_hi365=lc - pl.col("high").rolling_max(365, min_samples=28).log(),
        dist_lo28=lc - pl.col("low").rolling_min(28).log(),
        range1=(pl.col("high") / pl.col("low")).log() / (pl.col("rv").rolling_mean(28).sqrt() + 1e-9),
        clv1=(pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low") + 1e-12),
        age=pl.int_range(pl.len()).cast(pl.Float64),
    ).with_columns(
        r28_7=pl.col("r28") - pl.col("r7"),
        r112_28=pl.col("r112") - pl.col("r28"),
        vratio=pl.col("vol7") / (pl.col("vol28") + 1e-12),
    ).drop("high", "low", "c_first", "cube", "maxr2", "tbq", "trades", "n", "rv_dn")
    out = cal.join(f, on="day", how="left").with_columns(symbol=pl.lit(name))
    return out


def _symbol_frames(sym: str, data_end_us: int) -> list[pl.DataFrame]:
    segs = hourly_segments(sym)
    out = []
    for j, seg in enumerate(segs):
        name = sym if j == len(segs) - 1 else f"{sym}~{j}"
        fr = _segment_frame(seg, name, data_end_us, j == len(segs) - 1)
        if fr is not None:
            out.append(fr)
    return out


def perp_daily() -> pl.DataFrame:
    """Per (day, base): the most liquid USDT perp's close, volume, funding known at
    the end of day d (fund1, fund7), funding paid over the holding day that starts
    one hour after (fund_hold), its 28-day volume, and metrics where they exist."""
    perps = json.loads((ROOT / "hist" / "um_universe.json").read_text())

    def one(s: str) -> pl.DataFrame | None:
        kd = ROOT / "hist" / "binance_um" / "klines_1d" / f"symbol={s}"
        files = sorted(kd.glob("*.parquet"))
        if not files:
            return None
        k = (pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
             .unique("open_time_us").sort("open_time_us")
             .select(day=(pl.col("open_time_us") // DAY_US) * DAY_US, perp_close="close", perp_qv="quote_volume"))
        fd = ROOT / "hist" / "binance_um" / "funding" / f"symbol={s}"
        ffiles = sorted(fd.glob("*.parquet"))
        if ffiles:
            fu = pl.concat([pl.read_parquet(f) for f in ffiles], how="vertical_relaxed").unique("funding_time_us")
            # Known at the end of day d: settlements in (start of d, start of d+1].
            known = (fu.with_columns(day=((pl.col("funding_time_us") - 1) // DAY_US) * DAY_US)
                     .group_by("day").agg(fund_day=pl.col("funding_rate").sum()))
            # Paid while holding from 01:00 of d+1 to 01:00 of d+2.
            hold = (fu.with_columns(day=((pl.col("funding_time_us") - HOUR_US - 1) // DAY_US) * DAY_US - DAY_US)
                    .group_by("day").agg(fund_hold=pl.col("funding_rate").sum()))
            k = k.join(known, on="day", how="left").join(hold, on="day", how="left")
        else:
            k = k.with_columns(fund_day=pl.lit(None, pl.Float64), fund_hold=pl.lit(None, pl.Float64))
        k = k.sort("day").with_columns(
            fund1=pl.col("fund_day").fill_null(0.0),
            fund7=pl.col("fund_day").fill_null(0.0).rolling_sum(7, min_samples=1),
            fund_hold=pl.col("fund_hold").fill_null(0.0),
            perp_adv28=pl.col("perp_qv").rolling_mean(28, min_samples=7),
        ).drop("fund_day")
        md = ROOT / "hist" / "binance_um" / "metrics" / f"symbol={s}"
        mfiles = sorted(md.glob("*.parquet"))
        if mfiles:
            m = (pl.concat([pl.read_parquet(f) for f in mfiles], how="vertical_relaxed")
                 .unique("ts_us").sort("ts_us")
                 .with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US)
                 .group_by("day").agg(oi=pl.col("sum_open_interest_value").last(),
                                      ls_top=pl.col("sum_toptrader_long_short_ratio").last())
                 .sort("day"))
            # A snapshot stamped exactly 00:00 belongs to the day it closes; the last
            # one inside day d is taken at 23:55, known by the end of d.
            m = m.with_columns(oi_chg1=pl.col("oi").log() - pl.col("oi").log().shift(1),
                               oi_chg7=pl.col("oi").log() - pl.col("oi").log().shift(7)).drop("oi")
            k = k.join(m, on="day", how="left")
        else:
            k = k.with_columns(oi_chg1=pl.lit(None, pl.Float64), oi_chg7=pl.lit(None, pl.Float64),
                               ls_top=pl.lit(None, pl.Float64))
        return k.with_columns(base=pl.lit(perp_base(s)), perp=pl.lit(s))

    with ThreadPoolExecutor(8) as ex:
        frames = [f for f in ex.map(one, perps) if f is not None]
    pp = pl.concat(frames, how="diagonal_relaxed")
    return pp.sort("perp_qv", descending=True).group_by(["day", "base"]).first()


def build_panel(refresh: bool = False) -> pl.DataFrame:
    path = CACHE / "xs_daily_panel.parquet"
    if path.exists() and not refresh:
        return pl.read_parquet(path)
    t0 = time.time()
    syms = json.loads((ROOT / "hist" / "universe.json").read_text())
    btc_segs = hourly_segments("BTCUSDT")
    data_end = int(btc_segs[-1]["open_time_us"].max())
    frames = []
    with ThreadPoolExecutor(6) as ex:
        for i, fr in enumerate(ex.map(lambda s: _symbol_frames(s, data_end), syms)):
            frames.extend(fr)
            if i % 100 == 0:
                print(f"{i}/{len(syms)} symbols, {time.time() - t0:.0f}s", flush=True)
    p = pl.concat(frames, how="vertical_relaxed")
    btc = p.filter(pl.col("symbol") == "BTCUSDT").select(
        "day", btc_ret="ret", btc_r1="r1", btc_r7="r7", btc_vol28="vol28")
    p = p.join(btc, on="day", how="left")
    # Beta, correlation, residuals and idiosyncratic volatility against BTC over 56 days.
    xy = pl.col("ret") * pl.col("btc_ret")
    p = p.sort(["symbol", "day"]).with_columns(
        _mx=pl.col("ret").rolling_mean(56, min_samples=40).over("symbol"),
        _my=pl.col("btc_ret").rolling_mean(56, min_samples=40).over("symbol"),
        _mxy=xy.rolling_mean(56, min_samples=40).over("symbol"),
        _mxx=(pl.col("ret") ** 2).rolling_mean(56, min_samples=40).over("symbol"),
        _myy=(pl.col("btc_ret") ** 2).rolling_mean(56, min_samples=40).over("symbol"),
    ).with_columns(
        _cov=pl.col("_mxy") - pl.col("_mx") * pl.col("_my"),
        _vx=pl.col("_mxx") - pl.col("_mx") ** 2,
        _vy=pl.col("_myy") - pl.col("_my") ** 2,
    ).with_columns(
        beta56=pl.col("_cov") / (pl.col("_vy") + 1e-12),
        corr56=pl.col("_cov") / ((pl.col("_vx") * pl.col("_vy")).sqrt() + 1e-12),
    ).with_columns(
        ivol56=(pl.col("_vx") - pl.col("beta56") ** 2 * pl.col("_vy")).clip(lower_bound=0).sqrt(),
        resid1=pl.col("r1") - pl.col("beta56") * pl.col("btc_r1"),
        resid7=pl.col("r7") - pl.col("beta56") * pl.col("btc_r7"),
    ).drop("_mx", "_my", "_mxy", "_mxx", "_myy", "_cov", "_vx", "_vy")
    btc28 = p.filter(pl.col("symbol") == "BTCUSDT").select("day", _b28="r28")
    p = p.join(btc28, on="day", how="left").with_columns(
        resid28=pl.col("r28") - pl.col("beta56") * pl.col("_b28")).drop("_b28")
    print(f"spot panel built, {time.time() - t0:.0f}s; loading perpetuals", flush=True)
    pf = perp_daily()
    p = (p.with_columns(base=pl.col("symbol").str.strip_suffix("USDT"))
         .join(pf, on=["day", "base"], how="left")
         .with_columns(mult=(pl.col("perp_close") / pl.col("close")).log10().round(0))
         .with_columns(basis=(pl.col("perp_close") / (pl.col("close") * 10 ** pl.col("mult"))).log(),
                       perp_share=((pl.col("perp_qv") + 1) / (pl.col("qv") + 1)).log())
         .drop("perp_close", "mult"))
    elig = (pl.col("age") >= MIN_HISTORY_D) & (pl.col("adv28") >= np.log(MIN_ADV_USD + 1)) \
        & pl.col("r112").is_not_null() & pl.col("P").is_not_null()
    p = p.with_columns(eligible=elig.fill_null(False))
    disp = p.filter("eligible").group_by("day").agg(disp1=pl.col("r1").std())
    p = p.join(disp, on="day", how="left").sort(["day", "symbol"])
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_parquet(path)
    print(f"panel {p.height:,} rows, {p['symbol'].n_unique()} coins, {time.time() - t0:.0f}s", flush=True)
    return p


def ranked(p: pl.DataFrame) -> pl.DataFrame:
    """Eligible rows only, features as cross-sectional ranks in [0, 1] (nulls stay null)."""
    e = p.filter("eligible")
    e = e.with_columns([((pl.col(c).rank().over("day") - 1) / (pl.col(c).count().over("day") - 1).clip(1)).alias(c)
                        for c in RANKED])
    for k in HORIZONS:
        e = e.with_columns(**{
            f"y{k}": (pl.col(f"fwd{k}").rank().over("day") - 1) / (pl.col(f"fwd{k}").count().over("day") - 1).clip(1) - 0.5,
            f"q{k}": ((pl.col(f"fwd{k}").rank().over("day") - 1) * 5 / pl.col(f"fwd{k}").count().over("day"))
            .floor().clip(0, 4).cast(pl.Int32),
        })
    return e.filter(pl.len().over("day") >= 20).sort(["day", "symbol"])


# ---------------------------------------------------------------- models

def daily_ic(days: np.ndarray, a: np.ndarray, b: np.ndarray) -> pl.DataFrame:
    ok = np.isfinite(a) & np.isfinite(b)
    return (pl.DataFrame({"day": days[ok], "a": a[ok], "b": b[ok]})
            .group_by("day").agg(ic=pl.corr("a", "b", method="spearman"), n=pl.len())
            .filter(pl.col("n") >= 10).sort("day"))


def fit_scores(E: pl.DataFrame) -> tuple[dict[str, np.ndarray], list[dict]]:
    days = E["day"].to_numpy()
    X = E.select(FEATURES).to_numpy().astype(np.float32)
    scores = {m: np.full(E.height, np.nan) for m in ("reg1", "reg3", "rank3")}
    folds = []
    specs = {"reg1": ("y1", 1, False), "reg3": ("y3", 3, False), "rank3": ("q3", 3, True)}
    for name, (target, h, is_rank) in specs.items():
        y = E[target].to_numpy()
        yv = np.asarray(y, dtype=float)
        fwd = E[f"fwd{h}"].to_numpy()
        for fold in walk_forward(days, FIRST_TEST, embargo_h=(h + 1) * 24):
            t = time.time()
            tr = fold.train & np.isfinite(yv)
            if is_rank:
                order = np.argsort(days[tr], kind="stable")
                Xt, yt, dt = X[tr][order], yv[tr][order].astype(np.int32), days[tr][order]
                _, group = np.unique(dt, return_counts=True)
                m = lgb.LGBMRanker(**RANK_PARAMS).fit(Xt, yt, group=group)
            else:
                m = lgb.LGBMRegressor(**REG_PARAMS).fit(X[tr], yv[tr])
            scores[name][fold.test] = m.predict(X[fold.test])
            te = fold.test
            ic = daily_ic(days[te], scores[name][te], fwd[te])["ic"].mean()
            # In-sample fit on the last 180 training days, for the IS/OOS ratio.
            last = days[tr].max()
            rec = tr & (days > last - 180 * DAY_US)
            ic_is = daily_ic(days[rec], m.predict(X[rec]), fwd[rec])["ic"].mean()
            folds.append({"model": name, "fold": fold.name, "ic_oos": float(ic), "ic_is_last180d": float(ic_is),
                          "secs": round(time.time() - t)})
            print(folds[-1], flush=True)
    return scores, folds


# ---------------------------------------------------------------- books

def matrices(E: pl.DataFrame, P: pl.DataFrame, score_cols: list[str]):
    """Day x coin matrices: returns from the full panel (dead coins included), the
    rest from the eligible rows."""
    days = np.sort(E["day"].unique().to_numpy())
    syms = np.sort(E["symbol"].unique().to_numpy())
    di = {d: i for i, d in enumerate(days)}
    si = {s: i for i, s in enumerate(syms)}
    T, N = len(days), len(syms)

    def mat(frame: pl.DataFrame, col: str, fill=np.nan) -> np.ndarray:
        m = np.full((T, N), fill, dtype=float)
        f = frame.filter(pl.col("day").is_in(days) & pl.col("symbol").is_in(syms)).select("day", "symbol", col).drop_nulls()
        r = np.array([di[d] for d in f["day"].to_numpy()], dtype=np.int64)
        c = np.array([si[s] for s in f["symbol"].to_numpy()], dtype=np.int64)
        m[r, c] = f[col].to_numpy()
        return m

    out = {"days": days, "syms": syms, "R": mat(P, "R1"), "fund": mat(P, "fund_hold", 0.0)}
    for c in score_cols + ["adv28_raw", "perp_adv28", "r1_raw", "r28_raw", "fund7_raw"]:
        out[c] = mat(E, c)
    return out


def short_ok(M: dict, t: int, i: int, no_paying_shorts: bool) -> bool:
    """picks_ls's rule: skip a short whose funding over the last 7 days was negative
    (there the shorts pay the longs, and a crowded short hands back in funding what it makes)."""
    if not no_paying_shorts:
        return True
    f = M["fund7_raw"][t, i]
    return not (np.isfinite(f) and f < 0)


def book(M: dict, score: np.ndarray, k: int, hold: int, n_liquid: int, long_short: bool,
         regime: np.ndarray | None = None, no_paying_shorts: bool = False):
    """Overlapping tranches: each day 1/hold of the book is re-picked and held hold days.
    Returns gross daily return, turnover, funding, exposure."""
    R = np.nan_to_num(M["R"])
    T, N = R.shape
    liq = M["perp_adv28"] if long_short else M["adv28_raw"]
    tranches_l = [np.zeros(N) for _ in range(hold)]
    tranches_s = [np.zeros(N) for _ in range(hold)]
    w = np.zeros(N)
    gross, turn, fund, expo = (np.zeros(T) for _ in range(4))
    for t in range(T):
        ok = np.isfinite(score[t]) & np.isfinite(liq[t])
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-liq[t, idx])][:n_liquid]
        tl, ts = np.zeros(N), np.zeros(N)
        on = regime is None or bool(regime[t])
        if len(idx) >= 2 * k and on:
            order = idx[np.argsort(-score[t, idx])]
            if long_short:
                tl[order[:k]] = 0.5 / k
                cand = [i for i in order[::-1][:len(order) - k] if short_ok(M, t, i, no_paying_shorts)][:k]
                if len(cand) == k:
                    ts[cand] = -0.5 / k
                else:
                    tl[:] = 0.0  # no full short side: no book today rather than a naked long
            else:
                tl[order[:k]] = 1.0 / k
        tranches_l[t % hold], tranches_s[t % hold] = tl, ts
        tgt = (sum(tranches_l) + sum(tranches_s)) / hold
        turn[t] = np.abs(tgt - w).sum()
        w = tgt
        g = float(np.dot(w, R[t]))
        fund[t] = -float(np.dot(w, M["fund"][t])) if long_short else 0.0
        gross[t] = g
        expo[t] = np.abs(w).sum()
        # Drift to the next day's weights before re-targeting.
        denom = 1 + g
        w = w * (1 + R[t]) / denom if denom > 0 else w
        # Tranches drift too, so a held tranche does not trade on its own.
        tranches_l = [x * (1 + R[t]) / denom if denom > 0 else x for x in tranches_l]
        tranches_s = [x * (1 + R[t]) / denom if denom > 0 else x for x in tranches_s]
    return gross, turn, fund, expo


def book_buffer(M: dict, score: np.ndarray, k: int, exit_frac: float, n_liquid: int,
                no_paying_shorts: bool = False):
    """Long/short with a rank buffer (round two): a name enters a side when it ranks in
    that side's best k and leaves only when it drops out of that side's best exit_frac
    of the liquid perp set (or out of the set). Held names drift with their price and are not re-equalised;
    an entering name gets 0.5 / k, a held one is capped at twice that.
    Returns gross, turnover, funding, exposure."""
    R = np.nan_to_num(M["R"])
    T, N = R.shape
    liq = M["perp_adv28"]
    w = np.zeros(N)
    gross, turn, fund, expo = (np.zeros(T) for _ in range(4))
    for t in range(T):
        ok = np.isfinite(score[t]) & np.isfinite(liq[t])
        idx = np.flatnonzero(ok)
        idx = idx[np.argsort(-liq[t, idx])][:n_liquid]
        tgt = np.zeros(N)
        exit_k = max(k, int(exit_frac * len(idx)))
        if len(idx) >= 2 * k:
            order = idx[np.argsort(-score[t, idx])]
            top_keep, bot_keep = set(order[:exit_k]), set(order[-exit_k:])
            longs = [i for i in np.flatnonzero(w > 0) if i in top_keep]
            shorts = [i for i in np.flatnonzero(w < 0) if i in bot_keep]
            # A held name may drift to twice its entry size, no further (a pumping short is trimmed).
            tgt[longs] = np.minimum(w[longs], 1.0 / k)
            tgt[shorts] = np.maximum(w[shorts], -1.0 / k)
            for i in order:
                if len(longs) >= k:
                    break
                if i not in longs and i not in shorts:
                    longs.append(i)
                    tgt[i] = 0.5 / k
            for i in order[::-1]:
                if len(shorts) >= k:
                    break
                if i not in shorts and i not in longs and short_ok(M, t, i, no_paying_shorts):
                    shorts.append(i)
                    tgt[i] = -0.5 / k
        turn[t] = np.abs(tgt - w).sum()
        w = tgt
        g = float(np.dot(w, R[t]))
        fund[t] = -float(np.dot(w, M["fund"][t]))
        gross[t] = g
        expo[t] = np.abs(w).sum()
        denom = 1 + g
        w = w * (1 + R[t]) / denom if denom > 0 else w
    return gross, turn, fund, expo


def perf(r: np.ndarray, turn: np.ndarray | None = None) -> dict:
    r = r[np.isfinite(r)]
    if len(r) < 2:
        return {"days": len(r), "cagr": None, "sharpe": 0.0, "max_dd": None}
    eq = np.cumprod(1 + r)
    years = len(r) / 365
    out = {"days": int(len(r)), "cagr": float(eq[-1] ** (1 / years) - 1) if eq[-1] > 0 else -1.0,
           "sharpe": float(r.mean() / r.std() * np.sqrt(365)) if r.std() > 0 else 0.0,
           "max_dd": float((1 - eq / np.maximum.accumulate(eq)).max())}
    if turn is not None:
        out["turnover_yr"] = float(turn.sum() / years)
    return out


def btc_regime(days: np.ndarray) -> np.ndarray:
    """BTC close above its 200-day average at the end of each day (the momentum book's rule)."""
    from .picks import daily_bars
    b = daily_bars("BTCUSDT").select("day", "close").sort("day")
    b = b.with_columns(on=pl.col("close") > pl.col("close").rolling_mean(200))
    on = dict(zip(b["day"].to_list(), b["on"].to_list()))
    return np.array([bool(on.get(int(d))) for d in days])


def main() -> None:
    t0 = time.time()
    P = build_panel(refresh="--refresh" in __import__("sys").argv)
    E = ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                              fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    print(f"eligible panel {E.height:,} coin-days, {E['symbol'].n_unique()} coins, {E['day'].n_unique()} days", flush=True)
    score_path = CACHE / "xs_daily_scores.parquet"
    if score_path.exists() and "--refit" not in __import__("sys").argv:
        S = pl.read_parquet(score_path)
        E = E.join(S, on=["day", "symbol"], how="left")
        folds = json.loads((CACHE / "xs_daily_folds.json").read_text())
    else:
        scores, folds = fit_scores(E)
        E = E.with_columns(**{k: pl.Series(v) for k, v in scores.items()})
        E.select("day", "symbol", "reg1", "reg3", "rank3").write_parquet(score_path)
        (CACHE / "xs_daily_folds.json").write_text(json.dumps(folds))
    E = E.filter(pl.col("day") >= FIRST_TEST)
    days = E["day"].to_numpy()

    # Signal quality, out of sample.
    ic_rows = []
    for m in ("reg1", "reg3", "rank3"):
        for h in HORIZONS:
            ic = daily_ic(days, E[m].to_numpy(), E[f"fwd{h}"].to_numpy())
            liq = E.with_columns(lr=pl.col("adv28_raw").rank(descending=True).over("day")).filter(pl.col("lr") <= 100)
            ic_l = daily_ic(liq["day"].to_numpy(), liq[m].to_numpy(), liq[f"fwd{h}"].to_numpy())
            v = ic["ic"].to_numpy()
            ic_rows.append({"score": m, "horizon_d": h, "rank_ic": float(v.mean()),
                            "t_stat": float(v.mean() / (v.std() / np.sqrt(len(v)))),
                            "rank_ic_top100_liquid": float(ic_l["ic"].mean())})
    for name, col, sign in (("1-day reversal", "r1_raw", -1), ("28-day momentum", "r28_raw", 1)):
        for h in HORIZONS:
            ic = daily_ic(days, sign * E[col].to_numpy(), E[f"fwd{h}"].to_numpy())["ic"].to_numpy()
            ic_rows.append({"score": name, "horizon_d": h, "rank_ic": float(ic.mean()),
                            "t_stat": float(ic.mean() / (ic.std() / np.sqrt(len(ic)))), "rank_ic_top100_liquid": None})
    # Deciles of the 1-day model on next-day return.
    dec = (E.drop_nulls(["reg1", "fwd1"])
           .with_columns(dec=((pl.col("reg1").rank().over("day") - 1) * 10 / pl.len().over("day")).floor().cast(pl.Int32))
           .group_by("dec").agg(mean_fwd1_bps=pl.col("fwd1").mean() * 1e4, coin_days=pl.len()).sort("dec")
           .with_columns(decile=pl.col("dec") + 1).drop("dec"))

    E = E.with_columns(rev1=-pl.col("r1_raw"), mom28=pl.col("r28_raw"), lowvol=-pl.col("vol28_raw"))
    score_cols = ["reg1", "reg3", "rank3", "rev1", "mom28", "lowvol"]
    m2_path = ROOT / "reports" / "picks_v2" / "scores.parquet"  # M2 v2's own walk-forward scores (read only)
    if m2_path.exists():
        m2 = pl.read_parquet(m2_path).select("day", "symbol", m2="score")
        E = E.join(m2, on=["day", "symbol"], how="left")
        score_cols.append("m2")
    M = matrices(E, P.filter(pl.col("day") >= FIRST_TEST), score_cols)
    reg = btc_regime(M["days"])
    sel = M["days"] < HOLDOUT
    hold_mask = ~sel

    variants = []  # (family, name, gross, turn, fund, expo)
    for m in ("reg1", "reg3", "rank3"):
        for k in (10, 20):
            for hold in (1, 3):
                for use_reg in (False, True):
                    g, tu, fu, ex = book(M, M[m], k, hold, 100, False, reg if use_reg else None)
                    variants.append(("long-only", f"{m} top {k} of 100 liquid, hold {hold}d" + (" · regime" if use_reg else ""),
                                     g, tu, fu, ex))
        for n in (50, 100):
            for hold in (1, 3):
                g, tu, fu, ex = book(M, M[m], 10, hold, n, True)
                variants.append(("long/short", f"{m} 10/10 of {n} liquid perps, hold {hold}d", g, tu, fu, ex))
    # Round two, designed after round one's holdout showed turnover eating a strong gross
    # signal: slower books. Longer tranches, and a rank buffer that lets a name stay until
    # it leaves the best 30 or 50. Same selection rule, same deflation pool.
    # Round one also showed funding eating the 2025-26 short leg, so each round-two book
    # runs with and without picks_ls's no-paying-shorts rule.
    for m in ("reg3", "rank3"):
        for n in (50, 100):
            for nps in (False, True):
                tag = " · no paying shorts" if nps else ""
                for hold in (5, 7):
                    g, tu, fu, ex = book(M, M[m], 10, hold, n, True, no_paying_shorts=nps)
                    variants.append(("long/short", f"{m} 10/10 of {n} liquid perps, hold {hold}d{tag} (round 2)", g, tu, fu, ex))
                for frac in (0.3, 0.5):
                    g, tu, fu, ex = book_buffer(M, M[m], 10, frac, n, no_paying_shorts=nps)
                    variants.append(("long/short", f"{m} 10/10 of {n} liquid perps, buffer {int(frac * 100)} %{tag} (round 2)",
                                     g, tu, fu, ex))
    # M2 v2's weekly scores in the same daily books: does M4 add anything over M2?
    if "m2" in M:
        for n in (50, 100):
            g, tu, fu, ex = book(M, M["m2"], 10, 7, n, True)
            variants.append(("baseline", f"M2 v2 score 10/10 of {n} liquid perps, hold 7d", g, tu, fu, ex))
            g, tu, fu, ex = book_buffer(M, M["m2"], 10, 0.5, n)
            variants.append(("baseline", f"M2 v2 score 10/10 of {n} liquid perps, buffer 50 %", g, tu, fu, ex))
    # The single strongest raw feature, with no model: long the calmest coins, short the wildest.
    for n in (50, 100):
        g, tu, fu, ex = book(M, M["lowvol"], 10, 7, n, True)
        variants.append(("baseline", f"low 28-day vol 10/10 of {n} liquid perps, hold 7d", g, tu, fu, ex))
        g, tu, fu, ex = book_buffer(M, M["lowvol"], 10, 0.5, n)
        variants.append(("baseline", f"low 28-day vol 10/10 of {n} liquid perps, buffer 50 %", g, tu, fu, ex))
    for m, label in (("rev1", "1-day reversal"), ("mom28", "28-day momentum")):
        for use_reg in (False, True):
            g, tu, fu, ex = book(M, M[m], 10, 3, 100, False, reg if use_reg else None)
            variants.append(("baseline", f"{label} top 10 of 100 liquid, hold 3d" + (" · regime" if use_reg else ""), g, tu, fu, ex))
        g, tu, fu, ex = book(M, M[m], 10, 3, 50, True)
        variants.append(("baseline", f"{label} 10/10 of 50 liquid perps, hold 3d", g, tu, fu, ex))

    rows = []
    for fam, name, g, tu, fu, ex in variants:
        row = {"family": fam, "variant": name}
        for cname, c in COSTS.items():
            net = g + fu - tu * c
            ps, ph = perf(net[sel]), perf(net[hold_mask], tu[hold_mask])
            row[f"sel_sharpe_{cname}"] = ps["sharpe"]
            row[f"hold_sharpe_{cname}"] = ph["sharpe"]
            row[f"hold_cagr_{cname}"] = ph["cagr"]
            row[f"hold_max_dd_{cname}"] = ph["max_dd"]
            row["turnover_yr"] = ph["turnover_yr"]
        row["hold_gross_sharpe"] = perf((g + fu)[hold_mask])["sharpe"]
        row["avg_exposure"] = float(ex[hold_mask].mean())
        rows.append(row)
    n_obs = int(hold_mask.sum())
    for cname in COSTS:
        srs = np.array([r[f"hold_sharpe_{cname}"] for r in rows]) / np.sqrt(365)
        for r in rows:
            r[f"deflated_p_{cname}"] = deflated_sharpe(r[f"hold_sharpe_{cname}"] / np.sqrt(365), n_obs, len(rows),
                                                       float(np.var(srs)))

    # Baselines without a model: the liquid universe, BTC, BTC with the regime switch.
    R = np.nan_to_num(M["R"])
    liq_mask = np.zeros_like(R, dtype=bool)
    for t in range(len(M["days"])):
        a = M["adv28_raw"][t]
        idx = np.flatnonzero(np.isfinite(a))
        liq_mask[t, idx[np.argsort(-a[idx])][:100]] = True
    ew = np.array([R[t, liq_mask[t]].mean() if liq_mask[t].any() else 0.0 for t in range(len(M["days"]))])
    bi = list(M["syms"]).index("BTCUSDT")
    btc = R[:, bi]
    base_rows = []
    for name, r in (("equal-weight 100 most liquid (daily rebalance, no costs)", ew), ("BTC buy and hold", btc),
                    ("BTC with 200-day regime switch (no costs)", btc * reg)):
        ps, ph = perf(r[sel]), perf(r[hold_mask])
        base_rows.append({"baseline": name, "sel_sharpe": ps["sharpe"], "hold_sharpe": ph["sharpe"],
                          "hold_cagr": ph["cagr"], "hold_max_dd": ph["max_dd"]})

    picks = []
    for fam in ("long-only", "long/short"):
        fr = [r for r in rows if r["family"] == fam]
        best = max(fr, key=lambda r: r["sel_sharpe_15bps"])
        picks.append(best)
    lines = []
    btc_dd = base_rows[1]["hold_max_dd"]
    for b in picks:
        passed = (b["deflated_p_15bps"] > 0.95 and b["hold_sharpe_41bps"] > 0
                  and b["hold_max_dd_15bps"] < btc_dd)
        b["passes"] = passed
        lines.append(
            f"- **{b['family']}**, picked on 2022-2023: *{b['variant']}*. Holdout 2024 on: Sharpe "
            f"{b['hold_sharpe_15bps']:.2f} at 15 bps ({b['hold_cagr_15bps'] * 100:.0f} % a year, drawdown "
            f"{b['hold_max_dd_15bps'] * 100:.0f} %), {b['hold_sharpe_41bps']:.2f} at 41 bps; gross {b['hold_gross_sharpe']:.2f}; "
            f"turnover {b['turnover_yr']:.0f}x a year; deflated p {b['deflated_p_15bps']:.2f} over {len(rows)} variants. "
            + ("Passes." if passed else "Does not pass."))
    # Per calendar year for each pick: where the return came from.
    by_name = {v[1]: v for v in variants}
    years = np.array([datetime.fromtimestamp(d / 1e6, timezone.utc).year for d in M["days"]])
    year_rows = []
    for b in picks:
        _, _, g, tu, fu, _ = by_name[b["variant"]]
        for yr in np.unique(years):
            m = years == yr
            year_rows.append({"pick": b["variant"], "year": int(yr), "days": int(m.sum()),
                              "gross_sum": float(g[m].sum()), "funding_sum": float(fu[m].sum()),
                              "cost_sum_15bps": float((tu[m] * COSTS["15bps"]).sum()),
                              "sharpe_15bps": perf((g + fu - tu * COSTS["15bps"])[m])["sharpe"],
                              "sharpe_41bps": perf((g + fu - tu * COSTS["41bps"])[m])["sharpe"]})
        pl.DataFrame({"day": M["days"], "gross": g, "funding": fu, "turnover": tu}).write_parquet(
            CACHE / f"xs_daily_pick_{b['family'].replace('/', '_')}.parquet")
    # Plateau (gate 4): how the whole model long/short family did, not just the pick.
    ls = [r for r in rows if r["family"] == "long/short" and "hold 1d" not in r["variant"]]
    plateau = (f"The {len(ls)} model long/short books held longer than one day: median holdout Sharpe "
               f"{np.median([r['hold_sharpe_15bps'] for r in ls]):.2f} at 15 bps and "
               f"{np.median([r['hold_sharpe_41bps'] for r in ls]):.2f} at 41 bps; "
               f"{np.mean([r['hold_sharpe_15bps'] > 0 for r in ls]) * 100:.0f} % and "
               f"{np.mean([r['hold_sharpe_41bps'] > 0 for r in ls]) * 100:.0f} % of them positive.")
    lines.append("- " + plateau)
    ic_best = max((r for r in ic_rows if r["score"] in ("reg1", "reg3", "rank3")), key=lambda r: r["rank_ic"])
    md = (
        "# M4 · Daily cross-sectional ranking\n\n"
        f"{E.height:,} eligible coin-days out of sample from 2022, {E['symbol'].n_unique()} coins (dead ones included), "
        f"{len(FEATURES)} features. Entry one hour after the features are known. Variant choice on 2022-2023, holdout "
        f"from 2024 ({n_obs} days). Costs 15 and 41 bps per unit of one-way turnover. Took {(time.time() - t0) / 60:.0f} min.\n\n"
        f"Best signal: {ic_best['score']} on {ic_best['horizon_d']}-day returns, Rank-IC {ic_best['rank_ic']:.3f} "
        f"(t {ic_best['t_stat']:.1f}).\n\n" + "\n".join(lines) + "\n\n"
        "## Signal quality out of sample (Rank-IC per day, averaged)\n\n"
        + report.table(ic_rows, ["score", "horizon_d", "rank_ic", "t_stat", "rank_ic_top100_liquid"])
        + "\n## Next-day return by reg1 decile (10 = best score), all eligible coins\n\n"
        + report.table(dec.to_dicts(), ["decile", "mean_fwd1_bps", "coin_days"])
        + "\n## Baselines\n\n"
        + report.table(base_rows, ["baseline", "sel_sharpe", "hold_sharpe", "hold_cagr", "hold_max_dd"])
        + f"\n## All {len(rows)} books (sel = 2022-2023, hold = 2024 on)\n\n"
        + report.table(sorted(rows, key=lambda r: (r["family"], -r["sel_sharpe_15bps"])),
                       ["family", "variant", "sel_sharpe_15bps", "hold_sharpe_15bps", "hold_sharpe_41bps",
                        "hold_gross_sharpe", "hold_cagr_15bps", "hold_max_dd_15bps", "turnover_yr",
                        "deflated_p_15bps", "deflated_p_41bps"])
        + "\n## The picks year by year (sums of daily contributions)\n\n"
        + report.table(year_rows, ["pick", "year", "days", "gross_sum", "funding_sum", "cost_sum_15bps",
                                   "sharpe_15bps", "sharpe_41bps"])
        + "\n## Walk-forward folds\n\n"
        + report.table(folds, ["model", "fold", "ic_oos", "ic_is_last180d"])
    )
    report.write("xs_daily", md, {"ic": ic_rows, "rows": rows, "picks": picks, "baselines": base_rows,
                                  "folds": folds, "n_variants": len(rows)})


if __name__ == "__main__":
    main()
