"""W6: the listing effect. What does buying a coin when it gets listed earn?

    python -m lab.experiments.listings              the study (needs the lake and network)
    python -m lab.experiments.listings --offline    only what the lake holds (family A)

Pre-registered in results/listings.md (the part above the marker was committed
before this file ran). Three families of long-only events, every return net of
35 bps per side (Alpaca taker plus slippage) and measured against BTC over the
same window:

  A  first listings on Binance: every USDT pair whose hourly history in the
     lake (hist/binance_spot/klines_1h, every pair ever listed, delisted ones
     included, from 2020-01) starts after 2020-02-01. Entry at the close of the
     first hour or of the first day, held 1, 3, 7 or 30 days (8 cells).
  B  cross-venue listings: a coin that has traded on Binance for 30 days or
     more gets its first USD pair on Coinbase or Kraken. Listing time: the
     first daily candle on Coinbase, the first trade on Kraken (both public).
     Entry at the Binance close of the first full hour after that time (the
     watcher sees a new pair within 10 minutes), held 1, 3, 7 or 30 days
     (4 cells, both venues pooled). The day before the listing (the
     announcement pop, not tradable on the listing alert) is reported only.
  C  Alpaca listings: the first daily bar of every Alpaca crypto pair, the
     launch batch (first bar within 45 days of the earliest) left out. Entry
     and exits as B, priced on Binance (4 cells).

In sample: events up to 2023-12-31; out of sample from 2024-01-01. Per family
the in-sample pick is the cell with the highest mean net excess return. The
pass rule for a paper book on Alpaca listings is in results/listings.md.
Writes results/listings.md and <reports>/listing_effect/latest.json.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..data import HOUR_US, ROOT
from ..metrics import deflated_sharpe

NAME = "listings"
MARKER = "<!-- generated below by lab.experiments.listings; edit above this line only -->"
COST = 0.0035
STRESS = 0.0070
DAY_US = 24 * HOUR_US
HORIZONS = (1, 3, 7, 30)
ENTRIES_A = {"first hour": 1, "first day": 24}
FIRST_OK = int(datetime(2020, 2, 1, tzinfo=timezone.utc).timestamp() * 1e6)
SPLIT = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
MIN_PRIOR_DAYS = 30
LAUNCH_DAYS = 45
STALE_H = 6                 # a price older than this many hours at the time asked is no price
BOOT = 10_000
SEED = 7
TRIALS_HERE = 2 * 4 + 4 + 4
PRIOR_TRIALS = 377          # the pool after C16 (results/alpaca_universe.md)
MIN_OOS_EVENTS = 30
BOOK_BUDGET_USD = 500.0

RESULTS = Path(os.environ.get("PYTHIA_FAM_RESULTS", str(Path(__file__).resolve().parents[2] / "results")))
REPORTS = Path(os.environ.get("PYTHIA_REPORTS", str(ROOT / "reports")))
CACHE = ROOT / "hist" / "listings"

# Not crypto risk, or not a coin: stablecoins, gold, wrapped duplicates, leveraged tokens.
EXCLUDE_BASES = {"USDC", "BUSD", "TUSD", "USDP", "FDUSD", "DAI", "USDS", "USDSB", "PAX", "PAXG", "XAUT", "EUR",
                 "GBP", "AUD", "TRY", "BRL", "WBTC", "WBETH", "BETH", "BNSOL", "FRAX", "AEUR", "EURI", "USD1",
                 "PYUSD", "RLUSD", "USDE", "BFUSD", "XUSD"}
LEVERAGED = ("UP", "DOWN", "BULL", "BEAR")


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

@dataclass
class Series:
    """Hourly closes: t[i] is the START of hour i (us), c[i] its close."""
    t: np.ndarray
    c: np.ndarray

    def at(self, ts_us: int) -> float:
        """The last close known at ts_us (the bar that ended at or before it), NaN when stale or outside."""
        i = int(np.searchsorted(self.t + HOUR_US, ts_us, side="right")) - 1
        if i < 0 or ts_us - (self.t[i] + HOUR_US) > STALE_H * HOUR_US:
            return float("nan")
        return float(self.c[i])

    @property
    def start(self) -> int:
        return int(self.t[0])

    @property
    def end(self) -> int:
        return int(self.t[-1] + HOUR_US)


def net(entry: float, exit_: float, cost: float = COST) -> float:
    """Long round trip: buy at entry plus cost, sell at exit minus cost."""
    if not (entry > 0 and exit_ > 0):
        return float("nan")
    return exit_ * (1 - cost) / (entry * (1 + cost)) - 1


def event_returns(s: Series, btc: Series, entry_us: int, horizons=HORIZONS, cost: float = COST) -> dict:
    """Net, gross and BTC returns from entry_us to entry_us + h days, for each h."""
    e = s.at(entry_us)
    b0 = btc.at(entry_us)
    out = {"entry_us": entry_us, "entry_px": e}
    for h in horizons:
        x = s.at(entry_us + h * DAY_US) if entry_us + h * DAY_US <= s.end + STALE_H * HOUR_US else float("nan")
        bx = btc.at(entry_us + h * DAY_US)
        out[f"gross_{h}"] = x / e - 1 if e > 0 and x > 0 else float("nan")
        out[f"net_{h}"] = net(e, x, cost)
        out[f"stress_{h}"] = net(e, x, STRESS)
        out[f"btc_{h}"] = bx / b0 - 1 if b0 > 0 and bx > 0 else float("nan")
        out[f"excess_{h}"] = out[f"net_{h}"] - out[f"btc_{h}"]
    return out


def lake_series(symbol: str) -> list[Series]:
    """The lake's hourly closes of a Binance pair, split into segments like picks.hourly_segments."""
    from .picks import hourly_segments
    return [Series(seg["open_time_us"].to_numpy().astype(np.int64), seg["close"].to_numpy().astype(float))
            for seg in hourly_segments(symbol)]


