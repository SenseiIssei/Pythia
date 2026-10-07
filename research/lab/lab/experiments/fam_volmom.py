"""Family 2: time-series momentum on the survivorship-free universe, with and without
volatility management of the whole book.

The base book is the existing candidate's rule (tsmom.py: hold a coin while its
28-day return is positive, each held coin sized to 40 % annual vol over the
number of slots, total capped at 100 %, daily) moved from today's 20 survivors
to the N most liquid coins OF EACH DAY. That alone answers whether the
candidate's edge was survivorship. Lookback and per-coin vol target are
carried over from the earlier lab rounds, not tuned again.

Vol management (Barroso and Santa-Clara 2015, Moreira and Muir 2017): scale the
whole book by its own recent volatility, measured on the unscaled book's daily
returns up to the decision close.
  invvol L   scale = 25 % / (book vol over the last L days), L = 20 or 60
  invvar     scale = c / (book variance over the last 20 days), c fitted in sample
             so the average scale over 2020 to 2023 is 1
Scale capped at 3x and the book at 100 % invested (no leverage).

Grid (16 variants): universe top 20 / top 50 · regime filter off / on ·
scaling none / invvol 20 / invvol 60 / invvar.
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc

FAMILY = "volmom"
LOOKBACK = 28
COIN_VOL = 0.40
UNIVERSES = {"top 20": 20, "top 50": 50}
SCALINGS = ["none", "invvol 20", "invvol 60", "invvar 20"]
BOOK_VOL = 0.25
MAX_SCALE = 3.0


def base_weights(P: fc.Panel, n: int, regime: bool, lookback: int = LOOKBACK) -> np.ndarray:
    uni = P.top_liquid(n)
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[lookback:] = P.px[lookback:] / P.px[:-lookback] - 1
    held = uni & np.isfinite(past) & (past > 0)
    W = fc.vol_sized(P, held, COIN_VOL, uni.sum(1))
    if regime:
        W = W * P.btc_on[:, None]
    return W


def scale_series(book: np.ndarray, how: str, ins: np.ndarray) -> np.ndarray:
    """Scale decided at the close of day t from book returns up to and including day t."""
    kind, L = how.split()
    L = int(L)
    var = fc.rolling(book[:, None] ** 2, L, int(L * 0.8))[:, 0]  # mean-zero variance, robust for short windows
    with np.errstate(invalid="ignore", divide="ignore"):
        if kind == "invvol":
            s = BOOK_VOL / np.sqrt(var * 365)
        else:
            inv = 1 / var
            c = 1 / np.nanmean(inv[ins & np.isfinite(inv) & (book != 0)])
            s = c * inv
    return np.clip(np.nan_to_num(s, nan=0.0, posinf=MAX_SCALE), 0, MAX_SCALE)


def variants(P: fc.Panel) -> list[fc.Result]:
    ins, _ = fc.masks(P)
    out = []
    for (uname, n), regime in itertools.product(UNIVERSES.items(), (False, True)):
        Wb = base_weights(P, n, regime)
        base = fc.run(P, FAMILY, "spot long-only", "", Wb, start=60)
        for how in SCALINGS:
            name = f"tsmom 28d · {uname}" + (" · regime" if regime else "") + f" · {how}"
            if how == "none":
                out.append(fc.Result(FAMILY, "spot long-only", name, base.gross, base.turnover, base.long_expo,
                                     base.short_expo))
                continue
            s = scale_series(base.gross, how, ins)
            W = Wb * s[:, None]
            tot = W.sum(1, keepdims=True)
            W = np.where(tot > 1, W / np.maximum(tot, 1e-12), W)
            out.append(fc.run(P, FAMILY, "spot long-only", name, W, start=60))
    return out


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
