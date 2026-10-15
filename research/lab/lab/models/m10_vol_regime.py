"""M10: regime-aware daily volatility.

M6 (vol_daily) found that LightGBM beats HAR for the next day's realised
variance by about 9 % QLIKE, but that sizing books with it did worse than the
30-day mean (RW30). M10 asks the narrower question whether knowing the market
regime makes the daily forecast better: the M6 inputs plus BTC's distance to
its 200-day mean, breadth (share of coins above their 50-day mean), where
market-wide volatility sits within its last year, and the cross-sectional
dispersion of returns.

Target: next UTC day's realised variance (sum of squared 1-minute log
returns). Loss: QLIKE. Baseline: HAR (log RV on log 1, 7, 30-day RV, refit on
each training window). Gate: lower QLIKE than HAR with DM p < 0.05, and lower
than the same LightGBM without the regime inputs (otherwise the regime part
adds nothing and M6 is the model). RW30, what the books use, is reported too.
Used by no book: M6 showed a better forecast does not size better. It is the
candidate input for a future sizing study, nothing more.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl

from . import core, daily
from .core import Spec

EPS = 1e-12
BASE_FEATURES = ["h1", "h7", "h30", "h90", "h1_l1", "h1_l2", "dn_share7", "jump7", "ret1", "ret7", "ret30",
                 "absret1", "park1", "qv_z", "tr_z", "dist_hi30", "btc_h1", "btc_h7", "mkt_h1", "mkt_h7",
                 "rel_h7", "dow_next", "fund1", "fund7", "oi_chg1", "oi_chg7"]
REGIME = ["btc_trend200", "breadth50", "mkt_vol_pct", "xs_disp", "ma200_gap"]
FEATURES = BASE_FEATURES + REGIME
HAR = ["h1", "h7", "h30"]
PARAMS = dict(n_estimators=400, learning_rate=0.03, num_leaves=15, min_child_samples=300, subsample=0.8,
              subsample_freq=1, colsample_bytree=0.8, reg_lambda=5.0, n_jobs=4, verbose=-1)

SPEC = Spec(
    code="M10", name="m10_vol_regime", title="Regime-aware daily volatility",
    target="next UTC day's realised variance per coin (sum of squared 1-minute log returns)",
    features=FEATURES, horizon="next UTC day", horizon_days=1,
    universe="the 20 recorded coins", metric="qlike",
    baseline="HAR on log 1, 7 and 30-day RV, refit per window (RW30, what the books use, reported too)",
    every_days=7, weekday=6, margin=0.01, relative=True, first_test="2021-01-01", min_rows=1000, min_days=21,
    min_train=3000, calendar=("dow_next",),
    use_rule="No book: M6 showed a better daily forecast sizes worse than RW30. Input for a future, "
             "pre-registered sizing study only.",
    results="model_zoo.md",
)


def coin_with_perp(base: str) -> pl.DataFrame:
    from ..experiments.vol_daily import coin_daily, perp_feats
    f = coin_daily(base)
    if f.is_empty():
        return f
    pf = perp_feats(base)
    if pf is not None:
        return f.join(pf, on="day", how="left")
    return f.with_columns(**{c: pl.lit(None, pl.Float64) for c in ("fund1", "fund7", "oi_chg1", "oi_chg7")})


def load() -> pl.DataFrame:
    from ..data import UNIVERSE
    return panel_from(daily.enrich(daily.coin_frames(UNIVERSE, coin_with_perp)))


def panel_from(p: pl.DataFrame) -> pl.DataFrame:
    p = p.with_columns(target=pl.when(pl.col("y1") > 0).then(pl.col("y1")).otherwise(None))
    ok = pl.all_horizontal(pl.col(HAR).is_not_null())
    return p.filter(ok)


def _X(frame: pl.DataFrame, cols: list[str]) -> np.ndarray:
    return frame.select(cols).fill_null(np.nan).to_numpy().astype(np.float64)


def _lgb(frame: pl.DataFrame, cols: list[str]):
    import lightgbm as lgb
    ly = np.log(frame["target"].to_numpy().astype(float) + EPS)
    X = _X(frame, cols)
    m = lgb.LGBMRegressor(**PARAMS).fit(X, ly).booster_
    return m, float(np.var(ly - m.predict(X)))


def fit(frame: pl.DataFrame) -> dict:
    m, rv = _lgb(frame, FEATURES)
    m0, rv0 = _lgb(frame, BASE_FEATURES)
    ly = np.log(frame["target"].to_numpy().astype(float) + EPS)
    Xh = np.column_stack([np.ones(frame.height), _X(frame, HAR)])
    beta = np.linalg.lstsq(Xh, ly, rcond=None)[0]
    return {"lgb": m, "resid": rv, "lgb0": m0, "resid0": rv0, "har": [float(b) for b in beta],
            "har_resid": float(np.var(ly - Xh @ beta))}


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return np.exp(fitted["lgb"].predict(_X(frame, FEATURES)) + fitted["resid"] / 2)


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    b = np.asarray(fitted["har"])
    return np.exp(b[0] + _X(frame, HAR) @ b[1:] + fitted["har_resid"] / 2)


def loss(y, f):
    return core.qlike(y, f)


def side(fitted: dict, frame: pl.DataFrame) -> dict[str, np.ndarray]:
    out = {"rw30": frame["rw30"].to_numpy().astype(float)}
    if fitted.get("lgb0") is not None:
        out["noregime"] = np.exp(fitted["lgb0"].predict(_X(frame, BASE_FEATURES)) + fitted["resid0"] / 2)
    return out


def gate_extra(ev: dict) -> tuple[bool, str]:
    from ..metrics import diebold_mariano
    h = ev["holdout"].filter(pl.col("x_noregime").is_not_null())
    y = h["target"].to_numpy().astype(float)
    lm, l0 = loss(y, h["challenger"].to_numpy()), loss(y, h["x_noregime"].to_numpy())
    ts = h["ts_us"].to_numpy()
    _, p = diebold_mariano(core.per_period(ts, lm), core.per_period(ts, l0), lag=1)
    ok = bool(lm.mean() < l0.mean() and p < core.GATE_P)
    return ok, (f"against the same model without regime inputs {lm.mean():.4f} vs {l0.mean():.4f}, DM p {p:.3g}"
                + ("" if ok else ": the regime inputs do not add enough"))


def extra(fitted: dict, panel: pl.DataFrame, ev: dict) -> dict:
    h = ev["holdout"]
    if h.is_empty():
        return {}
    y = h["target"].to_numpy().astype(float)
    ok = np.isfinite(h["x_rw30"].fill_null(np.nan).to_numpy())
    q = {k: float(np.mean(loss(y[ok], h[c].to_numpy()[ok])))
         for k, c in (("model", "challenger"), ("har", "baseline_pred"), ("rw30", "x_rw30"), ("no_regime", "x_noregime"))}
    imp = fitted["lgb"].feature_importance("gain")
    top = sorted(zip(FEATURES, imp), key=lambda t: -t[1])[:8]
    # By regime: BTC above or below its 200-day mean.
    up = h["btc_trend200"].fill_null(np.nan).to_numpy() > 0
    by = {}
    for name, m in (("btc_above_200d", up), ("btc_below_200d", ~up)):
        mm = m & ok
        if mm.sum() >= 100:
            by[name] = {"rows": int(mm.sum()), "model": float(np.mean(loss(y[mm], h["challenger"].to_numpy()[mm]))),
                        "har": float(np.mean(loss(y[mm], h["baseline_pred"].to_numpy()[mm])))}
    return core.finite({"qlike_same_rows": q, "by_regime": by,
                        "top_features": [{"feature": f, "gain_share": float(g / max(imp.sum(), 1e-12))} for f, g in top]})


def save(fitted: dict, folder: Path) -> None:
    core.lgb_dump(fitted["lgb"], folder / "model.json")
    core.lgb_dump(fitted["lgb0"], folder / "noregime.json")
    (folder / "params.json").write_text(json.dumps({k: fitted[k] for k in ("resid", "resid0", "har", "har_resid")}),
                                        encoding="utf-8")


def restore(folder: Path) -> dict:
    p = json.loads((folder / "params.json").read_text(encoding="utf-8"))
    return {"lgb": core.lgb_load(folder / "model.json"), "lgb0": core.lgb_load(folder / "noregime.json"), **p}
