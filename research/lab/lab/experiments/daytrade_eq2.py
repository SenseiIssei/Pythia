"""EQ2: single-stock day trading at 50 EUR, new signals under the real rules (Alpaca, fractional shares).

Pre-registered in results/daytrade_eq2_prereg.md; results in results/daytrade_eq2.md and .json.

    PYTHIA_TRIALS_REGISTRY=<registry> python -m lab.experiments.daytrade_eq2 [--no-register]
    python -m lab.experiments.daytrade_eq2 --register    append the trials in results/daytrade_eq2.json to the
                                                         registry (by id, once), for the server's registry

W4's cached Alpaca SIP 5 minute bars (<data>/intraday/alpaca-sip, read only, no download) of its 41 large caps and
SPY, every bar after 2026-06-30 dropped at load (the lockbox is never read). One position a session with all buying
power, fractional market orders decided at a bar's close and filled at the open two bars on (one bar late; the
next bar reported), flat at the 15:55 open, a conservative spread model (COST_BPS or a cent a side, doubled in the
first OPEN_BARS bars), the SEC fee and TAF on the sells, EUR to USD at FX_COST each way. Two accounts (Wallet): cash
(settled cash only, a sale settles the next session; the judged book) and margin under 25,000 USD (the pattern day
trader rule, PDT_MAX day trades in PDT_SESSIONS sessions). Two families: rvol_orb (opening range breakout on the
stock in play by relative volume) and pattern_clf (a classifier on the bars so far, walk-forward purged, checked by
the leak harness on a time axis of session and bar). Sixteen trials of R5's registry (family small), registered with
their in-sample Sharpes before any validation number. Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
from scipy import optimize, special

from .. import cv, leak, metrics
from . import director_common as dc
from . import etf_books_eq1 as eq1
from . import intraday_equities as ie

NAME = "daytrade_eq2"
PREREG = "results/daytrade_eq2_prereg.md"
RESULTS = Path(__file__).resolve().parents[2] / "results"
SUMMARY = RESULTS / f"{NAME}.json"
STOCKS = ie.CANDIDATES
BENCH = "SPY"
NB, EXIT_BAR, LAST_ENTRY = ie.NB, ie.EXIT_BAR, ie.LAST_ENTRY
IS_FROM, IS_TO, VAL_FROM, VAL_TO = "2016-01-01", "2023-12-31", "2024-01-01", "2026-06-30"
CLF_FROM = "2018-01-01"                  # the classifier's first walk-forward test quarter; PBO from here
WINDOWS = {"is": (IS_FROM, IS_TO), "val": (VAL_FROM, VAL_TO)}
CAPITAL_EUR = 50.0
FX_COST = 0.005                          # EUR to USD and back, each way
COST_BPS, CENT, OPEN_BARS = 5.0, 0.01, 3
LAG = 1                                  # judged: decided at bar k, filled at the open of bar k + 1 + LAG
MIN_NOTIONAL = 1.0                       # Alpaca's fractional minimum, USD
PDT_MAX, PDT_SESSIONS = 3, 5
ACCOUNTS = ("cash", "margin")
JUDGED = "cash"
RVOL_DAYS = 14
ORB_GRID = ((5, 1.5), (5, 3.0), (15, 1.5), (15, 3.0))
CLF_GRID = (("logit", 5), ("logit", 29), ("gbm", 5), ("gbm", 29))     # decision at the close of bar 5 (10:00), 29
P_MIN = 0.55
LOGIT_C = 1.0
GBM = dict(n_estimators=100, num_leaves=15, learning_rate=0.05, min_child_samples=200, random_state=7, n_jobs=1,
           deterministic=True, force_row_wise=True, verbose=-1)
CLF_FEATURES = ("r_open", "r_last", "gapz", "prev_ret", "range", "pos", "vwap_dev", "rvol", "spy_r_open", "spy_gapz",
                "rel_open")
LEAK_SYMS, LEAK_FROM, LEAK_TO, LEAK_CUTS = 6, "2017-01-01", "2019-06-30", 2
DSR_PASS, PBO_PASS, MIN_TRADES = 0.95, 0.2, 100


def rule_name(fam: str, a, b) -> str:
    if fam == "rvol_orb":
        return f"rvol_orb_m{a}_r{b:g}"
    return f"pattern_clf_{a}_{(9 * 60 + 30 + 5 * (b + 1)) // 60:02d}{(9 * 60 + 30 + 5 * (b + 1)) % 60:02d}"


RULES = {rule_name("rvol_orb", m, r): ("rvol_orb", m, r) for m, r in ORB_GRID} | \
        {rule_name("pattern_clf", mo, k): ("pattern_clf", mo, k) for mo, k in CLF_GRID}


def trial_id(rule: str, acct: str) -> str:
    return f"small:eq2:{rule}:{acct}"


# ---------------------------------------------------------------- the bars

def load(cache: Path | None = None, to: str = VAL_TO, syms=None) -> ie.Bars:
    """W4's cached SIP bars (no keys, no download), every day after `to` dropped; the calendar is SPY's full
    sessions, a symbol counts on a day with at least 39 bars (as ie.load_alpaca)."""
    cache = cache or ie.CACHE_ROOT / "alpaca-sip"
    last = np.datetime64(to)
    per, frames = {}, {}
    for s in syms or (BENCH,) + STOCKS:
        parts = [pl.read_parquet(f) for f in sorted((cache / s).glob("*.parquet")) if f.stem <= to[:7]]
        parts = [p.select("date", "bar", "open", "high", "low", "close", "volume", "tp") for p in parts if p.height]
        if not parts:
            continue
        df = pl.concat(parts, how="vertical_relaxed").filter(pl.col("date") <= last.astype(object))
        if df.is_empty():
            continue
        frames[s], per[s] = df, ie.frame_to_blocks(df)
    if BENCH not in per:
        raise ie.DataUnavailable(f"no {BENCH} bars under {cache}")
    spy = frames[BENCH].group_by("date").agg(n=pl.len(), last=pl.col("bar").max()).sort("date")
    full = (spy["n"].to_numpy() >= 70) & (spy["last"].to_numpy() >= EXIT_BAR)
    calendar = spy["date"].to_numpy().astype("datetime64[D]")[full]
    valid = {s: df.group_by("date").agg(n=pl.len()).sort("date")["n"].to_numpy() >= NB // 2 for s, df in frames.items()}
    return ie.assemble(per, valid, calendar, {}, "alpaca", [f"{len(calendar)} full sessions to {to}"])


def stock_mask(B: ie.Bars) -> np.ndarray:
    return np.array([s in STOCKS for s in B.syms])


# ---------------------------------------------------------------- costs and fills

def cost(px: np.ndarray, bar: np.ndarray, mult: float = 1.0) -> np.ndarray:
    """Half spread and slippage a side: the larger of COST_BPS and a cent, doubled in the first OPEN_BARS bars."""
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.maximum(COST_BPS / 1e4, CENT / px)
    return mult * c * np.where(np.asarray(bar) < OPEN_BARS, 2.0, 1.0)


def trade_returns(B: ie.Bars, sym: np.ndarray, ent: np.ndarray, stop: np.ndarray | None = None, lag: int = LAG,
                  mult: float = 1.0) -> np.ndarray:
    """(D,) net return of each session's round trip, NaN without one. sym (D,) the stock (-1 none), ent (D,) the bar
    whose close decides the buy; stop (D,) a level: the first close at or after the fill bar below it sells. Fills at
    the open of the decision bar + 1 + lag, the forced sale at the 15:55 open; an entry filled then or later is not
    made. Sells pay the SEC fee and the TAF (per share, on the shares bought with 1 USD)."""
    out = np.full(B.D, np.nan)
    for d in np.flatnonzero((sym >= 0) & (ent >= 0)):
        j, fe = int(sym[d]), int(ent[d]) + 1 + lag
        if fe >= EXIT_BAR:
            continue
        fx = EXIT_BAR
        if stop is not None and np.isfinite(stop[d]):
            hit = np.flatnonzero(B.c[j, d, fe:EXIT_BAR] < stop[d])
            if hit.size:
                fx = min(fe + int(hit[0]) + 1 + lag, EXIT_BAR)
        po, px = B.o[j, d, fe], B.o[j, d, fx]
        if not (np.isfinite(po) and np.isfinite(px) and po > 0):
            continue
        pe = po * (1 + cost(po, fe, mult))
        ps = px * (1 - cost(px, fx, mult))
        out[d] = (ps * (1 - ie.SEC_FEE) - ie.TAF_PER_SHARE) / pe - 1
    return out


# ---------------------------------------------------------------- the accounts

@dataclass
class Wallet:
    """A USD account. cash: a buy uses settled cash only and a sale's proceeds settle the next session; margin
    (under 25,000 USD): unsettled cash may be used, at most PDT_MAX day trades in any PDT_SESSIONS sessions."""
    kind: str
    settled: float
    pending: list = field(default_factory=list)      # [usable from session, USD]
    day_trades: list = field(default_factory=list)   # sessions of each day trade
    skipped_pdt: int = 0
    skipped_cash: int = 0

    def settle(self, s: int) -> None:
        self.settled += sum(a for t, a in self.pending if t <= s)
        self.pending = [(t, a) for t, a in self.pending if t > s]

    @property
    def equity(self) -> float:
        return self.settled + sum(a for _, a in self.pending)

    def buying_power(self, s: int) -> float:
        self.settle(s)
        return self.settled if self.kind == "cash" else self.equity

    def pdt_ok(self, s: int) -> bool:
        """A new day trade in session s keeps the last PDT_SESSIONS sessions at PDT_MAX or fewer."""
        return self.kind != "margin" or sum(s - PDT_SESSIONS < t <= s for t in self.day_trades) < PDT_MAX

    def round_trip(self, s: int, ret: float) -> bool:
        """Buy with all buying power and sell the same session at ret; False when the rules refuse it."""
        if not self.pdt_ok(s):
            self.skipped_pdt += 1
            return False
        bp = self.buying_power(s)
        if bp < MIN_NOTIONAL:
            self.skipped_cash += 1
            return False
        if self.kind == "cash":
            self.settled -= bp
        else:                                   # margin: settled first, then what is pending
            take = min(bp, self.settled)
            self.settled -= take
            rest = bp - take
            while rest > 1e-12 and self.pending:
                t, a = self.pending.pop(0)
                if a > rest:
                    self.pending.insert(0, (t, a - rest))
                    rest = 0.0
                else:
                    rest -= a
        self.pending.append((s + 1, bp * (1 + ret)))
        self.day_trades.append(s)
        return True


def run_book(r: np.ndarray, kind: str, start_usd: float) -> dict:
    """The wallet over the window's sessions; r (n,) each session's round trip return (NaN none)."""
    w = Wallet(kind, start_usd)
    eq, done = np.zeros(len(r)), []
    for s, x in enumerate(r):
        if np.isfinite(x) and w.round_trip(s, float(x)):
            done.append(float(x))
        w.settle(s)
        eq[s] = w.equity
    return {"equity": eq, "trades": np.array(done), "skipped_pdt": w.skipped_pdt, "skipped_cash": w.skipped_cash}


# ---------------------------------------------------------------- F1: rvol_orb

def _trailing_mean(B: ie.Bars, x: np.ndarray, n: int = RVOL_DAYS) -> np.ndarray:
    return ie._per_symbol(x, B.valid, ie._trailing(np.mean, n=n, min_n=n))


def plan_orb(B: ie.Bars, F: ie.Features, minutes: int, r_min: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(sym, entry decision bar, stop level) per session: the in-play stock with the highest relative volume of
    its opening range (at least r_min, the range closed up), bought on the first close above the range's high."""
    nr = minutes // 5
    hi, lo = B.h[:, :, :nr].max(2), B.l[:, :, :nr].min(2)
    vol = B.v[:, :, :nr].sum(2)
    with np.errstate(divide="ignore", invalid="ignore"):
        rvol = vol / _trailing_mean(B, np.where(B.valid, vol, np.nan))
    ok = stock_mask(B)[:, None] & B.valid & np.isfinite(rvol) & (rvol >= r_min) & (B.c[:, :, nr - 1] > B.o[:, :, 0])
    score = np.where(ok, rvol, -np.inf)
    sym = np.where(ok.any(0), score.argmax(0), -1)
    ent, stop = np.full(B.D, -1), np.full(B.D, np.nan)
    for d in np.flatnonzero(sym >= 0):
        j = sym[d]
        up = np.flatnonzero(B.c[j, d, nr:LAST_ENTRY + 1] > hi[j, d])
        if up.size:
            ent[d], stop[d] = nr + int(up[0]), lo[j, d]
    return sym, ent, stop


