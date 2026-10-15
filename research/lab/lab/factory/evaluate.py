"""Judging a genome: the in-sample fitness the search sees, the holdout gates, the promotion bar.

Windows are the hand studies' own: in sample from 2020-08-01 to 2023-12-31
(split in two halves for a stability check), held back from 2024-01-01 to
the last close. The search sees only the in-sample window. A genome reaches
the holdout only when the search sends it there, and every holdout check is
written down.

Shadow gates (all must hold to start a 30-day forward shadow book):
  is_stable    both in-sample halves have a positive Sharpe at 35 bps
  oos_positive held-back Sharpe at 35 bps above 0
  stress       held-back Sharpe at 70 bps above 0
  drawdown     held-back drawdown at 35 bps below BTC's over the same days
  late_fill    still positive at 35 bps when every decision is filled a close later
  twin         for the fixed lists (core, Alpaca): the point-in-time twin (the same
               number of the most liquid coins at the start of each year) positive too

Promotion bar (the hand studies' bar, plus the forward test):
  every shadow gate, deflated p above 0.95 against the whole pool (hand studies
  plus every factory trial so far), and after 30 shadow days a forward return
  not below the 5 % quantile of the backtest's own 30-day returns.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from ..experiments import fam_common as fc
from . import build, grammar
from .ledger import deflated

COMPLEXITY_COST = 0.03     # in-sample Sharpe given up per moving part
MIN_EXPOSURE = 0.10        # a book that is almost always cash has a Sharpe made of a few days
DEFLATED_BAR = 0.95
BOOT_DRAWS, BOOT_BLOCK, SEED = 2000, 5, 7
SHADOW_GATES = ("is_stable", "oos_positive", "stress", "drawdown", "late_fill", "twin")


def windows(c: build.Ctx) -> dict[str, np.ndarray]:
    ins = (c.days >= fc.IS_START) & (c.days < fc.SPLIT)
    idx = np.flatnonzero(ins)
    mid = idx[len(idx) // 2] if len(idx) else 0
    h1 = ins & (np.arange(c.T) < mid)
    return {"is": ins, "h1": h1, "h2": ins & ~h1, "oos": c.days >= fc.SPLIT}


def sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    sd = x.std() if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0


def _day(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def in_sample(c: build.Ctx, g: dict, run_id: str) -> dict:
    """The only numbers the search ever sees."""
    w = windows(c)
    gross, tov, expo = build.run(c, g)
    n35 = build.net(gross, tov, build.COSTS["35bps"])
    years = w["is"].sum() / 365
    p = fc.perf(n35[w["is"]])
    cx = grammar.complexity(g)
    row = {
        "key": grammar.key(g), "run": run_id, "name": grammar.describe(g), "genome": g, "complexity": cx,
        "is_sharpe": sharpe(n35[w["is"]]), "is_sharpe_15": sharpe(build.net(gross, tov, 0.0015)[w["is"]]),
        "is_h1": sharpe(n35[w["h1"]]), "is_h2": sharpe(n35[w["h2"]]),
        "is_cagr": p["cagr"], "is_max_dd": p["max_dd"],
        "is_turnover_yr": float(tov[w["is"]].sum() / years) if years else 0.0,
        "is_exposure": float(expo[w["is"]].mean()) if w["is"].any() else 0.0,
    }
    f = row["is_sharpe"] - COMPLEXITY_COST * cx
    if row["is_exposure"] < MIN_EXPOSURE:
        f -= 1.0
    row["fitness"] = f if math.isfinite(f) else -9.0
    row["is_returns"] = None   # filled only for genomes kept in memory for the diversity check
    return row


def is_series(c: build.Ctx, g: dict) -> np.ndarray:
    gross, tov, _ = build.run(c, g)
    return build.net(gross, tov, build.COSTS["35bps"])[windows(c)["is"]]


def boot_quantiles(x: np.ndarray, days: int, q=(5, 50, 95), draws: int = BOOT_DRAWS,
                   block: int = BOOT_BLOCK, seed: int = SEED) -> list[float]:
    """Quantiles of the compounded return over `days` days, moving-block bootstrap of x."""
    x = x[np.isfinite(x)]
    if len(x) < block * 2 or days < 1:
        return [float("nan")] * len(q)
    rng = np.random.default_rng(seed)
    nb = -(-days // block)
    starts = rng.integers(0, len(x) - block + 1, (draws, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(draws, -1)[:, :days]
    tot = np.prod(1 + x[idx], axis=1) - 1
    return [float(v) for v in np.percentile(tot, q)]


def holdout(c: build.Ctx, g: dict, pool: dict, btc: dict) -> dict:
    """Every held-back number and the shadow gates. `btc`: BTC's held-back Sharpe and drawdown."""
    w = windows(c)
    oos = w["oos"]
    gross, tov, expo = build.run(c, g)
    nets = {k: build.net(gross, tov, v) for k, v in build.COSTS.items()}
    p35 = fc.perf(nets["35bps"][oos])
    lg, lt, _ = build.run(c, g, late=True)
    late35 = sharpe(build.net(lg, lt, build.COSTS["35bps"])[oos])
    twin35 = None
    if g["universe"]["kind"] != "top":
        tg, tt, _ = build.run(c, g, twin=True)
        twin35 = sharpe(build.net(tg, tt, build.COSTS["35bps"])[oos])
    years = oos.sum() / 365
    x35 = nets["35bps"][oos]
    res = {
        "key": grammar.key(g), "name": grammar.describe(g),
        "oos_from": _day(int(c.days[oos][0])) if oos.any() else None,
        "oos_to": _day(int(c.days[oos][-1])) if oos.any() else None,
        "oos_days": int(oos.sum()),
        **{f"oos_sharpe_{k}": sharpe(v[oos]) for k, v in nets.items()},
        "oos_cagr": p35["cagr"], "oos_max_dd": p35["max_dd"],
        "oos_turnover_yr": float(tov[oos].sum() / years) if years else 0.0,
        "oos_exposure": float(expo[oos].mean()) if oos.any() else 0.0,
        "oos_late_sharpe": late35, "oos_twin_sharpe": twin35,
        "btc_sharpe": btc["sharpe"], "btc_max_dd": btc["max_dd"],
        "deflated_p": deflated(x35, pool), "pool_trials": pool["n_trials"], "pool_sr0": pool["sr0_annual"],
        "band30": boot_quantiles(x35, 30),
    }
    return res


