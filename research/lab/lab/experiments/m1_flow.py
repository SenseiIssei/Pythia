"""X11 b: does M1 (next-hour volatility) get better with flow inputs or the order book?

Pre-registered in results/model_upgrades_prereg.md (section b).

b1  M1's LightGBM on its 21 inputs against the same with nine flow inputs
    (per coin: latest funding, open-interest changes over 1 and 24 hours, the
    all-accounts long/short ratio, the perp taker ratio; market: the Coinbase
    premium at that hour, yesterday's BTC DVOL, Korean premium and stablecoin
    growth). Quarterly folds from 2024-Q1, 24 h embargo, both refit on every
    fold. Pass: lower QLIKE, Diebold-Mariano p below 0.025, lower in two thirds
    of the quarters. The two groups alone are diagnostics.
b2  The recorder's Binance spot order book (from 2026-09-30): a linear
    correction of M1's log forecast on top-5 imbalance, spread and depth change,
    refit daily on the earlier days of the record. Pass: lower QLIKE than M1
    alone, DM p below 0.025, at least 3,000 coin-hours.

    python -m lab.experiments.m1_flow [--part b1|b2] [--refresh]

Writes results/m1_flow.md (PYTHIA_RESULTS) and reports/m1_flow/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import lightgbm as lgb
import numpy as np
import polars as pl

from .. import report
from ..cv import walk_forward
from ..data import HOUR_US, ROOT, UNIVERSE, perp_symbol
from ..metrics import diebold_mariano, qlike
from . import vol

NAME = "m1_flow"
DAY_US = 24 * HOUR_US
CACHE = Path(os.environ.get("PYTHIA_CACHE", report.REPORTS / "_cache"))
FIRST_TEST = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
OB_START = int(datetime(2026, 9, 30, tzinfo=timezone.utc).timestamp() * 1e6)
PASS_P = 0.025
MIN_OB_ROWS = 3000
OB_WARMUP_D = 7
COIN_FLOW = ["fund_last", "oi_chg1h", "oi_chg24h", "ls_acct_h", "perp_taker_h"]
MKT_FLOW = ["cb_prem_h", "dvol_prev", "kr_prem_prev", "stable7_prev"]
OB_FEATURES = ["imb5", "spread_l", "depth_chg"]
PARAMS = {**vol.LGBM_PARAMS, "n_jobs": 16}
EPS = 1e-10


# ---------------------------------------------------------------- inputs

def _um(kind: str, sym: str, cols: list[str]) -> pl.DataFrame:
    d = ROOT / "hist" / "binance_um" / kind / f"symbol={sym}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f, columns=cols) for f in files], how="vertical_relaxed")


def coin_flow(base: str) -> pl.DataFrame:
    """(ts_us, the four metrics inputs) for one coin, each known at the end of the hour ts_us
    (the last 5-minute snapshot inside it). Funding is attached by attach_funding."""
    m = _um("metrics", perp_symbol(base),
            ["ts_us", "sum_open_interest", "count_long_short_ratio", "sum_taker_long_short_vol_ratio"])
    if m.is_empty():
        return pl.DataFrame()
    h = (m.unique("ts_us").sort("ts_us").with_columns(h=(pl.col("ts_us") // HOUR_US) * HOUR_US)
         .group_by("h").agg(oi=pl.col("sum_open_interest").drop_nulls().last(),
                            ls=pl.col("count_long_short_ratio").drop_nulls().last(),
                            tk=pl.col("sum_taker_long_short_vol_ratio").mean())
         .rename({"h": "ts_us"}).sort("ts_us"))
    p1 = h.select(ts_us=pl.col("ts_us") + HOUR_US, oi1="oi")
    p24 = h.select(ts_us=pl.col("ts_us") + 24 * HOUR_US, oi24="oi")
    return (h.join(p1, on="ts_us", how="left").join(p24, on="ts_us", how="left")
            .with_columns(oi_chg1h=(pl.col("oi") / pl.col("oi1")).log(),
                          oi_chg24h=(pl.col("oi") / pl.col("oi24")).log(),
                          ls_acct_h=pl.col("ls"), perp_taker_h=(pl.col("tk") + 1e-9).log())
            .select("ts_us", "oi_chg1h", "oi_chg24h", "ls_acct_h", "perp_taker_h"))


def attach_funding(panel: pl.DataFrame) -> pl.DataFrame:
    """fund_last: the latest settled funding at or before the end of the row's hour."""
    parts = []
    for sym, g in panel.group_by("symbol", maintain_order=True):
        s = sym[0] if isinstance(sym, tuple) else sym
        fu = _um("funding", perp_symbol(s.removesuffix("USDT")), ["funding_time_us", "funding_rate"])
        g = g.sort("ts_us").with_columns(known=pl.col("ts_us") + HOUR_US)
        if fu.is_empty():
            parts.append(g.with_columns(fund_last=pl.lit(None, pl.Float64)).drop("known"))
            continue
        f = fu.unique("funding_time_us").sort("funding_time_us").select(
            known=pl.col("funding_time_us"), fund_last="funding_rate")
        parts.append(g.join_asof(f, on="known", strategy="backward").drop("known"))
    return pl.concat(parts, how="vertical_relaxed")