# ---------------------------------------------------------------- F2: pattern_clf

def clf_features(B: ie.Bars, F: ie.Features, k: int) -> np.ndarray:
    """(S, D, len(CLF_FEATURES)) known at the close of bar k: bars 0..k of the session and W4's daily features."""
    o0, ck = B.o[:, :, 0], B.c[:, :, k]
    sd = F.std20
    ppc = ie._per_symbol(F.prev_close, B.valid, lambda s: np.r_[np.nan, s[:-1]])
    hi, lo = B.h[:, :, :k + 1].max(2), B.l[:, :, :k + 1].min(2)
    vk = B.v[:, :, :k + 1].sum(2)
    with np.errstate(divide="ignore", invalid="ignore"):
        vwap = (B.tp[:, :, :k + 1] * B.v[:, :, :k + 1]).sum(2) / vk
        rvol = np.log(vk / _trailing_mean(B, np.where(B.valid, vk, np.nan)))
        r_open = np.log(ck / o0) / sd
        x = [r_open, np.log(ck / B.c[:, :, max(k - 3, 0)]) / sd, F.gapz, (F.prev_close / ppc - 1) / sd,
             (hi - lo) / o0 / sd, np.where(hi > lo, (ck - lo) / (hi - lo), 0.5), np.log(ck / vwap) / sd, rvol]
    j = B.syms.index(BENCH)
    x += [np.broadcast_to(r_open[j], r_open.shape), np.broadcast_to(F.gapz[j], r_open.shape), r_open - r_open[j]]
    X = np.stack(x, 2)
    return np.where(np.isfinite(X), X, np.nan)


