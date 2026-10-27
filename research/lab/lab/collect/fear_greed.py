"""The Crypto Fear and Greed index of alternative.me, daily, with its full history once. Data only,
point in time (lab.collect.pit).

GET https://api.alternative.me/fng/?limit=N&format=json, no key (its published limit is 60
requests a minute over 10 minutes; we send one a run). limit=0 is the whole history from
2018-02-01: the first run asks for it, later runs for the last 10 days.

The value of a day is published at its 00:00 UTC (from the day before's data). Backfilled
rows are known at the day's 00:00 UTC plus one hour; a row stored more than 30 hours after
that counts as backfilled.

Table under $PYTHIA_FREE/fear_greed (with ts_us, collected_us, known_us, backfilled):
  daily     ts_us (the day), value (0 extreme fear to 100 extreme greed), classification

    python -m lab.collect.fear_greed [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

import polars as pl

from . import pit

SOURCE = "fear_greed"
API = "https://api.alternative.me/fng/?limit={}&format=json"
PUBLISH_US = pit.HOUR_US
LIVE_LAG_US = 30 * pit.HOUR_US
COLS = ["value", "classification"]


def parse(doc: object, now: int) -> pl.DataFrame:
    data = (doc or {}).get("data") if isinstance(doc, dict) else None
    if not isinstance(data, list):
        raise ValueError("fng: no data list in the answer")
    rows = [(int(r["timestamp"]) * 1_000_000, float(r["value"]), str(r.get("value_classification") or ""))
            for r in data if r.get("value") is not None and r.get("timestamp")]
    df = pl.DataFrame(rows, schema={"ts_us": pl.Int64, "value": pl.Float64, "classification": pl.Utf8},
                      orient="row")
    df = df.with_columns(ts_us=pl.col("ts_us") - pl.col("ts_us") % pit.DAY_US).filter(
        pl.col("ts_us") <= now).unique("ts_us", keep="first")
    late = now - (pl.col("ts_us") + PUBLISH_US) > LIVE_LAG_US
    return df.with_columns(collected_us=pl.lit(now, pl.Int64),
                           known_us=pl.when(late).then(pl.col("ts_us") + PUBLISH_US).otherwise(pl.lit(now, pl.Int64)),
                           backfilled=late).select(["ts_us"] + COLS + pit.PIT[1:]).sort("ts_us")


def run(dry: bool = False, fetch: pit.Fetch | None = None, now: int | None = None) -> dict:
    fetch = fetch or pit.paced(1.0)
    now = now or pit.now_us()
    errors: dict[str, str] = {}

    def do() -> None:
        limit = 0 if pit.last_ts(SOURCE, "daily") is None else 10
        pit.append(SOURCE, "daily", parse(fetch(API.format(limit)), now), ["ts_us"], dry)

    pit.step(errors, "daily", do)
    tables = {"daily": pit.table_health(SOURCE, "daily", COLS, pit.DAY_US, now)}
    return pit.write_health(SOURCE, tables, errors, dry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    a = ap.parse_args(argv)
    print(f"fear and greed -> {pit.FREE / SOURCE}", flush=True)
    return pit.exit_code(run(a.dry_run)["errors"], 1)


if __name__ == "__main__":
    sys.exit(main())
