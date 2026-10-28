"""Loss functions and tests used by every experiment."""

from __future__ import annotations

import itertools
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats


def qlike(realised_var: np.ndarray, forecast_var: np.ndarray) -> np.ndarray:
    """Patton's QLIKE, robust to noise in the realised-variance proxy. Lower is better, 0 is perfect."""
    ratio = realised_var / forecast_var
    return ratio - np.log(ratio) - 1.0


def r2(y: np.ndarray, pred: np.ndarray) -> float:
    return float(1.0 - np.mean((y - pred) ** 2) / np.var(y))


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, lag: int = 24) -> tuple[float, float]:
    """DM test on loss_a - loss_b with a Newey-West variance. Negative stat: A is better.

    Returns (statistic, two-sided p-value).
    """
    d = loss_a - loss_b
    d = d[np.isfinite(d)]
    n = d.size
    dc = d - d.mean()
    var = np.dot(dc, dc) / n
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)
        var += 2 * w * np.dot(dc[k:], dc[:-k]) / n
    stat = d.mean() / math.sqrt(var / n)
    return float(stat), float(2 * stats.norm.sf(abs(stat)))


def deflated_sharpe(sharpe: float, n_obs: int, n_trials: int | None = None, sharpe_var_trials: float | None = None,
                    skew: float = 0.0, kurt: float = 3.0, family: str | None = None) -> float:
    """Bailey and Lopez de Prado. Probability that the true Sharpe is above the best of
    n_trials pure-noise strategies (the DSR: higher is better, pass at 0.95 or more). Sharpe values are
    per observation, not annualised. Without n_trials and sharpe_var_trials both come from the trial
    registry: the family's pool, or with family None the pool of all."""
    if n_trials is None or sharpe_var_trials is None:
        p = trial_pool(family)
        n_trials = p["n_trials"] if n_trials is None else n_trials
        sharpe_var_trials = p["var"] if sharpe_var_trials is None else sharpe_var_trials
    sr0 = expected_max_sharpe(sharpe_var_trials, n_trials)
    denom = math.sqrt(1 - skew * sharpe + (kurt - 1) / 4 * sharpe ** 2)
    return float(stats.norm.cdf((sharpe - sr0) * math.sqrt(n_obs - 1) / denom))


# ---------------------------------------------------------------------------
# The trial registry (R5): one count of trials for every study and factory
# ---------------------------------------------------------------------------
#
# <data>/trials/registry.jsonl (PYTHIA_TRIALS_REGISTRY), append-only, one line a trial or a block of trials:
#   {"id", "family", "source", "n": 1, "sharpe": annual in-sample Sharpe or null, "var": per-day variance of the
#    block's trial Sharpes or null, "added"}
# A line whose id is already there is never written again. The hand studies' counts before the registry are
# TRIAL_SEED (from director_common and the results files), always part of what is read, written into the file
# with its first line. The factories register every ledger line (lab.factory.ledger), one trial per genome.
# A family's pool: N is every trial in it; the variance pools the blocks' variances (each over its n) with the
# variance of its single trials' Sharpes (clipped at +-3 a year, like fam_common.deflate); a block or trial
# without either only counts. In all: N over every family, the variance the families' pooled by their weight.
# Only per-day Sharpes of daily books pool here: pump.fun's per-entry Sharpes (F3, the Y studies) stay outside.

G_EULER = 0.5772156649
SR_CLIP = 3.0
FAMILIES = ("hand", "factory", "small")
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43        # the hand studies' published bar to C16: the best of 377 at 2.43 a year


def expected_max_sharpe(var: float, n: int) -> float:
    """Expected best per-observation Sharpe of n noise trials with this variance of trial Sharpes (SR0)."""
    if n <= 1 or var <= 0:
        return 0.0
    return math.sqrt(var) * ((1 - G_EULER) * stats.norm.ppf(1 - 1 / n) + G_EULER * stats.norm.ppf(1 - 1 / (n * math.e)))


