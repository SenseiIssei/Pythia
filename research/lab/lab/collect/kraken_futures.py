"""Kraken Futures funding history and hourly mark prices, public endpoints only (no key).

    python -m lab.collect.kraken_futures [--out DIR] [--coins BTC,ETH,...]

For every Alpaca coin (lab.universe.ALPACA) that Kraken Futures lists as a PF_
perpetual: the hourly funding history (`/derivatives/api/v4/historicalfundingrates`,
which serves about the last year, from 2025-10-15 when checked on 2026-10-21) and
hourly mark-price candles over the same span (`/api/charts/v1/mark/<symbol>/1h`,
2,000 candles a request). Each run merges with what is on disk, so the history grows
past the endpoint's one-year window. Written to <out>/funding/<symbol>.parquet
(ts_us, rate: relativeFundingRate, a share of the price per hour, positive = longs
pay) and <out>/mark_1h/<symbol>.parquet (ts_us = candle open, close). Default out:
<data>/kraken_futures. Information and research only: nothing here can trade.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from ..data import ROOT
from ..experiments.perps_common import ALIASES
from ..universe import ALPACA
from .flow import get_json

BASE = "https://futures.kraken.com"
FUNDING = BASE + "/derivatives/api/v4/historicalfundingrates?symbol={sym}"
MARK = BASE + "/api/charts/v1/mark/{sym}/1h?from={a}&to={b}"
INSTRUMENTS = BASE + "/derivatives/api/v3/instruments"
PAUSE = 0.17          # at most about 6 requests a second
HOUR_US = 3_600_000_000


def listing() -> dict[str, str]:
    """{coin: PF symbol} of the tradeable PF_ perpetuals."""
    ans = get_json(INSTRUMENTS, pause=PAUSE)
    out: dict[str, str] = {}
    for ins in ans.get("instruments") or []:
        sym = str(ins.get("symbol", ""))
        if not sym.startswith("PF_") or ins.get("tradeable") is not True or ins.get("suspended", False):
            continue
        base = ins.get("base") or (sym[3:-3] if sym.endswith("USD") else "")
        if base:
            out.setdefault(ALIASES.get(base, base), sym)
    return out


def ts_of(iso: str) -> int:
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1e6)


def funding(sym: str) -> pl.DataFrame:
    rates = get_json(FUNDING.format(sym=sym), pause=PAUSE).get("rates") or []
    return pl.DataFrame({"ts_us": [ts_of(r["timestamp"]) for r in rates],
                         "rate": [float(r["relativeFundingRate"]) for r in rates]},
                        schema={"ts_us": pl.Int64, "rate": pl.Float64})


def mark(sym: str, start_us: int, end_us: int) -> pl.DataFrame:
    rows, a = [], start_us // 1_000_000
    end = end_us // 1_000_000
    while a < end:
        d = get_json(MARK.format(sym=sym, a=a, b=end), pause=PAUSE)
        c = d.get("candles") or []
        if not c:
            break
        rows += [(int(x["time"]) * 1000, float(x["close"])) for x in c]
        a = int(c[-1]["time"]) // 1000 + 3600
        if not d.get("more_candles"):
            break
    return pl.DataFrame(rows, schema={"ts_us": pl.Int64, "close": pl.Float64}, orient="row")


def merge(path: Path, new: pl.DataFrame) -> pl.DataFrame:
    if path.exists():
        new = pl.concat([pl.read_parquet(path), new], how="vertical_relaxed")
    out = new.unique("ts_us", keep="last").sort("ts_us")
    path.parent.mkdir(parents=True, exist_ok=True)
    out.write_parquet(path)
    return out


def collect(out: Path, coins: list[str] | None = None) -> dict:
    lst = listing()
    coins = [c for c in (coins or ALPACA) if c in lst]
    now_us = int(time.time() * 1e6)
    done = {}
    for c in coins:
        sym = lst[c]
        f = merge(out / "funding" / f"{sym}.parquet", funding(sym))
        if f.height == 0:
            continue
        start = int(f["ts_us"].min())
        mp = out / "mark_1h" / f"{sym}.parquet"
        if mp.exists():
            start = max(start, int(pl.read_parquet(mp)["ts_us"].max()) - 2 * HOUR_US)
        m = merge(mp, mark(sym, start, now_us))
        done[c] = {"symbol": sym, "funding_hours": f.height, "mark_hours": m.height,
                   "from": datetime.fromtimestamp(int(f["ts_us"].min()) / 1e6, timezone.utc).isoformat()}
        print(c, done[c], flush=True)
    return done


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "kraken_futures"))
    ap.add_argument("--coins", default="")
    a = ap.parse_args(argv)
    coins = [x.strip().upper() for x in a.coins.split(",") if x.strip()] or None
    collect(Path(a.out), coins)
    return 0


if __name__ == "__main__":
    sys.exit(main())
