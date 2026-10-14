"""M7: a market regime model (Gaussian HMM) as a gate for the books.

    python -m lab.experiments.regime_hmm

Pre-registered in results/regime_hmm.md (the part above the marker was
committed before this file ran). Daily features of BTC and the whole market
(7-day return, realised vol, breadth, volume trend, funding) feed a Gaussian
HMM with 2 to 4 states, refitted at every month end on an expanding window.
Only filtered probabilities are used: P(state on day t) comes from a forward
pass over features up to t with parameters fitted on data up to the last month
end on or before t. The filtered probability of the "bull" states becomes a
book-level exposure scale (soft) or an on/off switch with hysteresis, applied
as an overlay to the ungated books, and is compared with the 200-day rule and
with no gate, out of sample from 2024 at Alpaca-like costs.

Writes results/regime_hmm.md and <agent-strategies>/reports/regime_hmm.json.
"""

from __future__ import annotations

import itertools
import json
import math
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np
from scipy import stats

from ..data import UNIVERSE
from ..metrics import deflated_sharpe
from . import fam_breakout, fam_common as fc, fam_volmom
from . import tsmom_tranches as tt

NAME = "regime_hmm"
MARKER = "<!-- generated below by lab.experiments.regime_hmm; edit above this line only -->"
COSTS = {"maker 15bps": 0.0015, "taker 35bps": 0.0035, "stress 70bps": 0.0070}
BASE = "taker 35bps"
START = 60
FIRST_FIT = int(datetime(2021, 3, 31, tzinfo=timezone.utc).timestamp() * 1e6)
SEL_START = int(datetime(2021, 7, 1, tzinfo=timezone.utc).timestamp() * 1e6)
YEARS = (2021, 2022, 2023, 2024, 2025, 2026)
YEARS_OOS = (2024, 2025, 2026)
FEATURE_SETS = {"price": ("r7", "vol14", "breadth"), "full": ("r7", "vol14", "breadth", "volume", "funding")}
STATES = (2, 3, 4)
MAPPINGS = ("soft", "switch")
ON, OFF = 0.6, 0.4
MIN_COVAR, N_ITER, TOL, SEEDS = 1e-3, 200, 1e-4, (0, 1, 2)
# The prior pool: every trial counted before this study and its published bar.
PRIOR_TRIALS, PRIOR_SR0 = 265, 2.74
HERE_TRIALS = 66
BOOKS = ("breakout_top10", "tsmom_top20", "tsmom_tranches", "tsmom_regime")


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def btc_funding(P: fc.Panel) -> np.ndarray:
    """BTC's USDT perpetual funding summed per day, (T,), NaN before the archive starts."""
    pp = fc._perp_daily()
    pp = pp.filter(pp["base"] == "BTC")
    di = {int(d): i for i, d in enumerate(P.days)}
    out = np.full(P.T, np.nan)
    for d, f in zip(pp["day"].to_numpy(), pp["funding"].to_numpy()):
        t = di.get(int(d))
        if t is not None:
            out[t] = f if np.isfinite(f) else 0.0
    return out


