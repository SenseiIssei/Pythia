"""Daily English Wikipedia page views of the coins' articles: investor attention. Data only.

Source: the Wikimedia REST API (public, keyless),
    https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/<title>/daily/<from>/<to>
one request per title for the whole range, and the MediaWiki API for each article's
redirects. Wikimedia asks clients for a User-Agent that says who they are; ours names the
project's public repository. We send at most 4 requests a second; a daily run is about
300 small requests.

A coin's attention is the sum of the views of its article and of every redirect to it
(today's redirect list, kept per run in wiki_titles.parquet), so an article that was
renamed keeps its history: the old title is a redirect now. Views of day d are published
by the next morning; whoever uses them for a decision at the close of day t must stop at
day t-1 (lab.experiments.attention_wiki does).

Lake (under $PYTHIA_FLOW, default $PYTHIA_DATA/flow):
  wiki_pageviews.parquet   title, day_us, views      (agent "user", all access)
  wiki_titles.parquet      day_us, base, article, title   (the title set of each run)

    python -m lab.collect.wiki               continue every title (history from 2015-07-01 on the first run)
    python -m lab.collect.wiki --dry-run     fetch, print counts, write nothing

The mapping below was built on 2026-10-21 (results/attention_wiki_prereg.md): the most
liquid coins of the survivorship-free panel, each to one English article about the coin
or its own network. Coins without such an article are left out, with the reason.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Callable

import polars as pl

from . import flow

UA = "pythia-lab attention collector (https://github.com/SenseiIssei/Pythia; research, daily)"
PAGEVIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user"
MEDIAWIKI = "https://en.wikipedia.org/w/api.php"
START = date(2015, 7, 1)       # the first day the pageviews API serves
PAUSE = 0.25
OVERLAP_DAYS = 3

# Base (as fam_common.base_of names it) -> canonical English Wikipedia article.
ARTICLES: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana (blockchain platform)",
    "XRP": "XRP Ledger",                       # "XRP" redirects here; Ripple Labs is the company
    "DOGE": "Dogecoin",
    "ADA": "Cardano (blockchain platform)",
    "MATIC": "Polygon (blockchain)",           # MATIC until 2024-09, then POL: one network
    "POL": "Polygon (blockchain)",
    "LINK": "Chainlink (blockchain oracle)",
    "AVAX": "Avalanche (blockchain platform)",
    "LTC": "Litecoin",
    "TRX": "Tron (blockchain)",
    "SHIB": "Shiba Inu (cryptocurrency)",
    "WLD": "World (blockchain)",               # formerly Worldcoin
    "NEAR": "NEAR (blockchain platform)",
    "DOT": "Polkadot (blockchain platform)",
    "FIL": "Filecoin",
    "BCH": "Bitcoin Cash",
    "TRUMP": "$Trump",
    "UNI": "Uniswap",
    "AAVE": "Aave",
    "EOS": "EOS.IO",
    "TON": "TON (blockchain)",
    "ETC": "Ethereum Classic",
    "XMR": "Monero",
    "XLM": "Stellar (payment network)",
    "HBAR": "Hedera (distributed ledger)",
    "ZEC": "Zcash",
    "ALGO": "Algorand",
    "HNT": "Helium Network",
    "LUNA": "Terra (blockchain)",              # both LUNA segments; LUNC left out (same article)
    "AXS": "Axie Infinity",
    "MANA": "Decentraland",
    "DASH": "Dash (cryptocurrency)",
    "NEO": "NEO (blockchain)",
    "CHZ": "Chiliz",
    "CAKE": "PancakeSwap",
    "XTZ": "Tezos",
    "IOTA": "IOTA (technology)",
    "NANO": "Nano (cryptocurrency)",
    "XNO": "Nano (cryptocurrency)",
    "BCHSV": "Bitcoin Satoshi Vision",
    "BSV": "Bitcoin Satoshi Vision",
    "BTG": "Bitcoin Gold",
    "XVG": "Verge (cryptocurrency)",
    "ENJ": "Enjin",
    "1INCH": "1inch",
    "BNT": "Bancor",
    "LSK": "Lisk",
    "CKB": "Nervos Network",
    "PYTH": "Pyth Network",
    "ILV": "Illuvium",
    "HMSTR": "Hamster Kombat",
    "REP": "Augur (software)",
    "KAS": "Kaspa",
}

# Liquid coins left out, and why (checked against the MediaWiki API on 2026-10-21).
DROPPED: dict[str, str] = {
    "BNB": "no article of its own; 'Binance Coin' redirects to the exchange",
    "FTT": "only the exchange's article (FTX)",
    "WLFI": "the company's article (World Liberty Financial)",
    "PUMP": "the platform's article (Pump.fun), not the token's",
    "PEPE": "no coin article; 'Pepe' is the cartoon frog",
    "FLOKI": "'Floki' resolves to a Norse figure",
    "KSM": "'Kusama' resolves to the artist",
    "EGLD": "'Elrond' is the Tolkien character; MultiversX has no article",
    "TIA": "'Celestia' is the astronomy program",
    "INJ": "registered as dropped ('Injective' resolves to the maths term)",
    "OP": "'Optimism (blockchain)' redirects to Ethereum",
    "SAND": "'The Sandbox' is a disambiguation page",
    "LUNC": "the Terra article stays with LUNA",
    "BAT": "'Basic Attention Token' redirects to the Brave browser",
    "STEEM": "'Steem' is a disambiguation page; Steemit is the site",
    "WIF": "redirects to 'Meme coin'",
}
NO_ARTICLE = ("SUI", "ENA", "ARB", "FTM", "TAO", "BONK", "APT", "ATOM", "ICP", "MKR", "VET", "THETA", "GRT", "SNX",
              "COMP", "WAVES", "SUSHI", "FET", "GALA", "ZIL", "RVN", "DCR", "GLM", "ZRX", "CRV", "RENDER", "RNDR",
              "ONDO", "LDO", "ENS", "STRK", "STX", "DYDX", "SEI", "QTUM", "SC", "HOT", "ORDI", "SAGA", "JUP")

Fetch = Callable[[str], object]


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def get_json(url: str, tries: int = 6, pause: float = PAUSE) -> object | None:
    """GET a JSON document with our User-Agent; None on 404 (no views stored for that title
    and range). 429 and 5xx are retried with backoff (Retry-After honoured)."""
    last: Exception | None = None
    for k in range(tries):
        if pause:
            time.sleep(pause)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:
                return None
            if e.code != 429 and e.code < 500:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(60.0, 2.0 ** k))
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            last = e
            time.sleep(min(60.0, 2.0 ** k))
    raise RuntimeError(f"{url}: no answer after {tries} tries ({last})")


# ---------------------------------------------------------------------------
# Titles and views
# ---------------------------------------------------------------------------

def redirects(fetch: Fetch, article: str) -> list[str]:
    """Every main-namespace redirect to the article (following 'continue')."""
    out: list[str] = []
    cont: dict = {}
    while True:
        q = {"action": "query", "titles": article, "prop": "redirects", "rdlimit": "max", "rdnamespace": 0,
             "format": "json", **cont}
        ans = fetch(f"{MEDIAWIKI}?{urllib.parse.urlencode(q)}") or {}
        for p in (ans.get("query") or {}).get("pages", {}).values():
            out += [r["title"] for r in p.get("redirects", [])]
        if "continue" not in ans:
            return sorted(set(out))
        cont = {k: v for k, v in ans["continue"].items()}


def title_set(fetch: Fetch, articles: dict[str, str] | None = None) -> pl.DataFrame:
    """(base, article, title): every coin's article and its redirects."""
    articles = articles or ARTICLES
    rd: dict[str, list[str]] = {}
    rows = []
    for base, art in articles.items():
        if art not in rd:
            rd[art] = redirects(fetch, art)
        for t in [art] + rd[art]:
            rows.append({"base": base, "article": art, "title": t})
    return pl.DataFrame(rows, schema={"base": pl.Utf8, "article": pl.Utf8, "title": pl.Utf8})


