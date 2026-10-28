"""T6: the lab's two leads to the end, an honest yes or no for each.

Pre-registered in results/two_leads_t6_prereg.md; results in results/two_leads_t6.md.

    PYTHIA_CACHE=<the 2026-10-07 xs_daily cache> PYTHIA_AGENT_OUT=<panel cache> \
        flock <heavy lock> python -m lab.experiments.two_leads_t6

Lead A: the perps_neutral portfolio (M4 reg7n, funding carry F7, low-vol beta-neutral, ERC
monthly) filled one close late at the costs of its era (USD-M taker plus T5's half-spread
tiers on each coin's volume that day, T4's 10k order cost where its depth files exist), the
low-vol leg on T5's PIT50. Lead B: F2's survivor 07493e8a8adb late through R10's wallets.
Each: its registered gates, the DSR over R5's registry and its family, PBO, CPCV paths, T1's
leak harness, the paper record against the validated distribution. Every series is cut at
2026-06-30; the lockbox is never read here, a validation pass only queues the look for
run.lockbox_step. Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics
from . import director_common as dc
from . import fam_common as fc
from . import pit_universe_t5 as t5

NAME = "two_leads_t6"
IS_FROM_A, IS_FROM_B, IS_TO = "2022-03-01", "2020-08-01", "2023-12-31"
VAL_FROM, VAL_TO = "2024-01-01", "2026-06-30"
YEARS = (2024, 2025, 2026)
BOOKS, METHODS, PICK = ("M4", "Carry", "LowVol"), ("EW", "IV", "ERC"), "ERC"
CANDIDATES = BOOKS + METHODS
REWEIGHT_COST = 0.0010                  # the study's judged cost, on book reweights only
FLAT = 0.0010                           # the published pipeline's cost, for the check on time
GATE_SHARPE, GATE_CORR, GATE_YEARS = 0.5, 0.3, 2
DSR_PASS, PBO_PASS, PAPER_Q = 0.95, 0.5, 0.05
LADDER_PAPER_DAYS = 90
F2_KEY = "07493e8a8adb"
PAPER_FROM = "2026-10-22"               # the journal's first marked day (2026-10-21 is the start)
DAY_US = fc.DAY_US


# ---------------------------------------------------------------- costs of their era

def depth_costs(days: np.ndarray, coins: list[str], table) -> np.ndarray | None:
    """(T, N) T4's daily mean cost of a 10k USD market order as a fraction (NaN where there is none), from a frame
    (ts_us the UTC day, asset, cost10k in bps). None without a row."""
    if table is None or not len(table):
        return None
    out = np.full((len(days), len(coins)), np.nan)
    ci = {c: j for j, c in enumerate(coins)}
    ts = table["ts_us"].to_numpy() // DAY_US * DAY_US
    t = np.searchsorted(days, ts)
    for k, (a, c) in enumerate(zip(table["asset"].to_list(), table["cost10k"].to_numpy())):
        j = ci.get(a)
        if j is not None and t[k] < len(days) and days[t[k]] == ts[k] and np.isfinite(c):
            out[t[k], j] = c / 1e4
    return out if np.isfinite(out).any() else None


def era_cost(vol: np.ndarray, depth: np.ndarray | None = None) -> np.ndarray:
    """(T, N) the perp cost per unit of one-way turnover: the taker fee plus T4's 10k order cost where it exists,
    else T5's half-spread tier of the coin's volume that day."""
    c = t5.era_cost(vol, True)
    return c if depth is None else np.where(np.isfinite(depth), t5.PERP_FEE + depth, c)


def load_depth():
    from ..features import book
    try:
        return book.book_table("1d", None)
    except Exception:           # noqa: BLE001 (no depth files: the tiers, said so)
        return None


# ---------------------------------------------------------------- lead A: the books

def cut_matrices(M: dict, last_day: str) -> dict:
    """xs_daily's matrices up to and including last_day (every array with a row per day sliced)."""
    keep = int(np.searchsorted(M["days"], dc.us(last_day), side="right"))
    T = len(M["days"])
    return {k: v[:keep] if isinstance(v, np.ndarray) and v.ndim >= 1 and len(v) == T and k != "syms" else v
            for k, v in M.items()}


