"""S2: a fairly safe 20 to 50 EUR wallet on Solana with the S&P 500 token, BTC, gold and USDC, against the ETF token.

Pre-registered in results/smallaccount_s2_prereg.md; results in results/smallaccount_s2.md.

    python -m lab.experiments.smallaccount_s2 --snapshot   what exists: the tokenized stocks, ETFs and gold on
                                                           Jupiter's verified list, a quote ladder 5 to 100 USD,
                                                           each token against its underlying (GeckoTerminal,
                                                           CoinGecko, Yahoo), the issuers' words, into results/
    python -m lab.experiments.smallaccount_s2              the study on the lab's daily panel and <data>/etf/daily
                                                           (run it under the heavy lock)

S1's wallet (lab.experiments.smallaccount: cash and units in EUR, MIN_TRADE 5
USDC, dust, the SOL reserve) with this snapshot's ladder, the Sender tip on top
of S1's network fee, and the way there as one SOL to USDC swap (the owner holds
SOL). Before the tokens existed they are their underlying's adjusted close times
exp(drift x years): the measured premium drift less 30 % withholding on the
dividends. The same candidates, venue and wallet step the two paper books
(lab.paper.smallaccount). Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import fam_common as fc
from . import smallaccount as s1

NAME = "smallaccount_s2"
RESULTS = s1.RESULTS
TOKENS_CSV = RESULTS / "smallaccount_s2_tokens.csv"
QUOTES_CSV = RESULTS / "smallaccount_s2_quotes.csv"
TRACKING_CSV = RESULTS / "smallaccount_s2_tracking.csv"
PREMIUMS_CSV = RESULTS / "smallaccount_s2_premiums.csv"
SNAPSHOT_JSON = RESULTS / "smallaccount_s2_snapshot.json"
CUT = "2026-10-21"
IS_FROM, OOS_FROM = s1.IS_FROM, s1.OOS_FROM
CAPITALS = (20.0, 40.0, 50.0)
MAIN = 40.0
RUNGS = (5.0, 10.0, 25.0, 50.0, 100.0)
SWAP_FEE_SOL = s1.SWAP_FEE_SOL + 0.0001     # S1's base and priority fee plus the live trader's Sender tip
WHT = 0.30                                  # withholding on the reinvested dividends, assumed (not published)
MIN_LIQ_LIST, MIN_LIQ_PICK = 50_000.0, 100_000.0
SAFE_DD, MATCH_SLACK = 0.20, 0.01
BOOT_DRAWS, BOOT_BLOCK = 2_000, 20
NOISE_SEEDS = 20
VOL_TARGET, VOL_WIN = 0.10, 60
TRIALS = 8
DSR_PASS = 0.95                             # the DSR a convincing candidate reaches over the registry's pool of all
KEYS = ("SPY", "BTC", "GOLD")               # what the rules hold besides USDC; tsmom1 adds the panel's coins
FAMILIES = ("xstocks", "ondo", "backpack", "prestocks", "tessera")
RWA_TAGS = set(FAMILIES) | {"stocks", "rwa", "commodities"}
SP500 = {"SPY", "IVV", "VOO", "SPLG"}
NDX = {"QQQ", "QQQM"}
TOTAL = {"VTI", "VT"}
GOLD_ETF = {"GLD", "IAU", "GLDM"}
GOLD_PHYS = {"XAUt0": "Tether Gold", "PAXG": "Paxos", "XAUM": "Matrixdock", "VNXAU": "VNX"}
ETF_WORDS = re.compile(r"\bETF\b|\bFund\b|\bTrust\b|S&P|SP500|Nasdaq|Vanguard|iShares|SPDR", re.I)
JUP_VERIFIED = "/tokens/v2/tag"
GECKO = "https://api.geckoterminal.com/api/v2/networks/solana"
COINGECKO = "https://api.coingecko.com/api/v3/coins/{}/market_chart?vs_currency=usd&days=365&interval=daily"
YAHOO = "https://query1.finance.yahoo.com/v8/finance/chart/{}?period1={}&period2={}&interval=1d"
HOURLY_DAYS = 180
TRACK_COLS = ["symbol", "underlying", "source", "pool", "days", "first", "last", "premium_mean_bps", "premium_sd_bps",
              "premium_abs_p95_bps", "te_yr_pct", "drift_yr_pct", "corr", "weekend_abs_mean_bps",
              "weekend_abs_max_bps", "weekends", "div_yield_pct"]
ISSUER_PAGES = {"xStocks (Backed Assets)": ["https://docs.xstocks.fi/docs/product-legal-overview", "https://xstocks.fi/"],
                "Ondo Global Markets": ["https://ondo.finance/global-markets"],
                "Paxos (PAXG)": ["https://paxos.com/paxg/"],
                "Tether Gold (XAUt)": ["https://gold.tether.to/"]}
ISSUER_WORDS = re.compile(r"U\.S\. persons?|US persons?|United States|EU/EEA|European Economic Area|\bEEA\b|"
                          r"retail clients|restricted|prohibited|not available", re.I)


# ---------------------------------------------------------------- the snapshot

def root_of(symbol: str, family: str) -> str:
    """The ticker a token stands for: SPYx -> SPY, SPYon -> SPY, a Backpack share is its ticker."""
    if family == "xstocks" and symbol.endswith("x"):
        return symbol[:-1]
    if family == "ondo" and symbol.endswith("on"):
        return symbol[:-2]
    return symbol


def classify(t: dict) -> dict:
    """A token of Jupiter's list as (family, root, kind, underlying). kind: sp500, ndx, total, gold, etf, share,
    pre_ipo, other; underlying is the Yahoo ticker the token is measured against ("" when none)."""
    tags = set(t.get("tags") or [])
    sym, name = str(t.get("symbol") or ""), str(t.get("name") or "")
    family = next((f for f in FAMILIES if f in tags), "other")
    root = root_of(sym, family)
    if sym in GOLD_PHYS:
        return {"family": GOLD_PHYS[sym], "root": sym, "kind": "gold", "underlying": "GLD"}
    if family in ("prestocks", "tessera"):
        return {"family": family, "root": root, "kind": "pre_ipo", "underlying": ""}
    if family == "other":
        return {"family": family, "root": root, "kind": "other", "underlying": ""}
    for kind, roots in (("sp500", SP500), ("ndx", NDX), ("total", TOTAL), ("gold", GOLD_ETF)):
        if root in roots:
            return {"family": family, "root": root, "kind": kind, "underlying": root}
    kind = "etf" if ETF_WORDS.search(name) else "share"
    return {"family": family, "root": root, "kind": kind, "underlying": root}


def token_rows(verified: list[dict]) -> list[dict]:
    """The listed tokenized assets: every RWA token with MIN_LIQ_LIST of liquidity, and every ETF or gold token."""
    out = []
    for t in verified:
        if not set(t.get("tags") or []) & RWA_TAGS:
            continue
        c = classify(t)
        liq = float(t.get("liquidity") or 0.0)
        if liq < MIN_LIQ_LIST and c["kind"] not in ("sp500", "ndx", "total", "gold", "etf"):
            continue
        out.append({"symbol": t.get("symbol"), "name": str(t.get("name") or "")[:60], "mint": t.get("id"),
                    "decimals": int(t.get("decimals") or 0), "program": "token-2022" if "token-2022" in
                    (t.get("tags") or []) or str(t.get("tokenProgram", "")).startswith("Tokenz") else "spl",
                    "liquidity_usd": round(liq), "holders": int(t.get("holderCount") or 0), **c})
    return sorted(out, key=lambda r: -r["liquidity_usd"])


def shortlist(rows: list[dict]) -> list[dict]:
    """The tokens quoted and measured: every S&P 500, Nasdaq 100, total-market and gold token, and the three
    most liquid single shares."""
    keep = [r for r in rows if r["kind"] in ("sp500", "ndx", "total", "gold")]
    keep += [r for r in rows if r["kind"] == "share"][:3]
    return keep


def pick(rows: list[dict], quotes: list[dict], kind: str) -> dict | None:
    """The pre-registered pick of a kind: the lowest half round trip at 50 USD among its tokens with
    MIN_LIQ_PICK of liquidity."""
    at50 = {q["symbol"]: float(q["half_rt_bps"]) for q in quotes if float(q["usd"]) == 50.0}
    c = [r for r in rows if r["kind"] == kind and r["liquidity_usd"] >= MIN_LIQ_PICK and r["symbol"] in at50]
    return min(c, key=lambda r: at50[r["symbol"]]) if c else None


class Paced:
    """GET JSON with a minimum gap per host and a few waits on 429 and 5xx; None when it does not answer."""

    def __init__(self, gaps: dict[str, float] | None = None, sleep=time.sleep, fetch=None):
        self.gaps, self.sleep, self.last = gaps or {}, sleep, {}
        self.fetch = fetch or self._fetch

    @staticmethod
    def _fetch(url: str) -> tuple[int, bytes]:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except OSError:
            return 0, b""

    def get(self, url: str, tries: int = 5) -> dict | list | None:
        host = url.split("/")[2]
        for i in range(tries):
            wait = self.last.get(host, -1e18) + self.gaps.get(host, 1.0) - time.time()
            if wait > 0:
                self.sleep(wait)
            self.last[host] = time.time()
            status, body = self.fetch(url)
            if status == 200:
                try:
                    return json.loads(body)
                except ValueError:
                    return None
            if status not in (0, 429) and status < 500:
                return None
            self.sleep(min(15.0 * 2 ** i, 60.0))
        return None


def quote_rows(client, tokens: dict[str, tuple[str, int]], rungs=RUNGS) -> list[dict]:
    """USDC -> token -> USDC at every rung (S1's measure); a token stops at its first failed rung."""
    from ..onchain import mints as M
    from ..onchain.jupiter import QuoteError
    out = []
    for sym, (mint, _) in tokens.items():
        for usd in rungs:
            try:
                q = client.quote(M.USDC.mint, mint, M.raw(M.USDC, usd))
                back = client.quote(mint, M.USDC.mint, q.out_amount)
            except QuoteError as e:
                print(f"  {sym} {usd:g}: {e}", file=sys.stderr)
                break
            out.append({"symbol": sym, "usd": usd, "half_rt_bps": round((1 - back.out_amount / q.in_amount) / 2 * 1e4, 3),
                        "impact_pct": round(float(q.price_impact_pct) * 100, 4), "route": "+".join(q.labels)})
    return out


def ny_close_utc(day: str) -> datetime:
    """16:00 in New York on that day, in UTC (20:00 in summer time, 21:00 in winter time)."""
    from zoneinfo import ZoneInfo
    d = datetime.strptime(day, "%Y-%m-%d")
    return d.replace(hour=16, tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)


def yahoo_rows(payload: dict) -> list[tuple[str, float, float]]:
    """Yahoo's chart answer as (day, close, adjusted close)."""
    r = payload["chart"]["result"][0]
    q, a = r["indicators"]["quote"][0]["close"], r["indicators"]["adjclose"][0]["adjclose"]
    out = []
    for ts, c, ac in zip(r["timestamp"], q, a):
        if c and ac and c > 0 and ac > 0:
            out.append((datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d"), float(c), float(ac)))
    return out


def dividend_yield(rows: list[tuple[str, float, float]], start: str = IS_FROM) -> float:
    """The yearly dividend yield over the window from adjusted against unadjusted closes."""
    r = [x for x in rows if x[0] >= start]
    if len(r) < 2:
        return 0.0
    years = (datetime.strptime(r[-1][0], "%Y-%m-%d") - datetime.strptime(r[0][0], "%Y-%m-%d")).days / 365.25
    g = math.log((r[-1][2] / r[-1][1]) / (r[0][2] / r[0][1]))
    return max(g / years, 0.0) if years > 0 else 0.0


def at_close(candles: list[list], days: list[str]) -> dict[str, float]:
    """The close of the hourly candle that ends at each day's US close (candles: [start s, o, h, l, c, v])."""
    by = {int(c[0]): float(c[4]) for c in candles}
    out = {}
    for d in days:
        s = int((ny_close_utc(d) - timedelta(hours=1)).timestamp())
        if s in by and by[s] > 0:
            out[d] = by[s]
    return out


def tracking_stats(token: dict[str, float], under: dict[str, float]) -> dict:
    """The token's price against its underlying's close on the days both have: premium, tracking error, drift,
    correlation."""
    days = sorted(set(token) & set(under))
    if len(days) < 20:
        return {"days": len(days)}
    tk = np.array([token[d] for d in days])
    un = np.array([under[d] for d in days])
    prem = tk / un - 1
    rt, ru = tk[1:] / tk[:-1] - 1, un[1:] / un[:-1] - 1
    t = np.array([(datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(days[0], "%Y-%m-%d")).days / 365.25
                  for d in days])
    slope = float(np.polyfit(t, np.log(tk / un), 1)[0]) if t[-1] > 0 else 0.0
    return {"days": len(days), "first": days[0], "last": days[-1], "premium_mean_bps": float(prem.mean() * 1e4),
            "premium_sd_bps": float(prem.std() * 1e4), "premium_abs_p95_bps": float(np.quantile(np.abs(prem), 0.95) * 1e4),
            "te_yr_pct": float((rt - ru).std() * math.sqrt(252) * 100), "drift_yr_pct": slope * 100,
            "corr": float(np.corrcoef(rt, ru)[0, 1]) if rt.std() > 0 and ru.std() > 0 else 0.0}


def per_unit(token: dict[str, float], under: dict[str, float]) -> dict[str, float]:
    """A token that is another unit of the asset (an ounce of gold against a GLD share) on the underlying's scale:
    divided by the median ratio of the days both have, so its premium is measured around that ratio."""
    r = [token[d] / under[d] for d in set(token) & set(under)]
    k = float(np.median(r)) if r else 1.0
    return {d: p / k for d, p in token.items()}


def weekend_moves(candles: list[list], days: list[str]) -> list[float]:
    """The token's move from a Friday's US close to the same hour on Sunday, while the underlying is shut."""
    by = {int(c[0]): float(c[4]) for c in candles}
    out = []
    for d in days:
        if datetime.strptime(d, "%Y-%m-%d").weekday() != 4:
            continue
        s = int((ny_close_utc(d) - timedelta(hours=1)).timestamp())
        if s in by and s + 2 * 86_400 in by and by[s] > 0:
            out.append(by[s + 2 * 86_400] / by[s] - 1)
    return out


def gecko_hourly(get, mint: str, now_s: int, days: int = HOURLY_DAYS) -> tuple[list[list], str, str]:
    """The hourly candles in USD of the token's deepest USDC or SOL pool on GeckoTerminal, as far back as the
    keyless API goes; (candles, pool, coingecko id)."""
    from ..onchain import mints as M
    d = get(f"{GECKO}/tokens/{mint}/pools?page=1") or {}
    pools = []
    for p in d.get("data") or []:
        a, rel = p.get("attributes") or {}, p.get("relationships") or {}
        base = ((rel.get("base_token") or {}).get("data") or {}).get("id", "")
        quote = ((rel.get("quote_token") or {}).get("data") or {}).get("id", "")
        other = quote if base.endswith(mint) else base
        if not other.endswith((M.USDC.mint, M.SOL.mint)):
            continue
        pools.append((float(a.get("reserve_in_usd") or 0), a.get("address"), "base" if base.endswith(mint) else "quote"))
    if not pools:
        return [], "", ""
    _, addr, side = max(pools)
    out, before, cg = [], now_s, ""
    for _ in range(days * 24 // 1000 + 2):
        if before <= now_s - days * 86_400:
            break
        r = get(f"{GECKO}/pools/{addr}/ohlcv/hour?aggregate=1&limit=1000&currency=usd&token={side}"
                f"&before_timestamp={before}")
        if not r:
            break
        lst = ((r.get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        meta = (r.get("meta") or {}).get(side) or {}
        cg = cg or meta.get("coingecko_coin_id") or ""
        if not lst:
            break
        out += lst
        if min(int(c[0]) for c in lst) >= before:
            break                                   # the API answered the same page again
        before = min(int(c[0]) for c in lst)
    return sorted({int(c[0]): c for c in out}.values()), addr, cg


def issuer_words(get_text) -> dict[str, list[str]]:
    """What each issuer's public page says about who may hold the tokens (sentences naming the US, the EEA,
    restrictions); an empty list when the page did not answer."""
    out = {}
    for issuer, urls in ISSUER_PAGES.items():
        said: list[str] = []
        for u in urls:
            text = get_text(u) or ""
            text = " ".join(re.sub(r"<[^>]+>", " ", re.sub(r"(?s)<(script|style).*?</\1>", " ", text)).split())
            for s in re.split(r"(?<=[a-z0-9)][.!?])\s+", text):
                if ISSUER_WORDS.search(s) and len(s) < 400 and s not in said and len(said) < 4:
                    said.append(s.strip())
        out[issuer] = said
    return out


def _get_text(url: str) -> str | None:
    import html
    status, body = Paced._fetch(url)
    return html.unescape(body.decode("utf-8", "replace")) if status == 200 else None


def snapshot(tracking_only: bool = False) -> None:
    """Tokens, quotes, tracking, issuers. `tracking_only` keeps the recorded tokens and quotes (Jupiter's keyless
    limit makes the ladder slow) and measures the rest."""
    from ..onchain import mints as M
    from ..onchain.jupiter import Jupiter
    now = datetime.now(timezone.utc)
    if tracking_only:
        rows = [{**r, "liquidity_usd": float(r["liquidity_usd"]), "decimals": int(r["decimals"])}
                for r in s1.read_csv(TOKENS_CSV)]
        quotes = s1.read_csv(QUOTES_CSV)
        short = shortlist(rows)
    else:
        jup = Jupiter()
        rows = token_rows(Jupiter(timeout=90.0).get(JUP_VERIFIED, {"query": "verified"}))
        s1.write_csv(TOKENS_CSV, rows)
        print(f"{len(rows)} tokenized assets -> {TOKENS_CSV.name}")
        short = shortlist(rows)
        tokens = {r["symbol"]: (r["mint"], r["decimals"]) for r in short}
        tokens.update({c: (M.COINS[c].mint, M.COINS[c].decimals) for c in ("BTC", "ETH", "SOL")})
        quotes = quote_rows(jup, tokens)
        s1.write_csv(QUOTES_CSV, quotes)
        print(f"{len(quotes)} quotes -> {QUOTES_CSV.name}")
    get = Paced({"api.geckoterminal.com": 7.0, "api.coingecko.com": 8.0, "query1.finance.yahoo.com": 1.0}).get
    t0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
    under: dict[str, list] = {}
    for u in sorted({r["underlying"] for r in short if r["underlying"]} | {"SPY", "GLD"}):
        y = get(YAHOO.format(u, t0, int(now.timestamp())))
        try:
            under[u] = yahoo_rows(y)
        except (KeyError, IndexError, TypeError):
            print(f"  no Yahoo history for {u}", file=sys.stderr)
    # Resumable: a token already measured (tracking_only, same day) is kept, every token is written when done.
    track = [r for r in s1.read_csv(TRACKING_CSV)] if tracking_only and TRACKING_CSV.exists() else []
    prem_rows = [r for r in s1.read_csv(PREMIUMS_CSV)] if tracking_only and PREMIUMS_CSV.exists() else []
    done = {r["symbol"] for r in track}
    for r in short:
        u = r["underlying"]
        if u not in under or r["symbol"] in done:
            continue
        closes = {d: c for d, c, _ in under[u]}
        days = sorted(closes)
        candles, pool, cg = gecko_hourly(get, r["mint"], int(now.timestamp()))
        hourly = at_close(candles, days)
        scale = per_unit if r["symbol"] in GOLD_PHYS else (lambda t, u: t)
        hourly = scale(hourly, closes)
        h = tracking_stats(hourly, closes)
        wk = weekend_moves(candles, days)
        track.append({"symbol": r["symbol"], "underlying": u, "source": "hourly at the US close", "pool": pool,
                      **h, "weekend_abs_mean_bps": float(np.mean(np.abs(wk)) * 1e4) if wk else None,
                      "weekend_abs_max_bps": float(np.max(np.abs(wk)) * 1e4) if wk else None, "weekends": len(wk),
                      "div_yield_pct": dividend_yield(under[u]) * 100})
        for d in sorted(set(hourly) & set(closes)):
            prem_rows.append({"symbol": r["symbol"], "date": d, "premium_bps": round((hourly[d] / closes[d] - 1) * 1e4, 3)})
        if cg:
            c = get(COINGECKO.format(cg)) or {}
            daily = {}
            for ms, p in c.get("prices") or []:
                d = (datetime.fromtimestamp(ms / 1000, timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
                daily[d] = float(p)                 # 00:00 UTC stands for the previous US day's close
            track.append({"symbol": r["symbol"], "underlying": u, "source": "daily 00:00 UTC", "pool": cg,
                          **tracking_stats(scale(daily, closes), closes), "div_yield_pct": dividend_yield(under[u]) * 100})
        s1.write_csv(TRACKING_CSV, [{c: (round(v, 4) if isinstance(v, float) else v) for c, v in
                                     ((c, t.get(c)) for c in TRACK_COLS)} for t in track])
        if prem_rows:
            s1.write_csv(PREMIUMS_CSV, prem_rows)
        print(f"  tracked {r['symbol']} against {u}", flush=True)
    picks = {k: pick(rows, quotes, kind) for k, kind in (("SPY", "sp500"), ("GOLD", "gold"))}
    SNAPSHOT_JSON.write_text(json.dumps({"taken": now.isoformat(timespec="seconds"), "picks": picks,
                                         "issuers": issuer_words(_get_text)}, indent=1), encoding="utf-8")
    print(f"picks: {json.dumps({k: (v or {}).get('symbol') for k, v in picks.items()})}")


# ---------------------------------------------------------------- the venue

@dataclass
class S2Venue(s1.Venue):
    """S1's Jupiter venue with the Sender tip in the network fee and the way there as one SOL to USDC swap."""

    def cost(self, coin: str, eur: float, sol_eur: float) -> float:
        return eur * max(self.half_rt_bps(coin, eur * self.eurusd), 0.0) / 1e4 + SWAP_FEE_SOL * sol_eur

    def setup(self, capital: float, slots: int, sol_eur: float) -> tuple[float, float]:
        reserve = (s1.SOL_FEE_RESERVE + s1.RENT_SOL * (slots + 1)) * sol_eur
        return reserve, self.cost("SOL", max(capital - reserve, 0.0), sol_eur)


def load_snapshot(path: Path = SNAPSHOT_JSON) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def venue(quotes_csv: Path = QUOTES_CSV, snap: dict | None = None, kraken_csv: Path = s1.KRAKEN_CSV) -> S2Venue:
    """The ladder under the rules' keys: SPY and GOLD for the picked tokens, BTC, ETH and SOL as they are."""
    snap = snap or load_snapshot()
    alias = {(p or {}).get("symbol"): k for k, p in snap["picks"].items() if p}
    lad: dict[str, list] = {}
    for r in s1.read_csv(quotes_csv):
        k = alias.get(r["symbol"], r["symbol"])
        lad.setdefault(k, []).append((float(r["usd"]), float(r["half_rt_bps"])))
    fx = next(r for r in s1.read_csv(kraken_csv) if r["coin"] == "EURUSD")
    return S2Venue("jupiter", (float(fx["bid"]) + float(fx["ask"])) / 2, ladder={k: sorted(v) for k, v in lad.items()})


# ---------------------------------------------------------------- prices on the panel's calendar

def tracking(path: Path = TRACKING_CSV) -> dict[str, dict]:
    """Per token symbol: its measured row, the longest window first (daily before hourly)."""
    out: dict[str, dict] = {}
    for r in sorted(s1.read_csv(path), key=lambda r: r["source"] != "daily 00:00 UTC"):
        if r.get("drift_yr_pct") not in (None, ""):
            out.setdefault(r["symbol"], r)
    return out


def drift(row: dict | None, kind: str) -> float:
    """A token's yearly log drift against its underlying's adjusted close: the measured premium drift, less the
    withholding on dividends (none on gold)."""
    if not row:
        return 0.0
    d = float(row["drift_yr_pct"]) / 100
    return d - (0.0 if kind == "GOLD" else WHT * float(row.get("div_yield_pct") or 0) / 100)


def etf_on_days(days_us: np.ndarray, dates: np.ndarray, closes: np.ndarray) -> np.ndarray:
    """An ETF's close on each panel day: the last close on or before it, NaN before the first."""
    d = (days_us // fc.DAY_US).astype("datetime64[D]")
    i = np.searchsorted(dates, d, side="right") - 1
    return np.where(i >= 0, closes[np.maximum(i, 0)], np.nan)


def sma_on_trading_days(dates: np.ndarray, closes: np.ndarray, n: int = 200) -> np.ndarray:
    c = np.cumsum(np.r_[0.0, closes])
    out = np.full(len(closes), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


@dataclass
class Market:
    """The rules' inputs on the panel's days: EUR prices of SPY, GOLD, BTC (the tokens as modelled), SPY's and
    BTC's 200-day trend, SOL in EUR for the fees."""
    days: np.ndarray
    px: dict[str, np.ndarray]
    spy_up: np.ndarray
    btc_up: np.ndarray
    sol_eur: np.ndarray
    us_day: np.ndarray          # a US close happened that day (the ETF rows move)


def market(P: fc.Panel, etf: dict[str, tuple[np.ndarray, np.ndarray]], eurusd: float, drifts: dict[str, float],
           noise: dict[str, np.ndarray] | None = None, seed: int | None = None) -> Market:
    years = (P.days - P.days[0]) / (365.25 * fc.DAY_US)
    px: dict[str, np.ndarray] = {}
    for k, sym in (("SPY", "SPY"), ("GOLD", "GLD")):
        dates, closes = etf[sym]
        p = etf_on_days(P.days, dates, closes) * np.exp(drifts.get(k, 0.0) * years)
        if noise is not None and seed is not None and len(noise.get(k, [])):
            rng = np.random.default_rng([seed, len(k)])
            p = p * (1 + rng.choice(noise[k], P.T) / 1e4)
        px[k] = p / eurusd
    px["BTC"] = P.px[:, P.btc] / eurusd
    dates, closes = etf["SPY"]
    up = closes > sma_on_trading_days(dates, closes)
    spy_up = etf_on_days(P.days, dates, up.astype(float)) > 0.5
    us = np.isin((P.days // fc.DAY_US).astype("datetime64[D]"), dates)
    sol = P.px[:, P.col("SOLUSDT")] / eurusd if "SOLUSDT" in P.names else np.full(P.T, 100.0)
    return Market(P.days, px, spy_up, P.btc_on.copy(), np.nan_to_num(sol, nan=0.0), us)


# ---------------------------------------------------------------- the candidates

CANDIDATES = {
    "spy_hold": "the S&P 500 token bought once and held (the benchmark)",
    "btc_hold": "BTC bought once and held (reference)",
    "spy_trend": "the S&P 500 token above SPY's 200-day average, USDC below",
    "dual_mom": "the best of S&P 500 token, BTC and gold by 365-day return if above 0, else USDC",
    "mix_6040": "60 % S&P 500 token, 40 % BTC, back to 60/40 monthly",
    "trend_mix": "60 % S&P 500 token above its 200-day average, 40 % BTC above its own, USDC otherwise",
    "tsmom1": "S1's best: 28d momentum on the most liquid coin, regime, 40 % vol",
    "vol_target": "S&P 500 token, BTC and gold by inverse vol, 10 % portfolio vol, the rest USDC",
}
CADENCE = {"spy_hold": "once", "btc_hold": "once", "spy_trend": "daily", "dual_mom": "weekly", "mix_6040": "monthly",
           "trend_mix": "daily", "tsmom1": "daily", "vol_target": "weekly"}
SLOTS = {"spy_hold": 1, "btc_hold": 1, "spy_trend": 1, "dual_mom": 3, "mix_6040": 2, "trend_mix": 2, "tsmom1": 1,
         "vol_target": 3}
REFERENCES = ("spy_hold", "btc_hold")


def month_start(days_us: np.ndarray) -> np.ndarray:
    d = (days_us // fc.DAY_US).astype("datetime64[D]")
    return d == d.astype("datetime64[M]").astype("datetime64[D]")


def _ret_back(p: np.ndarray, n: int) -> np.ndarray:
    out = np.full(len(p), np.nan)
    out[n:] = p[n:] / p[:-n] - 1
    return out


def vol_weights(m: Market, t: int) -> dict[str, float]:
    """Inverse-vol weights of SPY, BTC and GOLD from the last VOL_WIN US closes, scaled to VOL_TARGET with their
    correlations over the same days, at most 100 % in all."""
    idx = np.flatnonzero(m.us_day[: t + 1])[-(VOL_WIN + 1):]
    if len(idx) < VOL_WIN + 1:
        return {k: 0.0 for k in KEYS}
    R = np.column_stack([np.diff(np.log(m.px[k][idx])) for k in KEYS])
    if not np.isfinite(R).all():
        return {k: 0.0 for k in KEYS}
    cov = np.cov(R, rowvar=False) * 252
    sd = np.sqrt(np.diag(cov))
    if not (sd > 0).all():
        return {k: 0.0 for k in KEYS}
    w = (1 / sd) / (1 / sd).sum()
    pv = float(np.sqrt(w @ cov @ w))
    w = w * min(VOL_TARGET / pv, 1.0 / w.sum()) if pv > 0 else w * 0
    return {k: float(x) for k, x in zip(KEYS, w)}


def candidate(key: str, m: Market, P: fc.Panel | None = None) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """(asset keys, target weights (T, K) known at each close, due (T,) the days it may trade, reweigh (T,) the
    days every asset goes back to its target)."""
    T = len(m.days)
    ones = np.ones(T, dtype=bool)
    none = np.zeros(T, dtype=bool)
    weekly = np.array([s1.rebalance_day(d, 7) for d in m.days])
    monthly = month_start(m.days)
    if key in ("spy_hold", "btc_hold"):
        k = "SPY" if key == "spy_hold" else "BTC"
        return [k], np.ones((T, 1)), ones, none
    if key == "spy_trend":
        return ["SPY"], m.spy_up.astype(float)[:, None], ones, none
    if key == "mix_6040":
        return ["SPY", "BTC"], np.tile([0.6, 0.4], (T, 1)), monthly, monthly
    if key == "trend_mix":
        return ["SPY", "BTC"], np.column_stack([0.6 * m.spy_up, 0.4 * m.btc_up]).astype(float), ones, monthly
    if key == "dual_mom":
        R = np.column_stack([_ret_back(m.px[k], 365) for k in KEYS])
        W = np.zeros((T, len(KEYS)))
        ok = np.isfinite(R).all(1)
        best = np.argmax(np.where(np.isfinite(R), R, -np.inf), axis=1)
        go = ok & (R[np.arange(T), best] > 0)
        W[np.flatnonzero(go), best[go]] = 1.0
        return list(KEYS), W, weekly, none
    if key == "vol_target":
        W = np.zeros((T, len(KEYS)))
        for t in np.flatnonzero(weekly):
            W[t] = [vol_weights(m, t)[k] for k in KEYS]
        return list(KEYS), W, weekly, none
    if key == "tsmom1":
        if P is None:
            raise ValueError("tsmom1 needs the panel")
        Wp = s1.ffill(s1.candidate(P, "tsmom_top20", 1))
        cols = [j for j in np.flatnonzero(np.abs(Wp).sum(0) > 0) if "~" not in P.names[j]]
        keys = [fc.base_of(P.names[j]) for j in cols]
        return keys, Wp[:, cols], ones, none
    raise KeyError(key)


def coin_prices(key: str, keys: list[str], m: Market, P: fc.Panel | None, eurusd: float) -> np.ndarray:
    """(T, K) EUR prices of the candidate's assets: the modelled tokens, or the panel's coins for tsmom1."""
    if key != "tsmom1":
        return np.column_stack([m.px[k] for k in keys])
    return np.column_stack([P.px[:, P.col(f"{k}USDT")] / eurusd for k in keys])


# ---------------------------------------------------------------- the wallet over a window

def simulate(px: np.ndarray, keys: list[str], W: np.ndarray, due: np.ndarray, reweigh: np.ndarray, sol_eur: np.ndarray,
             venue: S2Venue, capital: float, t0: int, t1: int, slots: int) -> dict:
    """S1's wallet from the close of t0 (all USDC, the way there paid) to the close of t1; trades at the closes
    on due days (and at t0), every asset back to its target on reweigh days (an order there under the minimum
    is not tried again before the next re-weight or a new target)."""
    w = s1.Wallet(cash=capital)
    idle, once = venue.setup(capital, slots, sol_eur[t0] or 100.0)
    w.cash -= idle + once
    w.idle, w.costs = idle, once
    eq = np.zeros(t1 - t0 + 1)
    for i, t in enumerate(range(t0, t1 + 1)):
        prices = {k: float(px[t, j]) for j, k in enumerate(keys) if np.isfinite(px[t, j]) and px[t, j] > 0}
        if (due[t] or t == t0) and np.isfinite(W[t]).all():
            tg = {k: float(W[t, j]) for j, k in enumerate(keys)}
            if reweigh[t]:
                w.last = {}
            s1.rebalance(w, tg, prices, venue, sol_eur[t])
            if reweigh[t]:
                w.last.update(tg)               # a re-weight under the minimum waits for the next month
        eq[i] = w.value(prices)
    return {"equity": eq, "costs": w.costs, "orders": w.orders, "skipped": w.skipped, "dust": w.dust}


def months(days_us: np.ndarray, eq: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(month labels, monthly returns) of an equity curve that starts at the first day's close."""
    lab = (days_us // fc.DAY_US).astype("datetime64[D]").astype("datetime64[M]")
    out_l, out_r = [], []
    prev = eq[0]
    for mth in np.unique(lab):
        last = eq[np.flatnonzero(lab == mth)[-1]]
        out_l.append(mth)
        out_r.append(last / prev - 1)
        prev = last
    return np.array(out_l), np.array(out_r)


def measure(res: dict, capital: float, days_us: np.ndarray, bench_eq: np.ndarray | None) -> dict:
    m = s1.measure(res, capital)
    _, mr = months(days_us, res["equity"])
    m["worst_month"] = float(mr.min()) if len(mr) else 0.0
    if bench_eq is not None:
        _, br = months(days_us, bench_eq)
        m["months_beat"] = float((mr > br).mean()) if len(mr) else 0.0
    return m


def daily_returns(eq: np.ndarray, capital: float) -> np.ndarray:
    return np.r_[eq[0] / capital - 1, eq[1:] / eq[:-1] - 1]


def _cagr(r: np.ndarray) -> float:
    g = float(np.prod(1 + r))
    return g ** (365 / len(r)) - 1 if g > 0 and len(r) else -1.0


def bootstrap(x: np.ndarray, y: np.ndarray, draws: int = BOOT_DRAWS, block: int = BOOT_BLOCK, seed: int = 0) -> dict:
    """Circular block bootstrap of the CAGR of x and of x's CAGR minus y's on the same drawn days."""
    rng = np.random.default_rng(seed)
    n = len(x)
    nb = -(-n // block)
    cx, cd = np.empty(draws), np.empty(draws)
    for i in range(draws):
        idx = ((rng.integers(0, n, nb)[:, None] + np.arange(block)[None, :]) % n).ravel()[:n]
        cx[i] = _cagr(x[idx])
        cd[i] = cx[i] - _cagr(y[idx])
    return {"cagr_p05": float(np.quantile(cx, 0.05)), "cagr_p95": float(np.quantile(cx, 0.95)),
            "diff_p05": float(np.quantile(cd, 0.05)), "diff_p95": float(np.quantile(cd, 0.95)),
            "diff_above_0": float((cd > 0).mean())}


def diff_var(diffs: dict[str, np.ndarray]) -> float:
    """The variance of the candidates' daily Sharpes of their difference to the benchmark (clipped at +-3 a year
    as fc.deflate does): the pool S2 registered, its 8 trials at their own variance."""
    sr = [d.mean() / d.std() if d.std() > 0 else 0.0 for d in diffs.values()]
    return float(np.var(np.clip(np.array(sr) * math.sqrt(365), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)))


def dsr(diffs: dict[str, np.ndarray], pool: dict | None = None) -> dict[str, float]:
    """The DSR (higher is better, pass at 0.95 or more) of each candidate's daily return difference to the
    benchmark: the probability that its Sharpe beats the best of pool's n_trials noise trials. pool: the trial
    registry's of all by default (metrics.trial_pool); {"n_trials": TRIALS, "var": diff_var(diffs)} is the
    pool as registered. Unmeasurable (no spread, or the skew and kurtosis leave no variance): 0."""
    from ..metrics import deflated_sharpe, trial_pool
    from scipy import stats
    pool = pool or trial_pool()
    out = {}
    for k, d in diffs.items():
        if d.std() == 0:
            out[k] = 0.0
            continue
        sr = d.mean() / d.std()
        sk, ku = float(stats.skew(d)), float(stats.kurtosis(d, fisher=False))
        if 1 - sk * sr + (ku - 1) / 4 * sr ** 2 <= 0:
            out[k] = 0.0
            continue
        out[k] = deflated_sharpe(sr, len(d), pool["n_trials"], pool["var"], sk, ku)
    return out


def dsr_pools(diffs: dict[str, np.ndarray]) -> dict[str, dict]:
    """The three pools S2 reports: the registry's of all (the one the bar uses), its small-account family, and
    the 8 trials as registered."""
    from ..metrics import trial_pool
    return {"all": trial_pool(), "small": trial_pool("small"), "registered": {"n_trials": TRIALS, "var": diff_var(diffs)}}


def verdict(rows: dict[str, dict], bench: str = "spy_hold") -> dict[str, dict]:
    """The pre-registered bar at 40 EUR out of sample: fairly safe, beats or matches, convincingly."""
    b = rows[bench]["oos"]["cagr"]
    out = {}
    for k, r in rows.items():
        o = r["oos"]
        safe = o["max_dd"] < SAFE_DD
        match = o["cagr"] >= b - MATCH_SLACK
        conv = safe and match and r.get("boot", {}).get("diff_p05", -1) > 0 and r.get("dsr", 0.0) >= DSR_PASS
        ok = k not in REFERENCES
        out[k] = {"safe": safe, "matches": match, "passes": ok and safe and match, "convincing": ok and conv}
    return out


def paper_picks(rows: dict[str, dict], n: int = 2) -> list[str]:
    """The two paper books: best in-sample Sharpe at 40 EUR with an in-sample drawdown under 20 %, filled up by
    in-sample Sharpe; never the references or tsmom1."""
    c = [k for k in rows if k not in REFERENCES and k != "tsmom1"]
    safe = sorted([k for k in c if rows[k]["is"]["max_dd"] < SAFE_DD], key=lambda k: -rows[k]["is"]["sharpe"])
    rest = sorted([k for k in c if k not in safe], key=lambda k: -rows[k]["is"]["sharpe"])
    return (safe + rest)[:n]


# ---------------------------------------------------------------- the study

def load_etf(syms=("SPY", "GLD")) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    from . import etf_trend as et
    return {s: et.parse_stooq(et.load_csv(s)) for s in syms}


def windows(P: fc.Panel, etf: dict) -> dict[str, tuple[int, int]]:
    """In sample and out of sample on the panel's days, the out-of-sample window ending at the last ETF close
    (at most CUT)."""
    last = min([CUT] + [str(etf[s][0][-1]) for s in etf])
    us = int(datetime.strptime(last, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
    cut = min(int(np.searchsorted(P.days, us, side="right")) - 1, P.T - 1)
    oos = s1._t(P, OOS_FROM)
    return {"is": (s1._t(P, IS_FROM), oos - 1), "oos": (oos, cut)}


def run(P: fc.Panel, etf: dict, v: S2Venue, drifts: dict[str, float], noise: dict[str, np.ndarray] | None = None,
        capitals=CAPITALS) -> dict:
    m = market(P, etf, v.eurusd, drifts)
    win = windows(P, etf)
    built = {k: candidate(k, m, P) for k in CANDIDATES}
    pxs = {k: coin_prices(k, built[k][0], m, P, v.eurusd) for k in CANDIDATES}
    res: dict[str, dict] = {}
    for cap in capitals:
        eqs: dict[tuple, np.ndarray] = {}
        for wname, (t0, t1) in win.items():
            for k in ["spy_hold"] + [x for x in CANDIDATES if x != "spy_hold"]:
                keys, W, due, rw = built[k]
                r = simulate(pxs[k], keys, W, due, rw, m.sol_eur, v, cap, t0, t1, SLOTS[k])
                eqs[(k, wname)] = r["equity"]
                res.setdefault(f"{k}@{cap:g}", {"key": k, "capital": cap})[wname] = measure(
                    r, cap, m.days[t0:t1 + 1], eqs[("spy_hold", wname)])
        if cap == MAIN:
            t0, t1 = win["oos"]
            ret = {k: daily_returns(eqs[(k, "oos")], cap) for k in CANDIDATES}
            diffs = {k: ret[k] - ret["spy_hold"] for k in CANDIDATES if k != "spy_hold"}
            pools = dsr_pools(diffs)
            by = {name: dsr(diffs, pl_) for name, pl_ in pools.items()}
            for k in CANDIDATES:
                if k != "spy_hold":
                    res[f"{k}@{cap:g}"]["boot"] = bootstrap(ret[k], ret["spy_hold"])
                    res[f"{k}@{cap:g}"]["dsr"] = by["all"][k]
                    res[f"{k}@{cap:g}"]["dsr_small"] = by["small"][k]
                    res[f"{k}@{cap:g}"]["dsr_registered"] = by["registered"][k]
            res["_pools"] = {name: {"n_trials": pl_["n_trials"], "var": pl_["var"]} for name, pl_ in pools.items()}
            res["_curves"] = {k: [round(float(x), 4) for x in eqs[(k, "oos")]] for k in CANDIDATES}
    if noise:
        sens: dict[str, list] = {k: [] for k in CANDIDATES}
        t0, t1 = win["oos"]
        for seed in range(NOISE_SEEDS):
            mn = market(P, etf, v.eurusd, drifts, noise, seed)
            for k in CANDIDATES:
                keys, W, due, rw = built[k] if k in ("spy_hold", "btc_hold", "mix_6040", "trend_mix", "spy_trend",
                                                      "tsmom1") else candidate(k, mn, P)
                r = simulate(coin_prices(k, keys, mn, P, v.eurusd), keys, W, due, rw, mn.sol_eur, v, MAIN, t0, t1,
                             SLOTS[k])
                sens[k].append(s1.measure(r, MAIN))
        res["_noise"] = {k: {f: float(np.median([x[f] for x in xs])) for f in ("cagr", "max_dd", "sharpe")}
                         for k, xs in sens.items()}
    res["_windows"] = {w: [str((P.days[a] // fc.DAY_US).astype("datetime64[D]")),
                           str((P.days[b] // fc.DAY_US).astype("datetime64[D]"))] for w, (a, b) in win.items()}
    return res


# ---------------------------------------------------------------- the report

MARKER = "<!-- generated below by lab.experiments.smallaccount_s2; edit above this line only -->"


def _pct(v, d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f} %"


def markdown(out: dict) -> str:
    res, ver = out["res"], out["verdict"]
    w = res["_windows"]
    md = [f"Generated {out['generated']}. In sample {w['is'][0]} to {w['is'][1]}, out of sample {w['oos'][0]} to "
          f"{w['oos'][1]}. EUR/USD {out['eurusd']:.4f}. Tokens priced from their underlying (drift a year: "
          + ", ".join(f"{k} {v * 100:+.2f} %" for k, v in out["drifts"].items()) + ").\n"]
    md.append("## 1. The tokens (Jupiter's verified list, liquidity as Jupiter reports it)\n")
    t = [{"token": r["symbol"], "what": r["name"], "family": r["family"], "kind": r["kind"],
          "liquidity": f"{int(r['liquidity_usd']):,} USD", "holders": f"{int(r['holders']):,}"}
         for r in out["tokens"] if r["kind"] in ("sp500", "ndx", "total", "gold") or int(r["liquidity_usd"]) >= 1e6]
    md.append(fc.table(t, list(t[0])) if t else "none\n")
    md.append("## 2. What a swap costs (half the round trip USDC to token and back, bps; network fee not in)\n")
    by: dict[str, dict] = {}
    for q in out["quotes"]:
        by.setdefault(q["symbol"], {"token": q["symbol"]})[f"{float(q['usd']):g} USD"] = (
            f"{float(q['half_rt_bps']):.1f} ({float(q['impact_pct']):.2f} %)")
    t = list(by.values())
    md.append(fc.table(t, ["token"] + [f"{u:g} USD" for u in RUNGS]) if t else "none\n")
    md.append("In brackets Jupiter's price impact on the way in.\n")
    md.append("## 3. How closely the tokens followed their underlying\n")
    t = [{"token": r["symbol"], "vs": r["underlying"], "source": r["source"], "days": r["days"],
          "since": r.get("first") or "", "premium mean / sd bps": f"{_f(r, 'premium_mean_bps')} / {_f(r, 'premium_sd_bps')}",
          "abs p95 bps": _f(r, "premium_abs_p95_bps"), "TE a year": f"{_f(r, 'te_yr_pct', 2)} %",
          "drift a year": f"{_f(r, 'drift_yr_pct', 2)} %", "corr": _f(r, "corr", 3),
          "weekend move mean / max bps": (f"{_f(r, 'weekend_abs_mean_bps')} / {_f(r, 'weekend_abs_max_bps')}"
                                          if r.get("weekend_abs_mean_bps") else "")} for r in out["tracking"]]
    md.append(fc.table(t, list(t[0])) if t else "none measured\n")
    md.append("## 4. The candidates out of sample at 20, 40 and 50 EUR\n")
    t = []
    for k in CANDIDATES:
        for cap in CAPITALS:
            r = res[f"{k}@{cap:g}"]
            o = r["oos"]
            t.append({"candidate": k, "EUR": f"{cap:g}", "CAGR": _pct(o["cagr"]), "max DD": _pct(o["max_dd"]),
                      "Sharpe": f"{o['sharpe']:.2f}", "worst month": _pct(o["worst_month"]),
                      "months > ETF": _pct(o.get("months_beat"), 0) if k != "spy_hold" else "",
                      "costs": _pct(o["cost_share"]), "orders/yr": f"{o['orders_yr']:.0f}",
                      "not sent/yr": f"{o['skipped_yr']:.0f}", "IS CAGR / DD / Sharpe":
                      f"{_pct(r['is']['cagr'])} / {_pct(r['is']['max_dd'])} / {r['is']['sharpe']:.2f}"})
    md.append(fc.table(t, list(t[0])))
    md.append("`costs`: share of the gain before costs the costs took (n/a: no gain). `months > ETF`: calendar "
              "months that beat spy_hold.\n")
    md.append("## 5. Against the ETF token at 40 EUR: bootstrap, deflation, the bar\n")
    t = []
    for k in CANDIDATES:
        r, v = res[f"{k}@{MAIN:g}"], ver[k]
        b = r.get("boot") or {}
        t.append({"candidate": k, "CAGR band": f"{_pct(b.get('cagr_p05'))} to {_pct(b.get('cagr_p95'))}" if b else "",
                  "CAGR minus ETF": f"{_pct(r['oos']['cagr'] - res[f'spy_hold@{MAIN:g}']['oos']['cagr'])}" if b else "",
                  "band": f"{_pct(b.get('diff_p05'))} to {_pct(b.get('diff_p95'))}" if b else "",
                  "draws above": _pct(b.get("diff_above_0"), 0) if b else "",
                  "DSR, pass at 0.95 or more (all / small / registered)": (
                      f"{r['dsr']:.3f} / {r['dsr_small']:.3f} / {r['dsr_registered']:.3f}" if "dsr" in r else ""),
                  "safe": v["safe"], "matches": v["matches"], "bar": v["passes"], "convincing": v["convincing"],
                  "with premium noise": (f"{_pct(out['res']['_noise'][k]['cagr'])} / {_pct(out['res']['_noise'][k]['max_dd'])}"
                                         if out["res"].get("_noise") else "")})
    md.append(fc.table(t, list(t[0])))
    pools = res.get("_pools") or {}
    n = {k: f"{int(pools[k]['n_trials']):,}" if k in pools else "?" for k in ("all", "small", "registered")}
    md.append("Bar: out-of-sample drawdown under 20 % and CAGR at least the ETF token's minus 1 point. Convincing: also "
              "the 5 % band of the difference above 0 and a DSR of 0.95 or more over the trial registry's pool of "
              f"all ({n['all']} trials). DSR: the deflated Sharpe ratio of the daily difference to the ETF token, the "
              "probability that it beats the best of that many noise trials; higher is better. Next to it the "
              f"registry's small-account family ({n['small']} trials) and the {n['registered']} trials as registered "
              "(their own variance). With premium noise: CAGR / drawdown, median of 20 draws of the measured premium "
              "at the close.\n")
    md.append("## 6. Paper books (picked in sample)\n")
    md.append(", ".join(f"`{k}`" for k in out["paper"]) + "\n")
    return "\n".join(md) + "\n"


def _f(r: dict, k: str, d: int = 1) -> str:
    v = r.get(k)
    try:
        return f"{float(v):.{d}f}"
    except (TypeError, ValueError):
        return "n/a"


def write(out: dict, path: Path = RESULTS / "smallaccount_s2.md") -> None:
    head = "# S2: a fairly safe 20 to 50 EUR wallet on Solana, against an ETF\n\n"
    if path.exists():
        old = path.read_text(encoding="utf-8")
        if MARKER in old:
            head = old.split(MARKER)[0]
    path.write_text(head + MARKER + "\n\n" + markdown(out), encoding="utf-8")


def premiums(path: Path = PREMIUMS_CSV, snap: dict | None = None) -> dict[str, np.ndarray]:
    snap = snap or load_snapshot()
    alias = {(p or {}).get("symbol"): k for k, p in snap["picks"].items() if p}
    out: dict[str, list] = {}
    if path.exists():
        for r in s1.read_csv(path):
            if r["symbol"] in alias:
                out.setdefault(alias[r["symbol"]], []).append(float(r["premium_bps"]))
    return {k: np.array(v) for k, v in out.items()}


def drifts_from(snap: dict, tr: dict[str, dict]) -> dict[str, float]:
    return {k: drift(tr.get((p or {}).get("symbol")), k) for k, p in snap["picks"].items() if p}


def main() -> int:
    if "--snapshot" in sys.argv:
        snapshot("--tracking-only" in sys.argv)
        return 0
    snap = load_snapshot()
    if not snap["picks"].get("SPY"):
        print("no S&P 500 token qualifies: the study stops here (pre-registered)", file=sys.stderr)
        return 1
    v = venue(snap=snap)
    tr = tracking()
    drifts = drifts_from(snap, tr)
    P = fc.load_panel()
    etf = load_etf()
    t0 = time.time()
    res = run(P, etf, v, drifts, premiums(snap=snap))
    rows = {k: res[f"{k}@{MAIN:g}"] for k in CANDIDATES}
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "eurusd": v.eurusd, "drifts": drifts,
           "picks": snap["picks"], "issuers": snap.get("issuers"), "res": res, "verdict": verdict(rows),
           "paper": paper_picks(rows), "tokens": s1.read_csv(TOKENS_CSV), "quotes": s1.read_csv(QUOTES_CSV),
           "tracking": s1.read_csv(TRACKING_CSV), "seconds": round(time.time() - t0)}
    from .. import report
    d = report.REPORTS / NAME
    d.mkdir(parents=True, exist_ok=True)
    (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    write(out)
    print(f"done in {out['seconds']} s; paper {out['paper']}; bar "
          f"{[k for k, x in out['verdict'].items() if x['passes']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
