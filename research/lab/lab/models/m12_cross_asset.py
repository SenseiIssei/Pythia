"""M12: the BTC and US equity correlation regime.

Data: BTC-USD's and SPY's daily closes from Yahoo's chart API (BTC from
September 2014, its UTC day close; SPY adjusted for dividends), on the days
SPY trades, cached for a day. Without Yahoo and without a cache, BTC falls
back to the recorder's 1-minute bars (from 2020 only). The day in progress is
dropped. BTC's close is three to four hours after SPY's, which is fine for
daily returns: every input is known at the end of day t and the target
starts with day t+1's returns.

Target: the correlation of daily BTC and SPY log returns over the next 20 SPY
trading days, Fisher-transformed (atanh), so errors in a calm and a coupled
market count alike. Inputs: the correlation over the last 20, 60 and 120 days
(atanh), its change over a month, both volatilities and their ratio, SPY's
drawdown from its one-year high, both trends against a 200-day mean.

Model: ridge regression on standardised inputs (about 2,900 overlapping
rows; a tree would only memorise them), fitted on the change from the last
60 days' correlation rather than its level (the level moved from about zero
before 2020 to coupled after; a ridge on the level kept pulling forecasts to
the old regime). Baseline: the last 60 days' correlation, carried forward.
Gate: lower squared error than the baseline with DM p < 0.05 (lag 20 for the
overlap). The regime the page shows: coupled (above 0.3), decoupled (below
0.1), mixed in between, from the model only if it passed its gate and from
the baseline otherwise. On real data (October 2026) neither ridge beats the
baseline (results/model_zoo.md), so the regime shown is the last 60 days'.
Used by no book: information for the owner on whether BTC is trading as a
risk asset; any use (e.g. leaving the equity and coin books' combined risk
alone when coupled) needs its own study.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import polars as pl

from . import core
from .core import DataUnavailable, Spec

FEATURES = ["z20", "z60", "z120", "dz60", "btc_vol20", "spy_vol20", "vol_ratio", "spy_dd252", "btc_trend",
            "spy_trend"]
WINDOW = 20
LAMBDA = 5.0
ANCHOR = "z60"            # the model forecasts the change from this, see fit()
COUPLED, DECOUPLED = 0.3, 0.1
YAHOO_MAX_AGE_S = 20 * 3600

SPEC = Spec(
    code="M12", name="m12_cross_asset", title="BTC vs US equities correlation regime",
    target="correlation of daily BTC and SPY returns over the next 20 SPY trading days (atanh)",
    features=FEATURES, horizon="next 20 trading days", horizon_days=28,
    universe="BTC-USD and SPY (Yahoo daily)", metric="mse_z", baseline="the last 60 days' correlation, carried forward",
    every_days=28, margin=0.002, first_test="2020-01-01", folds="quarter", min_rows=60, min_days=60, min_train=300,
    drift_days=120,
    use_rule="No book. Shown to the owner as the regime (coupled, mixed, decoupled); any use needs its own study.",
    results="model_zoo.md",
)


def yahoo_closes(sym: str, fetch=None, cache: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Daily closes from Yahoo's chart API, cached for a day under <data>/models/zoo/_data."""
    from ..experiments import etf_trend
    from ..ops import guard
    from ..data import ROOT
    cache = cache or ROOT / "models" / "zoo" / "_data" / f"{sym}.csv"
    fresh = cache.exists() and time.time() - cache.stat().st_mtime < YAHOO_MAX_AGE_S
    if not fresh:
        try:
            text = (fetch or etf_trend.download_yahoo)(sym)
            etf_trend.parse_stooq(text)
            guard.write_text(cache, text)
        except (etf_trend.DataUnavailable, OSError) as e:
            if not cache.exists():
                raise DataUnavailable(f"{sym} from Yahoo: {e}") from e
    try:
        return etf_trend.parse_stooq(cache.read_text(encoding="utf-8"))
    except etf_trend.DataUnavailable as e:
        raise DataUnavailable(str(e)) from e


