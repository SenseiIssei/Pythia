"""S1w: the small-account paper books traded weekly, with a no-trade band, at each path's honest costs.

Pre-registered in results/smallaccount_weekly_prereg.md; results in results/smallaccount_weekly.md.

    python -m lab.experiments.smallaccount_weekly      the study (run it under the heavy lock)

The four books of lab.paper.smallaccount (S1's small50_tsmom1 and small100_breakout_sol3, S2's small40_spy_trend
and small40_vol_target), each as it runs, traded only at Wednesday's close (`weekly`, the day S1's weekly cadence
and S2's weekly rules use), and weekly with a band (`weekly_band`): an asset whose target differs from its weight
now by less than BAND of the trading equity is not traded and keeps its last decision; an exit always trades.
Costs are R10's (lab.experiments.smallaccount_r10): each path's quote ladder and network fee only from the day the
asset could be swapped on chain, Kraken before; the wallet in USDC at the ECB's EUR/USD of the day; the way in and
back. In sample 2020-08-01 to 2023-12-31, validation 2024-01-01 to 2026-06-30 (R6; the lockbox is never read), on
time and one close late. Every new variant is one trial of R5's registry (small family), registered with its late
in-sample Sharpe before any validation number. Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import fam_common as fc
from . import smallaccount as s1
from . import smallaccount_r10 as r10
from . import smallaccount_s2 as s2

NAME = "smallaccount_weekly"
RESULTS = s1.RESULTS
SOURCE = "results/smallaccount_weekly_prereg.md"
BAND = 0.10                         # the no-trade band, of the wallet's trading equity
EVERY = 7                           # s1.rebalance_day(day, 7): days since 2020-01-01 (a Wednesday) modulo 7
SHARPE_SLACK, CAGR_SLACK = 0.10, 0.01
FOLLOW = "weekly_band"
BOOKS = {
    "small50_tsmom1": {"study": "S1", "rule": "tsmom1", "capital": 50.0, "cadence": "daily"},
    "small100_breakout_sol3": {"study": "S1", "rule": "breakout_sol3", "capital": 100.0, "cadence": "daily"},
    "small40_spy_trend": {"study": "S2", "rule": "spy_trend", "capital": 40.0, "cadence": "daily"},
    "small40_vol_target": {"study": "S2", "rule": "vol_target", "capital": 40.0, "cadence": "weekly"},
}
VARIANTS = ("as_run", "weekly", "weekly_band")


def variants(book: str) -> list[str]:
    """A book already weekly has no `weekly` of its own: it is its as run."""
    return [v for v in VARIANTS if not (v == "weekly" and BOOKS[book]["cadence"] == "weekly")]


def weekday(days_us: np.ndarray) -> np.ndarray:
    """The closes a weekly variant trades at: Wednesday's."""
    return np.array([s1.rebalance_day(d, EVERY) for d in days_us], dtype=bool)


def trial(book: str, variant: str, is_sharpe: float) -> dict:
    return {"id": f"small:s1w:{book}:{variant}", "family": "small", "n": 1, "sharpe": float(is_sharpe),
            "source": SOURCE}


# ---------------------------------------------------------------- the wallet with a band

def banded(w: s1.Wallet, targets: dict, prices: dict, band: float) -> dict:
    """The targets the band lets through: those at least `band` of the trading equity away from the asset's weight
    now, and every exit (a target of 0 for an asset held). The others are left out, so the wallet keeps their last
    decision and looks again at the next rebalance."""
    if band <= 0:
        return dict(targets)
    eq = w.trade_equity(prices)
    out = {}
    for k, tgt in targets.items():
        p = prices.get(k, 0.0)
        if not (p > 0 and eq > 0):
            out[k] = tgt                    # s1.rebalance skips it anyway
            continue
        have = w.units.get(k, 0.0) * p / eq
        if (tgt == 0 and have > 0) or abs(tgt - have) >= band:
            out[k] = tgt
    return out


