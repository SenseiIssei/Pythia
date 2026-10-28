"""Every perp on Hyperliquid and Kraken Futures: its listing and its whole hourly funding history,
point in time, for T12 (results/reachable_venues_t12_prereg.md). Data only, public endpoints, no key.

lab.collect.hyperliquid and lab.collect.kraken_futures keep only the lab's universe; this keeps every
perp the venue lists or has listed, so a study reads the folder instead of downloading.

  hyperliquid      `meta` (live and delisted perps, isDelisted), then `fundingHistory` per coin from
                   2023-05-12, 500 settlements a page. One request every PACE_HL s (a page of 500 weighs
                   45, so at most 900 of the 1,200 weight a minute Hyperliquid allows an IP) and at most
                   HL_REQUESTS a run: the coins already caught up get one page each, the rest of the
                   budget continues the backfill coin by coin, in meta's order. Hyperliquid keeps writing
                   settlements of exactly 0 (rate and premium) for a delisted coin up to today, so a
                   delisted coin's last listed hour is its last row that is not 0/0; trailing 0/0 rows of
                   a delisted coin are not stored, and its first page of nothing but 0/0 closes it (no
                   further request).
  kraken_futures   `instruments` (PF_ perpetuals, openingDate, tradeable), then
                   `historicalfundingrates` per symbol (about the last year in one answer, so the stored
                   history grows past it run by run). A symbol is fetched again once its last fetch is
                   KF_REFRESH_US old, at most KF_REQUESTS a run, oldest fetch first. A symbol that left
                   the list (or is no longer tradeable) is fetched once more and closed.

Under $PYTHIA_FREE/perps_all/<venue>/:
  funding/<coin>.parquet   ts_us (the settlement hour), coin, funding_rate (a share of the price for that
                           hour, positive = longs pay; Kraken's relativeFundingRate), premium (Hyperliquid's,
                           null on Kraken), collected_us, known_us, backfilled (lab.collect.pit). One row per
                           hour, the first value seen wins.
  listings.json            {coin: {base, delisted, closed, first_ts_us, last_ts_us, first_day, last_day,
                           opening_us (Kraken), caught_up (Hyperliquid), fetched_us (Kraken)}}; last_day only
                           for a delisted coin. `on_venue` turns it into T12's universe of a day.
and $PYTHIA_FREE/perps_all/health.json: per venue the coins done and left, the newest hour of the live
coins (the oldest of their newest, so one dead coin shows), gaps of the worst coin, errors.
Every write goes through a temporary file, so a cut run leaves the last complete state and the next run
continues from the stored rows.

    python -m lab.collect.perps_all [--venue hyperliquid|kraken_futures] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path

import polars as pl

from . import pit
from .hyperliquid import API as HL_API, HISTORY_START_MS, PAGE
from .kraken_futures import FUNDING as KF_FUNDING, INSTRUMENTS as KF_INSTRUMENTS, ts_of

SOURCE = "perps_all"
VENUES = ("hyperliquid", "kraken_futures")
PACE_HL = 3.0
PACE_KF = 1.0
HL_REQUESTS = 500
KF_REQUESTS = 120
KF_REFRESH_US = 12 * pit.HOUR_US
LIVE_LAG_US = 2 * pit.HOUR_US
COLS = ["ts_us", "coin", "funding_rate", "premium", "collected_us", "known_us", "backfilled"]
SCHEMA = {"ts_us": pl.Int64, "coin": pl.Utf8, "funding_rate": pl.Float64, "premium": pl.Float64,
          "collected_us": pl.Int64, "known_us": pl.Int64, "backfilled": pl.Boolean}


def folder(venue: str) -> Path:
    return pit.FREE / SOURCE / venue


def coin_path(venue: str, coin: str) -> Path:
    return folder(venue) / "funding" / (re.sub(r"[^A-Za-z0-9_-]", "_", coin) + ".parquet")


def _write(p: Path, write) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    write(tmp)
    os.replace(tmp, p)


def read_coin(venue: str, coin: str) -> pl.DataFrame | None:
    p = coin_path(venue, coin)
    return pl.read_parquet(p) if p.exists() else None


def store(venue: str, coin: str, new: pl.DataFrame, dry: bool = False) -> pl.DataFrame:
    """Add the hours of `new` not stored yet (first value wins) and return the coin's whole table."""
    old = read_coin(venue, coin)
    new = new.unique("ts_us", keep="first")
    if old is not None and not old.is_empty():
        new = new.join(old.select("ts_us"), on="ts_us", how="anti")
    out = (new if old is None else pl.concat([old, new], how="vertical_relaxed")).sort("ts_us")
    if not dry and new.height:
        _write(coin_path(venue, coin), out.write_parquet)
    return out


