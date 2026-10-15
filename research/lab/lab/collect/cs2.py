"""CS2 skins collector: Skinport snapshots and sales history for every item,
Steam prices for a watchlist. Read-only market data; nothing here can buy or
sell anything, and nothing ever will (automated trading on the Steam Community
Market or any skin marketplace breaks their terms; the owner trades by hand).

Hourly on the lab machine (see research/ops/README.md):

  python -m lab.collect.cs2                 Skinport items + sales history + Steam watchlist
  python -m lab.collect.cs2 --no-steam      Skinport only
  python -m lab.collect.cs2 --steam-max 40  fewer Steam requests this run

Sources, both public and keyless:
  Skinport  GET https://api.skinport.com/v1/items?app_id=730&currency=EUR
            GET https://api.skinport.com/v1/sales/history?app_id=730&currency=EUR
            Brotli only (Accept-Encoding: br). Limit 8 requests per 5 minutes;
            this job makes 2 an hour.
  Steam     GET https://steamcommunity.com/market/priceoverview/?appid=730&currency=3&market_hash_name=...
            About 20 requests a minute: one every 3.2 s, at most --steam-max a
            run (default 100). A 429 waits (Retry-After, else 60 s, then
            120 s) and a third one ends the Steam part of the run; the
            watchlist then resumes where it stopped next hour.

Writes under <data>/cs2/ (PYTHIA_DATA, as the rest of the lab):
  skinport_items/date=YYYY-MM-DD/HHMM.parquet   every item, every run
  skinport_sales/date=YYYY-MM-DD/HHMM.parquet   24h/7d/30d/90d sales stats
  steam_prices/date=YYYY-MM-DD/HHMM.parquet     the watchlist
  daily/skinport/date=YYYY-MM-DD.parquet        the day's last snapshot per item (items joined with sales)
  daily/steam/date=YYYY-MM-DD.parquet           the day's last Steam price per item
  collector.json                                the last run: counts, errors, where the watchlist stopped
"""

from __future__ import annotations

import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import polars as pl

from ..data import ROOT

SKINPORT_ITEMS = "https://api.skinport.com/v1/items?app_id=730&currency=EUR"
SKINPORT_SALES = "https://api.skinport.com/v1/sales/history?app_id=730&currency=EUR"
STEAM_PRICE = "https://steamcommunity.com/market/priceoverview/?appid=730&currency=3&market_hash_name="
USER_AGENT = "pythia-lab-cs2/1.0 (hourly price snapshots, read-only)"
WATCHLIST = Path(__file__).with_name("cs2_watchlist.json")

STEAM_INTERVAL_S = 3.2       # 60 / 3.2 = 18.75 requests a minute, under Steam's ~20
STEAM_MAX_PER_RUN = 100
STEAM_BACKOFF_S = (60, 120)  # waits after the first and second 429; the third stops the run
TOP_LIQUID = 40              # most traded Skinport items added to the Steam watchlist

# fetch(url, headers) -> (status, body bytes, response headers)
Fetch = Callable[[str, dict], tuple[int, bytes, dict]]


def cs2_root(root: Path | None = None) -> Path:
    return (root or ROOT) / "cs2"


def http_fetch(url: str, headers: dict, timeout: float = 30) -> tuple[int, bytes, dict]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read() or b"", dict(e.headers or {})


def decode(body: bytes, headers: dict) -> bytes:
    enc = {k.lower(): v for k, v in headers.items()}.get("content-encoding", "").lower()
    if "br" in enc:
        import brotli  # only the Skinport path needs it
        return brotli.decompress(body)
    if "gzip" in enc:
        import gzip
        return gzip.decompress(body)
    return body


# ---------------------------------------------------------------- parsing

