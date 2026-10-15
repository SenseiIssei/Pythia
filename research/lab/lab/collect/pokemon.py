"""Daily snapshot of Pokemon card prices and sets into the data lake. Data only.

Nothing here buys or sells anything. The cards are physical and the owner
trades them by hand; this job only reads public prices.

Sources
  cards, sets   the Pokemon TCG API (https://api.pokemontcg.io/v2). Every card
                carries TCGplayer prices in USD (low, mid, high, market per
                printing) and Cardmarket prices in EUR (trend, average sell,
                low, and the rolling averages avg1, avg7, avg30), both updated
                about once a day by the API. Works without a key at a lower
                rate limit; POKEMONTCG_API_KEY (environment only, never in a
                file) raises it.
  sealed        optional (--sealed): TCGplayer's daily product and price dumps
                as mirrored by tcgcsv.com (category 3 is Pokemon). Sealed
                product is everything without a card number. The Pokemon TCG
                API has no sealed product at all.
  EUR/USD       the ECB reference rate of the day, so Cardmarket and TCGplayer
                can be compared. The last good rate is kept for days it fails.

Lake (under $PYTHIA_DATA/pokemon):
  cards/date=YYYY-MM-DD/cards.parquet   one row per card whose TCGplayer market
                                        price or Cardmarket trend (in USD) is at
                                        least --min-usd (default 2)
  sets/date=YYYY-MM-DD/sets.parquet     every set with its release date
  sealed/date=YYYY-MM-DD/sealed.parquet with --sealed
  catalog.parquet                       every card, cheap ones too (id, name,
                                        set, rarity, release date): reprints
                                        are found here; replaced each full run
  meta/YYYY-MM-DD.json                  counts, FX rate, requests, errors
  _cache/YYYY-MM-DD/                    raw pages, so a rerun the same day
                                        continues instead of starting over;
                                        cleared after three days

Politeness: keyless the API allows about 30 requests a minute, so pages are
spaced 2.1 s apart (0.3 s with a key); 429 and 5xx answers are retried with
exponential backoff and Retry-After is honoured. A full run is about 90 pages.

  python -m lab.collect.pokemon                 today's snapshot
  python -m lab.collect.pokemon --sealed        plus sealed product
  python -m lab.collect.pokemon --min-usd 1 --max-pages 3 --dry-run
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

API = "https://api.pokemontcg.io/v2"
TCGCSV = "https://tcgcsv.com/tcgplayer"
POKEMON_CATEGORY = 3
ECB = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
PAGE_SIZE = 250
MIN_USD = 2.0
# A price block older than this at the snapshot is stale (see `fresh`).
CM_FRESH_DAYS = 14
TP_FRESH_DAYS = 7
CACHE_DAYS = 3
USER_AGENT = "pythia-lab-collector (data only)"
CARD_FIELDS = ("id,name,supertype,subtypes,types,hp,attacks,abilities,number,rarity,artist,"
               "nationalPokedexNumbers,set,images,tcgplayer,cardmarket")

CATALOG_COLS = ("card_id", "name", "text_key", "supertype", "rarity", "number", "set_id", "set_name", "release_date")

# Cardmarket price keys -> lake columns (EUR).
CM_KEYS = {
    "averageSellPrice": "cm_avg_sell", "lowPrice": "cm_low", "trendPrice": "cm_trend",
    "suggestedPrice": "cm_suggested", "lowPriceExPlus": "cm_low_explus",
    "avg1": "cm_avg1", "avg7": "cm_avg7", "avg30": "cm_avg30",
    "reverseHoloTrend": "cm_rh_trend", "reverseHoloAvg1": "cm_rh_avg1",
    "reverseHoloAvg7": "cm_rh_avg7", "reverseHoloAvg30": "cm_rh_avg30",
}


def data_root() -> Path:
    return Path(os.environ.get("PYTHIA_DATA", "/data"))


def lake() -> Path:
    return data_root() / "pokemon"


# ---------------------------------------------------------------- HTTP

Opener = Callable[[str, dict, float], tuple[int, dict, bytes]]


def urllib_opener(url: str, headers: dict, timeout: float) -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), b""


class FetchError(RuntimeError):
    pass


@dataclass
class Client:
    """GET with spacing between requests, retries with backoff, and a day cache."""
    opener: Opener = urllib_opener
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    spacing: float = 2.1
    retries: int = 6
    backoff: float = 2.0
    timeout: float = 60.0
    cache_dir: Path | None = None
    headers: dict = field(default_factory=dict)
    requests: int = 0
    cache_hits: int = 0
    _last: float = -1e9

    def _wait(self) -> None:
        gap = self.spacing - (self.clock() - self._last)
        if gap > 0:
            self.sleep(gap)
        self._last = self.clock()

    def get(self, url: str, cache_key: str | None = None, raw: bool = False):
        path = self.cache_dir / f"{cache_key}.gz" if (self.cache_dir and cache_key) else None
        if path is not None and path.exists():
            self.cache_hits += 1
            data = gzip.decompress(path.read_bytes())
            return data if raw else json.loads(data)
        hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **self.headers}
        last_err = "no attempt"
        for attempt in range(self.retries):
            self._wait()
            self.requests += 1
            try:
                status, rh, data = self.opener(url, hdrs, self.timeout)
            except (urllib.error.URLError, OSError, ValueError) as e:
                status, rh, data = 0, {}, b""
                last_err = type(e).__name__
            if status == 200:
                try:
                    out = data if raw else json.loads(data)
                except ValueError:
                    last_err = "invalid JSON"
                else:
                    if path is not None:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        tmp = path.with_name(path.name + ".tmp")
                        tmp.write_bytes(gzip.compress(data))
                        os.replace(tmp, path)
                    return out
            elif status:
                last_err = f"HTTP {status}"
                if status in (400, 401, 403, 404):
                    break  # retrying will not help
            wait = self.backoff * (2 ** attempt)
            ra = {k.lower(): v for k, v in (rh or {}).items()}.get("retry-after")
            try:
                wait = max(wait, float(ra)) if ra else wait
            except ValueError:
                pass
            if attempt < self.retries - 1:
                self.sleep(min(wait, 300.0))
        raise FetchError(f"{_strip(url)}: {last_err}")


def _strip(url: str) -> str:
    """The URL without its query, for messages."""
    return url.split("?", 1)[0]


# ---------------------------------------------------------------- parsing

def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and abs(f) != float("inf") and f >= 0 else None


def _date(s) -> str | None:
    """'2023/09/22' or '2023-09-22...' -> '2023-09-22'."""
    if not s:
        return None
    m = re.match(r"(\d{4})[/-](\d{2})[/-](\d{2})", str(s))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def tcgplayer_prices(card: dict) -> dict:
    """The printing with the highest market price (mid as fallback) and all printings as JSON."""
    tp = card.get("tcgplayer") or {}
    prices = tp.get("prices") or {}
    best, best_v = None, -1.0
    for variant, p in prices.items():
        if not isinstance(p, dict):
            continue
        v = _num(p.get("market")) or _num(p.get("mid"))
        if v is not None and v > best_v:
            best, best_v = variant, v
    p = prices.get(best) or {}
    return {
        "tp_variant": best,
        "tp_market": _num(p.get("market")),
        "tp_low": _num(p.get("low")),
        "tp_mid": _num(p.get("mid")),
        "tp_high": _num(p.get("high")),
        "tp_updated": _date(tp.get("updatedAt")),
        "tp_url": tp.get("url"),
        "tp_prices_json": json.dumps(prices, sort_keys=True) if prices else None,
    }


def cardmarket_prices(card: dict) -> dict:
    cm = card.get("cardmarket") or {}
    prices = cm.get("prices") or {}
    out = {col: _num(prices.get(k)) for k, col in CM_KEYS.items()}
    out["cm_updated"] = _date(cm.get("updatedAt"))
    out["cm_url"] = cm.get("url")
    return out


def text_key(card: dict) -> str:
    """Same name, HP, attacks and abilities: the same card text, so a later
    printing is a reprint (new art or not), not just a new card of that Pokemon."""
    atk = sorted(str(a.get("name") or "") for a in card.get("attacks") or [] if isinstance(a, dict))
    abi = sorted(str(a.get("name") or "") for a in card.get("abilities") or [] if isinstance(a, dict))
    return "|".join([str(card.get("name") or ""), str(card.get("hp") or ""), ",".join(atk), ",".join(abi)])


def card_row(card: dict, snap: str) -> dict:
    s = card.get("set") or {}
    imgs = card.get("images") or {}
    dex = card.get("nationalPokedexNumbers") or []
    return {
        "date": snap,
        "card_id": card.get("id"),
        "name": card.get("name"),
        "text_key": text_key(card),
        "supertype": card.get("supertype"),
        "subtypes": "|".join(card.get("subtypes") or []),
        "types": "|".join(card.get("types") or []),
        "number": str(card.get("number") or ""),
        "rarity": card.get("rarity"),
        "artist": card.get("artist"),
        "dex": int(dex[0]) if dex and str(dex[0]).isdigit() else None,
        "set_id": s.get("id"),
        "set_name": s.get("name"),
        "series": s.get("series"),
        "set_printed_total": s.get("printedTotal"),
        "release_date": _date(s.get("releaseDate")),
        "image_small": imgs.get("small"),
        "image_large": imgs.get("large"),
        **tcgplayer_prices(card),
        **cardmarket_prices(card),
    }


def fresh(updated: str | None, snap: str, days: int) -> bool:
    """A price block updated within `days` of the snapshot. The API stopped
    refreshing Cardmarket for most cards in mid 2026 (TCGplayer is updated
    daily), so a stale block must not pass for today's price."""
    if not updated:
        return False
    try:
        return (date.fromisoformat(snap) - date.fromisoformat(updated)).days <= days
    except ValueError:
        return False


