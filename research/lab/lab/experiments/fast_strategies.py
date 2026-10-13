"""Fast strategies on the 15 coins Alpaca lists, on 4h and 1h bars.

    python -m lab.experiments.fast_strategies

Pre-registered in results/fast_strategies.md (the part above the marker was
committed before this file ran). Four families (Donchian trend, EMA trend,
short-term reversal, volatility breakout with a time stop), each with and
without a BTC 200-day gate, on 4h and 1h bars: 64 variants. Picks per family
and bar size by in-sample Sharpe at Alpaca taker cost (35 bps per unit of
one-way turnover: 25 bps fee plus about 10 bps slippage), judged out of sample
from 2024 with maker (15 bps) as the optimistic case. Each pick is re-run on a
survivorship-free twin (the 15 most liquid eligible coins of each day, from the
sweep's panel) and filled one bar late; a quarterly walk-forward pick over all
64 is the selection-honest series. Every one of them is counted.

Bars come from the same hourly history files the sweep's panel is built from
(picks.hourly_segments: reused tickers split into segments). The simulator is
fam_common.simulate on a bar panel; returns are compounded per UTC day before
any Sharpe is taken, so every number is comparable with the daily studies.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from . import fam_common as fc
from . import tsmom_tranches as tt

NAME = "fast_strategies"
ALPACA = tt.ALPACA
BAR_HOURS = {"4h": 4, "1h": 1}
COSTS = {"gross": 0.0, "maker 15bps": 0.0015, "taker 35bps": 0.0035}
BASE = "taker 35bps"
COIN_VOL, SLOTS = 0.40, 15
VOL_DAYS, SPIKE = 30, 1.5
START_DAYS = 60
TOP = 15
MARKER = "<!-- generated below by lab.experiments.fast_strategies; edit above this line only -->"
YEARS_OOS = (2024, 2025, 2026)

FAMILIES = {
    "T1 Donchian": [{"n": n, "vf": vf} for n, vf in itertools.product((20, 55), (False, True))],
    "T2 EMA": [{"fast": f, "slow": s, "vf": vf} for (f, s), vf in itertools.product(((12, 48), (24, 96)), (False, True))],
    "R reversal": [{"k": k, "h": h} for k, h in itertools.product((2, 3), (6, 24))],
    "V vol breakout": [{"k": k, "h": h} for k, h in itertools.product((2, 3), (6, 24))],
}


def label(fam: str, p: dict, bars: str, gate: bool) -> str:
    if fam.startswith("T1"):
        core = f"Donchian {p['n']}/{p['n'] // 2}" + (" · vol filter" if p["vf"] else "")
    elif fam.startswith("T2"):
        core = f"EMA {p['fast']}/{p['slow']}" + (" · vol filter" if p["vf"] else "")
    elif fam.startswith("R"):
        core = f"reversal {p['k']} sigma · hold {p['h']} bars"
    else:
        core = f"vol breakout {p['k']} sigma · stop {p['h']} bars"
    return f"{core} · {bars}" + (" · BTC gate" if gate else "")


# ---------------------------------------------------------------------------
# Bars
# ---------------------------------------------------------------------------

@dataclass
class Bars:
    hours: int
    ts: np.ndarray          # (T,) bar start, us
    names: list[str]
    px: np.ndarray          # close forward-filled inside the segment's life, NaN outside
    ret: np.ndarray         # bar return inside the life, NaN outside
    alive: np.ndarray
    traded: np.ndarray
    sig_prev: np.ndarray    # bar vol over the trailing 30 days up to the previous bar
    spike_ok: np.ndarray    # trailing 24h realised vol <= SPIKE x the trailing 30-day level
    day: np.ndarray         # (T,) index of the last completed UTC day at the bar's close, into the daily panel

    @property
    def T(self) -> int:
        return len(self.ts)

    @property
    def N(self) -> int:
        return len(self.names)

    @property
    def per_year(self) -> float:
        return 365 * 24 / self.hours


def hourly_frame(name: str):
    """One segment's hourly bars: the segment the daily panel calls `name`."""
    from .picks import hourly_segments
    sym, _, j = name.partition("~")
    segs = hourly_segments(sym)
    if not segs:
        return None
    return segs[int(j)] if j else segs[-1]


