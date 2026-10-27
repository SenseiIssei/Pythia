"""DexScreener archive (D4): every DEX pair Pythia can find, snapshotted for as long as it lives.
Read-only public data; no wallet, no key, nothing here can trade.

    python -m lab.collect.dexscreener              one run (cron, every 2 minutes): discovery, then tracking
    python -m lab.collect.dexscreener --dry-run    one run, counts printed, nothing written
    python -m lab.collect.dexscreener --health     exit 0 when fresh, 1 when stale (job dexscreener-health)
    python -m lab.collect.dexscreener --compact    merge finished days' run parts into one file a day, prune

DexScreener's API has no history: what is not snapshotted here is lost.

Sources (api.dexscreener.com, public, keyless; limits as published in its API reference):

  60 a minute   /token-profiles/latest/v1, /token-boosts/latest/v1, /token-boosts/top/v1 (every run),
                /community-takeovers/latest/v1, /ads/latest/v1 (every 5th run),
                /orders/v1/<chain>/<token> (paid profile, ads and boosts with their payment time;
                once a token, for tokens with a paid sign, at most ORDERS_PER_RUN a run)
  300 a minute  /tokens/v1/<chain>/<up to 30 tokens> (every pair of those tokens, one call: the
                tracking), /latest/dex/search?q=<word> (four words of the config a run, in turn;
                pairs younger than new_pair_max_age_h are added, so Raydium, Meteora, Orca, PumpSwap
                and the other launchpads' pools come in, not only the paid lists)
  local         <data>/pumpfun_rt/pools.json, the real-time collector's PumpSwap migrations (read
                only): mints migrated in the last 2 hours, so every pump.fun graduation is followed
                on every pool it gets (the cross-launchpad view)

One shared budget per endpoint group for the whole run, far inside the limits: a call to the
60-a-minute group every SLOW_GAP_S (2 s, 30 a minute), to the 300 group every FAST_GAP_S (0.4 s,
150 a minute), and no call after RUN_S seconds, so a run ends before the next one starts. A 429 or
418 stops the group for the run and backs it off for 2, 4, 8 up to 30 minutes across runs
(state.json). The other DexScreener users of the lab (trending, the pump.fun paper watcher) stay
under 30 calls a run, so the IP as a whole stays under half of the published limits.

Tracking. Every pair found is snapshotted on a schedule that thins out with its age (from
pairCreatedAt, else from first seen): every 2 minutes in its first hour, every 15 minutes up to a
day, hourly up to a week, then daily. A pair is alive while its liquidity is at or above
liq_floor_usd (pools without a liquidity figure, such as a pump.fun bonding curve: while it traded
in the last 24 hours); dead pairs keep their schedule and are dropped after dead_drop_days dead.
The tokens endpoint is batched (30 tokens a call), so one call snapshots every pair of 30 tokens;
the youngest pairs go first when the budget is short.

Writes under <write root>/dexscreener/ (PYTHIA_WRITE_ROOT, else PYTHIA_DATA):

  snapshots/chain=<c>/date=<d>/<HHMMSS>.parquet  one row a pair a fetch, collected_at on every row
  snapshots/chain=<c>/date=<d>/day.parquet       a finished day's parts merged (--compact, and
                                                 every run for days before today)
  discovery/chain=<c>/date=<d>/...               what the paid lists, takeovers, ads and searches
                                                 showed: token, source, boost amounts, collected_at
  orders/chain=<c>/date=<d>/...                  paid orders and boosts of a token, payment time
  links/chain=<c>/date=<d>/...                   a token's websites and socials (links only), a row
                                                 when they change; snapshots carry links_hash
  pairs.parquet                                  the pair table: first seen, last seen, last snapshot,
                                                 status (active, dead, dropped), most liquidity,
                                                 rugged (liquidity pulled by more than 90 %)
  tokens.parquet                                 tokens: first seen, discovery sources, orders asked
  state.json                                     backoff, the search turn, the last run's counts
                                                 (the health check reads it)

Size (see research/lab/README.md, D4): 75 to 160 bytes a snapshot row once merged, about 270 rows a
pair in its first week; at the first day's 40 new pairs an hour, 20 to 45 MB a day for Solana.
retention_days (0: forever) deletes snapshot days older than that; budget_gb deletes whole
snapshot days, oldest first, over the budget. The pair, token, orders and links tables are kept.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import polars as pl

from ..data import ROOT, WRITE_ROOT

DEX = "https://api.dexscreener.com"
CONFIG_FILE = Path(__file__).with_name("dexscreener.json")
MIN_MS, HOUR_MS, DAY_MS = 60_000, 3_600_000, 86_400_000
SLOW, FAST = "slow", "fast"                         # the 60 and the 300 a minute groups
SLOW_GAP_S, FAST_GAP_S = 2.0, 0.4
SLOW_MAX, FAST_MAX = 20, 200                        # calls a run at most
RUN_S = 95.0                                        # no call after this many seconds (cron every 2 min)
BATCH = 30                                          # tokens a /tokens/v1 call
ORDERS_PER_RUN = 6
SEARCH_PER_RUN = 4
SLOW_LISTS_EVERY = 5                                # takeovers and ads every 5th run
MIGRATION_WINDOW_MS = 2 * HOUR_MS
PENDING_TRIES = 3                                   # a token without any pair is given up after this
BACKOFF_MIN_S, BACKOFF_MAX_S = 120, 1800
HEALTH_MAX_AGE_MIN = 12
RUG_DROP = 0.90
SLACK_MS = 30_000                                   # a pair due within this is fetched now
SCHEDULE = ((HOUR_MS, 2 * MIN_MS), (DAY_MS, 15 * MIN_MS), (7 * DAY_MS, HOUR_MS))   # age under, every

Fetch = Callable[[str], object]


# ---------------------------------------------------------------- settings and paths

def config(path: Path = CONFIG_FILE, env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    cfg = {"chains": ["solana"], "search": {}, "liq_floor_usd": 1000.0, "dead_drop_days": 30,
           "new_pair_max_age_h": 24.0, "retention_days": 0, "budget_gb": 20.0}
    try:
        cfg.update({k: v for k, v in json.loads(path.read_text(encoding="utf-8")).items() if not k.startswith("_")})
    except (OSError, ValueError):
        pass
    if env.get("PYTHIA_DEXSCREENER_CHAINS"):
        cfg["chains"] = [c.strip().lower() for c in env["PYTHIA_DEXSCREENER_CHAINS"].split(",") if c.strip()]
    for key, name in (("retention_days", "PYTHIA_DEXSCREENER_RETENTION_DAYS"),
                      ("budget_gb", "PYTHIA_DEXSCREENER_BUDGET_GB"),
                      ("liq_floor_usd", "PYTHIA_DEXSCREENER_LIQ_FLOOR")):
        if env.get(name):
            cfg[key] = float(env[name])
    return cfg


def base(root: Path | None = None) -> Path:
    return (root or WRITE_ROOT) / "dexscreener"


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def count(v) -> int | None:
    x = num(v)
    return int(x) if x is not None else None


# ---------------------------------------------------------------- HTTP with a shared budget

class RateLimited(OSError):
    """The group answered 429/418, its budget is spent or the run's time is up."""


