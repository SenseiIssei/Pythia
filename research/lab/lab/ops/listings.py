"""New coin listings: diff the asset lists of four venues and post every new one.

    python -m lab.ops.listings              one look at every venue (cron, every 10 minutes)
    python -m lab.ops.listings --dry-run    look and print, write and post nothing

Each run fetches the tradable lists of

  alpaca    GET /v2/assets?asset_class=crypto on the paper API, only when
            APCA_API_KEY_ID and APCA_API_SECRET_KEY are set (the only venue
            Pythia trades on)
  binance   /api/v3/exchangeInfo
  coinbase  /products on the exchange API
  kraken    /0/public/AssetPairs
  binance_news
            Binance's "New Cryptocurrency Listing" announcements, which come
            hours to days before the pair trades

and compares each with what it saw before (<data>/listings/state.json). The
first successful look at a venue only seeds it: nothing is posted for the
thousands of pairs that already exist. After that:

  - every new pair is a row in the data lake with its first-seen time,
    <data>/listings/first_seen/date=YYYY-MM-DD/<HHMMSS>-<venue>.parquet
    (event listed, removed, returned, announced or seed);
  - every new listing goes out as its own message through lab.ops.notify
    (Telegram or the webhook): a new coin (a base the venue had no pair for),
    a new Alpaca pair, a new Binance listing announcement; with venue,
    symbols, whether Alpaca lists the coin and the first price when the
    venue quotes one. At most MAX_ALERTS messages a run, the rest in one;
  - <data>/reports/listings/latest.json, the cockpit's feed (title,
    updatedMs, status, headline, items) plus the last 90 days of events and
    how each venue answered, for the engine's lab view (the Markets page
    shows them as New listings).

A venue that fails or answers with a list much shorter than the last one is
skipped for this run, so an outage never reads as a mass delisting followed by
a mass listing. Alerts are information: nothing here places an order.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from . import notify

VENUES = ("alpaca", "binance", "coinbase", "kraken")
NEWS = "binance_news"
RECENT_DAYS = 90
RECENT_MAX = 200
MAX_ALERTS = 10             # messages per run; a burst beyond that goes out as one summary
FEED_ITEMS = 50
DOLLARS = ("USD", "USDT", "USDC")   # the first price is quoted in dollars when the venue has a dollar pair
SHRINK_LIMIT = 0.8          # a list under 80 % of the known one is treated as a bad answer
STATE_VERSION = 1
TIMEOUT = 20
UA = {"User-Agent": "pythia-listings"}

ALPACA_ASSETS = "https://paper-api.alpaca.markets/v2/assets?asset_class=crypto"
ALPACA_TRADES = "https://data.alpaca.markets/v1beta3/crypto/us/latest/trades?symbols="
BINANCE_INFO = "https://api.binance.com/api/v3/exchangeInfo"
BINANCE_PRICE = "https://api.binance.com/api/v3/ticker/price?symbol="
BINANCE_NEWS = ("https://www.binance.com/bapi/composite/v1/public/cms/article/list/query"
                "?type=1&catalogId=48&pageNo=1&pageSize=20")
COINBASE_PRODUCTS = "https://api.exchange.coinbase.com/products"
COINBASE_TICKER = "https://api.exchange.coinbase.com/products/{}/ticker"
KRAKEN_PAIRS = "https://api.kraken.com/0/public/AssetPairs"
KRAKEN_TICKER = "https://api.kraken.com/0/public/Ticker?pair="

# Kraken's legacy names, so one coin has one base everywhere.
ALIASES = {"XBT": "BTC", "XDG": "DOGE", "XXBT": "BTC", "XXDG": "DOGE", "XETH": "ETH", "ZUSD": "USD",
           "ZEUR": "EUR", "XXRP": "XRP", "XLTC": "LTC", "XXLM": "XLM", "XETC": "ETC"}
VENUE_NAMES = {"alpaca": "Alpaca", "binance": "Binance", "coinbase": "Coinbase", "kraken": "Kraken",
               NEWS: "Binance announcement"}


def base_name(b: str) -> str:
    b = (b or "").upper().strip()
    return ALIASES.get(b, b)


def listings_dir() -> Path:
    return notify.data_root() / "listings"


def latest_path() -> Path:
    return notify.reports_root() / "listings" / "latest.json"


def lake_dir() -> Path:
    return listings_dir() / "first_seen"


# ---------------------------------------------------------------- fetching

def get_json(url: str, headers: dict | None = None, timeout: float = TIMEOUT):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def alpaca_headers() -> dict | None:
    k = (os.environ.get("APCA_API_KEY_ID") or "").strip()
    s = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("APCA_API_SECRET") or "").strip()
    return {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else None


def parse_alpaca(rows) -> dict[str, dict]:
    out = {}
    for a in rows or []:
        sym = str(a.get("symbol") or "")
        if not sym or a.get("status") != "active" or not a.get("tradable", True):
            continue
        base, _, quote = sym.partition("/")
        out[sym] = {"base": base_name(base), "quote": quote.upper(), "status": "active"}
    return out


def parse_binance(info) -> dict[str, dict]:
    out = {}
    for s in (info or {}).get("symbols") or []:
        sym = str(s.get("symbol") or "")
        if not sym or s.get("status") in ("BREAK", "HALT", "END_OF_DAY", "DELISTED"):
            continue
        out[sym] = {"base": base_name(s.get("baseAsset")), "quote": str(s.get("quoteAsset") or "").upper(),
                    "status": str(s.get("status") or "")}
    return out


def parse_coinbase(rows) -> dict[str, dict]:
    out = {}
    for p in rows or []:
        sym = str(p.get("id") or "")
        if not sym or p.get("status") not in (None, "online") or p.get("trading_disabled"):
            continue
        out[sym] = {"base": base_name(p.get("base_currency")), "quote": str(p.get("quote_currency") or "").upper(),
                    "status": str(p.get("status") or "online")}
    return out


def parse_kraken(doc) -> dict[str, dict]:
    out = {}
    for name, p in ((doc or {}).get("result") or {}).items():
        ws = str(p.get("wsname") or "")
        if p.get("status") not in (None, "online") or name.endswith(".d"):
            continue
        if "/" in ws:
            base, quote = ws.split("/", 1)
        else:
            base, quote = str(p.get("base") or ""), str(p.get("quote") or "")
        sym = str(p.get("altname") or name)
        out[sym] = {"base": base_name(base), "quote": base_name(quote), "status": str(p.get("status") or "online")}
    return out


TICKER_RE = re.compile(r"\(([A-Z0-9]{2,15})\)")


def parse_news(doc) -> list[dict]:
    """Binance's listing announcements: id, title, release time, the tickers in brackets."""
    out = []
    for cat in ((doc or {}).get("data") or {}).get("catalogs") or []:
        for a in cat.get("articles") or []:
            title = str(a.get("title") or "")
            if not title or a.get("id") is None:
                continue
            out.append({"id": str(a["id"]), "title": title, "release_ms": int(a.get("releaseDate") or 0),
                        "bases": sorted({base_name(t) for t in TICKER_RE.findall(title)})})
    return out