def clf_label(B: ie.Bars, k: int, lag: int = LAG) -> np.ndarray:
    """(S, D) 1.0 when a buy at the open of bar k + 1 + lag sold at the 15:55 open beats the cost model, else 0."""
    fe = k + 1 + lag
    po, px = B.o[:, :, fe], B.o[:, :, EXIT_BAR]
    with np.errstate(divide="ignore", invalid="ignore"):
        r = px * (1 - cost(px, EXIT_BAR)) * (1 - ie.SEC_FEE) / (po * (1 + cost(po, fe))) - 1
    return np.where(np.isfinite(r), (r > 0).astype(float), np.nan)


def fit_logit(X: np.ndarray, y: np.ndarray, C: float = LOGIT_C):
    """L2 logistic regression (0.5 |w|^2 + C * log loss, the intercept not penalised) on standardised X."""
    mu, sd = X.mean(0), X.std(0)
    sd = np.where(sd > 0, sd, 1.0)
    Z = np.c_[(X - mu) / sd, np.ones(len(X))]

    def f(w):
        z = Z @ w
        loss = np.logaddexp(0, z) - y * z
        g = Z.T @ (special.expit(z) - y)
        reg = np.r_[w[:-1], 0.0]
        return 0.5 * reg @ reg + C * loss.sum(), reg + C * g

    w = optimize.minimize(f, np.zeros(Z.shape[1]), jac=True, method="L-BFGS-B").x
    return lambda Xn: special.expit(np.c_[(Xn - mu) / sd, np.ones(len(Xn))] @ w)