def url_title(title: str) -> str:
    return urllib.parse.quote(title.replace(" ", "_"), safe="")


def views(fetch: Fetch, title: str, since: date, until: date) -> pl.DataFrame:
    """Daily user views of one title from since to until (inclusive)."""
    url = f"{PAGEVIEWS}/{url_title(title)}/daily/{since:%Y%m%d}00/{until:%Y%m%d}00"
    ans = fetch(url)
    items = (ans or {}).get("items", []) if isinstance(ans, dict) else []
    rows = [{"title": title, "day_us": flow.us_of(date(int(i["timestamp"][:4]), int(i["timestamp"][4:6]),
                                                       int(i["timestamp"][6:8]))), "views": int(i["views"])}
            for i in items]
    return pl.DataFrame(rows, schema={"title": pl.Utf8, "day_us": pl.Int64, "views": pl.Int64})


def continue_from(old: pl.DataFrame | None, title: str) -> date:
    if old is None or old.is_empty():
        return START
    t = old.filter(pl.col("title") == title)
    if t.is_empty():
        return START
    return max(START, flow.day_of(int(t["day_us"].max())) - timedelta(days=OVERLAP_DAYS))


def coin_views(pv: pl.DataFrame, titles: pl.DataFrame) -> pl.DataFrame:
    """(base, day_us, views): each coin's views summed over its article and redirects.
    A title stored twice for one base (MATIC and POL share theirs) counts once per base."""
    t = titles.select("base", "title").unique()
    return (pv.join(t, on="title", how="inner").group_by(["base", "day_us"]).agg(views=pl.col("views").sum())
            .sort(["base", "day_us"]))


def run(dry: bool, fetch: Fetch | None = None, until: date | None = None) -> dict:
    fetch = fetch or get_json
    until = until or (flow.today() - timedelta(days=1))
    titles = title_set(fetch)
    old = flow.read("wiki_pageviews")
    frames, empty = [], 0
    uniq = titles["title"].unique().sort().to_list()
    for i, t in enumerate(uniq):
        since = continue_from(old, t)
        if since > until:
            continue
        df = views(fetch, t, since, until)
        empty += df.is_empty()
        frames.append(df)
        if i % 50 == 0:
            print(f"  {i}/{len(uniq)} titles", flush=True)
    new = pl.concat(frames) if frames else pl.DataFrame(schema={"title": pl.Utf8, "day_us": pl.Int64,
                                                                "views": pl.Int64})
    out = flow.merge(old, new, ["title", "day_us"])
    snap = titles.with_columns(day_us=pl.lit(flow.us_of(flow.today()), pl.Int64)).select("day_us", "base", "article",
                                                                                         "title")
    summary = {"coins": titles["base"].n_unique(), "articles": titles["article"].n_unique(), "titles": len(uniq),
               "titles_without_views": int(empty), "rows_new": new.height, "rows_total": out.height,
               "last_day": str(flow.day_of(int(out["day_us"].max()))) if out.height else None}
    if not dry:
        flow.write("wiki_pageviews", out)
        flow.write("wiki_titles", flow.merge(flow.read("wiki_titles"), snap, ["day_us", "base", "title"]))
    return summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    s = run(a.dry_run)
    print(json.dumps(s, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
