"""CS2 market data from the collector's lake, and the fee arithmetic.

Everything is in euro. Prices come from two venues that do not share money:
Steam pays sellers in Steam wallet funds that cannot be withdrawn, Skinport
pays out cash. Items bought on Skinport arrive with a 7-day trade protection,
items bought on Steam are trade-locked for 7 days. The gaps below are what a
hand trade would net after fees, not a free lunch; nothing here trades.
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

from ..collect.cs2 import WATCHLIST, cs2_root, load_watchlist

STEAM_FEE_STEAM = 0.05   # Steam's own transaction fee, at least 0.01
STEAM_FEE_GAME = 0.10    # CS2's publisher fee, at least 0.01 (together about 15 % of what the seller gets)
SKINPORT_SALE_FEE = 0.08  # Skinport's seller fee (check the current rate; high-value items may pay less)
TICK = 0.01


# ---------------------------------------------------------------- fees

def steam_buyer_pays(seller_gets: float) -> float:
    """What a buyer pays for a listing that nets the seller `seller_gets`."""
    c = int(round(seller_gets * 100))
    fee = max(1, math.floor(c * STEAM_FEE_STEAM)) + max(1, math.floor(c * STEAM_FEE_GAME))
    return (c + fee) / 100


def steam_seller_gets(buyer_pays: float) -> float:
    """What the seller nets (in Steam wallet funds) when a buyer pays `buyer_pays`."""
    b = int(round(buyer_pays * 100))
    if b < 3:
        return 0.0
    s = max(1, int(b / (1 + STEAM_FEE_STEAM + STEAM_FEE_GAME)))
    while s > 1 and steam_buyer_pays(s / 100) > b / 100 + 1e-9:
        s -= 1
    while steam_buyer_pays((s + 1) / 100) <= b / 100 + 1e-9:
        s += 1
    return s / 100


def skinport_seller_gets(price: float, fee: float = SKINPORT_SALE_FEE) -> float:
    return price * (1 - fee)


def gaps(skinport_ask: float | None, steam_ask: float | None, fee: float = SKINPORT_SALE_FEE) -> dict:
    """Both hand routes between the venues, net of fees, undercutting the other side by one cent.

    to_steam:    buy on Skinport at its lowest ask, list on Steam one cent under
                 its lowest ask; nets Steam wallet funds (not cash).
    to_skinport: buy on Steam at its lowest ask, list on Skinport one cent under
                 its lowest ask; nets cash after Skinport's fee, 7 days later.
    """
    out = {"to_steam": None, "to_skinport": None}
    if skinport_ask and steam_ask and skinport_ask > 0 and steam_ask > 0:
        out["to_steam"] = steam_seller_gets(max(steam_ask - TICK, TICK)) / skinport_ask - 1
        out["to_skinport"] = skinport_seller_gets(max(skinport_ask - TICK, TICK), fee) / steam_ask - 1
    return out


def round_trip_cost(fee: float = SKINPORT_SALE_FEE, spread: float = 0.02) -> float:
    """Buy at the ask, sell one tick under it later and pay the fee: the hurdle a
    Skinport position has to clear, with a spread allowance for thin books."""
    return fee + spread


# ---------------------------------------------------------------- loading

def _scan(d: Path) -> pl.DataFrame:
    files = sorted(d.glob("date=*.parquet"))
    if not files:
        return pl.DataFrame()
    frames = []
    for f in files:
        day = f.stem.split("=", 1)[1]
        frames.append(pl.read_parquet(f).with_columns(date=pl.lit(day).str.to_date()))
    return pl.concat(frames, how="diagonal_relaxed")


def daily_skinport(root: Path | None = None) -> pl.DataFrame:
    """One row per item and day: the day's last Skinport snapshot with its sales stats."""
    return _scan(cs2_root(root) / "daily" / "skinport")


def daily_steam(root: Path | None = None) -> pl.DataFrame:
    return _scan(cs2_root(root) / "daily" / "steam")


def latest_daily(root: Path | None, source: str) -> pl.DataFrame:
    """The newest daily file of `source` (skinport or steam)."""
    files = sorted((cs2_root(root) / "daily" / source).glob("date=*.parquet"))
    return pl.read_parquet(files[-1]) if files else pl.DataFrame()


