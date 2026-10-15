"""Trending watcher: what the crypto crowd is chasing, every 15 minutes. Reads only.

    python -m lab.ops.trending              one run: snapshot, surge alerts, the daily digest when due
    python -m lab.ops.trending --dry-run    print what would be stored and posted, write and post nothing
    python -m lab.ops.trending --digest     post the daily watchlist digest now

Sources, all public and keyless:

  DexScreener   the top boosted tokens (/token-boosts/top/v1), the latest token
                profiles (/token-profiles/latest/v1) and, for those tokens,
                their most liquid pair (/tokens/v1/<chain>/<addresses>, with
                /latest/dex/search as the fallback): price change, volume,
                liquidity, FDV, pair age, buys and sells.
  Binance       24h tickers of every USDT spot pair (top gainers), and for the
                coins Alpaca lists the last 28 daily klines, so a coin's 24h
                quote volume and trade count can be set against its own
                28-day median (a volume surge). Market-wide surges use the
                daily volumes this watcher keeps itself, from 7 days of them.

What it does with them:

  store    every run appends one line to <data>/trending/<YYYY-MM-DD>.jsonl
           and rewrites <reports>/trending/latest.json
  alert    a strong surge on a coin Alpaca lists (actionable on the paper
           account) is posted at once: 24h quote volume at least 3x its
           28-day median and up at least 8 % in 24 h, or up at least 20 %
           with volume at least 2x. One alert per coin per 20 hours. The text
           says what W7 found about buying surges.
  digest   once a day, at the first run from 08:00 UTC: the on-chain hype
           (top boosted tokens with their risk flags), Binance's top gainers
           and the Alpaca coins' surge ratios. On-chain tokens are labelled
           high risk and read-only: they are not on Alpaca, and nothing here
           trades on a DEX or touches a wallet.

Delivery is lab.ops.notify's (PYTHIA_TELEGRAM_BOT_TOKEN and
PYTHIA_TELEGRAM_CHAT_ID, or PYTHIA_ALERT_WEBHOOK); unset, it only prints.
PYTHIA_ALPACA_COINS (comma separated bases) overrides the list of coins
Alpaca lists. State (alert times, daily volumes, last digest) is
<data>/trending/state.json. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import notify

DEX = "https://api.dexscreener.com"
BINANCE_HOSTS = ("https://api.binance.com", "https://data-api.binance.vision")
ALPACA_COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "BCH", "UNI", "AAVE",
                "PEPE", "FIL", "SHIB", "BONK", "WIF", "TRUMP")
MEMES = ("DOGE", "SHIB", "PEPE", "BONK", "WIF", "TRUMP")
NOT_COINS = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "AEUR", "EURI", "USD1", "XUSD", "BFUSD",
             "USDE", "RLUSD", "PYUSD", "PAXG", "XAUT", "WBTC", "WBETH", "U"}
# Alert rules, fixed in advance.
SURGE_STRONG, UP_STRONG = 3.0, 0.08
SURGE_SOME, UP_BIG = 2.0, 0.20
ALERT_EVERY_H = 20
DIGEST_HOUR = 8
MIN_GAINER_QV = 5_000_000
HISTORY_DAYS, HISTORY_MIN = 28, 7
TOP_DEX = 15
# On-chain risk flags.
LOW_LIQ_USD = 50_000
YOUNG_H = 72
FDV_LIQ_MAX = 50
CAVEAT = ("HIGH RISK, watch only. On-chain tokens are not on Alpaca; pumps, rug pulls and wash trading "
          "dominate. Nothing here trades on a DEX or touches a wallet.")

Fetch = Callable[[str], object]


def now_ms() -> int:
    return int(time.time() * 1000)


def alpaca_coins() -> tuple[str, ...]:
    env = (os.environ.get("PYTHIA_ALPACA_COINS") or "").strip()
    if env:
        return tuple(x.strip().upper() for x in env.split(",") if x.strip())
    return ALPACA_COINS


def http_json(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={"User-Agent": "pythia-trending", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def binance(get: Fetch, path: str):
    last: Exception | None = None
    for h in BINANCE_HOSTS:
        try:
            return get(f"{h}{path}")
        except (urllib.error.URLError, OSError, ValueError) as e:
            last = e
    raise last if last else RuntimeError("no Binance host")


def num(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


# ---------------------------------------------------------------- DexScreener

def dex_tokens(get: Fetch) -> list[dict]:
    """Boosted and newly profiled tokens, boosted first, one entry per (chain, address)."""
    out, seen = [], set()
    for path, kind in (("/token-boosts/top/v1", "boosted"), ("/token-profiles/latest/v1", "profile")):
        try:
            items = get(f"{DEX}{path}")
        except (urllib.error.URLError, OSError, ValueError):
            continue
        for it in items if isinstance(items, list) else []:
            key = (it.get("chainId"), it.get("tokenAddress"))
            if not all(key) or key in seen:
                continue
            seen.add(key)
            out.append({"chain": key[0], "address": key[1], "source": kind,
                        "boost": num(it.get("totalAmount") or it.get("amount")), "url": it.get("url")})
    return out


def best_pair(pairs: list[dict], address: str) -> dict | None:
    mine = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == address.lower()]
    if not mine:
        return None
    return max(mine, key=lambda p: num((p.get("liquidity") or {}).get("usd")) or 0.0)


def pair_row(p: dict, now: int) -> dict:
    liq = num((p.get("liquidity") or {}).get("usd"))
    fdv = num(p.get("fdv"))
    created = num(p.get("pairCreatedAt"))
    tx = (p.get("txns") or {}).get("h24") or {}
    row = {"symbol": (p.get("baseToken") or {}).get("symbol"), "name": (p.get("baseToken") or {}).get("name"),
           "dex": p.get("dexId"), "price_usd": num(p.get("priceUsd")),
           "change_h1": num((p.get("priceChange") or {}).get("h1")),
           "change_h24": num((p.get("priceChange") or {}).get("h24")),
           "volume_h24": num((p.get("volume") or {}).get("h24")), "liquidity_usd": liq, "fdv": fdv,
           "age_h": (now - created) / 3_600_000 if created else None,
           "buys_h24": tx.get("buys"), "sells_h24": tx.get("sells"), "pair_url": p.get("url")}
    row["flags"] = risk_flags(row)
    return row


def risk_flags(r: dict) -> list[str]:
    f = []
    if r.get("liquidity_usd") is None or r["liquidity_usd"] < LOW_LIQ_USD:
        f.append("thin liquidity")
    if r.get("age_h") is not None and r["age_h"] < YOUNG_H:
        f.append("pair under 3 days old")
    if r.get("fdv") and r.get("liquidity_usd") and r["fdv"] / r["liquidity_usd"] > FDV_LIQ_MAX:
        f.append("FDV over 50x liquidity")
    if r.get("volume_h24") and r.get("liquidity_usd") and r["volume_h24"] / r["liquidity_usd"] > 20:
        f.append("volume over 20x liquidity (wash?)")
    b, s = r.get("buys_h24"), r.get("sells_h24")
    if isinstance(b, int) and isinstance(s, int) and b + s > 50 and s < 0.2 * b:
        f.append("few sells (honeypot?)")
    return f


def dex_enrich(get: Fetch, tokens: list[dict], now: int, limit: int = TOP_DEX) -> list[dict]:
    tokens = tokens[:limit]
    by_chain: dict[str, list[dict]] = {}
    for t in tokens:
        by_chain.setdefault(t["chain"], []).append(t)
    pairs: dict[tuple, dict] = {}
    for chain, ts in by_chain.items():
        for i in range(0, len(ts), 30):
            addrs = ",".join(t["address"] for t in ts[i:i + 30])
            try:
                got = get(f"{DEX}/tokens/v1/{urllib.parse.quote(chain)}/{urllib.parse.quote(addrs, safe=',')}")
            except (urllib.error.URLError, OSError, ValueError):
                got = []
            for t in ts[i:i + 30]:
                p = best_pair(got if isinstance(got, list) else [], t["address"])
                if p is None:
                    try:
                        s = get(f"{DEX}/latest/dex/search?q={urllib.parse.quote(t['address'])}")
                        p = best_pair((s or {}).get("pairs") or [], t["address"])
                    except (urllib.error.URLError, OSError, ValueError):
                        p = None
                if p is not None:
                    pairs[(chain, t["address"])] = p
    out = []
    for t in tokens:
        p = pairs.get((t["chain"], t["address"]))
        row = {"chain": t["chain"], "address": t["address"], "source": t["source"], "boost": t["boost"]}
        row.update(pair_row(p, now) if p else {"flags": ["no pair found"]})
        out.append(row)
    return out


# ---------------------------------------------------------------- Binance

def base_of(symbol: str) -> str | None:
    if not symbol.endswith("USDT"):
        return None
    b = symbol[:-4]
    if not b or b in NOT_COINS or b.endswith(("UP", "DOWN", "BULL", "BEAR")):
        return None
    return b


def tickers(get: Fetch) -> dict[str, dict]:
    """base -> {change, qv, count, price} for every USDT spot pair with volume."""
    out = {}
    for t in binance(get, "/api/v3/ticker/24hr") or []:
        b = base_of(t.get("symbol", ""))
        qv = num(t.get("quoteVolume"))
        if b is None or not qv:
            continue
        out[b] = {"change": (num(t.get("priceChangePercent")) or 0.0) / 100, "qv": qv,
                  "count": int(num(t.get("count")) or 0), "price": num(t.get("lastPrice"))}
    return out


def kline_medians(get: Fetch, base: str) -> dict | None:
    """Median daily quote volume and trade count over the 28 completed days before today."""
    try:
        k = binance(get, f"/api/v3/klines?symbol={base}USDT&interval=1d&limit={HISTORY_DAYS + 1}")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    done = (k or [])[:-1]
    if len(done) < HISTORY_MIN:
        return None
    return {"qv": statistics.median(float(x[7]) for x in done), "count": statistics.median(float(x[8]) for x in done),
            "days": len(done)}


def surge(t: dict, med: dict | None) -> dict:
    out = {"change": t["change"], "qv": t["qv"], "count": t["count"], "qv_ratio": None, "count_ratio": None}
    if med and med.get("qv"):
        out["qv_ratio"] = t["qv"] / med["qv"]
    if med and med.get("count"):
        out["count_ratio"] = t["count"] / med["count"]
    return out


def is_strong(s: dict) -> bool:
    r, c = s.get("qv_ratio"), s.get("change")
    if r is None or c is None:
        return False
    return (r >= SURGE_STRONG and c >= UP_STRONG) or (r >= SURGE_SOME and c >= UP_BIG)


def update_history(hist: dict, tick: dict[str, dict], day: str) -> dict:
    """Keep each coin's last 24h quote volume per UTC day (the latest of the day), 28 days."""
    for b, t in tick.items():
        h = [x for x in hist.get(b, []) if x[0] != day]
        h.append([day, t["qv"]])
        hist[b] = sorted(h)[-HISTORY_DAYS - 1:]
    return hist