def market_flow(btc_close: pl.DataFrame) -> pl.DataFrame:
    """(ts_us hour, cb_prem_h) and (day, dvol_prev, kr_prem_prev, stable7_prev) merged per hour later."""
    from . import m2_v3
    cb = m2_v3._flow("coinbase_btcusd_1h")
    hourly = (cb.select("ts_us", cb_="close").join(btc_close, on="ts_us", how="inner")
              .select("ts_us", cb_prem_h=pl.col("cb_") / pl.col("bn") - 1)) if cb is not None else None
    dv = m2_v3._flow("dvol")
    up, fx, st = m2_v3._flow("upbit_krwbtc_1d"), m2_v3._flow("fx_usdkrw"), m2_v3._flow("stables")
    btc_d = (btc_close.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US).sort("ts_us")
             .group_by("day").agg(bn=pl.col("bn").last()))
    daily = btc_d.sort("day")
    if dv is not None:
        daily = daily.join(dv.filter(pl.col("currency") == "BTC").select(day="day_us", dvol=pl.col("close").log()),
                           on="day", how="left")
    if up is not None and fx is not None:
        daily = (daily.join(up.select(day="day_us", krw="close"), on="day", how="left")
                 .join_asof(fx.sort("day_us").select(day="day_us", usdkrw="usdkrw"), on="day", strategy="backward")
                 .with_columns(kr=pl.col("krw") / (pl.col("bn") * pl.col("usdkrw")) - 1))
    if st is not None:
        s = (st.filter(pl.col("usdt").is_not_null() & pl.col("usdc").is_not_null())
             .select(day=pl.col("day_us") + DAY_US, sup=pl.col("usdt") + pl.col("usdc")).sort("day"))
        s = s.join(s.select(day=pl.col("day") + 7 * DAY_US, sup7="sup"), on="day", how="left").with_columns(
            st7=(pl.col("sup") / pl.col("sup7")).log())
        daily = daily.join(s.select("day", "st7"), on="day", how="left")
    # Values of day D are used in every hour of day D + 1.
    prev = daily.select(day=pl.col("day") + DAY_US,
                        dvol_prev=pl.col("dvol") if "dvol" in daily.columns else pl.lit(None, pl.Float64),
                        kr_prem_prev=pl.col("kr") if "kr" in daily.columns else pl.lit(None, pl.Float64),
                        stable7_prev=pl.col("st7") if "st7" in daily.columns else pl.lit(None, pl.Float64))
    return hourly, prev


def finite_only(p: pl.DataFrame, cols: list[str]) -> pl.DataFrame:
    """Infinities (an open interest of 0 in the archive) and NaN become missing."""
    return p.with_columns([pl.when(pl.col(c).is_finite()).then(pl.col(c)).otherwise(None).alias(c)
                           for c in cols if c in p.columns])


def build(refresh: bool = False) -> pl.DataFrame:
    path = CACHE / "m1_flow_panel.parquet"
    if path.exists() and not refresh:
        return finite_only(pl.read_parquet(path), COIN_FLOW + MKT_FLOW)
    t0 = time.time()
    p = vol.build_panel()
    print(f"M1 panel {p.height:,} rows, {time.time() - t0:.0f}s", flush=True)
    flows = []
    for b in UNIVERSE:
        f = coin_flow(b)
        if not f.is_empty() and "ts_us" in f.columns:
            flows.append(f.with_columns(symbol=pl.lit(f"{b}USDT")))
    if flows:
        p = p.join(pl.concat(flows, how="diagonal_relaxed"), on=["ts_us", "symbol"], how="left")
    else:
        p = p.with_columns([pl.lit(None, pl.Float64).alias(c) for c in COIN_FLOW if c != "fund_last"])
    p = attach_funding(p)
    btc = p.filter(pl.col("symbol") == "BTCUSDT").select("ts_us", bn="close")
    hourly, prev = market_flow(btc)
    if hourly is not None:
        p = p.join(hourly, on="ts_us", how="left")
    else:
        p = p.with_columns(cb_prem_h=pl.lit(None, pl.Float64))
    p = (p.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US).join(prev, on="day", how="left")
         .drop("day").sort("ts_us"))
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_parquet(path)
    print(f"panel with flow {p.height:,} rows, {time.time() - t0:.0f}s", flush=True)
    return finite_only(p, COIN_FLOW + MKT_FLOW)


