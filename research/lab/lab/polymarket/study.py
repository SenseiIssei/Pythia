"""The pre-registered Polymarket study (results/polymarket_prereg.md): biases, M-PM1, the paper twin.

    python -m lab.polymarket.study             everything; the panel is cached
    python -m lab.polymarket.study --refresh   rebuild the panel from the resolved set

Writes reports/polymarket_study/latest.{md,json} (and results/polymarket_study.md
with PYTHIA_RESULTS) and the fitted model the daily book uses
(<data>/polymarket/model/: gbm.txt, iso.json, recal.json, meta.json).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone

import numpy as np
import polars as pl

from . import book as B, markets as M, panel as P, store

QUARTER_FIRST = "2024Q1"
TEST_YEARS = (2024, 2025, 2026)
BOOT = 500
GBM_PARAMS = dict(objective="binary", n_estimators=300, learning_rate=0.03, num_leaves=31, min_child_samples=200,
                  colsample_bytree=0.8, subsample=1.0, verbose=-1, random_state=7)
MARGINS = (0.02, 0.03, 0.05)
HIST_MAX_USD = 500.0
MIN_HALF_SPREAD = 0.005
PRIOR_HAND = 1115          # hand trials after X15 with X16 (results/candles.md)
HERE_TRIALS = 16           # 6 historical rule variants, 8 addendum checks, 2 live books
# The addendum's slices of the same test: states whose history price is more likely a real price.
SLICES = {
    "after day one": pl.col("days_since") >= 1.0,
    "price has moved": pl.col("hi") > pl.col("lo"),
    "after day one and moved": (pl.col("days_since") >= 1.0) & (pl.col("hi") > pl.col("lo")),
}
LOSS_TESTS = 4             # recal, gbm, Claude, ensemble against the market
EPS = 0.001


def log(s: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {s}", flush=True)


# ---------------------------------------------------------------- weights

def stratum_weights(mk: pl.DataFrame) -> dict[str, float]:
    """market id -> resolved markets in its stratum / sampled ones with history (reweights to the universe)."""
    strata = store.read_json(store.path("resolved", "strata.json"), {}) or {}
    have = mk.group_by(["_month", "category", "kind"]).len()
    n_have = {(r[0], r[1], r[2]): r[3] for r in have.iter_rows()}
    out = {}
    for r in mk.select("id", "_month", "category", "kind").iter_rows():
        c = (strata.get(r[1]) or {}).get(f"{r[2]}|{r[3]}") or {}
        k = n_have.get((r[1], r[2], r[3]), 1)
        out[str(r[0])] = float(c.get("resolved") or k) / max(k, 1)
    return out


def per_market(df: pl.DataFrame, by: list[str] | None = None) -> np.ndarray:
    """1 / number of states of the same market (in the same slice): each market weighs one."""
    keys = ["market_id"] + (by or [])
    return (1.0 / df.select(pl.len().over(keys)).to_series().to_numpy()).astype(float)


# ---------------------------------------------------------------- statistics

def irls(X: np.ndarray, y: np.ndarray, w: np.ndarray, clusters: np.ndarray | None = None, iters: int = 30,
         ridge: float = 1e-6) -> dict:
    """Weighted logistic regression by Newton steps, with cluster-robust standard errors."""
    beta = np.zeros(X.shape[1])
    for _ in range(iters):
        z = np.clip(X @ beta, -30, 30)
        p = 1 / (1 + np.exp(-z))
        g = X.T @ (w * (y - p)) - ridge * beta
        H = (X * (w * p * (1 - p))[:, None]).T @ X + ridge * np.eye(X.shape[1])
        step = np.linalg.solve(H, g)
        beta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    se = None
    if clusters is not None:
        z = np.clip(X @ beta, -30, 30)
        p = 1 / (1 + np.exp(-z))
        H = (X * (w * p * (1 - p))[:, None]).T @ X + ridge * np.eye(X.shape[1])
        s = X * (w * (y - p))[:, None]
        _, inv = np.unique(clusters, return_inverse=True)
        S = np.zeros((inv.max() + 1, X.shape[1]))
        np.add.at(S, inv, s)
        Hi = np.linalg.inv(H)
        V = Hi @ (S.T @ S) @ Hi
        se = np.sqrt(np.maximum(np.diag(V), 0))
    return {"beta": beta, "se": se}


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def brier(q, y, w):
    return float(np.sum(w * (q - y) ** 2) / np.sum(w))


def logloss(q, y, w):
    q = np.clip(q, EPS, 1 - EPS)
    return float(-np.sum(w * (y * np.log(q) + (1 - y) * np.log(1 - q))) / np.sum(w))


def event_boot(values: np.ndarray, w: np.ndarray, events: np.ndarray, draws: int = BOOT, seed: int = 3,
               denom: np.ndarray | None = None) -> tuple[float, float, float]:
    """Weighted mean of `values` with a 95 % band from resampling whole events."""
    _, inv = np.unique(events, return_inverse=True)
    E = inv.max() + 1
    num = np.bincount(inv, weights=w * values, minlength=E)
    den = np.bincount(inv, weights=w if denom is None else denom, minlength=E)
    rng = np.random.default_rng(seed)
    c = rng.multinomial(E, np.full(E, 1 / E), size=draws).astype(float)
    m = (c @ num) / np.maximum(c @ den, 1e-12)
    return float(num.sum() / max(den.sum(), 1e-12)), float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))


# ---------------------------------------------------------------- the panel

def panel(refresh: bool = False) -> tuple[pl.DataFrame, pl.DataFrame]:
    mk, hist = P.load_resolved()
    if mk is None or hist is None:
        raise SystemExit("no resolved set: run python -m lab.polymarket.collect --history first")
    cache = store.path("cache", "panel.parquet")
    stamp = f"v{P.VERSION}-{mk.height}-{hist.height}"
    meta = store.read_json(store.path("cache", "panel.json"), {}) or {}
    if not refresh and cache.exists() and meta.get("stamp") == stamp:
        return pl.read_parquet(cache), mk
    log(f"building the panel from {mk.height:,} markets and {hist.height:,} history points")
    df = P.build(mk, hist, log=log)
    store.write_parquet(df, cache)
    store.write_json(store.path("cache", "panel.json"), {"stamp": stamp, "states": df.height})
    return df, mk


# ---------------------------------------------------------------- B. the biases

def calib_table(df: pl.DataFrame, w: np.ndarray) -> list[dict]:
    p, y, ev = df["p"].to_numpy(), df["y"].to_numpy(), df["event_id"].to_numpy()
    b = P.price_bucket(p)
    rows = []
    for i, lab in enumerate(P.PRICE_LABELS):
        k = b == i
        if k.sum() < 30:
            continue
        rate, lo, hi = event_boot(y[k], w[k], ev[k], seed=i)
        mp = float(np.sum(w[k] * p[k]) / np.sum(w[k]))
        rows.append({"bucket": lab, "markets": int(df.filter(pl.Series(k))["market_id"].n_unique()),
                     "price": mp, "rate": rate, "lo": lo, "hi": hi, "diff": rate - mp})
    return rows


def line(df: pl.DataFrame, w: np.ndarray, extra: list[str] | None = None) -> dict:
    """logit P(win) = a + b * logit(p) (+ extra), with event-clustered standard errors."""
    cols = [np.ones(df.height), df["logit_p"].to_numpy()]
    for c in extra or []:
        v = df[c].to_numpy().astype(float)
        cols.append(np.nan_to_num(v))
    X = np.column_stack(cols)
    r = irls(X, df["y"].to_numpy().astype(float), w, df["event_id"].to_numpy())
    out = {"a": float(r["beta"][0]), "b": float(r["beta"][1]), "a_se": float(r["se"][0]),
           "b_se": float(r["se"][1]), "states": df.height, "markets": df["market_id"].n_unique()}
    for j, c in enumerate(extra or []):
        out[c] = float(r["beta"][2 + j])
        out[f"{c}_se"] = float(r["se"][2 + j])
    return out


def biases(df: pl.DataFrame, sw: dict[str, float]) -> dict:
    strat = np.array([sw.get(str(m), 1.0) for m in df["market_id"].to_list()])
    out: dict = {}
    w = per_market(df) * strat
    out["B1_buckets"] = calib_table(df, w)
    out["B1_line"] = line(df, w)
    hb = P.horizon_bucket(df["days_to_end"].to_numpy())
    d2 = df.with_columns(pl.Series("hb", hb))
    out["B2"] = []
    for i, lab in enumerate(P.HORIZON_LABELS):
        s = d2.filter(pl.col("hb") == i)
        if s.height < 200:
            continue
        ws = per_market(s) * np.array([sw.get(str(m), 1.0) for m in s["market_id"].to_list()])
        r = line(s, ws)
        r.update(horizon=lab, brier_market=brier(s["p"].to_numpy(), s["y"].to_numpy(), ws))
        out["B2"].append(r)
    out["B3"] = []
    for (cat, kind), s in df.group_by(["category", "kind"]):
        if s["market_id"].n_unique() < 100:
            continue
        ws = per_market(s) * np.array([sw.get(str(m), 1.0) for m in s["market_id"].to_list()])
        r = line(s, ws)
        r.update(category=cat, kind=kind, brier_market=brier(s["p"].to_numpy(), s["y"].to_numpy(), ws),
                 buckets=calib_table(s, ws))
        out["B3"].append(r)
    out["B3"].sort(key=lambda r: (r["category"], r["kind"]))
    # B4: final volume terciles (hindsight, descriptive)
    vol = df["volume"].to_numpy()
    mv = df.group_by("market_id").agg(pl.col("volume").first())
    qs = np.quantile(mv["volume"].to_numpy(), [1 / 3, 2 / 3])
    terc = np.searchsorted(qs, vol, side="right")
    out["B4_volume"] = []
    for i, lab in enumerate(["low", "mid", "high"]):
        s = df.filter(pl.Series(terc == i))
        ws = per_market(s) * np.array([sw.get(str(m), 1.0) for m in s["market_id"].to_list()])
        r = line(s, ws)
        r.update(tercile=lab, vol_from=float([0, qs[0], qs[1]][i]),
                 brier_market=brier(s["p"].to_numpy(), s["y"].to_numpy(), ws))
        out["B4_volume"].append(r)
    # B5: does the 7-day change add to logit(p)?
    s = df.filter(pl.col("chg_7d").is_not_nan() & pl.col("chg_7d").is_finite())
    ws = per_market(s) * np.array([sw.get(str(m), 1.0) for m in s["market_id"].to_list()])
    out["B5"] = line(s, ws, ["chg_7d"])
    s1 = df.filter(pl.col("chg_1d").is_not_nan() & pl.col("chg_1d").is_finite())
    ws1 = per_market(s1) * np.array([sw.get(str(m), 1.0) for m in s1["market_id"].to_list()])
    out["B5_1d"] = line(s1, ws1, ["chg_1d"])
    return out


# ---------------------------------------------------------------- M. the models

def recal_design(df: pl.DataFrame) -> np.ndarray:
    hb = P.horizon_bucket(df["days_to_end"].to_numpy())
    lp = df["logit_p"].to_numpy()
    cols = []
    for i in range(len(P.HORIZON_LABELS)):
        k = (hb == i).astype(float)
        cols += [k, k * lp]
    cat = df["category"].to_list()
    for c in P.CAT_ORDER[1:]:
        cols.append(np.array([1.0 if x == c else 0.0 for x in cat]))
    return np.column_stack(cols)


def fit_recal(tr: pl.DataFrame) -> np.ndarray:
    X = recal_design(tr)
    return irls(X, tr["y"].to_numpy().astype(float), per_market(tr), ridge=1.0)["beta"]


def X_of(df: pl.DataFrame) -> np.ndarray:
    return df.select(P.FEATURES).to_numpy().astype(float)


def fit_gbm(tr: pl.DataFrame):
    import lightgbm as lgb
    from sklearn.isotonic import IsotonicRegression
    tr = tr.sort("t_s")
    n = tr.height
    cut = int(n * 0.8)
    fit, cal = tr[:cut], tr[cut:]
    m = lgb.LGBMClassifier(**GBM_PARAMS)
    m.fit(X_of(fit), fit["y"].to_numpy(), sample_weight=per_market(fit))
    raw = m.predict_proba(X_of(cal))[:, 1]
    iso = IsotonicRegression(y_min=EPS, y_max=1 - EPS, out_of_bounds="clip")
    iso.fit(raw, cal["y"].to_numpy(), sample_weight=per_market(cal))
    return m, iso


def predict_gbm(model, df: pl.DataFrame) -> np.ndarray:
    m, iso = model
    return np.clip(iso.predict(m.predict_proba(X_of(df))[:, 1]), EPS, 1 - EPS)


def quarters(df: pl.DataFrame) -> list[tuple[str, int, int]]:
    out = []
    qs = sorted(q for q in df["quarter"].unique().to_list() if q >= QUARTER_FIRST)
    for q in qs:
        y, k = int(q[:4]), int(q[-1])
        a = int(datetime(y, 3 * k - 2, 1, tzinfo=timezone.utc).timestamp())
        b = int(datetime(y + (k == 4), 1 if k == 4 else 3 * k + 1, 1, tzinfo=timezone.utc).timestamp())
        out.append((q, a, b))
    return out


def walk_forward(df: pl.DataFrame) -> pl.DataFrame:
    parts = []
    for q, a, b in quarters(df):
        tr = df.filter(pl.col("close_s") < a)
        te = df.filter((pl.col("t_s") >= a) & (pl.col("t_s") < b))
        if tr.height < 5000 or te.height < 100:
            log(f"  {q}: skipped (train {tr.height}, test {te.height})")
            continue
        t0 = time.time()
        beta = fit_recal(tr)
        q_recal = sigmoid(recal_design(te) @ beta)
        g = fit_gbm(tr)
        q_gbm = predict_gbm(g, te)
        parts.append(te.with_columns(pl.Series("q_recal", q_recal), pl.Series("q_gbm", q_gbm)))
        log(f"  {q}: train {tr.height:,} states of {tr['market_id'].n_unique():,} markets, test {te.height:,}, "
            f"{time.time() - t0:.0f} s")
    return pl.concat(parts) if parts else pl.DataFrame()


def score(oos: pl.DataFrame, col: str) -> dict:
    y, p, q = oos["y"].to_numpy(), oos["p"].to_numpy(), oos[col].to_numpy()
    w = per_market(oos)
    ev = oos["event_id"].to_numpy()
    lm = (np.clip(p, EPS, 1 - EPS) - y) ** 2
    lq = (q - y) ** 2
    d, lo, hi = event_boot(lm - lq, w, ev, seed=11)
    llm = -(y * np.log(np.clip(p, EPS, 1 - EPS)) + (1 - y) * np.log(1 - np.clip(p, EPS, 1 - EPS)))
    llq = -(y * np.log(np.clip(q, EPS, 1 - EPS)) + (1 - y) * np.log(1 - np.clip(q, EPS, 1 - EPS)))
    dl, dllo, dlhi = event_boot(llm - llq, w, ev, seed=12)
    # one-sided p of the Brier difference from the bootstrap
    _, inv = np.unique(ev, return_inverse=True)
    E = inv.max() + 1
    num = np.bincount(inv, weights=w * (lm - lq), minlength=E)
    den = np.bincount(inv, weights=w, minlength=E)
    rng = np.random.default_rng(13)
    c = rng.multinomial(E, np.full(E, 1 / E), size=2000).astype(float)
    dist = (c @ num) / (c @ den)
    pval = float(np.mean(dist <= 0))
    out = {"model": col, "states": oos.height, "markets": oos["market_id"].n_unique(),
           "brier_market": brier(np.clip(p, EPS, 1 - EPS), y, w), "brier_model": brier(q, y, w),
           "logloss_market": logloss(p, y, w), "logloss_model": logloss(q, y, w),
           "brier_diff": d, "brier_diff_lo": lo, "brier_diff_hi": hi, "logloss_diff": dl,
           "logloss_diff_lo": dllo, "logloss_diff_hi": dlhi, "p_one_sided": pval}
    out["skill"] = 1 - out["brier_model"] / out["brier_market"]
    by_year, by_cat, by_h = {}, {}, {}
    for yv in TEST_YEARS:
        s = oos.filter(pl.col("year") == yv)
        if s.height:
            ws = per_market(s)
            by_year[str(yv)] = {"market": brier(np.clip(s["p"].to_numpy(), EPS, 1 - EPS), s["y"].to_numpy(), ws),
                                "model": brier(s[col].to_numpy(), s["y"].to_numpy(), ws),
                                "markets": s["market_id"].n_unique()}
    for (cat,), s in oos.group_by(["category"]):
        ws = per_market(s)
        by_cat[cat] = {"market": brier(np.clip(s["p"].to_numpy(), EPS, 1 - EPS), s["y"].to_numpy(), ws),
                       "model": brier(s[col].to_numpy(), s["y"].to_numpy(), ws), "markets": s["market_id"].n_unique()}
    hb = P.horizon_bucket(oos["days_to_end"].to_numpy())
    for i, lab in enumerate(P.HORIZON_LABELS):
        s = oos.filter(pl.Series(hb == i))
        if s.height:
            ws = per_market(s)
            by_h[lab] = {"market": brier(np.clip(s["p"].to_numpy(), EPS, 1 - EPS), s["y"].to_numpy(), ws),
                         "model": brier(s[col].to_numpy(), s["y"].to_numpy(), ws), "markets": s["market_id"].n_unique()}
    out.update(by_year=by_year, by_category=dict(sorted(by_cat.items())), by_horizon=by_h)
    years_better = sum(1 for v in by_year.values() if v["model"] < v["market"])
    big = {k: v for k, v in by_cat.items() if v["markets"] >= 300}
    cats_better = sum(1 for v in big.values() if v["model"] < v["market"])
    g = {"lower_brier": out["brier_model"] < out["brier_market"],
         "lower_logloss": out["logloss_model"] < out["logloss_market"],
         "band_above_zero": lo > 0,
         "two_of_three_years": years_better >= 2,
         "half_of_categories": bool(big) and cats_better * 2 >= len(big)}
    out.update(gates=g, years_better=years_better, cats_better=cats_better, cats_big=len(big),
               passes=all(g.values()))
    return out


def holm(pvals: dict[str, float], m: int = LOSS_TESTS) -> dict[str, float]:
    """Holm-adjusted p over m tests (tests not run yet count as p = 1)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    out, run = {}, 0.0
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


