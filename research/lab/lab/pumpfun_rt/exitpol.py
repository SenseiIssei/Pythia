"""X14: early detection and exit timing on the study's rows, paths and steps (early.py). PAPER ONLY.

Pre-registered in results/pumpfun_early_exit_plan.md before anything was computed.

  early detection   per label (mig1h, peak3x, peak10x, alive5m), LightGBM and a calibrated
                    logistic baseline in a purged walk-forward: AUC, Brier skill, precision
                    and lift at the top 1 % and 5 %, and the paper books that enter the top
                    (thresholds from the training scores) with exit E0
  exit timing       38 exit policies simulated on every filled position's path: 30 simple
                    baselines and the hazard policy HZ(k) on the exit models (dump10 hazard,
                    up30 upside); the pick in sample, judged out of sample by capture ratio
                    and P&L against the best baseline
  models            what the pipeline's X14 strategies use: e_<label>, hz_dump10, hz_up30 and
                    hz_policy (k*, |L|, the early thresholds per age), saved next to the lab's
                    other pump.fun models by the daily retrain

A sale is simulated as the pipeline's paper executor would fill it: signalled at a
trade (or the time stop), landing one latency draw later at the state then; a sale
into a curve that completed waits for the pool's first trade. Ladders sell parts and
re-check at the landing. The take-profit floor of the pipeline (a step under half its
expected proceeds is not taken) is not modelled.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import curve as C
from . import early as E
from . import model as M

STAKE = E.STAKE
FOLDS = 5
EMBARGO_MS = 10 * 60_000
TOPS = (0.01, 0.05)
DUMP_DROP = 0.25
DUMP_S, UP_S = 10, 30
HZ_K = (0.5, 1.0, 2.0, 4.0)
CROSS_BLOCKS = 3
POS_EMBARGO_MS = E.PATH_H_MS + EMBARGO_MS
MAX_STEPS = 3_000_000
MIN_STEPS = 500
BOOT = 5000


# ---------------------------------------------------------------- policies

@dataclass(frozen=True)
class Policy:
    name: str
    time_s: float = 1800.0
    sl: float | None = None
    tp: float | None = None
    ladder: tuple = ()
    trail_after: float | None = None
    trail_gap: float | None = None
    events: bool = True
    hazard_k: float | None = None


def grid() -> list[Policy]:
    """The 38 registered policies (plan section 2)."""
    base = []
    for s in (30, 120, 600):
        base.append(Policy(f"T{s}", time_s=s))
    for tp, sl in ((0.5, 0.3), (1.0, 0.4), (2.0, 0.5)):
        base.append(Policy(f"TS{int(tp * 100)}_{int(sl * 100)}", sl=sl, tp=tp))
    for lad in (((0.3, 0.5), (0.8, 1.0)), ((0.5, 0.5), (1.5, 1.0)), ((1.0, 0.5), (3.0, 1.0))):
        base.append(Policy(f"L{int(lad[0][0] * 100)}_{int(lad[1][0] * 100)}", sl=0.35, ladder=lad))
    for after in (0.2, 0.5):
        for gap in (0.15, 0.25, 0.40):
            base.append(Policy(f"TR{int(gap * 100)}_{int(after * 100)}", sl=0.35, trail_after=after, trail_gap=gap))
    out = []
    for ev in (True, False):
        for p in base:
            out.append(Policy(p.name + ("+ev" if ev else "-ev"), p.time_s, p.sl, p.tp, p.ladder, p.trail_after,
                              p.trail_gap, ev))
        for k in HZ_K:
            out.append(Policy(f"HZ{k:g}" + ("+ev" if ev else "-ev"), events=ev, hazard_k=k))
    return out


GRID = grid()
E0 = Policy("E0", 1800.0, 0.35, None, ((1.0, 0.5), (3.0, 1.0)), 0.5, 0.25, True)
N_EARLY_BOOKS = 16
N_EXIT = len(GRID)


# ---------------------------------------------------------------- one position

class PathView:
    """One position's path as arrays (times, the state, flags) with its value for any amount."""

    def __init__(self, paths: dict, i: int):
        a, b = int(paths["i_start"][i]), int(paths["i_end"][i])
        self.t = paths["p_t"][a:b]
        self.venue = paths["p_venue"][a:b].astype(np.int64)
        self.x, self.y, self.fee = paths["p_x"][a:b], paths["p_y"][a:b], paths["p_fee"][a:b]
        self.flag = paths["p_flag"][a:b]
        self.tokens = float(paths["i_tokens"][i])
        self.cost_l = float(paths["i_cost_l"][i])
        self.land = float(paths["i_land"][i])
        self._v = {}

    def value(self, amount: float) -> np.ndarray:
        """Lamports a sale of `amount` gets at each point (nan where there is no market)."""
        key = int(amount)
        v = self._v.get(key)
        if v is None:
            v = self._v[key] = E.sale_vec(amount, self.venue, self.x, self.y, self.fee)
        return v

    def at(self, ms: float) -> int:
        """The index of the state at time ms: the last point at or before it (-1 if none)."""
        return int(np.searchsorted(self.t, ms, side="right")) - 1

    def fill(self, amount: float, ms: float) -> tuple[float, float]:
        """(lamports, landing time) of a sale of `amount` landing at ms; a sale with no market waits for the
        first point with one (the executor retries every 2 s), 0 if none comes."""
        j = self.at(ms)
        v = self.value(amount)
        if j >= 0 and np.isfinite(v[j]):
            return float(v[j]), ms
        k = j + 1
        while k < len(v) and not np.isfinite(v[k]):
            k += 1
        if k >= len(v):
            return 0.0, ms
        wait = self.t[k] - ms
        return float(v[k]), ms + 2_000 * math.ceil(max(wait, 0) / 2_000)


def _first(mask: np.ndarray, start: int) -> int | None:
    if start >= len(mask):
        return None
    m = np.flatnonzero(mask[start:])
    return int(m[0]) + start if len(m) else None


