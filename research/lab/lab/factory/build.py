"""From genome to daily returns: features, target weights and a long-only simulator.

Everything runs on the sweep's survivorship-free daily panel
(fam_common.load_panel) with the lab's timing: what is decided at the close of
day t earns day t+1's return, and the turnover traded at that close is charged
against day t+1. Costs are per unit of one-way turnover.

To stay fast, a Ctx keeps only the panel columns that any universe (or its
twin) ever holds, and memoises every feature a genome asks for, so a factory
run evaluates hundreds of genomes on one set of arrays.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..data import UNIVERSE
from ..experiments import fam_common as fc
from ..experiments.alpaca_universe import ALPACA, annual_lists
from . import grammar

COSTS = {"15bps": 0.0015, "35bps": 0.0035, "70bps": 0.0070}
BASE_COST = "35bps"       # Alpaca taker plus slippage, the hand studies' judging cost
COIN_VOL = 0.40           # per-coin annual vol target of "invvol slots", as in the paper books
LIST_SIZE = {"core": 20, "alpaca": 15}


@dataclass
class Ctx:
    P: fc.Panel
    cols: np.ndarray
    days: np.ndarray
    px: np.ndarray
    ret: np.ndarray
    alive: np.ndarray
    traded: np.ndarray
    sigma: np.ndarray
    adv28: np.ndarray
    qv: np.ndarray
    btc_px: np.ndarray
    uni: dict[str, np.ndarray]
    names: list[str]
    memo: dict = field(default_factory=dict)

    @property
    def T(self) -> int:
        return len(self.days)

    def feat(self, name: str, fn):
        if name not in self.memo:
            self.memo[name] = fn()
        return self.memo[name]


def member(P: fc.Panel, bases) -> np.ndarray:
    """(N,) the current segment of each listed base (a reused ticker's dead segment is not tradable)."""
    return np.array([b in bases and "~" not in n for b, n in zip(P.bases, P.names)])


def make_ctx(P: fc.Panel) -> Ctx:
    full: dict[str, np.ndarray] = {}
    for n in grammar.UNIVERSES["top"]["n"]:
        full[f"top{n}"] = P.top_liquid(n)
    full["core"] = P.eligible & member(P, set(UNIVERSE))[None, :]
    full["alpaca"] = P.eligible & member(P, set(ALPACA))[None, :]
    # The point-in-time twins of the two fixed lists: the same number of the most
    # liquid eligible coins at the first close of each year, frozen for that year.
    for kind, size in LIST_SIZE.items():
        m, _ = annual_lists(P, size)
        full[f"twin_{kind}"] = P.eligible & m
    cols = np.flatnonzero(np.any([m.any(0) for m in full.values()], axis=0))
    btc_px = P.px[:, P.btc]
    return Ctx(P=P, cols=cols, days=P.days, px=P.px[:, cols], ret=P.ret[:, cols], alive=P.alive[:, cols],
               traded=P.traded[:, cols], sigma=P.sigma[:, cols], adv28=P.adv28[:, cols],
               qv=P.extra["qv"][:, cols], btc_px=btc_px, uni={k: v[:, cols] for k, v in full.items()},
               names=[P.names[j] for j in cols])


# ---------------------------------------------------------------- features

def past_return(c: Ctx, lb: int) -> np.ndarray:
    def f():
        out = np.full_like(c.px, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            out[lb:] = c.px[lb:] / c.px[:-lb] - 1
        return out
    return c.feat(f"ret{lb}", f)


def ma(c: Ctx, m: int) -> np.ndarray:
    return c.feat(f"ma{m}", lambda: fc.rolling(c.px, m, m))


def annvol(c: Ctx) -> np.ndarray:
    return c.feat("annvol", lambda: c.sigma * np.sqrt(365))


def btc_gate(c: Ctx, kind: str, p: int) -> np.ndarray:
    def f():
        if kind == "regime":
            avg = fc.rolling(c.btc_px[:, None], p, p)[:, 0]
            with np.errstate(invalid="ignore"):
                return np.nan_to_num(c.btc_px > avg, nan=0.0).astype(bool)
        past = np.full_like(c.btc_px, np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            past[p:] = c.btc_px[p:] / c.btc_px[:-p] - 1
            return np.nan_to_num(past > 0, nan=0.0).astype(bool)
    return c.feat(f"btc_{kind}{p}", f)


def volume_ratio(c: Ctx, slow: int) -> np.ndarray:
    def f():
        q = np.where(c.alive, np.nan_to_num(c.qv), np.nan)
        with np.errstate(invalid="ignore", divide="ignore"):
            return fc.rolling(q, 7, 5) / fc.rolling(q, slow, int(slow * 0.7))
    return c.feat(f"vr{slow}", f)


def donchian_on(c: Ctx, n: int, exit_frac: float) -> np.ndarray:
    """In the breakout state: entered on a close above the highest close of the
    previous n days, left on a close below the lowest close of the previous
    round(n * exit) days or when the series ends."""
    m = max(2, round(n * exit_frac))

    def f():
        hi = c.feat(f"hi{n}", lambda: fc.rolling_extreme(c.px, n, "max"))
        lo = c.feat(f"lo{m}", lambda: fc.rolling_extreme(c.px, m, "min"))
        with np.errstate(invalid="ignore"):
            enter = c.px > hi
            leave = (c.px < lo) | ~c.alive
        on = np.zeros_like(enter)
        held = np.zeros(enter.shape[1], dtype=bool)
        for t in range(c.T):
            held = (held & ~leave[t]) | (enter[t] & ~leave[t])
            on[t] = held
        return on
    return c.feat(f"don{n}_{m}", f)


def signal(c: Ctx, s: dict) -> tuple[np.ndarray, np.ndarray]:
    """(on, strength), both (T, n)."""
    k = s["kind"]
    with np.errstate(invalid="ignore", divide="ignore"):
        if k == "mom":
            r = past_return(c, s["lb"])
            return r > 0, r / annvol(c)
        if k == "rev":
            r = past_return(c, s["lb"])
            return r < 0, -r
        if k == "ma":
            a, b = ma(c, s["fast"]), ma(c, s["slow"])
            return a > b, a / b - 1
        if k == "donchian":
            r = past_return(c, s["n"])
            return donchian_on(c, s["n"], s["exit"]), r / annvol(c)
        if k == "lowvol":
            return np.isfinite(c.sigma), -c.sigma
    raise grammar.GenomeError(f"unknown signal {k}")


def universe_mask(c: Ctx, u: dict, twin: bool = False) -> np.ndarray:
    if u["kind"] == "top":
        return c.uni[f"top{u['n']}"]
    return c.uni[("twin_" if twin else "") + u["kind"]]


# ---------------------------------------------------------------- weights

def top_k(score: np.ndarray, cand: np.ndarray, k: int) -> np.ndarray:
    s = np.where(cand & np.isfinite(score), score, -np.inf)
    if s.shape[1] <= k:
        return cand & np.isfinite(s)
    part = np.argpartition(-s, k - 1, axis=1)[:, :k]
    out = np.zeros_like(cand)
    np.put_along_axis(out, part, True, axis=1)
    return out & np.isfinite(s)


def weights(c: Ctx, g: dict, twin: bool = False) -> np.ndarray:
    """(T, n) target weights decided at each close, 0 where not held. No NaN."""
    uni = universe_mask(c, g["universe"], twin)
    on, strength = signal(c, g["signal"])
    cand = uni & on
    rows_off = np.zeros(c.T, dtype=bool)
    with np.errstate(invalid="ignore"):
        for f in g["filters"]:
            k = f["kind"]
            if k == "regime":
                rows_off |= ~btc_gate(c, "regime", f["ma"])
            elif k == "btcmom":
                rows_off |= ~btc_gate(c, "btcmom", f["lb"])
            elif k == "vol":
                cand &= annvol(c) < f["max"]
            elif k == "volume":
                cand &= volume_ratio(c, f["slow"]) >= f["min"]
            elif k == "trend":
                cand &= c.px > ma(c, f["ma"])
    sel = g["select"]
    score = {"signal": strength, "liquidity": c.adv28, "lowvol": -c.sigma}[sel["rank"]]
    held = top_k(score, cand, sel["k"])
    held &= np.isfinite(c.sigma) & (c.sigma > 0)
    held[rows_off] = False
    K = sel["k"]
    w8 = g["weight"]
    av = annvol(c)
    with np.errstate(invalid="ignore", divide="ignore"):
        if w8["scheme"] == "equal":
            raw = held.astype(float)
        else:
            raw = np.where(held, 1.0 / av, 0.0)
        if w8["fill"] == "full":
            s = raw.sum(1, keepdims=True)
            W = np.where(s > 0, raw / np.where(s > 0, s, 1.0), 0.0)
        elif w8["scheme"] == "equal":
            W = raw / K
        else:
            W = np.where(held, np.minimum(COIN_VOL / av / K, 1.0 / K), 0.0)
    return np.nan_to_num(W)


# ---------------------------------------------------------------- simulation

def simulate(c: Ctx, W: np.ndarray, every: int = 1, band: float = 0.0, start: int = 0,
             keep_at: int | None = None, offset: int = 0):
    """Long-only, like fam_common.simulate, plus a rebalance cadence and a no-trade band.

    Rebalance days are calendar days with (day number since 1970 - offset) % every
    == 0, so the cadence does not depend on where the panel starts. On those days a
    held coin whose target is within band * target of its drifted weight is
    left alone; exits always trade. Returns (gross, turnover, exposure), each
    (T,), and with keep_at also the weights held after the close of that day.
    """
    T, n = W.shape
    dayno = c.days // fc.DAY_US
    reb = ((dayno - offset) % every) == 0
    w = np.zeros(n)
    kept = None
    gross, tov, expo = np.zeros(T), np.zeros(T), np.zeros(T)
    ret = np.nan_to_num(c.ret)
    for t in range(start, T):
        if reb[t]:
            tgt = W[t]
            tgt = np.where(c.traded[t] | (tgt == w), tgt, w)
            if band > 0:
                keep = (tgt > 0) & (w > 0) & (np.abs(tgt - w) <= band * tgt)
                tgt = np.where(keep, w, tgt)
            tov[t] += np.abs(tgt - w).sum()
            w = tgt
        expo[t] = w.sum()
        if t == keep_at:
            kept = w.copy()
        if t == T - 1:
            break
        r = ret[t + 1]
        g = float(w @ r)
        gross[t + 1] = g
        if 1 + g > 0:
            w = w * (1 + r) / (1 + g)
        else:
            w = np.zeros(n)
        dead = (w != 0) & ~c.alive[t + 1]
        if dead.any():
            tov[t + 1] += np.abs(w[dead]).sum()
            w[dead] = 0.0
    if keep_at is not None:
        return gross, tov, expo, kept
    return gross, tov, expo


def simulate_tranches(c: Ctx, W: np.ndarray, every: int, band: float, n: int, keep_at: int | None = None):
    """n sleeves, each a simulate() with its own rebalance day (offsets 0 to n-1),
    together one book. Each sleeve starts with 1/n of the capital and keeps what
    it earns, so a sleeve's share of the book drifts with its gross returns (the
    way the tsmom_tranches paper book keeps its "alloc"). Turnover and exposure
    are in units of the whole book. Same returns as simulate()."""
    outs = [simulate(c, W, every, band, keep_at=keep_at, offset=i) for i in range(n)]
    g = np.array([o[0] for o in outs])                 # (n, T)
    eq = np.cumprod(1 + g, axis=1)                     # each sleeve's capital after each close
    after = eq / eq.sum(0, keepdims=True)              # shares after the close of t
    before = np.hstack([np.full((n, 1), 1 / n), after[:, :-1]])   # shares going into day t
    gross = (before * g).sum(0)
    tov = (after * np.array([o[1] for o in outs])).sum(0)
    expo = (after * np.array([o[2] for o in outs])).sum(0)
    if keep_at is None:
        return gross, tov, expo
    kept = sum(after[i, keep_at] * outs[i][3] for i in range(n))
    return gross, tov, expo, kept


def _sim(c: Ctx, W: np.ndarray, g: dict, keep_at: int | None = None):
    r = g["rebalance"]
    if r.get("tranches", 1) > 1:
        return simulate_tranches(c, W, r["every"], r["band"], r["tranches"], keep_at=keep_at)
    return simulate(c, W, r["every"], r["band"], keep_at=keep_at)


def run(c: Ctx, g: dict, twin: bool = False, late: bool = False):
    """(gross, turnover, exposure) of a genome. late: every decision filled one close later."""
    W = weights(c, g, twin)
    if late:
        W = np.vstack([np.zeros((1, W.shape[1])), W[:-1]])
    return _sim(c, W, g)


def net(gross: np.ndarray, tov: np.ndarray, cost: float) -> np.ndarray:
    return gross - cost * np.r_[0.0, tov[:-1]]


def holdings(c: Ctx, g: dict, t: int) -> dict[str, float]:
    """What the genome's book holds after the decision close of day t (drifted, as simulated)."""
    *_, w = _sim(c, weights(c, g), g, keep_at=t)
    return {c.names[j]: float(w[j]) for j in np.flatnonzero(w > 1e-9)}
