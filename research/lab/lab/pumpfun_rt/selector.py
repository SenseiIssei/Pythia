"""A1 (results/pumpfun_adaptive_a1_prereg.md): the selector over the model zoo (zoo.py), per label. PAPER ONLY.

Every day the daily retrain (retrain.run_a1) tests each member of the zoo on each UTC day of the study's rows not yet
tested: trained on the rows whose label was known before the day started (the newest MAX_TRAIN), it predicts the
day's rows (walk). Next to the members a stacked blend: non-negative weights summing to one, fitted to the members'
out-of-sample predictions of the N days before (blend_weights). A day's out-of-sample log loss per candidate, and the
noise band of each pair (the standard error of the per-row loss differences), go into a history that only grows: a
day once tested is never tested again (state.json). The members' predictions of the last N days are kept for the blend
and the calibration (oof/<label>/<day>.npz).

The selection (choose), replayed over the whole history in day order, the incumbent first LightGBM (today's model):
  retirement   a member worse than the logistic baseline on each of the last RETIRE_DAYS days is retired for good
               (a new registration brings it back); a retired incumbent is replaced by the lowest N-day loss
  evidence     a challenger takes over only when it was ahead of the incumbent beyond the band (loss lower by more
               than BAND_Z standard errors) on each of the last EVIDENCE_DAYS days; among several, the lowest N-day
               loss
The pick's probabilities are calibrated by isotonic regression fitted to its out-of-sample predictions of the N days
before (out of fold), when there are CAL_MIN of them with both classes, kept within CAL_BOUND of 0 and 1 (a step of
a few hundred rows at 0 or 1 costs a log loss without limit).

Regimes (regime_of): market heat from the select rows' new pools per 15 min, buy volume per 15 min and the share of
rugs in the last hour (rug_share_1h, added here as a feature from the rows' own rug labels known by then), each as its
percentile among the training rows, averaged; cold, normal, hot at the terciles. The decision rows have only the new
coins of the last 10 minutes (market_10m). The report says per regime which candidate had the lowest loss.

Nothing a paper book or the live bot reads changes: the paper books keep LightGBM until A1's study shows the selector
better out of sample (the pre-registration's rule); reports/pumpfun_rt/zoo.{md,json}.
"""

from __future__ import annotations

import json
import math
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from . import model as M
from . import zoo as Z

N_DAYS = 7
EVIDENCE_DAYS = 5
RETIRE_DAYS = 7
BAND_Z = 1.0
CAL_MIN = 200
CAL_BOUND = 0.01                                       # the calibrated probabilities kept in [0.01, 0.99]
MAX_TRAIN = 300_000
MIN_TRAIN = {"decision": M.MIN_TRAIN, "select": 200}
MIN_TEST = 50
STEP_MS = 3_600_000                                    # the online member's update step in the walk-forward
DAY_MS = 86_400_000
HOUR_MS = 3_600_000
RUG_SHARE_H_MS = HOUR_MS
REGIMES = ("cold", "normal", "hot")
BLEND = "blend"
# the labels: the decision rows' realistic round trips (R2) and the select labels with the trend features (Y10, R2)
LABELS = {"win30": "decision", "win300": "decision", "win0t": "select", "rug0t": "select", "win5t": "select",
          "rug5t": "select"}
HEAT = {"decision": ["market_10m"], "select": ["mkt_pools_15m", "mkt_buy_sol_15m", "rug_share_1h"]}


def zoo_dir() -> Path:
    return M.model_dir() / "zoo"


