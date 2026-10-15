"""The crypto universes the lab can trade, and how much history each coin has.

The engine quotes every coin of its configured universe (pythia-core
`coins.rs`, `PYTHIA_CRYPTO_UNIVERSE`); crypto demo orders go to the Alpaca
paper account. The lab's daily panel (experiments/fam_common.py) holds every
USDT pair Binance ever listed, so any of these universes is a selection from
it, never a different panel:

  LAB20     the lab's original 20 coins (data.UNIVERSE), the Kraken pairs table
  ALPACA15  the 15 of LAB20 the Alpaca paper account lists (C16)
  ALPACA    every coin the Alpaca paper account lists, stablecoins and gold
            left out (32)
  MEMES     the memecoins among them (DOGE, PEPE, BONK, SHIB, TRUMP, WIF)
  CORE      ALPACA without MEMES (26)
  ENGINE    the engine's default: ALPACA plus the five LAB20 coins Alpaca
            lacks (37)

A coin is its current Binance USDT ticker (BONK is BONKUSDT, PEPE is
PEPEUSDT). Renamed coins are not bridged: POL starts in 2024 (MATIC before),
RENDER in 2024 (RNDR before), so their history is short. A coin without a
Binance USDT pair (HYPE, ONDO, SKY when this was written) is simply absent
from the panel; `coverage` names it.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .data import UNIVERSE as LAB20_LIST

LAB20 = tuple(LAB20_LIST)
ALPACA15 = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "BCH", "UNI", "AAVE",
            "PEPE", "FIL")
ALPACA = ("AAVE", "ADA", "ARB", "AVAX", "BAT", "BCH", "BONK", "BTC", "CRV", "DOGE", "DOT", "ETH", "FIL", "GRT",
          "HYPE", "LDO", "LINK", "LTC", "ONDO", "PEPE", "POL", "RENDER", "SHIB", "SKY", "SOL", "SUSHI", "TRUMP",
          "UNI", "WIF", "XRP", "XTZ", "YFI")
MEMES = ("BONK", "SHIB", "WIF", "PEPE", "TRUMP", "DOGE")
CORE = tuple(c for c in ALPACA if c not in MEMES)
ENGINE = ALPACA + tuple(c for c in LAB20 if c not in ALPACA)
# What the Alpaca paper account lists besides: pegs and gold, never traded.
NOT_TRADED = ("USDC", "USDG", "USDT", "PAXG", "USD", "DAI", "USDS", "PYUSD", "FDUSD", "TUSD", "XAUT")

PRESETS = {"LAB20": LAB20, "ALPACA15": ALPACA15, "ALPACA": ALPACA, "ALPACA32": ALPACA, "MEMES": MEMES,
           "CORE": CORE, "DEFAULT": ENGINE, "ALL": ENGINE, "ENGINE": ENGINE}

# Short history: fewer eligible days than this before the out-of-sample split.
SHORT_HISTORY_DAYS = 365
SPLIT_DAY = "2024-01-01"


def parse(text: str) -> tuple[str, ...]:
    """Coins (bases) in a universe setting, in order, without repeats.

    The engine's format (`coins.rs` parse_universe): commas, spaces or new
    lines, `#` starts a comment; a token is a preset (lab20, alpaca15, alpaca,
    memes, core, default) or a coin (`BTC`, `BTC/USD`, `BTC-USD`, `BTCUSD`).
    Pegs, other quote currencies and anything that is not a plain ticker are
    skipped."""
    out: list[str] = []
    for line in text.splitlines():
        for tok in line.split("#")[0].replace(",", " ").split():
            t = tok.strip().upper()
            if t in PRESETS:
                out += [c for c in PRESETS[t] if c not in out]
                continue
            if "/" in t or "-" in t:
                b, _, q = t.replace("-", "/").partition("/")
                if q != "USD":
                    continue
            elif t.endswith(("USDT", "USDC")):
                continue
            else:
                b = t[:-3] if t.endswith("USD") and len(t) > 3 else t
            b = {"XBT": "BTC", "XDG": "DOGE"}.get(b, b)
            ok = 2 <= len(b) <= 10 and b[0].isascii() and b[0].isupper() and all(
                ch.isascii() and (ch.isupper() or ch.isdigit()) for ch in b)
            if ok and b not in NOT_TRADED and b not in out:
                out.append(b)
    return tuple(out)


def engine_coins(env: dict | None = None) -> tuple[str, ...]:
    """The coins the engine has live markets for: PYTHIA_CRYPTO_UNIVERSE, else the
    file named by PYTHIA_CRYPTO_UNIVERSE_FILE, else the default (ENGINE), read
    the way the engine reads them."""
    env = os.environ if env is None else env
    texts = [env.get("PYTHIA_CRYPTO_UNIVERSE")]
    f = env.get("PYTHIA_CRYPTO_UNIVERSE_FILE")
    if f:
        try:
            texts.append(Path(f).read_text(encoding="utf-8"))
        except OSError:
            pass
    for text in texts:
        if text:
            coins = parse(text)
            if coins:
                return coins
    return ENGINE


def named(name: str) -> tuple[str, ...]:
    """A universe by name (a preset, or a setting in the engine's format)."""
    coins = parse(name)
    if not coins:
        raise ValueError(f"no coins in universe {name!r}")
    return coins


# ---------------------------------------------------------------------------
# On the panel
# ---------------------------------------------------------------------------

def mask(P, coins) -> np.ndarray:
    """(N,) the panel columns of `coins`: their current Binance USDT segment only (a
    reused ticker's dead segments, `NAME~0`, are another asset)."""
    want = set(coins)
    return np.array([b in want and "~" not in n for b, n in zip(P.bases, P.names)], dtype=bool)


def _day(P, day: str) -> int:
    us = int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1e6)
    return int(np.searchsorted(P.days, us))


def _iso(P, t: int) -> str:
    return str(np.datetime64(int(P.days[t]), "us").astype("datetime64[D]"))


def coverage(P, coins, split: str = SPLIT_DAY) -> list[dict]:
    """Per coin: whether the panel has it, its first bar and first eligible day,
    eligible days before `split`, and the label the studies use:

      "none"   no Binance USDT history: cannot be tested
      "short"  fewer than SHORT_HISTORY_DAYS eligible days before the split: it
               may be chosen out of sample but shaped no in-sample choice
      "long"   otherwise
    """
    m = mask(P, coins)
    s = min(_day(P, split), P.T)
    out = []
    for c in coins:
        cols = [j for j in np.flatnonzero(m) if P.bases[j] == c]
        if not cols:
            out.append({"coin": c, "in_panel": False, "first_bar": None, "first_eligible": None,
                        "eligible_days_is": 0, "history": "none"})
            continue
        j = cols[0]
        bars = np.flatnonzero(P.traded[:, j])
        el = np.flatnonzero(P.eligible[:, j])
        n_is = int(P.eligible[:s, j].sum())
        out.append({"coin": c, "in_panel": True, "first_bar": _iso(P, bars[0]) if len(bars) else None,
                    "first_eligible": _iso(P, el[0]) if len(el) else None, "eligible_days_is": n_is,
                    "history": "long" if n_is >= SHORT_HISTORY_DAYS else "short"})
    return out
