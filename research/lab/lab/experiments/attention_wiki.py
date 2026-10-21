"""Investor attention from Wikipedia page views: a cross-sectional signal and a BTC switch.

    PYTHIA_AGENT_OUT=<study folder> python -m lab.experiments.attention_wiki

Pre-registered in results/attention_wiki_prereg.md (committed before the page views were
downloaded and before this file ran). Page views from lab.collect.wiki (each coin's
article plus its redirects, agent "user"); a decision at the close of day t uses views up
to day t-1. att = log((1 + mean views of the last 7 days) / (1 + mean of the 90 days
before)). Ranked among the 100 most liquid eligible coins of the survivorship-free panel
that have an article with 97 days of views and at least 100 views a day. A rank IC test,
a weekly quintile long/short on perps, the worst third filtered out of the three Alpaca
books (crypto_own's harness and gates) and two BTC switches. Writes
results/attention_wiki.md below the marker and <reports>/attention_wiki/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import report
from ..collect import flow
from ..collect import wiki
from . import crypto_own as co
from . import director_common as dc
from . import fam_common as fc
from . import gated_btc as gb
from . import kr_premium_xs as kr
from . import trend_shorts as ts
from . import trio_common as tc

NAME = "attention_wiki"
W_SHORT, W_LONG = 7, 90
MIN_HISTORY = W_SHORT + W_LONG          # 97 days of views
MIN_VIEWS = 100.0
REF_TOP = 100
MIN_COINS = 10
LS_FRAC = 0.2
SPIKE_Q, SPIKE_WIN, SPIKE_MIN = 0.8, 365, 180


# ---------------------------------------------------------------------------
# The signal
# ---------------------------------------------------------------------------

def views_matrix(P: fc.Panel, cv: pl.DataFrame) -> np.ndarray:
    """(T, N) daily views of each coin's article(s) on the panel's days, NaN before the
    first day with views, 0 on later days without a row. Every segment of a base gets
    the base's views while it is alive."""
    V = np.full((P.T, P.N), np.nan)
    di = {int(d): i for i, d in enumerate(P.days)}
    cols: dict[str, list[int]] = {}
    for j, b in enumerate(P.bases):
        cols.setdefault(b, []).append(j)
    for (base,), g in cv.group_by(["base"]):
        js = cols.get(base, [])
        if not js:
            continue
        v = np.full(P.T, np.nan)
        rows = np.array([di.get(int(d), -1) for d in g["day_us"].to_numpy()])
        ok = rows >= 0
        v[rows[ok]] = g["views"].to_numpy()[ok]
        f = np.flatnonzero(np.isfinite(v))
        if len(f):
            v[f[0]:] = np.nan_to_num(v[f[0]:])
        for j in js:
            V[:, j] = np.where(P.alive[:, j], v, np.nan)
    return V


def attention(V: np.ndarray) -> dict[str, np.ndarray]:
    """att at the close of t from views up to t-1, and the history and level checks."""
    lag = np.full_like(V, np.nan)
    lag[1:] = V[:-1]
    v7 = fc.rolling(lag, W_SHORT, W_SHORT)
    v90 = np.full_like(V, np.nan)
    v90[W_SHORT:] = fc.rolling(lag, W_LONG, W_LONG)[:-W_SHORT]
    hist = fc.rolling(np.where(np.isfinite(lag), 1.0, np.nan), MIN_HISTORY, 1, how="sum")
    with np.errstate(invalid="ignore", divide="ignore"):
        att = np.log((1 + v7) / (1 + v90))
    ok = np.isfinite(att) & (np.nan_to_num(hist) >= MIN_HISTORY) & (np.nan_to_num(v90) >= MIN_VIEWS)
    return {"att": np.where(ok, att, np.nan), "v7": v7, "v90": v90}


def members(P: fc.Panel, att: np.ndarray) -> np.ndarray:
    m = P.eligible & P.top_liquid(REF_TOP) & np.isfinite(att)
    return m & (m.sum(1) >= MIN_COINS)[:, None]


def spikes(a: np.ndarray) -> np.ndarray:
    """a[t] above the SPIKE_Q quantile of its own previous SPIKE_WIN values (at least SPIKE_MIN)."""
    out = np.zeros(len(a), dtype=bool)
    for t in range(len(a)):
        if not np.isfinite(a[t]):
            continue
        h = a[max(0, t - SPIKE_WIN):t]
        h = h[np.isfinite(h)]
        if len(h) >= SPIKE_MIN:
            out[t] = a[t] > np.quantile(h, SPIKE_Q)
    return out


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