def is_coin(base: str) -> bool:
    if base in EXCLUDE_BASES or not base.isascii() or not base:
        return False
    return not any(base.endswith(x) and len(base) > len(x) + 1 for x in LEVERAGED)


# ---------------------------------------------------------------------------
# Family A: first listings on Binance
# ---------------------------------------------------------------------------

def family_a(first: dict[str, Series], btc: Series, now_us: int) -> list[dict]:
    """One row per (pair, entry): the first segment of every pair that starts after FIRST_OK."""
    rows = []
    for sym, s in sorted(first.items()):
        base = sym[:-4]
        if s.start < FIRST_OK or not is_coin(base) or s.start > now_us - 31 * DAY_US:
            continue
        for label, hours in ENTRIES_A.items():
            r = event_returns(s, btc, s.start + hours * HOUR_US)
            rows.append({"family": "A", "entry": label, "symbol": sym, "base": base, "listed_us": s.start, **r})
    return rows


# ---------------------------------------------------------------------------
# Families B and C: a coin already on Binance listed somewhere else
# ---------------------------------------------------------------------------

def cross_rows(family: str, venue: str, listed: dict[str, int], first: dict[str, Series],
               latest: dict[str, Series], btc: Series, now_us: int) -> list[dict]:
    """`listed` maps base -> listing time (us) on the other venue."""
    rows = []
    for base, t_l in sorted(listed.items()):
        sym = base + "USDT"
        s = latest.get(sym)
        f = first.get(sym)
        if s is None or f is None or not is_coin(base) or t_l > now_us - 2 * DAY_US:
            continue
        if t_l - f.start < MIN_PRIOR_DAYS * DAY_US or not (s.start <= t_l <= s.end):
            continue
        entry = (t_l // HOUR_US + 1) * HOUR_US
        r = event_returns(s, btc, entry)
        pre0, pre1 = s.at(t_l - DAY_US), s.at(t_l)
        btc_pre = btc.at(t_l) / btc.at(t_l - DAY_US) - 1
        r["pre_1"] = pre1 / pre0 - 1 if pre0 > 0 and pre1 > 0 else float("nan")
        r["preexcess_1"] = r["pre_1"] - btc_pre
        rows.append({"family": family, "entry": "first hour after", "venue": venue, "symbol": sym, "base": base,
                     "listed_us": t_l, **r})
    return rows


def drop_launch(first_bars: dict[str, int], days: int = LAUNCH_DAYS) -> dict[str, int]:
    """Alpaca pairs whose first bar is a real listing, not the start of the venue's data."""
    if not first_bars:
        return {}
    t0 = min(first_bars.values())
    return {b: t for b, t in first_bars.items() if t > t0 + days * DAY_US}


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def month_of(us: int) -> int:
    d = datetime.fromtimestamp(us / 1e6, timezone.utc)
    return d.year * 12 + d.month - 1


def cluster_boot(x: np.ndarray, clusters: np.ndarray, n: int = BOOT, seed: int = SEED) -> np.ndarray:
    """Bootstrap means, resampling whole listing months (events of one month share a market)."""
    ok = np.isfinite(x)
    x, clusters = x[ok], clusters[ok]
    if len(x) == 0:
        return np.array([])
    ids, inv = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inv, weights=x)
    cnts = np.bincount(inv).astype(float)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(ids), size=(n, len(ids)))
    return sums[pick].sum(1) / np.maximum(cnts[pick].sum(1), 1)


