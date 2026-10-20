"""Daily news sentiment per coin (X11 e2): headlines from publisher RSS feeds,
scored by one Claude Haiku call a day through the engine's metered endpoint
(Batches API). A candidate M2 input only if it earns it on forward data.

Pre-registered in results/model_upgrades_prereg.md (e2).

Sources: the public RSS feeds of CoinDesk, Cointelegraph, Decrypt, The Block,
CryptoSlate and Bitcoin Magazine. Only titles, links, the source and the
publication time are kept, for this private record; nothing is republished.
Google News RSS is not used: its feed says it may only be rendered in a
personal feed reader.

  python -m lab.ai.news --collect    every few hours: fetch the feeds, keep new headlines (no call)
  python -m lab.ai.news              daily after 00:00 UTC: score yesterday's headlines (one call)
  python -m lab.ai.news --dry-run    print the prompt and its size, call nothing
  python -m lab.ai.news --score      rescore only

Headlines of UTC day D are scored against the 7-day return from D's close,
so nothing published after the reference close is used. Files:
<data>/ai/news/<D>.jsonl (headlines), <data>/ai/news_sentiment.jsonl (one row
per coin and day), reports/ai_news/latest.json (scores).

The registered test (after at least 26 weeks of M2's recorded ranking days):
the mean of M2's and the sentiment's percentile ranks among the Alpaca coins
against M2 alone, weekly rank IC, paired t above 2. Until then nothing reads it.
"""

from __future__ import annotations

import email.utils
import json
import math
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from ..ops import notify
from . import analyst, engine, score

NAME = "ai_news"
FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt": "https://decrypt.co/feed",
    "The Block": "https://www.theblock.co/rss.xml",
    "CryptoSlate": "https://cryptoslate.com/feed/",
    "Bitcoin Magazine": "https://bitcoinmagazine.com/.rss/full/",
}
UA = "pythia-lab-news/1.0 (private research; titles only)"
MAX_PER_COIN = 10
MAX_TITLE = 160
MAX_TOKENS = 3000
BATCH_WAIT_SEC = 30 * 60
MIN_WEEKS = 26
PASS_T = 2.0

# Names (case-insensitive) and tickers (case-sensitive, whole word) per coin.
COINS: dict[str, tuple[list[str], list[str]]] = {
    "AAVE": (["aave"], ["AAVE"]), "ADA": (["cardano"], ["ADA"]), "ARB": (["arbitrum"], ["ARB"]),
    "AVAX": (["avalanche"], ["AVAX"]), "BAT": (["basic attention token"], ["BAT"]),
    "BCH": (["bitcoin cash"], ["BCH"]), "BONK": (["bonk"], ["BONK"]),
    "BTC": (["bitcoin(?! cash)"], ["BTC"]), "CRV": (["curve finance", "curve dao"], ["CRV"]),
    "DOGE": (["dogecoin"], ["DOGE"]), "DOT": (["polkadot"], ["DOT"]), "ETH": (["ethereum", "ether"], ["ETH"]),
    "FIL": (["filecoin"], ["FIL"]), "GRT": (["the graph"], ["GRT"]), "HYPE": (["hyperliquid"], ["HYPE"]),
    "LDO": (["lido"], ["LDO"]), "LINK": (["chainlink"], ["LINK"]), "LTC": (["litecoin"], ["LTC"]),
    "ONDO": (["ondo"], ["ONDO"]), "PEPE": (["pepe"], ["PEPE"]), "POL": (["polygon"], ["POL", "MATIC"]),
    "RENDER": (["render network"], ["RENDER", "RNDR"]), "SHIB": (["shiba inu"], ["SHIB"]),
    "SKY": (["sky protocol", "makerdao"], ["SKY"]), "SOL": (["solana"], ["SOL"]),
    "SUSHI": (["sushiswap"], ["SUSHI"]), "TRUMP": (["trump memecoin", "trump coin", "official trump"], [r"\$TRUMP"]),
    "UNI": (["uniswap"], ["UNI"]), "WIF": (["dogwifhat"], ["WIF"]), "XRP": (["ripple"], ["XRP"]),
    "XTZ": (["tezos"], ["XTZ"]), "YFI": (["yearn"], ["YFI"]),
}

