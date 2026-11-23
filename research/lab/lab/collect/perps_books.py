"""Order book snapshots of the M4 perps books' coins on Kraken Futures and Hyperliquid, public endpoints only (no key).

    python -m lab.collect.perps_books            one run: a snapshot of every symbol, health, the hourly report
    python -m lab.collect.perps_books report     the coverage report only (reports/perps_books/latest.md)

C2 (results/perps_books_c2_prereg.md). The universe is each book's own: the 100 most liquid Binance USDT perps on
the xs_daily panel cache's newest day with perp liquidity, among those Binance trades now (m4_ls.candidates' liquid
set), cut to the coins the venue lists the way the book cuts them (m4_perps.coin_of on Kraken Futures' PF_
listing, m4_hl_small.hl_coin on Hyperliquid's), plus any coin the book holds that fell out. Built once a UTC day; a failed build keeps the last.

Every 5 minutes, 20 levels a side: Kraken Futures `GET /derivatives/api/v3/orderbook?symbol=PF_..` (the whole book,
cut to the best 20) and Hyperliquid `POST /info {"type": "l2Book"}` (20 levels, weight 2). One call every 0.5 s per
venue (Hyperliquid: 240 of its 1,200 weight a minute). A 429 waits Retry-After or 2, 4, 8 s, then the venue stops for
this run and the health line names the 429 as the venue's rate limit. The run at a book's rebalance minute (the
paper job's schedule, REBALANCE) takes that venue first; its rows within a minute of it carry rebalance true.

Stored point in time (lab.collect.pit's columns) under <write root>/perps_books/<venue>/<YYYY-MM-DD>.parquet:
ts_us (the venue's book time), collected_us, known_us (= collected_us), backfilled (false), slot_us (the 5-minute
slot of collected_us), symbol (the venue's), coin, rebalance, bid_px, bid_sz, ask_px, ask_sz (lists, best first).
The first snapshot of a symbol in a slot wins. health.json beside it (the `feeds` row perps-books): a venue red when
a run lost more than 10 % of its symbols, or under 90 % coverage on the last finished UTC day after the first full
day of recording; red when a finished day stored more than BUDGET_MB over both venues. Data only: no book, study,
bot or engine reads it yet.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import polars as pl

from .. import report
from ..data import ROOT, WRITE_ROOT
from . import pit

VENUES = ("kraken_futures", "hyperliquid")
NAMES = {"kraken_futures": "Kraken Futures", "hyperliquid": "Hyperliquid"}
BOOKS = {"kraken_futures": "m4_perps", "hyperliquid": "m4_hl_small"}
# (hour, minute) UTC of each book's paper job (research/ops/jobs.yaml paper-m4-perps, paper-m4-hl-small)
REBALANCE = {"kraken_futures": (5, 15), "hyperliquid": (6, 0)}
KF_BOOK = "https://futures.kraken.com/derivatives/api/v3/orderbook?symbol={sym}"
KF_INSTRUMENTS = "https://futures.kraken.com/derivatives/api/v3/instruments"
HL_INFO = "https://api.hyperliquid.xyz/info"
BINANCE_INFO = "https://fapi.binance.com/fapi/v1/exchangeInfo"
LEVELS = 20
N_LIQUID = 100
PAUSE = 0.5
TRIES_429 = 4                 # the first call and three waits (2, 4, 8 s or Retry-After, at most 30 s)
DEADLINE_S = 200              # a run never runs into the next one's slot
SLOT_US = 5 * 60 * 1_000_000
SLOTS_DAY = pit.DAY_US // SLOT_US
REBALANCE_WINDOW_US = 60 * 1_000_000
COVERAGE_MIN = 0.90
LOST_MAX = 0.10               # a run that loses more than this share of a venue's symbols is red until the next
BUDGET_MB = 100              # stored a day over both venues (results/perps_books_c2_prereg.md)
KEEP_DAYS = 10                # days of universe kept in the state
PIT_COLS = ["ts_us", "collected_us", "known_us", "backfilled", "slot_us", "symbol", "coin", "rebalance",
            "bid_px", "bid_sz", "ask_px", "ask_sz"]
LEVEL = pl.List(pl.Float64)
SCHEMA = {"ts_us": pl.Int64, "collected_us": pl.Int64, "known_us": pl.Int64, "backfilled": pl.Boolean,
          "slot_us": pl.Int64, "symbol": pl.Utf8, "coin": pl.Utf8, "rebalance": pl.Boolean,
          "bid_px": LEVEL, "bid_sz": LEVEL, "ask_px": LEVEL, "ask_sz": LEVEL}

Fetch = Callable[..., object]


def root() -> Path:
    return Path(os.environ.get("PYTHIA_PERPS_BOOKS") or WRITE_ROOT / "perps_books")


def panel_path() -> Path:
    return Path(os.environ.get("PYTHIA_CACHE") or ROOT / "lab-cache") / "xs_daily_panel.parquet"


def day_str(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def day_us(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


# ---------------------------------------------------------------- HTTP

class RateLimited(Exception):
    """The venue answered 429 TRIES_429 times in a row."""


def request(url: str, body: dict | None = None) -> object:
    data = None if body is None else json.dumps(body).encode()
    headers = {"User-Agent": pit.UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


class Venue:
    """The calls to one venue: one every PAUSE seconds, a 429 backed off and counted."""

    def __init__(self, venue: str, fetch: Fetch, sleep=time.sleep, clock=time.time):
        self.venue, self.fetch, self.sleep, self.clock = venue, fetch, sleep, clock
        self.last = -1e18
        self.n429 = 0

    def call(self, url: str, body: dict | None = None) -> object:
        for k in range(TRIES_429):
            wait = self.last + PAUSE - self.clock()
            if wait > 0:
                self.sleep(wait)
            self.last = self.clock()
            try:
                return self.fetch(url, body)
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    raise
                self.n429 += 1
                if k == TRIES_429 - 1:
                    break
                after = (e.headers.get("Retry-After") if e.headers is not None else None) or 0
                try:
                    after = float(after)
                except ValueError:
                    after = 0.0
                self.sleep(min(30.0, after or 2.0 ** (k + 1)))
        raise RateLimited(f"HTTP 429 from {NAMES[self.venue]} (its rate limit)")


# ---------------------------------------------------------------- the books' universes

def liquid(path: Path, live: set[str] | None) -> tuple[list[str], str]:
    """The n_liquid most liquid perps of the panel's last day with perp liquidity for them (m4_ls.candidates' set
    before the score; the cached panel's newest day often has no perp columns yet), most liquid first, and that day."""
    lf = pl.scan_parquet(path).filter(pl.col("perp").is_not_null() & pl.col("perp_adv28").is_not_null())
    if live is not None:
        lf = lf.filter(pl.col("perp").is_in(sorted(live)))
    n = lf.group_by("day").len().filter(pl.col("len") >= N_LIQUID).collect()
    if n.is_empty():
        raise ValueError(f"{path.name}: no day with {N_LIQUID} perps")
    last = int(n["day"].max())
    df = lf.filter(pl.col("day") == last).select("perp", "perp_adv28").collect()
    return df.sort("perp_adv28", descending=True).head(N_LIQUID)["perp"].to_list(), day_str(last)


