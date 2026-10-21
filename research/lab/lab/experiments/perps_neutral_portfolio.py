"""One book from the three market-neutral perp books: equal weight, inverse vol, equal risk.

    PYTHIA_CACHE=<the 2026-10-07 xs_daily cache> PYTHIA_AGENT_OUT=<study folder> \
        python -m lab.experiments.perps_neutral_portfolio

Pre-registered in results/perps_neutral_portfolio_prereg.md (committed before this file
ran). The books as they exist: M4 reg7n (m4_residual.books, matched against the cached
pick series), funding carry's pick (F7, 10/10, 3-day tranches, funding_carry.load) and
the sweep's low-vol beta-neutral book (family 7, vol 60d, top 50, weekly) with both legs
on perps (trend_shorts.sim). Every series on the UTC day its return accrues; the
combination reweighted on the first day of each month from the trailing 90 days, one
gross target (1x before netting). Judged from 2024 at 10 bps. Writes
results/perps_neutral_portfolio.md below the marker and <reports>/perps_neutral_portfolio/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import report
from . import director_common as dc
from . import fam_common as fc
from . import trio_common as tc

NAME = "perps_neutral_portfolio"
BOOKS = ("M4", "Carry", "LowVol")
METHODS = ("EW", "IV", "ERC")
SEL_FROM, SEL_TO = "2022-03-01", "2023-12-31"
HOLD_FROM, HOLD_TO = "2024-01-02", "2026-09-29"
YEARS_OOS = (2024, 2025, 2026)
LOOKBACK, MIN_OBS = 90, 60
DAY_US = fc.DAY_US


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------

def erc(cov: np.ndarray, iters: int = 500, tol: float = 1e-10) -> np.ndarray:
    """Equal risk contribution weights (long only, summing to 1) by cyclical coordinate
    descent (Griveau-Billion, Richard and Roncalli 2013); copes with negative correlations."""
    n = cov.shape[0]
    sd = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    w = (1 / sd) / (1 / sd).sum()
    b = 1.0 / n
    for _ in range(iters):
        old = w.copy()
        for i in range(n):
            sig = float(np.sqrt(max(w @ cov @ w, 1e-24)))
            c = float(cov[i] @ w - cov[i, i] * w[i])
            a = cov[i, i]
            w[i] = (-c + np.sqrt(c * c + 4 * a * b * sig)) / (2 * a)
        if np.abs(w - old).max() < tol:
            break
    return w / w.sum()


def target(method: str, hist: np.ndarray) -> np.ndarray:
    """Book weights from the trailing daily returns hist (rows days, columns books)."""
    n = hist.shape[1]
    if method == "EW":
        return np.full(n, 1.0 / n)
    sd = hist.std(0)
    sd = np.where(sd > 0, sd, np.nan)
    if method == "IV":
        w = 1 / sd
        return w / np.nansum(w) if np.isfinite(w).all() else np.full(n, 1.0 / n)
    cov = np.cov(hist, rowvar=False)
    return erc(cov)


def month_starts(days: np.ndarray) -> np.ndarray:
    m = np.array([datetime.fromtimestamp(int(d) / 1e6, timezone.utc).month for d in days])
    out = np.zeros(len(days), dtype=bool)
    out[1:] = m[1:] != m[:-1]
    return out


def combine(R: np.ndarray, TV: np.ndarray, days: np.ndarray, method: str, cost: float,
            start: int) -> dict[str, np.ndarray]:
    """R: (T, n) daily net returns of the books at `cost`; TV: (T, n) their turnover
    charged on that day. Weights set on the first day of each month from the trailing
    LOOKBACK days (at least MIN_OBS complete rows), drifting in between. Returns the
    combination's net return, turnover and weights (NaN before the first reweight)."""
    T, n = R.shape
    ms = month_starts(days)
    out = {"net": np.full(T, np.nan), "turnover": np.full(T, np.nan), "w": np.full((T, n), np.nan)}
    w = None
    for t in range(start, T):
        if not np.isfinite(R[t]).all():
            if w is not None:
                out["net"][t], out["turnover"][t] = 0.0, 0.0
                out["w"][t] = w
            continue
        reb = 0.0
        if ms[t] or w is None:
            h = R[max(0, t - LOOKBACK):t]
            h = h[np.isfinite(h).all(1)]
            if len(h) >= MIN_OBS and (ms[t] or w is None):
                new = target(method, h)
                reb = float(np.abs(new - (w if w is not None else 0.0)).sum())
                w = new
        if w is None:
            continue
        g = float(w @ R[t])
        out["net"][t] = g - cost * reb
        out["turnover"][t] = float(w @ np.nan_to_num(TV[t])) + reb
        out["w"][t] = w
        w = w * (1 + R[t]) / (1 + g) if 1 + g > 0 else w
        w = w / w.sum()
    return out


