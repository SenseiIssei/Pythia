"""BTC volatility risk premium from DVOL, synthetic history (survey candidate 9). INFORMATION ONLY.

    python -m lab.experiments.btc_vrp

Pre-registered in results/btc_vrp_prereg.md (committed before this file ran). Monthly
30-day options sold at DVOL minus a haircut (Black-Scholes, zero rates), marked daily at
DVOL, settled at intrinsic value: a cash-secured put at the money and 10 % out of the
money, and an at-the-money covered call; each always or only when DVOL exceeds the
trailing 30-day realised volatility by its in-sample median. Against BTC and gated BTC.
No options trading code: evidence for a later IBIT options sleeve only. Writes
results/btc_vrp.md below the marker and <reports>/btc_vrp/latest.{md,json}.
"""

from __future__ import annotations

import json
import math
import sys
import time

import numpy as np
import polars as pl
from scipy import stats

from .. import report
from ..data import ROOT
from . import director_common as dc
from . import fam_common as fc
from . import gated_btc as gb
from . import vol_etf_common as vc

NAME = "btc_vrp"
LAST_DAY = "2026-10-19"
TENOR = 30
H_BASE, H_STRESS = 3.0, 6.0
SPLIT = np.datetime64("2024-01-01")
KINDS = ("P0", "P10", "CC")
YEARS_RULE = (2022, 2023, 2024, 2025, 2026)


def bs(S: float, K: float, tau: float, sig: float, call: bool) -> float:
    if tau <= 0 or sig <= 0:
        return max(S - K, 0.0) if call else max(K - S, 0.0)
    v = sig * math.sqrt(tau)
    d1 = (math.log(S / K) + 0.5 * v * v) / v
    d2 = d1 - v
    if call:
        return S * stats.norm.cdf(d1) - K * stats.norm.cdf(d2)
    return K * stats.norm.cdf(-d2) - S * stats.norm.cdf(-d1)