def usd_value(row: dict, eurusd: float | None) -> float | None:
    """The card's price in USD: TCGplayer market, else a fresh Cardmarket trend converted."""
    if row.get("tp_market"):
        return row["tp_market"]
    if row.get("cm_trend") and eurusd and fresh(row.get("cm_updated"), row["date"], CM_FRESH_DAYS):
        return row["cm_trend"] * eurusd
    return None


def keep(row: dict, min_usd: float, eurusd: float | None) -> bool:
    """At or above the floor on TCGplayer, or on a fresh Cardmarket trend."""
    tp = row.get("tp_market") or 0.0
    cm = (row.get("cm_trend") or 0.0) * (eurusd or 0.0)
    if not fresh(row.get("cm_updated"), row.get("date") or "", CM_FRESH_DAYS):
        cm = 0.0
    return row.get("card_id") is not None and max(tp, cm) >= min_usd


def set_row(s: dict, snap: str) -> dict:
    imgs = s.get("images") or {}
    return {
        "date": snap, "set_id": s.get("id"), "name": s.get("name"), "series": s.get("series"),
        "printed_total": s.get("printedTotal"), "total": s.get("total"),
        "release_date": _date(s.get("releaseDate")), "updated_at": s.get("updatedAt"),
        "ptcgo_code": s.get("ptcgoCode"), "symbol": imgs.get("symbol"), "logo": imgs.get("logo"),
    }