def fetch(venue: str) -> dict[str, dict]:
    if venue == "alpaca":
        h = alpaca_headers()
        if h is None:
            raise LookupError("no Alpaca keys")
        return parse_alpaca(get_json(ALPACA_ASSETS, h))
    if venue == "binance":
        return parse_binance(get_json(BINANCE_INFO))
    if venue == "coinbase":
        return parse_coinbase(get_json(COINBASE_PRODUCTS))
    if venue == "kraken":
        doc = get_json(KRAKEN_PAIRS)
        if doc.get("error"):
            raise ValueError("kraken: " + "; ".join(map(str, doc["error"]))[:120])
        return parse_kraken(doc)
    raise KeyError(venue)


def first_price(venue: str, sym: str) -> float | None:
    """The venue's last price for a new pair, None while it does not trade yet."""
    try:
        if venue == "binance":
            return float(get_json(BINANCE_PRICE + urllib.parse.quote(sym), timeout=10)["price"])
        if venue == "coinbase":
            return float(get_json(COINBASE_TICKER.format(urllib.parse.quote(sym)), timeout=10)["price"])
        if venue == "kraken":
            res = get_json(KRAKEN_TICKER + urllib.parse.quote(sym), timeout=10).get("result") or {}
            return float(next(iter(res.values()))["c"][0]) if res else None
        if venue == "alpaca":
            h = alpaca_headers()
            if h is None:
                return None
            t = get_json(ALPACA_TRADES + urllib.parse.quote(sym), h, timeout=10).get("trades") or {}
            return float(t[sym]["p"]) if sym in t else None
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, StopIteration):
        return None
    return None


def why(e: BaseException) -> str:
    """A short reason that never quotes a URL or a key."""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, LookupError) and not isinstance(e, KeyError):
        return str(e)
    if isinstance(e, ValueError) and str(e).startswith("kraken:"):
        return str(e)
    return type(getattr(e, "reason", None) or e).__name__


# ---------------------------------------------------------------- diffing