def group_of(url: str) -> str:
    path = urllib.parse.urlsplit(url).path
    return FAST if path.startswith(("/tokens/", "/token-pairs/", "/latest/dex/")) else SLOW


class Http:
    """Spaced GET of JSON with one budget per endpoint group for the run. A 429 stops the group."""

    def __init__(self, blocked: set[str] | None = None, run_s: float = RUN_S, sleep=time.sleep,
                 clock=time.monotonic, opener=None):
        self.gaps = {SLOW: SLOW_GAP_S, FAST: FAST_GAP_S}
        self.budgets = {SLOW: SLOW_MAX, FAST: FAST_MAX}
        self.calls = {SLOW: 0, FAST: 0}
        self.last: dict[str, float] = {}
        self.blocked = set(blocked or ())
        self.limited: set[str] = set()                  # got a 429 in this run
        self.sleep, self.clock = sleep, clock
        self.deadline = clock() + run_s
        self.opener = opener or urllib.request.urlopen

    def left(self, group: str) -> int:
        if group in self.blocked or self.clock() >= self.deadline:
            return 0
        return self.budgets[group] - self.calls[group]

    def __call__(self, url: str):
        g = group_of(url)
        if g in self.blocked:
            raise RateLimited(f"{g} group rate limited")
        if self.calls[g] >= self.budgets[g]:
            raise RateLimited(f"{g} group: this run's budget is spent")
        wait = self.last.get(g, -1e9) + self.gaps[g] - self.clock()
        if wait > 0:
            self.sleep(wait)
        if self.clock() >= self.deadline:
            raise RateLimited("the run's time is up")
        self.last[g] = self.clock()
        self.calls[g] += 1
        req = urllib.request.Request(url, headers={"User-Agent": "pythia-lab (research archive, read only)",
                                                   "Accept": "application/json"})
        try:
            with self.opener(req, timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (418, 429):
                self.blocked.add(g)
                self.limited.add(g)
                raise RateLimited(f"{g} group HTTP {e.code}") from e
            raise


def backoff_after(state: dict, limited: set[str], now: int) -> dict:
    """Doubles a group's pause after each run that got a 429, resets it after a clean run."""
    bo = dict(state.get("backoff") or {})
    for g in (SLOW, FAST):
        cur = bo.get(g) or {}
        if g in limited:
            secs = min(BACKOFF_MAX_S, max(BACKOFF_MIN_S, 2 * int(cur.get("secs") or 0)))
            bo[g] = {"secs": secs, "until": now + secs * 1000}
        elif cur and now >= int(cur.get("until") or 0):
            bo.pop(g, None)
    return bo


def blocked_groups(state: dict, now: int) -> set[str]:
    return {g for g, b in (state.get("backoff") or {}).items() if now < int(b.get("until") or 0)}


# ---------------------------------------------------------------- rows

def links_of(info: dict | None) -> tuple[list[dict], list[dict]]:
    info = info or {}
    webs = [{"label": w.get("label"), "url": w.get("url")} for w in info.get("websites") or [] if isinstance(w, dict)]
    socs = [{"type": s.get("type") or s.get("platform"), "url": s.get("url") or s.get("handle")}
            for s in info.get("socials") or [] if isinstance(s, dict)]
    return webs, socs


def links_hash(webs: list[dict], socs: list[dict]) -> str | None:
    if not webs and not socs:
        return None
    blob = json.dumps([webs, socs], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:16]


def snapshot_row(p: dict, now: int) -> dict:
    """One pair of a /tokens/v1 or search answer as a flat point-in-time row."""
    bt, qt = p.get("baseToken") or {}, p.get("quoteToken") or {}
    liq, vol, chg, tx = (p.get(k) or {} for k in ("liquidity", "volume", "priceChange", "txns"))
    info = p.get("info")
    webs, socs = links_of(info)
    row = {"collected_at": now, "chain": p.get("chainId"), "pair": p.get("pairAddress"), "token": bt.get("address"),
           "symbol": bt.get("symbol"), "name": bt.get("name"), "dex": p.get("dexId"),
           "labels": ",".join(str(x) for x in p.get("labels") or []) or None,
           "quote": qt.get("address"), "quote_symbol": qt.get("symbol"),
           "price_usd": num(p.get("priceUsd")), "price_native": num(p.get("priceNative")),
           "liq_usd": num(liq.get("usd")), "liq_base": num(liq.get("base")), "liq_quote": num(liq.get("quote")),
           "fdv": num(p.get("fdv")), "mcap": num(p.get("marketCap")),
           "pair_created_at": count(p.get("pairCreatedAt")),
           "boosts_active": count((p.get("boosts") or {}).get("active")) or 0,
           "has_profile": bool(isinstance(info, dict) and (info.get("imageUrl") or info.get("header"))),
           "n_websites": len(webs), "n_socials": len(socs),
           "social_types": ",".join(sorted({str(s["type"]) for s in socs if s.get("type")})) or None,
           "links_hash": links_hash(webs, socs),
           "_websites": json.dumps(webs, separators=(",", ":")), "_socials": json.dumps(socs, separators=(",", ":"))}
    for w in ("m5", "h1", "h6", "h24"):
        row[f"vol_{w}"] = num(vol.get(w))
        row[f"chg_{w}"] = num(chg.get(w))
        t = tx.get(w) or {}
        row[f"buys_{w}"] = count(t.get("buys"))
        row[f"sells_{w}"] = count(t.get("sells"))
    return row


SNAP_SCHEMA = {"collected_at": pl.Int64, "chain": pl.Utf8, "pair": pl.Utf8, "token": pl.Utf8, "symbol": pl.Utf8,
               "name": pl.Utf8, "dex": pl.Utf8, "labels": pl.Utf8, "quote": pl.Utf8, "quote_symbol": pl.Utf8,
               "price_usd": pl.Float64, "price_native": pl.Float64, "liq_usd": pl.Float64, "liq_base": pl.Float64,
               "liq_quote": pl.Float64, "fdv": pl.Float64, "mcap": pl.Float64, "pair_created_at": pl.Int64,
               "boosts_active": pl.Int64, "has_profile": pl.Boolean, "n_websites": pl.Int64, "n_socials": pl.Int64,
               "social_types": pl.Utf8, "links_hash": pl.Utf8,
               **{f"{k}_{w}": (pl.Float64 if k in ("vol", "chg") else pl.Int64)
                  for w in ("m5", "h1", "h6", "h24") for k in ("vol", "chg", "buys", "sells")}}
DISC_SCHEMA = {"collected_at": pl.Int64, "chain": pl.Utf8, "token": pl.Utf8, "pair": pl.Utf8, "source": pl.Utf8,
               "amount": pl.Float64, "total_amount": pl.Float64, "ad_type": pl.Utf8, "impressions": pl.Float64,
               "n_links": pl.Int64, "pair_created_at": pl.Int64, "dex": pl.Utf8}
ORDER_SCHEMA = {"collected_at": pl.Int64, "chain": pl.Utf8, "token": pl.Utf8, "kind": pl.Utf8, "type": pl.Utf8,
                "status": pl.Utf8, "amount": pl.Float64, "paid_at": pl.Int64}
LINK_SCHEMA = {"collected_at": pl.Int64, "chain": pl.Utf8, "token": pl.Utf8, "links_hash": pl.Utf8,
               "websites": pl.Utf8, "socials": pl.Utf8}
PAIR_SCHEMA = {"chain": pl.Utf8, "pair": pl.Utf8, "token": pl.Utf8, "symbol": pl.Utf8, "dex": pl.Utf8,
               "quote_symbol": pl.Utf8, "created_at": pl.Int64, "first_seen": pl.Int64, "last_seen": pl.Int64,
               "last_snap": pl.Int64, "status": pl.Utf8, "dead_since": pl.Int64, "first_liq": pl.Float64,
               "max_liq": pl.Float64, "last_liq": pl.Float64, "rugged": pl.Boolean, "rug_at": pl.Int64,
               "misses": pl.Int64, "snaps": pl.Int64}
TOKEN_SCHEMA = {"chain": pl.Utf8, "token": pl.Utf8, "first_seen": pl.Int64, "sources": pl.Utf8,
                "last_fetch": pl.Int64, "tries": pl.Int64, "paid": pl.Boolean, "orders_at": pl.Int64,
                "links_hash": pl.Utf8}


def frame(rows: list[dict], schema: dict) -> pl.DataFrame:
    return pl.DataFrame([{k: r.get(k) for k in schema} for r in rows], schema=schema, orient="row")


# ---------------------------------------------------------------- the pair schedule

def interval_ms(age_ms: int) -> int:
    for under, every in SCHEDULE:
        if age_ms < under:
            return every
    return DAY_MS


def alive(row: dict, floor: float) -> bool:
    """Liquidity at the floor or above; a pool without a liquidity figure while it traded in 24 h."""
    liq = row.get("liq_usd")
    if liq is not None:
        return liq >= floor
    return ((row.get("buys_h24") or 0) + (row.get("sells_h24") or 0)) > 0


def pair_due(p: dict, now: int) -> bool:
    if p.get("status") == "dropped":
        return False
    if not p.get("last_snap"):
        return True
    age = now - int(p.get("created_at") or p.get("first_seen") or now)
    return now - int(p["last_snap"]) >= interval_ms(age) - SLACK_MS


def update_pair(pairs: dict, row: dict, now: int, floor: float, drop_days: float) -> dict:
    key = (row["chain"], row["pair"])
    p = pairs.get(key) or {"chain": row["chain"], "pair": row["pair"], "first_seen": now, "status": "active",
                           "first_liq": row.get("liq_usd"), "max_liq": None, "rugged": False, "misses": 0, "snaps": 0}
    p.update({"token": row["token"], "symbol": row.get("symbol"), "dex": row.get("dex"),
              "quote_symbol": row.get("quote_symbol"), "created_at": row.get("pair_created_at") or p.get("created_at"),
              "last_seen": now, "last_snap": now, "last_liq": row.get("liq_usd"), "misses": 0,
              "snaps": int(p.get("snaps") or 0) + 1})
    liq = row.get("liq_usd")
    if liq is not None:
        if p.get("first_liq") is None:
            p["first_liq"] = liq
        p["max_liq"] = max(liq, p.get("max_liq") or 0.0)
        if not p.get("rugged") and (p["max_liq"] or 0) >= floor and liq < (1 - RUG_DROP) * p["max_liq"]:
            p["rugged"], p["rug_at"] = True, now
    if alive(row, floor):
        p["status"], p["dead_since"] = "active", None
    else:
        p["dead_since"] = p.get("dead_since") or now
        p["status"] = "dropped" if now - p["dead_since"] >= drop_days * DAY_MS else "dead"
    pairs[key] = p
    return p


def miss_pair(p: dict, now: int, drop_days: float) -> None:
    """Asked for, not in the answer: counted as dead from the third miss on (DexScreener drops dead pools)."""
    p["misses"] = int(p.get("misses") or 0) + 1
    p["last_snap"] = now
    if p["misses"] >= 3 and p.get("status") == "active":
        p["status"], p["dead_since"] = "dead", now
    if p.get("dead_since") and now - p["dead_since"] >= drop_days * DAY_MS:
        p["status"] = "dropped"


def due_tokens(pairs: dict, tokens: dict, now: int, chains: list[str]) -> list[tuple[str, str]]:
    """Tokens to fetch: never fetched first, then those with a due pair, youngest pair first."""
    rank: dict[tuple[str, str], float] = {}
    for key, t in tokens.items():
        if key[0] in chains and not t.get("last_fetch") and int(t.get("tries") or 0) < PENDING_TRIES:
            rank[key] = -1.0
    for p in pairs.values():
        key = (p["chain"], p["token"])
        if p["chain"] not in chains or key in rank or not pair_due(p, now):
            continue
        age = now - int(p.get("created_at") or p.get("first_seen") or now)
        rank[key] = min(rank.get(key, math.inf), float(age))
    return sorted(rank, key=lambda k: rank[k])


# ---------------------------------------------------------------- discovery

def note_token(tokens: dict, chain: str, token: str, source: str, now: int, paid: bool = False) -> bool:
    key = (chain, token)
    t = tokens.get(key)
    new = t is None
    if new:
        t = tokens[key] = {"chain": chain, "token": token, "first_seen": now, "sources": source, "tries": 0,
                           "paid": paid}
    elif source not in (t.get("sources") or "").split(","):
        t["sources"] = ",".join(x for x in ((t.get("sources") or "").split(",") + [source]) if x)
    t["paid"] = bool(t.get("paid")) or paid
    return new


LISTS = (("/token-profiles/latest/v1", "profile", True), ("/token-boosts/latest/v1", "boost_latest", True),
         ("/token-boosts/top/v1", "boost_top", True), ("/community-takeovers/latest/v1", "cto", False),
         ("/ads/latest/v1", "ad", True))


def discover_lists(get: Fetch, http: Http | None, tokens: dict, chains: list[str], now: int, run_no: int,
                   errors: list[str]) -> list[dict]:
    rows = []
    for path, source, paid in LISTS:
        if source in ("cto", "ad") and run_no % SLOW_LISTS_EVERY:
            continue
        if http is not None and not http.left(SLOW):
            break
        try:
            items = get(f"{DEX}{path}")
        except RateLimited as e:
            errors.append(f"{source}: {e}")
            break
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append(f"{source}: {type(e).__name__}")
            continue
        for it in items if isinstance(items, list) else []:
            chain, token = it.get("chainId"), it.get("tokenAddress")
            if chain not in chains or not token:
                continue
            note_token(tokens, chain, token, source, now, paid)
            rows.append({"collected_at": now, "chain": chain, "token": token, "source": source,
                         "amount": num(it.get("amount")), "total_amount": num(it.get("totalAmount")),
                         "ad_type": it.get("type"), "impressions": num(it.get("impressions")),
                         "n_links": len(it.get("links") or [])})
    return rows


def discover_search(get: Fetch, tokens: dict, pairs: dict, cfg: dict, now: int, turn: int,
                    errors: list[str]) -> tuple[list[dict], list[dict]]:
    """Search words in turn; pairs younger than new_pair_max_age_h become tracked (with this first snapshot)."""
    words = [(c, w) for c in cfg["chains"] for w in (cfg.get("search") or {}).get(c, [])]
    rows, snaps = [], []
    if not words:
        return rows, snaps
    max_age = float(cfg.get("new_pair_max_age_h") or 24) * HOUR_MS
    for i in range(min(SEARCH_PER_RUN, len(words))):
        chain, word = words[(turn + i) % len(words)]
        try:
            got = get(f"{DEX}/latest/dex/search?q={urllib.parse.quote(word)}")
        except RateLimited as e:
            errors.append(f"search: {e}")
            break
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append(f"search {word}: {type(e).__name__}")
            continue
        for p in (got or {}).get("pairs") or [] if isinstance(got, dict) else []:
            created = count(p.get("pairCreatedAt"))
            if p.get("chainId") != chain or not created or now - created > max_age:
                continue
            r = snapshot_row(p, now)
            if not r["pair"] or not r["token"]:
                continue
            note_token(tokens, chain, r["token"], f"search:{word}", now)
            rows.append({"collected_at": now, "chain": chain, "token": r["token"], "pair": r["pair"],
                         "source": f"search:{word}", "pair_created_at": created, "dex": r["dex"]})
            if (chain, r["pair"]) not in pairs and all(x["pair"] != r["pair"] for x in snaps):
                snaps.append(r)
    return rows, snaps


def discover_migrations(tokens: dict, now: int, root: Path | None = None) -> list[dict]:
    """pump.fun graduations the real-time collector saw (pool -> [mint, migrated at ms]), last 2 hours."""
    path = (root or ROOT) / "pumpfun_rt" / "pools.json"
    try:
        pools = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = []
    for pool, v in pools.items() if isinstance(pools, dict) else []:
        try:
            mint, at = str(v[0]), int(v[1])
        except (TypeError, ValueError, IndexError):
            continue
        if now - MIGRATION_WINDOW_MS <= at <= now and note_token(tokens, "solana", mint, "pumpfun_migration", now):
            rows.append({"collected_at": now, "chain": "solana", "token": mint, "pair": pool,
                         "source": "pumpfun_migration", "pair_created_at": at, "dex": "pumpswap"})
    return rows


def fetch_orders(get: Fetch, http: Http | None, tokens: dict, chains: list[str], now: int,
                 errors: list[str]) -> list[dict]:
    """Paid orders and boosts of tokens with a paid sign, once a token, newest first."""
    rows = []
    todo = sorted((t for t in tokens.values() if t["chain"] in chains and t.get("paid") and not t.get("orders_at")),
                  key=lambda t: -int(t.get("first_seen") or 0))[:ORDERS_PER_RUN]
    for t in todo:
        if http is not None and not http.left(SLOW):
            break
        try:
            got = get(f"{DEX}/orders/v1/{urllib.parse.quote(t['chain'])}/{urllib.parse.quote(t['token'])}")
        except RateLimited as e:
            errors.append(f"orders: {e}")
            break
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append(f"orders: {type(e).__name__}")
            continue
        t["orders_at"] = now
        orders = got if isinstance(got, list) else (got or {}).get("orders") or [] if isinstance(got, dict) else []
        boosts = (got or {}).get("boosts") or [] if isinstance(got, dict) else []
        for o in orders:
            rows.append({"collected_at": now, "chain": t["chain"], "token": t["token"], "kind": "order",
                         "type": o.get("type"), "status": o.get("status"), "paid_at": count(o.get("paymentTimestamp"))})
        for b in boosts:
            rows.append({"collected_at": now, "chain": t["chain"], "token": t["token"], "kind": "boost",
                         "type": "boost", "amount": num(b.get("amount")), "paid_at": count(b.get("paymentTimestamp"))})
        if not orders and not boosts:
            rows.append({"collected_at": now, "chain": t["chain"], "token": t["token"], "kind": "none"})
    return rows


# ---------------------------------------------------------------- tracking

def track(get: Fetch, http: Http | None, pairs: dict, tokens: dict, cfg: dict, now: int,
          errors: list[str]) -> tuple[list[dict], int]:
    floor, drop = float(cfg["liq_floor_usd"]), float(cfg["dead_drop_days"])
    todo = due_tokens(pairs, tokens, now, cfg["chains"])
    by_chain: dict[str, list[str]] = {}
    for chain, token in todo:
        by_chain.setdefault(chain, []).append(token)
    by_token: dict[tuple[str, str], list[dict]] = {}
    for p in pairs.values():
        by_token.setdefault((p["chain"], p["token"]), []).append(p)
    snaps, calls = [], 0
    batches = [(c, ts[i:i + BATCH]) for c, ts in by_chain.items() for i in range(0, len(ts), BATCH)]
    batches.sort(key=lambda b: todo.index((b[0], b[1][0])))          # youngest first across chains
    for chain, batch in batches:
        if http is not None and not http.left(FAST):
            break
        try:
            got = get(f"{DEX}/tokens/v1/{urllib.parse.quote(chain)}/{urllib.parse.quote(','.join(batch), safe=',')}")
        except RateLimited as e:
            errors.append(f"tokens: {e}")
            break
        except (urllib.error.URLError, OSError, ValueError) as e:
            errors.append(f"tokens: {type(e).__name__}")
            continue
        calls += 1
        want = {t.lower(): t for t in batch}
        seen_pairs: set[str] = set()
        seen_tokens: set[str] = set()
        for p in got if isinstance(got, list) else []:
            bt = ((p.get("baseToken") or {}).get("address") or "")
            if p.get("chainId") != chain or bt.lower() not in want or not p.get("pairAddress"):
                continue
            r = snapshot_row(p, now)
            r["token"] = want[bt.lower()]
            snaps.append(r)
            if (r["has_profile"] or r["boosts_active"]) and (chain, r["token"]) in tokens:
                tokens[(chain, r["token"])]["paid"] = True  # a paid sign: its orders are asked once
            if (chain, r["pair"]) not in pairs:
                by_token.setdefault((chain, r["token"]), []).append(update_pair(pairs, r, now, floor, drop))
            else:
                update_pair(pairs, r, now, floor, drop)
            seen_pairs.add(r["pair"])
            seen_tokens.add(r["token"])
        for token in batch:
            for p in by_token.get((chain, token), []):
                if p["pair"] not in seen_pairs and pair_due(p, now):
                    miss_pair(p, now, drop)
        for token in batch:
            t = tokens.get((chain, token))
            if t is None:
                continue
            t["last_fetch"] = now if token in seen_tokens else t.get("last_fetch")
            if token not in seen_tokens:
                t["tries"] = int(t.get("tries") or 0) + 1
    return snaps, calls


def links_rows(snaps: list[dict], tokens: dict, now: int) -> list[dict]:
    """A links row for a token whose websites or socials changed since the last one stored."""
    rows = []
    for r in snaps:
        t = tokens.get((r["chain"], r["token"]))
        if t is None or not r.get("links_hash") or t.get("links_hash") == r["links_hash"]:
            continue
        t["links_hash"] = r["links_hash"]
        rows.append({"collected_at": now, "chain": r["chain"], "token": r["token"], "links_hash": r["links_hash"],
                     "websites": r.get("_websites"), "socials": r.get("_socials")})
    return rows


# ---------------------------------------------------------------- storage

def _atomic_parquet(df: pl.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".parquet.tmp")
    df.write_parquet(tmp, compression="zstd")
    os.replace(tmp, path)


def write_parts(table: str, rows: list[dict], schema: dict, now: int, root: Path | None = None) -> list[Path]:
    if not rows:
        return []
    out = []
    df = frame(rows, schema)
    name = datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%H%M%S") + ".parquet"
    for (chain,), part in df.group_by(["chain"]):
        path = base(root) / table / f"chain={chain}" / f"date={day_of(now)}" / name
        _atomic_parquet(part, path)
        out.append(path)
    return out


def load_table(name: str, key: tuple[str, ...], root: Path | None = None) -> dict:
    path = base(root) / f"{name}.parquet"
    if not path.exists():
        return {}
    return {tuple(r[k] for k in key): r for r in pl.read_parquet(path).to_dicts()}


def save_table(name: str, rows: dict, schema: dict, root: Path | None = None) -> None:
    _atomic_parquet(frame(list(rows.values()), schema), base(root) / f"{name}.parquet")


def load_state(root: Path | None = None) -> dict:
    try:
        return json.loads((base(root) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict, root: Path | None = None) -> None:
    path = base(root) / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


TABLES = {"snapshots": SNAP_SCHEMA, "discovery": DISC_SCHEMA, "orders": ORDER_SCHEMA, "links": LINK_SCHEMA}


def compact(now: int, root: Path | None = None) -> int:
    """Merge the run parts of every finished day into day.parquet. Returns the days merged."""
    merged, today = 0, day_of(now)
    for table, schema in TABLES.items():
        for d in sorted(base(root).glob(f"{table}/chain=*/date=*")):
            parts = [f for f in d.glob("*.parquet") if f.name != "day.parquet"]
            if d.name >= f"date={today}" or not parts:
                continue
            files = ([d / "day.parquet"] if (d / "day.parquet").exists() else []) + sorted(parts)
            df = pl.concat([pl.read_parquet(f).cast(schema, strict=False) for f in files], how="diagonal_relaxed")
            _atomic_parquet(df.sort("collected_at"), d / "day.parquet")
            for f in parts:
                f.unlink()
            merged += 1
    return merged


def dir_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.exists() else 0


def prune(cfg: dict, now: int, root: Path | None = None) -> list[str]:
    """Snapshot days past retention_days, then the oldest days over budget_gb. Never today."""
    snaps = base(root) / "snapshots"
    days = sorted({d.name[5:] for d in snaps.glob("chain=*/date=*")})
    gone = []
    keep_days = float(cfg.get("retention_days") or 0)
    if keep_days > 0:
        cut = day_of(now - int(keep_days * DAY_MS))
        for day in [x for x in days if x < cut]:
            for d in snaps.glob(f"chain=*/date={day}"):
                shutil.rmtree(d)
            gone.append(day)
    budget = float(cfg.get("budget_gb") or 0) * 1e9
    days = [x for x in days if x not in gone and x < day_of(now)]
    while budget > 0 and days and dir_bytes(snaps) > budget:
        day = days.pop(0)
        for d in snaps.glob(f"chain=*/date={day}"):
            shutil.rmtree(d)
        gone.append(day)
    return gone


# ---------------------------------------------------------------- one run

def run(get: Fetch | None = None, now: int | None = None, cfg: dict | None = None, root: Path | None = None,
        data_root: Path | None = None, dry_run: bool = False) -> dict:
    now = now or int(time.time() * 1000)
    cfg = cfg or config()
    state = load_state(root)
    http = None
    if get is None:
        http = Http(blocked=blocked_groups(state, now))
        get = http
    pairs = load_table("pairs", ("chain", "pair"), root)
    tokens = load_table("tokens", ("chain", "token"), root)
    run_no = int(state.get("runs") or 0) + 1
    errors: list[str] = []
    n_tokens0, n_pairs0 = len(tokens), len(pairs)

    disc = discover_lists(get, http, tokens, cfg["chains"], now, run_no, errors)
    found, search_snaps = discover_search(get, tokens, pairs, cfg, now, int(state.get("search_turn") or 0), errors)
    disc += found
    if "solana" in cfg["chains"]:
        disc += discover_migrations(tokens, now, data_root)
    orders = fetch_orders(get, http, tokens, cfg["chains"], now, errors)
    for r in search_snaps:                          # snapshotted by the search itself: not fetched again this run
        update_pair(pairs, r, now, float(cfg["liq_floor_usd"]), float(cfg["dead_drop_days"]))
        t = tokens[(r["chain"], r["token"])]
        t["last_fetch"] = now
        t["paid"] = bool(t.get("paid") or r["has_profile"] or r["boosts_active"])
    snaps, calls = track(get, http, pairs, tokens, cfg, now, errors)
    snaps = search_snaps + snaps
    links = links_rows(snaps, tokens, now)

    status_n = {}
    for p in pairs.values():
        status_n[p["status"]] = status_n.get(p["status"], 0) + 1
    summary = {"t": now, "at": datetime.fromtimestamp(now / 1000, timezone.utc).isoformat()[:19] + "Z",
               "chains": cfg["chains"], "snapshots": len(snaps), "token_calls": calls,
               "discovered_rows": len(disc), "new_tokens": len(tokens) - n_tokens0,
               "new_pairs": len(pairs) - n_pairs0, "pairs": status_n, "tokens": len(tokens),
               "orders_rows": len(orders), "links_rows": len(links), "errors": errors[:10],
               "calls": dict(http.calls) if http else None, "limited": sorted(http.limited) if http else []}
    if dry_run:
        return summary
    for table, rows in (("snapshots", snaps), ("discovery", disc), ("orders", orders), ("links", links)):
        write_parts(table, rows, TABLES[table], now, root)
    save_table("pairs", pairs, PAIR_SCHEMA, root)
    save_table("tokens", tokens, TOKEN_SCHEMA, root)
    summary["compacted"] = compact(now, root)
    summary["pruned"] = prune(cfg, now, root)
    words = sum(len((cfg.get("search") or {}).get(c, [])) for c in cfg["chains"])
    state.update({"runs": run_no, "last": summary, "search_turn": (int(state.get("search_turn") or 0)
                                                                   + SEARCH_PER_RUN) % max(1, words),
                  "backoff": backoff_after(state, set(http.limited) if http else set(), now)})
    if snaps:
        state["last_snapshot"] = now
    save_state(state, root)
    return summary


# ---------------------------------------------------------------- health

def check(now: int | None = None, max_age_min: float = HEALTH_MAX_AGE_MIN, root: Path | None = None) -> tuple[bool, str]:
    """Fresh: a run in the last max_age_min minutes that wrote snapshots and was not rate limited out."""
    now = now or int(time.time() * 1000)
    st = load_state(root)
    last, snap = st.get("last") or {}, int(st.get("last_snapshot") or 0)
    problems = []
    if not last:
        problems.append("no run recorded")
    elif now - int(last.get("t") or 0) > max_age_min * MIN_MS:
        problems.append(f"last run {(now - int(last['t'])) / MIN_MS:.0f} min ago")
    if not snap:
        problems.append("no snapshot written yet")
    elif now - snap > max_age_min * MIN_MS:
        problems.append(f"last snapshot {(now - snap) / MIN_MS:.0f} min ago")
    bo = blocked_groups(st, now)
    detail = (f"{last.get('snapshots', 0)} snapshots and {last.get('new_pairs', 0)} new pairs in the last run, "
              f"{sum((last.get('pairs') or {}).values())} pairs ({(last.get('pairs') or {}).get('active', 0)} active), "
              f"{last.get('tokens', 0)} tokens" + (f", backing off: {', '.join(sorted(bo))}" if bo else "")
              + (f", errors: {'; '.join(last.get('errors') or [])}" if last.get("errors") else "")) if last else ""
    if problems:
        return False, "DexScreener archive: " + "; ".join(problems) + (f" ({detail})" if detail else "")
    return True, "DexScreener archive ok: " + detail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--health", action="store_true")
    ap.add_argument("--compact", action="store_true")
    ap.add_argument("--max-age-min", type=float, default=HEALTH_MAX_AGE_MIN)
    a = ap.parse_args(argv)
    if a.health:
        ok, msg = check(max_age_min=a.max_age_min)
        print(msg)
        return 0 if ok else 1
    now = int(time.time() * 1000)
    if a.compact:
        print(json.dumps({"compacted": compact(now), "pruned": prune(config(), now)}))
        return 0
    s = run(dry_run=a.dry_run)
    print(json.dumps(s, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
