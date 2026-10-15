"""What moves Pokemon card prices: the studies behind the model.

Each study has two forms. The cross-sectional form works from the first
snapshot on, using what the API exposes about the past (Cardmarket's rolling
averages avg1, avg7 and avg30 and its trend price): it describes the last 30
days across cards, it does not forecast. The panel form needs our own daily
snapshots and is reported only once enough of them exist; until then it says
how many days it is waiting for.

  release    do new sets drop and then recover? Price trend by set age.
  reprint    does a reprint hurt the older printing? Cards whose text (name,
             HP, attacks, abilities) came out again in a newer set (any
             rarity, from the full catalogue),
             plus announcements the owner lists in <lake>/reprints.csv
             (columns name, announced as YYYY-MM-DD), against cards that
             were not reprinted, within the same rarity group.
  premium    rarity and character effects: one regression of log price on
             rarity group, character, alt art, secret number, set age and
             card type across the latest snapshot (premiums in %, HC1 t).
  spread     TCGplayer (USD) against Cardmarket (EUR at the ECB rate).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import polars as pl

AGE_BUCKETS = [(0, 30, "0-30 d"), (30, 90, "1-3 mo"), (90, 180, "3-6 mo"), (180, 365, "6-12 mo"),
               (365, 730, "1-2 y"), (730, 1825, "2-5 y"), (1825, 100_000, "5 y +")]
PANEL_MIN_DAYS = 30
TREND_MIN_CARDS = 200
REPRINT_WINDOW = 90


def age_bucket(days) -> str | None:
    if days is None or (isinstance(days, float) and math.isnan(days)):
        return None
    for lo, hi, name in AGE_BUCKETS:
        if lo <= days < hi:
            return name
    return None


def _med(s: pl.Series) -> float | None:
    s = s.drop_nulls().drop_nans() if s.dtype in (pl.Float32, pl.Float64) else s.drop_nulls()
    return float(s.median()) if len(s) else None


def _mean_t(x: np.ndarray) -> tuple[float | None, float | None]:
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return (float(x.mean()) if len(x) else None), None
    sd = x.std(ddof=1)
    return float(x.mean()), (float(x.mean() / (sd / math.sqrt(len(x)))) if sd > 0 else None)


def latest(df: pl.DataFrame) -> pl.DataFrame:
    return df.filter(pl.col("date") == df["date"].max()) if not df.is_empty() else df


# ---------------------------------------------------------------- release

def release_cross(snap: pl.DataFrame) -> list[dict]:
    """Median Cardmarket 30-day trend (trend / avg30 - 1) and avg7 / avg30 - 1 by set age."""
    s = snap.with_columns(bucket=pl.col("set_age_days").map_elements(age_bucket, return_dtype=pl.Utf8))
    rows = []
    for _, _, name in AGE_BUCKETS:
        b = s.filter(pl.col("bucket") == name)
        rows.append({"set_age": name, "cards": b.height, "sets": b["set_id"].n_unique() if b.height else 0,
                     "median_trend_vs_avg30_pct": _pct(_med(b["cm_trend_30"])) if b.height else None,
                     "median_avg7_vs_avg30_pct": _pct(_med(b["cm_mom_7_30"])) if b.height else None,
                     "median_price_usd": _med(b["price"]) if b.height else None})
    return rows


def set_daily_returns(df: pl.DataFrame) -> pl.DataFrame:
    """Per set and day: the median log return of its cards since their previous
    snapshot (same card, same source, at most 3 days apart), with the set's age."""
    d = (df.select("card_id", "set_id", "date", "price", "price_src", "release_date")
         .with_columns(_d=pl.col("date").str.to_date()).sort("card_id", "_d")
         .with_columns(prev_p=pl.col("price").shift(1).over("card_id"),
                       prev_d=pl.col("_d").shift(1).over("card_id"),
                       prev_src=pl.col("price_src").shift(1).over("card_id"))
         .filter((pl.col("prev_src") == pl.col("price_src"))
                 & ((pl.col("_d") - pl.col("prev_d")).dt.total_days() <= 3))
         .with_columns(r=(pl.col("price") / pl.col("prev_p")).log() /
                       (pl.col("_d") - pl.col("prev_d")).dt.total_days()))
    return (d.group_by("set_id", "_d").agg(r=pl.col("r").median(), n=pl.len(),
                                            release=pl.col("release_date").first())
            .with_columns(age=(pl.col("_d") - pl.col("release").str.to_date()).dt.total_days())
            .sort("set_id", "_d"))


