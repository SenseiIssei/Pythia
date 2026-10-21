"""Taker order-flow imbalance across perpetuals: abnormal taker buying, long/short.

    PYTHIA_CACHE=<study folder with the xs_daily panel> python -m lab.experiments.taker_imbalance_xs

Pre-registered in results/taker_imbalance_xs_prereg.md (committed before this file ran).
From the USD-M daily klines (taker buy volume over volume, base asset) of the day's perp:
A1 = the day's share minus its mean over the previous 90 days, A7 = the 7-day share minus
the mean daily share of the 90 days before that window. Continuation: long the highest,
short the lowest among the 100 most liquid perps (xs_daily.book), funding paid and
received, Kraken Futures costs, the residual after the low-vol book and BTC judged from
2024 (funding_carry's machinery, round_two). Writes results/taker_imbalance_xs.md below
the marker and <reports>/taker_imbalance_xs/latest.*.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import numpy as np
import polars as pl

from .. import report
from ..data import ROOT
from . import director_common as dc
from . import fam_common as fc
from . import round_two as r2

NAME = "taker_imbalance_xs"
SEL_FROM, FIT_FROM, FIT_TO = "2020-08-01", "2022-01-01", "2023-12-31"
WINDOW, MIN_OBS = 90, 60
VARIANTS = [(f"{s} · {k}/{k} · " + {1: "daily", 3: "3-day tranches", 7: "weekly tranches"}[h], f"s_{s}", k, h)
            for s in ("A1", "A7") for k in (10, 20) for h in (1, 3, 7)]


def abnormal(share: np.ndarray, buy: np.ndarray, vol: np.ndarray) -> dict[str, np.ndarray]:
    """A1 and A7 on a gap-free calendar (column vectors); share = buy / vol per day."""
    lag1 = np.full_like(share, np.nan)
    lag1[1:] = share[:-1]
    lag7 = np.full_like(share, np.nan)
    lag7[7:] = share[:-7]
    s7 = r2.roll(buy, 7, 7, how="sum") / r2.roll(vol, 7, 7, how="sum")
    a1 = share - r2.roll(lag1, WINDOW, MIN_OBS)
    a7 = s7 - r2.roll(lag7, WINDOW, MIN_OBS)
    return {"s_A1": a1, "s_A7": a7}


def flows(arrs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    vol = np.where(arrs["volume"] > 0, arrs["volume"], np.nan)
    buy = np.where(np.isfinite(vol), arrs["taker_buy_volume"], np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        return abnormal(buy / vol, buy, vol)


def perp_klines(symbols: list[str]) -> pl.DataFrame:
    def one(s: str) -> pl.DataFrame | None:
        files = sorted((ROOT / "hist" / "binance_um" / "klines_1d" / f"symbol={s}").glob("*.parquet"))
        if not files:
            return None
        k = (pl.concat([pl.read_parquet(f, columns=["open_time_us", "volume", "taker_buy_volume"]) for f in files],
                       how="vertical_relaxed").unique("open_time_us").sort("open_time_us"))
        return k.select(day=(pl.col("open_time_us") // fc.DAY_US) * fc.DAY_US, volume="volume",
                        taker_buy_volume="taker_buy_volume").with_columns(perp=pl.lit(s))

    with ThreadPoolExecutor(8) as ex:
        frames = [f for f in ex.map(one, symbols) if f is not None]
    return pl.concat(frames, how="vertical_relaxed")


def spot_abnormal(P: pl.DataFrame) -> pl.DataFrame:
    """The panel's spot taker share (taker1, taker7 = share - 0.5) made abnormal the same way,
    per coin segment (rows are consecutive days): information only."""
    t1 = pl.col("taker1")
    return P.sort(["symbol", "day"]).with_columns(
        s_spotA1=(t1 - t1.shift(1).rolling_mean(WINDOW, min_samples=MIN_OBS)).over("symbol"),
        s_spotA7=(pl.col("taker7") - t1.shift(7).rolling_mean(WINDOW, min_samples=MIN_OBS)).over("symbol"),
    ).sort(["day", "symbol"])


def main() -> None:
    from . import xs_daily as xs
    perps = sorted(set(xs.build_panel().select(pl.col("perp").drop_nulls().unique())["perp"].to_list()))
    k = perp_klines(perps)
    sig = r2.per_perp(k, ["volume", "taker_buy_volume"], flows)
    cols = ["s_A1", "s_A7"]
    M, fund_end = r2.load_matrices(sig, cols + ["s_spotA1", "s_spotA7"], extra=spot_abnormal)
    print("matrices ready", flush=True)
    res = r2.perp_study(M, fund_end, VARIANTS, SEL_FROM, FIT_FROM, FIT_TO,
                        {c: M[c] for c in cols + ["s_spotA1", "s_spotA7"]})
    res["perps_with_klines"] = int(sig["perp"].n_unique())
    write(res)


def write(res: dict) -> None:
    intro = (f"Order flow from the USD-M daily klines of the day's perp ({res['perps_with_klines']} perps): the taker "
             "buy share of volume, A1 = the day's share minus its mean over the previous 90 days, A7 = the 7-day share "
             "minus the mean daily share of the 90 days before; score = +A (continuation). `s_spotA1` and `s_spotA7` "
             "in the IC table are the same from the spot hourly klines already in the panel (information only).")
    text = r2.perp_markdown("Taker order-flow imbalance across perpetuals", "taker_imbalance_xs_prereg.md", intro, res)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
