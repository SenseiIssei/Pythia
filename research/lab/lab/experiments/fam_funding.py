"""Family 6: perpetual funding and open interest as timing signals for spot longs.

Funding is what leveraged longs pay shorts; when it is extreme the long side is
crowded. Two opposite stories, both tested:
  contrarian   buy the coin when funding is unusually LOW (shorts crowded, z < -1)
  trend        buy when funding is unusually HIGH (z > +1): demand persists
  not crowded  hold the coin except when funding is unusually high (z < +1)
z = 7-day summed funding against its own trailing mean and std over Z days
(Z = 90 or 180), all known at the decision close.

Open interest (5-minute metrics, only the 20 coins of the old fixed universe
from 2022 on, so this part is NOT survivorship-free and its in-sample period is
only two years):
  confirm      hold when open interest AND price both rose over the last h days
  capitulation hold when both fell (positions being closed into a drop)
  h = 3 or 7 days.

Each held coin is sized to 40 % annual vol over the number of slots, total
capped at 100 %, rebalanced daily, spot long-only.

Grid (16 variants): 3 funding rules x Z 90 / 180 x coins BTC+ETH / the 20 most
liquid coins that have a perpetual, plus 2 OI rules x h 3 / 7.
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc
from ..data import UNIVERSE

FAMILY = "funding"
ZWIN = [90, 180]
COIN_VOL = 0.40


def funding_z(P: fc.Panel, zwin: int) -> np.ndarray:
    has = P.perp_ok.astype(float)
    f7 = fc.rolling(np.where(P.perp_ok, P.funding, np.nan), 7, 5, how="sum")
    mu = fc.rolling(f7, zwin, int(zwin * 0.7))
    sd = np.sqrt(np.maximum(fc.rolling(f7 ** 2, zwin, int(zwin * 0.7)) - mu ** 2, 0))
    with np.errstate(invalid="ignore", divide="ignore"):
        z = (f7 - mu) / sd
    return np.where(has > 0, z, np.nan)


def variants(P: fc.Panel) -> list[fc.Result]:
    out = []
    majors = np.zeros((P.T, P.N), dtype=bool)
    majors[:, [P.col("BTCUSDT"), P.col("ETHUSDT")]] = True
    majors &= P.eligible
    sets = {"BTC+ETH": (majors, 2, "btc"), "top 20 with perp": (P.top_liquid(20, need_perp=True), 20, "ew")}
    for zwin, (sname, (uni, slots, bench)) in itertools.product(ZWIN, sets.items()):
        z = funding_z(P, zwin)
        with np.errstate(invalid="ignore"):
            rules = {"contrarian": z < -1, "trend": z > 1, "not crowded": z < 1}
        for rname, sig in rules.items():
            held = uni & np.nan_to_num(sig, nan=0).astype(bool)
            W = fc.vol_sized(P, held, COIN_VOL, slots)
            out.append(fc.run(P, FAMILY, f"funding · {sname}", f"funding {rname} · z {zwin}d · {sname}", W,
                              start=60, benchmark=bench, spot_only=True))
    oi = fc.oi_matrix(P)
    cols = [P.col(f"{b}USDT") for b in UNIVERSE]
    uni = np.zeros((P.T, P.N), dtype=bool)
    uni[:, cols] = True
    uni &= P.eligible & np.isfinite(oi)
    for h in (3, 7):
        doi = np.full_like(oi, np.nan)
        dpx = np.full_like(oi, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            doi[h:] = oi[h:] / oi[:-h] - 1
            dpx[h:] = P.px[h:] / P.px[:-h] - 1
            rules = {"confirm": (doi > 0) & (dpx > 0), "capitulation": (doi < 0) & (dpx < 0)}
        for rname, sig in rules.items():
            W = fc.vol_sized(P, uni & sig, COIN_VOL, len(cols))
            out.append(fc.run(P, FAMILY, "open interest · old 20", f"OI {rname} · {h}d · old 20 coins", W,
                              start=60, benchmark="ew", spot_only=True))
    return out


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
