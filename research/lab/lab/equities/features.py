"""Model rows for X16: M13 (equity event candidates) and M15 (held equity positions).

Both are zoo-style panels: one row per (ts_us, symbol) with `target` (null
where the outcome is not known yet) and the features. `symbol` is
"<ticker>|<family>" so the same name on the same day in two families stays two
rows. Every feature uses closes up to the decision close only; every target
starts at the next fill.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl

from . import books as bk
from .panel import Panel

FAMILIES = ("A1", "A2", "A3")
M13_H = 20
M15_H = 10
CLIP = 5.0

M13_FEATURES = ["fam", "strength", "vol_ratio", "gap", "pead_z", "pead_av", "mom21", "mom63", "mom126",
                "mom252", "vol21", "vol63", "dist52", "size", "spy_mom21", "spy_vol21", "spy_on"]
M15_FEATURES = ["fam", "days_held", "ret_entry", "dd_peak", "dd_sig", "mom5", "mom21", "mom63", "vol21",
                "dist52", "spy_mom21", "spy_on"]
PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=200, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, random_state=0, n_jobs=4, verbose=-1)


def ts_us(dates: np.ndarray) -> np.ndarray:
    return dates.astype("datetime64[D]").astype("datetime64[us]").astype(np.int64)


def spy_inputs(E: Panel) -> dict[str, np.ndarray]:
    j = E.col("SPY")
    c = E.close[:, j]
    r = np.full(len(c), np.nan)
    r[1:] = c[1:] / c[:-1] - 1
    mom21 = np.full(len(c), np.nan)
    mom21[21:] = c[21:] / c[:-21] - 1
    vol21 = bk._roll_std(r[:, None], 21, 17)[:, 0]
    return {"mom21": mom21, "vol21": vol21, "on": bk.spy_regime(E).astype(float), "fill": E.fill()[:, j]}


def fwd_log(F: np.ndarray, h: int) -> np.ndarray:
    """log(F[t+1+h] / F[t+1]): from the next fill over h trading days (NaN past the data)."""
    out = np.full(F.shape, np.nan)
    if F.shape[0] > h + 1:
        with np.errstate(invalid="ignore", divide="ignore"):
            out[:F.shape[0] - 1 - h] = np.log(F[1 + h:] / F[1:F.shape[0] - h])
    return out


def _clip(z: np.ndarray) -> np.ndarray:
    return np.where(np.isfinite(z), np.clip(z, -CLIP, CLIP), np.nan)


def candidate_signals(S: Panel, X: bk.Inputs, pd: bk.Pead | None) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """The loosest variant of each event family (the rows M13 learns from)."""
    out = {"A1": bk.breakout(S, X, 20, 1.5), "A2": bk.gap_go(S, X, 0.02)}
    if pd is not None:
        out["A3"] = bk.pead(S, X, pd, 1.0, False)
    return out


def m13_rows(S: Panel, E: Panel, pd: bk.Pead | None) -> pl.DataFrame:
    X = bk.inputs(S)
    sp = spy_inputs(E)
    F = S.fill()
    y_name = fwd_log(F, M13_H)
    y_spy = fwd_log(sp["fill"][:, None], M13_H)[:, 0]
    with np.errstate(invalid="ignore", divide="ignore"):
        target = _clip((y_name - y_spy[:, None]) / (X.sig63 * math.sqrt(M13_H)))
        vol_ratio = np.where(S.traded, S.dv, np.nan) / X.dv50
        gap = S.open / bk._shift(X.c) - 1
        dist52 = X.c / X.hi_incl(bk.HISTORY) - 1
        size = np.log(bk.er._roll_mean(np.where(S.traded & (S.dv > 0), S.dv, np.nan), 63, 50))
    ts = ts_us(S.dates)
    frames = []
    for k, (fam, (sig, strength)) in enumerate(candidate_signals(S, X, pd).items()):
        tt, jj = np.nonzero(sig)
        if tt.size == 0:
            continue
        cols = {
            "ts_us": ts[tt], "symbol": [f"{S.names[j]}|{fam}" for j in jj], "t": tt, "j": jj,
            "fam": np.full(tt.size, float(FAMILIES.index(fam))), "strength": strength[tt, jj],
            "vol_ratio": vol_ratio[tt, jj], "gap": gap[tt, jj],
            "pead_z": pd.z[tt, jj] if pd is not None else np.full(tt.size, np.nan),
            "pead_av": pd.av[tt, jj] if pd is not None else np.full(tt.size, np.nan),
            "mom21": X.mom(21)[tt, jj], "mom63": X.mom(63)[tt, jj], "mom126": X.mom(126)[tt, jj],
            "mom252": X.mom(252)[tt, jj], "vol21": X.sig21[tt, jj], "vol63": X.sig63[tt, jj],
            "dist52": dist52[tt, jj], "size": size[tt, jj], "spy_mom21": sp["mom21"][tt],
            "spy_vol21": sp["vol21"][tt], "spy_on": sp["on"][tt], "target": target[tt, jj],
        }
        frames.append(pl.DataFrame(cols))
    if not frames:
        return pl.DataFrame()
    out = pl.concat(frames, how="vertical_relaxed")
    out = out.with_columns(pl.when(pl.col("target").is_nan()).then(None).otherwise(pl.col("target")).alias("target"))
    for f in M13_FEATURES:
        out = out.with_columns(pl.col(f).cast(pl.Float64).fill_nan(None))
    return out.sort(["ts_us", "symbol"])


def held_features(S: Panel, E: Panel, t: int, js: np.ndarray, entries: np.ndarray, pxs: np.ndarray,
                  peaks: np.ndarray, fam: float) -> np.ndarray:
    """(n, len(M15_FEATURES)) for positions held after the close of t."""
    X = bk.inputs(S)
    sp = S.extra.get("spy_inputs")
    if sp is None:
        sp = S.extra["spy_inputs"] = spy_inputs(E)
    if "dist52" not in S.extra:
        with np.errstate(invalid="ignore", divide="ignore"):
            S.extra["dist52"] = X.c / X.hi_incl(bk.HISTORY) - 1
    c = X.c[t, js]
    s21 = X.sig21[t, js]
    with np.errstate(invalid="ignore", divide="ignore"):
        ret_entry = np.log(c / pxs)
        dd = np.log(c / peaks)
        dd_sig = dd / s21
    n = len(js)
    return np.column_stack([np.full(n, fam), (t - entries + 1).astype(float), ret_entry, dd, dd_sig,
                            X.mom(5)[t, js], X.mom(21)[t, js], X.mom(63)[t, js], s21, S.extra["dist52"][t, js],
                            np.full(n, sp["mom21"][t]), np.full(n, sp["on"][t])])


def m15_rows(S: Panel, E: Panel, held: dict[str, list]) -> pl.DataFrame:
    """held: family -> Run.held of that family's pick with its base exit."""
    X = bk.inputs(S)
    F = S.fill()
    with np.errstate(invalid="ignore", divide="ignore"):
        target = _clip(fwd_log(F, M15_H) / (X.sig21 * math.sqrt(M15_H)))
    ts = ts_us(S.dates)
    frames = []
    for fam, rows in held.items():
        if not rows:
            continue
        a = np.array(rows, dtype=float)
        tt, jj = a[:, 0].astype(int), a[:, 1].astype(int)
        feats = np.full((len(tt), len(M15_FEATURES)), np.nan)
        for t in np.unique(tt):
            k = tt == t
            feats[k] = held_features(S, E, int(t), jj[k], a[k, 2], a[k, 3], a[k, 4], float(FAMILIES.index(fam)))
        d = {"ts_us": ts[tt], "symbol": [f"{S.names[j]}|{fam}" for j in jj], "t": tt, "j": jj,
             **{f: feats[:, i] for i, f in enumerate(M15_FEATURES)}, "target": target[tt, jj]}
        frames.append(pl.DataFrame(d))
    if not frames:
        return pl.DataFrame()
    out = pl.concat(frames, how="vertical_relaxed")
    out = out.with_columns(pl.when(pl.col("target").is_nan()).then(None).otherwise(pl.col("target")).alias("target"))
    for f in M15_FEATURES:
        out = out.with_columns(pl.col(f).cast(pl.Float64).fill_nan(None))
    return out.unique(["ts_us", "symbol"], keep="first").sort(["ts_us", "symbol"])


