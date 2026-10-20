"""X16 books on US shares and ETFs: signals, next-open fills, exits, capture, gates.

Everything here follows results/equities_training_prereg.md.

Timing. A decision uses closes up to the close of day t and is filled at the
fill price of day t + lag (lag 1: the next open; 2: a day late). A position
earns open-to-open returns (Panel.r_oo) from its fill on; the day's result is
booked on the fill day, so the daily series is indexed by the day a period
starts (its open).

Event books hold up to K slots. Each buy gets 1/K of the book at its fill, or
what cash is left if less; free slots stay in cash; a held name is not bought
again. Rebalanced books (52-week high, sectors, the equal-weight benchmark)
hold equal weights of a target set chosen on decision days, rebalanced in
full at the next fill, drifting in between.

Exits (event books): a time stop H (sold at the fill H days after the entry
fill), an ATR trail, a volatility-scaled target, or a model of the remaining
return, each decided on a close. Rebalanced books can carry an ATR trail
between rebalances (a stopped name stays in cash until the next rebalance).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats

from ..experiments import equities_ranking as er
from .panel import Panel

YEAR_DAYS = 252
SEC_FEE = 27.80e-6           # USD per USD sold
STOCK_BPS, ETF_BPS = 5.0, 2.0
BOOT_DRAWS, BOOT_BLOCK = 4_000, 20
ATR_DAYS = 14
DV_DAYS = 50
HISTORY = 252


# ---------------------------------------------------------------------------
# Inputs known at the close of day t
# ---------------------------------------------------------------------------

def _shift(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(x.shape, np.nan)
    out[k:] = x[:-k]
    return out


def _roll_std(r: np.ndarray, w: int, min_count: int) -> np.ndarray:
    mu = er._roll_mean(r, w, min_count)
    return np.sqrt(np.maximum(er._roll_mean(r * r, w, min_count) - mu * mu, 0.0))


@dataclass
class Inputs:
    """Per panel, the (T, N) inputs every rule and exit reads."""
    c: np.ndarray            # adjusted close inside the series' life, NaN outside
    r: np.ndarray            # close-to-close return
    sig21: np.ndarray        # daily vol over 21 days
    sig63: np.ndarray        # daily vol over 63 days
    atr: np.ndarray          # ATR(14) in price units
    dv50: np.ndarray         # mean dollar volume over the 50 days before t
    hist: np.ndarray         # bool: at least 252 closes up to t
    extra: dict = field(default_factory=dict)

    def hi_before(self, n: int) -> np.ndarray:
        """Highest close of the n days before t (t excluded)."""
        k = f"hi{n}"
        if k not in self.extra:
            self.extra[k] = _shift(er._roll_max(self.c, n))
        return self.extra[k]

    def hi_incl(self, n: int) -> np.ndarray:
        k = f"hii{n}"
        if k not in self.extra:
            self.extra[k] = er._roll_max(self.c, n)
        return self.extra[k]

    def mom(self, n: int) -> np.ndarray:
        k = f"mom{n}"
        if k not in self.extra:
            self.extra[k] = er._lag_ratio(self.c, 0, n)
        return self.extra[k]


def inputs(P: Panel) -> Inputs:
    if "inputs" in P.extra:
        return P.extra["inputs"]
    c = np.where(P.alive, P.close, np.nan)
    r = np.full(c.shape, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r[1:] = c[1:] / c[:-1] - 1
    pc = _shift(c)
    hi = np.where(np.isfinite(P.high), np.fmax(P.high, pc), np.nan)
    lo = np.where(np.isfinite(P.low), np.fmin(P.low, pc), np.nan)
    tr = np.where(np.isfinite(hi) & np.isfinite(lo), hi - lo, np.abs(c - pc))
    tr = np.where(P.traded, tr, np.nan)
    dv = np.where(P.traded & (P.dv > 0), P.dv, np.nan)
    n_hist = np.cumsum(np.isfinite(c), axis=0)
    out = Inputs(c=c, r=r, sig21=_roll_std(r, 21, 17), sig63=_roll_std(r, 63, 50),
                 atr=er._roll_mean(tr, ATR_DAYS, 10), dv50=_shift(er._roll_mean(dv, DV_DAYS, 40)),
                 hist=n_hist >= HISTORY)
    P.extra["inputs"] = out
    return out


def spy_regime(E: Panel) -> np.ndarray:
    """(T,) SPY's close above its 200-day average, known at the close."""
    c = E.close[:, E.col("SPY")]
    ma = er._roll_mean(c[:, None], 200, 200)[:, 0]
    return np.isfinite(ma) & (c > ma)


