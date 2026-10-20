"""Is the factory's shadow low-vol genome 44444c97ba5e anything more than its BTC gates?

    python -m lab.experiments.genome_gates               the registered run
    python -m lab.experiments.genome_gates --reproduce   only the genome's held-back numbers

Pre-registered in results/genome_gates_prereg.md (committed before this file ran).
The genome exactly as the factory checked it (lab.factory.build, every 3 days,
band 50 %) on the held-back window 2024-01-01 to 2026-10-14, against null A (the
same genome choosing its 5 by liquidity instead of low vol) and null B (BTC alone
under the same filters, through the same simulator). Writes results/genome_gates.md
below the marker and <reports>/genome_gates/latest.{md,json}.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timezone

import numpy as np

from .. import report
from ..factory import build, evaluate, grammar
from . import director_common as dc
from . import fam_common as fc

NAME = "genome_gates"
KEY = "44444c97ba5e"
LAST_DAY = "2026-10-14"
FACTORY_35, FACTORY_70 = 0.8762735226381085, 0.689476946196114
REPRO_TOL = 0.03
COSTS = {"35bps": build.COSTS["35bps"], "70bps": build.COSTS["70bps"]}
YEARS_OOS = (2024, 2025, 2026)


def genome() -> dict:
    meta = json.loads((dc.RESULTS / "factory_seed" / "shadow" / f"{KEY}.json").read_text(encoding="utf-8"))
    g = grammar.canonical(meta["genome"])
    assert grammar.key(g) == KEY, grammar.key(g)
    return g


def null_a(g: dict) -> dict:
    a = copy.deepcopy(g)
    a["select"]["rank"] = "liquidity"
    return grammar.canonical(a)


def null_b_weights(c: build.Ctx, g: dict) -> np.ndarray:
    """BTC alone at full weight on the closes where every one of the genome's filters lets it in."""
    j = int(np.flatnonzero(c.cols == c.P.btc)[0])
    on = np.ones(c.T, dtype=bool)
    with np.errstate(invalid="ignore"):
        for f in g["filters"]:
            if f["kind"] == "regime":
                on &= build.btc_gate(c, "regime", f["ma"])
            elif f["kind"] == "btcmom":
                on &= build.btc_gate(c, "btcmom", f["lb"])
            elif f["kind"] == "vol":
                on &= np.nan_to_num(build.annvol(c)[:, j] < f["max"], nan=0.0).astype(bool)
            else:
                raise ValueError(f"filter {f['kind']} not expected in {KEY}")
    W = np.zeros((c.T, len(c.cols)))
    W[on, j] = 1.0
    return W


def series(c: build.Ctx, W: np.ndarray, g: dict) -> dict:
    r = g["rebalance"]
    gross, tov, expo = build.simulate(c, W, r["every"], r["band"])
    return {"gross": gross, "tov": tov, "expo": expo, **{k: build.net(gross, tov, v) for k, v in COSTS.items()}}


def describe(name: str, s: dict, oos: np.ndarray, years: np.ndarray) -> dict:
    row = {"book": name}
    for k in COSTS:
        p = dc.perf(s[k][oos])
        row[f"sharpe_{k}"] = p["sharpe"]
        row[f"cagr_{k}"] = p["cagr"]
        row[f"dd_{k}"] = p["max_dd"]
    for y in YEARS_OOS:
        row[f"y{y}"] = dc.sharpe(s["35bps"][oos & (years == y)])
    row["exposure"] = float(s["expo"][oos].mean())
    row["cash_days"] = float((s["expo"][oos] <= 1e-9).mean())
    row["turnover_yr"] = float(s["tov"][oos].sum() / (oos.sum() / 365))
    return row