def summarize(rows: list[dict], h: int, key: str = "excess") -> dict:
    x = np.array([r[f"{key}_{h}"] for r in rows], dtype=float)
    cl = np.array([month_of(r["listed_us"]) for r in rows])
    ok = np.isfinite(x)
    if ok.sum() == 0:
        return {"n": 0}
    xs = x[ok]
    b = cluster_boot(x, cl)
    sd = float(xs.std(ddof=1)) if len(xs) > 1 else float("nan")
    return {"n": int(ok.sum()), "months": int(len(np.unique(cl[ok]))), "mean": float(xs.mean()),
            "median": float(np.median(xs)), "hit": float((xs > 0).mean()), "sd": sd,
            "sharpe_event": float(xs.mean() / sd) if sd and sd > 0 else float("nan"),
            "skew": float(((xs - xs.mean()) ** 3).mean() / sd ** 3) if sd and sd > 0 else 0.0,
            "kurt": float(((xs - xs.mean()) ** 4).mean() / sd ** 4) if sd and sd > 0 else 3.0,
            "p05": float(np.quantile(b, 0.05)) if len(b) else float("nan"),
            "p025": float(np.quantile(b, 0.025)) if len(b) else float("nan"),
            "p975": float(np.quantile(b, 0.975)) if len(b) else float("nan"),
            "p_boot": float((b <= 0).mean()) if len(b) else 1.0}


def holm(pvals: dict[str, float]) -> dict[str, float]:
    keys = sorted(pvals, key=lambda k: pvals[k])
    m = len(keys)
    out, run = {}, 0.0
    for i, k in enumerate(keys):
        run = max(run, min(1.0, (m - i) * pvals[k]))
        out[k] = run
    return out


def split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    return [r for r in rows if r["listed_us"] < SPLIT], [r for r in rows if r["listed_us"] >= SPLIT]


def year_of(us: int) -> int:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).year


def cells(rows: list[dict], family: str) -> dict[str, dict]:
    """Every cell of a family, in and out of sample."""
    out = {}
    entries = sorted({r["entry"] for r in rows}) or ["first hour after"]
    for e in entries:
        er = [r for r in rows if r["entry"] == e]
        ins, oos = split(er)
        for h in HORIZONS:
            key = f"{family} · {e} · {h}d"
            out[key] = {"family": family, "entry": e, "h": h, "is": summarize(ins, h), "oos": summarize(oos, h),
                        "oos_net": summarize(oos, h, "net"), "oos_stress": summarize(oos, h, "stress"),
                        "is_net": summarize(ins, h, "net"),
                        "oos_years": {y: summarize([r for r in oos if year_of(r["listed_us"]) == y], h)
                                      for y in sorted({year_of(r["listed_us"]) for r in oos})}}
    return out


def pick(cs: dict[str, dict]) -> str | None:
    best = [(c["is"].get("mean", -math.inf), k) for k, c in cs.items() if c["is"].get("n", 0) >= 10]
    return max(best)[1] if best else None


