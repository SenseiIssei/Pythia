"""The feature registry and its one point-in-time call.

A feature has a name, the raw sources it reads, the native frequency of those
sources, the delay after which a live system knows it, and a function that
computes it from the hourly or daily table of its group. A group is one table
per frequency: (ts_us bucket start, asset, end_us, base columns), where end_us
is the moment the row's last input was received (the end of an hour or a day
bucket, or an observation's own time). A feature's value is known at
end_us + delay_us.

frame(names, assets, times, freq) gives, for every asset and time t, the
newest value known at or before t (and not older than the feature's max age,
one bucket by default), so nothing later than "known at" can reach a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import polars as pl

HOUR = 3_600_000_000
DAY = 24 * HOUR
PERIOD = {"1h": HOUR, "1d": DAY}
MARKET = "*"                 # the asset of a market-wide row: one value for every asset


@dataclass(frozen=True)
class Feature:
    name: str
    group: str
    sources: tuple[str, ...]
    native: str                          # how often the raw source updates: "5s", "trade", "60s", "8h", "1d"
    delay_us: int                        # after end_us until it is known
    fn: Callable[[int], pl.Expr]         # bucket length (us) -> the value from the group's columns
    level: bool = False                  # a dollar amount: trees use it only inside ret, ma or z
    market: bool = False                 # one value for all assets
    max_age_us: dict = field(default_factory=dict)   # freq -> how old a value may be at t (default one bucket)
    about: str = ""
    freqs: tuple = ("1h", "1d")          # where it is defined (a 24 h change is the daily change once a day)


@dataclass(frozen=True)
class Group:
    name: str
    sources: tuple[str, ...]
    table: Callable[[str, tuple | None], pl.DataFrame]   # (freq, assets or None) -> ts_us, asset, end_us, columns
    cached: bool = False                 # built day by day into the store (store.build)


GROUPS: dict[str, Group] = {}
REGISTRY: dict[str, Feature] = {}
_TABLES: dict = {}


def group(g: Group) -> Group:
    GROUPS[g.name] = g
    return g


def register(f: Feature) -> Feature:
    if f.group not in GROUPS:
        raise ValueError(f"{f.name}: unknown group {f.group}")
    REGISTRY[f.name] = f
    return f


def names() -> list[str]:
    return list(REGISTRY)


def get(name: str) -> Feature:
    return REGISTRY[name]


def clear() -> None:
    """Forget the tables read in this process (after the raw data or the cache changed)."""
    _TABLES.clear()


def table(name: str, freq: str, assets=None) -> pl.DataFrame:
    """A group's table at this frequency, memoised per process."""
    k = (name, freq, None if assets is None else tuple(sorted(assets)))
    if k not in _TABLES:
        t = GROUPS[name].table(freq, k[2])
        _TABLES[k] = t.sort("asset", "ts_us") if t.height else t
    return _TABLES[k]


def values(name: str, freq: str = "1h", assets=None) -> pl.DataFrame:
    """A feature's native rows at this frequency: (asset, ts_us, known_us, value), every bucket with a value."""
    f = REGISTRY[name]
    t = table(f.group, freq, None if f.market or assets is None else list(assets)) if freq in f.freqs else pl.DataFrame()
    if not t.height:
        return pl.DataFrame(schema={"asset": pl.String, "ts_us": pl.Int64, "known_us": pl.Int64, "value": pl.Float64})
    return (t.select("asset", "ts_us", known_us=pl.col("end_us") + f.delay_us,
                     value=f.fn(PERIOD[freq]).cast(pl.Float64))
            .filter(pl.col("value").is_not_null() & pl.col("value").is_finite()))


def frame(names_: list[str], assets, times, freq: str = "1h") -> pl.DataFrame:
    """(ts_us, asset, one column per feature): at each time t the newest value known at or before t,
    null when there is none or it is older than the feature's max age."""
    if freq not in PERIOD:
        raise ValueError(f"freq {freq}: 1h or 1d")
    assets = list(dict.fromkeys(assets))
    ts = np.unique(np.asarray(list(times), dtype=np.int64))
    grid = (pl.DataFrame({"ts_us": ts}, schema={"ts_us": pl.Int64})
            .join(pl.DataFrame({"asset": assets}, schema={"asset": pl.String}), how="cross")
            .sort("ts_us"))
    for n in names_:
        f = REGISTRY[n]
        v = values(n, freq, assets).select("asset", "known_us", pl.col("value").alias(n))
        age = f.max_age_us.get(freq, PERIOD[freq]) - 1
        if f.market:
            v = v.filter(pl.col("asset") == MARKET).drop("asset").sort("known_us")
            col = (pl.DataFrame({"ts_us": ts}, schema={"ts_us": pl.Int64})
                   .join_asof(v, left_on="ts_us", right_on="known_us", strategy="backward", tolerance=age)
                   .drop("known_us"))
            grid = grid.join(col, on="ts_us", how="left")
        else:
            v = v.filter(pl.col("asset").is_in(assets)).sort("known_us")
            grid = (grid.sort("ts_us")
                    .join_asof(v, left_on="ts_us", right_on="known_us", by="asset", strategy="backward",
                               tolerance=age, check_sortedness=False)
                    .drop("known_us"))
    return grid.sort("ts_us", "asset")


def gap_ok(period: int) -> pl.Expr:
    """True where the row before (same asset) is exactly one bucket earlier: a change needs its neighbour."""
    return pl.col("ts_us").diff().over("asset") == period


def change(col: str, period: int) -> pl.Expr:
    return pl.when(gap_ok(period)).then(pl.col(col) - pl.col(col).shift(1).over("asset"))


def pct_change(col: str, period: int, lag: int = 1) -> pl.Expr:
    prev = pl.col(col).shift(lag).over("asset")
    ok = (pl.col("ts_us") - pl.col("ts_us").shift(lag).over("asset")) == period * lag
    return pl.when(ok & (prev > 0)).then(pl.col(col) / prev - 1)


def daily(hourly: pl.DataFrame, spec: dict, min_hours: int = 12) -> pl.DataFrame:
    """Hourly base rows to one row per UTC day: spec maps a column to "sum", "last", "max" or
    ("wmean", weight column); days with fewer than min_hours hourly rows are dropped."""
    if not hourly.height:
        return hourly.with_columns(hours=pl.lit(0, pl.UInt32))
    aggs = [pl.len().alias("hours")]
    for c, how in spec.items():
        if c not in hourly.columns:
            continue
        if how == "sum":
            aggs.append(pl.col(c).sum())
        elif how == "last":
            aggs.append(pl.col(c).drop_nulls().last())
        elif how == "max":
            aggs.append(pl.col(c).max())
        else:
            w = pl.col(how[1]).fill_null(0)
            aggs.append(pl.when(w.filter(pl.col(c).is_not_null()).sum() > 0)
                        .then((pl.col(c) * w).sum() / w.filter(pl.col(c).is_not_null()).sum()).alias(c))
    return (hourly.sort("ts_us").with_columns(ts_us=(pl.col("ts_us") // DAY) * DAY)
            .group_by("asset", "ts_us").agg(aggs)
            .filter(pl.col("hours") >= min_hours))