def main() -> None:
    reproduce_only = "--reproduce" in sys.argv
    P = dc.cut_panel(fc.load_panel(), LAST_DAY)
    c = build.make_ctx(P)
    w = evaluate.windows(c)
    oos = w["oos"]
    years = dc.years_of(c.days)
    g = genome()
    sg = series(c, build.weights(c, g), g)
    repro = {"from": dc.day_str(c.days[oos][0]), "to": dc.day_str(c.days[oos][-1]), "days": int(oos.sum()),
             "sharpe_35bps": dc.sharpe(sg["35bps"][oos]), "sharpe_70bps": dc.sharpe(sg["70bps"][oos]),
             "factory_35bps": FACTORY_35, "factory_70bps": FACTORY_70}
    repro["ok"] = abs(repro["sharpe_35bps"] - FACTORY_35) <= REPRO_TOL
    print(f"genome {KEY} held back {repro['from']} to {repro['to']} ({repro['days']} days): "
          f"{repro['sharpe_35bps']:.4f} at 35 bps (factory {FACTORY_35:.4f}), "
          f"{repro['sharpe_70bps']:.4f} at 70 (factory {FACTORY_70:.4f})", flush=True)
    if reproduce_only:
        return
    if not repro["ok"]:
        raise SystemExit(f"the rebuilt panel does not reproduce the factory's {FACTORY_35:.2f} within {REPRO_TOL}; "
                         "the registration says stop here")
    ga = null_a(g)
    sa = series(c, build.weights(c, ga), ga)
    sb = series(c, null_b_weights(c, g), g)
    rows = [describe(f"genome {KEY}", sg, oos, years), describe("null A: same genome, best 5 by liquidity", sa, oos, years),
            describe("null B: BTC alone under the same filters", sb, oos, years)]
    btc = np.nan_to_num(P.ret[:, P.btc])
    pbtc = dc.perf(btc[oos])
    diffs = []
    for tag, s0 in (("D_A (genome minus null A)", sa), ("D_B (genome minus null B)", sb)):
        d = {k: sg[k][oos] - s0[k][oos] for k in COSTS}
        lo, hi, above = dc.boot_band(sg["35bps"][oos] - s0["35bps"][oos])
        row = {"difference": tag, "sharpe_35bps": dc.sharpe(d["35bps"]), "sharpe_70bps": dc.sharpe(d["70bps"]),
               "mean_ann_35bps": float(d["35bps"].mean() * 365), "boot_p05": lo, "boot_p95": hi, "boot_above0": above,
               "corr": float(np.corrcoef(sg["35bps"][oos], s0["35bps"][oos])[0, 1])}
        for y in YEARS_OOS:
            m = years[oos] == y
            row[f"y{y}"] = dc.sharpe(d["35bps"][m])
        diffs.append(row)
    # Trials: null A, null B, D_A, D_B (annual Sharpes at 35 bps).
    trial_sr = [rows[1]["sharpe_35bps"], rows[2]["sharpe_35bps"], diffs[0]["sharpe_35bps"], diffs[1]["sharpe_35bps"]]
    pl_ = dc.pool(trial_sr)
    for r_, s_ in zip(rows, (sg, sa, sb)):
        r_["deflated_p"] = dc.deflated(s_["35bps"][oos], pl_)
    for d_, s0 in zip(diffs, (sa, sb)):
        d_["deflated_p"] = dc.deflated(sg["35bps"][oos] - s0["35bps"][oos], pl_)
    # Overlap with null A: the decided target sets.
    Wg, Wa = build.weights(c, g), build.weights(c, ga)
    hg, ha = Wg[oos] > 0, Wa[oos] > 0
    any_ = hg.any(1) | ha.any(1)
    same = (hg == ha).all(1) & any_
    overlap = {"same_set_share": float(same.sum() / max(any_.sum(), 1)),
               "mean_shared_coins": float((hg & ha).sum(1)[any_].mean()) if any_.any() else 0.0,
               "days_with_targets": int(any_.sum())}
    # Which coins the genome holds most (share of its invested target weight).
    tot = Wg[oos].sum(0)
    top = np.argsort(-tot)[:10]
    coins = [{"coin": c.names[j], "share": float(tot[j] / tot.sum())} for j in top if tot[j] > 0]
    da, db = diffs
    passed = all(x["sharpe_35bps"] > 0 and x["sharpe_70bps"] > 0 and x["boot_p05"] > 0 for x in diffs)
    killed = da["sharpe_35bps"] <= 0 or db["sharpe_35bps"] <= 0
    verdict = "pass" if passed else ("kill" if killed else "inconclusive")
    res = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "key": KEY,
           "name": grammar.describe(g), "null_a": grammar.describe(ga), "reproduce": repro, "rows": rows,
           "diffs": diffs, "overlap": overlap, "coins": coins, "pool": pl_, "verdict": verdict,
           "confirmed": passed and rows[0]["deflated_p"] > 0.95,
           "btc": {"sharpe": pbtc["sharpe"], "dd": pbtc["max_dd"], "cagr": pbtc["cagr"]}}
    write(res)