def binance_live(answer: dict) -> set[str]:
    return {s["symbol"] for s in answer.get("symbols") or [] if s.get("contractType") == "PERPETUAL"
            and s.get("status") == "TRADING" and s.get("quoteAsset") == "USDT"}


def held(book: str) -> list[str]:
    """What the paper book holds now: Binance perps (m4_perps' weights) or Hyperliquid coins (m4_hl_small's units)."""
    try:
        st = json.loads((ROOT / "paper" / book / "state.json").read_text())
    except (OSError, ValueError):
        return []
    pos = st.get("weights") if book == "m4_perps" else st.get("units")
    return sorted(k for k, v in (pos or {}).items() if v)


def kraken_universe(perps: list[str], listing: dict[str, str], holds: list[str]) -> list[dict]:
    """[{coin, symbol, held}] in liquidity order, one per coin, then the held coins that fell out."""
    from ..paper import m4_perps as mp
    out, seen = [], set()
    for p in perps + holds:
        c = mp.coin_of(p)
        if c in listing and c not in seen:
            seen.add(c)
            out.append({"coin": c, "symbol": listing[c], "held": p in holds})
    return out


def hl_universe(perps: list[str], listed: set[str], holds: list[str]) -> list[dict]:
    """The same on Hyperliquid's coins (m4_hl_small holds Hyperliquid coins, not Binance perps)."""
    from ..paper import m4_hl_small as hs
    out, seen = [], set()
    for c in [hs.hl_coin(p, listed) for p in perps] + [c for c in holds if c in listed]:
        if c and c not in seen:
            seen.add(c)
            out.append({"coin": c, "symbol": c, "held": c in holds})
    return out