def shadow_gates(is_row: dict, h: dict) -> dict[str, dict]:
    tw = h["oos_twin_sharpe"]
    gates = {
        "is_stable": (is_row["is_h1"] > 0 and is_row["is_h2"] > 0,
                      f"in-sample halves {is_row['is_h1']:.2f} / {is_row['is_h2']:.2f}"),
        "oos_positive": (h["oos_sharpe_35bps"] > 0, f"held-back Sharpe {h['oos_sharpe_35bps']:.2f} at 35 bps"),
        "stress": (h["oos_sharpe_70bps"] > 0, f"{h['oos_sharpe_70bps']:.2f} at 70 bps"),
        "drawdown": (h["oos_max_dd"] < h["btc_max_dd"],
                     f"drawdown {h['oos_max_dd'] * 100:.0f} % vs BTC {h['btc_max_dd'] * 100:.0f} %"),
        "late_fill": (h["oos_late_sharpe"] > 0, f"filled a close late {h['oos_late_sharpe']:.2f}"),
        "twin": (tw is None or tw > 0, "no fixed list" if tw is None else f"point-in-time twin {tw:.2f}"),
    }
    return {k: {"passed": bool(ok), "why": why} for k, (ok, why) in gates.items()}


def bar_gates(is_row: dict, h: dict) -> dict[str, dict]:
    """The promotion bar on the backtest: every shadow gate plus deflation over the whole pool."""
    g = shadow_gates(is_row, h)
    g["deflated"] = {"passed": h["deflated_p"] > DEFLATED_BAR,
                     "why": f"deflated p {h['deflated_p']:.2f} over {h['pool_trials']} trials "
                            f"(noise bar Sharpe {h['pool_sr0']:.2f})"}
    return g


def failed(gates: dict[str, dict]) -> list[str]:
    return [k for k, v in gates.items() if not v["passed"]]


def btc_benchmark(c: build.Ctx) -> dict:
    oos = windows(c)["oos"]
    r = np.nan_to_num(c.P.ret[:, c.P.btc])[oos]
    p = fc.perf(r)
    return {"sharpe": p["sharpe"], "max_dd": p["max_dd"], "cagr": p["cagr"]}
