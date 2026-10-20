"""Forward shadow of two exit overlays on the crypto books, judged only on data
that did not exist when they were registered. Nothing trades on it.

    python -m lab.paper.exit_shadow             # daily, after the paper books' signals
    python -m lab.paper.exit_shadow --dry-run   # today's decisions and scores, nothing written
    python -m lab.paper.exit_shadow --freeze    # once: fit M14 and write the frozen model file

Pre-registered in results/exit_shadow_prereg.md, committed before the first
decision. Background: X16 B2 (results/exit_overlays.md) found the M14 model
exit on tsmom_tranches at 1.64 against 0.64 out of sample but failing the
deflated improvement (p 0.021), and, after the fact, a 40-day time stop ahead
of all three crypto books. Neither may be used before it passes here.

The books are the three crypto paper books as the autopilot runs them on
Alpaca, exactly as X16 B2 built them (`au.originals`, every coin Alpaca does
not list held as cash, `au.simulate`). Four pairs, each a book with and
without one overlay:

  tsmom_tranches  with the M14 exit
  breakout_top10  with a 40-day time stop
  tsmom_top20     with a 40-day time stop
  tsmom_tranches  with a 40-day time stop

An overlay cuts a coin from the close on which it fires to the end of the
book's spell in that coin (it comes back only when the book's own rule enters
it again); the freed weight stays in cash (`exit_overlays.fires`, `cut_from`).
M14 fires when the frozen model's forecast of the next 10 days' log return is
below -70 bps; the time stop on the 40th close after the entry close.

Each run, after the paper books' signals (on the panel they rebuilt), decides
the close of yesterday (UTC) and appends one record per book to
<data>/paper/exit_shadow/decisions.jsonl: the book's weights after that close
and its weights with each overlay. Only yesterday's close is ever decided, so
every record is written before the close it is first scored from: a record
for the close of day D is scored on the return of day D+2 (held from the
close of D+1, a day after the record was written), with 35 bps per unit of
turnover traded at the close of D+1, and appended to scores.jsonl once that
day has closed. Both files are append-only; nothing rewrites a line.

Each pair is judged once, on the first 90 scored days by which it has made 30
exits (or failed after 365 scored days with fewer). verdicts.jsonl keeps each
verdict once, state.json the statuses. reports/exit_shadow/latest.json carries
the lab feed header (the Research page); a change of status is one line in the
daily digest (lab.ops.notify).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import polars as pl

from .. import report
from ..data import ROOT
from ..experiments import alpaca_universe as au
from ..experiments import exit_overlays as xo
from ..experiments import fam_common as fc

NAME = "exit_shadow"
TITLE = "Exit shadow (M14 exit, 40-day stop)"
DAY_US = fc.DAY_US
REGISTERED = "2026-10-20"
REGISTERED_US = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp() * 1_000_000)

# The frozen M14 (results/exit_shadow_prereg.md): any other file is refused.
MODEL_FILE = Path(__file__).resolve().parents[1] / "models" / "frozen" / "m14_exit_shadow.txt"
MODEL_SHA256 = "105bacba2a290b19aca8482bafb46018b6f1f7ad259da47abbc00c1cf61a78c6"

# The registered rules. Written out here rather than read from exit_overlays,
# so a later change to the study cannot move them.
M14_THRESHOLD = -0.0070      # forecast of the next 10 days' log return, a 35 bps round trip each side
M14_HORIZON = 10
TIME_STOP = 40               # cut on the 40th close after the entry close
OVERLAYS = {"m14": ("model", M14_THRESHOLD), "time40": ("time", TIME_STOP)}
BOOKS = ("breakout", "tsmom_daily", "tsmom_tranches")
PAIRS = (("tsmom_tranches", "m14"), ("breakout", "time40"), ("tsmom_daily", "time40"), ("tsmom_tranches", "time40"))
OVERLAY_LABEL = {"m14": "M14 exit", "time40": "40-day time stop"}

# Scoring and the pass rule.
COST = 0.0035
MIN_DAYS = 90
MIN_EXITS = 30
MAX_DAYS = 365
BAND_PCT = 5.0 / len(PAIRS)  # one-sided 5 %, Bonferroni over the four pairs
BOOT_DRAWS, BOOT_BLOCK = 4000, 20
SEED = 20261020

LEDGER = Path(os.environ.get("PYTHIA_EXIT_SHADOW", str(ROOT / "paper" / NAME)))

Predictor = Callable[[pl.DataFrame], np.ndarray]


class ShadowError(RuntimeError):
    """The run cannot decide today: the frozen model or the panel is not as registered."""


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc):%H:%M:%S} {NAME}: {msg}", file=sys.stderr, flush=True)


def iso(day_us: int) -> str:
    return datetime.fromtimestamp(int(day_us) / 1e6, timezone.utc).strftime("%Y-%m-%d")


def pair_id(book: str, overlay: str) -> str:
    return f"{au.ORIGINAL[book]}:{overlay}"


def pair_label(book: str, overlay: str) -> str:
    return f"{au.ORIGINAL[book]} · {OVERLAY_LABEL[overlay]}"


# ---------------------------------------------------------------------------
# The frozen model
# ---------------------------------------------------------------------------

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_model(path: Path | None = None, expect: str | None = None):
    """The frozen M14 booster; any file but the registered one is refused."""
    path = path or MODEL_FILE
    expect = expect or MODEL_SHA256
    if not path.exists():
        raise ShadowError(f"no frozen M14 model at {path.name}")
    got = sha256(path)
    if got != expect:
        raise ShadowError(f"frozen M14 model {got[:12]} is not the registered {expect[:12]}")
    import lightgbm as lgb
    return lgb.Booster(model_file=str(path))


def booster_predictor(booster) -> Predictor:
    from ..models import m14_exit_hazard as m14

    def predict(rows: pl.DataFrame) -> np.ndarray:
        return booster.predict(rows.select(m14.FEATURES).fill_null(np.nan).to_numpy().astype(np.float64))
    return predict


def freeze(force: bool = False) -> dict:
    """Fit M14 once on every row of its panel with a known target (lab.models.m14_exit_hazard,
    lab.experiments.exit_overlays.m14_panel) and write the frozen file. Refuses to replace it."""
    from ..models import m14_exit_hazard as m14
    if MODEL_FILE.exists() and not force:
        raise ShadowError(f"{MODEL_FILE.name} exists; a registered model is never replaced")
    import lightgbm as lgb
    P = fc.load_panel()
    fr = xo.m14_panel(P)
    known = fr.filter(pl.col("target").is_not_null())
    fitted = m14.fit(fr)
    MODEL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fitted["model"].save_model(str(MODEL_FILE))
    meta = {"model": "M14", "file": MODEL_FILE.name, "sha256": sha256(MODEL_FILE),
            "panel_end": iso(int(P.days[-1])), "rows": known.height,
            "first_day": iso(int(known["ts_us"].min())), "last_day": iso(int(known["ts_us"].max())),
            "features": m14.FEATURES, "target_mean": fitted["mean"], "lightgbm": lgb.__version__,
            "fitted": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    MODEL_FILE.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8", newline="\n")
    return meta


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def live_books(P: fc.Panel) -> dict[str, np.ndarray]:
    """Each book's weights after every close, as X16 B2 ran them on Alpaca."""
    alp = au.alpaca_mask(P)
    O = au.originals(P)
    return {b: au.simulate(P, b, au.cash_left(O[b], alp))[3] for b in BOOKS}