# ---------------------------------------------------------------- P. the historical twin

def half_spreads() -> dict:
    """Median half-spread of the YES side by price bucket and category, from the live book record."""
    bk = store.read_all("books")
    lv = store.read_all("live")
    if bk is None or lv is None:
        return {}
    yes = bk.filter(pl.col("side") == "yes").with_columns(
        pl.col("bid_px").list.first().alias("b"), pl.col("ask_px").list.first().alias("a"))
    yes = yes.filter(pl.col("a").is_not_null() & pl.col("b").is_not_null() & (pl.col("a") > pl.col("b")))
    yes = yes.join(lv.select(pl.col("id").alias("market_id"), "category", "ts_ms", "created_ms")
                   .unique(["market_id", "ts_ms"]), on=["market_id", "ts_ms"], how="left")
    mid = ((yes["a"] + yes["b"]) / 2).to_numpy()
    hs = ((yes["a"] - yes["b"]) / 2).to_numpy()
    age = ((yes["ts_ms"] - yes["created_ms"].fill_null(0)) / 86_400_000).to_numpy().astype(float)
    b = P.price_bucket(mid)
    cats = np.array(yes["category"].fill_null("other").to_list())
    ages = np.array([age_label(a) for a in age])
    out: dict = {"by_bucket": {}, "by_bucket_cat": {}, "by_bucket_age": {}, "n": int(len(hs)),
                 "by_age": {a: float(np.median(hs[ages == a])) for a in AGE_LABELS if (ages == a).sum() >= 5},
                 "n_age": {a: int((ages == a).sum()) for a in AGE_LABELS}}
    for i, lab in enumerate(P.PRICE_LABELS):
        k = b == i
        if k.sum() >= 5:
            out["by_bucket"][lab] = float(np.median(hs[k]))
        for c in set(cats.tolist()):
            kc = k & (cats == c)
            if kc.sum() >= 10:
                out["by_bucket_cat"][f"{lab}|{c}"] = float(np.median(hs[kc]))
        for a in AGE_LABELS:
            ka = k & (ages == a)
            if ka.sum() >= 5:
                out["by_bucket_age"][f"{lab}|{a}"] = float(np.median(hs[ka]))
    return out


