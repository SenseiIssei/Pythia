"""M1: current model techniques as candidates, judged by the same bar as everything else. PAPER ONLY.

    python -m lab.experiments.modern_m1 run [--out DIR] [--only fm,features,tabular,regime,conformal,meta]
                                            [--budget-min 60] [--fm chronos_bolt_small,timesfm_2_5]

Needs the ML image (research/lab/Dockerfile.ml) for torch, Chronos, TimesFM, TabPFN and CatBoost; in the lab image
those parts are skipped with the reason and the rest runs. Writes modern_m1.json and modern_m1.md to --out
(default <data>/reports/models/modern_m1); results/modern_models_m1.md is the first run's write-up.

  fm         (lab.models.fm) Chronos-Bolt small and TimesFM 2.5 zero shot from each coin's past window only, from
             EVAL_FROM (the factories' held-back start), on the very rows the zoo's incumbents were judged on out of
             sample (their newest walk-forward holdout in the registry): next-day return quantiles against M8q and
             its baseline (pinball), next-day variance against M10 and HAR (QLIKE), next-day log volume against the
             last 7 days' mean (squared error; no zoo model forecasts volume). The zoo's gate each time.
  features   Chronos's forecasts as inputs: M10's and M8q's own LightGBM refitted on the same quarterly folds with
             and without them (core.evaluate, the same gate, the incumbent without them as the bar).
  tabular    (lab.models.factory) CatBoost and TabPFN v2 as members of the pump.fun model zoo, walked forward by
             UTC day by A1's selector.walk next to LightGBM (the incumbent) and the logistic baseline; A1's bar:
             the hourly log loss difference deflated over every comparison, p 0.95.
  regime     the small-account regime choice (BTC or USDC for the next 7 days) as a table: every learner walked
             forward by year from 2020 against the base rate and the incumbent rule (BTC above its 200-day mean)
             as a probability; then each as the gate of a 40 and 100 EUR BTC wallet with F2's costs, held back
             from 2024 against the rule's wallet and F2's bar.
  conformal  (lab.models.conformal) rolling split conformal 80 % intervals around M8q's 10-90 % range and M10's
             variance, their coverage; a paper sizing variant of a 15-coin trend book scaled by the interval's width
             against the same book unscaled, held back from 2024.
  meta       (lab.models.metalabel) a second model on the trades of the factory survivors (F2's shadow, the weekly
             factory's shadow) that says whether a trade pays after costs, walked forward by year; the filtered
             book through the same simulator and costs, judged by that factory's bar against the unfiltered one.

R6 (results/factory_lockbox_r6.md): everything is judged on validation only, EVAL_FROM to EVAL_TO; the zoo's
holdout rows stop before EVAL_TO (a row's next-day target ends on it at the latest), the regime and meta-labelling
learners see no label known in the lockbox. Every judged book is a trial in R5's registry (register_trials), written
before its number; the deflation's N is the registry's.

Runtime and peak memory per part are measured in the run (on the VPS when it runs there). Nothing here trades,
signs, holds a key or writes anywhere a book, the engine or the live bots read.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import resource
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import polars as pl

from ..models import conformal as CF
from ..models import core
from ..models import factory as F
from ..models import metalabel as ML

PARTS = ("fm", "features", "tabular", "regime", "conformal", "meta")
EVAL_FROM = "2024-01-01"
EVAL_TO = "2026-06-30"            # R6: validation ends here; LOCKBOX_FROM on is never read
LOCKBOX_FROM = "2026-07-01"       # factory.evaluate.LOCKBOX_FROM
TRIAL_SOURCE = "lab/experiments/modern_m1.py (M1)"
FEAT_FROM = "2021-03-01"
FEAT_TEST = "2023-01-01"
CONF_ALPHA = 0.2
BOOK_FROM = "2022-01-01"
COST = 0.0035                     # the weekly factory's judging cost a unit of one-way turnover
F2_HURDLE = 0.01                  # a small wallet's round trip (Jupiter both ways, network fee and tip on a slot)
PASS_P = 0.95
BOOT_DRAWS, BOOT_BLOCK = 2000, 5
CLASSIFIERS = ("base", "logit", "lgb", "hgb", "catboost", "tabpfn")
META_LEARNERS = ("base", "logit", "lgb", "catboost", "tabpfn")
PF_NEW = ("catboost", "tabpfn")
PF_DECISION_DAYS = 4              # the decision labels' 190,000 rows: the last days only (the runtime)


def out_dir() -> Path:
    from ..data import ROOT
    return ROOT / "reports" / "models" / "modern_m1"


def peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def us(day: str) -> int:
    return core.us(day)


def held(ts: np.ndarray) -> np.ndarray:
    """Validation (R6): EVAL_FROM up to and including EVAL_TO."""
    return (ts >= us(EVAL_FROM)) & (ts < us(LOCKBOX_FROM))


def lockbox_t(days: np.ndarray) -> int:
    """The first row of the lockbox in a daily index (len(days) when it has none)."""
    return int(np.searchsorted(days, us(LOCKBOX_FROM)))


def register_trials(family: str, names: list[str]) -> None:
    """R5: the judged books as trials (id <family>:m1:<name>), before their numbers; a rerun counts them once."""
    from .. import metrics
    metrics.register([{"id": f"{family}:m1:{n}", "family": family, "n": 1, "sharpe": None, "source": TRIAL_SOURCE}
                      for n in names])


def holdout(name: str) -> tuple[pl.DataFrame, str]:
    """The newest walk-forward holdout of a zoo model in the registry: its out-of-sample rows with the challenger's
    and the baseline's forecasts, those before EVAL_TO only (R6: the next-day target of the last ends on EVAL_TO)."""
    from ..data import ROOT
    d = ROOT / "models" / "registry" / name / "candidates"
    vs = sorted(p.name for p in d.iterdir() if (p / "holdout.parquet").exists()) if d.is_dir() else []
    if not vs:
        raise core.DataUnavailable(f"no holdout of {name} in {d}")
    return (pl.read_parquet(d / vs[-1] / "holdout.parquet").filter(pl.col("ts_us") < us(EVAL_TO))
            .sort(["ts_us", "symbol"]), vs[-1])