def simulate(pol: Policy, pv: PathView, lat, tx: int, hz: tuple | None = None, lat_scale: float = 1.0) -> dict:
    """One policy on one position. `lat(leg)` gives the sale's latency draw in ms; `hz` is (step point
    indices, predicted dump10, predicted up30, |L|) for the hazard policies."""
    left = pv.tokens
    proceeds = 0.0
    legs = 0
    why = None
    step = 0
    peak = -np.inf                              # the trailing stop's peak multiple before `start`
    start = 0                                   # the first point a decision may use (0: the landing)
    now = pv.land                               # no sale is signalled before the last leg landed
    t_end = pv.land + pol.time_s * 1000
    n = len(pv.t)
    while left > 0:
        v = pv.value(left)
        mult = v / (pv.cost_l * left / pv.tokens)
        fin = np.isfinite(mult)
        cand = []                               # (point index, why, sells all)
        if start < n:
            if pol.events:
                j = _first(pv.flag > 0, start)
                if j is not None:
                    cand.append((j, "dev_sell" if pv.flag[j] & 1 else "pull", True))
            if pol.hazard_k is not None and hz is not None and len(hz[0]) and left == pv.tokens:
                sp, pd, pu, loss = hz
                sel = np.flatnonzero((sp >= start) & (pu < pol.hazard_k * pd * loss))
                if len(sel):
                    cand.append((int(sp[sel[0]]), "hazard", True))
            if pol.sl is not None:
                j = _first(fin & (mult <= 1 - pol.sl), start)
                if j is not None:
                    cand.append((j, "stop", True))
            if pol.tp is not None:
                j = _first(fin & (mult >= 1 + pol.tp), start)
                if j is not None:
                    cand.append((j, "take", True))
            if pol.trail_after is not None:
                run = np.maximum(np.fmax.accumulate(np.where(fin, mult, -np.inf)[start:]), peak)
                hit = fin[start:] & (run >= 1 + pol.trail_after) & (mult[start:] <= run * (1 - pol.trail_gap))
                j = _first(hit, 0)
                if j is not None:
                    cand.append((j + start, "trail", True))
            if step < len(pol.ladder):
                j = _first(fin & (mult >= 1 + pol.ladder[step][0]), start)
                if j is not None:
                    cand.append((j, "take", pol.ladder[step][1] >= 1.0))
        best = min(cand, key=lambda c: c[0]) if cand else None     # ties: the protective exits come first
        if best is None or max(pv.t[best[0]], now) >= t_end:
            sig, why_now, all_out = max(t_end, now), "time", True
        else:
            sig, why_now, all_out = max(float(pv.t[best[0]]), now), best[1], best[2]
            if pol.trail_after is not None:
                seg = mult[start:best[0] + 1]
                seg = seg[np.isfinite(seg)]
                if len(seg):
                    peak = max(peak, float(seg.max()))
        if all_out:
            amount = left
        else:
            amount = left - int(pv.tokens * (1 - pol.ladder[step][1]))
            step += 1
        got, land = pv.fill(amount, sig + lat(legs) * lat_scale)
        proceeds += got
        legs += 1
        left -= amount
        why = why_now
        now = land
        if left <= 0:
            break
        # the leg is back: a protective trigger or the time stop that came while it was in flight sells the
        # rest at once (the pipeline's "due"); otherwise the next check is at the landing's state
        flight = slice(pv.at(sig) + 1, pv.at(land) + 1)
        due = pol.events and bool((pv.flag[flight] > 0).any())
        if due or land >= t_end:
            got, land = pv.fill(left, land + lat(legs) * lat_scale)
            proceeds += got
            legs += 1
            left = 0
            why = "dev_sell" if due else "time"
            now = land
            break
        start = max(pv.at(land), 0)
    pnl = proceeds - pv.cost_l - (1 + legs) * tx
    return {"pnl_l": pnl, "ret": pnl / STAKE, "why": why, "exit_ms": now, "legs": legs}


def best_gain(pv: PathView, tx: int) -> float:
    """The best possible result afterwards: all tokens sold at the highest value within 30 minutes."""
    v = pv.value(pv.tokens)
    m = (pv.t <= pv.land + E.PATH_H_MS) & np.isfinite(v)
    if not m.any():
        return -pv.cost_l - 2 * tx
    return float(v[m].max()) - pv.cost_l - 2 * tx


def capture(res: list[dict], best: list[float]) -> dict:
    """Ratio of sums over positions whose best gain is above 0; median per position; never above cost."""
    g = np.array([r["pnl_l"] for r in res], dtype=float)
    b = np.array(best, dtype=float)
    pos = b > 0
    out = {"n": int(len(g)), "never_above_cost": float((~pos).mean()) if len(g) else math.nan}
    if pos.any():
        out["ratio"] = float(g[pos].sum() / b[pos].sum())
        out["median"] = float(np.median(np.clip(g[pos] / b[pos], -5, 1)))
    else:
        out["ratio"] = out["median"] = math.nan
    return out


# ---------------------------------------------------------------- step labels

def step_labels(paths: dict, steps: dict, tx: int) -> dict[str, np.ndarray]:
    """dump10 (the value at a trade within 10 s at or below 75 % of the step's), its log drop, and up30
    (log of the highest value within 30 s over the step's, at least 0), from each position's path."""
    n = len(steps["pos"])
    dump, drop, up, v0 = (np.full(n, np.nan) for _ in range(4))
    pos_ids = paths["i_pos"]
    order = np.argsort(steps["pos"], kind="stable")
    sp = steps["pos"][order]
    bounds = np.searchsorted(sp, pos_ids, side="left"), np.searchsorted(sp, pos_ids, side="right")
    for i in range(len(pos_ids)):
        a, b = bounds[0][i], bounds[1][i]
        if a == b:
            continue
        pv = PathView(paths, i)
        v = pv.value(pv.tokens) - tx
        for s in order[a:b]:
            j = int(steps["pt"][s])
            if j >= len(v) or not np.isfinite(v[j]) or v[j] <= 0:
                continue
            t = pv.t[j]
            w10 = slice(j + 1, int(np.searchsorted(pv.t, t + DUMP_S * 1000, side="right")))
            w30 = slice(j + 1, int(np.searchsorted(pv.t, t + UP_S * 1000, side="right")))
            seg = v[w10]
            seg = seg[np.isfinite(seg)]
            lo = float(seg.min()) if len(seg) else v[j]
            dump[s] = float(lo <= (1 - DUMP_DROP) * v[j])
            drop[s] = math.log(max(lo, 1.0) / v[j])
            seg = v[w30]
            seg = seg[np.isfinite(seg)]
            hi = max(float(seg.max()), v[j]) if len(seg) else v[j]
            up[s] = math.log(hi / v[j])
            v0[s] = v[j]
    return {"dump10": dump, "drop10": drop, "up30": up}


# ---------------------------------------------------------------- models