def xs_cost(M: dict, depth_table=None) -> np.ndarray:
    from . import perps_common as pc
    coins = [pc.coin_of(s) for s in M["syms"]]
    return era_cost(M["perp_adv28"], depth_costs(M["days"], coins, depth_table))


def xs_net(b: tuple) -> tuple[np.ndarray, np.ndarray]:
    """(net, turnover) of xs_daily.book's output with the cost matrix (the turnover returned is the cost)."""
    g, cost, fu, _ = b
    return g + fu - cost, cost


def xs_books(depth_table=None) -> dict:
    """M4 reg7n and funding carry's F7 on the 2026-10-07 cache, cut at VAL_TO: late at era costs, and on time at
    the published 10 bps (the check). {name: (decision days, net, turnover)}."""
    import polars as pl
    from . import funding_carry as fcy
    from . import xs_daily as xs
    P = xs.build_panel()
    P, _ = xs.add_net_labels(P)
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    S = pl.read_parquet(xs.CACHE / "xs_daily_scores_net.parquet").select("day", "symbol", "reg7n")
    E = E.join(S, on=["day", "symbol"], how="left").filter(pl.col("day") >= xs.FIRST_TEST)
    M = cut_matrices(xs.matrices(E, P.filter(pl.col("day") >= xs.FIRST_TEST), ["reg7n"]), VAL_TO)
    del E, S, P
    C = xs_cost(M, depth_table)
    out = {"M4": (M["days"], *xs_net(xs.book_buffer(M, fcy.late(M["reg7n"]), 10, 0.5, 100, C=C)))}
    g, tu, fu, _ = xs.book_buffer(M, M["reg7n"], 10, 0.5, 100)
    out["M4 on time"] = (M["days"], g + fu - FLAT * tu, tu)
    del M
    F, _ = fcy.load()
    F = cut_matrices(F, VAL_TO)
    C = xs_cost(F, depth_table)
    out["Carry"] = (F["days"], *xs_net(xs.book(F, fcy.late(F["s_F7"]), 10, 3, fcy.N_LIQUID, True, C=C)))
    g, tu, fu, _ = xs.book(F, F["s_F7"], 10, 3, fcy.N_LIQUID, True)
    out["Carry on time"] = (F["days"], g + fu - FLAT * tu, tu)
    return out


def lowvol_weights(P: fc.Panel, table=None, vol=None) -> np.ndarray:
    """perps_neutral's low-vol leg on T5's PIT50 (the weight function T1 checks)."""
    from .fam_lowvol import weights
    from .. import universe as U
    return weights(t5.on(P, U.pit(P, 50, table=table, vol=vol)), "vol 60d", 50, "beta-neutral BAB")


def lowvol_books(P: fc.Panel, vol: np.ndarray, delist=None, depth_table=None) -> dict:
    """The low-vol leg on PIT50 late at era costs (T5's run_rule), and on time at 10 bps on the panel's top 50 (the
    published book, the check). {name: (net, turnover on its return day)}."""
    from .. import universe as U
    from .perps_neutral_portfolio import lowvol_book
    coins = [n.removesuffix("USDT") if "~" not in n else "" for n in P.names]
    C = era_cost(vol, depth_costs(P.days, coins, depth_table))
    uni = U.pit(P, 50, table=delist, vol=vol)
    net = t5.run_rule(P, "lowvol", uni, 50, C)
    live = np.arange(P.T) > 100
    o = lowvol_book(P)["perp"]
    tv = np.r_[0.0, o["turnover"][:-1]]
    return {"LowVol": (np.where(live, net, np.nan), np.full(P.T, np.nan)),
            "LowVol on time": (np.where(live, o["gross"] - FLAT * tv, np.nan), np.where(live, tv, np.nan))}