def _f(x, fmt="{:.4f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


# ---------------------------------------------------------------- fm: zero-shot forecasters

def next_log_volume(h: pl.DataFrame) -> pl.DataFrame:
    """Per row: tomorrow's log quote volume (null unless tomorrow is the next calendar day) and the mean of the
    last 7 days' (the baseline)."""
    return (h.sort(["symbol", "ts_us"])
            .with_columns(lqv=pl.col("qv").log())
            .with_columns(lqv_next=pl.when(pl.col("ts_us").shift(-1).over("symbol") - pl.col("ts_us") == core.DAY_US)
                          .then(pl.col("lqv").shift(-1).over("symbol")).otherwise(None),
                          lqv_base=pl.col("lqv").rolling_mean(7, min_samples=7).over("symbol"))
            .sort(["ts_us", "symbol"]))


def judge_quantiles(h: pl.DataFrame, Q: np.ndarray, start: int) -> dict:
    from ..models import m8_quantiles as m8q
    ts = h["ts_us"].to_numpy()
    y = h["target"].to_numpy().astype(float)
    inc, base = core.as_array(h["challenger"]), core.as_array(h["baseline_pred"])
    m = (ts >= start) & np.isfinite(y) & core.finite_rows(Q) & core.finite_rows(inc) & core.finite_rows(base)
    lm, li, lb = (m8q.loss(y[m], a[m]) for a in (Q, inc, base))
    cov = {f"q{int(a * 100)}": float(np.mean(y[m] <= Q[m, i])) for i, a in enumerate(m8q.ALPHAS)}
    return {"rows": int(m.sum()), "pinball_bps": float(lm.mean() * 1e4), "incumbent_bps": float(li.mean() * 1e4),
            "baseline_bps": float(lb.mean() * 1e4), "coverage": cov,
            "vs_baseline": F.gate(ts[m], lm, lb, 1, "M8q's baseline"), "vs_incumbent": F.gate(ts[m], lm, li, 1, "M8q")}


def judge_vol(h: pl.DataFrame, V: np.ndarray, start: int) -> dict:
    ts = h["ts_us"].to_numpy()
    y = h["target"].to_numpy().astype(float)
    f = np.asarray(V, float)
    inc, har = h["challenger"].to_numpy().astype(float), h["baseline_pred"].to_numpy().astype(float)
    rw = h["x_rw30"].fill_null(np.nan).to_numpy().astype(float) if "x_rw30" in h.columns else np.full(len(y), np.nan)
    m = (ts >= start) & np.isfinite(y) & (y > 0) & np.isfinite(f) & (f > 0) & np.isfinite(inc) & np.isfinite(har)
    lm, li, lb = (core.qlike(y[m], a[m]) for a in (f, inc, har))
    ok = m & np.isfinite(rw) & (rw > 0)
    return {"rows": int(m.sum()), "qlike": float(lm.mean()), "incumbent": float(li.mean()), "baseline": float(lb.mean()),
            "rw30": float(core.qlike(y[ok], rw[ok]).mean()) if ok.any() else None,
            "vs_baseline": F.gate(ts[m], lm, lb, 1, "HAR"), "vs_incumbent": F.gate(ts[m], lm, li, 1, "M10")}


def judge_volume(h: pl.DataFrame, Q: np.ndarray, start: int) -> dict:
    ts = h["ts_us"].to_numpy()
    y = h["lqv_next"].fill_null(np.nan).to_numpy().astype(float)
    b = h["lqv_base"].fill_null(np.nan).to_numpy().astype(float)
    last = h["lqv"].fill_null(np.nan).to_numpy().astype(float)
    f = Q[:, 1]
    m = (ts >= start) & np.isfinite(y) & np.isfinite(b) & np.isfinite(f) & np.isfinite(last)
    lm, lb, ll = (y[m] - f[m]) ** 2, (y[m] - b[m]) ** 2, (y[m] - last[m]) ** 2
    return {"rows": int(m.sum()), "mse": float(lm.mean()), "baseline": float(lb.mean()), "incumbent": None,
            "last_day": float(ll.mean()), "vs_baseline": F.gate(ts[m], lm, lb, 1, "the last 7 days' mean log volume"),
            "vs_last_day": F.gate(ts[m], lm, ll, 1, "today's log volume")}


def fm_part(models: list[str], budget_s: float, log=print) -> dict:
    from ..models import fm
    q, qv = holdout("m8_quantiles")
    v, vv = holdout("m10_vol_regime")
    v = next_log_volume(v)
    start = us(EVAL_FROM)
    out = {"eval_from": EVAL_FROM, "eval_to": EVAL_TO, "m8q_version": qv, "m10_version": vv, "models": {}}
    for name in models:
        t0 = time.time()
        try:
            fc = fm.load(name)
        except (F.Unavailable, OSError) as e:
            out["models"][name] = {"skipped": str(e)}
            log(f"m1 fm: {name} skipped: {e}")
            continue
        res, infos = {}, []
        for key, panel, col, tf in (("returns", q, "ret1", None), ("vol", v, "rv", np.log), ("volume", v, "qv", np.log)):
            left = max(budget_s - (time.time() - t0), 0.0)
            cache = fm.Cache(name, fc.revision, col)
            Q, info = fm.forecast_panel(panel, col, fc, start, left, transform=tf, cache=cache, log=log)
            infos.append(info)
            if key == "returns":
                res[key] = judge_quantiles(panel, Q, start)
            elif key == "vol":
                res[key] = judge_vol(panel, fm.lognormal_mean(Q), start)
            else:
                res[key] = judge_volume(panel, Q, start)
        computed = sum(i["computed"] for i in infos)
        out["models"][name] = {"revision": fc.revision, "licence": fm.PINS[name].licence, **res, "runs": infos,
                               "seconds": time.time() - t0, "complete": all(i["complete"] for i in infos),
                               "ms_per_series": (sum(i["seconds"] for i in infos) / computed * 1000) if computed else None,
                               "peak_mb": peak_mb()}
        del fc
    return out


# ---------------------------------------------------------------- features: the incumbents with Chronos inputs

def _m10_plus(extra: list[str]):
    from ..models import m10_vol_regime as m10
    from dataclasses import replace
    feats = m10.FEATURES + extra

    def fit(frame):
        m, rv = m10._lgb(frame, feats)
        m0, rv0 = m10._lgb(frame, m10.FEATURES)
        return {"m": m, "rv": rv, "m0": m0, "rv0": rv0}

    def predict(f, frame):
        return np.exp(f["m"].predict(m10._X(frame, feats)) + f["rv"] / 2)

    def baseline(f, frame):
        return np.exp(f["m0"].predict(m10._X(frame, m10.FEATURES)) + f["rv0"] / 2)

    spec = replace(m10.SPEC, name="m10_with_chronos", first_test=FEAT_TEST, features=feats, min_train=2000,
                   baseline="M10's LightGBM refitted on the same folds without the Chronos inputs")
    return SimpleNamespace(SPEC=spec, fit=fit, predict=predict, baseline=baseline, loss=m10.loss)


def _m8q_plus(extra: list[str]):
    from ..models import m8_quantiles as m8q
    from dataclasses import replace
    feats = m8q.FEATURES + extra

    def _fit(frame, cols):
        import lightgbm as lgb
        X = frame.select(cols).fill_null(np.nan).to_numpy().astype(np.float64)
        z = frame["z_next"].to_numpy().astype(float)
        ok = np.isfinite(z)
        return {a: lgb.LGBMRegressor(objective="quantile", alpha=a, **m8q.QR).fit(X[ok], z[ok]).booster_
                for a in m8q.ALPHAS}

    def _pred(qr, frame, cols):
        X = frame.select(cols).fill_null(np.nan).to_numpy().astype(np.float64)
        s = frame["sigma"].to_numpy().astype(float)
        return np.sort(np.column_stack([qr[a].predict(X) for a in m8q.ALPHAS]), axis=1) * s[:, None]

    spec = replace(m8q.SPEC, name="m8q_with_chronos", first_test=FEAT_TEST, features=feats,
                   baseline="M8q's LightGBM refitted on the same folds without the Chronos inputs")
    return SimpleNamespace(SPEC=spec, fit=lambda fr: {"m": _fit(fr, feats), "m0": _fit(fr, m8q.FEATURES)},
                           predict=lambda f, fr: _pred(f["m"], fr, feats),
                           baseline=lambda f, fr: _pred(f["m0"], fr, m8q.FEATURES), loss=m8q.loss)


def features_part(budget_s: float, name: str = "chronos_bolt_small", log=print) -> dict:
    from ..models import fm
    t0 = time.time()
    try:
        fc = fm.load(name)
    except (F.Unavailable, OSError) as e:
        return {"skipped": str(e)}
    out = {"model": name, "from": FEAT_FROM, "first_test": FEAT_TEST}
    v, _ = holdout("m10_vol_regime")
    Q, info = fm.forecast_panel(v, "rv", fc, us(FEAT_FROM), budget_s / 2, transform=np.log,
                                cache=fm.Cache(name, fc.revision, "rv"), log=log)
    v = v.with_columns(fm_lrv50=pl.Series(Q[:, 1]), fm_lrv_w=pl.Series(Q[:, 2] - Q[:, 0]))
    v = v.filter(pl.col("fm_lrv50").is_not_nan() & (pl.col("ts_us") >= us(FEAT_FROM)))
    out["vol"] = _ev(_m10_plus(["fm_lrv50", "fm_lrv_w"]), v, info)
    q, _ = holdout("m8_quantiles")
    Q, info = fm.forecast_panel(q, "ret1", fc, us(FEAT_FROM), max(budget_s - (time.time() - t0), 0.0),
                                cache=fm.Cache(name, fc.revision, "ret1"), log=log)
    s = q["sigma"].to_numpy().astype(float)
    q = q.with_columns(fm_z10=pl.Series(Q[:, 0] / s), fm_z50=pl.Series(Q[:, 1] / s), fm_z90=pl.Series(Q[:, 2] / s))
    q = q.filter(pl.col("fm_z50").is_not_nan() & (pl.col("ts_us") >= us(FEAT_FROM)))
    out["returns"] = _ev(_m8q_plus(["fm_z10", "fm_z50", "fm_z90"]), q, info)
    out["seconds"], out["peak_mb"] = time.time() - t0, peak_mb()
    return out


def _ev(mod, panel: pl.DataFrame, info: dict) -> dict:
    ev = core.evaluate(mod, panel)
    return {"rows_oos": ev["rows_oos"], "with": ev["model_score"], "without": ev["baseline_score"],
            "gain_pct": ev["gain_pct"], "dm_p": ev["dm_p"], "folds_won": ev.get("folds_won"),
            "folds": len(ev["folds"]), "gate": ev["gate"], "forecasts": info}


# ---------------------------------------------------------------- tabular: the pump.fun zoo

def tabular_part(log=print) -> dict:
    from ..pumpfun_rt import adaptive_a1 as A1
    from ..pumpfun_rt import selector as S
    from ..pumpfun_rt import selmodel as SM
    from ..pumpfun_rt import zoo as Z
    from ..pumpfun_rt.retrain import load_rows
    t0 = time.time()
    sel, _ = SM.load_rows()
    try:
        rows, _ = load_rows()
    except OSError:
        rows = None
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = {"labels": {}, "comparisons": [], "skipped": {}}
    news = []
    for n in PF_NEW:
        ok, why = F.available(n)
        (news.append(n) if ok else out["skipped"].__setitem__(n, why))
    with F.members(tuple(news)) as lent:
        for label in S.LABELS:
            tab = S.table_for(label, rows, sel)
            if tab is None:
                out["labels"][label] = {"note": "no rows"}
                continue
            days = [d for d in sorted({S.day_of(x) for x in tab["t"]})[1:] if d < today]
            if tab["family"] == "decision":
                days = days[-PF_DECISION_DAYS:]
            names = [Z.INCUMBENT, Z.BASELINE, "hgb"]
            for n in lent:
                if n == "tabpfn":
                    big = max((int((tab["t"] + tab["h_ms"] < S.day_start(d)).sum()) for d in days), default=0)
                    try:
                        F.TabPFN().check(min(big, S.MAX_TRAIN), tab["X"].shape[1])
                    except F.TooLarge as e:
                        out["labels"].setdefault(label, {})["tabpfn"] = str(e)
                        continue
                names.append(n)
            ts = time.time()
            walked = S.walk(tab, days, names=names, log=log)
            if not walked:
                out["labels"][label] = {"note": "no day with enough rows"}
                continue
            y = np.concatenate([x["y"] for x in walked])
            t = np.concatenate([x["t"] for x in walked])
            ls = {c: Z.logloss_rows(np.concatenate([x["p"][c].astype(float) for x in walked]), y)
                  for c in names if all(c in x["p"] for x in walked)}
            res = out["labels"].setdefault(label, {})
            res.update(days=[x["day"] for x in walked], rows=int(len(y)), rate=float(y.mean()),
                       loss={c: float(v.mean()) for c, v in ls.items()}, seconds=time.time() - ts)
            for c in [n for n in lent if n in ls]:
                for other in (Z.INCUMBENT, Z.BASELINE):
                    r = A1.sharpe(A1.hourly(ls[other] - ls[c], t))
                    r.update(label=label, member=c, against=other)
                    out["comparisons"].append(r)
    A1.deflate(out["comparisons"])
    for r in out["comparisons"]:
        r["beats"] = bool(r["dsr"] >= PASS_P and r["mean"] > 0)
    out["seconds"], out["peak_mb"] = time.time() - t0, peak_mb()
    return out


# ---------------------------------------------------------------- regime: the small account's BTC or USDC

REGIME_FEATURES = ["btc_r7", "btc_r28", "btc_r90", "btc_r180", "spy_r28", "spy_r90", "gold_r28", "eth_btc_r28",
                   "btc_vol", "spy_vol", "btc_ma100", "btc_ma200", "spy_ma200", "breadth100"]
REGIME_H = 7


def regime_rows(c) -> dict:
    """Per close t of F2's market: the features above from closes up to t, y = BTC up over the next REGIME_H days
    (known at t + REGIME_H), and the incumbent rule (BTC above its 200-day mean)."""
    from ..factory import small
    A = small.ASSETS
    j = {a: A.index(a) for a in A}
    r = {lb: small._ret_back(c, lb) for lb in (7, 28, 90, 180)}
    vol = small.annvol(c)
    ma100, ma200 = small._ma(c, 100), small._ma(c, 200)
    with np.errstate(all="ignore"):
        gap100, gap200 = c.sig / ma100 - 1, c.sig / ma200 - 1
        X = np.column_stack([r[7][:, j["BTC"]], r[28][:, j["BTC"]], r[90][:, j["BTC"]], r[180][:, j["BTC"]],
                             r[28][:, j["SPY"]], r[90][:, j["SPY"]], r[28][:, j["GOLD"]],
                             r[28][:, j["ETH"]] - r[28][:, j["BTC"]], vol[:, j["BTC"]], vol[:, j["SPY"]],
                             gap100[:, j["BTC"]], gap200[:, j["BTC"]], gap200[:, j["SPY"]],
                             np.mean(np.where(np.isfinite(gap100), gap100 > 0, 0.0), axis=1)])
        b = c.sig[:, j["BTC"]]
        fwd = np.full(c.T, np.nan)
        fwd[:-REGIME_H] = np.log(b[REGIME_H:] / b[:-REGIME_H])
    y = np.where(np.isfinite(fwd), (fwd > 0).astype(float), np.nan)
    rule = np.nan_to_num(gap200[:, j["BTC"]] > 0).astype(float)
    return {"X": X, "y": y, "t": np.arange(c.T, dtype=float), "known": np.arange(c.T, dtype=float) + REGIME_H,
            "rule": rule, "ok": np.isfinite(X[:, 11])}


def rule_probability(rule: np.ndarray, y: np.ndarray, known: np.ndarray, t: np.ndarray, blocks) -> np.ndarray:
    """The incumbent as a forecaster: in each block the training rows' up rate when the rule was on, and off."""
    p = np.full(len(y), np.nan)
    for lo, hi in blocks:
        tr = (known < lo) & np.isfinite(y)
        te = (t >= lo) & (t < hi)
        for v in (0.0, 1.0):
            m = tr & (rule == v)
            p[te & (rule == v)] = y[m].mean() if m.sum() >= 20 else (y[tr].mean() if tr.any() else 0.5)
    return p


def yearly_blocks(c, first: int = 2020) -> list[tuple[int, int]]:
    last = int(str((c.days[-1] // core.DAY_US).astype("datetime64[D]"))[:4])
    out = []
    for yr in range(first, last + 1):
        lo = c.t_of(f"{yr}-01-01")
        hi = c.t_of(f"{yr + 1}-01-01") if yr < last else c.T
        out.append((lo, hi))
    return out


def regime_part(log=print) -> dict:
    from ..factory import small
    t0 = time.time()
    c, v = small.load_market(offline=True)
    R = regime_rows(c)
    ok = R["ok"] & np.isfinite(R["y"]) & (R["known"] < lockbox_t(c.days))     # R6: no label known in the lockbox
    blocks = yearly_blocks(c)
    names = [n for n in CLASSIFIERS]
    sub = {k: (x[ok] if isinstance(x, np.ndarray) and len(x) == c.T else x) for k, x in R.items()}
    w = F.walk(sub["X"], sub["y"], sub["t"], sub["known"], blocks, names, min_train=200, log=log)
    p = {n: np.full(c.T, np.nan) for n in names}
    for n in names:
        p[n][ok] = w["p"][n]
    p["rule"] = rule_probability(R["rule"], np.where(ok, R["y"], np.nan), R["known"], R["t"], blocks)
    ts = c.days
    y = R["y"]
    m = ok & np.isfinite(p["base"])
    res = {"rows": int(m.sum()), "from": str((ts[m][0] // core.DAY_US).astype("datetime64[D]")) if m.any() else None,
           "rate": float(y[m].mean()) if m.any() else None, "not_run": w["skipped"], "seconds_fit": w["seconds"],
           "learners": {}}
    for n in names + ["rule"]:
        mm = m & np.isfinite(p[n])
        if not mm.any():
            continue
        ln, lb, lr = core.logloss(y[mm], p[n][mm]), core.logloss(y[mm], p["base"][mm]), core.logloss(y[mm], p["rule"][mm])
        res["learners"][n] = {"logloss": float(ln.mean()), "vs_base": F.gate(ts[mm], ln, lb, REGIME_H, "the base rate"),
                              "vs_rule": F.gate(ts[mm], ln, lr, REGIME_H, "the 200-day rule")}
    res["books"] = regime_books(c, v, p, R["rule"], log)
    res["seconds"], res["peak_mb"] = time.time() - t0, peak_mb()
    return res


def _f2_pool(trials: list[str]) -> dict:
    """F2's pool with these trials registered first (register_trials, the small family)."""
    from ..factory import small
    register_trials("small", trials)
    led = small.Ledger(small.seed_dir() / "ledger.jsonl") if not (small.small_dir() / "ledger.jsonl").exists() \
        else small.Ledger()
    return led.pool()


def _f2_book(c, v, W: np.ndarray, g: dict, pool: dict, bench: dict) -> dict:
    """F2's held-back numbers for a weight matrix at 40 and 100 EUR, and the gates of F2's bar that do not need an
    in-sample row (drawdown, above holding SPYx at both sizes, a close late, deflated p)."""
    from ..factory import ledger as lg
    from ..factory import small
    t0, t1 = small.windows(c)["oos"]
    out = {}
    x40 = None
    for cap in small.CAPITALS:
        res = small.simulate(c, W, g, v, cap, t0, t1)
        m = small.measure(res, cap)
        tag = f"{cap:g}"
        out.update({f"{k}_{tag}": m[k] for k in ("cagr", "max_dd", "sharpe", "end_eur", "costs_eur", "exposure")})
        out[f"spy_cagr_{tag}"] = bench[f"SPY@{tag}"]["cagr"]
        if cap == small.MAIN:
            x40 = small.returns(res, cap)
    late = np.vstack([np.zeros((1, W.shape[1])), W[:-1]])
    out["late_cagr"] = small.measure(small.simulate(c, late, g, v, small.MAIN, t0, t1), small.MAIN)["cagr"]
    out["deflated_p"] = lg.deflated(x40, pool)
    caps = [f"{x:g}" for x in small.CAPITALS]
    out["gates"] = {"drawdown": max(out[f"max_dd_{t}"] for t in caps) < small.SAFE_DD,
                    "beats_spy": all(out[f"cagr_{t}"] > out[f"spy_cagr_{t}"] for t in caps),
                    "late_fill": out["late_cagr"] > 0, "deflated": out["deflated_p"] > PASS_P}
    out["passes"] = all(out["gates"].values())
    out["oos_returns_40"] = x40
    return out


def regime_books(c, v, p: dict, rule: np.ndarray, log=print) -> dict:
    from ..factory import small
    g = small.hold_genome("BTC")
    W0 = small.weights(c, g)
    bench = small.benchmarks(c, v, small.windows(c)["oos"])
    pool = _f2_pool([f"regime:{n}" for n in p])
    out = {"window": [small._day(c, x) for x in small.windows(c)["oos"]], "pool_trials": pool["n_trials"],
           "spy": {k: small.strip_returns(bench)[k] for k in ("SPY@40", "SPY@100")},
           "btc": {k: small.strip_returns(bench)[k] for k in ("BTC@40", "BTC@100")}, "books": {}}
    for n, pr in p.items():
        if n != "rule" and (n == F.BASELINE or not np.isfinite(pr).any()):
            continue                                  # the base rate is the classifiers' bar, not a gate
        gate = rule > 0 if n == "rule" else np.nan_to_num(pr, nan=0.0) > 0.5
        out["books"][n] = _f2_book(c, v, W0 * gate[:, None], g, pool, bench)
    r0 = out["books"]["rule"]["oos_returns_40"]
    for n, b in out["books"].items():
        b["vs_rule"] = boot_sharpe_diff(b.pop("oos_returns_40"), r0) if n != "rule" else None
    out["books"]["rule"].pop("oos_returns_40", None)
    return out


# ---------------------------------------------------------------- the bootstrap of a Sharpe difference

def boot_sharpe_diff(a: np.ndarray, b: np.ndarray, draws: int = BOOT_DRAWS, block: int = BOOT_BLOCK,
                     seed: int = 7) -> dict:
    """Annual Sharpe of a and b on the same days and the share of paired block-bootstrap draws in which a's is
    higher (moving blocks of `block` days)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    n = min(len(a), len(b))
    a, b = a[-n:], b[-n:]
    ok = np.isfinite(a) & np.isfinite(b)
    a, b = a[ok], b[ok]

    def sh(x):
        sd = x.std()
        return float(x.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0
    if len(a) < 2 * block:
        return {"sharpe": sh(a), "other": sh(b), "p_better": None}
    rng = np.random.default_rng(seed)
    k = math.ceil(len(a) / block)
    better = 0
    for _ in range(draws):
        idx = (rng.integers(0, len(a) - block + 1, k)[:, None] + np.arange(block)[None, :]).ravel()[: len(a)]
        better += sh(a[idx]) > sh(b[idx])
    return {"sharpe": sh(a), "other": sh(b), "p_better": better / draws}


# ---------------------------------------------------------------- conformal

def conformal_part(log=print) -> dict:
    t0 = time.time()
    out = {"alpha": CONF_ALPHA, "window_days": CF.WINDOW_DAYS, "eval_from": EVAL_FROM, "eval_to": EVAL_TO}
    q, _ = holdout("m8_quantiles")
    ts = q["ts_us"].to_numpy()
    y = q["target"].to_numpy().astype(float)
    Q = core.as_array(q["challenger"])
    cq = CF.rolling(ts, y, Q[:, 0], Q[:, 2], CONF_ALPHA, embargo_days=1)
    ev = held(ts)
    out["m8q"] = {"raw": CF.coverage(y[ev], Q[ev, 0], Q[ev, 2]), "conformal": CF.coverage(y[ev], cq["lo"][ev], cq["hi"][ev]),
                  "by_symbol": per_symbol_coverage(q["symbol"].to_numpy()[ev], y[ev], cq["lo"][ev], cq["hi"][ev])}
    v, _ = holdout("m10_vol_regime")
    tv = v["ts_us"].to_numpy()
    ly = np.log(v["target"].to_numpy().astype(float))
    lf = np.log(v["challenger"].to_numpy().astype(float))
    cv = CF.rolling(tv, ly, lf, lf, CONF_ALPHA, embargo_days=1)
    evv = held(tv)
    out["m10"] = {"conformal": CF.coverage(ly[evv], cv["lo"][evv], cv["hi"][evv]),
                  "note": "M10 is a point forecast: the interval is on the log variance, |log y - log f| as the score"}
    out["sizing"] = sizing_book(q, cq)
    out["seconds"], out["peak_mb"] = time.time() - t0, peak_mb()
    return out


def per_symbol_coverage(sym: np.ndarray, y, lo, hi) -> dict:
    cov = {}
    for s in np.unique(sym):
        m = sym == s
        c = CF.coverage(y[m], lo[m], hi[m])["coverage"]
        if c is not None:
            cov[str(s)] = c
    vals = list(cov.values())
    return {"min": min(vals) if vals else None, "max": max(vals) if vals else None}


def sizing_book(q: pl.DataFrame, cq: dict) -> dict:
    """A 15-coin trend book (a coin held at 1/15 while its 30-day return and its distance to its 200-day mean are
    both positive), daily at the close, COST a unit of turnover, unscaled and scaled by the conformal width."""
    d = q.with_columns(lo=pl.Series(cq["lo"]), hi=pl.Series(cq["hi"])).filter(pl.col("ts_us") >= us(BOOK_FROM))
    syms = sorted(d["symbol"].unique().to_list())
    days = np.unique(d["ts_us"].to_numpy())
    n = len(syms)
    on, ret, width = (np.zeros((len(days), n)), np.zeros((len(days), n)), np.full((len(days), n), np.nan))
    di = {t: i for i, t in enumerate(days)}
    si = {s: j for j, s in enumerate(syms)}
    for r in d.select(["ts_us", "symbol", "ret30", "ma200_gap", "ret_next", "lo", "hi"]).iter_rows():
        i, j = di[r[0]], si[r[1]]
        on[i, j] = float((r[2] or 0) > 0 and (r[3] or 0) > 0)
        ret[i, j] = math.exp(r[4]) - 1 if r[4] is not None and math.isfinite(r[4]) else 0.0
        width[i, j] = (r[6] - r[5]) if r[5] is not None and r[6] is not None else np.nan
    scale = np.ones_like(width)
    for j in range(n):
        scale[:, j] = CF.width_scale(days, width[:, j])
    out = {"coins": n, "from": BOOK_FROM, "held_back_from": EVAL_FROM, "held_back_to": EVAL_TO}
    series = {}
    for name, W in (("unscaled", on / n), ("scaled", on / n * scale)):
        gross = (W * ret).sum(1)
        tov = np.abs(np.diff(np.vstack([np.zeros((1, n)), W]), axis=0)).sum(1)
        r = gross - COST * tov
        hb = held(days)
        from .fam_common import perf
        series[name] = r[hb]
        out[name] = {**perf(r[hb]), "turnover_yr": float(tov[hb].sum() / max(hb.sum() / 365, 1e-9)),
                     "exposure": float(W[hb].sum(1).mean())}
    from ..factory import ledger as lg
    register_trials("hand", ["sizing:scaled", "sizing:unscaled"])
    pool = lg.Ledger().pool()
    out["scaled"]["deflated_p"] = lg.deflated(series["scaled"], pool)
    out["unscaled"]["deflated_p"] = lg.deflated(series["unscaled"], pool)
    out["pool_trials"] = pool["n_trials"]
    out["vs_unscaled"] = boot_sharpe_diff(series["scaled"], series["unscaled"])
    out["passes"] = bool((out["vs_unscaled"]["p_better"] or 0) >= PASS_P and out["scaled"]["deflated_p"] > PASS_P)
    return out


# ---------------------------------------------------------------- meta-labelling

def survivors() -> dict[str, list[dict]]:
    """The survivors of F2 and of the weekly factory (a held-back check that started a shadow, on this machine or in
    the committed seed), with their genomes from the ledgers."""
    from ..factory import ledger as lg
    from ..factory import small
    out = {}
    for kind, hold_paths, led_paths in (
            ("small", [small.small_dir() / "holdout.jsonl", small.seed_dir() / "holdout.jsonl"],
             [small.small_dir() / "ledger.jsonl", small.seed_dir() / "ledger.jsonl"]),
            ("weekly", [lg.factory_dir() / "holdout.jsonl", lg.seed_dir() / "holdout.jsonl"],
             [lg.ledger_path(), lg.seed_dir() / "ledger.jsonl"])):
        hold = [h for p in hold_paths for h in lg.read_jsonl(p)]
        keys = list(dict.fromkeys(h["key"] for h in hold if h.get("decision") == "shadow"))
        rows = {}
        for p in led_paths:
            for r in lg.read_jsonl(p):
                rows.setdefault(r["key"], r)
        out[kind] = [{"key": k, "name": rows[k].get("name"), "genome": rows[k]["genome"]} for k in keys if k in rows]
    return out


def meta_walk(px, W, btc: int, days: np.ndarray, blocks, hurdle: float, log=print) -> dict:
    tr = ML.trades(W)
    y = ML.labels(px, tr, hurdle)
    X = ML.features(px, W, tr, btc)
    t = np.array([a for _, a, _ in tr], dtype=float)
    known = ML.known_at(tr, len(W))
    lab = np.isfinite(y) & (known < lockbox_t(days))      # R6: no label known in the lockbox is learned or scored
    w = F.walk(X[lab], y[lab], t[lab], known[lab], blocks, list(META_LEARNERS), min_train=40, log=log)
    p = {n: np.full(len(tr), np.nan) for n in META_LEARNERS}
    for n in META_LEARNERS:
        p[n][lab] = w["p"][n]
    # a trade still open at the end has no label, but the filter needs its probability: from the trades closed
    # before it opened
    for k in np.flatnonzero(~lab & (t >= blocks[0][0])):
        tr_ok = lab & (known < t[k])
        for n in META_LEARNERS:
            if n in w["skipped"] or tr_ok.sum() < 40:
                continue
            try:
                m = F.make(n)
                m.check(int(tr_ok.sum()), X.shape[1])
                p[n][k] = m.fit(X[tr_ok], y[tr_ok]).predict_proba(X[k:k + 1])[0]
            except (F.Unavailable, F.TooLarge):
                pass
    m = lab & np.isfinite(p["base"])
    ts = days[t.astype(int)]
    cls = {}
    for n in META_LEARNERS:
        mm = m & np.isfinite(p[n])
        if mm.sum() >= 30:
            ln, lb = core.logloss(y[mm], p[n][mm]), core.logloss(y[mm], p["base"][mm])
            cls[n] = {"logloss": float(ln.mean()), "vs_base": F.gate(ts[mm], ln, lb, 1, "the base rate")}
    return {"trades": tr, "p": p, "info": {"trades": len(tr), "labelled": int(lab.sum()),
                                           "pay_rate": float(y[lab].mean()) if lab.any() else None,
                                           "scored": int(m.sum()), "skipped": w["skipped"],
                                           "seconds_fit": w["seconds"], "classifier": cls}}


def filters_of(mw: dict) -> list[str]:
    """The learners that gave the trades a probability (the base rate is the classifiers' bar, not a filter)."""
    return [n for n in META_LEARNERS if n != F.BASELINE and np.isfinite(mw["p"][n]).any()]


def meta_part(log=print) -> dict:
    t0 = time.time()
    surv = survivors()
    out = {"small": [], "weekly": []}
    if surv["small"]:
        from ..factory import small
        c, v = small.load_market(offline=True)
        bench = small.benchmarks(c, v, small.windows(c)["oos"])
        pool = _f2_pool([f"meta:{s['key']}:{n}" for s in surv["small"] for n in META_LEARNERS])
        for s in surv["small"]:
            g = s["genome"]
            W = small.weights(c, g)
            mw = meta_walk(c.px, W, small.ASSETS.index("BTC"), c.days, yearly_blocks(c), F2_HURDLE, log)
            base = _f2_book(c, v, W, g, pool, bench)
            r0 = base.pop("oos_returns_40")
            books = {}
            for n in filters_of(mw):
                b = _f2_book(c, v, ML.filtered(W, mw["trades"], mw["p"][n]), g, pool, bench)
                b["vs_unfiltered"] = boot_sharpe_diff(b.pop("oos_returns_40"), r0)
                b["passes_meta"] = bool(b["passes"] and (b["vs_unfiltered"]["p_better"] or 0) >= PASS_P)
                books[n] = b
            out["small"].append({"key": s["key"], "name": s["name"], **mw["info"], "unfiltered": base, "filtered": books,
                                 "pool_trials": pool["n_trials"]})
    if surv["weekly"]:
        out["weekly"] = meta_weekly(surv["weekly"], log)
    out["seconds"], out["peak_mb"] = time.time() - t0, peak_mb()
    return out


def meta_weekly(surv: list[dict], log=print) -> list[dict]:
    from ..factory import build
    from ..factory import evaluate as E
    from ..factory import ledger as lg
    from . import fam_common as fc
    c = build.make_ctx(fc.load_panel())
    oos = E.windows(c)["oos"]
    btc = E.btc_benchmark(c)
    register_trials("factory", [f"meta:{s['key']}:{n}" for s in surv for n in META_LEARNERS])
    pool = lg.Ledger().pool()
    btc_col = c.names.index("BTCUSDT") if "BTCUSDT" in c.names else int(np.argmax(c.qv[-1]))
    yrs = sorted({int(str((d // fc.DAY_US).astype("datetime64[D]"))[:4]) for d in c.days})
    blocks = []
    for yr in range(2020, yrs[-1] + 1):
        lo = int(np.searchsorted(c.days, us(f"{yr}-01-01")))
        hi = int(np.searchsorted(c.days, us(f"{yr + 1}-01-01"))) if yr < yrs[-1] else c.T
        blocks.append((lo, hi))
    out = []
    for s in surv:
        g = s["genome"]
        W = build.weights(c, g)
        mw = meta_walk(c.px, W, btc_col, c.days, blocks, 2 * COST, log)

        def judge(Wx):
            gross, tov, _ = build._sim(c, Wx, g)
            net = build.net(gross, tov, COST)
            lgr, lt, _ = build._sim(c, np.vstack([np.zeros((1, Wx.shape[1])), Wx[:-1]]), g)
            p35 = fc.perf(net[oos])
            r = {"sharpe_35": p35["sharpe"], "sharpe_70": E.sharpe(build.net(gross, tov, 0.0070)[oos]),
                 "cagr": p35["cagr"], "max_dd": p35["max_dd"], "late": E.sharpe(build.net(lgr, lt, COST)[oos]),
                 "deflated_p": lg.deflated(net[oos], pool)}
            r["gates"] = {"oos_positive": r["sharpe_35"] > 0, "stress": r["sharpe_70"] > 0,
                          "drawdown": r["max_dd"] < btc["max_dd"], "late_fill": r["late"] > 0,
                          "deflated": r["deflated_p"] > PASS_P}
            r["passes"] = all(r["gates"].values())
            return r, net[oos]
        base, r0 = judge(W)
        books = {}
        for n in filters_of(mw):
            b, rn = judge(ML.filtered(W, mw["trades"], mw["p"][n]))
            b["vs_unfiltered"] = boot_sharpe_diff(rn, r0)
            b["passes_meta"] = bool(b["passes"] and (b["vs_unfiltered"]["p_better"] or 0) >= PASS_P)
            books[n] = b
        out.append({"key": s["key"], "name": s["name"], **mw["info"], "unfiltered": base, "filtered": books,
                    "btc": btc, "pool_trials": pool["n_trials"]})
    return out


# ---------------------------------------------------------------- the run and the report

def run(out: Path, parts=PARTS, budget_min: float = 60.0, fm_models=None, log=print) -> dict:
    from ..models import fm
    fm_models = list(fm_models or fm.PINS)
    res = {"run": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "parts": {}, "timing": {}}
    for part in parts:
        t0 = time.time()
        try:
            if part == "fm":
                r = fm_part(fm_models, budget_min * 60, log)
            elif part == "features":
                r = features_part(budget_min * 60 / 2, log=log)
            elif part == "tabular":
                r = tabular_part(log)
            elif part == "regime":
                r = regime_part(log)
            elif part == "conformal":
                r = conformal_part(log)
            else:
                r = meta_part(log)
        except core.DataUnavailable as e:
            r = {"skipped": str(e)}
        res["parts"][part] = r
        res["timing"][part] = {"seconds": time.time() - t0, "peak_mb": peak_mb()}
        log(f"m1: {part} in {time.time() - t0:.0f} s, peak {peak_mb():.0f} MB")
        out.mkdir(parents=True, exist_ok=True)
        (out / "modern_m1.json").write_text(json.dumps(jsonable(res), indent=1, default=str), encoding="utf-8")
    (out / "modern_m1.md").write_text(markdown(res), encoding="utf-8")
    return res


def jsonable(x):
    if isinstance(x, dict):
        return {str(k): jsonable(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, np.ndarray):
        return [jsonable(v) for v in x.tolist()]
    if isinstance(x, (np.floating, float)):
        return float(x) if math.isfinite(float(x)) else None
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, np.bool_):
        return bool(x)
    return x


def _yes(g: dict | None) -> str:
    return "n/a" if not g else ("passes" if g.get("passed") else "fails")


def markdown(res: dict) -> str:
    P = res["parts"]
    L = [f"# M1 run {res['run']}", ""]
    t = res.get("timing", {})
    if "fm" in P:
        p = P["fm"]
        L += ["## Foundation models, zero shot", ""]
        if "skipped" in p:
            L += [f"Skipped: {p['skipped']}", ""]
        else:
            L += [f"Rows from {p['eval_from']}; incumbents M8q {p['m8q_version']}, M10 {p['m10_version']}.", "",
                  "| model | target | loss | incumbent | baseline | vs baseline | vs incumbent | rows |",
                  "|---|---|---|---|---|---|---|---|"]
            for name, m in p["models"].items():
                if "skipped" in m:
                    L.append(f"| {name} | skipped: {m['skipped']} | | | | | | |")
                    continue
                r, v, w = m["returns"], m["vol"], m["volume"]
                L.append(f"| {name} | return q10/50/90 (pinball bps) | {_f(r['pinball_bps'], '{:.1f}')} | "
                         f"{_f(r['incumbent_bps'], '{:.1f}')} | {_f(r['baseline_bps'], '{:.1f}')} | "
                         f"{_yes(r['vs_baseline'])} (p {_f(r['vs_baseline']['dm_p'], '{:.3g}')}) | "
                         f"{_yes(r['vs_incumbent'])} (p {_f(r['vs_incumbent']['dm_p'], '{:.3g}')}) | {r['rows']:,} |")
                L.append(f"| {name} | next-day variance (QLIKE) | {_f(v['qlike'])} | {_f(v['incumbent'])} | "
                         f"{_f(v['baseline'])} | {_yes(v['vs_baseline'])} (p {_f(v['vs_baseline']['dm_p'], '{:.3g}')}) | "
                         f"{_yes(v['vs_incumbent'])} (p {_f(v['vs_incumbent']['dm_p'], '{:.3g}')}) | {v['rows']:,} |")
                L.append(f"| {name} | next-day log volume (MSE) | {_f(w['mse'])} | none | {_f(w['baseline'])} | "
                         f"{_yes(w['vs_baseline'])} (p {_f(w['vs_baseline']['dm_p'], '{:.3g}')}) | n/a | {w['rows']:,} |")
                L.append(f"| {name} | the same against today's volume | {_f(w['mse'])} | none | {_f(w['last_day'])} | "
                         f"{_yes(w['vs_last_day'])} (p {_f(w['vs_last_day']['dm_p'], '{:.3g}')}) | n/a | {w['rows']:,} |")
            L.append("")
            for name, m in p["models"].items():
                if "skipped" not in m:
                    L.append(f"- {name} ({m['licence']}, revision {m['revision'][:8]}): {m['seconds']:.0f} s, "
                             f"{_f(m['ms_per_series'], '{:.1f}')} ms a series, peak {m['peak_mb']:.0f} MB, "
                             f"{'complete' if m['complete'] else 'stopped at the budget'}; coverage of its q10/q50/q90 "
                             + ", ".join(f"{k} {v_ * 100:.1f} %" for k, v_ in m["returns"]["coverage"].items()))
            L.append("")
    if "features" in P:
        p = P["features"]
        L += ["## Chronos as an input to the incumbents", ""]
        if "skipped" in p:
            L += [f"Skipped: {p['skipped']}", ""]
        else:
            for k, title in (("vol", "M10 (QLIKE)"), ("returns", "M8q (pinball)")):
                e = p[k]
                L.append(f"- {title}: with {_f(e['with'])} vs without {_f(e['without'])} on {e['rows_oos']:,} rows "
                         f"from {p['first_test']}, folds won {e['folds_won']} of {e['folds']}, DM p {_f(e['dm_p'], '{:.3g}')}: "
                         f"{'passes' if e['gate']['passed'] else 'fails'}")
            L.append("")
    if "tabular" in P:
        p = P["tabular"]
        L += ["## CatBoost and TabPFN in the pump.fun zoo", ""]
        for n, why in p.get("skipped", {}).items():
            L.append(f"- {n}: {why}")
        L += ["", "| label | days | rows | lgb | logit | hgb | catboost | tabpfn |", "|---|---|---|---|---|---|---|---|"]
        for label, r in p["labels"].items():
            if "loss" not in r:
                L.append(f"| {label} | {r.get('note', '')} {r.get('tabpfn', '')} | | | | | | |")
                continue
            lo = r["loss"]
            L.append(f"| {label} | {len(r['days'])} | {r['rows']:,} | " + " | ".join(
                _f(lo.get(n)) if n in lo else ("skipped" if n == "tabpfn" and "tabpfn" in r else "n/a")
                for n in ("lgb", "logit", "hgb", "catboost", "tabpfn")) + " |")
        for label, r in p["labels"].items():
            if "tabpfn" in r:
                L.append(f"\n{label}: {r['tabpfn']}")
        L += ["", "| label | member | against | hourly mean | deflated | beats |", "|---|---|---|---|---|---|"]
        for c in p["comparisons"]:
            L.append(f"| {c['label']} | {c['member']} | {c['against']} | {c['mean']:+.4f} | {c['dsr']:.2f} | "
                     f"{'yes' if c['beats'] else 'no'} |")
        L.append("")
    if "regime" in P:
        p = P["regime"]
        L += ["## Small-account regime choice", ""]
        if "skipped" in p:
            L += [f"Skipped: {p['skipped']}", ""]
        else:
            L += [f"{p['rows']:,} days from {p['from']}, BTC up over the next 7 days on {p['rate'] * 100:.1f} %.", "",
                  "| learner | log loss | vs base rate | vs 200-day rule | wallet 40 EUR CAGR | drawdown | Sharpe | "
                  "beats SPYx | deflated p | Sharpe above the rule's |", "|---|---|---|---|---|---|---|---|---|---|"]
            for n, b in p["books"]["books"].items():
                le = p["learners"].get(n, {})
                vr = b.get("vs_rule") or {}
                L.append(f"| {n} | {_f(le.get('logloss'))} | {_yes(le.get('vs_base'))} | {_yes(le.get('vs_rule'))} | "
                         f"{b['cagr_40'] * 100:.1f} % | {b['max_dd_40'] * 100:.1f} % | {b['sharpe_40']:.2f} | "
                         f"{'yes' if b['gates']['beats_spy'] else 'no'} | {b['deflated_p']:.2f} | "
                         f"{_f(vr.get('p_better'), '{:.2f}')} |")
            for n, why in p.get("not_run", {}).items():
                L.append(f"\n{n}: {why}")
            L.append("")
    if "conformal" in P:
        p = P["conformal"]
        L += ["## Conformal intervals", ""]
        m8, m10 = p["m8q"], p["m10"]
        L.append(f"- M8q 10-90 % range from {p['eval_from']}: raw coverage {m8['raw']['coverage'] * 100:.1f} % "
                 f"(width {m8['raw']['width'] * 100:.2f} %), conformal {m8['conformal']['coverage'] * 100:.1f} % "
                 f"(width {m8['conformal']['width'] * 100:.2f} %), per coin {m8['by_symbol']['min'] * 100:.1f} to "
                 f"{m8['by_symbol']['max'] * 100:.1f} %")
        L.append(f"- M10 log variance: conformal 80 % coverage {m10['conformal']['coverage'] * 100:.1f} % "
                 f"(width {m10['conformal']['width']:.2f} in log units)")
        s = p["sizing"]
        L.append(f"- sizing, {s['coins']} coins, held back from {s['held_back_from']}: unscaled Sharpe "
                 f"{s['unscaled']['sharpe']:.2f} (drawdown {s['unscaled']['max_dd'] * 100:.1f} %), scaled "
                 f"{s['scaled']['sharpe']:.2f} (drawdown {s['scaled']['max_dd'] * 100:.1f} %), scaled higher in "
                 f"{_f(s['vs_unscaled']['p_better'], '{:.2f}')} of the bootstrap draws, deflated p "
                 f"{s['scaled']['deflated_p']:.2f}: {'passes' if s['passes'] else 'fails'}")
        L.append("")
    if "meta" in P:
        p = P["meta"]
        L += ["## Meta-labelling the factory survivors", ""]
        for kind in ("small", "weekly"):
            for s in p.get(kind, []):
                u = s["unfiltered"]
                sh = "sharpe_40" if kind == "small" else "sharpe_35"
                L.append(f"### {kind} {s['key']}: {s['name']}")
                L.append("")
                L.append(f"{s['trades']:,} trades, {s['labelled']:,} closed, pay after costs {_f(s['pay_rate'], '{:.2f}')}; "
                         f"unfiltered held-back Sharpe {u[sh]:.2f}, deflated p {u['deflated_p']:.2f}.")
                L += ["", "| learner | log loss | vs base | filtered Sharpe | drawdown | deflated p | above unfiltered | bar |",
                      "|---|---|---|---|---|---|---|---|"]
                for n, b in s["filtered"].items():
                    cl = s["classifier"].get(n, {})
                    dd = b.get("max_dd_40", b.get("max_dd"))
                    L.append(f"| {n} | {_f(cl.get('logloss'))} | {_yes(cl.get('vs_base'))} | {b[sh]:.2f} | "
                             f"{dd * 100:.1f} % | {b['deflated_p']:.2f} | {_f(b['vs_unfiltered']['p_better'], '{:.2f}')} | "
                             f"{'passes' if b['passes_meta'] else 'fails'} |")
                for n, why in s.get("skipped", {}).items():
                    L.append(f"\n{n}: {why}")
                L.append("")
    L += ["## Runtime", "", "| part | seconds | peak memory MB |", "|---|---|---|"]
    for k, v in t.items():
        L.append(f"| {k} | {v['seconds']:.0f} | {v['peak_mb']:.0f} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.experiments.modern_m1")
    ap.add_argument("cmd", nargs="?", default="run", choices=("run",))
    ap.add_argument("--out", default=None)
    ap.add_argument("--only", default=",".join(PARTS))
    ap.add_argument("--budget-min", type=float, default=float(os.environ.get("PYTHIA_M1_BUDGET_MIN", "60")))
    ap.add_argument("--fm", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    parts = [p for p in a.only.split(",") if p in PARTS]
    res = run(Path(a.out) if a.out else out_dir(), parts, a.budget_min, a.fm.split(",") if a.fm else None)
    print(markdown(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
