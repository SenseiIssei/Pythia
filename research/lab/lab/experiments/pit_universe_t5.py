"""T5: how much today's 20 surviving coins flatter the main crypto rules.

Pre-registered in results/pit_universe_t5_prereg.md; results in results/pit_universe_t5.md.

    PYTHIA_AGENT_OUT=<panel cache> flock <heavy lock> python -m lab.experiments.pit_universe_t5

Six rules (tsmom, tsmom1, breakout_top10, F2's Donchian 100/50, perps_neutral's
low-vol and carry legs) each on three universes: today's 20 (LAB20) and the
point-in-time top 20 and top 50 by 30-day median dollar volume (lab.universe.pit,
PIT20 and PIT50). A rule runs on the sweep's panel with its eligibility
intersected with the day's universe, nothing else changed. Every rule is filled
one close late and charged per coin the costs of its era: the taker fee plus a
half spread from the coin's own 30-day median dollar volume on the day of the
trade. The panel is cut at the end of validation (2026-06-30): the lockbox is
never read. Each rule and universe is one trial of R5's registry, registered
with its in-sample Sharpe before the validation numbers are computed.
"""

from __future__ import annotations

import dataclasses
import json
import sys
import time
from datetime import datetime, timezone

import numpy as np

from .. import metrics
from .. import universe as U
from . import director_common as dc
from . import fam_common as fc

NAME = "pit_universe_t5"
IS_FROM, IS_TO, VAL_FROM, VAL_TO = "2020-08-01", "2023-12-31", "2024-01-01", "2026-06-30"
UNIVERSES = ("LAB20", "PIT20", "PIT50")
SIZE = {"LAB20": 20, "PIT20": 20, "PIT50": 50}
RULES = ("tsmom", "tsmom1", "breakout_top10", "donchian_100_50", "lowvol", "carry")
PERP_BOTH = ("lowvol", "carry")                     # both legs on perps; the rest are spot longs
SPOT_FEE, PERP_FEE = 0.0010, 0.0005                 # Binance spot taker, USD-M taker
# Half spread by the coin's 30-day median dollar volume on the day (assumed tiers), lowest tier below 1 M.
SPREAD_TIERS = ((1e9, 0.0001), (1e8, 0.0003), (1e7, 0.0010), (1e6, 0.0025))
SPREAD_BELOW = 0.0050
TSMOM_LB, TSMOM_VOL, TSMOM_HISTORY = 28, 0.40, 120  # tsmom.py's pick: 28d, daily, 40 % vol
DON_N, DON_EXIT, DON_MA, DON_RANK, DON_VOL, DON_EVERY = 100, 50, 100, 90, 0.20, 7   # F2's 07493e8a8adb
F2_VOL_WIN = 60
CARRY_SHARE, CARRY_HOLD = 0.10, 3                   # k a tenth of the universe a side, three 3-day tranches
MATERIAL_GAP = 0.20


# ---------------------------------------------------------------- universes and costs

def universes(P: fc.Panel, vol: np.ndarray, table=None, lab_delist: bool = False) -> dict[str, np.ndarray]:
    """(T, N) masks: LAB20's current segments on every day (lab_delist: until its delisting was announced,
    lab.universe.tradable, T6b), PIT20 and PIT50."""
    lab = (U.tradable(P, U.LAB20, True, table) if lab_delist
           else np.broadcast_to(U.mask(P, U.LAB20), (P.T, P.N)).copy())
    return {"LAB20": lab, "PIT20": U.pit(P, 20, table=table, vol=vol), "PIT50": U.pit(P, 50, table=table, vol=vol)}


def on(P: fc.Panel, uni: np.ndarray) -> fc.Panel:
    """The panel with its eligibility intersected with the universe of each day."""
    return dataclasses.replace(P, eligible=P.eligible & uni)


def half_spread(vol: np.ndarray) -> np.ndarray:
    out = np.full(vol.shape, SPREAD_BELOW)
    v = np.nan_to_num(vol, nan=0.0)
    for lo, hs in reversed(SPREAD_TIERS):
        out = np.where(v >= lo, hs, out)
    return out


