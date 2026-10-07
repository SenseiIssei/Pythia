"""Family 4: mean reversion of major-pair spreads, cointegration tested out of sample.

Fourteen pairs fixed in advance from economic similarity, not from the data:
ETH/BTC, LTC/BTC, BCH/BTC, BCH/LTC, ETC/ETH, BNB/ETH, SOL/ETH, AVAX/SOL,
LINK/ETH, DOGE/BTC, ADA/XRP, DOT/ADA, AAVE/UNI, XLM/XRP.

Walk-forward, every 30 days: on the trailing W days only, fit
log(a) = alpha + beta log(b) by OLS and run an Engle-Granger test on the
residual (ADF with one lag, 5 % critical value -3.34 for two series). For the
next 30 days the spread z = (residual - its window mean) / its window std uses
those frozen numbers. Enter at |z| > z_in (short the rich leg, long the cheap
one, the b leg scaled by beta), exit at |z| < 0.5, stop at |z| > 4, and
re-decide at every refit. Each open pair carries 1/7 of capital gross, the
book is capped at 1x gross. The long leg is spot, the short leg a perpetual
with real funding. Rebalanced daily to the pair weights (the drift turnover is
charged too).

Grid (8 variants): W 90 / 180 days · z_in 1.5 / 2.0 · trade only pairs that
pass the test in their window / trade every pair.

The extra table answers the question behind the family: does a pair that
tests cointegrated in one window still test cointegrated in the next one?
"""

from __future__ import annotations

import itertools

import numpy as np

from . import fam_common as fc

FAMILY = "pairs"
PAIRS = [("ETH", "BTC"), ("LTC", "BTC"), ("BCH", "BTC"), ("BCH", "LTC"), ("ETC", "ETH"), ("BNB", "ETH"),
         ("SOL", "ETH"), ("AVAX", "SOL"), ("LINK", "ETH"), ("DOGE", "BTC"), ("ADA", "XRP"), ("DOT", "ADA"),
         ("AAVE", "UNI"), ("XLM", "XRP")]
WINDOWS = [90, 180]
Z_IN = [1.5, 2.0]
Z_OUT, Z_STOP = 0.5, 4.0
REFIT = 30
EG_CRIT_5 = -3.34
SLOT = 1 / 7


def adf_t(e: np.ndarray) -> float:
    de = np.diff(e)
    y, x1, x2 = de[1:], e[1:-1], de[:-1]
    X = np.column_stack([np.ones_like(x1), x1, x2])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = resid @ resid / max(len(y) - 3, 1)
    cov = s2 * np.linalg.pinv(X.T @ X)
    return float(beta[1] / np.sqrt(cov[1, 1])) if cov[1, 1] > 0 else 0.0


def fit(la: np.ndarray, lb: np.ndarray) -> tuple[float, float, float, float, float] | None:
    ok = np.isfinite(la) & np.isfinite(lb)
    if ok.sum() < 0.9 * len(la):
        return None
    a, b = la[ok], lb[ok]
    X = np.column_stack([np.ones_like(b), b])
    (alpha, beta), *_ = np.linalg.lstsq(X, a, rcond=None)
    e = a - alpha - beta * b
    return alpha, beta, e.mean(), e.std(), adf_t(e)


def pair_cols(P: fc.Panel) -> list[tuple[int, int, str]]:
    out = []
    for a, b in PAIRS:
        out.append((P.col(f"{a}USDT"), P.col(f"{b}USDT"), f"{a}/{b}"))
    return out


def pairs_weights(P: fc.Panel, W: int, z_in: float, need_coint: bool) -> np.ndarray:
    lp = np.log(P.px)
    Wt = np.zeros((P.T, P.N))
    for ia, ib, _ in pair_cols(P):
        # state +1: long the spread (long a, short b), entered when z < -z_in; -1 the reverse.
        state, params, blocked = 0, None, False
        for t in range(W, P.T):
            if t % REFIT == 0:
                f = fit(lp[t - W + 1:t + 1, ia], lp[t - W + 1:t + 1, ib])
                params = f if (f is not None and f[3] > 0 and (not need_coint or f[4] < EG_CRIT_5)
                               and f[1] > 0) else None
                blocked = False
                if params is None:
                    state = 0
            if params is not None and P.traded[t, ia] and P.traded[t, ib]:
                alpha, beta, mu, sd, _ = params
                z = (lp[t, ia] - alpha - beta * lp[t, ib] - mu) / sd
                if state != 0 and abs(z) > Z_STOP:
                    state, blocked = 0, True       # stopped out: no new entry until the next refit
                elif state != 0 and (abs(z) < Z_OUT or np.sign(z) == state):
                    state = 0                      # back to the mean, or crossed it
                if state == 0 and not blocked and abs(z) <= Z_STOP:
                    state = -1 if z > z_in else (1 if z < -z_in else 0)
            if state != 0 and params is not None:
                beta = params[1]
                ga, gb = 1 / (1 + beta), beta / (1 + beta)
                Wt[t, ia] += state * SLOT * ga
                Wt[t, ib] -= state * SLOT * gb
    gross = np.abs(Wt).sum(1, keepdims=True)
    return np.where(gross > 1, Wt / np.maximum(gross, 1e-12), Wt)


def variants(P: fc.Panel) -> list[fc.Result]:
    out = []
    for W, z_in, need in itertools.product(WINDOWS, Z_IN, (True, False)):
        Wt = pairs_weights(P, W, z_in, need)
        name = f"pairs · window {W}d · z {z_in}" + (" · cointegrated only" if need else " · all pairs")
        out.append(fc.run(P, FAMILY, "market-neutral", name, Wt, start=W, spot_only=False))
    return out


def extra_markdown(P: fc.Panel) -> str:
    """How often does in-window cointegration survive into the next, unseen window?"""
    lp = np.log(P.px)
    rows = []
    for W in WINDOWS:
        n_fit = n_pass = n_next = n_next_uncond = n_uncond = 0
        for ia, ib, _ in pair_cols(P):
            for t in range(W, P.T - W, REFIT):
                f = fit(lp[t - W + 1:t + 1, ia], lp[t - W + 1:t + 1, ib])
                g = fit(lp[t + 1:t + W + 1, ia], lp[t + 1:t + W + 1, ib])
                if f is None or g is None:
                    continue
                n_fit += 1
                n_uncond += 1
                n_next_uncond += g[4] < EG_CRIT_5
                if f[4] < EG_CRIT_5:
                    n_pass += 1
                    n_next += g[4] < EG_CRIT_5
        rows.append({"window_days": W, "pair_windows": n_fit, "tested_cointegrated": n_pass / max(n_fit, 1),
                     "still_cointegrated_next_window": n_next / max(n_pass, 1),
                     "cointegrated_next_window_unconditional": n_next_uncond / max(n_uncond, 1)})
    return ("\n## Does cointegration persist out of sample?\n\n"
            "Every 30 days, every pair: Engle-Granger 5 % test on the trailing window, then the same test on the "
            "next, non-overlapping window. With no persistence the conditional and unconditional rates are equal. "
            "About 5 % of windows should pass by chance alone.\n\n"
            + fc.table(rows, list(rows[0])))


if __name__ == "__main__":
    from .families import run_one
    run_one(FAMILY)
    print(extra_markdown(fc.load_panel()))