def day_of(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def day_start(d: str) -> int:
    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


# ---------------------------------------------------------------- the label tables

def rug_share(table: dict, at: np.ndarray, window_ms: int = RUG_SHARE_H_MS) -> np.ndarray:
    """The share of rugs among the migrations (entry 0 rows) whose rug window ended in the window_ms before each time
    in `at`; NaN without any."""
    from .selfeat import RUG_MS
    m = (table["entry"] == 0) & np.isfinite(table["rug"])
    known = table["t"][m] + RUG_MS
    o = np.argsort(known, kind="stable")
    known, rug = known[o], table["rug"][m][o]
    cs = np.r_[0.0, np.cumsum(rug)]
    hi = np.searchsorted(known, at, side="right")
    lo = np.searchsorted(known, at - window_ms, side="right")
    n = hi - lo
    with np.errstate(all="ignore"):
        return np.where(n > 0, (cs[hi] - cs[lo]) / np.maximum(n, 1), np.nan)


def table_for(label: str, rows: dict | None, sel: dict | None) -> dict | None:
    """One label's rows in time order: X, y, t, the purge horizon, the features, the heat columns, and for the select
    win labels the exit time and the return (the hazard member's). None without rows."""
    from . import labels_r2 as L2
    from . import selmodel as SM
    fam = LABELS[label]
    if fam == "decision":
        if rows is None or not len(rows.get("t", [])):
            return None
        rs = M.labelled(L2.realistic_rows(rows) or rows, label)
        rs = {k: v[-M.MAX_ROWS:] for k, v in rs.items()}
        feats = list(M.FEATURES)
        h_ms = M.LABELS[label] * 1000 + M.EMBARGO_MS
        y, kind, extra = rs[label], "any", {}
    else:
        if sel is None or not len(sel.get("t", [])) or (label in SM.TREND_LABELS and not SM.has_trend(sel)):
            return None
        full = dict(sel)
        full["rug_share_1h"] = rug_share(sel, sel["t"])
        rs = SM.rows_for(full, label)
        feats = SM.features_for(label) + ["rug_share_1h"]
        h_ms = SM.LABEL_H_MS
        y = rs[SM.LABELS[label][1]]
        kind = "exit" if SM.LABELS[label][1] == "win" else "any"
        extra = {"dur": (rs["exit_ms"] - rs["t"]) / 1000.0, "ret": rs["ret"]}
    if not len(y):
        return None
    return {"label": label, "family": fam, "kind": kind, "t": rs["t"], "y": y.astype(float), "X": M.matrix(rs, feats),
            "features": feats, "h_ms": h_ms, "heat": M.matrix(rs, HEAT[fam]), **extra}


# ---------------------------------------------------------------- regimes

def heat_score(train: np.ndarray, X: np.ndarray) -> np.ndarray:
    """Each heat column's percentile among the training rows, averaged over the columns known (NaN without any)."""
    cols = []
    for j in range(X.shape[1]):
        tr = np.sort(train[:, j][np.isfinite(train[:, j])])
        if not len(tr):
            continue
        q = np.searchsorted(tr, X[:, j], side="right") / len(tr)
        cols.append(np.where(np.isfinite(X[:, j]), q, np.nan))
    if not cols:
        return np.full(len(X), np.nan)
    with warnings.catch_warnings():                       # an all-NaN row: NaN, said once here
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(np.column_stack(cols), axis=1)


def regime_of(train_heat: np.ndarray, heat: np.ndarray) -> np.ndarray:
    """cold / normal / hot at the terciles of the training rows' own heat scores; "" where unknown."""
    s_tr = heat_score(train_heat, train_heat)
    s = heat_score(train_heat, heat)
    ok = s_tr[np.isfinite(s_tr)]
    if not len(ok):
        return np.full(len(heat), "", dtype=object)
    a, b = np.quantile(ok, [1 / 3, 2 / 3])
    out = np.where(s <= a, "cold", np.where(s <= b, "normal", "hot")).astype(object)
    out[~np.isfinite(s)] = ""
    return out


# ---------------------------------------------------------------- the walk-forward

def walk(tab: dict, days: list[str], names: list[str] | None = None, params: dict | None = None,
         log=print) -> list[dict]:
    """Each day in `days`: every member trained on the rows known before it (purged by the label's horizon), its
    predictions of the day's rows. [{"day", "y", "t", "regime", "p": {member: array}}]."""
    names = Z.members_for(tab["kind"], names)
    t, y, X = tab["t"], tab["y"], tab["X"]
    out = []
    for d in days:
        st = day_start(d)
        tr = np.flatnonzero(t + tab["h_ms"] < st)[-MAX_TRAIN:]
        te = (t >= st) & (t < st + DAY_MS)
        if len(tr) < MIN_TRAIN[tab["family"]] or te.sum() < MIN_TEST:
            continue
        ctx = {"label": tab["label"], "family": tab["family"], "features": tab["features"], "t": t[tr],
               "params": params if params is not None else (M.params_for(tab["label"])
                                                            if tab["family"] == "decision" else None)}
        if "dur" in tab:
            ctx.update(dur=tab["dur"][tr], ret=tab["ret"][tr])
        ps, t0 = {}, time.time()
        for n in names:
            m = Z.make(n).fit(X[tr], y[tr], ctx)
            ps[n] = m.stream(X[te], t[te], t[te] + tab["h_ms"], y[te], STEP_MS).astype(np.float32)
        out.append({"day": d, "y": y[te], "t": t[te], "regime": regime_of(tab["heat"][tr], tab["heat"][te]),
                    "p": ps})
        log(f"a1 zoo: {tab['label']} {d}: {len(tr):,} training rows, {int(te.sum()):,} tested, "
            f"{len(names)} members in {time.time() - t0:.0f} s")
    return out


# ---------------------------------------------------------------- the blend and the calibration

def blend_weights(P: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Non-negative weights summing to one that minimise the log loss of P @ w (columns: members' predictions)."""
    from scipy.optimize import minimize
    k = P.shape[1]
    if k == 1:
        return np.ones(1)
    Q = np.clip(P, 1e-6, 1 - 1e-6)

    def f(w):
        p = np.clip(Q @ w, 1e-6, 1 - 1e-6)
        g = (p - y) / (p * (1 - p))
        return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))), Q.T @ g / len(y)
    r = minimize(f, np.full(k, 1 / k), jac=True, method="SLSQP", bounds=[(0, 1)] * k,
                 constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1, "jac": lambda w: np.ones(k)}])
    w = np.clip(r.x if r.success else np.full(k, 1 / k), 0, None)
    return w / w.sum() if w.sum() > 0 else np.full(k, 1 / k)


