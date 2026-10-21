"""Route the crypto books' BTC and ETH legs through US spot ETFs (survey idea O1).

    python -m lab.experiments.etf_routing

Pre-registered in results/etf_routing_prereg.md (committed before this file ran). For
breakout_top10, tsmom_top20, tsmom_tranches (as they run on Alpaca, non-Alpaca coins in
cash) and the experimental btc_gated: each BTC and ETH leg filled (A) on Alpaca crypto at
04:15 UTC after the daily decision at 35 bps, or (B) through IBIT / ETHA at the next US
session's official open at 2 bps a side, the ETF position moving only at its own prints.
D = book with B legs minus book with A legs, per UTC day, from 2024-01-11. Writes
results/etf_routing.md below the marker and <reports>/etf_routing/latest.{md,json}.
"""

from __future__ import annotations

import json
import math
import sys
import time

import numpy as np

from .. import report
from . import alpaca_universe as au
from . import director_common as dc
from . import fam_common as fc
from . import vol_etf_common as vc

NAME = "etf_routing"
LAST_DAY = "2026-10-14"
START = np.datetime64("2024-01-11")
ETF = {"BTC": ("IBIT", "BTCUSDT"), "ETH": ("ETHA", "ETHUSDT")}
A_COST, B_COST = 0.0035, 0.0002
SCEN = {"base (A 35, B 2 bps)": (0.0035, 0.0002), "stress (A 25, B 5 bps)": (0.0025, 0.0005),
        "A maker 15, B 2 bps": (0.0015, 0.0002), "A 25, B 2 bps": (0.0025, 0.0002)}
BASE, STRESS_KEY = "base (A 35, B 2 bps)", "stress (A 25, B 5 bps)"
FILL_A_US = (4 * 60 + 15) * vc.MIN_US
YEARS = (2024, 2025, 2026)
TE_MAX = 0.02


# ---------------------------------------------------------------------------
# Books: held weights and gross returns per UTC day
# ---------------------------------------------------------------------------

def books(P: fc.Panel) -> dict[str, dict]:
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    out = {}
    for b, name in (("breakout", "breakout_top10"), ("tsmom_daily", "tsmom_top20"),
                    ("tsmom_tranches", "tsmom_tranches")):
        g, tv, _, held = au.simulate(P, b, au.cash_left(O[b], alp))
        out[name] = {"gross": g, "tov": tv, "held": held}
    # btc_gated: all of the book in BTC on a close above the 200-day average
    held = np.zeros((P.T, P.N))
    held[:, P.btc] = P.btc_on.astype(float)
    r = np.nan_to_num(P.ret[:, P.btc])
    g = np.r_[0.0, held[:-1, P.btc] * r[1:]]
    tv = np.abs(np.diff(np.r_[0.0, held[:, P.btc]]))
    out["btc_gated"] = {"gross": g, "tov": tv, "held": held}
    return out


def coin_col(P: fc.Panel, base: str) -> int:
    if base == "BTC":
        return P.btc
    c = [j for j, (b, n) in enumerate(zip(P.bases, P.names)) if b == base and "~" not in n and n.endswith("USDT")]
    return c[0]


# ---------------------------------------------------------------------------
# The two fills
# ---------------------------------------------------------------------------

def sessions(sym: str) -> dict[np.datetime64, tuple[float, float]]:
    df = vc.yahoo_daily(sym)
    d = vc.to_np_dates(df["date"])
    o, c = df["open"].to_numpy().astype(float), df["close"].to_numpy().astype(float)
    return {d[i]: (o[i], c[i]) for i in range(len(d)) if np.isfinite(o[i]) and o[i] > 0}