def load() -> dict:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    days = (P.days // vc.DAY_US).astype("datetime64[D]")
    S = P.px[:, P.btc]
    dv = pl.read_parquet(ROOT / "flow" / "dvol.parquet").filter(pl.col("currency") == "BTC").sort("day_us")
    dd = (dv["day_us"].to_numpy() // vc.DAY_US).astype("datetime64[D]")
    iv = np.full(P.T, np.nan)
    idx = np.searchsorted(days, dd)
    ok = (idx < P.T) & (days[np.minimum(idx, P.T - 1)] == dd)
    iv[idx[ok]] = dv["close"].to_numpy().astype(float)[ok] / 100
    lr = np.r_[np.nan, np.log(S[1:] / S[:-1])]
    rv = np.full(P.T, np.nan)
    for t in range(30, P.T):
        seg = lr[t - 29:t + 1]
        if np.isfinite(seg).all():
            rv[t] = seg.std(ddof=1) * math.sqrt(365)
    rv_fwd = np.full(P.T, np.nan)
    rv_fwd[:-30] = rv[30:]
    return {"P": P, "days": days, "S": S, "iv": iv, "rv": rv, "rv_fwd": rv_fwd}


def strategy(D: dict, kind: str, filt: bool, h: float, thresh: float | None, first: int) -> tuple[np.ndarray, list]:
    """Daily returns from `first` on, and the roll log."""
    S, iv, rv = D["S"], D["iv"], D["rv"]
    T = len(S)
    ret = np.zeros(T)
    rolls = []
    t = first
    while t < T - 1:
        exp = min(t + TENOR, T - 1)
        sell = not filt or (np.isfinite(rv[t]) and iv[t] - rv[t] > thresh)
        S0 = S[t]
        K = S0 * (0.9 if kind == "P10" else 1.0)
        call = kind == "CC"
        sig = iv[t] - h / 100
        prem = bs(S0, K, TENOR / 365, sig, call) if sell else 0.0
        cap = S0 if call else K
        prev = cap
        for u in range(t + 1, exp + 1):
            tau = (exp - u) / 365
            val = bs(S[u], K, tau, iv[u] if np.isfinite(iv[u]) else iv[u - 1], call) if sell else 0.0
            if call:
                nav = S[u] + prem - val
            else:
                nav = cap + prem - val
            ret[u] = nav / prev - 1
            prev = nav
        rolls.append({"day": str(D["days"][t]), "sold": bool(sell), "iv": float(iv[t]), "rv": float(rv[t]),
                      "premium_pct": float(prem / cap * 100), "result_pct": float((prev / cap - 1) * 100)})
        t = exp
    return ret, rolls


def run() -> dict:
    D = load()
    days, S, iv, rv = D["days"], D["S"], D["iv"], D["rv"]
    first = int(np.flatnonzero(np.isfinite(iv))[0]) + 30
    m = np.arange(len(days)) >= first
    ins = m & (days < SPLIT)
    oos = m & (days >= SPLIT)
    years = days.astype("datetime64[Y]").astype(int) + 1970
    # the filter threshold: the in-sample median of DVOL - RV30 on the in-sample roll days
    roll_days = np.arange(first, len(days), TENOR)
    rd_is = roll_days[days[roll_days] < SPLIT]
    thresh = float(np.nanmedian(iv[rd_is] - rv[rd_is]))
    btc = np.r_[0.0, S[1:] / S[:-1] - 1]
    P = D["P"]
    g1, t1 = gb.sim_gate(np.nan_to_num(P.ret[:, P.btc]), P.btc_on, 1.0)
    gated = gb.net(g1, t1, 0.0035)
    rows, series = [], {}
    for kind in KINDS:
        for filt in (False, True):
            name = f"{kind}{' F' if filt else ''}"
            x, rolls = strategy(D, kind, filt, H_BASE, thresh, first)
            xs, _ = strategy(D, kind, filt, H_STRESS, thresh, first)
            series[name] = {"base": x, "stress": xs, "rolls": rolls, "kind": kind, "filt": filt}
            p_is, p_oos = vc.perf(x[ins], 365), vc.perf(x[oos], 365)
            rows.append({"variant": name, "is_sharpe": p_is["sharpe"], "is_dd": p_is["max_dd"],
                         "oos_sharpe": p_oos["sharpe"], "oos_cagr": p_oos["cagr"], "oos_vol": p_oos["vol"],
                         "oos_dd": p_oos["max_dd"], "oos_h6": vc.sharpe(xs[oos], 365),
                         "sold_share": float(np.mean([r["sold"] for r in rolls])),
                         "worst_month_pct": float(min(r["result_pct"] for r in rolls))})
    pick = max(rows, key=lambda r: r["is_sharpe"])
    x = series[pick["variant"]]["base"]
    yrs = {y: vc.sharpe(x[m & (years == y)], 365) for y in YEARS_RULE}
    band = vc.boot_band(x[oos], 365, btc[oos])
    pool_ = vc.pool([r["oos_sharpe"] for r in rows])
    bench = {"BTC": vc.perf(btc[oos], 365), "gated BTC": vc.perf(gated[oos], 365)}
    bench_is = {"BTC": vc.perf(btc[ins], 365), "gated BTC": vc.perf(gated[ins], 365)}
    rules = {"Sharpe above BTC's and gated BTC's at 3 points": pick["oos_sharpe"] > bench["BTC"]["sharpe"]
             and pick["oos_sharpe"] > bench["gated BTC"]["sharpe"],
             "Sharpe above 0 at 6 points": pick["oos_h6"] > 0,
             "drawdown below BTC's": pick["oos_dd"] < bench["BTC"]["max_dd"],
             "positive in 3 of 2022 to 2026": sum(v > 0 for v in yrs.values()) >= 3,
             "bootstrap 5 % of Sharpe - BTC's above 0": band[0] > 0}
    # break-even haircut of the pick out of sample
    def sr_at(h: float) -> float:
        y, _ = strategy(D, series[pick["variant"]]["kind"], series[pick["variant"]]["filt"], h, thresh, first)
        return vc.sharpe(y[oos], 365)
    lo, hi = 0.0, 40.0
    be = float("nan")
    if sr_at(lo) > 0 > sr_at(hi):
        for _ in range(25):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if sr_at(mid) > 0 else (lo, mid)
        be = (lo + hi) / 2
    elif sr_at(hi) > 0:
        be = hi
    # the premium itself
    vrp = iv - D["rv_fwd"]
    ok = np.isfinite(vrp)
    prem = {int(y): {"mean_pts": float(np.nanmean(vrp[ok & (years == y)]) * 100),
                     "share_pos": float((vrp[ok & (years == y)] > 0).mean())}
            for y in sorted(set(years[ok])) if (ok & (years == y)).sum() > 20}
    prem["all"] = {"mean_pts": float(np.nanmean(vrp[ok]) * 100), "share_pos": float((vrp[ok] > 0).mean())}
    return {"generated": dc.day_str(int(time.time() * 1e6)), "first_roll": str(days[first]), "last_day": LAST_DAY,
            "thresh_pts": thresh * 100, "rows": rows, "pick": pick, "pick_years": yrs, "band": band,
            "deflated_p": vc.deflated(x[oos], pool_, 365), "pool": pool_, "bench": bench, "bench_is": bench_is,
            "rules": rules, "passes": all(rules.values()),
            "killed": pick["oos_sharpe"] < bench["BTC"]["sharpe"], "breakeven_h": be, "premium": prem,
            "rolls_pick": series[pick["variant"]]["rolls"]}


def pct(v: float) -> str:
    return f"{v * 100:.1f} %"


def markdown(res: dict) -> str:
    p, b = res["pick"], res["bench"]
    verdict = "**Passes.**" if res["passes"] else ("**Killed.**" if res["killed"] else "**Fails.**")
    L = [f"## Results (generated {res['generated']}, first roll {res['first_roll']}, in sample to 2023-12-31, "
         f"out of sample 2024-01-01 to {res['last_day']})", ""]
    L.append(f"{verdict} The in-sample pick is **{p['variant']}** (in-sample Sharpe {p['is_sharpe']:.2f}). Out of "
             f"sample at a 3-point haircut it makes Sharpe {p['oos_sharpe']:.2f}, {pct(p['oos_cagr'])} a year, "
             f"volatility {pct(p['oos_vol'])}, drawdown {pct(p['oos_dd'])}; at 6 points {p['oos_h6']:.2f}. BTC "
             f"{b['BTC']['sharpe']:.2f} / {pct(b['BTC']['cagr'])} / {pct(b['BTC']['max_dd'])}, gated BTC "
             f"{b['gated BTC']['sharpe']:.2f} / {pct(b['gated BTC']['cagr'])} / {pct(b['gated BTC']['max_dd'])}. "
             f"Bootstrap 90 % band of Sharpe(pick) - Sharpe(BTC) {res['band'][0]:.2f} to {res['band'][1]:.2f}. "
             f"Break-even haircut out of sample {res['breakeven_h']:.1f} vol points. Deflated p "
             f"{res['deflated_p']:.2f} over {res['pool']['n_total']:,}.")
    fails = [k for k, v in res["rules"].items() if not v]
    if fails:
        L += ["", "Failed: " + "; ".join(fails) + "."]
    L += ["", "Per year (Sharpe): " + ", ".join(f"{y} {v:.2f}" for y, v in res["pick_years"].items()) + ".", "",
          "### The six variants (3-point haircut; the filter sells when DVOL - RV30 exceeds "
          f"{res['thresh_pts']:.1f} points)", ""]
    L.append(dc.table(res["rows"], ["variant", "is_sharpe", "is_dd", "oos_sharpe", "oos_cagr", "oos_vol", "oos_dd",
                                    "oos_h6", "sold_share", "worst_month_pct"]))
    L += ["", f"In sample BTC {res['bench_is']['BTC']['sharpe']:.2f}, gated BTC "
          f"{res['bench_is']['gated BTC']['sharpe']:.2f}.", "",
          "### The premium: DVOL minus the next 30 days' realised volatility", ""]
    L.append(dc.table([{"year": k, **v} for k, v in res["premium"].items()], ["year", "mean_pts", "share_pos"]))
    return "\n".join(L)


def main() -> int:
    res = run()
    md = markdown(res)
    dc.write_results(NAME, md)
    report.write(NAME, md, json.loads(json.dumps(res, default=str)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
