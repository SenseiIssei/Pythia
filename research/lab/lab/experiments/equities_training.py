"""X16: early detection, exit timing and more training on US shares and ETFs.

    python -m lab.experiments.equities_training             (cached panel and EDGAR events)
    python -m lab.experiments.equities_training --refresh   (downloads the dataset and refetches EDGAR)

Pre-registered in results/equities_training_prereg.md (committed before any
number existed). This file runs parts A (early detection), B1 (exits on the
equity picks), C (M13 used) and the gates of M13 and M15; part B2 (exits on
the crypto books) and M14 are lab.experiments.exit_overlays. Writes
results/equities_training.md below the marker (PYTHIA_RESULTS or the repo's
results/) and <reports>/equities_training/latest.json.

Data: lab.equities.panel (the point-in-time S&P 500 M9 reads, with opens) and
lab.equities.edgar (SEC filing dates for the earnings events). On the PC:

    PYTHIA_DATA=F:/PythiaData PYTHIA_REPORTS=F:/PythiaData/agent-x16/reports \
        python -m lab.experiments.equities_training
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import stats

from .. import report
from ..data import ROOT
from ..equities import books as bk
from ..equities import edgar
from ..equities import features as fe
from ..equities import panel as pn
from . import fam_common as fc
from . import flow_overlays as fo

NAME = "equities_training"
MARKER = "<!-- generated below by lab.experiments.equities_training; edit above this line only -->"
SEL_FROM = np.datetime64("2000-01-01")
PEAD_SEL_FROM = np.datetime64("2005-01-01")
OOS_FROM = np.datetime64("2016-01-01")
K = 20
STOCK_BPS, ETF_BPS = bk.STOCK_BPS, bk.ETF_BPS
HAND_TRIALS = 948
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
TRIALS = {"A": 57, "B1": 30, "C": 6}
B2_TRIALS = 27
MODEL_THR = -0.0010          # M15 exit: forecast 10-day log return below minus a round trip at 5 bps a side
RESULTS = Path(os.environ.get("PYTHIA_RESULTS", str(Path(__file__).resolve().parents[2] / "results")))
SEED = 20261020


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------

@dataclass
class Ctx:
    S: pn.Panel
    E: pn.Panel
    regime: np.ndarray
    me: np.ndarray
    spy: np.ndarray                  # SPY open to open, the books' calendar
    pd: bk.Pead | None
    edgar_info: dict
    bench: dict = field(default_factory=dict)
    m13_pred: dict = field(default_factory=dict)     # family -> (T, N) out-of-fold forecast
    m15_folds: list = field(default_factory=list)


def load_ctx(refresh: bool = False, offline_edgar: bool = False) -> Ctx:
    S, E = pn.load(refresh)
    bk.inputs(S)
    bk.inputs(E)
    regime = bk.spy_regime(E)
    me = bk.month_ends(S.dates)
    spy = E.r_oo()[:, E.col("SPY")]
    try:
        ev = edgar.load_events(S, refresh=refresh, offline=offline_edgar)
    except Exception as e:  # noqa: BLE001 - no EDGAR, no A3; the rest still runs
        print(f"{NAME}: EDGAR unavailable, no earnings events: {e}", file=sys.stderr)
        ev = {"events": [], "cik": {}}
    pd = None
    if ev["events"]:
        start, has = edgar.event_matrix(S, ev["events"])
        pd = bk.pead_inputs(S, E, bk.inputs(S), start, has)
    info = {"events": len(ev["events"]), "companies": len(ev.get("cik") or {}),
            "pead_windows": pd.n_events if pd else 0}
    return Ctx(S=S, E=E, regime=regime, me=me, spy=spy, pd=pd, edgar_info=info)


# ---------------------------------------------------------------------------
# Part A grid
# ---------------------------------------------------------------------------

def grid_a() -> list[dict]:
    out = []
    for n in (20, 55):
        for k in (1.5, 2.5):
            for H in (10, 40):
                for reg in (False, True):
                    out.append({"fam": "A1", "n": n, "k": k, "H": H, "reg": reg,
                                "label": f"A1 breakout {n}d, volume {k}x, time {H}" + (", regime" if reg else "")})
    for g in (0.02, 0.04):
        for H in (5, 20):
            for reg in (False, True):
                out.append({"fam": "A2", "g": g, "H": H, "reg": reg,
                            "label": f"A2 gap {g:.0%}, time {H}" + (", regime" if reg else "")})
    for z in (1.0, 2.0):
        for vf in (False, True):
            for H in (20, 60):
                out.append({"fam": "A3", "z": z, "vf": vf, "H": H, "reg": False,
                            "label": f"A3 PEAD z {z:g}" + (", volume 2x" if vf else "") + f", time {H}"})
    for k in (20, 50):
        for reg in (False, True):
            out.append({"fam": "A4", "K": k, "reg": reg, "label": f"A4 52-week high top {k}" + (", regime" if reg else "")})
    for L in (63, 126, 252, "blend"):
        for m in (2, 3):
            for reg in (False, True):
                out.append({"fam": "A5", "L": L, "M": m, "reg": reg,
                            "label": f"A5 sectors {L}{'d' if L != 'blend' else ''} top {m}" + (", regime" if reg else "")})
    return out


def is_event(v: dict) -> bool:
    return v["fam"] in ("A1", "A2", "A3")


def signals(ctx: Ctx, v: dict) -> tuple[np.ndarray, np.ndarray]:
    X = bk.inputs(ctx.S)
    if v["fam"] == "A1":
        return bk.breakout(ctx.S, X, v["n"], v["k"])
    if v["fam"] == "A2":
        return bk.gap_go(ctx.S, X, v["g"])
    if ctx.pd is None:
        z = np.zeros((ctx.S.T, ctx.S.N), dtype=bool)
        return z, np.zeros(z.shape)
    return bk.pead(ctx.S, X, ctx.pd, v["z"], v["vf"])


def run_variant(ctx: Ctx, v: dict, exit: bk.Exit | None = None, lag: int = 1, record: bool = False,
                model13: np.ndarray | None = None) -> tuple[bk.Run, pn.Panel, float]:
    """The book of one variant: (run, its panel, its cost in bps a side)."""
    reg = ctx.regime if v["reg"] else None
    if is_event(v):
        sig, strength = signals(ctx, v)
        if model13 is not None:
            with np.errstate(invalid="ignore"):
                sig = sig & np.isfinite(model13) & (model13 >= 0)
            strength = model13
        ex = exit or bk.Exit("time", H=v["H"])
        return (bk.simulate(ctx.S, sig=sig, strength=strength, K=K, exit=ex, lag=lag, regime=reg, record=record),
                ctx.S, STOCK_BPS)
    if v["fam"] == "A4":
        tg = bk.high52_targets(ctx.S, bk.inputs(ctx.S), v["K"], ctx.me, reg)
        return bk.simulate(ctx.S, targets=tg, exit=exit, lag=lag, record=record), ctx.S, STOCK_BPS
    tg = bk.sector_targets(ctx.E, v["L"], v["M"], ctx.me, reg)
    return bk.simulate(ctx.E, targets=tg, exit=exit, lag=lag, record=record), ctx.E, ETF_BPS


def masks(ctx: Ctx, v: dict) -> tuple[np.ndarray, np.ndarray]:
    d = ctx.S.dates
    lo = PEAD_SEL_FROM if v["fam"] == "A3" else SEL_FROM
    return (d >= lo) & (d < OOS_FROM), d >= OOS_FROM


def benchmarks(ctx: Ctx) -> dict[str, np.ndarray]:
    if ctx.bench:
        return ctx.bench
    S, E = ctx.S, ctx.E
    XS = bk.inputs(S)
    ew = bk.simulate(S, targets=bk.ew_targets(S, XS, ctx.me))
    out = {"SPY": ctx.spy, "equal weight": ew.net(STOCK_BPS)}
    if ctx.pd is not None:
        cik = bk.simulate(S, targets=bk.ew_targets(S, XS, ctx.me, cols_ok=ctx.pd.has_cik))
        out["equal weight, CIK members"] = cik.net(STOCK_BPS)
    sect = np.array([s != "SPY" for s in E.names])
    out["equal-weight sectors"] = bk.simulate(E, targets=bk.ew_targets(E, bk.inputs(E), ctx.me, cols_ok=sect)).net(ETF_BPS)
    ctx.bench = out
    return out


def bench_for(v: dict) -> list[str]:
    if v["fam"] == "A5":
        return ["SPY", "equal-weight sectors"]
    if v["fam"] == "A3":
        return ["SPY", "equal weight", "equal weight, CIK members"]
    return ["SPY", "equal weight"]


def describe(ctx: Ctx, v: dict, run: bk.Run, bps: float, **tags) -> dict:
    sel, oos = masks(ctx, v)
    x, x2 = run.net(bps), run.net(2 * bps)
    po = bk.perf(x[oos])
    a, b = bk.alpha_beta(x[oos], ctx.spy[oos])
    a2, _ = bk.alpha_beta(x2[oos], ctx.spy[oos])
    xo = x[oos]
    row = {"label": v["label"], "fam": v["fam"], **tags,
           "sel_sharpe": bk.sharpe(x[sel]), "oos_sharpe": po["sharpe"], "oos_sharpe_2x": bk.sharpe(x2[oos]),
           "oos_cagr": po["cagr"], "oos_vol": po["vol"], "oos_max_dd": po["max_dd"], "alpha": a, "beta": b,
           "alpha_2x": a2, "turnover_yr": float(run.turnover[oos].sum() / (oos.sum() / bk.YEAR_DAYS)),
           "expo": float(run.expo[oos].mean()), "trades": len(run.trades),
           "close_fill_share": run.close_fills / run.fills if run.fills else 0.0,
           "sr_obs": float(xo.mean() / xo.std()) if xo.std() > 0 else 0.0, "oos_days": int(oos.sum())}
    return row


# ---------------------------------------------------------------------------
# Deflation over the global pool
# ---------------------------------------------------------------------------

def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pool(mine_obs: list[float]) -> dict:
    """The pooled per-observation Sharpe variance: the hand trials at the published bar's
    variance, the factory ledger, and this study's trials (per trading day for equities, per
    calendar day for crypto, as each series is observed)."""
    v1, n1 = prior_var(), HAND_TRIALS
    fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine_obs) * math.sqrt(bk.YEAR_DAYS), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(bk.YEAR_DAYS)
    n3, v3 = len(x), float(np.var(x)) if len(x) > 1 else 0.0
    # B2's crypto trials (lab.experiments.exit_overlays), per calendar day, once it has run.
    xc = np.array([])
    try:
        d = json.loads((report.REPORTS / "exit_overlays" / "latest.json").read_text(encoding="utf-8"))
        xc = np.clip(np.array([r["sr_obs"] for r in d["rows"]]) * math.sqrt(365), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    except (OSError, ValueError, KeyError):
        pass
    n4, v4 = len(xc), float(np.var(xc)) if len(xc) > 1 else 0.0
    n = n1 + n2 + n3 + n4
    v = (n1 * v1 + n2 * v2 + n3 * v3 + n4 * v4) / n
    sr0 = fc._sr0(v, n)
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "crypto_trials": n4, "n_total": n, "var": v,
            "sr0_obs": sr0, "sr0_annual_equity": sr0 * math.sqrt(bk.YEAR_DAYS), "sr0_annual_crypto": sr0 * math.sqrt(365)}


def deflate_within(series: list[np.ndarray]) -> tuple[float, list[float]]:
    """Each series' deflated p over these series only, at their own Sharpe variance."""
    srs = np.array([x.mean() / x.std() if x.std() > 0 else 0.0 for x in series])
    var = float(np.var(np.clip(srs * math.sqrt(bk.YEAR_DAYS), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(bk.YEAR_DAYS)))
    return var, [fo.deflated(x, len(series), var) for x in series]


def holm(ps: dict[str, float], alpha: float = 0.05) -> dict[str, bool]:
    items = sorted((p, k) for k, p in ps.items() if p is not None and math.isfinite(p))
    out = {k: False for k in ps}
    m = len(items)
    for i, (p, k) in enumerate(items):
        if p <= alpha / (m - i):
            out[k] = True
        else:
            break
    return out


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def gates_a(ctx: Ctx, v: dict, row: dict, x: np.ndarray, late_row: dict, rng: np.random.Generator,
            defl_pool: float) -> tuple[dict, dict]:
    _, oos = masks(ctx, v)
    B = benchmarks(ctx)
    bench_sr = {b: bk.sharpe(B[b][oos]) for b in bench_for(v)}
    boot = bk.boot_diff(x[oos], ctx.spy[oos], rng)
    yrs = bk.per_year(ctx.S.dates, x, ctx.spy, oos)
    g = {
        "1 Sharpe above SPY and equal weight": row["oos_sharpe"] > max(bench_sr.values()),
        "2 OOS Sharpe at least half the selection's (> 0)": row["sel_sharpe"] > 0 and row["oos_sharpe"] >= 0.5 * row["sel_sharpe"],
        "3 alpha > 0 at doubled costs": row["alpha_2x"] > 0,
        "4 a day late, alpha > 0": late_row["alpha"] > 0,
        "5 bootstrap: Sharpe above SPY's in >= 90 %": boot["share_above_0"] >= 0.90,
        "6 alpha positive in more than half the years": sum(y["alpha"] > 0 for y in yrs.values()) > len(yrs) / 2,
        "7 deflated p > 0.95 over the pool": defl_pool > 0.95,
    }
    return g, {"bench_sharpe": bench_sr, "bootstrap": boot, "per_year": yrs}


def gates_diff(ctx: Ctx, v: dict, row: dict, base: dict, x: np.ndarray, xb: np.ndarray, late_row: dict,
               rng: np.random.Generator, defl_diff: float) -> tuple[dict, dict]:
    """B1 and C: the variant against the same pick with its base exit (or without M13)."""
    _, oos = masks(ctx, v)
    yx = bk.per_year(ctx.S.dates, x, ctx.spy, oos)
    yb = bk.per_year(ctx.S.dates, xb, ctx.spy, oos)
    better = sum(yx[y]["sharpe"] > yb[y]["sharpe"] for y in yx)
    boot = bk.boot_diff(x[oos], xb[oos], rng)
    g = {
        "1 Sharpe higher, and in more than half the years": row["oos_sharpe"] > base["oos_sharpe"] and better > len(yx) / 2,
        "2 drawdown not higher": row["oos_max_dd"] <= base["oos_max_dd"],
        "3 bootstrap 5 % of the difference above 0": boot["p05"] > 0,
        "4 a day late still higher": late_row["oos_sharpe"] > base["oos_sharpe"],
        "5 still higher at doubled costs": row["oos_sharpe_2x"] > base["oos_sharpe_2x"],
        "6 deflated p of the improvement > 0.95": defl_diff > 0.95,
    }
    return g, {"bootstrap": boot, "years_better": better, "years": len(yx)}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def m13_panel(ctx: Ctx | None = None) -> pl.DataFrame:
    ctx = ctx or load_ctx(offline_edgar=True)
    return fe.m13_rows(ctx.S, ctx.E, ctx.pd)


def picks_from_report() -> dict[str, dict] | None:
    p = report.REPORTS / NAME / "latest.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return {k: v["variant"] for k, v in d["picks"].items()}
    except (OSError, ValueError, KeyError):
        return None


def m15_panel(ctx: Ctx | None = None, picks: dict[str, dict] | None = None) -> pl.DataFrame:
    ctx = ctx or load_ctx(offline_edgar=True)
    picks = picks or picks_from_report()
    if picks is None:
        raise RuntimeError("no X16 picks yet: run lab.experiments.equities_training first")
    held = {}
    for fam in fe.FAMILIES:
        if fam in picks:
            run, _, _ = run_variant(ctx, picks[fam], record=True)
            held[fam] = run.held
    return fe.m15_rows(ctx.S, ctx.E, held)


def model_report(name: str, ev: dict, folds: list) -> dict:
    h = ev["holdout"]
    y = h["target"].to_numpy().astype(float)
    p = h["challenger"].to_numpy().astype(float)
    ts = h["ts_us"].to_numpy()
    sel = ts < int(np.datetime64(OOS_FROM, "us").astype(np.int64))
    imps = [f["importance"] for _, _, f in folds]
    out = {k: ev.get(k) for k in ("model_score", "baseline_score", "gain_pct", "dm_stat", "dm_p", "folds_won", "rows_oos")}
    out["gate"] = ev.get("gate")
    out["folds"] = len(ev.get("folds") or [])
    out["rank_ic"] = fe.rank_ic(p, y, ts)
    out["rank_ic_from_2016"] = fe.rank_ic(p[~sel], y[~sel], ts[~sel])
    out["stability"] = fe.importance_stability(imps)
    out["name"] = name
    return out


def matrix_from_holdout(S: pn.Panel, h: pl.DataFrame, fam: str, col: str = "challenger") -> np.ndarray:
    out = np.full((S.T, S.N), np.nan)
    f = h.filter(pl.col("symbol").str.ends_with(f"|{fam}"))
    if f.height:
        out[f["t"].to_numpy().astype(int), f["j"].to_numpy().astype(int)] = f[col].to_numpy().astype(float)
    return out


def m15_model_fn(ctx: Ctx, fam: str):
    ts = fe.ts_us(ctx.S.dates)
    X = bk.inputs(ctx.S)
    famf = float(fe.FAMILIES.index(fam))

    def fn(t, js, entries, pxs, peaks):
        f = fe.fold_for(ctx.m15_folds, int(ts[t]))
        if f is None:
            return np.full(len(js), np.nan)
        feats = fe.held_features(ctx.S, ctx.E, t, js, entries, pxs, peaks, famf)
        z = f["model"].predict(feats)
        return z * X.sig21[t, js] * math.sqrt(fe.M15_H)

    return fn


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%H:%M:%S} {NAME}: {msg}", file=sys.stderr, flush=True)