# ---------------------------------------------------------------------------
# The three books on one calendar
# ---------------------------------------------------------------------------

def xs_books() -> tuple[np.ndarray, dict]:
    """M4 reg7n and funding carry's pick on the cached xs_daily panel: (decision days,
    {book: {gross, turnover, funding}}). Imported here: both read the cache on import."""
    from . import funding_carry as fcy
    from . import m4_residual as m4r
    days, B, _ = m4r.books()
    diff = m4r.check_cache(days, B["reg7n"])
    M, _ = fcy.load()
    carry = fcy.run_book(M, M["s_F7"], 10, 3)
    return days, {"M4": (days, B["reg7n"]), "Carry": (M["days"], carry), "match": diff}


def lowvol_book(P: fc.Panel) -> dict:
    """The sweep's low-vol beta-neutral book, both legs on perps, and the sweep's own
    version (spot long leg) for the reproduction check."""
    from . import fam_lowvol as flv
    from . import trend_shorts as ts
    W = flv.weights(P, "vol 60d", 50, "beta-neutral BAB")
    reb = fc.every(P, 7)
    o = ts.sim(P, np.where(reb[:, None], W, np.nan), start=100)
    g, tv, _, _ = fc.simulate(P, W, reb, 100)
    return {"perp": o, "sweep": (g, tv)}


def on_calendar(cal: np.ndarray, src_days: np.ndarray, x: np.ndarray, shift_days: int = 0) -> np.ndarray:
    out = np.full(len(cal), np.nan)
    idx = np.searchsorted(cal, src_days + shift_days * DAY_US)
    ok = (idx < len(cal)) & (cal[np.minimum(idx, len(cal) - 1)] == src_days + shift_days * DAY_US)
    out[idx[ok]] = x[ok]
    return out


