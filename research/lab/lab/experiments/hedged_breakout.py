"""breakout_top10 with its BTC beta hedged by a BTC perp short, and with perps_neutral.

    PYTHIA_AGENT_OUT=<sweep panel copy> PYTHIA_CACHE=<the 2026-10-07 xs_daily cache> \
        python -m lab.experiments.hedged_breakout

Pre-registered in results/hedged_breakout_prereg.md (committed before this file ran).
The book exactly as lab/paper/families.py builds it (Donchian 20/10 on the 10 most liquid
coins of each day), simulated by alpaca_universe.sim_daily; at each close the hedge is a
BTC perp position of minus the book's holdings beta (each coin's OLS beta to BTC over the
last 60 days), held to the next close, paying or receiving BTC funding. Trial 1 (H) is the
hedged book at 35 bps on the long leg and 10 bps on the hedge; trial 2 (C) holds H and
perps_neutral_portfolio's pick (rebuilt by that study's own functions and checked against
its published Sharpe) at equal risk, reweighted monthly. Writes results/hedged_breakout.md
below the marker and <reports>/hedged_breakout/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import report
from . import alpaca_universe as au
from . import director_common as dc
from . import fam_common as fc
from . import perps_neutral_portfolio as pnp
from . import round_two as r2

NAME = "hedged_breakout"
BETA_DAYS, BETA_MIN = 60, 40
# (long leg, hedge) per unit of one-way turnover
COSTS = {"judged": (0.0035, 0.0010), "stress": (0.0070, 0.0020), "binance": (0.0015, 0.0010)}
IS_FROM, OOS_FROM = "2020-08-01", "2024-01-01"
PN_CHECK = 2.47           # perps_neutral_portfolio's published holdout Sharpe of the pick at 10 bps


# ---------------------------------------------------------------------------
# Betas and the hedge
# ---------------------------------------------------------------------------

def coin_betas(P: fc.Panel, days: int = BETA_DAYS, min_obs: int = BETA_MIN) -> np.ndarray:
    """(T, N) OLS slope of each coin's daily return on BTC's over days t-days+1..t (both
    returns present, at least min_obs days); BTC's own is 1."""
    x = P.ret
    y = np.repeat(P.ret[:, P.btc][:, None], P.N, 1)
    ok = np.isfinite(x) & np.isfinite(y)
    xv, yv = np.where(ok, x, np.nan), np.where(ok, y, np.nan)
    mx, my = fc.rolling(xv, days, min_obs), fc.rolling(yv, days, min_obs)
    mxy, myy = fc.rolling(xv * yv, days, min_obs), fc.rolling(yv * yv, days, min_obs)
    var = myy - my ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        b = np.where(var > 0, (mxy - mx * my) / var, np.nan)
    b[:, P.btc] = 1.0
    return b


def hedge_ratio(held: np.ndarray, beta: np.ndarray) -> np.ndarray:
    """h(t) = - sum_i w_i(t) beta_i(t); a held coin without a beta gets the median beta of
    the held coins that have one that day, or 1."""
    T = held.shape[0]
    h = np.zeros(T)
    for t in range(T):
        on = held[t] > 0
        if not on.any():
            continue
        b = beta[t, on]
        fin = np.isfinite(b)
        fill = float(np.median(b[fin])) if fin.any() else 1.0
        h[t] = -float(held[t, on] @ np.where(fin, b, fill))
    return h


def hedge_leg(P: fc.Panel, h: np.ndarray, book_gross: np.ndarray) -> dict[str, np.ndarray]:
    """The BTC perp position h(t) held from close t to close t+1: its return (BTC's move
    minus the funding a long pays) and its turnover at each close, the position drifting
    with BTC and the book's equity in between."""
    r = np.nan_to_num(P.ret[:, P.btc])
    f = P.funding[:, P.btc]
    T = len(h)
    ret, tov = np.zeros(T), np.zeros(T)
    pos = 0.0
    for t in range(T):
        tov[t] = abs(h[t] - pos)
        pos = h[t]
        if t + 1 < T:
            g = pos * (r[t + 1] - f[t + 1])
            ret[t + 1] = g
            tot = 1 + book_gross[t + 1] + g
            pos = pos * (1 + r[t + 1]) / tot if tot > 0 else 0.0
    return {"ret": ret, "tov": tov, "funding": -h * np.r_[f[1:], 0.0]}


