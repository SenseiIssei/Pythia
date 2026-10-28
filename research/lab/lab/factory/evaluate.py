"""Judging a genome: the in-sample fitness the search sees, the holdout gates, the promotion bar.

Fitness is the in-sample Sharpe at 35 bps (for a fixed list the worse of the
list and its point-in-time twin) minus COMPLEXITY_COST per moving part (a tree
counts its nodes), minus TREE_NODE_COST more per tree node (an invented
building block needs more evidence than a hand-made one of the same size), and a
penalty for a book that is almost always cash. In sample from 2018-01-01 to 2023-12-31 on the panel with
Binance's daily bars before 2020 (lab.history; until D1 it was the hand studies' 2020-08-01, rows of that window
still count in the pool but are not bred from or held back), split in two halves for a stability check; held back
from 2024-01-01 to the last close. The search sees only the in-sample window. A genome reaches
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

R6 (pre-registered in results/factory_lockbox_r6.md): 2024-01-01 to 2026-06-30 is
validation, spent by every study since the families sweep; "held back" and "oos"
mean that window now. 2026-07-01 on is the lockbox, which only the weekly run looks
at (run.lockbox_step, every look logged in ledger.lockbox_path() across the
factories), once per behaviour. The deflated gate is now on the held-back excess
over BTC (ledger.deflated_excess: N the registry's pool of all, the variance the
family's in-sample excess Sharpes); the raw Sharpe's DSR is kept as dsr_raw. The
lockbox gate: a look was made and its excess over BTC beats the best of that many
looks' noise at LOCKBOX_BAR. Each run also reports the effective N of its genomes
(clusters of the in-sample return matrix) and their PBO by CSCV; neither moves the
bar (the registry's N is the larger and decides).

T2 (results/overfit_yardsticks_prereg.md): the PBO also over the whole family (every
genome of the window, one per behaviour, at most FAMILY_MAX) with the rank logits'
distribution, and each candidate that reaches validation gets a combinatorial purged
CV of its in-sample days (cpcv) and one line in the report (candidate_line). Neither
moves the bar.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from .. import cv, history, metrics
from ..experiments import fam_common as fc
from . import build, grammar
from .ledger import deflated, deflated_excess, lockbox_looks

COMPLEXITY_COST = 0.03     # in-sample Sharpe given up per moving part
TREE_NODE_COST = 0.02      # and more per node of an expression tree (G1): 0.05 a node in all
MIN_EXPOSURE = 0.10        # a book that is almost always cash has a Sharpe made of a few days
DEFLATED_BAR = 0.95
BOOT_DRAWS, BOOT_BLOCK, SEED = 2000, 5, 7
SHADOW_GATES = ("is_stable", "oos_positive", "stress", "drawdown", "late_fill", "twin")
IS_FROM = history.LONG_FROM
OLD_IS_FROM = "2020-08-01"                   # fc.IS_START, the window of the rows before D1
IS_START = int(datetime.strptime(IS_FROM, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
LOCKBOX_FROM = "2026-07-01"                  # validation ends the day before (R6)
LOCKBOX_START = int(datetime.strptime(LOCKBOX_FROM, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)
LOCKBOX_MIN_DAYS = 60                        # no look before the lockbox holds this many days
LOCKBOX_BAR = 0.5                            # the look's DSR over every look so far must reach this
EFF_CORR = 0.5                               # genomes in one cluster of the effective N correlate above this
CSCV_BLOCKS = metrics.CSCV_BLOCKS
CPCV_GROUPS, CPCV_TEST = 12, 3               # T2: 220 splits, 55 paths
CPCV_PURGE, CPCV_EMBARGO = 1, 0.01           # a day's return is the label; embargo 1 % of the days
CPCV_CORR = 0.90                             # a near variant: in-sample correlation above this (run.DIVERSITY_CORR;
                                             # at EFF_CORR every long book is everyone's variant, results/overfit_yardsticks.md)
FAMILY_MAX = 2000                            # the family's PBO over at most this many genomes, the best by fitness


def current(rows: list[dict]) -> list[dict]:
    """The ledger rows scored on this in-sample window; older rows only count as trials."""
    return [r for r in rows if r.get("is_from", OLD_IS_FROM) == IS_FROM]


def windows(c: build.Ctx) -> dict[str, np.ndarray]:
    ins = (c.days >= IS_START) & (c.days < fc.SPLIT)
    idx = np.flatnonzero(ins)
    mid = idx[len(idx) // 2] if len(idx) else 0
    h1 = ins & (np.arange(c.T) < mid)
    return {"is": ins, "h1": h1, "h2": ins & ~h1, "oos": (c.days >= fc.SPLIT) & (c.days < LOCKBOX_START),
            "lockbox": c.days >= LOCKBOX_START}


def btc_returns(c: build.Ctx) -> np.ndarray:
    return np.nan_to_num(c.P.ret[:, c.P.btc])


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
        "is_from": IS_FROM,
        "is_sharpe": sharpe(n35[w["is"]]), "is_sharpe_15": sharpe(build.net(gross, tov, 0.0015)[w["is"]]),
        "is_h1": sharpe(n35[w["h1"]]), "is_h2": sharpe(n35[w["h2"]]),
        "is_cagr": p["cagr"], "is_max_dd": p["max_dd"],
        "is_turnover_yr": float(tov[w["is"]].sum() / years) if years else 0.0,
        "is_exposure": float(expo[w["is"]].mean()) if w["is"].any() else 0.0,
    }
    # A fixed list (core, Alpaca) is today's survivors, which flatters every year before
    # today. The search scores such a genome by the worse of the list and its
    # point-in-time twin, so survivorship cannot win the in-sample race.
    base = row["is_sharpe"]
    row["is_twin"] = None
    if g["universe"]["kind"] != "top":
        tg, tt, _ = build.run(c, g, twin=True)
        row["is_twin"] = sharpe(build.net(tg, tt, build.COSTS["35bps"])[w["is"]])
        base = min(base, row["is_twin"])
    row["tree_nodes"] = grammar.tree_nodes(g)
    if row["tree_nodes"]:
        row["expression"] = grammar.expression(g)
    f = base - COMPLEXITY_COST * cx - TREE_NODE_COST * row["tree_nodes"]
    if row["is_exposure"] < MIN_EXPOSURE:
        f -= 1.0
    row["fitness"] = f if math.isfinite(f) else -9.0
    row["is_excess_sharpe"] = sharpe(n35[w["is"]] - btc_returns(c)[w["is"]])
    row["behaviour"] = grammar.behaviour(n35[w["is"]])
    row["is_returns"] = n35[w["is"]]   # in memory only (PBO, effective N); run.strip drops it before the ledger
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
    ex = x35 - btc_returns(c)[oos]
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
        "oos_excess_sharpe": sharpe(ex), "behaviour": grammar.behaviour(nets["35bps"][w["is"]]),
        "deflated_p": deflated_excess(ex, pool), "dsr_raw": deflated(x35, pool), "pool_trials": pool["n_trials"],
        "pool_sr0": pool.get("excess_sr0_annual", pool["sr0_annual"]), "raw_sr0": pool["sr0_annual"],
        "band30": boot_quantiles(x35, 30),
    }
    return res


def lockbox(c: build.Ctx, g: dict, pool: dict) -> dict | None:
    """The numbers of one look at the lockbox (None while it is shorter than LOCKBOX_MIN_DAYS). Only
    run.lockbox_step calls this, and it logs the look before it uses it."""
    lb = windows(c)["lockbox"]
    if lb.sum() < LOCKBOX_MIN_DAYS:
        return None
    gross, tov, _ = build.run(c, g)
    x35 = build.net(gross, tov, build.COSTS["35bps"])[lb]
    ex = x35 - btc_returns(c)[lb]
    n = len(lockbox_looks()) + 1                 # this look counts too
    return {"lockbox_from": _day(int(c.days[lb][0])), "lockbox_to": _day(int(c.days[lb][-1])),
            "lockbox_days": int(lb.sum()), "lockbox_sharpe": sharpe(x35), "lockbox_excess_sharpe": sharpe(ex),
            "btc_sharpe": sharpe(btc_returns(c)[lb]), "looks": n, "dsr": deflated_excess(ex, pool, n=n)}


def lockbox_gate(key: str, behaviour: str | None = None) -> dict:
    """Passed when the genome (or one that does the same) was looked at and its look reached LOCKBOX_BAR."""
    mine = [x for x in lockbox_looks() if x.get("key") == key or behaviour and x.get("behaviour") == behaviour]
    if not mine:
        return {"passed": False, "why": "never looked at in the lockbox"}
    x = mine[0]
    return {"passed": bool(x["dsr"] >= LOCKBOX_BAR),
            "why": f"lockbox look {x['look']}: excess over BTC Sharpe {x['lockbox_excess_sharpe']:.2f} over "
                   f"{x['lockbox_days']} days, DSR {x['dsr']:.2f} over {x['looks']} looks (needs {LOCKBOX_BAR})"}


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
                     "why": f"DSR of the excess over BTC {h['deflated_p']:.2f} over {h['pool_trials']} trials "
                            f"(noise bar excess Sharpe {h['pool_sr0']:.2f})"}
    g["lockbox"] = lockbox_gate(h["key"], h.get("behaviour"))
    return g


def excess_bar(h: dict) -> bool:
    """The held-back excess passes the deflated bar (what earns a lockbox look)."""
    return h["deflated_p"] > DEFLATED_BAR


def _matrix(series: list[np.ndarray]) -> np.ndarray:
    """Equal-length series (the last days in common) as columns, those that never move dropped."""
    xs = [np.nan_to_num(np.asarray(x, dtype=float)) for x in series if x is not None and len(x)]
    if not xs:
        return np.zeros((0, 0))
    n = min(len(x) for x in xs)
    R = np.column_stack([x[-n:] for x in xs])
    return R[:, R.std(0) > 0]


def effective_n(series: list[np.ndarray], corr: float = EFF_CORR) -> dict:
    """Clusters of the genomes' in-sample returns (average linkage on 1 - correlation, cut at 1 - corr): the
    number of independent bets among them. Books that never move are one more cluster if there are any."""
    from scipy.cluster.hierarchy import fcluster, linkage
    R = _matrix(series)
    flat = sum(1 for x in series if x is not None and len(x)) - R.shape[1]
    m = R.shape[1]
    if m < 2:
        return {"genomes": m + flat, "effective_n": m + (flat > 0), "corr": corr}
    C = np.clip(np.corrcoef(R, rowvar=False), -1, 1)
    D = 1 - C[np.triu_indices(m, 1)]
    k = int(fcluster(linkage(np.clip(D, 0, 2), "average"), t=1 - corr, criterion="distance").max())
    return {"genomes": m + flat, "effective_n": k + (flat > 0), "corr": corr}


def pbo(series: list[np.ndarray], blocks: int = CSCV_BLOCKS) -> dict | None:
    """Probability of backtest overfitting by CSCV (Bailey, Borwein, Lopez de Prado, Zhu): the days cut into
    `blocks` blocks, every half of them in sample and the rest out; how often the in-sample best by Sharpe
    ranks in the lower half out of sample, with the rank logits' quantiles and histogram (metrics.cscv). None
    with fewer than 2 moving genomes or too few days."""
    return metrics.cscv(_matrix(series), blocks)


def family_pbo(series: dict[str, np.ndarray], blocks: int = CSCV_BLOCKS) -> dict | None:
    """T2: PBO over a whole family (every genome of the ledger's window, one per behaviour), not one run's."""
    p = pbo(list(series.values()), blocks)
    return {**p, "family_genomes": len(series)} if p else None


def _sharpe_cols(R: np.ndarray, mask: np.ndarray) -> np.ndarray:
    x = R[mask]
    sd = x.std(0)
    return np.where(sd > 0, x.mean(0) / np.where(sd > 0, sd, 1), -np.inf)


def cpcv(x: np.ndarray, family: dict[str, np.ndarray] | None = None, key: str | None = None,
         n_groups: int = CPCV_GROUPS, k_test: int = CPCV_TEST, corr: float = CPCV_CORR) -> dict | None:
    """T2: combinatorial purged CV of a candidate on its in-sample returns x (cv.cpcv: n_groups groups of days,
    k_test of them tested, purge CPCV_PURGE days, embargo CPCV_EMBARGO of the days). A rule has nothing to fit, so
    each split picks, among the candidate and its near variants (family series correlating above `corr`), the one
    with the best training Sharpe, and its test days fill the paths: picking in this region of the search the way
    the search picks. Returns the paths' annual Sharpes (median, 10th percentile). None with too few days."""
    x = np.nan_to_num(np.asarray(x, dtype=float))
    T = len(x)
    if T < n_groups * 10:
        return None
    cols = [x]
    for k, y in (family or {}).items():
        if k == key or y is None or len(y) < T:
            continue
        y = np.nan_to_num(np.asarray(y, dtype=float))[-T:]
        if y.std() > 0 and x.std() > 0 and np.corrcoef(x, y)[0, 1] > corr and not np.array_equal(x, y):
            cols.append(y)
    R = np.column_stack(cols)
    t = np.arange(T)
    splits = cv.cpcv(t, n_groups, k_test, purge=CPCV_PURGE, embargo=math.ceil(CPCV_EMBARGO * T))
    picks = [int(np.argmax(_sharpe_cols(R, sp.train))) for sp in splits]
    paths = cv.assemble(splits, [R[:, j] for j in picks], n_groups, k_test, t)
    srs = np.array([sharpe(p) for p in paths])
    return {"paths": len(srs), "splits": len(splits), "groups": n_groups, "test_groups": k_test,
            "variants": len(cols) - 1, "median": float(np.median(srs)), "p10": float(np.percentile(srs, 10)),
            "picked_self": float(np.mean([j == 0 for j in picks]))}


def candidate_line(h: dict, fam: dict | None, what: str = "the excess over BTC") -> str:
    """T2: one line per candidate that reached validation: DSR (its direction), the family's PBO, CPCV."""
    c = h.get("cpcv")
    cp = (f"CPCV in sample median Sharpe {c['median']:.2f}, 10th percentile {c['p10']:.2f} over {c['paths']} paths "
          f"({c['variants']} near variant(s)" + ("; none, so every path is the candidate itself)" if not c["variants"]
                                                   else ")") if c else "CPCV n/a (too few days)")
    pb = f"PBO of the family {fam['pbo']:.2f}" if fam else "PBO of the family n/a"
    return (f"- {h['key']} {h.get('name', '')}: DSR of {what} {h['deflated_p']:.2f} (higher is better, pass at "
            f"{DEFLATED_BAR}) · {pb} · {cp}")


def failed(gates: dict[str, dict]) -> list[str]:
    return [k for k, v in gates.items() if not v["passed"]]


def btc_benchmark(c: build.Ctx) -> dict:
    oos = windows(c)["oos"]
    r = np.nan_to_num(c.P.ret[:, c.P.btc])[oos]
    p = fc.perf(r)
    return {"sharpe": p["sharpe"], "max_dd": p["max_dd"], "cagr": p["cagr"]}
