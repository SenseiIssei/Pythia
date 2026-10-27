"""Deribit implied volatility, hourly: BTC and ETH DVOL, ATM IV and 25-delta skew at 7, 30 and 90
days, put/call open interest. Data only, point in time (lab.collect.pit).

Deribit's public API, no key. Two kinds of request:
  public/get_volatility_index_data   DVOL hourly candles (1000 a request, paged backwards through
                                     its continuation); history from 2021-03-24, backfilled once
  public/get_book_summary_by_currency  today's book of every option (mark IV, underlying, open
                                     interest): ATM IV and the 25-delta risk reversal per expiry,
                                     interpolated in days to 7, 30 and 90 (lab.collect.flow's
                                     skew_row), and the open interest of puts and calls
Public requests are limited by credits (about 20 a second without a key); we send at most one
every 0.3 s and about 4 a run.

Tables under $PYTHIA_FREE/deribit (with ts_us, collected_us, known_us, backfilled):
  dvol      ts_us (hour open), currency, open, high, low, close; known at the hour's close (backfill)
  surface   ts_us (the snapshot), currency, atm_7, atm_30, atm_90, rr25_7, rr25_30, rr25_90
            (IV as a fraction, call minus put), days_7, days_30, days_90 (the days actually used,
            the nearest expiry when a target is outside), oi_call, oi_put (coins), pc_oi, n_options.
            Deribit serves no history of these without a key: live only, from the first run.

    python -m lab.collect.deribit_vol [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
from datetime import datetime

import polars as pl

from . import pit
from .flow import parse_instrument, skew_row

SOURCE = "deribit"
API = "https://www.deribit.com/api/v2/public"
CURRENCIES = ("BTC", "ETH")
DVOL_START_MS = 1616544000000  # 2021-03-24, the first DVOL candle
TENORS = (7, 30, 90)
LIVE_LAG_US = 2 * pit.HOUR_US  # a candle stored later than this after its close counts as backfilled
DVOL_COLS = ["currency", "open", "high", "low", "close"]
SURFACE_COLS = ["currency"] + [f"{k}_{d}" for k in ("atm", "rr25", "days") for d in TENORS] + \
    ["oi_call", "oi_put", "pc_oi", "n_options"]


def dvol(fetch: pit.Fetch, currency: str, start_ms: int, now: int) -> pl.DataFrame:
    """Closed hourly DVOL candles from start_ms, stamped: backfilled when stored more than 2 h after the close."""
    end_ms = now // 1000
    rows: list[list] = []
    while end_ms > start_ms:
        q = urllib.parse.urlencode({"currency": currency, "start_timestamp": start_ms, "end_timestamp": end_ms,
                                    "resolution": 3600})
        res = (fetch(f"{API}/get_volatility_index_data?{q}") or {}).get("result") or {}
        data = res.get("data") or []
        rows.extend(data)
        nxt = res.get("continuation")
        if not data or not nxt or int(nxt) >= end_ms:
            break
        end_ms = int(nxt)
    df = pl.DataFrame({"ts_us": [int(r[0]) * 1000 for r in rows], "open": [float(r[1]) for r in rows],
                       "high": [float(r[2]) for r in rows], "low": [float(r[3]) for r in rows],
                       "close": [float(r[4]) for r in rows]},
                      schema={"ts_us": pl.Int64, "open": pl.Float64, "high": pl.Float64, "low": pl.Float64,
                              "close": pl.Float64})
    df = df.filter(pl.col("ts_us") + pit.HOUR_US <= now).unique("ts_us", keep="last").sort("ts_us") \
        .with_columns(currency=pl.lit(currency))
    close = pl.col("ts_us") + pit.HOUR_US
    late = now - close > LIVE_LAG_US
    return df.with_columns(collected_us=pl.lit(now, pl.Int64),
                           known_us=pl.when(late).then(close).otherwise(pl.lit(now, pl.Int64)),
                           backfilled=late).select(["ts_us"] + DVOL_COLS + pit.PIT[1:])


def surface_row(snap: list[dict], now: datetime, currency: str) -> dict | None:
    """ATM IV and 25-delta risk reversal at 7, 30 and 90 days, and the open interest of calls and puts."""
    if not snap:
        return None
    out: dict = {"currency": currency, "n_options": len(snap)}
    for d in TENORS:
        r = skew_row(snap, now, currency, float(d))
        out[f"atm_{d}"] = r["atm_iv"] if r else None
        out[f"rr25_{d}"] = r["rr25"] if r else None
        out[f"days_{d}"] = r["days"] if r else None
    oi = {"C": 0.0, "P": 0.0}
    for o in snap:
        p = parse_instrument(o.get("instrument_name", ""))
        if p is not None and o.get("open_interest") is not None:
            oi[p[2]] = oi.get(p[2], 0.0) + float(o["open_interest"])
    out["oi_call"], out["oi_put"] = oi["C"], oi["P"]
    out["pc_oi"] = oi["P"] / oi["C"] if oi["C"] > 0 else None
    return out


def snapshot(fetch: pit.Fetch, currency: str) -> list[dict]:
    q = urllib.parse.urlencode({"currency": currency, "kind": "option"})
    return (fetch(f"{API}/get_book_summary_by_currency?{q}") or {}).get("result") or []


def run(dry: bool = False, fetch: pit.Fetch | None = None, now: int | None = None) -> dict:
    fetch = fetch or pit.paced(0.3)
    now = now or pit.now_us()
    errors: dict[str, str] = {}

    def do_dvol() -> None:
        frames = []
        for cur in CURRENCIES:
            last = pit.last_ts(SOURCE, "dvol", "currency", cur)
            start = DVOL_START_MS if last is None else (last - 3 * pit.HOUR_US) // 1000
            frames.append(dvol(fetch, cur, start, now))
        pit.append(SOURCE, "dvol", pl.concat(frames), ["currency", "ts_us"], dry)

    def do_surface() -> None:
        t = datetime.fromtimestamp(now / 1e6, pit.UTC)
        rows = [r for cur in CURRENCIES if (r := surface_row(snapshot(fetch, cur), t, cur))]
        if not rows:
            raise RuntimeError("no option snapshot")
        df = pl.DataFrame(rows, schema={c: (pl.Utf8 if c == "currency" else pl.Int64 if c == "n_options"
                                            else pl.Float64) for c in SURFACE_COLS})
        df = pit.stamp(df.with_columns(ts_us=pl.lit(now, pl.Int64)), now)
        pit.append(SOURCE, "surface", df.select(["ts_us"] + SURFACE_COLS + pit.PIT[1:]), ["currency", "ts_us"], dry)

    pit.step(errors, "dvol", do_dvol)
    pit.step(errors, "surface", do_surface)
    tables = {"dvol": pit.table_health(SOURCE, "dvol", DVOL_COLS, pit.HOUR_US, now, by="currency"),
              "surface": pit.table_health(SOURCE, "surface", SURFACE_COLS, pit.HOUR_US, now, by="currency")}
    return pit.write_health(SOURCE, tables, errors, dry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    a = ap.parse_args(argv)
    print(f"deribit vol -> {pit.FREE / SOURCE}", flush=True)
    return pit.exit_code(run(a.dry_run)["errors"], 2)


if __name__ == "__main__":
    sys.exit(main())
