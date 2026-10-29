"""O1: order book depth as a signal. Does T4's depth say anything about returns?

Pre-registered in results/depth_signal_o1_prereg.md; results in results/depth_signal_o1.md.

    PYTHIA_AGENT_OUT=<panel cache> PYTHIA_TRIALS_REGISTRY=<registry> \
        flock <heavy lock> python -m lab.experiments.depth_signal_o1 [--no-register] [--report]

Three signals from the feature store (lab.features, group book_depth, daily rows asked at the close of each day):
IMB the imbalance within 1 % (bd_imb1), DCHG the daily change of depth within 1 % (bd_depth1_chg), ILLIQ the log
cost of a 100k order (bd_cost100k_bps). Each as a cross-sectional book (top fifth long, bottom fifth short) and as a
time-series book (each coin against its own 30 days: bd_imb1_dev30, the change itself, bd_cost100k_dev30) on T5's
PIT50 with T4's delisting table, the perp traded and the signal known; 1 day for IMB and DCHG, seven 7-day tranches
for ILLIQ. Weights from close t are traded at close t+1 on the perps (t5.simulate, funding both ways) at T4's own
costs (T6b's cost matrix at 10k a leg). Tests: the rank IC (XS), the book's mean gross return (TS), and whether
depth falling says the next day moves more than usual. Seven trials of R5's registry, registered with their
in-sample Sharpes before any validation number. Rows from 2026-07-01 on are dropped before anything is computed:
the lockbox is never read. Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl
from scipy import stats

from .. import metrics
from . import director_common as dc
from . import fam_common as fc
from . import pit_universe_t5 as t5
from . import two_leads_t6 as t6
from . import two_leads_t6b as t6b

NAME = "depth_signal_o1"
PREREG = "results/depth_signal_o1_prereg.md"
IS_FROM, IS_TO, VAL_FROM, VAL_TO = "2023-01-01", "2023-12-31", "2024-01-01", "2026-06-30"
LOCKBOX = "2026-07-01"
YEARS = (2024, 2025, 2026)
# signal: (the XS feature, the TS feature, horizon in days); XS of ILLIQ on the log cost
SIGNALS = {"imb": ("bd_imb1", "bd_imb1_dev30", 1), "dchg": ("bd_depth1_chg", "bd_depth1_chg", 1),
           "illiq": ("bd_cost100k_bps", "bd_cost100k_dev30", 7)}
HOWS = ("xs", "ts")
BOOKS = tuple(f"{s}:{h}" for s in SIGNALS for h in HOWS)
FEATURES = tuple(dict.fromkeys(f for a, b, _ in SIGNALS.values() for f in (a, b)))
UNI_N, MIN_COINS = 50, 20
LEG = "10k"                                       # T6b's judged leg notional
WARM = "2022-12-01"                               # the books' first day (nothing before the depth files)
SHARPE_PASS, YEARS_PASS, T_PASS = 0.5, 2, 2.0
DSR_PASS, PBO_PASS = 0.95, 0.5
TS_LAGS = 10
VOL_WIN, VOL_MIN = 30, 20
DAY_US = fc.DAY_US


# ---------------------------------------------------------------- the features, point in time

def feature_matrices(P: fc.Panel, names=FEATURES, cut: str = LOCKBOX, since: str = WARM) -> dict[str, np.ndarray]:
    """{feature: (T, N)} each depth feature as lab.features.frame gives it at the close of day t (the day's row,
    known at its end), on the panel's columns by coin (t6b.coin_key); NaN where none. The group's daily table is
    cut before `cut` and put in the registry's memo first, so no row of the lockbox reaches a feature."""
    from ..features import book as fbook  # noqa: F401  (registers the book_depth features)
    from ..features import registry as R
    keys = [t6b.coin_key(n) for n in P.names]
    assets = sorted({k for k in keys if k})
    k = ("book_depth", "1d", tuple(assets))
    R._TABLES[k] = R.GROUPS["book_depth"].table("1d", k[2]).filter(pl.col("ts_us") < dc.us(cut)).sort("asset", "ts_us")
    t0 = int(np.searchsorted(P.days, dc.us(since)))
    F = R.frame(list(names), assets, P.days[t0:] + DAY_US, "1d")
    R._TABLES.pop(k, None)
    out = {n: np.full((P.T, P.N), np.nan) for n in names}
    ci: dict[str, list[int]] = {}
    for j, a in enumerate(keys):
        if a:
            ci.setdefault(a, []).append(j)
    t = np.searchsorted(P.days + DAY_US, F["ts_us"].to_numpy())
    for i, a in enumerate(F["asset"].to_list()):
        for n in names:
            v = F[n][i]
            if v is not None:
                out[n][t[i], ci[a]] = v
    return out