def coverage(ctx: Ctx) -> dict:
    S = ctx.S
    yr = bk.years(S.dates)
    out = {}
    nov = S.member & S.traded & ~np.isfinite(S.dv)
    for y in np.unique(yr):
        m = yr == y
        mem = S.member[m]
        row = {"members_no_volume": float(nov[m].sum() / max(mem.sum(), 1)),
               "fills_at_close_possible": float((S.member & S.fill_at_close())[m].sum() / max(mem.sum(), 1))}
        if ctx.pd is not None:
            row["members_with_cik"] = float((mem & ctx.pd.has_cik[None, :]).sum() / max(mem.sum(), 1))
        out[int(y)] = row
    return out


def run(ctx: Ctx) -> dict:
    rng = np.random.default_rng(SEED)
    t0 = time.time()
    B = benchmarks(ctx)
    log(f"benchmarks in {time.time() - t0:.0f}s")
    grid = grid_a()
    rows, series = [], {}
    for v in grid:
        r, P, bps = run_variant(ctx, v)
        row = describe(ctx, v, r, bps, part="A", kind="grid")
        rows.append(row)
        series[v["label"]] = r.net(bps)
    log(f"part A grid ({len(grid)}) done")
    picks = {}
    for fam in ("A1", "A2", "A3", "A4", "A5"):
        cand = [(row, v) for row, v in zip(rows[:len(grid)], grid) if v["fam"] == fam]
        row, v = max(cand, key=lambda rv: rv[0]["sel_sharpe"])
        picks[fam] = {"variant": v, "row": row}
    late = {}
    for fam, pk in picks.items():
        v = pk["variant"]
        r, P, bps = run_variant(ctx, v, lag=2)
        row = describe(ctx, v, r, bps, part="A", kind="late")
        row["label"] = v["label"] + " · a day late"
        rows.append(row)
        series[row["label"]] = r.net(bps)
        late[fam] = row
    a_rows = [r for r in rows if r["part"] == "A"]
    assert len(a_rows) == TRIALS["A"], len(a_rows)
    log("part A late runs done")

    # Capture of the picks' base exits (and their held rows for M15)
    capture, held = {}, {}
    for fam, pk in picks.items():
        r, P, _ = run_variant(ctx, pk["variant"], record=fam in fe.FAMILIES)
        capture[fam] = bk.capture(r, P)
        if fam in fe.FAMILIES:
            held[fam] = r.held
    log("capture done")

    # Models: M13 on the candidates, M15 on the held days
    from ..models import m13_eq_events as m13
    from ..models import m15_eq_exit as m15
    models = {}
    p13 = fe.m13_rows(ctx.S, ctx.E, ctx.pd)
    ev13, folds13 = fe.evaluate_keep(m13, p13)
    models["M13"] = model_report("M13", ev13, folds13)
    for fam in fe.FAMILIES:
        ctx.m13_pred[fam] = matrix_from_holdout(ctx.S, ev13["holdout"], fam)
    log(f"M13 done: {models['M13']['gate']}")
    p15 = fe.m15_rows(ctx.S, ctx.E, held)
    ev15, folds15 = fe.evaluate_keep(m15, p15)
    ctx.m15_folds = folds15
    models["M15"] = model_report("M15", ev15, folds15)
    log(f"M15 done: {models['M15']['gate']}")

    # Part B1: exits on the picks
    b1 = []
    for fam, pk in picks.items():
        v = pk["variant"]
        if is_event(v):
            H = v["H"]
            exits = [bk.Exit("time", H=max(1, H // 2)), bk.Exit("time", H=2 * H), bk.Exit("atr", k=2, cap=4 * H),
                     bk.Exit("atr", k=3, cap=4 * H), bk.Exit("target", m=1, H=H), bk.Exit("target", m=2, H=H),
                     bk.Exit("model", cap=4 * H, thr=MODEL_THR, model_fn=m15_model_fn(ctx, fam))]
        else:
            exits = [bk.Exit("atr", k=2), bk.Exit("atr", k=3)]
        for ex in exits:
            r, P, bps = run_variant(ctx, v, exit=ex)
            row = describe(ctx, v, r, bps, part="B1", kind="exit", exit=ex.label(), family=fam)
            row["label"] = f"{v['label']} · exit {ex.label()}"
            rows.append(row)
            series[row["label"]] = r.net(bps)
            b1.append((row, ex, r))
        log(f"B1 {fam} done")
    b1_picks = {}
    for fam, pk in picks.items():
        cand = [(row, ex, r) for row, ex, r in b1 if row["family"] == fam]
        row, ex, r = max(cand, key=lambda t: t[0]["sel_sharpe"])
        v = pk["variant"]
        rl, P, bps = run_variant(ctx, v, exit=ex, lag=2)
        lrow = describe(ctx, v, rl, bps, part="B1", kind="late", exit=ex.label(), family=fam)
        lrow["label"] = row["label"] + " · a day late"
        rows.append(lrow)
        series[lrow["label"]] = rl.net(bps)
        b1_picks[fam] = {"row": row, "exit": ex, "late": lrow, "capture": bk.capture(r, P)}
    assert len([r for r in rows if r["part"] == "B1"]) == TRIALS["B1"]
    log("part B1 done")

    # Part C: M13 used on the event picks
    c_rows = {}
    for fam in fe.FAMILIES:
        v = picks[fam]["variant"]
        r, P, bps = run_variant(ctx, v, model13=ctx.m13_pred[fam])
        row = describe(ctx, v, r, bps, part="C", kind="m13", family=fam)
        row["label"] = v["label"] + " · M13 ranks and skips"
        rows.append(row)
        series[row["label"]] = r.net(bps)
        rl, _, _ = run_variant(ctx, v, model13=ctx.m13_pred[fam], lag=2)
        lrow = describe(ctx, v, rl, bps, part="C", kind="late", family=fam)
        lrow["label"] = row["label"] + " · a day late"
        rows.append(lrow)
        series[lrow["label"]] = rl.net(bps)
        c_rows[fam] = (row, lrow)
    assert len([r for r in rows if r["part"] == "C"]) == TRIALS["C"]
    log("part C done")

    # Deflation: the pool (this study's equity trials, B2 counted in exit_overlays at its own scale)
    pl_ = pool([r["sr_obs"] for r in rows] + [0.0] * 0)
    for r in rows:
        r["deflated_p_pool"] = fo.deflated(series[r["label"]][ctx.S.dates >= OOS_FROM], pl_["n_total"], pl_["var"])
    oos = ctx.S.dates >= OOS_FROM
    _, within = deflate_within([series[r["label"]][oos] for r in a_rows])
    for r, p in zip(a_rows, within):
        r["deflated_p_study"] = p

    # Verdicts
    verdict_a = {}
    for fam, pk in picks.items():
        v, row = pk["variant"], pk["row"]
        g, extra = gates_a(ctx, v, row, series[v["label"]], late[fam], rng, row["deflated_p_pool"])
        verdict_a[fam] = {"pick": v["label"], "row": row, "late": late[fam], "gates": g, "passes": all(g.values()), **extra}
    b1_diff = []
    for row, ex, r in b1:
        base = series[picks[row["family"]]["variant"]["label"]]
        b1_diff.append(series[row["label"]] - base)
    b1_late = [series[b1_picks[f]["late"]["label"]] - series[picks[f]["variant"]["label"]] for f in b1_picks]
    dvar, _ = deflate_within([d[oos] for d in b1_diff + b1_late])
    verdict_b1 = {}
    for fam, bp in b1_picks.items():
        v = picks[fam]["variant"]
        row = bp["row"]
        x, xb = series[row["label"]], series[v["label"]]
        dp = fo.deflated((x - xb)[oos], TRIALS["B1"], dvar)
        g, extra = gates_diff(ctx, v, row, picks[fam]["row"], x, xb, bp["late"], rng, dp)
        verdict_b1[fam] = {"pick": row["label"], "exit": bp["exit"].label(), "row": row, "late": bp["late"],
                           "base": picks[fam]["row"], "gates": g, "passes": all(g.values()), "deflated_p_diff": dp,
                           "capture": bp["capture"], **extra}
    c_diff = [series[c[0]["label"]] - series[picks[f]["variant"]["label"]] for f, c in c_rows.items()]
    c_diff += [series[c[1]["label"]] - series[picks[f]["variant"]["label"]] for f, c in c_rows.items()]
    cvar, _ = deflate_within([d[oos] for d in c_diff])
    verdict_c = {}
    for fam, (row, lrow) in c_rows.items():
        v = picks[fam]["variant"]
        x, xb = series[row["label"]], series[v["label"]]
        dp = fo.deflated((x - xb)[oos], TRIALS["C"], cvar)
        g, extra = gates_diff(ctx, v, row, picks[fam]["row"], x, xb, lrow, rng, dp)
        verdict_c[fam] = {"pick": row["label"], "row": row, "late": lrow, "base": picks[fam]["row"], "gates": g,
                          "passes": all(g.values()), "deflated_p_diff": dp, **extra}

    # Model gates with Holm over M13, M14 (from exit_overlays, when it has run) and M15
    ps = {"M13": models["M13"]["dm_p"] if (models["M13"].get("model_score") or 1) < (models["M13"].get("baseline_score") or 0) else 1.0,
          "M15": models["M15"]["dm_p"] if (models["M15"].get("model_score") or 1) < (models["M15"].get("baseline_score") or 0) else 1.0}
    m14 = m14_gate()
    if m14 is not None:
        ps["M14"] = m14
    hm = holm(ps)
    for k in models:
        models[k]["holm_pass"] = hm.get(k, False)
    models["holm_inputs"] = ps

    bench_oos = {k: {**bk.perf(x[oos]), "alpha": bk.alpha_beta(x[oos], ctx.spy[oos])[0]} for k, x in B.items()}
    bench_sel = {k: bk.sharpe(x[(ctx.S.dates >= SEL_FROM) & ~oos]) for k, x in B.items()}
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"first": str(ctx.S.dates[0]), "last": str(ctx.S.dates[-1]), "stocks": ctx.S.N, "etfs": ctx.E.names,
                 "members_ever": int(ctx.S.member.any(0).sum()), "edgar": ctx.edgar_info},
        "coverage": coverage(ctx),
        "pool": pl_, "rows": rows, "picks": {k: {"variant": v["variant"], "row": v["row"]} for k, v in picks.items()},
        "verdict_a": verdict_a, "verdict_b1": verdict_b1, "verdict_c": verdict_c, "capture": capture,
        "models": models, "benchmarks_oos": bench_oos, "benchmarks_sel": bench_sel,
        "passes": {"A": [k for k, v in verdict_a.items() if v["passes"]],
                   "B1": [k for k, v in verdict_b1.items() if v["passes"]],
                   "C": [k for k, v in verdict_c.items() if v["passes"]]},
    }