# ---------------------------------------------------------------------------
# Shared model functions (M13, M14, M15 are LightGBM regressions of a z-scored return)
# ---------------------------------------------------------------------------

def fit_lgb(frame: pl.DataFrame, features: list[str], params: dict | None = None) -> dict:
    import lightgbm as lgb
    X = frame.select(features).fill_null(np.nan).to_numpy().astype(np.float64)
    y = frame["target"].to_numpy().astype(float)
    fam = frame["fam"].to_numpy().astype(float) if "fam" in frame.columns else np.zeros(len(y))
    ok = np.isfinite(y)
    m = lgb.LGBMRegressor(**(params or PARAMS)).fit(X[ok], y[ok])
    base = {float(f): float(np.mean(y[ok & (fam == f)])) for f in np.unique(fam[ok])}
    return {"model": m.booster_, "base": base, "mean": float(np.mean(y[ok])),
            "importance": dict(zip(features, m.booster_.feature_importance("gain").tolist()))}


def predict_lgb(fitted: dict, frame: pl.DataFrame, features: list[str]) -> np.ndarray:
    return fitted["model"].predict(frame.select(features).fill_null(np.nan).to_numpy().astype(np.float64))


def baseline_mean(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    if "fam" in frame.columns:
        fam = frame["fam"].fill_null(np.nan).to_numpy().astype(float)
        return np.array([fitted["base"].get(float(f), fitted["mean"]) for f in fam])
    return np.full(frame.height, fitted["mean"])


def evaluate_keep(mod, panel: pl.DataFrame) -> tuple[dict, list[tuple[int, int, dict]]]:
    """core.evaluate (the zoo's purged walk-forward and gate) on `panel`, also keeping each
    fold's fitted model: [(test from us, test to us, fitted)] in time order. The last fit
    core.evaluate makes (on every known row) is not a fold and is left out."""
    from types import SimpleNamespace

    from ..models import core
    fits: list[dict] = []

    def fit(frame):
        f = mod.fit(frame)
        fits.append(f)
        return f

    proxy = SimpleNamespace(SPEC=mod.SPEC, fit=fit, predict=mod.predict, baseline=mod.baseline, loss=mod.loss)
    panel = panel.sort(["ts_us", "symbol"])
    ev = core.evaluate(proxy, panel)
    ts = panel["ts_us"].to_numpy()
    y = panel["target"].fill_null(np.nan).to_numpy().astype(float)
    known = np.isfinite(y)
    folds = []
    k = 0
    for f in core.folds_for(mod.SPEC, ts, known):
        tr, te = f.train & known, f.test & known
        if tr.sum() < mod.SPEC.min_train or te.sum() == 0:
            continue
        lo = int(ts[f.test].min())
        hi = int(ts[f.test].max())
        folds.append((lo, hi, fits[k]))
        k += 1
    # Contiguous windows: a day between one fold's last row and the next fold's first row
    # belongs to the earlier fold (whose model saw nothing after its own quarter began).
    folds = [(lo, folds[i + 1][0] - 1 if i + 1 < len(folds) else hi, f) for i, (lo, hi, f) in enumerate(folds)]
    return ev, folds


def fold_for(folds: list[tuple[int, int, dict]], t_us: int) -> dict | None:
    """The fold model whose test window holds t_us (None before the first)."""
    for lo, hi, f in folds:
        if lo <= t_us <= hi:
            return f
    if folds and t_us > folds[-1][1]:
        return folds[-1][2]
    return None


def importance_stability(imps: list[dict]) -> dict:
    """Spearman correlation of each fit's gain ranks with the previous fit's."""
    from scipy import stats
    rs = []
    for a, b in zip(imps[:-1], imps[1:]):
        keys = sorted(set(a) & set(b))
        va, vb = [a[k] for k in keys], [b[k] for k in keys]
        if len(keys) > 2 and np.std(va) > 0 and np.std(vb) > 0:
            rs.append(float(stats.spearmanr(va, vb)[0]))
    if not rs:
        return {"fits": len(imps), "mean": None, "min": None, "stable": None}
    mean_gain = {k: float(np.mean([d.get(k, 0.0) for d in imps])) for k in imps[0]}
    tot = sum(mean_gain.values()) or 1.0
    return {"fits": len(imps), "mean": float(np.mean(rs)), "min": float(np.min(rs)), "stable": bool(np.mean(rs) >= 0.5),
            "mean_gain_share": {k: v / tot for k, v in sorted(mean_gain.items(), key=lambda kv: -kv[1])}}


def rank_ic(pred: np.ndarray, y: np.ndarray, ts: np.ndarray) -> dict:
    """Mean per-day Spearman IC (days with at least 5 rows) and the pooled Spearman."""
    from scipy import stats
    ok = np.isfinite(pred) & np.isfinite(y)
    pooled = float(stats.spearmanr(pred[ok], y[ok])[0]) if ok.sum() > 30 else float("nan")
    fr = pl.DataFrame({"t": ts[ok], "p": pred[ok], "y": y[ok]})
    ics = []
    for _, g in fr.group_by("t"):
        if g.height >= 5 and g["p"].std() > 0 and g["y"].std() > 0:
            ics.append(stats.spearmanr(g["p"].to_numpy(), g["y"].to_numpy())[0])
    ics = np.array([x for x in ics if np.isfinite(x)])
    return {"pooled": pooled, "daily_mean": float(ics.mean()) if ics.size else float("nan"),
            "days": int(ics.size), "t": float(ics.mean() / ics.std(ddof=1) * math.sqrt(ics.size)) if ics.size > 2 else float("nan")}