def calibrator(p: np.ndarray, y: np.ndarray):
    """Isotonic on out-of-fold predictions, None with fewer than CAL_MIN rows or one class."""
    from sklearn.isotonic import IsotonicRegression
    if len(y) < CAL_MIN or y.min() == y.max():
        return None
    return IsotonicRegression(out_of_bounds="clip", y_min=CAL_BOUND, y_max=1 - CAL_BOUND).fit(p, y)


def stats(day: str, ps: dict[str, np.ndarray], y: np.ndarray) -> dict:
    """A day's log loss per candidate and the band of each pair (standard error of the per-row differences)."""
    ls = {k: Z.logloss_rows(v.astype(float), y) for k, v in ps.items()}
    se = {a: {b: float(np.std(ls[a] - ls[b], ddof=1) / math.sqrt(len(y))) if len(y) > 1 else 0.0
              for b in ls if b != a} for a in ls}
    return {"day": day, "n": int(len(y)), "rate": float(y.mean()) if len(y) else None,
            "loss": {k: float(v.mean()) for k, v in ls.items()}, "se": se}


# ---------------------------------------------------------------- the selection rules

def choose(history: list[dict], start: str = Z.INCUMBENT, n_days: int = N_DAYS, evidence: int = EVIDENCE_DAYS,
           retire: int = RETIRE_DAYS, band_z: float = BAND_Z) -> dict:
    """Replay of the rules over the days' stats in order. Returns the pick for each day (decided on the days
    before it), the pick after the last day, the retired members with their day, and the changes."""
    inc, retired, changes, picks = start, {}, [], []

    def nday(c, upto):
        xs = [(h["loss"][c], h["n"]) for h in history[max(0, upto - n_days):upto] if c in h["loss"]]
        return sum(a * b for a, b in xs) / sum(b for _, b in xs) if xs else math.inf
    for i, h in enumerate(history):
        picks.append(inc)
        seen = history[:i + 1]
        cands = sorted({c for x in seen for c in x["loss"]})
        for c in cands:                                   # retirement against the logistic baseline
            if c in retired or c == Z.BASELINE:
                continue
            last = [x for x in seen if c in x["loss"] and Z.BASELINE in x["loss"]][-retire:]
            if len(last) == retire and all(x["loss"][c] > x["loss"][Z.BASELINE] for x in last):
                retired[c] = h["day"]
        active = [c for c in cands if c not in retired]
        if inc in retired or inc not in active:
            new = min(active, key=lambda c: nday(c, i + 1)) if active else Z.BASELINE
            if new != inc:
                changes.append({"day": h["day"], "from": inc, "to": new, "why": "retired"})
            inc = new
        ahead = []
        for c in active:                                  # the evidence rule
            if c == inc:
                continue
            last = [x for x in seen if c in x["loss"] and inc in x["loss"]][-evidence:]
            if len(last) == evidence and all(x["loss"][c] < x["loss"][inc] - band_z * x["se"][c][inc] for x in last):
                ahead.append(c)
        if ahead:
            new = min(ahead, key=lambda c: nday(c, i + 1))
            changes.append({"day": h["day"], "from": inc, "to": new, "why": f"{evidence} days ahead beyond the band"})
            inc = new
    return {"picks": picks, "pick": inc, "retired": retired, "changes": changes,
            "nday": {c: nday(c, len(history)) for c in sorted({c for x in history for c in x["loss"]})}}