def era_cost(vol: np.ndarray, perp: bool) -> np.ndarray:
    """(T, N) cost per unit of one-way turnover traded at the close of day t."""
    return (PERP_FEE if perp else SPOT_FEE) + half_spread(vol)


def late(W: np.ndarray, reb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """The targets known at close t traded at close t+1."""
    W2 = np.full_like(W, np.nan)
    W2[1:] = W[:-1]
    r2 = np.zeros_like(reb)
    r2[1:] = reb[:-1]
    return W2, r2


# ---------------------------------------------------------------- one simulator, costs per coin

def simulate(P: fc.Panel, W: np.ndarray, reb: np.ndarray, C: np.ndarray, perp_both: bool = False,
             start: int = 0) -> tuple[np.ndarray, np.ndarray]:
    """fc.simulate (perp_both False: spot longs, shorts on perps) or trend_shorts.sim (True: every position on a
    perp that traded that day, longs pay and shorts receive funding), with each coin's turnover charged at C[t, j].
    The cost of trading at close t is taken from day t+1's return. Returns (net, gross)."""
    T, N = W.shape
    w = np.zeros(N)
    gross, cost = np.zeros(T), np.zeros(T)
    for t in range(start, T - 1):
        if reb[t]:
            tgt = np.where(np.isnan(W[t]), w, W[t])
            tgt = np.where(P.traded[t] | (tgt == w), tgt, w)
            tgt = np.where(((tgt != 0) if perp_both else (tgt < 0)) & ~P.perp_ok[t], 0.0, tgt)
            cost[t] += float(np.abs(tgt - w) @ C[t])
            w = tgt
        r = np.nan_to_num(P.ret[t + 1])
        f = P.funding[t + 1]
        g = float(w @ r - (w @ f if perp_both else np.where(w < 0, w, 0.0) @ f))
        gross[t + 1] = g
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            cost[t + 1] += float(np.abs(w[dead]) @ C[t, dead])
            w[dead] = 0.0
    return gross - np.r_[0.0, cost[:-1]], gross


# ---------------------------------------------------------------- the rules

def tsmom_weights(P: fc.Panel) -> np.ndarray:
    """tsmom.py's pick on the panel: the coins with 120 days of history, held when the 28-day return is positive,
    0.40 / annual vol / coins counted, the sum capped at 1."""
    ok = P.eligible & (P.age >= TSMOM_HISTORY) & np.isfinite(P.sigma) & (P.sigma > 0)
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[TSMOM_LB:] = P.px[TSMOM_LB:] / P.px[:-TSMOM_LB] - 1
    return fc.vol_sized(P, ok & np.isfinite(past) & (past > 0), TSMOM_VOL, ok.sum(1))


def f2_vol(px: np.ndarray) -> np.ndarray:
    """F2's annual vol: the std of 60 daily log returns (small.annvol)."""
    lr = np.full_like(px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        lr[1:] = np.log(px[1:] / px[:-1])
    m = fc.rolling(lr, F2_VOL_WIN, F2_VOL_WIN // 2)
    m2 = fc.rolling(lr ** 2, F2_VOL_WIN, F2_VOL_WIN // 2)
    return np.sqrt(np.maximum(m2 - m ** 2, 0.0) * 365)


def donchian_weights(px: np.ndarray, uni: np.ndarray) -> np.ndarray:
    """F2's genome 07493e8a8adb (small.weights) on any columns: Donchian 100/50 held state, the close above its
    100-day average, the best 1 by 90-day return among the universe, full, scaled down to 20 % vol. No NaN."""
    vol = f2_vol(px)
    hi, lo = fc.rolling_extreme(px, DON_N, "max"), fc.rolling_extreme(px, DON_EXIT, "min")
    with np.errstate(invalid="ignore"):
        enter, leave = px > hi, (px < lo) | ~np.isfinite(px)
    state = np.zeros_like(enter)
    held = np.zeros(px.shape[1], dtype=bool)
    for t in range(len(px)):
        held = (held & ~leave[t]) | (enter[t] & ~leave[t])
        state[t] = held
    r90 = np.full_like(px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r90[DON_RANK:] = px[DON_RANK:] / px[:-DON_RANK] - 1
        cand = uni & state & np.isfinite(px) & np.isfinite(vol) & (vol > 0) & (px > fc.rolling(px, DON_MA, DON_MA))
    score = np.where(cand & np.isfinite(r90), r90, -np.inf)
    order = np.argsort(-score, axis=1, kind="stable")
    pick = np.zeros_like(cand)
    np.put_along_axis(pick, order[:, :1], True, axis=1)
    pick &= cand
    with np.errstate(invalid="ignore", divide="ignore"):
        W = pick * np.minimum(1.0, DON_VOL / np.where(pick & (vol > 0), vol, np.inf))
    return np.nan_to_num(W)


def carry_weights(P: fc.Panel, k: int, offset: int) -> tuple[np.ndarray, np.ndarray]:
    """One tranche of funding carry's F7: every CARRY_HOLD days from `offset`, long the k lowest 7-day funding
    sums and short the k highest among the eligible coins whose perp traded, 0.5 a side; no book with fewer
    than 2k."""
    f7 = fc.rolling(np.where(P.perp_ok, P.funding, np.nan), 7, 5, how="sum")
    ok = P.eligible & P.perp_ok & np.isfinite(f7)
    reb = (np.arange(P.T) % CARRY_HOLD) == offset
    W = np.full((P.T, P.N), np.nan)
    for t in np.flatnonzero(reb):
        row = np.zeros(P.N)
        idx = np.flatnonzero(ok[t])
        if len(idx) >= 2 * k:
            o = idx[np.argsort(f7[t, idx], kind="stable")]
            row[o[:k]] = 0.5 / k
            row[o[::-1][:k]] = -0.5 / k
        W[t] = row
    return W, reb


def books(P: fc.Panel, rule: str, n: int) -> list[tuple[np.ndarray, np.ndarray, int]]:
    """(W, rebalance, start) per sleeve of a rule on a panel already restricted to its universe of n coins."""
    from . import smallaccount as s1
    from .fam_breakout import breakout_weights
    from .fam_lowvol import weights as lowvol_weights
    from .fam_volmom import base_weights
    daily = np.ones(P.T, dtype=bool)
    if rule == "tsmom":
        return [(tsmom_weights(P), daily, 60)]
    if rule == "tsmom1":
        return [(base_weights(P, 1, regime=True), daily, 60)]
    if rule == "breakout_top10":
        allowed = P.top_liquid(10)
        return [(breakout_weights(P, np.flatnonzero(allowed.any(0)), allowed, 20, 10, False), daily, 60)]
    if rule == "donchian_100_50":
        due = np.array([s1.rebalance_day(d, DON_EVERY) for d in P.days])
        return [(donchian_weights(P.px, P.eligible), due, 60)]
    if rule == "lowvol":
        reb = fc.every(P, 7)
        W = lowvol_weights(P, "vol 60d", n, "beta-neutral BAB")
        return [(np.where(reb[:, None], W, np.nan), daily, 100)]
    if rule == "carry":
        k = max(1, round(CARRY_SHARE * n))
        return [(*carry_weights(P, k, o), 60) for o in range(CARRY_HOLD)]
    raise KeyError(rule)


def run_rule(P: fc.Panel, rule: str, uni: np.ndarray, n: int, C: np.ndarray) -> np.ndarray:
    """(T,) the late net return of a rule on a universe at the era's costs (tranches as sleeves of equal thirds)."""
    Pu = on(P, uni)
    nets = []
    for W, reb, start in books(Pu, rule, n):
        W, reb = late(W, reb)
        if rule in PERP_BOTH:
            reb = np.ones(P.T, dtype=bool)               # NaN rows hold; trend_shorts.sim's daily perp check
        nets.append(simulate(Pu, W, reb, C, rule in PERP_BOTH, start)[0])
    return np.mean(nets, axis=0)


# ---------------------------------------------------------------- measuring

def window(P: fc.Panel, a: str, b: str) -> np.ndarray:
    return (P.days >= dc.us(a)) & (P.days <= dc.us(b))


def stats_of(x: np.ndarray) -> dict:
    p = fc.perf(x)
    return {"sharpe": p["sharpe"], "cagr": p["cagr"], "max_dd": p["max_dd"], "days": p["days"]}


def trial(rule: str, uni: str, is_sharpe: float, tag: str = "t5_pit",
          source: str = "results/pit_universe_t5_prereg.md") -> dict:
    return {"id": f"hand:{tag}:{rule}:{uni}", "family": "hand", "n": 1, "sharpe": float(is_sharpe), "source": source}


def about(P: fc.Panel, unis: dict[str, np.ndarray], ins: np.ndarray, val: np.ndarray, table) -> dict:
    lab = U.mask(P, U.LAB20)
    pit20 = unis["PIT20"] & (ins | val)[:, None]
    out = {"delisting_table": bool(table is not None and len(table)),
           "lab20_share_of_pit20": float((pit20 & lab[None, :]).sum() / max(pit20.sum(), 1))}
    last = P.extra["last"]                              # of the uncut panel: a coin alive after VAL_TO is not gone
    for k in ("PIT20", "PIT50"):
        m = unis[k] & (ins | val)[:, None]
        ever = np.flatnonzero(m.any(0))
        gone = [P.names[j] for j in ever if last[j] < P.T - 1 or "~" in P.names[j]]
        out[k] = {"coins": int(len(ever)), "ended": len(gone), "ended_names": sorted(gone)}
    return out


def evaluate(P: fc.Panel, unis: dict[str, np.ndarray], vol: np.ndarray, register: bool = True,
             log=print, tag: str = "t5_pit", source: str = "results/pit_universe_t5_prereg.md") -> dict:
    ins, val = window(P, IS_FROM, IS_TO), window(P, VAL_FROM, VAL_TO)
    C = {False: era_cost(vol, False), True: era_cost(vol, True)}
    series, rows, trials = {}, [], []
    for rule in RULES:
        for u in UNIVERSES:
            x = run_rule(P, rule, unis[u], SIZE[u], C[rule in PERP_BOTH])
            series[(rule, u)] = x
            si = stats_of(x[ins])
            trials.append(trial(rule, u, si["sharpe"], tag, source))
            rows.append({"rule": rule, "universe": u, "is": si})
            log(f"  {rule} {u}: in sample {si['sharpe']:.2f}")
    if register:
        metrics.register(trials)                         # before any validation number exists
    pool = metrics.trial_pool(extra=dc.ledger_trials() + trials)
    for r in rows:
        x = series[(r["rule"], r["universe"])][val]
        r["val"] = {**stats_of(x), "dsr": metrics.dsr(x, pool)}
    gaps = []
    for rule in RULES:
        by = {r["universe"]: r for r in rows if r["rule"] == rule}
        g = {"rule": rule}
        for other in ("PIT20", "PIT50"):
            for w in ("is", "val"):
                for m in ("sharpe", "cagr"):
                    g[f"{w}_{m}_gap_{other}"] = by["LAB20"][w][m] - by[other][w][m]
        lo, hi, share = dc.boot_band(series[(rule, "LAB20")][val], series[(rule, "PIT20")][val])
        g.update({"band_lo": lo, "band_hi": hi, "share_above_0": share,
                  "material": g["val_sharpe_gap_PIT20"] > MATERIAL_GAP and lo > 0})
        gaps.append(g)
    return {"rows": rows, "gaps": gaps, "trials": [t["id"] for t in trials],
            "pool": {"n_trials": pool["n_trials"], "sr0_annual": pool["sr0_annual"]}}


# ---------------------------------------------------------------- the report

def _pct(v: float) -> str:
    return f"{v * 100:.1f} %"


def markdown(out: dict) -> str:
    a = out["about"]
    md = [f"Generated {out['generated']}. In sample {IS_FROM} to {IS_TO}, validation {VAL_FROM} to {VAL_TO}; the panel "
          f"cut at {VAL_TO}, the lockbox not read. Every rule filled one close late at the costs of its era (taker "
          f"{SPOT_FEE * 1e4:.0f} bps spot, {PERP_FEE * 1e4:.0f} bps perps, plus a half spread of 1 to 50 bps from the "
          f"coin's own 30-day median dollar volume that day).\n",
          "## 1. The survivorship premium (LAB20 minus the point-in-time universe)\n"]
    t = []
    for g in out["gaps"]:
        t.append({"rule": g["rule"],
                  "Sharpe gap vs PIT20, in sample / validation": f"{g['is_sharpe_gap_PIT20']:+.2f} / {g['val_sharpe_gap_PIT20']:+.2f}",
                  "CAGR gap vs PIT20, in sample / validation": f"{g['is_cagr_gap_PIT20'] * 100:+.1f} / {g['val_cagr_gap_PIT20'] * 100:+.1f} pts",
                  "Sharpe gap vs PIT50, in sample / validation": f"{g['is_sharpe_gap_PIT50']:+.2f} / {g['val_sharpe_gap_PIT50']:+.2f}",
                  "CAGR gap vs PIT50, in sample / validation": f"{g['is_cagr_gap_PIT50'] * 100:+.1f} / {g['val_cagr_gap_PIT50'] * 100:+.1f} pts",
                  "90 % band, validation Sharpe gap vs PIT20": f"{g['band_lo']:+.2f} to {g['band_hi']:+.2f}",
                  "material": "yes" if g["material"] else "no"})
    md.append(dc.table(t, list(t[0])) + "\n")
    md.append(f"Positive: today's 20 make the rule look better than the coins that were really there. Material: the "
              f"validation Sharpe gap against PIT20 above {MATERIAL_GAP:.2f} and the band's lower end above 0 "
              f"(stationary bootstrap, {dc.BOOT_DRAWS} draws, mean block {dc.BOOT_BLOCK} days).\n")
    md.append("## 2. Per rule and universe\n")
    t = []
    for r in out["rows"]:
        i, v = r["is"], r["val"]
        t.append({"rule": r["rule"], "universe": r["universe"],
                  "in sample Sharpe / CAGR / DD": f"{i['sharpe']:.2f} / {_pct(i['cagr'])} / {_pct(i['max_dd'])}",
                  "validation Sharpe / CAGR / DD": f"{v['sharpe']:.2f} / {_pct(v['cagr'])} / {_pct(v['max_dd'])}",
                  "validation DSR, pass at 0.95 or more": f"{v['dsr']:.3f}"})
    md.append(dc.table(t, list(t[0])) + "\n")
    md.append(f"DSR over R5's registry, the pool of all with the factory ledgers and these "
              f"{len(out['trials'])} trials ({out['pool']['n_trials']:,} trials, noise bar "
              f"{out['pool']['sr0_annual']:.2f} a year); higher is better. Trials: `hand:t5_pit:<rule>:<universe>`.\n")
    md.append("## 3. The universe\n")
    md.append(f"- Coins ever in PIT20 over both windows: {a['PIT20']['coins']}, of them {a['PIT20']['ended']} with a "
              f"last bar before {VAL_TO} (delisted) or an older asset of a reused ticker; in PIT50 {a['PIT50']['coins']} "
              f"and {a['PIT50']['ended']}.")
    md.append(f"- Share of PIT20's coin-days that are LAB20 coins: {_pct(a['lab20_share_of_pit20'])}.")
    md.append(f"- PIT20's ended coins: {', '.join(a['PIT20']['ended_names']) or 'none'}.")
    md.append("- T4's delisting table: " + ("present, a coin leaves from the day its delisting was announced."
                                            if a["delisting_table"] else "not present on this run, nothing dropped "
                                            "early; ended coins leave with their last bar.") + "\n")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    t0 = time.time()
    from ..collect import book_depth
    table = book_depth.read_delistings()
    P = dc.cut_panel(fc.load_panel(), VAL_TO)
    vol = U.median_volume(P)
    unis = universes(P, vol, table)
    out = evaluate(P, unis, vol, register="--no-register" not in argv)
    out["about"] = about(P, unis, window(P, IS_FROM, IS_TO), window(P, VAL_FROM, VAL_TO), table)
    out["generated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    out["seconds"] = round(time.time() - t0)
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), "# T5: a point-in-time universe\n")
    print(f"done in {out['seconds']} s; material: {[g['rule'] for g in out['gaps'] if g['material']] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
