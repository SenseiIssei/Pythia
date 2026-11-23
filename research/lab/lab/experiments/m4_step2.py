"""M4S2: step 2 of the readiness ladder for m4_perps, perps_neutral and m4_hl_small, as they run on paper.

Pre-registered in results/m4_step2_prereg.md; results in results/m4_step2.md and results/m4_step2.json (each book's
tested daily series, which lab.ops.ladder deflates again over every day's registry).

    PYTHIA_CACHE=<data>/lab-cache PYTHIA_AGENT_OUT=<a copy of lab-cache's cache/ and m4h/> PYTHIA_REPORTS=<reports> \
        PYTHIA_TRIALS_REGISTRY=<registry> flock <heavy lock> python -m lab.experiments.m4_step2 [--no-register]
    ... python -m lab.experiments.m4_step2 --report      results/m4_step2.md and .json again from the report

The rules unchanged: reg7n 10/10 with the 50 % rank buffer on M4L's frozen panel (m4_perps on Kraken Futures' coins,
the ideal account; m4_hl_small M4H's judged cell on Hyperliquid's, 230 USD), and perps_neutral's ERC over M4, carry F7
and low vol, each on Kraken's coins. First the band check: both M4 books on time at the band's costs equal their
stored series (M4L) or the run stops. Then two cases per book: one close late (day t trades on t-1's signal) and on
time, both at the costs of their era (the venue's taker of the period plus T4's 1k depth cost at the fill hour,
the band's proxy where no depth file exists). The 30 trials go into R5's registry with their in-sample Sharpes (the
Binance universe, 2022-2023) before any number of the judged days (decision days 2024-01-01 to 2026-06-28). Per
book: late and era CAGR, the DSR of the late case over R5's registry and the book's family, and the PBO (CSCV) of
each family its rule went through (reg7n's 18 funding-aware books, M4H's k, perps_neutral's six), the highest
judged. Nothing from 2026-07-01 is read; nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import metrics
from . import director_common as dc
from . import m4h

NAME = "m4_step2"
PREREG = "results/m4_step2_prereg.md"
IS_FROM, IS_TO, PN_IS_FROM = m4h.IS_FROM, m4h.IS_TO, "2022-03-01"
OOS_FROM, OOS_TO, CUT = m4h.OOS_FROM, m4h.OOS_TO, m4h.CUT
YEARS = m4h.YEARS_OOS
DAY_US = m4h.DAY_US
DSR_PASS, PBO_MAX = 0.95, 0.2               # the ladder's bars
CHECK_TOL = 1e-9                            # the band check: largest daily difference allowed
DEPTH_USD = 1e3                             # T6b's smallest measured order; every order of these books is below it
FEE_KF = 5.0e-4                             # Kraken Futures' base taker (DT1's FEE_KF); no dated schedule: a proxy
# Hyperliquid's base taker by the fill day (T11, T12): to 2023-12-31, to 2025-04-30, after (switches to the quarter).
HL_ERA = (("2023-12-31", 2.5e-4), ("2025-04-30", 3.5e-4), (None, 4.5e-4))
FA_COST = 0.0015                            # m4_funding's pick was made at 15 bps
REWEIGHT = 0.0010                           # perps_neutral's book reweights
PN_BOOKS, PN_METHODS = ("M4", "Carry", "LowVol"), ("EW", "IV", "ERC")
BOOKS = {
    "m4_perps": {"family": "hand", "venue": "kraken_futures", "capital": None, "band_fee": m4h.SERIES["m4_perps"]["fee"],
                 "rule": "reg7n 10/10 of the 100 most liquid perps Kraken Futures lists, rank buffer 50 %, the ideal "
                         "account, 01:00 fills, Binance's funding",
                 "pbo": ("fa",)},
    "perps_neutral": {"family": "hand", "venue": "kraken_futures", "capital": None, "band_fee": None,
                      "rule": "ERC monthly over M4 (m4_perps' rule), carry F7 (10/10 of the 100 most liquid, three "
                              "3-day tranches) and low vol (vol 60d, top 50, beta-neutral, weekly), each on Kraken's "
                              "coins, book reweights 10 bps",
                      "pbo": ("fa", "pn")},
    "m4_hl_small": {"family": "small", "venue": "hyperliquid", "capital": m4h.ACCOUNTS["230usd"],
                    "band_fee": m4h.SERIES["m4_hl_small"]["fee"],
                    "rule": "M4H's judged cell: reg7n 10/10 of the 100 most liquid perps Hyperliquid lists, rank "
                            "buffer 50 %, 230 USD with size decimals and the 10 USD minimum, 01:00 fills, "
                            "Hyperliquid's funding",
                    "pbo": ("fa", "m4h")},
}
FAMILIES = {"fa": "reg7n's family: m4_funding's 18 funding-aware books (Binance's universe, 15 bps)",
            "m4h": "M4H's k: the judged cells k 3, 5 and 10 at 230 USD",
            "pn": "perps_neutral's pick: M4, Carry, LowVol, EW, IV and ERC, late at the era's costs"}
CONDS = ("late", "era", "dsr_all", "dsr_family", "pbo")


def trial(id_: str, sharpe: float) -> dict:
    return {"id": id_, "family": id_.split(":")[0], "n": 1, "sharpe": float(sharpe), "source": PREREG}


def stats(x: np.ndarray, days: np.ndarray | None = None) -> dict:
    x = np.asarray(x, dtype=float)
    out = {"sharpe": m4h.ann_sharpe(x), "cagr": m4h.cagr(x), "max_dd": m4h.max_dd(x), "days": int(len(x))}
    if days is not None:
        yr = dc.years_of(days)
        out["by_year"] = {str(y): m4h.ann_sharpe(x[yr == y]) for y in YEARS if (yr == y).any()}
    return out


# ---------------------------------------------------------------- costs of their era

def hl_fee(days: np.ndarray) -> np.ndarray:
    """(T,) Hyperliquid's base taker of the period of each decision day's fill (the next UTC day)."""
    fill = np.asarray(days) + DAY_US
    out = np.full(len(fill), HL_ERA[-1][1])
    for last, fee in reversed(HL_ERA[:-1]):
        out = np.where(fill < dc.us(last) + DAY_US, fee, out)
    return out


def venue_fee(days: np.ndarray, venue: str) -> np.ndarray:
    return hl_fee(days) if venue == "hyperliquid" else np.full(len(days), FEE_KF)


def era_cost(fee: np.ndarray, depth: np.ndarray, proxy: np.ndarray) -> np.ndarray:
    """(T, N) a side per unit traded: the period's taker plus T4's depth cost where its file exists, else the proxy."""
    return fee[:, None] + np.where(np.isfinite(depth), depth, proxy)


def traded(W: np.ndarray, R: np.ndarray, ret: np.ndarray) -> np.ndarray:
    """(n, N) |weight traded| per row of m4h.simulate's held weights W (after each day's orders): the weights before
    the orders are the last row's drifted by its coins' returns and the account's (pos x (1 + R) / new equity)."""
    pre = np.zeros_like(W)
    g = 1 + np.asarray(ret[:-1], dtype=float)
    pre[1:] = np.where(g[:, None] > 0, W[:-1] * (1 + R[:-1]) / np.where(g > 0, g, 1.0)[:, None], 0.0)
    return np.abs(W - pre)


