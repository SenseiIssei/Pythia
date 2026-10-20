"""Do the Alpaca books beat BTC held only above its 200-day average, at the same risk?

    python -m lab.experiments.gated_btc

Pre-registered in results/gated_btc_prereg.md (committed before this file ran).
breakout_top10, tsmom_top20 and tsmom_tranches as they run on Alpaca (coins Alpaca
does not list held as cash, alpaca_universe's C books) and trend4h_pullback
(fast_maker's pick, rerun on the PC's 1h bars), each against G: BTC at weight k
while its close is above its 200-day average, k matched to the book's in-sample
volatility. Out of sample 2024-01-01 to 2026-10-14. Writes results/gated_btc.md
below the marker and <reports>/gated_btc/latest.{md,json}.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from .. import report
from . import alpaca_universe as au
from . import director_common as dc
from . import fam_common as fc
from . import fast_maker as fm

NAME = "gated_btc"
LAST_DAY = "2026-10-14"
COST, STRESS = 0.0035, 0.0070
TRIM_BAND = 0.25
YEARS_OOS = (2024, 2025, 2026)
DAILY_BOOKS = (("breakout", "breakout_top10"), ("tsmom_daily", "tsmom_top20"), ("tsmom_tranches", "tsmom_tranches"))
TREND4H = fm.Variant("B", tuple(sorted({"rule": "ema", "p": 0.5, "W": 60, "gate": True}.items())))
DD_SLACK = 0.05


# ---------------------------------------------------------------------------
# G: BTC above its 200-day average
# ---------------------------------------------------------------------------

def sim_gate(ret: np.ndarray, on: np.ndarray, k: float, band: float = TRIM_BAND) -> tuple[np.ndarray, np.ndarray]:
    """BTC at weight k while on[t] (decided at the close of t, earning t+1), cash otherwise.
    Bought to k at a switch-on close, sold at a switch-off close, traded back to k in
    between only where the drifted weight is more than band x k away. (gross, turnover)."""
    T = len(ret)
    r_all = np.nan_to_num(ret)
    w = 0.0
    gross, tov = np.zeros(T), np.zeros(T)
    for t in range(T):
        if on[t]:
            tgt = k if (w <= 0 or abs(w - k) > band * k) else w
        else:
            tgt = 0.0
        tov[t] = abs(tgt - w)
        w = tgt
        if t == T - 1:
            break
        r = r_all[t + 1]
        g = w * r
        gross[t + 1] = g
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else 0.0
    return gross, tov


def net(gross: np.ndarray, tov: np.ndarray, cost: float) -> np.ndarray:
    return gross - cost * np.r_[0.0, tov[:-1]]


# ---------------------------------------------------------------------------
# The books
# ---------------------------------------------------------------------------

def daily_books(P: fc.Panel) -> dict[str, dict]:
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    out = {}
    for b, name in DAILY_BOOKS:
        g, tv, ex, _ = au.simulate(P, b, au.cash_left(O[b], alp))
        out[name] = {"judged": net(g, tv, COST), "stress": net(g, tv, STRESS), "tov": tv, "expo": ex,
                     "judged_label": "35 bps", "stress_label": "70 bps"}
    return out


def trend4h_book() -> dict:
    """fast_maker's pick alone on the 1h bars: maker base, and every order at the close at 35 and 70 bps."""
    coins = fm.load_alpaca(60)
    btc = next(c for c in coins if c.name == "BTC")
    ctx = fm.Ctx(gate_d=fm.btc_gate(btc))
    tm, tt_ = [], []
    for c in coins:
        tm += fm.simulate_coin(c, TREND4H, ctx)
        tt_ += fm.simulate_coin(c, TREND4H, ctx, taker=True)
    mk = fm.run_book(tm, {"base": fm.SCEN_MAKER["base"]}, TREND4H.label)
    tk = fm.run_book(tt_, {"close35": (0.0, COST), "close70": (0.0, STRESS)}, TREND4H.label)
    return {"judged": mk.rets["base"], "stress": tk.rets["close70"], "close35": tk.rets["close35"],
            "judged_label": "maker base", "stress_label": "close fills, 70 bps", "label": TREND4H.label,
            "coins": [c.name for c in coins]}


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def main() -> None:
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    ins, oos = fc.masks(P)
    years = dc.years_of(P.days)
    ret_btc = np.nan_to_num(P.ret[:, P.btc])
    on = P.btc_on.copy()
    books = daily_books(P)
    print("trend4h_pullback on 1h bars", flush=True)
    t4 = trend4h_book()
    assert len(t4["judged"]) == P.T, (len(t4["judged"]), P.T)
    books["trend4h_pullback"] = t4

    # G at k = 1: the volatility every book is matched to.
    g1, t1 = sim_gate(ret_btc, on, 1.0)
    g1_35 = net(g1, t1, COST)
    sd_g1_is = float(g1_35[ins].std())

    rows, trial_sr = [], []
    for name, b in books.items():
        k = min(1.0, float(b["judged"][ins].std()) / sd_g1_is)
        gk, tk = sim_gate(ret_btc, on, k)
        G = {"judged": net(gk, tk, COST), "stress": net(gk, tk, STRESS)}
        D = {s: b[s] - G[s] for s in ("judged", "stress")}
        lo, hi, above = dc.boot_band(D["judged"][oos])
        pb, pg = dc.perf(b["judged"][oos]), dc.perf(G["judged"][oos])
        row = {"book": name, "judged_at": b["judged_label"], "k": k,
               "vol_ratio_is": float(b["judged"][ins].std() / G["judged"][ins].std()),
               "vol_ratio_oos": float(b["judged"][oos].std() / G["judged"][oos].std()),
               "book_is": dc.sharpe(b["judged"][ins]), "g_is": dc.sharpe(G["judged"][ins]),
               "book_oos": pb["sharpe"], "book_dd": pb["max_dd"], "book_cagr": pb["cagr"],
               "g_oos": pg["sharpe"], "g_dd": pg["max_dd"], "g_cagr": pg["cagr"],
               "book_stress": dc.sharpe(b["stress"][oos]), "g_stress": dc.sharpe(G["stress"][oos]),
               "d_oos": dc.sharpe(D["judged"][oos]), "d_stress": dc.sharpe(D["stress"][oos]),
               "d_mean_ann": float(D["judged"][oos].mean() * 365),
               "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
               "corr": float(np.corrcoef(b["judged"][oos], G["judged"][oos])[0, 1]),
               "corr_btc": float(np.corrcoef(b["judged"][oos], ret_btc[oos])[0, 1])}
        for y in YEARS_OOS:
            m = oos & (years == y)
            row[f"d{y}"] = dc.sharpe(D["judged"][m])
            row[f"b{y}"] = dc.sharpe(b["judged"][m])
            row[f"g{y}"] = dc.sharpe(G["judged"][m])
        if "close35" in b:
            dc35 = b["close35"] - G["judged"]
            row["close35_oos"] = dc.sharpe(b["close35"][oos])
            row["d_close35"] = dc.sharpe(dc35[oos])
        # Exposure on gate-on and gate-off days (decided the previous close).
        on_prev = np.r_[False, on[:-1]]
        row["book_sharpe_gate_on"] = dc.sharpe(b["judged"][oos & on_prev])
        row["book_sharpe_gate_off"] = dc.sharpe(b["judged"][oos & ~on_prev])
        row["book_ret_gate_off_ann"] = float(b["judged"][oos & ~on_prev].mean() * 365)
        row["_D"] = D["judged"][oos]
        rows.append(row)
        trial_sr.append(row["d_oos"])

    pl_ = dc.pool(trial_sr)
    for r in rows:
        r["d_deflated_p"] = dc.deflated(r.pop("_D"), pl_)
        yrs = sum(r[f"d{y}"] > 0 for y in YEARS_OOS)
        r["d_years_pos"] = int(yrs)
        fails = []
        if not r["d_oos"] > 0:
            fails.append("1 D Sharpe <= 0")
        if yrs < 2:
            fails.append(f"2 D positive in {yrs} of 3 years")
        if not r["boot_p05"] > 0:
            fails.append("3 bootstrap 5 % <= 0")
        if not r["d_stress"] > 0:
            fails.append("4 D <= 0 at stress")
        if not r["book_dd"] <= r["g_dd"] + DD_SLACK:
            fails.append("5 drawdown above G's + 5 pp")
        r["fails"] = "; ".join(fails) or "none"
        r["passes"] = not fails
        r["killed"] = not r["d_oos"] > 0
        r["confirmed"] = r["passes"] and r["d_deflated_p"] > 0.95
        r["verdict"] = ("beats gated BTC" + (" (confirmed)" if r["confirmed"] else "")) if r["passes"] else \
            ("no better than gated BTC at the same risk" if r["killed"] else "not shown to beat gated BTC")

    # G's own record at k = 1 (the paper-book question).
    idx = np.flatnonzero(ins)
    mid = idx[len(idx) // 2]
    h1 = ins & (np.arange(P.T) < mid)
    h2 = ins & ~h1
    on_late = np.r_[False, on[:-1]]
    gl, tl = sim_gate(ret_btc, on_late, 1.0)
    g1_70 = net(g1, t1, STRESS)
    pbtc = dc.perf(ret_btc[oos])
    p1 = dc.perf(g1_35[oos])
    grec = {"is": dc.sharpe(g1_35[ins]), "h1": dc.sharpe(g1_35[h1]), "h2": dc.sharpe(g1_35[h2]),
            "oos_35": p1["sharpe"], "oos_70": dc.sharpe(g1_70[oos]), "cagr": p1["cagr"], "dd": p1["max_dd"],
            "late": dc.sharpe(net(gl, tl, COST)[oos]), "btc_oos": pbtc["sharpe"], "btc_dd": pbtc["max_dd"],
            "btc_cagr": pbtc["cagr"], "exposure": float(np.r_[False, on[:-1]][oos].mean()),
            "switches_yr": float((np.abs(np.diff(on[oos].astype(int))) > 0).sum() / (oos.sum() / 365)),
            "turnover_yr": float(t1[oos].sum() / (oos.sum() / 365)),
            **{f"y{y}": dc.sharpe(g1_35[oos & (years == y)]) for y in YEARS_OOS}}
    grec["deflated_p"] = dc.deflated(g1_35[oos], pl_)
    grec["boot_p05"], grec["boot_p95"], _ = dc.boot_band(g1_35[oos])
    gates = {"G1 both in-sample halves above 0": grec["h1"] > 0 and grec["h2"] > 0,
             "G2 above 0 at 35 and 70 bps": grec["oos_35"] > 0 and grec["oos_70"] > 0,
             "G3 drawdown below BTC bought and held": grec["dd"] < grec["btc_dd"],
             "G4 a close late above 0": grec["late"] > 0,
             "G5 positive in 2 of 3 years": sum(grec[f"y{y}"] > 0 for y in YEARS_OOS) >= 2}
    grec["gates"] = gates
    any_pass = any(r["passes"] for r in rows)
    all_killed = all(r["killed"] for r in rows)
    propose = (not any_pass) and all(gates.values())
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "oos_from": dc.day_str(P.days[oos][0]), "oos_to": dc.day_str(P.days[oos][-1]), "oos_days": int(oos.sum()),
           "is_from": dc.day_str(P.days[ins][0]), "is_to": dc.day_str(P.days[ins][-1]),
           "rows": rows, "g": grec, "pool": pl_, "any_pass": any_pass, "all_killed": all_killed,
           "propose_paper_book": propose, "trend4h_label": t4["label"], "trend4h_coins": len(t4["coins"])}
    write(res)