def main() -> None:
    P = fc.load_panel()
    cal = P.days
    years = dc.years_of(cal)
    sel = (cal >= dc.us(SEL_FROM)) & (cal <= dc.us(SEL_TO))
    hold = (cal >= dc.us(HOLD_FROM)) & (cal <= dc.us(HOLD_TO))
    btc = np.nan_to_num(P.ret[:, P.btc])

    lv = lowvol_book(P)
    _, xb = xs_books()
    print("books ready", flush=True)

    # Per book and cost: net return and the turnover charged that day, on the return calendar.
    net, tov = {}, {}
    for c, v in tc.PERP_COSTS.items():
        for name in ("M4", "Carry"):
            d, b = xb[name]
            n_ = b["gross"] + b["funding"] - b["turnover"] * v
            net[(name, c)] = on_calendar(cal, d, n_, 1)
            tov[name] = on_calendar(cal, d, b["turnover"], 1)
        o = lv["perp"]
        live = np.arange(len(cal)) > 100
        n_lv = o["gross"] - v * np.r_[0.0, o["turnover"][:-1]]
        net[("LowVol", c)] = np.where(live, n_lv, np.nan)
        tov["LowVol"] = np.where(live, np.r_[0.0, o["turnover"][:-1]], np.nan)

    # Common days: every book has a value.
    common = np.all([np.isfinite(net[(b, tc.PERP_JUDGED)]) for b in BOOKS], axis=0)
    sel &= common
    hold &= common
    start = int(np.flatnonzero(common)[0])

    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "cache_match": xb["match"], "sel_from": dc.day_str(cal[sel][0]), "sel_to": dc.day_str(cal[sel][-1]),
                 "hold_from": dc.day_str(cal[hold][0]), "hold_to": dc.day_str(cal[hold][-1]),
                 "hold_days": int(hold.sum()), "first_common": dc.day_str(cal[start])}

    # Each book alone.
    singles = []
    for b in BOOKS:
        row = {"book": b}
        for c in tc.PERP_COSTS:
            x = net[(b, c)]
            row[f"sel_{c}"] = dc.sharpe(x[sel])
            row[f"hold_{c}"] = dc.sharpe(x[hold])
        x = net[(b, tc.PERP_JUDGED)]
        p = dc.perf(x[hold])
        row.update({"hold_cagr_pct": p["cagr"] * 100, "hold_dd_pct": p["max_dd"] * 100,
                    "turnover_yr": float(np.nanmean(tov[b][hold]) * 365),
                    "corr_btc_hold": float(np.corrcoef(x[hold], btc[hold])[0, 1]),
                    "corr_btc_sel": float(np.corrcoef(x[sel], btc[sel])[0, 1])})
        for y in YEARS_OOS:
            row[f"y{y}"] = dc.sharpe(x[hold & (years == y)])
        singles.append(row)
    res["singles"] = singles
    corr = []
    for lab_, m in (("selection", sel), ("holdout", hold)):
        X = np.column_stack([net[(b, tc.PERP_JUDGED)][m] for b in BOOKS])
        C = np.corrcoef(X, rowvar=False)
        corr.append({"window": lab_, "M4_Carry": C[0, 1], "M4_LowVol": C[0, 2], "Carry_LowVol": C[1, 2]})
    res["corr"] = corr

    # Sweep reproduction (spot long leg, 15 and 41 bps, the sweep's out-of-sample window).
    g, tv = lv["sweep"]
    ins, oos = fc.masks(P)
    res["sweep_repro"] = {c: dc.sharpe((g - v * np.r_[0.0, tv[:-1]])[oos]) for c, v in fc.COSTS.items()}
    res["sweep_repro_is"] = dc.sharpe((g - fc.COSTS["15bps"] * np.r_[0.0, tv[:-1]])[ins])

    # The three methods at every cost.
    combos, rows = {}, []
    for m in METHODS:
        row = {"method": m}
        for c, v in tc.PERP_COSTS.items():
            R = np.column_stack([net[(b, c)] for b in BOOKS])
            TV = np.column_stack([tov[b] for b in BOOKS])
            o = combine(R, TV, cal, m, v, start)
            combos[(m, c)] = o
            row[f"sel_{c}"] = dc.sharpe(o["net"][sel])
            row[f"hold_{c}"] = dc.sharpe(o["net"][hold])
        o = combos[(m, tc.PERP_JUDGED)]
        x = o["net"]
        p = dc.perf(x[hold])
        row.update({"hold_cagr_pct": p["cagr"] * 100, "hold_dd_pct": p["max_dd"] * 100,
                    "turnover_yr": float(np.nanmean(o["turnover"][hold]) * 365),
                    "corr_btc_hold": float(np.corrcoef(x[hold], btc[hold])[0, 1])})
        for y in YEARS_OOS:
            row[f"y{y}"] = dc.sharpe(x[hold & (years == y)])
        for i, b in enumerate(BOOKS):
            wb = o["w"][hold, i]
            row[f"w_{b}_mean"], row[f"w_{b}_min"], row[f"w_{b}_max"] = (float(np.nanmean(wb)), float(np.nanmin(wb)),
                                                                          float(np.nanmax(wb)))
        rows.append(row)
    res["methods"] = rows

    pick = max(rows, key=lambda r: r["sel_10bps"])
    ref = max(singles, key=lambda r: r["sel_10bps"])
    res["pick"], res["reference"] = pick["method"], ref["book"]
    x = combos[(pick["method"], tc.PERP_JUDGED)]["net"]
    xr = net[(ref["book"], tc.PERP_JUDGED)]
    lo, hi, above = tc.boot(x[hold])
    dlo, dhi, dabove = tc.boot(x[hold], xr[hold])
    pl_ = tc.pool([r["hold_10bps"] for r in rows])
    res["pool"] = pl_
    res["boot"] = {"p05": lo, "p95": hi, "above0": above, "diff_p05": dlo, "diff_p95": dhi, "diff_above0": dabove}
    res["deflated_p"] = dc.deflated(x[hold], pl_)
    checks = {"1 Sharpe above 0.5 at 10 bps and above 0 at 20 bps": pick["hold_10bps"] > 0.5 and pick["hold_20bps"] > 0,
              "2 positive in 2 of 2024, 2025, 2026": sum(pick[f"y{y}"] > 0 for y in YEARS_OOS) >= 2,
              "3 bootstrap 5 % above 0": lo > 0,
              "4 above the reference book's Sharpe with a lower drawdown":
                  pick["hold_10bps"] > ref["hold_10bps"] and pick["hold_dd_pct"] < ref["hold_dd_pct"],
              "5 correlation with BTC within +-0.3": abs(pick["corr_btc_hold"]) < 0.3}
    res["checks"] = checks
    passed = all(checks.values())
    res["verdict"] = "pass" if passed else ("kill" if pick["hold_10bps"] <= 0 else "fail")
    res["confirmed"] = passed and res["deflated_p"] > 0.95
    write(res)