def write(res: dict) -> None:
    rp, rows, diffs, ov, pl_ = res["reproduce"], res["rows"], res["diffs"], res["overlap"], res["pool"]
    v = {"pass": "**Pass.** The signal adds to the gates.",
         "kill": "**Kill.** The genome's held-back result is an effect of its gates.",
         "inconclusive": "**Inconclusive.** Not shown to add to its gates."}[res["verdict"]]
    md = [f"# Genome {res['key']} against its gates: results\n",
          f"Generated {res['generated']}. Registered in `results/genome_gates_prereg.md` before the run.\n",
          f"Genome: {res['name']}. Null A: {res['null_a']}. Null B: BTC alone at full weight while the same "
          f"three filters let it in, same cadence and band.\n",
          f"Held back {rp['from']} to {rp['to']} ({rp['days']} days). Reproduced: {rp['sharpe_35bps']:.3f} at 35 bps "
          f"and {rp['sharpe_70bps']:.3f} at 70 (factory {rp['factory_35bps']:.3f} / {rp['factory_70bps']:.3f}). "
          f"BTC bought and held: Sharpe {res['btc']['sharpe']:.2f}, drawdown {res['btc']['dd'] * 100:.0f} %.\n",
          f"## Verdict\n\n{v}\n",
          "## The genome and the nulls\n",
          dc.table([{**r, **{f"{k}_pct": r[k] * 100 for k in ("dd_35bps", "cagr_35bps", "exposure", "cash_days")}}
                    for r in rows],
                   ["book", "sharpe_35bps", "sharpe_70bps", "cagr_35bps_pct", "dd_35bps_pct", "y2024", "y2025", "y2026",
                    "exposure_pct", "cash_days_pct", "turnover_yr", "deflated_p"]),
          "\n## The differences\n",
          dc.table(diffs, ["difference", "sharpe_35bps", "sharpe_70bps", "mean_ann_35bps", "boot_p05", "boot_p95",
                           "boot_above0", "y2024", "y2025", "y2026", "corr", "deflated_p"]),
          f"\nBootstrap: stationary, mean block {dc.BOOT_BLOCK} days, {dc.BOOT_DRAWS} draws, seed {dc.BOOT_SEED}, "
          "5 % and 95 % of the Sharpe of the daily difference at 35 bps.\n",
          f"\nOverlap with null A: the two target sets are identical on {ov['same_set_share'] * 100:.0f} % of the "
          f"{ov['days_with_targets']} held-back days on which either holds anything; they share "
          f"{ov['mean_shared_coins']:.1f} coins on average.\n",
          "\nThe genome's held-back target weight by coin: "
          + ", ".join(f"{x['coin']} {x['share'] * 100:.0f} %" for x in res["coins"]) + ".\n",
          f"\n## Pool\n\n{pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand, {pl_['factory_trials']} factory, "
          f"{pl_['today_trials']} registered today); the best noise trial sits at an annual Sharpe of about "
          f"{pl_['sr0_annual']:.2f}. The genome's deflated p over it: {rows[0]['deflated_p']:.4f}.\n"]
    text = "\n".join(md)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
