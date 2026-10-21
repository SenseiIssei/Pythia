"""tsmom_top20 and breakout_top10 with a short leg on perpetuals, against the same books long-only.

    PYTHIA_AGENT_OUT=<fresh panel folder> python -m lab.experiments.trend_shorts

Pre-registered in results/trend_shorts_prereg.md (committed before this file ran).
The sweep's survivorship-free daily panel cut at 2026-10-19; every leg a USDT
perpetual (a coin is tradeable on day t only if its perp traded), the long side
paying and the short side receiving funding, prices from spot closes. Five short-leg
variants per book (BTC-gated or always, full or half size, dollar-neutral), the
in-sample pick per book judged against its long-only perp book (six gates) and
against BTC held above its 200-day average. Costs 10 bps per unit of one-way
turnover (20 stress; 0 and 41 reported). Writes results/trend_shorts.md below the
marker and <reports>/trend_shorts/latest.*.
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from .. import report
from . import alpaca_universe as au
from . import director_common as dc
from . import fam_common as fc
from . import perps_common as pc

NAME = "trend_shorts"
LAST_DAY = "2026-10-19"
LOOKBACK, COIN_VOL = 28, 0.40
YEARS_OOS = (2024, 2025, 2026)
VARIANTS = ("V1 bear 100", "V2 bear 50", "V3 always 100", "V4 always 50", "V5 dollar-neutral")
START = 60


# ---------------------------------------------------------------------------
# Weights (NaN in a row = leave that coin as it is)
# ---------------------------------------------------------------------------

def tsmom_side(P: fc.Panel, uni: np.ndarray, side: int, size: float = 1.0) -> np.ndarray:
    """Hold a coin of uni while its 28-day return has the side's sign, 40 % vol over the
    universe's slots, the side's gross capped at size. Magnitudes signed by side."""
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[LOOKBACK:] = P.px[LOOKBACK:] / P.px[:-LOOKBACK] - 1
    held = uni & np.isfinite(past) & ((past > 0) if side > 0 else (past < 0))
    return side * size * fc.vol_sized(P, held, COIN_VOL, uni.sum(1))


def donchian_side(P: fc.Panel, cols: np.ndarray, allowed: np.ndarray, n: int, slots: int, side: int,
                  flat: np.ndarray | None = None, size_mult: float = 1.0) -> np.ndarray:
    """fam_breakout's rule (enter on a close beyond the n-day extreme while allowed, leave on
    a close beyond the n/2-day opposite extreme), long (side +1) or its mirror (side -1).
    flat[t]: no entries and every position closed that day."""
    px = P.px[:, cols]
    hi_n, lo_n = fc.rolling_extreme(px, n, "max"), fc.rolling_extreme(px, n, "min")
    hi_x, lo_x = fc.rolling_extreme(px, n // 2, "max"), fc.rolling_extreme(px, n // 2, "min")
    with np.errstate(invalid="ignore"):
        enter = ((px > hi_n) if side > 0 else (px < lo_n)) & allowed[:, cols]
        leave = ((px < lo_x) if side > 0 else (px > hi_x)) | ~P.alive[:, cols]
    with np.errstate(invalid="ignore", divide="ignore"):
        sz = np.minimum(COIN_VOL / (P.sigma[:, cols] * np.sqrt(365)) / slots, 1.0 / slots)
    sz = np.nan_to_num(sz) * size_mult
    W = np.full((P.T, P.N), np.nan)
    held = np.zeros(len(cols), dtype=bool)
    for t in range(P.T):
        row = np.full(len(cols), np.nan)
        if flat is not None and flat[t]:
            row[held] = 0.0
            held[:] = False
        else:
            ex = held & leave[t]
            en = ~held & enter[t] & (sz[t] > 0)
            row[ex] = 0.0
            row[en] = side * sz[t, en]
            held = (held & ~ex) | en
        W[t, cols] = row
    W[:, np.setdiff1d(np.arange(P.N), cols)] = 0.0
    return W


def combine(WL: np.ndarray, WS: np.ndarray) -> np.ndarray:
    """One target matrix from a long and a short leg in NaN-means-keep form: an entry of
    either side wins (a long entry and a short entry cannot fall on the same coin and day:
    the entry of one is beyond the other's exit), then an exit, then keep."""
    out = WL.copy()
    s_set = np.isfinite(WS)
    l_entry = np.isfinite(WL) & (WL != 0)
    s_entry = s_set & (WS != 0)
    out = np.where(s_entry & ~l_entry, WS, out)
    out = np.where(s_set & ~s_entry & ~np.isfinite(WL), 0.0, out)
    return out


# ---------------------------------------------------------------------------
# One simulator: both legs perpetuals
# ---------------------------------------------------------------------------

def sim(P: fc.Panel, W: np.ndarray, neutral: bool = False, start: int = START) -> dict[str, np.ndarray]:
    """fc.simulate for a perp book: a position can be opened or resized only where the
    perp traded that day, one whose perp did not trade is closed; longs pay and shorts
    receive the day's funding. neutral: the rule's own book (u, NaN rows keep u) is
    held scaled each day so that the larger side has the smaller side's gross; the
    rule's state is never changed by the scaling. Returns gross and its parts,
    turnover per side, exposure."""
    T, N = W.shape
    w = np.zeros(N)
    u = np.zeros(N)
    o = {k: np.zeros(T) for k in ("gross", "long_px", "short_px", "long_fund", "short_fund", "tov_long",
                                  "tov_short", "long_expo", "short_expo")}
    for t in range(start, T - 1):
        tgt = np.where(np.isnan(W[t]), u, W[t])
        tgt = np.where(P.traded[t] | (tgt == u), tgt, u)
        tgt = np.where((tgt != 0) & ~P.perp_ok[t], 0.0, tgt)
        u = tgt
        if neutral:
            L, S = tgt[tgt > 0].sum(), -tgt[tgt < 0].sum()
            m = min(L, S)
            tgt = np.where(tgt > 0, tgt * (m / L if L > 0 else 0.0), np.where(tgt < 0, tgt * (m / S if S > 0 else 0.0), 0.0))
        o["tov_long"][t] += np.abs(np.maximum(tgt, 0) - np.maximum(w, 0)).sum()
        o["tov_short"][t] += np.abs(np.minimum(tgt, 0) - np.minimum(w, 0)).sum()
        w = tgt
        r = np.nan_to_num(P.ret[t + 1])
        f = P.funding[t + 1]
        wl, ws = np.where(w > 0, w, 0.0), np.where(w < 0, w, 0.0)
        o["long_px"][t + 1], o["short_px"][t + 1] = float(wl @ r), float(ws @ r)
        o["long_fund"][t + 1], o["short_fund"][t + 1] = -float(wl @ f), -float(ws @ f)
        g = float(w @ r - w @ f)
        o["gross"][t + 1] = g
        o["long_expo"][t], o["short_expo"][t] = wl.sum(), -ws.sum()
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        if neutral:
            gu = float(u @ r - u @ f)
            u = u * (1 + r) / (1 + gu) if 1 + gu > 0 else np.zeros(N)
            u[(u != 0) & ~P.alive[t + 1]] = 0.0
        else:
            u = w
        dead = (w != 0) & ~P.alive[t + 1]
        if dead.any():
            o["tov_long"][t + 1] += np.abs(w[dead & (w > 0)]).sum()
            o["tov_short"][t + 1] += np.abs(w[dead & (w < 0)]).sum()
            w[dead] = 0.0
    o["turnover"] = o["tov_long"] + o["tov_short"]
    return o


def net(o: dict, cost: float) -> np.ndarray:
    return o["gross"] - cost * np.r_[0.0, o["turnover"][:-1]]


def short_alone(o: dict, cost: float) -> np.ndarray:
    return o["short_px"] + o["short_fund"] - cost * np.r_[0.0, o["tov_short"][:-1]]


def gate_btc(P: fc.Panel, k: float, cost: float, band: float = 0.25) -> np.ndarray:
    """gated_btc's G on the BTC perpetual: weight k while BTC closes above its 200-day
    average, cash otherwise, trimmed back to k beyond a 25 % band; a long pays funding."""
    T = P.T
    r_all, f_all = np.nan_to_num(P.ret[:, P.btc]), P.funding[:, P.btc]
    w, out = 0.0, np.zeros(T)
    tov = np.zeros(T)
    for t in range(T - 1):
        tgt = (k if (w <= 0 or abs(w - k) > band * k) else w) if P.btc_on[t] else 0.0
        tov[t] = abs(tgt - w)
        w = tgt
        g = w * (r_all[t + 1] - f_all[t + 1])
        out[t + 1] = g
        w = w * (1 + r_all[t + 1]) / (1 + g) if 1 + g > 0 else 0.0
    return out - cost * np.r_[0.0, tov[:-1]]


# ---------------------------------------------------------------------------
# The books
# ---------------------------------------------------------------------------

def build(P: fc.Panel) -> dict[str, dict]:
    """{book: {"long": W, variant: (W, neutral)}}."""
    off = ~P.btc_on            # the short leg's gate: only while BTC closes below its 200-day average
    on = P.btc_on
    top20 = P.top_liquid(20, need_perp=True)
    top10 = P.top_liquid(10, need_perp=True)
    cols = np.flatnonzero(top10.any(0))
    out = {}
    # tsmom_top20: the long leg flat while BTC is below its 200-day average.
    L = tsmom_side(P, top20, +1) * on[:, None]
    L_free = tsmom_side(P, top20, +1)
    S = tsmom_side(P, top20, -1)
    out["tsmom_top20"] = {
        "long": (L, False),
        VARIANTS[0]: (L + S * off[:, None], False),
        VARIANTS[1]: (L + 0.5 * S * off[:, None], False),
        VARIANTS[2]: (L + S, False),
        VARIANTS[3]: (L + 0.5 * S, False),
        VARIANTS[4]: (L_free + S, True),
    }
    # breakout_top10: no regime on the long leg.
    BL = donchian_side(P, cols, top10, 20, 10, +1)
    out["breakout_top10"] = {
        "long": (BL, False),
        VARIANTS[0]: (combine(BL, donchian_side(P, cols, top10, 20, 10, -1, flat=on)), False),
        VARIANTS[1]: (combine(BL, donchian_side(P, cols, top10, 20, 10, -1, flat=on, size_mult=0.5)), False),
        VARIANTS[2]: (combine(BL, donchian_side(P, cols, top10, 20, 10, -1)), False),
        VARIANTS[3]: (combine(BL, donchian_side(P, cols, top10, 20, 10, -1, size_mult=0.5)), False),
        VARIANTS[4]: (combine(BL, donchian_side(P, cols, top10, 20, 10, -1)), True),
    }
    return out


def spot_reference(P: fc.Panel) -> dict[str, np.ndarray]:
    """The paper books as they run on spot (no perp restriction), at Alpaca's 35 bps."""
    O = au.originals(P)
    out = {}
    for b, name in (("breakout", "breakout_top10"), ("tsmom_daily", "tsmom_top20")):
        g, tv, _, _ = fc.simulate(P, O[b], start=START)
        out[name] = g - pc.ALPACA_TAKER * np.r_[0.0, tv[:-1]]
    return out


def main() -> None:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    ins, oos = fc.masks(P)
    years = dc.years_of(P.days)
    on_prev = np.r_[False, P.btc_on[:-1]]
    books = build(P)
    spot = spot_reference(P)
    res: dict = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "is_from": dc.day_str(P.days[ins][0]), "is_to": dc.day_str(P.days[ins][-1]),
                 "oos_from": dc.day_str(P.days[oos][0]), "oos_to": dc.day_str(P.days[oos][-1]),
                 "oos_days": int(oos.sum()), "books": {}}
    trial_sr, diffs = [], {}
    for book, spec in books.items():
        Wl, _ = spec["long"]
        lo_ = sim(P, Wl)
        lo_late = sim(P, au.one_day_late(Wl))
        base = {c: net(lo_, v) for c, v in pc.COSTS.items()}
        rows = []
        sims = {}
        for var in VARIANTS:
            W, neu = spec[var]
            o = sim(P, W, neutral=neu)
            sims[var] = (o, W, neu)
            row = {"variant": var, "turnover_yr": float(o["turnover"][oos].sum() / (oos.sum() / 365)),
                   "avg_long": float(o["long_expo"][oos].mean()), "avg_short": float(o["short_expo"][oos].mean())}
            for c, v in pc.COSTS.items():
                n = net(o, v)
                row[f"is_{c}"], row[f"oos_{c}"] = dc.sharpe(n[ins]), dc.sharpe(n[oos])
            n10 = net(o, pc.JUDGED)
            p = dc.perf(n10[oos])
            row["oos_cagr"], row["oos_dd"] = p["cagr"], p["max_dd"]
            sa = short_alone(o, pc.JUDGED)
            row["short_is"], row["short_oos"] = dc.sharpe(sa[ins]), dc.sharpe(sa[oos])
            row["short_oos_ann"] = float(sa[oos].mean() * 365)
            row["short_fund_oos_ann"] = float(o["short_fund"][oos].mean() * 365)
            for y in YEARS_OOS:
                row[f"y{y}"] = dc.sharpe(n10[oos & (years == y)])
            d = n10 - base["10bps"]
            row["d_oos"] = dc.sharpe(d[oos])
            row["sr_on"], row["sr_off"] = dc.sharpe(n10[oos & on_prev]), dc.sharpe(n10[oos & ~on_prev])
            trial_sr.append(row["d_oos"])
            diffs[(book, var)] = d[oos]
            rows.append(row)
            print(book, var, round(row["is_10bps"], 2), round(row["oos_10bps"], 2), flush=True)
        pick = max(rows, key=lambda r: r["is_10bps"])
        o, W, neu = sims[pick["variant"]]
        n10 = net(o, pc.JUDGED)
        b10 = base["10bps"]
        o_late = sim(P, au.one_day_late(W), neutral=neu)
        pb, pp = dc.perf(b10[oos]), dc.perf(n10[oos])
        lo, hi, above = pc.boot(n10[oos], b10[oos])
        # Short leg alone by year (2022 sits in sample).
        sa = short_alone(o, pc.JUDGED)
        leg_years = [{"year": y, "short_sharpe": dc.sharpe(sa[(years == y) & (ins | oos)]),
                      "short_ret_pct": float(sa[(years == y) & (ins | oos)].mean() * 365 * 100),
                      "short_fund_pct": float(o["short_fund"][(years == y) & (ins | oos)].mean() * 365 * 100),
                      "long_ret_pct": float((o["long_px"] + o["long_fund"])[(years == y) & (ins | oos)].mean()
                                            * 365 * 100)}
                     for y in range(2020, 2027)]
        # Gated BTC at the pick's in-sample vol.
        g1 = gate_btc(P, 1.0, pc.JUDGED)
        k = min(1.0, float(n10[ins].std() / g1[ins].std()))
        G = gate_btc(P, k, pc.JUDGED)
        D = n10 - G
        glo, ghi, gab = pc.boot(D[oos])
        trial_sr.append(dc.sharpe(D[oos]))
        pk = {"pick": pick["variant"], "pick_is": pick["is_10bps"], "pick_oos": pp["sharpe"], "pick_dd": pp["max_dd"],
              "pick_cagr": pp["cagr"], "long_is": dc.sharpe(b10[ins]), "long_oos": pb["sharpe"],
              "long_dd": pb["max_dd"], "long_cagr": pb["cagr"],
              "diff_sr": pp["sharpe"] - pb["sharpe"], "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
              "late_oos": dc.sharpe(net(o_late, pc.JUDGED)[oos]),
              "long_late_oos": dc.sharpe(net(lo_late, pc.JUDGED)[oos]),
              "pick_20": dc.sharpe(net(o, pc.STRESS)[oos]), "long_20": dc.sharpe(base["20bps"][oos]),
              "short_oos": pick["short_oos"],
              "spot_ref_oos": dc.sharpe(spot[book][oos]), "spot_ref_is": dc.sharpe(spot[book][ins]),
              "k": k, "g_oos": dc.sharpe(G[oos]), "d_g": dc.sharpe(D[oos]), "d_g_p05": glo, "d_g_p95": ghi,
              "d_g_above0": gab, "leg_years": leg_years,
              **{f"pick{y}": dc.sharpe(n10[oos & (years == y)]) for y in YEARS_OOS},
              **{f"long{y}": dc.sharpe(b10[oos & (years == y)]) for y in YEARS_OOS}}
        pk["_D"] = (n10 - b10)[oos]
        long_row = {"variant": "long-only (perps)", "avg_long": float(lo_["long_expo"][oos].mean()), "avg_short": 0.0,
                    "turnover_yr": float(lo_["turnover"][oos].sum() / (oos.sum() / 365)),
                    **{f"is_{c}": dc.sharpe(base[c][ins]) for c in pc.COSTS},
                    **{f"oos_{c}": dc.sharpe(base[c][oos]) for c in pc.COSTS},
                    "oos_cagr": pb["cagr"], "oos_dd": pb["max_dd"],
                    **{f"y{y}": dc.sharpe(b10[oos & (years == y)]) for y in YEARS_OOS},
                    "sr_on": dc.sharpe(b10[oos & on_prev]), "sr_off": dc.sharpe(b10[oos & ~on_prev])}
        res["books"][book] = {"rows": [long_row] + rows, "pick": pk}

    pl_ = pc.pool(trial_sr)
    res["pool"] = pl_
    for book, b in res["books"].items():
        pk = b["pick"]
        pk["d_deflated_p"] = dc.deflated(pk.pop("_D"), pl_)
        yrs = sum(pk[f"pick{y}"] > pk[f"long{y}"] for y in YEARS_OOS)
        gates = {"1 higher Sharpe, and in 2 of 3 years": pk["pick_oos"] > pk["long_oos"] and yrs >= 2,
                 "2 drawdown not above long-only's": pk["pick_dd"] <= pk["long_dd"],
                 "3 bootstrap band of the difference above 0": pk["boot_p05"] > 0,
                 "4 a close late still above long-only": pk["late_oos"] > pk["long_oos"],
                 "5 at 20 bps still above long-only": pk["pick_20"] > pk["long_20"],
                 "6 improvement deflated above 0.95": pk["d_deflated_p"] > 0.95}
        pk["gates"] = gates
        first5 = all(v for k_, v in gates.items() if not k_.startswith("6"))
        pk["killed"] = pk["short_oos"] <= 0
        pk["verdict"] = ("kill: the short leg alone loses" if pk["killed"] else
                         "pass (confirmed)" if all(gates.values()) else
                         "pass gates 1 to 5, fails deflation: experimental" if first5 else "fails")
        pk["beats_gated_btc"] = pk["d_g"] > 0 and pk["d_g_p05"] > 0
    write(res)


