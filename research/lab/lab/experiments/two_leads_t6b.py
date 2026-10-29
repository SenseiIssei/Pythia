"""T6b: lead A (the perps_neutral portfolio) with T4's order book depth, and T5 with T4's delisting table.

Pre-registered in results/two_leads_t6b_prereg.md; results in results/two_leads_t6.md (the section "T6b: with
order book depth") and results/pit_universe_t5.md (the section "T6b: with T4's delisting table").

    PYTHIA_CACHE=<xs_daily panel cache> PYTHIA_AGENT_OUT=<panel cache> \
        flock <heavy lock> python -m lab.experiments.two_leads_t6b [--t5] [--refit] [--no-register] [--report]

Only T6's cost model changes: each perp leg traded at the close of day t (one close late) pays the USD-M taker fee
plus the cost of a market order of the leg's notional (1k, 10k judged, 100k USD) from T4's hourly row nearest the
fill (the latest hour of day t in the coin's file); a day without a file keeps T5's tier, a size the hour cannot
price pays 500 bps, both counted. M4's reg7n walk-forward scores are refit (the 2026-10-07 cache is gone) on the
xs_daily panel cut at 2026-06-30, and T6's tiers are rerun on the same inputs as the reference. --t5: T5's study
with LAB20 through lab.universe.tradable and its own 18 trials. The lockbox is never read; nothing here changes a
book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import metrics
from . import director_common as dc
from . import fam_common as fc
from . import pit_universe_t5 as t5
from . import two_leads_t6 as t6

NAME = "two_leads_t6b"
PREREG = "results/two_leads_t6b_prereg.md"
SIZES = {"1k": 1e3, "10k": 1e4, "100k": 1e5}       # USD a leg
JUDGED = "10k"
VARIANTS = ("fee", "tier") + tuple(SIZES)         # fee: the taker only; tier: T6's cost model on today's inputs
BEYOND = 0.05                                     # a size the hour cannot price: the 5 % level
HALF = 0.5                                        # the capacity: where the depth cost halves the fee-only Sharpe
DAY_US = fc.DAY_US
COLS = ("bid02", "ask02", "bid1", "ask1", "cost10k", "cost100k")
T5_TAG = "t5_pit_dl"


# ---------------------------------------------------------------- the depth at the fill

def coin_key(name: str) -> str:
    """The coin of a panel or xs_daily symbol as T4 names it (1000PEPEUSDT is PEPE); "" for an older asset of a
    reused ticker (NAME~0), which has no depth."""
    from ..collect import book_depth as bd
    return "" if "~" in name else bd.base_of(name)


def fill_hours(last_day: str = t6.VAL_TO) -> pl.DataFrame:
    """Per coin and UTC day T4's hourly row nearest the fill at the day's close: the day's latest hour (a coin with
    two perps keeps the deeper book of that hour, as lab.features.book). day_us, asset, ts_us and COLS."""
    from ..collect import book_depth as bd
    d = bd.out_dir() / "hourly"
    end = dc.us(last_day) + DAY_US
    rows = []
    for p in sorted(d.glob("symbol=*")) if d.is_dir() else []:
        s = p.name.removeprefix("symbol=")
        files = sorted(p.glob("*.parquet"))
        if not s.endswith("USDT") or not files:
            continue
        h = (pl.concat([pl.read_parquet(f, columns=["ts_us", *COLS]) for f in files], how="vertical_relaxed")
             .filter(pl.col("ts_us") < end).with_columns(day_us=pl.col("ts_us") // DAY_US * DAY_US))
        rows.append(h.sort("ts_us").group_by("day_us").last().with_columns(asset=pl.lit(bd.base_of(s))))
    if not rows:
        return pl.DataFrame(schema={"day_us": pl.Int64, "asset": pl.String, "ts_us": pl.Int64,
                                    **{c: pl.Float64 for c in COLS}})
    return (pl.concat(rows, how="vertical_relaxed")
            .sort("asset", "day_us", "ts_us", "bid1", descending=[False, False, True, True], nulls_last=True)
            .unique(["asset", "day_us"], keep="first").sort("asset", "day_us"))


def order_cost(fh: pl.DataFrame, size: float) -> np.ndarray:
    """(rows,) the cost of a market order of `size` USD from each fill hour, a fraction (buy and sell averaged);
    NaN where the hour cannot price it. 10k and 100k: the hour's measured cost; any other size: the collector's
    model (book_depth.cost_bps) on the hour's mean notional at 0.2 % and 1 % (nothing beyond 1 % is kept
    hourly)."""
    from ..collect import book_depth as bd
    k = next((c for c, s in bd.SIZES.items() if s == size), None)
    if k is not None:
        return fh[k].cast(pl.Float64).fill_null(np.nan).to_numpy() / 1e4
    out = []
    for a, b in (("bid02", "bid1"), ("ask02", "ask1")):
        lo, hi = (fh[c].cast(pl.Float64).fill_null(np.nan).to_numpy() for c in (a, b))
        out.append(bd.cost_bps(np.column_stack([lo] + [hi] * 5), size))
    return (out[0] + out[1]) / 2 / 1e4


def depth_matrix(days: np.ndarray, keys: list[str], fh: pl.DataFrame, size: float) -> tuple[np.ndarray, np.ndarray]:
    """(T, N) the depth cost of a leg of `size` USD traded at the close of each day (BEYOND where the hour has its
    book but cannot price the size, NaN where the coin has no depth file that day) and (T, N) where it was
    BEYOND."""
    D = np.full((len(days), len(keys)), np.nan)
    if not len(fh):
        return D, np.zeros(D.shape, dtype=bool)
    c = order_cost(fh, size)
    has = np.all([np.isfinite(fh[k].cast(pl.Float64).fill_null(np.nan).to_numpy()) for k in ("bid1", "ask1")], axis=0)
    c = np.where(np.isfinite(c), c, np.where(has, BEYOND, np.nan))
    beyond = np.zeros(D.shape, dtype=bool)
    ci: dict[str, list[int]] = {}
    for j, k in enumerate(keys):
        if k:
            ci.setdefault(k, []).append(j)
    ts = fh["day_us"].to_numpy()
    t = np.searchsorted(days, ts)
    hit = (t < len(days)) & (days[np.minimum(t, len(days) - 1)] == ts)
    for i, a in enumerate(fh["asset"].to_list()):
        if hit[i] and a in ci and np.isfinite(c[i]):
            D[t[i], ci[a]] = c[i]
            beyond[t[i], ci[a]] = c[i] >= BEYOND
    return D, beyond


def cost_matrices(days: np.ndarray, keys: list[str], vol: np.ndarray, fh: pl.DataFrame) -> dict[str, np.ndarray]:
    """{variant: (T, N) cost per unit of one-way turnover} and the counters: "at tier" (1 where the judged size
    falls back to the tier, the turnover there), "all" (1), "beyond <size>" (1 where the size was BEYOND)."""
    out = {"fee": np.full(vol.shape, t5.PERP_FEE), "tier": t6.era_cost(vol)}
    for k, s in SIZES.items():
        D, b = depth_matrix(days, keys, fh, s)
        out[k] = t6.era_cost(vol, D)
        out[f"beyond {k}"] = b.astype(float)
        if k == JUDGED:
            out["at tier"] = (~np.isfinite(D)).astype(float)
    out["all"] = np.ones(vol.shape)
    return out


COUNTERS = ("at tier", "all") + tuple(f"beyond {k}" for k in SIZES)


# ---------------------------------------------------------------- lead A's books under every cost matrix

def reg7n_scores(P: pl.DataFrame, log=print) -> pl.DataFrame:
    """M4's reg7n walk-forward scores (xs_daily.fit_net_scores' folds, embargo and parameters, reg7n only) on a
    panel already cut at the last validation day."""
    import lightgbm as lgb
    from ..cv import walk_forward
    from . import xs_daily as xs
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    days = E["day"].to_numpy()
    X = E.select(xs.FEATURES).to_numpy().astype(np.float32)
    yv = np.asarray(E["y7n"].to_numpy(), dtype=float)
    s = np.full(E.height, np.nan)
    for fold in walk_forward(days, xs.FIRST_TEST, embargo_h=8 * 24):
        tr = fold.train & np.isfinite(yv)
        s[fold.test] = lgb.LGBMRegressor(**xs.REG_PARAMS).fit(X[tr], yv[tr]).predict(X[fold.test])
        log(f"  reg7n {fold.name}: {int(tr.sum()):,} rows")
    return E.select("day", "symbol").with_columns(reg7n=pl.Series(s))


def xs_books(fh: pl.DataFrame, refit: bool = False, log=print) -> dict:
    """M4 reg7n and carry F7 late under every cost matrix, and on time at 10 bps (T6's check).
    {"days", "M4": {variant: (net, cost)}, "Carry": ..., "M4 on time": (net, turnover), ...}."""
    from . import funding_carry as fcy
    from . import xs_daily as xs
    from .. import report
    P = xs.build_panel().filter(pl.col("day") <= dc.us(t6.VAL_TO))
    P, _ = xs.add_net_labels(P)
    path = report.REPORTS / NAME / "reg7n_scores.parquet"
    if path.exists() and not refit:
        S = pl.read_parquet(path)
    else:
        S = reg7n_scores(P, log)
        path.parent.mkdir(parents=True, exist_ok=True)
        S.write_parquet(path)
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    E = E.join(S, on=["day", "symbol"], how="left").filter(pl.col("day") >= xs.FIRST_TEST)
    M = t6.cut_matrices(xs.matrices(E, P.filter(pl.col("day") >= xs.FIRST_TEST), ["reg7n"]), t6.VAL_TO)
    del E, S, P
    out = {"M4": {}, "Carry": {}}
    Cs = cost_matrices(M["days"], [coin_key(s) for s in M["syms"]], M["perp_adv28"], fh)
    late = fcy.late(M["reg7n"])
    for v, C in Cs.items():
        out["M4"][v] = t6.xs_net(xs.book_buffer(M, late, 10, 0.5, 100, C=C))
    g, tu, fu, _ = xs.book_buffer(M, M["reg7n"], 10, 0.5, 100)
    out["M4 on time"] = (M["days"], g + fu - t6.FLAT * tu, tu)
    out["M4 days"] = M["days"]
    del M
    F, _ = fcy.load()
    F = t6.cut_matrices(F, t6.VAL_TO)
    Cs = cost_matrices(F["days"], [coin_key(s) for s in F["syms"]], F["perp_adv28"], fh)
    late = fcy.late(F["s_F7"])
    for v, C in Cs.items():
        out["Carry"][v] = t6.xs_net(xs.book(F, late, 10, 3, fcy.N_LIQUID, True, C=C))
    g, tu, fu, _ = xs.book(F, F["s_F7"], 10, 3, fcy.N_LIQUID, True)
    out["Carry on time"] = (F["days"], g + fu - t6.FLAT * tu, tu)
    out["Carry days"] = F["days"]
    return out


def run_costs(P: fc.Panel, rule: str, uni: np.ndarray, n: int, Cs: dict[str, np.ndarray]) -> dict:
    """t5.run_rule under several cost matrices on one set of weights: {name: (net, cost)} (the sleeves' mean)."""
    Pu = t5.on(P, uni)
    acc: dict[str, list] = {k: [] for k in Cs}
    for W, reb, start in t5.books(Pu, rule, n):
        W, reb = t5.late(W, reb)
        if rule in t5.PERP_BOTH:
            reb = np.ones(P.T, dtype=bool)
        for k, C in Cs.items():
            net, gross = t5.simulate(Pu, W, reb, C, rule in t5.PERP_BOTH, start)
            acc[k].append((net, gross - net))
    return {k: (np.mean([a[0] for a in v], axis=0), np.mean([a[1] for a in v], axis=0)) for k, v in acc.items()}


def lowvol_books(P: fc.Panel, vol: np.ndarray, fh: pl.DataFrame, delist=None) -> dict:
    """The low-vol leg on PIT50 late under every cost matrix (T6's lowvol_books), and on time at 10 bps on the
    panel's top 50 (the check). {"LowVol": {variant: (net, cost)}, "LowVol on time": (net, turnover)}."""
    from .. import universe as U
    from .perps_neutral_portfolio import lowvol_book
    Cs = cost_matrices(P.days, [coin_key(n) for n in P.names], vol, fh)
    live = np.arange(P.T) > 100
    r = run_costs(P, "lowvol", U.pit(P, 50, table=delist, vol=vol), 50, Cs)
    o = lowvol_book(P)["perp"]
    tv = np.r_[0.0, o["turnover"][:-1]]
    return {"LowVol": {k: (np.where(live, a, np.nan), np.where(live, b, np.nan)) for k, (a, b) in r.items()},
            "LowVol on time": (np.where(live, o["gross"] - t6.FLAT * tv, np.nan), np.where(live, tv, np.nan))}


def nets(P: fc.Panel, xb: dict, lv: dict, variant: str) -> dict[str, np.ndarray]:
    """The three books' net (or, for a counter, the cost charged) under one matrix on the panel's calendar, with
    T6's on-time check series."""
    from .perps_neutral_portfolio import on_calendar
    out, j = {}, 1 if variant in COUNTERS else 0
    for b in ("M4", "Carry"):
        out[b] = on_calendar(P.days, xb[f"{b} days"], xb[b][variant][j], 1)
        d, n_, _ = xb[f"{b} on time"]
        out[f"{b} on time"] = on_calendar(P.days, d, n_, 1)
    out["LowVol"] = lv["LowVol"][variant][j]
    out["LowVol on time"] = lv["LowVol on time"][0]
    return out


# ---------------------------------------------------------------- measuring

def windows(P: fc.Panel, net: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    """lead_a's masks: (common, in sample, validation, the first common day)."""
    common = np.all([np.isfinite(net[b]) for b in t6.BOOKS], axis=0)
    ins = common & (P.days >= dc.us(t6.IS_FROM_A)) & (P.days <= dc.us(t6.IS_TO))
    val = common & (P.days >= dc.us(t6.VAL_FROM)) & (P.days <= dc.us(t6.VAL_TO))
    return common, ins, val, int(np.flatnonzero(common)[0])


def candidates(P: fc.Panel, net: dict, start: int) -> dict[str, np.ndarray]:
    """The three books and their combinations as lead_a builds them."""
    s = {b: net[b] for b in t6.BOOKS}
    s.update(t6.combos(P, net, {b: np.zeros(P.T) for b in t6.BOOKS}, t6.BOOKS, start))
    return s


def trial_rows(ins_sharpe: dict[str, float]) -> list[dict]:
    """The 10 trials: the six candidates at the judged size, and the ERC at the other sizes, the tiers and the fee."""
    rows = [t6.trial(f"hand:t6b:a:{k}", "hand", ins_sharpe[f"{k}@{JUDGED}"]) for k in t6.CANDIDATES]
    rows += [t6.trial(f"hand:t6b:a:{t6.PICK}@{v}", "hand", ins_sharpe[f"{t6.PICK}@{v}"])
             for v in VARIANTS if v != JUDGED]
    for r in rows:
        r["source"] = PREREG
    return rows


def capacity(sharpe: dict[str, float], fee: float) -> dict:
    """The leg notional where the ERC's Sharpe falls to HALF of its fee-only Sharpe, linear in log10 of the
    notional between the measured sizes. {"usd": float | None, "side": "below" | "above" | "at"}."""
    bar = HALF * fee
    xs_ = [math.log10(SIZES[k]) for k in SIZES]
    ys = [sharpe[k] for k in SIZES]
    if ys[0] <= bar:
        return {"usd": None, "side": "below", "bar": bar}
    for i in range(1, len(ys)):
        if ys[i] <= bar:
            f = (ys[i - 1] - bar) / (ys[i - 1] - ys[i])
            return {"usd": float(10 ** (xs_[i - 1] + f * (xs_[i] - xs_[i - 1]))), "side": "at", "bar": bar}
    return {"usd": None, "side": "above", "bar": bar}


def tier_counts(P: fc.Panel, cnt: dict[str, dict[str, np.ndarray]], ins: np.ndarray, val: np.ndarray) -> dict:
    """Per book and window: the days with a trade, the days with a leg at the tier and the share of the turnover
    at the tier (at the judged size), and per size the days with a leg beyond the hour's depth."""
    out = {}
    for b in t6.BOOKS:
        allc, tier = np.nan_to_num(cnt["all"][b]), np.nan_to_num(cnt["at tier"][b])
        row = {}
        for w, m in (("is", ins), ("val", val)):
            tr = (allc > 1e-12) & m
            row[w] = {"trade_days": int(tr.sum()), "tier_days": int(((tier > 1e-12) & m).sum()),
                      "tier_share": float(tier[m].sum() / allc[m].sum()) if allc[m].sum() > 0 else 0.0,
                      "beyond_days": {k: int(((np.nan_to_num(cnt[f"beyond {k}"][b]) > 1e-12) & m).sum())
                                      for k in SIZES}}
        out[b] = row
    return out


def lead_a(P: fc.Panel, by: dict[str, dict], cnt: dict, paper: dict, leak: dict | None, register: bool = True,
           log=print) -> dict:
    """T6's lead A at the judged size (t6.lead_a, its conditions, DSR, PBO, CPCV, paper record) with T6b's trials
    registered first, the ERC under every cost variant, the capacity and the counts. by: {variant: nets(...)}."""
    _, ins, val, start = windows(P, by[JUDGED])
    cands = {v: candidates(P, by[v], start) for v in VARIANTS}
    ins_sh = {f"{k}@{v}": t6.stats_of(cands[v][k][ins])["sharpe"] for v in VARIANTS for k in t6.CANDIDATES}
    trials = trial_rows(ins_sh)
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  T6b: in sample " + ", ".join(f"{t['id'].split(':')[-1]} {t['sharpe']:.2f}" for t in trials))
    A = t6.lead_a(P, by[JUDGED], paper, leak, register=False, log=lambda *_: None)
    A["trials"] = [t["id"] for t in trials]
    A["variants"] = {v: {"is": t6.stats_of(cands[v][t6.PICK][ins]), "val": t6.stats_of(cands[v][t6.PICK][val])}
                     for v in VARIANTS}
    A["capacity"] = capacity({k: A["variants"][k]["val"]["sharpe"] for k in SIZES},
                             A["variants"]["fee"]["val"]["sharpe"])
    A["counts"] = tier_counts(P, cnt, ins, val)
    return A


# ---------------------------------------------------------------- the reports

def put_section(name: str, title: str, body: str) -> None:
    """results/<name>.md: the T6b section (its title, hand-written lines, then the generated body between T6b's
    markers) kept above the file's own generated part; only the body between the markers is replaced."""
    path = dc.RESULTS / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    a, b = f"<!-- T6b: generated by lab.experiments.{NAME}, from here -->", "<!-- T6b: to here -->"
    block = f"{a}\n\n{body.rstrip()}\n\n{b}"
    if a in text and b in text:
        text = text.split(a)[0] + block + text.split(b, 1)[1]
    else:
        mk = dc.marker(name)
        above, below = text.split(mk) if mk in text else (text, "")
        text = above.rstrip() + f"\n\n## {title}\n\n{block}\n\n" + (mk + below if below else "")
    path.write_text(text, encoding="utf-8")


def _pct(v) -> str:
    return t6._pct(v)


def markdown(A: dict, about: dict) -> str:
    v = A["val"]
    md = [f"Generated {about['generated']}. Validation {A['from']} to {A['to']}, every series cut at {t6.VAL_TO}, "
          f"the lockbox not read. Costs: the USD-M taker {t5.PERP_FEE * 1e4:.0f} bps plus the cost of a market order "
          f"of the leg's notional from T4's hour nearest the fill (the latest hour of the fill's day), T5's tier on a "
          f"day without a depth file, {BEYOND * 1e4:.0f} bps beyond the hour's depth; book reweights "
          f"{t6.REWEIGHT_COST * 1e4:.0f} bps. M4's reg7n refit on the panel cut at {t6.VAL_TO} "
          f"({about['folds']}); T4's delisting table {about['delist']}. Judged at {JUDGED} USD a leg.\n",
          "| ERC (perps_neutral) | in sample Sharpe | validation Sharpe / CAGR / DD |", "|---|---|---|"]
    label = {"fee": "taker fee only", "tier": "T6's tiers (today's inputs)", **{k: f"depth, {k} a leg" for k in SIZES}}
    for k in VARIANTS:
        i, x = A["variants"][k]["is"], A["variants"][k]["val"]
        md.append(f"| {label[k]} | {i['sharpe']:.2f} | {x['sharpe']:.2f} / {_pct(x['cagr'])} / {_pct(x['max_dd'])} |")
    c = A["capacity"]
    cap = (f"below 1k a leg (the Sharpe at 1k is under {c['bar']:.2f})" if c["side"] == "below" else
           f"above 100k a leg (not measured; the Sharpe at 100k stays over {c['bar']:.2f})" if c["side"] == "above"
           else f"about {c['usd'] / 1e3:,.0f}k USD a leg (the Sharpe there {c['bar']:.2f})")
    md.append(f"\nCapacity, where the depth cost halves the fee-only validation Sharpe "
              f"({A['variants']['fee']['val']['sharpe']:.2f}): {cap}.\n")
    t = [{"candidate": k, "in sample Sharpe": f"{A['is'][k]['sharpe']:.2f}",
          "validation Sharpe / CAGR / DD": f"{A['val_all'][k]['sharpe']:.2f} / {_pct(A['val_all'][k]['cagr'])} / "
                                           f"{_pct(A['val_all'][k]['max_dd'])}"} for k in t6.CANDIDATES]
    md.append(f"At {JUDGED} a leg: validation Sharpe {v['sharpe']:.2f}, {_pct(v['cagr'])} a year, drawdown "
              f"{_pct(v['max_dd'])}; by year " + ", ".join(f"{y} {s:.2f}" for y, s in A["years"].items()) +
              f"; correlation with BTC {A['corr_btc']:+.2f}; 90 % band {A['band'][0]:.2f} to {A['band'][1]:.2f}.\n")
    md.append(dc.table(t, list(t[0])) + "\n")
    pb, cp, lk, pr = A["pbo"], A["cpcv"], A["leak"], A["paper"]
    ev = {"A1 gates": "; ".join(f"{k} {'yes' if x else 'no'}" for k, x in A["gates"].items()),
          "A2 DSR all": f"{A['dsr_all']:.3f} over {A['pool_all']['n_trials']:,} trials (noise bar "
                        f"{A['pool_all']['sr0_annual']:.2f} a year)",
          "A3 DSR family": f"{A['dsr_family']:.3f} over the hand family's {A['pool_family']['n_trials']:,} "
                           f"({A['pool_family']['sr0_annual']:.2f})",
          "A4 PBO": f"{pb['pbo']:.2f} over {pb['genomes']} candidates, {pb['combos']:,} splits" if pb else "n/a",
          "A5 CPCV": f"median {cp['median']:.2f}, 10th percentile {cp['p10']:.2f} over {cp['paths']} paths, "
                     f"{cp['variants']} near variant(s)" if cp else "n/a",
          "A6 leak": (f"low-vol weight function on PIT50: {'no leak' if lk['ok'] else 'LEAK ' + str(lk['first'])} "
                      f"({lk['runs']} runs); M4's scores and carry's xs_daily features not covered by T1"
                      if lk else "not run"),
          "A7 paper record": (f"{pr['days']} days {_pct(pr['ret'])}, percentile {_pct(pr['pct'])} of the "
                              f"validation's {pr['days']}-day returns (5 % {_pct(pr['p05'])}); sub-books " +
                              ", ".join(f"{k} {_pct(x['pct'])}" for k, x in A["paper_subs"].items())
                              if pr["days"] else "no journal")}
    md.append(dc.table([{"condition": k, "result": t6._yes(ok), "evidence": ev[k]}
                        for k, ok in A["conditions"].items()], ["condition", "result", "evidence"]) + "\n")
    t = []
    for b, r in A["counts"].items():
        row = {"book": b}
        for w, lab in (("is", "in sample"), ("val", "validation")):
            x = r[w]
            row[f"{lab}: days at the tier / with a trade, turnover share"] = (
                f"{x['tier_days']:,} / {x['trade_days']:,}, {_pct(x['tier_share'])}")
        row["validation days beyond the depth, 1k / 10k / 100k"] = " / ".join(
            f"{r['val']['beyond_days'][k]:,}" for k in SIZES)
        t.append(row)
    md.append(f"Days without a depth file (T5's tier kept, at {JUDGED}) and beyond the hour's depth "
              f"({BEYOND * 1e4:.0f} bps): a day counts when one leg traded there.\n")
    md.append(dc.table(t, list(t[0])) + "\n")
    md.append(t6._tail(A))
    md.append(f"Trials (R5's registry, before the validation numbers): {', '.join(A['trials'])}.\n")
    return "\n".join(md)


def t5_old_gaps(text: str) -> dict[str, str]:
    """T5's validation Sharpe gap against PIT20 per rule, from its generated table (section 1)."""
    out = {}
    for rule in t5.RULES:
        m = re.search(rf"^\| {re.escape(rule)} \| [^|]+ / ([+-]\d+\.\d+) \|", text, re.M)
        if m:
            out[rule] = m.group(1)
    return out


def t5_markdown(out: dict, about: dict, old: dict[str, str]) -> str:
    rows = {(r["rule"], r["universe"]): r for r in out["rows"]}
    md = [f"Generated {about['generated']}. T5 rerun with T4's delisting table ({about['rows']} rows): LAB20 through "
          f"`lab.universe.tradable`, PIT20 and PIT50 with the delisting flag; {len(out['trials'])} trials "
          f"`hand:{T5_TAG}:<rule>:<universe>`, DSR pool {out['pool']['n_trials']:,} (noise bar "
          f"{out['pool']['sr0_annual']:.2f}). LAB20 coins dropped early: {about['lab20_dropped'] or 'none'}; "
          f"PIT20 coin-days changed by the table: {about['pit20_changed']:,}.\n"]
    for g in out["gaps"]:
        r = g["rule"]
        s = " / ".join(f"{rows[(r, u)]['val']['sharpe']:.2f}" for u in t5.UNIVERSES)
        md.append(f"- **{r}**: validation Sharpe LAB20 / PIT20 / PIT50 {s}; gap against PIT20 "
                  f"{g['val_sharpe_gap_PIT20']:+.2f} (band {g['band_lo']:+.2f} to {g['band_hi']:+.2f}, material "
                  f"{'yes' if g['material'] else 'no'}; T5 without the table {old.get(r, 'n/a')}).")
    return "\n".join(md)


# ---------------------------------------------------------------- runs

def run_t5(register: bool = True) -> dict:
    from .. import report
    from .. import universe as U
    from ..collect import book_depth
    table = book_depth.read_delistings()
    P = dc.cut_panel(fc.load_panel(), t6.VAL_TO)
    vol = U.median_volume(P)
    unis = t5.universes(P, vol, table, lab_delist=True)
    out = t5.evaluate(P, unis, vol, register, tag=T5_TAG, source=PREREG)
    lab = U.mask(P, U.LAB20)
    gone = [P.names[j] for j in np.flatnonzero(lab) if not unis["LAB20"][:, j].all()]
    before = U.pit(P, 20, drop_delisting=False, vol=vol)
    about = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "rows": len(table),
             "lab20_dropped": ", ".join(gone), "pit20_changed": int((before != unis["PIT20"]).sum())}
    old = t5_old_gaps((dc.RESULTS / f"{t5.NAME}.md").read_text(encoding="utf-8"))
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "t5_latest.json").write_text(json.dumps({**out, "about": about}, indent=1, default=float), encoding="utf-8")
    put_section(t5.NAME, "T6b: with T4's delisting table", t5_markdown(out, about, old))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    register = "--no-register" not in argv
    t0 = time.time()
    if "--t5" in argv:
        out = run_t5(register)
        print(f"T5 with delistings done in {time.time() - t0:.0f} s; material: "
              f"{[g['rule'] for g in out['gaps'] if g['material']] or 'none'}")
        return 0
    from .. import report
    if "--report" in argv:                               # the section again from the last run's numbers
        out = json.loads((report.REPORTS / NAME / "latest.json").read_text(encoding="utf-8"))
        put_section(t6.NAME, "T6b: with order book depth", markdown(out["A"], out["about"]))
        return 0
    from .. import universe as U
    from ..collect import book_depth
    from ..data import ROOT
    from ..leak import checks
    delist = book_depth.read_delistings()
    delist = delist if len(delist) else None
    fh = fill_hours()
    xb = xs_books(fh, "--refit" in argv)
    print(f"xs books ready, {time.time() - t0:.0f} s", flush=True)
    P = dc.cut_panel(fc.load_panel(), t6.VAL_TO)
    vol = U.median_volume(P)
    lv = lowvol_books(P, vol, fh, delist)
    print(f"low-vol books ready, {time.time() - t0:.0f} s", flush=True)
    by = {v: nets(P, xb, lv, v) for v in VARIANTS}
    cnt = {c: nets(P, xb, lv, c) for c in COUNTERS}
    del xb, lv
    leak = checks.book("perps_neutral lowvol PIT50", lambda Q: t6.lowvol_weights(Q, delist), P)
    paper = t6.read_journal(ROOT / "paper" / "perps_neutral" / "journal.csv")
    A = lead_a(P, by, cnt, paper, leak, register)
    about = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "folds": "xs_daily's quarterly walk-forward from 2022, embargo 8 days",
             "delist": "present, the low-vol leg's PIT50 drops a coin from its announcement day"
                       if delist is not None else "not present"}
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps({"A": A, "about": about}, indent=1, default=float), encoding="utf-8")
    put_section(t6.NAME, "T6b: with order book depth", markdown(A, about))
    print(f"done in {time.time() - t0:.0f} s; A at {JUDGED} validation {A['validation']} step {A['step']}, "
          f"capacity {A['capacity']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