def verdict(all_cells: dict[str, dict], picks: dict[str, str | None]) -> dict:
    """The pre-registered pass rule (results/listings.md) for a paper book on Alpaca listings."""
    srs = [c["oos"]["sharpe_event"] for c in all_cells.values() if math.isfinite(c["oos"].get("sharpe_event", math.nan))]
    var = float(np.var(srs, ddof=1)) if len(srs) > 1 else 0.0
    pv = {k: c["oos"].get("p_boot", 1.0) for k, c in all_cells.items() if c["oos"].get("n", 0) > 0}
    adj = holm(pv)
    for k, c in all_cells.items():
        o = c["oos"]
        c["holm_p"] = adj.get(k, 1.0)
        c["deflated_p"] = (deflated_sharpe(o["sharpe_event"], o["n"], PRIOR_TRIALS + TRIALS_HERE, var,
                                           o["skew"], o["kurt"])
                           if o.get("n", 0) > 2 and math.isfinite(o.get("sharpe_event", math.nan)) else 0.0)
    reasons = []
    kb = picks.get("B")
    if kb is None:
        reasons.append("family B has no in-sample pick (fewer than 10 events)")
        return {"passed": False, "reasons": reasons, "rule": None}
    c = all_cells[kb]
    o = c["oos"]
    if o.get("n", 0) < MIN_OOS_EVENTS:
        reasons.append(f"{o.get('n', 0)} out-of-sample events, {MIN_OOS_EVENTS} needed")
    if not o.get("mean", -1) > 0:
        reasons.append("out-of-sample mean net excess not above 0")
    if not o.get("p025", -1) > 0:
        reasons.append("bootstrap 95 % band of the mean includes 0")
    if not c["holm_p"] < 0.05:
        reasons.append(f"Holm-adjusted p {c['holm_p']:.2f} over {len(pv)} cells, 0.05 needed")
    if not c["deflated_p"] > 0.95:
        reasons.append(f"deflated p {c['deflated_p']:.2f}, 0.95 needed")
    bad_years = [y for y, s in c["oos_years"].items() if s.get("n", 0) >= 10 and not s.get("mean", -1) > 0]
    if bad_years:
        reasons.append("negative in " + ", ".join(map(str, bad_years)))
    kc = f"C · first hour after · {c['h']}d"
    cc = all_cells.get(kc)
    if cc:
        allc = [s for s in (cc["is"], cc["oos"]) if s.get("n", 0)]
        n = sum(s["n"] for s in allc)
        m = sum(s["n"] * s["mean"] for s in allc) / n if n else float("nan")
        if n >= 5 and not m >= 0:
            reasons.append(f"the {n} Alpaca listings lost on average at {c['h']} days ({m * 100:+.1f} %)")
    passed = not reasons
    return {"passed": passed, "reasons": reasons,
            "rule": {"entry": "first full hour after the listing", "horizon_days": c["h"], "cell": kb} if passed else None}


# ---------------------------------------------------------------------------
# Listing dates on the other venues (network, cached)
# ---------------------------------------------------------------------------

UA = {"User-Agent": "pythia-lab"}


def get_json(url: str, headers: dict | None = None, timeout: float = 30):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, OSError):
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError("unreachable")


def _cache(name: str) -> dict:
    p = CACHE / f"{name}.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return {}


def _save(name: str, d: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    tmp = CACHE / f"{name}.json.tmp"
    tmp.write_text(json.dumps(d, indent=1, sort_keys=True))
    os.replace(tmp, CACHE / f"{name}.json")


def coinbase_first(bases: set[str]) -> dict[str, int]:
    """base -> first daily candle (us) of its USD pair on Coinbase. Delisted products are not in the list."""
    known = _cache("coinbase_first")
    prods = get_json("https://api.exchange.coinbase.com/products")
    for p in prods:
        base = str(p.get("base_currency") or "").upper()
        if p.get("quote_currency") != "USD" or base not in bases or base in known:
            continue
        pid = p["id"]
        start = datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp()
        end_all = time.time()
        first = None
        while start < end_all and first is None:
            end = min(start + 299 * 86400, end_all)
            q = urllib.parse.urlencode({"granularity": 86400,
                                        "start": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                                        "end": datetime.fromtimestamp(end, timezone.utc).isoformat()})
            try:
                c = get_json(f"https://api.exchange.coinbase.com/products/{pid}/candles?{q}")
            except urllib.error.HTTPError:
                break
            if c:
                first = int(min(row[0] for row in c)) * 1_000_000
            start = end
            time.sleep(0.15)
        known[base] = first
        _save("coinbase_first", known)
    return {b: t for b, t in known.items() if t}


KRAKEN_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}