def build_universe(vs: dict[str, Venue], binance: Fetch) -> dict:
    """{venue: [{coin, symbol, held}], panel_day}. Raises when the panel or a listing cannot be read."""
    from ..paper import m4_hl_small as hs
    from ..paper import m4_perps as mp
    perps, pday = liquid(panel_path(), binance_live(binance(BINANCE_INFO, None)))
    listing = mp.parse_listing(vs["kraken_futures"].call(KF_INSTRUMENTS))
    listed = set(hs.parse_ctxs(vs["hyperliquid"].call(HL_INFO, {"type": "metaAndAssetCtxs"})))
    return {"panel_day": pday,
            "kraken_futures": kraken_universe(perps, listing, held("m4_perps")),
            "hyperliquid": hl_universe(perps, listed, held("m4_hl_small"))}


# ---------------------------------------------------------------- one snapshot

def _side(levels, desc: bool) -> tuple[list[float], list[float]]:
    lv = sorted(((float(p), float(s)) for p, s in levels), key=lambda x: -x[0] if desc else x[0])[:LEVELS]
    return [p for p, _ in lv], [s for _, s in lv]


def parse_kraken(answer: dict) -> tuple[int, tuple, tuple]:
    """(book time, bids, asks) of an orderbook answer; Kraken sends the whole book, bids worst first."""
    if not isinstance(answer, dict) or answer.get("result") != "success" or "orderBook" not in answer:
        raise ValueError(f"orderbook answer: {str(answer)[:200]}")
    ob = answer["orderBook"]
    t = answer.get("serverTime")
    ts = int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1e6) if t else None
    return ts, _side(ob.get("bids") or [], True), _side(ob.get("asks") or [], False)


def parse_hl(answer: dict) -> tuple[int, tuple, tuple]:
    if not isinstance(answer, dict) or not isinstance(answer.get("levels"), list) or len(answer["levels"]) != 2:
        raise ValueError(f"l2Book answer: {str(answer)[:200]}")
    b, a = answer["levels"]
    ts = int(answer["time"]) * 1000 if answer.get("time") else None
    return ts, _side([(x["px"], x["sz"]) for x in b], True), _side([(x["px"], x["sz"]) for x in a], False)


def snapshot(v: Venue, u: dict) -> tuple[int | None, tuple, tuple]:
    if v.venue == "kraken_futures":
        return parse_kraken(v.call(KF_BOOK.format(sym=u["symbol"])))
    return parse_hl(v.call(HL_INFO, {"type": "l2Book", "coin": u["symbol"]}))


def rebalance_us(venue: str, t_us: int) -> int:
    h, m = REBALANCE[venue]
    return day_us(day_str(t_us)) + (h * 60 + m) * 60_000_000


def take(v: Venue, universe: list[dict], start: float, now_us: Callable[[], int]) -> tuple[list[dict], dict]:
    """Snapshots of the venue's universe until the deadline; (rows, what happened)."""
    rows, failed, err = [], 0, None
    for i, u in enumerate(universe):
        if v.clock() - start > DEADLINE_S:
            err = f"deadline {DEADLINE_S} s reached"
            failed += len(universe) - i
            break
        try:
            ts, (bp, bs), (ap, az) = snapshot(v, u)
        except RateLimited as e:
            err = str(e)
            failed += len(universe) - i
            break
        except Exception as e:  # noqa: BLE001 - one symbol failing does not stop the others
            failed += 1
            err = err or f"{u['symbol']}: {type(e).__name__}: {e}"[:160]
            continue
        got = now_us()
        reb = abs(got - rebalance_us(v.venue, got)) <= REBALANCE_WINDOW_US
        rows.append({"ts_us": ts or got, "collected_us": got, "known_us": got, "backfilled": False,
                     "slot_us": got // SLOT_US * SLOT_US, "symbol": u["symbol"], "coin": u["coin"],
                     "rebalance": reb, "bid_px": bp, "bid_sz": bs, "ask_px": ap, "ask_sz": az})
    return rows, {"asked": len(universe), "taken": len(rows), "failed": failed, "error": err, "n429": v.n429}


# ---------------------------------------------------------------- storage

def day_file(venue: str, day: str) -> Path:
    return root() / venue / f"{day}.parquet"