def selected(day: dict, prior: list[dict], pick: str, retired=()) -> tuple[np.ndarray, dict]:
    """The selector's probabilities for a tested day: the blend (weights from the prior days) or the member `pick`,
    calibrated on the prior days' out-of-sample predictions of the same candidate. Also returns what was used."""
    p_all = with_blend(day, prior, retired)
    raw = p_all.get(pick)
    if raw is None:
        raw = day["p"].get(Z.INCUMBENT, next(iter(day["p"].values())))
    pp = [with_blend(x, prior[:i], retired).get(pick) for i, x in enumerate(prior)]
    ok = [(a, x["y"]) for a, x in zip(pp, prior) if a is not None]
    cal = calibrator(np.concatenate([a for a, _ in ok]).astype(float), np.concatenate([b for _, b in ok])) \
        if ok else None
    return (cal.predict(raw.astype(float)) if cal is not None else raw.astype(float)), {"calibrated": cal is not None}


def with_blend(day: dict, prior: list[dict], retired=()) -> dict[str, np.ndarray]:
    """The day's members' predictions and the blend's (weights on the prior days, the members in all of them that
    are not retired); no blend without a prior day."""
    out = dict(day["p"])
    w = weights_of(prior, [c for c in day["p"] if c not in retired])
    if w:
        out[BLEND] = sum(day["p"][c].astype(float) * v for c, v in w.items()).astype(np.float32)
    return out


def weights_of(prior: list[dict], names: list[str]) -> dict[str, float]:
    if not prior:
        return {}
    names = [c for c in names if all(c in x["p"] for x in prior)]
    if not names:
        return {}
    P = np.vstack([np.column_stack([x["p"][c] for c in names]) for x in prior]).astype(float)
    y = np.concatenate([x["y"] for x in prior])
    if y.min() == y.max():
        return {}
    return {c: float(v) for c, v in zip(names, blend_weights(P, y))}


# ---------------------------------------------------------------- the daily run

def oof_dir(label: str) -> Path:
    return zoo_dir() / "oof" / label


def save_day(label: str, day: dict, d: Path | None = None) -> None:
    d = d or oof_dir(label)
    d.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(d / f"{day['day']}.npz", y=day["y"], t=day["t"], regime=day["regime"].astype(str),
                        **{"p_" + k: v for k, v in day["p"].items()})


def load_day(path: Path) -> dict:
    z = np.load(path, allow_pickle=False)
    return {"day": path.stem, "y": z["y"], "t": z["t"], "regime": z["regime"].astype(object),
            "p": {k[2:]: z[k] for k in z.files if k.startswith("p_")}}