class FittedReg:
    """A LightGBM regression (the upside model), saved like model.Fitted."""

    def __init__(self, booster, base: float, features: list[str]):
        self.booster, self.base, self.features = booster, base, features

    def predict(self, X: np.ndarray) -> np.ndarray:
        if self.booster is None:
            return np.full(len(X), self.base)
        return self.booster.predict(X)

    def to_json(self) -> dict:
        return {"kind": "reg", "booster": self.booster.model_to_string() if self.booster is not None else None,
                "base": self.base, "features": self.features}

    @classmethod
    def from_json(cls, d: dict) -> "FittedReg":
        booster = None
        if d.get("booster"):
            import lightgbm as lgb
            booster = lgb.Booster(model_str=d["booster"])
        return cls(booster, float(d["base"]), list(d["features"]))


class HzPolicy:
    """k* and |L| of the hazard exit, and the early filters' thresholds by label, top share and age."""
    booster = None
    base = math.nan

    def __init__(self, k: float, loss: float, thresholds: dict, meta: dict | None = None):
        self.k, self.loss, self.thresholds, self.meta = float(k), float(loss), thresholds, meta or {}

    def to_json(self) -> dict:
        return {"kind": "policy", "k": self.k, "loss": self.loss, "thresholds": self.thresholds, "meta": self.meta}

    @classmethod
    def from_json(cls, d: dict) -> "HzPolicy":
        return cls(d["k"], d["loss"], d.get("thresholds") or {}, d.get("meta"))


def fit_reg(X: np.ndarray, y: np.ndarray, features: list[str]) -> FittedReg:
    import lightgbm as lgb
    base = float(np.mean(y)) if len(y) else 0.0
    if len(y) < M.MIN_TRAIN:
        return FittedReg(None, base, features)
    params = {k: v for k, v in M.PARAMS.items()}
    reg = lgb.LGBMRegressor(objective="regression", **params)
    reg.fit(X, y)
    return FittedReg(reg.booster_, base, features)


def logistic_cal(Xtr: np.ndarray, ytr: np.ndarray, Xte: np.ndarray) -> np.ndarray:
    """The baseline: logistic regression on the same features (medians for gaps, standardised), fitted on
    the first 80 % of the training rows and calibrated by isotonic regression on the last 20 %."""
    from sklearn.isotonic import IsotonicRegression
    cut = int(len(ytr) * 0.8)
    if cut < 50 or ytr[:cut].min() == ytr[:cut].max():
        return np.full(len(Xte), float(ytr.mean()) if len(ytr) else 0.0)
    raw_cal = M.logistic(Xtr[:cut], ytr[:cut], Xtr[cut:])
    raw_te = M.logistic(Xtr[:cut], ytr[:cut], Xte)
    if len(set(ytr[cut:].tolist())) < 2:
        return raw_te
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(raw_cal, ytr[cut:])
    return iso.predict(raw_te)


def _x(fr: dict, features: list[str]) -> np.ndarray:
    n = len(fr["t"])
    return np.column_stack([fr[f] if f in fr else np.full(n, math.nan) for f in features]) if n else \
        np.zeros((0, len(features)))


def precision_at(p: np.ndarray, y: np.ndarray, top: float) -> tuple[float, int]:
    """Precision among the top share of rows by score (ties broken by order), and how many rows that is."""
    n = len(p)
    k = max(1, int(math.ceil(top * n))) if n else 0
    if not k:
        return math.nan, 0
    idx = np.argsort(-p, kind="stable")[:k]
    return float(y[idx].mean()), k


# ---------------------------------------------------------------- early detection

def early_rows(data: dict) -> dict[str, np.ndarray]:
    """The early rows not dropped for a gap, in time order, with their index in the saved table ("rid")."""
    fr = dict(data["rows"])
    n = len(fr["t"])
    fr["rid"] = np.arange(n, dtype=np.float64)
    keep = fr["dropped"] == 0 if "dropped" in fr else np.ones(n, dtype=bool)
    order = np.argsort(fr["t"][keep], kind="stable")
    return {k: v[keep][order] for k, v in fr.items()}


def evaluate_early(fr: dict, label: str, features: list[str], folds: int = FOLDS) -> dict:
    """Purged walk-forward of LightGBM and the calibrated logistic baseline; out-of-fold scores kept
    (out["oof"], aligned with fr through oof["at"])."""
    m = np.isfinite(fr[label])
    rs = {k: v[m] for k, v in fr.items()}
    n = len(rs["t"])
    out = {"label": label, "rows": int(n), "folds": [], "oof": None}
    if n < M.MIN_TRAIN + M.MIN_TEST:
        out["verdict"] = f"too few labelled rows ({n})"
        return out
    t, y = rs["t"], rs[label]
    X = _x(rs, features)
    horizon = E.LABELS[label] * 1000 + EMBARGO_MS
    edges = np.quantile(t, np.linspace(0, 1, folds + 2))
    oof = {"gbm": np.full(n, np.nan), "logit": np.full(n, np.nan), "base": np.full(n, np.nan),
           "fold": np.zeros(n, dtype=int), "thr": {}, "at": np.flatnonzero(m)}
    beat = 0
    for i in range(1, folds + 1):
        lo, hi = edges[i], edges[i + 1]
        te = (t >= lo) & ((t < hi) if i < folds else (t <= hi))
        tr = t + horizon < lo
        if tr.sum() < M.MIN_TRAIN or te.sum() < M.MIN_TEST or y[tr].min() == y[tr].max():
            continue
        fit = M.fit(X[tr], y[tr], features)
        pg = fit.predict(X[te])
        pl_ = logistic_cal(X[tr], y[tr], X[te])
        base = float(y[tr].mean())
        sg, sl = M.scores(pg, y[te], base), M.scores(pl_, y[te], base)
        if sg["brier"] < sl["brier"]:
            beat += 1
        tr_g, tr_l = fit.predict(X[tr]), logistic_cal(X[tr], y[tr], X[tr])
        thr = {"gbm": {q: float(np.quantile(tr_g, 1 - q)) for q in TOPS},
               "logit": {q: float(np.quantile(tr_l, 1 - q)) for q in TOPS}}
        out["folds"].append({"fold": i, "train": int(tr.sum()), "test": int(te.sum()), "gbm": sg, "logit": sl,
                             "base_rate": base})
        oof["gbm"][te], oof["logit"][te], oof["base"][te], oof["fold"][te] = pg, pl_, base, i
        oof["thr"][i] = thr
    if not out["folds"]:
        out["verdict"] = "no fold had enough rows before its embargo"
        return out
    k = oof["fold"] > 0
    yy = y[k]
    base_all = float(oof["base"][k].mean())
    pooled = {"gbm": M.scores(oof["gbm"][k], yy, base_all), "logit": M.scores(oof["logit"][k], yy, base_all)}
    prec = {}
    for name in ("gbm", "logit"):
        for q in TOPS:
            hits = ks = 0
            rate_w = 0.0
            for f in out["folds"]:
                sel = oof["fold"] == f["fold"]
                pr, kk = precision_at(oof[name][sel], y[sel], q)
                hits += pr * kk
                ks += kk
                rate_w += float(y[sel].mean()) * kk
            p_ = hits / ks if ks else math.nan
            prec[f"{name}_{q}"] = {"precision": p_, "k": ks,
                                   "lift": p_ / (rate_w / ks) if ks and rate_w > 0 else math.nan}
    by_kind = {}
    for kid, kname in enumerate(E.KINDS):
        sel = k & (rs["kind"] == kid)
        if sel.sum() >= 20 and len(set(y[sel].tolist())) == 2:
            pr, _ = precision_at(oof["gbm"][sel], y[sel], 0.05)
            r_ = float(y[sel].mean())
            by_kind[kname] = {"n": int(sel.sum()), "rate": r_, "auc": M.auc(oof["gbm"][sel], y[sel]),
                              "prec5": pr, "lift5": pr / r_ if r_ > 0 else math.nan}
    need = max(1, math.ceil(0.8 * len(out["folds"])))
    pg = pooled["gbm"]
    useful = bool(pg["auc"] > M.USEFUL_AUC and pg["brier_skill"] > 0 and beat >= need)
    out.update(pooled=pooled, precision=prec, by_kind=by_kind, beats_logistic_folds=beat, useful=useful,
               rate=float(yy.mean()),
               verdict=(f"{'useful' if useful else 'not useful'}: AUC {pg['auc']:.3f} (logistic "
                        f"{pooled['logit']['auc']:.3f}), Brier skill {pg['brier_skill']:+.3f}, beats the logistic "
                        f"baseline in {beat} of {len(out['folds'])} folds"))
    out["oof"] = oof
    return out


