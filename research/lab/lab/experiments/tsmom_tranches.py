"""tsmom_top20 rebalanced weekly in seven daily tranches: the simulator the paper book uses, and its evidence.

    python -m lab.experiments.tsmom_tranches

The rule is the blend study's weekday-free weekly book ("B · seven weekly
tranches · band 50 %", counted there as one of 183 trials): the momentum
targets of tsmom_top20 (fam_volmom.base_weights: 28-day return positive, top 20
by volume each day, BTC 200-day regime, 40 % vol per coin over the slots), held
by seven sub-accounts. Tranche k rebalances only on the days whose calendar
index d (days since ANCHOR) has d % 7 == k, with a 50 % no-trade band; every 30
days (d % 30 == 0) the seven sub-accounts are set back to 1/7 of the book each.
With a panel starting at ANCHOR this is exactly blend_study.blend over seven
blend_study.sim_long books (asserted in the tests); the calendar phase makes it
independent of where a panel starts, so the paper book and the backtest agree
on which tranche is due on which date.

The evidence re-runs the book on the sweep's survivorship-free daily panel at
the lab's costs (15 and 41 bps per unit of one-way turnover) and at Alpaca-like
costs: taker 25 bps plus about 10 bps of measured slippage per side (35 bps),
and maker 15 bps as the optimistic case. Restricted to the 15 coins Alpaca
lists, the same targets are reported as a check (counted as a trial). No new
variant was tuned: the rule, lookback, band and tranche count are the blend
study's. Writes results/tsmom_tranches.md and <agent-strategies>/reports/tsmom_tranches.json.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

import numpy as np

from . import fam_common as fc
from . import fam_volmom

NAME = "tsmom_tranches"
VARIANT = "tsmom 28d · top 20 · regime · seven weekly tranches · band 50 %"
ANCHOR_US = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
K, RESET, BAND, START = 7, 30, 0.5, 60
ALPACA = ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "LTC", "DOT", "BCH", "UNI", "AAVE", "PEPE", "FIL")
# 15 bps is both the lab's usual cost and Alpaca's maker fee.
COSTS = {"maker 15bps": 0.0015, "taker 35bps": 0.0035, "41bps": 0.0041, "taker x2 70bps": 0.0070}
# The blend study's published bar: the best of its 183 trials' noise counterparts.
PRIOR_TRIALS, PRIOR_SR0 = 183, 2.45
BOOT_DRAWS, BOOT_BLOCK = 4000, 20


def day_index(days_us: np.ndarray | int) -> np.ndarray | int:
    """Calendar days since ANCHOR; tranche k is due when this is k modulo 7."""
    return (np.asarray(days_us, dtype=np.int64) - ANCHOR_US) // fc.DAY_US


def due_tranche(day_us: int) -> int:
    return int(day_index(day_us)) % K


def band_target(w: np.ndarray, tgt: np.ndarray, band: float) -> np.ndarray:
    """blend_study.sim_long's no-trade band: a held coin that stays held is resized only
    when |target - current| > band x target; entries and exits always trade."""
    if band <= 0:
        return tgt
    resize = (w > 0) & (tgt > 0)
    small = resize & (np.abs(tgt - w) <= band * np.where(resize, tgt, 1.0))
    return np.where(small, w, tgt)


def simulate(P: fc.Panel, W: np.ndarray, start: int = START, band: float = BAND, until: int | None = None,
             record: bool = False):
    """The seven-tranche book on weights W (T, N), long-only.

    Returns (gross, turnover, expo, alloc, inner, held): gross return earned on
    day t, one-way turnover traded at the close of day t (charged on t+1),
    exposure after the close of t; the state after the close of day `until`
    (default the last day): alloc (K,) the share of the book each tranche holds
    and inner (K, N) each tranche's weights as a share of that tranche; and with
    `record` the book's combined weights after every close, (T, N), else None.
    """
    T, N = W.shape
    last = T - 1 if until is None else until
    d = day_index(P.days)
    alloc, inner = np.zeros(K), np.zeros((K, N))
    dead_tv = np.zeros(K)
    gross, tov, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    held = np.zeros((T, N)) if record else None
    for t in range(start, last + 1):
        tv = dead_tv.copy()
        k = int(d[t] % K)
        tgt = np.where(np.isnan(W[t]), inner[k], W[t])
        tgt = np.where(P.traded[t] | (tgt == inner[k]), tgt, inner[k])
        tgt = band_target(inner[k], tgt, band)
        tv[k] += np.abs(tgt - inner[k]).sum()
        inner[k] = tgt
        ex = inner.sum(1)
        a = np.full(K, 1.0 / K) if (t == start or d[t] % RESET == 0) else alloc.copy()
        e = float((a * ex).sum())
        if e > 1 + 1e-9:                # float drift of a fully invested book is not a breach
            a = a / e
        tov[t] += float((np.abs(a - alloc) * ex).sum() + (a * tv).sum())
        alloc = a
        expo[t] = float((alloc * ex).sum())
        if record:
            held[t] = alloc @ inner
        if t == last or t == T - 1:
            break
        r = np.nan_to_num(P.ret[t + 1])
        gk = inner @ r
        g = float((alloc * gk).sum())
        gross[t + 1] = g
        alloc = alloc * (1 + gk) / (1 + g) if 1 + g > 0 else np.zeros(K)
        for j in range(K):
            inner[j] = inner[j] * (1 + r) / (1 + gk[j]) if 1 + gk[j] > 0 else 0.0
        # A coin whose series ended is closed at its last close; charged at the next close.
        dead = (inner != 0) & ~P.alive[t + 1][None, :]
        dead_tv = np.abs(np.where(dead, inner, 0.0)).sum(1)
        inner[dead] = 0.0
    return gross, tov, expo, alloc, inner, held


def reset_due(day_us: int) -> bool:
    """Whether a close sets the tranches back to 1/7 each (as `simulate`, after its first day)."""
    return int(day_index(day_us)) % RESET == 0


def targets(P: fc.Panel) -> np.ndarray:
    """The momentum targets every tranche rebalances to: tsmom_top20's own weights."""
    return fam_volmom.base_weights(P, 20, regime=True)