def kraken_first(bases: set[str]) -> dict[str, int]:
    """base -> first trade (us) of its USD pair on Kraken (Trades with since=0 starts at the first trade)."""
    known = _cache("kraken_first")
    pairs = get_json("https://api.kraken.com/0/public/AssetPairs").get("result") or {}
    for name, p in pairs.items():
        ws = str(p.get("wsname") or "")
        if "/" not in ws or name.endswith(".d"):
            continue
        b, q = ws.split("/", 1)
        base = KRAKEN_ALIASES.get(b, b)
        if q != "USD" or base not in bases or base in known:
            continue
        try:
            res = get_json(f"https://api.kraken.com/0/public/Trades?pair={urllib.parse.quote(name)}&since=0&count=1")
            trades = next((v for k, v in (res.get("result") or {}).items() if k != "last"), [])
            known[base] = int(float(trades[0][2]) * 1_000_000) if trades else None
        except (urllib.error.URLError, OSError, ValueError, IndexError, KeyError):
            known[base] = None
        _save("kraken_first", known)
        time.sleep(1.1)
    return {b: t for b, t in known.items() if t}


def alpaca_first() -> dict[str, int]:
    """base -> first daily bar (us) of every Alpaca crypto USD pair. Pairs Alpaca removed are not listed."""
    known = _cache("alpaca_first")
    k = (os.environ.get("APCA_API_KEY_ID") or "").strip()
    s = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("APCA_API_SECRET") or "").strip()
    h = {"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else {}
    if h:
        assets = get_json("https://paper-api.alpaca.markets/v2/assets?asset_class=crypto", h)
        syms = [a["symbol"] for a in assets if str(a.get("symbol", "")).endswith("/USD")]
    else:
        syms = [f"{b}/USD" for b in known] or []
    for sym in syms:
        base = sym.split("/")[0]
        if base in known:
            continue
        q = urllib.parse.urlencode({"symbols": sym, "timeframe": "1Day", "start": "2020-01-01T00:00:00Z", "limit": 1})
        try:
            bars = (get_json(f"https://data.alpaca.markets/v1beta3/crypto/us/bars?{q}", h).get("bars") or {}).get(sym) or []
            known[base] = int(datetime.fromisoformat(bars[0]["t"].replace("Z", "+00:00")).timestamp() * 1e6) if bars else None
        except (urllib.error.URLError, OSError, ValueError, KeyError, IndexError):
            known[base] = None
        _save("alpaca_first", known)
        time.sleep(0.3)
    return {b: t for b, t in known.items() if t}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def pct(v, d: int = 1) -> str:
    return "n/a" if v is None or not isinstance(v, (int, float)) or not math.isfinite(v) else f"{v * 100:+.{d}f} %"


def day(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def cell_table(all_cells: dict[str, dict], picks: dict[str, str | None]) -> list[str]:
    head = ("| cell | pick | IS n | IS mean excess | OOS n | OOS months | OOS mean excess | OOS median | OOS hit | "
            "boot 95 % | OOS mean net | at 70 bps | Holm p | deflated p |")
    out = [head, "|" + "---|" * 14]
    for k, c in all_cells.items():
        i, o = c["is"], c["oos"]
        out.append(f"| {k} | {'yes' if k in picks.values() else ''} | {i.get('n', 0)} | {pct(i.get('mean'))} | "
                   f"{o.get('n', 0)} | {o.get('months', 0)} | {pct(o.get('mean'))} | {pct(o.get('median'))} | "
                   f"{o.get('hit', float('nan')) * 100:.0f} % | {pct(o.get('p025'))} to {pct(o.get('p975'))} | "
                   f"{pct(c['oos_net'].get('mean'))} | {pct(c['oos_stress'].get('mean'))} | "
                   f"{c.get('holm_p', 1):.2f} | {c.get('deflated_p', 0):.2f} |")
    return out


def alpaca_table(rows: list[dict], budget: float = 1000.0) -> list[str]:
    out = [f"| coin | first Alpaca bar | " + " | ".join(f"net {h}d" for h in HORIZONS) + " |",
           "|" + "---|" * (2 + len(HORIZONS))]
    for r in sorted(rows, key=lambda r: r["listed_us"]):
        out.append(f"| {r['base']} | {day(r['listed_us'])} | " + " | ".join(pct(r[f'net_{h}']) for h in HORIZONS) + " |")
    tot = []
    for h in HORIZONS:
        x = np.array([r[f"net_{h}"] for r in rows], dtype=float)
        x = x[np.isfinite(x)]
        tot.append(f"${budget * x.sum():+,.0f} on {len(x)}" if len(x) else "n/a")
    out.append(f"| ${budget:,.0f} per listing, total | | " + " | ".join(tot) + " |")
    return out


def write_results(res: dict) -> None:
    p = RESULTS / "listings.md"
    head = p.read_text(encoding="utf-8").split(MARKER)[0] if p.exists() else "# listings\n\n"
    v = res["verdict"]
    L = [MARKER, "", f"## Results (generated {res['generated']}, data to {res['data_to']})", ""]
    if v["passed"]:
        L.append(f"**Verdict: the rule passes.** {v['rule']['cell']}: a paper book buys every new Alpaca listing "
                 f"with ${BOOK_BUDGET_USD:,.0f} at the first full hour and sells after {v['rule']['horizon_days']} days.")
    else:
        L.append("**Verdict: no rule passes; alerts only.** " + "; ".join(v["reasons"]) + ".")
    L += ["", f"Events: A {res['n']['A']} first Binance listings (two entries each), B {res['n']['B']} cross-venue "
          f"listings (Coinbase {res['n']['B_coinbase']}, Kraken {res['n']['B_kraken']}), C {res['n']['C']} Alpaca "
          f"listings after the launch batch. Trials here {TRIALS_HERE}, pool {PRIOR_TRIALS + TRIALS_HERE}. "
          f"Returns are per event, net of {COST * 1e4:.0f} bps per side, minus BTC over the same window "
          "(excess); the band is a bootstrap over listing months.", ""]
    if res.get("missing"):
        L += ["Not measured: " + "; ".join(res["missing"]) + ".", ""]
    L += ["### Every cell", ""] + cell_table(res["cells"], res["picks"]) + [""]
    if res.get("pre"):
        L += ["### The day before a cross-venue listing (not tradable on the alert)", "",
              "| venue | n | mean excess | median excess | hit |", "|---|---|---|---|---|"]
        for venue, s in res["pre"].items():
            L.append(f"| {venue} | {s.get('n', 0)} | {pct(s.get('mean'))} | {pct(s.get('median'))} | "
                     f"{s.get('hit', float('nan')) * 100:.0f} % |")
        L.append("")
    L += ["### Buy every new Alpaca listing and hold N days", "",
          f"{res['n']['C']} listings since the launch batch. Too few to test anything; this table is what it would "
          "have made, not evidence.", ""] + alpaca_table(res["rows_c"]) + [""]
    L += ["### Out of sample by year (each pick)", "", "| pick | year | n | mean excess | hit |", "|---|---|---|---|---|"]
    for fam, k in res["picks"].items():
        if k:
            for y, s in res["cells"][k]["oos_years"].items():
                L.append(f"| {k} | {y} | {s.get('n', 0)} | {pct(s.get('mean'))} | {s.get('hit', float('nan')) * 100:.0f} % |")
    p.write_text(head + "\n".join(L) + "\n", encoding="utf-8")


def headline(res: dict) -> str:
    v = res["verdict"]
    parts = []
    for fam, k in res["picks"].items():
        if k:
            o = res["cells"][k]["oos"]
            parts.append(f"{k}: {o.get('n', 0)} events out of sample, mean {pct(o.get('mean'))} vs BTC")
    s = "; ".join(parts)
    return ("Rule passes: paper book on new Alpaca listings. " if v["passed"] else "No rule passes, alerts only. ") + s + "."


def save_report(res: dict) -> None:
    d = REPORTS / "listing_effect"
    d.mkdir(parents=True, exist_ok=True)
    slim = {k: v for k, v in res.items() if not k.startswith("rows")}
    slim["verdict_text"] = headline(res)
    out = {"generated": res["generated"], "verdict": headline(res), "passed": res["verdict"]["passed"],
           "rule": res["verdict"]["rule"], "reasons": res["verdict"]["reasons"], "detail": slim}
    tmp = d / "latest.json.tmp"
    tmp.write_text(json.dumps(out, indent=1, default=float))
    os.replace(tmp, d / "latest.json")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def analyse(first: dict[str, Series], latest: dict[str, Series], btc: Series, now_us: int,
            cb: dict[str, int], kr: dict[str, int], alp: dict[str, int], missing: list[str]) -> dict:
    rows_a = family_a(first, btc, now_us)
    rows_b = (cross_rows("B", "coinbase", cb, first, latest, btc, now_us)
              + cross_rows("B", "kraken", kr, first, latest, btc, now_us))
    rows_c = cross_rows("C", "alpaca", drop_launch(alp), first, latest, btc, now_us)
    all_cells = {**cells(rows_a, "A"), **cells(rows_b, "B"), **cells(rows_c, "C")}
    picks = {f: pick({k: c for k, c in all_cells.items() if c["family"] == f}) for f in ("A", "B", "C")}
    v = verdict(all_cells, picks)
    pre = {}
    for venue in ("coinbase", "kraken"):
        rr = [r for r in rows_b if r["venue"] == venue]
        if rr:
            pre[venue] = summarize(rr, 1, "preexcess")
    return {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "data_to": day(min(btc.end, now_us)), "cells": all_cells, "picks": picks, "verdict": v, "pre": pre,
            "missing": missing,
            "n": {"A": len({r["symbol"] for r in rows_a}), "B": len(rows_b),
                  "B_coinbase": sum(r["venue"] == "coinbase" for r in rows_b),
                  "B_kraken": sum(r["venue"] == "kraken" for r in rows_b), "C": len(rows_c)},
            "rows_a": rows_a, "rows_b": rows_b, "rows_c": rows_c}


def load_lake() -> tuple[dict[str, Series], dict[str, Series], Series]:
    syms = json.loads((ROOT / "hist" / "universe.json").read_text(encoding="utf-8"))
    first, latest = {}, {}
    for i, s in enumerate(syms):
        if not s.endswith("USDT") or not s.isascii():
            continue
        segs = lake_series(s)
        if not segs:
            continue
        first[s], latest[s] = segs[0], segs[-1]
        if i % 200 == 0:
            print(f"  lake {i}/{len(syms)}", flush=True)
    btc = latest["BTCUSDT"]
    return first, latest, btc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="W6 listing-effect study")
    ap.add_argument("--offline", action="store_true", help="family A only, no network")
    a = ap.parse_args(argv)
    print("listings: reading the lake", flush=True)
    first, latest, btc = load_lake()
    now_us = int(time.time() * 1e6)
    bases = {s[:-4] for s in first}
    missing: list[str] = []
    cb = kr = alp = {}
    if a.offline:
        missing.append("B and C (run offline)")
    else:
        for name, fn in (("Coinbase listing dates", lambda: coinbase_first(bases)),
                         ("Kraken listing dates", lambda: kraken_first(bases)),
                         ("Alpaca listing dates", alpaca_first)):
            try:
                got = fn()
            except Exception as e:  # noqa: BLE001 - one venue down leaves the rest of the study
                got = {}
                missing.append(f"{name} ({type(e).__name__})")
            if name.startswith("Coinbase"):
                cb = got
            elif name.startswith("Kraken"):
                kr = got
            else:
                alp = got
    res = analyse(first, latest, btc, now_us, cb, kr, alp, missing)
    write_results(res)
    save_report(res)
    print(headline(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
