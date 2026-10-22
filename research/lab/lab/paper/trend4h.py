"""EXPERIMENTAL paper book: 4h trend with pullback entries on the Alpaca coins. No real money.

    python -m lab.paper.trend4h              one run (hourly from cron): fills, exits, decisions, signal
    python -m lab.paper.trend4h --dry-run    the same, printed; nothing written

The only W15 family that paid (results/fast_maker.md), its in-sample pick
"B EMA 24/96 · p 0.5 · W 1h · BTC gate": 0.71 out of sample with resting maker
fills, 0.51 filled at the close at taker cost, BTC 0.74, deflated p 0.00 over
841 trials. It FAILED the bar and runs as an experiment (lab.paper.experimental,
results/experiments.md).

The rule, as the study simulated it on 1h bars:

- Trend: on 4h bars (closing 00, 04, ... 20 UTC) the 24-bar EMA of the close
  above the 96-bar EMA, and BTC's last daily close above its 200-day average.
- Entry: at every 4h close while the trend is on and the coin is flat, a buy
  limit at close x (1 - 0.5 x 4h vol) (4h vol: RMS of the 180 4h returns before
  the bar) resting in the next hour only. It fills only where the hour's low
  trades at least 1 bp through it, a share of depth / 10 bps (all at 10 bps or
  more), never more than 10 % of the hour's quote volume, at the limit. A
  missed entry stays missed; the next 4h close may place a new one.
- Size: min(40 % / (hourly vol x sqrt(8760)), 1) / 10 of the book (hourly vol
  over the 720 hours before the last hour), times the share filled. An entry
  that would take the book's open targets above 100 % is skipped; entries of
  one 4h close are queued by 28-day quote volume, largest first.
- Exit: at the first 4h close where the trend or the BTC gate is off, a sell
  limit at the hour's close, re-placed every hour at the latest close, filled
  by the same trade-through rule on the hour's high; whatever is left 24 hours
  after the exit decision is sold at the close at taker cost (35 bps).
- Costs: every maker fill pays 15 bps (Alpaca's maker fee) and is booked 3 bps
  worse (adverse selection).
- Coins: the study's 33 (Alpaca's list without stablecoins), on Binance USDT
  spot bars from the public klines endpoint (no key), eligible from 60 days of
  history and 1 M USD of daily quote volume over 28 days.

The book starts flat; it does not take over the backtest's open trades.

Engine signal (<data>/signals/trend4h_pullback/latest.json): the book's
holdings as weights of its equity, restricted to coins the Alpaca demo route
can trade, marked experimental and autopilot_only, valid 3 hours. A new signal
(new generated_ms, which the engine trades once) is written only when the
holdings changed, by an entry fill or an exit decision; between changes the
file keeps its weights and generated_ms and only its validity moves on, so the
engine does not chase drift every hour. The engine enters AFTER the paper
book's pullback limit filled, at its own maker price on the Alpaca route: its
fills differ from the paper book's, which the forward report shows.

Data: <data>/paper/trend4h_pullback/state.json, journal.csv (one row per UTC
day, rewritten through the day), trades.csv (every fill).
"""

from __future__ import annotations

import csv
import json
import math
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .. import universe as uni
from ..data import ROOT, WRITE_ROOT
from . import experimental as ex

NAME = "trend4h_pullback"
HOSTS = ("https://data-api.binance.vision", "https://api.binance.com")
# The study's 33 coins (fast_maker.SYMBOLS), by their current Binance USDT symbol.
COINS = ("AAVE", "ADA", "ARB", "AVAX", "BAT", "BCH", "BONK", "BTC", "CRV", "DOGE", "DOT", "ETH", "FIL", "GRT", "HYPE",
         "LDO", "LINK", "LTC", "ONDO", "PAXG", "PEPE", "POL", "RENDER", "SHIB", "SKY", "SOL", "SUSHI", "TRUMP", "UNI",
         "WIF", "XRP", "XTZ", "YFI")

HOUR_MS = 3_600_000
H4_MS = 4 * HOUR_MS
DAY_MS = 24 * HOUR_MS
START_EQUITY = 10_000.0
EMA_FAST, EMA_SLOW = 24, 96
PULL = 0.5                  # p: the limit sits p 4h vols under the close
WINDOW_H = 1                # W: the entry rests one hour
VOL4_BARS, VOL4_MIN = 180, 144
VOLH, VOLH_MIN = 720, 576
COIN_VOL, SLOTS = 0.40, 10
MIN_AGE_D, MIN_ADV = 60, 1_000_000.0
THROUGH, FULL_DEPTH, VOL_CAP = 1e-4, 10e-4, 0.10
MAKER_FEE, HAIRCUT, TAKER = 15e-4, 3e-4, 35e-4
FALLBACK_H = 24
SIGNAL_VALID_MS = 3 * HOUR_MS

