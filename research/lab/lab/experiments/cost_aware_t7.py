"""T7: train on what pays, models judged by the return after costs and turnover, not by hit rates.

Pre-registered in results/cost_aware_t7_prereg.md; results in results/cost_aware_t7.md.

    PYTHIA_AGENT_OUT=<panel cache> PYTHIA_TRIALS_REGISTRY=<registry> PYTHIA_MODEL_FACTORY_DIR=<dir> \
        flock <heavy lock> python -m lab.experiments.cost_aware_t7

Part A: G2's net target (lab.models.factory, net1): N_SPECS ridge_net specs drawn by the factory
(the first N_RANDOM at random, then mutations of the five best), each through the purged quarterly
screen 2021-23 at the costs of its era against the plain signal (the sign of the 30-day return in
the same book); the N_LOOKS best screen passes through the leak harness and a validation look
(2024-01-01 to 2026-06-30), DSR over R5's registry of all; a pass joins G2's shadows.

Part B: M1's meta-label as a size (lab.models.metalabel.sized) for tsmom1, breakout_top10 and F2's
Donchian 100/50 (T5's definitions on PIT20), filled a close late at the costs of their era, against
the plain rule and the plain filter (a probability under 0.5 out). The meta model is the factory's
LightGBM on M1's features, an expanding yearly walk from 2020, a trade's label known at its late exit.

Every spec and variant is a trial of R5's registry with its in-sample Sharpe, registered before any
validation number exists. The panels are cut at 2026-06-30 (part B) or scored to it (part A): the
lockbox is never read. Nothing here changes a book, a gate, the engine or a wallet.
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timezone

import numpy as np

from .. import metrics
from . import director_common as dc
from . import fam_common as fc
from . import pit_universe_t5 as t5

NAME = "cost_aware_t7"
SOURCE = "results/cost_aware_t7_prereg.md"
IS_FROM, IS_TO, VAL_FROM, VAL_TO = "2020-08-01", "2023-12-31", "2024-01-01", "2026-06-30"
TARGET, RUN = "net1", "t7"
N_SPECS, N_RANDOM, N_LOOKS = 32, 16, 2
RULES, UNIVERSE, UNI_SIZE = ("tsmom1", "breakout_top10", "donchian_100_50"), "PIT20", 20
META_LEARNER, META_MIN_TRAIN, META_FIRST_YEAR, LAG = "lgb", 40, 2020, 1
VARIANTS = ("plain", "filter", "size")
DSR_PASS = 0.95


# ---------------------------------------------------------------- part A: the net target

def plain_trial(j: dict) -> dict:
    return {"id": "factory:t7_net:plain_signal", "family": "factory", "n": 1, "sharpe": float(j["base_sharpe"]),
            "source": SOURCE}


def screen_pbo(series: dict) -> dict | None:
    """PBO by CSCV of the specs' daily screen nets on the days every one of them scored."""
    xs = [v for v in series.values() if len(v["days"])]
    if len(xs) < 2:
        return None
    days = xs[0]["days"]
    for v in xs[1:]:
        days = np.intersect1d(days, v["days"])
    M = np.column_stack([v["net"][np.searchsorted(v["days"], days)] for v in xs])
    return metrics.cscv(M)


def by_kappa(rows: list[dict]) -> list[dict]:
    """The family by its turnover penalty: specs, median screen Sharpe, gross Sharpe and turnover a year."""
    out = []
    for k in sorted({r["spec"]["params"]["kappa"] for r in rows}):
        rs = [r for r in rows if r["spec"]["params"]["kappa"] == k and r.get("fitness") is not None]
        if rs:
            out.append({"kappa": k, "specs": len(rs), "median_sharpe": float(np.median([r["fitness"] for r in rs])),
                        "median_gross": float(np.median([r["screen"]["gross_sharpe"] for r in rs])),
                        "median_turnover": float(np.median([r["screen"]["turnover_pa"] for r in rs])),
                        "screen_passes": sum(1 for r in rs if r["screen_pass"])})
    return out


