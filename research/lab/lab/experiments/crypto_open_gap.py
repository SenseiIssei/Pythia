"""Does the overnight BTC move predict COIN and MSTR's session after the open gap? (survey O6)

    python -m lab.experiments.crypto_open_gap

Pre-registered in results/crypto_open_gap_prereg.md (committed before this file ran).
u_t = the stock's open gap minus its rolling 120-session BTC beta times BTC's move from
the previous 16:00 New York close to the 09:30 open (Binance 1-minute prices); does u_t
predict the open-to-close return, and does trading it pay after costs, entered at the open
and (judged) an hour late? Writes results/crypto_open_gap.md below the marker and
<reports>/crypto_open_gap/latest.{md,json}.
"""

from __future__ import annotations

import json
import math
import sys
import time

import numpy as np

from .. import report
from . import director_common as dc
from . import vol_etf_common as vc

NAME = "crypto_open_gap"
LAST_DAY = "2026-10-14"
STOCKS = {"COIN": "2021-10-01", "MSTR": "2021-03-01"}
SPLIT = np.datetime64("2023-01-01")
BETA_WIN = 120
THRESH = 0.0010
COST, STRESS = 0.0005, 0.0010
BORROW = 0.03 / 252
YEARS_OOS = (2023, 2024, 2025, 2026)


def ols_hc1(x: np.ndarray, y: np.ndarray) -> tuple[float, float, float]:
    """(intercept, slope, slope t with HC1 errors)."""
    n = len(x)
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    meat = (X * (e ** 2)[:, None]).T @ X
    V = XtX_inv @ meat @ XtX_inv * n / (n - 2)
    return float(b[0]), float(b[1]), float(b[1] / math.sqrt(V[1, 1])) if V[1, 1] > 0 else 0.0


def build(sym: str) -> dict:
    df = vc.yahoo_daily(sym)
    d = vc.to_np_dates(df["date"])
    keep = d <= np.datetime64(LAST_DAY)
    d = d[keep]
    o = df["open"].to_numpy().astype(float)[keep]
    c = df["close"].to_numpy().astype(float)[keep]
    t16 = np.array([vc.ny_us(x, 16, 0) for x in d])
    t0930 = np.array([vc.ny_us(x, 9, 30) for x in d])
    b16 = vc.price_at("BTCUSDT", t16)
    b0930 = vc.price_at("BTCUSDT", t0930)
    T = len(d)
    x = np.full(T, np.nan)
    g = np.full(T, np.nan)
    rc = np.full(T, np.nan)
    rb = np.full(T, np.nan)
    x[1:] = b0930[1:] / b16[:-1] - 1
    g[1:] = o[1:] / c[:-1] - 1
    rc[1:] = c[1:] / c[:-1] - 1
    rb[1:] = b16[1:] / b16[:-1] - 1
    s = c / o - 1
    beta = np.full(T, np.nan)
    for t in range(BETA_WIN + 1, T):
        a, b_ = rc[t - BETA_WIN:t], rb[t - BETA_WIN:t]
        m = np.isfinite(a) & np.isfinite(b_)
        if m.sum() >= BETA_WIN - 10 and b_[m].var() > 0:
            beta[t] = np.cov(a[m], b_[m])[0, 1] / b_[m].var(ddof=1)
    u = g - beta * x
    # an hour late: the open of the 10:30 hourly bar
    late = np.full(T, np.nan)
    try:
        h = vc.yahoo_hourly(sym)
        hts, hop = h["ts_us"].to_numpy(), h["open"].to_numpy().astype(float)
        pos = {int(a): v for a, v in zip(hts, hop)}
        for t in range(T):
            v = pos.get(vc.ny_us(d[t], 10, 30))
            if v is not None and v > 0:
                late[t] = v
    except vc.DataUnavailable as e:
        print(f"  {sym}: no hourly bars ({e})", file=sys.stderr)
    s_late = c / late - 1
    return {"d": d, "x": x, "g": g, "u": u, "s": s, "s_late": s_late, "beta": beta}


def rule(m: np.ndarray, s: np.ndarray, cost: float) -> tuple[np.ndarray, np.ndarray]:
    pos = np.where(np.abs(m) > THRESH, np.sign(m), 0.0)
    pos = np.where(np.isfinite(m) & np.isfinite(s), pos, 0.0)
    r = pos * np.nan_to_num(s) - 2 * cost * np.abs(pos) - BORROW * (pos < 0)
    return r, pos


