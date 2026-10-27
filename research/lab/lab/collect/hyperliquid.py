"""Hyperliquid perps, hourly: funding, open interest and the mark/oracle premium of the coins in
Pythia's universe. Data only, point in time (lab.collect.pit).

Hyperliquid's public info API (POST https://api.hyperliquid.xyz/info, no key). Its limit is
1200 weight a minute per IP: metaAndAssetCtxs weighs 20, fundingHistory 20 plus one per 20
rows. We send one request every 1.5 s (at most 800 weight a minute) and at most
BACKFILL_REQUESTS funding pages a run, so the first runs share the backfill.

  metaAndAssetCtxs   the snapshot of every perp: funding (the current hourly rate), open
                     interest, mark, oracle and mid price, Hyperliquid's premium, day volume
  fundingHistory     each coin's settled hourly funding and premium (500 a page), history from
                     2023-05-12, backfilled once per coin, then continued

Coins: lab.universe.ENGINE as Hyperliquid names them (BONK, PEPE and SHIB as kBONK, kPEPE,
kSHIB, a thousand coins each), the ones it lists and has not delisted.

Tables under $PYTHIA_FREE/hyperliquid (with ts_us, collected_us, known_us, backfilled):
  ctx       ts_us (the snapshot), coin, funding, open_interest (coins), oi_usd, mark, oracle, mid,
            premium (Hyperliquid's), mark_premium (mark / oracle - 1), day_volume_usd; live only
  funding   ts_us (the settlement), coin, funding_rate, premium; known at the settlement (backfill)

    python -m lab.collect.hyperliquid [--dry-run]
"""

from __future__ import annotations

import argparse
import sys

import polars as pl

from . import pit
from ..universe import ENGINE

SOURCE = "hyperliquid"
API = "https://api.hyperliquid.xyz/info"
HISTORY_START_MS = 1683849600000  # 2023-05-12, Hyperliquid's first funding
PAGE = 500
BACKFILL_REQUESTS = 400
LIVE_LAG_US = 2 * pit.HOUR_US
KILO = {"BONK": "kBONK", "PEPE": "kPEPE", "SHIB": "kSHIB", "FLOKI": "kFLOKI"}
CTX_COLS = ["coin", "funding", "open_interest", "oi_usd", "mark", "oracle", "mid", "premium", "mark_premium",
            "day_volume_usd"]
FUNDING_COLS = ["coin", "funding_rate", "premium"]


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def coins_listed(meta: dict, coins=ENGINE) -> list[str]:
    """Hyperliquid names of our coins that it lists and has not delisted, in our order."""
    live = {u.get("name") for u in (meta or {}).get("universe") or [] if not u.get("isDelisted")}
    return [KILO.get(c, c) for c in coins if KILO.get(c, c) in live]


def contexts(doc: list, coins: list[str], now: int) -> pl.DataFrame:
    """One row per coin of the metaAndAssetCtxs answer ([meta, [ctx, ...]], in the universe's order)."""
    meta, ctxs = doc[0], doc[1]
    want = set(coins)
    rows = []
    for u, c in zip(meta.get("universe") or [], ctxs):
        if u.get("name") not in want:
            continue
        mark, oracle, oi = _f(c.get("markPx")), _f(c.get("oraclePx")), _f(c.get("openInterest"))
        rows.append({"coin": u["name"], "funding": _f(c.get("funding")), "open_interest": oi,
                     "oi_usd": oi * oracle if oi is not None and oracle else None, "mark": mark, "oracle": oracle,
                     "mid": _f(c.get("midPx")), "premium": _f(c.get("premium")),
                     "mark_premium": mark / oracle - 1 if mark and oracle else None,
                     "day_volume_usd": _f(c.get("dayNtlVlm"))})
    df = pl.DataFrame(rows, schema={k: pl.Utf8 if k == "coin" else pl.Float64 for k in CTX_COLS})
    return pit.stamp(df.with_columns(ts_us=pl.lit(now, pl.Int64)), now).select(["ts_us"] + CTX_COLS + pit.PIT[1:])


def funding(fetch: pit.Fetch, coin: str, start_ms: int, now: int, budget: list[int]) -> pl.DataFrame:
    """Settled funding from start_ms, page by page while `budget[0]` requests are left."""
    rows: list[dict] = []
    t = start_ms
    while budget[0] > 0 and t < now // 1000:
        budget[0] -= 1
        page = fetch(API, {"type": "fundingHistory", "coin": coin, "startTime": t}) or []
        rows.extend(page)
        if len(page) < PAGE:
            break
        t = max(int(r["time"]) for r in page) + 1
    df = pl.DataFrame({"ts_us": [int(r["time"]) * 1000 for r in rows], "funding_rate": [_f(r.get("fundingRate"))
                                                                                      for r in rows],
                       "premium": [_f(r.get("premium")) for r in rows]},
                      schema={"ts_us": pl.Int64, "funding_rate": pl.Float64, "premium": pl.Float64})
    late = now - pl.col("ts_us") > LIVE_LAG_US
    return df.unique("ts_us", keep="last").sort("ts_us").with_columns(
        coin=pl.lit(coin), collected_us=pl.lit(now, pl.Int64),
        known_us=pl.when(late).then(pl.col("ts_us")).otherwise(pl.lit(now, pl.Int64)),
        backfilled=late).select(["ts_us"] + FUNDING_COLS + pit.PIT[1:])


def run(dry: bool = False, fetch: pit.Fetch | None = None, now: int | None = None,
        backfill_requests: int = BACKFILL_REQUESTS) -> dict:
    fetch = fetch or pit.paced(1.5)
    now = now or pit.now_us()
    errors: dict[str, str] = {}
    coins: list[str] = []

    def do_ctx() -> None:
        doc = fetch(API, {"type": "metaAndAssetCtxs"})
        if not isinstance(doc, list) or len(doc) != 2 or "universe" not in (doc[0] or {}):
            raise ValueError("metaAndAssetCtxs: unexpected answer")
        coins.extend(coins_listed(doc[0]))
        pit.append(SOURCE, "ctx", contexts(doc, coins, now), ["coin", "ts_us"], dry)

    def do_funding() -> None:
        if not coins:
            raise RuntimeError("no coin list (the snapshot failed)")
        budget = [backfill_requests + len(coins)]  # one page per coin always, the rest for the backfill
        frames = []
        for c in coins:
            last = pit.last_ts(SOURCE, "funding", "coin", c)
            start = HISTORY_START_MS if last is None else last // 1000 + 1
            frames.append(funding(fetch, c, start, now, budget))
        pit.append(SOURCE, "funding", pl.concat(frames), ["coin", "ts_us"], dry)

    pit.step(errors, "ctx", do_ctx)
    pit.step(errors, "funding", do_funding)
    tables = {"ctx": pit.table_health(SOURCE, "ctx", CTX_COLS, pit.HOUR_US, now, by="coin"),
              "funding": pit.table_health(SOURCE, "funding", FUNDING_COLS, pit.HOUR_US, now, by="coin")}
    return pit.write_health(SOURCE, tables, errors, dry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    ap.add_argument("--backfill-requests", type=int, default=BACKFILL_REQUESTS,
                    help="funding history pages a run beyond one a coin")
    a = ap.parse_args(argv)
    print(f"hyperliquid -> {pit.FREE / SOURCE}", flush=True)
    return pit.exit_code(run(a.dry_run, backfill_requests=a.backfill_requests)["errors"], 2)


if __name__ == "__main__":
    sys.exit(main())