def fit_gbm(X: np.ndarray, y: np.ndarray):
    import lightgbm as lgb
    m = lgb.LGBMClassifier(**GBM).fit(X, y.astype(int))
    return lambda Xn: m.predict_proba(Xn)[:, 1]


def clf_predict(B: ie.Bars, F: ie.Features, model: str, k: int, first_test: str = CLF_FROM) -> np.ndarray:
    """(S, D) walk-forward probabilities (NaN where no model or no features): quarterly folds from first_test, each
    trained on the rows whose label (the session's 15:55 open) ended before the fold starts, one day embargo."""
    X, y = clf_features(B, F, k), clf_label(B, k)
    rows = stock_mask(B)[:, None] & B.valid & np.isfinite(X).all(2)
    js, ds = np.nonzero(rows)
    P = np.full((B.S, B.D), np.nan)
    if not len(ds):
        return P
    ts = (B.dates[ds].astype("datetime64[us]").astype(np.int64))
    end = ts + 16 * cv.HOUR_US
    first = int(np.datetime64(first_test).astype("datetime64[us]").astype(np.int64))
    Xr, yr = X[js, ds], y[js, ds]
    fit = fit_logit if model == "logit" else fit_gbm
    for fold in cv.walk_forward(ts, first, embargo_h=24, label_end_us=end):
        tr = fold.train & np.isfinite(yr)
        if tr.sum() < 500 or len(np.unique(yr[tr])) < 2:
            continue
        P[js[fold.test], ds[fold.test]] = fit(Xr[tr], yr[tr])(Xr[fold.test])
    return P


def plan_clf(B: ie.Bars, P: np.ndarray, k: int, p_min: float = P_MIN) -> tuple[np.ndarray, np.ndarray]:
    """(sym, entry decision bar) per session: the stock with the highest probability, when at least p_min."""
    Q = np.where(np.isfinite(P), P, -np.inf)
    sym = np.where(Q.max(0) >= p_min, Q.argmax(0), -1)
    return sym, np.where(sym >= 0, k, -1)


# ---------------------------------------------------------------- the leak harness on a (session, bar) axis

def flat_panel(B: ie.Bars) -> dict:
    """The bars on one time axis of (session, bar): arrays (D * NB, S), `days` each bar's start."""
    t = (B.dates.astype("datetime64[m]")[:, None] + np.timedelta64(570, "m")
         + np.arange(NB)[None, :] * np.timedelta64(5, "m")).ravel()
    P = {"days": t, "syms": list(B.syms)}
    for a in ("o", "h", "l", "c", "v", "tp"):
        P[a] = getattr(B, a).transpose(1, 2, 0).reshape(-1, B.S)
    return P