def from_hourly(names: list[str], t0: int, t1: int, closes: dict[str, tuple[np.ndarray, np.ndarray]],
                hours: int, day0: int) -> Bars:
    """Bars of `hours` hours on the grid [t0, t1) from per-name (open_time_us, close) arrays."""
    H = (t1 - t0) // fc.HOUR_US
    N = len(names)
    close = np.full((H, N), np.nan)
    for j, n in enumerate(names):
        ot, c = closes[n]
        i = (ot - t0) // fc.HOUR_US
        ok = (i >= 0) & (i < H)
        close[i[ok], j] = c[ok]
    traded_h = np.isfinite(close)
    idx = np.arange(H)[:, None]
    first = np.where(traded_h.any(0), np.argmax(traded_h, 0), H)
    last = np.where(traded_h.any(0), H - 1 - np.argmax(traded_h[::-1], 0), -1)
    alive_h = (idx >= first[None, :]) & (idx <= last[None, :])
    fidx = np.maximum.accumulate(np.where(traded_h, idx, 0), axis=0)
    px_h = np.where(alive_h, close[fidx, np.arange(N)[None, :]], np.nan)
    if hours > 1:
        B = H // hours
        px = px_h[: B * hours].reshape(B, hours, N)[:, -1, :]
        alive = alive_h[: B * hours].reshape(B, hours, N)[:, -1, :]
        traded = traded_h[: B * hours].reshape(B, hours, N).any(1) & alive
    else:
        px, alive, traded = px_h, alive_h, traded_h
    T = px.shape[0]
    ts = t0 + np.arange(T, dtype=np.int64) * hours * fc.HOUR_US
    ret = np.full((T, N), np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ret[1:] = np.where(alive[1:] & alive[:-1], px[1:] / px[:-1] - 1, np.nan)
    w = VOL_DAYS * 24 // hours
    var = fc.rolling(ret ** 2, w, int(w * 0.8))
    sig = np.sqrt(var)
    sig_prev = np.full_like(sig, np.nan)
    sig_prev[1:] = sig[:-1]
    w24 = 24 // hours
    var24 = fc.rolling(ret ** 2, w24, max(1, int(w24 * 0.8)))
    with np.errstate(invalid="ignore"):
        spike_ok = np.sqrt(var24) <= SPIKE * sig
    close_us = ts + hours * fc.HOUR_US
    day = (close_us - day0) // fc.DAY_US - 1
    return Bars(hours, ts, list(names), px, ret, alive, traded, sig_prev, spike_ok, day)


def load_bars(names: list[str], hours: int, P: fc.Panel) -> Bars:
    t0 = int(P.days[0])
    t1 = int(P.days[-1]) + fc.DAY_US
    closes = {}
    for n in names:
        h = hourly_frame(n)
        if h is None or h.is_empty():
            closes[n] = (np.zeros(0, dtype=np.int64), np.zeros(0))
            continue
        closes[n] = (h["open_time_us"].to_numpy(), h["close"].to_numpy().astype(float))
    return from_hourly(names, t0, t1, closes, hours, t0)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def ema(x: np.ndarray, span: int) -> np.ndarray:
    """Column-wise EMA that starts at each column's first finite value and skips NaN."""
    a = 2 / (span + 1)
    out = np.full_like(x, np.nan)
    cur = np.full(x.shape[1], np.nan)
    for t in range(x.shape[0]):
        v = x[t]
        ok = np.isfinite(v)
        cur = np.where(ok & np.isnan(cur), v, cur)
        cur = np.where(ok, cur + a * (v - cur), np.nan)
        out[t] = cur
    return out


@dataclass
class Trades:
    t_in: np.ndarray
    t_out: np.ndarray
    col: np.ndarray


def rule_weights(B: Bars, fam: str, p: dict, gate: np.ndarray | None, allowed: np.ndarray | None,
                 start: int) -> tuple[np.ndarray, Trades]:
    """Target weights (NaN = leave as it is) and the round trips the rule makes."""
    T, N = B.T, B.N
    with np.errstate(invalid="ignore", divide="ignore"):
        size = np.nan_to_num(np.minimum(COIN_VOL / (B.sig_prev * math.sqrt(B.per_year)) / SLOTS, 1.0 / SLOTS))
    alive_next = np.zeros((T, N), dtype=bool)
    alive_next[:-1] = B.alive[1:]
    timed = fam[0] in "RV"
    with np.errstate(invalid="ignore"):
        if fam.startswith("T1"):
            hi = fc.rolling_extreme(B.px, p["n"], "max")
            lo = fc.rolling_extreme(B.px, p["n"] // 2, "min")
            enter, leave = B.px > hi, B.px < lo
        elif fam.startswith("T2"):
            up = ema(B.px, p["fast"]) > ema(B.px, p["slow"])
            enter, leave = up, ~up
        elif fam.startswith("R"):
            enter, leave = B.ret < -p["k"] * B.sig_prev, np.zeros((T, N), dtype=bool)
        else:
            enter, leave = B.ret > p["k"] * B.sig_prev, np.zeros((T, N), dtype=bool)
    if p.get("vf"):
        enter = enter & B.spike_ok
    enter = enter & B.traded & (size > 0)
    if allowed is not None:
        enter = enter & allowed
    W = np.full((T, N), np.nan)
    held = np.zeros(N, dtype=bool)
    since = np.zeros(N, dtype=np.int64)
    t_in, t_out, cols = [], [], []
    open_at = np.full(N, -1)
    for t in range(start, T):
        row = np.full(N, np.nan)
        if gate is not None and not gate[t]:
            ex = held.copy()
            en = np.zeros(N, dtype=bool)
        else:
            if timed:
                ex = held & ((t - since) >= p["h"])
            else:
                ex = held & leave[t]
            ex |= held & ~alive_next[t]
            en = ~held & enter[t] & alive_next[t]
        row[ex] = 0.0
        row[en] = size[t, en]
        for j in np.flatnonzero(ex):
            t_in.append(open_at[j]); t_out.append(t); cols.append(j)
        open_at[en] = t
        since[en] = t
        held = (held & ~ex) | en
        W[t] = row
    for j in np.flatnonzero(held):          # still open at the end: marked at the last bar
        t_in.append(open_at[j]); t_out.append(T - 1); cols.append(j)
    W[:start] = 0.0
    return W, Trades(np.array(t_in, dtype=np.int64), np.array(t_out, dtype=np.int64), np.array(cols, dtype=np.int64))


def bar_panel(B: Bars) -> fc.Panel:
    """The bar data in fam_common's Panel, so fam_common.simulate runs on it unchanged."""
    z = np.zeros((B.T, B.N))
    return fc.Panel(days=B.ts, names=B.names, bases=[fc.base_of(n) for n in B.names], close=B.px, px=B.px,
                    high=B.px, low=B.px, ret=B.ret, alive=B.alive, traded=B.traded, age=z, adv28=z, sigma=z,
                    eligible=B.alive, perp_ok=np.zeros((B.T, B.N), dtype=bool), funding=z,
                    btc_on=np.ones(B.T, dtype=bool), btc=0)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

@dataclass
class Run:
    name: str
    family: str
    bars: str
    gate: bool
    gross: np.ndarray      # (D,) daily gross return
    cost_tov: np.ndarray   # (D,) turnover charged on day d (traded at an earlier bar's close)
    trades: Trades
    trade_ret: np.ndarray  # price return of each round trip
    hold_h: np.ndarray     # holding time of each round trip, hours
    trade_day: np.ndarray  # daily-panel index of each round trip's entry
    net: dict = field(default_factory=dict)   # cost -> (D,) daily net return


def simulate(B: Bars, W: np.ndarray, trades: Trades, P: fc.Panel, name: str, fam: str, bars: str, gate: bool,
             start: int, lag: int = 0) -> Run:
    """fam_common.simulate on the bars; bar returns compounded into UTC days per cost level."""
    if lag:
        W = np.vstack([np.zeros((lag, B.N)), W[:-lag]])
    g, tv, _, _ = fc.simulate(bar_panel(B), W, start=start)
    charged = np.r_[0.0, tv[:-1]]
    d = (B.ts - int(P.days[0])) // fc.DAY_US
    D = P.T
    run = Run(name, fam, bars, gate, np.zeros(D), np.zeros(D), trades, np.zeros(0), np.zeros(0), np.zeros(0))
    for c in COSTS.values():
        net = g - c * charged
        with np.errstate(invalid="ignore"):
            lg = np.log1p(np.maximum(net, -0.999999))
        run.net[c] = np.expm1(np.bincount(d, weights=lg, minlength=D)[:D])
    run.gross = run.net[0.0]
    run.cost_tov = np.bincount(d, weights=charged, minlength=D)[:D]
    ti, to = trades.t_in + lag, np.minimum(trades.t_out + lag, B.T - 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = B.px[to, trades.col] / B.px[ti, trades.col] - 1
    # A trade whose exit falls after the series ended is marked at the last close of the segment.
    bad = ~np.isfinite(r)
    if bad.any():
        last = np.array([np.flatnonzero(np.isfinite(B.px[:, j]))[-1] for j in trades.col[bad]])
        r[bad] = B.px[last, trades.col[bad]] / B.px[ti[bad], trades.col[bad]] - 1
    run.trade_ret = r
    run.hold_h = (to - ti) * B.hours
    run.trade_day = d[ti]
    return run


def describe(run: Run, P: fc.Panel) -> dict:
    ins, oos = fc.masks(P)
    yr = np.array([int(str(np.datetime64(int(x), "us").astype("datetime64[Y]"))) for x in P.days])
    row: dict = {"variant": run.name, "family": run.family, "bars": run.bars, "gate": run.gate}
    for k, c in COSTS.items():
        x = run.net[c]
        pi, po = fc.perf(x[ins]), fc.perf(x[oos])
        row[f"is_{k}"] = pi["sharpe"]
        row[f"oos_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    x = run.net[COSTS[BASE]]
    for y in YEARS_OOS:
        row[f"y{y}"] = fc.perf(x[oos & (yr == y)])["sharpe"]
    row["years_pos"] = int(sum(row[f"y{y}"] > 0 for y in YEARS_OOS))
    m = oos[np.clip(run.trade_day, 0, P.T - 1)]
    n_oos = int(oos.sum())
    row["trades_day"] = float(m.sum() / n_oos)
    row["gross_bps_trade"] = float(run.trade_ret[m].mean() * 1e4) if m.any() else float("nan")
    row["net_bps_trade"] = row["gross_bps_trade"] - 2 * COSTS[BASE] * 1e4
    row["net_bps_trade_maker"] = row["gross_bps_trade"] - 2 * COSTS["maker 15bps"] * 1e4
    row["hold_h"] = float(run.hold_h[m].mean()) if m.any() else float("nan")
    row["win_rate"] = float((run.trade_ret[m] > 2 * COSTS[BASE]).mean()) if m.any() else float("nan")
    row["turnover_yr"] = float(run.cost_tov[oos].sum() / (n_oos / 365))
    row["is_trades_day"] = float(ins[np.clip(run.trade_day, 0, P.T - 1)].sum() / max(int(ins.sum()), 1))
    row["is_gross_bps_trade"] = float(run.trade_ret[ins[np.clip(run.trade_day, 0, P.T - 1)]].mean() * 1e4) \
        if ins[np.clip(run.trade_day, 0, P.T - 1)].any() else float("nan")
    return row


def prior_mean_sharpe() -> float:
    """Mean out-of-sample Sharpe (15 bps) of the sweep's 100 trials, from results/family_*.md."""
    from ..paper.families import _md_tables
    vals = []
    for f in sorted(fc.RESULTS_DIR.glob("family_*.md")):
        for tb in _md_tables(f.read_text(encoding="utf-8")):
            for r in tb:
                if "oos_sharpe_15bps" in r and isinstance(r["oos_sharpe_15bps"], float):
                    vals.append(r["oos_sharpe_15bps"])
    return float(np.mean(np.clip(vals, -fc.SR_CLIP, fc.SR_CLIP))) if vals else 0.0


def pooled_var(mine: list[float]) -> tuple[float, dict]:
    """Variance of daily trial Sharpes over the prior 184 trials and this study's, pooled.

    The prior's variance is backed out of the blend study's bar (2.45 over 183);
    its mean is the sweep's 100 trials' mean (the 83 others are not on file)."""
    n1, v1 = tt.PRIOR_TRIALS + 1, tt.prior_var()
    m1 = prior_mean_sharpe() / math.sqrt(365)
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2, m2 = len(x), float(np.var(x)), float(np.mean(x))
    n = n1 + n2
    v = (n1 * v1 + n2 * v2 + n1 * n2 / n * (m1 - m2) ** 2) / n
    return v, {"prior_trials": n1, "prior_var": v1, "prior_mean_annual": m1 * math.sqrt(365), "mine": n2,
               "mine_var": v2, "mine_mean_annual": m2 * math.sqrt(365), "pooled_var": v, "n_total": n,
               "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def grid(B: Bars, P: fc.Panel, bars: str, gate_arr: np.ndarray, allowed: np.ndarray | None = None,
         only: tuple | None = None, lag: int = 0, suffix: str = "") -> list[tuple[Run, dict, tuple]]:
    start = START_DAYS * 24 // B.hours
    out = []
    for fam, ps in FAMILIES.items():
        for p in ps:
            for gate in (False, True):
                if only is not None and only != (fam, tuple(sorted(p.items())), gate):
                    continue
                W, tr = rule_weights(B, fam, p, gate_arr if gate else None, allowed, start)
                name = label(fam, p, bars, gate) + suffix
                run = simulate(B, W, tr, P, name, fam, bars, gate, start, lag)
                out.append((run, describe(run, P), (fam, tuple(sorted(p.items())), gate)))
    return out


def gate_for(B: Bars, P: fc.Panel) -> np.ndarray:
    d = np.clip(B.day, 0, P.T - 1)
    return np.where(B.day >= 0, P.btc_on[d], False)


def allowed_for(B: Bars, P: fc.Panel, top: np.ndarray, cols: np.ndarray) -> np.ndarray:
    d = np.clip(B.day, 0, P.T - 1)
    return np.where((B.day >= 0)[:, None], top[d][:, cols], False)


def walk_forward(runs: list[Run], P: fc.Panel) -> tuple[np.ndarray, list[str]]:
    """Each out-of-sample quarter trades the variant with the best Sharpe at 35 bps on all
    data before it (from 2020-08). Switching costs between variants are not charged."""
    c = COSTS[BASE]
    days = P.days
    q = np.array([(int(str(np.datetime64(int(x), "us").astype("datetime64[M]"))[:4]),
                   (int(str(np.datetime64(int(x), "us").astype("datetime64[M]"))[5:7]) - 1) // 3) for x in days])
    out = np.zeros(P.T)
    picks = []
    for y in YEARS_OOS:
        for k in range(4):
            m = (q[:, 0] == y) & (q[:, 1] == k)
            if not m.any():
                continue
            first = int(np.flatnonzero(m)[0])
            hist = (days >= fc.IS_START) & (np.arange(P.T) < first)
            best = max(runs, key=lambda r: fc.perf(r.net[c][hist])["sharpe"])
            out[m] = best.net[c][m]
            picks.append(f"{y}Q{k + 1}: {best.name}")
    return out, picks


def trial_row(x: np.ndarray, name: str) -> dict:
    from scipy import stats
    sd = x.std()
    return {"variant": name, "oos_sharpe_15bps": float(x.mean() / sd * math.sqrt(365)) if sd > 0 else 0.0,
            "oos_skew": float(stats.skew(x)) if sd > 0 else 0.0,
            "oos_kurt": float(stats.kurtosis(x, fisher=False)) if sd > 0 else 3.0, "oos_days": len(x)}


def main() -> None:
    P = fc.load_panel()
    ins, oos = fc.masks(P)
    alp_names = [f"{c}USDT" for c in ALPACA]
    res: dict = {"panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")), "coins": ALPACA}
    allrows, allruns, picks = [], [], []
    trials: list[tuple[str, np.ndarray]] = []
    top = P.top_liquid(TOP)
    twin_cols = np.flatnonzero(top.any(0))
    twin_names = [P.names[j] for j in twin_cols]
    for bars, h in BAR_HOURS.items():
        B = load_bars(alp_names, h, P)
        g = gate_for(B, P)
        out = grid(B, P, bars, g)
        print(bars, "grid done", flush=True)
        for run, row, key in out:
            allrows.append(row)
            allruns.append(run)
            trials.append((run.name, run.net[COSTS[BASE]][oos]))
        # Picks per family on this bar size: best in-sample Sharpe at 35 bps.
        Bt = load_bars(twin_names, h, P)
        al = allowed_for(Bt, P, top, twin_cols)
        gt = gate_for(Bt, P)
        for fam in FAMILIES:
            cand = [(run, row, key) for run, row, key in out if run.family == fam]
            run, row, key = max(cand, key=lambda x: x[1][f"is_{BASE}"])
            twin = grid(Bt, P, bars, gt, allowed=al, only=key, suffix=" · survivorship-free top 15")[0]
            late = grid(B, P, bars, g, only=key, lag=1, suffix=" · filled one bar late")[0]
            for r2, _, _ in (twin, late):
                trials.append((r2.name, r2.net[COSTS[BASE]][oos]))
            picks.append({"pick": row, "twin": twin[1], "late": late[1], "run": run})
        print(bars, "picks done", flush=True)
    wf, wf_picks = walk_forward(allruns, P)
    trials.append(("walk-forward pick by quarter", wf[oos]))
    res["walk_forward"] = {"oos": fc.perf(wf[oos]), "picks": wf_picks}

    var, pool = pooled_var([trial_row(x, n)["oos_sharpe_15bps"] for n, x in trials])
    res["pool"] = pool
    res["n_trials_here"] = len(trials)
    rng = np.random.default_rng(20261012)
    from ..metrics import deflated_sharpe
    judged = []
    for pk in picks:
        run, row = pk["run"], pk["pick"]
        x = run.net[COSTS[BASE]][oos]
        tr = trial_row(x, row["variant"])
        p = deflated_sharpe(tr["oos_sharpe_15bps"] / math.sqrt(365), tr["oos_days"], pool["n_total"], var,
                            tr["oos_skew"], tr["oos_kurt"])
        lo, hi = tt.boot_band(x, rng)
        why = []
        if row[f"oos_{BASE}"] <= 0:
            why.append(f"Sharpe at 35 bps {row[f'oos_{BASE}']:.2f} <= 0")
        if not row["net_bps_trade"] > 0:
            why.append(f"net {row['net_bps_trade']:.0f} bps per trade")
        if p <= 0.95:
            why.append(f"deflated p {p:.2f} <= 0.95")
        if pk["twin"][f"oos_{BASE}"] <= 0:
            why.append(f"survivorship-free twin {pk['twin'][f'oos_{BASE}']:.2f}")
        if row["years_pos"] < 2:
            why.append(f"positive in {row['years_pos']} of 3 years")
        judged.append({**row, "deflated_p": p, "boot35_p05": lo, "boot35_p95": hi,
                       "twin_oos_35": pk["twin"][f"oos_{BASE}"], "twin_net_bps_trade": pk["twin"]["net_bps_trade"],
                       "late_oos_35": pk["late"][f"oos_{BASE}"], "late_net_bps_trade": pk["late"]["net_bps_trade"],
                       "passes": not why, "verdict": "passes" if not why else "fails: " + "; ".join(why)})
    res["judged"] = judged
    res["grid"] = allrows
    res["twins"] = [pk["twin"] for pk in picks]
    res["late"] = [pk["late"] for pk in picks]
    res["frequency"] = frequency(allrows)
    res["trials"] = [n for n, _ in trials]
    write(res)


def frequency(rows: list[dict]) -> dict:
    """What the fee level allows: gross edge per round trip against holding time.

    For each holding-time bucket, the best and the median gross bps per round trip
    any variant delivered out of sample, against the 70 bps (taker) and 30 bps
    (maker) a round trip costs."""
    buckets = [(0, 12), (12, 48), (48, 168), (168, 10_000)]
    out = []
    for lo, hi in buckets:
        b = [r for r in rows if lo <= r["hold_h"] < hi and np.isfinite(r["gross_bps_trade"])]
        if not b:
            continue
        g = np.array([r["gross_bps_trade"] for r in b])
        out.append({"hold": f"{lo} to {hi} h" if hi < 10_000 else f"{lo} h and more", "variants": len(b),
                    "median_gross_bps": float(np.median(g)), "best_gross_bps": float(g.max()),
                    "median_trades_day": float(np.median([r["trades_day"] for r in b])),
                    "clear_taker": int((g > 70).sum()), "clear_maker": int((g > 30).sum())})
    return {"buckets": out}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write(res: dict) -> None:
    pre = (fc.RESULTS_DIR / f"{NAME}.md").read_text(encoding="utf-8")
    pre = pre.split(MARKER)[0] + MARKER + "\n"
    cols = ["variant", "trades_day", "hold_h", "gross_bps_trade", "net_bps_trade", "net_bps_trade_maker",
            "is_taker 35bps", "oos_gross", "oos_maker 15bps", "oos_taker 35bps", "dd_taker 35bps",
            "cagr_taker 35bps", "turnover_yr"]
    jc = ["variant", "trades_day", "net_bps_trade", "oos_taker 35bps", "oos_maker 15bps", "dd_taker 35bps",
          "y2024", "y2025", "y2026", "deflated_p", "boot35_p05", "boot35_p95", "twin_oos_35",
          "late_oos_35", "verdict"]
    pool = res["pool"]
    j = res["judged"]
    passed = [r for r in j if r["passes"]]
    best = max(res["grid"], key=lambda r: r["oos_taker 35bps"])
    wf = res["walk_forward"]["oos"]
    pos_taker = sum(r["oos_taker 35bps"] > 0 for r in res["grid"])
    pos_net = sum(r["net_bps_trade"] > 0 for r in res["grid"])
    pos_maker = sum(r["oos_maker 15bps"] > 0 for r in res["grid"])
    pos_gross = sum(r["oos_gross"] > 0 for r in res["grid"])
    fq = res["frequency"]["buckets"]
    md = [pre, f"\n## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']})\n\n"]
    md.append(f"**Verdict: {'a variant passes' if passed else 'nothing passes'}.** "
              f"{pos_taker} of {len(res['grid'])} variants have an out-of-sample Sharpe above 0 at taker cost "
              f"(35 bps), {pos_net} make money per trade after it, {pos_maker} are positive at maker cost "
              f"(15 bps) and {pos_gross} before any cost. The best out-of-sample variant at taker cost "
              f"({best['variant']}, picked after the fact) makes {best['oos_taker 35bps']:.2f}. The quarterly "
              f"walk-forward pick makes {wf['sharpe']:.2f} at 35 bps (drawdown {wf['max_dd'] * 100:.0f} %). "
              f"Deflation pool {pool['n_total']} trials (prior {pool['prior_trials']}, here "
              f"{res['n_trials_here']}); the best noise trial is expected at an annual Sharpe of about "
              f"{pool['sr0_annual']:.2f}.\n\n")
    md.append("### The picks, judged against the pass rule\n\nPer family and bar size, the best in-sample "
              "Sharpe at 35 bps. `trades_day` counts round trips across all 15 coins per day out of sample; "
              "`net_bps_trade` is the average round trip's price return minus 70 bps. `twin_oos_35` is the "
              "survivorship-free twin, `late_oos_35` the pick filled one bar late.\n\n")
    md.append(fc.table(j, jc))
    md.append("\n### Fee arithmetic: what a round trip earns before costs, by holding time\n\n"
              "Across all 64 variants out of sample. A round trip has to clear 70 bps at Alpaca taker cost "
              "and 30 bps at maker cost.\n\n")
    md.append(fc.table(fq, ["hold", "variants", "median_trades_day", "median_gross_bps", "best_gross_bps",
                            "clear_taker", "clear_maker"]))
    md.append("\n### Walk-forward pick by quarter\n\n" + "".join(f"- {p}\n" for p in res["walk_forward"]["picks"]))
    for bars in BAR_HOURS:
        rows = sorted([r for r in res["grid"] if r["bars"] == bars], key=lambda r: (r["family"], r["variant"]))
        md.append(f"\n### All {bars} variants (out of sample unless marked is_)\n\n" + fc.table(rows, cols))
    md.append("\n### Checks on the picks\n\n" + fc.table(res["twins"] + res["late"], cols))
    md.append(f"\n### Deflation pool\n\nPrior: {pool['prior_trials']} trials, variance of their daily Sharpes "
              f"backed out of the blend study's bar ({tt.PRIOR_SR0} over {tt.PRIOR_TRIALS}), mean "
              f"{pool['prior_mean_annual']:.2f} (the sweep's 100). Here: {pool['mine']} trials at 35 bps, mean "
              f"{pool['mine_mean_annual']:.2f}, clipped at +-3. Pooled: bar {pool['sr0_annual']:.2f} over "
              f"{pool['n_total']}.\n\nTrials counted here: " + "; ".join(res["trials"]) + ".\n")
    (fc.RESULTS_DIR / f"{NAME}.md").write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    import json
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
