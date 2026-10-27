"""DefiLlama, daily: stablecoin supply (all, USDT, USDC) and its daily change, DEX volume in total and
on Solana, Solana's TVL. Data only, point in time (lab.collect.pit).

DefiLlama's free API, no key (the free tier allows hundreds of requests a minute; we send six a
run, one every 2 s). Every answer is the whole daily history, so the first run is the backfill:
  stablecoins.llama.fi/stablecoincharts/all[?stablecoin=1|2]   circulating USD (all, USDT, USDC)
  api.llama.fi/overview/dexs[/solana]?dataType=dailyVolume     DEX volume per day
  api.llama.fi/v2/historicalChainTvl/Solana                    TVL per day
Only closed UTC days are kept.

Table under $PYTHIA_FREE/defillama, long (with ts_us, collected_us, known_us, backfilled):
  daily     ts_us (the day), series, value. Series: stables_total, usdt, usdc (USD in
            circulation), stables_total_chg, usdt_chg, usdc_chg (against the day before),
            dex_volume, dex_volume_solana (USD), tvl_solana (USD).
A day's value is known after the day has closed and DefiLlama has written it: for backfilled
rows we take the close plus 2 hours, and a row stored more than 30 hours after the close counts
as backfilled.

    python -m lab.collect.defillama [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

import polars as pl

from . import pit

SOURCE = "defillama"
STABLES = "https://stablecoins.llama.fi/stablecoincharts/all"
DEX = "https://api.llama.fi/overview/dexs{}?excludeTotalDataChart=false&excludeTotalDataChartBreakdown=true" \
      "&dataType=dailyVolume"
TVL = "https://api.llama.fi/v2/historicalChainTvl/Solana"
PUBLISH_US = 2 * pit.HOUR_US
LIVE_LAG_US = 30 * pit.HOUR_US
SERIES = ("stables_total", "usdt", "usdc", "stables_total_chg", "usdt_chg", "usdc_chg", "dex_volume",
          "dex_volume_solana", "tvl_solana")
COLS = ["series", "value"]


def stable_series(doc: object) -> dict[int, float]:
    out = {}
    for r in doc if isinstance(doc, list) else []:
        v = (r.get("totalCirculatingUSD") or {}).get("peggedUSD")
        if v is not None:
            out[int(r["date"]) * 1_000_000] = float(v)
    return out


def chart_series(doc: object) -> dict[int, float]:
    """[[unix seconds, value], ...] of a DEX overview's totalDataChart."""
    rows = (doc or {}).get("totalDataChart") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise ValueError("no totalDataChart in the answer")
    return {int(t) * 1_000_000: float(v) for t, v in rows if v is not None}


def tvl_series(doc: object) -> dict[int, float]:
    if not isinstance(doc, list):
        raise ValueError("TVL: expected a list")
    return {int(r["date"]) * 1_000_000: float(r["tvl"]) for r in doc if r.get("tvl") is not None}


def change(s: dict[int, float]) -> dict[int, float]:
    """The change against the day before (only where the day before is there)."""
    return {d: v - s[d - pit.DAY_US] for d, v in s.items() if d - pit.DAY_US in s}


def frame(series: dict[str, dict[int, float]], now: int) -> pl.DataFrame:
    today = pit.us_of(pit.day_of(now))
    rows = [(d - d % pit.DAY_US, name, v) for name, s in series.items() for d, v in s.items()]
    df = pl.DataFrame(rows, schema={"ts_us": pl.Int64, "series": pl.Utf8, "value": pl.Float64}, orient="row")
    df = df.filter(pl.col("ts_us") < today).unique(["series", "ts_us"], keep="last")
    close = pl.col("ts_us") + pit.DAY_US
    late = now - close > LIVE_LAG_US
    return df.with_columns(collected_us=pl.lit(now, pl.Int64),
                           known_us=pl.when(late).then(close + PUBLISH_US).otherwise(pl.lit(now, pl.Int64)),
                           backfilled=late).select(["ts_us"] + COLS + pit.PIT[1:])


def run(dry: bool = False, fetch: pit.Fetch | None = None, now: int | None = None) -> dict:
    fetch = fetch or pit.paced(2.0)
    now = now or pit.now_us()
    errors: dict[str, str] = {}
    series: dict[str, dict[int, float]] = {}

    def stables() -> None:
        for name, q in (("stables_total", ""), ("usdt", "?stablecoin=1"), ("usdc", "?stablecoin=2")):
            s = stable_series(fetch(STABLES + q))
            if not s:
                raise ValueError(f"{name}: no rows")
            series[name], series[name + "_chg"] = s, change(s)

    def dex() -> None:
        series["dex_volume"] = chart_series(fetch(DEX.format("")))
        series["dex_volume_solana"] = chart_series(fetch(DEX.format("/solana")))

    def tvl() -> None:
        series["tvl_solana"] = tvl_series(fetch(TVL))

    for name, fn in (("stables", stables), ("dex", dex), ("tvl", tvl)):
        pit.step(errors, name, fn)
    if series:
        pit.append(SOURCE, "daily", frame(series, now), ["series", "ts_us"], dry)
    tables = {"daily": pit.table_health(SOURCE, "daily", COLS, pit.DAY_US, now, by="series")}
    return pit.write_health(SOURCE, tables, errors, dry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    a = ap.parse_args(argv)
    print(f"defillama -> {pit.FREE / SOURCE}", flush=True)
    return pit.exit_code(run(a.dry_run)["errors"], 3)


if __name__ == "__main__":
    sys.exit(main())