SYSTEM = """You score crypto news headlines for Pythia, a paper-trading research system. For each coin you get \
the headlines of one UTC day that mention it. Give sentiment: a number from -1 (clearly bad news for the coin's \
price over the next week) through 0 (neutral, mixed, or not really about the coin) to 1 (clearly good news). \
Judge only from the headlines given; do not add knowledge of later events. A headline that only mentions the coin \
in passing counts little. relevant: how many of the headlines are really about this coin. Do not use em dashes. \
Answer with the JSON object only, in the schema given."""

SCHEMA = {
    "type": "object",
    "properties": {"scores": {"type": "array", "items": {
        "type": "object",
        "properties": {"coin": {"type": "string"}, "sentiment": {"type": "number"}, "relevant": {"type": "integer"}},
        "required": ["coin", "sentiment", "relevant"], "additionalProperties": False}}},
    "required": ["scores"], "additionalProperties": False,
}


def news_dir() -> Path:
    return score.ai_dir() / "news"


def sentiment_path() -> Path:
    return score.ai_dir() / "news_sentiment.jsonl"


# ---------------------------------------------------------------- collect

def patterns() -> dict[str, re.Pattern]:
    out = {}
    for c, (names, tickers) in COINS.items():
        parts = [r"(?i:\b" + n + r"\b)" for n in names] + [r"(?<![A-Za-z])" + t + r"\b" for t in tickers]
        out[c] = re.compile("|".join(parts))
    return out


def coins_in(title: str, pats: dict[str, re.Pattern] | None = None) -> list[str]:
    pats = pats or patterns()
    return [c for c, p in pats.items() if p.search(title)]


def parse_feed(xml: bytes, source: str) -> list[dict]:
    """RSS 2.0 items as {title, link, source, published_us}; items without a date are skipped."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        title = " ".join((it.findtext("title") or "").split())
        pub = it.findtext("pubDate")
        if not title or not pub:
            continue
        try:
            dt = email.utils.parsedate_to_datetime(pub)
        except (TypeError, ValueError):
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        out.append({"title": title[:300], "link": (it.findtext("link") or "").strip()[:300], "source": source,
                    "published_us": int(dt.timestamp() * 1e6)})
    return out


def fetch(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(5_000_000)


def collect(fetcher=fetch) -> int:
    """Fetch every feed, keep headlines not seen yet in their UTC day's file. Returns how many were new."""
    pats = patterns()
    new = 0
    by_day: dict[str, list[dict]] = {}
    for src, url in FEEDS.items():
        try:
            items = parse_feed(fetcher(url), src)
        except Exception as e:  # noqa: BLE001 - one feed down never stops the others
            notify.say(f"news: {src} not fetched ({type(e).__name__})", err=True)
            continue
        for it in items:
            it["coins"] = coins_in(it["title"], pats)
            day = datetime.fromtimestamp(it["published_us"] / 1e6, timezone.utc).strftime("%Y-%m-%d")
            by_day.setdefault(day, []).append(it)
    d = news_dir()
    d.mkdir(parents=True, exist_ok=True)
    for day, items in by_day.items():
        f = d / f"{day}.jsonl"
        seen = {r["title"] for r in read_jsonl(f)}
        with f.open("a", encoding="utf-8", newline="\n") as fh:
            for it in items:
                if it["title"] in seen:
                    continue
                seen.add(it["title"])
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
                new += 1
    notify.say(f"news: {new} new headlines")
    return new


def read_jsonl(p: Path) -> list[dict]:
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict):
            out.append(r)
    return out