def freshness(rows: list[dict], snap: str) -> dict:
    """How current the two price sources are on the kept cards."""
    n = len(rows) or 1
    tp = [r.get("tp_updated") for r in rows if r.get("tp_market")]
    cm = [r.get("cm_updated") for r in rows if r.get("cm_trend")]
    return {
        "tcgplayer_cards": len(tp),
        "tcgplayer_fresh": sum(fresh(u, snap, TP_FRESH_DAYS) for u in tp),
        "tcgplayer_newest": max((u for u in tp if u), default=None),
        "cardmarket_cards": len(cm),
        "cardmarket_fresh": sum(fresh(u, snap, CM_FRESH_DAYS) for u in cm),
        "cardmarket_newest": max((u for u in cm if u), default=None),
        "cardmarket_fresh_share": round(sum(fresh(u, snap, CM_FRESH_DAYS) for u in cm) / n, 4),
    }


# ---------------------------------------------------------------- fetching

def fetch_sets(client: Client) -> list[dict]:
    out, page = [], 1
    while True:
        q = urllib.parse.urlencode({"page": page, "pageSize": PAGE_SIZE, "orderBy": "releaseDate"})
        d = client.get(f"{API}/sets?{q}", cache_key=f"sets_{page}")
        rows = d.get("data") or []
        out += rows
        if not rows or len(out) >= int(d.get("totalCount") or 0):
            return out
        page += 1