def simulate(px: np.ndarray, keys: list[str], W: np.ndarray, due: np.ndarray, sol: np.ndarray, venue: s1.Venue,
             capital: float, t0: int, t1: int, slots: int, days: np.ndarray, band: float = 0.0) -> dict:
    """S2's wallet loop (lab.experiments.smallaccount_s2.simulate, without re-weights) with the band: from the
    close of t0 (all cash, the venue's setup paid, a first trade) to the close of t1, trading on due closes.
    Adds per close the amount traded and the costs paid."""
    w = s1.Wallet(cash=capital)
    venue.at(days[t0])
    idle, once = venue.setup(capital, slots, sol[t0] or 100.0)
    w.cash -= idle + once
    w.idle, w.costs = idle, once
    n = t1 - t0 + 1
    eq, traded, paid = np.zeros(n), np.zeros(n), np.zeros(n)
    prices: dict = {}
    for i, t in enumerate(range(t0, t1 + 1)):
        venue.at(days[t])
        prices = {k: float(px[t, j]) for j, k in enumerate(keys) if np.isfinite(px[t, j]) and px[t, j] > 0}
        if (due[t] or t == t0) and np.isfinite(W[t]).all():
            tg = {k: float(W[t, j]) for j, k in enumerate(keys)}
            fills = s1.rebalance(w, banded(w, tg, prices, band), prices, venue, sol[t])
            traded[i] = sum(f["eur"] for f in fills)
            paid[i] = sum(f["cost"] for f in fills)
        eq[i] = w.value(prices)
    return {"equity": eq, "costs": w.costs, "orders": w.orders, "skipped": w.skipped, "dust": w.dust,
            "end_held": s1.held_at_end(w, prices), "traded": traded, "paid": paid, "setup": once}


# ---------------------------------------------------------------- the books' inputs