def leg(P: fc.Panel, bk: dict, base: str, days: np.ndarray, t0: int, t1: int) -> dict:
    """Daily leg P&L and turnover of both fills over panel rows t0..t1 (UTC days)."""
    j = coin_col(P, base)
    etf, pair = ETF[base]
    S = sessions(etf)
    first_etf = min(S)
    held = bk["held"][:, j]
    gross = bk["gross"]
    T = t1 - t0 + 1
    starts = P.days[t0:t1 + 1]
    p00 = vc.price_at(pair, starts)
    p0415 = vc.price_at(pair, starts + FILL_A_US)
    p24 = vc.price_at(pair, starts + vc.DAY_US)
    rday = np.nan_to_num(P.ret[t0:t1 + 1, j])
    pnl_a, pnl_b, tov_a, tov_b = (np.zeros(T) for _ in range(4))
    on_etf = np.zeros(T, dtype=bool)
    hA = held[t0 - 1]
    hB = hA
    prev_close = None
    in_etf = False
    for k in range(T):
        t = t0 + k
        day = days[t]
        tgt = held[t - 1]                         # decided at 00:00 UTC of this day
        g = gross[t]
        # A: crypto, trade at 04:15
        r1 = p0415[k] / p00[k] - 1
        r2 = p24[k] / p0415[k] - 1
        # Weights as a share of the book drift from close to close by the coin's daily return
        # against the book's (the simulator's own rule), for both fills alike, so a leg that
        # does not trade carries no spurious drift turnover.
        drift = (1 + rday[k]) / (1 + g) if 1 + g > 0 else 0.0
        pnl_a[k] = hA * r1
        tov_a[k] = abs(tgt - hA)
        pnl_a[k] += tgt * r2
        hA = tgt * drift
        # B: the same as A until the ETF's first session; the leg moves over at that day's
        # close at no cost (from then on the ETF leg starts from A's weight and that close).
        sess = S.get(day)
        if not in_etf:
            pnl_b[k], tov_b[k] = pnl_a[k], tov_a[k]
            hB = hA
            if day >= first_etf and sess is not None:
                in_etf = True
                prev_close = sess[1]
            continue
        on_etf[k] = True
        if sess is not None:
            o, c = sess
            gap = o / prev_close - 1
            pnl_b[k] = hB * gap
            tov_b[k] = abs(tgt - hB)
            ses = c / o - 1
            pnl_b[k] += tgt * ses
            hB = tgt * drift
            prev_close = c
        else:
            hB = hB * drift
    return {"pnl_a": pnl_a, "pnl_b": pnl_b, "tov_a": tov_a, "tov_b": tov_b, "on_etf": on_etf,
            "first_etf": str(first_etf), "held": held[t0:t1 + 1]}