def release_panel(df: pl.DataFrame, days: int) -> dict:
    if days < PANEL_MIN_DAYS:
        return {"ready": False, "waiting_days": PANEL_MIN_DAYS - days, "rows": []}
    sr = set_daily_returns(df).with_columns(
        bucket=pl.col("age").map_elements(age_bucket, return_dtype=pl.Utf8))
    rows = []
    for _, _, name in AGE_BUCKETS:
        b = sr.filter(pl.col("bucket") == name)
        # Mean over set-days of the set's median daily return, scaled to 30 days.
        m, t = _mean_t(b["r"].to_numpy()) if b.height else (None, None)
        rows.append({"set_age": name, "set_days": b.height, "sets": b["set_id"].n_unique() if b.height else 0,
                     "mean_30d_pct": _pct(m * 30) if m is not None else None, "t": t})
    return {"ready": True, "waiting_days": 0, "rows": rows}


# ---------------------------------------------------------------- reprints

def reprint_events(catalog: pl.DataFrame, announced: pl.DataFrame | None = None) -> pl.DataFrame:
    """(key, by, event_date, kind): the release of every later printing of the
    same card text (`by` = "text_key"; by name for a lake without text keys),
    and the owner's announcement dates (`by` = "name")."""
    ev = []
    if not catalog.is_empty():
        by = "text_key" if "text_key" in catalog.columns else "name"
        c = (catalog.filter(pl.col("release_date").is_not_null() & pl.col(by).is_not_null())
             .group_by(by).agg(dates=pl.col("release_date").unique().sort()))
        for key, dates in c.iter_rows():
            for d in dates[1:]:
                ev.append({"key": key, "by": by, "event_date": d, "kind": "release"})
    if announced is not None and not announced.is_empty():
        for name, d in announced.select("name", "announced").iter_rows():
            ev.append({"key": name, "by": "name", "event_date": str(d)[:10], "kind": "announced"})
    return pl.DataFrame(ev, schema={"key": pl.Utf8, "by": pl.Utf8, "event_date": pl.Utf8, "kind": pl.Utf8})


def _join_events(frame: pl.DataFrame, events: pl.DataFrame) -> pl.DataFrame:
    """Each row of `frame` with every event of its card text or its name."""
    parts = []
    for by in ("text_key", "name"):
        e = events.filter(pl.col("by") == by)
        if by in frame.columns and not e.is_empty():
            parts.append(frame.join(e.drop("by").rename({"key": by}), on=by, how="inner"))
    return pl.concat(parts, how="diagonal_relaxed") if parts else frame.clear().with_columns(
        event_date=pl.lit(None, pl.Utf8), kind=pl.lit(None, pl.Utf8))


def mark_reprints(snap: pl.DataFrame, events: pl.DataFrame, window: int = REPRINT_WINDOW) -> pl.DataFrame:
    """`reprinted` for each card: a reprint event of its text (or an announcement
    for its name) after its own set's release and within `window` days before
    the snapshot."""
    cols = [c for c in ("card_id", "name", "text_key", "date", "release_date") if c in snap.columns]
    j = _join_events(snap.select(cols), events)
    if j.is_empty():
        return snap.with_columns(reprinted=pl.lit(False))
    j = (j.with_columns(age=(pl.col("date").str.to_date() - pl.col("event_date").str.to_date()).dt.total_days())
         .filter((pl.col("event_date") > pl.col("release_date")) & pl.col("age").is_between(0, window))
         .select("card_id", "date").unique().with_columns(reprinted=pl.lit(True)))
    return snap.join(j, on=["card_id", "date"], how="left").with_columns(pl.col("reprinted").fill_null(False))


def reprint_cross(snap: pl.DataFrame) -> list[dict]:
    """Within each rarity group: median Cardmarket 30-day trend of reprinted vs other cards."""
    rows = []
    s = snap.filter(pl.col("cm_trend_30").is_not_null() & pl.col("cm_trend_30").is_not_nan())
    for g in sorted(s["rarity_group"].unique().to_list()):
        a = s.filter((pl.col("rarity_group") == g) & pl.col("reprinted"))
        b = s.filter((pl.col("rarity_group") == g) & ~pl.col("reprinted"))
        if a.height < 3 or b.height < 3:
            continue
        ma, mb = _med(a["cm_trend_30"]), _med(b["cm_trend_30"])
        rows.append({"rarity_group": g, "reprinted": a.height, "others": b.height,
                     "reprinted_trend_pct": _pct(ma), "others_trend_pct": _pct(mb),
                     "difference_pts": _pct(ma - mb) if ma is not None and mb is not None else None})
    return rows