def market_surges(hist: dict, tick: dict[str, dict], day: str, top: int = 10) -> list[dict]:
    out = []
    for b, t in tick.items():
        past = [v for d, v in hist.get(b, []) if d < day]
        if len(past) < HISTORY_MIN or t["qv"] < MIN_GAINER_QV:
            continue
        m = statistics.median(past)
        if m > 0:
            out.append({"coin": b, "qv_ratio": t["qv"] / m, "change": t["change"], "qv": t["qv"]})
    return sorted(out, key=lambda x: -x["qv_ratio"])[:top]


def gainers(tick: dict[str, dict], top: int = 10) -> list[dict]:
    rows = [{"coin": b, **t} for b, t in tick.items() if t["qv"] >= MIN_GAINER_QV]
    return sorted(rows, key=lambda r: -r["change"])[:top]


# ---------------------------------------------------------------- texts

def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v * 100:+.0f}%"


def money(v: float | None) -> str:
    if v is None:
        return "n/a"
    for unit, d in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(v) >= d:
            return f"${v / d:.1f}{unit}"
    return f"${v:.0f}"


def alert_text(prefix: str, coin: str, s: dict, finding: str | None) -> str:
    lines = [f"{prefix} surge: {coin} on Alpaca (paper account) {pct(s['change'])} in 24h, "
             f"volume {s['qv_ratio']:.1f}x its 28-day median"
             + (f", trades {s['count_ratio']:.1f}x" if s.get("count_ratio") else "") + ".",
             "Watch only: no order is placed."]
    if coin in MEMES:
        lines.append("Memecoin: moves like this often reverse within days.")
    if finding:
        lines.append(finding)
    return "\n".join(lines)