def m14_pred(P: fc.Panel, sp: dict, predict: Predictor) -> np.ndarray:
    """(T, N) the frozen M14's forecast of the next 10 days' log return on the book's held cells."""
    out = np.full((P.T, P.N), np.nan)
    rows = xo.held_rows(P, sp)
    if rows.is_empty():
        return out
    t, j = rows["t"].to_numpy(), rows["j"].to_numpy()
    out[t, j] = np.asarray(predict(rows), dtype=float) * P.sigma[t, j] * math.sqrt(M14_HORIZON)
    return out


def _weights(P: fc.Panel, row: np.ndarray) -> dict[str, float]:
    return {P.names[j]: round(float(row[j]), 8) for j in np.flatnonzero(row > 1e-12)}


def _names(P: fc.Panel, mask: np.ndarray) -> list[str]:
    return [P.names[j] for j in np.flatnonzero(mask)]


def decide(P: fc.Panel, held: dict[str, np.ndarray], t: int, predict: Predictor | None) -> list[dict]:
    """One record per book for the close of day t: the book's weights after that close and
    its weights with each of its overlays (the cut coins, and those cut first on this close)."""
    out = []
    for b in BOOKS:
        if b not in held:
            continue
        h = held[b]
        sp = xo.spells(P, h)
        ovs = [ov for bb, ov in PAIRS if bb == b]
        pred = None
        if "m14" in ovs:
            if predict is None:
                raise ShadowError("the M14 overlay needs the frozen model")
            pred = m14_pred(P, sp, predict)
        base = au.sim_daily(P, h)[3]
        on = sp["on"][t]
        rec = {"book": au.ORIGINAL[b], "day": iso(int(P.days[t])), "day_us": int(P.days[t]),
               "base": _weights(P, base[t]), "overlays": {}, "coins": {}}
        for ov in ovs:
            rule, x = OVERLAYS[ov]
            cut = xo.cut_from(xo.fires(P, sp, rule, x, pred), sp)
            w = au.sim_daily(P, np.where(cut, 0.0, h))[3]
            before = cut[t - 1] & (sp["start"][t] != t) if t else np.zeros(P.N, dtype=bool)
            rec["overlays"][ov] = {"weights": _weights(P, w[t]), "cut": _names(P, cut[t] & on),
                                   "new": _names(P, cut[t] & on & ~before)}
        for j in np.flatnonzero(on):
            c: dict = {"days_held": int(t - sp["start"][t, j] + 1)}
            if pred is not None:
                c["m14"] = round(float(pred[t, j]), 6) if np.isfinite(pred[t, j]) else None
            rec["coins"][P.names[j]] = c
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# The ledgers
# ---------------------------------------------------------------------------