def score(P: fc.Panel, sig: str, how: str) -> np.ndarray:
    """(T, N) the pre-registered score (long the high) from the panel's depth arrays (P.extra, one per feature)."""
    f = SIGNALS[sig][0 if how == "xs" else 1]
    x = np.asarray(P.extra[f], dtype=float)
    if sig == "illiq" and how == "xs":
        with np.errstate(invalid="ignore", divide="ignore"):
            x = np.where(x > 0, np.log(x), np.nan)
    return x


def universe(P: fc.Panel, s: np.ndarray, delist=None) -> np.ndarray:
    """(T, N) T5's PIT50 (T4's delisting table) where the perp traded and the score is known at the close."""
    from .. import universe as U
    return U.pit(P, UNI_N, table=delist, vol=P.extra.get("o1_vol")) & P.perp_ok & np.isfinite(s)


# ---------------------------------------------------------------- the books

def targets(s: np.ndarray, uni: np.ndarray, how: str, reb: np.ndarray) -> np.ndarray:
    """(T, N) weights on the rebalance days, NaN elsewhere (hold). XS: the top fifth of the day's coins long, the
    bottom fifth short, half the capital a side; TS: +-1/n by the sign. A day with fewer than MIN_COINS holds."""
    W = np.full(s.shape, np.nan)
    for t in np.flatnonzero(reb):
        idx = np.flatnonzero(uni[t])
        if len(idx) < MIN_COINS:
            continue
        row = np.zeros(s.shape[1])
        if how == "xs":
            k = max(1, len(idx) // 5)
            o = idx[np.argsort(s[t, idx], kind="stable")]
            row[o[::-1][:k]] = 0.5 / k
            row[o[:k]] = -0.5 / k
        else:
            row[idx] = np.sign(s[t, idx]) / len(idx)
        W[t] = row
    return W


def sleeves(P: fc.Panel, sig: str, how: str, delist=None) -> list[tuple[np.ndarray, np.ndarray]]:
    """(W, rebalance) per tranche, on time (the close of the signal): one daily book, or SIGNALS' horizon of
    tranches each re-picked every h days."""
    h = SIGNALS[sig][2]
    s = score(P, sig, how)
    uni = universe(P, s, delist)
    out = []
    for o in range(h):
        reb = (np.arange(P.T) % h) == o
        out.append((targets(s, uni, how, reb), reb))
    return out


def weights(P: fc.Panel, sig: str, how: str, delist=None) -> np.ndarray:
    """The first tranche's weights on time (T1's leak check runs on these)."""
    return sleeves(P, sig, how, delist)[0][0]


def run_book(P: fc.Panel, sig: str, how: str, C: np.ndarray, delist=None) -> dict[str, np.ndarray]:
    """One book late (traded at the next close), both legs on the perps at C: {"net", "gross"} (T,), the
    tranches' mean, NaN before WARM."""
    t0 = int(np.searchsorted(P.days, dc.us(WARM)))
    nets, gross = [], []
    for W, reb in sleeves(P, sig, how, delist):
        W, reb = t5.late(W, reb)
        n_, g = t5.simulate(P, W, reb, C, True, t0)
        nets.append(n_)
        gross.append(g)
    live = np.arange(P.T) > t0
    return {"net": np.where(live, np.mean(nets, axis=0), np.nan), "gross": np.where(live, np.mean(gross, axis=0), np.nan)}


# ---------------------------------------------------------------- the tests

def hac_t(x: np.ndarray, lags: int) -> float:
    from ..features.study import hac_t as h
    x = np.asarray(x, dtype=float)
    return h(x[np.isfinite(x)], lags)


def forward(P: fc.Panel, h: int) -> np.ndarray:
    """(T, N) the late forward return of day t: close t+1 to close t+1+h (NaN where unknown)."""
    px = P.px
    out = np.full(px.shape, np.nan)
    if P.T > h + 1:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:P.T - 1 - h] = px[1 + h:] / px[1:P.T - h] - 1
    return out