def rows(coin: str, ts_ms: list[int], rate: list, premium: list, now: int) -> pl.DataFrame:
    """Settlements as stored rows: the hour, known at the settlement when older than LIVE_LAG_US, else now."""
    df = pl.DataFrame({"ts_us": [t * 1000 // pit.HOUR_US * pit.HOUR_US for t in ts_ms],
                       "funding_rate": [_f(x) for x in rate], "premium": [_f(x) for x in premium]},
                      schema={"ts_us": pl.Int64, "funding_rate": pl.Float64, "premium": pl.Float64})
    late = now - pl.col("ts_us") > LIVE_LAG_US
    return df.with_columns(coin=pl.lit(coin), collected_us=pl.lit(now, pl.Int64),
                           known_us=pl.when(late).then(pl.col("ts_us")).otherwise(pl.lit(now, pl.Int64)),
                           backfilled=late).select(COLS).unique("ts_us", keep="first").sort("ts_us")


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _iso(ts_us: int | None) -> str | None:
    return None if ts_us is None else pit.day_of(ts_us).isoformat()


def listed_span(df: pl.DataFrame | None, delisted: bool) -> tuple[int | None, int | None]:
    """First and last listed hour of a stored table: a delisted coin's last row that is not 0/0."""
    if df is None or df.is_empty():
        return None, None
    last = df
    if delisted:
        last = df.filter((pl.col("funding_rate").fill_null(0) != 0) | (pl.col("premium").fill_null(0) != 0))
    return int(df["ts_us"].min()), (int(last["ts_us"].max()) if not last.is_empty() else None)


def update_listing(e: dict, df: pl.DataFrame | None) -> dict:
    first, last = listed_span(df, e.get("delisted", False))
    if e.get("opening_us") is not None and first is not None:
        first = max(first, int(e["opening_us"]))
    e.update(first_ts_us=first, last_ts_us=last, first_day=_iso(first),
             last_day=_iso(last) if e.get("delisted") else None)
    return e


def read_listings(venue: str) -> dict:
    p = folder(venue) / "listings.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def write_listings(venue: str, doc: dict, dry: bool = False) -> None:
    if not dry:
        _write(folder(venue) / "listings.json",
               lambda t: t.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8"))


def on_venue(listings: dict, d: date) -> list[str]:
    """T12's universe of UTC day d: the coins whose first record falls before the start of d and (a
    delisted coin) whose last listed day is after d. A coin is never on a venue before its first record."""
    start = pit.us_of(d)
    out = []
    for coin, e in sorted(listings.items()):
        if e.get("first_ts_us") is None or e["first_ts_us"] >= start:
            continue
        if e.get("delisted") and (e.get("last_ts_us") is None or start >= pit.us_of(pit.day_of(e["last_ts_us"]))):
            continue
        out.append(coin)
    return out


# ---------------------------------------------------------------------------
# Hyperliquid
# ---------------------------------------------------------------------------

def hl_base(name: str) -> str:
    """kPEPE is a thousand PEPE: its base is PEPE."""
    return name[1:] if re.fullmatch(r"k[A-Z0-9]+", name) else name


def hl_coin(fetch: pit.Fetch, coin: str, e: dict, now: int, budget: list[int], dry: bool,
            once: bool = False) -> None:
    """Continue one coin's funding from its stored rows while `budget[0]` requests are left (one page
    when `once`). Sets caught_up when a page comes back short, closed when a delisted coin is done."""
    old = read_coin("hyperliquid", coin)
    t = HISTORY_START_MS if old is None or old.is_empty() else (int(old["ts_us"].max()) + pit.HOUR_US // 2) // 1000
    frames, delisted = [], e.get("delisted", False)
    try:
        while budget[0] > 0 and t < now // 1000:
            budget[0] -= 1
            page = fetch(HL_API, {"type": "fundingHistory", "coin": coin, "startTime": t}) or []
            live = [r for r in page if _f(r.get("fundingRate")) or _f(r.get("premium"))]
            # a delisted coin: only up to its last settlement that is not 0/0
            keep = page if not delisted else [r for r in page if live and int(r["time"]) <= int(live[-1]["time"])]
            frames.append(rows(coin, [int(r["time"]) for r in keep], [r.get("fundingRate") for r in keep],
                               [r.get("premium") for r in keep], now))
            if delisted and page and not live:
                e["closed"] = True
                break
            if len(page) < PAGE:
                e.update(caught_up=True, closed=delisted)
                break
            t = max(int(r["time"]) for r in page) + 1
            if once:
                break
    finally:  # the pages fetched before a failure are kept
        df = store("hyperliquid", coin, pl.concat(frames) if frames else pl.DataFrame(schema=SCHEMA), dry)
        update_listing(e, df)


def run_hyperliquid(fetch: pit.Fetch, now: int, requests: int = HL_REQUESTS, dry: bool = False) -> dict:
    meta = fetch(HL_API, {"type": "meta"})
    if not isinstance(meta, dict) or not isinstance(meta.get("universe"), list):
        raise ValueError("meta: unexpected answer")
    budget = [requests - 1]
    lst = read_listings("hyperliquid")
    names = [u["name"] for u in meta["universe"] if u.get("name")]
    gone = {u["name"] for u in meta["universe"] if u.get("isDelisted")} | (set(lst) - set(names))
    for c in names + sorted(set(lst) - set(names)):
        e = lst.setdefault(c, {"base": hl_base(c), "delisted": False, "caught_up": False,
                                "closed": False})
        if c in gone and not e.get("delisted"):
            e.update(delisted=True, closed=False)  # one more pass closes it at its 0/0 rows
        elif c not in gone and e.get("delisted"):
            e.update(delisted=False, closed=False, caught_up=False)  # listed again
    try:
        for c in names:  # the caught up coins first, one page each, so they stay current
            e = lst[c]
            if e.get("caught_up") and not e.get("closed") and budget[0] > 0:
                hl_coin(fetch, c, e, now, budget, dry, once=True)
        for c in names:  # then the backfill, coin by coin
            e = lst[c]
            if not e.get("caught_up") and not e.get("closed") and budget[0] > 0:
                hl_coin(fetch, c, e, now, budget, dry)
    finally:
        write_listings("hyperliquid", lst, dry)
    return {"requests": requests - budget[0], "listings": lst}


# ---------------------------------------------------------------------------
# Kraken Futures
# ---------------------------------------------------------------------------

def kf_listed(doc: dict) -> dict[str, dict]:
    """{symbol: {base, opening_us}} of the tradeable PF_ perpetuals."""
    out = {}
    for ins in (doc or {}).get("instruments") or []:
        sym = str(ins.get("symbol", ""))
        if not sym.startswith("PF_") or ins.get("tradeable") is not True or ins.get("suspended", False):
            continue
        base = ins.get("base") or (sym[3:-3] if sym.endswith("USD") else sym[3:])
        out[sym] = {"base": "BTC" if base == "XBT" else base,
                    "opening_us": ts_of(ins["openingDate"]) if ins.get("openingDate") else None}
    return out


def kf_symbol(fetch: pit.Fetch, sym: str, e: dict, now: int, dry: bool) -> None:
    try:
        rates = (fetch(KF_FUNDING.format(sym=sym)) or {}).get("rates") or []
    except Exception:  # noqa: BLE001 - a delisted symbol may be refused: keep what is stored and close it
        if not e.get("delisted"):
            raise
        rates = []
    df = rows(sym, [ts_of(r["timestamp"]) // 1000 for r in rates], [r.get("relativeFundingRate") for r in rates],
              [None] * len(rates), now)
    e["fetched_us"] = now
    e["closed"] = bool(e.get("delisted"))
    update_listing(e, store("kraken_futures", sym, df, dry))


def run_kraken(fetch: pit.Fetch, now: int, requests: int = KF_REQUESTS, dry: bool = False) -> dict:
    doc = fetch(KF_INSTRUMENTS)
    if not isinstance(doc, dict) or not isinstance(doc.get("instruments"), list):
        raise ValueError("instruments: unexpected answer")
    live = kf_listed(doc)
    lst = read_listings("kraken_futures")
    for sym, info in live.items():
        e = lst.setdefault(sym, {"closed": False})
        if e.get("delisted"):
            e.update(delisted=False, closed=False)  # listed again
        e.update(info, delisted=False)
    for sym in set(lst) - set(live):
        if not lst[sym].get("delisted"):
            lst[sym].update(delisted=True, closed=False)
    due = [s for s, e in lst.items() if not e.get("closed") and now - (e.get("fetched_us") or 0) >= KF_REFRESH_US]
    todo = sorted(due, key=lambda s: (lst[s].get("fetched_us") or 0, s))
    used, errors = 1, {}
    try:
        for sym in todo:
            if used >= requests:
                break
            used += 1
            try:
                kf_symbol(fetch, sym, lst[sym], now, dry)
            except Exception as e:  # noqa: BLE001 - one symbol failing does not stop the others
                errors[sym] = f"{type(e).__name__}: {e}"[:200]
    finally:
        write_listings("kraken_futures", lst, dry)
    if errors and len(errors) >= used - 1:
        raise RuntimeError(f"every symbol failed, first {next(iter(errors.items()))}")
    return {"requests": used, "listings": lst, "symbol_errors": errors}


# ---------------------------------------------------------------------------
# Health and run
# ---------------------------------------------------------------------------

def done(venue: str, e: dict) -> bool:
    return bool(e.get("closed") or (e.get("caught_up") if venue == "hyperliquid" else e.get("fetched_us")))


def venue_health(venue: str, now: int) -> dict:
    lst = read_listings(venue)
    finished = [c for c, e in lst.items() if done(venue, e)]
    live = [c for c in finished if not lst[c].get("delisted")]
    lasts, gp, rows_ = [], 0, 0
    for c in finished:
        df = read_coin(venue, c)
        if df is None or df.is_empty():
            continue
        rows_ += df.height
        if c in live:
            lasts.append(int(df["ts_us"].max()))
            gp = max(gp, pit.gaps(df["ts_us"].to_list(), pit.HOUR_US, now))
    return {"rows": rows_, "last_ts_us": min(lasts) if lasts else None, "gaps": gp, "missing": [],
            "schema_ok": True, "coins": len(lst), "done": len(finished), "left": len(lst) - len(finished),
            "delisted": sum(1 for e in lst.values() if e.get("delisted")),
            "left_coins": sorted(c for c in lst if c not in finished)[:20]}


def write_health(tables: dict, errors: dict, extra: dict, dry: bool = False) -> dict:
    doc = pit.write_health(SOURCE, tables, errors, dry=True)
    doc.update(extra)
    if not dry:
        _write(pit.FREE / SOURCE / "health.json",
               lambda t: t.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8"))
    return doc


def run(venues=VENUES, dry: bool = False, fetch_hl: pit.Fetch | None = None, fetch_kf: pit.Fetch | None = None,
        now: int | None = None, hl_requests: int = HL_REQUESTS, kf_requests: int = KF_REQUESTS) -> dict:
    now = now or pit.now_us()
    errors: dict[str, str] = {}
    runs: dict[str, dict] = {}
    if "hyperliquid" in venues:
        pit.step(errors, "hyperliquid", lambda: runs.update(hyperliquid=run_hyperliquid(
            fetch_hl or pit.paced(PACE_HL), now, hl_requests, dry)))
    if "kraken_futures" in venues:
        pit.step(errors, "kraken_futures", lambda: runs.update(kraken_futures=run_kraken(
            fetch_kf or pit.paced(PACE_KF), now, kf_requests, dry)))
    tables = {v: venue_health(v, now) for v in VENUES}
    extra = {"requests": {v: r["requests"] for v, r in runs.items()},
             "symbol_errors": {v: r["symbol_errors"] for v, r in runs.items() if r.get("symbol_errors")}}
    for v, h in tables.items():
        print(f"  {v}: {h['done']} of {h['coins']} coins done, {h['left']} left, {h['rows']} rows", flush=True)
    return write_health(tables, errors, extra, dry)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--venue", choices=VENUES, help="one venue only (default both)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    ap.add_argument("--hl-requests", type=int, default=HL_REQUESTS, help="Hyperliquid requests a run")
    ap.add_argument("--kf-requests", type=int, default=KF_REQUESTS, help="Kraken Futures requests a run")
    a = ap.parse_args(argv)
    venues = (a.venue,) if a.venue else VENUES
    print(f"perps_all -> {pit.FREE / SOURCE}", flush=True)
    doc = run(venues, a.dry_run, hl_requests=a.hl_requests, kf_requests=a.kf_requests)
    return pit.exit_code(doc["errors"], len(venues))


if __name__ == "__main__":
    sys.exit(main())