def store(venue: str, rows: list[dict]) -> int:
    """Append to each row's day file (a symbol's first snapshot in a slot wins), through a temporary file."""
    if not rows:
        return 0
    new = pl.DataFrame(rows, schema=SCHEMA)
    n = 0
    for (day,), part in new.group_by(pl.col("collected_us").map_elements(day_str, return_dtype=pl.Utf8)):
        p = day_file(venue, day)
        if p.exists():
            try:
                old = pl.read_parquet(p)
                part = part.join(old.select("symbol", "slot_us"), on=["symbol", "slot_us"], how="anti")
                part = pl.concat([old, part], how="vertical_relaxed")
            except Exception as e:  # noqa: BLE001 - a truncated file (a cut run) is started again
                print(f"{p.name}: unreadable ({type(e).__name__}), replaced", file=sys.stderr)
        out = part.unique(["symbol", "slot_us"], keep="first").sort(["slot_us", "symbol"])
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        out.write_parquet(tmp)
        os.replace(tmp, p)
        n += out.height
    return n


def read_slots(venue: str, day: str) -> pl.DataFrame | None:
    p = day_file(venue, day)
    if not p.exists():
        return None
    try:
        return pl.read_parquet(p, columns=["symbol", "slot_us", "rebalance"])
    except Exception:  # noqa: BLE001 - unreadable counts as nothing stored
        return None


# ---------------------------------------------------------------- coverage