def calendar(P: fc.Panel, xb: dict, lv: dict) -> tuple[dict, dict]:
    """Every book's net and turnover on the panel's return days (an xs decision of day d books on d+1)."""
    from .perps_neutral_portfolio import on_calendar
    net, tov = {}, {}
    for k, (d, n_, tu) in xb.items():
        net[k], tov[k] = on_calendar(P.days, d, n_, 1), on_calendar(P.days, d, tu, 1)
    for k, (n_, tu) in lv.items():
        net[k], tov[k] = n_, tu
    return net, tov


def combos(P: fc.Panel, net: dict, tov: dict, books: tuple[str, ...], start: int) -> dict[str, np.ndarray]:
    from .perps_neutral_portfolio import combine
    R = np.column_stack([net[b] for b in books])
    TV = np.nan_to_num(np.column_stack([tov[b] for b in books]))
    return {m: combine(R, TV, P.days, m, REWEIGHT_COST, start)["net"] for m in METHODS}


# ---------------------------------------------------------------- measuring

def stats_of(x: np.ndarray) -> dict:
    p = fc.perf(x)
    return {"sharpe": p["sharpe"], "cagr": p["cagr"], "max_dd": p["max_dd"], "days": p["days"]}


def needed_sharpe(x: np.ndarray, pool: dict, bar: float = DSR_PASS) -> float:
    """The annual Sharpe a series of this length, skew and kurtosis needs for DSR `bar` on this pool."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 3 or x.std() == 0:
        return float("nan")
    from scipy import stats
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    sr0 = metrics.expected_max_sharpe(pool["var"], pool["n_trials"])
    s = sr0
    for _ in range(50):
        s = sr0 + stats.norm.ppf(bar) * math.sqrt(max(1 - sk * s + (ku - 1) / 4 * s * s, 1e-12)) / math.sqrt(len(x) - 1)
    return float(s * math.sqrt(365))


def rolling_compound(x: np.ndarray, n: int) -> np.ndarray:
    """Every n-day compounded return of x (NaN days dropped)."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if n < 1 or len(x) < n:
        return np.zeros(0)
    c = np.r_[0.0, np.cumsum(np.log1p(x))]
    return np.expm1(c[n:] - c[:-n])


def paper_rank(paper: np.ndarray, val: np.ndarray) -> dict:
    """The paper record's compounded return against the validation series' rolling returns over as many days:
    its percentile (the share of windows below it) and the 5 % and 95 % of those windows."""
    paper = np.asarray(paper, dtype=float)
    n = len(paper)
    w = rolling_compound(val, n)
    r = float(np.prod(1 + paper) - 1) if n else float("nan")
    if not len(w):
        return {"days": n, "ret": r, "pct": None, "p05": None, "p95": None, "passes": False}
    p05 = float(np.percentile(w, PAPER_Q * 100))
    return {"days": n, "ret": r, "pct": float((w < r).mean()), "p05": p05, "p95": float(np.percentile(w, 95)),
            "passes": r >= p05}


def read_journal(path: Path, since: str = PAPER_FROM) -> dict[str, np.ndarray]:
    """The perps_neutral journal's daily returns from `since`: the book's and each sub-book's (fractions)."""
    out: dict[str, list] = {k: [] for k in ("book",) + BOOKS}
    days: list[str] = []
    if not path.exists():
        return {"days": np.array([]), **{k: np.array([]) for k in out}}
    with path.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["date"] < since:
                continue
            days.append(r["date"])
            out["book"].append(float(r["ret_pct"]) / 100)
            for b in BOOKS:
                out[b].append(float(r[f"ret_{b}_pct"]) / 100)
    return {"days": np.array(days), **{k: np.array(v) for k, v in out.items()}}