def share_rows(tot: np.ndarray, dep: np.ndarray, bey: np.ndarray, days: np.ndarray) -> dict:
    """The share of the traded turnover (per row: all, at depth, beyond it) priced from T4's depth and beyond it, all
    and by year."""
    yr = dc.years_of(days)

    def one(m):
        t = tot[m].sum()
        return {"depth": float(dep[m].sum() / t) if t > 0 else None, "beyond": float(bey[m].sum() / t) if t > 0 else None}
    return {**one(np.ones(len(days), dtype=bool)), "by_year": {str(y): one(yr == y) for y in sorted(set(yr))}}


def shares(tr: np.ndarray, depth: np.ndarray, beyond: np.ndarray, days: np.ndarray) -> dict:
    """share_rows of an M4 book's traded weights tr (rows of days, coins) against its depth matrix."""
    has = np.isfinite(depth)
    return share_rows(tr.sum(1), (tr * has).sum(1), (tr * beyond).sum(1), days)


# ---------------------------------------------------------------- the M4 books (m4h's account)

def kraken_by_coin() -> dict[str, int]:
    """{coin: first listed day number} of Kraken Futures' perps (DT1's kf_listings, from the day after openingDate)."""
    from . import daytrade_dt1 as dt
    from . import perps_common as pc
    out: dict[str, int] = {}
    for s, f in dt.kf_listings().items():
        c = pc.coin_of(s)
        out[c] = min(f, out.get(c, f))
    return out


def coin_listed(days: np.ndarray, names, first: dict[str, int]) -> np.ndarray:
    """(T, N) bool: the column's coin is listed on the fill day (the UTC day after the decision or close)."""
    from . import perps_common as pc
    fill = np.asarray(days) // DAY_US + 1
    out = np.zeros((len(days), len(names)), dtype=bool)
    for j, n in enumerate(names):
        f = None if "~" in n else first.get(pc.coin_of(n))
        if f is not None:
            out[:, j] = fill >= f
    return out


def late_score(s: np.ndarray) -> np.ndarray:
    """Day t trades on day t-1's signal (funding_carry.late)."""
    out = np.full_like(s, np.nan)
    out[1:] = s[:-1]
    return out


def m4_run(X: dict, t0: int, t1: int, book: str, S: np.ndarray, listed: np.ndarray | None, late: bool,
           k: int = 10, hl_funding: bool = False) -> dict:
    """m4h.simulate of one M4 book over rows t0..t1 with the cost matrix S a side (fee included), Hyperliquid's
    funding or Binance's; late: the scores one row later. Adds "tr", the weight traded per row and coin."""
    nan = np.full(X["R"].shape, np.nan)
    Xc = {**X, "slip": S, "F": X["F_hl"] if hl_funding else nan, "F2": nan}
    if late:
        Xc["score"] = late_score(X["score"])
    r = m4h.simulate(Xc, t0, t1, k, 1, BOOKS[book]["capital"] if book in BOOKS else None, 0.0, "base", listed,
                     keep_weights=True)
    r["tr"] = traded(r["W"], np.nan_to_num(X["R"][t0:t1 + 1]), r["ret"])
    r["W"] = None
    return r


