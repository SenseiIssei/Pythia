"""Part 2 of results/autopilot_optimization.md: a resize band for lab rebalances.

    python -m lab.experiments.rebalance_band          print the results (markdown)
    python -m lab.experiments.rebalance_band --json   the same as JSON

Pre-registered in results/autopilot_optimization.md (committed before this file
existed). Replays the engine's lab rebalance on the four books the autopilots
run on Alpaca, at each close and per coin:

  baseline   today's engine (lab::rebalance): every difference of at least 0.2 %
             of capital trades, entries and exits included
  band b     an entry (held 0, target > 0) and an exit (target 0) always trade
             once they clear the venue minimum ($10 on a $10,000 book); a
             resize (both above 0) trades only when |target - held| >= b,
             and then all the way to the target

Every trade costs 35 bps per unit of turnover (stress 70), charged the day
after, as alpaca_universe and book_portfolio charge it. The coin set held on any
day is the baseline's by construction; only how often a held coin is resized
changes.
"""

from __future__ import annotations

import json
import math
import sys

import numpy as np

from . import alpaca_universe as au
from . import fam_common as fc
from . import tsmom as ts

BASE_BAND = 0.002
MIN_W = 10.0 / 10_000.0
BANDS = (0.005, 0.01, 0.02)
COST, STRESS = 0.0035, 0.0070
IS_START = np.datetime64("2020-08-01")
SPLIT = np.datetime64("2024-01-01")
YEAR = 365
# The registered pick rule (results/autopilot_optimization.md, part 2).
COST_CUT = 0.25
SHARPE_SLACK = 0.02
TE_MAX = 0.010


def replay(ret: np.ndarray, W: np.ndarray, traded: np.ndarray, alive: np.ndarray, start: int,
           band: float | None, min_w: float = MIN_W, base_band: float = BASE_BAND):
    """The engine's rebalance at every close from `start`. band None is the baseline rule.

    ret[t] is the return earned from close t-1 to close t; W[t] the targets at close t
    (NaN: no new target, hold). Returns (gross, turnover, exposure): gross earned on
    day t, one-way turnover traded at the close of day t, exposure after it."""
    T, N = W.shape
    w = np.zeros(N)
    gross, tov, ex = np.zeros(T), np.zeros(T), np.zeros(T)
    for t in range(start, T):
        tgt = np.where(np.isnan(W[t]), w, W[t])
        tgt = np.where(traded[t] | (tgt == w), np.maximum(tgt, 0.0), w)
        d = tgt - w
        if band is None:
            move = np.abs(d) >= max(base_band, min_w)
        else:
            entry = (w <= 1e-12) & (tgt > 1e-12)
            exit_ = (tgt <= 1e-12) & (w > 1e-12)
            resize = (w > 1e-12) & (tgt > 1e-12)
            move = ((entry & (tgt >= min_w)) | (exit_ & (w >= min_w)) | (resize & (np.abs(d) >= band)))
        new = np.where(move, tgt, w)
        tov[t] += float(np.abs(new - w).sum())
        w = new
        ex[t] = float(w.sum())
        if t == T - 1:
            break
        r = np.nan_to_num(ret[t + 1])
        g = float(np.dot(w, r))
        gross[t + 1] = g
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        dead = (w != 0) & ~alive[t + 1]
        if dead.any():
            tov[t + 1] += float(np.abs(w[dead]).sum())
            w[dead] = 0.0
    return gross, tov, ex


def net(gross: np.ndarray, tov: np.ndarray, cost: float) -> np.ndarray:
    return gross - cost * np.r_[0.0, tov[:-1]]


def sharpe(x: np.ndarray) -> float:
    sd = x.std()
    return float(x.mean() / sd * math.sqrt(YEAR)) if sd > 0 else 0.0


def max_dd(x: np.ndarray) -> float:
    eq = np.cumprod(1 + x)
    peak = np.maximum.accumulate(np.r_[1.0, eq])[1:]
    return float((1 - eq / peak).max()) if len(x) else 0.0


def measure(gross, tov, ex, base, mask) -> dict:
    """Numbers over the masked days; `base` is the baseline's (gross, tov) for the tracking error."""
    n35 = net(gross, tov, COST)[mask]
    n70 = net(gross, tov, STRESS)[mask]
    b35 = net(base[0], base[1], COST)[mask]
    yrs = mask.sum() / YEAR
    charged = np.r_[0.0, tov[:-1]][mask]
    return {"sharpe": sharpe(n35), "sharpe_stress": sharpe(n70), "cagr": float(np.prod(1 + n35) ** (1 / yrs) - 1),
            "dd": max_dd(n35), "turnover_yr": float(charged.sum() / yrs), "cost_yr": float(COST * charged.sum() / yrs),
            "te": float((n35 - b35).std() * math.sqrt(YEAR)), "max_exposure": float(ex[mask].max())}


# ---------------------------------------------------------------- the books

def panel_books():
    """(P, {book: targets}) for the three panel books, as the autopilots run them on Alpaca."""
    P = fc.load_panel()
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    W_tr = au.cash_left(O["tsmom_tranches"], alp)
    _, _, _, held = au.sim_tranches(P, W_tr)
    held = held.copy()
    held[: au.START] = np.nan
    return P, {"breakout_top10": au.cash_left(O["breakout"], alp),
               "tsmom_top20": au.cash_left(O["tsmom_daily"], alp),
               "tsmom_tranches": held}