def s1_inputs(P: fc.Panel, rule: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    """An S1 book's (coins, USD closes, targets held at each close) on the panel: its weight matrix filled
    forward, a reused ticker's old segment left out (no venue lists it, S1's wallet holds it as cash)."""
    key, n = r10.S1_RULES[rule]
    Wp = s1.ffill(s1.candidate(P, key, n))
    cols = [j for j in np.flatnonzero(np.abs(Wp).sum(0) > 0) if "~" not in P.names[j]]
    return [fc.base_of(P.names[j]) for j in cols], P.px[:, cols], Wp[:, cols]


def sol_usd(P: fc.Panel) -> np.ndarray:
    return np.nan_to_num(P.px[:, P.col("SOLUSDT")], nan=0.0) if "SOLUSDT" in P.names else np.full(P.T, 100.0)


def inputs(mk: r10.Market, book: str, memo: dict) -> dict:
    """keys, px (USD), W, the as-run due closes, slots and the two venues of a book."""
    b = BOOKS[book]
    if ("in", book) in memo:
        return memo[("in", book)]
    P = mk.P
    if b["study"] == "S1":
        keys, px, W = s1_inputs(P, b["rule"])
        out = {"keys": keys, "px": px, "W": W, "due": np.ones(P.T, dtype=bool), "slots": r10.S1_RULES[b["rule"]][1],
               "v": mk.v1, "v_today": mk.v1_today}
    else:
        keys, W, due, _ = s2.candidate(b["rule"], mk.m, P)
        mt = memo.setdefault(("tok", r10.SEED), r10.token_market(mk, r10.SEED))
        out = {"keys": keys, "px": s2.coin_prices(b["rule"], keys, mt, P, 1.0), "W": W, "due": due,
               "slots": s2.SLOTS[b["rule"]], "v": mk.v2, "v_today": mk.v2_today}
    memo[("in", book)] = out
    return out


def plan(x: dict, days: np.ndarray, variant: str, is_late: bool) -> tuple[np.ndarray, np.ndarray, float]:
    """(targets, due closes, band) of a variant, one close late when asked."""
    W, due = x["W"], (x["due"] if variant == "as_run" else weekday(days))
    if is_late:
        W, due = r10.late(W), r10.late_mask(due)
    return W, due, BAND if variant == "weekly_band" else 0.0


def run(mk: r10.Market, book: str, variant: str, is_late: bool, t0: int, t1: int, today: bool = False,
        memo: dict | None = None) -> dict:
    """One wallet in EUR (the last close after the way back) and what it paid, in EUR at the day's rate."""
    memo = {} if memo is None else memo
    P, cap = mk.P, BOOKS[book]["capital"]
    x = inputs(mk, book, memo)
    W, due, band = plan(x, P.days, variant, is_late)
    v = x["v_today"] if today else x["v"]
    fx0 = float(mk.fx[t0])
    usd = r10.way_in(cap, fx0, mk.rate, r10.sol_on_chain(v, P.days[t0]))
    sol = mk.m.sol_eur
    res = simulate(x["px"], x["keys"], W, due, sol, v, usd, t0, t1, x["slots"], P.days, band)
    eq = r10.in_eur(res, cap, mk.fx, t0, t1, v, P.days, float(sol[t1]), mk.rate)
    fx = mk.fx[t0:t1 + 1]
    return {"eq": eq, "way_in": cap - usd / fx0, "setup": res["setup"] / fx0,
            "way_back": float(res["equity"][-1] / fx[-1] - eq[-1]), "trading": float((res["paid"] / fx).sum()),
            "traded": float((res["traded"] / fx).sum()), "orders": res["orders"], "skipped": res["skipped"],
            "trade_days": np.flatnonzero(res["traded"] > 0) + t0}


def measure(r: dict, cap: float) -> dict:
    m = r10.measure(r["eq"], cap)
    years = max(len(r["eq"]) / 365, 1e-9)
    total = r["way_in"] + r["setup"] + r["trading"] + r["way_back"]
    return {**m, "costs_eur": total, "trading_eur": r["trading"], "way_in_eur": r["way_in"] + r["setup"],
            "way_back_eur": r["way_back"], "costs_share": total / cap, "trading_share_yr": r["trading"] / years / cap,
            "turnover_yr": r["traded"] / max(float(np.mean(r["eq"])), 1e-9) / years,
            "orders_yr": r["orders"] / years, "skipped_yr": r["skipped"] / years}


# ---------------------------------------------------------------- judging

def follows(row: dict) -> dict:
    """The pre-registered rule for the variant to follow, late, validation, at the book's wallet: trading costs
    below the as-run book's, Sharpe at least its minus 0.10, CAGR at least its minus 1 point, no leak."""
    a, f = row["late"]["as_run"], row["late"][FOLLOW]
    checks = {"trading costs below as run": f["trading_eur"] < a["trading_eur"],
              "Sharpe >= as run - 0.10": f["sharpe"] >= a["sharpe"] - SHARPE_SLACK,
              "CAGR >= as run - 1 pt": f["cagr"] >= a["cagr"] - CAGR_SLACK,
              "no leak": bool(row.get("leak", {}).get("ok"))}
    return {"follow": all(checks.values()), "fails": [k for k, ok in checks.items() if not ok]}


def leak_check(mk: r10.Market, book: str, n_cuts: int = 3) -> dict:
    """T1's harness on the weekly_band late wallet: S1's books on the panel, S2's on S2's market (in USD, the
    tokens as their underlying), both cut at the end of the validation window. Output: the equity at each close."""
    from .. import leak
    b = BOOKS[book]
    end = r10.window(mk.P.days, "val")[1]
    cap = b["capital"] * float(mk.fx[r10.t_of(mk.P.days, r10.IS_FROM)])
    v = r10.era_venue(mk.v1.ladder if b["study"] == "S1" else mk.v2.ladder,
                      s1.SWAP_FEE_SOL if b["study"] == "S1" else s2.SWAP_FEE_SOL, mk.v1.cex)

    def wallet(keys, px, W, sol, days, slots) -> np.ndarray:
        W, due, band = plan({"W": W, "due": None}, days, FOLLOW, True)
        t0 = r10.t_of(days, r10.IS_FROM)
        out = np.full(len(days), np.nan)
        out[t0:] = simulate(px, keys, W, due, sol, v, cap, t0, len(days) - 1, slots, days, band)["equity"]
        return out

    if b["study"] == "S1":
        def fn(P):
            keys, px, W = s1_inputs(P, b["rule"])
            return wallet(keys, px, W, sol_usd(P), P.days, r10.S1_RULES[b["rule"]][1])
        data = leak.cut_panel(mk.P, end)
    else:
        def fn(m):
            keys, W, _, _ = s2.candidate(b["rule"], m, None)
            return wallet(keys, s2.coin_prices(b["rule"], keys, m, None, 1.0), W, m.sol_eur, m.days, s2.SLOTS[b["rule"]])
        data = leak.cut_panel(mk.m, end)
    res = leak.check(fn, data, n_cuts=n_cuts, name=f"{book} {FOLLOW}")
    return {"ok": res["ok"], "reason": leak.reason(res), "runs": res["runs"], "cuts": res["cuts"]}


def pbo(series: dict[tuple[str, str], np.ndarray]) -> dict:
    """CSCV's PBO by Sharpe over the variants' late daily returns, per book and over all."""
    from ..metrics import cscv
    out = {}
    for book in BOOKS:
        cols = [series[(book, v)] for v in variants(book)]
        out[book] = cscv(np.column_stack(cols))
    out["all"] = cscv(np.column_stack(list(series.values())))
    return {k: (None if c is None else {"pbo": c["pbo"], "median_logit": c["median_logit"], "combos": c["combos"]})
            for k, c in out.items()}


def evaluate(mk: r10.Market, register: bool = True, log=print) -> dict:
    from .. import metrics
    P = mk.P
    memo: dict = {}
    ins = r10.window(P.days, "is")
    val = r10.window(P.days, "val")
    rows: dict[str, dict] = {}
    trials = []
    for book in BOOKS:
        cap = BOOKS[book]["capital"]
        row = rows.setdefault(book, {"book": book, **BOOKS[book], "is_sharpe": {}})
        for v in variants(book):
            row["is_sharpe"][v] = measure(run(mk, book, v, True, *ins, memo=memo), cap)["sharpe"]
            if v != "as_run":
                trials.append(trial(book, v, row["is_sharpe"][v]))
    if register:
        metrics.register(trials)                         # before any validation number exists
    pools = r10.dsr_pools()
    for book, row in rows.items():
        cap = BOOKS[book]["capital"]
        for fill, lt in (("on_time", False), ("late", True)):
            row[fill] = {}
            for v in variants(book):
                r = run(mk, book, v, lt, *val, memo=memo)
                m = measure(r, cap)
                row[fill][v] = m
                if v != "as_run":
                    row.setdefault(f"weekday_only_{fill}", {})[v] = wednesdays_only(P.days, r["trade_days"], val[0], lt)
        base = row["late"]["as_run"]["returns"]
        for v in variants(book):
            m = row["late"][v]
            ex = r10.excess(m["returns"], base)
            m.update({"dsr": metrics.dsr(m["returns"], pools["all"]), "dsr_small": metrics.dsr(m["returns"], pools["small"]),
                      "dsr_ex": metrics.dsr(ex, pools["all"]) if v != "as_run" else None,
                      "dsr_ex_small": metrics.dsr(ex, pools["small"]) if v != "as_run" else None})
        row["today"] = {v: measure(run(mk, book, v, True, *val, today=True, memo=memo), cap) for v in variants(book)}
        log(f"  {book}: late trading costs " + ", ".join(f"{v} {row['late'][v]['trading_eur']:.2f}" for v in variants(book))
            + " EUR; Sharpe " + ", ".join(f"{row['late'][v]['sharpe']:.2f}" for v in variants(book)))
    full = (ins[0], val[1])
    series = {(book, v): r10.measure(run(mk, book, v, True, *full, memo=memo)["eq"], BOOKS[book]["capital"])["returns"]
              for book in BOOKS for v in variants(book)}
    for book, row in rows.items():
        row["leak"] = leak_check(mk, book)
        row["verdict"] = follows(row)
        log(f"  {book}: leak {row['leak']['reason']}; follow {row['verdict']['follow']}")
    return {"rows": rows, "pbo": pbo(series), "trials": [t["id"] for t in trials],
            "pools": {k: {"n_trials": p["n_trials"], "sr0_annual": p["sr0_annual"]} for k, p in pools.items()}}


def wednesdays_only(days_us: np.ndarray, trade_days: np.ndarray, t0: int, is_late: bool) -> bool:
    """Every trade after the first close falls on the weekday (on Thursday when filled one close late)."""
    wk = weekday(days_us)
    ok = r10.late_mask(wk) if is_late else wk
    return bool(all(ok[t] for t in trade_days if t != t0))


# ---------------------------------------------------------------- loading

def load() -> r10.Market:
    """R10's market without F2's context: the panel, S2's market in USD, the FX, the venues of their era."""
    P = fc.load_panel()
    etf = s2.load_etf(("SPY", "GLD"))
    snap = s2.load_snapshot()
    m = s2.market(P, etf, 1.0, s2.drifts_from(snap, s2.tracking()))
    cex, rate = r10.kraken_costs()
    v1 = s1.venues()["jupiter"]
    v2 = s2.venue(snap=snap)
    return r10.Market(P=P, m=m, fx=r10.eurusd_on(P.days), v1=r10.era_venue(v1.ladder, s1.SWAP_FEE_SOL, cex),
                      v2=r10.era_venue(v2.ladder, s2.SWAP_FEE_SOL, cex),
                      v1_today=r10.era_venue(v1.ladder, s1.SWAP_FEE_SOL, cex, True),
                      v2_today=r10.era_venue(v2.ladder, s2.SWAP_FEE_SOL, cex, True), rate=rate, devs=r10.deviations())


# ---------------------------------------------------------------- the report

MARKER = "<!-- generated below by lab.experiments.smallaccount_weekly; edit above this line only -->"


def _pct(v, d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f} %"


def _num(v, d: int = 3) -> str:
    return "" if v is None else f"{v:.{d}f}"


def markdown(out: dict) -> str:
    pools = out["pools"]
    md = [f"Generated {out['generated']}. Validation 2024-01-01 to {out['val_to']}, late (filled one close after the "
          "close its targets read) unless a column says otherwise; each book at its own wallet, in EUR after the way "
          f"back. Weekly: Wednesday's close (late: Thursday's); band {BAND * 100:.0f} points of the trading equity, "
          "exits always trade. Costs in EUR at the day's EUR/USD.\n",
          "## 1. Return, drawdown and costs (validation, late)\n"]
    t = []
    for book, row in out["rows"].items():
        for v in variants(book):
            m = row["late"][v]
            t.append({"book": book, "variant": v, "CAGR": _pct(m["cagr"]), "max DD": _pct(m["max_dd"]),
                      "Sharpe": f"{m['sharpe']:.2f}", "end EUR": f"{m['end_eur']:.2f}",
                      "trading costs EUR": f"{m['trading_eur']:.2f}", "way in / back EUR":
                      f"{m['way_in_eur']:.2f} / {m['way_back_eur']:.2f}", "all costs, share of wallet":
                      f"{m['costs_eur']:.2f} ({_pct(m['costs_share'])})", "trading a year, share of wallet":
                      _pct(m["trading_share_yr"], 2), "turnover a year": f"{m['turnover_yr']:.1f}x",
                      "orders / not sent a year": f"{m['orders_yr']:.0f} / {m['skipped_yr']:.0f}"})
    md.append(fc.table(t, list(t[0])))
    md.append("## 2. On time against late, today's quotes, in sample (Sharpe; CAGR / trading costs EUR)\n")
    t = []
    for book, row in out["rows"].items():
        for v in variants(book):
            o, lt, td = row["on_time"][v], row["late"][v], row["today"][v]
            t.append({"book": book, "variant": v, "in sample, late": f"{row['is_sharpe'][v]:.2f}",
                      "on time": f"{o['sharpe']:.2f}; {_pct(o['cagr'])} / {o['trading_eur']:.2f}",
                      "late": f"{lt['sharpe']:.2f}; {_pct(lt['cagr'])} / {lt['trading_eur']:.2f}",
                      "late, today's quotes back to 2024": f"{td['sharpe']:.2f}; {_pct(td['cagr'])} / {td['trading_eur']:.2f}"})
    md.append(fc.table(t, list(t[0])))
    md.append("## 3. Deflation and overfitting\n")
    t = []
    for book, row in out["rows"].items():
        for v in variants(book):
            m = row["late"][v]
            t.append({"book": book, "variant": v, "DSR (all / small)": f"{m['dsr']:.3f} / {m['dsr_small']:.3f}",
                      "DSR of the excess over as run (all / small)":
                          f"{_num(m['dsr_ex'])} / {_num(m['dsr_ex_small'])}" if m["dsr_ex"] is not None else ""})
    md.append(fc.table(t, list(t[0])))
    md.append(f"DSR (higher is better, pass at 0.95 or more) of the late validation daily returns in EUR over R5's "
              f"registry, the pool of all ({pools['all']['n_trials']:,} trials, noise bar {pools['all']['sr0_annual']:.2f} "
              f"a year) and the small family ({pools['small']['n_trials']:,} trials, {pools['small']['sr0_annual']:.2f}). "
              "PBO (CSCV, 16 blocks, by Sharpe, one late wallet from 2020-08-01 to the end of validation): "
              + ", ".join(f"{k} " + ("n/a" if p is None else f"{p['pbo']:.2f}") for k, p in out["pbo"].items()) + ".\n")
    md.append("## 4. The pre-registered rule: follow weekly_band?\n")
    t = [{"book": book, "leak (T1)": row["leak"]["reason"], "follow": "yes" if row["verdict"]["follow"] else "no",
          "fails on": "; ".join(row["verdict"]["fails"])} for book, row in out["rows"].items()]
    md.append(fc.table(t, list(t[0])))
    md.append(f"Trials registered (small family): {', '.join(out['trials'])}.\n")
    return "\n".join(md) + "\n"


def write(out: dict, path: Path = RESULTS / f"{NAME}.md") -> None:
    head = "# S1w: the small-account books traded weekly\n\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if MARKER in old:
            head = old.split(MARKER)[0]
    path.write_text(head + MARKER + "\n\n" + markdown(out), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    t0 = time.time()
    mk = load()
    res = evaluate(mk, register="--no-register" not in argv)
    for row in res["rows"].values():
        for fill in ("on_time", "late"):
            for m in row[fill].values():
                m.pop("returns", None)
        for m in row["today"].values():
            m.pop("returns", None)
    b = r10.window(mk.P.days, "val")[1]
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "val_to": str((mk.P.days[b] // fc.DAY_US).astype("datetime64[D]")), **res,
           "follow": [k for k, r in res["rows"].items() if r["verdict"]["follow"]], "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    write(out)
    print(f"done in {out['seconds']} s; follow: {out['follow'] or 'nothing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
