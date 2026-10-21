"""Shared by the three studies registered together on 2026-10-21 in the evening
(perps_neutral_portfolio, attention_wiki, intraday_tsmom): the pool they count into,
the bootstrap seed and the perp cost levels.

The pool (results/perps_neutral_portfolio_prereg.md): 1,328 hand trials before this
registration (1,140 after polymarket plus the parallel batches of 2026-10-21 that each
started from 1,140: the four perp studies 37, the equity survey 33, the vol/ETF batch
22, crypto_own 94 with O9's 2 forward trials), at the variance backed out of the
published bar (377 trials at 2.43); the factory ledger as read at run time; and the 25
trials registered here, each study's own at its own variance.
"""

from __future__ import annotations

import math

import numpy as np

from . import director_common as dc
from . import fam_common as fc

HAND_TRIALS = 1140 + 37 + 33 + 22 + 96
STUDY_TRIALS = {"perps_neutral_portfolio": 3, "attention_wiki": 13, "intraday_tsmom": 9}
TODAY_TRIALS = sum(STUDY_TRIALS.values())
SEED = 20261021

# Perp costs per unit of one-way turnover (perps_common: Kraken Futures taker 5 bps
# plus half-spread; maker 2 bps is the maker fee with every order filled, an upper bound).
PERP_COSTS = {"2bps": 0.0002, "10bps": 0.0010, "20bps": 0.0020, "41bps": 0.0041}
PERP_JUDGED, PERP_STRESS = "10bps", "20bps"


def pool(mine_annual: list[float]) -> dict:
    """The pooled per-day variance of trial Sharpes and the trial count. mine_annual: this
    study's trial Sharpes (annual); they stand for all 25 of today's trials."""
    v1, n1 = dc.prior_var(), HAND_TRIALS
    fx = np.clip(dc.factory_sharpes(), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(dc.YEAR)
    n2, v2 = len(fx), float(np.var(fx)) if len(fx) > 1 else 0.0
    x = np.clip(np.array(mine_annual, dtype=float), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(dc.YEAR)
    v3 = float(np.var(x)) if len(x) > 1 else v1
    n3 = TODAY_TRIALS
    n = n1 + n2 + n3
    v = (n1 * v1 + n2 * v2 + n3 * v3) / n
    return {"hand_trials": n1, "factory_trials": n2, "today_trials": n3, "mine": len(x), "n_total": n,
            "var": v, "sr0_annual": fc._sr0(v, n) * math.sqrt(dc.YEAR)}


def pool_line(pl_: dict) -> str:
    return (f"Pool: {pl_['n_total']:,} trials ({pl_['hand_trials']:,} hand before this registration, "
            f"{pl_['factory_trials']} factory as read now, {pl_['today_trials']} registered together on "
            f"2026-10-21: perps_neutral_portfolio 3, attention_wiki 13, intraday_tsmom 9); the best noise trial "
            f"sits at an annual Sharpe of about {pl_['sr0_annual']:.2f}. The next study starts from "
            f"{HAND_TRIALS + TODAY_TRIALS:,} hand trials.")


def boot(x: np.ndarray, y: np.ndarray | None = None) -> tuple[float, float, float]:
    return dc.boot_band(np.asarray(x, dtype=float), None if y is None else np.asarray(y, dtype=float), seed=SEED)


def max_dd(x: np.ndarray) -> float:
    return float(fc.perf(np.asarray(x, dtype=float))["max_dd"])
