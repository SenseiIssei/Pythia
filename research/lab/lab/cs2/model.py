"""CS2 price models: a bootstrap from Skinport's sales windows now, an honest
walk-forward LightGBM once the collector has history, and the studies
(cross-market spread, momentum and reversion, case age and drop pool events).

Bootstrap (one snapshot, cross-sectional, NOT a time-series backtest).
Skinport's sales stats give each item three disjoint average prices: days
30-90, 7-30 and 0-7 ago (`market.buckets`). The 7-day model learns
  log(avg 0-7 / avg 7-30)  from  the change avg 30-90 -> avg 7-30, the sales
  rate and its trend, the price level, the category and the case age,
so every feature is older than the label. It is scored with 5-fold cross
validation across items: every fold sees the same weeks, so a market-wide
move is in train and test alike. It says whether items that rose kept rising
(or fell back) over the last three months, nothing more. The 30-day model
learns log(avg 0-30 / avg 30-90) from static traits only (level, sales rate,
category, case age). A prediction is the learned change relative to the
median item (one snapshot says nothing about the whole market's next move),
scaled from the distance between the window centres to the horizon, and
applied to the current price with no built-in reversion to an average.

Walk-forward (from the collector's daily snapshots). Features at day t from
data up to t, labels log p(t+h)/p(t) for h = 7 and 30, monthly expanding
refits, training rows only where t+h is before the test month. Needs at least
MIN_TRAIN_DAYS of labelled days before the first test month.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl

from . import market

SEED = 7
MIN_TRAIN_DAYS = 45
LGB_PARAMS = dict(n_estimators=300, learning_rate=0.03, num_leaves=15, min_child_samples=40,
                  subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, verbose=-1,
                  random_state=SEED)

BOOT7 = ["mom", "rate", "rate_trend", "lvl", "cat_code", "case_age_days"]
BOOT30 = ["lvl", "rate", "cat_code", "case_age_days"]
# label window centres: 7d model 3.5 vs 18.5 days ago (15 apart), 30d model 15 vs 60 (45 apart)
BOOT_SCALE = {7: 7 / 15, 30: 30 / 45}
PANEL = ["r1", "r7", "r30", "z30", "vol30", "lvl", "rate", "qty_chg7", "ask_prem", "cat_code", "case_age_days"]


def _lgbm():
    import lightgbm as lgb
    return lgb.LGBMRegressor(**LGB_PARAMS)


def spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    m = np.isfinite(a) & np.isfinite(b)
    if m.sum() < 10:
        return None
    ra = np.argsort(np.argsort(a[m])).astype(float)
    rb = np.argsort(np.argsort(b[m])).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def _x(df: pl.DataFrame, cols: list[str]) -> np.ndarray:
    return df.select([pl.col(c).cast(pl.Float64) for c in cols]).to_numpy()


# ---------------------------------------------------------------- bootstrap

def bootstrap_frame(snap: pl.DataFrame, asof: date, min_sales: int = 3) -> pl.DataFrame:
    """Train and predict features from one snapshot (items joined with sales)."""
    df = market.with_meta(market.buckets(snap, min_sales), asof)
    return df.with_columns(
        # training view: everything at least 7 days old, label the last week
        t_mom=(pl.col("b7_30") / pl.col("b30_90")).log(),
        t_rate=(pl.col("n7_30") / 23).log1p(),
        t_rate_trend=((pl.col("n7_30") / 23 + 0.1) / (pl.col("n30_90") / 60 + 0.1)).log(),
        t_lvl=pl.col("b7_30").log(),
        y7=(pl.col("b0_7") / pl.col("b7_30")).log(),
        # the same features today
        mom=(pl.col("b0_7") / pl.col("b7_30")).log(),
        rate=(pl.col("n0_7") / 7).log1p(),
        rate_trend=((pl.col("n0_7") / 7 + 0.1) / (pl.col("n7_30") / 23 + 0.1)).log(),
        lvl=pl.col("b0_7").log(),
        # 30 days: static traits only
        t30_lvl=pl.col("b30_90").log(),
        t30_rate=(pl.col("n30_90") / 60).log1p(),
        y30=(pl.col("s30_avg") / pl.col("b30_90")).log(),
        lvl30=pl.col("s30_avg").log(),
        rate30=(pl.col("s30_volume").fill_null(0) / 30).log1p(),
    )


def _train_view(df: pl.DataFrame, h: int) -> tuple[np.ndarray, np.ndarray]:
    if h == 7:
        d = df.filter(pl.col("y7").is_finite() & pl.col("t_mom").is_finite())
        x = d.select(pl.col("t_mom").alias("mom"), pl.col("t_rate").alias("rate"),
                     pl.col("t_rate_trend").alias("rate_trend"), pl.col("t_lvl").alias("lvl"),
                     "cat_code", "case_age_days")
        return _x(x, BOOT7), d["y7"].to_numpy()
    d = df.filter(pl.col("y30").is_finite() & pl.col("t30_lvl").is_finite())
    x = d.select(pl.col("t30_lvl").alias("lvl"), pl.col("t30_rate").alias("rate"), "cat_code", "case_age_days")
    return _x(x, BOOT30), d["y30"].to_numpy()


def _now_view(df: pl.DataFrame, h: int) -> np.ndarray:
    if h == 7:
        return _x(df, BOOT7)
    return _x(df.select(pl.col("lvl30").alias("lvl"), pl.col("rate30").alias("rate"), "cat_code", "case_age_days"),
              BOOT30)


def top_spread(pred: np.ndarray, y: np.ndarray, q: float = 0.1) -> float | None:
    """Mean label of the top `q` by prediction minus the mean label of all."""
    m = np.isfinite(pred) & np.isfinite(y)
    if m.sum() < 20:
        return None
    p, yy = pred[m], y[m]
    k = max(int(len(p) * q), 1)
    return float(yy[np.argsort(-p)[:k]].mean() - yy.mean())


def cv_score(x: np.ndarray, y: np.ndarray, folds: int = 5) -> dict:
    """K-fold across items: out-of-fold rank IC, top-decile spread, MSE against predicting zero."""
    n = len(y)
    if n < folds * 20:
        return {"n": n, "status": "too few items"}
    rng = np.random.default_rng(SEED)
    fold = rng.permutation(n) % folds
    oof = np.full(n, np.nan)
    for k in range(folds):
        m = _lgbm().fit(x[fold != k], y[fold != k])
        oof[fold == k] = m.predict(x[fold == k])
    return {"n": int(n), "status": "ok", "ic": spearman(oof, y), "top_decile_minus_all": top_spread(oof, y),
            "mse_model": float(np.mean((oof - y) ** 2)), "mse_zero": float(np.mean(y ** 2)),
            "mse_mean": float(np.mean((y - y.mean()) ** 2)), "oof": oof}


def bootstrap(snap: pl.DataFrame, asof: date, liquid_sales: int = 20) -> tuple[dict, pl.DataFrame]:
    """(report, predictions per item: pred7, pred30 as expected log changes)."""
    df = bootstrap_frame(snap, asof)
    rep: dict = {"kind": "bootstrap", "asof": asof.isoformat(), "items": df.height}
    preds = df.select("name").with_columns(pred7=pl.lit(None, pl.Float64), pred30=pl.lit(None, pl.Float64))
    for h in (7, 30):
        x, y = _train_view(df, h)
        sc = cv_score(x, y)
        sc.pop("oof", None)
        if h == 7 and sc.get("status") == "ok":
            mom = x[:, 0]
            sc["ic_momentum_alone"] = spearman(mom, y)
            liq = df.filter(pl.col("y7").is_finite() & pl.col("t_mom").is_finite())["n7_30"].to_numpy() >= liquid_sales
            sc["ic_momentum_liquid"] = spearman(mom[liq], y[liq])
            sc["liquid_items"] = int(liq.sum())
        rep[f"h{h}"] = sc
        if sc.get("status") == "ok":
            m = _lgbm().fit(x, y)
            p = m.predict(_now_view(df, h))
            # One snapshot cannot tell where the whole market goes next, so the
            # prediction is relative to the median item, scaled from the
            # distance between the window centres to the horizon.
            p = (p - np.nanmedian(p)) * BOOT_SCALE[h]
            preds = preds.with_columns(pl.Series(f"pred{h}", p))
    return rep, preds


# ---------------------------------------------------------------- the daily panel

def daily_matrix(daily: pl.DataFrame, min_sales30: float = 10, max_items: int = 5000) -> dict | None:
    """Dates x items matrices of the reference price and its companions, from the
    collector's daily snapshots. Items: those with at least `min_sales30` sales in
    30 days on the last day, the most traded `max_items`."""
    if daily.is_empty():
        return None
    d = daily.with_columns(p=market.ref_price(daily)).filter(pl.col("p") > 0)
    last = d["date"].max()
    keep = (d.filter(pl.col("date") == last).filter(pl.col("s30_volume").fill_null(0) >= min_sales30)
            .sort("s30_volume", descending=True).head(max_items)["name"].to_list())
    d = d.filter(pl.col("name").is_in(keep))
    if d.is_empty():
        return None
    dates = pl.date_range(d["date"].min(), last, "1d", eager=True)
    names = sorted(d["name"].unique().to_list())

    def wide(col: str) -> np.ndarray:
        w = d.pivot(on="name", index="date", values=col, aggregate_function="last")
        w = pl.DataFrame({"date": dates}).join(w, on="date", how="left")
        m = w.select([pl.col(n) if n in w.columns else pl.lit(None, pl.Float64).alias(n) for n in names]).to_numpy()
        return m.astype(float)

    p = _ffill(wide("p"), 3)
    return {"dates": dates.to_list(), "names": names, "p": p, "ask": _ffill(wide("min_price"), 3),
            "qty": _ffill(wide("quantity"), 3), "s7": _ffill(wide("s7_volume"), 3)}


def _ffill(a: np.ndarray, limit: int) -> np.ndarray:
    out = a.copy()
    gap = np.zeros(a.shape[1])
    for t in range(1, len(a)):
        miss = ~np.isfinite(out[t])
        gap = np.where(miss, gap + 1, 0)
        fill = miss & (gap <= limit)
        out[t, fill] = out[t - 1, fill]
    return out


def _shift(a: np.ndarray, k: int) -> np.ndarray:
    out = np.full_like(a, np.nan)
    if k > 0:
        out[k:] = a[:-k]
    elif k < 0:
        out[:k] = a[-k:]
    else:
        out[:] = a
    return out


def panel_features(mx: dict, asof: date | None = None) -> dict[str, np.ndarray]:
    lp = np.log(mx["p"])
    r = lp - _shift(lp, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        roll = np.lib.stride_tricks.sliding_window_view
        n = len(lp)
        mean30 = np.full_like(lp, np.nan)
        sd30 = np.full_like(lp, np.nan)
        vol30 = np.full_like(lp, np.nan)
        if n >= 30:
            w = roll(lp, 30, axis=0)
            mean30[29:] = np.nanmean(w, axis=-1)
            sd30[29:] = np.nanstd(w, axis=-1)
            vol30[29:] = np.nanstd(roll(r, 30, axis=0), axis=-1)
        cats = np.array([market.CATEGORIES.index(market.category(nm)) for nm in mx["names"]], dtype=float)
        rel = market.case_release_dates()
        dates = mx["dates"]
        age = np.array([[(dt - rel[nm]).days if nm in rel else np.nan for nm in mx["names"]] for dt in dates], dtype=float)
        f = {
            "r1": r,
            "r7": lp - _shift(lp, 7),
            "r30": lp - _shift(lp, 30),
            "z30": (lp - mean30) / np.where(sd30 > 0, sd30, np.nan),
            "vol30": vol30,
            "lvl": lp,
            "rate": np.log1p(np.nan_to_num(mx["s7"], nan=0) / 7),
            "qty_chg7": np.log((mx["qty"] + 1) / (_shift(mx["qty"], 7) + 1)),
            "ask_prem": np.log(mx["ask"] / mx["p"]),
            "cat_code": np.broadcast_to(cats, lp.shape).copy(),
            "case_age_days": age,
        }
    return f


def walk_forward(mx: dict | None, horizons: tuple[int, ...] = (7, 30), cost: float | None = None) -> dict:
    """Monthly expanding walk-forward per horizon; predictions for the last day."""
    cost = market.round_trip_cost() if cost is None else cost
    if mx is None:
        return {"status": "no history", "days": 0}
    n_days, n_items = mx["p"].shape
    out: dict = {"days": n_days, "items": n_items, "first": str(mx["dates"][0]), "last": str(mx["dates"][-1])}
    feats = panel_features(mx)
    X = np.stack([feats[c] for c in PANEL], axis=-1)  # days x items x features
    lp = np.log(mx["p"])
    months = np.array([d.year * 12 + d.month for d in mx["dates"]])
    for h in horizons:
        y = _shift(lp, -h) - lp
        labelled = np.isfinite(y).any(axis=1)
        if labelled.sum() < MIN_TRAIN_DAYS + h:
            out[f"h{h}"] = {"status": f"needs {MIN_TRAIN_DAYS + h} labelled days, has {int(labelled.sum())}"}
            continue
        first_ok = MIN_TRAIN_DAYS + h
        test_months = sorted({m for i, m in enumerate(months) if i >= first_ok and labelled[i]})
        oof = np.full_like(y, np.nan)
        for m in test_months:
            start = int(np.argmax(months == m))
            train_rows = np.arange(n_days) < start - h  # label t+h known before the test month
            test_rows = (months == m) & labelled
            xt, yt = X[train_rows].reshape(-1, len(PANEL)), y[train_rows].reshape(-1)
            ok = np.isfinite(yt) & np.isfinite(xt[:, PANEL.index("r7")])
            if ok.sum() < 200:
                continue
            model = _lgbm().fit(xt[ok], yt[ok])
            xs = X[test_rows].reshape(-1, len(PANEL))
            oof[test_rows] = model.predict(xs).reshape(int(test_rows.sum()), n_items)
        res = _score_panel(oof, y, h, cost, mx["dates"])
        # final model on everything labelled, for today's predictions
        xa, ya = X.reshape(-1, len(PANEL)), y.reshape(-1)
        ok = np.isfinite(ya) & np.isfinite(xa[:, PANEL.index("r7")])
        if ok.sum() >= 200:
            model = _lgbm().fit(xa[ok], ya[ok])
            res["pred_last"] = dict(zip(mx["names"], model.predict(X[-1]).tolist()))
        out[f"h{h}"] = res
    return out


def _score_panel(oof: np.ndarray, y: np.ndarray, h: int, cost: float, dates: list) -> dict:
    """Rank IC per day (t from every h-th day, so the labels do not overlap),
    and a long-only top-decile book held h days, net of the round trip."""
    ics, tops, base = [], [], []
    for t in range(len(y)):
        m = np.isfinite(oof[t]) & np.isfinite(y[t])
        if m.sum() < 20:
            continue
        ic = spearman(oof[t][m], y[t][m])
        if ic is None:
            continue
        ics.append((t, ic))
        k = max(int(m.sum() * 0.1), 1)
        idx = np.argsort(-oof[t][m])[:k]
        tops.append((t, float(np.mean(np.expm1(y[t][m][idx]))) - cost))
        base.append((t, float(np.mean(np.expm1(y[t][m])))))
    if not ics:
        return {"status": "no out-of-sample days yet"}
    ind = [ic for t, ic in ics if (t - ics[0][0]) % h == 0]
    arr = np.array(ind)
    t_stat = float(arr.mean() / (arr.std(ddof=1) / np.sqrt(len(arr)))) if len(arr) > 2 and arr.std(ddof=1) > 0 else None
    top_ind = np.array([v for t, v in tops if (t - tops[0][0]) % h == 0])
    base_ind = np.array([v for t, v in base if (t - base[0][0]) % h == 0])
    return {"status": "ok", "oos_days": len(ics), "first_oos": str(dates[ics[0][0]]), "ic_mean": float(np.mean([i for _, i in ics])),
            "ic_independent": float(arr.mean()), "ic_t": t_stat, "independent_periods": int(len(arr)),
            "top_decile_net_per_trade": float(top_ind.mean()) if len(top_ind) else None,
            "universe_gross_per_period": float(base_ind.mean()) if len(base_ind) else None,
            "hit_rate_net": float((top_ind > 0).mean()) if len(top_ind) else None}


# ---------------------------------------------------------------- studies

def spread_study(skin: pl.DataFrame, steam: pl.DataFrame) -> dict:
    """Both hand routes per item and day, net of fees; drift of Steam over Skinport."""
    if skin.is_empty() or steam.is_empty():
        return {"status": "no Steam prices yet", "rows": 0}
    j = (skin.select("date", "name", "min_price", pl.col("s7_volume").fill_null(0).alias("sk_sales7"))
         .join(steam.select("date", "name", pl.col("lowest").alias("steam_ask"), pl.col("median").alias("steam_median"),
                            pl.col("volume").alias("steam_volume")), on=["date", "name"], how="inner")
         .filter(pl.col("min_price").is_not_null() & pl.col("steam_ask").is_not_null()))
    if j.is_empty():
        return {"status": "no overlap between Skinport and Steam yet", "rows": 0}
    g = [market.gaps(a, b) for a, b in zip(j["min_price"].to_list(), j["steam_ask"].to_list())]
    j = j.with_columns(to_steam=pl.Series([x["to_steam"] for x in g], dtype=pl.Float64),
                       to_skinport=pl.Series([x["to_skinport"] for x in g], dtype=pl.Float64),
                       ratio=(pl.col("steam_ask") / pl.col("min_price")).log())
    last = j.filter(pl.col("date") == j["date"].max())
    days = j["date"].n_unique()
    drift = None
    if days >= 14:
        z = (j.group_by("name").agg(mu=pl.col("ratio").mean(), sd=pl.col("ratio").std(), n=pl.len())
             .filter(pl.col("n") >= 10)
             .join(last.select("name", "ratio"), on="name")
             .with_columns(z=(pl.col("ratio") - pl.col("mu")) / pl.col("sd")))
        drift = {"items": z.height, "median_abs_z": float(z["z"].abs().median()) if z.height else None,
                 "mean_daily_change_of_log_ratio": float(
                     j.sort("date").group_by("name").agg(d=pl.col("ratio").diff().mean())["d"].drop_nulls().mean() or 0)}
    return {
        "status": "ok", "rows": j.height, "days": days, "items_today": last.height,
        "steam_premium_median": float(np.expm1(last["ratio"].median())),
        "to_steam_median": float(last["to_steam"].median()), "to_skinport_median": float(last["to_skinport"].median()),
        "share_to_steam_positive": float((j["to_steam"] > 0).mean()),
        "share_to_skinport_positive": float((j["to_skinport"] > 0).mean()),
        "drift": drift,
        "best_today": last.sort(pl.max_horizontal("to_steam", "to_skinport"), descending=True).head(10)
        .select("name", "min_price", "steam_ask", "to_steam", "to_skinport", "steam_volume").to_dicts(),
    }


def case_study(snap: pl.DataFrame, asof: date) -> dict:
    """Cases only: does the 90-day path depend on age? Spearman of case age
    against the change avg 30-90 -> avg 0-7, and the same by age group."""
    df = market.with_meta(market.buckets(snap), asof).filter(pl.col("category") == "case")
    df = df.with_columns(chg=(pl.col("b0_7") / pl.col("b30_90")).log()).filter(pl.col("chg").is_finite())
    if df.height < 8:
        return {"status": "too few cases with sales in all windows", "cases": df.height}
    known = df.filter(pl.col("case_age_days").is_not_null())
    groups = (known.with_columns(group=pl.when(pl.col("case_age_days") < 3 * 365).then(pl.lit("under 3 years"))
                                 .when(pl.col("case_age_days") < 7 * 365).then(pl.lit("3 to 7 years"))
                                 .otherwise(pl.lit("over 7 years")))
              .group_by("group").agg(cases=pl.len(), median_change=pl.col("chg").median()).sort("group"))
    return {"status": "ok", "cases": df.height, "known_age": known.height,
            "ic_age_vs_change": spearman(known["case_age_days"].to_numpy(), known["chg"].to_numpy()),
            "by_age": groups.to_dicts()}


def event_study(mx: dict | None, events: list[dict], pre: int = 7, post: int = 30) -> dict:
    """Abnormal log return of the named items around each event inside the
    history, against the median of all cases the same days."""
    if mx is None:
        return {"status": "no history", "events": []}
    dates = mx["dates"]
    idx = {d: i for i, d in enumerate(dates)}
    names = {n: j for j, n in enumerate(mx["names"])}
    cases = [j for n, j in names.items() if market.category(n) == "case"]
    lp = np.log(mx["p"])
    rows = []
    for ev in events:
        try:
            d = date.fromisoformat(ev["date"])
        except (KeyError, ValueError):
            continue
        if d not in idx or idx[d] - pre < 0 or idx[d] + post >= len(dates):
            rows.append({"date": ev.get("date"), "kind": ev.get("kind"), "status": "outside the collected history"})
            continue
        i0, i1 = idx[d] - pre, idx[d] + post
        mkt = np.nanmedian(lp[i1, cases] - lp[i0, cases]) if cases else 0.0
        for n in ev.get("items") or []:
            if n in names:
                j = names[n]
                rows.append({"date": ev["date"], "kind": ev.get("kind"), "item": n,
                             "abnormal": float(lp[i1, j] - lp[i0, j] - mkt)})
    done = [r for r in rows if "abnormal" in r]
    return {"status": "ok" if done else "no event inside the history yet", "events": rows,
            "mean_abnormal": float(np.mean([r["abnormal"] for r in done])) if done else None}
