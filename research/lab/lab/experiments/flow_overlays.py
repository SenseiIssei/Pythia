"""X6: flow and positioning signals as exposure overlays on the daily books.

    python -m lab.experiments.flow_overlays

Pre-registered in results/flow_overlays.md (the part above the marker was
committed before this file or its data existed). Ten daily signals (Coinbase
and Korean premiums, stablecoin supply growth over 30 and 7 days, market
funding, basis, open-interest growth, the account long/short ratio, a
long-liquidation proxy, BTC DVOL), each as a 365-day z-score, scale the three
paper books as the autopilot runs them (non-Alpaca coins in cash) to 100, 50 or
0 %; a small L2 logistic model on all of them predicts bad weeks. 198 trials,
judged out of sample from 2024 at 35 bps against the book alone.

Data: the sweep's panel and perp caches, Binance spot 1h and USD-M 1d klines
and metrics from the lake, and `<flow>` (lab.collect.flow; $PYTHIA_FLOW,
default $PYTHIA_DATA/flow) for Coinbase, Upbit, USD/KRW, DefiLlama and DVOL.

Writes results/flow_overlays.md and <agent-strategies>/reports/flow_overlays.json.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from .. import data as labdata
from ..collect import flow as flowsrc
from ..metrics import deflated_sharpe
from . import alpaca_universe as au
from . import fam_common as fc

NAME = "flow_overlays"
MARKER = "<!-- generated below by lab.experiments.flow_overlays; edit above this line only -->"
DAY_US = fc.DAY_US
COSTS = {"maker 15bps": 0.0015, "taker 35bps": 0.0035, "stress 70bps": 0.0070}
BASE = "taker 35bps"
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
YEARS_OOS = (2024, 2025, 2026)
BOOKS = ("breakout", "tsmom_daily", "tsmom_tranches")
ORIGINAL = au.ORIGINAL
Z_WINDOW, Z_MIN = 365, 180
SMOOTH = 7
THRESHOLDS = ((1.0, 2.0), (0.5, 1.5))
TOP_PERPS = 20
BAD_WEEK, HORIZON = -0.05, 7
Q_HALF, Q_ZERO = 0.70, 0.90
MIN_TRAIN = 365
COMBO_C = (0.1, 1.0)
PRIMARY = ("long", 0.1)

# Prior expectation of the sign (+1: risk-off when high), written down before the run.
SIGNALS = {
    "cb_prem": -1, "kr_prem": +1, "stable_30": -1, "stable_7": -1, "funding": +1, "basis": +1,
    "oi_7": +1, "ls_ratio": +1, "liq": -1, "dvol": +1,
}
FEATURE_SETS = {
    "long": ("cb_prem", "kr_prem", "stable_30", "stable_7", "funding", "basis", "dvol"),
    "all": tuple(SIGNALS),
}

# The pool before this study (see the pre-registration): the 377 hand trials to C16
# at their published bar, 231 hand trials counted in parallel since (listings 16,
# memecoins 50, equities 45, fast_maker 53, intraday_equities 46, alpaca36 21), the
# factory's ledger. This study: 198.
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
PARALLEL_HAND = 231
HERE_TRIALS = 198


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def day_rows(P: fc.Panel, day_us: np.ndarray) -> np.ndarray:
    """Panel row of each day start (-1 where the day is outside the panel)."""
    t = np.searchsorted(P.days, day_us)
    ok = (t < P.T) & (P.days[np.minimum(t, P.T - 1)] == day_us)
    return np.where(ok, t, -1)


def on_days(P: fc.Panel, day_us, values) -> np.ndarray:
    """(T,) array with the values placed on their days, NaN elsewhere."""
    out = np.full(P.T, np.nan)
    day_us = np.asarray(day_us, dtype=np.int64)
    values = np.asarray(values, dtype=float)
    t = day_rows(P, day_us)
    out[t[t >= 0]] = values[t >= 0]
    return out


def trailing_mean(x: np.ndarray, w: int, min_obs: int) -> np.ndarray:
    return fc.rolling(x[:, None], w, min_obs)[:, 0]


def zscore(x: np.ndarray, w: int = Z_WINDOW, min_obs: int = Z_MIN) -> np.ndarray:
    """(x_t - mean) / std over the w values up to and including t (at least min_obs)."""
    m = fc.rolling(x[:, None], w, min_obs)[:, 0]
    m2 = fc.rolling((x ** 2)[:, None], w, min_obs)[:, 0]
    with np.errstate(invalid="ignore", divide="ignore"):
        sd = np.sqrt(np.maximum(m2 - m ** 2, 0.0))
        z = np.where(sd > 0, (x - m) / sd, np.nan)
    return np.where(np.isfinite(x), z, np.nan)


def ffill_asof(P: fc.Panel, day_us: np.ndarray, values: np.ndarray) -> np.ndarray:
    """The last value stamped on or before each panel day (NaN before the first)."""
    order = np.argsort(day_us)
    d, v = np.asarray(day_us)[order], np.asarray(values, dtype=float)[order]
    i = np.searchsorted(d, P.days, side="right") - 1
    return np.where(i >= 0, v[np.maximum(i, 0)], np.nan)


# ---------------------------------------------------------------------------
# Signals: raw daily values known at the close of day t
# ---------------------------------------------------------------------------

def read_flow(name: str) -> pl.DataFrame | None:
    p = flowsrc.FLOW / f"{name}.parquet"
    return pl.read_parquet(p) if p.exists() else None


def binance_1h(symbol: str) -> pl.DataFrame:
    d = labdata.ROOT / "hist" / "binance_spot" / "klines_1h" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    return (pl.concat([pl.read_parquet(f, columns=["open_time_us", "close"]) for f in files], how="vertical_relaxed")
            .unique("open_time_us", keep="last").sort("open_time_us"))


def sig_cb_prem(P: fc.Panel) -> np.ndarray:
    cb = read_flow("coinbase_btcusd_1h")
    if cb is None:
        return np.full(P.T, np.nan)
    bn = binance_1h("BTCUSDT").rename({"open_time_us": "ts_us", "close": "bn"})
    h = cb.select("ts_us", cb_="close").join(bn, on="ts_us", how="inner")
    d = (h.with_columns(prem=pl.col("cb_") / pl.col("bn") - 1, day=(pl.col("ts_us") // DAY_US) * DAY_US)
         .group_by("day").agg(pl.col("prem").mean(), n=pl.len()).filter(pl.col("n") >= 12).sort("day"))
    x = on_days(P, d["day"].to_numpy(), d["prem"].to_numpy())
    return trailing_mean(x, SMOOTH, 5)


def sig_kr_prem(P: fc.Panel) -> np.ndarray:
    up, fx = read_flow("upbit_krwbtc_1d"), read_flow("fx_usdkrw")
    if up is None or fx is None:
        return np.full(P.T, np.nan)
    krw = on_days(P, up["day_us"].to_numpy(), up["close"].to_numpy())
    rate = ffill_asof(P, fx["day_us"].to_numpy(), fx["usdkrw"].to_numpy())
    btc = P.close[:, P.btc]
    with np.errstate(invalid="ignore", divide="ignore"):
        x = krw / (btc * rate) - 1
    return trailing_mean(x, SMOOTH, 5)


def stable_supply(P: fc.Panel) -> np.ndarray:
    """USDT + USDC in circulation, the value stamped D used from the close of D+1."""
    s = read_flow("stables")
    if s is None:
        return np.full(P.T, np.nan)
    s = s.filter(pl.col("usdt").is_not_null() & pl.col("usdc").is_not_null())
    v = on_days(P, s["day_us"].to_numpy() + DAY_US, (s["usdt"] + s["usdc"]).to_numpy())
    return v


def log_change(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[k:] = np.log(x[k:] / x[:-k])
    return out


def sig_funding(P: fc.Panel) -> np.ndarray:
    """Funding over day t, mean over the 20 most liquid perps that day, weighted by quote volume."""
    pp = fc._perp_daily().filter(pl.col("perp_qv").is_not_null() & pl.col("funding").is_not_null())
    top = (pp.with_columns(rk=pl.col("perp_qv").rank("ordinal", descending=True).over("day"))
           .filter(pl.col("rk") <= TOP_PERPS)
           .group_by("day").agg(f=(pl.col("funding") * pl.col("perp_qv")).sum() / pl.col("perp_qv").sum())
           .sort("day"))
    x = on_days(P, top["day"].to_numpy(), top["f"].to_numpy())
    return trailing_mean(x, SMOOTH, 5)


def lab_perps() -> list[tuple[str, str, float]]:
    """(base, perp symbol, perp price multiplier) of the 20 lab coins."""
    return [(b, labdata.perp_symbol(b), 1000.0 if labdata.perp_symbol(b).startswith("1000") else 1.0)
            for b in labdata.UNIVERSE]


def spot_col(P: fc.Panel, base: str) -> int | None:
    name = f"{base}USDT"
    return P.names.index(name) if name in P.names else None


def sig_basis(P: fc.Panel) -> np.ndarray:
    num, den = np.zeros(P.T), np.zeros(P.T)
    for base, sym, mult in lab_perps():
        j = spot_col(P, base)
        d = labdata.ROOT / "hist" / "binance_um" / "klines_1d" / f"symbol={sym}"
        files = sorted(d.glob("*.parquet"))
        if j is None or not files:
            continue
        k = (pl.concat([pl.read_parquet(f, columns=["open_time_us", "close", "quote_volume"]) for f in files],
                       how="vertical_relaxed").unique("open_time_us", keep="last"))
        perp = on_days(P, k["open_time_us"].to_numpy(), k["close"].to_numpy() / mult)
        qv = on_days(P, k["open_time_us"].to_numpy(), k["quote_volume"].to_numpy())
        with np.errstate(invalid="ignore", divide="ignore"):
            b = perp / P.close[:, j] - 1
        ok = np.isfinite(b) & np.isfinite(qv) & (qv > 0) & (np.abs(b) < 0.2)
        num += np.where(ok, b * qv, 0.0)
        den += np.where(ok, qv, 0.0)
    with np.errstate(invalid="ignore", divide="ignore"):
        x = np.where(den > 0, num / den, np.nan)
    return trailing_mean(x, SMOOTH, 5)


def metrics_daily(P: fc.Panel) -> dict[str, np.ndarray]:
    """(T, 20) per lab coin: OI in coins and in USD at the day's last snapshot, the day's
    mean all-accounts long/short ratio, and the coin's spot return."""
    cols = lab_perps()
    oi_c, oi_v, ls, ret = (np.full((P.T, len(cols)), np.nan) for _ in range(4))
    for i, (base, sym, _) in enumerate(cols):
        d = labdata.ROOT / "hist" / "binance_um" / "metrics" / f"symbol={sym}"
        files = sorted(d.glob("*.parquet"))
        j = spot_col(P, base)
        if j is not None:
            ret[:, i] = P.ret[:, j]
        if not files:
            continue
        m = (pl.concat([pl.read_parquet(f, columns=["ts_us", "sum_open_interest", "sum_open_interest_value",
                                                    "count_long_short_ratio"]) for f in files],
                       how="vertical_relaxed").unique("ts_us").sort("ts_us")
             .with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US)
             .group_by("day").agg(pl.col("sum_open_interest").drop_nulls().last(),
                                  pl.col("sum_open_interest_value").drop_nulls().last(),
                                  pl.col("count_long_short_ratio").mean()).sort("day"))
        dd = m["day"].to_numpy()
        oi_c[:, i] = on_days(P, dd, m["sum_open_interest"].to_numpy().astype(float))
        oi_v[:, i] = on_days(P, dd, m["sum_open_interest_value"].to_numpy().astype(float))
        ls[:, i] = on_days(P, dd, m["count_long_short_ratio"].to_numpy().astype(float))
    return {"oi_c": oi_c, "oi_v": oi_v, "ls": ls, "ret": ret}