def band_check(X: dict, listed: dict, out=None) -> dict:
    """Both M4 books on time at the band's costs (M4L's export_series) against their stored series: the largest
    daily difference, the days and whether they match."""
    o0, o1 = m4h.window_rows(X["days"], OOS_FROM, OOS_TO)
    nan = np.full(X["R"].shape, np.nan)
    res = {}
    for b in ("m4_perps", "m4_hl_small"):
        c = m4h.SERIES[b]
        X["F"], X["F2"] = (X["F_hl"] if c["venue"] == "hyperliquid" else nan), nan
        x = m4h.simulate(X, o0, o1, 10, 1, c["capital"], c["fee"], "base", listed[c["venue"]])["ret"]
        p = (out or m4h.series_dir()) / c["file"]
        s = pl.read_parquet(p).sort("day") if p.exists() else None
        same_days = s is not None and s.height == len(x) and np.array_equal(s["day"].to_numpy(), X["days"][o0:o1 + 1])
        diff = float(np.max(np.abs(s["ret"].to_numpy() - x))) if same_days else None
        res[b] = {"file": c["file"], "days": int(len(x)), "max_diff": diff,
                  "ok": diff is not None and diff <= CHECK_TOL}
    X["F"], X["F2"] = nan, nan
    return res


# ---------------------------------------------------------------- reg7n's family (m4_funding's round three)

def net_scores(P: pl.DataFrame, h: int, log=print) -> pl.DataFrame:
    """reg{h}n's walk-forward scores (xs_daily.fit_net_scores' folds, parameters and embargo h + 1 days) on a panel
    with its net labels, cut at CUT: T6b's reg7n_scores for any horizon."""
    import lightgbm as lgb
    from ..cv import walk_forward
    from . import xs_daily as xs
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    days = E["day"].to_numpy()
    Xf = E.select(xs.FEATURES).to_numpy().astype(np.float32)
    yv = np.asarray(E[f"y{h}n"].to_numpy(), dtype=float)
    s = np.full(E.height, np.nan)
    for fold in walk_forward(days, xs.FIRST_TEST, embargo_h=(h + 1) * 24):
        tr = fold.train & np.isfinite(yv)
        s[fold.test] = lgb.LGBMRegressor(**xs.REG_PARAMS).fit(Xf[tr], yv[tr]).predict(Xf[fold.test])
        log(f"  reg{h}n {fold.name}: {int(tr.sum()):,} rows")
    return E.select("day", "symbol").with_columns(pl.Series(f"reg{h}n", s))


def family_matrices(P: pl.DataFrame, tag: str, log=print) -> dict:
    """xs_daily's matrices of the frozen cut with reg3n, reg5n (refit, cached under the panel's hash) and reg7n
    (M4H's cache) scores, as m4h.load_matrices builds them."""
    from .. import report
    from . import two_leads_t6 as t6
    from . import xs_daily as xs
    P, _ = xs.add_net_labels(P)
    S = [pl.read_parquet(m4h.CACHE / f"reg7n_scores{tag}.parquet")]
    for h in (3, 5):
        path = report.REPORTS / NAME / f"reg{h}n_scores{tag}.parquet"
        if path.exists():
            S.append(pl.read_parquet(path))
        else:
            S.append(net_scores(P, h, log))
            path.parent.mkdir(parents=True, exist_ok=True)
            S[-1].write_parquet(path)
    E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                 fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    for s in S:
        E = E.join(s, on=["day", "symbol"], how="left")
    E = E.filter(pl.col("day") >= xs.FIRST_TEST)
    return t6.cut_matrices(xs.matrices(E, P.filter(pl.col("day") >= xs.FIRST_TEST), ["reg3n", "reg5n", "reg7n"]), CUT)


def fa_books(M: dict) -> dict[str, np.ndarray]:
    """The 18 funding-aware books of xs_daily's round three, daily net at FA_COST with Binance's funding."""
    from . import xs_daily as xs
    out = {}
    for h in (3, 5, 7):
        m = f"reg{h}n"
        for n in (50, 100):
            g, tu, fu, _ = xs.book(M, M[m], 10, h, n, True)
            out[f"{m}:{n}:hold"] = g + fu - FA_COST * tu
            for frac in (0.3, 0.5):
                g, tu, fu, _ = xs.book_buffer(M, M[m], 10, frac, n)
                out[f"{m}:{n}:buf{int(frac * 100)}"] = g + fu - FA_COST * tu
    return out


# ---------------------------------------------------------------- perps_neutral's carry and low vol

def carry_matrices(P: pl.DataFrame) -> dict:
    """funding_carry.load's matrices (F7 = minus the funding settled over 7 days) of a given panel."""
    from . import xs_daily as xs
    P, _ = xs.add_net_labels(P)
    P = P.sort(["symbol", "day"]).with_columns(
        fund7_raw=pl.when(pl.col("perp").is_not_null()).then(pl.col("fund7")).otherwise(None)).sort(["day", "symbol"])
    E = P.filter(pl.col("eligible")).with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"),
                                                  r28_raw=pl.col("r28"), s_F7=-pl.col("fund7_raw"))
    return xs.matrices(E, P, ["s_F7"])