# ---------------------------------------------------------------- score one day

def build_prompt(day: str, items: list[dict]) -> tuple[str, list[str]]:
    per: dict[str, list[str]] = {}
    for it in sorted(items, key=lambda x: x["published_us"]):
        for c in it.get("coins") or []:
            if len(per.setdefault(c, [])) < MAX_PER_COIN:
                per[c].append(it["title"][:MAX_TITLE])
    lines = [f"DAY: {day} (UTC). Headlines per coin:"]
    for c, ts in per.items():
        lines.append(f"{c}:")
        lines += [f"- {t}" for t in ts]
    return "\n".join(lines), list(per)


def parse_answer(obj, cs: list[str]) -> dict[str, dict]:
    out = {}
    for it in (obj or {}).get("scores") or []:
        if not isinstance(it, dict):
            continue
        c = str(it.get("coin") or "").strip().upper()
        try:
            s = float(it.get("sentiment"))
            n = int(it.get("relevant"))
        except (TypeError, ValueError):
            continue
        if c in cs and c not in out and math.isfinite(s):
            out[c] = {"sentiment": max(-1.0, min(1.0, s)), "relevant": max(0, n)}
    return out


def score_day(day: str, now: int, dry_run: bool = False, poster=None) -> tuple[int, float]:
    items = read_jsonl(news_dir() / f"{day}.jsonl")
    prompt, cs = build_prompt(day, items)
    if not cs:
        notify.say(f"news: no headline about an Alpaca coin on {day}")
        return 0, 0.0
    if dry_run:
        notify.say(SYSTEM + "\n\n" + prompt)
        notify.say(f"\n[dry run] about {(len(SYSTEM) + len(prompt)) // 4:,} input tokens, at most {MAX_TOKENS} out")
        return 0, 0.0
    ans = engine.complete("news", SYSTEM, prompt, MAX_TOKENS, model=engine.model_for("news", engine.ROUTINE),
                          schema=SCHEMA, effort=engine.effort_for("news", "low"),
                          batch=True, batch_wait_sec=BATCH_WAIT_SEC, poster=poster)
    got = parse_answer(ans.get("json"), cs)
    cost = float(ans.get("costUsd") or 0.0)
    counts = {c: sum(c in (it.get("coins") or []) for it in items) for c in cs}
    rows = [{"day": day, "made_ms": now, "coin": c, "sentiment": g["sentiment"], "relevant": g["relevant"],
             "headlines": counts[c], "model": ans.get("servedBy") or ans.get("model") or engine.ROUTINE,
             "cost_usd_call": cost} for c, g in got.items()]
    _append(rows)
    notify.say(f"news {day}: {len(rows)} coins scored, ${cost:.4f}")
    return len(rows), cost


def _append(rows: list[dict]) -> None:
    p = sentiment_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + "\n")


# ---------------------------------------------------------------- scoring

def pct(xs: dict[str, float]) -> dict[str, float]:
    ks = list(xs)
    if len(ks) < 2:
        return {k: 0.5 for k in ks}
    order = sorted(ks, key=lambda k: xs[k])
    r = {}
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in order[i:j + 1]:
            r[k] = ((i + j) / 2) / (len(ks) - 1)
        i = j + 1
    return r