def wmean(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    ok = np.isfinite(x) & np.isfinite(w) & (w > 0)
    num = np.where(ok, np.where(ok, x, 0.0) * np.where(ok, w, 0.0), 0.0).sum(1)
    den = np.where(ok, w, 0.0).sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, num / den, np.nan)


def lag(x: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(x, np.nan)
    out[k:] = x[:-k]
    return out


def sig_positioning(P: fc.Panel) -> dict[str, np.ndarray]:
    m = metrics_daily(P)
    oi_c, oi_v = m["oi_c"], m["oi_v"]
    with np.errstate(invalid="ignore", divide="ignore"):
        g7 = np.log(oi_c / lag(oi_c, 7))
        g1 = np.log(oi_c / lag(oi_c, 1))
    oi_7 = wmean(g7, lag(oi_v, 7))
    ls = trailing_mean(wmean(m["ls"], oi_v), SMOOTH, 5)
    ok = np.isfinite(g1) & np.isfinite(m["ret"])
    lost = np.where(ok, np.maximum(0.0, -np.where(ok, g1, 0.0)) * (m["ret"] < 0), np.nan)
    liq_d = wmean(lost, lag(oi_v, 1))
    liq = fc.rolling(liq_d[:, None], SMOOTH, 5, "sum")[:, 0]
    return {"oi_7": oi_7, "ls_ratio": ls, "liq": liq}


def sig_dvol(P: fc.Panel) -> np.ndarray:
    d = read_flow("dvol")
    if d is None:
        return np.full(P.T, np.nan)
    d = d.filter(pl.col("currency") == "BTC")
    return on_days(P, d["day_us"].to_numpy(), d["close"].to_numpy())


def raw_signals(P: fc.Panel) -> dict[str, np.ndarray]:
    sup = stable_supply(P)
    out = {"cb_prem": sig_cb_prem(P), "kr_prem": sig_kr_prem(P), "stable_30": log_change(sup, 30),
           "stable_7": log_change(sup, 7), "funding": sig_funding(P), "basis": sig_basis(P)}
    out.update(sig_positioning(P))
    out["dvol"] = sig_dvol(P)
    return {k: out[k] for k in SIGNALS}


# ---------------------------------------------------------------------------
# Overlays
# ---------------------------------------------------------------------------

def scale_from_z(z: np.ndarray, orient: int, a: float, b: float) -> np.ndarray:
    """1 / 0.5 / 0 from the oriented z-score; 1 where the signal does not exist."""
    oz = orient * z
    s = np.where(oz >= b, 0.0, np.where(oz >= a, 0.5, 1.0))
    return np.where(np.isfinite(z), s, 1.0)


def apply_overlay(g: np.ndarray, tov: np.ndarray, expo: np.ndarray, S: np.ndarray, late: int = 0):
    """The book scaled by S (decided at each close): gross, turnover, exposure."""
    if late:
        S = np.r_[np.ones(late), S[:-late]]
    go = np.zeros_like(g)
    go[1:] = S[:-1] * g[1:]
    tv = S * tov + np.abs(np.diff(np.r_[1.0, S])) * expo
    return go, tv, S * expo, S


def net(g: np.ndarray, tv: np.ndarray, c: float) -> np.ndarray:
    return g - c * np.r_[0.0, tv[:-1]]


# ---------------------------------------------------------------------------
# The combination
# ---------------------------------------------------------------------------

def basket_returns(P: fc.Panel) -> np.ndarray:
    """Daily return of the equal-weight basket of eligible Alpaca coins (eligible at t-1)."""
    alp = au.alpaca_mask(P)
    r = np.zeros(P.T)
    for t in range(1, P.T):
        m = P.eligible[t - 1] & alp & np.isfinite(P.ret[t])
        r[t] = float(P.ret[t][m].mean()) if m.any() else 0.0
    return r


def forward_return(r: np.ndarray, h: int = HORIZON) -> np.ndarray:
    """Compounded return over days t+1 .. t+h (NaN where the window runs past the data)."""
    lr = np.log1p(r)
    c = np.r_[0.0, np.cumsum(lr)]
    out = np.full(len(r), np.nan)
    T = len(r)
    idx = np.arange(T - h)
    out[idx] = np.expm1(c[idx + h + 1] - c[idx + 1])
    return out


def quarter_starts(P: fc.Panel) -> list[int]:
    d = P.days.astype("datetime64[us]").astype("datetime64[D]")
    m = d.astype("datetime64[M]")
    q = np.array([int(str(x)[5:7]) for x in m])
    first = np.r_[True, m[1:] != m[:-1]] & np.isin(q, (1, 4, 7, 10))
    return list(np.flatnonzero(first))


def walk_forward_logit(P: fc.Panel, Z: np.ndarray, y: np.ndarray, C: float):
    """Quarterly expanding refits; returns (p, S, fits). Training rows: features finite,
    label known and its window ended before the refit day."""
    from sklearn.linear_model import LogisticRegression
    T = P.T
    p = np.full(T, np.nan)
    S = np.ones(T)
    fits = []
    feat_ok = np.isfinite(Z).all(1)
    qs = quarter_starts(P) + [T]
    for a, b in zip(qs[:-1], qs[1:]):
        rows = np.flatnonzero(feat_ok[:a] & np.isfinite(y[:a]) & (np.arange(a) + HORIZON < a))
        if len(rows) < MIN_TRAIN or len(np.unique(y[rows])) < 2:
            continue
        mu, sd = Z[rows].mean(0), Z[rows].std(0)
        sd = np.where(sd > 0, sd, 1.0)
        X = (Z[rows] - mu) / sd
        mdl = LogisticRegression(C=C, max_iter=2000)
        mdl.fit(X, y[rows])
        fitted = mdl.predict_proba(X)[:, 1]
        q_half, q_zero = np.quantile(fitted, Q_HALF), np.quantile(fitted, Q_ZERO)
        seg = np.arange(a, b)
        ok = seg[feat_ok[seg]]
        if len(ok):
            p[ok] = mdl.predict_proba((Z[ok] - mu) / sd)[:, 1]
            S[ok] = np.where(p[ok] >= q_zero, 0.0, np.where(p[ok] >= q_half, 0.5, 1.0))
        fits.append({"refit": str(P.days[a].astype("datetime64[us]").astype("datetime64[D]")), "rows": int(len(rows)),
                     "base_rate": float(y[rows].mean()), "coef": [float(c) for c in mdl.coef_[0]],
                     "q70": float(q_half), "q90": float(q_zero)})
    return p, S, fits


def auc(score: np.ndarray, y: np.ndarray) -> float:
    pos, neg = score[y == 1], score[y == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    r = stats.rankdata(np.r_[pos, neg])
    return float((r[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ---------------------------------------------------------------------------
# Measuring and the pool
# ---------------------------------------------------------------------------

def sharpe_d(x: np.ndarray) -> float:
    sd = x.std()
    return float(x.mean() / sd) if sd > 0 else 0.0


def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def factory_sharpes() -> np.ndarray:
    from ..factory.ledger import ledger_path, read_jsonl, seed_dir
    rows = {r["key"]: r for r in read_jsonl(seed_dir() / "ledger.jsonl")}
    try:
        rows.update({r["key"]: r for r in read_jsonl(ledger_path())})
    except Exception:
        pass
    return np.array([r["is_sharpe"] for r in rows.values()
                     if r.get("is_sharpe") is not None and math.isfinite(r["is_sharpe"])])


def pool(mine: list[float]) -> dict:
    v1, n1 = prior_var(), PRIOR_TRIALS + PARALLEL_HAND
    fx = np.clip(factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n3, v3 = len(x), float(np.var(x))
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated(x: np.ndarray, n: int, var: float) -> float:
    if x.std() == 0:
        return 0.0
    s, sk, ku = sharpe_d(x), float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s, len(x), n, var, sk, ku)


def describe(P: fc.Panel, name: str, run: tuple, S: np.ndarray, avail: np.ndarray, **tags) -> dict:
    g, tv, ex = run[:3]
    ins, oos = fc.masks(P)
    yr = au.years_of(P)
    isd = ins & avail
    row: dict = {"variant": name, **tags}
    for k, c in COSTS.items():
        n = net(g, tv, c)
        row[f"is_{k}"] = fc.perf(n[isd])["sharpe"] if isd.any() else float("nan")
        row[f"oos_{k}"] = fc.perf(n[oos])["sharpe"]
    n35 = net(g, tv, COSTS[BASE])
    po = fc.perf(n35[oos])
    row["cagr_35"], row["dd_35"] = po["cagr"], po["max_dd"]
    row["expo"] = float(ex[oos].mean())
    row["turnover_yr"] = float(tv[oos].sum() / (oos.sum() / 365))
    row["half_days"] = float((S[oos] == 0.5).mean())
    row["zero_days"] = float((S[oos] == 0.0).mean())
    row["is_days"] = int(isd.sum())
    for y in YEARS:
        m = (P.days >= fc.IS_START) & (yr == y)
        row[f"y{y}"] = fc.perf(n35[m])["sharpe"]
    return row


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_books(P: fc.Panel) -> dict[tuple[str, str], tuple]:
    """(book, 'live' | 'twin') -> (gross, turnover, exposure): live is cash-left, twin the original."""
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    out = {}
    for b in BOOKS:
        g, tv, ex, _ = au.simulate(P, b, au.cash_left(O[b], alp))
        out[(b, "live")] = (g, tv, ex)
        g, tv, ex, _ = au.simulate(P, b, O[b])
        out[(b, "twin")] = (g, tv, ex)
        print(f"  book {b} simulated", flush=True)
    return out


def main() -> None:
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    yr = au.years_of(P)
    rng = np.random.default_rng(20261015)
    print("signals ...", flush=True)
    X = raw_signals(P)
    Zs = {k: zscore(v) for k, v in X.items()}
    print("books ...", flush=True)
    B = run_books(P)
    c35 = COSTS[BASE]

    def avail_of(z: np.ndarray) -> np.ndarray:
        a = np.zeros(P.T, dtype=bool)
        a[1:] = np.isfinite(z[:-1])
        return a

    rows: list[dict] = []
    series: dict[str, tuple] = {}

    def add(key: str, run: tuple, S: np.ndarray, avail: np.ndarray, **tags) -> dict:
        r = describe(P, key, run, S, avail, **tags)
        base = B[(tags["book"], tags.get("version", "live"))]
        xb, xo = net(base[0], base[1], c35), net(run[0], run[1], c35)
        r["diff_sr"] = sharpe_d((xo - xb)[oos]) * math.sqrt(365)
        r["book_is_35"] = fc.perf(xb[ins & avail])["sharpe"] if (ins & avail).any() else float("nan")
        rows.append(r)
        series[key] = (run, S, xo, xb)
        return r

    # Book references (not counted)
    refs = {}
    for (b, v), run in B.items():
        r = describe(P, f"{ORIGINAL[b]} {v} alone", run, np.ones(P.T), np.ones(P.T, dtype=bool), book=b, version=v,
                     kind="book")
        refs[(b, v)] = r

    # S: single signals, every orientation and threshold pair
    for s in SIGNALS:
        z = Zs[s]
        av = avail_of(z)
        for b in BOOKS:
            g, tv, ex = B[(b, "live")]
            for o in (+1, -1):
                for a, bb in THRESHOLDS:
                    S = scale_from_z(z, o, a, bb)
                    run = apply_overlay(g, tv, ex, S)
                    key = f"{s} · {'+' if o > 0 else '-'} · z {a}/{bb} · {b}"
                    add(key, run, run[3], av, group="S", signal=s, orient=o, a=a, b=bb, book=b,
                        prior=o == SIGNALS[s])
        print(f"  {s}: z from {first_day(P, z)}", flush=True)

    # C: the combination
    r_ew = basket_returns(P)
    fwd = forward_return(r_ew)
    y = np.where(np.isfinite(fwd), (fwd < BAD_WEEK).astype(float), np.nan)
    combos = {}
    for fs, feats in FEATURE_SETS.items():
        Z = np.column_stack([Zs[f] for f in feats])
        for C in COMBO_C:
            p, S, fits = walk_forward_logit(P, Z, y, C)
            av = np.zeros(P.T, dtype=bool)
            av[1:] = np.isfinite(p[:-1])
            m = oos & np.isfinite(p) & np.isfinite(y)
            base_rate = fits[-1]["base_rate"] if fits else float("nan")
            yy = y[m]
            combos[(fs, C)] = {"features": list(feats), "C": C, "auc_oos": auc(p[m], yy),
                               "brier_oos": float(np.mean((p[m] - yy) ** 2)) if m.any() else float("nan"),
                               "brier_base": float(np.mean((base_rate - yy) ** 2)) if m.any() else float("nan"),
                               "bad_rate_oos": float(yy.mean()) if m.any() else float("nan"),
                               "first_prediction": first_day(P, p), "fits": fits, "S": S, "avail": av}
            for b in BOOKS:
                g, tv, ex = B[(b, "live")]
                run = apply_overlay(g, tv, ex, S)
                add(f"logit {fs} C {C} · {b}", run, run[3], av, group="C", signal=f"logit_{fs}", C=C, book=b,
                    primary=(fs, C) == PRIMARY)
    print("  combinations done", flush=True)

    # Picks, late and twin
    picks = []
    for s in SIGNALS:
        for b in BOOKS:
            cand = [r for r in rows if r["group"] == "S" and r["signal"] == s and r["book"] == b]
            pk = max(cand, key=lambda r: r[f"is_{BASE}"] if math.isfinite(r[f"is_{BASE}"]) else -1e9)
            picks.append(pk)
    picks += [r for r in rows if r["group"] == "C" and r.get("primary")]
    for pk in picks:
        (run, S, _, _) = series[pk["variant"]]
        b = pk["book"]
        av = combos[PRIMARY]["avail"] if pk["group"] == "C" else avail_of(Zs[pk["signal"]])
        g, tv, ex = B[(b, "live")]
        late = apply_overlay(g, tv, ex, S, late=1)
        add(pk["variant"] + " · one day late", late, late[3], av, group="L", signal=pk["signal"], book=b)
        g, tv, ex = B[(b, "twin")]
        tw = apply_overlay(g, tv, ex, S)
        add(pk["variant"] + " · twin", tw, tw[3], av, group="T", signal=pk["signal"], book=b, version="twin")

    counted = [r for r in rows if r["group"] in ("S", "C", "L", "T")]
    assert len(counted) == HERE_TRIALS, len(counted)
    pl_ = pool([r[f"oos_{BASE}"] for r in counted])
    dsr = np.clip(np.array([r["diff_sr"] for r in counted]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    dvar = float(np.var(dsr))
    for r in counted:
        _, _, xo, xb = series[r["variant"]]
        r["deflated_p_pool"] = deflated(xo[oos], pl_["n_total"], pl_["var"])
        r["deflated_p_diff"] = deflated((xo - xb)[oos], HERE_TRIALS, dvar)

    verdicts = []
    for pk in picks:
        _, _, xo, xb = series[pk["variant"]]
        late = next(r for r in rows if r["variant"] == pk["variant"] + " · one day late")
        twin = next(r for r in rows if r["variant"] == pk["variant"] + " · twin")
        ref, tref = refs[(pk["book"], "live")], refs[(pk["book"], "twin")]
        lo, hi = au.boot_band(xo[oos], rng, xb[oos])
        years_better = sum(pk[f"y{yy}"] > ref[f"y{yy}"] for yy in YEARS_OOS)
        gates = {
            "1 Sharpe and years": pk[f"oos_{BASE}"] > ref[f"oos_{BASE}"] and years_better >= 2,
            "2 drawdown": pk["dd_35"] < ref["dd_35"],
            "3 band above 0": lo > 0,
            "4 one day late": late[f"oos_{BASE}"] > ref[f"oos_{BASE}"],
            "5 twin": twin[f"oos_{BASE}"] >= tref[f"oos_{BASE}"],
            "6 deflated improvement": pk["deflated_p_diff"] > 0.95,
        }
        verdicts.append({
            "pick": pk["variant"], "signal": pk["signal"], "book": ORIGINAL[pk["book"]],
            "orient": pk.get("orient"), "thresholds": f"{pk.get('a')}/{pk.get('b')}" if pk["group"] == "S" else "-",
            "is_35": pk[f"is_{BASE}"], "book_is_35": pk["book_is_35"], "oos_35": pk[f"oos_{BASE}"],
            "book_oos_35": ref[f"oos_{BASE}"], "dd": pk["dd_35"], "book_dd": ref["dd_35"],
            "years_better": years_better, "diff_sr": pk["diff_sr"], "diff_p05": lo, "diff_p95": hi,
            "late_35": late[f"oos_{BASE}"], "twin_35": twin[f"oos_{BASE}"], "twin_book_35": tref[f"oos_{BASE}"],
            "zero_days": pk["zero_days"], "half_days": pk["half_days"],
            "deflated_p_diff": pk["deflated_p_diff"], "deflated_p_pool": pk["deflated_p_pool"],
            "gates_failed": [k for k, v in gates.items() if not v], "passes": all(gates.values())})

    ic = {}
    fwd_ok = np.isfinite(fwd)
    for s, z in Zs.items():
        m = oos & fwd_ok & np.isfinite(z)
        mi = ins & fwd_ok & np.isfinite(z)
        ic[s] = {"ic_oos": float(stats.spearmanr(z[m], fwd[m])[0]) if m.sum() > 30 else float("nan"),
                 "ic_is": float(stats.spearmanr(z[mi], fwd[mi])[0]) if mi.sum() > 30 else float("nan"),
                 "first_z": first_day(P, z), "prior_sign": SIGNALS[s]}

    res = {"panel_end": str(P.days[-1].astype("datetime64[us]").astype("datetime64[D]")), "oos_days": int(oos.sum()),
           "refs": list(refs.values()), "rows": rows, "verdicts": verdicts, "pool": pl_, "diff_var": dvar,
           "ic": ic, "combos": {f"{k[0]} C {k[1]}": {kk: vv for kk, vv in v.items() if kk not in ("S", "avail")}
                                for k, v in combos.items()},
           "bad_week_rate_all": float(np.nanmean(y))}
    write(res)


def first_day(P: fc.Panel, x: np.ndarray) -> str | None:
    f = np.flatnonzero(np.isfinite(x))
    return str(P.days[f[0]].astype("datetime64[us]").astype("datetime64[D]")) if len(f) else None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write(res: dict) -> None:
    path = fc.RESULTS_DIR / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = f"# {NAME}\n\n"
    v, pl_ = res["verdicts"], res["pool"]
    n_pass = sum(x["passes"] for x in v)
    ver_cols = ["pick", "is_35", "book_is_35", "oos_35", "book_oos_35", "dd", "book_dd", "years_better", "diff_sr",
                "diff_p05", "diff_p95", "late_35", "twin_35", "twin_book_35", "zero_days", "half_days",
                "deflated_p_diff", "passes"]
    cols = ["variant", "is_maker 15bps", "is_taker 35bps", "oos_maker 15bps", "oos_taker 35bps", "oos_stress 70bps",
            "cagr_35", "dd_35", "expo", "turnover_yr", "half_days", "zero_days", "diff_sr", "deflated_p_diff",
            "deflated_p_pool"]
    year_cols = ["variant"] + [f"y{y}" for y in YEARS]
    md = [head.rstrip() + "\n\n", MARKER, "\n\n",
          f"## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, panel to {res['panel_end']})\n\n",
          f"**Verdict: {'nothing passes' if n_pass == 0 else f'{n_pass} pick(s) pass'}** "
          f"({len(v)} picks judged: 30 single-signal picks and the primary combination on each book). "
          f"Pool {pl_['n_total']} trials ({pl_['hand_trials']} hand, {pl_['factory_trials']} factory, "
          f"{pl_['mine']} here); the best noise trial is expected at an annual Sharpe of about "
          f"{pl_['sr0_annual']:.2f}. Out of sample {res['oos_days']} days.\n\n",
          "### Gates failed per pick\n\n"]
    for x in v:
        md.append(f"- {x['pick']}: " + (", ".join(x["gates_failed"]) if x["gates_failed"] else "passes") + "\n")
    md += ["\n### The picks against the book alone (out of sample, 35 bps)\n\n",
           "`book_*` is the cash-left book alone over the same days; `diff_sr` the annual Sharpe of the daily "
           "difference; `diff_p05`/`diff_p95` the bootstrap band of the Sharpe difference; `twin_*` the overlay and "
           "the book on the survivorship-free original; `zero_days`/`half_days` the share of out-of-sample days at "
           "0 and 0.5.\n\n", fc.table(v, ver_cols), "\n",
           "### The books alone (references, not counted)\n\n",
           fc.table(res["refs"], cols[:10] + ["y2024", "y2025", "y2026"]),
           "\n### Signals: first z-score and rank correlation with the next 7 days of the Alpaca basket\n\n",
           fc.table([{"signal": k, **x} for k, x in res["ic"].items()],
                    ["signal", "first_z", "prior_sign", "ic_is", "ic_oos"]), "\n",
           "### The combination (bad week: the basket down more than 5 % over the next 7 days)\n\n",
           fc.table([{"model": k, **{kk: vv for kk, vv in x.items() if kk != "fits"}} for k, x in res["combos"].items()],
                    ["model", "first_prediction", "auc_oos", "brier_oos", "brier_base", "bad_rate_oos"]), "\n"]
    for k, x in res["combos"].items():
        if x["fits"]:
            f = x["fits"][-1]
            md.append(f"- {k}, last fit {f['refit']} on {f['rows']} rows (base rate {f['base_rate']:.2f}): "
                      + ", ".join(f"{n} {c:+.2f}" for n, c in zip(x["features"], f["coef"])) + "\n")
    md += ["\n### Every trial\n\n", "S single signal (+ risk-off when high, - when low), C combination, L a pick one "
           "day late, T a pick on the twin. In-sample Sharpe over the days the signal existed.\n\n",
           fc.table(res["rows"], cols), "\n### Per year (Sharpe at 35 bps)\n\n",
           fc.table(res["refs"] + res["rows"], year_cols)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(md), encoding="utf-8", newline="\n")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