def shift_cost(tov: np.ndarray, c: float) -> np.ndarray:
    return c * np.r_[0.0, tov[:-1]]


def hedged(P: fc.Panel, W: np.ndarray, beta: np.ndarray, book_beta: bool = False) -> dict:
    """Book (au.sim_daily) and hedge; returns the parts and the net series per cost level."""
    g, tv, ex, held = au.sim_daily(P, W)
    if book_beta:
        book = g - COSTS["judged"][0] * np.r_[0.0, tv[:-1]]
        h = -trailing_beta(book, np.nan_to_num(P.ret[:, P.btc]))
    else:
        h = hedge_ratio(held, beta)
    hl = hedge_leg(P, h, g)
    out = {"gross": g, "tov": tv, "expo": ex, "held": held, "h": h, "hedge": hl}
    for k, (cl, ch) in COSTS.items():
        out[f"book_{k}"] = g - shift_cost(tv, cl)
        out[f"H_{k}"] = out[f"book_{k}"] + hl["ret"] - shift_cost(hl["tov"], ch)
    return out


def trailing_beta(x: np.ndarray, m: np.ndarray, days: int = BETA_DAYS) -> np.ndarray:
    """Slope of x on m over the last `days` days up to and including t (reported variant)."""
    xv, mv = x[:, None], m[:, None]
    mx, mm = fc.rolling(xv, days, BETA_MIN), fc.rolling(mv, days, BETA_MIN)
    mxm, mmm = fc.rolling(xv * mv, days, BETA_MIN), fc.rolling(mv * mv, days, BETA_MIN)
    var = mmm - mm ** 2
    with np.errstate(invalid="ignore", divide="ignore"):
        b = np.where(var > 0, (mxm - mx * mm) / var, 0.0)[:, 0]
    return np.nan_to_num(b)


# ---------------------------------------------------------------------------
# perps_neutral, rebuilt by its own study's functions
# ---------------------------------------------------------------------------

def perps_neutral_series(P: fc.Panel) -> dict:
    """perps_neutral_portfolio's books and its pick (ERC) on the sweep calendar, at every
    perp cost, exactly as that study's main() builds them."""
    cal = P.days
    lv = pnp.lowvol_book(P)
    _, xb = pnp.xs_books()
    net = {}
    for c, v in r2.PERP_COSTS.items():
        for name in ("M4", "Carry"):
            d, b = xb[name]
            net[(name, c)] = pnp.on_calendar(cal, d, b["gross"] + b["funding"] - b["turnover"] * v, 1)
        o = lv["perp"]
        live = np.arange(len(cal)) > 100
        net[("LowVol", c)] = np.where(live, o["gross"] - v * np.r_[0.0, o["turnover"][:-1]], np.nan)
    tov = {}
    for name in ("M4", "Carry"):
        d, b = xb[name]
        tov[name] = pnp.on_calendar(cal, d, b["turnover"], 1)
    o = lv["perp"]
    tov["LowVol"] = np.where(np.arange(len(cal)) > 100, np.r_[0.0, o["turnover"][:-1]], np.nan)
    common = np.all([np.isfinite(net[(b, r2.JUDGED)]) for b in pnp.BOOKS], axis=0)
    start = int(np.flatnonzero(common)[0])
    hold = (cal >= dc.us(pnp.HOLD_FROM)) & (cal <= dc.us(pnp.HOLD_TO)) & common
    out = {"hold": hold, "common": common, "books": {b: net[(b, r2.JUDGED)] for b in pnp.BOOKS}}
    for c, v in r2.PERP_COSTS.items():
        R = np.column_stack([net[(b, c)] for b in pnp.BOOKS])
        TV = np.column_stack([tov[b] for b in pnp.BOOKS])
        out[c] = pnp.combine(R, TV, cal, "ERC", v, start)["net"]
    out["check"] = dc.sharpe(out[r2.JUDGED][hold])
    return out


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def ols_ab(x: np.ndarray, m: np.ndarray) -> dict:
    from .m4_residual import ols, ols_se
    coef, r2_ = ols(x, m[:, None])
    se = ols_se(x, m[:, None])
    return {"alpha_ann": float(coef[0] * 365), "alpha_t": float(coef[0] / se[0]) if se[0] > 0 else 0.0,
            "beta": float(coef[1]), "r2": r2_}