def write(res: dict) -> None:
    rows, g, pl_ = res["rows"], res["g"], res["pool"]
    pct = lambda v: f"{v * 100:.0f} %"  # noqa: E731
    lines = [f"# Alpaca books against gated BTC: results\n",
             f"Generated {res['generated']}. Registered in `results/gated_btc_prereg.md` before the run.\n",
             f"In sample {res['is_from']} to {res['is_to']}, out of sample {res['oos_from']} to {res['oos_to']} "
             f"({res['oos_days']} days). Daily books at 35 bps per unit of turnover (stress 70), coins Alpaca does "
             f"not list in cash; trend4h_pullback ({res['trend4h_label']}, {res['trend4h_coins']} coins, 1h bars) "
             "at fast_maker's maker base (stress: every order at the close at 70 bps). G = BTC at weight k while its "
             "close is above its 200-day average, k = the book's in-sample vol over G's at k = 1, capped at 1.\n",
             "## Verdict per book\n"]
    for r in rows:
        lines.append(f"- **{r['book']}**: {r['verdict']}. D {r['d_oos']:.2f} at {r['judged_at']} "
                     f"(book {r['book_oos']:.2f}, G at k {r['k']:.2f} {r['g_oos']:.2f}), band {r['boot_p05']:.2f} to "
                     f"{r['boot_p95']:.2f}, stress {r['d_stress']:.2f}, years {r['d2024']:.2f} / {r['d2025']:.2f} / "
                     f"{r['d2026']:.2f}, drawdown {pct(r['book_dd'])} against G's {pct(r['g_dd'])}. "
                     f"Failed: {r['fails']}.")
    lines.append("")
    lines.append("## Books and G\n")
    tab = [{**r, "book_dd_pct": r["book_dd"] * 100, "g_dd_pct": r["g_dd"] * 100,
            "book_cagr_pct": r["book_cagr"] * 100, "g_cagr_pct": r["g_cagr"] * 100} for r in rows]
    lines.append(dc.table(tab, ["book", "judged_at", "k", "vol_ratio_is", "vol_ratio_oos", "book_is", "g_is", "book_oos",
                                "g_oos", "book_cagr_pct", "g_cagr_pct", "book_dd_pct", "g_dd_pct", "book_stress",
                                "g_stress", "corr", "corr_btc"]))
    lines.append("\n## The difference D = book minus G\n")
    lines.append(dc.table(rows, ["book", "d_oos", "d_mean_ann", "boot_p05", "boot_p95", "boot_above0", "d_stress",
                                 "d2024", "d2025", "d2026", "d_years_pos", "d_deflated_p", "passes"]))
    lines.append(f"\nBootstrap: stationary, mean block {dc.BOOT_BLOCK} days, {dc.BOOT_DRAWS} draws, seed "
                 f"{dc.BOOT_SEED}, 5 % and 95 % of D's annual Sharpe. `d_mean_ann` is D's mean daily return x 365.\n")
    lines.append("\n## Per year (Sharpe at the judged cost)\n")
    lines.append(dc.table(rows, ["book", "b2024", "g2024", "d2024", "b2025", "g2025", "d2025", "b2026", "g2026", "d2026"]))
    lines.append("\n## Where the books earn: by the BTC gate at the previous close\n")
    lines.append(dc.table(rows, ["book", "book_sharpe_gate_on", "book_sharpe_gate_off", "book_ret_gate_off_ann"]))
    t4 = next(r for r in rows if r["book"] == "trend4h_pullback")
    lines.append(f"\ntrend4h_pullback with every order at the close at 35 bps (reported, not judged): Sharpe "
                 f"{t4.get('close35_oos', float('nan')):.2f}, D {t4.get('d_close35', float('nan')):.2f}.\n")
    lines.append("\n## G's own record at k = 1\n")
    lines.append(f"In sample {g['is']:.2f} (halves {g['h1']:.2f} / {g['h2']:.2f}). Out of sample {g['oos_35']:.2f} at "
                 f"35 bps, {g['oos_70']:.2f} at 70, CAGR {pct(g['cagr'])}, drawdown {pct(g['dd'])}; a close late "
                 f"{g['late']:.2f}; years {g['y2024']:.2f} / {g['y2025']:.2f} / {g['y2026']:.2f}; in BTC on "
                 f"{pct(g['exposure'])} of days, {g['switches_yr']:.1f} switches and {g['turnover_yr']:.1f}x turnover a "
                 f"year. BTC bought and held: {g['btc_oos']:.2f}, CAGR {pct(g['btc_cagr'])}, drawdown "
                 f"{pct(g['btc_dd'])}. Deflated p over the pool {g['deflated_p']:.4f}.\n")
    lines.append(dc.table([{"variant": "BTC above its 200-day average, k = 1", **g, "dd_pct": g["dd"] * 100,
                            "cagr_pct": g["cagr"] * 100}],
                          ["variant", "is", "h1", "h2", "oos_35", "oos_70", "cagr_pct", "dd_pct", "late", "y2024",
                           "y2025", "y2026", "boot_p05", "boot_p95", "deflated_p", "turnover_yr"]))
    lines.append("")
    for k, v in g["gates"].items():
        lines.append(f"- {k}: {'passed' if v else 'failed'}")
    lines.append("")
    if res["propose_paper_book"]:
        lines.append("No book passes and G passes G1 to G5: proposed as the lab paper book `btc_gated` "
                     "(autopilot-only signal, forward evidence only, off by default).\n")
    elif res["any_pass"]:
        lines.append("At least one book passes, so no G paper book is proposed.\n")
    else:
        lines.append("No book passes, but G fails at least one of G1 to G5: nothing is proposed.\n")
    lines.append(f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} "
                 f"factory, {pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of "
                 f"about {pl_['sr0_annual']:.2f}.\n")
    text = "\n".join(lines)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
