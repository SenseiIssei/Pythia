"""X11 c: M8u (the next day's 90 % quantile) as a take-profit trim on the long-only books.

Pre-registered in results/model_upgrades_prereg.md (section c).

c1  M8u's own gate: its purged quarterly walk-forward (core.evaluate) against
    its baseline, 0.9 pinball, DM p below 0.05.
c2  U = M8u's forecast over its baseline's, made at the close of day t. The cut
    is the 20th percentile of every coin's U over the trailing 365 days (at
    least 180). exhaust: a coin's target is halved while U is below the cut;
    take-profit: the same, only while the coin's 7-day return is above 0.
    Control: the same rules on minus the vol-scaled 7-day return (a plain trim
    after a run-up). 2 rules x 2 sources x 3 books + the per-book pick one day
    late and on the twin = 18 trials, X6's six gates plus 7 (above the control).

    python -m lab.experiments.m8_trim [--refresh]

Writes results/m8_trim.md (PYTHIA_RESULTS) and <agent out>/reports/m8_trim.json.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from .. import report
from . import alpaca_universe as au
from . import fam_common as fc
from . import flow_overlays as fo
from . import model_review as mr

NAME = "m8_trim"
BASE = fo.BASE
BOOKS = fo.BOOKS
ORIGINAL = au.ORIGINAL
YEARS_OOS = (2024, 2025, 2026)
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
HAND_TRIALS = 930
HERE_TRIALS = 18
WINDOW, WINDOW_MIN = 365, 180
CUT_Q = 0.20
TRIM = 0.5
PICK_FROM = int(np.datetime64("2021-07-01", "us").astype(np.int64))
RULES = ("exhaust", "take-profit")
SOURCES = ("m8u", "control")


def holdout(refresh: bool = False) -> tuple[pl.DataFrame, dict]:
    """M8u's walk-forward: (ts_us, symbol, ratio, ret7, sigma, target, q90, q90_base) and its gate."""
    cache = fc.OUT / "cache" / "x11_m8u_holdout.parquet"
    meta = fc.OUT / "cache" / "x11_m8u_gate.json"
    if cache.exists() and meta.exists() and not refresh:
        return pl.read_parquet(cache), json.loads(meta.read_text())
    from ..models import core, m8_upper
    ev = core.evaluate(m8_upper, m8_upper.load())
    h = ev["holdout"]
    out = h.select(ts_us=pl.col("ts_us").cast(pl.Int64), symbol=pl.col("symbol").cast(pl.Utf8),
                   ratio=pl.col("x_ratio"), ret7="ret7", sigma="sigma", target="target",
                   q90="challenger", q90_base="baseline_pred")
    gate = core.finite({k: ev.get(k) for k in ("model_score", "baseline_score", "gain_pct", "dm_stat", "dm_p",
                                               "folds_won", "gate", "rows_oos")})
    gate["folds"] = len(ev.get("folds") or [])
    y, q, qb = out["target"].to_numpy(), out["q90"].to_numpy(), out["q90_base"].to_numpy()
    oos = out["ts_us"].to_numpy() >= fc.SPLIT
    gate["coverage_from_2024"] = float(np.mean(y[oos] <= q[oos]))
    gate["baseline_coverage_from_2024"] = float(np.mean(y[oos] <= qb[oos]))
    from ..metrics import diebold_mariano
    lm = core.pinball(y[oos], q[oos], 0.9)
    lb = core.pinball(y[oos], qb[oos], 0.9)
    ts = out["ts_us"].to_numpy()[oos]
    gate["from_2024"] = {"pinball_bps": float(lm.mean() * 1e4), "baseline_bps": float(lb.mean() * 1e4),
                         "dm_p": diebold_mariano(core.per_period(ts, lm), core.per_period(ts, lb), lag=1)[1]}
    cache.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(cache)
    meta.write_text(json.dumps(gate, indent=1))
    return out, gate


def matrix(P: fc.Panel, h: pl.DataFrame, col: str) -> np.ndarray:
    """(T, N) of a holdout column on the panel's days and coins (NaN elsewhere)."""
    di = {int(d): i for i, d in enumerate(P.days)}
    ni = {n: j for j, n in enumerate(P.names)}
    r = np.array([di.get(int(d), -1) for d in h["ts_us"].to_numpy()])
    c = np.array([ni.get(f"{s}USDT", -1) for s in h["symbol"].to_list()])
    m = (r >= 0) & (c >= 0)
    x = np.full((P.T, P.N), np.nan)
    x[r[m], c[m]] = h[col].to_numpy().astype(float)[m]
    return x


def trailing_cut(U: np.ndarray, q: float = CUT_Q, w: int = WINDOW, min_days: int = WINDOW_MIN) -> np.ndarray:
    """(T,) the q quantile of every coin's value over the last w days up to and including t."""
    has = np.isfinite(U).any(1)
    out = np.full(U.shape[0], np.nan)
    for t in range(U.shape[0]):
        lo = max(0, t - w + 1)
        if has[lo:t + 1].sum() < min_days:
            continue
        v = U[lo:t + 1]
        v = v[np.isfinite(v)]
        out[t] = float(np.quantile(v, q))
    return out