def unflat(P: dict) -> ie.Bars:
    """flat_panel's inverse; a cut session is padded with NaN bars."""
    T, S = len(P["days"]), len(P["syms"])
    D = -(-T // NB)
    arr = {}
    for a in ("o", "h", "l", "c", "v", "tp"):
        x = np.full((D * NB, S), np.nan)
        x[:T] = P[a]
        arr[a] = x.reshape(D, NB, S).transpose(2, 0, 1)
    dates = P["days"][::NB].astype("datetime64[D]")
    return ie.Bars(dates, list(P["syms"]), arr["o"], arr["h"], arr["l"], arr["c"], arr["v"], arr["tp"],
                   np.ones(S), "flat")


def clf_flat(model: str, k: int, first_test: str = CLF_FROM):
    """The classifier's whole path as a function of the flat panel: each session's probabilities at the row of its
    decision bar, NaN elsewhere."""
    def fn(P: dict) -> np.ndarray:
        B = unflat(P)
        prob = clf_predict(B, ie.features(B), model, k, first_test)
        out = np.full((B.D * NB, B.S), np.nan)
        out[np.arange(B.D) * NB + k] = prob.T
        return out[:len(P["days"])]
    return fn


def leak_check(B: ie.Bars, model: str, k: int, n_cuts: int = LEAK_CUTS) -> dict:
    """lab.leak.check on a slice of the real bars (LEAK_SYMS stocks and SPY, LEAK_FROM to LEAK_TO)."""
    keep = [B.syms.index(BENCH)] + [j for j, s in enumerate(B.syms) if s in STOCKS][:LEAK_SYMS]
    d = (B.dates >= np.datetime64(LEAK_FROM)) & (B.dates <= np.datetime64(LEAK_TO))
    S = ie.Bars(B.dates[d], [B.syms[j] for j in keep], *(getattr(B, a)[keep][:, d] for a in ("o", "h", "l", "c", "v",
                                                                                              "tp")),
                np.ones(len(keep)), "slice")
    P = flat_panel(S)
    T = len(P["days"])
    lo = int(np.searchsorted(S.dates, np.datetime64(CLF_FROM))) * NB + NB
    cuts = sorted({int(x) + k for x in np.linspace(lo, T - 2 * NB, n_cuts) // NB * NB})
    res = leak.check(clf_flat(model, k), P, cuts=cuts, columns=P["syms"], name=f"eq2:{model}:{k}")
    return {"name": res["name"], "ok": res["ok"], "runs": res["runs"], "cuts": res["cuts"], "first": res["first"],
            "error": res["error"]}


# ---------------------------------------------------------------- the books

def fx_rate(fx: tuple[np.ndarray, np.ndarray], day) -> float:
    i = int(np.searchsorted(fx[0], np.datetime64(day, "D"), side="right")) - 1
    return float(fx[1][max(i, 0)])


def window(B: ie.Bars, win: str) -> np.ndarray:
    a, z = WINDOWS[win]
    return np.flatnonzero((B.dates >= np.datetime64(a)) & (B.dates <= np.datetime64(z)))


def calendar(days: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Returns on every calendar day from the first session to the last, 0 on days without one."""
    off = (days - days[0]).astype(int)
    out = np.zeros(int(off[-1]) + 1)
    out[off] = r
    return out


def spy_held(B: ie.Bars, idx: np.ndarray, start_usd: float) -> np.ndarray:
    """SPY bought with all of it at the first session's close (one side of the cost model), on the closes after."""
    c = B.c[B.syms.index(BENCH), idx, NB - 1]
    c = c[np.maximum.accumulate(np.where(np.isfinite(c), np.arange(len(c)), 0))]     # a missing close: the last one
    return start_usd * (1 - cost(c[0], NB - 1)) * c / c[0]


def measure(days: np.ndarray, eq: np.ndarray, start_usd: float, fx: tuple, trades=None) -> dict:
    r = eq / np.r_[start_usd, eq[:-1]] - 1
    x = calendar(days, r)
    yrs = max((days[-1] - days[0]).astype(int) + 1, 1) / 365.25
    end_eur = eq[-1] / fx_rate(fx, days[-1]) * (1 - FX_COST)
    m = {"cagr": (eq[-1] / start_usd) ** (1 / yrs) - 1, "max_dd": float(1 - (np.r_[start_usd, eq] / np.maximum.accumulate(
        np.r_[start_usd, eq])).min()), "sharpe": float(x.mean() / x.std() * math.sqrt(365)) if x.std() > 0 else 0.0,
         "total": eq[-1] / start_usd - 1, "end_eur": end_eur}
    if trades is not None:
        m |= {"trades": len(trades), "win": float((trades > 0).mean()) if len(trades) else 0.0,
              "per_trade": float(trades.mean()) if len(trades) else 0.0}
    return m


def plans(B: ie.Bars, F: ie.Features, log=print) -> dict:
    """rule -> (sym, ent, stop or None); the classifier's walk-forward probabilities made once per rule."""
    out = {}
    for rule, (fam, a, b) in RULES.items():
        if fam == "rvol_orb":
            out[rule] = plan_orb(B, F, a, b)
        else:
            sym, ent = plan_clf(B, clf_predict(B, F, a, b), b)
            out[rule] = (sym, ent, None)
        log(f"  {rule}: {int((out[rule][1] >= 0).sum())} sessions with a buy decision")
    return out


def books(B: ie.Bars, pl_: dict, win: str, fx: tuple) -> dict:
    """(rule, acct, variant) -> run, variant late (judged), next (fill at the next bar), stress (costs doubled)."""
    idx = window(B, win)
    start = CAPITAL_EUR * fx_rate(fx, B.dates[idx[0]]) * (1 - FX_COST)
    out = {}
    for rule, (sym, ent, stop) in pl_.items():
        for var, lag, mult in (("late", LAG, 1.0), ("next", 0, 1.0), ("stress", LAG, 2.0)):
            r = trade_returns(B, sym, ent, stop, lag, mult)[idx]
            for acct in ACCOUNTS:
                out[(rule, acct, var)] = run_book(r, acct, start) | {"start": start}
    return out


def evaluate(B: ie.Bars, register: bool = True, leak_checks: bool = True, log=print) -> dict:
    fx = eq1.read_fx()
    F = ie.features(B)
    pl_ = plans(B, F, log)
    days = {w: B.dates[window(B, w)] for w in WINDOWS}
    runs = {w: books(B, pl_, w, fx) for w in ("is",)}
    ins_sh, series = {}, {}
    for (rule, acct, var), r in runs["is"].items():
        if var != "late":
            continue
        x = calendar(days["is"], r["equity"] / np.r_[r["start"], r["equity"][:-1]] - 1)
        series[(rule, acct, "is")] = x
        if RULES[rule][0] == "pattern_clf":
            x = x[(days["is"][0] + np.arange(len(x))) >= np.datetime64(CLF_FROM)]
        ins_sh[(rule, acct)] = float(x.mean() / x.std() * math.sqrt(365)) if x.std() > 0 else 0.0
    trials = [{"id": trial_id(rule, acct), "family": "small", "source": PREREG, "sharpe": ins_sh[(rule, acct)]}
              for rule in RULES for acct in ACCOUNTS]
    if register:
        metrics.register(trials)                         # before any validation number exists
    log("  EQ2 in sample Sharpe (cash, late): " + ", ".join(f"{r} {ins_sh[(r, JUDGED)]:.2f}" for r in RULES))
    runs["val"] = books(B, pl_, "val", fx)
    leaks = {f"{mo}:{k}": leak_check(B, mo, k) for mo, k in CLF_GRID} if leak_checks else {}
    clean = bool(leaks) and all(v["ok"] for v in leaks.values())
    p_all, p_fam = metrics.trial_pool(None, extra=trials), metrics.trial_pool("small", extra=trials)
    for (rule, acct, var), r in runs["val"].items():
        if var == "late":
            series[(rule, acct, "val")] = calendar(days["val"], r["equity"] / np.r_[r["start"], r["equity"][:-1]] - 1)
    cut = (days["is"][0] + np.arange(len(series[(next(iter(RULES)), JUDGED, "is")]))) >= np.datetime64(CLF_FROM)
    M = np.column_stack([np.r_[series[(rule, JUDGED, "is")][cut], series[(rule, JUDGED, "val")]] for rule in RULES])
    pbo = metrics.cscv(M)
    pbo_v = pbo["pbo"] if pbo else None
    bench = {}
    for w in WINDOWS:
        idx = window(B, w)
        start = runs[w][(next(iter(RULES)), JUDGED, "late")]["start"]
        spy = spy_held(B, idx, start)
        bench[w] = {"spy": measure(days[w], spy, start, fx), "nothing": measure(days[w], np.full(len(idx), start),
                                                                                start, fx),
                    "spy_x": calendar(days[w], spy / np.r_[start, spy[:-1]] - 1)}
    rows = []
    for rule in RULES:
        for acct in ACCOUNTS:
            row = {"rule": rule, "family": RULES[rule][0], "account": acct, "trial": trial_id(rule, acct),
                   "is_sharpe": ins_sh[(rule, acct)]}
            for w in WINDOWS:
                for var in ("late", "next", "stress"):
                    r = runs[w][(rule, acct, var)]
                    m = measure(days[w], r["equity"], r["start"], fx, r["trades"])
                    m |= {"skipped_pdt": r["skipped_pdt"], "skipped_cash": r["skipped_cash"]}
                    row[f"{w}_{var}"] = m
            x = series[(rule, acct, "val")]
            row["dsr_all"], row["dsr_small"] = metrics.dsr(x, p_all), metrics.dsr(x, p_fam)
            ex = x - bench["val"]["spy_x"]
            row["excess_sharpe"] = float(ex.mean() / ex.std() * math.sqrt(365)) if ex.std() > 0 else 0.0
            row["dsr_excess_all"] = metrics.dsr(ex, p_all)
            if acct == JUDGED:
                v = row["val_late"]
                row["conditions"] = {
                    "beats nothing (end EUR)": v["end_eur"] > bench["val"]["nothing"]["end_eur"],
                    "DSR all >= 0.95": row["dsr_all"] >= DSR_PASS, "DSR small >= 0.95": row["dsr_small"] >= DSR_PASS,
                    "CAGR > SPY held": v["cagr"] > bench["val"]["spy"]["cagr"],
                    "costs doubled > 0": row["val_stress"]["total"] > 0,
                    f">= {MIN_TRADES} trades": v["trades"] >= MIN_TRADES,
                    "PBO < 0.2": pbo_v is not None and pbo_v < PBO_PASS}
                if RULES[rule][0] == "pattern_clf":
                    row["conditions"]["leak harness clean"] = clean
                row["pass"] = all(row["conditions"].values())
            rows.append(row)
    passed = [r["trial"] for r in rows if r.get("pass")]
    for w in WINDOWS:
        bench[w].pop("spy_x")
    return {"rows": rows, "bench": bench, "pbo": pbo_v, "pbo_combos": pbo["combos"] if pbo else None,
            "pool_all": {"n_trials": p_all["n_trials"], "sr0_annual": p_all["sr0_annual"]},
            "pool_small": {"n_trials": p_fam["n_trials"], "sr0_annual": p_fam["sr0_annual"]},
            "leaks": leaks, "trial_rows": trials, "passed": passed, "notes": B.notes,
            "sessions": {w: [str(days[w][0]), str(days[w][-1]), len(days[w])] for w in WINDOWS}}


# ---------------------------------------------------------------- the report

def _pct(v, d: int = 1) -> str:
    return "n/a" if v is None or not np.isfinite(v) else f"{v * 100:.{d}f} %"


def _cell(m: dict) -> str:
    return f"{_pct(m['cagr'])} / {_pct(m['max_dd'])} / {m['sharpe']:.2f}"


def markdown(out: dict, about: dict) -> str:
    rows, bv = out["rows"], out["bench"]
    s = out["sessions"]
    md = [f"Generated {about['generated']}. {', '.join(out['notes'])}. In sample {s['is'][0]} to {s['is'][1]} "
          f"({s['is'][2]} sessions; the classifier from {CLF_FROM}), validation {s['val'][0]} to {s['val'][1]} "
          f"({s['val'][2]}), every bar after {VAL_TO} dropped at load (the lockbox not read). W4's 41 large caps (today's "
          f"list, survivors). One stock a session with all buying power, filled one bar late (decided at the close of "
          f"bar k, bought at the open of bar k + 2), flat at the 15:55 open; per side the larger of {COST_BPS:g} bps "
          f"and a cent, doubled in the first {OPEN_BARS} bars; EUR to USD {FX_COST * 100:g} % each way; wire fees and "
          f"taxes left out. News tags: not testable (crypto headlines from 2026-10-26 only), no trial.\n",
          "## 1. Validation, one bar late (CAGR / max DD / Sharpe, USD; end value in EUR after both conversions)\n",
          "| rule | account | validation | end EUR | trades (PDT skips) | win | per trade | next bar | costs doubled | "
          "excess Sharpe over SPY | DSR all / small | passes |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["val_late"]
        md.append(f"| {r['rule']} | {r['account']} | {_cell(v)} | {v['end_eur']:.2f} | {v['trades']} ({v['skipped_pdt']})"
                  f" | {_pct(v['win'], 0)} | {_pct(v['per_trade'], 2)} | {_cell(r['val_next'])} | "
                  f"{_pct(r['val_stress']['total'])} total | {r['excess_sharpe']:.2f} | {r['dsr_all']:.3f} / "
                  f"{r['dsr_small']:.3f} | {('yes' if r['pass'] else 'no') if 'pass' in r else 'not judged'} |")
    md.append(f"| doing nothing | | {_cell(bv['val']['nothing'])} | {bv['val']['nothing']['end_eur']:.2f} | | | | | | | | |")
    md.append(f"| SPY held | | {_cell(bv['val']['spy'])} | {bv['val']['spy']['end_eur']:.2f} | | | | | | | | |")
    md.append(f"\nDSR of the daily return (higher is better, pass at 0.95) on calendar days over R5's pool of all "
              f"({out['pool_all']['n_trials']:,} trials, noise bar {out['pool_all']['sr0_annual']:.2f} a year) and the "
              f"small family ({out['pool_small']['n_trials']:,}, {out['pool_small']['sr0_annual']:.2f}). PBO of the "
              f"eight cash-account rules from {CLF_FROM}: " + (f"{out['pbo']:.2f} over {out['pbo_combos']:,} splits."
                                                              if out["pbo"] is not None else "n/a.") + "\n")
    md += ["## 2. In sample, one bar late (same columns)\n",
           "| rule | account | in sample | registered Sharpe | trades (PDT skips) | win | per trade | next bar |",
           "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r["is_late"]
        md.append(f"| {r['rule']} | {r['account']} | {_cell(v)} | {r['is_sharpe']:.2f} | {v['trades']} "
                  f"({v['skipped_pdt']}) | {_pct(v['win'], 0)} | {_pct(v['per_trade'], 2)} | {_cell(r['is_next'])} |")
    md.append(f"| SPY held | | {_cell(bv['is']['spy'])} | | | | | |")
    md.append("\n## 3. The leak harness on the classifier (session and bar on one time axis)\n")
    for n, v in out["leaks"].items():
        md.append(f"- `{n}`: {'clean' if v['ok'] else 'LEAK or not checked'}, {v['runs']} runs, cuts "
                  f"{', '.join(v['cuts'])}" + (f"; first {v['first']}" if v["first"] else "")
                  + (f"; error {v['error']}" if v["error"] else ""))
    fails = {}
    for r in rows:
        for c, ok in (r.get("conditions") or {}).items():
            if not ok:
                fails[c] = fails.get(c, 0) + 1
    md.append("\n## 4. The verdict\n")
    md.append(f"Passed: {', '.join(out['passed']) or 'none'}. Failed conditions over the eight cash-account rules: "
              + ", ".join(f"{c} {n}" for c, n in fails.items()) + ".\n")
    md.append(f"Trials (R5's registry, family small, before the validation numbers): {len(out['trial_rows'])}, "
              f"`small:eq2:<rule>:<cash|margin>`.\n")
    return "\n".join(md)


HEAD = """# EQ2: single-stock day trading at 50 EUR, new signals under the real rules

Pre-registered in `results/daytrade_eq2_prereg.md` (committed before the first run). Code:
`lab.experiments.daytrade_eq2`, tests `tests/test_daytrade_eq2.py`. Paper only: nothing a live bot, a wallet or the
engine reads changed.
"""


def summary(out: dict) -> dict:
    keep = ("cagr", "max_dd", "sharpe", "total", "end_eur", "trades", "win", "per_trade", "skipped_pdt")
    rows = [{k: r.get(k) for k in ("rule", "account", "trial", "is_sharpe", "dsr_all", "dsr_small", "excess_sharpe",
                                   "pass", "conditions")}
            | {w: {k: r[w][k] for k in keep} for w in ("val_late", "val_next", "val_stress", "is_late")}
            for r in out["rows"]]
    return {"study": "EQ2", "prereg": PREREG, "judged": JUDGED, "pbo": out["pbo"], "pool_all": out["pool_all"],
            "pool_small": out["pool_small"], "passed": out["passed"], "bench": out["bench"], "leaks": out["leaks"],
            "rows": rows, "window": [VAL_FROM, VAL_TO], "trials": out["trial_rows"]}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--register" in argv:
        new = metrics.register(json.loads(SUMMARY.read_text(encoding="utf-8"))["trials"])
        print(f"{len(new)} trials appended to {metrics.registry_path()}")
        return 0
    B = load()
    out = evaluate(B, "--no-register" not in argv)
    about = {"generated": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    SUMMARY.write_text(json.dumps(summary(out), indent=1, default=float) + "\n", encoding="utf-8")
    dc.write_results(NAME, markdown(out, about), HEAD)
    print(f"passed: {out['passed'] or 'none'}; PBO {out['pbo']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