def prior_var() -> float:
    """The per-day variance of trial Sharpes backed out of the published bar, as every hand study since C16."""
    return (PRIOR_SR0 / math.sqrt(365) / expected_max_sharpe(1.0, PRIOR_TRIALS)) ** 2


def _block(id_: str, family: str, n: int, source: str, var: float | None) -> dict:
    return {"id": id_, "family": family, "source": source, "n": n, "sharpe": None, "var": var, "added": "seed"}


# The hand count step by step as the results files published it (1,377 after 2026-10-21), each block at the
# prior variance; S1 picked from 61 configurations (it counted 8), S2 8, L1's change of tsmom1 1, all three only
# counted (the small family's variance comes from F2's genomes, as F2's pool did).
TRIAL_SEED = [
    _block("hand:to_c16", "hand", 377, "results/alpaca_universe.md (C16)", prior_var()),
    _block("hand:c16_to_x11", "hand", 571, "results/candles_prereg.md (948 after X11)", prior_var()),
    _block("hand:x15_candles", "hand", 47, "results/candles.md", prior_var()),
    _block("hand:x16_equities_training", "hand", 120, "results/candles.md (1,115 after X15 and X16)", prior_var()),
    _block("hand:director_2026_10_20", "hand", 9, "lab/experiments/director_common.py (gated_btc 4, genome_gates 4, "
           "m4_residual 1)", prior_var()),
    _block("hand:polymarket", "hand", 16, "results/polymarket_study.md", prior_var()),
    _block("hand:batches_2026_10_21", "hand", 188, "results/perps_neutral_portfolio_prereg.md (perp studies 37, equity "
           "survey 33, vol/ETF 22, crypto_own 94 with O9's 2)", prior_var()),
    _block("hand:perps_attention_intraday", "hand", 25, "results/perps_neutral_portfolio.md", prior_var()),
    _block("hand:positioning_taker_hedged_pead", "hand", 24, "results/hedged_breakout.md (1,377 after)", prior_var()),
    _block("small:s1", "small", 61, "results/smallaccount_s1.md (61 configurations, 8 candidates)", None),
    _block("small:s2", "small", 8, "results/smallaccount_s2.md", None),
    _block("small:l1", "small", 1, "results/onchain_longterm_l1.md (tsmom1 on BTC/ETH, ETH at most 25 %, 10 % band)",
           None),
]


def registry_path() -> Path:
    env = os.environ.get("PYTHIA_TRIALS_REGISTRY")
    if env:
        return Path(env)
    return Path(os.environ.get("PYTHIA_DATA", "/data")) / "trials" / "registry.jsonl"


def _read(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line) if line.strip() else None
        except ValueError:
            continue           # a torn last line from a killed run
        if isinstance(r, dict) and r.get("id"):
            out.append(r)
    return out


def read_registry(path: Path | None = None) -> list[dict]:
    """Every trial: the file's lines, then the seed's blocks it does not hold yet; one line per id, the first."""
    seen, out = set(), []
    for r in _read(path or registry_path()) + TRIAL_SEED:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out