def carry_run(F: dict, listed: np.ndarray | None, C: np.ndarray, late: bool) -> tuple[np.ndarray, np.ndarray]:
    """(net, traded at C) of carry F7 10/10, three 3-day tranches, among the listed coins (the score masked: the 100
    most liquid of the listed ones, as the paper book takes them)."""
    from . import funding_carry as fcy
    from . import xs_daily as xs
    s = late_score(F["s_F7"]) if late else F["s_F7"]
    if listed is not None:
        s = np.where(listed, s, np.nan)
    g, cost, fu, _ = xs.book(F, s, 10, 3, fcy.N_LIQUID, True, C=C)
    return g + fu - cost, cost


def restrict_rows(W: np.ndarray, keep: np.ndarray) -> np.ndarray:
    """perps_neutral.restrict_legs per row: the kept coins only, each leg scaled back to its gross; a row without a
    kept long or short leg is flat. NaN rows (no rebalance) stay NaN."""
    out = np.array(W, dtype=float, copy=True)
    for t in np.flatnonzero(np.isfinite(W).any(1)):
        w = np.nan_to_num(W[t])
        L0, S0 = w[w > 0].sum(), -w[w < 0].sum()
        k = np.where(keep[t], w, 0.0)
        L1, S1 = k[k > 0].sum(), -k[k < 0].sum()
        out[t] = 0.0 if L1 <= 0 or S1 <= 0 else np.where(k > 0, k * L0 / L1, k * S0 / max(S1, 1e-18))
    return out


def lowvol_targets(Pw, listed: np.ndarray | None) -> np.ndarray:
    """The sweep's beta-neutral low-vol weights on its weekly rows (NaN between), on Kraken's coins with a perp that
    day when listed is given (the paper book's lowvol_target)."""
    from . import fam_common as fc
    from . import fam_lowvol as flv
    W = np.where(fc.every(Pw, 7)[:, None], flv.weights(Pw, "vol 60d", 50, "beta-neutral BAB"), np.nan)
    if listed is None:
        return W
    seg = np.array(["~" in n for n in Pw.names])
    return restrict_rows(W, listed & Pw.perp_ok & ~seg[None, :])


def lowvol_run(Pw, W: np.ndarray, C: np.ndarray, late: bool) -> tuple[np.ndarray, np.ndarray]:
    """(net, cost) on the panel's return days: both legs on perps (t5.simulate, NaN rows hold), from row 100."""
    from . import pit_universe_t5 as t5
    if late:
        W, _ = t5.late(W, np.zeros(Pw.T, dtype=bool))
    net, gross = t5.simulate(Pw, W, np.ones(Pw.T, dtype=bool), C, True, 100)
    live = np.arange(Pw.T) > 100
    return np.where(live, net, np.nan), np.where(live, gross - net, np.nan)


def pn_candidates(Pw, legs: dict[str, np.ndarray]) -> tuple[dict[str, np.ndarray], np.ndarray]:
    """The three books and EW, IV and ERC over them (perps_neutral_portfolio.combine at REWEIGHT, from the first
    day all three have a return), and the common days."""
    from .perps_neutral_portfolio import combine
    common = np.all([np.isfinite(legs[b]) for b in PN_BOOKS], axis=0)
    start = int(np.flatnonzero(common)[0])
    R = np.column_stack([legs[b] for b in PN_BOOKS])
    out = {b: legs[b] for b in PN_BOOKS}
    for m in PN_METHODS:
        out[m] = combine(R, np.zeros(R.shape), Pw.days, m, REWEIGHT, start)["net"]
    return out, common


# ---------------------------------------------------------------- judging

def pbo_of(series: dict[str, np.ndarray]) -> dict | None:
    """T2's CSCV over the columns (rows where all are finite)."""
    M = np.column_stack(list(series.values()))
    M = M[np.isfinite(M).all(1)]
    r = metrics.cscv(M)
    return None if r is None else {"pbo": r["pbo"], "n": r["genomes"], "combos": r["combos"], "days": int(len(M)),
                                   "median_logit": r["median_logit"]}


def judged_pbo(book: str, fams: dict[str, dict | None]) -> dict:
    """The highest PBO of the families the book's rule went through (each pick had to survive every stage); None
    when one is missing."""
    v = [fams.get(f) for f in BOOKS[book]["pbo"]]
    return {"value": None if any(x is None for x in v) else max(x["pbo"] for x in v),
            "families": {f: fams.get(f) for f in BOOKS[book]["pbo"]}}


def conditions(row: dict) -> dict[str, dict]:
    """Step 2's five rows of a book: {id: {"ok", "value"}} with the numbers (the ladder's bars)."""
    la, er, pb = row["late"], row["era"], row["pbo"]["value"]
    fam = row["family"]
    return {"late": {"ok": la["cagr"] > 0, "value": la["cagr"]},
            "era": {"ok": er["cagr"] > 0, "value": er["cagr"]},
            "dsr_all": {"ok": row["dsr_all"] >= DSR_PASS, "value": row["dsr_all"]},
            "dsr_family": {"ok": row[f"dsr_{fam}"] >= DSR_PASS, "value": row[f"dsr_{fam}"]},
            "pbo": {"ok": pb is not None and pb < PBO_MAX, "value": pb}}