def tracking(base: str) -> dict:
    """ETF close-to-close against Binance at the same 16:00 New York minute."""
    etf, pair = ETF[base]
    S = sessions(etf)
    d = np.array(sorted(S))
    c = np.array([S[x][1] for x in d])
    t16 = np.array([vc.ny_us(x, 16, 0) for x in d])
    p = vc.price_at(pair, t16)
    re = c[1:] / c[:-1] - 1
    rs = p[1:] / p[:-1] - 1
    m = np.isfinite(re) & np.isfinite(rs) & (d[1:] <= np.datetime64(LAST_DAY))
    diff = re[m] - rs[m]
    return {"etf": etf, "days": int(m.sum()), "te": float(diff.std() * math.sqrt(252)),
            "shortfall_yr": float(diff.mean() * 252), "corr": float(np.corrcoef(re[m], rs[m])[0, 1])}


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run() -> dict:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    days = (P.days // vc.DAY_US).astype("datetime64[D]")
    t0 = int(np.searchsorted(days, START))
    t1 = P.T - 1
    D_days = days[t0:t1 + 1]
    years = D_days.astype("datetime64[Y]").astype(int) + 1970
    B = books(P)
    trk = {b: tracking(b) for b in ETF}
    rows, series = [], {}
    for name, bk in B.items():
        legs = {b: leg(P, bk, b, days, t0, t1) for b in ETF}
        tot_tov = bk["tov"][t0:t1 + 1].sum()
        out = {"book": name}
        for sc, (ca, cb) in SCEN.items():
            d = sum(L["pnl_b"] - L["pnl_a"] - np.where(L["on_etf"], cb, ca) * L["tov_b"] + ca * L["tov_a"]
                    for L in legs.values())
            series[(name, sc)] = d
        d = series[(name, BASE)]
        ca, cb = SCEN[BASE]
        fee = sum(ca * L["tov_a"] - np.where(L["on_etf"], cb, ca) * L["tov_b"] for L in legs.values())
        rest = sum(L["pnl_b"] - L["pnl_a"] for L in legs.values())
        yrs = len(d) / 365
        # the book both ways: the backtest at 35 bps with the A legs, then + D
        # The book with A legs: the backtest (filled at the 00:00 UTC close, 35 bps) with its
        # BTC and ETH legs replaced by the 04:15 fills; with B legs that plus D.
        bt = bk["gross"][t0:t1 + 1] - A_COST * bk["tov"][t0 - 1:t1]
        pre_all = au.drifted(P, bk["held"])
        a_real = bt.copy()
        for b, L in legs.items():
            j = coin_col(P, b)
            h_prev = bk["held"][t0 - 1:t1, j]
            r = np.nan_to_num(P.ret[t0:t1 + 1, j])
            if name == "btc_gated":
                tv_bt = np.abs(np.diff(bk["held"][t0 - 2:t1, j]))
            else:
                tv_bt = np.abs(h_prev - pre_all[t0 - 1:t1, j])
            a_real += (L["pnl_a"] - A_COST * L["tov_a"]) - (h_prev * r - A_COST * tv_bt)
        b_real = a_real + d
        band = vc.boot_band(d, 365)
        mband = vc.boot_mean(d)
        out.update({
            "d_bps_yr": float(d.mean() * 365 * 1e4), "fee_saved_bps_yr": float(fee.sum() / yrs * 1e4),
            "rest_bps_yr": float(rest.sum() / yrs * 1e4),
            "d_sharpe": vc.sharpe(d, 365), "boot_p05": band[0], "boot_p95": band[1], "boot_above0": band[2],
            "mean_p05_bps": mband[0] * 365 * 1e4, "mean_p95_bps": mband[1] * 365 * 1e4,
            "d_stress_bps_yr": float(series[(name, STRESS_KEY)].mean() * 365 * 1e4),
            "d_a25_bps_yr": float(series[(name, "A 25, B 2 bps")].mean() * 365 * 1e4),
            "d_maker_bps_yr": float(series[(name, "A maker 15, B 2 bps")].mean() * 365 * 1e4),
            "book_a_sharpe": vc.sharpe(a_real, 365), "book_b_sharpe": vc.sharpe(b_real, 365),
            "book_a_dd": vc.max_dd(a_real), "book_b_dd": vc.max_dd(b_real),
            "book_a_cagr": vc.perf(a_real, 365)["cagr"], "book_b_cagr": vc.perf(b_real, 365)["cagr"],
            "bt_sharpe": vc.sharpe(bt, 365),
            "btc_eth_tov_share": float(sum(L["tov_a"].sum() for L in legs.values()) / tot_tov) if tot_tov else 0.0,
            "tov_yr": float(tot_tov / yrs),
            "avg_btc_eth_weight": float(sum(np.abs(L["held"]).mean() for L in legs.values())),
        })
        for y in YEARS:
            m = years == y
            out[f"d{y}_bps"] = float(d[m].mean() * 365 * 1e4) if m.any() else float("nan")
        series[(name, "a_real")] = a_real
        rows.append(out)
    pl_ = vc.pool([r["d_sharpe"] for r in rows])
    for r in rows:
        d = series[(r["book"], BASE)]
        r["deflated_p"] = vc.deflated(d, pl_, 365)
        te_ok = all(trk[b]["te"] < TE_MAX for b in ETF)
        rules = {"mean above 0 and bootstrap 5 % of D's Sharpe above 0": r["d_bps_yr"] > 0 and r["boot_p05"] > 0,
                 "mean above 0 with B 5 bps and A 25 bps": r["d_stress_bps_yr"] > 0,
                 "tracking error below 2 % a year": te_ok,
                 "no year negative": all(r[f"d{y}_bps"] >= 0 for y in YEARS if math.isfinite(r[f"d{y}_bps"]))}
        r["rules"] = rules
        r["passes"] = all(rules.values())
        r["killed"] = r["d_bps_yr"] <= 0
        r["verdict"] = "pass" if r["passes"] else ("killed" if r["killed"] else "fails: " + "; ".join(
            k for k, v in rules.items() if not v))
    return {"generated": dc.day_str(int(time.time() * 1e6)), "start": str(START), "last_day": LAST_DAY,
            "rows": rows, "tracking": trk, "pool": pl_, "days": int(len(D_days))}


def markdown(res: dict) -> str:
    rows = res["rows"]
    L = [f"## Results (generated {res['generated']}, {res['start']} to {res['last_day']}, {res['days']} days)", ""]
    passing = [r["book"] for r in rows if r["passes"]]
    L.append(("**Verdict: ETF routing saves money in " + ", ".join(passing) + ".**") if passing else
             "**Verdict: no book passes.**")
    L.append("")
    for r in rows:
        L.append(f"- **{r['book']}**: {r['verdict']}. D {r['d_bps_yr']:+.0f} bps of book equity a year "
                 f"(fee saved {r['fee_saved_bps_yr']:+.0f}, timing, weekend gap and tracking {r['rest_bps_yr']:+.0f}); "
                 f"mean band {r['mean_p05_bps']:+.0f} to {r['mean_p95_bps']:+.0f} bps; D's Sharpe {r['d_sharpe']:.2f}, "
                 f"band {r['boot_p05']:.2f} to {r['boot_p95']:.2f}; stress {r['d_stress_bps_yr']:+.0f} bps; per year "
                 + " / ".join(f"{r[f'd{y}_bps']:+.0f}" for y in YEARS) + f". Book Sharpe {r['book_a_sharpe']:.2f} "
                 f"with crypto fills, {r['book_b_sharpe']:.2f} with ETF fills; BTC and ETH are "
                 f"{r['btc_eth_tov_share'] * 100:.0f} % of its turnover.")
    L += ["", "### Per book", ""]
    L.append(dc.table(rows, ["book", "d_bps_yr", "fee_saved_bps_yr", "rest_bps_yr", "d_sharpe", "boot_p05", "boot_p95",
                             "d_stress_bps_yr", "d_a25_bps_yr", "d_maker_bps_yr", "d2024_bps", "d2025_bps", "d2026_bps",
                             "deflated_p"], ".2f"))
    L += ["", "### The books both ways (from 2024-01-11)", ""]
    L.append(dc.table(rows, ["book", "bt_sharpe", "book_a_sharpe", "book_b_sharpe", "book_a_cagr", "book_b_cagr",
                             "book_a_dd", "book_b_dd", "tov_yr", "btc_eth_tov_share", "avg_btc_eth_weight"], ".3f"))
    L += ["", "`bt_sharpe` is the backtest's own convention (filled at the 00:00 UTC close at 35 bps); `book_a` fills "
          "the BTC and ETH legs at 04:15 UTC as the engine does, `book_b` through the ETFs.", "",
          "### Tracking against spot (16:00 New York)", ""]
    L.append(dc.table(list(res["tracking"].values()), ["etf", "days", "te", "shortfall_yr", "corr"], ".4f"))
    pl_ = res["pool"]
    L += ["", f"Pool {pl_['n_total']:,} trials; noise bar about {pl_['sr0_annual']:.2f}."]
    return "\n".join(L)


def main() -> int:
    res = run()
    md = markdown(res)
    dc.write_results(NAME, md)
    report.write(NAME, md, json.loads(json.dumps(res, default=str)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