def m14_gate() -> float | None:
    """M14's DM p from lab.experiments.exit_overlays' latest report (1.0 when not lower)."""
    try:
        d = json.loads((report.REPORTS / "exit_overlays" / "latest.json").read_text(encoding="utf-8"))
        m = d["models"]["M14"]
        return m["dm_p"] if (m.get("model_score") or 1) < (m.get("baseline_score") or 0) else 1.0
    except (OSError, ValueError, KeyError, TypeError):
        return None


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
        if not math.isfinite(x):
            return "n/a"
        return f"{x:.{nd}f}"
    return str(x)


def _pct(x) -> str:
    return "n/a" if x is None or not math.isfinite(x) else f"{x * 100:.1f} %"


def _table(rows: list[dict], cols: list[tuple[str, str, str]]) -> str:
    head = "| " + " | ".join(c[1] for c in cols) + " |\n|" + "---|" * len(cols) + "\n"
    out = []
    for r in rows:
        cells = []
        for key, _, kind in cols:
            v = r.get(key)
            cells.append(_pct(v) if kind == "pct" else _f(v, 3 if kind == "p" else 2))
        out.append("| " + " | ".join(cells) + " |")
    return head + "\n".join(out) + "\n"


def markdown(res: dict) -> str:
    d, pl_ = res["data"], res["pool"]
    md = [f"## Results (generated {res['generated'][:10]}, data {d['first']} to {d['last']})\n",
          f"Point-in-time S&P 500, {d['members_ever']} names ever in the index from 1996; ETFs {', '.join(d['etfs'])}. "
          f"EDGAR: {d['edgar']['companies']} companies, {d['edgar']['events']} earnings events, "
          f"{d['edgar']['pead_windows']} reaction windows. Selection 2000 to 2015 (PEAD 2005 to 2015), out of sample "
          f"from 2016-01-01. Costs 5 bps a side for stocks, 2 for ETFs, plus the SEC fee on sells; next-open fills.\n",
          f"Pool: {pl_['n_total']} trials ({pl_['hand_trials']} hand, {pl_['factory_trials']} factory, {pl_['mine']} "
          f"equity trials here, {pl_.get('crypto_trials', 0)} crypto trials of B2 in `exit_overlays.md`); the best "
          "noise trial sits at an annual Sharpe of about "
          f"{pl_['sr0_annual_equity']:.2f} on trading days ({pl_['sr0_annual_crypto']:.2f} on calendar days).\n",
          "### Benchmarks\n",
          _table([{"name": k, "sel": res["benchmarks_sel"][k], **v} for k, v in res["benchmarks_oos"].items()],
                 [("name", "benchmark", "s"), ("sel", "Sharpe 2000-15", "n"), ("sharpe", "Sharpe OOS", "n"),
                  ("cagr", "CAGR", "pct"), ("max_dd", "max DD", "pct"), ("alpha", "alpha vs SPY", "pct")])]
    md.append("\n### Part A: the family picks\n")
    for fam, v in res["verdict_a"].items():
        r = v["row"]
        md.append(f"**{fam}: {v['pick']}** ({'passes' if v['passes'] else 'fails'}). Selection Sharpe "
                  f"{_f(r['sel_sharpe'])}, out of sample {_f(r['oos_sharpe'])} (doubled costs {_f(r['oos_sharpe_2x'])}), "
                  f"CAGR {_pct(r['oos_cagr'])}, drawdown {_pct(r['oos_max_dd'])}, alpha {_pct(r['alpha'])} (beta "
                  f"{_f(r['beta'])}), exposure {_pct(r['expo'])}, turnover {_f(r['turnover_yr'], 1)} a year, "
                  f"{r['trades']} trades, fills at the close {_pct(r['close_fill_share'])}. A day late: Sharpe "
                  f"{_f(v['late']['oos_sharpe'])}, alpha {_pct(v['late']['alpha'])}. Benchmarks: "
                  + ", ".join(f"{k} {_f(x)}" for k, x in v["bench_sharpe"].items())
                  + f". Bootstrap: Sharpe minus SPY's {_f(v['bootstrap']['p05'])} to {_f(v['bootstrap']['p95'])}, "
                  f"{_pct(v['bootstrap']['share_above_0'])} above 0. Deflated p: pool {_f(r['deflated_p_pool'], 3)}, "
                  f"this study's 57 {_f(r.get('deflated_p_study'), 3)}.\n")
        md.append("Failed: " + (", ".join(k for k, ok in v["gates"].items() if not ok) or "none") + ".\n")
        md.append(_table([{"year": y, **x} for y, x in sorted(v["per_year"].items())],
                         [("year", "year", "s"), ("ret", "book", "pct"), ("spy", "SPY", "pct"),
                          ("alpha", "alpha", "pct"), ("beta", "beta", "n"), ("sharpe", "Sharpe", "n")]))
    md.append("\n### Part A: every trial\n")
    cols = [("label", "variant", "s"), ("sel_sharpe", "sel", "n"), ("oos_sharpe", "OOS", "n"),
            ("oos_sharpe_2x", "OOS 2x", "n"), ("oos_cagr", "CAGR", "pct"), ("oos_max_dd", "max DD", "pct"),
            ("alpha", "alpha", "pct"), ("beta", "beta", "n"), ("expo", "exposure", "pct"),
            ("turnover_yr", "turnover/yr", "n"), ("trades", "trades", "s"), ("deflated_p_pool", "defl. p pool", "p"),
            ("deflated_p_study", "defl. p 57", "p")]
    md.append(_table([r for r in res["rows"] if r["part"] == "A"], cols))
    md.append("\n### Part B: capture of the picks' current exits\n")
    md.append("Per closed trade: realised return, MFE (the highest close held over the entry fill), capture "
              "(realised / MFE where MFE > 0), give-back (MFE minus realised), left on the table (the highest close "
              "in the 20 days after the exit over the exit price). 25th, 50th and 75th percentiles.\n")
    cap_rows = []
    for fam, c in res["capture"].items():
        if c.get("trades"):
            cap_rows.append({"book": f"{fam} {res['verdict_a'][fam]['pick']}", **_qcols(c)})
    for fam, v in res["verdict_b1"].items():
        c = v["capture"]
        if c.get("trades"):
            cap_rows.append({"book": f"{fam} with exit {v['exit']}", **_qcols(c)})
    md.append(_table(cap_rows, [("book", "book", "s"), ("trades", "trades", "s"), ("realised", "realised", "s"),
                                ("mfe", "MFE", "s"), ("capture", "capture", "s"), ("giveback", "give-back", "s"),
                                ("left", "left on table", "s"), ("lost", "gain lost", "pct")]))
    md.append("\n### Part B1: exits on the picks\n")
    for fam, v in res["verdict_b1"].items():
        r, b = v["row"], v["base"]
        md.append(f"- **{fam}**: exit pick {v['exit']}: OOS Sharpe {_f(r['oos_sharpe'])} against {_f(b['oos_sharpe'])} "
                  f"with the base exit (selection {_f(r['sel_sharpe'])} vs {_f(b['sel_sharpe'])}), drawdown "
                  f"{_pct(r['oos_max_dd'])} vs {_pct(b['oos_max_dd'])}, better in {v['years_better']} of {v['years']} "
                  f"years, bootstrap of the difference {_f(v['bootstrap']['p05'])} to {_f(v['bootstrap']['p95'])}, a day "
                  f"late {_f(v['late']['oos_sharpe'])}, deflated p of the improvement {_f(v['deflated_p_diff'], 3)}. "
                  f"{'Passes.' if v['passes'] else 'Fails: ' + ', '.join(k for k, ok in v['gates'].items() if not ok) + '.'}\n")
    md.append("\n" + _table([r for r in res["rows"] if r["part"] == "B1"], cols[:-1]))
    md.append("\n### Part C: M13 ranks and filters the candidates\n")
    for fam, v in res["verdict_c"].items():
        r, b = v["row"], v["base"]
        md.append(f"- **{fam}**: OOS Sharpe {_f(r['oos_sharpe'])} against {_f(b['oos_sharpe'])} without M13 "
                  f"(selection {_f(r['sel_sharpe'])} vs {_f(b['sel_sharpe'])}), a day late {_f(v['late']['oos_sharpe'])}, "
                  f"bootstrap of the difference {_f(v['bootstrap']['p05'])} to {_f(v['bootstrap']['p95'])}, deflated p "
                  f"{_f(v['deflated_p_diff'], 3)}. "
                  f"{'Passes.' if v['passes'] else 'Fails: ' + ', '.join(k for k, ok in v['gates'].items() if not ok) + '.'}\n")
    md.append("\n### The models\n")
    for k in ("M13", "M15"):
        m = res["models"][k]
        st = m["stability"]
        g = m.get("gain_pct")
        gain = "n/a" if g is None else f"{abs(g):.1f} % {'lower' if g > 0 else 'higher'}"
        md.append(f"- **{k}**: squared error {_f(m.get('model_score'), 4)} vs {_f(m.get('baseline_score'), 4)} for the "
                  f"baseline ({gain}), DM p {_f(m.get('dm_p'), 4)}, {m.get('folds_won')} of "
                  f"{m.get('folds')} quarters better, {m.get('rows_oos')} out-of-fold rows; zoo gate "
                  f"{'passed' if (m.get('gate') or {}).get('passed') else 'failed'}, Holm over the three "
                  f"{'passed' if m.get('holm_pass') else 'failed'}. Rank IC (pooled) {_f(m['rank_ic']['pooled'], 3)}, "
                  f"daily mean {_f(m['rank_ic']['daily_mean'], 3)} (t {_f(m['rank_ic']['t'])}); from 2016 "
                  f"{_f(m['rank_ic_from_2016']['pooled'], 3)}. Importance stability over {st['fits']} fits: mean "
                  f"{_f(st['mean'])}, min {_f(st['min'])} ({'stable' if st['stable'] else 'unstable'}; consecutive "
                  f"expanding fits share most rows, so also: fits 20 quarters apart {_f(st.get('lag20_mean'))}, first "
                  f"against last {_f(st.get('first_last'))}). Largest gain "
                  "shares: " + ", ".join(f"{a} {b * 100:.0f} %" for a, b in list((st.get('mean_gain_share') or {}).items())[:5])
                  + ".\n")
    md.append(f"\nHolm inputs (DM p, 1.0 where the model is not lower): {res['models']['holm_inputs']}.\n")
    md.append("\n### Coverage\n")
    cov = [{"year": y, **v} for y, v in sorted(res["coverage"].items()) if y >= 1997]
    md.append(_table(cov, [("year", "year", "s"), ("members_no_volume", "members without volume", "pct"),
                           ("fills_at_close_possible", "member days without an open", "pct"),
                           ("members_with_cik", "members with a CIK", "pct")]))
    return "".join(x if x.endswith("\n") else x + "\n" for x in md)