def read_jsonl(path: Path) -> list[dict]:
    out = []
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")


def admissible(records: list[dict], have: list[dict], now_ms: int) -> list[dict]:
    """The records that may go into the ledger: on or after the registration day, not there
    yet, and written before the close of the next day (from which they are first scored)."""
    keys = {(int(d["day_us"]), d["book"]) for d in have}
    now_us = int(now_ms) * 1000
    out = []
    for r in records:
        d = int(r["day_us"])
        if d < REGISTERED_US or (d, r["book"]) in keys or now_us >= d + 2 * DAY_US:
            continue
        out.append({**r, "written_ms": int(now_ms),
                    **({"model_sha256": MODEL_SHA256} if "m14" in r["overlays"] else {})})
    return out


def _variants(rec: dict) -> dict[str, dict[str, float]]:
    return {"base": rec["base"], **{ov: o["weights"] for ov, o in rec["overlays"].items()}}


def score_new(P: fc.Panel, decisions: list[dict], scores: list[dict], now_ms: int) -> list[dict]:
    """Score every recorded close D whose day D+2 has closed and is not scored yet: the
    weights held over day D+2, the turnover from the record of D-1 drifted over day D+1
    (not charged when that record is missing)."""
    done = {(int(s["day_us"]), s["book"]) for s in scores}
    by = {(int(d["day_us"]), d["book"]): d for d in decisions}
    row = {int(d): i for i, d in enumerate(P.days)}
    col = {n: j for j, n in enumerate(P.names)}
    now_us = int(now_ms) * 1000

    def ret(t: int, sym: str) -> float:
        j = col.get(sym)
        if j is None:
            return 0.0
        v = P.ret[t, j]
        return float(v) if np.isfinite(v) else 0.0

    out = []
    for d in sorted(decisions, key=lambda r: (int(r["day_us"]), r["book"])):
        k = (int(d["day_us"]), d["book"])
        t = row.get(k[0])
        if k in done or t is None or t + 2 >= P.T or int(P.days[t + 2]) + DAY_US > now_us:
            continue
        prev = by.get((k[0] - DAY_US, d["book"]))
        pv = _variants(prev) if prev is not None else {}
        gross, tov, net = {}, {}, {}
        for v, w in _variants(d).items():
            g = sum(x * ret(t + 2, s) for s, x in w.items())
            tv = None
            if v in pv:
                g1 = sum(x * ret(t + 1, s) for s, x in pv[v].items())
                drift = ({s: x * (1 + ret(t + 1, s)) / (1 + g1) for s, x in pv[v].items()} if 1 + g1 > 0 else {})
                tv = sum(abs(w.get(s, 0.0) - drift.get(s, 0.0)) for s in set(w) | set(drift))
            gross[v], tov[v] = round(g, 10), (None if tv is None else round(tv, 10))
            net[v] = round(g - COST * (tv or 0.0), 10)
        out.append({"day": d["day"], "day_us": k[0], "book": d["book"], "return_day": iso(int(P.days[t + 2])),
                    "scored_ms": int(now_ms), "gross": gross, "turnover": tov, "net": net,
                    "turnover_charged": prev is not None})
    return out