def fetch_cards(client: Client, max_pages: int | None = None, log=print):
    """Yield every card, page by page (oldest set first, stable order)."""
    page, seen = 1, 0
    while True:
        q = urllib.parse.urlencode({"page": page, "pageSize": PAGE_SIZE, "orderBy": "set.releaseDate,number",
                                    "select": CARD_FIELDS})
        d = client.get(f"{API}/cards?{q}", cache_key=f"cards_{page}")
        rows = d.get("data") or []
        seen += len(rows)
        total = int(d.get("totalCount") or 0)
        if page == 1 or page % 10 == 0:
            log(f"cards page {page}: {seen} of {total}")
        yield from rows
        if not rows or seen >= total or (max_pages and page >= max_pages):
            return
        page += 1


def fetch_eurusd(client: Client) -> float | None:
    try:
        xml = client.get(ECB, cache_key="ecb", raw=True).decode("utf-8", "replace")
    except FetchError:
        return None
    m = re.search(r"currency=['\"]USD['\"]\s+rate=['\"]([0-9.]+)['\"]", xml)
    return float(m.group(1)) if m else None


def fetch_sealed(client: Client, snap: str, groups_back: int = 24, log=print) -> list[dict]:
    """Sealed product (no card number) of the newest `groups_back` TCGplayer groups."""
    g = client.get(f"{TCGCSV}/{POKEMON_CATEGORY}/groups", cache_key="tcgcsv_groups")
    groups = sorted(g.get("results") or [], key=lambda x: str(x.get("publishedOn") or ""), reverse=True)
    out = []
    for grp in groups[:groups_back]:
        gid = grp.get("groupId")
        try:
            prods = client.get(f"{TCGCSV}/{POKEMON_CATEGORY}/{gid}/products", cache_key=f"tcgcsv_{gid}_products")
            prices = client.get(f"{TCGCSV}/{POKEMON_CATEGORY}/{gid}/prices", cache_key=f"tcgcsv_{gid}_prices")
        except FetchError as e:
            log(f"sealed: group {gid} skipped ({e})")
            continue
        by_id: dict = {}
        for p in prices.get("results") or []:
            by_id.setdefault(p.get("productId"), []).append(p)
        for p in prods.get("results") or []:
            ext = {str(e.get("name")): e.get("value") for e in p.get("extendedData") or []}
            if "Number" in ext or "Rarity" in ext:
                continue  # a single card
            for pr in by_id.get(p.get("productId"), []):
                if _num(pr.get("marketPrice")) is None:
                    continue
                out.append({
                    "date": snap, "product_id": p.get("productId"), "group_id": gid,
                    "group_name": grp.get("name"), "published_on": _date(grp.get("publishedOn")),
                    "name": p.get("name"), "image_url": p.get("imageUrl"), "url": p.get("url"),
                    "sub_type": pr.get("subTypeName"), "low": _num(pr.get("lowPrice")),
                    "mid": _num(pr.get("midPrice")), "high": _num(pr.get("highPrice")),
                    "market": _num(pr.get("marketPrice")),
                })
    return out


# ---------------------------------------------------------------- writing

def write_parquet(rows: list[dict], path: Path) -> None:
    import polars as pl
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    pl.DataFrame(rows, infer_schema_length=None).write_parquet(tmp)
    os.replace(tmp, path)


def clean_cache(root: Path, today: date) -> None:
    base = root / "_cache"
    if not base.exists():
        return
    for d in base.iterdir():
        try:
            day = date.fromisoformat(d.name)
        except ValueError:
            continue
        if (today - day).days > CACHE_DAYS:
            shutil.rmtree(d, ignore_errors=True)


def client_for(cache_dir: Path | None) -> Client:
    key = (os.environ.get("POKEMONTCG_API_KEY") or "").strip()
    c = Client(cache_dir=cache_dir, spacing=0.3 if key else 2.1)
    if key:
        c.headers["X-Api-Key"] = key
    return c