def net_part(P=None, register: bool = True, admit: bool = True, log=print) -> dict:
    from ..models import factory as F
    P = P or F.Panels()
    rng = random.Random(RUN)
    rows, have, series = [], set(), {}
    for i in range(N_SPECS):
        s = F.net_draw(rng, P, TARGET, rows, have, 1.0 if i < N_RANDOM else 0.0)
        if s is None:
            break
        r = F.net_trial(P, s, RUN, series)
        rows.append(r)
        have.add(r["key"])
        log(f"  net {r['key']} {r['what']}: screen {r.get('fitness')}"
            f"{' (' + r['error'] + ')' if r.get('error') else ''}")
    ok = [r for r in rows if r.get("screen")]
    plain = ok[0]["screen"] if ok else None
    trials = [F.net_registry_row(r, SOURCE) for r in rows] + ([plain_trial(plain)] if plain else [])
    if register:
        metrics.register(trials)                         # before any validation number exists
    F._append(F.net_ledger_path(), rows)
    pool = metrics.trial_pool(extra=dc.ledger_trials() + trials)
    from ..leak import checks
    bad = checks.bad_inputs()
    passes = sorted((r for r in rows if r.get("screen_pass")), key=lambda r: -r["fitness"])[:N_LOOKS]
    looks = []
    for r in passes:
        if why := F.leak_reason(P, r, bad):
            F._append(F.net_holdout_path(), [{"key": r["key"], "run": RUN, "status": "leak", "why": why}])
            looks.append({"key": r["key"], "what": r["what"], "status": "leak", "why": why, "passed": False})
            continue
        h = F.net_look(P, r, pool, RUN)
        ser = h.pop("series")
        lo, hi, _ = dc.boot_band(ser["net"], ser["base"])
        try:
            cp = F.net_cpcv(P, TARGET, r["spec"])
        except Exception as e:           # noqa: BLE001 (a yardstick must not stop the run)
            cp = {"error": f"{type(e).__name__}: {e}"[:200]}
        looks.append({**h, "what": r["what"], "band": [lo, hi], "cpcv": cp,
                      "needed_sharpe": needed(ser["net"], pool)})
        log(f"  look {r['key']}: validation {h['held']['sharpe']:.2f} vs plain {h['held']['base_sharpe']:.2f}, "
            f"DSR {h['dsr']:.3f}, {'PASSED' if h['passed'] else 'failed'}")
    admitted = []
    if admit and any(h.get("passed") for h in looks):
        admitted = F.admit([h for h in looks if h.get("passed")], {r["key"]: r for r in rows},
                           datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    return {"specs": [{k: r.get(k) for k in ("key", "what", "fitness", "screen_pass", "error")} |
                      {"screen": r.get("screen"), "kappa": r["spec"]["params"]["kappa"]} for r in rows],
            "plain_screen": plain, "pbo": screen_pbo(series), "by_kappa": by_kappa(ok), "looks": looks,
            "admitted": admitted, "pool": {"n_trials": pool["n_trials"], "sr0_annual": pool["sr0_annual"]},
            "trials": [t["id"] for t in trials]}


def needed(x: np.ndarray, pool: dict) -> float:
    from .two_leads_t6 import needed_sharpe
    return needed_sharpe(x, pool, DSR_PASS)


# ---------------------------------------------------------------- part B: meta-labelling as a size

def held(W: np.ndarray, reb: np.ndarray) -> np.ndarray:
    """The targets in force each day: W on a rebalance day (a NaN entry keeps the one before), else the day
    before's."""
    out = np.zeros_like(W)
    cur = np.zeros(W.shape[1])
    for t in range(len(W)):
        if reb[t]:
            cur = np.where(np.isnan(W[t]), cur, W[t])
        out[t] = cur
    return out


def yearly_blocks(days: np.ndarray, first: int = META_FIRST_YEAR) -> list[tuple[int, int]]:
    yrs = dc.years_of(days)
    return [(int(np.flatnonzero(yrs == y)[0]), int(np.flatnonzero(yrs == y)[-1]) + 1)
            for y in range(first, int(yrs[-1]) + 1) if (yrs == y).any()]


def meta_probability(px: np.ndarray, H: np.ndarray, btc: int, C: np.ndarray, blocks, log=print) -> dict:
    """M1's meta model on the trades of held targets H: labels of the late trade at the era's round trip, the
    factory's learner in an expanding walk (a block trained on the trades whose label was known before it), a trade
    still open at the end from the trades closed before it opened."""
    from ..models import factory as F
    from ..models import metalabel as ML
    tr = ML.trades(H)
    y = ML.labels(px, tr, C, LAG)
    X = ML.features(px, H, tr, btc)
    t = np.array([a for _, a, _ in tr], dtype=float)
    known = ML.known_at(tr, len(H), LAG)
    lab = np.isfinite(y)
    p = np.full(len(tr), np.nan)
    if lab.sum() >= META_MIN_TRAIN:
        w = F.walk(X[lab], y[lab], t[lab], known[lab], blocks, [META_LEARNER], min_train=META_MIN_TRAIN, log=log)
        p[lab] = w["p"][META_LEARNER]
    for k in np.flatnonzero(~lab & (t >= blocks[0][0])):
        ok = lab & (known < t[k])
        if ok.sum() >= META_MIN_TRAIN:
            p[k] = F.make(META_LEARNER).fit(X[ok], y[ok]).predict_proba(X[k:k + 1])[0]
    return {"trades": tr, "y": y, "p": p, "t": t}


def auc(y: np.ndarray, p: np.ndarray) -> float | None:
    """Rank AUC of probabilities against 0/1 labels (ties at half)."""
    ok = np.isfinite(y) & np.isfinite(p)
    y, p = y[ok], p[ok]
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    if not n1 or not n0:
        return None
    from scipy.stats import rankdata
    r = rankdata(p)
    return float((r[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def factors(H: np.ndarray, mp: dict) -> dict[str, np.ndarray]:
    """Per variant the factor on each day's target: 1 (plain), 0 or 1 (filter: a trade under 0.5 out), the trade's
    probability clipped to 0 to 1 (size)."""
    from ..models import metalabel as ML
    one = np.ones_like(H)
    return {"plain": one, "filter": ML.filtered(one, mp["trades"], mp["p"]), "size": ML.sized(one, mp["trades"], mp["p"])}


def variant(W: np.ndarray, f: np.ndarray) -> np.ndarray:
    """The rule's targets times a factor where they decide (a NaN entry still holds)."""
    return np.where(np.isfinite(W), W * f, W)


def meta_trial(rule: str, variant: str, is_sharpe: float) -> dict:
    id_ = f"hand:t5_pit:{rule}:{UNIVERSE}" if variant == "plain" else f"hand:t7_meta:{rule}:{variant}"
    return {"id": id_, "family": "hand", "n": 1, "sharpe": float(is_sharpe),
            "source": "results/pit_universe_t5_prereg.md" if variant == "plain" else SOURCE}


def meta_part(P: fc.Panel, vol: np.ndarray, delist=None, register: bool = True, log=print) -> dict:
    from .. import universe as U
    uni = U.pit(P, UNI_SIZE, table=delist, vol=vol)
    C = t5.era_cost(vol, False)
    Pu = t5.on(P, uni)
    ins, val = t5.window(P, IS_FROM, IS_TO), t5.window(P, VAL_FROM, VAL_TO)
    blocks = yearly_blocks(P.days)
    series, rows, trials = {}, [], []
    for rule in RULES:
        (W, reb, start), = t5.books(Pu, rule, UNI_SIZE)
        H = held(W, reb)
        mp = meta_probability(P.px, H, P.btc, C, blocks, log)
        fs = factors(H, mp)
        for v in VARIANTS:
            Wl, rl = t5.late(variant(W, fs[v]), reb)
            series[(rule, v)] = t5.simulate(Pu, Wl, rl, C, False, start)[0]
            trials.append(meta_trial(rule, v, t5.stats_of(series[(rule, v)][ins])["sharpe"]))
        t_in = mp["t"].astype(int)
        scored = np.isfinite(mp["p"]) & np.isfinite(mp["y"])
        iv, vv = ins[t_in] & scored, val[t_in] & scored
        inside = H > 0
        fv = fs["size"][inside & val[:, None]]
        rows.append({"rule": rule, "trades": len(mp["trades"]), "labelled": int(np.isfinite(mp["y"]).sum()),
                     "with_p": int(np.isfinite(mp["p"]).sum()),
                     "pay_rate_val": float(mp["y"][vv].mean()) if vv.any() else None,
                     "auc_is": auc(mp["y"][iv], mp["p"][iv]), "auc_val": auc(mp["y"][vv], mp["p"][vv]),
                     "mean_size_val": float(fv.mean()) if len(fv) else None,
                     "max_scale": float(fs["size"][inside].max()) if inside.any() else 0.0})
        log(f"  meta {rule}: {len(mp['trades'])} trades, in sample " + ", ".join(
            f"{v} {trials[-3 + i]['sharpe']:.2f}" for i, v in enumerate(VARIANTS)))
    if register:
        metrics.register(trials)                         # before any validation number exists
    pool = metrics.trial_pool(extra=dc.ledger_trials() + trials)
    for r in rows:
        rule = r["rule"]
        r["is"] = {v: t5.stats_of(series[(rule, v)][ins]) for v in VARIANTS}
        r["val"] = {v: {**t5.stats_of(series[(rule, v)][val]), "dsr": metrics.dsr(series[(rule, v)][val], pool)}
                    for v in VARIANTS}
        x, x0 = series[(rule, "size")][val], series[(rule, "plain")][val]
        lo, hi, share = dc.boot_band(x, x0)
        vs = r["val"]
        r["band_size_vs_plain"] = [lo, hi, share]
        r["needed_sharpe"] = needed(x, pool)
        r["conditions"] = {"above plain": vs["size"]["sharpe"] > vs["plain"]["sharpe"],
                           "above filter": vs["size"]["sharpe"] > vs["filter"]["sharpe"],
                           "band 5 % above 0": lo > 0, "DSR all": vs["size"]["dsr"] >= DSR_PASS}
        r["passes"] = all(r["conditions"].values())
    return {"rows": rows, "trials": [t["id"] for t in trials],
            "pool": {"n_trials": pool["n_trials"], "sr0_annual": pool["sr0_annual"]}}


# ---------------------------------------------------------------- the report

def _pct(v) -> str:
    return "n/a" if v is None else f"{v * 100:.1f} %"


def _f(v, fmt=".2f") -> str:
    return "n/a" if v is None else format(v, fmt)


def markdown(out: dict) -> str:
    a, b = out["A"], out["B"]
    md = [f"Generated {out['generated']}. In sample to {IS_TO}, validation {VAL_FROM} to {VAL_TO}; the lockbox not "
          f"read. Costs: {out['costs']}.\n", "## A. The net target (G2, net1)\n"]
    pl_ = a["plain_screen"]
    if pl_:
        md.append(f"Screen 2021-01-01 to 2023-12-31, purged quarterly walk-forward: the plain signal (sign of the "
                  f"30-day return, same book and costs) makes net Sharpe {pl_['base_sharpe']:.2f} at "
                  f"{pl_['base_turnover_pa']:.0f}x turnover a year.\n")
    t = [{"turnover penalty kappa": f"{k['kappa']:g}", "specs": k["specs"],
          "median net Sharpe": f"{k['median_sharpe']:.2f}", "median gross Sharpe": f"{k['median_gross']:.2f}",
          "median turnover a year": f"{k['median_turnover']:.0f}x", "screen passes": k["screen_passes"]}
         for k in a["by_kappa"]]
    if t:
        md.append(dc.table(t, list(t[0])) + "\n")
    best = sorted((s for s in a["specs"] if s.get("fitness") is not None), key=lambda s: -s["fitness"])[:5]
    t = [{"spec": s["key"], "what": s["what"], "net Sharpe": f"{s['fitness']:.2f}",
          "gross": f"{s['screen']['gross_sharpe']:.2f}", "turnover a year": f"{s['screen']['turnover_pa']:.0f}x",
          "screen": "pass" if s["screen_pass"] else "fail"} for s in best]
    if t:
        md.append("Best five by screen net Sharpe:\n\n" + dc.table(t, list(t[0])) + "\n")
    errs = sum(1 for s in a["specs"] if s.get("error"))
    pb = a["pbo"]
    md.append(f"{len(a['specs'])} specs ({errs} errors), {sum(1 for s in a['specs'] if s.get('screen_pass'))} screen "
              f"passes (net Sharpe above 0 and above the plain signal). PBO of the family's screen nets "
              f"{_f(pb and pb['pbo'])} over {pb['genomes'] if pb else 0} specs (CSCV, 16 blocks).\n")
    if not a["looks"]:
        md.append("No validation look: no screen pass.\n")
    for h in a["looks"]:
        if h.get("status") == "leak":
            md.append(f"- {h['key']}: rejected by the leak harness before its look ({h['why']}).")
            continue
        j, cp = h["held"], h.get("cpcv") or {}
        md.append(f"- {h['key']} ({h['what']}): validation net Sharpe {j['sharpe']:.2f} against the plain signal's "
                  f"{j['base_sharpe']:.2f} (difference band {h['band'][0]:+.2f} to {h['band'][1]:+.2f}), turnover "
                  f"{j['turnover_pa']:.0f}x a year, DSR {h['dsr']:.3f} over {h['n_trials']:,} trials (bar about "
                  f"{h['needed_sharpe']:.2f}); CPCV of the screen excess over the plain signal median "
                  f"{_f(cp.get('median'))}, 10th percentile {_f(cp.get('p10'))}; "
                  f"**{'passes' if h['passed'] else 'fails'}**.")
    md.append(f"\nShadows admitted: {', '.join(a['admitted']) or 'none'}. Trials: {len(a['trials'])} "
              f"(`factory:t7_net:<key>` and `factory:t7_net:plain_signal`).\n")
    md.append(f"## B. Meta-labelling as a size ({UNIVERSE}, late, costs of their era)\n")
    t = []
    for r in b["rows"]:
        v = r["val"]
        t.append({"rule": r["rule"], "trades (labelled, with p)": f"{r['trades']} ({r['labelled']}, {r['with_p']})",
                  "AUC in sample / validation": f"{_f(r['auc_is'])} / {_f(r['auc_val'])}",
                  "in sample plain / filter / size": " / ".join(f"{r['is'][k]['sharpe']:.2f}" for k in VARIANTS),
                  "validation plain / filter / size": " / ".join(f"{v[k]['sharpe']:.2f}" for k in VARIANTS),
                  "validation DD plain / size": f"{_pct(v['plain']['max_dd'])} / {_pct(v['size']['max_dd'])}",
                  "mean size": _f(r["mean_size_val"]),
                  "size - plain, 90 % band": f"{r['band_size_vs_plain'][0]:+.2f} to {r['band_size_vs_plain'][1]:+.2f}",
                  "DSR size": f"{v['size']['dsr']:.3f}", "verdict": "pass" if r["passes"] else "fail"})
    if not t:
        return "\n".join(md) + "\n"
    md.append(dc.table(t, list(t[0])) + "\n")
    md.append(f"Sizing passes with a validation Sharpe above the plain rule and the plain filter, the bootstrap band "
              f"of size minus plain above 0 at 5 % and a DSR of 0.95 or more over the registry's pool of all "
              f"({b['pool']['n_trials']:,} trials, noise bar {b['pool']['sr0_annual']:.2f} a year). Highest scale "
              f"of a rule's weight: {max(r['max_scale'] for r in b['rows']):.2f} (never above 1).\n")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    register = "--no-register" not in argv
    t0 = time.time()
    A = net_part(register=register, admit="--no-admit" not in argv)
    print(f"part A done, {time.time() - t0:.0f} s", flush=True)
    from .. import universe as U
    from ..collect import book_depth
    delist = book_depth.read_delistings()
    delist = delist if len(delist) else None
    P = dc.cut_panel(fc.load_panel(), VAL_TO)
    vol = U.median_volume(P)
    B = meta_part(P, vol, delist, register)
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "A": A, "B": B,
           "costs": (f"part A the USD-M taker {t5.PERP_FEE * 1e4:.0f} bps plus T5's half-spread tiers (1 to 50 bps by "
                     f"the coin's 30-day median dollar volume) per unit of one-way turnover, filled at the close; "
                     f"part B the spot taker {t5.SPOT_FEE * 1e4:.0f} bps plus the same tiers, one close late; T4's "
                     f"delisting table {'present' if delist is not None else 'not present'}"),
           "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    dc.write_results(NAME, markdown(out), "# T7: train on what pays\n")
    print(f"done in {out['seconds']} s; net looks passed {sum(1 for h in A['looks'] if h.get('passed'))}, "
          f"meta sizing passes {[r['rule'] for r in B['rows'] if r['passes']] or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
