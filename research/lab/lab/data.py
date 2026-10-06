"""Loaders for what pythia-recorder writes. Everything returns polars frames sorted by time."""

from __future__ import annotations

import os
from pathlib import Path

import polars as pl

ROOT = Path(os.environ.get("PYTHIA_DATA", "/data"))
HOUR_US = 3_600_000_000

UNIVERSE = [
    "BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT",
    "BCH", "TRX", "SUI", "NEAR", "ATOM", "UNI", "AAVE", "XLM", "PEPE", "FIL",
]


def live(source: str, table: str) -> pl.LazyFrame:
    """A recorded table across all days (compacted day files and today's parts)."""
    return pl.scan_parquet(ROOT / source / table / "**" / "*.parquet", hive_partitioning=True)


def klines_1m(symbol: str) -> pl.DataFrame:
    d = ROOT / "hist" / "binance_spot" / "klines_1m" / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return pl.DataFrame()
    return (pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
            .unique("open_time_us", keep="last").sort("open_time_us"))


def perp_symbol(base: str) -> str:
    return "1000PEPEUSDT" if base == "PEPE" else f"{base}USDT"


def _hist(kind: str, symbol: str) -> pl.DataFrame:
    d = ROOT / "hist" / "binance_um" / kind / f"symbol={symbol}"
    files = sorted(d.glob("*.parquet"))
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")


def funding(base: str) -> pl.DataFrame:
    """Settled funding rates; known from funding_time_us on."""
    f = _hist("funding", perp_symbol(base))
    if f.is_empty():
        return f
    return f.select("funding_time_us", "funding_rate").unique("funding_time_us").sort("funding_time_us")


def open_interest_hourly(base: str) -> pl.DataFrame:
    """Open interest at the end of each hour (5-minute metrics, last value per hour)."""
    m = _hist("metrics", perp_symbol(base))
    if m.is_empty():
        return m
    return (m.select("ts_us", "sum_open_interest_value")
            .with_columns(ts_us=(pl.col("ts_us") // HOUR_US) * HOUR_US)
            .group_by("ts_us").agg(oi_usd=pl.col("sum_open_interest_value").last())
            .sort("ts_us"))


def hourly(symbol: str) -> pl.DataFrame:
    """1h bars built from 1m klines, with realised variance from 1m log returns.

    ts_us is the START of the hour. Everything in a row is known at ts_us + 1h.
    """
    k = klines_1m(symbol)
    if k.is_empty():
        return k
    return (
        k.with_columns(
            r=(pl.col("close").log() - pl.col("close").shift(1).log()).fill_null(0.0),
            ts_us=(pl.col("open_time_us") // HOUR_US) * HOUR_US,
        )
        .group_by("ts_us", maintain_order=True)
        .agg(
            open=pl.col("open").first(),
            high=pl.col("high").max(),
            low=pl.col("low").min(),
            close=pl.col("close").last(),
            ret=pl.col("r").sum(),
            rv=(pl.col("r") ** 2).sum(),
            volume_q=pl.col("quote_volume").sum(),
            taker_buy_q=pl.col("taker_buy_quote_volume").sum(),
            trades=pl.col("trades").sum(),
            minutes=pl.len(),
        )
        .filter(pl.col("minutes") >= 50)  # drop hours the exchange was mostly down
        .with_columns(symbol=pl.lit(symbol))
        .sort("ts_us")
    )