# ---------------------------------------------------------------- b1

def fit_predict(X: np.ndarray, y: np.ndarray, tr: np.ndarray, te: np.ndarray) -> tuple[np.ndarray, float]:
    m = lgb.LGBMRegressor(**PARAMS).fit(X[tr], y[tr])
    return m.predict(X[te]), float(np.var(y[tr] - m.predict(X[tr])))


def part_b1(p: pl.DataFrame) -> dict:
    ts = p["ts_us"].to_numpy()
    y, yvar = p["y"].to_numpy(), p["y_var"].to_numpy()
    sets = {"M1": vol.FEATURES, "M1 + flow": vol.FEATURES + COIN_FLOW + MKT_FLOW,
            "M1 + coin flow (diagnostic)": vol.FEATURES + COIN_FLOW,
            "M1 + market flow (diagnostic)": vol.FEATURES + MKT_FLOW}
    Xs = {k: p.select(v).to_numpy().astype(np.float32) for k, v in sets.items()}
    var = {k: np.full(len(y), np.nan) for k in sets}
    folds = []
    for fold in walk_forward(ts, FIRST_TEST):
        t = time.time()
        row = {"fold": fold.name, "rows": int(fold.test.sum())}
        for k, X in Xs.items():
            pr, rv = fit_predict(X, y, fold.train, fold.test)
            var[k][fold.test] = np.exp(pr + rv / 2)
            row[k] = float(np.mean(qlike(yvar[fold.test], var[k][fold.test])))
        folds.append(row)
        print(f"  {fold.name}: " + "  ".join(f"{k} {row[k]:.4f}" for k in sets) + f" ({time.time() - t:.0f}s)", flush=True)
    ok = np.isfinite(var["M1"]) & np.isfinite(var["M1 + flow"])
    loss = {k: qlike(yvar[ok], v[ok]) for k, v in var.items()}
    per_h = {k: pl.DataFrame({"t": ts[ok], "l": l}).group_by("t").agg(pl.col("l").mean()).sort("t")["l"].to_numpy()
             for k, l in loss.items()}
    out = {"rows": int(ok.sum()), "folds": folds, "models": {}}
    for k in sets:
        st, pv = diebold_mariano(per_h[k], per_h["M1"], lag=24)
        out["models"][k] = {"qlike": float(loss[k].mean()), "gain_pct": float(100 * (1 - loss[k].mean() / loss["M1"].mean())),
                            "dm_stat": st, "dm_p": pv,
                            "quarters_better": int(sum(r[k] < r["M1"] for r in folds)), "quarters": len(folds)}
    c = out["models"]["M1 + flow"]
    out["passes"] = bool(c["qlike"] < out["models"]["M1"]["qlike"] and c["dm_p"] < PASS_P
                         and c["quarters_better"] >= math.ceil(2 * len(folds) / 3))
    cov = p.filter(pl.col("ts_us") >= FIRST_TEST)
    out["coverage_oos"] = {f: float(cov[f].is_not_null().mean()) for f in COIN_FLOW + MKT_FLOW}
    return out


# ---------------------------------------------------------------- b2