Fetch = Callable[[str], object]


def http_json(url: str, timeout: float = 20):
    req = urllib.request.Request(url, headers={"User-Agent": "pythia-lab", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def klines(get: Fetch, symbol: str, interval: str, limit: int, now_ms: int) -> dict[str, np.ndarray] | None:
    """Finished bars only: open_ms, high, low, close, qv. None when no host has the symbol."""
    rows = None
    for h in HOSTS:
        try:
            rows = get(f"{h}/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}")
            break
        except urllib.error.HTTPError as e:
            if e.code == 400:            # unknown symbol: not on Binance
                return None
        except (OSError, ValueError):
            continue
    if not isinstance(rows, list):
        return None
    rows = [k for k in rows if int(k[6]) < now_ms]
    if not rows:
        return None
    col = lambda i: np.array([float(k[i]) for k in rows])  # noqa: E731
    return {"open_ms": np.array([int(k[0]) for k in rows], dtype=np.int64), "high": col(2), "low": col(3),
            "close": col(4), "qv": col(7)}


def ema(x: np.ndarray, span: int) -> np.ndarray:
    a = 2 / (span + 1)
    out = np.empty_like(x)
    cur = x[0]
    for i, v in enumerate(x):
        cur = v if i == 0 else cur + a * (v - cur)
        out[i] = cur
    return out


def rms_before(r: np.ndarray, end: int, w: int, min_obs: int) -> float:
    """RMS of the w values of r before index `end` (finite ones, at least min_obs)."""
    x = r[max(0, end - w):end]
    x = x[np.isfinite(x)]
    return float(np.sqrt(np.mean(x * x))) if len(x) >= min_obs else float("nan")


def btc_gate(d1: dict | None, at_ms: int) -> bool:
    """BTC's last daily close at or before at_ms above its 200-day average."""
    if d1 is None:
        return False
    close_ms = d1["open_ms"] + DAY_MS
    k = np.flatnonzero(close_ms <= at_ms)
    if len(k) == 0 or k[-1] < 199:
        return False
    i = int(k[-1])
    return bool(d1["close"][i] > d1["close"][i - 199:i + 1].mean())


def coin_state(h1: dict | None, h4: dict | None, at_ms: int) -> dict | None:
    """Everything the rule needs about one coin at the 4h close at_ms, or None."""
    if h1 is None or h4 is None:
        return None
    k4 = np.flatnonzero(h4["open_ms"] + H4_MS <= at_ms)
    if len(k4) < EMA_SLOW:
        return None
    k = int(k4[-1])
    if int(h4["open_ms"][k]) + H4_MS != at_ms:
        return None                                  # no bar closing at this 4h close
    c4 = h4["close"][: k + 1]
    r4 = np.r_[np.nan, c4[1:] / c4[:-1] - 1]
    sig4 = rms_before(r4, k, VOL4_BARS, VOL4_MIN)
    on = bool(ema(c4, EMA_FAST)[-1] > ema(c4, EMA_SLOW)[-1])
    kh = np.flatnonzero(h1["open_ms"] + HOUR_MS <= at_ms)
    if len(kh) == 0:
        return None
    hc = h1["close"][: int(kh[-1]) + 1]
    hr = np.r_[np.nan, hc[1:] / hc[:-1] - 1]
    sig_h = rms_before(hr, len(hr) - 1, VOLH, VOLH_MIN)        # hours up to the one before the last
    # Eligibility from full UTC days before the decision's day.
    day0 = (at_ms // DAY_MS) * DAY_MS
    m = (h4["open_ms"] >= day0 - 28 * DAY_MS) & (h4["open_ms"] < day0)
    days = len(set((h4["open_ms"][m] // DAY_MS).tolist()))
    adv = float(h4["qv"][m].sum() / days) if days >= 20 else 0.0
    age_d = (at_ms - int(h4["open_ms"][0])) / DAY_MS
    # With 1000 4h bars a coin shows at most about 166 days; fewer bars means a young coin.
    eligible = age_d >= MIN_AGE_D and adv >= MIN_ADV
    return {"on": on, "close4": float(c4[-1]), "sig4": sig4, "sig_h": sig_h, "adv": adv, "eligible": eligible}


def target_of(sig_h: float) -> float:
    if not math.isfinite(sig_h) or sig_h <= 0:
        return 0.0
    return min(COIN_VOL / (sig_h * math.sqrt(8760)), 1.0) / SLOTS


def through_share(depth: float) -> float:
    """Share of a resting limit filled when the price went `depth` (fraction) through it."""
    if not math.isfinite(depth) or depth < THROUGH - 1e-12:
        return 0.0
    return min(1.0, depth / FULL_DEPTH)


def bar_at(h1: dict | None, open_ms: int) -> int | None:
    if h1 is None:
        return None
    k = np.flatnonzero(h1["open_ms"] == open_ms)
    return int(k[0]) if len(k) else None


# ---------------------------------------------------------------- the book

def new_state(now_ms: int) -> dict:
    return {"variant": ex.BOOKS[NAME]["variant"], "started": datetime.fromtimestamp(now_ms / 1000, timezone.utc)
            .isoformat(timespec="seconds"), "cash": START_EQUITY, "positions": {}, "pending": {}, "exits": {},
            "marks": {}, "last_decision_ms": 0, "signal": None, "day": None}


def equity_of(st: dict) -> float:
    held = sum(p["qty"] * st["marks"].get(c, p["entry"]) for c, p in st["positions"].items())
    leaving = sum(x["qty"] * st["marks"].get(c, x["entry"]) for c, x in st["exits"].items())
    return st["cash"] + held + leaving


def _book_day(st: dict, now_ms: int, notional: float, cost: float, model: float) -> None:
    day = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")
    d = st.get("day")
    if not d or d.get("date") != day:
        d = st["day"] = {"date": day, "notional": 0.0, "cost": 0.0, "model": 0.0, "fills": 0, "start": equity_of(st)}
    d["notional"] += notional
    d["cost"] += cost
    d["model"] += model
    d["fills"] += 1 if notional > 0 else 0


def process_entries(st: dict, h1s: dict, now_ms: int, trades: list) -> None:
    """Fill or cancel every pending entry whose resting hour has closed."""
    for coin, o in list(st["pending"].items()):
        end = o["window_ms"] + WINDOW_H * HOUR_MS
        if end > now_ms:
            continue                                     # still resting
        h1 = h1s.get(coin)
        got = 0.0
        for h in range(WINDOW_H):
            i = bar_at(h1, o["window_ms"] + h * HOUR_MS)
            if i is None:
                continue
            L = o["limit"]
            share = through_share((L - h1["low"][i]) / L)
            if o["usd"] > 0:
                share = min(share, VOL_CAP * h1["qv"][i] / o["usd"])
            got = max(got, share)
        del st["pending"][coin]
        if got <= 1e-12:
            trades.append({"ts_ms": end, "coin": coin, "side": "buy", "qty": 0.0, "price": o["limit"],
                           "kind": "missed", "cost_usd": 0.0})
            continue
        usd = o["usd"] * got
        qty = usd / o["limit"]
        cost = usd * (MAKER_FEE + HAIRCUT)
        st["cash"] -= usd + cost
        st["positions"][coin] = {"qty": qty, "entry": o["limit"], "entry_ms": end, "target": o["target"] * got,
                                 "share": got}
        st["marks"].setdefault(coin, o["limit"])
        _book_day(st, now_ms, usd, cost, usd * (MAKER_FEE + HAIRCUT))
        trades.append({"ts_ms": end, "coin": coin, "side": "buy", "qty": qty, "price": o["limit"], "kind": "maker",
                       "cost_usd": cost})


def process_exits(st: dict, h1s: dict, now_ms: int, trades: list) -> None:
    """Work every exit hour by hour: a sell limit at the last close, re-placed each hour,
    the rest at taker cost 24 hours after the decision (or when the data ends)."""
    for coin, x in list(st["exits"].items()):
        h1 = h1s.get(coin)
        while x["qty"] > 1e-15 and x["next_ms"] + HOUR_MS <= now_ms and x["next_ms"] < x["deadline_ms"]:
            i, prev = bar_at(h1, x["next_ms"]), bar_at(h1, x["next_ms"] - HOUR_MS)
            if i is not None and prev is not None:
                L = float(h1["close"][prev])
                share = through_share((h1["high"][i] - L) / L)
                usd_left = x["qty"] * L
                if usd_left > 0:
                    share = min(share, VOL_CAP * h1["qv"][i] / usd_left)
                if share > 1e-12:
                    q = x["qty"] * share
                    proceeds = q * L
                    cost = proceeds * (MAKER_FEE + HAIRCUT)
                    st["cash"] += proceeds - cost
                    x["qty"] -= q
                    _book_day(st, now_ms, proceeds, cost, proceeds * (MAKER_FEE + HAIRCUT))
                    trades.append({"ts_ms": x["next_ms"] + HOUR_MS, "coin": coin, "side": "sell", "qty": q, "price": L,
                                   "kind": "maker", "cost_usd": cost})
            x["next_ms"] += HOUR_MS
        if x["qty"] > 1e-15 and x["next_ms"] >= x["deadline_ms"]:
            i = bar_at(h1, x["deadline_ms"] - HOUR_MS)
            px = float(h1["close"][i]) if i is not None else st["marks"].get(coin, x["entry"])
            proceeds = x["qty"] * px
            cost = proceeds * TAKER
            st["cash"] += proceeds - cost
            _book_day(st, now_ms, proceeds, cost, proceeds * TAKER)
            trades.append({"ts_ms": x["deadline_ms"], "coin": coin, "side": "sell", "qty": x["qty"], "price": px,
                           "kind": "fallback", "cost_usd": cost})
            x["qty"] = 0.0
        if x["qty"] <= 1e-15:
            del st["exits"][coin]


def decide(st: dict, feats: dict[str, dict | None], gate: bool, at_ms: int) -> list[str]:
    """The 4h close at_ms: exits for held coins whose trend (or the gate) is off,
    pullback limits for flat coins whose trend is on. Returns what it did, in words."""
    did = []
    for coin, p in list(st["positions"].items()):
        f = feats.get(coin)
        if f is not None and f["on"] and gate:
            continue
        if f is None and coin in st["marks"]:
            # No bar for this close (a data gap): hold, as the backtest's forward-filled price would.
            continue
        st["exits"][coin] = {"qty": p["qty"], "entry": p["entry"], "decided_ms": at_ms, "next_ms": at_ms,
                             "deadline_ms": at_ms + FALLBACK_H * HOUR_MS}
        del st["positions"][coin]
        did.append(f"exit {coin}")
    if not gate:
        return did
    eq = equity_of(st)
    open_t = sum(p["target"] for p in st["positions"].values()) + sum(o["target"] for o in st["pending"].values())
    cands = [(c, f) for c, f in feats.items() if f and f["on"] and f["eligible"] and math.isfinite(f["sig4"])
             and c not in st["positions"] and c not in st["pending"] and c not in st["exits"]]
    for coin, f in sorted(cands, key=lambda cf: -cf[1]["adv"]):
        tgt = target_of(f["sig_h"])
        if tgt <= 0:
            continue
        if open_t + tgt > 1.0 + 1e-9:
            did.append(f"skip {coin} (book full)")
            continue
        limit = f["close4"] * (1 - PULL * f["sig4"])
        if not (limit > 0):
            continue
        st["pending"][coin] = {"limit": limit, "target": tgt, "usd": tgt * eq, "window_ms": at_ms, "decided_ms": at_ms}
        open_t += tgt
        did.append(f"bid {coin} at {limit:.6g}")
    return did


def tradable() -> frozenset[str]:
    return frozenset(uni.ALPACA) & frozenset(uni.engine_coins())


def holdings_signal(st: dict, now_ms: int, gate: bool, coins: frozenset[str] | None = None) -> dict:
    """The engine signal. Weights change (with a new generated_ms) only when the holdings do."""
    coins = tradable() if coins is None else coins
    eq = equity_of(st)
    weights, dropped = {}, []
    for c, p in sorted(st["positions"].items()):
        w = p["qty"] * st["marks"].get(c, p["entry"]) / eq if eq > 0 else 0.0
        if c in coins:
            weights[c] = round(w, 6)
        else:
            dropped.append(c)
    key = sorted((c, round(p["qty"], 12)) for c, p in st["positions"].items())
    prev = st.get("signal") or {}
    if prev.get("key") == key and prev.get("generated_ms"):
        generated, weights = prev["generated_ms"], prev["weights"]
    else:
        generated = now_ms
    st["signal"] = {"key": key, "generated_ms": generated, "weights": weights}
    sig = {
        "strategy": NAME,
        "variant": ex.BOOKS[NAME]["variant"],
        "as_of_ms": st.get("last_decision_ms") or now_ms,
        "generated_ms": generated,
        "valid_until_ms": now_ms + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": weights,
        "regime_on": gate,
        "evidence": ex.evidence(NAME),
        "dropped": dropped,
        "lab_exposure": round(sum(p["qty"] * st["marks"].get(c, p["entry"]) for c, p in st["positions"].items())
                              / eq, 6) if eq > 0 else 0.0,
        "cadence": "4h",
        "execution": "maker",
    }
    return ex.mark(sig, NAME)


def run(get: Fetch = http_json, now_ms: int | None = None, st: dict | None = None) -> tuple[dict, dict, list, list]:
    """One run on a state: fills, exits, the due 4h decision. Returns (state, signal, trades, words)."""
    now_ms = now_ms or int(time.time() * 1000)
    st = st or new_state(now_ms)
    h1s, h4s = {}, {}
    for c in COINS:
        sym = f"{c}USDT"
        h1s[c] = klines(get, sym, "1h", 1000, now_ms)
        h4s[c] = klines(get, sym, "4h", 1000, now_ms)
    d1 = klines(get, "BTCUSDT", "1d", 260, now_ms)
    _book_day(st, now_ms, 0.0, 0.0, 0.0)             # opens the day's record at the last marks
    trades: list = []
    process_entries(st, h1s, now_ms, trades)
    process_exits(st, h1s, now_ms, trades)
    # Marks: the latest finished hour.
    for c, h1 in h1s.items():
        if h1 is not None and len(h1["close"]):
            st["marks"][c] = float(h1["close"][-1])
    words: list[str] = []
    at = (now_ms // H4_MS) * H4_MS
    gate = btc_gate(d1, at)
    if at > st.get("last_decision_ms", 0):
        feats = {c: coin_state(h1s[c], h4s[c], at) for c in COINS}
        words = decide(st, feats, gate, at)
        st["last_decision_ms"] = at
        # An exit decided now may already have hours to work through (a late run).
        process_exits(st, h1s, now_ms, trades)
    _book_day(st, now_ms, 0.0, 0.0, 0.0)
    sig = holdings_signal(st, now_ms, gate)
    return st, sig, trades, words


def journal_row(st: dict) -> dict:
    eq = equity_of(st)
    d = st["day"]
    held = {c: round(p["qty"] * st["marks"].get(c, p["entry"]) / eq, 4) for c, p in st["positions"].items()} if eq else {}
    return {"date": d["date"], "equity": round(eq, 2),
            "gross_ret_pct": round(((eq + d["cost"]) / d["start"] - 1) * 100, 4) if d["start"] else 0.0,
            "paper_cost_bps": round(d["cost"] / max(d["start"], 1e-9) * 1e4, 2),
            "model_cost_bps": round(d["model"] / max(d["start"], 1e-9) * 1e4, 2),
            "turnover": round(d["notional"] / max(d["start"], 1e-9), 4),
            "exposure": round(sum(held.values()), 4), "held": len(held), "fills": d["fills"],
            "pending": len(st["pending"]), "exiting": len(st["exits"]), "weights": json.dumps(held)}


def write_journal(path: Path, row: dict) -> None:
    """One row per UTC day: today's row is replaced through the day."""
    rows = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    rows = [r for r in rows if r.get("date") != row["date"]] + [row]
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        wr.writeheader()
        for r in rows:
            wr.writerow({k: r.get(k, "") for k in row})
    tmp.replace(path)


def main() -> int:
    dry = "--dry-run" in sys.argv
    d = WRITE_ROOT / "paper" / NAME
    f = d / "state.json"
    st = json.loads(f.read_text()) if f.exists() else None
    st, sig, trades, words = run(st=st)
    if dry:
        print(json.dumps({"equity": round(equity_of(st), 2), "positions": st["positions"], "pending": st["pending"],
                          "exits": st["exits"], "did": words, "trades": trades}, indent=1, default=str))
        print("signal", json.dumps(sig["weights"]), "regime_on", sig["regime_on"])
        return 0
    from .tsmom import save_signal
    d.mkdir(parents=True, exist_ok=True)
    if trades:
        tp = d / "trades.csv"
        new = not tp.exists()
        with tp.open("a", newline="", encoding="utf-8") as fh:
            wr = csv.DictWriter(fh, fieldnames=list(trades[0]))
            if new:
                wr.writeheader()
            for t in trades:
                wr.writerow(t)
    write_journal(d / "journal.csv", journal_row(st))
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st, indent=1))
    tmp.replace(f)
    save_signal(NAME, sig, int(time.time() * 1000) * 1000)
    print(NAME, f"equity {equity_of(st):.2f}", "; ".join(words) or "no decision due", f"{len(trades)} fills")
    return 0


if __name__ == "__main__":
    sys.exit(main())
