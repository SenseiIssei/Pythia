"""EXPERIMENTAL paper books on the six memecoins Alpaca lists. No real money.

    python -m lab.paper.memes              step both books and write their engine signals
    python -m lab.paper.memes --dry-run    print targets, signals and evidence; write nothing

Both rules come from W7 (results/memecoins.md) and both FAILED the lab's bar;
they run as experiments because the owner wants more risk and more activity
on paper (see lab.paper.experimental and results/experiments.md):

  memes_rotation   the top 1 of DOGE SHIB PEPE BONK WIF TRUMP by 28-day return,
                   only while that return is above 0 and BTC is above its
                   200-day average; sized at 40 % annual vol (at most all of
                   the sleeve). W7's near miss: 1.15 out of sample at 35 bps,
                   deflated p 0.01.
  memes_tsmom      each of the six held while its 28-day return is above 0,
                   BTC gate, 40 % vol over 6 slots (at most 1/6 each). W7's
                   pre-registered pick: 0.67, below BTC's 0.74.

The panel is W7's own (Binance daily klines from data.binance.vision through
lab.klines_daily, the same build_panel), and the weights come from W7's
rotation() and trend(), so the books hold exactly what the study's rules hold.
When the archive has not published yesterday's daily file yet, the last days
are topped up from Binance's public klines endpoint.

Paper fills: live Binance touch plus Alpaca's 25 bps taker fee (the route the
engine would use), the study's 35 bps per unit of turnover journaled next to
it. Engine signals: <data>/signals/<book>/latest.json, marked experimental and
autopilot_only, restricted to coins the Alpaca demo route can trade (the
Alpaca list intersected with the engine's universe); anything else is named
in "dropped" and stays cash. Runs daily after the backfill, see
research/ops/jobs.yaml (paper-memes).

Per book: <data>/paper/<book>/state.json and journal.csv
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np
import polars as pl

from .. import universe as uni
from ..experiments import fam_common as fc
from ..experiments import memecoins as w7
from . import experimental as ex
from .families import step
from .tsmom import live_quotes, save_signal

NAMES = ("memes_rotation", "memes_tsmom")
SYMBOLS = ("BTCUSDT",) + tuple(f"{b}USDT" for b in w7.ALPACA_MEMES)
ALPACA_TAKER = 0.0025
MODEL_COST = 0.0035
SIGNAL_VALID_MS = 36 * 3600 * 1000
KLINES = ("https://data-api.binance.vision", "https://api.binance.com")


def tradable() -> frozenset[str]:
    """Coins the Alpaca demo route can trade: Alpaca's list within the engine's universe."""
    return frozenset(uni.ALPACA) & frozenset(uni.engine_coins())


def rest_days(symbol: str, now_ms: int, limit: int = 5) -> pl.DataFrame:
    """The last few finished daily bars from Binance's public klines endpoint."""
    last: Exception | None = None
    for h in KLINES:
        try:
            req = urllib.request.Request(f"{h}/api/v3/klines?symbol={symbol}&interval=1d&limit={limit}",
                                         headers={"User-Agent": "pythia-lab"})
            with urllib.request.urlopen(req, timeout=20) as r:
                rows = json.load(r)
            break
        except (OSError, ValueError) as e:
            last = e
    else:
        raise last if last else RuntimeError("no Binance host")
    rows = [k for k in rows if int(k[6]) < now_ms]
    return pl.DataFrame({
        "day": [int(k[0]) * 1000 for k in rows], "open": [float(k[1]) for k in rows],
        "high": [float(k[2]) for k in rows], "low": [float(k[3]) for k in rows],
        "close": [float(k[4]) for k in rows], "volume": [float(k[5]) for k in rows],
        "qv": [float(k[7]) for k in rows], "n": [int(k[8]) for k in rows], "taker_qv": [float(k[10]) for k in rows],
    }, schema=w7.klines_daily.empty().schema)


def load_panel(now_ms: int) -> fc.Panel:
    frames = w7.load_frames(SYMBOLS)
    for s in SYMBOLS:
        try:
            top = rest_days(s, now_ms)
        except (OSError, ValueError, RuntimeError) as e:
            print(f"  {s}: no top-up ({type(e).__name__})", file=sys.stderr)
            continue
        if top.height:
            old = frames.get(s, w7.klines_daily.empty())
            frames[s] = pl.concat([old, top], how="vertical_relaxed").unique("day", keep="first").sort("day")
    return w7.build_panel(frames)


def targets(P: fc.Panel) -> dict[str, np.ndarray]:
    """Both books' weight matrices, with W7's own functions on universe A."""
    A = P.eligible & w7.member(P, w7.ALPACA_MEMES)[None, :]
    return {"memes_rotation": w7.rotation(P, A, 1), "memes_tsmom": w7.trend(P, A, 28, True)}


def signal(name: str, P: fc.Panel, W: np.ndarray, t: int, now_us: int, coins: frozenset[str] | None = None) -> dict:
    """The engine signal: W[t] on the coins the demo route can trade, marked experimental."""
    coins = tradable() if coins is None else coins
    weights, dropped = {}, {}
    for j in np.flatnonzero(np.nan_to_num(W[t]) > 0):
        coin, x = fc.base_of(P.names[j]), float(W[t, j])
        if coin in coins:
            weights[coin] = round(x, 6)
        else:
            dropped[coin] = dropped.get(coin, 0.0) + x
    sig = {
        "strategy": name,
        "variant": ex.BOOKS[name]["variant"],
        "as_of_ms": int(P.days[t]) // 1000,
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": weights,
        "regime_on": bool(P.btc_on[t]),
        "evidence": ex.evidence(name),
        "dropped": sorted(dropped),
        "dropped_weight": round(sum(dropped.values()), 6),
        "lab_exposure": round(float(np.nan_to_num(W[t]).sum()), 6),
        "cadence": "daily",
    }
    return ex.mark(sig, name)


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    dry = "--dry-run" in sys.argv
    P = load_panel(now_us // 1000)
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not dry:
            print(f"history ends {ends}, yesterday is missing; not rebalancing on stale data", file=sys.stderr)
            return 1
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    W = targets(P)
    quotes = {} if dry else live_quotes(list(SYMBOLS[1:]))
    for name, w in W.items():
        sig = signal(name, P, w, t, now_us)
        if dry:
            print(name, "BTC above 200d" if P.btc_on[t] else "BTC below 200d", json.dumps(sig["weights"]))
            print(name, "evidence", json.dumps({k: sig["evidence"].get(k) for k in (
                "oos_sharpe", "sharpe_2x_cost", "deflated_p", "variants_tried", "oos_sharpe_survivorship_free",
                "verdict", "missing")}))
            continue
        row = step(name, w[t], P, t, quotes, now_us, w[t], label=ex.BOOKS[name]["variant"],
                   taker=ALPACA_TAKER, model=MODEL_COST)
        save_signal(name, sig, now_us)
        print(name, json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