def book_hourly() -> pl.DataFrame:
    """(ts_us hour, symbol, imb5, spread_l, depth5) from the recorder's Binance spot book20."""
    root = ROOT / "binance" / "book20"
    out = []
    for d in sorted(root.glob("date=*")):
        files = sorted(d.glob("*.parquet"))
        if not files:
            continue
        b = pl.concat([pl.read_parquet(f, columns=["ts_recv_us", "symbol", "bid_px", "bid_qty", "ask_px", "ask_qty"])
                       for f in files], how="vertical_relaxed")
        bq = pl.col("bid_qty").list.head(5).list.sum()
        aq = pl.col("ask_qty").list.head(5).list.sum()
        b0, a0 = pl.col("bid_px").list.first(), pl.col("ask_px").list.first()
        notional = ((pl.col("bid_px").list.head(5) * pl.col("bid_qty").list.head(5)).list.sum()
                    + (pl.col("ask_px").list.head(5) * pl.col("ask_qty").list.head(5)).list.sum())
        h = (b.filter(pl.col("bid_px").list.len() > 0)
             .with_columns(ts_us=(pl.col("ts_recv_us") // HOUR_US) * HOUR_US,
                           imb=(bq - aq) / (bq + aq), spr=(a0 - b0) / ((a0 + b0) / 2) * 1e4,
                           notional=notional)
             .group_by("ts_us", "symbol").agg(imb5=pl.col("imb").mean(), spr=pl.col("spr").mean(),
                                              depth5=pl.col("notional").mean(), n=pl.len()))
        out.append(h.filter(pl.col("n") >= 60))
        print(f"  book {d.name}", flush=True)
    h = pl.concat(out).sort("symbol", "ts_us")
    return (h.with_columns(spread_l=(pl.col("spr") + 1e-3).log(),
                           depth_chg=(pl.col("depth5") + 1).log()
                           - (pl.col("depth5").shift(1).rolling_mean(24, min_samples=12).over("symbol") + 1).log())
            .select("ts_us", "symbol", "imb5", "spread_l", "depth_chg"))


def ols(X: np.ndarray, y: np.ndarray) -> np.ndarray:
    A = np.column_stack([np.ones(len(X)), X])
    return np.linalg.lstsq(A, y, rcond=None)[0]


def part_b2(p: pl.DataFrame) -> dict:
    bk = book_hourly()
    ts = p["ts_us"].to_numpy()
    X = p.select(vol.FEATURES).to_numpy().astype(np.float32)
    y = p["y"].to_numpy()
    tr = ts < OB_START - DAY_US
    after = ts >= OB_START
    m = lgb.LGBMRegressor(**PARAMS).fit(X[tr], y[tr])
    rv = float(np.var(y[tr] - m.predict(X[tr])))
    q = p.filter(pl.Series(after)).select("ts_us", "symbol", "y", "y_var").with_columns(
        pred=pl.Series(m.predict(X[after]))).join(bk, on=["ts_us", "symbol"], how="inner").drop_nulls(OB_FEATURES)
    q = q.with_columns(day=(pl.col("ts_us") // DAY_US) * DAY_US).sort("ts_us")
    days = np.unique(q["day"].to_numpy())
    first = int(days.min()) + OB_WARMUP_D * DAY_US if len(days) else 0
    qs = q["ts_us"].to_numpy()
    Z = q.select(OB_FEATURES).to_numpy()
    res = q["y"].to_numpy() - q["pred"].to_numpy()
    corr = np.full(q.height, np.nan)
    corr0 = np.full(q.height, np.nan)
    rvc = np.full(q.height, np.nan)
    rv0 = np.full(q.height, np.nan)
    qd = q["day"].to_numpy()
    for d in days[days >= first]:
        fit = qs < d - DAY_US
        if fit.sum() < 200:
            continue
        beta = ols(Z[fit], res[fit])
        here = qd == d
        corr[here] = beta[0] + Z[here] @ beta[1:]
        rvc[here] = float(np.var(res[fit] - (beta[0] + Z[fit] @ beta[1:])))
        # Addendum control (not registered): the same refit with an intercept only.
        corr0[here] = float(res[fit].mean())
        rv0[here] = float(np.var(res[fit] - res[fit].mean()))
    ok = np.isfinite(corr)
    yv = q["y_var"].to_numpy()[ok]
    base = np.exp(q["pred"].to_numpy()[ok] + rv / 2)
    cand = np.exp(q["pred"].to_numpy()[ok] + corr[ok] + rvc[ok] / 2)
    ctrl = np.exp(q["pred"].to_numpy()[ok] + corr0[ok] + rv0[ok] / 2)
    out = {"book_hours": bk.height, "rows": int(ok.sum()),
           "first_day": datetime.fromtimestamp(first / 1e6, timezone.utc).strftime("%Y-%m-%d") if len(days) else None}
    if ok.sum() == 0:
        out["verdict"] = "too little data"
        out["passes"] = False
        return out
    lb, lc, l0 = qlike(yv, base), qlike(yv, cand), qlike(yv, ctrl)
    t = qs[ok]

    def per(l):
        return pl.DataFrame({"t": t, "l": l}).group_by("t").agg(pl.col("l").mean()).sort("t")["l"].to_numpy()
    st, pv = diebold_mariano(per(lc), per(lb), lag=24)
    st0, pv0 = diebold_mariano(per(lc), per(l0), lag=24)
    out.update(qlike_m1=float(lb.mean()), qlike_ob=float(lc.mean()), qlike_intercept=float(l0.mean()),
               dm_p=pv, dm_stat=st, dm_p_vs_intercept=pv0, dm_stat_vs_intercept=st0,
               beta_last=[float(x) for x in beta])
    enough = ok.sum() >= MIN_OB_ROWS
    out["passes"] = bool(enough and lc.mean() < lb.mean() and pv < PASS_P)
    out["verdict"] = ("passes" if out["passes"] else "fails" if enough else "too little data")
    return out


# ---------------------------------------------------------------- report

def _f(x, nd=4) -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else f"{x:.{nd}f}"


def write(res: dict) -> None:
    md = ["# M1 with flow and order-book inputs (X11 b)\n\nGenerated by `python -m lab.experiments.m1_flow` from the "
          "pre-registration in `model_upgrades_prereg.md`. 20 coins, next-hour log realised variance, QLIKE on the "
          "variance (lower is better).\n\n"]
    b1 = res.get("b1")
    if b1:
        md.append(f"## b1. Flow inputs, quarterly folds from 2024 ({b1['rows']:,} coin-hours)\n\n"
                  "| model | QLIKE | gain over M1 | DM p vs M1 | quarters better |\n|---|---|---|---|---|\n")
        for k, v in b1["models"].items():
            md.append(f"| {k} | {_f(v['qlike'])} | {v['gain_pct']:+.2f} % | {_f(v['dm_p'], 3) if k != 'M1' else ''} | "
                      f"{v['quarters_better'] if k != 'M1' else ''}{' of ' + str(v['quarters']) if k != 'M1' else ''} |\n")
        md.append("\n| quarter | rows | " + " | ".join(b1["models"]) + " |\n|---|---|" + "---|" * len(b1["models"]) + "\n")
        for r in b1["folds"]:
            md.append(f"| {r['fold']} | {r['rows']:,} | " + " | ".join(_f(r[k]) for k in b1["models"]) + " |\n")
        md.append("\nShare of out-of-sample rows with each input: "
                  + ", ".join(f"{k} {100 * v:.0f} %" for k, v in b1["coverage_oos"].items()) + ".\n\n"
                  f"**b1 verdict:** {'passes' if b1['passes'] else 'fails'} (needs lower QLIKE, DM p below {PASS_P}, "
                  "better in two thirds of the quarters).\n\n")
    b2 = res.get("b2")
    if b2:
        md.append(f"## b2. Order book (Binance spot book20 from 2026-09-30)\n\n{b2['book_hours']:,} coin-hours of "
                  f"book; corrected and scored from {b2.get('first_day')}: {b2['rows']:,} coin-hours.\n\n")
        if b2.get("qlike_m1") is not None:
            md.append("| forecast | QLIKE |\n|---|---|\n"
                      f"| M1 alone (fit before 2026-09-30) | {_f(b2['qlike_m1'])} |\n"
                      f"| M1 + order-book correction | {_f(b2['qlike_ob'])} |\n"
                      f"| M1 + intercept-only correction (addendum control, not registered) | {_f(b2['qlike_intercept'])} |\n\n"
                      f"DM p of the order-book correction against M1 alone {_f(b2['dm_p'], 3)}; against the intercept-only "
                      f"control {_f(b2['dm_p_vs_intercept'], 3)}.\n\n")
        md.append(f"**b2 verdict:** {b2['verdict']} (needs at least {MIN_OB_ROWS:,} coin-hours, lower QLIKE than M1, DM p "
                  f"below {PASS_P}).\n")
    report.write(NAME, "".join(md), res)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", choices=["b1", "b2"], default=None)
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    p = build(a.refresh)
    prev = report.REPORTS / NAME / "latest.json"
    # One part at a time keeps the other part's last result in the report.
    res = json.loads(prev.read_text(encoding="utf-8")) if a.part and prev.exists() else {}
    if a.part in (None, "b1"):
        res["b1"] = part_b1(p)
    if a.part in (None, "b2"):
        res["b2"] = part_b2(p)
    write(res)


if __name__ == "__main__":
    main()