def coverage(venue: str, day: str, expected: list[str], until_us: int | None = None, first: bool = False) -> dict:
    """One venue-day: symbols expected and seen, snapshots per symbol, coverage of the expected symbols x slots
    (until_us: only the slots to its own, for today; first: from the day's first stored slot, the first day of
    recording), missing symbol-slots, slots with no snapshot at all, the longest run of those in minutes,
    rebalance snapshots."""
    d0 = day_us(day)
    df = read_slots(venue, day)
    df = df if df is not None else pl.DataFrame(schema={"symbol": pl.Utf8, "slot_us": pl.Int64,
                                                        "rebalance": pl.Boolean})
    hi = SLOTS_DAY if until_us is None else max(0, min(SLOTS_DAY, (until_us - d0) // SLOT_US + 1))
    lo = (int(df["slot_us"].min()) - d0) // SLOT_US if first and df.height else 0
    df = df.filter(pl.col("slot_us") < d0 + hi * SLOT_US)
    d0, slots = d0 + lo * SLOT_US, max(0, hi - lo)
    want = sorted(set(expected))
    per = dict(df.filter(pl.col("symbol").is_in(want)).group_by("symbol").len().iter_rows())
    counts = [min(per.get(s, 0), slots) for s in want]
    have = {(t - d0) // SLOT_US for t in df["slot_us"].to_list()}
    empty = [s for s in range(slots) if s not in have]
    longest, run, prev = 0, 0, None
    for s in empty:
        run = run + 1 if prev is not None and s == prev + 1 else 1
        longest, prev = max(longest, run), s
    total = len(want) * slots
    return {"venue": venue, "day": day, "slots": slots, "expected": len(want), "seen": sum(1 for c in counts if c),
            "extra": df.filter(~pl.col("symbol").is_in(want))["symbol"].n_unique(),
            "snapshots": df.height, "per_symbol_min": min(counts) if counts else 0,
            "per_symbol_median": sorted(counts)[len(counts) // 2] if counts else 0,
            "coverage": sum(counts) / total if total else None, "missing": total - sum(counts),
            "empty_slots": len(empty), "longest_gap_min": longest * 5,
            "rebalance": int(df["rebalance"].sum()) if df.height else 0,
            "never_seen": [s for s, c in zip(want, counts) if not c][:20]}


def coverage_red(st: dict, venue: str, now: int) -> str | None:
    """The red line of the last finished UTC day, None when green or not judged yet (no full day of recording)."""
    first = (st.get("first_day") or {}).get(venue)
    yday = day_str(now - pit.DAY_US)
    if first is None or yday <= first:
        return None
    exp = ((st.get("days") or {}).get(yday) or {}).get(venue)
    if not exp:
        return f"{yday}: no universe stored"
    c = coverage(venue, yday, exp)
    if c["coverage"] is not None and c["coverage"] >= COVERAGE_MIN:
        return None
    return (f"{yday} {100 * (c['coverage'] or 0):.1f} % of {c['expected']} symbols x {SLOTS_DAY} snapshots "
            f"(under {100 * COVERAGE_MIN:.0f} %), {c['expected'] - c['seen']} never seen, {c['empty_slots']} empty "
            f"slots, longest gap {c['longest_gap_min']} min")


def gaps_7d(venue: str, now: int) -> int:
    """5-minute slots with no snapshot of the venue in the last 7 days, from its first stored slot (pit's rule)."""
    ts = []
    for k in range(8):
        df = read_slots(venue, day_str(now - k * pit.DAY_US))
        if df is not None:
            ts += df["slot_us"].unique().to_list()
    return pit.gaps(ts, SLOT_US, now)


# ---------------------------------------------------------------- state, health, report

def state_path() -> Path:
    return root() / "state.json"


def load_state() -> dict:
    try:
        return json.loads(state_path().read_text())
    except (OSError, ValueError):
        return {}


def save_state(st: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def write_health(st: dict, results: dict, errors: dict, notes: dict, now: int) -> dict:
    tables = {}
    for v in VENUES:
        df = read_slots(v, day_str(now))
        last = (st.get("last_us") or {}).get(v)
        tables[v] = {"rows": 0 if df is None else df.height, "last_ts_us": last, "gaps": gaps_7d(v, now),
                     "missing": [], "schema_ok": True}
    doc = {"at": datetime.fromtimestamp(now / 1e6, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "source": "perps_books", "tables": tables, "errors": errors, "runs": results}
    if notes:
        doc["notes"] = notes
    p = root() / "health.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)
    return doc


def render(st: dict, now: int, days: int = 7) -> tuple[str, dict]:
    """The coverage report: per venue and day, symbols seen, snapshots per symbol, gaps, rebalance snapshots,
    429s, the day file's size."""
    rows = []
    for v in VENUES:
        for k in range(days - 1, -1, -1):
            d = day_str(now - k * pit.DAY_US)
            exp = ((st.get("days") or {}).get(d) or {}).get(v)
            if exp is None:
                continue
            c = coverage(v, d, exp, None if k else now, (st.get("first_day") or {}).get(v) == d)
            f = day_file(v, d)
            c["mb"] = f.stat().st_size / 1e6 if f.exists() else 0.0
            c["n429"] = ((st.get("n429") or {}).get(d) or {}).get(v, 0)
            c["full_day"] = bool(k) and (st.get("first_day") or {}).get(v, d) < d
            rows.append(c)
    lines = ["# Perps order books C2: coverage", "",
             f"`results/perps_books_c2_prereg.md`, `lab.collect.perps_books`. As of "
             f"{datetime.fromtimestamp(now / 1e6, timezone.utc):%Y-%m-%d %H:%M} UTC. 20 levels a side every 5 "
             f"minutes ({SLOTS_DAY} a day) of each book's universe (Kraken Futures: m4_perps, Hyperliquid: "
             f"m4_hl_small). Red under {100 * COVERAGE_MIN:.0f} % on a full day. Data only, nothing reads it yet.", "",
             "| venue | day | symbols seen / expected | snapshots per symbol (min / median) | coverage | missing "
             "snapshots | empty slots | longest gap | rebalance | 429s | MB |",
             "|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for c in rows:
        cov = "-" if c["coverage"] is None else f"{100 * c['coverage']:.1f} %"
        mark = "" if not c["full_day"] or c["coverage"] is None or c["coverage"] >= COVERAGE_MIN else " **red**"
        day = c["day"] + ("" if c["full_day"] else f" (to {datetime.fromtimestamp(now / 1e6, timezone.utc):%H:%M})"
                          if c["day"] == day_str(now) else f" (first day, {c['slots']} slots)")
        lines.append(f"| {NAMES[c['venue']]} | {day} | {c['seen']} / {c['expected']} | {c['per_symbol_min']} / "
                     f"{c['per_symbol_median']} | {cov}{mark} | {c['missing']} | {c['empty_slots']} | "
                     f"{c['longest_gap_min']} min | {c['rebalance']} | {c['n429']} | {c['mb']:.2f} |")
    if not rows:
        lines.append("| - | no run yet | | | | | | | | | |")
    u = st.get("universe") or {}
    lines += ["", f"Universe of {u.get('day', '-')} (panel day {u.get('panel_day', '-')}): "
              + ", ".join(f"{NAMES[v]} {len(u.get(v) or [])} symbols ({sum(1 for x in u.get(v) or [] if x['held'])}"
                          " held)" for v in VENUES) + "."]
    full = [c for c in rows if c["full_day"]]
    mb = sum(c["mb"] for c in full) / max(1, len({c["day"] for c in full}))
    if full:
        lines.append(f"Storage: {mb:.1f} MB a full day over both venues (budget {BUDGET_MB} MB).")
    return "\n".join(lines) + "\n", {"at_us": now, "rows": rows, "universe_day": u.get("day"),
                                     "mb_per_full_day": mb if full else None}


def write_report(st: dict, now: int) -> str:
    md, data = render(st, now)
    report.write("perps_books", md, data)
    return md


# ---------------------------------------------------------------- one run

def run(fetch: Fetch | None = None, sleep=time.sleep, clock=time.time, now_us: Callable[[], int] | None = None,
        binance: Fetch | None = None) -> dict:
    fetch = fetch or request
    now_us = now_us or (lambda: int(clock() * 1e6))
    t0, now = clock(), now_us()
    today = day_str(now)
    st = load_state()
    vs = {v: Venue(v, fetch, sleep, clock) for v in VENUES}
    errors, notes, results = {}, {}, {}

    u = st.get("universe") or {}
    if u.get("day") != today:
        try:
            u = dict(build_universe(vs, binance or fetch), day=today)
            st["universe"] = u
        except Exception as e:  # noqa: BLE001 - the last universe stands in
            msg = f"{type(e).__name__}: {e}"[:200]
            if u:
                notes["universe"] = f"kept {u.get('day')} ({msg})"
            else:
                errors["universe"] = msg
    if u:
        days = st.setdefault("days", {})
        days.setdefault(today, {v: [x["symbol"] for x in u.get(v) or []] for v in VENUES})
        for d in sorted(days)[:-KEEP_DAYS]:
            days.pop(d)

    # at a book's rebalance minute its venue goes first
    order = sorted(VENUES, key=lambda v: 0 if abs(now - rebalance_us(v, now)) <= REBALANCE_WINDOW_US else 1)
    for v in order:
        uni = u.get(v) or []
        if not uni:
            continue
        rows, res = take(vs[v], uni, t0, now_us)
        store(v, rows)
        results[v] = res
        if rows:
            st.setdefault("first_day", {}).setdefault(v, day_str(rows[0]["collected_us"]))
            st.setdefault("last_us", {})[v] = max(r["collected_us"] for r in rows)
        if res["n429"]:
            n = st.setdefault("n429", {}).setdefault(today, {})
            n[v] = n.get(v, 0) + res["n429"]
            notes[f"{v} 429"] = f"{res['n429']} HTTP 429 from {NAMES[v]} this run"
        if res["failed"] > LOST_MAX * res["asked"]:
            errors[v] = (f"{res['failed']} of {res['asked']} symbols not taken this run ({res['error']})"
                         + ("" if "429" in (res["error"] or "") or not res["n429"]
                            else f"; {res['n429']} HTTP 429, {NAMES[v]}'s rate limit"))
        elif res["failed"]:
            notes[v] = f"{res['failed']} of {res['asked']} symbols not taken ({res['error']})"
    for d in sorted(st.get("n429") or {})[:-KEEP_DAYS]:
        st["n429"].pop(d)
    for v in VENUES:
        red = coverage_red(st, v, now)
        if red:
            errors[f"coverage {v}"] = red
    yday = day_str(now - pit.DAY_US)
    mb = sum(day_file(v, yday).stat().st_size for v in VENUES if day_file(v, yday).exists()) / 1e6
    if mb > BUDGET_MB:
        errors["storage"] = f"{yday} {mb:.0f} MB over both venues (budget {BUDGET_MB} MB a day)"
    save_state(st)
    doc = write_health(st, results, errors, notes, now)
    for v, r in results.items():
        print(f"{v}: {r['taken']} of {r['asked']} taken, {r['n429']} 429" + (f", {r['error']}" if r["error"] else ""),
              flush=True)
    for k, e in errors.items():
        print(f"  {k}: {e}", flush=True)
    # the report once an hour (the run in the hour's first slot) and on the day's first run
    if now % pit.HOUR_US < SLOT_US or not (st.get("reported") == today):
        write_report(st, now)
        st["reported"] = today
        save_state(st)
    doc["exit"] = 1 if not u or (results and not any(r["taken"] for r in results.values())) else 0
    return doc


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["report"]:
        write_report(load_state(), int(time.time() * 1e6))
        return 0
    print(f"perps_books -> {root()}", flush=True)
    return run()["exit"]


if __name__ == "__main__":
    sys.exit(main())