def trim_scale(U: np.ndarray, ret7: np.ndarray, rule: str, late: int = 0) -> np.ndarray:
    """(T, N) 0.5 where the rule trims, 1 elsewhere (a coin without a forecast is never trimmed)."""
    cut = trailing_cut(U)
    with np.errstate(invalid="ignore"):
        low = np.isfinite(U) & np.isfinite(cut)[:, None] & (U < cut[:, None])
        if rule == "take-profit":
            low &= np.isfinite(ret7) & (ret7 > 0)
    S = np.where(low, TRIM, 1.0)
    if late:
        S = np.r_[np.ones((late, S.shape[1])), S[:-late]]
    return S


def trimmed(W: np.ndarray, S: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(W), W * S, W)


def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pool(mine: list[float]) -> dict:
    v1, n1 = prior_var(), HAND_TRIALS
    fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n3, v3 = len(x), float(np.var(x))
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    rng = np.random.default_rng(20261021)
    h, gate = holdout(a.refresh)
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    alp = au.alpaca_mask(P)
    print("books ...", flush=True)
    B = fo.run_books(P)
    refs = {(b, v): fo.describe(P, f"{ORIGINAL[b]} {v} alone", run, np.ones(P.T), np.ones(P.T, dtype=bool),
                                book=b, version=v, kind="book") for (b, v), run in B.items()}
    ret7 = matrix(P, h, "ret7")
    sig = matrix(P, h, "sigma")
    U = {"m8u": matrix(P, h, "ratio")}
    with np.errstate(invalid="ignore", divide="ignore"):
        U["control"] = -ret7 / (sig * math.sqrt(7))
    first = np.flatnonzero(np.isfinite(U["m8u"]).any(1))[0]
    avail = np.zeros(P.T, dtype=bool)
    avail[first + 1:] = True
    avail &= P.days >= PICK_FROM
    O = au.originals(P)
    c35 = fo.COSTS[BASE]
    ones = np.ones(P.T)
    rows, series = [], {}
    Ss = {(src, rule): trim_scale(U[src], ret7, rule) for src in SOURCES for rule in RULES}

    def add(key, W, book, twin=False, **tags):
        g, tv, ex, held = au.simulate(P, book, W if twin else au.cash_left(W, alp))
        r = fo.describe(P, key, (g, tv, ex), ones, avail, book=book, version="twin" if twin else "live", **tags)
        base = B[(book, "twin" if twin else "live")]
        xb, xo = fo.net(base[0], base[1], c35), fo.net(g, tv, c35)
        r["diff_sr"] = fo.sharpe_d((xo - xb)[oos]) * math.sqrt(365)
        rows.append(r)
        series[key] = ((g, tv, ex), ones, xo, xb)
        return r

    for b in BOOKS:
        for (src, rule), S in Ss.items():
            r = add(f"{src} {rule} · {b}", trimmed(O[b], S), b, group="A", source=src, rule=rule)
            S_oos = S[oos][:, alp]
            held = np.nan_to_num(O[b][oos][:, alp]) > 0
            r["trimmed_share_held"] = float((S_oos[held] < 1).mean()) if held.any() else 0.0
        print(f"  {b} done", flush=True)
    picks = []
    for b in BOOKS:
        cand = [r for r in rows if r["book"] == b and r["source"] == "m8u" and r["group"] == "A"]
        pk = max(cand, key=lambda r: r[f"is_{BASE}"] if math.isfinite(r[f"is_{BASE}"]) else -1e9)
        picks.append(pk)
        add(pk["variant"] + " · one day late", trimmed(O[b], trim_scale(U["m8u"], ret7, pk["rule"], late=1)), b,
            group="L", source="m8u", rule=pk["rule"])
        add(pk["variant"] + " · twin", trimmed(O[b], Ss[("m8u", pk["rule"])]), b, twin=True,
            group="T", source="m8u", rule=pk["rule"])
    assert len(rows) == HERE_TRIALS, len(rows)
    pl_ = pool([r[f"oos_{BASE}"] for r in rows])
    diffs = np.clip(np.array([r["diff_sr"] for r in rows]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    dvar = float(np.var(diffs))
    for r in rows:
        _, _, xo, xb = series[r["variant"]]
        r["deflated_p_pool"] = fo.deflated(xo[oos], pl_["n_total"], pl_["var"])
        r["deflated_p_diff"] = fo.deflated((xo - xb)[oos], HERE_TRIALS, dvar)
    control = {(r["book"], r["rule"]): r for r in rows if r.get("source") == "control" and r["group"] == "A"}
    part = {"rows": rows, "series": series, "picks": picks}
    verdicts = mr.gates(P, part, refs, rng, control)
    res = {"panel_end": str(P.days[-1].astype("datetime64[us]").astype("datetime64[D]")), "oos_days": int(oos.sum()),
           "gate_m8u": gate, "pool": pl_, "rows": rows, "verdicts": verdicts, "refs": list(refs.values()),
           "first_forecast": str(P.days[first].astype("datetime64[us]").astype("datetime64[D]"))}
    out = fc.OUT / "reports" / f"{NAME}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mr._finite(res), indent=1), encoding="utf-8")
    write(res)


def _f(v, nd: int = 2) -> str:
    return mr._f(v, nd)


def write(res: dict) -> None:
    g = res["gate_m8u"]
    f24 = g.get("from_2024") or {}
    md = ["# M8u and the upside-exhaustion trim (X11 c)\n\n",
          "Generated by `python -m lab.experiments.m8_trim` from the pre-registration in `model_upgrades_prereg.md`.\n\n",
          "## c1. M8u, the 90 % quantile alone\n\n",
          f"Purged quarterly walk-forward from 2021 ({g.get('folds')} folds, {g.get('rows_oos')} coin-days): 0.9 pinball "
          f"{_f((g.get('model_score') or 0) * 1e4)} bps against {_f((g.get('baseline_score') or 0) * 1e4)} bps for the baseline "
          f"({_f(g.get('gain_pct'))} % lower), DM p {_f(g.get('dm_p'), 3) if (g.get('dm_p') or 0) >= 0.001 else format(g.get('dm_p') or 0, '.1e')}, "
          f"better in {g.get('folds_won')} quarters. From 2024: {_f(f24.get('pinball_bps'))} against "
          f"{_f(f24.get('baseline_bps'))} bps, DM p {format(f24.get('dm_p') or 0, '.2g')}. Share of days at or below the "
          f"forecast from 2024: {_f(100 * (g.get('coverage_from_2024') or 0), 1)} % (baseline "
          f"{_f(100 * (g.get('baseline_coverage_from_2024') or 0), 1)} %, target 90 %). "
          f"Gate: **{'passes' if (g.get('gate') or {}).get('passed') else 'fails'}**.\n\n",
          f"## c2. The trim on the books\n\nOut of sample from 2024-01-01 to {res['panel_end']} ({res['oos_days']} days), "
          "35 bps per unit of turnover, books as the autopilot runs them on Alpaca. Deflation pool: "
          f"{res['pool']['n_total']} trials ({res['pool']['hand_trials']} hand, {res['pool']['factory_trials']} factory, "
          f"{res['pool']['mine']} here; noise bar {_f(res['pool']['sr0_annual'])}).\n\n",
          "| book | alone OOS 35 | OOS 70 | drawdown |\n|---|---|---|---|\n"]
    for r in res["refs"]:
        md.append(f"| {r['variant']} | {_f(r[f'oos_{BASE}'])} | {_f(r['oos_stress 70bps'])} | {_f(100 * r['dd_35'], 1)} % |\n")
    md.append("\n| variant | IS 35 | OOS 35 | OOS 70 | drawdown | held coin-days trimmed | diff Sharpe | 2024 | 2025 | 2026 |\n"
              "|---|---|---|---|---|---|---|---|---|---|\n")
    for r in res["rows"]:
        md.append(f"| {r['variant']} | {_f(r[f'is_{BASE}'])} | {_f(r[f'oos_{BASE}'])} | {_f(r['oos_stress 70bps'])} | "
                  f"{_f(100 * r['dd_35'], 1)} % | {_f(100 * r['trimmed_share_held'], 1) + ' %' if 'trimmed_share_held' in r else ''} | "
                  f"{_f(r['diff_sr'])} | {_f(r['y2024'])} | {_f(r['y2025'])} | {_f(r['y2026'])} |\n")
    md.append("\n| pick | OOS 35 | book | drawdown | book | years better | band of diff | late | twin | twin book | control | "
              "deflated p diff | deflated p pool | gates failed |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    for v in res["verdicts"]:
        md.append(f"| {v['pick']} | {_f(v['oos_35'])} | {_f(v['book_oos_35'])} | {_f(100 * v['dd'], 1)} % | "
                  f"{_f(100 * v['book_dd'], 1)} % | {v['years_better']} of 3 | {_f(v['diff_p05'])} to {_f(v['diff_p95'])} | "
                  f"{_f(v['late_35'])} | {_f(v['twin_35'])} | {_f(v['twin_book_35'])} | {_f(v.get('control_oos_35'))} | "
                  f"{_f(v['deflated_p_diff'])} | {_f(v['deflated_p_pool'])} | {', '.join(v['gates_failed']) or 'none'} |\n")
    passed = [v["pick"] for v in res["verdicts"] if v["passes"]]
    md.append(f"\n**Verdict.** {'Passes: ' + ', '.join(passed) if passed else 'No pick passes every gate; nothing is wired.'}\n")
    report.write(NAME, "".join(md), mr._finite(res))


if __name__ == "__main__":
    main()