def ladder(gates: bool, validation: bool, lockbox: bool = False, paper_days: int = 0, paper_ok: bool = False) -> int:
    """The provisional ladder (results/two_leads_t6_prereg.md): 0 a backtest, 1 its gates late at era costs,
    2 validation passes, 3 the lockbox look passed, 4 plus 90 paper days in the band; 5 and 6 are the owner's."""
    step = 0
    for ok in (gates, validation, lockbox, paper_ok and paper_days >= LADDER_PAPER_DAYS):
        if not ok:
            break
        step += 1
    return step


def lockbox_line(validation: bool, lead: str) -> str:
    if not validation:
        return "no look (validation fails)"
    if lead == "A":
        return "look due: run.lockbox_step has no path for a hand book yet (its own brief); not looked"
    return "look due: through F2's held-back line with its excess passed (small.lockbox_step); not looked here"


def trial(id_: str, family: str, is_sharpe: float) -> dict:
    return {"id": id_, "family": family, "n": 1, "sharpe": float(is_sharpe), "source": "results/two_leads_t6_prereg.md"}


def pools(trials: list[dict], family: str) -> tuple[dict, dict]:
    extra = dc.ledger_trials() + trials
    return metrics.trial_pool(extra=extra), metrics.trial_pool(family, extra=extra)


# ---------------------------------------------------------------- lead A

def lead_a(P: fc.Panel, net: dict, paper: dict, leak: dict | None, register: bool = True, log=print) -> dict:
    """Lead A's conditions on the books' late era-cost series on the panel's calendar (net has BOOKS and, for the
    check, '<book> on time')."""
    days = P.days
    years = dc.years_of(days)
    common = np.all([np.isfinite(net[b]) for b in BOOKS], axis=0)
    start = int(np.flatnonzero(common)[0])
    ins = common & (days >= dc.us(IS_FROM_A)) & (days <= dc.us(IS_TO))
    val = common & (days >= dc.us(VAL_FROM)) & (days <= dc.us(VAL_TO))
    s = {b: net[b] for b in BOOKS}
    s.update(combos(P, net, {b: np.zeros(P.T) for b in BOOKS}, BOOKS, start))
    trials = [trial(f"hand:t6:a:{k}", "hand", stats_of(s[k][ins])["sharpe"]) for k in CANDIDATES]
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  lead A: in sample " + ", ".join(f"{t['id'].split(':')[-1]} {t['sharpe']:.2f}" for t in trials))
    p_all, p_fam = pools(trials, "hand")
    x = s[PICK][val]
    lo, hi, _ = dc.boot_band(x)
    btc = np.nan_to_num(P.ret[:, P.btc])
    v = stats_of(x)
    yrs = {y: dc.sharpe(s[PICK][val & (years == y)]) for y in YEARS}
    corr = float(np.corrcoef(x, btc[val])[0, 1])
    on_time = {b: net.get(f"{b} on time") for b in BOOKS}
    check = None
    if all(y is not None for y in on_time.values()):
        ok = np.all([np.isfinite(on_time[b]) for b in BOOKS], axis=0)
        st = int(np.flatnonzero(ok)[0])
        check = dc.sharpe(combos(P, on_time, {b: np.zeros(P.T) for b in BOOKS}, BOOKS, st)[PICK][val & ok])
    both = (ins | val) & common
    pbo = metrics.cscv(np.column_stack([np.nan_to_num(s[k][both]) for k in CANDIDATES]))
    from ..factory import evaluate as ev
    cp = ev.cpcv(s[PICK][ins], {k: s[k][ins] for k in CANDIDATES if k != PICK}, PICK)
    g1 = {"Sharpe above 0.5": v["sharpe"] > GATE_SHARPE,
          "positive in 2 of 2024, 2025, 2026": sum(yrs[y] > 0 for y in YEARS) >= GATE_YEARS,
          "bootstrap 5 % above 0": lo > 0, "correlation with BTC within +-0.3": abs(corr) < GATE_CORR}
    cond = {"A1 gates": all(g1.values()),
            "A2 DSR all": metrics.dsr(x, p_all) >= DSR_PASS,
            "A3 DSR family": metrics.dsr(x, p_fam) >= DSR_PASS,
            "A4 PBO": pbo is not None and pbo["pbo"] < PBO_PASS,
            "A5 CPCV": cp is not None and cp["p10"] > 0,
            "A6 leak": bool(leak and leak.get("ok"))}
    validation = all(cond.values())
    pr = paper_rank(paper.get("book", np.zeros(0)), x)
    subs = {b: paper_rank(paper.get(b, np.zeros(0)), s[b][val]) for b in BOOKS}
    cond["A7 paper record"] = pr["passes"]
    return {"lead": "A", "val": v, "is": {k: stats_of(s[k][ins]) for k in CANDIDATES},
            "val_all": {k: stats_of(s[k][val]) for k in CANDIDATES}, "years": yrs, "corr_btc": corr,
            "band": [lo, hi], "gates": g1, "dsr_all": metrics.dsr(x, p_all), "dsr_family": metrics.dsr(x, p_fam),
            "pool_all": _pool(p_all), "pool_family": _pool(p_fam), "pbo": pbo, "cpcv": cp,
            "leak": _leak(leak), "paper": pr, "paper_subs": subs, "conditions": cond, "validation": validation,
            "lockbox": lockbox_line(validation, "A"), "check_on_time_10bps": check,
            "needed_sharpe": {"all": needed_sharpe(x, p_all), "family": needed_sharpe(x, p_fam)},
            "step": ladder(cond["A1 gates"], validation, False, pr["days"], pr["passes"]),
            "from": dc.day_str(days[val][0]), "to": dc.day_str(days[val][-1]),
            "trials": [t["id"] for t in trials]}