AGE_LABELS = ("<1d", "1-7d", ">7d")


def age_label(days: float) -> str:
    return "<1d" if days < 1 else "1-7d" if days < 7 else ">7d"


def hs_for(hs: dict, p: float, cat: str, mult: float = 1.0, age_days: float | None = None) -> float:
    lab = P.PRICE_LABELS[int(P.price_bucket([p])[0])]
    base = hs.get("by_bucket", {}).get(lab, 0.01)
    if age_days is not None:
        a = age_label(age_days)
        v = hs.get("by_bucket_age", {}).get(f"{lab}|{a}", hs.get("by_age", {}).get(a, base))
    else:
        v = hs.get("by_bucket_cat", {}).get(f"{lab}|{cat}", base)
    return max(MIN_HALF_SPREAD, v) * mult


def simulate(oos: pl.DataFrame, full: pl.DataFrame, col: str, margin: float, hs: dict, mult: float = 1.0,
             min_age_days: float = 0.0, by_age: bool = False, moved_only: bool = False) -> dict:
    """The rule on the test states, day by day, marked daily at the history price.
    min_age_days, by_age and moved_only are the addendum's checks (no first-day states; the
    half-spread looked up by the market's age; only states whose price has moved since the
    market opened)."""
    bk = B.Book(f"{col}@{margin}", margin)
    ent = oos.filter(pl.col("days_since") >= min_age_days) if min_age_days else oos
    if moved_only:
        ent = ent.filter(pl.col("hi") > pl.col("lo"))
    ent = ent.with_columns((pl.col("t_s") // 86400).alias("d")).sort("d")
    marks = full.select("market_id", "t_s", "p").with_columns((pl.col("t_s") // 86400).alias("d"))
    closes = full.group_by("market_id").agg(pl.col("close_s").first(), pl.col("y").first())
    close_day = {r[0]: (int(r[1]) // 86400, float(r[2])) for r in closes.iter_rows()}
    d0, d1 = int(ent["d"].min()), int(max(v[0] for v in close_day.values()))
    ent_by_day = {int(k[0]): g for k, g in ent.group_by(["d"])}
    mark_by_day = {int(k[0]): g for k, g in marks.filter(pl.col("d") >= d0).group_by(["d"])}
    settle_by_day: dict[int, list] = {}
    eq, days, trades = [], [], []
    for d in range(d0, d1 + 1):
        for mid in settle_by_day.pop(d, []):
            bk.settle(mid, close_day[mid][1], d * 86_400_000)
        g = mark_by_day.get(d)
        if g is not None and bk.positions:
            for mid, p in g.select("market_id", "p").iter_rows():
                bk.set_mark(mid, p)
        g = ent_by_day.get(d)
        if g is not None:
            q = g[col].to_numpy()
            p = g["p"].to_numpy()
            order = np.argsort(-np.abs(q - p))
            rows = g.to_dicts()
            for i in order:
                r = rows[i]
                h = hs_for(hs, r["p"], r["category"], mult, r["days_since"] if by_age else None)
                end_ms = int((r["t_s"] + r["days_to_end"] * 86400) * 1000)
                m = {"id": r["market_id"], "event_id": r["event_id"], "category": r["category"], "kind": r["kind"],
                     "end_ms": end_ms, "fee_rate": M.FEE_RATE.get(r["category"], 0.05), "fee_exponent": 1.0}
                f = bk.consider(m, float(q[i]), r["t_s"] * 1000, [(r["p"] + h, 1e12)], [(1 - r["p"] + h, 1e12)],
                                max_usd=HIST_MAX_USD)
                if f:
                    trades.append(f)
                    cd = close_day[r["market_id"]][0]
                    settle_by_day.setdefault(max(cd, d + 1), []).append(r["market_id"])
        if d <= d1:
            eq.append(bk.equity())
            days.append(d)
        if d > int(ent["d"].max()) and not bk.positions:
            break
    eq = np.array(eq)
    ret = np.diff(eq) / eq[:-1] if len(eq) > 1 else np.array([0.0])
    closed = bk.closed
    n = len(closed)
    rets = np.array([c["ret"] for c in closed]) if n else np.array([])
    evs = np.array([c["event_id"] for c in closed]) if n else np.array([])
    mean, lo, hi = event_boot(rets, np.ones(n), evs, seed=21) if n >= 5 else (float(rets.mean()) if n else 0.0,
                                                                              math.nan, math.nan)
    peak = np.maximum.accumulate(eq) if len(eq) else np.array([B.START_USD])
    dd = float(np.max(1 - eq / peak)) if len(eq) else 0.0
    yrs = max(len(eq) / 365.0, 1e-9)
    by_cat = {}
    for c in closed:
        k = by_cat.setdefault(c["category"], {"n": 0, "pnl": 0.0, "won": 0})
        k["n"] += 1
        k["pnl"] += c["pnl"]
        k["won"] += int(c["won"])
    by_year = {}
    for c in closed:
        y = datetime.fromtimestamp(c["entry_ms"] / 1000, timezone.utc).year
        k = by_year.setdefault(str(y), {"n": 0, "pnl": 0.0})
        k["n"] += 1
        k["pnl"] += c["pnl"]
    sharpe = float(ret.mean() / ret.std() * math.sqrt(365)) if len(ret) > 1 and ret.std() > 0 else 0.0
    return {"book": col, "margin": margin, "spread_mult": mult, "trades": n,
            "hit_rate": float(np.mean([c["won"] for c in closed])) if n else None,
            "mean_ret": mean, "mean_ret_lo": lo, "mean_ret_hi": hi,
            "pnl": float(eq[-1] - B.START_USD) if len(eq) else 0.0,
            "total_return": float(eq[-1] / B.START_USD - 1) if len(eq) else 0.0,
            "cagr": float((eq[-1] / B.START_USD) ** (1 / yrs) - 1) if len(eq) and eq[-1] > 0 else -1.0,
            "sharpe": sharpe, "max_dd": dd, "days": len(eq),
            "fees": float(sum(t["fee"] for t in trades)), "staked": float(sum(t["usd"] for t in trades)),
            "by_category": dict(sorted(by_cat.items())), "by_year": by_year,
            "_daily": ret.tolist()}


def pool(mine_annual: list[float]) -> dict:
    from ..experiments import fam_common as fc
    from ..experiments import flow_overlays as fo
    v1 = fo.prior_var()
    try:
        fx = np.clip(fo.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    except Exception:
        fx = np.array([])
    x = np.clip(np.array([s for s in mine_annual if np.isfinite(s)] or [0.0]), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n1, n2, n3 = PRIOR_HAND, len(fx), HERE_TRIALS
    v2 = float(np.var(fx)) if len(fx) > 1 else 0.0
    v3 = float(np.var(x)) if len(x) > 1 else 0.0
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "mine": n3, "n_total": n, "var": v,
            "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated_p(daily: list[float], pl_: dict) -> float | None:
    from ..experiments import flow_overlays as fo
    x = np.array(daily)
    if len(x) < 30 or x.std() == 0:
        return None
    return float(fo.deflated(x, pl_["n_total"], pl_["var"]))


# ---------------------------------------------------------------- the live model

def save_model(df: pl.DataFrame) -> dict:
    """Fit recal and gbm on every state and save them for the daily book."""
    import lightgbm  # noqa: F401
    beta = fit_recal(df)
    m, iso = fit_gbm(df)
    d = store.path("model")
    d.mkdir(parents=True, exist_ok=True)
    m.booster_.save_model(str(d / "gbm.txt"))
    store.write_json(d / "iso.json", {"x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()})
    store.write_json(d / "recal.json", {"beta": beta.tolist()})
    meta = {"features": P.FEATURES, "categories": list(P.CAT_ORDER), "kinds": list(P.KIND_ORDER),
            "trained_states": df.height, "trained_markets": df["market_id"].n_unique(),
            "trained_until_s": int(df["close_s"].max()), "fitted_ms": int(time.time() * 1000)}
    store.write_json(d / "meta.json", meta)
    return meta


# ---------------------------------------------------------------- the run

def run(refresh: bool = False) -> dict:
    t0 = time.time()
    df, mk = panel(refresh)
    log(f"panel: {df.height:,} states of {df['market_id'].n_unique():,} markets, "
        f"{df['event_id'].n_unique():,} events")
    sw = stratum_weights(mk)
    res: dict = {"data": data_summary(df, mk)}
    log("B: biases")
    res["biases"] = biases(df, sw)
    log("M: walk-forward")
    oos = walk_forward(df)
    store.write_parquet(oos, store.path("cache", "oos.parquet"))
    res["models"] = {c: score(oos, c) for c in ("q_recal", "q_gbm")}
    res["holm"] = holm({c: v["p_one_sided"] for c, v in res["models"].items()})
    # addendum slices: where the history price is a real price (descriptive, same test)
    res["slices"] = {}
    for name, cond in SLICES.items():
        s = oos.filter(cond)
        if s.height > 1000:
            res["slices"][name] = {c: score(s, c) for c in ("q_recal", "q_gbm")}
            res["slices"][name]["share_states"] = s.height / oos.height
    log("P: historical twin")
    hs = half_spreads()
    res["half_spreads"] = hs
    sims = []
    for col in ("q_recal", "q_gbm"):
        for m in MARGINS:
            sims.append(simulate(oos, df, col, m, hs))
            log(f"  {col} m={m}: {sims[-1]['trades']} trades, return {sims[-1]['total_return']:+.1%}, "
                f"Sharpe {sims[-1]['sharpe']:.2f}")
    stress = [simulate(oos, df, col, 0.03, hs, mult=2.0) for col in ("q_recal", "q_gbm")]
    checks = []
    for col in ("q_recal", "q_gbm"):
        for name, kw in (("no first-day states", {"min_age_days": 1.0}), ("half-spread by age", {"by_age": True}),
                         ("price has moved", {"moved_only": True}),
                         ("after day one and moved", {"min_age_days": 1.0, "moved_only": True})):
            c = simulate(oos, df, col, 0.03, hs, **kw)
            c["check"] = name
            checks.append(c)
    for c in checks:
        log(f"  check {c['check']}, {c['book']}: {c['trades']} trades, return {c['total_return']:+.1%}, "
            f"Sharpe {c['sharpe']:.2f}")
    pl_ = pool([s["sharpe"] for s in sims + checks])
    for s in sims + stress + checks:
        s["deflated_p"] = deflated_p(s.pop("_daily"), pl_)
    res.update(sims=sims, stress=stress, checks=checks, pool=pl_)
    log("fitting the live model on every state")
    res["live_model"] = save_model(df)
    res["seconds"] = round(time.time() - t0)
    return res


def data_summary(df: pl.DataFrame, mk: pl.DataFrame) -> dict:
    strata = store.read_json(store.path("resolved", "strata.json"), {}) or {}
    universe = sum(v.get("all", 0) for m in strata.values() for k, v in m.items() if not k.startswith("_"))
    resolved = sum(v.get("resolved", 0) for m in strata.values() for k, v in m.items() if not k.startswith("_"))
    by_year = df.group_by("year").agg(pl.col("market_id").n_unique().alias("markets"), pl.len().alias("states")) \
        .sort("year").to_dicts()
    by_cat = df.group_by(["category"]).agg(pl.col("market_id").n_unique().alias("markets"),
                                           pl.len().alias("states")).sort("category").to_dicts()
    return {"universe_markets": universe, "universe_resolved": resolved, "sampled_with_history": mk.height,
            "markets_in_panel": df["market_id"].n_unique(), "events": df["event_id"].n_unique(),
            "states": df.height, "first": datetime.fromtimestamp(int(df["t_s"].min()), timezone.utc).strftime("%Y-%m-%d"),
            "last": datetime.fromtimestamp(int(df["t_s"].max()), timezone.utc).strftime("%Y-%m-%d"),
            "by_year": by_year, "by_category": by_cat, "size_mb": round(store.size_bytes() / 1e6, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.refresh)
    from . import writeup
    writeup.write(res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