def score_rows(rows: list[dict], bars: dict[str, analyst.Bars], m2: dict[str, dict[str, float]]) -> dict:
    close = {c: {x["day"]: x["close"] for x in b} for c, b in bars.items()}
    alp = set(analyst.coins())
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        by_day.setdefault(r["day"], {})[r["coin"]] = float(r["sentiment"])

    def fwd(c, d):
        e = (date.fromisoformat(d) + timedelta(days=7)).isoformat()
        a, b = close.get(c, {}).get(d), close.get(c, {}).get(e)
        return math.log(b / a) if a and b else None
    daily = []
    for d, s in sorted(by_day.items()):
        cs = [c for c in s if fwd(c, d) is not None]
        ic = analyst.spearman([s[c] for c in cs], [fwd(c, d) for c in cs])
        if ic is not None:
            daily.append({"day": d, "coins": len(cs), "ic": ic})
    weeks = []
    for d, m in sorted(m2.items()):
        cs = [c for c in m if c in alp and fwd(c, d) is not None]
        if len(cs) < 5 or d not in by_day:
            continue
        sent = {c: by_day[d].get(c, 0.0) for c in cs}  # no headline: neutral
        pm, ps = pct({c: m[c] for c in cs}), pct(sent)
        y = [fwd(c, d) for c in cs]
        a = analyst.spearman([pm[c] for c in cs], y)
        b = analyst.spearman([(pm[c] + ps[c]) / 2 for c in cs], y)
        if a is not None and b is not None:
            weeks.append({"day": d, "coins": len(cs), "ic_m2": a, "ic_m2_news": b})
    diff = [w["ic_m2_news"] - w["ic_m2"] for w in weeks]
    t = analyst.tstat(diff)
    ok = len(weeks) >= MIN_WEEKS and sum(diff) > 0 and (t or 0) > PASS_T
    return {"days_scored": len(daily), "mean_daily_ic": (sum(x["ic"] for x in daily) / len(daily)) if daily else None,
            "m2_weeks": len(weeks), "mean_ic_m2": (sum(w["ic_m2"] for w in weeks) / len(weeks)) if weeks else None,
            "mean_ic_m2_news": (sum(w["ic_m2_news"] for w in weeks) / len(weeks)) if weeks else None,
            "t_diff": t, "daily": daily[-60:], "weeks": weeks,
            "verdict": (f"Too early: {len(weeks)} M2 weeks of {MIN_WEEKS}." if len(weeks) < MIN_WEEKS else
                        "Passes: a candidate M2 input (needs its own study)." if ok else
                        "Fails: sentiment stays a shadow record.")}


def run(now_ms: int | None = None, dry_run: bool = False, only_score: bool = False, loader=analyst.lake_bars,
        poster=None) -> int:
    now = now_ms or notify.clock_ms()
    rows = read_jsonl(sentiment_path())
    if not only_score:
        day = (datetime.fromtimestamp(now / 1000, timezone.utc).date() - timedelta(days=1)).isoformat()
        if any(r.get("day") == day for r in rows) and not dry_run:
            notify.say(f"news: {day} is scored already")
        else:
            try:
                score_day(day, now, dry_run, poster)
            except engine.AiError as e:
                notify.say(f"no news score: {e}", err=e.kind not in ("budget", "nokey"))
                return 0 if e.kind in ("budget", "nokey") else 1
            if dry_run:
                return 0
            rows = read_jsonl(sentiment_path())
    bars = analyst.bars_for(sorted({r["coin"] for r in rows}), loader) if rows else {}
    sc = score_rows(rows, bars, analyst.m2_ranks())
    calls = {r["made_ms"]: float(r.get("cost_usd_call") or 0.0) for r in rows}
    sc.update(cost_usd_total=sum(calls.values()), calls=len(calls), title="AI news sentiment (shadow)",
              status="ok", updated_ms=now,
              headline=f"Daily Claude sentiment from publisher headlines, {sc['days_scored']} days scored. {sc['verdict']}",
              items=[{"label": "mean daily rank IC, sentiment", "value": analyst._r(sc.get("mean_daily_ic"))},
                     {"label": "M2 weeks, M2 alone / with sentiment",
                      "value": f"{analyst._r(sc.get('mean_ic_m2'))} / {analyst._r(sc.get('mean_ic_m2_news'))}"}])
    notify.write_json(notify.reports_root() / NAME / "latest.json", sc)
    notify.say(sc["verdict"])
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if "--collect" in argv:
        collect()
        return 0
    return run(dry_run="--dry-run" in argv, only_score="--score" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