def empty_state() -> dict:
    return {"version": STATE_VERSION, "venues": {}, "news": {"ids": [], "seeded_ms": None}}


def load_state(p: Path) -> dict:
    st = notify.read_json(p)
    if not isinstance(st, dict) or st.get("version") != STATE_VERSION:
        return empty_state()
    st.setdefault("venues", {})
    st.setdefault("news", {"ids": [], "seeded_ms": None})
    return st


def diff_venue(venue: str, known: dict | None, now: dict[str, dict], now_ms: int) -> tuple[dict, list[dict], str | None]:
    """(new venue state, events, skip reason). `known` is the venue's saved state or None."""
    if known is None or not known.get("symbols"):
        if not now:
            return known or {}, [], "empty answer"
        syms = {s: {**m, "first_seen_ms": now_ms} for s, m in now.items()}
        events = [{"event": "seed", "venue": venue, "symbol": s, **m, "new_base": False} for s, m in now.items()]
        return {"symbols": syms, "gone": {}, "seeded_ms": now_ms}, events, None
    syms: dict = dict(known["symbols"])
    gone: dict = dict(known.get("gone") or {})
    if len(now) < SHRINK_LIMIT * len(syms):
        return known, [], f"answered {len(now)} pairs against {len(syms)} known"
    old_bases = {m["base"] for m in syms.values()}
    events = []
    for s, m in sorted(now.items()):
        if s in syms:
            syms[s] = {**syms[s], **m}
            continue
        if s in gone:
            events.append({"event": "returned", "venue": venue, "symbol": s, **m, "new_base": False})
            syms[s] = {**m, "first_seen_ms": gone.pop(s).get("first_seen_ms", now_ms)}
            continue
        events.append({"event": "listed", "venue": venue, "symbol": s, **m, "new_base": m["base"] not in old_bases})
        syms[s] = {**m, "first_seen_ms": now_ms}
    for s in sorted(set(syms) - set(now)):
        m = syms.pop(s)
        gone[s] = {**m, "removed_ms": now_ms}
        events.append({"event": "removed", "venue": venue, "symbol": s, "base": m["base"], "quote": m["quote"],
                       "status": "", "new_base": False})
    return {"symbols": syms, "gone": gone, "seeded_ms": known.get("seeded_ms")}, events, None


def diff_news(known: dict, items: list[dict], now_ms: int) -> tuple[dict, list[dict]]:
    ids = list(known.get("ids") or [])
    seeded = known.get("seeded_ms")
    events = []
    for a in items:
        if a["id"] in ids:
            continue
        ids.append(a["id"])
        if seeded is not None:
            events.append({"event": "announced", "venue": NEWS, "symbol": ",".join(a["bases"]) or "?",
                           "base": a["bases"][0] if a["bases"] else "", "quote": "", "status": "",
                           "new_base": True, "title": a["title"], "release_ms": a["release_ms"]})
    return {"ids": ids[-500:], "seeded_ms": seeded if seeded is not None else now_ms}, events


def alpaca_bases(state: dict) -> set[str] | None:
    a = (state.get("venues") or {}).get("alpaca") or {}
    return {m["base"] for m in (a.get("symbols") or {}).values()} if a.get("symbols") else None


def alert_worthy(e: dict) -> bool:
    if e["event"] == "announced":
        return True
    if e["event"] != "listed":
        return False
    return e["venue"] == "alpaca" or e["new_base"]