def _qcols(c: dict) -> dict:
    q = lambda v: "/".join(f"{x * 100:.1f}" if math.isfinite(x) else "n/a" for x in v) + " %"  # noqa: E731
    qr = lambda v: "/".join(f"{x:.2f}" if math.isfinite(x) else "n/a" for x in v)  # noqa: E731
    return {"trades": c["trades"], "realised": q(c["realised_q"]), "mfe": q(c["mfe_q"]), "capture": qr(c["capture_q"]),
            "giveback": q(c["giveback_q"]), "left": q(c["left_q"]), "lost": c["share_lost_gain"]}


def write(res: dict) -> None:
    path = RESULTS / f"{NAME}.md"
    try:
        head = path.read_text(encoding="utf-8").split(MARKER)[0]
    except OSError:
        head = f"# X16 equities training\n\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head.rstrip() + "\n\n" + MARKER + "\n\n" + markdown(res), encoding="utf-8", newline="\n")
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    clean = json.loads(json.dumps(res, default=_json_default))
    (d / "latest.json").write_text(json.dumps(clean, indent=1), encoding="utf-8")
    (d / f"{datetime.now(timezone.utc):%Y-%m-%d}.json").write_text(json.dumps(clean, indent=1), encoding="utf-8")


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, bk.Exit):
        return o.label()
    return str(o)


def main() -> int:
    refresh = "--refresh" in sys.argv
    try:
        ctx = load_ctx(refresh)
    except Exception as e:  # noqa: BLE001
        print(f"{NAME}: no data, nothing judged: {e}", file=sys.stderr)
        return 2
    res = run(ctx)
    write(res)
    print(json.dumps(res["passes"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