def rank_ic(s: np.ndarray, y: np.ndarray, uni: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """(T,) per day in `mask` the Spearman correlation of score and return over the universe (NaN with fewer than
    MIN_COINS)."""
    out = np.full(len(s), np.nan)
    for t in np.flatnonzero(mask):
        ok = uni[t] & np.isfinite(y[t]) & np.isfinite(s[t])
        if ok.sum() >= MIN_COINS:
            r = stats.spearmanr(s[t, ok], y[t, ok])[0]
            out[t] = r if np.isfinite(r) else np.nan
    return out


def vol_test(P: fc.Panel, chg: np.ndarray, uni: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """(T,) per day in `mask` the OLS coefficient of rank(|r(t+1)| / s30) on rank(-chg) with rank(|r(t)| / s30)
    beside it (ranks over n, across the universe), s30 the mean |r| of days t-29 to t; NaN with fewer than
    MIN_COINS."""
    a = np.abs(P.ret)
    s30 = fc.rolling(a, VOL_WIN, VOL_MIN)
    nxt = np.full(a.shape, np.nan)
    nxt[:-1] = a[1:]
    with np.errstate(invalid="ignore", divide="ignore"):
        y_, x2 = nxt / s30, a / s30
    out = np.full(P.T, np.nan)
    for t in np.flatnonzero(mask):
        ok = uni[t] & np.isfinite(y_[t]) & np.isfinite(x2[t]) & np.isfinite(chg[t]) & (s30[t] > 0)
        n = int(ok.sum())
        if n < MIN_COINS:
            continue
        X = np.column_stack([np.ones(n), stats.rankdata(-chg[t, ok]) / n, stats.rankdata(x2[t, ok]) / n])
        out[t] = np.linalg.lstsq(X, stats.rankdata(y_[t, ok]) / n, rcond=None)[0][1]
    return out


# ---------------------------------------------------------------- judging

def trial_rows(ins_sharpe: dict[str, float]) -> list[dict]:
    """The 7 trials: the six books with their in-sample Sharpes, the depth-falling test counted."""
    rows = [{"id": f"hand:o1:{b}", "family": "hand", "n": 1, "sharpe": float(ins_sharpe[b]), "source": PREREG}
            for b in BOOKS]
    return rows + [{"id": "hand:o1:dchg:vol", "family": "hand", "n": 1, "sharpe": None, "source": PREREG}]


def passes(v: dict, years: dict, t: float, dsr_all: float, dsr_fam: float, pbo: dict | None, leak: bool) -> dict:
    """The pre-registered conditions of one book."""
    return {"1 Sharpe and years": v["sharpe"] > SHARPE_PASS and sum(years[y] > 0 for y in YEARS) >= YEARS_PASS,
            "2 test t": bool(np.isfinite(t) and t >= T_PASS),
            "3 DSR all and family": dsr_all >= DSR_PASS and dsr_fam >= DSR_PASS,
            "4 PBO": pbo is not None and pbo["pbo"] < PBO_PASS,
            "5 leak": bool(leak)}


def evaluate(P: fc.Panel, C: np.ndarray, delist=None, leaks: dict | None = None, register: bool = True,
             log=print) -> dict:
    """Every book and test on a panel already holding the depth arrays (P.extra), cut at VAL_TO. Registers the
    trials with their in-sample Sharpes before any validation number is computed."""
    days = P.days
    ins = (days >= dc.us(IS_FROM)) & (days <= dc.us(IS_TO))
    val = (days >= dc.us(VAL_FROM)) & (days <= dc.us(VAL_TO))
    years = dc.years_of(days)
    base = universe(P, np.zeros((P.T, P.N)), delist)       # PIT50 with a traded perp, signal or not
    runs = {}
    for b in BOOKS:
        sig, how = b.split(":")
        runs[b] = run_book(P, sig, how, C, delist)
        log(f"  {b} done")
    ins_sh = {b: dc.sharpe(runs[b]["net"][ins]) for b in BOOKS}
    trials = trial_rows(ins_sh)
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  O1: in sample " + ", ".join(f"{b} {ins_sh[b]:.2f}" for b in BOOKS))
    p_all, p_fam = t6.pools(trials, "hand")
    both = (ins | val) & np.all([np.isfinite(runs[b]["net"]) for b in BOOKS], axis=0)
    pbo = metrics.cscv(np.column_stack([np.nan_to_num(runs[b]["net"][both]) for b in BOOKS]))
    out = {"books": {}, "pbo": pbo, "pool_all": t6._pool(p_all), "pool_family": t6._pool(p_fam),
           "trials": [t["id"] for t in trials], "from": dc.day_str(days[val][0]), "to": dc.day_str(days[val][-1])}
    for b in BOOKS:
        sig, how = b.split(":")
        h = SIGNALS[sig][2]
        net, gross = runs[b]["net"], runs[b]["gross"]
        x = net[val]
        s = score(P, sig, how)
        uni = universe(P, s, delist)
        if how == "xs":
            ic = rank_ic(s, forward(P, h), uni, val)
            test = {"what": f"rank IC, {h}-day late return", "stat": float(np.nanmean(ic)),
                    "t": hac_t(ic[val], max(10, 2 * h)), "days": int(np.isfinite(ic[val]).sum())}
        else:
            test = {"what": "mean daily gross return", "stat": float(np.nanmean(gross[val])),
                    "t": hac_t(gross[val], TS_LAGS), "days": int(np.isfinite(gross[val]).sum())}
        yrs = {y: dc.sharpe(net[val & (years == y)]) for y in YEARS}
        d_all, d_fam = metrics.dsr(x, p_all), metrics.dsr(x, p_fam)
        lk = (leaks or {}).get(b)
        cov = {w: float(uni[m].sum() / max(1, base[m].sum())) for w, m in (("is", ins), ("val", val))}
        out["books"][b] = {"is": t6.stats_of(net[ins]), "val": t6.stats_of(x), "years": yrs, "test": test,
                           "drag": float(np.nanmean(gross[val] - net[val]) * 365), "dsr_all": d_all,
                           "dsr_family": d_fam, "leak": t6._leak(lk), "coverage": cov,
                           "coins": float(np.mean(uni[val].sum(1))),
                           "conditions": passes(t6.stats_of(x), yrs, test["t"], d_all, d_fam, pbo,
                                                bool(lk and lk.get("ok")))}
        out["books"][b]["pass"] = all(out["books"][b]["conditions"].values())
    chg = score(P, "dchg", "xs")
    v = vol_test(P, chg, universe(P, chg, delist), val)
    out["vol"] = {"coef": float(np.nanmean(v[val])), "t": hac_t(v[val], TS_LAGS), "days": int(np.isfinite(v[val]).sum())}
    out["passed"] = [b for b in BOOKS if out["books"][b]["pass"]]
    out["lockbox"] = ("look due for " + ", ".join(out["passed"]) + " (not looked here)") if out["passed"] \
        else "no look (no book passes validation)"
    return out


# ---------------------------------------------------------------- the report

def _pct(v) -> str:
    return t6._pct(v)


def markdown(out: dict, about: dict) -> str:
    md = [f"Generated {about['generated']}. Validation {out['from']} to {out['to']}, in sample {IS_FROM} to {IS_TO}, "
          f"every series and the depth table cut before {LOCKBOX} (the lockbox not read). Universe: T5's PIT50 with "
          f"T4's delisting table ({about['delist']}), the perp traded and the signal known, at least {MIN_COINS} coins. "
          f"Late: weights of close t traded at close t+1 on the perps, funding both ways. Costs: the USD-M taker "
          f"{t5.PERP_FEE * 1e4:.0f} bps plus the cost of a {LEG} USD market order from T4's hour nearest the fill "
          f"(T6b's matrix; T5's tier on a day without a depth file, {t6b.BEYOND * 1e4:.0f} bps beyond the depth).\n",
          "| Book | in sample Sharpe | validation Sharpe / CAGR / DD | by year | cost drag a year | test (validation) "
          "| DSR all / family | coins a day, coverage | passes |", "|---|---|---|---|---|---|---|---|---|"]
    for b, r in out["books"].items():
        v, te = r["val"], r["test"]
        stat = f"{te['stat']:+.4f}" if te["what"].startswith("rank") else f"{te['stat'] * 1e4:+.2f} bps a day"
        md.append(f"| {b} | {r['is']['sharpe']:.2f} | {v['sharpe']:.2f} / {_pct(v['cagr'])} / {_pct(v['max_dd'])} | "
                  + ", ".join(f"{y} {s:.2f}" for y, s in r["years"].items())
                  + f" | {_pct(r['drag'])} | {te['what']} {stat}, t {te['t']:+.2f} ({te['days']:,} days) | "
                  f"{r['dsr_all']:.3f} / {r['dsr_family']:.3f} | {r['coins']:.0f}, {_pct(r['coverage']['val'])} | "
                  f"{t6._yes(r['pass'])} |")
    pb = out["pbo"]
    md.append(f"\nDSR over {out['pool_all']['n_trials']:,} trials (noise bar {out['pool_all']['sr0_annual']:.2f} a "
              f"year) and the hand family's {out['pool_family']['n_trials']:,} "
              f"({out['pool_family']['sr0_annual']:.2f}); pass at 0.95 or more. PBO of the six books: "
              + (f"{pb['pbo']:.2f} over {pb['combos']:,} splits." if pb else "n/a."))
    md.append("Coverage: the universe's coin-days with the signal against PIT50's with a traded perp (validation).\n")
    rows = []
    for b, r in out["books"].items():
        c = r["conditions"]
        lk = r["leak"]
        rows.append({"book": b, **{k: t6._yes(x) for k, x in c.items()},
                     "leak run": (f"{'no leak' if lk['ok'] else 'LEAK ' + str(lk['first'])} ({lk['runs']} runs)"
                                  if lk else "not run")})
    md.append(dc.table(rows, list(rows[0])) + "\n")
    fl = about.get("feature_leak", {})
    md.append("Features through T1's harness (`lab.leak.checks.feature`, 1d, real rows): "
              + (", ".join(f"`{n}` {'ok' if ok else 'LEAK'}" for n, ok in fl.items()) or "not run") + ".\n")
    vt = out["vol"]
    md.append(f"Depth falling ahead of moves (information): per day across the universe, rank(|r(t+1)| / s30) on "
              f"rank(-DCHG) and rank(|r(t)| / s30): mean coefficient {vt['coef']:+.4f}, t {vt['t']:+.2f} over "
              f"{vt['days']:,} validation days ({'holds' if np.isfinite(vt['t']) and vt['t'] >= T_PASS else 'not shown'} "
              f"at t 2 in the prior's direction).\n")
    md.append(f"Passed: {', '.join(out['passed']) or 'none'}. Lockbox: {out['lockbox']}. Paper book: "
              + ("pre-registered as `depth_o1_<book>`, its own commit" if out["passed"] else "none (no book passes)")
              + ".\n")
    md.append(f"Trials (R5's registry, before the validation numbers): {', '.join(out['trials'])}.\n")
    return "\n".join(md)


HEAD = """# O1: order book depth as a signal

Pre-registered in `results/depth_signal_o1_prereg.md` (committed before the first run). Code:
`lab.experiments.depth_signal_o1`, the features in `lab.features.book` (`bd_imb1`, `bd_depth1_chg`,
`bd_cost100k_bps`, and O1's `bd_imb1_dev30`, `bd_cost100k_dev30`). Paper only: nothing a live bot, a wallet or the
engine reads changed.
"""


# ---------------------------------------------------------------- run

def feature_rows(assets=("BTC", "ETH", "SOL", "XRP"), days: int = 400) -> pl.DataFrame:
    """The real daily rows T1's feature check runs on: the last `days` before the lockbox (checks.real_table's
    rows without the lockbox)."""
    from ..features import registry as R
    t = R.GROUPS["book_depth"].table("1d", tuple(sorted(assets))).filter(pl.col("ts_us") < dc.us(LOCKBOX))
    return t.filter(pl.col("ts_us") >= dc.us(LOCKBOX) - days * DAY_US).sort("asset", "ts_us")



def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .. import report
    from .. import universe as U
    from ..collect import book_depth
    from ..leak import checks
    d = report.REPORTS / NAME
    if "--report" in argv:                               # the file again from the last run's numbers
        o = json.loads((d / "latest.json").read_text(encoding="utf-8"))
        dc.write_results(NAME, markdown(o["out"], o["about"]), HEAD)
        return 0
    t0 = time.time()
    delist = book_depth.read_delistings()
    delist = delist if len(delist) else None
    P = dc.cut_panel(fc.load_panel(), VAL_TO)
    vol = U.median_volume(P)
    P.extra.update(feature_matrices(P))
    P.extra["o1_vol"] = vol
    print(f"panel and features ready, {time.time() - t0:.0f} s", flush=True)
    C = t6b.cost_matrices(P.days, [t6b.coin_key(n) for n in P.names], vol, t6b.fill_hours(VAL_TO))[LEG]
    leaks = {}
    Q = dc.cut_panel(P, VAL_TO)
    Q.extra.pop("o1_vol")                                # the leak runs recompute the volume from the changed rows
    for b in BOOKS:
        sig, how = b.split(":")
        leaks[b] = checks.book(f"o1 {b}", lambda X, s=sig, h=how: weights(X, s, h, delist), Q)
        print(f"  leak {b}: {'ok' if leaks[b]['ok'] else leaks[b]['first']}", flush=True)
    fl = {n: bool(checks.feature(n, "1d", feature_rows())["ok"]) for n in FEATURES}
    out = evaluate(P, C, delist, leaks, "--no-register" not in argv)
    about = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "delist": f"{len(delist)} rows" if delist is not None else "not present", "feature_leak": fl}
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps({"out": out, "about": about}, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out, about), HEAD)
    print(f"done in {time.time() - t0:.0f} s; passed: {out['passed'] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
