"""Family 9: risk-parity ensembles of the other families' in-sample picks.

The sleeves are fixed by in-sample information only: in every sub-family of
families 1 to 8, the variant with the best 2020-2023 Sharpe at 15 bps (the
same pick the sweep judges). Nothing out of sample decides what goes in.

Weights are re-set every 30 days, proportional to 1 / (each sleeve's daily
volatility over the last 90 days), summing to 1, known at the decision close.
Each sleeve keeps its own costs; moving capital between sleeves is charged as
|change in sleeve weight| x the sleeve's gross exposure.

Variants (4):
  all picks, risk parity
  picks with in-sample Sharpe > 0.5, risk parity
  picks with in-sample Sharpe > 0.5, equal weight
  spot long-only picks with in-sample Sharpe > 0.5, risk parity (executable by the engine)
"""

from __future__ import annotations

import numpy as np

from . import fam_common as fc

FAMILY = "ensemble"
REWEIGHT = 30
VOL_WIN = 90


def combine(P: fc.Panel, sleeves: list[fc.Result], name: str, risk_parity: bool, spot: bool) -> fc.Result:
    K = len(sleeves)
    G = np.array([s.gross for s in sleeves])            # (K, T)
    TV = np.array([s.turnover for s in sleeves])
    EX = np.array([s.long_expo + s.short_expo for s in sleeves])
    var = fc.rolling((G ** 2).T, VOL_WIN, int(VOL_WIN * 0.8)).T
    a = np.zeros((K, P.T))
    cur = np.zeros(K)
    for t in range(P.T):
        if t % REWEIGHT == 0:
            if risk_parity:
                with np.errstate(divide="ignore", invalid="ignore"):
                    inv = np.where(np.isfinite(var[:, t]) & (var[:, t] > 0), 1 / np.sqrt(var[:, t]), 0.0)
            else:
                inv = np.where(np.isfinite(var[:, t]) & (var[:, t] > 0), 1.0, 0.0)
            cur = inv / inv.sum() if inv.sum() > 0 else np.zeros(K)
        a[:, t] = cur
    # a[:, t] is decided at the close of t and earns day t+1
    a_prev = np.concatenate([np.zeros((K, 1)), a[:, :-1]], axis=1)
    gross = (a_prev * G).sum(0)
    shift = np.abs(np.diff(np.concatenate([np.zeros((K, 1)), a], axis=1), axis=1))
    turnover = (a * TV).sum(0) + (shift * EX).sum(0)
    le = (a * np.array([s.long_expo for s in sleeves])).sum(0)
    se = (a * np.array([s.short_expo for s in sleeves])).sum(0)
    return fc.Result(FAMILY, "spot long-only" if spot else "with market-neutral sleeves", name, gross, turnover,
                     le, se, "ew", spot)


def variants(P: fc.Panel, sleeves: list[fc.Result]) -> list[fc.Result]:
    ins, _ = fc.masks(P)
    is_sr = {id(s): fc.perf(s.net(fc.COSTS["15bps"])[ins])["sharpe"] for s in sleeves}
    good = [s for s in sleeves if is_sr[id(s)] > 0.5]
    good_spot = [s for s in good if s.spot_only]
    out = [combine(P, sleeves, f"risk parity · all {len(sleeves)} picks", True, False),
           combine(P, good, f"risk parity · {len(good)} picks with IS Sharpe > 0.5", True, False),
           combine(P, good, f"equal weight · {len(good)} picks with IS Sharpe > 0.5", False, False),
           combine(P, good_spot, f"risk parity · {len(good_spot)} spot picks with IS Sharpe > 0.5", True, True)]
    members = "; ".join(f"{s.family}/{s.name} (IS {is_sr[id(s)]:.2f})" for s in sleeves)
    print("ensemble sleeves:", members)
    return out