def reprint_panel(df: pl.DataFrame, events: pl.DataFrame, days: int) -> dict:
    """Mean daily return of reprinted cards minus same-day same-rarity-group
    median, by days relative to the event (-30..+60), scaled to 30 days."""
    if days < PANEL_MIN_DAYS or events.is_empty():
        return {"ready": False, "waiting_days": max(PANEL_MIN_DAYS - days, 0), "rows": []}
    keep = [c for c in ("card_id", "name", "text_key", "date", "price", "price_src", "release_date", "rarity_group")
            if c in df.columns]
    d = (df.select(keep)
         .with_columns(_d=pl.col("date").str.to_date()).sort("card_id", "_d")
         .with_columns(r=(pl.col("price") / pl.col("price").shift(1).over("card_id")).log(),
                       gap=(pl.col("_d") - pl.col("_d").shift(1).over("card_id")).dt.total_days(),
                       same=pl.col("price_src") == pl.col("price_src").shift(1).over("card_id"))
         .filter(pl.col("same") & (pl.col("gap") <= 3))
         .with_columns(r=pl.col("r") / pl.col("gap")))
    d = d.with_columns(ex=pl.col("r") - pl.col("r").median().over("_d", "rarity_group"))
    j = (_join_events(d, events)
         .filter(pl.col("event_date") > pl.col("release_date"))
         .with_columns(rel=(pl.col("_d") - pl.col("event_date").str.to_date()).dt.total_days())
         .filter(pl.col("rel").is_between(-30, 60)))
    rows = []
    for lo, hi, name in ((-30, 0, "30 d before"), (0, 30, "first 30 d after"), (30, 60, "30-60 d after")):
        b = j.filter((pl.col("rel") >= lo) & (pl.col("rel") < hi))
        m, t = _mean_t(b["ex"].to_numpy()) if b.height else (None, None)
        rows.append({"window": name, "card_days": b.height, "cards": b["card_id"].n_unique() if b.height else 0,
                     "excess_30d_pct": _pct(m * 30) if m is not None else None, "t": t})
    return {"ready": True, "waiting_days": 0, "rows": rows}


# ---------------------------------------------------------------- premiums