def book_weights(P: fc.Panel, W: np.ndarray, t: int) -> np.ndarray:
    """What the backtest holds after the close of day t, as shares of the whole book."""
    _, _, _, alloc, inner, _ = simulate(P, W, until=t)
    return np.clip(alloc @ inner, 0.0, None)


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

def _net(gross: np.ndarray, tov: np.ndarray, cost: float) -> np.ndarray:
    return gross - cost * np.r_[0.0, tov[:-1]]


def prior_var() -> float:
    """Variance of the daily trial Sharpes implied by the blend study's bar (2.45 over 183 trials)."""
    g = 0.5772156649
    from scipy import stats
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def deflate(x: np.ndarray, n_trials: int, var: float) -> float:
    from scipy import stats
    from ..metrics import deflated_sharpe
    s = x.mean() / x.std() if x.std() > 0 else 0.0
    return deflated_sharpe(float(s), len(x), n_trials, var, float(stats.skew(x)), float(stats.kurtosis(x, fisher=False)))


def boot_band(x: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """5 % and 95 % of the annual Sharpe over stationary-bootstrap resamples."""
    n = len(x)
    idx = np.empty((BOOT_DRAWS, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, BOOT_DRAWS)
    jump = rng.random((BOOT_DRAWS, n)) < 1 / BOOT_BLOCK
    fresh = rng.integers(0, n, (BOOT_DRAWS, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    s = x[idx]
    sd = s.std(1)
    sr = np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * np.sqrt(365), 0.0)
    return float(np.percentile(sr, 5)), float(np.percentile(sr, 95))


def describe(P: fc.Panel, name: str, gross: np.ndarray, tov: np.ndarray, expo: np.ndarray) -> dict:
    ins, oos = fc.masks(P)
    yr = np.array([int(str(np.datetime64(int(d), "us").astype("datetime64[Y]"))) for d in P.days])
    row: dict = {"variant": name}
    for k, c in COSTS.items():
        n = _net(gross, tov, c)
        pi, po = fc.perf(n[ins]), fc.perf(n[oos])
        row[f"is_{k}"] = pi["sharpe"]
        row[f"oos_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    row["turnover_yr"] = float(tov[oos].sum() / (oos.sum() / 365))
    row["expo"] = float(expo[oos].mean())
    on_prev = np.r_[False, P.btc_on[:-1]]
    n35 = _net(gross, tov, COSTS["taker 35bps"])
    row["oos_btc_above"] = fc.perf(n35[oos & on_prev])["sharpe"]
    row["oos_btc_below"] = fc.perf(n35[oos & ~on_prev])["sharpe"]
    for y in range(2021, 2027):
        m = (P.days >= fc.IS_START) & (yr == y)
        row[f"y{y}"] = fc.perf(n35[m])["sharpe"]
    row["oos_days"] = int(oos.sum())
    return row


def main() -> None:
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    W = targets(P)
    g, tv, ex, _, _, held = simulate(P, W, record=True)
    rows = [describe(P, VARIANT, g, tv, ex)]
    # Daily rebalance, the tsmom_top20 book itself, for reference (already in the sweep).
    gd, tvd, led, _ = fc.simulate(P, W, start=START)
    rows.append(describe(P, "tsmom_top20, daily (reference)", gd, tvd, led))
    # Check, counted: the same targets restricted to the coins Alpaca lists.
    alp = np.array([b in ALPACA and "~" not in n for b, n in zip(P.bases, P.names)])
    Wa = np.where(alp[None, :], W, 0.0)
    ga, tva, exa, _, _, _ = simulate(P, Wa)
    rows.append(describe(P, VARIANT + " · Alpaca coins only (check)", ga, tva, exa))

    rng = np.random.default_rng(20261012)
    var = prior_var()
    n_trials = PRIOR_TRIALS + 1             # the Alpaca-only check is new; the base was counted
    for r, (gg, tt) in zip(rows, ((g, tv), (gd, tvd), (ga, tva))):
        x15 = _net(gg, tt, 0.0015)[oos]
        x35 = _net(gg, tt, COSTS["taker 35bps"])[oos]
        r["deflated_p"] = deflate(x15, n_trials, var)
        r["boot35_p05"], r["boot35_p95"] = boot_band(x35, rng)
    # Share of the book's exposure out of sample in coins Alpaca does not list.
    tot = held[oos].sum(1)
    share = np.where(tot > 0, held[oos][:, ~alp].sum(1) / np.where(tot > 0, tot, 1), np.nan)
    res = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")),
           "segments": P.N, "rows": rows, "n_trials": n_trials, "sr0_annual": PRIOR_SR0,
           "non_alpaca_share": float(np.nanmean(share)), "variant": VARIANT}
    write(res)


def write(res: dict) -> None:
    rows = res["rows"]
    b = rows[0]
    cols = ["variant", "is_taker 35bps", "oos_maker 15bps", "oos_taker 35bps", "oos_41bps", "oos_taker x2 70bps",
            "cagr_taker 35bps", "dd_taker 35bps", "turnover_yr", "expo", "deflated_p", "boot35_p05", "boot35_p95"]
    years = ["variant"] + [f"y{y}" for y in range(2021, 2027)] + ["oos_btc_above", "oos_btc_below"]
    md = [f"# tsmom_tranches (generated {datetime.now(timezone.utc):%Y-%m-%d})\n\n",
          "`python -m lab.experiments.tsmom_tranches`. The paper book `tsmom_tranches` "
          "(lab/paper/families.py) runs this rule. Survivorship-free daily panel "
          f"({res['segments']} coin segments, delisted coins included) to {res['panel_end']}. "
          "In sample 2020-08 to 2023, out of sample from 2024-01-01. Costs per unit of one-way "
          "turnover: Alpaca maker 15 bps (also the lab's usual figure; optimistic for Alpaca, no slippage and "
          "every order filled), Alpaca taker 25 bps plus about 10 bps measured slippage (35 bps), the lab's "
          "41 bps, and taker doubled (70 bps).\n\n",
          "## Out of sample\n\n", fc.table(rows, cols), "\n",
          "## Per year (Sharpe at 35 bps, 2021 to 2026) and by BTC regime\n\n", fc.table(rows, years), "\n",
          "## Reading\n\n",
          f"- At Alpaca taker cost the tranche book makes an out-of-sample Sharpe of {b['oos_taker 35bps']:.2f} "
          f"(maker {b['oos_maker 15bps']:.2f}, taker doubled {b['oos_taker x2 70bps']:.2f}) with a "
          f"{b['dd_taker 35bps'] * 100:.0f} % drawdown and {b['turnover_yr']:.1f}x turnover a year; "
          f"the daily-rebalanced tsmom_top20 makes {rows[1]['oos_taker 35bps']:.2f} at the same cost.\n",
          f"- Deflated p {b['deflated_p']:.2f} over {res['n_trials']} trials (the blend study's 183 plus the "
          f"Alpaca-only check here; bar about {res['sr0_annual']:.2f}). It fails the lab's deflation bar. The "
          f"90 % bootstrap band of the Sharpe at 35 bps is {b['boot35_p05']:.2f} to {b['boot35_p95']:.2f}.\n",
          f"- On average {res['non_alpaca_share'] * 100:.0f} % of the book's exposure out of sample sits in "
          "coins Alpaca does not list (TRX, SUI, NEAR, ATOM, XLM and coins outside the engine's 20); an "
          "autopilot on Alpaca holds that part as cash. The Alpaca-only row is that book.\n",
          "- Caveat: forward evidence only. The rule was picked in the blend study as the weekday-free form "
          "of a weekly pick whose own number was weekday luck; nothing here was tuned again.\n"]
    fc.write_result(NAME, "".join(md), res)


if __name__ == "__main__":
    main()