def collect(snap: str | None = None, min_usd: float = MIN_USD, sealed: bool = False, max_pages: int | None = None,
            dry_run: bool = False, client: Client | None = None, log=print) -> dict:
    t0 = time.time()
    snap = snap or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    root = lake()
    if client is None:
        client = client_for(None if dry_run else root / "_cache" / snap)
    errors: list[str] = []
    fx_path = root / "fx.json"
    eurusd = fetch_eurusd(client)
    fx_source = "ECB"
    if eurusd is None:
        try:
            eurusd, fx_source = float(json.loads(fx_path.read_text())["eurusd"]), "last known"
        except (OSError, ValueError, KeyError, TypeError):
            eurusd, fx_source = None, "none"
        errors.append(f"EUR/USD: ECB unreachable, using {fx_source}")
    # /sets has answered 500 and 502 for hours at a time while /cards worked;
    # every card carries its full set, so the sets are rebuilt from the cards then.
    sets_src = "api"
    try:
        sets = [set_row(s, snap) for s in fetch_sets(client)]
    except FetchError as e:
        sets, sets_src = None, "cards"
        errors.append(f"sets: {e}; rebuilt from the cards' set fields")
    card_sets: dict[str, dict] = {}
    seen, rows, catalog = 0, [], []
    for c in fetch_cards(client, max_pages=max_pages, log=log):
        seen += 1
        s = c.get("set") or {}
        if s.get("id"):
            card_sets.setdefault(s["id"], s)
        r = card_row(c, snap)
        catalog.append({k: r[k] for k in CATALOG_COLS})
        if keep(r, min_usd, eurusd):
            rows.append(r)
    if sets is None:
        sets = [set_row(s, snap) for s in sorted(card_sets.values(), key=lambda s: str(s.get("releaseDate") or ""))]
    log(f"sets: {len(sets)} (from {sets_src})")
    log(f"cards: {seen} seen, {len(rows)} at or above ${min_usd:g}")
    fresh_info = freshness(rows, snap)
    log(f"freshness: {json.dumps(fresh_info)}")
    sealed_rows: list[dict] = []
    if sealed:
        try:
            sealed_rows = fetch_sealed(client, snap, log=log)
        except FetchError as e:
            errors.append(f"sealed: {e}")
        log(f"sealed: {len(sealed_rows)} products")
    meta = {
        "date": snap, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cards_seen": seen, "cards_kept": len(rows), "min_usd": min_usd, "sets": len(sets), "sets_source": sets_src,
        "freshness": fresh_info,
        "sealed": len(sealed_rows) if sealed else None, "eurusd": eurusd, "fx_source": fx_source,
        "requests": client.requests, "cache_hits": client.cache_hits, "seconds": round(time.time() - t0, 1),
        "errors": errors, "complete": max_pages is None,
    }
    if dry_run:
        log(json.dumps(meta, indent=2))
        return meta
    if not rows:
        raise FetchError("no card passed the price filter; nothing written")
    write_parquet(rows, root / "cards" / f"date={snap}" / "cards.parquet")
    write_parquet(sets, root / "sets" / f"date={snap}" / "sets.parquet")
    if max_pages is None:
        write_parquet(catalog, root / "catalog.parquet")
    if sealed_rows:
        write_parquet(sealed_rows, root / "sealed" / f"date={snap}" / "sealed.parquet")
    (root / "meta").mkdir(parents=True, exist_ok=True)
    (root / "meta" / f"{snap}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if eurusd and fx_source == "ECB":
        fx_path.write_text(json.dumps({"date": snap, "eurusd": eurusd}), encoding="utf-8")
    clean_cache(root, date.fromisoformat(snap))
    log(json.dumps(meta))
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--date", help="snapshot date (default today, UTC)")
    ap.add_argument("--min-usd", type=float, default=MIN_USD)
    ap.add_argument("--sealed", action="store_true", help="also snapshot sealed product (tcgcsv.com)")
    ap.add_argument("--max-pages", type=int, help="stop after this many card pages (a test run)")
    ap.add_argument("--dry-run", action="store_true", help="fetch and count, write nothing")
    a = ap.parse_args(argv)
    try:
        collect(a.date, a.min_usd, a.sealed, a.max_pages, a.dry_run)
    except FetchError as e:
        print(f"pokemon collector failed: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