def book_rows(fr: dict, oof: dict, name: str, q: float) -> list[int]:
    """The rids a book enters: test rows at or above their fold's training threshold, the first per token."""
    chosen = []
    for j in range(len(oof["at"])):
        f = int(oof["fold"][j])
        if f and oof[name][j] >= oof["thr"][f][name][q]:
            chosen.append(int(oof["at"][j]))
    chosen.sort(key=lambda r: fr["t"][r])
    seen, out = set(), []
    for r in chosen:
        if fr["tid"][r] not in seen:
            seen.add(fr["tid"][r])
            out.append(int(fr["rid"][r]))
    return out


def books(fr: dict, ev: dict, exit_by_rid: dict, t_of: dict) -> tuple[dict, dict]:
    """The paper books of one label (exit E0, and E0 at doubled latency); also the rids entered."""
    oof = ev.get("oof")
    out, entered = {}, {}
    if oof is None:
        return out, entered
    for name in ("gbm", "logit"):
        for q in TOPS:
            rids = book_rows(fr, oof, name, q)
            entered[f"{name}_{q}"] = rids
            tr = [{"ret": exit_by_rid[r]["ret"], "pnl_sol": exit_by_rid[r]["pnl_l"] / C.LAMPORTS,
                   "signal_ms": t_of[r]} for r in rids if r in exit_by_rid]
            st = [{"ret": exit_by_rid[r]["ret2"], "pnl_sol": exit_by_rid[r]["pnl2_l"] / C.LAMPORTS,
                   "signal_ms": t_of[r]} for r in rids if r in exit_by_rid]
            out[f"{name}_{q}"] = book_stats(tr, st)
    return out, entered