def _pool(p: dict) -> dict:
    return {"n_trials": p["n_trials"], "sr0_annual": p["sr0_annual"]}


def _leak(r: dict | None) -> dict | None:
    if r is None:
        return None
    return {"name": r.get("name"), "ok": r.get("ok"), "runs": r.get("runs"), "first": r.get("first"),
            "error": r.get("error")}


# ---------------------------------------------------------------- lead B

def f2_pbo() -> dict | None:
    """F2's family PBO from its newest nightly run (read, not recomputed)."""
    from ..factory import ledger as lg
    d = lg.small_dir() / "runs"
    for p in sorted(d.glob("*.json"), reverse=True) if d.is_dir() else []:
        try:
            fam = (json.loads(p.read_text(encoding="utf-8")).get("night") or {}).get("family")
        except (OSError, ValueError):
            continue
        if fam and fam.get("pbo") is not None:
            return {"run": p.stem, "pbo": float(fam["pbo"]), "genomes": fam.get("genomes")}
    return None


def lead_b(mk, register: bool = True, leak: dict | None = None, family: dict | None = None, log=print) -> dict:
    """Lead B through R10's wallets, late, at 40 and 100 EUR; mk is smallaccount_r10.load()'s market."""
    from ..factory import small as f2
    from . import smallaccount_r10 as r10
    g = next(x["genome"] for x in mk.f2 if x["key"] == F2_KEY)
    days = mk.c.days
    memo: dict = {}
    ins = {cap: r10.measure(r10.run_f2(mk, g, cap, True, *r10.window(days, "is"), memo=memo), cap)
           for cap in r10.CAPITALS}
    t0, t1 = f2.windows(mk.c)["is"]
    cx = r10.measure(r10.run_f2(mk, g, r10.MAIN, True, t0, t1, memo=memo), r10.MAIN)
    trials = [trial(f"small:t6:{F2_KEY}:late@{cap:g}", "small", ins[cap]["sharpe"]) for cap in r10.CAPITALS]
    trials.append(trial(f"small:t6:{F2_KEY}:cpcv", "small", cx["sharpe"]))
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  lead B: in sample " + ", ".join(f"{t['id'].split(':')[-1]} {t['sharpe']:.2f}" for t in trials))
    p_all, p_fam = pools(trials, "small")
    rows, gates = {}, {}
    for cap in r10.CAPITALS:
        b = r10.measure(r10.benchmarks(mk, cap, "val", on_ctx=True)[r10.UCITS], cap)
        m = r10.measure(r10.run_f2(mk, g, cap, True, *r10.window(days, "val"), memo=memo), cap)
        ex = r10.excess(m.pop("returns"), b.pop("returns"))
        m.update({"excess_sharpe": float(ex.mean() / ex.std() * math.sqrt(365)) if ex.std() > 0 else 0.0,
                  "dsr_all": metrics.dsr(ex, p_all), "dsr_family": metrics.dsr(ex, p_fam)})
        if cap == r10.MAIN:
            m["needed_sharpe"] = {"all": needed_sharpe(ex, p_all), "family": needed_sharpe(ex, p_fam)}
        rows[cap] = {"wallet": m, "bench": b}
        gates[f"{cap:g} EUR: DD < 20 %"] = m["max_dd"] < r10.SAFE_DD
        gates[f"{cap:g} EUR: CAGR >= fund - 1 pt"] = m["cagr"] >= b["cagr"] - r10.MATCH_SLACK
    from ..factory import evaluate as ev
    cp = ev.cpcv(cx["returns"], family, F2_KEY) if family is not None else None
    pbo = f2_pbo()
    main = rows[r10.MAIN]["wallet"]
    shadow = (f2.shadow_dir() / f"{F2_KEY}.json").exists()
    cond = {"B1 gates": all(gates.values()), "B2 DSR all": main["dsr_all"] >= DSR_PASS,
            "B3 DSR family": main["dsr_family"] >= DSR_PASS, "B4 PBO": pbo is not None and pbo["pbo"] < PBO_PASS,
            "B5 CPCV": cp is not None and cp["p10"] > 0, "B6 leak": bool(leak and leak.get("ok"))}
    validation = all(cond.values())
    cond["B7 paper record"] = False                      # no shadow wallet ran (shadow file below for the record)
    return {"lead": "B", "rows": {f"{k:g}": v for k, v in rows.items()},
            "is": {f"{k:g}": {f: v[f] for f in ("cagr", "max_dd", "sharpe")} for k, v in ins.items()},
            "gates": gates, "pool_all": _pool(p_all), "pool_family": _pool(p_fam), "pbo": pbo, "cpcv": cp,
            "leak": _leak(leak), "shadow_file": shadow, "conditions": cond, "validation": validation,
            "lockbox": lockbox_line(validation, "B"), "step": ladder(cond["B1 gates"], validation),
            "trials": [t["id"] for t in trials]}