def _f(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def parse_items(rows: list[dict], ts_ms: int) -> pl.DataFrame:
    out = [{
        "ts_ms": ts_ms,
        "name": str(r.get("market_hash_name") or ""),
        "currency": str(r.get("currency") or "EUR"),
        "suggested_price": _f(r.get("suggested_price")),
        "min_price": _f(r.get("min_price")),
        "max_price": _f(r.get("max_price")),
        "mean_price": _f(r.get("mean_price")),
        "median_price": _f(r.get("median_price")),
        "quantity": int(_f(r.get("quantity")) or 0),
        "created_at": int(_f(r.get("created_at")) or 0),
        "updated_at": int(_f(r.get("updated_at")) or 0),
    } for r in rows if r.get("market_hash_name")]
    return pl.DataFrame(out, schema=ITEM_SCHEMA)


ITEM_SCHEMA = {"ts_ms": pl.Int64, "name": pl.Utf8, "currency": pl.Utf8, "suggested_price": pl.Float64,
               "min_price": pl.Float64, "max_price": pl.Float64, "mean_price": pl.Float64,
               "median_price": pl.Float64, "quantity": pl.Int64, "created_at": pl.Int64, "updated_at": pl.Int64}
WINDOWS = {"s24": "last_24_hours", "s7": "last_7_days", "s30": "last_30_days", "s90": "last_90_days"}
STATS = ("min", "max", "avg", "median", "volume")
SALES_SCHEMA = {"ts_ms": pl.Int64, "name": pl.Utf8, "version": pl.Utf8,
                **{f"{w}_{s}": pl.Float64 for w in WINDOWS for s in STATS}}
STEAM_SCHEMA = {"ts_ms": pl.Int64, "name": pl.Utf8, "ok": pl.Boolean, "lowest": pl.Float64,
                "median": pl.Float64, "volume": pl.Int64, "status": pl.Int64}


def parse_sales(rows: list[dict], ts_ms: int) -> pl.DataFrame:
    """Sales history, one row per item; the Doppler phases (version) are
    folded into the plain name's row only when it has none of its own."""
    out = []
    for r in rows:
        name = r.get("market_hash_name")
        if not name:
            continue
        row = {"ts_ms": ts_ms, "name": str(name), "version": r.get("version")}
        for w, key in WINDOWS.items():
            stats = r.get(key) or {}
            for s in STATS:
                row[f"{w}_{s}"] = _f(stats.get(s))
        out.append(row)
    df = pl.DataFrame(out, schema=SALES_SCHEMA)
    # Phased items appear once per version; keep the row without a version, else the most traded one.
    return (df.sort(["name", pl.col("version").is_null(), "s30_volume"], descending=[False, True, True], nulls_last=True)
              .unique("name", keep="first").sort("name"))


def steam_number(text) -> float | None:
    """'1,23€', '1.234,56€', '5,--€', '0,03 €' -> float (currency 3, euro)."""
    if text is None:
        return None
    s = str(text).replace("--", "00")
    s = "".join(c for c in s if c.isdigit() or c in ",.")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def parse_steam(name: str, status: int, body: bytes, ts_ms: int) -> dict:
    row = {"ts_ms": ts_ms, "name": name, "ok": False, "lowest": None, "median": None, "volume": None, "status": status}
    if status != 200:
        return row
    try:
        d = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return row
    if not isinstance(d, dict) or not d.get("success"):
        return row
    vol = steam_number(str(d.get("volume", "")).replace(".", "").replace(",", ""))
    row.update(ok=True, lowest=steam_number(d.get("lowest_price")), median=steam_number(d.get("median_price")),
               volume=int(vol) if vol is not None else 0)
    return row


# ---------------------------------------------------------------- the watchlist

def load_watchlist(path: Path = WATCHLIST) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def steam_names(watch: dict, sales: pl.DataFrame | None, top: int = TOP_LIQUID) -> list[str]:
    """The fixed watchlist (cases, skins, stickers) and the most traded Skinport items, no duplicates."""
    names = [c["name"] for c in watch.get("cases") or []] + list(watch.get("skins") or []) + list(watch.get("stickers") or [])
    if sales is not None and not sales.is_empty() and top > 0:
        liquid = (sales.filter(pl.col("s7_volume").is_not_null() & (pl.col("s7_avg").fill_null(0) >= 0.5))
                  .sort("s7_volume", descending=True).head(top)["name"].to_list())
        names += liquid
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def rotate(names: list[str], start: int, n: int) -> tuple[list[str], int]:
    """n names from `start` on, wrapping around; and where the next run starts."""
    if not names:
        return [], 0
    start %= len(names)
    n = min(n, len(names))
    take = [names[(start + i) % len(names)] for i in range(n)]
    return take, (start + n) % len(names)


# ---------------------------------------------------------------- the runs

def fetch_skinport(fetch: Fetch, url: str) -> list[dict]:
    status, body, headers = fetch(url, {"Accept-Encoding": "br", "Accept": "application/json"})
    if status != 200:
        raise RuntimeError(f"Skinport answered HTTP {status}")
    data = json.loads(decode(body, headers).decode("utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("Skinport answered something other than a list")
    return data


def fetch_steam(fetch: Fetch, names: list[str], ts_ms: int, sleep: Callable[[float], None] = time.sleep,
                interval: float = STEAM_INTERVAL_S, backoff: tuple[int, ...] = STEAM_BACKOFF_S) -> tuple[list[dict], int, bool]:
    """(rows, how many names were done, stopped by rate limiting). One request
    every `interval` seconds; each 429 waits, the one after the last wait stops."""
    rows: list[dict] = []
    hits = 0
    for i, name in enumerate(names):
        while True:
            if rows or hits:
                sleep(interval + random.uniform(0, 0.4))
            status, body, headers = fetch(STEAM_PRICE + urllib.parse.quote(name, safe=""), {"Accept": "application/json"})
            if status != 429:
                break
            if hits >= len(backoff):
                return rows, i, True
            retry = _f({k.lower(): v for k, v in headers.items()}.get("retry-after"))
            sleep(max(retry or 0, backoff[hits]))
            hits += 1
        rows.append(parse_steam(name, status, body, ts_ms))
    return rows, len(names), False


def _write(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    df.write_parquet(tmp)
    tmp.replace(path)


def daily_skinport(items: pl.DataFrame, sales: pl.DataFrame | None) -> pl.DataFrame:
    if sales is None or sales.is_empty():
        return items
    return items.join(sales.drop("ts_ms"), on="name", how="full", coalesce=True).with_columns(
        ts_ms=pl.col("ts_ms").fill_null(items["ts_ms"].max()))


def merge_daily_steam(path: Path, rows: pl.DataFrame) -> pl.DataFrame:
    """Today's Steam file gains this run's rows; a later price replaces an earlier one per item."""
    ok = rows.filter(pl.col("ok"))
    if path.exists():
        ok = pl.concat([pl.read_parquet(path), ok], how="vertical_relaxed")
    return ok.sort("ts_ms").unique("name", keep="last").sort("name")


def run(root: Path | None = None, fetch: Fetch = http_fetch, steam: bool = True, steam_max: int = STEAM_MAX_PER_RUN,
        now_ms: int | None = None, sleep: Callable[[float], None] = time.sleep) -> dict:
    base = cs2_root(root)
    now_ms = now_ms or int(time.time() * 1000)
    t = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    day, hhmm = t.strftime("%Y-%m-%d"), t.strftime("%H%M")
    state_path = base / "collector.json"
    try:
        prev = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    report: dict = {"ts_ms": now_ms, "at": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "errors": []}

    items = sales = None
    try:
        items = parse_items(fetch_skinport(fetch, SKINPORT_ITEMS), now_ms)
        _write(items, base / "skinport_items" / f"date={day}" / f"{hhmm}.parquet")
        report["skinport_items"] = items.height
    except Exception as e:  # noqa: BLE001 - one source failing must not stop the other
        report["errors"].append(f"skinport items: {type(e).__name__}: {e}")
    try:
        sales = parse_sales(fetch_skinport(fetch, SKINPORT_SALES), now_ms)
        _write(sales, base / "skinport_sales" / f"date={day}" / f"{hhmm}.parquet")
        report["skinport_sales"] = sales.height
    except Exception as e:  # noqa: BLE001
        report["errors"].append(f"skinport sales: {type(e).__name__}: {e}")
    if items is not None:
        _write(daily_skinport(items, sales), base / "daily" / "skinport" / f"date={day}.parquet")

    cursor = int(prev.get("steam_cursor") or 0)
    if steam:
        names = steam_names(load_watchlist(), sales)
        batch, nxt = rotate(names, cursor, steam_max)
        # After a run that Steam refused outright, this run only knocks once:
        # the first 429 ends the Steam part at once instead of waiting it out.
        cooling = bool(prev.get("steam_rate_limited")) and not prev.get("steam_ok")
        rows, done, limited = fetch_steam(fetch, batch, now_ms, sleep=sleep,
                                          backoff=() if cooling else STEAM_BACKOFF_S)
        cursor = (cursor + done) % max(len(names), 1)
        if not limited:
            cursor = nxt
        df = pl.DataFrame(rows, schema=STEAM_SCHEMA)
        if not df.is_empty():
            _write(df, base / "steam_prices" / f"date={day}" / f"{hhmm}.parquet")
            daily_path = base / "daily" / "steam" / f"date={day}.parquet"
            _write(merge_daily_steam(daily_path, df), daily_path)
        missing = [r["name"] for r in rows if r["status"] == 200 and not r["ok"]]
        report.update(steam_requested=len(batch), steam_ok=int(df["ok"].sum()) if not df.is_empty() else 0,
                      steam_rate_limited=limited, steam_missing=missing[:20], steam_watchlist=len(names),
                      steam_cooling=cooling)
        if limited:
            report["errors"].append("steam: refused (429) after one try, cooling off" if cooling
                                    else "steam: rate limited three times, stopped early")
    report["steam_cursor"] = cursor
    report["ok"] = items is not None and sales is not None
    base.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    steam_max = STEAM_MAX_PER_RUN
    if "--steam-max" in argv:
        steam_max = int(argv[argv.index("--steam-max") + 1])
    rep = run(steam="--no-steam" not in argv, steam_max=steam_max)
    print(json.dumps(rep, indent=2))
    return 0 if rep["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