def spy_closes(fetch=None, cache: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    return yahoo_closes("SPY", fetch, cache)


def recorder_btc() -> tuple[np.ndarray, np.ndarray]:
    from ..experiments.vol_daily import coin_daily
    f = coin_daily("BTC")
    if f.is_empty():
        raise DataUnavailable("no BTC 1-minute history under <data>/hist/binance_spot/klines_1m")
    f = f.drop_nulls("close")
    return (f["day"].to_numpy() // 86_400_000_000).astype("datetime64[D]"), f["close"].to_numpy().astype(float)


def btc_closes(fetch=None, cache: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    try:
        return yahoo_closes("BTC-USD", fetch, cache)
    except DataUnavailable:
        return recorder_btc()


def complete_days(series: tuple[np.ndarray, np.ndarray], today: np.datetime64 | None = None):
    """Only days that are over (UTC): Yahoo includes the day in progress."""
    today = today if today is not None else np.datetime64(int(time.time() // 86_400), "D")
    keep = series[0] < today
    return series[0][keep], series[1][keep]


def load() -> pl.DataFrame:
    return panel_from(complete_days(btc_closes()), complete_days(spy_closes()))


def _atanh(c):
    return c.clip(-0.99, 0.99).arctanh()


def panel_from(btc: tuple[np.ndarray, np.ndarray], spy: tuple[np.ndarray, np.ndarray]) -> pl.DataFrame:
    b = pl.DataFrame({"date": btc[0], "btc": btc[1]})
    s = pl.DataFrame({"date": spy[0], "spy": spy[1]})
    d = s.join(b, on="date", how="inner").sort("date")
    if d.height < 300:
        raise DataUnavailable(f"only {d.height} days with both a BTC and a SPY close")
    rb, rs = pl.col("btc").log().diff(), pl.col("spy").log().diff()
    d = d.with_columns(rb=rb, rs=rs)
    corr = lambda w: pl.rolling_corr(pl.col("rb"), pl.col("rs"), window_size=w, min_samples=int(w * 0.8))  # noqa: E731
    d = d.with_columns(
        z20=_atanh(corr(20)), z60=_atanh(corr(60)), z120=_atanh(corr(120)),
        btc_vol20=(pl.col("rb").rolling_std(20) * np.sqrt(252)).log(),
        spy_vol20=(pl.col("rs").rolling_std(20) * np.sqrt(252)).log(),
        spy_dd252=pl.col("spy").log() - pl.col("spy").rolling_max(252, min_samples=120).log(),
        btc_trend=pl.col("btc").log() - pl.col("btc").rolling_mean(200, min_samples=150).log(),
        spy_trend=pl.col("spy").log() - pl.col("spy").rolling_mean(200, min_samples=150).log(),
    ).with_columns(dz60=pl.col("z60") - pl.col("z60").shift(20), vol_ratio=pl.col("btc_vol20") - pl.col("spy_vol20"),
                   target=_atanh(corr(WINDOW)).shift(-WINDOW))
    return (d.with_columns(ts_us=pl.col("date").cast(pl.Datetime("us")).cast(pl.Int64), symbol=pl.lit("BTC-SPY"))
            .filter(pl.col("z60").is_not_null() & pl.col("z120").is_not_null()))


def _X(frame: pl.DataFrame) -> np.ndarray:
    return frame.select(FEATURES).fill_null(np.nan).to_numpy().astype(np.float64)


def fit(frame: pl.DataFrame) -> dict:
    """Ridge on the change from the last 60 days' correlation (anchor), not on its level:
    the level moved from about zero before 2020 to coupled after, and a fitted level
    would pull every forecast towards the old regime."""
    X, y = _X(frame), frame["target"].to_numpy().astype(float)
    y = y - np.nan_to_num(frame[ANCHOR].to_numpy().astype(float))
    mu, sd = np.nanmean(X, 0), np.nanstd(X, 0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.nan_to_num((X - mu) / sd)
    ym = y.mean()
    w = np.linalg.solve(Z.T @ Z + LAMBDA * len(y) / 100 * np.eye(Z.shape[1]), Z.T @ (y - ym))
    return {"mu": mu.tolist(), "sd": sd.tolist(), "w": w.tolist(), "b": float(ym), "anchor": ANCHOR}


def predict(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    Z = np.nan_to_num((_X(frame) - np.asarray(fitted["mu"])) / np.asarray(fitted["sd"]))
    a = fitted.get("anchor")
    base = np.nan_to_num(frame[a].to_numpy().astype(float)) if a else 0.0
    return base + fitted["b"] + Z @ np.asarray(fitted["w"])


def baseline(fitted: dict, frame: pl.DataFrame) -> np.ndarray:
    return frame["z60"].to_numpy().astype(float)


def loss(y, f):
    return core.squared(y, f)


def regime(c: float) -> str:
    return "coupled" if c > COUPLED else "decoupled" if c < DECOUPLED else "mixed"


def extra(fitted: dict, panel: pl.DataFrame, ev: dict) -> dict:
    h = ev["holdout"]
    out = {}
    if not h.is_empty():
        real = np.vectorize(regime)(np.tanh(h["target"].to_numpy()))
        out["regime_hit_model"] = float(np.mean(np.vectorize(regime)(np.tanh(h["challenger"].to_numpy())) == real))
        out["regime_hit_baseline"] = float(np.mean(np.vectorize(regime)(np.tanh(h["baseline_pred"].to_numpy())) == real))
        out["regime_share"] = {k: float(np.mean(real == k)) for k in ("coupled", "mixed", "decoupled")}
    last = panel.filter(pl.col("ts_us") == panel["ts_us"].max())
    if not last.is_empty():
        c = float(np.tanh(predict(fitted, last)[0]))
        c60 = float(np.tanh(last["z60"][0])) if last["z60"][0] is not None else None
        # A model that did not beat its baseline does not get to name the regime.
        use_model = bool((ev.get("gate") or {}).get("passed")) or c60 is None
        out["today"] = {"date": core.iso(int(last["ts_us"][0])), "forecast_corr": c, "corr60": c60,
                        "regime": regime(c if use_model else c60), "regime_from": "model" if use_model else "baseline"}
    out["weights"] = dict(zip(FEATURES, fitted["w"]))
    return core.finite(out)


def save(fitted: dict, folder: Path) -> None:
    (folder / "model.json").write_text(json.dumps({"kind": "ridge", "features": FEATURES, **fitted}), encoding="utf-8")


def restore(folder: Path) -> dict:
    m = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    return {k: m.get(k) for k in ("mu", "sd", "w", "b", "anchor")}


def synthetic(n: int = 2200, seed: int = 0) -> tuple[tuple[np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]:
    """BTC and SPY with a slowly moving true correlation that mean-reverts: the last
    60 days lag it, a model that sees 20, 60 and 120 days should do better."""
    rng = np.random.default_rng(seed)
    dates = np.datetime64("2017-01-02") + np.arange(n)
    rho = np.clip(0.25 + 0.35 * np.sin(np.arange(n) / 90.0), -0.9, 0.9)
    e1, e2 = rng.standard_normal(n), rng.standard_normal(n)
    rs = 0.01 * e1
    rb = 0.035 * (rho * e1 + np.sqrt(1 - rho ** 2) * e2)
    return (dates, 1000 * np.exp(np.cumsum(rb))), (dates, 300 * np.exp(np.cumsum(rs)))