# ---------------------------------------------------------------- the report

def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f} %"


def _yes(ok: bool) -> str:
    return "pass" if ok else "fail"


def markdown(out: dict) -> str:
    a, b = out["A"], out["B"]
    md = [f"Generated {out['generated']}. Validation {VAL_FROM} to {VAL_TO}; every series cut at {VAL_TO}, the "
          f"lockbox not read. Costs: {out['costs']}.\n",
          "## Lead A: the perps_neutral portfolio (ERC of M4, carry, low vol), late at the costs of its era\n"]
    v = a["val"]
    md.append(f"Validation ({a['from']} to {a['to']}): Sharpe {v['sharpe']:.2f}, {_pct(v['cagr'])} a year, drawdown "
              f"{_pct(v['max_dd'])}; by year " + ", ".join(f"{y} {s:.2f}" for y, s in a["years"].items()) +
              f"; correlation with BTC {a['corr_btc']:+.2f}; 90 % band {a['band'][0]:.2f} to {a['band'][1]:.2f}." +
              (f" Check, the published pipeline on time at 10 bps over the same days: {a['check_on_time_10bps']:.2f} "
               "(published 2.47 to 2026-09-29)." if a["check_on_time_10bps"] is not None else "") + "\n")
    t = [{"candidate": k, "in sample Sharpe": f"{a['is'][k]['sharpe']:.2f}",
          "validation Sharpe / CAGR / DD": f"{a['val_all'][k]['sharpe']:.2f} / {_pct(a['val_all'][k]['cagr'])} / "
                                           f"{_pct(a['val_all'][k]['max_dd'])}"} for k in CANDIDATES]
    md.append(dc.table(t, list(t[0])) + "\n")
    pb, cp, lk, pr = a["pbo"], a["cpcv"], a["leak"], a["paper"]
    ev = {"A1 gates": "; ".join(f"{k} {'yes' if x else 'no'}" for k, x in a["gates"].items()),
          "A2 DSR all": f"{a['dsr_all']:.3f} over {a['pool_all']['n_trials']:,} trials (noise bar "
                        f"{a['pool_all']['sr0_annual']:.2f} a year)",
          "A3 DSR family": f"{a['dsr_family']:.3f} over the hand family's {a['pool_family']['n_trials']:,} "
                           f"({a['pool_family']['sr0_annual']:.2f})",
          "A4 PBO": f"{pb['pbo']:.2f} over {pb['genomes']} candidates, {pb['combos']:,} splits" if pb else "n/a",
          "A5 CPCV": f"median {cp['median']:.2f}, 10th percentile {cp['p10']:.2f} over {cp['paths']} paths, "
                     f"{cp['variants']} near variant(s)" if cp else "n/a",
          "A6 leak": (f"low-vol weight function on PIT50: {'no leak' if lk['ok'] else 'LEAK ' + str(lk['first'])} "
                      f"({lk['runs']} runs); M4's cached scores and carry's xs_daily features not covered by T1"
                      if lk else "not run"),
          "A7 paper record": (f"{pr['days']} days {_pct(pr['ret'])}, percentile {_pct(pr['pct'])} of the "
                              f"validation's {pr['days']}-day returns (5 % {_pct(pr['p05'])}, 95 % {_pct(pr['p95'])}); "
                              "sub-books " + ", ".join(f"{k} {_pct(x['pct'])}" for k, x in a["paper_subs"].items())
                              if pr["days"] else "no journal")}
    md.append(dc.table([{"condition": k, "result": _yes(ok), "evidence": ev[k]} for k, ok in a["conditions"].items()],
                       ["condition", "result", "evidence"]) + "\n")
    md.append(_tail(a))
    md.append("## Lead B: F2's survivor 07493e8a8adb (Donchian 100/50 on the six), late through R10's wallets\n")
    t = []
    for cap, r in b["rows"].items():
        w, f = r["wallet"], r["bench"]
        t.append({"EUR": cap, "late CAGR / DD / Sharpe": f"{_pct(w['cagr'])} / {_pct(w['max_dd'])} / {w['sharpe']:.2f}",
                  "SXR8.DE CAGR / DD / Sharpe": f"{_pct(f['cagr'])} / {_pct(f['max_dd'])} / {f['sharpe']:.2f}",
                  "excess Sharpe": f"{w['excess_sharpe']:.2f}",
                  "DSR all / small": f"{w['dsr_all']:.3f} / {w['dsr_family']:.3f}",
                  "in sample Sharpe": f"{b['is'][cap]['sharpe']:.2f}"})
    md.append(dc.table(t, list(t[0])) + "\n")
    pb, cp, lk = b["pbo"], b["cpcv"], b["leak"]
    main = b["rows"]["40"]["wallet"]
    ev = {"B1 gates": "; ".join(f"{k} {'yes' if x else 'no'}" for k, x in b["gates"].items()),
          "B2 DSR all": f"{main['dsr_all']:.3f} of the 40 EUR excess over {b['pool_all']['n_trials']:,} trials",
          "B3 DSR family": f"{main['dsr_family']:.3f} over the small family's {b['pool_family']['n_trials']:,} "
                           f"({b['pool_family']['sr0_annual']:.2f} a year)",
          "B4 PBO": f"{pb['pbo']:.2f} over F2's {pb['genomes']} genomes (run {pb['run']})" if pb else "no F2 run",
          "B5 CPCV": f"median {cp['median']:.2f}, 10th percentile {cp['p10']:.2f} over {cp['paths']} paths, "
                     f"{cp['variants']} near variant(s)" if cp else "n/a",
          "B6 leak": (f"{'no leak' if lk['ok'] else 'LEAK ' + str(lk['first'])} ({lk['runs']} runs)" if lk
                      else "not run"),
          "B7 paper record": "none: F2 lost the survivor before a shadow wallet ran" +
                             (" (a shadow file exists)" if b["shadow_file"] else "")}
    md.append(dc.table([{"condition": k, "result": _yes(ok), "evidence": ev[k]} for k, ok in b["conditions"].items()],
                       ["condition", "result", "evidence"]) + "\n")
    md.append("Point in time: the six assets cannot be chosen point in time; T5's rule on coins made 0.98 on today's "
              "20 and 0.10 on PIT20 in validation (`results/pit_universe_t5.md`, not rerun).\n")
    md.append(_tail(b, main["needed_sharpe"], "validation excess Sharpe over SXR8 at 40 EUR"))
    md.append(f"Trials (R5's registry, before the validation numbers): {', '.join(a['trials'] + b['trials'])}.\n")
    return "\n".join(md) + "\n"