def alert_groups(events: list[dict]) -> list[list[dict]]:
    """The run's alert-worthy events, one group per venue and coin, in order."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for e in events:
        if alert_worthy(e):
            groups.setdefault((e["venue"], e["base"] if e["event"] != "announced" else e["symbol"]), []).append(e)
    return list(groups.values())


def alert_line(es: list[dict]) -> str:
    """One listing in one sentence: venue, coin, symbols, Alpaca, first price."""
    e0 = es[0]
    venue = e0["venue"]
    if e0["event"] == "announced":
        return f"{VENUE_NAMES[venue]}: {e0.get('title', '')}. Alpaca: {alpaca_word(e0)}."
    syms = ", ".join(e["symbol"] for e in es[:6]) + (f" and {len(es) - 6} more" if len(es) > 6 else "")
    priced = [e for e in es if e.get("price") is not None]
    px = min(priced, key=lambda e: DOLLARS.index(e["quote"]) if e["quote"] in DOLLARS else len(DOLLARS),
             default=None)
    price = f" First price {px['price']:.8g} {px['quote']} ({px['symbol']})." if px else " No price yet."
    what = "new pair" if venue == "alpaca" and not e0["new_base"] else "new coin"
    return f"{VENUE_NAMES[venue]} {what} {e0['base']}: {syms}. Alpaca: {alpaca_word(e0)}.{price}"


def alert_texts(events: list[dict], prefix: str, limit: int = MAX_ALERTS) -> list[str]:
    """One message per new listing; past `limit` the rest share one message."""
    lines = [alert_line(es) for es in alert_groups(events)]
    if len(lines) > limit:
        lines = lines[:limit - 1] + ["\n".join([f"{len(lines) - limit + 1} more:"] + lines[limit - 1:])]
    return [notify.clip(f"{prefix} new listing: {ln}\nInformation only: nothing is bought.") for ln in lines]


def alert_text(events: list[dict], prefix: str) -> str:
    """Every message of the run, one after the other (for the dry run and the logs)."""
    return "\n\n".join(alert_texts(events, prefix))


def alpaca_word(e: dict) -> str:
    v = e.get("alpaca_lists")
    return "unknown (no keys)" if v is None else ("lists it" if v else "does not list it")


# ---------------------------------------------------------------- writing

LAKE_COLS = ("ts_ms", "venue", "event", "symbol", "base", "quote", "status", "new_base", "alpaca_lists",
             "price", "title", "release_ms")


def write_lake(events: list[dict], now_ms: int, root: Path) -> list[Path]:
    """One parquet file per venue and run under date=YYYY-MM-DD."""
    if not events:
        return []
    import pyarrow as pa
    import pyarrow.parquet as pq
    dt = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    out_dir = root / f"date={dt:%Y-%m-%d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    schema = pa.schema([("ts_ms", pa.int64()), ("venue", pa.string()), ("event", pa.string()),
                        ("symbol", pa.string()), ("base", pa.string()), ("quote", pa.string()),
                        ("status", pa.string()), ("new_base", pa.bool_()), ("alpaca_lists", pa.bool_()),
                        ("price", pa.float64()), ("title", pa.string()), ("release_ms", pa.int64())])
    paths = []
    for venue in sorted({e["venue"] for e in events}):
        rows = [e for e in events if e["venue"] == venue]
        cols = {c: [({**e, "ts_ms": now_ms}).get(c) for e in rows] for c in LAKE_COLS}
        p = out_dir / f"{dt:%H%M%S}-{venue}.parquet"
        tmp = p.with_name(p.name + ".tmp")
        pq.write_table(pa.table(cols, schema=schema), tmp)
        os.replace(tmp, p)
        paths.append(p)
    return paths


def update_recent(prev: dict | None, events: list[dict], venues: dict, now_ms: int) -> dict:
    """The feed file: the cockpit's common header (title, updatedMs, status,
    headline, items) over the last 90 days of listings and each venue's answer."""
    keep = [e for e in (prev or {}).get("listings") or []
            if isinstance(e, dict) and now_ms - int(e.get("ts_ms") or 0) <= RECENT_DAYS * notify.DAY_MS]
    for e in events:
        if e["event"] in ("listed", "announced"):
            keep.append({k: e.get(k) for k in ("venue", "event", "symbol", "base", "quote", "new_base",
                                               "alpaca_lists", "price", "title")} | {"ts_ms": now_ms})
    keep.sort(key=lambda e: -int(e.get("ts_ms") or 0))
    keep = keep[:RECENT_MAX]
    return {"title": "New listings", "updatedMs": now_ms, **feed_summary(keep, venues, now_ms),
            "generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "generated_ms": now_ms, "venues": venues, "listings": keep}


def feed_summary(listings: list[dict], venues: dict, now_ms: int) -> dict:
    """status, headline and items. watch: a new coin in the last day or a venue
    did not answer; bad: no venue answered; ok otherwise."""
    worthy = [e for e in listings if alert_worthy({"event": e.get("event") or "", "venue": e.get("venue") or "",
                                                   "new_base": bool(e.get("new_base"))})]
    day = [e for e in worthy if now_ms - int(e.get("ts_ms") or 0) <= notify.DAY_MS]
    down = sorted(v for v, s in venues.items() if not (s or {}).get("ok"))
    up = [v for v, s in venues.items() if (s or {}).get("ok")]
    status = "bad" if venues and not up else ("watch" if day or down else "ok")
    coins: list[str] = []
    for e in day:
        name = f"{VENUE_NAMES.get(e['venue'], e['venue'])} {e.get('base') or e.get('symbol')}"
        if name not in coins:
            coins.append(name)
    head = (f"{len(coins)} new in the last 24 hours: {', '.join(coins[:5])}{' and more' if len(coins) > 5 else ''}."
            if coins else "Nothing new in the last 24 hours.")
    head += f" {len(worthy)} in 90 days."
    if down:
        head += " Not answering: " + ", ".join(VENUE_NAMES.get(v, v) for v in down) + "."
    items, seen = [], set()
    for e in worthy:
        key = (e.get("venue"), e.get("base") or e.get("symbol"), e.get("event"))
        if key in seen:
            continue
        seen.add(key)
        fresh = now_ms - int(e.get("ts_ms") or 0) <= notify.DAY_MS
        px = e.get("price")
        items.append({
            "label": f"{VENUE_NAMES.get(e['venue'], e['venue'])} {e.get('base') or e.get('symbol')}",
            "value": f"{px:.8g} {e.get('quote') or ''}".strip() if isinstance(px, (int, float)) else None,
            "status": "watch" if fresh else "ok",
            "detail": (e.get("title") or e.get("symbol") or "") + f". Alpaca: {alpaca_word(e)}.",
            "importance": 90 if fresh and e.get("alpaca_lists") else (70 if fresh else 20),
            "atMs": int(e.get("ts_ms") or 0)})
        if len(items) >= FEED_ITEMS:
            break
    return {"status": status, "headline": head, "items": items}


# ---------------------------------------------------------------- one run

def run(dry_run: bool = False, now_ms: int | None = None, fetcher=fetch, news_fetcher=None, pricer=first_price,
        poster=None) -> dict:
    """One look at every venue. Returns {"events", "text", "venues", "delivered"}."""
    now_ms = now_ms or int(time.time() * 1000)
    state_p = listings_dir() / "state.json"
    state = load_state(state_p)
    venues: dict[str, dict] = {}
    events: list[dict] = []
    for v in VENUES:
        try:
            now = fetcher(v)
        except Exception as e:  # noqa: BLE001 - every venue failure is reported, none stops the run
            venues[v] = {"ok": False, "count": len((state["venues"].get(v) or {}).get("symbols") or {}),
                         "error": why(e)}
            continue
        vs, ev, skip = diff_venue(v, state["venues"].get(v), now, now_ms)
        state["venues"][v] = vs
        venues[v] = {"ok": skip is None, "count": len(vs.get("symbols") or {}), "error": skip,
                     "seeded": any(e["event"] == "seed" for e in ev)}
        events += ev
    try:
        items = (news_fetcher or (lambda: parse_news(get_json(BINANCE_NEWS))))()
        state["news"], ev = diff_news(state["news"], items, now_ms)
        venues[NEWS] = {"ok": True, "count": len(items), "error": None}
        events += ev
    except Exception as e:  # noqa: BLE001
        venues[NEWS] = {"ok": False, "count": 0, "error": why(e)}

    alp = alpaca_bases(state)
    for e in events:
        if e["event"] == "seed":
            continue
        e["alpaca_lists"] = None if alp is None else (e["base"] in alp if e["base"] else None)
        if e["event"] in ("listed", "returned") and alert_worthy(e) and pricer is not None:
            e["price"] = pricer(e["venue"], e["symbol"])

    prefix = notify.config()[2]
    texts = alert_texts(events, prefix)
    text = "\n\n".join(texts)
    delivered = None
    if dry_run:
        print(json.dumps({"venues": venues, "new": [e for e in events if e["event"] != "seed"]}, indent=2))
        if text:
            print(text)
        return {"events": events, "text": text, "texts": texts, "venues": venues, "delivered": None}

    write_lake(events, now_ms, lake_dir())
    notify.write_json(state_p, state)
    notify.write_json(latest_path(), update_recent(notify.read_json(latest_path()), events, venues, now_ms))
    if texts:
        url, fmt, _ = notify.config()
        sent = 0
        for t in texts:
            if poster is not None:
                ok = bool(poster(t))
            elif url is None:
                print(t)
                continue
            else:
                ok, err = notify.post(url, fmt, t)
                if not ok:
                    print(f"listings: alert not delivered: {err}", file=sys.stderr)
            sent += ok
        delivered = None if poster is None and url is None else sent == len(texts)
    for v, s in venues.items():
        if not s["ok"]:
            print(f"listings: {v} skipped ({s['error']})", file=sys.stderr)
    return {"events": events, "text": text, "texts": texts, "venues": venues, "delivered": delivered}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print, write and post nothing")
    a = ap.parse_args(argv)
    r = run(dry_run=a.dry_run)
    new = [e for e in r["events"] if e["event"] in ("listed", "announced")]
    print(f"listings: {len(new)} new, " + ", ".join(f"{v} {s['count'] if s['ok'] else 'skipped'}"
                                                   for v, s in r["venues"].items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