def register(rows: list[dict], path: Path | None = None) -> list[dict]:
    """Append the trials whose id is not in the file yet (the seed first, once); returns what was appended.
    Never rewrites or removes a line."""
    p = path or registry_path()
    have = {r["id"] for r in _read(p)}
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    new = []
    for r in TRIAL_SEED + list(rows):
        if r["id"] not in have:
            have.add(r["id"])
            new.append({"n": 1, "sharpe": None, "var": None, **r, "added": r.get("added") or now})
    if new:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            for r in new:
                fh.write(json.dumps(r, separators=(",", ":"), default=float) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    return [r for r in new if not any(r["id"] == s["id"] for s in TRIAL_SEED)]


def _family_pool(rows: list[dict]) -> dict:
    n = sum(int(r.get("n") or 1) for r in rows)
    blocks = [(int(r.get("n") or 1), float(r["var"])) for r in rows if r.get("var") is not None]
    x = np.array([float(r["sharpe"]) for r in rows if r.get("var") is None and r.get("sharpe") is not None
                  and math.isfinite(float(r["sharpe"]))])
    x = np.clip(x, -SR_CLIP, SR_CLIP) / math.sqrt(365)
    w = sum(k for k, _ in blocks) + len(x)
    s = sum(k * v for k, v in blocks) + (len(x) * float(np.var(x)) if len(x) > 1 else 0.0)
    return {"n_trials": n, "var": s / w if w else 0.0, "weight": w}


def trial_pool(family: str | None = None, extra: list[dict] = (), path: Path | None = None) -> dict:
    """{"n_trials", "var" (per-day), "sr0_annual", "family", "families": {name: the same}} of one family or, with
    family None, of all. extra: trials not registered (yet), counted once with the registry's by id."""
    rows = read_registry(path)
    seen = {r["id"] for r in rows}
    rows += [r for r in extra if r["id"] not in seen]
    fams: dict[str, list[dict]] = {}
    for r in rows:
        fams.setdefault(r.get("family") or "hand", []).append(r)
    per = {f: _family_pool(rs) for f, rs in sorted(fams.items())}
    for p in per.values():
        p["sr0_annual"] = expected_max_sharpe(p["var"], p["n_trials"]) * math.sqrt(365)
    if family is not None:
        p = per.get(family, {"n_trials": 0, "var": 0.0, "weight": 0, "sr0_annual": 0.0})
        return {**p, "family": family, "families": per}
    n = sum(p["n_trials"] for p in per.values())
    w = sum(p["weight"] for p in per.values())
    v = sum(p["weight"] * p["var"] for p in per.values()) / w if w else 0.0
    return {"n_trials": n, "var": v, "weight": w, "sr0_annual": expected_max_sharpe(v, n) * math.sqrt(365),
            "family": "all", "families": per}


def dsr(x: np.ndarray, pool: dict | None = None, family: str | None = None) -> float:
    """Deflated Sharpe ratio of a daily return series (higher is better, pass at 0.95 or more) against a pool,
    by default the registry's family or all. 0 when it cannot be measured."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2 or x.std() == 0:
        return 0.0
    s = float(x.mean() / x.std())
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    pool = pool or trial_pool(family)
    return deflated_sharpe(s, len(x), pool["n_trials"], pool["var"], sk, ku)


# ---------------------------------------------------------------------------
# T2: overfitting yardsticks (results/overfit_yardsticks_prereg.md)
# ---------------------------------------------------------------------------
#
# cscv: PBO by combinatorially symmetric CV (Bailey, Borwein, Lopez de Prado, Zhu) on a matrix of per-period
# performance, the rank logits' distribution with it. spa and mcs: Hansen's superior predictive ability test and the
# model confidence set (Hansen, Lunde, Nason), with arch as the reference, on the stationary bootstrap of Politis and
# Romano. Losses are lower-is-better throughout; SPA's p is the probability of a statistic this large when no model
# beats the benchmark.

CSCV_BLOCKS = 16
LOGIT_BINS = (-3.0, -2.0, -1.0, 0.0, 1.0, 2.0, 3.0)    # the histogram's inner edges (open at both ends)
BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED = 1000, 10, 7
SPA_P, MCS_ALPHA = 0.05, 0.10


def cscv(M: np.ndarray, blocks: int = CSCV_BLOCKS, stat: str = "sharpe") -> dict | None:
    """PBO of picking the best column of M (periods x strategies, higher is better) by CSCV: the periods cut into
    `blocks` blocks, every half of them in sample and the rest out; per split the in-sample best (by Sharpe, or by
    mean with stat "mean") and its relative rank w out of sample; PBO is the share of logits log(w / (1 - w)) at or
    below 0. None with fewer than 2 columns or blocks shorter than 5 periods."""
    M = np.asarray(M, dtype=float)
    T, m = M.shape if M.ndim == 2 else (0, 0)
    L = T // blocks
    if m < 2 or L < 5:
        return None
    B = M[: L * blocks].reshape(blocks, L, m)
    bs, bq = B.sum(1), (B ** 2).sum(1)
    combos = np.array([[i in cmb for i in range(blocks)] for cmb in itertools.combinations(range(blocks), blocks // 2)],
                      dtype=float)
    n = L * blocks // 2

    def perf(Cm):
        mu = Cm @ bs / n
        if stat == "mean":
            return mu
        return mu / np.sqrt(np.maximum(Cm @ bq / n - mu ** 2, 1e-18))

    logits = []
    for i in range(0, len(combos), 2000):
        Cm = combos[i:i + 2000]
        ins, out = perf(Cm), perf(1 - Cm)
        best = ins.argmax(1)
        ob = out[np.arange(len(Cm)), best]
        w = ((out < ob[:, None]).sum(1) + 1) / (m + 1)
        logits.append(np.log(w / (1 - w)))
    lam = np.concatenate(logits)
    hist = np.bincount(np.searchsorted(LOGIT_BINS, lam, side="right"), minlength=len(LOGIT_BINS) + 1)
    return {"pbo": float((lam <= 0).mean()), "combos": len(lam), "genomes": m, "blocks": blocks,
            "median_logit": float(np.median(lam)),
            "logit_q": {str(q): float(np.percentile(lam, q)) for q in (5, 25, 50, 75, 95)},
            "logit_hist": {"edges": list(LOGIT_BINS), "counts": [int(x) for x in hist]}}


def logit_text(p: dict) -> str:
    """The rank logits of a cscv result in words: the quantiles and the histogram."""
    q, h = p["logit_q"], p["logit_hist"]
    e = h["edges"]
    labels = [f"<{e[0]:g}"] + [f"{a:g}..{b:g}" for a, b in zip(e[:-1], e[1:])] + [f">{e[-1]:g}"]
    return (f"rank logits 5/25/50/75/95 %: {q['5']:.2f} / {q['25']:.2f} / {q['50']:.2f} / {q['75']:.2f} / "
            f"{q['95']:.2f}; histogram " + ", ".join(f"{a} {c}" for a, c in zip(labels, h["counts"])))


def stationary_bootstrap(n: int, draws: int = BOOT_DRAWS, block: float = BOOT_BLOCK, seed: int = BOOT_SEED) -> np.ndarray:
    """(draws, n) indices of Politis and Romano's stationary bootstrap: blocks of geometric length with mean
    `block`, wrapping around the end."""
    rng = np.random.default_rng(seed)
    idx = np.empty((draws, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, draws)
    fresh = rng.random((draws, n)) < 1.0 / max(block, 1.0)
    starts = rng.integers(0, n, (draws, n))
    for t in range(1, n):
        idx[:, t] = np.where(fresh[:, t], starts[:, t], (idx[:, t - 1] + 1) % n)
    return idx


def sb_variance(X: np.ndarray, block: float = BOOT_BLOCK) -> np.ndarray:
    """Hansen's (2005) kernel estimate of n times the variance of each column's mean under the stationary
    bootstrap: the autocovariances weighted by kappa(i) = (n - i) / n (1 - q)^i + i / n (1 - q)^(n - i), q = 1/block."""
    X = np.asarray(X, dtype=float).reshape(len(X), -1)
    n = len(X)
    Xc = X - X.mean(0)
    q = 1.0 / max(block, 1.0)
    f = np.fft.rfft(Xc, 2 * n, axis=0)
    g = np.fft.irfft(f * np.conj(f), axis=0)[:n] / n            # autocovariances at lags 0 .. n-1
    i = np.arange(n)[:, None]
    k = (n - i) / n * (1 - q) ** i + i / n * (1 - q) ** (n - i)
    return g[0] + 2 * (k[1:] * g[1:]).sum(0)


def _boot_means(X: np.ndarray, idx: np.ndarray) -> np.ndarray:
    """(draws, columns): each column's mean over every bootstrap draw."""
    return np.stack([X[i].mean(0) for i in idx])


def spa(bench: np.ndarray, models: np.ndarray, draws: int = BOOT_DRAWS, block: float = BOOT_BLOCK,
        seed: int = BOOT_SEED) -> dict:
    """Hansen's SPA test: is any model's loss lower than the benchmark's? bench (periods,), models (periods,) or
    (periods, k), losses per period, lower is better. Returns the consistent p-value ("p", the test) with the lower
    and upper ones, the statistic and the best model's column. Periods with a missing loss are dropped."""
    b = np.asarray(bench, dtype=float)
    X = np.asarray(models, dtype=float).reshape(len(b), -1)
    ok = np.isfinite(b) & np.isfinite(X).all(1)
    d = b[ok, None] - X[ok]                       # positive: the model's loss is lower
    n, k = d.shape
    if n < 10:
        return {"p": 1.0, "p_lower": 1.0, "p_upper": 1.0, "stat": 0.0, "best": None, "n": n,
                "why": f"only {n} periods"}
    dbar = d.mean(0)
    mu_b = _boot_means(d, stationary_bootstrap(n, draws, block, seed))
    omega = np.sqrt(np.maximum(sb_variance(d, block), 1e-18))
    t = math.sqrt(n) * dbar / omega
    stat = max(float(t.max()), 0.0)
    thr = -np.sqrt(omega ** 2 / n * 2 * math.log(max(math.log(n), 1.0 + 1e-9)))
    out = {"stat": stat, "best": int(t.argmax()), "n": n, "mean_gain": [float(x) for x in dbar]}
    for name, g in (("p_lower", np.maximum(dbar, 0)), ("p", dbar * (dbar >= thr)), ("p_upper", dbar)):
        z = math.sqrt(n) * (mu_b - g) / omega
        out[name] = float((np.maximum(z.max(1), 0.0) >= stat).mean()) if stat > 0 else 1.0
    return out


def mcs(losses: np.ndarray, names: list[str] | None = None, alpha: float = MCS_ALPHA, draws: int = BOOT_DRAWS,
        block: float = BOOT_BLOCK, seed: int = BOOT_SEED) -> dict:
    """The model confidence set (Hansen, Lunde, Nason) with the T-max statistic: while the set's models are not
    equally good at alpha, drop the one with the largest standardised mean loss over the set's average. losses
    (periods, models), lower is better. Returns MCS p-values per model (the running maximum) and the set at alpha."""
    L = np.asarray(losses, dtype=float)
    L = L[np.isfinite(L).all(1)]
    n, m = L.shape
    names = list(names) if names is not None else [str(i) for i in range(m)]
    if n < 10 or m < 2:
        return {"pvalues": {x: 1.0 for x in names}, "included": names, "alpha": alpha, "n": n}
    lbar = L.mean(0)
    lb = _boot_means(L, stationary_bootstrap(n, draws, block, seed))
    live, pv, run = list(range(m)), {}, 0.0
    while len(live) > 1:
        a = np.array(live)
        d = lbar[a] - lbar[a].mean()
        db = lb[:, a] - lb[:, a].mean(1, keepdims=True)
        sd = np.sqrt(np.maximum(((db - d) ** 2).mean(0), 1e-18))
        t = d / sd
        p = float((((db - d) / sd).max(1) >= t.max()).mean())
        run = max(run, p)
        worst = int(a[t.argmax()])
        pv[names[worst]] = run
        live.remove(worst)
    pv[names[live[0]]] = 1.0
    return {"pvalues": pv, "included": [x for x in names if pv[x] >= alpha], "alpha": alpha, "n": n}
