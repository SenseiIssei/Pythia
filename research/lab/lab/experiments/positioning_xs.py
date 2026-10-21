"""Cross-sectional positioning on perpetuals: crowded against uncrowded, long/short.

    PYTHIA_CACHE=<study folder with the xs_daily panel> python -m lab.experiments.positioning_xs

Pre-registered in results/positioning_xs_prereg.md (committed before the metrics were
downloaded and before this file ran). Binance's daily futures metrics (lab.collect.um_metrics:
top traders' account and position ratios, the taker buy/sell ratio, open interest), each
input a z-score against the perp's own last 90 days; crowding = the mean of five z-scores;
long the least crowded, short the most crowded among the 100 most liquid perps
(xs_daily.book), funding paid and received, Kraken Futures costs, the residual after the
low-vol book and BTC judged from 2024 (funding_carry's machinery, round_two). Writes
results/positioning_xs.md below the marker and <reports>/positioning_xs/latest.*.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from .. import report
from ..collect import um_metrics
from . import director_common as dc
from . import round_two as r2

NAME = "positioning_xs"
SEL_FROM, FIT_FROM, FIT_TO = "2022-03-15", "2022-03-15", "2023-12-31"
WINDOW, MIN_OBS, CLIP = 90, 60, 5.0
COMPONENTS = ("z_acct", "z_pos", "z_taker", "z_oi3", "z_oi7")
VARIANTS = [(f"crowding · {k}/{k} · " + ("3-day tranches" if h == 3 else "weekly tranches"), "s_crowd", k, h)
            for k in (10, 20) for h in (3, 7)]


def signals(arrs: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """The five z-scores and the composite for one perp on a gap-free calendar."""
    lo = np.log(np.where(arrs["oi"] > 0, arrs["oi"], np.nan))
    g3, g7 = np.full_like(lo, np.nan), np.full_like(lo, np.nan)
    g3[3:], g7[7:] = lo[3:] - lo[:-3], lo[7:] - lo[:-7]
    z = {"z_acct": r2.zscore_own(arrs["top_acct"], WINDOW, MIN_OBS),
         "z_pos": r2.zscore_own(arrs["top_pos"], WINDOW, MIN_OBS),
         "z_taker": r2.zscore_own(arrs["taker"], WINDOW, MIN_OBS),
         "z_oi3": r2.zscore_own(g3, WINDOW, MIN_OBS),
         "z_oi7": r2.zscore_own(g7, WINDOW, MIN_OBS)}
    Z = np.clip(np.column_stack([z[c][:, 0] for c in COMPONENTS]), -CLIP, CLIP)
    crowd = np.where(np.isfinite(Z).all(1), Z.mean(1), np.nan)
    out = {f"s_{c[2:]}": -z[c][:, 0] for c in COMPONENTS}          # contrarian sign
    out["s_crowd"] = -crowd
    return out


def signal_frame() -> pl.DataFrame:
    m = um_metrics.load()
    if m.is_empty():
        raise SystemExit("no metrics stored: run python -m lab.collect.um_metrics first")
    return r2.per_perp(m.rename({"day_us": "day"}), ["oi", "top_acct", "top_pos", "taker"], signals)


def main() -> None:
    sig = signal_frame()
    cols = ["s_crowd"] + [f"s_{c[2:]}" for c in COMPONENTS]
    M, fund_end = r2.load_matrices(sig, cols)
    print("matrices ready", flush=True)
    res = r2.perp_study(M, fund_end, VARIANTS, SEL_FROM, FIT_FROM, FIT_TO, {c: M[c] for c in cols})
    res["perps_with_metrics"] = int(sig["perp"].n_unique())
    write(res)


def write(res: dict) -> None:
    intro = (f"Positioning from Binance's daily futures metrics ({res['perps_with_metrics']} perps, "
             "`lab.collect.um_metrics`), each of five inputs (top-trader account and position ratio, taker buy/sell "
             "ratio, open-interest growth over 3 and 7 days in contracts) a z-score against the perp's own previous 90 "
             "days; score = minus their mean (long the least crowded). Scores `s_acct` to `s_oi7` in the IC table are "
             "the single components with the same contrarian sign.")
    text = r2.perp_markdown("Cross-sectional positioning on perpetuals", "positioning_xs_prereg.md", intro, res)
    dc.write_results(NAME, text)
    report.write(NAME, text, res)


if __name__ == "__main__":
    main()