def series_row(name: str, x: np.ndarray, m: np.ndarray, years: np.ndarray, btc: np.ndarray) -> dict:
    p = dc.perf(x[m])
    row = {"series": name, "sharpe": dc.sharpe(x[m]), "cagr_pct": p["cagr"] * 100, "dd_pct": p["max_dd"] * 100,
           "vol_pct": float(np.nanstd(x[m]) * np.sqrt(365) * 100),
           "corr_btc": float(np.corrcoef(x[m], btc[m])[0, 1])}
    for y in r2.YEARS_OOS:
        row[f"y{y}"] = dc.sharpe(x[m & (years == y)])
    return row


def main() -> None:
    P = fc.load_panel()
    cal = P.days
    years = dc.years_of(cal)
    btc = np.nan_to_num(P.ret[:, P.btc])
    ins = (cal >= dc.us(IS_FROM)) & (cal < dc.us(OOS_FROM))
    oos = cal >= dc.us(OOS_FROM)
    beta = coin_betas(P)
    W = au.originals(P)["breakout"]
    base = hedged(P, W, beta)
    late = hedged(P, au.one_day_late(W), beta)
    bookb = hedged(P, W, beta, book_beta=True)
    alp = au.alpaca_mask(P)
    cashl = hedged(P, au.cash_left(W, alp), beta)
    print("books ready", flush=True)
    pn = perps_neutral_series(P)
    print(f"perps_neutral rebuilt: {pn['check']:.4f}", flush=True)
    if round(pn["check"], 2) != PN_CHECK:
        raise SystemExit(f"perps_neutral rebuild gives {pn['check']:.4f}, not {PN_CHECK}: stop as registered")

    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "panel_to": dc.day_str(cal[-1]), "oos_days": int(oos.sum()), "pn_check": pn["check"]}
    # Trial 1: H.
    H = base["H_judged"]
    rows = []
    for k in COSTS:
        for nm, x in ((f"book · {k}", base[f"book_{k}"]), (f"H · {k}", base[f"H_{k}"])):
            r = series_row(nm, x, oos, years, btc)
            r["is"] = dc.sharpe(x[ins])
            rows.append(r)
    for nm, d in (("H · one day late", late), ("H · trailing book-return beta", bookb),
                  ("H · Alpaca coins, rest in cash", cashl)):
        r = series_row(nm, d["H_judged"], oos, years, btc)
        r["is"] = dc.sharpe(d["H_judged"][ins])
        rows.append(r)
    res["rows"] = rows
    hr = next(r for r in rows if r["series"] == "H · judged")
    hs = next(r for r in rows if r["series"] == "H · stress")
    lo, hi, above = r2.boot(H[oos])
    res["H_boot"] = {"p05": lo, "p95": hi, "above0": above}
    res["alpha"] = {"is": ols_ab(base["book_judged"][ins], btc[ins]), "oos": ols_ab(base["book_judged"][oos], btc[oos])}
    hm = base["h"][oos & (base["expo"] > 0)]
    res["hedge"] = {"mean_h": float(hm.mean()) if len(hm) else 0.0, "min_h": float(hm.min()) if len(hm) else 0.0,
                    "max_h": float(hm.max()) if len(hm) else 0.0,
                    "days_invested_pct": float((base["expo"][oos] > 0).mean() * 100),
                    "funding_pct_yr": float(base["hedge"]["funding"][oos].mean() * 365 * 100),
                    "hedge_tov_yr": float(base["hedge"]["tov"][oos].sum() / (oos.sum() / 365)),
                    "book_tov_yr": float(base["tov"][oos].sum() / (oos.sum() / 365))}
    late_sr = next(r for r in rows if r["series"] == "H · one day late")["sharpe"]
    res["H_checks"] = {"1 Sharpe above 0.5 at the judged cost and above 0 at the stress cost":
                       hr["sharpe"] > 0.5 and hs["sharpe"] > 0,
                       "2 positive in 2 of 2024, 2025, 2026": sum(hr[f"y{y}"] > 0 for y in r2.YEARS_OOS) >= 2,
                       "3 bootstrap 5 % above 0": lo > 0,
                       "4 correlation with BTC within +-0.3": abs(hr["corr_btc"]) < 0.3,
                       "5 one day late above 0": late_sr > 0}

    # Trial 2: C, on perps_neutral's holdout.
    m = pn["hold"]
    corr = {"perps_neutral": float(np.corrcoef(H[m], pn[r2.JUDGED][m])[0, 1])}
    for b, x in pn["books"].items():
        corr[b] = float(np.corrcoef(H[m], x[m])[0, 1])
    res["corr_pn"] = corr
    combos = {}
    for k, (cl, ch) in COSTS.items():
        if k == "binance":
            continue
        pn_c = r2.STRESS if k == "stress" else r2.JUDGED
        R = np.column_stack([base[f"H_{k}"], pn[pn_c]])
        R = np.where(pn["common"][:, None], R, np.nan)
        TV = np.zeros_like(R)
        start = int(np.flatnonzero(pn["common"])[0])
        combos[k] = pnp.combine(R, TV, cal, "IV", cl, start)
    C = combos["judged"]["net"]
    pnx = pn[r2.JUDGED]
    crow = series_row("C · judged", C, m, years, btc)
    cstr = series_row("C · stress", combos["stress"]["net"], m, years, btc)
    pnr = series_row("perps_neutral · 10 bps", pnx, m, years, btc)
    hpn = series_row("H · judged, same window", H, m, years, btc)
    res["C_rows"] = [crow, cstr, pnr, hpn]
    clo, chi, cab = r2.boot(C[m])
    dlo, dhi, dab = r2.boot(C[m], pnx[m])
    res["C_boot"] = {"p05": clo, "p95": chi, "above0": cab, "diff_p05": dlo, "diff_p95": dhi, "diff_above0": dab}
    wts = combos["judged"]["w"][m, 0]
    res["C_weight_H"] = {"mean": float(np.nanmean(wts)), "min": float(np.nanmin(wts)), "max": float(np.nanmax(wts))}
    res["C_checks"] = {"1 Sharpe above perps_neutral's and drawdown not above its":
                       crow["sharpe"] > pnr["sharpe"] and crow["dd_pct"] <= pnr["dd_pct"],
                       "2 Sharpe above 0.5 at the judged cost and above 0 at the stress cost":
                       crow["sharpe"] > 0.5 and cstr["sharpe"] > 0,
                       "3 positive in 2 of 2024, 2025, 2026": sum(crow[f"y{y}"] > 0 for y in r2.YEARS_OOS) >= 2,
                       "4 bootstrap 5 % above 0": clo > 0,
                       "5 correlation with BTC within +-0.3": abs(crow["corr_btc"]) < 0.3}

    pl_ = r2.pool([hr["sharpe"], crow["sharpe"]])
    res["pool"] = pl_
    res["H_deflated_p"] = dc.deflated(H[oos], pl_)
    res["C_deflated_p"] = dc.deflated(C[m], pl_)
    for t in ("H", "C"):
        passed = all(res[f"{t}_checks"].values())
        res[f"{t}_verdict"] = "pass" if passed else "fail"
        res[f"{t}_confirmed"] = passed and res[f"{t}_deflated_p"] > 0.95
    if hr["sharpe"] <= 0:
        res["H_verdict"] = "kill"
    res["C_window"] = (dc.day_str(cal[m][0]), dc.day_str(cal[m][-1]), int(m.sum()))
    write(res)


