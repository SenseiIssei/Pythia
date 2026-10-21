"""O4: each coin's own Korean premium as a cross-sectional signal on the Alpaca books.

Run through `python -m lab.experiments.crypto_own` (registered in
results/crypto_own_prereg.md). Upbit day candles of every KRW market listed today
(`lab.collect.flow --only upbit_all`, under $PYTHIA_FLOW), USD/KRW from the same
folder, Binance closes from the panel. s = the 7-day mean of the coin's premium minus
BTC's. Rank IC against 7 and 28-day returns, a filter and a tilt on the three books,
and a weekly quintile long/short on perps as information. Writes
results/kr_premium_xs.md and <reports>/kr_premium_xs/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import polars as pl
from scipy import stats

from .. import report
from ..collect import flow as flowsrc
from . import crypto_own as co
from . import director_common as dc
from . import fam_common as fc

NAME = "kr_premium_xs"
GUARD_DAYS, GUARD_MAX = 30, 0.10
CUT = 0.5
MIN_COINS = 10
LS_COST = 0.0041
LS_FRAC = 0.2


def signal(P: fc.Panel) -> dict:
    up = pl.read_parquet(flowsrc.FLOW / "upbit_krw_1d.parquet")
    fx = pl.read_parquet(flowsrc.FLOW / "fx_usdkrw.parquet").sort("day_us")
    di = {int(d): i for i, d in enumerate(P.days)}
    # USD/KRW: the last ECB rate on or before each day.
    fxv = np.full(P.T, np.nan)
    fd, fv = fx["day_us"].to_numpy(), fx["usdkrw"].to_numpy()
    pos = np.searchsorted(fd, P.days, side="right") - 1
    fxv[pos >= 0] = fv[pos[pos >= 0]]
    cols_of: dict[str, list[int]] = {}
    for j, b in enumerate(P.bases):
        cols_of.setdefault(b, []).append(j)
    U = np.full((P.T, P.N), np.nan)
    markets = 0
    for (mk,), g in up.group_by(["market"]):
        base = mk.split("-", 1)[1]
        cols = cols_of.get(base, [])
        if not cols:
            continue
        markets += 1
        rows = np.array([di.get(int(d), -1) for d in g["day_us"].to_numpy()])
        vals = g["close"].to_numpy()
        ok = rows >= 0
        for j in cols:
            r, v = rows[ok], vals[ok]
            alive = P.alive[r, j]
            U[r[alive], j] = v[alive]
    with np.errstate(invalid="ignore", divide="ignore"):
        p = np.log(U / (P.close * fxv[:, None]))
    dropped = []
    for j in range(P.N):
        f = np.flatnonzero(np.isfinite(p[:, j]))
        if len(f) == 0:
            continue
        if np.median(np.abs(p[f[:GUARD_DAYS], j])) > GUARD_MAX:
            dropped.append(P.names[j])
            p[:, j] = np.nan
    p = np.where(np.abs(p) > CUT, np.nan, p)
    x = p - p[:, [P.btc]]
    s = fc.rolling(x, 7, 5)
    s[:, P.btc] = np.nan
    member = P.eligible & np.isfinite(s)
    member &= (member.sum(1) >= MIN_COINS)[:, None]
    return {"s": np.where(member, s, np.nan), "member": member, "p": p, "markets_matched": markets,
            "dropped": dropped}


def daily_ic(P: fc.Panel, s: np.ndarray, member: np.ndarray, fwd: np.ndarray) -> np.ndarray:
    ic = np.full(P.T, np.nan)
    for t in range(P.T):
        m = member[t] & np.isfinite(fwd[t])
        if m.sum() >= MIN_COINS:
            ic[t] = stats.spearmanr(s[t, m], fwd[t, m])[0]
    return ic


def ic_stats(ic: np.ndarray, mask: np.ndarray, step: int) -> dict:
    sel = np.flatnonzero(mask & np.isfinite(ic))
    every = sel[sel % step == 0]
    v = ic[every]
    t = float(v.mean() / v.std(ddof=1) * np.sqrt(len(v))) if len(v) > 2 and v.std() > 0 else float("nan")
    return {"ic": float(np.nanmean(ic[sel])) if len(sel) else float("nan"), "t": t, "n": int(len(v))}


def long_short(P: fc.Panel, s: np.ndarray, member: np.ndarray) -> np.ndarray:
    uni = member & P.perp_ok
    weekday = ((P.days // fc.DAY_US) + 3) % 7
    reb = (weekday == 0) & (uni.sum(1) >= MIN_COINS)
    q = fc.xs_rank(s, uni)
    W = np.zeros((P.T, P.N))
    lo, hi = uni & (q <= LS_FRAC), uni & (q > 1 - LS_FRAC)
    nl, nh = lo.sum(1, keepdims=True), hi.sum(1, keepdims=True)
    W = np.where(lo, 0.5 / np.maximum(nl, 1), W) - np.where(hi, 0.5 / np.maximum(nh, 1), 0.0)
    g, tv, _, _ = fc.simulate(P, W, rebalance=reb)
    return g - LS_COST * np.r_[0.0, tv[:-1]]


def compute(ctx: co.Ctx) -> dict:
    P = ctx.P
    sig = signal(P)
    s, member = sig["s"], sig["member"]
    print(f"  Upbit markets matched {sig['markets_matched']}, dropped by the guard {len(sig['dropped'])}", flush=True)
    fwd7, fwd28 = co.fwd_log_return(P, 7), co.fwd_log_return(P, 28)
    ic7, ic28 = daily_ic(P, s, member, fwd7), daily_ic(P, s, member, fwd28)
    ics = {"ic7_is": ic_stats(ic7, ctx.ins, 7), "ic7_oos": ic_stats(ic7, ctx.oos, 7),
           "ic28_is": ic_stats(ic28, ctx.ins, 28), "ic28_oos": ic_stats(ic28, ctx.oos, 28)}
    for y in co.YEARS_OOS:
        ics[f"ic7_{y}"] = ic_stats(ic7, ctx.oos & (ctx.years == y), 7)
    ic_pass = ics["ic7_oos"]["t"] <= -2
    killed = not ics["ic7_oos"]["t"] <= -1

    q = co.badness(s, member)
    flag = co.worst_third(q)
    mods = {"filter": flag, "tilt": q}
    trials, picks, forms = [], [], []
    for b in co.BOOKS:
        base_live = ctx.base35[(b, "live")]
        runs = {}
        for form, M in mods.items():
            runs[form] = co.apply(ctx, b, "live", form, M)
            t = co.trial(ctx, NAME, f"KR premium {form}", b, "mod", runs[form], base_live)
            trials.append(t)
            forms.append({"book": co.ORIGINAL[b], "form": form, "is": t.is_sr, "oos": t.oos_sr,
                          "book_is": co.sharpe(base_live[ctx.ins]), "book_oos": co.sharpe(base_live[ctx.oos])})
        best = max(mods, key=lambda f: co.sharpe(co.net(runs[f][0], runs[f][1], co.COST)[ctx.ins]))
        M = mods[best]
        lrun = co.apply(ctx, b, "live", best, co.late(M))
        trun = co.apply(ctx, b, "twin", best, M)
        key = f"KR premium {best}"
        trials += [co.trial(ctx, NAME, key + " · late", b, "late", lrun, base_live),
                   co.trial(ctx, NAME, key + " · twin", b, "twin", trun, ctx.base35[(b, "twin")])]
        picks.append(co.pick_row(ctx, b, key, runs[best], lrun, trun, form=best))
    ls = long_short(P, s, member)
    trials.append(co.trial(ctx, NAME, "KR premium quintile long/short, weekly, 41 bps", None, "ls", ls, None))
    pls = fc.perf(ls[ctx.oos])
    ls_row = {"is": co.sharpe(ls[ctx.ins]), "oos": pls["sharpe"], "cagr_pct": pls["cagr"] * 100,
              "dd_pct": pls["max_dd"] * 100, **{f"y{y}": co.sharpe(ls[ctx.oos & (ctx.years == y)]) for y in co.YEARS_OOS}}

    cover = []
    for y in (2020, 2021, 2022, 2023, 2024, 2025, 2026):
        m = ctx.years == y
        n = member[m].sum(1)
        cover.append({"year": y, "median_coins": float(np.median(n)) if m.any() else 0.0,
                      "days_ranked": int((n >= MIN_COINS).sum())})
    alp_cov = []
    for j in np.flatnonzero(ctx.alp):
        f = np.flatnonzero(np.isfinite(s[:, j]))
        alp_cov.append({"coin": P.bases[j], "first_signal": dc.day_str(P.days[f[0]]) if len(f) else "none",
                        "mean_s_pct_oos": float(np.nanmean(s[ctx.oos, j]) * 100) if np.isfinite(s[ctx.oos, j]).any()
                        else float("nan")})
    held_flag = []
    for b in co.BOOKS:
        hw = ctx.base[(b, "live")][3]
        inv = (hw > 0).any(1) & ctx.oos
        held_flag.append({"book": co.ORIGINAL[b], "days_holding_worst_third_pct":
                          100 * float(((hw > 0) & flag).any(1)[inv].mean()) if inv.any() else 0.0})
    first = np.flatnonzero(member.any(1))
    return {"trials": trials, "picks": picks, "forms": forms, "ics": ics, "ic_pass": bool(ic_pass),
            "killed": bool(killed), "ls": ls_row, "coverage": cover, "alpaca": alp_cov, "held": held_flag,
            "markets_matched": sig["markets_matched"], "dropped": sig["dropped"],
            "first_ranked": dc.day_str(P.days[first[0]]) if len(first) else "none"}


def write(ctx: co.Ctx, res: dict, fin: dict) -> None:
    ics, picks = res["ics"], res["picks"]
    any_pass = any(r["passes"] for r in picks)
    md = ["# Per-coin Korean premium (survey O4): results\n",
          f"Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}. Registered in "
          "`results/crypto_own_prereg.md` before the run and before the Upbit history was downloaded. Panel to "
          f"{dc.day_str(ctx.P.days[-1])}; out of sample from 2024-01-01; books at 35 bps, coins Alpaca does not list "
          "in cash. Upbit serves only the markets it lists today, so the coins on both are today's Upbit survivors; "
          "a pass could only be experimental and forward.\n",
          "## Verdict\n"]
    o7 = ics["ic7_oos"]
    if res["killed"]:
        v = f"Killed: the out-of-sample 7-day IC t-statistic is {o7['t']:.2f} (kill above -1)."
    elif res["ic_pass"]:
        v = f"The rank IC passes (t {o7['t']:.2f})."
    else:
        v = f"The rank IC neither passes nor is killed (t {o7['t']:.2f})."
    v += " No book passes the gates." if not any_pass else " At least one book passes the gates (experimental at best)."
    md.append(v + "\n")
    md.append(f"- {res['markets_matched']} Upbit KRW markets matched a Binance coin; {len(res['dropped'])} dropped by the "
              f"same-ticker guard ({', '.join(res['dropped'][:12]) or 'none'}). First ranked day "
              f"{res['first_ranked']}.")
    md.append(f"- Rank IC, 7 days: in sample {ics['ic7_is']['ic']:+.3f} (t {ics['ic7_is']['t']:.2f}, "
              f"{ics['ic7_is']['n']} weeks), out of sample {o7['ic']:+.3f} (t {o7['t']:.2f}, {o7['n']} weeks); by year "
              + ", ".join(f"{y} {ics[f'ic7_{y}']['ic']:+.3f} (t {ics[f'ic7_{y}']['t']:.2f})" for y in co.YEARS_OOS) + ".")
    md.append(f"- Rank IC, 28 days: in sample {ics['ic28_is']['ic']:+.3f} (t {ics['ic28_is']['t']:.2f}), out of "
              f"sample {ics['ic28_oos']['ic']:+.3f} (t {ics['ic28_oos']['t']:.2f}, {ics['ic28_oos']['n']} periods).")
    ls = res["ls"]
    md.append(f"- Long/short on perps (information, never wired): in sample {ls['is']:.2f}, out of sample "
              f"{ls['oos']:.2f} at 41 bps with funding, {ls['cagr_pct']:.1f} % a year, drawdown {ls['dd_pct']:.0f} %; "
              f"years {ls['y2024']:.2f} / {ls['y2025']:.2f} / {ls['y2026']:.2f}.")
    md.append("")
    md.append("## The books\n")
    md += co.gates_lines(picks)
    md.append("")
    md.append(co.pick_table(picks))
    md.append("\nBoth forms per book (35 bps):\n")
    md.append(dc.table(res["forms"], ["book", "form", "is", "book_is", "oos", "book_oos"]))
    md.append("\nHow often the books held a coin in the worst third (out of sample, days with any position):\n")
    md.append(dc.table(res["held"], ["book", "days_holding_worst_third_pct"]))
    md.append("\nThe books alone and gated BTC:\n")
    md.append(co.refs_table(ctx))
    md.append("\n## Coverage\n")
    md.append(dc.table(res["coverage"], ["year", "median_coins", "days_ranked"]))
    md.append("\nThe Alpaca coins (s is the coin's premium minus BTC's, 7-day mean):\n")
    md.append(dc.table(res["alpaca"], ["coin", "first_signal", "mean_s_pct_oos"]))
    md.append("\n" + co.pool_line(fin) + "\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    data = {k: v for k, v in res.items() if k != "trials"}
    data["pool"] = fin["pool"]
    report.write(NAME, text, data)
