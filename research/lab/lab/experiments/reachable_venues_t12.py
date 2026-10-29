"""T12: lead A on venues the owner can reach (Hyperliquid, Kraken Futures), against Binance on the same days.

Pre-registered in results/reachable_venues_t12_prereg.md; results in results/reachable_venues_t12.md.

    PYTHIA_CACHE=<xs_daily panel cache> PYTHIA_AGENT_OUT=<panel cache> \
        flock <heavy lock> python -m lab.experiments.reachable_venues_t12 [--refit] [--no-register]

T6's lead A (M4 reg7n, carry F7, low vol on PIT50, ERC monthly, one close late) with each venue's coins, funding
and fees: a coin is on a venue from the UTC day after its first record there (Hyperliquid's first settled
funding; Kraken the later of openingDate and its first funding) and, a delisted Hyperliquid perp, until the day of
its last settlement; M4 and carry keep the 100 most liquid by Binance perp volume among those coins, low vol T5's
PIT50 among them. Funding is the venue's settlements (Hyperliquid 8-hourly to 2023-06, hourly after; Kraken
hourly) summed over T6's holding windows; costs the venue's base taker of its era plus T5's half-spread tier one
tier wider. Prices are Binance's. Listings and funding come from T12b's collector (<free>/perps_all, nothing is
downloaded). ERC's trailing window takes Binance's legs for the days before a venue's legs start. M4's reg7n is
refit as in T6b (the 2026-10-07 score cache is gone). Every input is cut at 2026-06-30 24:00; the lockbox is
never read. Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import metrics
from . import director_common as dc
from . import fam_common as fc
from . import pit_universe_t5 as t5
from . import two_leads_t6 as t6

NAME = "reachable_venues_t12"
PREREG = "results/reachable_venues_t12_prereg.md"
VENUES = {"hyperliquid": "Hyperliquid", "kraken_futures": "Kraken Futures"}
TAG = {"hyperliquid": "hyperliquid", "kraken_futures": "kraken"}
KRAKEN_FEE = 0.0005                     # Kraken Futures' base taker (its public schedule, UNVERIFIED for the window)
CUT_US = dc.us("2026-07-01")            # every input before 2026-07-01 00:00 UTC
STEPS = ("universe", "funding", "full")  # the venue's coins; plus its funding; plus its costs (the full ERC)
TRIALS = t6.CANDIDATES + ("ERC_universe", "ERC_funding")
SURVIVE_SHARPE, KEEP, PARTLY_SHARPE = 1.0, 0.5, 0.5
DAY_US, HOUR_US = fc.DAY_US, 3_600_000_000
NEVER = np.iinfo(np.int64).max


# ---------------------------------------------------------------- listings and the universe

def venue_dir(venue: str) -> Path:
    from ..collect import pit
    return pit.FREE / "perps_all" / venue


def read_doc(venue: str) -> dict:
    return json.loads((venue_dir(venue) / "listings.json").read_text(encoding="utf-8"))


def listings(venue: str, doc: dict) -> dict[str, tuple[int, int | None]]:
    """{base: (first record us, start of the day of the last settlement or None)} from the collector's listings
    (Hyperliquid's kPEPE is PEPE there). Kraken's first record is the later of openingDate and its first funding.
    A base listed twice keeps the earliest first and the latest end."""
    out: dict[str, tuple[int, int | None]] = {}
    for coin, e in sorted(doc.items()):
        first = e.get("first_ts_us")
        if first is None:
            continue
        if venue == "kraken_futures" and e.get("opening_us"):
            first = max(int(first), int(e["opening_us"]))
        end = None
        if e.get("delisted"):
            if e.get("last_ts_us") is None:
                continue
            end = int(e["last_ts_us"]) // DAY_US * DAY_US
        b = e.get("base") or coin
        if b in out:
            f0, e0 = out[b]
            first, end = min(int(first), f0), (None if end is None or e0 is None else max(end, e0))
        out[b] = (int(first), end)
    return out


def coin_key(name: str) -> str:
    """The coin of a Binance panel or xs_daily symbol (1000PEPEUSDT is PEPE); "" for an older asset of a reused
    ticker (NAME~0), which is on no venue but Binance."""
    from ..collect import book_depth as bd
    return "" if "~" in name else bd.base_of(name)


def on_venue(days: np.ndarray, keys: list[str], lst: dict) -> np.ndarray:
    """(T, N) a coin is on the venue on UTC day d when its first record falls before the start of d and d starts
    before the day of its last settlement (a delisted perp). Never before its first record."""
    first = np.array([lst[k][0] if k in lst else NEVER for k in keys], dtype=np.int64)
    end = np.array([(lst[k][1] if lst[k][1] is not None else NEVER) if k in lst else NEVER for k in keys],
                   dtype=np.int64)
    d = np.asarray(days, dtype=np.int64)[:, None]
    return (first[None, :] < d) & (d < end[None, :])


# ---------------------------------------------------------------- funding at each venue's schedule

def read_funding(venue: str, doc: dict, cut: int = CUT_US) -> pl.DataFrame:
    """(base, ts_us, rate) every settlement before `cut` (a share of the price, positive when longs pay); a base
    with two perps keeps the first coin's row of an hour."""
    frames = []
    for p in sorted((venue_dir(venue) / "funding").glob("*.parquet")):
        f = pl.read_parquet(p, columns=["ts_us", "coin", "funding_rate"]).filter(pl.col("ts_us") < cut)
        if f.height:
            frames.append(f)
    if not frames:
        return pl.DataFrame(schema={"base": pl.String, "ts_us": pl.Int64, "rate": pl.Float64})
    base = {c: (e.get("base") or c) for c, e in doc.items()}
    f = pl.concat(frames, how="vertical_relaxed").drop_nulls("funding_rate")
    f = f.with_columns(base=pl.col("coin").replace_strict(base, default=pl.col("coin")), rate=pl.col("funding_rate"))
    return f.sort("coin", "ts_us").unique(["base", "ts_us"], keep="first").select("base", "ts_us", "rate")


def daily(fund: pl.DataFrame, kind: str) -> pl.DataFrame:
    """(base, day, f) the settlements summed per day as T6 sums Binance's: known (settled in (start of d, start of
    d + 1], known at the close of d, carry's signal), hold (settled in (01:00 of d + 1, 01:00 of d + 2], paid while
    an xs book decided at d is held) or utc (settled in [start of d, start of d + 1), the low-vol panel's day)."""
    ts = pl.col("ts_us")
    day = {"known": (ts - 1) // DAY_US * DAY_US,
           "hold": (ts - HOUR_US - 1) // DAY_US * DAY_US - DAY_US,
           "utc": ts // DAY_US * DAY_US}[kind]
    return fund.with_columns(day=day).group_by("base", "day").agg(f=pl.col("rate").sum())


def matrix(d: pl.DataFrame, days: np.ndarray, keys: list[str], fill: float = np.nan) -> np.ndarray:
    """(T, N) of a daily frame on a calendar and the columns' coins (a coin in several columns in each)."""
    out = np.full((len(days), len(keys)), fill)
    cols: dict[str, list[int]] = {}
    for j, k in enumerate(keys):
        if k:
            cols.setdefault(k, []).append(j)
    d = d.filter(pl.col("base").is_in(list(cols)))
    t = np.searchsorted(days, d["day"].to_numpy())
    hit = (t < len(days)) & (days[np.minimum(t, len(days) - 1)] == d["day"].to_numpy())
    for i, (b, f) in enumerate(zip(d["base"].to_list(), d["f"].to_numpy())):
        if hit[i]:
            out[t[i], cols[b]] = f
    return out


def fund7(known: pl.DataFrame, days: np.ndarray, keys: list[str]) -> np.ndarray:
    """(T, N) the venue's funding summed over the 7 days known at the close of each day (days with a settlement
    only, like Binance's fund7), NaN with none."""
    dense = np.arange(int(days[0]) - 7 * DAY_US, int(days[-1]) + DAY_US, DAY_US, dtype=np.int64)
    f7 = fc.rolling(matrix(known, dense, keys), 7, 1, how="sum")
    return f7[np.searchsorted(dense, days)]


# ---------------------------------------------------------------- costs

def venue_fee(venue: str, days: np.ndarray) -> np.ndarray:
    from .hl_funding_t11 import hl_fee
    return hl_fee(days) if venue == "hyperliquid" else np.full(len(days), KRAKEN_FEE)


def wider_half_spread(vol: np.ndarray) -> np.ndarray:
    """T5's half-spread tier one tier wider (thinner books, assumed): 1 -> 3, 3 -> 10, 10 -> 25, 25 -> 50 bps;
    the widest tier (50 bps) stays."""
    tiers = [hs for _, hs in t5.SPREAD_TIERS] + [t5.SPREAD_BELOW]
    h = t5.half_spread(vol)
    out = h.copy()
    for a, b in zip(tiers[:-1], tiers[1:]):
        out = np.where(h == a, b, out)
    return out


def venue_cost(venue: str, days: np.ndarray, vol: np.ndarray) -> np.ndarray:
    return venue_fee(venue, days)[:, None] + wider_half_spread(vol)


# ---------------------------------------------------------------- the legs

def lead_zeros_out(x: np.ndarray) -> np.ndarray:
    """A venue leg has a return from its first day with a position: the leading days of nothing held are NaN."""
    x = np.asarray(x, dtype=float).copy()
    live = np.flatnonzero(np.isfinite(x) & (x != 0))
    x[:live[0] if len(live) else len(x)] = np.nan
    return x


def _xs(b: tuple) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    g, cost, fu, _ = b
    return g + fu - cost, cost, fu


def xs_venue(M: dict, F: dict, venue: str, lst: dict, fund: pl.DataFrame) -> dict:
    """M4 and carry on one venue at each step: {step: {"M4": (net, cost, funding), "Carry": ...}} on the decision
    days of M and F, and the eligible counts {"M4": (T,), "Carry": (T,)}."""
    from . import funding_carry as fcy
    from . import xs_daily as xs
    hold, known = daily(fund, "hold"), daily(fund, "known")
    out: dict = {s: {} for s in STEPS}
    keys = [coin_key(s) for s in M["syms"]]
    on = on_venue(M["days"], keys, lst)
    sc = np.where(on, M["reg7n"], np.nan)                # the universe of day d decides at the close of d
    Mv = {**M, "fund": matrix(hold, M["days"], keys, 0.0)}
    Cb, Cv = t6.xs_cost(M), venue_cost(venue, M["days"], M["perp_adv28"])
    late = fcy.late(sc)
    for s, (m, C) in zip(STEPS, ((M, Cb), (Mv, Cb), (Mv, Cv))):
        out[s]["M4"] = _xs(xs.book_buffer(m, late, 10, 0.5, 100, C=C))
    counts = {"M4": np.isfinite(sc).sum(1)}
    keys = [coin_key(s) for s in F["syms"]]
    on = on_venue(F["days"], keys, lst)
    ok = on & np.isfinite(F["s_F7"])
    sb = np.where(ok, F["s_F7"], np.nan)
    sv = np.where(ok, -fund7(known, F["days"], keys), np.nan)
    Fv = {**F, "fund": matrix(hold, F["days"], keys, 0.0)}
    Cb, Cv = t6.xs_cost(F), venue_cost(venue, F["days"], F["perp_adv28"])
    for s, (f, score, C) in zip(STEPS, ((F, sb, Cb), (Fv, sv, Cb), (Fv, sv, Cv))):
        out[s]["Carry"] = _xs(xs.book(f, fcy.late(score), 10, 3, fcy.N_LIQUID, True, C=C))
    counts["Carry"] = np.isfinite(sv).sum(1)
    return {"legs": out, "counts": counts}


def xs_binance(M: dict, F: dict) -> dict:
    """T6's M4 and carry late at the costs of its era: {"M4": (net, cost, funding), "Carry": ...}."""
    from . import funding_carry as fcy
    from . import xs_daily as xs
    return {"M4": _xs(xs.book_buffer(M, fcy.late(M["reg7n"]), 10, 0.5, 100, C=t6.xs_cost(M))),
            "Carry": _xs(xs.book(F, fcy.late(F["s_F7"]), 10, 3, fcy.N_LIQUID, True, C=t6.xs_cost(F)))}


def xs_unlisted(M: dict, F: dict, lst: dict) -> dict:
    """{book: (decision days, one-way turnover on coins not on the venue the day it trades, all one-way turnover)}
    of T6's Binance books."""
    from . import funding_carry as fcy
    from . import xs_daily as xs
    out = {}
    for b, X, run in (("M4", M, lambda X, C: xs.book_buffer(X, fcy.late(X["reg7n"]), 10, 0.5, 100, C=C)),
                      ("Carry", F, lambda X, C: xs.book(X, fcy.late(X["s_F7"]), 10, 3, fcy.N_LIQUID, True, C=C))):
        off = (~on_venue(X["days"], [coin_key(s) for s in X["syms"]], lst)).astype(float)
        out[b] = (X["days"], run(X, off)[1], run(X, np.ones(off.shape))[1])
    return out


def lowvol_venue(P: fc.Panel, vol: np.ndarray, delist, venue: str, lst: dict, fund: pl.DataFrame) -> dict:
    """The low-vol leg on the venue's PIT50 at each step {step: (net, cost)}, its funding a day at the full step,
    and the PIT50 size a day."""
    from .. import universe as U
    from .two_leads_t6b import run_costs
    keys = [coin_key(n) for n in P.names]
    on = on_venue(P.days, keys, lst)
    uni = U.pit(P, 50, table=delist, vol=np.where(on, vol, np.nan))
    Cb, Cv = t6.era_cost(vol), venue_cost(venue, P.days, vol)
    Pv = dataclasses.replace(P, funding=matrix(daily(fund, "utc"), P.days, keys, 0.0))
    a = run_costs(P, "lowvol", uni, 50, {"universe": Cb})
    b = run_costs(Pv, "lowvol", uni, 50, {"funding": Cb, "full": Cv})
    z = run_costs(dataclasses.replace(P, funding=np.zeros_like(P.funding)), "lowvol", uni, 50, {"full": Cv})
    live = np.arange(P.T) > 100
    legs = {s: np.where(live, v[0], np.nan) for s, v in {**a, **b}.items()}
    return {"legs": legs, "funding": np.where(live, b["full"][0] - z["full"][0], np.nan), "counts": uni.sum(1)}


def lowvol_binance(P: fc.Panel, vol: np.ndarray, delist, lsts: dict) -> dict:
    """T6's low-vol leg on PIT50 late at its era's costs, its funding a day and per venue the turnover on coins the
    venue does not list (unlisted, all)."""
    from .. import universe as U
    from .two_leads_t6b import run_costs
    uni = U.pit(P, 50, table=delist, vol=vol)
    keys = [coin_key(n) for n in P.names]
    Cs = {"era": t6.era_cost(vol), "all": np.ones((P.T, P.N))}
    for v, lst in lsts.items():
        Cs[v] = (~on_venue(P.days, keys, lst)).astype(float)
    r = run_costs(P, "lowvol", uni, 50, Cs)
    z = run_costs(dataclasses.replace(P, funding=np.zeros_like(P.funding)), "lowvol", uni, 50, {"era": Cs["era"]})
    live = np.arange(P.T) > 100
    return {"net": np.where(live, r["era"][0], np.nan),
            "funding": np.where(live, r["era"][0] - z["era"][0], np.nan),
            "unlisted": {v: (r[v][1], r["all"][1]) for v in lsts}}


# ---------------------------------------------------------------- the book on a venue

def mixed_combos(days: np.ndarray, R_v: np.ndarray, R_b: np.ndarray, methods=t6.METHODS) -> dict[str, np.ndarray]:
    """The combinations of a venue's three legs (T, 3): from the first day all three have a return, weighted on
    the trailing 90 days where the days before that start are Binance's legs R_b (the risk estimate then);
    returns are always the venue's (NaN before its start)."""
    from .perps_neutral_portfolio import combine
    ok = np.isfinite(R_v).all(1)
    if not ok.any():
        return {m: np.full(len(days), np.nan) for m in methods}
    start = int(np.flatnonzero(ok)[0])
    R = R_v.copy()
    R[:start] = R_b[:start]
    TV = np.zeros(R.shape)
    out = {}
    for m in methods:
        x = combine(R, TV, days, m, t6.REWEIGHT_COST, start)["net"]
        x[:start] = np.nan
        out[m] = x
    return out


def series(days: np.ndarray, legs: dict[str, dict[str, np.ndarray]], binance: dict[str, np.ndarray]) -> dict:
    """{name: (T,)} a venue's candidates (the full step's legs and EW, IV, ERC) and the decomposition's ERCs."""
    Rb = np.column_stack([binance[b] for b in t6.BOOKS])
    out = {b: legs["full"][b] for b in t6.BOOKS}
    out.update(mixed_combos(days, np.column_stack([legs["full"][b] for b in t6.BOOKS]), Rb))
    for s, name in (("universe", "ERC_universe"), ("funding", "ERC_funding")):
        out[name] = mixed_combos(days, np.column_stack([legs[s][b] for b in t6.BOOKS]), Rb, ("ERC",))["ERC"]
    return out


# ---------------------------------------------------------------- judging

def trial_rows(venue_trials: dict[str, dict[str, float | None]]) -> list[dict]:
    """The 17 trials: per venue its 8 (Hyperliquid with the in-sample Sharpe, Kraken counted only) and Binance's ERC
    over Kraken's overlap (counted only)."""
    rows = []
    for v, d in venue_trials.items():
        for k in TRIALS:
            rows.append({"id": f"hand:t12:{TAG[v]}:{k}", "family": "hand", "n": 1, "sharpe": d.get(k),
                         "source": PREREG})
    rows.append({"id": "hand:t12:binance:erc_kraken_days", "family": "hand", "n": 1, "sharpe": None,
                 "source": PREREG})
    return rows


def verdict(c: dict) -> str:
    """survive when every condition holds, partly when the Sharpe is above 0.5 and the 5 % above 0, no otherwise."""
    if all(c["conditions"].values()):
        return "survives"
    if c["sharpe"] > PARTLY_SHARPE and c["boot_lo"] > 0:
        return "partly"
    return "no"


def judge(days: np.ndarray, x_v: np.ndarray, x_b: np.ndarray, btc: np.ndarray, years: bool,
          p_all: dict, p_fam: dict) -> dict:
    """The venue's ERC against Binance's on the same days (both finite): kept share, the difference's band, the
    survive rule, DSRs and the Sharpe the bar needs."""
    m = np.isfinite(x_v) & np.isfinite(x_b)
    v, b = x_v[m], x_b[m]
    sv, sb = dc.sharpe(v), dc.sharpe(b)
    lo, hi, _ = dc.boot_band(v)
    dlo, dhi, dshare = dc.boot_band(v, b)
    corr = float(np.corrcoef(v, btc[m])[0, 1]) if len(v) > 2 else float("nan")
    yrs = {}
    cond = {"Sharpe 1.0 or more": sv >= SURVIVE_SHARPE,
            "at least half of Binance's": sv >= KEEP * sb,
            "bootstrap 5 % above 0": lo > 0, "correlation with BTC within +-0.3": abs(corr) <= t6.GATE_CORR}
    if years:
        yr = dc.years_of(days[m])
        yrs = {y: dc.sharpe(v[yr == y]) for y in t6.YEARS}
        cond["positive in 2 of 2024, 2025, 2026"] = sum(s > 0 for s in yrs.values()) >= t6.GATE_YEARS
    out = {"days": int(m.sum()), "from": dc.day_str(days[m][0]), "to": dc.day_str(days[m][-1]),
           "sharpe": sv, "binance": sb, "kept": sv / sb if sb else float("nan"), "diff": sv - sb,
           "diff_band": [dlo, dhi], "diff_share_above_0": dshare, "boot_lo": lo, "boot_hi": hi, "corr_btc": corr,
           "years": yrs, "conditions": cond, "venue": t6.stats_of(v), "binance_stats": t6.stats_of(b),
           "dsr_all": metrics.dsr(v, p_all), "dsr_family": metrics.dsr(v, p_fam),
           "needed_sharpe": {"all": t6.needed_sharpe(v, p_all), "family": t6.needed_sharpe(v, p_fam)}}
    out["verdict"] = verdict(out)
    return out


def windows(days: np.ndarray, s: dict[str, np.ndarray], venue: str) -> dict[str, np.ndarray]:
    """The venue's windows: from the first day all three legs have a return; Hyperliquid in sample to 2023-12-31
    and validation, Kraken only the overlap to 2026-06-30."""
    common = np.all([np.isfinite(s[b]) for b in t6.BOOKS], axis=0)
    to = days <= dc.us(t6.VAL_TO)
    if venue == "hyperliquid":
        return {"is": common & (days <= dc.us(t6.IS_TO)), "judged": common & (days >= dc.us(t6.VAL_FROM)) & to}
    return {"is": np.zeros(len(days), dtype=bool), "judged": common & to}


def evaluate(days: np.ndarray, S: dict[str, dict[str, np.ndarray]], B: dict[str, np.ndarray], btc: np.ndarray,
             register: bool = True, log=print) -> dict:
    """S: {venue: series()}, B: Binance's candidates. The 17 trials registered (Hyperliquid's with their in-sample
    Sharpe) before any judged-window number is computed; then every venue judged against Binance."""
    W = {v: windows(days, s, v) for v, s in S.items()}
    vt = {v: {k: (t6.stats_of(s[k][W[v]["is"]])["sharpe"] if v == "hyperliquid" else None) for k in TRIALS}
          for v, s in S.items()}
    trials = trial_rows(vt)
    if register:
        metrics.register(trials)                         # before any judged-window number exists
    log("  in sample (Hyperliquid): " + ", ".join(f"{k} {x:.2f}" for k, x in vt.get("hyperliquid", {}).items()))
    p_all, p_fam = t6.pools(trials, "hand")
    out = {"trials": [t["id"] for t in trials], "pool_all": t6._pool(p_all), "pool_family": t6._pool(p_fam),
           "venues": {}}
    for v, s in S.items():
        w = W[v]
        r = judge(days, np.where(w["judged"], s["ERC"], np.nan),
                  np.where(w["judged"], B["ERC"], np.nan), btc, v == "hyperliquid", p_all, p_fam)
        same = w["judged"] & np.isfinite(B["ERC"])
        r["table"] = {k: {"is": t6.stats_of(s[k][w["is"]]) if w["is"].any() else None,
                          "judged": t6.stats_of(s[k][same])} for k in TRIALS}
        r["binance_table"] = {k: {"is": t6.stats_of(B[k][w["is"] & np.isfinite(B[k])]) if w["is"].any() else None,
                                  "judged": t6.stats_of(B[k][same])} for k in t6.CANDIDATES}
        out["venues"][v] = r
    return out


# ---------------------------------------------------------------- reported, not judged

def by_month(days: np.ndarray, lst: dict, keys_panel: list[str], counts: dict[str, np.ndarray],
             first: str, last: str = t6.VAL_TO) -> list[dict]:
    """Per first day of a month: the coins on the venue, those with Binance data on the panel and each leg's
    eligible count (counts on the panel's calendar)."""
    rows = []
    have = set(k for k in keys_panel if k)
    for t, d in enumerate(days):
        s = dc.day_str(d)
        if not (first <= s <= last) or not s.endswith("-01"):
            continue
        on = [b for b, (f, e) in lst.items() if f < d and (e is None or d < e)]
        rows.append({"month": s[:7], "on the venue": len(on), "with Binance data": sum(b in have for b in on),
                     **{f"{k} eligible": int(c[t]) if np.isfinite(c[t]) else 0 for k, c in counts.items()}})
    return rows


def ann(x: np.ndarray, m: np.ndarray) -> float:
    x = np.where(m, x, np.nan)
    return float(np.nanmean(x) * 365) if np.isfinite(x).any() else float("nan")


# ---------------------------------------------------------------- the report

def _pct(v) -> str:
    return t6._pct(v)


def _row(name: str, st: dict | None) -> str:
    return "n/a" if st is None else f"{st['sharpe']:.2f} / {_pct(st['cagr'])} / {_pct(st['max_dd'])}"


def markdown(out: dict) -> str:
    md = [f"Generated {out['generated']}. Data: T12b's collector ({out['data_at']}), Binance's prices and volumes "
          f"from the lab's panels, every input cut at {t6.VAL_TO} 24:00 UTC, the lockbox not read. Costs: "
          f"{out['costs']}. Binance check: {out['check']}.\n",
          "## Which venue can be reached (as the venues state it; no account, key or legal opinion)\n"]
    md += [f"- **{k}**: {v}" for k, v in out["reach"].items()]
    md.append("")
    for v, r in out["venues"].items():
        name = VENUES[v]
        span = ("validation" if v == "hyperliquid" else "the overlap, inside validation (about eight months: a "
                "short record, not a validation)")
        md.append(f"## {name}: {r['verdict'].upper()}\n")
        md.append(f"ERC over {span}, {r['from']} to {r['to']} ({r['days']} days): Sharpe {r['sharpe']:.2f} against "
                  f"Binance's {r['binance']:.2f} on the same days, kept share {r['kept']:.2f}, difference "
                  f"{r['diff']:+.2f} (90 % band {r['diff_band'][0]:+.2f} to {r['diff_band'][1]:+.2f}); "
                  f"{_pct(r['venue']['cagr'])} a year, drawdown {_pct(r['venue']['max_dd'])}; bootstrap 5 % / 95 % "
                  f"{r['boot_lo']:.2f} / {r['boot_hi']:.2f}; correlation with BTC {r['corr_btc']:+.2f}" +
                  ("; by year " + ", ".join(f"{y} {s:.2f}" for y, s in r["years"].items()) if r["years"] else "") +
                  f". DSR {r['dsr_all']:.3f} over all {out['pool_all']['n_trials']:,} trials, {r['dsr_family']:.3f} "
                  f"over the hand family's {out['pool_family']['n_trials']:,} (pass at 0.95, higher is better); the "
                  f"bar needs a Sharpe of about {r['needed_sharpe']['all']:.2f} / {r['needed_sharpe']['family']:.2f} "
                  f"on as many days.\n")
        md.append(dc.table([{"condition": k, "holds": ok} for k, ok in r["conditions"].items()],
                           ["condition", "holds"]) + "\n")
        t = []
        for k in TRIALS:
            x = r["table"][k]
            bx = r["binance_table"].get(k)
            t.append({"candidate": k, "in sample Sharpe / CAGR / DD": _row(k, x["is"]),
                      "judged window Sharpe / CAGR / DD": _row(k, x["judged"]),
                      "Binance, same days": _row(k, bx["judged"]) if bx else ""})
        md.append(dc.table(t, list(t[0])) + "\n")
        d = r["decomposition"]
        md.append(f"Decomposition of the ERC over the judged days: Binance {d['binance']:.2f}, the venue's coins "
                  f"{d['universe']:.2f}, plus its funding {d['funding']:.2f}, plus its costs {d['full']:.2f}.\n")
        t = [{"leg": b, "venue": f"{_pct(f['venue'])}", "Binance, same days": f"{_pct(f['binance'])}",
              "Binance turnover on coins the venue does not list": _pct(r["unlisted"][b])}
             for b, f in r["funding"].items()]
        md.append("Net funding a year over the judged days (received minus paid, a share of the leg's capital), and "
                  "the share of T6's Binance book's one-way turnover in coins the venue does not list that day:\n")
        md.append(dc.table(t, list(t[0])) + "\n")
        md.append(f"Coins on {name} by month (with Binance data: on the lab's panel; eligible: M4 and carry coins "
                  "with a score, low vol the PIT50 size):\n")
        md.append(dc.table(r["months"], list(r["months"][0])) + "\n")
    lk = out.get("leak")
    md.append("## Checks\n")
    md.append("- T1's leak harness on the low-vol weight function on Hyperliquid's PIT50: " +
              ((("no leak" if lk["ok"] else f"LEAK {lk['first']}") + f" ({lk['runs']} runs)") if lk else "not run") +
              "; M4's scores and carry's xs_daily features are not covered by T1.")
    md.append(f"- Trials (R5's registry, hand family, before any judged number): {', '.join(out['trials'])}.\n")
    return "\n".join(md) + "\n"


REACH = {"Binance USD-M": "the training plan's premise: not open to German retail customers (UNVERIFIED here).",
         "Kraken Futures": "its instrument list names its EU platforms per contract and a `countriesBanned` field; "
                           "T12b's collector keeps neither, so this run could not read them (UNVERIFIED).",
         "Hyperliquid": "a decentralised venue whose terms name the restricted places; not read in this run, "
                        "nothing downloaded (UNVERIFIED)."}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    register = "--no-register" not in argv
    t0 = time.time()
    from .. import report
    from .. import universe as U
    from ..collect import book_depth
    from ..leak import checks
    from . import funding_carry as fcy
    from . import two_leads_t6b as t6b
    from . import xs_daily as xs
    health = json.loads((venue_dir("hyperliquid").parent / "health.json").read_text(encoding="utf-8"))
    for v in VENUES:
        h = health["tables"][v]
        if h.get("left") or not h.get("schema_ok") or h.get("done") != h.get("coins"):
            raise SystemExit(f"{v}: the collector is not done ({h}); stopped")
    docs = {v: read_doc(v) for v in VENUES}
    lsts = {v: listings(v, docs[v]) for v in VENUES}
    funds = {v: read_funding(v, docs[v]) for v in VENUES}
    delist = book_depth.read_delistings()
    delist = delist if len(delist) else None

    # M4 and carry: T6b's refit reg7n on the panel cut at VAL_TO, carry's matrices cut there
    Px = xs.build_panel().filter(pl.col("day") <= dc.us(t6.VAL_TO))
    Px, _ = xs.add_net_labels(Px)
    path = report.REPORTS / NAME / "reg7n_scores.parquet"
    if path.exists() and "--refit" not in argv:
        S = pl.read_parquet(path)
    else:
        S = t6b.reg7n_scores(Px)
        path.parent.mkdir(parents=True, exist_ok=True)
        S.write_parquet(path)
    E = xs.ranked(Px.with_columns(adv28_raw=pl.col("adv28"), r1_raw=pl.col("r1"), r28_raw=pl.col("r28"),
                                  fund7_raw=pl.col("fund7"), vol28_raw=pl.col("vol28")))
    E = E.join(S, on=["day", "symbol"], how="left").filter(pl.col("day") >= xs.FIRST_TEST)
    M = t6.cut_matrices(xs.matrices(E, Px.filter(pl.col("day") >= xs.FIRST_TEST), ["reg7n"]), t6.VAL_TO)
    del E, S, Px
    F, _ = fcy.load()
    F = t6.cut_matrices(F, t6.VAL_TO)
    xb = xs_binance(M, F)
    xv = {v: xs_venue(M, F, v, lsts[v], funds[v]) for v in VENUES}
    xu = {v: xs_unlisted(M, F, lsts[v]) for v in VENUES}
    Md, Fd = M["days"], F["days"]
    del M, F
    print(f"xs books ready, {time.time() - t0:.0f} s", flush=True)

    P = dc.cut_panel(fc.load_panel(), t6.VAL_TO)
    vol = U.median_volume(P)
    lb = lowvol_binance(P, vol, delist, lsts)
    lv = {v: lowvol_venue(P, vol, delist, v, lsts[v], funds[v]) for v in VENUES}
    print(f"low-vol books ready, {time.time() - t0:.0f} s", flush=True)
    from .perps_neutral_portfolio import on_calendar
    cal = P.days
    bdays = {"M4": Md, "Carry": Fd}
    oc = lambda b, x: on_calendar(cal, bdays[b], x, 1)                       # noqa: E731
    binance = {"M4": oc("M4", xb["M4"][0]), "Carry": oc("Carry", xb["Carry"][0]), "LowVol": lb["net"]}
    B = dict(binance)
    common = np.all([np.isfinite(binance[b]) for b in t6.BOOKS], axis=0)
    B.update(t6.combos(P, binance, {b: np.zeros(P.T) for b in t6.BOOKS}, t6.BOOKS, int(np.flatnonzero(common)[0])))
    Sv, extra = {}, {}
    for v in VENUES:
        legs = {s: {b: lead_zeros_out(oc(b, xv[v]["legs"][s][b][0])) for b in ("M4", "Carry")} for s in STEPS}
        for s in STEPS:
            legs[s]["LowVol"] = lead_zeros_out(lv[v]["legs"][s])
        Sv[v] = series(cal, legs, binance)
        extra[v] = {"fund": {"M4": oc("M4", xv[v]["legs"]["full"]["M4"][2]),
                             "Carry": oc("Carry", xv[v]["legs"]["full"]["Carry"][2]), "LowVol": lv[v]["funding"]},
                    "counts": {"M4": oc("M4", xv[v]["counts"]["M4"].astype(float)),
                               "Carry": oc("Carry", xv[v]["counts"]["Carry"].astype(float)),
                               "LowVol": lv[v]["counts"].astype(float)}}
    bfund = {"M4": oc("M4", xb["M4"][2]), "Carry": oc("Carry", xb["Carry"][2]), "LowVol": lb["funding"]}
    btc = np.nan_to_num(P.ret[:, P.btc])
    res = evaluate(cal, Sv, B, btc, register)
    val = common & (cal >= dc.us(t6.VAL_FROM)) & (cal <= dc.us(t6.VAL_TO))
    check = dc.sharpe(B["ERC"][val])
    keys_panel = [coin_key(n) for n in P.names]
    for v, r in res["venues"].items():
        w = windows(cal, Sv[v], v)
        same = w["judged"] & np.isfinite(B["ERC"])
        r["decomposition"] = {"binance": dc.sharpe(B["ERC"][same]),
                              "universe": dc.sharpe(Sv[v]["ERC_universe"][same]),
                              "funding": dc.sharpe(Sv[v]["ERC_funding"][same]), "full": dc.sharpe(Sv[v]["ERC"][same])}
        r["funding"] = {b: {"venue": ann(extra[v]["fund"][b], same), "binance": ann(bfund[b], same)} for b in t6.BOOKS}
        un = {}
        for b in ("M4", "Carry"):
            d_, off, alln = xu[v][b]
            off, alln = oc(b, off), oc(b, alln)
            un[b] = float(np.nansum(off[same]) / max(np.nansum(alln[same]), 1e-12))
        off, alln = lb["unlisted"][v]
        un["LowVol"] = float(off[same].sum() / max(alln[same].sum(), 1e-12))
        r["unlisted"] = un
        first = r["from"] if v != "hyperliquid" else "2023-05-01"
        r["months"] = by_month(cal, lsts[v], keys_panel, extra[v]["counts"], first)
    from .fam_lowvol import weights
    on_hl = lambda Q: on_venue(Q.days, [coin_key(n) for n in Q.names], lsts["hyperliquid"])   # noqa: E731
    leak = checks.book("t12 lowvol PIT50 hyperliquid", lambda Q: weights(
        t5.on(Q, U.pit(Q, 50, table=delist, vol=np.where(on_hl(Q), U.median_volume(Q), np.nan))),
        "vol 60d", 50, "beta-neutral BAB"), P)
    out = {**res, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "data_at": f"health.json of {health['at']}, Hyperliquid {health['tables']['hyperliquid']['coins']} perps "
                      f"({health['tables']['hyperliquid']['delisted']} delisted), Kraken Futures "
                      f"{health['tables']['kraken_futures']['coins']} (today's list only)",
           "costs": f"Hyperliquid's base taker 2.5 / 3.5 / 4.5 bps (to 2023-12-31, to 2025-04-30, after), Kraken "
                    f"Futures {KRAKEN_FEE * 1e4:.0f} bps, each plus T5's half-spread tier one tier wider (3 to 50 "
                    f"bps); Binance as T6 (USD-M taker {t5.PERP_FEE * 1e4:.0f} bps plus T5's tiers, T4's depth not "
                    f"used); book reweights {t6.REWEIGHT_COST * 1e4:.0f} bps",
           "check": f"T6's ERC rebuilt (reg7n refit as in T6b, T4's delisting table "
                    f"{'present' if delist is not None else 'absent'}) has a validation Sharpe of {check:.2f} "
                    f"(T6 published 1.74 on the lost 2026-10-07 cache; T6b's tier rerun on today's inputs 2.08)",
           "check_sharpe": check, "reach": REACH, "leak": t6._leak(leak), "seconds": round(time.time() - t0)}
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), "# T12: lead A on venues the owner can reach\n")
    print(f"done in {out['seconds']} s; " + ", ".join(f"{v} {r['verdict']} ({r['sharpe']:.2f} vs {r['binance']:.2f})"
                                                     for v, r in out["venues"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