def proxy_text(sh: dict, venue: str) -> str:
    """Which periods run on a proxy: the fee (Kraken's whole window, Hyperliquid's switch dates) and the turnover
    priced without a depth file."""
    fee = ("Kraken's 5 bps taker for the whole window (no dated schedule)" if venue == "kraken_futures" else
           "Hyperliquid's 3.5 / 4.5 bps with the 2025-05-01 switch assumed to the quarter")
    yrs = ", ".join(f"{y} {(1 - v['depth']) * 100:.0f} %" for y, v in sh["by_year"].items() if v["depth"] is not None)
    return (f"{fee}; T4's depth (Binance's book standing in for the venue's) on {sh['depth'] * 100:.0f} % of the "
            f"judged turnover, the proxy on the rest ({yrs})")


# ---------------------------------------------------------------- the run

def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    from .. import report
    rep = report.REPORTS / NAME
    if "--report" in argv:
        o = json.loads((rep / "latest.json").read_text(encoding="utf-8"))
        if o.get("books"):
            write_json(o)
        dc.write_results(NAME, markdown(o), HEAD)
        return 0
    register = "--no-register" not in argv
    t_0 = time.time()
    log = lambda s: print(f"[{time.time() - t_0:.0f} s] {s}", flush=True)       # noqa: E731
    from . import daytrade_dt1 as dt
    from . import fam_common as fc
    from . import pit_universe_t5 as t5
    from . import two_leads_t6 as t6
    from . import two_leads_t6b as t6b
    from .. import universe as U
    from .perps_neutral_portfolio import on_calendar

    # The frozen cut, M4H's matrices and the band check, before anything else.
    P, st = m4h.frozen_panel(log=log)
    tag = "_" + st["sha256"][:12]
    X = m4h.build(log, P, tag)
    days = X["days"]
    i0, i1 = m4h.window_rows(days, IS_FROM, IS_TO)
    o0, o1 = m4h.window_rows(days, OOS_FROM, OOS_TO)
    kf = dt.kf_listings()
    listed = {"hyperliquid": X["listed"],
              "kraken_futures": m4h.listed_matrix(days, X["perp"], {s: (f, None) for s, f in kf.items()})}
    check = band_check(X, listed)
    log("band check: " + ", ".join(f"{b} {v['max_diff']}" for b, v in check.items()))
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "prereg": PREREG, "panel": st,
           "check": check, "oos_from": OOS_FROM, "oos_to": OOS_TO, "books": {}}
    if not all(v["ok"] for v in check.values()):
        out["stopped"] = "the band check failed: the rebuilt series differ from the stored ones"
        rep.mkdir(parents=True, exist_ok=True)
        (rep / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
        dc.write_results(NAME, markdown(out), HEAD)
        log(out["stopped"])
        return 1

    # Costs of their era: T4's 1k depth at the latest hour of each decision day (the fill hour's nearest).
    fh = t6b.fill_hours(CUT)
    Dx, Bx = t6b.depth_matrix(days, [t6b.coin_key(s) for s in X["syms"]], fh, DEPTH_USD)
    S = {v: era_cost(venue_fee(days, v), Dx, X["slip"]) for v in ("kraken_futures", "hyperliquid")}
    M = family_matrices(P, tag, log)
    assert np.array_equal(M["days"], days) and list(M["syms"]) == list(X["syms"])
    F = carry_matrices(P)
    del P
    Df, Bf = t6b.depth_matrix(F["days"], [t6b.coin_key(s) for s in F["syms"]], fh, DEPTH_USD)
    Cf = era_cost(np.full(len(F["days"]), FEE_KF), Df, t5.half_spread(F["perp_adv28"]))
    first = kraken_by_coin()
    Lf = coin_listed(F["days"], F["syms"], first)
    Pw = dc.cut_panel(fc.load_panel(), CUT)
    vol = U.median_volume(Pw)
    Dw, Bw = t6b.depth_matrix(Pw.days, [t6b.coin_key(n) for n in Pw.names], fh, DEPTH_USD)
    Cw = era_cost(np.full(Pw.T, FEE_KF), Dw, t5.half_spread(vol))
    Lw = coin_listed(Pw.days, Pw.names, first)
    log("inputs ready")

    # In sample (the Binance universe), every trial's Sharpe, registered before any judged number.
    ins = {}
    for b in ("m4_perps", "m4_hl_small"):
        for case in ("late", "era"):
            ins[f"{b}:{case}"] = m4h.ann_sharpe(m4_run(X, i0, i1, b, S[BOOKS[b]["venue"]], None, case == "late")["ret"])
    Mi = t6.cut_matrices(M, IS_TO)
    r0 = int(np.searchsorted(Mi["days"], dc.us(IS_FROM)))
    for k, x in fa_books(Mi).items():
        ins[f"fa:{k}"] = m4h.ann_sharpe(x[r0:])
    for k in (3, 5):
        ins[f"m4h:k{k}"] = m4h.ann_sharpe(m4h.simulate({**X, "F": np.full(X["R"].shape, np.nan)}, i0, i1, k, 1,
                                                       m4h.ACCOUNTS["230usd"], m4h.FEE["taker"], "base", None)["ret"])
    Fi, Pi = t6.cut_matrices(F, IS_TO), dc.cut_panel(Pw, IS_TO)
    for case in ("late", "era"):
        legs = pn_legs(X, i0, i1, Fi, Pi, S["kraken_futures"], Cf, Cw, None, None, case == "late", on_calendar)
        c, common = pn_candidates(Pi, legs)
        m = common & (Pi.days >= dc.us(PN_IS_FROM))
        ins[f"perps_neutral:{case}"] = dc.sharpe(c["ERC"][m])
        if case == "late":
            for k in ("Carry", "LowVol", "EW", "IV"):
                ins[f"pn:{k}"] = dc.sharpe(c[k][m])
    T = trials_of(ins)
    if register:
        metrics.register(T)
    pools = {f: metrics.trial_pool(None if f == "all" else f, extra=T) for f in ("all", "hand", "small")}
    log(f"{len(T)} trials registered; pool {pools['all']['n_trials']:,}")

    # The judged days.
    od = days[o0:o1 + 1]
    fams: dict[str, dict | None] = {}
    rows = {}
    for b in ("m4_perps", "m4_hl_small"):
        v, hlf = BOOKS[b]["venue"], BOOKS[b]["venue"] == "hyperliquid"
        r = {case: m4_run(X, o0, o1, b, S[v], listed[v], case == "late", hl_funding=hlf) for case in ("late", "era")}
        sh = shares(r["era"]["tr"], Dx[o0:o1 + 1], Bx[o0:o1 + 1], od)
        rows[b] = book_row(b, r["late"]["ret"], r["era"]["ret"], od, sh, pools)
    fb = fa_books(M)
    fams["fa"] = pbo_of({k: x[i0:o1 + 1] for k, x in fb.items()})
    cells = {}
    for k in m4h.KS:
        a = m4h.simulate({**X, "F": np.full(X["R"].shape, np.nan)}, i0, i1, k, 1, m4h.ACCOUNTS["230usd"],
                         m4h.FEE["taker"], "base", None)["ret"]
        z = m4h.simulate({**X, "F": X["F_hl"]}, o0, o1, k, 1, m4h.ACCOUNTS["230usd"], m4h.FEE["taker"], "base",
                         listed["hyperliquid"])["ret"]
        cells[f"k{k}"] = np.r_[a, z]
    fams["m4h"] = pbo_of(cells)
    pn = {}
    for case in ("late", "era"):
        for u, (lx, lf, lw) in (("bin", (None, None, None)), ("kr", (listed["kraken_futures"], Lf, Lw))):
            legs = pn_legs(X, i0, o1, F, Pw, S["kraken_futures"], Cf, Cw, lx, (lf, lw), case == "late", on_calendar)
            pn[(case, u)] = pn_candidates(Pw, legs)
    cal = Pw.days
    jm = (cal >= dc.us(OOS_FROM) + DAY_US) & (cal <= dc.us(OOS_TO) + DAY_US)
    c_late, _ = pn[("late", "kr")]
    c_era, _ = pn[("era", "kr")]
    sh = pn_shares(X, o0, o1, F, Pw, S["kraken_futures"], Cf, Cw, listed["kraken_futures"], Lf, Lw, Dx, Bx, Df, Bf,
                   Dw, Bw)
    rows["perps_neutral"] = book_row("perps_neutral", c_late["ERC"][jm], c_era["ERC"][jm], cal[jm], sh, pools)
    spl = {k: np.where(cal <= dc.us(IS_TO), pn[("late", "bin")][0][k], c_late[k]) for k in c_late}
    win = (cal >= dc.us(PN_IS_FROM)) & (cal <= dc.us(OOS_TO) + DAY_US)
    fams["pn"] = pbo_of({k: x[win] for k, x in spl.items()})
    for b, row in rows.items():
        row["pbo"] = judged_pbo(b, fams)
        row["conditions"] = conditions(row)
        row["band_check"] = check.get(b)
        log(f"{b}: late {row['late']['sharpe']:.2f}, era {row['era']['sharpe']:.2f}, DSR {row['dsr_all']:.3f}, "
            f"PBO {row['pbo']['value']}")
    out.update({"books": rows, "families": fams, "trials": [t["id"] for t in T],
                "trial_counts": {"hand": sum(t["family"] == "hand" for t in T),
                                 "small": sum(t["family"] == "small" for t in T)},
                "pool": {f: {"n_trials": p["n_trials"], "sr0_annual": p["sr0_annual"]} for f, p in pools.items()},
                "in_sample": ins})
    rep.mkdir(parents=True, exist_ok=True)
    (rep / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    write_json(out)
    dc.write_results(NAME, markdown(out), HEAD)
    log("done")
    return 0


def pn_legs(X, t0, t1, F, Pw, Sx, Cf, Cw, lx, lfw, late, on_calendar) -> dict[str, np.ndarray]:
    """perps_neutral's three books on the sweep panel's return days at the era's costs: M4 (m4_perps' rule over
    decision rows t0..t1, booked on d + 1), carry and low vol; lfw (carry's, low vol's listed matrices) or None."""
    days = X["days"]
    m4 = m4_run(X, t0, t1, "m4_perps", Sx, lx, late)["ret"]
    lf, lw = lfw if lfw is not None else (None, None)
    cn, _ = carry_run(F, lf, Cf, late)
    W = lowvol_targets(Pw, lw)
    lv, _ = lowvol_run(Pw, W, Cw, late)
    return {"M4": on_calendar(Pw.days, days[t0:t1 + 1], m4, 1), "Carry": on_calendar(Pw.days, F["days"], cn, 1),
            "LowVol": lv}


def pn_shares(X, o0, o1, F, Pw, Sx, Cf, Cw, lx, Lf, Lw, Dx, Bx, Df, Bf, Dw, Bw) -> dict:
    """perps_neutral's legs on time over the judged days, their traded turnover at depth and beyond, the three legs
    at a third each (information: the share, not a cost)."""
    from . import funding_carry as fcy
    from . import xs_daily as xs
    od = X["days"][o0:o1 + 1]
    tr = m4_run(X, o0, o1, "m4_perps", Sx, lx, False)["tr"]
    has, bey = np.isfinite(Dx[o0:o1 + 1]), Bx[o0:o1 + 1]
    parts = [(tr.sum(1), (tr * has).sum(1), (tr * bey).sum(1), od)]
    jf = (F["days"] >= dc.us(OOS_FROM)) & (F["days"] <= dc.us(OOS_TO))
    s = np.where(Lf, F["s_F7"], np.nan)
    parts.append(tuple(xs.book(F, s, 10, 3, fcy.N_LIQUID, True, C=C)[1][jf]
                       for C in (np.ones(Df.shape), np.isfinite(Df).astype(float), Bf.astype(float))) + (F["days"][jf],))
    W = lowvol_targets(Pw, Lw)
    jw = (Pw.days >= dc.us(OOS_FROM)) & (Pw.days <= dc.us(OOS_TO))       # the close the trade is made at
    v = [lowvol_run(Pw, W, C, False)[1] for C in (np.ones(Dw.shape), np.isfinite(Dw).astype(float), Bw.astype(float))]
    parts.append(tuple(np.r_[x[1:], np.nan][jw] for x in v) + (Pw.days[jw],))    # charged on the next return day
    cat = [np.concatenate([np.nan_to_num(p[i]) / 3 for p in parts]) for i in range(3)]
    return share_rows(*cat, np.concatenate([p[3] for p in parts]))


def book_row(book: str, late: np.ndarray, era: np.ndarray, days: np.ndarray, sh: dict, pools: dict) -> dict:
    """One book's judged numbers: the late case (the tested series, stored), the on-time case at the era's costs,
    the share priced from depth, the DSR over all, hand and small."""
    x = np.asarray(late, dtype=float)
    c = BOOKS[book]
    return {"book": book, "family": c["family"], "venue": c["venue"], "rule": c["rule"],
            "first": dc.day_str(int(days[0])), "last": dc.day_str(int(days[-1])), "days": int(len(x)),
            "late": stats(x, days), "era": {**stats(era, days), "shares": sh, "proxy": proxy_text(sh, c["venue"])},
            **{f"dsr_{f}": metrics.dsr(x, pools[f]) for f in ("all", "hand", "small")},
            "pool_all": pools["all"]["n_trials"], "pool_family": pools[c["family"]]["n_trials"],
            "oos_returns": [round(float(v), 10) for v in x]}


def trials_of(ins: dict[str, float]) -> list[dict]:
    """The 30 trials with their in-sample Sharpes (ids as pre-registered)."""
    ids = {"m4_perps:late": "hand:m4s2:m4_perps:late", "m4_perps:era": "hand:m4s2:m4_perps:era",
           "perps_neutral:late": "hand:m4s2:perps_neutral:late", "perps_neutral:era": "hand:m4s2:perps_neutral:era",
           "m4_hl_small:late": "small:m4s2:m4_hl_small:late", "m4_hl_small:era": "small:m4s2:m4_hl_small:era",
           "m4h:k3": "small:m4s2:pbo:m4h:k3", "m4h:k5": "small:m4s2:pbo:m4h:k5"}
    out = []
    for k, v in ins.items():
        if k in ids:
            out.append(trial(ids[k], v))
        elif k.startswith("fa:"):
            m, n, kind = k[3:].split(":")
            out.append(trial(f"hand:m4s2:pbo:fa:{m}:{n}:{kind}", v))
        elif k.startswith("pn:"):
            out.append(trial(f"hand:m4s2:pbo:pn:{k[3:]}", v))
    return out


def write_json(o: dict) -> None:
    """results/m4_step2.json: per book the tested series and what the ladder shows (its rows read only this)."""
    keep = ("book", "family", "venue", "rule", "first", "last", "days", "late", "era", "dsr_all", "dsr_hand",
            "dsr_small", "pool_all", "pool_family", "pbo", "conditions", "oos_returns")
    d = {"generated": o["generated"], "prereg": PREREG, "panel": (o.get("panel") or {}).get("sha256"),
         "pool": o.get("pool"), "books": {b: {k: r.get(k) for k in keep} for b, r in o["books"].items()}}
    for r in d["books"].values():
        fs = (r.get("pbo") or {}).get("families") or {}
        r["pbo"] = {**r["pbo"], "families": {f: v if v is None else {**v, "label": FAMILIES[f].split(":")[0]}
                                             for f, v in fs.items()}}
    (dc.RESULTS / f"{NAME}.json").write_text(json.dumps(d, indent=1, default=float), encoding="utf-8")


# ---------------------------------------------------------------- the results file

HEAD = """# M4S2: step 2 of the readiness ladder for m4_perps, perps_neutral and m4_hl_small

Pre-registered in `results/m4_step2_prereg.md` (committed first). Code: `lab.experiments.m4_step2`, tests
`tests/test_m4_step2.py`; the ladder reads `results/m4_step2.json`. The tables below the marker are generated.
"""

LABEL = {"late": "one close late still positive", "era": "costs of their era", "dsr_all": "DSR over R5 >= 0.95",
         "dsr_family": "DSR over its family >= 0.95", "pbo": "PBO < 0.2"}


def _pc(v) -> str:
    return "n/a" if v is None or not math.isfinite(v) else f"{v * 100:.1f} %"


def cond_text(b: dict, cid: str) -> str:
    c, la, er = b["conditions"][cid], b["late"], b["era"]
    if cid == "late":
        return f"late CAGR {_pc(la['cagr'])} a year, Sharpe {la['sharpe']:.2f}, drawdown {_pc(la['max_dd'])}"
    if cid == "era":
        return f"on time at the era's costs CAGR {_pc(er['cagr'])}, Sharpe {er['sharpe']:.2f}; {er['proxy']}"
    if cid == "dsr_all":
        return f"{b['dsr_all']:.3f} over {b['pool_all']:,} trials"
    if cid == "dsr_family":
        return f"{c['value']:.3f} over the {b['family']} family's {b['pool_family']:,}"
    f = b["pbo"]["families"]
    return ("not measured" if c["value"] is None else f"{c['value']:.2f} (the highest of: " + "; ".join(
        f"{FAMILIES[k].split(':')[0]} {v['pbo']:.2f} over {v['n']}" for k, v in f.items() if v) + ")")


def markdown(o: dict) -> str:
    md = [f"Generated {o['generated']}. M4L's frozen panel {((o.get('panel') or {}).get('sha256') or '')[:12]} "
          f"(built {(o.get('panel') or {}).get('built')}), cut at {CUT}; judged decision days {OOS_FROM} to {OOS_TO} "
          "(perps_neutral the same days as return days); in sample 2022-01-01 to 2023-12-31 on the Binance universe; "
          "nothing from 2026-07-01 read.", ""]
    ck = o.get("check") or {}
    md.append("Band check (on time at the band's costs against the stored series): " + "; ".join(
        f"{b} {'matches' if v['ok'] else 'DIFFERS'} over {v['days']} days (largest difference "
        f"{'n/a' if v['max_diff'] is None else format(v['max_diff'], '.1e')})" for b, v in ck.items()) + ".")
    if o.get("stopped"):
        return "\n".join(md + ["", f"**Stopped**: {o['stopped']}. No trial was registered, no number judged."]) + "\n"
    p = o["pool"]
    md += ["", f"{len(o['trials'])} trials in R5's registry ({o['trial_counts']['hand']} hand, "
           f"{o['trial_counts']['small']} small, with their in-sample Sharpes, before any judged number); pool "
           f"{p['all']['n_trials']:,} (hand {p['hand']['n_trials']:,}, small {p['small']['n_trials']:,}), noise bar "
           f"{p['all']['sr0_annual']:.2f} a year.", "", "## Step 2, one row per book and requirement", "",
           "| book | requirement | result | number |", "|---|---|---|---|"]
    for b, r in o["books"].items():
        for cid in CONDS:
            md.append(f"| {b} | {LABEL[cid]} | {'pass' if r['conditions'][cid]['ok'] else 'fail'} | "
                      f"{cond_text(r, cid).replace('|', '/')} |")
    md += ["", "## The cases", "", "| book | case | Sharpe | CAGR | max DD | 2024 | 2025 | 2026 |",
           "|---|---|---|---|---|---|---|---|"]
    for b, r in o["books"].items():
        for case, lab in (("late", "one close late, era costs"), ("era", "on time, era costs")):
            x = r[case]
            y = x.get("by_year") or {}
            md.append(f"| {b} | {lab} | {x['sharpe']:.2f} | {_pc(x['cagr'])} | {_pc(x['max_dd'])} | "
                      + " | ".join(f"{y[str(k)]:.2f}" if str(k) in y else "n/a" for k in YEARS) + " |")
    md += ["", "DSR of the late case (higher is better): over all, hand and small.", "",
           "| book | family | DSR all | DSR hand | DSR small |", "|---|---|---|---|---|"]
    for b, r in o["books"].items():
        md.append(f"| {b} | {r['family']} | {r['dsr_all']:.3f} | {r['dsr_hand']:.3f} | {r['dsr_small']:.3f} |")
    md += ["", "## Costs: the share of the judged turnover priced from T4's depth (on time)", "",
           "| book | at depth | beyond the hour's depth | proxy by year |", "|---|---|---|---|"]
    for b, r in o["books"].items():
        s = r["era"]["shares"]
        md.append(f"| {b} | {_pc(s['depth'])} | {_pc(s['beyond'])} | " + ", ".join(
            f"{y} {_pc(None if v['depth'] is None else 1 - v['depth'])}" for y, v in s["by_year"].items()) + " |")
    md += ["", "## PBO (CSCV, 16 blocks, every split, in sample and judged days together)", "",
           "| family | PBO | candidates | splits | days | median logit |", "|---|---|---|---|---|---|"]
    for k, v in o["families"].items():
        md.append(f"| {FAMILIES[k]} | " + ("not measured | | | | |" if v is None else
                  f"{v['pbo']:.2f} | {v['n']} | {v['combos']:,} | {v['days']} | {v['median_logit']:.2f} |"))
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    sys.exit(main())