def write(res: dict) -> None:
    def verdict(t: str) -> str:
        v = res[f"{t}_verdict"]
        if v == "pass":
            return "**Pass" + (", confirmed.**" if res[f"{t}_confirmed"] else ", experimental (fails deflation).**")
        return {"fail": "**Fail.**", "kill": "**Kill.** The hedged book loses money at the judged cost."}[v]

    a = res["alpha"]
    h = res["hedge"]
    b = res["H_boot"]
    cb = res["C_boot"]
    hr = next(r for r in res["rows"] if r["series"] == "H · judged")
    cw = res["C_window"]
    md = ["# breakout_top10 with its BTC beta hedged: results\n",
          f"Generated {res['generated']}. Registered in `results/hedged_breakout_prereg.md` before the run.\n",
          f"Sweep panel to {res['panel_to']}; out of sample from 2024-01-01 ({res['oos_days']} days). Costs per unit "
          "of one-way turnover as (long leg, hedge): judged 35/10 bps, stress 70/20, the paper book's Binance level "
          f"15/10. perps_neutral rebuilt from its study's functions: holdout Sharpe {res['pn_check']:.4f} at 10 bps "
          "(published 2.47).\n",
          f"## Trial 1, H: the hedged book\n\n{verdict('H')}\n"]
    for k, ok in res["H_checks"].items():
        md.append(f"- {k}: {'yes' if ok else 'no'}")
    md.append(f"\nFrom 2024 at the judged cost H makes Sharpe {hr['sharpe']:.2f}, {hr['cagr_pct']:.1f} % a year, drawdown "
              f"{hr['dd_pct']:.1f} %, correlation with BTC {hr['corr_btc']:+.2f}; bootstrap band {b['p05']:.2f} to "
              f"{b['p95']:.2f} ({b['above0'] * 100:.0f} % of draws above 0); deflated p {res['H_deflated_p']:.4f}. The "
              f"unhedged book's alpha against BTC: {a['oos']['alpha_ann'] * 100:.1f} % a year (t {a['oos']['alpha_t']:.2f}), "
              f"beta {a['oos']['beta']:.2f} out of sample; in sample {a['is']['alpha_ann'] * 100:.1f} % (t "
              f"{a['is']['alpha_t']:.2f}), beta {a['is']['beta']:.2f}.\n")
    md.append(dc.table(res["rows"], ["series", "is", "sharpe", "cagr_pct", "dd_pct", "vol_pct", "corr_btc", "y2024",
                                     "y2025", "y2026"]))
    md.append("\n`is` is the Sharpe 2020-08 to 2023, the rest from 2024. `book` is breakout_top10 unhedged, `H` with "
              "the hedge; the last three rows are H at the judged cost decided a close late, hedged by the book's own "
              "trailing 60-day return beta, and on the coins Alpaca lists (the rest in cash).\n")
    md.append(f"\nThe hedge on invested days from 2024: mean {h['mean_h']:.2f} of book equity (range {h['min_h']:.2f} to "
              f"{h['max_h']:.2f}); the book is invested on {h['days_invested_pct']:.0f} % of days; the hedge earned "
              f"{h['funding_pct_yr']:.2f} % a year in funding; turnover a year {h['hedge_tov_yr']:.1f} on the hedge, "
              f"{h['book_tov_yr']:.1f} on the book.\n")
    c = res["corr_pn"]
    md.append(f"\nCorrelation of H's daily returns with perps_neutral on its holdout ({cw[0]} to {cw[1]}): "
              f"{c['perps_neutral']:+.2f}; with its books M4 {c['M4']:+.2f}, carry {c['Carry']:+.2f}, low vol "
              f"{c['LowVol']:+.2f}.\n")
    md.append(f"## Trial 2, C: H and perps_neutral at equal risk\n\n{verdict('C')}\n")
    for k, ok in res["C_checks"].items():
        md.append(f"- {k}: {'yes' if ok else 'no'}")
    cr = res["C_rows"][0]
    w = res["C_weight_H"]
    md.append(f"\nOn {cw[0]} to {cw[1]} ({cw[2]} days) C makes Sharpe {cr['sharpe']:.2f}, {cr['cagr_pct']:.1f} % a year, "
              f"drawdown {cr['dd_pct']:.1f} %; bootstrap band {cb['p05']:.2f} to {cb['p95']:.2f}; the band of the "
              f"difference to perps_neutral alone {cb['diff_p05']:.2f} to {cb['diff_p95']:.2f} "
              f"({cb['diff_above0'] * 100:.0f} % of draws above 0); deflated p {res['C_deflated_p']:.4f}. H's weight in "
              f"C: mean {w['mean']:.2f}, range {w['min']:.2f} to {w['max']:.2f}.\n")
    md.append(dc.table(res["C_rows"], ["series", "sharpe", "cagr_pct", "dd_pct", "vol_pct", "corr_btc", "y2024", "y2025",
                                       "y2026"]))
    md.append("\nWeights proportional to 1 / trailing 90-day volatility, set on the first day of each month, drifting "
              "in between; reweights charged at the long leg's cost. perps_neutral at 10 bps (20 in the stress row).\n")
    md.append("\n## Pool\n\n" + r2.pool_line(res["pool"]) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