def month_ends(dates: np.ndarray) -> np.ndarray:
    m = dates.astype("datetime64[M]")
    out = np.zeros(len(dates), dtype=bool)
    out[:-1] = m[1:] != m[:-1]
    out[-1] = False             # the month is not over on the data's last day
    return out


# ---------------------------------------------------------------------------
# Part A signals: (T, N) bool candidates and a (T, N) strength to rank them
# ---------------------------------------------------------------------------

def base_ok(P: Panel, X: Inputs) -> np.ndarray:
    return P.member & P.traded & X.hist & np.isfinite(X.c)


def breakout(P: Panel, X: Inputs, n: int, k: float) -> tuple[np.ndarray, np.ndarray]:
    dv = np.where(P.traded, P.dv, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = dv / X.dv50
        sig = base_ok(P, X) & (X.c > X.hi_before(n)) & (ratio >= k)
    return sig, ratio


def gap_go(P: Panel, X: Inputs, g: float, vol_k: float = 2.0) -> tuple[np.ndarray, np.ndarray]:
    pc = _shift(X.c)
    dv = np.where(P.traded, P.dv, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        gap = P.open / pc - 1
        sig = (base_ok(P, X) & np.isfinite(P.open) & (gap >= g) & (X.c >= P.open)
               & (dv / X.dv50 >= vol_k))
    return sig, gap


@dataclass
class Pead:
    z: np.ndarray            # (T, N) at the reaction window's last day, NaN elsewhere
    av: np.ndarray           # abnormal dollar volume there
    has_cik: np.ndarray      # (N,)
    n_events: int


def pead_inputs(P: Panel, E: Panel, X: Inputs, start: np.ndarray, has_cik: np.ndarray) -> Pead:
    """z and AV at the close of the window's second day for every event (window = the first
    trading day on or after the filing date and the next one)."""
    spy = E.close[:, E.col("SPY")]
    z = np.full((P.T, P.N), np.nan)
    av = np.full((P.T, P.N), np.nan)
    dv = np.where(P.traded, P.dv, np.nan)
    tt, jj = np.nonzero(start)
    n = 0
    for t0, j in zip(tt, jj):
        t1 = t0 + 1
        if t0 < 64 or t1 >= P.T:
            continue
        c_before, c1 = X.c[t0 - 1, j], X.c[t1, j]
        s = X.sig63[t0 - 1, j]
        if not (np.isfinite(c_before) and np.isfinite(c1) and np.isfinite(s) and s > 0):
            continue
        ar = c1 / c_before - 1 - (spy[t1] / spy[t0 - 1] - 1)
        z[t1, j] = ar / (s * math.sqrt(2))
        base = X.dv50[t0, j]
        win = np.nanmean(dv[t0:t1 + 1, j]) if np.isfinite(dv[t0:t1 + 1, j]).any() else np.nan
        av[t1, j] = win / base if np.isfinite(base) and base > 0 else np.nan
        n += 1
    return Pead(z=z, av=av, has_cik=has_cik, n_events=n)


def pead(P: Panel, X: Inputs, pd: Pead, z_min: float, vol_filter: bool) -> tuple[np.ndarray, np.ndarray]:
    with np.errstate(invalid="ignore"):
        sig = base_ok(P, X) & np.isfinite(pd.z) & (pd.z >= z_min)
        if vol_filter:
            sig &= np.isfinite(pd.av) & (pd.av >= 2.0)
    return sig, pd.z


def high52_targets(P: Panel, X: Inputs, k: int, days: np.ndarray, regime: np.ndarray | None) -> dict[int, np.ndarray]:
    """Month ends: the k members closest to their 52-week high (ties by 12-month return)."""
    ok = base_ok(P, X)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = X.c / X.hi_incl(HISTORY)
    m12 = X.mom(HISTORY)
    out = {}
    for t in np.flatnonzero(days):
        if regime is not None and not regime[t]:
            out[t] = np.array([], dtype=int)
            continue
        e = np.flatnonzero(ok[t] & np.isfinite(ratio[t]))
        if e.size < k:
            continue
        order = np.lexsort((-np.nan_to_num(m12[t, e], nan=-9.0), -ratio[t, e]))
        out[t] = e[order[:k]]
    return out


def sector_targets(E: Panel, look: int | str, m: int, days: np.ndarray, regime: np.ndarray | None) -> dict[int, np.ndarray]:
    """Month ends: the m sector ETFs with the strongest total return over `look` days, or
    ("blend") the best mean rank over 63, 126 and 252 days; an ETF needs that history."""
    cols = np.array([E.col(s) for s in E.names if s != "SPY"])
    c = np.where(E.alive, E.close, np.nan)
    looks = (63, 126, 252) if look == "blend" else (int(look),)
    rets = {L: er._lag_ratio(c, 0, L) for L in looks}
    out = {}
    for t in np.flatnonzero(days):
        if regime is not None and not regime[t]:
            out[t] = np.array([], dtype=int)
            continue
        ok = np.all([np.isfinite(rets[L][t, cols]) for L in looks], axis=0)
        e = cols[ok]
        if e.size < m:
            continue
        if look == "blend":
            score = np.mean([stats.rankdata(rets[L][t, e]) for L in looks], axis=0)
        else:
            score = rets[looks[0]][t, e]
        out[t] = e[np.argsort(-score, kind="stable")[:m]]
    return out


def ew_targets(P: Panel, X: Inputs, days: np.ndarray, cols_ok: np.ndarray | None = None) -> dict[int, np.ndarray]:
    ok = base_ok(P, X) if cols_ok is None else base_ok(P, X) & cols_ok[None, :]
    return {t: np.flatnonzero(ok[t]) for t in np.flatnonzero(days)}


# ---------------------------------------------------------------------------
# Exits
# ---------------------------------------------------------------------------

@dataclass
class Exit:
    kind: str = "time"              # time, atr, target, model, none (rebalanced books)
    H: int = 10                     # time stop (and the target's horizon and fallback)
    k: float = 0.0                  # ATR multiple
    m: float = 0.0                  # target multiple of vol x sqrt(H)
    cap: int | None = None          # longest hold for atr and model
    thr: float = 0.0                # model: sell when the forecast log return is below this
    pred: np.ndarray | None = field(default=None, repr=False)   # (T, N) model forecast at close t
    # model: fn(t, cols, entry days, entry prices, peaks) -> forecast log returns of the held names
    model_fn: object = field(default=None, repr=False)

    def label(self) -> str:
        if self.kind == "time":
            return f"time {self.H}"
        if self.kind == "atr":
            return f"ATR {self.k:g}" + (f", cap {self.cap}" if self.cap else "")
        if self.kind == "target":
            return f"target {self.m:g}, time {self.H}"
        if self.kind == "model":
            return "model" + (f", cap {self.cap}" if self.cap else "")
        return "none"


# ---------------------------------------------------------------------------
# The simulator
# ---------------------------------------------------------------------------

@dataclass
class Run:
    gross: np.ndarray        # (T,) open-to-open, booked on the period's first day
    turnover: np.ndarray     # (T,) traded at that day's fill, in book units
    sells: np.ndarray        # (T,) of which sold
    expo: np.ndarray         # (T,) invested share after that day's trades
    close_fills: int = 0     # fills at the close (no open known)
    fills: int = 0
    trades: list = field(default_factory=list)   # closed trades: dicts
    held: list = field(default_factory=list)     # (t, j, entry_day, entry_px, peak) per held close, when recorded

    def net(self, bps: float) -> np.ndarray:
        return self.gross - bps * 1e-4 * self.turnover - SEC_FEE * self.sells


@dataclass
class _Pos:
    entry: int
    px: float
    peak: float
    sigma: float


def simulate(P: Panel, *, sig: np.ndarray | None = None, strength: np.ndarray | None = None, K: int = 20,
             targets: dict[int, np.ndarray] | None = None, exit: Exit | None = None, lag: int = 1,
             regime: np.ndarray | None = None, start: int = 0, record: bool = False) -> Run:
    """An event book (sig, strength, K) or a rebalanced book (targets: decision day -> columns,
    equal weight). Decisions at the close of t, fills at t + lag."""
    X = inputs(P)
    F = P.fill()
    R = P.r_oo()
    at_close = P.fill_at_close()
    T, N = P.T, P.N
    ex = exit or Exit("none" if targets is not None else "time")
    rebalanced = targets is not None
    w = np.zeros(N)
    gross, tov, sells, expo = np.zeros(T), np.zeros(T), np.zeros(T), np.zeros(T)
    pos: dict[int, _Pos] = {}
    sell_at: dict[int, set] = {}
    buy_at: dict[int, list] = {}
    rebal_at: dict[int, np.ndarray] = {}
    pend_sell: set = set()
    pend_buy: set = set()
    run = Run(gross, tov, sells, expo)
    alive_next = np.zeros_like(P.alive)
    alive_next[:-1] = P.alive[1:]

    def close_trade(j: int, t: int) -> None:
        p = pos.pop(j)
        run.trades.append({"j": j, "entry": p.entry, "exit": t, "entry_px": p.px, "exit_px": float(F[t, j]),
                           "peak": p.peak})

    for t in range(start, T):
        # ---- fills at the open of t
        out = sell_at.pop(t, set())
        for j in out:
            pend_sell.discard(j)
            if j in pos:
                tov[t] += w[j]
                sells[t] += w[j]
                w[j] = 0.0
                close_trade(j, t)
                run.fills += 1
                run.close_fills += int(at_close[t, j])
        if t in rebal_at:
            tgt = rebal_at.pop(t)
            tgt = tgt[np.isfinite(F[t, tgt]) & P.alive[t, tgt]]
            new = np.zeros(N)
            if tgt.size:
                new[tgt] = 1.0 / tgt.size
            d = new - w
            tov[t] += np.abs(d).sum()
            sells[t] += -d[d < 0].sum()
            for j in list(pos):
                if new[j] == 0:
                    close_trade(j, t)
            for j in tgt:
                if j not in pos:
                    pos[j] = _Pos(t, float(F[t, j]), float(F[t, j]), float(X.sig63[max(t - lag, 0), j]))
            moved = np.flatnonzero(np.abs(d) > 1e-12)
            run.fills += moved.size
            run.close_fills += int(at_close[t, moved].sum())
            w = new
        for j in buy_at.pop(t, []):
            pend_buy.discard(j)
            if j in pos or len(pos) >= K or not np.isfinite(F[t, j]) or not P.alive[t, j]:
                continue
            cash = 1.0 - w.sum()
            amt = min(1.0 / K, cash)
            if amt < 0.25 / K:
                continue
            w[j] = amt
            tov[t] += amt
            pos[j] = _Pos(t, float(F[t, j]), float(F[t, j]), float(X.sig63[max(t - lag, 0), j]))
            run.fills += 1
            run.close_fills += int(at_close[t, j])
        expo[t] = w.sum()
        # ---- the day: open t to open t+1
        r = R[t]
        g = float(w @ r)
        gross[t] = g
        if 1 + g > 0:
            w = w * (1 + r) / (1 + g)
        else:
            w = np.zeros(N)
        # ---- the close of t: exits, then new decisions
        ct = X.c[t]
        for j, p in pos.items():
            if np.isfinite(ct[j]):
                p.peak = max(p.peak, float(ct[j]))
            if record:
                run.held.append((t, j, p.entry, p.px, p.peak))
        when = t + lag
        if when >= T:
            continue
        fc = {}
        if ex.kind == "model" and ex.model_fn is not None and pos:
            js = np.array([j for j in pos if j not in pend_sell], dtype=int)
            if js.size:
                f = ex.model_fn(t, js, np.array([pos[j].entry for j in js]), np.array([pos[j].px for j in js]),
                                np.array([pos[j].peak for j in js]))
                fc = dict(zip(js.tolist(), np.asarray(f, float).tolist()))
        for j, p in list(pos.items()):
            if j in pend_sell:
                continue
            days = t - p.entry + 1
            c = ct[j]
            go = not alive_next[t, j]
            if not go and np.isfinite(c):
                if ex.kind == "time":
                    go = days >= ex.H
                elif ex.kind == "atr":
                    a = X.atr[t, j]
                    go = (np.isfinite(a) and c < p.peak - ex.k * a) or (ex.cap is not None and days >= ex.cap)
                elif ex.kind == "target":
                    s = p.sigma if np.isfinite(p.sigma) else X.sig63[t, j]
                    go = days >= ex.H or (np.isfinite(s) and c >= p.px * (1 + ex.m * s * math.sqrt(ex.H)))
                elif ex.kind == "model":
                    f = fc.get(j, np.nan) if ex.model_fn is not None else (
                        ex.pred[t, j] if ex.pred is not None else np.nan)
                    go = (np.isfinite(f) and f < ex.thr) or (ex.cap is not None and days >= ex.cap)
            if go:
                sell_at.setdefault(when, set()).add(j)
                pend_sell.add(j)
        if rebalanced:
            if t in targets:
                rebal_at[when] = np.asarray(targets[t], dtype=int)
            continue
        if regime is not None and not regime[t]:
            continue
        cand = np.flatnonzero(sig[t])
        if cand.size == 0:
            continue
        cand = np.array([j for j in cand if j not in pos and j not in pend_buy], dtype=int)
        if cand.size == 0:
            continue
        free = K - (len(pos) - len(pend_sell & set(pos))) - len(pend_buy)
        if free <= 0:
            continue
        s = strength[t, cand]
        order = cand[np.argsort(-np.nan_to_num(s, nan=-np.inf), kind="stable")][:free]
        lst = buy_at.setdefault(when, [])
        for j in order:
            lst.append(int(j))
            pend_buy.add(int(j))
    return run


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    x = x[np.isfinite(x)]
    sd = x.std()
    return float(x.mean() / sd * math.sqrt(YEAR_DAYS)) if x.size > 1 and sd > 0 else 0.0


def perf(x: np.ndarray) -> dict:
    x = x[np.isfinite(x)]
    if x.size < 2:
        return {"sharpe": 0.0, "cagr": 0.0, "vol": 0.0, "max_dd": 0.0, "days": int(x.size)}
    eq = np.cumprod(1 + x)
    dd = 1 - eq / np.maximum.accumulate(eq)
    yrs = x.size / YEAR_DAYS
    return {"sharpe": sharpe(x), "cagr": float(eq[-1] ** (1 / yrs) - 1) if eq[-1] > 0 else -1.0,
            "vol": float(x.std() * math.sqrt(YEAR_DAYS)), "max_dd": float(dd.max()), "days": int(x.size)}


def alpha_beta(x: np.ndarray, m: np.ndarray) -> tuple[float, float]:
    """Annualised OLS intercept and the slope of x on m."""
    ok = np.isfinite(x) & np.isfinite(m)
    x, m = x[ok], m[ok]
    if x.size < 20 or m.var() == 0:
        return 0.0, 0.0
    b = float(np.cov(x, m, ddof=0)[0, 1] / m.var())
    return float((x.mean() - b * m.mean()) * YEAR_DAYS), b


def years(dates: np.ndarray) -> np.ndarray:
    return dates.astype("datetime64[Y]").astype(int) + 1970


def per_year(dates: np.ndarray, x: np.ndarray, m: np.ndarray, mask: np.ndarray) -> dict[int, dict]:
    yr = years(dates)
    out = {}
    for y in np.unique(yr[mask]):
        k = mask & (yr == y)
        a, b = alpha_beta(x[k], m[k])
        out[int(y)] = {"ret": float(np.prod(1 + x[k]) - 1), "spy": float(np.prod(1 + m[k]) - 1),
                       "alpha": a, "beta": b, "sharpe": sharpe(x[k])}
    return out


def boot_indices(n: int, rng: np.random.Generator, draws: int = BOOT_DRAWS, block: int = BOOT_BLOCK) -> np.ndarray:
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    jump = rng.random((draws, n)) < 1 / block
    fresh = rng.integers(0, n, (draws, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)
    return idx


def boot_diff(x: np.ndarray, y: np.ndarray, rng: np.random.Generator, idx: np.ndarray | None = None) -> dict:
    """Stationary bootstrap (20-day blocks) of Sharpe(x) - Sharpe(y) on the same days."""
    idx = boot_indices(len(x), rng) if idx is None else idx

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(YEAR_DAYS), 0.0)

    d = sr(x) - sr(y)
    return {"p05": float(np.percentile(d, 5)), "p95": float(np.percentile(d, 95)), "share_above_0": float((d > 0).mean())}


def capture(run: Run, P: Panel, after: int = 20) -> dict:
    """Per closed trade: realised, MFE (highest close held over the entry fill), capture
    (realised / MFE where MFE > 0), give-back and left on the table after the exit."""
    X = inputs(P)
    rows = []
    for tr in run.trades:
        j, e, x = tr["j"], tr["entry"], tr["exit"]
        if x <= e:
            continue
        held_c = X.c[e:x, j]
        if not np.isfinite(held_c).any():
            continue
        peak = float(np.nanmax(held_c))
        mfe = peak / tr["entry_px"] - 1
        real = tr["exit_px"] / tr["entry_px"] - 1
        post = X.c[x:x + after, j]
        lot = float(np.nanmax(post) / tr["exit_px"] - 1) if np.isfinite(post).any() else float("nan")
        rows.append((real, mfe, real / mfe if mfe > 0 else np.nan, mfe - real, lot, x - e))
    if not rows:
        return {"trades": 0}
    a = np.array(rows)

    def q(v: np.ndarray) -> list[float]:
        v = v[np.isfinite(v)]
        return [float(x) for x in np.percentile(v, [25, 50, 75])] if v.size else [float("nan")] * 3

    return {"trades": int(len(a)), "realised_q": q(a[:, 0]), "mfe_q": q(a[:, 1]), "capture_q": q(a[:, 2]),
            "giveback_q": q(a[:, 3]), "left_q": q(a[:, 4]), "days_q": q(a[:, 5]),
            "share_mfe_pos": float(np.mean(a[:, 1] > 0)), "share_lost_gain": float(np.mean((a[:, 1] > 0) & (a[:, 0] <= 0))),
            "mean_realised": float(np.mean(a[:, 0])), "mean_mfe": float(np.mean(a[:, 1]))}