def digest_text(prefix: str, snap: dict, finding: str | None) -> str:
    lines = [f"{prefix} trending digest {snap['ts'][:10]}"]
    al = snap.get("alpaca") or {}
    hot = sorted(((c, s) for c, s in al.items() if s.get("qv_ratio")), key=lambda cs: -cs[1]["qv_ratio"])[:6]
    if hot:
        lines.append("Alpaca coins, volume vs 28d median:")
        lines += [f"  {c} {s['qv_ratio']:.1f}x, {pct(s['change'])}" for c, s in hot]
    g = snap.get("gainers") or []
    if g:
        lines.append("Binance top gainers 24h: " + ", ".join(f"{r['coin']} {pct(r['change'])}" for r in g[:6]))
    ms = snap.get("market_surges") or []
    if ms:
        lines.append("Binance volume surges: " + ", ".join(f"{r['coin']} {r['qv_ratio']:.1f}x" for r in ms[:6]))
    dex = [r for r in snap.get("dex") or [] if r.get("symbol")]
    if dex:
        lines.append("")
        lines.append("ON-CHAIN HYPE (" + CAVEAT + ")")
        for r in dex[:8]:
            fl = "; ".join(r.get("flags") or []) or "no flags"
            lines.append(f"  {r['symbol']} ({r['chain']}) {pct((r.get('change_h24') or 0) / 100)} 24h, "
                         f"liq {money(r.get('liquidity_usd'))}, vol {money(r.get('volume_h24'))} [{fl}]")
    if finding:
        lines += ["", finding]
    return notify.clip("\n".join(lines))