def ls_weights(P: fc.Panel, s: np.ndarray, member: np.ndarray) -> np.ndarray:
    """Every 7th day (kr_premium_xs's weekday) long the lowest fifth by s and short the
    highest fifth among ranked coins with a live perp, half the capital per side; NaN rows
    (no rebalance) keep the book."""
    uni = member & P.perp_ok
    weekday = ((P.days // fc.DAY_US) + 3) % 7
    reb = (weekday == 0) & (uni.sum(1) >= MIN_COINS)
    q = fc.xs_rank(s, uni)
    lo, hi = uni & (q <= LS_FRAC), uni & (q > 1 - LS_FRAC)
    nl, nh = lo.sum(1, keepdims=True), hi.sum(1, keepdims=True)
    W = np.where(lo, 0.5 / np.maximum(nl, 1), 0.0) - np.where(hi, 0.5 / np.maximum(nh, 1), 0.0)
    return np.where(reb[:, None], W, np.nan)


def late_score(s: np.ndarray) -> np.ndarray:
    out = np.full_like(s, np.nan)
    out[1:] = s[:-1]
    return out


def btc_rule(P: fc.Panel, on: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return gb.sim_gate(np.nan_to_num(P.ret[:, P.btc]), on, 1.0)


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def load_views() -> tuple[pl.DataFrame, pl.DataFrame]:
    pv = flow.read("wiki_pageviews")
    tt = flow.read("wiki_titles")
    if pv is None or tt is None:
        raise SystemExit("no page views stored: run python -m lab.collect.wiki first")
    tt = tt.filter(pl.col("day_us") == tt["day_us"].max())
    return wiki.coin_views(pv, tt), tt


def main() -> None:
    ctx = co.build_ctx()
    P, ins, oos, years = ctx.P, ctx.ins, ctx.oos, ctx.years
    cv, tt = load_views()
    V = views_matrix(P, cv)
    A = attention(V)
    att = A["att"]
    member = members(P, att)
    att_m = np.where(member, att, np.nan)
    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "panel_to": dc.day_str(P.days[-1]), "titles": int(tt.height),
                 "coins_mapped": int(tt["base"].n_unique()),
                 "coins_in_panel": int(len({b for b in P.bases if b in set(tt["base"].to_list())}))}

    # Rank IC (test, not a trial).
    fwd7, fwd28 = co.fwd_log_return(P, 7), co.fwd_log_return(P, 28)
    ic7, ic28 = kr.daily_ic(P, att_m, member, fwd7), kr.daily_ic(P, att_m, member, fwd28)
    ics = {"ic7_is": kr.ic_stats(ic7, ins, 7), "ic7_oos": kr.ic_stats(ic7, oos, 7),
           "ic28_is": kr.ic_stats(ic28, ins, 28), "ic28_oos": kr.ic_stats(ic28, oos, 28)}
    for y in co.YEARS_OOS:
        ics[f"ic7_{y}"] = kr.ic_stats(ic7, oos & (years == y), 7)
    res["ics"] = ics
    res["ic_pass"] = bool(ics["ic7_oos"]["t"] <= -2)
    res["ic_killed"] = bool(not ics["ic7_oos"]["t"] <= -1)
    print("IC done", flush=True)

    trials: list[co.Trial] = []
    # 1-2: long/short on perps.
    Wls = ls_weights(P, att_m, member)
    o = ts.sim(P, Wls, start=0)
    ol = ts.sim(P, ls_weights(P, late_score(att_m), co.late(member)), start=0)
    ls_net = {c: ts.net(o, v) for c, v in tc.PERP_COSTS.items()}
    late_net = ts.net(ol, tc.PERP_COSTS[tc.PERP_JUDGED])
    x = ls_net[tc.PERP_JUDGED]
    trials.append(co.trial(ctx, NAME, "attention quintile long/short, perps, 10 bps", None, "ls", x, None))
    trials.append(co.trial(ctx, NAME, "attention long/short one day late", None, "ls", late_net, None))
    p = fc.perf(x[oos])
    lo, hi, above = tc.boot(x[oos])
    ls = {"is": co.sharpe(x[ins]), "oos": p["sharpe"], "cagr_pct": p["cagr"] * 100, "dd_pct": p["max_dd"] * 100,
          **{f"oos_{c}": co.sharpe(v[oos]) for c, v in ls_net.items()},
          **{f"y{y}": co.sharpe(x[oos & (years == y)]) for y in co.YEARS_OOS},
          "late": co.sharpe(late_net[oos]), "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
          "corr_btc": float(np.corrcoef(x[oos], np.nan_to_num(P.ret[oos, P.btc]))[0, 1]),
          "turnover_yr": float(o["turnover"][oos].sum() / (oos.sum() / 365)),
          **{f"{k}_pct_yr": float(o[k][oos].mean() * 365 * 100) for k in ("long_px", "short_px", "long_fund",
                                                                          "short_fund")}}
    ls["checks"] = {"1 Sharpe above 0.5 at 10 bps and above 0 at 20 bps": ls["oos_10bps"] > 0.5 and ls["oos_20bps"] > 0,
                    "2 positive in 2 of 2024, 2025, 2026": sum(ls[f"y{y}"] > 0 for y in co.YEARS_OOS) >= 2,
                    "3 one day late above 0": ls["late"] > 0,
                    "4 bootstrap 5 % above 0": lo > 0}
    ls["passes"] = all(ls["checks"].values())
    res["ls"] = ls
    print("long/short done", flush=True)

    # 3-11: the filter on the three books.
    flag = co.worst_third(co.badness(att_m, member))
    picks, held = [], []
    for b in co.BOOKS:
        base_live = ctx.base35[(b, "live")]
        run = co.apply(ctx, b, "live", "filter", flag)
        lrun = co.apply(ctx, b, "live", "filter", co.late(flag))
        trun = co.apply(ctx, b, "twin", "filter", flag)
        trials += [co.trial(ctx, NAME, "attention filter", b, "mod", run, base_live),
                   co.trial(ctx, NAME, "attention filter · late", b, "late", lrun, base_live),
                   co.trial(ctx, NAME, "attention filter · twin", b, "twin", trun, ctx.base35[(b, "twin")])]
        picks.append(co.pick_row(ctx, b, "attention filter", run, lrun, trun))
        hw = ctx.base[(b, "live")][3]
        inv = (hw > 0).any(1) & oos
        held.append({"book": co.ORIGINAL[b],
                     "days_holding_flagged_pct": 100 * float(((hw > 0) & flag).any(1)[inv].mean()) if inv.any() else 0.0,
                     "held_weight_ranked_pct": 100 * float(np.where(member, hw, 0).sum(1)[inv].mean()
                                                           / max(hw.sum(1)[inv].mean(), 1e-12)) if inv.any() else 0.0})
    print("filters done", flush=True)

    # 12-13: BTC switches at 35 bps.
    a_btc = att[:, P.btc]
    spike = spikes(a_btc)
    spike_late = np.r_[False, spike[:-1]]
    ones = np.ones(P.T, dtype=bool)
    btc_rows = []
    for key, on, on_late, bench_on, bench_name in (
            ("BTC unless spike", ~spike, ~spike_late, ones, "BTC held"),
            ("gated BTC unless spike", P.btc_on & ~spike, P.btc_on & ~spike_late, P.btc_on, "gated BTC")):
        g, tv = btc_rule(P, on)
        gl, tvl = btc_rule(P, on_late)
        gB, tvB = btc_rule(P, bench_on)
        m35, l35, b35 = gb.net(g, tv, co.COST), gb.net(gl, tvl, co.COST), gb.net(gB, tvB, co.COST)
        trials.append(co.trial(ctx, NAME, key, None, "btc", m35, b35))
        pm, pb = fc.perf(m35[oos]), fc.perf(b35[oos])
        dlo, dhi, dab = tc.boot(m35[oos], b35[oos])
        ym = {y: co.sharpe(m35[oos & (years == y)]) for y in co.YEARS_OOS}
        yb = {y: co.sharpe(b35[oos & (years == y)]) for y in co.YEARS_OOS}
        row = {"rule": key, "bench": bench_name, "is": co.sharpe(m35[ins]), "bench_is": co.sharpe(b35[ins]),
               "oos": pm["sharpe"], "bench_oos": pb["sharpe"], "dd_pct": pm["max_dd"] * 100,
               "bench_dd_pct": pb["max_dd"] * 100, "cagr_pct": pm["cagr"] * 100, "bench_cagr_pct": pb["cagr"] * 100,
               "late": co.sharpe(l35[oos]), "band_lo": dlo, "band_hi": dhi,
               "years_better": int(sum(ym[y] > yb[y] for y in co.YEARS_OOS)),
               "flagged_oos_pct": 100 * float(spike[oos].mean()), "flagged_is_pct": 100 * float(spike[ins].mean()),
               "_diff": (m35 - b35)[oos], "_m35": m35[oos]}
        row["checks"] = {"1 Sharpe above the benchmark, 2 of 3 years": row["oos"] > row["bench_oos"]
                         and row["years_better"] >= 2,
                         "2 drawdown not above the benchmark's": row["dd_pct"] <= row["bench_dd_pct"],
                         "3 band of the difference above 0": dlo > 0,
                         "4 a day late above the benchmark": row["late"] > row["bench_oos"]}
        row["passes"] = all(row["checks"].values())
        btc_rows.append(row)
    print("BTC done", flush=True)

    # Deflation: the pool over the 13 trials; gate 6 over the improvements.
    assert len(trials) == tc.STUDY_TRIALS[NAME], len(trials)
    pl_ = tc.pool([t.oos_sr for t in trials])
    diffs = [t for t in trials if t.diff is not None]
    dsr = np.clip(np.array([co.sharpe(t.diff[oos]) for t in diffs]), -fc.SR_CLIP, fc.SR_CLIP) / np.sqrt(365)
    dvar = float(np.var(dsr)) if len(dsr) > 1 else 1.0 / 365
    for row in picks:
        row["deflated_diff"] = co.deflated(row.pop("_diff"), len(trials), dvar)
        row["deflated_pool"] = co.deflated(row.pop("_m35"), pl_["n_total"], pl_["var"])
        co.verdict(row)
    for row in btc_rows:
        row["deflated_diff"] = co.deflated(row.pop("_diff"), len(trials), dvar)
        row["deflated_pool"] = co.deflated(row.pop("_m35"), pl_["n_total"], pl_["var"])
        row["confirmed"] = row["passes"] and row["deflated_diff"] > 0.95 and row["deflated_pool"] > 0.95
    ls["deflated_p"] = dc.deflated(x[oos], pl_)
    ls["confirmed"] = ls["passes"] and ls["deflated_p"] > 0.95
    res.update({"picks": picks, "held": held, "btc": btc_rows, "pool": pl_, "diff_var": dvar,
                "trial_oos": [{"key": t.key, "book": co.ORIGINAL.get(t.book, "") if t.book else "", "is": t.is_sr,
                               "oos": t.oos_sr} for t in trials]})

    # Coverage.
    cover = []
    for y in range(2020, int(years.max()) + 1):
        m = years == y
        n = member[m].sum(1)
        cover.append({"year": y, "median_ranked": float(np.median(n)) if m.any() else 0.0,
                      "days_ranked": int((n >= MIN_COINS).sum())})
    res["coverage"] = cover
    alp = []
    for j in np.flatnonzero(ctx.alp):
        f = np.flatnonzero(member[:, j])
        alp.append({"coin": P.bases[j], "first_ranked": dc.day_str(P.days[f[0]]) if len(f) else "never",
                    "mean_att_oos": float(np.nanmean(att_m[oos, j])) if np.isfinite(att_m[oos, j]).any() else float("nan")})
    res["alpaca"] = alp
    write(res)


def write(res: dict) -> None:
    ics, ls = res["ics"], res["ls"]
    o7 = ics["ic7_oos"]
    md = ["# Investor attention from Wikipedia page views: results\n",
          f"Generated {res['generated']}. Registered in `results/attention_wiki_prereg.md` before the page views were "
          f"downloaded. Panel to {res['panel_to']}; out of sample from 2024-01-01. {res['coins_mapped']} coins mapped "
          f"({res['coins_in_panel']} in the panel), {res['titles']} titles (articles and their redirects). A decision "
          "at the close of day t uses views up to day t-1.\n", "## Verdict\n"]
    if res["ic_killed"]:
        v = f"Cross-section killed: the out-of-sample 7-day rank IC t is {o7['t']:.2f} (kill above -1)."
    elif res["ic_pass"]:
        v = f"The cross-sectional rank IC passes (t {o7['t']:.2f})."
    else:
        v = f"The cross-sectional rank IC neither passes nor is killed (t {o7['t']:.2f})."
    passing = ([f"long/short ({'confirmed' if ls['confirmed'] else 'experimental'})"] if ls["passes"] else []) + \
        [f"{r['book']} filter ({r['verdict']})" for r in res["picks"] if r["passes"]] + \
        [f"{r['rule']} ({'confirmed' if r['confirmed'] else 'experimental'})" for r in res["btc"] if r["passes"]]
    v += (" Passes its gates: " + ", ".join(passing) + ".") if passing else " No trial passes its gates."
    md.append(v + "\n")
    md.append(f"- Rank IC with the next 7 days: in sample {ics['ic7_is']['ic']:+.3f} (t {ics['ic7_is']['t']:.2f}, "
              f"{ics['ic7_is']['n']} weeks), out of sample {o7['ic']:+.3f} (t {o7['t']:.2f}, {o7['n']} weeks); by year "
              + ", ".join(f"{y} {ics[f'ic7_{y}']['ic']:+.3f} (t {ics[f'ic7_{y}']['t']:.2f})" for y in co.YEARS_OOS)
              + f". 28 days: in sample {ics['ic28_is']['ic']:+.3f} (t {ics['ic28_is']['t']:.2f}), out of sample "
              f"{ics['ic28_oos']['ic']:+.3f} (t {ics['ic28_oos']['t']:.2f}).")
    md.append(f"- Long/short on perps (long the quiet fifth, short the hot fifth, weekly): out of sample "
              f"{ls['oos_10bps']:.2f} at 10 bps (2 bps {ls['oos_2bps']:.2f}, 20 bps {ls['oos_20bps']:.2f}, 41 bps "
              f"{ls['oos_41bps']:.2f}), {ls['cagr_pct']:.1f} % a year, drawdown {ls['dd_pct']:.0f} %, correlation with "
              f"BTC {ls['corr_btc']:+.2f}, years {ls['y2024']:.2f} / {ls['y2025']:.2f} / {ls['y2026']:.2f}, a day late "
              f"{ls['late']:.2f}, bootstrap band {ls['boot_p05']:.2f} to {ls['boot_p95']:.2f}, deflated p "
              f"{ls['deflated_p']:.4f}; in sample {ls['is']:.2f}. Gates failed: "
              + (", ".join(k for k, ok in ls["checks"].items() if not ok) or "none") + ".")
    md.append(f"  Legs from 2024 (% of capital a year): long price {ls['long_px_pct_yr']:.1f}, short price "
              f"{ls['short_px_pct_yr']:.1f}, long funding {ls['long_fund_pct_yr']:.1f}, short funding "
              f"{ls['short_fund_pct_yr']:.1f}; turnover {ls['turnover_yr']:.0f}x a year.")
    md.append("\n## The filter on the three books (35 bps, coins Alpaca does not list in cash)\n")
    md += co.gates_lines(res["picks"])
    md.append("")
    md.append(co.pick_table(res["picks"]))
    md.append("\nHow often the books held a flagged coin, and the share of their weight that is ranked at all (out of "
              "sample, days with any position):\n")
    md.append(dc.table(res["held"], ["book", "days_holding_flagged_pct", "held_weight_ranked_pct"]))
    md.append("\n## BTC switches (35 bps)\n")
    for r in res["btc"]:
        f = ", ".join(k for k, ok in r["checks"].items() if not ok) or "none"
        md.append(f"- **{r['rule']}** against {r['bench']}: {r['oos']:.2f} vs {r['bench_oos']:.2f}, drawdown "
                  f"{r['dd_pct']:.0f} % vs {r['bench_dd_pct']:.0f} %, {r['cagr_pct']:.1f} % vs {r['bench_cagr_pct']:.1f} % "
                  f"a year, band of the difference {r['band_lo']:.2f} to {r['band_hi']:.2f}, a day late {r['late']:.2f}, "
                  f"better in {r['years_better']} of 3 years; in cash {r['flagged_oos_pct']:.0f} % of days from 2024 "
                  f"({r['flagged_is_pct']:.0f} % before); improvement deflated p {r['deflated_diff']:.3f}. Failed: {f}.")
    md.append("\n## Every trial\n")
    md.append(dc.table(res["trial_oos"], ["key", "book", "is", "oos"]))
    md.append("\n## Coverage\n")
    md.append(dc.table(res["coverage"], ["year", "median_ranked", "days_ranked"]))
    md.append("\nThe Alpaca coins (att = log of the 7-day over the 90-day mean views):\n")
    md.append(dc.table(res["alpaca"], ["coin", "first_ranked", "mean_att_oos"]))
    md.append("\n## Pool\n\n" + tc.pool_line(res["pool"]) + f" Gate 6 deflates each improvement over the "
              f"{tc.STUDY_TRIALS[NAME]} trials at the variance of this study's {len(res['picks']) * 3 + 2} improvements.\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