# ---------------------------------------------------------------------------
# Measuring and the verdict
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    sd = float(np.std(x)) if len(x) > 1 else 0.0
    return float(np.mean(x) / sd * math.sqrt(365)) if sd > 0 else 0.0


def max_dd(x: np.ndarray) -> float:
    if len(x) == 0:
        return 0.0
    eq = np.cumprod(1 + np.asarray(x, dtype=float))
    return float((1 - eq / np.maximum.accumulate(np.r_[1.0, eq])[1:]).max())


def diff_band(x: np.ndarray, y: np.ndarray, pct: float = BAND_PCT, seed: int = SEED) -> tuple[float, float]:
    """The pct and 100 - pct percentiles of Sharpe(x) - Sharpe(y), annual, over stationary
    bootstrap resamples of the same days (mean block 20, 4000 draws, a fixed seed)."""
    n = len(x)
    rng = np.random.default_rng(seed)
    idx = np.empty((BOOT_DRAWS, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, BOOT_DRAWS)
    jump = rng.random((BOOT_DRAWS, n)) < 1 / BOOT_BLOCK
    fresh = rng.integers(0, n, (BOOT_DRAWS, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(365), 0.0)

    v = sr(np.asarray(x, dtype=float)) - sr(np.asarray(y, dtype=float))
    return float(np.percentile(v, pct)), float(np.percentile(v, 100 - pct))


def pair_series(pair: tuple[str, str], decisions: list[dict], scores: list[dict]):
    """Scored days of one pair in order: (days, overlay net, book net, exits per day)."""
    book, ov = au.ORIGINAL[pair[0]], pair[1]
    exits = {int(d["day_us"]): len(d["overlays"][ov]["new"]) for d in decisions
             if d["book"] == book and ov in d.get("overlays", {})}
    sc = sorted((s for s in scores if s["book"] == book and ov in s["net"]), key=lambda s: int(s["day_us"]))
    days = [s["return_day"] for s in sc]
    x = np.array([s["net"][ov] for s in sc], dtype=float)
    y = np.array([s["net"]["base"] for s in sc], dtype=float)
    e = np.array([exits.get(int(s["day_us"]), 0) for s in sc], dtype=int)
    return days, x, y, e


def judge(x: np.ndarray, y: np.ndarray, exits: np.ndarray) -> dict | None:
    """The registered rule, once: on the first n >= 90 scored days by which the overlay has
    made 30 exits; a fail when 365 scored days pass with fewer; None while collecting."""
    ce = np.cumsum(exits)
    n = next((k for k in range(MIN_DAYS, min(len(x), MAX_DAYS) + 1) if ce[k - 1] >= MIN_EXITS), None)
    if n is None:
        if len(x) >= MAX_DAYS:
            return {"passed": False, "days": MAX_DAYS, "exits": int(ce[MAX_DAYS - 1]),
                    "why": f"fewer than {MIN_EXITS} exits in {MAX_DAYS} scored days", "gates": {}}
        return None
    xs, ys = x[:n], y[:n]
    sx, sy = sharpe(xs), sharpe(ys)
    lo, hi = diff_band(xs, ys)
    dx, dy = max_dd(xs), max_dd(ys)
    gates = {"Sharpe above the book's": sx > sy, "bootstrap band of the difference above 0": lo > 0,
             "drawdown not worse": dx <= dy}
    failed = [k for k, v in gates.items() if not v]
    return {"passed": not failed, "days": int(n), "exits": int(ce[n - 1]), "sharpe": sx, "sharpe_book": sy,
            "band": [lo, hi], "dd": dx, "dd_book": dy, "gates": gates,
            "why": "all three gates hold" if not failed else "failed: " + ", ".join(failed)}


def summarise(pair: tuple[str, str], decisions: list[dict], scores: list[dict], prior: dict | None) -> dict:
    days, x, y, e = pair_series(pair, decisions, scores)
    out = {"pair": pair_id(*pair), "label": pair_label(*pair), "book": au.ORIGINAL[pair[0]], "overlay": pair[1],
           "scored_days": len(x), "exits": int(e.sum()), "first_day": days[0] if days else None,
           "last_day": days[-1] if days else None, "sharpe": sharpe(x), "sharpe_book": sharpe(y),
           "return": float(np.prod(1 + x) - 1) if len(x) else 0.0,
           "return_book": float(np.prod(1 + y) - 1) if len(y) else 0.0,
           "dd": max_dd(x), "dd_book": max_dd(y),
           "exposure_days": sum(1 for d in decisions if d["book"] == au.ORIGINAL[pair[0]]
                                and d["overlays"].get(pair[1], {}).get("cut"))}
    verdict = (prior or {}).get("verdict")
    if verdict is None:
        verdict = judge(x, y, e)
    out["verdict"] = verdict
    out["status"] = ("waiting" if not len(x) else "collecting") if verdict is None else (
        "passed" if verdict["passed"] else "failed")
    return out


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

STATUS_FEED = {"waiting": "ok", "collecting": "ok", "passed": "watch", "failed": "bad"}


def feed(pairs: list[dict], now_ms: int, error: str | None = None) -> dict:
    items = []
    for p in pairs:
        v = p.get("verdict")
        if v:
            value = "passed" if v["passed"] else "failed"
            detail = (f"judged on {v['days']} scored days, {v['exits']} exits: {v['why']}. "
                      + ("A write-up and your decision come first; nothing trades on it." if v["passed"] else
                         "It stays a record."))
        elif p["scored_days"]:
            value = f"day {p['scored_days']} of {MIN_DAYS} · {p['exits']} of {MIN_EXITS} exits"
            detail = (f"so far (not a verdict): Sharpe {p['sharpe']:.2f} with the overlay, {p['sharpe_book']:.2f} "
                      f"without; drawdown {p['dd'] * 100:.1f} % against {p['dd_book'] * 100:.1f} %")
        else:
            value = "waiting"
            detail = "decisions are recorded; the first is scored two closes after it was written"
        items.append({"label": p["label"], "value": value, "status": STATUS_FEED[p["status"]], "detail": detail,
                      "link": "study:exit_shadow_prereg", "importance": 70 if p["status"] == "passed" else 30})
    if error:
        status, head = "bad", f"Exit shadow could not record today: {error}."
    elif any(p["status"] == "passed" for p in pairs):
        status = "watch"
        head = ("An exit rule passed its pre-registered forward test: "
                + ", ".join(p["label"] for p in pairs if p["status"] == "passed")
                + ". Nothing trades on it until it is written up and you decide.")
    else:
        done = sum(1 for p in pairs if p["status"] == "failed")
        n = max((p["scored_days"] for p in pairs), default=0)
        head = (f"Two exit rules from X16 recorded before the outcome on the crypto books, day {n} of at least "
                f"{MIN_DAYS}; nothing trades on them." + (f" {done} of {len(pairs)} failed." if done else ""))
        status = "ok"
    return report.feed_header(TITLE, status, head, items, updated_ms=now_ms)


def markdown(data: dict) -> str:
    out = [f"# {TITLE}\n\n{data['headline']}\n\n",
           "Pre-registered in `results/exit_shadow_prereg.md`. Scored on the return two closes after each "
           "decision was written, 35 bps per unit of turnover.\n\n",
           "| pair | status | scored days | exits | Sharpe | book | return | book | drawdown | book |\n",
           "|---|---|---|---|---|---|---|---|---|---|\n"]
    for p in data["pairs"]:
        out.append(f"| {p['label']} | {p['status']} | {p['scored_days']} | {p['exits']} | {p['sharpe']:.2f} | "
                   f"{p['sharpe_book']:.2f} | {p['return'] * 100:.2f} % | {p['return_book'] * 100:.2f} % | "
                   f"{p['dd'] * 100:.1f} % | {p['dd_book'] * 100:.1f} % |\n")
    for p in data["pairs"]:
        if p.get("verdict"):
            out.append(f"\n**{p['label']}**: {'passed' if p['verdict']['passed'] else 'failed'} "
                       f"({p['verdict']['why']}).\n")
    if data.get("changes"):
        out.append("\nChanged today: " + "; ".join(f"{c['label']} {c['from']} to {c['to']}" for c in data["changes"])
                   + ".\n")
    return "".join(out)


def run(now_ms: int | None = None, dry: bool = False, P: fc.Panel | None = None,
        held: dict[str, np.ndarray] | None = None, predict: Predictor | None = None,
        ledger: Path | None = None) -> dict:
    now = int(now_ms if now_ms is not None else time.time() * 1000)
    ledger = ledger or LEDGER
    state_path = ledger / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    prior = state.get("pairs") or {}
    decisions = read_jsonl(ledger / "decisions.jsonl")
    scores = read_jsonl(ledger / "scores.jsonl")
    error = None
    new_dec: list[dict] = []
    new_sc: list[dict] = []
    try:
        P = P if P is not None else fc.load_panel()
        yesterday = (now * 1000 // DAY_US - 1) * DAY_US
        rows = np.flatnonzero(P.days == yesterday)
        if not len(rows):
            raise ShadowError(f"the panel ends {iso(int(P.days[-1]))}, yesterday ({iso(yesterday)}) is missing")
        t = int(rows[0])
        if predict is None:
            predict = booster_predictor(load_model())
        held = held if held is not None else live_books(P)
        new_dec = admissible(decide(P, held, t, predict), decisions, now)
        decisions = decisions + new_dec
        new_sc = score_new(P, decisions, scores, now)
        scores = scores + new_sc
    except ShadowError as e:
        error = str(e)
        log(error)
    pairs = [summarise(p, decisions, scores, prior.get(pair_id(*p))) for p in PAIRS]
    changes = [{"pair": p["pair"], "label": p["label"], "book": p["book"], "overlay": p["overlay"],
                "from": (prior.get(p["pair"]) or {}).get("status", "waiting"), "to": p["status"]}
               for p in pairs if p["status"] != (prior.get(p["pair"]) or {}).get("status", "waiting")]
    data = {**feed(pairs, now, error), "date": datetime.fromtimestamp(now / 1000, timezone.utc).strftime("%Y-%m-%d"),
            "registered": REGISTERED, "model_sha256": MODEL_SHA256, "recorded": len(new_dec), "scored": len(new_sc),
            "decisions": len(decisions), "pairs": pairs, "changes": changes, "error": error,
            "rule": {"min_days": MIN_DAYS, "min_exits": MIN_EXITS, "max_days": MAX_DAYS, "band_pct": BAND_PCT,
                     "cost": COST, "m14_threshold": M14_THRESHOLD, "time_stop": TIME_STOP}}
    if dry:
        data["today"] = new_dec
        return data
    append_jsonl(ledger / "decisions.jsonl", new_dec)
    append_jsonl(ledger / "scores.jsonl", new_sc)
    append_jsonl(ledger / "verdicts.jsonl", [{"pair": p["pair"], "at_ms": now, **p["verdict"]} for p in pairs
                                              if p["verdict"] and not (prior.get(p["pair"]) or {}).get("verdict")])
    ledger.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"updated_ms": now, "pairs": {p["pair"]: {
        "status": p["status"], "verdict": p["verdict"]} for p in pairs}}, indent=1), encoding="utf-8", newline="\n")
    report.write(NAME, markdown(data), data)
    return data


def main() -> int:
    if "--freeze" in sys.argv:
        print(json.dumps(freeze(force="--force" in sys.argv), indent=1))
        return 0
    dry = "--dry-run" in sys.argv
    data = run(dry=dry)
    if dry:
        print(json.dumps(data, indent=1, default=str))
    else:
        log(f"recorded {data['recorded']}, scored {data['scored']}; "
            + "; ".join(f"{p['pair']} {p['status']}" for p in data["pairs"]))
    return 1 if data["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
