"""X16 B2: exit timing on the live crypto books, and M14 (their remaining-return model).

    python -m lab.experiments.exit_overlays

Pre-registered in results/equities_training_prereg.md (part B2 and M14).

Books: breakout_top10, tsmom_top20 and tsmom_tranches as the autopilot runs
them on Alpaca (the 15 Alpaca coins, the rest in cash; X6's `fo.run_books`),
35 bps per unit of turnover; the twin is the original book on every coin.

A spell is a run of closes after which the book holds a coin. An exit fires
on a close inside a spell and cuts the coin from that close to the end of the
spell (it comes back only when the book's own rule enters it again); the
freed weight stays in cash. The overlaid book is the original's post-trade
weights with the cut coins at 0, run through au.sim_daily; the reference is
the same machinery without cuts.

Exits per book: time 20 and 40 days; ATR(14) trail 2 and 3; target at the
entry close x (1 + m x 30-day vol x sqrt 20), m 2 and 3; M14's forecast of the
next 10 days' log return below -70 bps (a round trip at 35 bps a side). 21
trials, and per book the in-sample pick (best 35 bps Sharpe 2020-08-01 to
2023-12-31) a day late and on the twin: 6. Gates: X6's six.

Writes results/exit_overlays.md (PYTHIA_RESULTS or the repo's results/) and
<reports>/exit_overlays/latest.json.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from .. import report
from ..equities import features as fe
from . import alpaca_universe as au
from . import fam_common as fc
from . import flow_overlays as fo

NAME = "exit_overlays"
MARKER = "<!-- generated below by lab.experiments.exit_overlays; edit above this line only -->"
BOOKS = ("breakout", "tsmom_daily", "tsmom_tranches")
ORIGINAL = au.ORIGINAL
COST = 0.0035
YEARS_OOS = (2024, 2025, 2026)
TRIALS = 27
MODEL_THR = -0.0070
H_MODEL = 10
TARGET_DAYS = 20
SEED = 20261021
RESULTS = Path(os.environ.get("PYTHIA_RESULTS", str(Path(__file__).resolve().parents[2] / "results")))


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%H:%M:%S} {NAME}: {msg}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Inputs on the crypto panel
# ---------------------------------------------------------------------------

def crypto_inputs(P: fc.Panel) -> dict[str, np.ndarray]:
    if "x16" in P.extra:
        return P.extra["x16"]
    px = P.px
    pc = np.full(px.shape, np.nan)
    pc[1:] = px[:-1]
    hi = np.where(np.isfinite(P.high), np.fmax(P.high, pc), np.nan)
    lo = np.where(np.isfinite(P.low), np.fmin(P.low, pc), np.nan)
    tr = np.where(np.isfinite(hi) & np.isfinite(lo), hi - lo, np.abs(px - pc))
    tr = np.where(P.traded, tr, np.nan)
    rv = P.extra["rv"]
    qv = np.where(P.alive, P.extra["qv"], np.nan)

    def lag_log(k: int) -> np.ndarray:
        out = np.full(px.shape, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[k:] = np.log(px[k:] / px[:-k])
        return out

    with np.errstate(invalid="ignore", divide="ignore"):
        ma50 = fc.rolling(px, 50, 40)
        out = {"atr": fc.rolling(tr, 14, 10), "mom7": lag_log(7), "mom28": lag_log(28),
               "vol_ratio": np.sqrt(fc.rolling(rv, 7, 5)) / P.sigma, "dist_ma50": np.log(px / ma50),
               "qv_ratio": np.log(fc.rolling(qv, 7, 5) / fc.rolling(qv, 28, 20))}
    b = P.btc
    out["btc_mom28"] = out["mom28"][:, b]
    out["btc_on"] = P.btc_on.astype(float)
    P.extra["x16"] = out
    return out


def spells(P: fc.Panel, held: np.ndarray) -> dict[str, np.ndarray]:
    """Spell start row, entry close and running peak close for every held cell (NaN/-1 elsewhere)."""
    on = held > 1e-12
    T, N = on.shape
    start = np.full((T, N), -1, dtype=np.int64)
    peak = np.full((T, N), np.nan)
    cur_s = np.full(N, -1, dtype=np.int64)
    cur_p = np.full(N, np.nan)
    px = P.px
    for t in range(T):
        new = on[t] & ~on[t - 1] if t else on[t].copy()
        cur_s = np.where(new, t, np.where(on[t], cur_s, -1))
        p = px[t]
        cur_p = np.where(new, p, np.where(on[t], np.fmax(cur_p, p), np.nan))
        start[t] = cur_s
        peak[t] = cur_p
    ok = start >= 0
    entry = np.full((T, N), np.nan)
    tt, jj = np.nonzero(ok)
    entry[tt, jj] = px[start[tt, jj], jj]
    return {"on": on, "start": start, "entry": entry, "peak": peak}


def cut_from(fire: np.ndarray, sp: dict, late: bool = False) -> np.ndarray:
    """(T, N) cells cut: from the firing close (late: the close after) to the end of the spell."""
    on, start = sp["on"], sp["start"]
    T, N = on.shape
    cut = np.zeros((T, N), dtype=bool)
    active = np.zeros(N, dtype=bool)
    for t in range(T):
        new = on[t] & (start[t] == t)
        prev = np.where(new, False, active) & on[t]
        active = (prev | (fire[t] & on[t]))
        cut[t] = prev if late else active
    return cut


def fires(P: fc.Panel, sp: dict, rule: str, x: float, pred: np.ndarray | None = None) -> np.ndarray:
    on, start, entry, peak = sp["on"], sp["start"], sp["entry"], sp["peak"]
    t_ix = np.arange(P.T)[:, None]
    with np.errstate(invalid="ignore"):
        if rule == "time":
            f = on & (t_ix - start >= x)
        elif rule == "atr":
            atr = crypto_inputs(P)["atr"]
            f = on & np.isfinite(atr) & (P.px < peak - x * atr)
        elif rule == "target":
            s0 = np.full(P.sigma.shape, np.nan)
            tt, jj = np.nonzero(on)
            s0[tt, jj] = P.sigma[start[tt, jj], jj]
            f = on & np.isfinite(s0) & (P.px >= entry * (1 + x * s0 * math.sqrt(TARGET_DAYS)))
        elif rule == "model":
            f = on & np.isfinite(pred) & (pred < x)
        else:
            raise ValueError(rule)
    return f


# ---------------------------------------------------------------------------
# M14
# ---------------------------------------------------------------------------

def held_rows(P: fc.Panel, sp: dict, mask: np.ndarray | None = None) -> pl.DataFrame:
    """Feature rows for every held cell of one book (mask: which cells)."""
    X = crypto_inputs(P)
    on = sp["on"] if mask is None else sp["on"] & mask
    tt, jj = np.nonzero(on)
    px = P.px[tt, jj]
    with np.errstate(invalid="ignore", divide="ignore"):
        ret = np.log(px / sp["entry"][tt, jj])
        dd = np.log(px / sp["peak"][tt, jj])
        dd_atr = (px - sp["peak"][tt, jj]) / X["atr"][tt, jj]
    return pl.DataFrame({
        "t": tt, "j": jj, "days_held": (tt - sp["start"][tt, jj] + 1).astype(float), "ret_entry": ret,
        "dd_peak": dd, "dd_atr": dd_atr, "mom7": X["mom7"][tt, jj], "mom28": X["mom28"][tt, jj],
        "vol30": P.sigma[tt, jj], "vol_ratio": X["vol_ratio"][tt, jj], "dist_ma50": X["dist_ma50"][tt, jj],
        "qv_ratio": X["qv_ratio"][tt, jj], "btc_mom28": X["btc_mom28"][tt], "btc_on": X["btc_on"][tt]})


def m14_target(P: fc.Panel) -> np.ndarray:
    out = np.full((P.T, P.N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        out[:-H_MODEL] = np.log(P.px[H_MODEL:] / P.px[:-H_MODEL]) / (P.sigma[:-H_MODEL] * math.sqrt(H_MODEL))
    return np.where(np.isfinite(out), np.clip(out, -fe.CLIP, fe.CLIP), np.nan)


def m14_panel(P: fc.Panel | None = None, twins: dict | None = None) -> pl.DataFrame:
    """Rows of the original breakout_top10 and tsmom_top20 (the longer spell where both hold)."""
    P = P or fc.load_panel()
    if twins is None:
        O = au.originals(P)
        twins = {b: spells(P, au.simulate(P, b, O[b])[3]) for b in ("breakout", "tsmom_daily")}
    a, b = twins["breakout"], twins["tsmom_daily"]
    t_ix = np.arange(P.T)[:, None]
    da = np.where(a["on"], t_ix - a["start"], -1)
    db = np.where(b["on"], t_ix - b["start"], -1)
    use_a = a["on"] & (da >= db)
    use_b = b["on"] & ~use_a
    fr = pl.concat([held_rows(P, a, use_a), held_rows(P, b, use_b)])
    y = m14_target(P)
    tt, jj = fr["t"].to_numpy(), fr["j"].to_numpy()
    fr = fr.with_columns(ts_us=pl.Series(P.days[tt].astype(np.int64)), symbol=pl.Series([P.names[j] for j in jj]),
                         target=pl.Series(y[tt, jj]))
    fr = fr.filter(pl.col("ts_us") >= fc.IS_START)
    fr = fr.with_columns(pl.when(pl.col("target").is_nan()).then(None).otherwise(pl.col("target")).alias("target"))
    from ..models import m14_exit_hazard as m14
    for f in m14.FEATURES:
        fr = fr.with_columns(pl.col(f).cast(pl.Float64).fill_nan(None))
    return fr.sort(["ts_us", "symbol"])


def model_pred(P: fc.Panel, sp: dict, folds: list) -> np.ndarray:
    """(T, N) M14's forecast of the next 10 days' log return on the book's held cells, each
    day by the fold model whose quarter it is in (NaN before the first fold)."""
    from ..models import m14_exit_hazard as m14
    rows = held_rows(P, sp)
    out = np.full((P.T, P.N), np.nan)
    if rows.is_empty():
        return out
    ts = P.days[rows["t"].to_numpy()].astype(np.int64)
    for lo, hi, f in folds:
        k = (ts >= lo) & (ts <= hi)
        if not k.any():
            continue
        sub = rows.filter(pl.Series(k))
        z = fe.predict_lgb(f, sub, m14.FEATURES)
        t, j = sub["t"].to_numpy(), sub["j"].to_numpy()
        out[t, j] = z * P.sigma[t, j] * math.sqrt(H_MODEL)
    if folds:
        k = ts > folds[-1][1]
        if k.any():
            sub = rows.filter(pl.Series(k))
            t, j = sub["t"].to_numpy(), sub["j"].to_numpy()
            out[t, j] = fe.predict_lgb(folds[-1][2], sub, m14.FEATURES) * P.sigma[t, j] * math.sqrt(H_MODEL)
    return out


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------

def capture(P: fc.Panel, held: np.ndarray, mask: np.ndarray, after: int = 20) -> dict:
    """Per spell that ends inside the mask: bought at the close of s, sold at the close of e
    (the first close after which it is no longer held)."""
    on = held > 1e-12
    rows = []
    for j in range(P.N):
        col = on[:, j]
        if not col.any():
            continue
        d = np.diff(np.r_[0, col.astype(int), 0])
        for s, e in zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)):
            if e >= P.T or not mask[e]:
                continue
            px = P.px[:, j]
            if not (np.isfinite(px[s]) and np.isfinite(px[e])):
                continue
            real = px[e] / px[s] - 1
            mfe = np.nanmax(px[s + 1:e + 1]) / px[s] - 1
            post = px[e + 1:e + 1 + after]
            left = np.nanmax(post) / px[e] - 1 if np.isfinite(post).any() else np.nan
            rows.append((real, mfe, real / mfe if mfe > 0 else np.nan, mfe - real, left, e - s))
    if not rows:
        return {"trades": 0}
    a = np.array(rows)

    def q(v):
        v = v[np.isfinite(v)]
        return [float(x) for x in np.percentile(v, [25, 50, 75])] if v.size else [float("nan")] * 3

    return {"trades": len(a), "realised_q": q(a[:, 0]), "mfe_q": q(a[:, 1]), "capture_q": q(a[:, 2]),
            "giveback_q": q(a[:, 3]), "left_q": q(a[:, 4]), "days_q": q(a[:, 5]),
            "share_lost_gain": float(np.mean((a[:, 1] > 0) & (a[:, 0] <= 0)))}


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def describe(P: fc.Panel, name: str, g: np.ndarray, tv: np.ndarray, ex: np.ndarray, **tags) -> dict:
    ins, oos = fc.masks(P)
    yr = au.years_of(P)
    n = fo.net(g, tv, COST)
    po = fc.perf(n[oos])
    row = {"variant": name, **tags, "is_35": fc.perf(n[ins])["sharpe"], "oos_35": po["sharpe"],
           "oos_70": fc.perf(fo.net(g, tv, 2 * COST)[oos])["sharpe"], "cagr": po["cagr"], "dd": po["max_dd"],
           "expo": float(ex[oos].mean()), "turnover_yr": float(tv[oos].sum() / (oos.sum() / 365))}
    for y in YEARS_OOS:
        row[f"y{y}"] = fc.perf(n[oos & (yr == y)])["sharpe"]
    xo = n[oos]
    row["sr_obs"] = float(xo.mean() / xo.std()) if xo.std() > 0 else 0.0
    return row


def run() -> dict:
    from ..models import m14_exit_hazard as m14
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    held = {}
    orig = {}
    for b in BOOKS:
        for ver, W in (("live", au.cash_left(O[b], alp)), ("twin", O[b])):
            g, tv, ex, h = au.simulate(P, b, W)
            held[(b, ver)] = h
            orig[(b, ver)] = describe(P, f"{ORIGINAL[b]} {ver} (its own simulator)", g, tv, ex, book=b, version=ver)
    log(f"books in {time.time() - t0:.0f}s")
    sp = {k: spells(P, h) for k, h in held.items()}
    ref, ref_series = {}, {}
    for k, h in held.items():
        g, tv, ex, _ = au.sim_daily(P, h)
        ref[k] = describe(P, f"{ORIGINAL[k[0]]} {k[1]} (reference)", g, tv, ex, book=k[0], version=k[1])
        ref_series[k] = fo.net(g, tv, COST)

    # M14
    mp = m14_panel(P, {"breakout": sp[("breakout", "twin")], "tsmom_daily": sp[("tsmom_daily", "twin")]})
    ev, folds = fe.evaluate_keep(m14, mp)
    h = ev["holdout"]
    imps = [f["importance"] for _, _, f in folds]
    tsh = h["ts_us"].to_numpy()
    yv, pv = h["target"].to_numpy().astype(float), h["challenger"].to_numpy().astype(float)
    m14_res = {k: ev.get(k) for k in ("model_score", "baseline_score", "gain_pct", "dm_stat", "dm_p", "folds_won", "rows_oos")}
    m14_res.update(gate=ev.get("gate"), folds=len(ev.get("folds") or []), rows=mp.height,
                   rank_ic=fe.rank_ic(pv, yv, tsh), rank_ic_from_2024=fe.rank_ic(pv[tsh >= fc.SPLIT], yv[tsh >= fc.SPLIT], tsh[tsh >= fc.SPLIT]),
                   stability=fe.importance_stability(imps))
    log(f"M14: {m14_res['gate']}")
    preds = {k: model_pred(P, s, folds) for k, s in sp.items()}

    rules = [("time", 20), ("time", 40), ("atr", 2.0), ("atr", 3.0), ("target", 2.0), ("target", 3.0), ("model", MODEL_THR)]
    label = {"time": "time {:g}", "atr": "ATR {:g}", "target": "target {:g}", "model": "model"}
    rows, series = [], {}

    def overlay(b: str, ver: str, rule: str, x: float, late: bool = False):
        k = (b, ver)
        f = fires(P, sp[k], rule, x, preds[k] if rule == "model" else None)
        cut = cut_from(f, sp[k], late)
        W = np.where(cut, 0.0, held[k])
        g, tv, ex, hh = au.sim_daily(P, W)
        return g, tv, ex, hh, cut

    for b in BOOKS:
        for rule, x in rules:
            g, tv, ex, hh, cut = overlay(b, "live", rule, x)
            name = f"{ORIGINAL[b]} · exit {label[rule].format(x)}"
            r = describe(P, name, g, tv, ex, book=b, rule=rule, x=x, group="E")
            r["cut_share"] = float(cut[oos].sum() / max(sp[(b, 'live')]["on"][oos].sum(), 1))
            rows.append(r)
            series[name] = (fo.net(g, tv, COST), hh)
        log(f"{b} exits done")
    picks = {}
    for b in BOOKS:
        cand = [r for r in rows if r["group"] == "E" and r["book"] == b]
        pk = max(cand, key=lambda r: r["is_35"])
        g, tv, ex, _, _ = overlay(b, "live", pk["rule"], pk["x"], late=True)
        lr = describe(P, pk["variant"] + " · a day late", g, tv, ex, book=b, group="L")
        rows.append(lr)
        series[lr["variant"]] = (fo.net(g, tv, COST), None)
        g, tv, ex, _, _ = overlay(b, "twin", pk["rule"], pk["x"])
        tr = describe(P, pk["variant"] + " · twin", g, tv, ex, book=b, group="T")
        rows.append(tr)
        series[tr["variant"]] = (fo.net(g, tv, COST), None)
        picks[b] = (pk, lr, tr)
    assert len(rows) == TRIALS, len(rows)

    diffs = []
    for r in rows:
        base = ref_series[(r["book"], "twin" if r["group"] == "T" else "live")]
        d = (series[r["variant"]][0] - base)[oos]
        diffs.append(d)
        r["diff_sr"] = fo.sharpe_d(d) * math.sqrt(365)
    dvar = float(np.var(np.clip(np.array([fo.sharpe_d(d) for d in diffs]) * math.sqrt(365), -fc.SR_CLIP, fc.SR_CLIP)
                        / math.sqrt(365)))
    for r, d in zip(rows, diffs):
        r["deflated_p_diff"] = fo.deflated(d, TRIALS, dvar)
    pl_ = pool_all([r["sr_obs"] for r in rows])
    for r in rows:
        r["deflated_p_pool"] = fo.deflated(series[r["variant"]][0][oos], pl_["n_total"], pl_["var"])

    verdicts = []
    for b, (pk, lr, tr) in picks.items():
        rf, tref = ref[(b, "live")], ref[(b, "twin")]
        x, y = series[pk["variant"]][0][oos], ref_series[(b, "live")][oos]
        lo, hi = au.boot_band(x, rng, y)
        better = sum(pk[f"y{yy}"] > rf[f"y{yy}"] for yy in YEARS_OOS)
        gates = {
            "1 Sharpe and years": pk["oos_35"] > rf["oos_35"] and better >= 2,
            "2 drawdown": pk["dd"] < rf["dd"],
            "3 band above 0": lo > 0,
            "4 one day late": lr["oos_35"] > rf["oos_35"],
            "5 twin": tr["oos_35"] >= tref["oos_35"],
            "6 deflated improvement": pk["deflated_p_diff"] > 0.95,
        }
        verdicts.append({"book": ORIGINAL[b], "pick": pk["variant"], "rule": pk["rule"], "x": pk["x"],
                         "is_35": pk["is_35"], "ref_is_35": rf["is_35"], "oos_35": pk["oos_35"], "ref_oos_35": rf["oos_35"],
                         "dd": pk["dd"], "ref_dd": rf["dd"], "years_better": better, "diff_p05": lo, "diff_p95": hi,
                         "late_35": lr["oos_35"], "twin_35": tr["oos_35"], "twin_ref_35": tref["oos_35"],
                         "deflated_p_diff": pk["deflated_p_diff"], "deflated_p_pool": pk["deflated_p_pool"],
                         "gates_failed": [k for k, v in gates.items() if not v], "passes": all(gates.values())})
    cap = {}
    for k, h_ in held.items():
        if k[1] == "live":
            cap[ORIGINAL[k[0]]] = capture(P, h_, oos)
    for b, (pk, _, _) in picks.items():
        cap[pk["variant"]] = capture(P, series[pk["variant"]][1], oos)
    return {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "panel_end": str(P.days[-1].astype("datetime64[us]").astype("datetime64[D]")), "oos_days": int(oos.sum()),
            "originals": list(orig.values()), "refs": list(ref.values()), "rows": rows, "verdicts": verdicts,
            "capture": cap, "pool": pl_, "diff_var": dvar, "models": {"M14": m14_res},
            "passes": [v["book"] for v in verdicts if v["passes"]]}


def pool_all(mine_crypto_obs: list[float]) -> dict:
    """The global pool with this part's trials and, when it has run, the equity trials of
    lab.experiments.equities_training (per trading day)."""
    from . import equities_training as et
    v1, n1 = et.prior_var(), et.HAND_TRIALS
    fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    xc = np.clip(np.array(mine_crypto_obs) * math.sqrt(365), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    eq = []
    try:
        d = json.loads((report.REPORTS / et.NAME / "latest.json").read_text(encoding="utf-8"))
        eq = [r["sr_obs"] for r in d["rows"]]
    except (OSError, ValueError, KeyError):
        pass
    xe = np.clip(np.array(eq) * math.sqrt(252), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(252) if eq else np.array([])
    groups = [(n1, v1), (len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0), (len(xc), float(np.var(xc))),
              (len(xe), float(np.var(xe)) if len(xe) > 1 else 0.0)]
    n = sum(g[0] for g in groups)
    v = sum(g[0] * g[1] for g in groups) / n
    sr0 = fc._sr0(v, n)
    return {"hand_trials": n1, "factory_trials": len(fx), "mine": len(xc), "equity_trials": len(xe), "n_total": n,
            "var": v, "sr0_obs": sr0, "sr0_annual_crypto": sr0 * math.sqrt(365)}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _f(x, nd: int = 2) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, (int, np.integer)):
        return str(int(x))
    if isinstance(x, float):
        return f"{x:.{nd}f}" if math.isfinite(x) else "n/a"
    return str(x)


def markdown(res: dict) -> str:
    pl_ = res["pool"]
    m = res["models"]["M14"]
    st = m["stability"]
    out = [f"## Results (generated {res['generated'][:10]}, panel to {res['panel_end']})\n\n",
           f"Out of sample from 2024-01-01 ({res['oos_days']} days), 35 bps per unit of turnover, books as they run on "
           f"Alpaca. Pool {pl_['n_total']} trials ({pl_['hand_trials']} hand, {pl_['factory_trials']} factory, "
           f"{pl_['equity_trials']} X16 equity trials, {pl_['mine']} here); noise bar about "
           f"{pl_['sr0_annual_crypto']:.2f} annual on calendar days.\n\n",
           f"**Verdict: {'nothing passes' if not res['passes'] else ', '.join(res['passes']) + ' pass'}.**\n\n",
           "### The picks against the book\n\n",
           "| book | pick | IS 35 | book IS | OOS 35 | book OOS | DD | book DD | years better | band | late | twin | twin book | defl. p diff | defl. p pool | failed |\n",
           "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n"]
    for v in res["verdicts"]:
        out.append(f"| {v['book']} | {v['pick']} | {_f(v['is_35'])} | {_f(v['ref_is_35'])} | {_f(v['oos_35'])} | "
                   f"{_f(v['ref_oos_35'])} | {v['dd'] * 100:.1f} % | {v['ref_dd'] * 100:.1f} % | {v['years_better']} of 3 | "
                   f"{_f(v['diff_p05'])} to {_f(v['diff_p95'])} | {_f(v['late_35'])} | {_f(v['twin_35'])} | "
                   f"{_f(v['twin_ref_35'])} | {_f(v['deflated_p_diff'], 3)} | {_f(v['deflated_p_pool'], 3)} | "
                   f"{', '.join(v['gates_failed']) or 'none'} |\n")
    out.append("\n### Capture of the current exits and of the picks (spells closed out of sample)\n\n"
               "Per spell: bought at a close, sold at the first close after which it is no longer held. MFE is the "
               "highest close while held over the entry; capture = realised / MFE where MFE > 0; left on the table = "
               "the highest close in the 20 days after the sale over the sale price. 25/50/75th percentiles.\n\n"
               "| book | spells | realised | MFE | capture | give-back | left on table | gains lost |\n|---|---|---|---|---|---|---|---|\n")
    for k, c in res["capture"].items():
        if not c.get("trades"):
            continue
        q = lambda v: "/".join(f"{x * 100:.1f}" for x in v) + " %"  # noqa: E731
        out.append(f"| {k} | {c['trades']} | {q(c['realised_q'])} | {q(c['mfe_q'])} | "
                   + "/".join(f"{x:.2f}" for x in c["capture_q"]) + f" | {q(c['giveback_q'])} | {q(c['left_q'])} | "
                   f"{c['share_lost_gain'] * 100:.0f} % |\n")
    g = m.get("gain_pct")
    gain = "n/a" if g is None else f"{abs(g):.1f} % {'lower' if g > 0 else 'higher'}"
    out.append(f"\n### M14\n\nSquared error {_f(m.get('model_score'), 4)} vs {_f(m.get('baseline_score'), 4)} for the "
               f"training mean ({gain}), DM p {_f(m.get('dm_p'), 4)}, {m.get('folds_won')} of "
               f"{m.get('folds')} quarters better, {m.get('rows_oos')} out-of-fold rows of {m.get('rows')}; zoo gate "
               f"{'passed' if (m.get('gate') or {}).get('passed') else 'failed'}. Rank IC pooled "
               f"{_f(m['rank_ic']['pooled'], 3)}, daily mean {_f(m['rank_ic']['daily_mean'], 3)} (t {_f(m['rank_ic']['t'])}); "
               f"from 2024 {_f(m['rank_ic_from_2024']['pooled'], 3)}. Importance stability over {st['fits']} fits: "
               f"mean {_f(st['mean'])}, min {_f(st['min'])} (first against last {_f(st.get('first_last'))}). "
               "Largest gain shares: "
               + ", ".join(f"{a} {b * 100:.0f} %" for a, b in list((st.get('mean_gain_share') or {}).items())[:5]) + ".\n\n")
    cols = ["variant", "is_35", "oos_35", "oos_70", "cagr", "dd", "expo", "turnover_yr", "y2024", "y2025", "y2026",
            "diff_sr", "deflated_p_diff", "deflated_p_pool"]
    out.append("### The books (not counted)\n\n" + fc.table(res["originals"] + res["refs"], cols[:11]))
    out.append("\n### Every trial\n\n" + fc.table(res["rows"], cols + ["cut_share"]))
    return "".join(out)


def write(res: dict) -> None:
    path = RESULTS / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = "# X16 B2: exit timing on the crypto books\n\nPre-registered in `equities_training_prereg.md` (part B2 and M14); the write-up is in `equities_training.md`.\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n\n" + MARKER + "\n\n" + markdown(res), encoding="utf-8", newline="\n")
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    txt = json.dumps(res, indent=1, default=lambda o: o.tolist() if isinstance(o, np.ndarray) else
                     (float(o) if isinstance(o, np.floating) else (int(o) if isinstance(o, np.integer) else str(o))))
    (d / "latest.json").write_text(txt, encoding="utf-8")
    (d / f"{datetime.now(timezone.utc):%Y-%m-%d}.json").write_text(txt, encoding="utf-8")


def main() -> int:
    res = run()
    write(res)
    print(json.dumps({"passes": res["passes"], "M14": res["models"]["M14"]["gate"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