def features(P: fc.Panel, funding: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """The five daily features, each (T,) and known at the close of day t."""
    b = P.btc
    px = P.px[:, b]
    r7 = np.full(P.T, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        r7[7:] = np.log(px[7:] / px[:-7])
        vol14 = 0.5 * np.log(fc.rolling(P.extra["rv"][:, b:b + 1], 14, 10)[:, 0] * 365)
        ma50 = fc.rolling(P.px, 50, 40)
        ok = P.eligible & np.isfinite(ma50)
        n = ok.sum(1)
        breadth = np.where(n > 0, (ok & (P.px > ma50)).sum(1) / np.maximum(n, 1), np.nan)
        qv = np.where(P.eligible, np.nan_to_num(P.extra["qv"]), 0.0).sum(1)
        v7 = fc.rolling(qv[:, None], 7, 7)[:, 0]
        v90 = fc.rolling(qv[:, None], 90, 80)[:, 0]
        volume = np.log(v7 / v90)
    f = btc_funding(P) if funding is None else funding
    funding7 = fc.rolling(f[:, None], 7, 5)[:, 0]
    return {"r7": r7, "vol14": vol14, "breadth": breadth, "volume": volume, "funding": funding7}


def design(feats: dict[str, np.ndarray], names: tuple[str, ...]) -> tuple[np.ndarray, int]:
    """(T, d) matrix and the first row where every feature exists; later gaps are carried forward."""
    X = np.column_stack([feats[k] for k in names]).astype(float)
    ok = np.isfinite(X).all(1)
    first = int(np.argmax(ok)) if ok.any() else len(X)
    for t in range(first + 1, len(X)):
        bad = ~np.isfinite(X[t])
        if bad.any():
            X[t, bad] = X[t - 1, bad]
    return X, first


# ---------------------------------------------------------------------------
# The HMM: fitted by EM (hmmlearn), read with a forward filter only
# ---------------------------------------------------------------------------

@dataclass
class Fit:
    startprob: np.ndarray
    transmat: np.ndarray
    means: np.ndarray       # in z units of this fit
    covars: np.ndarray      # (K, d, d)
    mu: np.ndarray          # the z-score's mean and std, from the training window
    sd: np.ndarray
    loglik: float


def _log_emission(Z: np.ndarray, means: np.ndarray, covars: np.ndarray) -> np.ndarray:
    """log N(z_t; mean_k, cov_k), (T, K)."""
    T, d = Z.shape
    out = np.empty((T, len(means)))
    for k, (m, c) in enumerate(zip(means, covars)):
        L = np.linalg.cholesky(c + 1e-9 * np.eye(d))
        y = np.linalg.solve(L, (Z - m).T)
        out[:, k] = -0.5 * (y ** 2).sum(0) - np.log(np.diag(L)).sum() - 0.5 * d * math.log(2 * math.pi)
    return out


def forward_filter(Z: np.ndarray, startprob: np.ndarray, transmat: np.ndarray, means: np.ndarray,
                   covars: np.ndarray) -> np.ndarray:
    """Filtered state probabilities P(s_t | z_1..z_t), (T, K). No backward pass: row t never sees t+1."""
    le = _log_emission(Z, means, covars)
    T, K = le.shape
    out = np.empty((T, K))
    prior = startprob
    for t in range(T):
        a = np.log(np.maximum(prior, 1e-300)) + le[t]
        a = np.exp(a - a.max())
        a /= a.sum()
        out[t] = a
        prior = a @ transmat
    return out


def _model(K: int, seed: int):
    from hmmlearn.hmm import GaussianHMM
    return GaussianHMM(n_components=K, covariance_type="full", n_iter=N_ITER, tol=TOL, random_state=seed,
                       min_covar=MIN_COVAR)


def fit_hmm(X: np.ndarray, K: int, prev: Fit | None = None) -> Fit:
    """EM from the previous fit (moved into this window's z units) and three seeded starts; best likelihood."""
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = (X - mu) / sd
    best = None
    tries = ([("warm", 0)] if prev is not None else []) + [("kmeans", s) for s in SEEDS]
    for how, seed in tries:
        m = _model(K, seed)
        if how == "warm":
            m.init_params = ""
            m.startprob_ = prev.startprob
            m.transmat_ = prev.transmat
            m.means_ = (prev.means * prev.sd + prev.mu - mu) / sd
            scale = np.outer(prev.sd, prev.sd) / np.outer(sd, sd)
            m.covars_ = prev.covars * scale[None]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                m.fit(Z)
                ll = float(m.score(Z))
            except (ValueError, np.linalg.LinAlgError):
                continue
        if not np.isfinite(ll):
            continue
        if best is None or ll > best.loglik:
            best = Fit(m.startprob_.copy(), m.transmat_.copy(), m.means_.copy(), m.covars_.copy(), mu, sd, ll)
    if best is None:
        raise RuntimeError("no HMM start converged")
    return best


def bull_states(fit: Fit) -> np.ndarray:
    """Bool (K,): the states whose mean 7-day BTC return (raw units, feature 0) is above 0; else the top one."""
    r7 = fit.means[:, 0] * fit.sd[0] + fit.mu[0]
    bull = r7 > 0
    if not bull.any():
        bull = r7 == r7.max()
    return bull


def month_ends(days: np.ndarray, first: int) -> list[int]:
    """Row indices of the last day of every month, from the first fit date on."""
    m = days.astype("datetime64[us]").astype("datetime64[M]")
    last = np.flatnonzero(np.r_[m[1:] != m[:-1], False])
    return [int(t) for t in last if days[t] >= first]


@dataclass
class Regime:
    p_bull: np.ndarray                     # (T,) filtered P(bull) used on day t, NaN before the first fit
    top: np.ndarray                        # (T,) most likely state, ranked by mean r7 (0 = lowest), -1 before
    durations: list = field(default_factory=list)   # per fit: expected duration of each state, days
    agreement: list = field(default_factory=list)   # per refit: share of the next month the old and new fit agree
    n_fits: int = 0


def regime(X: np.ndarray, first_row: int, days: np.ndarray, K: int, first_fit: int = FIRST_FIT) -> Regime:
    """Expanding-window fits at every month end, filtered probabilities only.

    The fit at the close of month end e uses rows first_row..e; its filter
    gives the probabilities for rows e..(next month end - 1), so a refit takes
    over from its own fitting close on (the decision at that close may use it:
    everything it saw is known then)."""
    T = len(X)
    ends = month_ends(days, first_fit)
    p = np.full(T, np.nan)
    top = np.full(T, -1)
    out = Regime(p, top)
    prev: Fit | None = None
    prev_p: np.ndarray | None = None
    for i, e in enumerate(ends):
        if e - first_row < 200:
            continue
        fit = fit_hmm(X[first_row:e + 1], K, prev)
        nxt = ends[i + 1] if i + 1 < len(ends) else T
        Z = (X[first_row:nxt] - fit.mu) / fit.sd
        fp = forward_filter(Z, fit.startprob, fit.transmat, fit.means, fit.covars)
        bull = bull_states(fit)
        pb = fp[:, bull].sum(1)
        rank = np.argsort(np.argsort(fit.means[:, 0]))
        seg = slice(e, nxt)
        p[seg] = pb[e - first_row:]
        top[seg] = rank[fp[e - first_row:].argmax(1)]
        out.durations.append((1 / np.maximum(1 - np.diag(fit.transmat), 1e-9)).tolist())
        if prev is not None and prev_p is not None:
            old = prev_p[e - first_row:nxt - first_row] if len(prev_p) >= nxt - first_row else None
            if old is not None and len(old):
                out.agreement.append(float(((old > 0.5) == (pb[e - first_row:] > 0.5)).mean()))
        # The old fit's filter carried one month further, for the next refit's agreement.
        nn = ends[i + 2] if i + 2 < len(ends) else T
        Zn = (X[first_row:nn] - fit.mu) / fit.sd
        prev_p = forward_filter(Zn, fit.startprob, fit.transmat, fit.means, fit.covars)[:, bull].sum(1)
        prev = fit
        out.n_fits += 1
    return out


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def soft_gate(p_bull: np.ndarray) -> np.ndarray:
    """Exposure scale = P(bull); 1 before the model exists (as no gate)."""
    return np.where(np.isfinite(p_bull), np.clip(p_bull, 0.0, 1.0), 1.0)


def switch_gate(p_bull: np.ndarray, on: float = ON, off: float = OFF) -> np.ndarray:
    """On above `on`, off below `off`, unchanged in between; starts on."""
    s = np.ones(len(p_bull))
    cur = 1.0
    for t, x in enumerate(p_bull):
        if np.isfinite(x):
            if x > on:
                cur = 1.0
            elif x < off:
                cur = 0.0
        s[t] = cur
    return s


def ma200_gate(P: fc.Panel) -> np.ndarray:
    return P.btc_on.astype(float)


def lagged(s: np.ndarray, k: int = 1) -> np.ndarray:
    """The gate applied k days late (the first k days ungated)."""
    return np.r_[np.ones(k), s[:-k]]


# ---------------------------------------------------------------------------
# Books: ungated holdings, then the gate as an overlay
# ---------------------------------------------------------------------------

def holdings(P: fc.Panel, W: np.ndarray, start: int = START) -> np.ndarray:
    """What fam_common.simulate holds after every close, (T, N): the same steps, recorded."""
    T, N = W.shape
    H = np.zeros((T, N))
    w = np.zeros(N)
    for t in range(start, T):
        tgt = np.where(np.isnan(W[t]), w, W[t])
        w = np.where(P.traded[t] | (tgt == w), tgt, w)
        H[t] = w
        if t == T - 1:
            break
        r = np.nan_to_num(P.ret[t + 1])
        g = float(np.dot(w, r))
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
        w[(w != 0) & ~P.alive[t + 1]] = 0.0
    return np.clip(H, 0.0, None)


def regime20_weights(P: fc.Panel, lookback: int = 28, target: float = 0.40, min_hist: int = 120) -> np.ndarray:
    """tsmom_regime's core (experiments/tsmom.target_weights) on the engine's 20 coins, regime off."""
    cols = np.array([P.col(f"{c}USDT") for c in UNIVERSE if f"{c}USDT" in P.names])
    past = np.full_like(P.px, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        past[lookback:] = P.px[lookback:] / P.px[:-lookback] - 1
    sub = np.zeros((P.T, P.N), dtype=bool)
    sub[:, cols] = True
    ok = sub & P.alive & (P.age >= min_hist) & np.isfinite(P.sigma) & (P.sigma > 0) & np.isfinite(P.px)
    n_ok = np.maximum(ok.sum(1), 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        w = np.where(ok & np.isfinite(past) & (past > 0), target / (P.sigma * np.sqrt(365)), 0.0) / n_ok[:, None]
    w = np.nan_to_num(w)
    s = w.sum(1, keepdims=True)
    return np.where(s > 1, w / np.maximum(s, 1e-12), w)


def book_holdings(P: fc.Panel) -> dict[str, np.ndarray]:
    """Each book's ungated holdings after every close, plus the native 200d references."""
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    out = {
        "breakout_top10": holdings(P, fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False)),
        "tsmom_top20": holdings(P, fam_volmom.base_weights(P, 20, regime=False)),
        "tsmom_regime": holdings(P, regime20_weights(P)),
    }
    *_, H = tt.simulate(P, fam_volmom.base_weights(P, 20, regime=False), record=True)
    out["tsmom_tranches"] = np.clip(H, 0.0, None)
    out["breakout_top10 · native 200d"] = holdings(
        P, fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=True))
    *_, Hn = tt.simulate(P, tt.targets(P), record=True)
    out["tsmom_tranches · native 200d"] = np.clip(Hn, 0.0, None)
    return out


def gated(P: fc.Panel, H: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The book holding s[t] x H[t] after the close of day t: (gross, turnover, exposure)."""
    W = H * np.clip(s, 0.0, 1.0)[:, None]
    g, tv, le, _ = fc.simulate(P, W, start=START)
    return g, tv, le


def net(g: np.ndarray, tv: np.ndarray, c: float) -> np.ndarray:
    return g - c * np.r_[0.0, tv[:-1]]


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def windows(P: fc.Panel) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    sel = (P.days >= SEL_START) & (P.days < fc.SPLIT)
    oos = P.days >= fc.SPLIT
    yr = P.days.astype("datetime64[us]").astype("datetime64[Y]").astype(int) + 1970
    return sel, oos, yr


def describe(P: fc.Panel, book: str, gate: str, g: np.ndarray, tv: np.ndarray, ex: np.ndarray) -> dict:
    sel, oos, yr = windows(P)
    row: dict = {"book": book, "gate": gate}
    for k, c in COSTS.items():
        x = net(g, tv, c)
        ps, po = fc.perf(x[sel]), fc.perf(x[oos])
        row[f"sel_{k}"] = ps["sharpe"]
        row[f"oos_{k}"] = po["sharpe"]
        row[f"cagr_{k}"] = po["cagr"]
        row[f"dd_{k}"] = po["max_dd"]
    row["sel_dd"] = fc.perf(net(g, tv, COSTS[BASE])[sel])["max_dd"]
    x = net(g, tv, COSTS[BASE])
    for y in YEARS:
        m = (yr == y) & (P.days >= SEL_START)
        row[f"y{y}"] = fc.perf(x[m])["sharpe"]
    row["turnover_yr"] = float(tv[oos].sum() / (oos.sum() / 365))
    row["expo"] = float(ex[oos].mean())
    return row


def sharpe_d(x: np.ndarray) -> float:
    sd = x.std()
    return float(x.mean() / sd) if sd > 0 else 0.0


def prior_var() -> float:
    """Variance of daily trial Sharpes implied by the published bar over the prior pool (2.74 over 265)."""
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def pooled_var(mine: list[float]) -> tuple[float, dict]:
    """The prior pool's variance pooled with this study's trial Sharpes (annual, clipped at +-3).
    The prior's mean is taken as this study's (its own mean is not on file for all 265)."""
    v1, n1 = prior_var(), PRIOR_TRIALS
    x = np.clip(np.array(mine), -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
    n2, v2 = len(x), float(np.var(x))
    n = n1 + n2
    v = (n1 * v1 + n2 * v2) / n
    return v, {"prior_trials": n1, "prior_var": v1, "mine": n2, "mine_var": v2, "pooled_var": v, "n_total": n,
               "sr0_annual": fc._sr0(v, n) * math.sqrt(365)}


def deflated(x: np.ndarray, n: int, var: float) -> float:
    if x.std() == 0:
        return 0.0
    return deflated_sharpe(sharpe_d(x), len(x), n, var, float(stats.skew(x)), float(stats.kurtosis(x, fisher=False)))


def stability(P: fc.Panel, R: Regime, s: np.ndarray, mapping: str) -> dict:
    _, oos, _ = windows(P)
    live = P.days >= SEL_START
    years = live.sum() / 365
    if mapping == "switch":
        sw = float((np.abs(np.diff(s[live])) > 0).sum() / years)
    else:
        sw = float((np.abs(np.diff(s[live])) > 0.25).sum() / years)
    top = R.top[live]
    runs = np.diff(np.flatnonzero(np.r_[True, top[1:] != top[:-1], True]))
    d = np.array(R.durations)
    p = R.p_bull[oos]
    return {"switches_yr": sw, "mean_run_days": float(runs.mean()) if len(runs) else float("nan"),
            "exp_duration_days": float(np.median(d.mean(1))) if len(d) else float("nan"),
            "undecided_share": float(((p > 0.4) & (p < 0.6)).mean()),
            "refit_agreement": float(np.mean(R.agreement)) if R.agreement else float("nan"),
            "bull_share_oos": float((p > 0.5).mean()), "fits": R.n_fits}


def walk_forward(P: fc.Panel, series: dict[str, np.ndarray]) -> tuple[np.ndarray, list[str]]:
    """Each out-of-sample quarter uses the gate with the best Sharpe at 35 bps on all data before it
    (from the selection window's start). Switching between gates is not charged."""
    q = P.days.astype("datetime64[us]").astype("datetime64[M]").astype(int)
    qi = q // 3
    out = np.zeros(P.T)
    picks = []
    _, oos, _ = windows(P)
    for k in np.unique(qi[oos]):
        m = oos & (qi == k)
        first = int(np.flatnonzero(m)[0])
        hist = (P.days >= SEL_START) & (np.arange(P.T) < first)
        best = max(series, key=lambda n: fc.perf(series[n][hist])["sharpe"])
        out[m] = series[best][m]
        y, qq = 1970 + int(k) // 4, int(k) % 4 + 1
        picks.append(f"{y}Q{qq}: {best}")
    return out, picks


def gate_name(K: int, fs: str, mapping: str) -> str:
    return f"HMM {K} states · {fs} · {mapping}"


def main() -> None:
    P = fc.load_panel()
    sel, oos, yr = windows(P)
    feats = features(P)
    regimes: dict[tuple, Regime] = {}
    gates: dict[str, np.ndarray] = {"none": np.ones(P.T), "200d": ma200_gate(P)}
    stab: list[dict] = []
    for fs, K in itertools.product(FEATURE_SETS, STATES):
        X, first = design(feats, FEATURE_SETS[fs])
        R = regime(X, first, P.days, K)
        regimes[(fs, K)] = R
        for mp in MAPPINGS:
            s = soft_gate(R.p_bull) if mp == "soft" else switch_gate(R.p_bull)
            gates[gate_name(K, fs, mp)] = s
            stab.append({"gate": gate_name(K, fs, mp), **stability(P, R, s, mp)})
        print(fs, K, "fitted", R.n_fits, flush=True)
    hmm_names = [n for n in gates if n.startswith("HMM")]
    stab.append({"gate": "200d", **stability(P, Regime(np.where(P.btc_on, 1.0, 0.0),
                                                       P.btc_on.astype(int)), gates["200d"], "switch"),
                 "exp_duration_days": float("nan"), "refit_agreement": float("nan"), "fits": 0})

    H = book_holdings(P)
    c = COSTS[BASE]
    rows, nets = [], {}
    for book in BOOKS:
        for gname, s in gates.items():
            g, tv, ex = gated(P, H[book], s)
            rows.append(describe(P, book, gname, g, tv, ex))
            nets[(book, gname)] = (g, tv)
        print(book, "gated", flush=True)
    for nat in ("breakout_top10 · native 200d", "tsmom_tranches · native 200d"):
        book = nat.split(" · ")[0]
        g, tv, ex = gated(P, H[nat], np.ones(P.T))
        rows.append(describe(P, book, "200d (native)", g, tv, ex))
        nets[(book, "200d (native)")] = (g, tv)

    def row(book: str, gname: str) -> dict:
        return next(r for r in rows if r["book"] == book and r["gate"] == gname)

    # The cross-book pick: best average selection-window Sharpe at 35 bps over the four books.
    avg_sel = {n: float(np.mean([row(b, n)[f"sel_{BASE}"] for b in BOOKS])) for n in hmm_names}
    pick = max(avg_sel, key=avg_sel.get)
    per_book_pick = {b: max(hmm_names, key=lambda n: row(b, n)[f"sel_{BASE}"]) for b in BOOKS}

    trials: list[tuple[str, np.ndarray]] = []
    for (book, gname), (g, tv) in nets.items():
        trials.append((f"{book} · {gname}", net(g, tv, c)[oos]))
    wf_rows, late_rows = [], []
    for book in BOOKS:
        series = {n: net(*nets[(book, n)], c) for n in hmm_names}
        wf, wf_picks = walk_forward(P, series)
        trials.append((f"{book} · walk-forward HMM gate", wf[oos]))
        wf_rows.append({"book": book, "oos": fc.perf(wf[oos])["sharpe"], "dd": fc.perf(wf[oos])["max_dd"],
                        "picks": wf_picks})
        g, tv, ex = gated(P, H[book], lagged(gates[pick]))
        lr = describe(P, book, pick + " · one day late", g, tv, ex)
        late_rows.append(lr)
        trials.append((f"{book} · {pick} · one day late", net(g, tv, c)[oos]))
    assert len(trials) == HERE_TRIALS, len(trials)

    var, pool = pooled_var([sharpe_d(x) * math.sqrt(365) for _, x in trials])
    n_total = pool["n_total"]
    # Difference series against the 200d overlay, for the 48 HMM trials (the variance of the rule's test).
    diffs = {(b, n): net(*nets[(b, n)], c)[oos] - net(*nets[(b, "200d")], c)[oos] for b in BOOKS for n in hmm_names}
    dvar = float(np.var(np.clip([sharpe_d(x) * math.sqrt(365) for x in diffs.values()], -fc.SR_CLIP, fc.SR_CLIP)
                        / math.sqrt(365)))
    rng = np.random.default_rng(20261014)
    judged = []
    for book in BOOKS:
        r, r200 = row(book, pick), row(book, "200d")
        d = diffs[(book, pick)]
        dyears = {y: float(d[(yr[oos] == y)].sum()) for y in YEARS_OOS}
        lo, hi = tt.boot_band(d, rng)
        x = net(*nets[(book, pick)], c)[oos]
        judged.append({
            "book": book, "gate": pick, "oos_pick": r[f"oos_{BASE}"], "oos_200d": r200[f"oos_{BASE}"],
            "oos_none": row(book, "none")[f"oos_{BASE}"], "dd_pick": r[f"dd_{BASE}"], "dd_200d": r200[f"dd_{BASE}"],
            "beats_200d": r[f"oos_{BASE}"] > r200[f"oos_{BASE}"],
            "diff_sharpe": sharpe_d(d) * math.sqrt(365),
            "diff_deflated_p": deflated(d, n_total, dvar),
            "diff_boot_p05": lo, "diff_boot_p95": hi,
            "diff_years_pos": int(sum(v > 0 for v in dyears.values())),
            **{f"diff_{y}": v for y, v in dyears.items()},
            "book_deflated_p": deflated(x, n_total, var),
        })
    rule = {
        "1 beats 200d in 3 of 4 incl. tsmom_top20": sum(j["beats_200d"] for j in judged) >= 3
        and next(j for j in judged if j["book"] == "tsmom_top20")["beats_200d"],
        "2 difference deflated p > 0.95 in 3 of 4": sum(j["diff_deflated_p"] > 0.95 for j in judged) >= 3,
        "3 bootstrap band above 0 in 3 of 4": sum(j["diff_boot_p05"] > 0 for j in judged) >= 3,
        "4 difference positive in 2 of 3 years in 3 of 4": sum(j["diff_years_pos"] >= 2 for j in judged) >= 3,
    }
    res = {
        "panel_end": str(np.datetime64(int(P.days[-1]), "us").astype("datetime64[D]")), "segments": P.N, "rows": rows, "stability": stab, "pick": pick, "avg_sel": avg_sel,
        "per_book_pick": per_book_pick, "judged": judged, "rule": rule, "passes": all(rule.values()),
        "walk_forward": wf_rows, "late": late_rows, "pool": pool, "diff_var": dvar,
        "trials": [n for n, _ in trials], "feature_corr": feature_summary(feats, oos),
        "pbull_by_year": {str(y): float(np.nanmean(regimes[_pick_key(pick)].p_bull[yr == y])) for y in YEARS},
    }
    write(res)


def _pick_key(name: str) -> tuple[str, int]:
    parts = name.split(" · ")
    return parts[1], int(parts[0].split()[1])


def feature_summary(feats: dict[str, np.ndarray], oos: np.ndarray) -> dict:
    return {k: {"mean_oos": float(np.nanmean(v[oos])), "sd_oos": float(np.nanstd(v[oos]))} for k, v in feats.items()}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def write(res: dict) -> None:
    pre = (fc.RESULTS_DIR / f"{NAME}.md").read_text(encoding="utf-8")
    pre = pre.split(MARKER)[0] + MARKER + "\n"
    rows = res["rows"]
    pool = res["pool"]
    cols = ["book", "gate", f"sel_{BASE}", "oos_maker 15bps", f"oos_{BASE}", f"cagr_{BASE}", f"dd_{BASE}",
            "turnover_yr", "expo"]
    years = ["book", "gate"] + [f"y{y}" for y in YEARS]
    jc = ["book", "oos_none", "oos_200d", "oos_pick", "dd_200d", "dd_pick", "diff_sharpe", "diff_deflated_p",
          "diff_boot_p05", "diff_boot_p95", "diff_2024", "diff_2025", "diff_2026", "book_deflated_p"]
    sc = ["gate", "fits", "switches_yr", "mean_run_days", "exp_duration_days", "undecided_share", "refit_agreement",
          "bull_share_oos"]
    md = [pre, f"\n## Results (generated {datetime.now(timezone.utc):%Y-%m-%d}, data to {res['panel_end']})\n\n"]
    verdict = "the pick passes" if res["passes"] else "nothing passes"
    md.append(f"**Verdict: {verdict}.** Cross-book pick (best average selection-window Sharpe at 35 bps): "
              f"**{res['pick']}**. Pass rule: " + "; ".join(f"{k}: {'yes' if v else 'no'}"
                                                            for k, v in res["rule"].items()) + ". "
              f"Deflation pool {pool['n_total']} trials (prior {pool['prior_trials']}, here {pool['mine']}); "
              f"the best noise trial is expected at an annual Sharpe of about {pool['sr0_annual']:.2f}.\n\n")
    md.append("### The cross-book pick against the 200-day rule (out of sample, 35 bps)\n\n"
              "`diff_*` is the pick-gated book minus the 200d-gated book, daily net returns; `diff_2024` to "
              "`diff_2026` are its summed returns per year; `book_deflated_p` is the gated book's own deflated p "
              "over the whole pool.\n\n")
    md.append(fc.table(res["judged"], jc))
    md.append("\n### Every book and gate (selection window 2021-07 to 2023, out of sample from 2024)\n\n")
    md.append(fc.table(sorted(rows, key=lambda r: (r["book"], r["gate"])), cols))
    md.append("\n### Per year (Sharpe at 35 bps; 2021 from July)\n\n")
    md.append(fc.table(sorted(rows, key=lambda r: (r["book"], r["gate"])), years))
    md.append("\n### State stability\n\n`switches_yr`: gate changes a year from 2021-07 (soft: days the scale "
              "moves by more than 0.25); `mean_run_days`: mean run of the most likely state; `exp_duration_days`: "
              "median over fits of the mean expected state duration from the transition matrix; "
              "`undecided_share`: out-of-sample days with P(bull) between 0.4 and 0.6; `refit_agreement`: on the "
              "month after each refit, the share of days the new and the previous fit make the same bull call.\n\n")
    md.append(fc.table(res["stability"], sc))
    md.append("\n### Selection details\n\nAverage selection-window Sharpe at 35 bps over the four books:\n\n")
    md.append(fc.table([{"gate": k, "avg_sel_35": v} for k, v in sorted(res["avg_sel"].items(), key=lambda x: -x[1])],
                       ["gate", "avg_sel_35"]))
    md.append("\nPer book, the best HMM gate in the selection window (information only): "
              + "; ".join(f"{b}: {g}" for b, g in res["per_book_pick"].items()) + ".\n\n")
    md.append("Walk-forward HMM gate per book (each out-of-sample quarter uses the best gate so far):\n\n")
    md.append(fc.table(res["walk_forward"], ["book", "oos", "dd"]))
    md.append("\nThe pick applied one day late:\n\n" + fc.table(res["late"], cols))
    md.append(f"\nP(bull) of the pick, mean per year: "
              + ", ".join(f"{y} {v:.2f}" for y, v in res["pbull_by_year"].items()) + ".\n")
    md.append(f"\n### Deflation\n\nPrior: {pool['prior_trials']} trials, variance backed out of the fast "
              f"strategies' bar ({PRIOR_SR0} over {PRIOR_TRIALS}); here {pool['mine']} trials at 35 bps. Pooled bar "
              f"{pool['sr0_annual']:.2f} over {pool['n_total']}. The difference test uses the variance of the 48 HMM "
              f"difference series' Sharpes (daily {res['diff_var']:.2e}) with the same {pool['n_total']} trials.\n\n"
              "Trials counted here: " + "; ".join(res["trials"]) + ".\n")
    (fc.RESULTS_DIR / f"{NAME}.md").write_text("".join(md), encoding="utf-8")
    d = fc.OUT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{NAME}.json").write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