def read_state(d: Path | None = None) -> dict:
    try:
        return json.loads(((d or zoo_dir()) / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def regime_table(days: list[dict], retired=()) -> dict:
    """Per regime, each candidate's pooled log loss over the days (the blend from the days before each) and the
    winner."""
    acc: dict[str, dict[str, list]] = {}
    for i, x in enumerate(days):
        ps = with_blend(x, days[max(0, i - N_DAYS):i], retired)
        for r in REGIMES:
            m = x["regime"] == r
            if not m.any():
                continue
            for c, p in ps.items():
                acc.setdefault(r, {}).setdefault(c, []).append(Z.logloss_rows(p[m].astype(float), x["y"][m]))
    out = {}
    for r, cs in acc.items():
        loss = {c: float(np.concatenate(v).mean()) for c, v in cs.items()}
        out[r] = {"n": int(sum(len(v) for v in next(iter(cs.values())))), "loss": loss,
                  "winner": min(loss, key=loss.get)}
    return out


def run(rows: dict | None, sel: dict | None, now_ms: int, d: Path | None = None, log=print) -> dict:
    """Test the days not yet tested (full UTC days before today), grow the history, replay the rules, write the
    state and the out-of-fold days; returns the summary for the report."""
    d = d or zoo_dir()
    state = read_state(d)
    hist = state.setdefault("history", {})
    today = day_of(now_ms)
    out = {"updated_ms": now_ms, "labels": {}}
    for label in LABELS:
        tab = table_for(label, rows, sel)
        if tab is None:
            out["labels"][label] = {"note": "no rows"}
            continue
        h = hist.setdefault(label, {})
        odir = d / "oof" / label
        days = sorted({day_of(x) for x in tab["t"]})
        new = [x for x in days[1:] if x < today and x not in h]
        prior = sorted(odir.glob("*.npz"))[-N_DAYS:] if odir.exists() else []
        kept = [load_day(p) for p in prior]
        for x in walk(tab, new, log=log):
            past = [k for k in kept if k["day"] < x["day"]][-N_DAYS:]
            rt = choose([h[k] for k in sorted(h)])["retired"]
            h[x["day"]] = stats(x["day"], with_blend(x, past, rt), x["y"])
            save_day(label, x, odir)
            kept.append(x)
        for p in sorted(odir.glob("*.npz"))[:-(N_DAYS + 1)] if odir.exists() else []:
            p.unlink()                                   # only the last N days' predictions are kept
        ch = choose([h[k] for k in sorted(h)])
        kept = sorted(kept, key=lambda k: k["day"])[-N_DAYS:]
        w = weights_of(kept, [c for c in Z.members_for(tab["kind"]) if c not in ch["retired"]])
        out["labels"][label] = {"days": len(h), "pick": ch["pick"], "retired": ch["retired"], "changes": ch["changes"],
                                "nday": ch["nday"], "weights": w, "regimes": regime_table(kept, ch["retired"]),
                                "members": Z.members_for(tab["kind"])}
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(state, default=str), encoding="utf-8")
    tmp.replace(d / "state.json")
    return out


def _f(x, fmt="{:.4f}") -> str:
    return fmt.format(x) if Z.finite(x) else "n/a"


def markdown(s: dict) -> str:
    md = ["# pump.fun real-time lab: A1 model zoo and selector", "",
          "Paper research only. Each member trained on the rows known before a UTC day predicts that day "
          f"(walk-forward); the pick per label by the last {N_DAYS} days' out-of-sample log loss, a challenger only "
          f"after {EVIDENCE_DAYS} days ahead of the incumbent beyond its noise band, a member worse than the logistic "
          f"baseline {RETIRE_DAYS} days in a row retired; the pick calibrated (isotonic, out of fold). The paper books "
          "keep LightGBM until A1's study shows the selector better (results/pumpfun_adaptive_a1.md).", "",
          "| label | days tested | pick | " + " | ".join(list(Z.MEMBERS) + [BLEND]) + " | retired |",
          "|---|---|---|" + "---|" * (len(Z.MEMBERS) + 2)]
    for label, v in s["labels"].items():
        if "pick" not in v:
            md.append(f"| {label} | 0 | {v.get('note', '')} |" + " |" * (len(Z.MEMBERS) + 2))
            continue
        md.append(f"| {label} | {v['days']} | {v['pick']} | "
                  + " | ".join(_f(v["nday"].get(c)) for c in list(Z.MEMBERS) + [BLEND])
                  + f" | {', '.join(f'{k} ({x})' for k, x in v['retired'].items()) or 'none'} |")
    md += ["", f"Log loss over the last {N_DAYS} tested days (lower is better). Blend weights now: "]
    for label, v in s["labels"].items():
        if v.get("weights"):
            md.append(f"- {label}: " + ", ".join(f"{k} {x:.2f}" for k, x in v["weights"].items() if x >= 0.005))
    md += ["", "Per market regime (heat: new pools and buy volume per 15 min, the share of rugs in the last hour; "
               "decision rows: new coins in 10 min), the candidate with the lowest log loss over the kept days:", "",
           "| label | " + " | ".join(REGIMES) + " |", "|---|" + "---|" * len(REGIMES)]
    for label, v in s["labels"].items():
        rg = v.get("regimes") or {}
        md.append(f"| {label} | " + " | ".join(
            f"{rg[r]['winner']} ({rg[r]['n']:,} rows)" if r in rg else "n/a" for r in REGIMES) + " |")
    ch = [(label, c) for label, v in s["labels"].items() for c in v.get("changes") or []]
    md += ["", "Changes of pick: " + ("; ".join(f"{label} {c['day']}: {c['from']} to {c['to']} ({c['why']})"
                                                for label, c in ch) if ch else "none so far.")]
    return "\n".join(md) + "\n"