def book_stats(trades: list[dict], stress: list[dict] | None = None) -> dict:
    from .study import boot_mean
    rets = np.array([t["ret"] for t in trades], dtype=float)
    out = {"n": int(len(rets)), "pnl_sol": float(sum(t["pnl_sol"] for t in trades))}
    if len(rets):
        lo, hi = boot_mean(trades)
        out.update(mean=float(rets.mean()), median=float(np.median(rets)), hit=float((rets > 0).mean()),
                   band=(lo, hi), best=float(rets.max()), worst=float(rets.min()),
                   days=len({int(t["signal_ms"] // 86_400_000) for t in trades}))
    if stress:
        out["mean_lat2x"] = float(np.mean([t["ret"] for t in stress]))
    return out


# ---------------------------------------------------------------- the exit study

def latency_fn(costs, mint: str, kind: float, pol: str):
    return lambda leg: costs.latency("early", mint, int(kind), pol, "sell", leg)


def usable_positions(data: dict) -> np.ndarray:
    """Positions whose path reaches 30 minutes, with no curve gap, and no pool gap while in the pool."""
    pa = data["paths"]
    ok = (pa["i_full"] > 0) & (pa["i_gap"] == 0)
    pool_gaps = (data.get("gaps") or {}).get("pool") or []
    if pool_gaps:
        g = np.array(pool_gaps, dtype=float)
        for i in np.flatnonzero(ok):
            a, b = int(pa["i_start"][i]), int(pa["i_end"][i])
            pool = pa["p_venue"][a:b] == 1
            if pool.any():
                t0, t1 = pa["p_t"][a:b][pool][0], pa["i_land"][i] + E.PATH_H_MS
                if ((g[:, 0] < t1) & (t0 < g[:, 1])).any():
                    ok[i] = False
    return ok


def mint_of(data: dict, i: int) -> str:
    tid = int(data["paths"]["i_tid"][i])
    mints = data.get("mints") or []
    return mints[tid] if 0 <= tid < len(mints) else str(tid)


def run_policies(data: dict, idx, pols: list[Policy], costs, preds: dict | None, loss: float,
                 lat_scale: float = 1.0) -> dict[str, list[dict]]:
    """Every policy on every position in idx; preds: position index -> (step points, P(dump10), up30)."""
    pa = data["paths"]
    tx = costs.tx_lamports()
    out = {p.name: [] for p in pols}
    for i in idx:
        pv = PathView(pa, i)
        mint = mint_of(data, i)
        hz = None
        if preds is not None and i in preds:
            sp, pd, pu = preds[i]
            hz = (sp, pd, pu, loss)
        for pol in pols:
            if pol.hazard_k is not None and hz is None:
                continue
            r = simulate(pol, pv, latency_fn(costs, mint, pa["i_kind"][i], pol.name), tx, hz, lat_scale)
            r["i"], r["signal_ms"] = int(i), pv.land
            out[pol.name].append(r)
    return out


def hazard_models(st: dict, mask: np.ndarray, features: list[str]) -> tuple:
    """hz_dump10 (calibrated LightGBM), hz_up30 (LightGBM regression) and |L| from the training steps
    (the first 10 minutes of each position, plan section 2)."""
    m = mask & np.isfinite(st["dump10"]) & (st["tau_s"] <= E.STEP_TRAIN_S)
    if m.sum() > MAX_STEPS:
        keep = np.flatnonzero(m)
        m = np.zeros_like(m)
        m[keep[np.linspace(0, len(keep) - 1, MAX_STEPS).astype(int)]] = True
    order = np.argsort(st["t"][m], kind="stable")
    sub = {k: v[m][order] for k, v in st.items()}
    yd = sub["dump10"]
    dumps = sub["drop10"][yd == 1]
    loss = float(-np.mean(dumps)) if len(dumps) else -math.log(1 - DUMP_DROP)
    if len(yd) < MIN_STEPS or yd.min() == yd.max():
        return None, None, loss
    X = _x(sub, features)
    return M.fit(X, yd, features), fit_reg(X, sub["up30"], features), loss


def preds_by_pos(st: dict, sel: np.ndarray, md, mu, features: list[str], pos_index: dict) -> dict:
    """Position index -> (step points, P(dump10), predicted up30) for the selected steps."""
    ids = np.flatnonzero(sel)
    if not len(ids):
        return {}
    X = _x({k: v[ids] for k, v in st.items()}, features)
    pd, pu = md.predict(X), mu.predict(X)
    out: dict[int, tuple] = {}
    pos = st["pos"][ids]
    order = np.argsort(pos, kind="stable")
    pos_s = pos[order]
    cuts = np.flatnonzero(np.diff(pos_s)) + 1
    for grp in np.split(order, cuts):
        i = pos_index.get(int(pos[grp[0]]))
        if i is None:
            continue
        g = grp[np.argsort(st["pt"][ids[grp]], kind="stable")]
        out[i] = (st["pt"][ids[g]].astype(np.int64), pd[g], pu[g])
    return out


def mean_ret(rs: list[dict]) -> float:
    return float(np.mean([r["ret"] for r in rs])) if rs else math.nan


def _mix(rs: list[dict]) -> dict:
    out: dict[str, int] = {}
    for r in rs:
        out[r["why"] or "?"] = out.get(r["why"] or "?", 0) + 1
    return out


def summarise(rs: list[dict], best: dict) -> dict:
    c = capture(rs, [best[r["i"]] for r in rs])
    return {"n": len(rs), "mean": mean_ret(rs), "pnl_sol": float(sum(r["pnl_l"] for r in rs)) / C.LAMPORTS,
            "capture": c, "why": _mix(rs)}


def cross_fit(data: dict, st: dict, positions: list[int], pos_index: dict, step_land: np.ndarray,
              until_ms: float, features: list[str]) -> tuple[dict, float]:
    """In-sample predictions for the hazard policies: each time block of the positions predicted by models
    trained on the other blocks, a position's 30 minutes plus the embargo purged at every boundary."""
    land = data["paths"]["i_land"]
    preds: dict = {}
    if not positions:
        return preds, -math.log(1 - DUMP_DROP)
    lands = np.array([land[i] for i in positions])
    edges = np.quantile(lands, np.linspace(0, 1, CROSS_BLOCKS + 1))
    for b in range(CROSS_BLOCKS):
        lo, hi = edges[b], edges[b + 1]
        in_b = (step_land >= lo) & ((step_land < hi) if b < CROSS_BLOCKS - 1 else (step_land <= hi))
        train = (step_land < until_ms - POS_EMBARGO_MS) & ((step_land < lo - POS_EMBARGO_MS)
                                                           | (step_land > hi + POS_EMBARGO_MS))
        md, mu, _ = hazard_models(st, train, features)
        if md is not None and in_b.any():
            preds.update(preds_by_pos(st, in_b, md, mu, features, pos_index))
    _, _, loss = hazard_models(st, step_land < until_ms - POS_EMBARGO_MS, features)
    return preds, loss


def pick_by_mean(names: list[str], sims: dict, common: set | None) -> str | None:
    def m(name):
        rs = [r for r in sims[name] if r["i"] in common] if common else sims[name]
        v = mean_ret(rs)
        return v if math.isfinite(v) else -9.0
    names = [n for n in names if sims.get(n)]
    return max(names, key=m) if names else None


def prepare(data: dict, costs) -> dict:
    """Step labels, the step frame with each step's landing, the position index and the usable positions."""
    tx = costs.tx_lamports()
    pa = data["paths"]
    st = dict(data["steps"])
    st.update(step_labels(pa, data["steps"], tx))
    pos_index = {int(p): i for i, p in enumerate(pa["i_pos"])}
    land = pa["i_land"]
    st_land = np.array([land[pos_index[int(p)]] if int(p) in pos_index else np.nan for p in st["pos"]])
    return {"st": st, "pos_index": pos_index, "step_land": st_land, "usable": usable_positions(data)}


def run(data: dict, costs=None, split_ms: float | None = None, log=print) -> dict:
    """The whole X14 evaluation on one study's rows, paths and steps (plan sections 1 and 2)."""
    costs = costs or C.Costs()
    tx = costs.tx_lamports()
    fr = early_rows(data)
    feats = E.early_feature_list()
    pa = data["paths"]
    raw = data["rows"]
    n_pos = len(pa["i_pos"])
    if split_ms is None:
        t = raw["t"]
        split_ms = float(t.min() + (t.max() - t.min()) / 2) if len(t) else 0.0
    pre = prepare(data, costs)
    st, pos_index, step_land, ok = pre["st"], pre["pos_index"], pre["step_land"], pre["usable"]
    usable = [i for i in range(n_pos) if ok[i]]
    res = {"split_ms": split_ms, "rows": int(len(fr["t"])), "rows_dropped": int(len(raw["t"]) - len(fr["t"])),
           "positions": n_pos, "usable_positions": len(usable), "steps": int(len(st.get("pos", [])))}

    # E0 for every usable position (the early books); a failed buy costs its fee
    e0 = run_policies(data, usable, [E0], costs, None, 0.0)["E0"]
    e02 = run_policies(data, usable, [E0], costs, None, 0.0, lat_scale=2.0)["E0"]
    exit_by_rid: dict[int, dict] = {}
    for r, r2 in zip(e0, e02):
        exit_by_rid[int(pa["i_row"][r["i"]])] = {"ret": r["ret"], "pnl_l": r["pnl_l"], "ret2": r2["ret"],
                                                 "pnl2_l": r2["pnl_l"]}
    for j in np.flatnonzero(raw["filled"] == 0):
        exit_by_rid[int(j)] = {"ret": -tx / STAKE, "pnl_l": -tx, "ret2": -tx / STAKE, "pnl2_l": -tx}
    t_of = {int(r): float(t) for r, t in zip(fr["rid"], fr["t"])}

    # 1. early detection
    early, entered = {}, {}
    for label in E.LABELS:
        ev = evaluate_early(fr, label, feats)
        bk, ent = books(fr, ev, exit_by_rid, t_of)
        ev.pop("oof", None)
        early[label] = {**ev, "books": bk}
        entered[label] = ent
        log(f"x14 early {label}: {ev.get('verdict')}")
    res["early"] = early

    # 2. exit timing: in sample (cross-fitted hazard predictions), out of sample (in-sample models)
    land = pa["i_land"]
    is_pos = [i for i in usable if land[i] < split_ms]
    oos_pos = [i for i in usable if land[i] >= split_ms]
    sfeat = list(E.STEP_FEATURES)
    preds_is, loss = cross_fit(data, st, is_pos, pos_index, step_land, split_ms, sfeat)
    md, mu, loss = hazard_models(st, step_land < split_ms - POS_EMBARGO_MS, sfeat)
    preds_oos, hz_eval = {}, {}
    sel = step_land >= split_ms
    if md is not None and sel.any():
        preds_oos = preds_by_pos(st, sel, md, mu, sfeat, pos_index)
        hz_eval = hazard_eval(st, step_land, split_ms, md, mu, sfeat)
    res["hazard_models"] = {"loss": loss, "eval": hz_eval, "is_positions": len(is_pos), "oos_positions": len(oos_pos),
                            "is_with_preds": len(preds_is), "oos_with_preds": len(preds_oos)}
    sim_is = run_policies(data, is_pos, GRID, costs, preds_is, loss)
    sim_oos = run_policies(data, oos_pos, GRID, costs, preds_oos, loss)
    best_is = {i: best_gain(PathView(pa, i), tx) for i in is_pos}
    best_oos = {i: best_gain(PathView(pa, i), tx) for i in oos_pos}
    table = {p.name: {"is": summarise(sim_is[p.name], best_is), "oos": summarise(sim_oos[p.name], best_oos)}
             for p in GRID}
    common = set(preds_is) or None
    names_all = [p.name for p in GRID if p.hazard_k is None or common]
    pick = pick_by_mean(names_all, sim_is, common)
    base_pick = pick_by_mean([p.name for p in GRID if p.hazard_k is None], sim_is, common)
    hz_pick = pick_by_mean([p.name for p in GRID if p.hazard_k is not None and p.events], sim_is, common) \
        if common else None
    k_star = next((p.hazard_k for p in GRID if p.name == hz_pick), 1.0) if hz_pick else 1.0
    judge = {"pick": pick, "base_pick": base_pick, "hz_pick": hz_pick, "k_star": k_star}
    from .study import boot_diff, boot_mean
    for name in {pick, base_pick, hz_pick} - {None}:
        rs = sim_oos.get(name) or []
        judge[f"band_{name}"] = boot_mean([{"ret": r["ret"], "signal_ms": r["signal_ms"]} for r in rs])
    for a_name in (pick, hz_pick):
        if a_name and base_pick and a_name != base_pick:
            a = [{"ret": r["ret"], "signal_ms": r["signal_ms"]} for r in sim_oos.get(a_name) or []]
            b = [{"ret": r["ret"], "signal_ms": r["signal_ms"]} for r in sim_oos.get(base_pick) or []]
            judge[f"diff_{a_name}"] = boot_diff(a, b) if a and b else (math.nan, math.nan)
    hz_diff = judge.get(f"diff_{hz_pick}") if hz_pick else None
    judge["hazard_better"] = bool(hz_diff is not None and math.isfinite(hz_diff[0]) and hz_diff[0] > 0
                                  and table[hz_pick]["oos"]["mean"] > table[base_pick]["oos"]["mean"])
    res["exit"] = {"table": table, "judge": judge}
    # the same policies on the top 5 % peak3x LightGBM entries that landed out of sample
    row_pos = {int(pa["i_row"][i]): i for i in oos_pos}
    top_pos = {row_pos[r] for r in entered.get("peak3x", {}).get("gbm_0.05", []) if r in row_pos}
    res["exit_top5"] = {p.name: summarise([r for r in sim_oos[p.name] if r["i"] in top_pos], best_oos)
                        for p in GRID} if top_pos else {}
    res["exit_top5_n"] = len(top_pos)
    log(f"x14 exits: pick {pick}, baseline pick {base_pick}, hazard pick {hz_pick} (k* {k_star:g}); "
        f"{len(is_pos)} positions in sample, {len(oos_pos)} out")
    return res


def hazard_eval(st: dict, step_land: np.ndarray, split_ms: float, md, mu, features: list[str]) -> dict:
    """Out of sample: dump10 against the base rate and the calibrated logistic baseline, up30 against the
    training mean."""
    trm = (step_land < split_ms - POS_EMBARGO_MS) & np.isfinite(st["dump10"]) & (st["tau_s"] <= E.STEP_TRAIN_S)
    te = (step_land >= split_ms) & np.isfinite(st["dump10"]) & (st["tau_s"] <= E.STEP_TRAIN_S)
    out = {}
    if not te.any() or not trm.any():
        return out
    sub_tr = {k: v[trm] for k, v in st.items()}
    sub_te = {k: v[te] for k, v in st.items()}
    o_tr, o_te = np.argsort(sub_tr["t"], kind="stable"), np.argsort(sub_te["t"], kind="stable")
    sub_tr = {k: v[o_tr] for k, v in sub_tr.items()}
    sub_te = {k: v[o_te] for k, v in sub_te.items()}
    Xtr, Xte = _x(sub_tr, features), _x(sub_te, features)
    y = sub_te["dump10"]
    base = float(sub_tr["dump10"].mean())
    if len(set(y.tolist())) == 2:
        out["dump10"] = {"gbm": M.scores(md.predict(Xte), y, base),
                         "logit": M.scores(logistic_cal(Xtr, sub_tr["dump10"], Xte), y, base), "steps": int(len(y))}
    u = sub_te["up30"]
    pu = mu.predict(Xte)
    mean_tr = float(sub_tr["up30"].mean())
    sse, sst = float(np.sum((pu - u) ** 2)), float(np.sum((mean_tr - u) ** 2))
    out["up30"] = {"r2_vs_train_mean": 1 - sse / sst if sst > 0 else math.nan,
                   "corr": float(np.corrcoef(pu, u)[0, 1]) if pu.std() > 0 and u.std() > 0 else math.nan,
                   "steps": int(len(u))}
    return out


# ---------------------------------------------------------------- the models the pipeline uses

def fit_live(data: dict, costs=None, until_ms: float | None = None, k: float | None = None, log=print) -> dict:
    """e_<label>, hz_dump10, hz_up30 and hz_policy from every row and step whose window ends before until_ms
    (all of them when None). k None: k* chosen on these positions by the cross-fitted in-sample selection."""
    costs = costs or C.Costs()
    fr = early_rows(data)
    feats = E.early_feature_list()
    out: dict = {}
    thresholds: dict = {}
    for label, h in E.LABELS.items():
        m = np.isfinite(fr[label])
        if until_ms is not None:
            m &= fr["t"] + h * 1000 + EMBARGO_MS < until_ms
        sub = {kk: v[m] for kk, v in fr.items()}
        fit = M.fit(_x(sub, feats), sub[label], feats)
        out["e_" + label] = fit
        if fit.booster is None:
            continue
        sc = fit.predict(_x(sub, feats))
        thresholds[label] = {str(q): {kind: float(np.quantile(sc[sub["kind"] == kid], 1 - q))
                                      for kid, kind in enumerate(E.KINDS) if (sub["kind"] == kid).sum() >= 20}
                             for q in TOPS}
    pre = prepare(data, costs)
    st, step_land = pre["st"], pre["step_land"]
    lim = np.inf if until_ms is None else until_ms - POS_EMBARGO_MS
    md, mu, loss = hazard_models(st, step_land < lim, list(E.STEP_FEATURES))
    if md is not None:
        out["hz_dump10"], out["hz_up30"] = md, mu
    if k is None:
        k = select_k(data, costs, pre, until_ms, log)
    out["hz_policy"] = HzPolicy(k, loss, thresholds, {"until_ms": until_ms, "rows": int(len(fr["t"])),
                                                      "steps": int(len(st.get("pos", [])))})
    return out


def select_k(data: dict, costs, pre: dict, until_ms: float | None, log=print) -> float:
    """k* among the HZ(k) with the event exits, by the in-sample mean on cross-fitted predictions."""
    pa = data["paths"]
    lim = np.inf if until_ms is None else until_ms - E.PATH_H_MS - E.PATH_PAD_MS
    positions = [i for i in range(len(pa["i_pos"])) if pre["usable"][i] and pa["i_land"][i] < lim]
    preds, loss = cross_fit(data, pre["st"], positions, pre["pos_index"], pre["step_land"],
                            np.inf if until_ms is None else until_ms, list(E.STEP_FEATURES))
    if not preds:
        return 1.0
    pols = [p for p in GRID if p.hazard_k is not None and p.events]
    sims = run_policies(data, [i for i in positions if i in preds], pols, costs, preds, loss)
    best = pick_by_mean([p.name for p in pols], sims, None)
    k = next((p.hazard_k for p in pols if p.name == best), 1.0)
    log(f"x14: k* {k:g} on {len(preds)} positions")
    return k


def pipeline_capture(trades: list[dict], max_done: dict, tx: int) -> dict:
    """The capture ratio of a pipeline strategy's closed paper trades: realised P&L over the best possible
    result (all its tokens sold at the highest value within 30 minutes of the landing, early.Tracker.watch_max)."""
    got, best = [], []
    for t in trades:
        m = max_done.get((t.get("book"), t.get("pid")))
        if m is None or not m.get("complete"):
            continue
        got.append({"pnl_l": t["pnl_sol"] * C.LAMPORTS})
        best.append(m["max_l"] - m["cost_l"] - tx)
    return capture(got, best)


def save_models(models: dict, d: Path) -> None:
    d.mkdir(parents=True, exist_ok=True)
    for name, m in models.items():
        tmp = d / f"{name}.json.tmp"
        tmp.write_text(json.dumps(m.to_json()), encoding="utf-8")
        tmp.replace(d / f"{name}.json")


LIVE_NAMES = [f"e_{k}" for k in E.LABELS] + ["hz_dump10", "hz_up30", "hz_policy"]


def load_models(d: Path) -> dict:
    out = {}
    for name in LIVE_NAMES:
        p = d / f"{name}.json"
        if not p.exists():
            continue
        try:
            js = json.loads(p.read_text(encoding="utf-8"))
            kind = js.get("kind")
            out[name] = (HzPolicy.from_json(js) if kind == "policy" else FittedReg.from_json(js) if kind == "reg"
                         else M.Fitted.from_json(js))
        except (OSError, ValueError, KeyError):
            pass
    return out


# ---------------------------------------------------------------- report

def _p(x, signed: bool = True) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "n/a"
    return f"{x * 100:+.1f} %" if signed else f"{x * 100:.1f} %"


def _f(x, fmt: str = "{:.3f}") -> str:
    return "n/a" if x is None or (isinstance(x, float) and not math.isfinite(x)) else fmt.format(x)


def summary(res: dict) -> dict:
    """What the daily card and the models' meta show of X14."""
    j = (res.get("exit") or {}).get("judge") or {}
    tab = (res.get("exit") or {}).get("table") or {}

    def cap(name):
        return ((tab.get(name) or {}).get("oos") or {}).get("capture", {}).get("ratio") if name else None
    pk = (((res.get("early") or {}).get("peak3x") or {}).get("precision") or {}).get("gbm_0.05") or {}
    return {"pick": j.get("pick"), "base_pick": j.get("base_pick"), "hz_pick": j.get("hz_pick"),
            "k_star": j.get("k_star"), "capture_pick": cap(j.get("pick")), "capture_base": cap(j.get("base_pick")),
            "capture_hz": cap(j.get("hz_pick")), "hazard_better": bool(j.get("hazard_better")),
            "prec5_peak3x": pk.get("precision"), "lift5_peak3x": pk.get("lift"),
            "rate_peak3x": ((res.get("early") or {}).get("peak3x") or {}).get("rate"),
            "positions": res.get("usable_positions"), "rows": res.get("rows")}


def report_md(res: dict, day: str = "") -> str:
    md = [f"# pump.fun early detection and exit timing (X14){' (' + day + ')' if day else ''}", "",
          "Paper only. Pre-registered in results/pumpfun_early_exit_plan.md. Every fill with latency, the fee and "
          "the priority fee; out of sample only; under 14 days of record every verdict is \"too early\".", "",
          f"{res['rows']:,} early rows ({res.get('rows_dropped', 0):,} dropped for a gap), {res['positions']:,} "
          f"filled paper buys with a path, {res['usable_positions']:,} usable (30 minutes recorded, no gap), "
          f"{res['steps']:,} step rows.", "", "## 1. Early detection (purged walk-forward, out of fold)", "",
          "| label | rows | rate | AUC | logistic AUC | Brier skill | logistic Brier skill | prec. top 1 % (lift) | "
          "prec. top 5 % (lift) | logistic top 5 % (lift) | verdict |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for label, ev in (res.get("early") or {}).items():
        po = ev.get("pooled") or {}
        pr = ev.get("precision") or {}

        def pl(key):
            v = pr.get(key) or {}
            return f"{_p(v.get('precision'), False)} ({_f(v.get('lift'), '{:.2f}')}x)" if v else "n/a"
        md.append(f"| {label} | {ev.get('rows', 0):,} | {_p(ev.get('rate'), False)} | "
                  f"{_f((po.get('gbm') or {}).get('auc'))} | {_f((po.get('logit') or {}).get('auc'))} | "
                  f"{_f((po.get('gbm') or {}).get('brier_skill'), '{:+.3f}')} | "
                  f"{_f((po.get('logit') or {}).get('brier_skill'), '{:+.3f}')} | {pl('gbm_0.01')} | {pl('gbm_0.05')} | "
                  f"{pl('logit_0.05')} | {ev.get('verdict', '')} |")
    md += ["", "By decision kind (LightGBM, top 5 %):", "", "| label | kind | rows | rate | AUC | prec. top 5 % | lift |",
           "|---|---|---|---|---|---|---|"]
    for label, ev in (res.get("early") or {}).items():
        for kind, v in (ev.get("by_kind") or {}).items():
            md.append(f"| {label} | {kind} | {v['n']:,} | {_p(v['rate'], False)} | {_f(v['auc'])} | "
                      f"{_p(v['prec5'], False)} | {_f(v['lift5'], '{:.2f}')} |")
    md += ["", "Paper books (exit E0; thresholds from each fold's training scores; one entry per token):", "",
           "| label | book | trades | mean | median | hit | P&L SOL | band of mean | lat 2x |", "|---|---|---|---|---|---|---|---|---|"]
    for label, ev in (res.get("early") or {}).items():
        for name, b in (ev.get("books") or {}).items():
            band = b.get("band") or (math.nan, math.nan)
            md.append(f"| {label} | {name} | {b['n']} | {_p(b.get('mean'))} | {_p(b.get('median'))} | "
                      f"{_p(b.get('hit'), False)} | {b['pnl_sol']:+.3f} | {_p(band[0])} to {_p(band[1])} | "
                      f"{_p(b.get('mean_lat2x'))} |")
    ex = res.get("exit") or {}
    j = ex.get("judge") or {}
    hm = res.get("hazard_models") or {}
    md += ["", "## 2. Exit timing", "",
           f"In sample {hm.get('is_positions', 0):,} positions ({hm.get('is_with_preds', 0):,} with cross-fitted hazard "
           f"predictions), out of sample {hm.get('oos_positions', 0):,} ({hm.get('oos_with_preds', 0):,}). |L| = "
           f"{_f(hm.get('loss'))}. In-sample pick {j.get('pick')}, best baseline {j.get('base_pick')}, hazard pick "
           f"{j.get('hz_pick')} (k* {j.get('k_star')}). Hazard better out of sample: "
           f"{'yes' if j.get('hazard_better') else 'no'}.", ""]
    ev_ = hm.get("eval") or {}
    if ev_.get("dump10"):
        d = ev_["dump10"]
        md.append(f"dump10 out of sample ({d['steps']:,} steps, rate {_p(d['gbm']['rate'], False)}): AUC "
                  f"{_f(d['gbm']['auc'])} (logistic {_f(d['logit']['auc'])}), Brier skill "
                  f"{_f(d['gbm']['brier_skill'], '{:+.3f}')} (logistic {_f(d['logit']['brier_skill'], '{:+.3f}')}).")
    if ev_.get("up30"):
        u = ev_["up30"]
        md.append(f"up30 out of sample: R2 against the training mean {_f(u['r2_vs_train_mean'], '{:+.3f}')}, "
                  f"correlation {_f(u['corr'])}.")
    for name in (j.get("pick"), j.get("hz_pick")):
        if name and f"diff_{name}" in j:
            lo, hi = j[f"diff_{name}"]
            md.append(f"{name} minus {j.get('base_pick')} out of sample, 90 % band of the mean difference: "
                      f"{_p(lo)} to {_p(hi)}.")
    md += ["", "| policy | IS mean | IS capture | OOS trades | OOS mean | OOS capture | OOS median capture | "
           "OOS P&L SOL | never above cost |", "|---|---|---|---|---|---|---|---|---|"]
    for name, v in (ex.get("table") or {}).items():
        i, o = v["is"], v["oos"]
        md.append(f"| {name} | {_p(i['mean'])} | {_p(i['capture']['ratio'])} | {o['n']:,} | {_p(o['mean'])} | "
                  f"{_p(o['capture']['ratio'])} | {_p(o['capture'].get('median'))} | {o['pnl_sol']:+.2f} | "
                  f"{_p(o['capture']['never_above_cost'], False)} |")
    top = res.get("exit_top5") or {}
    if top:
        md += ["", f"The same policies on the {res.get('exit_top5_n', 0)} top 5 % peak3x entries that landed out "
               "of sample:", "", "| policy | trades | mean | capture | P&L SOL |", "|---|---|---|---|---|"]
        for name, o in top.items():
            md.append(f"| {name} | {o['n']} | {_p(o['mean'])} | {_p(o['capture']['ratio'])} | {o['pnl_sol']:+.3f} |")
    return "\n".join(md) + "\n"


def jsonable(res: dict) -> dict:
    """The result without the fitted models."""
    return {k: v for k, v in res.items() if k != "models_is"}