def regime_book():
    """(days as datetime64[D], ret, targets, traded, alive) of book_portfolio's tsmom_regime."""
    days, close, rv, names = ts.daily_matrix()
    sigma = np.sqrt(ts.rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = ts.rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)
    listed = np.array([n in au.ALPACA for n in names], dtype=float)
    T, N = close.shape
    ret = np.full_like(close, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = close[1:] / close[:-1] - 1
    W = np.full((T, N), np.nan)
    for t in range(200, T):
        W[t] = ts.target_weights(close, sigma, history, t, [28], 0.40) * (1.0 if risk_on[t] else 0.0) * listed
    traded = np.isfinite(close)
    alive = np.ones_like(traded, dtype=bool)
    d = (np.asarray(days, dtype=np.int64) // 86_400_000_000).astype("datetime64[D]")
    return d, ret, W, traded, alive


def run() -> dict:
    P, books = panel_books()
    pdays = (np.asarray(P.days, dtype=np.int64) // 86_400_000_000).astype("datetime64[D]")
    setups = {b: (pdays, P.ret, W, P.traded, P.alive, au.START) for b, W in books.items()}
    rd, rret, rW, rtr, ral = regime_book()
    setups["tsmom_regime"] = (rd, rret, rW, rtr, ral, 200)
    rows = []
    for book, (days, ret, W, traded, alive, start) in setups.items():
        isk = (days >= IS_START) & (days < SPLIT)
        oos = days >= SPLIT
        base = replay(ret, W, traded, alive, start, None)
        for band in (None,) + BANDS:
            run_ = base if band is None else replay(ret, W, traded, alive, start, band)
            for label, mask in (("is", isk), ("oos", oos)):
                rows.append({"book": book, "band": "baseline 0.2 %" if band is None else f"{band * 100:g} %",
                             "b": band, "window": label, **measure(*run_, base[:2], mask)})
    return {"rows": rows, "verdict": judge(rows), "end": str(pdays[-1])}


def judge(rows: list[dict]) -> dict:
    """The registered rule: the largest band that passes in sample for every book, then confirmed out of sample."""
    def ok(window: str, band: float) -> tuple[bool, list[str]]:
        why = []
        for book in sorted({r["book"] for r in rows}):
            base = next(r for r in rows if r["book"] == book and r["b"] is None and r["window"] == window)
            x = next(r for r in rows if r["book"] == book and r["b"] == band and r["window"] == window)
            if not x["cost_yr"] <= (1 - COST_CUT) * base["cost_yr"]:
                why.append(f"{book}: cost {x['cost_yr'] * 1e4:.0f} bps a year against {base['cost_yr'] * 1e4:.0f}")
            if not x["sharpe"] >= base["sharpe"] - SHARPE_SLACK:
                why.append(f"{book}: Sharpe {x['sharpe']:.3f} against {base['sharpe']:.3f}")
            if not x["te"] <= TE_MAX:
                why.append(f"{book}: tracking error {x['te'] * 100:.2f} %")
        return not why, why

    tried = {}
    pick = None
    for band in sorted(BANDS, reverse=True):
        good, why = ok("is", band)
        tried[f"{band * 100:g} %"] = why
        if good:
            pick = band
            break
    if pick is None:
        return {"pick": None, "confirmed": False, "in_sample_failures": tried, "oos_failures": []}
    good, why = ok("oos", pick)
    return {"pick": pick, "confirmed": good, "in_sample_failures": tried, "oos_failures": why}


def markdown(res: dict) -> str:
    v = res["verdict"]
    lines = [f"### Results (panel to {res['end']})\n"]
    if v["pick"] is None:
        lines.append("**No band passes in sample for every book; the default stays at 0.2 %.**\n")
    elif v["confirmed"]:
        lines.append(f"**Picked and confirmed: a resize band of {v['pick'] * 100:g} % of capital.** In sample and out "
                     f"of sample, for every book, it cuts the turnover cost by at least {COST_CUT * 100:.0f} %, keeps "
                     f"the Sharpe within {SHARPE_SLACK} of today's rule and tracks it within {TE_MAX * 100:.1f} % a year.\n")
    else:
        lines.append(f"**Picked in sample ({v['pick'] * 100:g} %), not confirmed out of sample:** "
                     + "; ".join(v["oos_failures"]) + ". The default stays at 0.2 %.\n")
    for band, why in v["in_sample_failures"].items():
        if why:
            lines.append(f"- {band} fails in sample: " + "; ".join(why))
    lines.append("")
    cols = ["book", "band", "window", "sharpe", "sharpe_stress", "cagr", "dd", "turnover_yr", "cost_yr", "te", "max_exposure"]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "---|" * len(cols))
    for r in res["rows"]:
        cells = []
        for c in cols:
            x = r[c]
            if c in ("cagr", "dd", "cost_yr", "te"):
                cells.append(f"{x * 100:.2f} %")
            elif isinstance(x, float):
                cells.append(f"{x:.3f}")
            else:
                cells.append(str(x))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def main() -> int:
    res = run()
    text = json.dumps(res, indent=1, default=float) if "--json" in sys.argv else markdown(res)
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
