"""T10: the xStocks tokens the small books use, recorded twice a day, point in time (lab.collect.pit). Data only.

Pre-registered in results/xstocks_t10_prereg.md. The tokens: S2's picks of family xstocks
(results/smallaccount_s2_snapshot.json; today SPYx on SPY, PAXG is Paxos's). xStocks' keyless public API
(https://api.xstocks.fi/api/v2/public, described at docs.xstocks.fi/apis/openapi; its limit is 1,000 requests a
minute, we send at most two a second, about 7 a token a run):

  assets/{s}/price-data           the issuer's indicative price of one token in USD (the API names the token's Pyth
                                  and Chainlink feeds but serves no oracle value without a key; this is the
                                  oracle-side price there is)
  assets/{s}/multiplier           shares of the underlying one token stands for (dividends raise it, splits scale it),
                                  the next one, when it activates and why (network Solana)
  system/status/{s}               trading halted or not
  proof-of-reserves/{s}           shares held by the custodians, circulating supply, the source's timestamp
  oracles/{s}?network=Solana      the feeds (provider, feed id)
  corporate-actions/history and /upcoming?symbol={s}, paged

Tables under $PYTHIA_FREE/xstocks (with ts_us, collected_us, known_us, backfilled):
  quotes    ts_us the run's hour, symbol, underlying, quote_usd, multiplier, multiplier_next, multiplier_next_us,
            multiplier_reason, halted
  reserves  ts_us the run's hour, symbol, por_us (the source's time), shares_held, supply, holdings (JSON)
  oracles   ts_us the hour first seen, symbol, provider, feed_id, feed_type, created_us
  actions   ts_us the record's creation, symbol, event_id, version, status, ca_type, effective_us, multiplier_old,
            multiplier_new, gross_usd, net_usd, wht_rate, from_units, to_units, redemption_usd, notes; known at the
            run that saw it, or at its creation plus an hour when first seen more than 30 hours later (backfilled)

A missing field is an empty value (a quote without a price is no row and an error of that token); an error page or
an {"error"} answer fails that part only. The health file covers quotes and reserves (the feed row `xstocks`);
oracles and actions change rarely and are not aged.

After the record, the premium (`premium`, `report`): each quote against its underlying's last close known at its time
(<data>/etf/daily, the close of day d known from d 21:00 UTC), in bps. SPYx is a token-2022 token with a scaled UI
amount: a wallet shows raw units x multiplier, and the quote (like Jupiter's price) is per shown unit, one share. So
to NAV = quote / close - 1, and a raw unit = quote x multiplier / close - 1, the price of one unscaled unit, which
is what R10's CoinGecko deviations and S2's premiums most likely measured (their means track the multiplier). The
pre-registration had the multiplier the other way round (results/xstocks_t10.md). Both next to R10's 00:00 UTC
deviations and S2's premiums at the US close (both cleaned with s2.clean), and the reserve cover shares held /
(supply x multiplier). One trial in R5's
registry (small:t10:xstocks_premium, counted only). Report: <data>/reports/xstocks/latest.{md,json}.

    python -m lab.collect.xstocks [--dry-run] [--symbols SPYx,QQQx]

Job `xstocks-collect`, 00:00 UTC (the small books' decision time) and 12:00 UTC.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import quote as urlq

import numpy as np
import polars as pl

from . import pit

SOURCE = "xstocks"
API = "https://api.xstocks.fi/api/v2/public"
NETWORK = "Solana"
PAGE = 100
MAX_PAGES = 20
LIVE_LAG_US = 30 * pit.HOUR_US
PUBLISH_US = pit.HOUR_US
CLOSE_KNOWN_US = 21 * pit.HOUR_US        # a US close of day d is known from d 21:00 UTC (16:00 New York in winter)
STEP_US = 12 * pit.HOUR_US               # two runs a day
SNAPSHOT_JSON = Path(__file__).resolve().parents[2] / "results" / "smallaccount_s2_snapshot.json"
DEFAULT = {"SPYx": ("SPY", "SPY")}       # symbol: (S2's key, underlying), when the snapshot cannot be read
TRIAL = {"id": "small:t10:xstocks_premium", "family": "small", "n": 1, "sharpe": None, "var": None,
         "source": "results/xstocks_t10_prereg.md (the premium of the small books' xStocks to their underlying)"}

QUOTE_COLS = ["symbol", "underlying", "quote_usd", "multiplier", "multiplier_next", "multiplier_next_us",
              "multiplier_reason", "halted"]
QUOTE_SCHEMA = {"ts_us": pl.Int64, "symbol": pl.Utf8, "underlying": pl.Utf8, "quote_usd": pl.Float64,
                "multiplier": pl.Float64, "multiplier_next": pl.Float64, "multiplier_next_us": pl.Int64,
                "multiplier_reason": pl.Utf8, "halted": pl.Boolean}
RES_COLS = ["symbol", "por_us", "shares_held", "supply", "holdings"]
RES_SCHEMA = {"ts_us": pl.Int64, "symbol": pl.Utf8, "por_us": pl.Int64, "shares_held": pl.Float64,
              "supply": pl.Float64, "holdings": pl.Utf8}
ORACLE_COLS = ["symbol", "provider", "feed_id", "feed_type", "created_us"]
ORACLE_SCHEMA = {"ts_us": pl.Int64, "symbol": pl.Utf8, "provider": pl.Utf8, "feed_id": pl.Utf8, "feed_type": pl.Utf8,
                 "created_us": pl.Int64}
ACTION_COLS = ["symbol", "event_id", "version", "status", "ca_type", "effective_us", "multiplier_old",
               "multiplier_new", "gross_usd", "net_usd", "wht_rate", "from_units", "to_units", "redemption_usd",
               "notes"]
ACTION_SCHEMA = {"ts_us": pl.Int64, "symbol": pl.Utf8, "event_id": pl.Utf8, "version": pl.Int64, "status": pl.Utf8,
                 "ca_type": pl.Utf8, "effective_us": pl.Int64, "multiplier_old": pl.Float64,
                 "multiplier_new": pl.Float64, "gross_usd": pl.Float64, "net_usd": pl.Float64,
                 "wht_rate": pl.Float64, "from_units": pl.Float64, "to_units": pl.Float64,
                 "redemption_usd": pl.Float64, "notes": pl.Utf8}
KEYS = {"quotes": ["ts_us", "symbol"], "reserves": ["ts_us", "symbol"], "oracles": ["symbol", "provider", "feed_id"],
        "actions": ["event_id", "version", "status"]}


def tokens(path: Path = SNAPSHOT_JSON) -> dict[str, tuple[str, str]]:
    """{symbol: (S2's key, underlying)} of the small books' xStocks picks."""
    try:
        picks = json.loads(path.read_text(encoding="utf-8")).get("picks") or {}
    except (OSError, ValueError):
        return dict(DEFAULT)
    out = {p["symbol"]: (k, p.get("underlying") or p.get("root") or k) for k, p in picks.items()
           if p and p.get("family") == "xstocks" and p.get("symbol")}
    return out or dict(DEFAULT)


# ---------------------------------------------------------------------------
# Parsing (each answer checked: a page or an {"error"} raises, a missing field is None)
# ---------------------------------------------------------------------------

def _doc(doc: object, what: str) -> dict:
    if not isinstance(doc, dict):
        raise ValueError(f"xstocks {what}: not a JSON object ({str(doc)[:60]!r})")
    if doc.get("error") is not None:
        raise ValueError(f"xstocks {what}: {str(doc.get('error'))[:80]} {json.dumps(doc.get('details'))[:120]}")
    return doc


def _num(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _epoch_us(x: float) -> int:
    """An epoch number of unstated unit (the API documents none) by its size: seconds, ms or us."""
    return int(x * 1e6) if x < 1e11 else int(x * 1e3) if x < 1e14 else int(x)


def _iso_us(s) -> int | None:
    if not s or not isinstance(s, str):
        return None
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1e6)
    except ValueError:
        return None


def _nodes(doc: object, what: str) -> list[dict]:
    nodes = _doc(doc, what).get("nodes")
    if not isinstance(nodes, list):
        raise ValueError(f"xstocks {what}: no nodes list")
    return [n for n in nodes if isinstance(n, dict)]


def parse_quote(symbol: str, underlying: str, price: object, mult: object, status: object | None) -> dict:
    """One quotes row (without ts_us). No price is an error; a missing multiplier or status is empty."""
    q = _num(_doc(price, f"{symbol} price-data").get("quote"))
    if q is None or q <= 0:
        raise ValueError(f"xstocks {symbol} price-data: no quote")
    m = mult if isinstance(mult, dict) and mult.get("error") is None else {}      # optional: a bad answer is empty
    nxt, at = _num(m.get("newMultiplier")), _num(m.get("activationDateTime"))
    halted = (status or {}).get("isMarketTradingHalted") if isinstance(status, dict) else None
    cur = _num(m.get("currentMultiplier"))
    return {"symbol": symbol, "underlying": underlying, "quote_usd": q,
            "multiplier": cur if cur and cur > 0 else None,
            "multiplier_next": nxt if nxt else None,                        # 0 means none pending
            "multiplier_next_us": _epoch_us(at) if at else None,
            "multiplier_reason": m.get("reason") if isinstance(m.get("reason"), str) else None,
            "halted": halted if isinstance(halted, bool) else None}


def parse_reserves(symbol: str, doc: object) -> dict:
    d = _doc(doc, f"{symbol} proof-of-reserves")
    if d.get("symbol") not in (None, symbol):
        raise ValueError(f"xstocks {symbol} proof-of-reserves: answered for {d.get('symbol')}")
    hold = d.get("holdings") if isinstance(d.get("holdings"), list) else []
    return {"symbol": symbol, "por_us": _iso_us(d.get("timestamp")), "shares_held": _num(d.get("sharesHeld")),
            "supply": _num(d.get("circulatingSupply")),
            "holdings": json.dumps([{k: h.get(k) for k in ("provider", "symbol", "quantity")} for h in hold
                                    if isinstance(h, dict)], separators=(",", ":"))}


def parse_oracles(symbol: str, doc: object) -> list[dict]:
    out = []
    for n in _nodes(doc, f"{symbol} oracles"):
        md = n.get("metadata") if isinstance(n.get("metadata"), dict) else {}
        fid = md.get("hermesId") or md.get("feedId") or md.get("pythLazerId") or n.get("address") or n.get("id")
        if n.get("symbol") not in (None, symbol) or not fid:
            continue
        out.append({"symbol": symbol, "provider": str(n.get("managedBy") or ""), "feed_id": str(fid),
                    "feed_type": str(n.get("feedType") or ""), "created_us": _iso_us(n.get("createdAt"))})
    return out


def parse_actions(symbol: str, doc: object) -> list[dict]:
    """The corporate actions of one page; a node without an event id, version, status or creation time is
    dropped (it cannot be keyed or dated)."""
    out = []
    for n in _nodes(doc, f"{symbol} corporate-actions"):
        ts, ver = _iso_us(n.get("createdTimeUtc")), n.get("version")
        if (n.get("xstockSymbol") not in (None, symbol) or not n.get("eventId") or ts is None
                or not isinstance(ver, int) or not n.get("status")):
            continue
        out.append({"ts_us": ts, "symbol": symbol, "event_id": str(n["eventId"]), "version": ver,
                    "status": str(n["status"]), "ca_type": str(n.get("caType") or ""),
                    "effective_us": _iso_us(n.get("effectiveTimeUtc")),
                    "multiplier_old": _num(n.get("multiplierOld")), "multiplier_new": _num(n.get("multiplierNew")),
                    "gross_usd": _num(n.get("grossCashflowUsd")), "net_usd": _num(n.get("netCashflowUsd")),
                    "wht_rate": _num(n.get("withholdingTaxRate")), "from_units": _num(n.get("fromUnits")),
                    "to_units": _num(n.get("toUnits")), "redemption_usd": _num(n.get("redemptionPriceUsd")),
                    "notes": n.get("notes") if isinstance(n.get("notes"), str) else None})
    return out


def _frame(rows: list[dict], schema: dict, ts: int | None = None) -> pl.DataFrame:
    if ts is not None:
        rows = [{"ts_us": ts, **r} for r in rows]
    return pl.DataFrame(rows, schema=schema, orient="row") if rows else pl.DataFrame(schema=schema)


def stamp_actions(df: pl.DataFrame, now: int) -> pl.DataFrame:
    """Live when first seen within 30 hours of its creation, else backfilled and known an hour after it."""
    late = now - pl.col("ts_us") > LIVE_LAG_US
    return df.with_columns(collected_us=pl.lit(now, pl.Int64),
                           known_us=pl.when(late).then(pl.col("ts_us") + PUBLISH_US).otherwise(pl.lit(now, pl.Int64)),
                           backfilled=late).select(["ts_us"] + ACTION_COLS + pit.PIT[1:])


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

def _pages(fetch: pit.Fetch, url: str, symbol: str) -> list[dict]:
    rows = []
    for page in range(1, MAX_PAGES + 1):
        doc = fetch(f"{url}?symbol={urlq(symbol)}&page={page}&pageSize={PAGE}")
        rows += parse_actions(symbol, doc)
        if not ((doc.get("page") or {}).get("hasNextPage")):
            break
    return rows


def run(dry: bool = False, fetch: pit.Fetch | None = None, now: int | None = None,
        syms: dict[str, tuple[str, str]] | None = None, closes: dict | None = None, register: bool = True) -> dict:
    fetch = fetch or pit.paced(0.5)
    now = now or pit.now_us()
    hour = now - now % pit.HOUR_US
    syms = syms or tokens()
    errors: dict[str, str] = {}

    def each(name: str, fn) -> list[dict]:
        """fn(symbol) per token; a token failing is an error of this part, the others go on."""
        rows, bad = [], []
        for s in sorted(syms):
            try:
                got = fn(s)
                rows += got if isinstance(got, list) else [got]
            except Exception as e:  # one token failing does not stop the others
                bad.append(f"{s}: {type(e).__name__}: {e}")
        if bad and not rows:
            raise RuntimeError("; ".join(bad))
        if bad:
            errors[name] = "; ".join(bad)[:300]
            print(f"  {name}: FAILED {errors[name]}", flush=True)
        return rows

    def opt(url: str):
        try:
            return fetch(url)
        except Exception as e:  # multiplier and status are optional parts of a quote
            print(f"  {url}: {type(e).__name__}: {e}"[:200], flush=True)
            return None

    def quotes() -> None:
        rows = each("quotes", lambda s: parse_quote(
            s, syms[s][1], fetch(f"{API}/assets/{urlq(s)}/price-data"),
            opt(f"{API}/assets/{urlq(s)}/multiplier?network={NETWORK}"), opt(f"{API}/system/status/{urlq(s)}")))
        pit.append(SOURCE, "quotes", pit.stamp(_frame(rows, QUOTE_SCHEMA, hour), now), KEYS["quotes"], dry)

    def reserves() -> None:
        rows = each("reserves", lambda s: parse_reserves(s, fetch(f"{API}/proof-of-reserves/{urlq(s)}")))
        pit.append(SOURCE, "reserves", pit.stamp(_frame(rows, RES_SCHEMA, hour), now), KEYS["reserves"], dry)

    def oracles() -> None:
        rows = each("oracles", lambda s: parse_oracles(s, fetch(f"{API}/oracles/{urlq(s)}?network={NETWORK}")))
        pit.append(SOURCE, "oracles", pit.stamp(_frame(rows, ORACLE_SCHEMA, hour), now), KEYS["oracles"], dry)

    def actions() -> None:
        rows = each("actions", lambda s: _pages(fetch, f"{API}/corporate-actions/history", s)
                    + _pages(fetch, f"{API}/corporate-actions/upcoming", s))
        pit.append(SOURCE, "actions", stamp_actions(_frame(rows, ACTION_SCHEMA), now), KEYS["actions"], dry)

    for name, fn in (("quotes", quotes), ("reserves", reserves), ("oracles", oracles), ("actions", actions)):
        pit.step(errors, name, fn)
    tables = {t: pit.table_health(SOURCE, t, c, STEP_US, now, by="symbol")
              for t, c in (("quotes", QUOTE_COLS), ("reserves", RES_COLS))}
    doc = pit.write_health(SOURCE, tables, errors, dry)
    if not dry:
        try:
            report(syms, now, closes=closes, register_trial=register)
        except Exception as e:  # the record stands without its report; the report fails loudly in the log
            print(f"  premium report: FAILED {type(e).__name__}: {e}", flush=True)
    return doc


# ---------------------------------------------------------------------------
# The premium, next to R10's series
# ---------------------------------------------------------------------------

def load_closes(underlyings) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """{underlying: (dates, closes)} from <data>/etf/daily; a symbol without a file is left out."""
    from ..experiments import etf_trend as et
    out = {}
    for u in sorted(set(underlyings)):
        f = et.CACHE / f"{u}.csv"
        if f.exists():
            out[u] = et.parse_stooq(f.read_text(encoding="utf-8"))
    return out


def premium(quotes: pl.DataFrame, closes: dict[str, tuple[np.ndarray, np.ndarray]]) -> list[dict]:
    """Each quote (per shown unit, one share) against its underlying's last close known at its time: the premium
    to NAV and the raw unit's (quote x multiplier) in bps."""
    out = []
    for r in quotes.sort(["symbol", "ts_us"]).iter_rows(named=True):
        dates, cl = closes.get(r["underlying"], (None, None))
        if dates is None or not r["quote_usd"]:
            continue
        cut = np.datetime64(pit.day_of(r["ts_us"] - CLOSE_KNOWN_US))   # the newest close day known at ts_us
        i = int(np.searchsorted(dates.astype("datetime64[D]"), cut, side="right")) - 1
        if i < 0:
            continue
        c, m = float(cl[i]), r["multiplier"]
        out.append({"symbol": r["symbol"], "at": datetime.fromtimestamp(r["ts_us"] / 1e6, pit.UTC)
                    .strftime("%Y-%m-%dT%H:%MZ"), "ts_us": r["ts_us"], "midnight": r["ts_us"] % pit.DAY_US == 0,
                    "close_date": str(dates[i])[:10], "close": c, "quote": r["quote_usd"], "multiplier": m,
                    "nav_bps": round((r["quote_usd"] / c - 1) * 1e4, 3),
                    "unit_bps": round((r["quote_usd"] * m / c - 1) * 1e4, 3) if m else None,
                    "halted": r["halted"]})
    return out


def _stats(x) -> dict:
    x = np.asarray([v for v in x if v is not None], dtype=float)
    return {"n": int(len(x)), "mean_bps": round(float(x.mean()), 2) if len(x) else None,
            "sd_bps": round(float(x.std(ddof=1)), 2) if len(x) > 1 else None}


def r10_series(syms: dict[str, tuple[str, str]]) -> dict[str, dict]:
    """Per symbol: R10's 00:00 UTC deviations and S2's premiums at the US close, their stats cleaned (R10's on US
    days and on days without a US close apart), their values by date as printed."""
    from ..experiments import smallaccount as s1
    from ..experiments import smallaccount_r10 as r10
    from ..experiments import smallaccount_s2 as s2
    tok = s1.read_csv(r10.TOKENS_CSV) if r10.TOKENS_CSV.exists() else []
    pre = s1.read_csv(s2.PREMIUMS_CSV) if s2.PREMIUMS_CSV.exists() else []
    out = {}
    for sym, (key, _) in syms.items():
        rows = [r for r in tok if r["key"] == key]
        us = s2.clean([float(r["dev_bps"]) for r in rows if r["us_day"] == "True"])
        shut = s2.clean([float(r["dev_bps"]) for r in rows if r["us_day"] != "True"])
        p = [r for r in pre if r["symbol"] == sym]
        out[sym] = {"r10_us": _stats(us), "r10_shut": _stats(shut),
                    "s2_close": _stats(s2.clean([float(r["premium_bps"]) for r in p])),
                    "r10_by_date": {r["date"]: float(r["dev_bps"]) for r in rows},       # as printed, uncleaned
                    "s2_by_date": {r["date"]: float(r["premium_bps"]) for r in p},
                    "r10_last": max((r["date"] for r in rows), default=None)}
    return out


def cover(res: pl.DataFrame | None, quotes: pl.DataFrame | None) -> dict[str, dict]:
    """The newest reserve figures per symbol and their cover of supply x multiplier."""
    out = {}
    if res is None or res.is_empty():
        return out
    for (sym,), g in res.sort("ts_us").group_by(["symbol"], maintain_order=True):
        r = g.row(-1, named=True)
        m = None
        if quotes is not None and not quotes.is_empty():
            q = quotes.filter((pl.col("symbol") == sym) & (pl.col("ts_us") <= r["ts_us"])
                              & pl.col("multiplier").is_not_null()).sort("ts_us")
            m = q["multiplier"][-1] if q.height else None
        need = r["supply"] * m if r["supply"] is not None and m else None
        out[sym] = {"at": datetime.fromtimestamp(r["ts_us"] / 1e6, pit.UTC).strftime("%Y-%m-%dT%H:%MZ"),
                    "shares_held": r["shares_held"], "supply": r["supply"], "multiplier": m,
                    "cover": round(r["shares_held"] / need, 5) if need and r["shares_held"] is not None else None}
    return out


def report(syms: dict[str, tuple[str, str]], now: int, closes: dict | None = None, register_trial: bool = True,
           write: bool = True) -> dict:
    from .. import metrics
    from .. import report as rp
    if register_trial:
        try:
            metrics.register([TRIAL])                       # before the first premium exists
        except OSError as e:
            print(f"t10: the registry could not be written ({e}); the trial counts when it can", flush=True)
    q = pit.read(SOURCE, "quotes")
    q = None if q is None else pit.as_of(q, now)
    closes = closes if closes is not None else load_closes(u for _, u in syms.values())
    rows = premium(q, closes) if q is not None else []
    ref = r10_series(syms)
    acts = pit.read(SOURCE, "actions")
    per = {}
    for sym in sorted(syms):
        mine = [r for r in rows if r["symbol"] == sym]
        mid = [r for r in mine if r["midnight"]]
        a = acts.filter(pl.col("symbol") == sym).sort("ts_us") if acts is not None else None
        rf = ref.get(sym, {})
        per[sym] = {"underlying": syms[sym][1], "midnight_nav": _stats(r["nav_bps"] for r in mid),
                    "midnight_unit": _stats(r["unit_bps"] for r in mid), "all_nav": _stats(r["nav_bps"] for r in mine),
                    "all_unit": _stats(r["unit_bps"] for r in mine), "newest": mine[-1] if mine else None,
                    "r10_us": rf.get("r10_us"), "r10_shut": rf.get("r10_shut"), "s2_close": rf.get("s2_close"),
                    "r10_last": rf.get("r10_last"),
                    "actions": 0 if a is None else a.height,
                    "last_action": None if a is None or a.is_empty() else
                    {k: a.row(-1, named=True)[k] for k in ("ca_type", "status", "effective_us", "multiplier_new")},
                    # the side by side: each record's day next to R10's and S2's value of the same close day
                    "side_by_side": [{**{k: r[k] for k in ("at", "close_date", "nav_bps", "unit_bps")},
                                      "r10_dev_bps": rf.get("r10_by_date", {}).get(r["close_date"]) if r["midnight"]
                                      else None,
                                      "s2_premium_bps": rf.get("s2_by_date", {}).get(r["close_date"])}
                                     for r in mine[-30:]]}
    data = {"at": datetime.fromtimestamp(now / 1e6, pit.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "tokens": per,
            "reserves": cover(pit.read(SOURCE, "reserves"), q), "trial": TRIAL["id"]}
    if write:
        rp.write("xstocks", markdown(data), data)
    return data


def _f(x, nd: int = 1) -> str:
    return "" if x is None else f"{x:,.{nd}f}"


def _s(st: dict | None) -> str:
    st = st or {}
    return f"{st.get('n', 0)}: {_f(st.get('mean_bps'))} / {_f(st.get('sd_bps'))}"


def markdown(d: dict) -> str:
    out = [f"# xStocks: the small books' tokens against their underlying (T10, {d['at']})", "",
           "Premium in bps: count: mean / sd. The quote is per shown unit (one share; the token's balance is scaled "
           "by the multiplier): to NAV = quote / last close - 1, a raw unit = quote x multiplier / last close - 1 "
           "(what R10's and S2's series most likely measured); the last close known at the record's time (from "
           "21:00 UTC of its day). R10: its 00:00 UTC deviations from CoinGecko, after a US close and without one; "
           "S2: premiums at the US close; both cleaned of bad prints. A measurement, one trial in R5's registry, "
           "counted only.", "",
           "| token | 00:00 UTC to NAV | 00:00 UTC raw unit | all to NAV | all raw unit | R10 US days | "
           "R10 no US close | S2 at the close | newest |", "|---|---|---|---|---|---|---|---|---|"]
    for sym, t in d["tokens"].items():
        n = t["newest"]
        newest = f"{n['at']}: {_f(n['quote'], 2)} against {_f(n['close'], 2)} ({n['close_date']}), " \
                 f"{_f(n['nav_bps'])} / {_f(n['unit_bps'])}" if n else "no record yet"
        out.append(f"| {sym} on {t['underlying']} | {_s(t['midnight_nav'])} | {_s(t['midnight_unit'])} | "
                   f"{_s(t['all_nav'])} | {_s(t['all_unit'])} | {_s(t['r10_us'])} | {_s(t['r10_shut'])} | "
                   f"{_s(t['s2_close'])} | {newest} |")
    out += ["", "| token | reserves at | shares held | supply | multiplier | cover |", "|---|---|---|---|---|---|"]
    for sym, r in d["reserves"].items():
        out.append(f"| {sym} | {r['at']} | {_f(r['shares_held'], 2)} | {_f(r['supply'], 2)} | "
                   f"{_f(r['multiplier'], 6)} | {_f(r['cover'], 5)} |")
    for sym, t in d["tokens"].items():
        la = t["last_action"]
        out += ["", f"{sym}: {t['actions']} corporate action records" + (
            f", the newest {la['ca_type']} ({la['status']}), multiplier to {_f(la['multiplier_new'], 6)}" if la else "")
            + f". R10's series ends {t['r10_last'] or 'nowhere'}.", "",
            "| record | close day | to NAV | raw unit | R10 00:00 UTC | S2 at the close |", "|---|---|---|---|---|---|"]
        out += [f"| {r['at']} | {r['close_date']} | {_f(r['nav_bps'])} | {_f(r['unit_bps'])} | "
                f"{_f(r['r10_dev_bps'])} | {_f(r['s2_premium_bps'])} |" for r in t["side_by_side"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true", help="fetch and print counts, write nothing")
    ap.add_argument("--symbols", help="comma separated xStocks symbols instead of the small books' (underlying: "
                                      "the symbol without its x)")
    a = ap.parse_args(argv)
    syms = {s: (s[:-1], s[:-1]) for s in a.symbols.split(",")} if a.symbols else None
    print(f"xstocks -> {pit.FREE / SOURCE}", flush=True)
    return pit.exit_code(run(a.dry_run, syms=syms)["errors"], 4)


if __name__ == "__main__":
    sys.exit(main())