def w7_finding() -> str | None:
    """One line from the W7 report, if it is there."""
    p = Path(os.environ.get("PYTHIA_AGENT_OUT", str(notify.data_root() / "agent-strategies"))) / "reports" / "memecoins.json"
    data = notify.read_json(p)
    if not data:
        return W7_LINE
    for v in data.get("verdicts", []):
        if v.get("family", "").startswith("F4"):
            return (f"W7 backtest: buying volume surges on the Alpaca memecoins made Sharpe {v['pick_oos_35']:.2f} "
                    f"out of sample at 35 bps (drawdown {v['pick_dd'] * 100:.0f} %), positive in "
                    f"{v['years_pos']} of 3 years. Not a paper book.")
    return W7_LINE


W7_LINE = ("W7 backtest: buying volume surges on the Alpaca memecoins paid in 2024 and lost in 2025 and 2026; "
           "not a paper book (results/memecoins.md).")


# ---------------------------------------------------------------- one run

def state_path() -> Path:
    return notify.data_root() / "trending" / "state.json"


def snapshot(get: Fetch, hist: dict, now: int) -> tuple[dict, dict]:
    ts = datetime.fromtimestamp(now / 1000, timezone.utc)
    day = f"{ts:%Y-%m-%d}"
    snap: dict = {"ts": ts.isoformat(timespec="seconds"), "errors": []}
    try:
        tick = tickers(get)
    except (urllib.error.URLError, OSError, ValueError, RuntimeError) as e:
        tick = {}
        snap["errors"].append(f"binance tickers: {type(e).__name__}")
    al = {}
    for c in alpaca_coins():
        if c in tick:
            al[c] = surge(tick[c], kline_medians(get, c))
    snap["alpaca"] = al
    snap["gainers"] = gainers(tick)
    if tick:
        hist = update_history(hist, tick, day)
    snap["market_surges"] = market_surges(hist, tick, day)
    try:
        snap["dex"] = dex_enrich(get, dex_tokens(get), now)
    except (urllib.error.URLError, OSError, ValueError) as e:
        snap["dex"] = []
        snap["errors"].append(f"dexscreener: {type(e).__name__}")
    return snap, hist


def run(get: Fetch = http_json, now: int | None = None, dry_run: bool = False, force_digest: bool = False,
        poster=None) -> dict:
    now = now or now_ms()
    st = notify.read_json(state_path()) or {}
    snap, hist = snapshot(get, st.get("history", {}), now)
    url, fmt, prefix = notify.config()
    post = poster or (lambda text: notify.post(url, fmt, text) if url else (False, "no webhook"))
    finding = w7_finding()
    alerts = st.get("alerts", {})
    sent = []
    for c, s in snap["alpaca"].items():
        if not is_strong(s):
            continue
        if now - alerts.get(c, 0) < ALERT_EVERY_H * 3_600_000:
            continue
        text = notify.clip(alert_text(prefix, c, s, finding))
        ok, err = (False, "dry run") if dry_run else post(text)
        print(text, flush=True)
        sent.append({"coin": c, "delivered": ok, "error": err})
        if not dry_run:
            alerts[c] = now
    snap["alerts_sent"] = sent
    ts = datetime.fromtimestamp(now / 1000, timezone.utc)
    day = f"{ts:%Y-%m-%d}"
    due = force_digest or (ts.hour >= DIGEST_HOUR and st.get("last_digest") != day)
    if due:
        text = digest_text(prefix, snap, finding)
        ok, err = (False, "dry run") if dry_run else post(text)
        print(text, flush=True)
        snap["digest"] = {"delivered": ok, "error": err}
        if not dry_run:
            st["last_digest"] = day
    if dry_run:
        print(json.dumps({k: v for k, v in snap.items() if k != "dex"}, indent=1)[:4000])
        return snap
    d = notify.data_root() / "trending"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{day}.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(snap) + "\n")
    notify.write_json(notify.reports_root() / "trending" / "latest.json", snap)
    st.update({"history": hist, "alerts": alerts, "last_run": snap["ts"]})
    notify.write_json(state_path(), st)
    return snap


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--digest", action="store_true")
    a = ap.parse_args(argv)
    snap = run(dry_run=a.dry_run, force_digest=a.digest)
    return 1 if snap.get("errors") and not snap.get("alpaca") and not snap.get("dex") else 0


if __name__ == "__main__":
    sys.exit(main())