def latest_hourly(root: Path | None = None, table: str = "skinport_items", back: int = 0) -> pl.DataFrame:
    """The newest hourly snapshot of a table, or the one `back` runs before it."""
    files = sorted((cs2_root(root) / table).glob("date=*/*.parquet"))
    if len(files) <= back:
        return pl.DataFrame()
    return pl.read_parquet(files[-1 - back])


def hourly_at(root: Path | None, table: str, ts_ms: int) -> pl.DataFrame:
    """The last hourly snapshot taken at or before ts_ms."""
    best = None
    for f in sorted((cs2_root(root) / table).glob("date=*/*.parquet")):
        day, hhmm = f.parent.name.split("=", 1)[1], f.stem
        try:
            t = datetime.strptime(f"{day} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if t.timestamp() * 1000 <= ts_ms:
            best = f
    return pl.read_parquet(best) if best is not None else pl.DataFrame()


# ---------------------------------------------------------------- items

def category(name: str) -> str:
    n = name.lower()
    if n.startswith("sticker |") or "sticker capsule" in n or n.endswith("capsule"):
        return "sticker"
    if n.endswith(" case") or n.endswith("weapon case") or n == "cs:go weapon case":
        return "case"
    if n.startswith("★"):
        return "knife_glove"
    if " | " in name and "(" in name:
        return "skin"
    if n.startswith("music kit"):
        return "music_kit"
    return "other"


CATEGORIES = ["case", "sticker", "skin", "knife_glove", "music_kit", "other"]


def case_release_dates(watch: dict | None = None) -> dict[str, date]:
    watch = watch if watch is not None else load_watchlist(WATCHLIST)
    out = {}
    for c in watch.get("cases") or []:
        try:
            out[c["name"]] = date.fromisoformat(c["released"])
        except (KeyError, ValueError):
            continue
    return out


def with_meta(df: pl.DataFrame, asof: date, watch: dict | None = None) -> pl.DataFrame:
    """Adds category, its code and the case age in days (null when not a known case)."""
    rel = case_release_dates(watch)
    names = df["name"].to_list()
    cats = [category(n) for n in names]
    age = [float((asof - rel[n]).days) if n in rel else None for n in names]
    return df.with_columns(category=pl.Series(cats, dtype=pl.Utf8),
                           cat_code=pl.Series([CATEGORIES.index(c) for c in cats], dtype=pl.Int64),
                           case_age_days=pl.Series(age, dtype=pl.Float64))


# ---------------------------------------------------------------- the sales windows as buckets

def buckets(df: pl.DataFrame, min_sales: int = 3) -> pl.DataFrame:
    """Skinport's nested 7/30/90-day sales windows split into disjoint ones.

    Each window's average times its volume is its turnover, so
      days 0-7    avg7
      days 7-30   (avg30*v30 - avg7*v7) / (v30 - v7)
      days 30-90  (avg90*v90 - avg30*v30) / (v90 - v30)
    A bucket with fewer than `min_sales` sales, or an implied average outside
    the 90-day min and max (the windows were not computed together), is null.
    """
    v7, v30, v90 = (pl.col(f"s{w}_volume").fill_null(0) for w in (7, 30, 90))
    a7, a30, a90 = (pl.col(f"s{w}_avg") for w in (7, 30, 90))
    lo, hi = pl.col("s90_min"), pl.col("s90_max")

    def ok(x, n):
        return pl.when((n >= min_sales) & x.is_not_null() & (x > 0) & (x >= lo * 0.999) & (x <= hi * 1.001)).then(x)

    b7_30 = (a30 * v30 - a7.fill_null(0) * v7) / (v30 - v7)
    b30_90 = (a90 * v90 - a30.fill_null(0) * v30) / (v90 - v30)
    return df.with_columns(
        b0_7=ok(a7, v7),
        b7_30=ok(b7_30, v30 - v7),
        b30_90=ok(b30_90, v90 - v30),
        n0_7=v7, n7_30=v30 - v7, n30_90=v90 - v30,
    )


# ---------------------------------------------------------------- reference prices

def ref_price(df: pl.DataFrame) -> pl.Expr:
    """What an item is worth now: the 24h sales median with 3 sales or more,
    else the 7-day median, else the lowest Skinport ask."""
    return (pl.when(pl.col("s24_volume").fill_null(0) >= 3).then(pl.col("s24_median"))
            .when(pl.col("s7_volume").fill_null(0) >= 3).then(pl.col("s7_median"))
            .otherwise(pl.col("min_price")))


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def finite(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None