def _tail(x: dict, need: dict | None = None, what: str = "validation Sharpe") -> str:
    need = need or x["needed_sharpe"]
    return (f"**Validation {'passes' if x['validation'] else 'fails'}.** Lockbox: {x['lockbox']}. Step on the "
            f"provisional ladder: {x['step']}. The DSR bar on this pool needs a {what} of about "
            f"{need['all']:.2f} (all) / {need['family']:.2f} (family) on as many days.\n")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    register = "--no-register" not in argv
    t0 = time.time()
    from .. import universe as U
    from ..collect import book_depth
    from ..data import ROOT
    from ..leak import checks
    depth = load_depth()
    delist = book_depth.read_delistings()
    delist = delist if len(delist) else None
    P = dc.cut_panel(fc.load_panel(), VAL_TO)
    vol = U.median_volume(P)
    lv = lowvol_books(P, vol, delist, depth)
    xb = xs_books(depth)
    print(f"lead A books ready, {time.time() - t0:.0f} s", flush=True)
    net, _ = calendar(P, xb, lv)
    leak = checks.book("perps_neutral lowvol PIT50", lambda Q: lowvol_weights(Q, delist), P)
    paper = read_journal(ROOT / "paper" / "perps_neutral" / "journal.csv")
    A = lead_a(P, net, paper, leak, register)
    del P, net, lv, xb
    from ..factory import small as f2
    from . import smallaccount_r10 as r10
    mk = r10.load()
    g = next(x["genome"] for x in mk.f2 if x["key"] == F2_KEY)
    fam = f2.family_series(mk.c, f2.venue(mk.v2_today), f2.Ledger().rows, [])
    B = lead_b(mk, register, checks.genome(mk.c, g, small=True), fam)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "A": A, "B": B,
           "costs": ("T4's depth where present, else " if depth is not None and len(depth) else
                     "no T4 depth file on the data folder, so ") +
                    f"the USD-M taker {t5.PERP_FEE * 1e4:.0f} bps plus T5's half-spread tiers (1 to 50 bps by the "
                    f"coin's volume that day) for every perp leg, book reweights {REWEIGHT_COST * 1e4:.0f} bps; "
                    f"T4's delisting table {'present' if delist is not None else 'not present'}; lead B R10's "
                    "costs of their era", "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), "# T6: the two leads to the end\n")
    print(f"done in {out['seconds']} s; A validation {A['validation']} step {A['step']}, "
          f"B validation {B['validation']} step {B['step']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