def write(res: dict) -> None:
    pl_ = res["pool"]
    pct = lambda v: f"{v * 100:.0f} %"  # noqa: E731
    md = ["# Trend following with a short leg on perpetuals: results\n",
          f"Generated {res['generated']}. Registered in `results/trend_shorts_prereg.md` before the run.\n",
          f"In sample {res['is_from']} to {res['is_to']}, out of sample {res['oos_from']} to {res['oos_to']} "
          f"({res['oos_days']} days). Every leg a USDT perpetual (longs pay funding, shorts receive it), judged at "
          "10 bps per unit of one-way turnover.\n", "## Verdict per book\n"]
    for book, b in res["books"].items():
        p = b["pick"]
        md.append(f"- **{book}**, pick {p['pick']}: {p['verdict']}. Out of sample {p['pick_oos']:.2f} against "
                  f"{p['long_oos']:.2f} long-only on perps (band of the difference {p['boot_p05']:.2f} to "
                  f"{p['boot_p95']:.2f}), drawdown {pct(p['pick_dd'])} against {pct(p['long_dd'])}, a close late "
                  f"{p['late_oos']:.2f}, at 20 bps {p['pick_20']:.2f} against {p['long_20']:.2f}, short leg alone "
                  f"{p['short_oos']:.2f}, deflated improvement p {p['d_deflated_p']:.4f}. Against gated BTC "
                  f"(k {p['k']:.2f}, G {p['g_oos']:.2f}): D {p['d_g']:.2f}, band {p['d_g_p05']:.2f} to "
                  f"{p['d_g_p95']:.2f}, " + ("beats it." if p["beats_gated_btc"] else "does not beat it.")
                  + f" The book as it runs on spot at 35 bps: {p['spot_ref_oos']:.2f}.")
        for k_, v in p["gates"].items():
            md.append(f"  - gate {k_}: {'yes' if v else 'no'}")
    for book, b in res["books"].items():
        md.append(f"\n## {book}: every variant\n")
        tab = [{**r, "oos_dd_pct": r["oos_dd"] * 100, "oos_cagr_pct": r["oos_cagr"] * 100} for r in b["rows"]]
        md.append(dc.table(tab, ["variant", "is_10bps", "oos_0bps", "oos_10bps", "oos_20bps", "oos_41bps", "oos_cagr_pct",
                                 "oos_dd_pct", "y2024", "y2025", "y2026", "d_oos", "short_is", "short_oos",
                                 "short_fund_oos_ann", "avg_long", "avg_short", "turnover_yr", "sr_on", "sr_off"]))
        md.append(f"\n### {book}: the pick's legs by year (10 bps; 2020 to 2023 in sample)\n")
        md.append(dc.table(b["pick"]["leg_years"], ["year", "short_sharpe", "short_ret_pct", "short_fund_pct",
                                                    "long_ret_pct"]))
    md.append("\nSharpe = daily mean over sd x sqrt 365. `d_oos`: Sharpe of the daily difference against the long-only "
              "perp book. `short_*`: the short leg alone (its price return, funding and its share of costs); "
              "`short_fund_oos_ann`: funding the short leg received a year. `sr_on` / `sr_off`: Sharpe on days the "
              "BTC gate was on / off at the previous close. Bootstrap: stationary, mean block "
              f"{dc.BOOT_BLOCK} days, {dc.BOOT_DRAWS} draws, seed {pc.SEED}.\n")
    md.append(f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} factory, "
              f"{pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of about "
              f"{pl_['sr0_annual']:.2f}.\n")
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