def run() -> dict:
    out, all_series = [], {}
    for sym, start in STOCKS.items():
        B = build(sym)
        d = B["d"]
        ok = np.isfinite(B["u"]) & np.isfinite(B["s"])
        ins = ok & (d >= np.datetime64(start)) & (d < SPLIT)
        oos = ok & (d >= SPLIT)
        a_is, b_is, t_is = ols_hc1(B["u"][ins], B["s"][ins])
        a_o, b_o, t_o = ols_hc1(B["u"][oos], B["s"][oos])
        sign = np.sign(b_is) if b_is != 0 else 1.0
        m = b_is * B["u"]
        r_open, pos = rule(m, B["s"], COST)
        r_open_s, _ = rule(m, B["s"], STRESS)
        r_late, pl_ = rule(m, B["s_late"], COST)
        r_late_s, _ = rule(m, B["s_late"], STRESS)
        lw = oos & np.isfinite(B["s_late"])
        years = d.astype("datetime64[Y]").astype(int) + 1970
        row = {"stock": sym, "is_days": int(ins.sum()), "oos_days": int(oos.sum()),
               "late_days": int(lw.sum()), "late_from": str(d[lw][0]) if lw.any() else "none",
               "b_is": b_is, "t_is": t_is, "b_oos": b_o, "t_oos": t_o, "t_oos_signed": float(t_o * sign),
               "corr_gap_btc_oos": float(np.corrcoef(B["g"][oos], B["x"][oos])[0, 1]),
               "beta_median_oos": float(np.nanmedian(B["beta"][oos])),
               "is_open": vc.sharpe(r_open[ins], 252),
               "oos_open": vc.sharpe(r_open[oos], 252), "oos_open_stress": vc.sharpe(r_open_s[oos], 252),
               "oos_open_cagr": vc.perf(r_open[oos], 252)["cagr"],
               "late_open_same_days": vc.sharpe(r_open[lw], 252),
               "late": vc.sharpe(r_late[lw], 252), "late_stress": vc.sharpe(r_late_s[lw], 252),
               "trade_share_oos": float((pos[oos] != 0).mean()),
               "hit_oos": float((r_open[oos][pos[oos] != 0] > 0).mean()) if (pos[oos] != 0).any() else float("nan"),
               "mean_trade_bps_oos": float(r_open[oos][pos[oos] != 0].mean() * 1e4) if (pos[oos] != 0).any() else 0.0}
        row["years_open"] = vc.by_year(r_open[oos], years[oos], 252, YEARS_OOS)
        # the hour after the open, the part an open-to-close trade earns before a late entry
        row["first_hour_slope_t"] = float("nan")
        fh = lw & np.isfinite(B["s_late"])
        if fh.sum() > 30:
            first = (1 + B["s"][fh]) / (1 + B["s_late"][fh]) - 1
            row["first_hour_slope_t"] = ols_hc1(B["u"][fh], first)[2] * sign
            row["late_slope_t"] = ols_hc1(B["u"][fh], B["s_late"][fh])[2] * sign
        all_series[sym] = {"late": r_late[lw], "open": r_open[oos]}
        out.append(row)
    pool_ = vc.pool([r["late"] for r in out])
    for r in out:
        r["deflated_p_late"] = vc.deflated(all_series[r["stock"]]["late"], pool_, 252)
        rules = {"slope t above 2 in the in-sample sign": r["t_oos_signed"] > 2,
                 "rule above 0 an hour late at 5 bps": r["late"] > 0,
                 "rule above 0 an hour late at 10 bps": r["late_stress"] > 0}
        r["rules"] = rules
        r["passes"] = all(rules.values())
        r["killed"] = r["t_oos_signed"] < 1
        r["verdict"] = ("pass" if r["passes"] else ("killed (slope t below 1)" if r["killed"] else
                        "fails: " + "; ".join(k for k, v in rules.items() if not v)))
    return {"generated": dc.day_str(int(time.time() * 1e6)), "last_day": LAST_DAY, "rows": out, "pool": pool_}


def markdown(res: dict) -> str:
    L = [f"## Results (generated {res['generated']}, out of sample 2023-01-01 to {res['last_day']})", ""]
    if any(r["passes"] for r in res["rows"]):
        L.append("**Verdict: " + ", ".join(r["stock"] for r in res["rows"] if r["passes"]) + " passes.**")
    else:
        L.append("**Verdict: no pass.**")
    L.append("")
    for r in res["rows"]:
        L.append(f"- **{r['stock']}**: {r['verdict']}. Slope of the session on the gap surprise in sample "
                 f"{r['b_is']:.3f} (t {r['t_is']:.2f}, {r['is_days']} sessions), out of sample {r['b_oos']:.3f} "
                 f"(t {r['t_oos']:.2f}, {r['oos_days']} sessions). The rule at the official open makes Sharpe "
                 f"{r['oos_open']:.2f} out of sample ({r['oos_open_stress']:.2f} at 10 bps), trading "
                 f"{r['trade_share_oos'] * 100:.0f} % of sessions, {r['mean_trade_bps_oos']:+.1f} bps a trade; an hour "
                 f"late (from {r['late_from']}, {r['late_days']} sessions) {r['late']:.2f} ({r['late_stress']:.2f} at "
                 f"10 bps) against {r['late_open_same_days']:.2f} at the open on the same days. Deflated p "
                 f"{r['deflated_p_late']:.2f}.")
    L += ["", dc.table(res["rows"], ["stock", "is_days", "oos_days", "b_is", "t_is", "b_oos", "t_oos", "is_open",
                                     "oos_open", "oos_open_stress", "late_days", "late_open_same_days", "late",
                                     "late_stress", "first_hour_slope_t", "late_slope_t", "corr_gap_btc_oos",
                                     "beta_median_oos", "deflated_p_late"], ".3f"), ""]
    for r in res["rows"]:
        L.append(f"{r['stock']} at the open per year: " + ", ".join(f"{y} {v:.2f}" for y, v in r["years_open"].items())
                 + ".")
    L += ["", "`first_hour_slope_t` and `late_slope_t`: the slope's t (in the in-sample sign) for the first hour "
          "alone and for 10:30 to the close, on the sessions with hourly bars.", "",
          f"Pool {res['pool']['n_total']:,} trials; noise bar about {res['pool']['sr0_annual']:.2f}."]
    return "\n".join(L)


def main() -> int:
    res = run()
    md = markdown(res)
    dc.write_results(NAME, md)
    report.write(NAME, md, json.loads(json.dumps(res, default=str)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