def write(res: dict) -> None:
    pick = next(r for r in res["methods"] if r["method"] == res["pick"])
    ref = next(r for r in res["singles"] if r["book"] == res["reference"])
    v = {"pass": "**Pass" + (", confirmed.**" if res["confirmed"] else ", experimental (fails deflation).**"),
         "fail": "**Fail.** The combination does not clear the registered gates.",
         "kill": "**Kill.** The combination loses money at the judged cost."}[res["verdict"]]
    b = res["boot"]
    md = ["# One book from the market-neutral perp books: results\n",
          f"Generated {res['generated']}. Registered in `results/perps_neutral_portfolio_prereg.md` before the run.\n",
          f"Selection {res['sel_from']} to {res['sel_to']}, holdout {res['hold_from']} to {res['hold_to']} "
          f"({res['hold_days']} days, return days). M4 rebuilt from the 2026-10-07 xs_daily cache matches the cached "
          f"pick series (largest difference {max(res['cache_match'].values()):.1e}). Costs per unit of one-way "
          "turnover; judged at 10 bps.\n",
          f"## Verdict\n\n{v} Pick (best selection Sharpe at 10 bps): **{res['pick']}**; reference single book: "
          f"**{res['reference']}**.\n"]
    for k, ok in res["checks"].items():
        md.append(f"- {k}: {'yes' if ok else 'no'}")
    md.append(f"\nThe pick from 2024 at 10 bps: Sharpe {pick['hold_10bps']:.2f} (2 bps {pick['hold_2bps']:.2f}, 20 bps "
              f"{pick['hold_20bps']:.2f}, 41 bps {pick['hold_41bps']:.2f}), {pick['hold_cagr_pct']:.1f} % a year, "
              f"drawdown {pick['hold_dd_pct']:.1f} %, correlation with BTC {pick['corr_btc_hold']:+.2f}, turnover "
              f"{pick['turnover_yr']:.0f}x a year; bootstrap 90 % band {b['p05']:.2f} to {b['p95']:.2f}. The reference "
              f"{ref['book']} alone: {ref['hold_10bps']:.2f}, drawdown {ref['hold_dd_pct']:.1f} %; band of the difference "
              f"{b['diff_p05']:.2f} to {b['diff_p95']:.2f} ({b['diff_above0'] * 100:.0f} % of draws above 0). Deflated p "
              f"{res['deflated_p']:.4f}.\n")
    md.append("## Each book alone\n")
    tab = res["singles"]
    md.append(dc.table(tab, ["book", "sel_10bps", "hold_2bps", "hold_10bps", "hold_20bps", "hold_41bps", "hold_cagr_pct",
                             "hold_dd_pct", "turnover_yr", "corr_btc_sel", "corr_btc_hold", "y2024", "y2025", "y2026"]))
    md.append("\nSharpe at each cost (daily x sqrt 365); CAGR, drawdown, turnover, years and correlations at 10 bps. "
              "LowVol has both legs on perps (longs pay funding).\n")
    md.append("\nPairwise correlations of the books' daily net returns at 10 bps:\n")
    md.append(dc.table(res["corr"], ["window", "M4_Carry", "M4_LowVol", "Carry_LowVol"]))
    r = res["sweep_repro"]
    md.append(f"\nReproduction: the sweep's low-vol book (spot long leg, no funding on it) makes {r['15bps']:.2f} / "
              f"{r['41bps']:.2f} at 15 / 41 bps from 2024 on today's panel (the sweep reported 2.11 / 1.91 to "
              f"2026-10-07), in sample {res['sweep_repro_is']:.2f} (0.54).\n")
    md.append("\n## The combinations\n")
    md.append(dc.table(res["methods"], ["method", "sel_10bps", "hold_2bps", "hold_10bps", "hold_20bps", "hold_41bps",
                                        "hold_cagr_pct", "hold_dd_pct", "turnover_yr", "corr_btc_hold", "y2024", "y2025",
                                        "y2026"]))
    md.append("\nBook weights from 2024 at 10 bps (mean, min, max):\n")
    md.append(dc.table(res["methods"], ["method"] + [f"w_{b}_{s}" for b in BOOKS for s in ("mean", "min", "max")]))
    md.append("\nReweighted on the first day of each month from the trailing 90 days; book weights sum to 1, every "
              "book at 1x gross, so the book is at 1x gross before netting. Reweight trades are charged; netting "
              "between books is not credited.\n")
    md.append("\n## Pool\n\n" + tc.pool_line(res["pool"]) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