def design(snap: pl.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Dummies for the hedonic regression; base = common, no character, Pokemon card."""
    cols, names = [np.ones(snap.height)], ["intercept"]
    for g in ("rare", "holo", "ultra", "chase", "promo", "other"):
        cols.append((snap["rarity_group"] == g).to_numpy().astype(float))
        names.append(f"rarity: {g}")
    for c in ("charizard", "pikachu", "eeveelution", "mew", "legendary_bird_dragon"):
        cols.append((snap["character"].fill_null("") == c).to_numpy().astype(float))
        names.append(f"character: {c}")
    cols.append(snap["alt_art"].fill_null(False).to_numpy().astype(float))
    names.append("alt art")
    cols.append(snap["secret"].fill_null(False).to_numpy().astype(float))
    names.append("secret number")
    age = snap["set_age_days"].fill_null(0).clip(0, None).to_numpy().astype(float)
    cols.append(np.log1p(age / 365.0))
    names.append("log(1 + set age in years)")
    cols.append((~snap["is_pokemon"].fill_null(True)).to_numpy().astype(float))
    names.append("trainer or energy")
    return np.column_stack(cols), names


def ols_hc1(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    ok = np.isfinite(y) & np.isfinite(X).all(axis=1)
    X, y = X[ok], y[ok]
    keep = X.std(axis=0) > 0
    keep[0] = True
    b = np.full(X.shape[1], np.nan)
    t = np.full(X.shape[1], np.nan)
    Xk = X[:, keep]
    n, k = Xk.shape
    if n <= k + 2:
        return b, t, float("nan")
    beta, *_ = np.linalg.lstsq(Xk, y, rcond=None)
    e = y - Xk @ beta
    xtx_inv = np.linalg.pinv(Xk.T @ Xk)
    meat = (Xk * e[:, None] ** 2).T @ Xk
    cov = xtx_inv @ meat @ xtx_inv * n / (n - k)
    se = np.sqrt(np.clip(np.diag(cov), 0, None))
    b[keep] = beta
    t[keep] = np.where(se > 0, beta / np.where(se > 0, se, 1), np.nan)
    r2 = 1 - (e @ e) / (((y - y.mean()) ** 2).sum() or 1)
    return b, t, float(r2)


def premiums(snap: pl.DataFrame) -> dict:
    X, names = design(snap)
    b, t, r2 = ols_hc1(X, snap["log_price"].to_numpy())
    rows = [{"feature": n, "premium_pct": _pct(math.exp(bi) - 1) if np.isfinite(bi) else None,
             "t": float(ti) if np.isfinite(ti) else None,
             "cards": int(X[:, i].sum()) if n not in ("intercept", "log(1 + set age in years)") else snap.height}
            for i, (n, bi, ti) in enumerate(zip(names, b, t)) if n != "intercept"]
    # The same features against the Cardmarket 30-day trend: who has been rising.
    # Only with enough fresh Cardmarket rows (stale ones are null in cm_trend_30).
    ytr = snap["cm_trend_30"].cast(pl.Float64).fill_nan(None).to_numpy().astype(float)
    if np.isfinite(ytr).sum() < TREND_MIN_CARDS:
        return {"r2": r2, "rows": rows, "trend_r2": None, "trend_rows": [], "cards": snap.height,
                "trend_cards": int(np.isfinite(ytr).sum())}
    tb, tt, tr2 = ols_hc1(X, ytr)
    trend = [{"feature": n, "trend_pts": _pct(bi) if np.isfinite(bi) else None,
              "t": float(ti) if np.isfinite(ti) else None}
             for n, bi, ti in zip(names, tb, tt) if n != "intercept"]
    return {"r2": r2, "rows": rows, "trend_r2": tr2, "trend_rows": trend, "cards": snap.height}


# ---------------------------------------------------------------- spread

def spread(snap: pl.DataFrame) -> dict:
    s = snap.filter(pl.col("spread").is_finite())
    if s.is_empty():
        return {"cards": 0, "rows": []}
    x = s["spread"].to_numpy()
    rows = []
    for lo, hi, name in ((0, 5, "under $5"), (5, 20, "$5-20"), (20, 100, "$20-100"), (100, 1e12, "$100 +")):
        b = s.filter((pl.col("tp_market") >= lo) & (pl.col("tp_market") < hi))
        if b.height:
            v = b["spread"].to_numpy()
            rows.append({"tcgplayer_price": name, "cards": b.height, "median_pct": _pct(math.exp(np.median(v)) - 1),
                         "share_us_30pct_dearer": float((v > math.log(1.3)).mean()),
                         "share_eu_30pct_dearer": float((v < -math.log(1.3)).mean())})
    return {"cards": s.height, "median_pct": _pct(math.exp(float(np.median(x))) - 1),
            "p25_pct": _pct(math.exp(float(np.quantile(x, 0.25))) - 1),
            "p75_pct": _pct(math.exp(float(np.quantile(x, 0.75))) - 1), "rows": rows}


def _pct(v):
    return None if v is None or not np.isfinite(v) else float(v) * 100.0


def run(df: pl.DataFrame, catalog: pl.DataFrame, announced: pl.DataFrame | None, days: int) -> dict:
    """All four studies on a featured frame (`data.features`)."""
    snap = latest(df)
    if catalog.is_empty():
        catalog = df.select([c for c in ("card_id", "name", "text_key", "release_date") if c in df.columns]).unique()
    events = reprint_events(catalog, announced)
    snap = mark_reprints(snap, events)
    return {
        "release": {"cross": release_cross(snap), "panel": release_panel(df, days)},
        "reprint": {"events": events.height, "reprinted_now": int(snap["reprinted"].sum()),
                    "cross": reprint_cross(snap), "panel": reprint_panel(df, events, days)},
        "premium": premiums(snap),
        "spread": spread(snap),
    }


def read_announced(root: Path) -> pl.DataFrame | None:
    p = root / "reprints.csv"
    if not p.exists():
        return None
    try:
        return pl.read_csv(p, columns=["name", "announced"], schema_overrides={"announced": pl.Utf8})
    except Exception:  # noqa: BLE001 - a hand-edited file; a broken one is skipped, not fatal
        return None
