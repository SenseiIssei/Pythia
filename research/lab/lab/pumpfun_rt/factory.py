"""F3: the pump.fun factory, a nightly search for strategies and model settings on realistic money. PAPER ONLY.

    python -m lab.pumpfun_rt.factory                  the nightly job: PYTHIA_PF_FACTORY_TRIALS strategy trials (300),
                                                      the model settings, the paper books, reports/pumpfun_rt/factory.*
    python -m lab.pumpfun_rt.factory --trials 30      a short search

No language model anywhere: Optuna's TPE sampler proposes, the record decides.

Strategies (search): a typed space over the pipeline's building blocks (space): the entry (at the migration with a
delay of 0 to 60 s and Y8's wait for the pool's first trade, or a fresh pool by its age, Y10's list), the filters
(R2's select models' P(win) in its top 30 % or at least k x its base rate and P(rug) at most k x its base rate, with or
without the Y10 trend features; Y10's market heat; the pool's SOL; distinct buyers; Y16's R3 rug rule; the owner's block
list without its mint lines, which were written after the fact), the exits (take profit, stop, time stop, Y12's lock,
a partial sale at the take profit with the rest at a higher one) and the sizing as R2 (5 to 25 % of the wallet, 1 to 3
open, the brake on or off). The models a filter reads at a delay under 3 s are the entry-0 ones, else the entry-5 ones.

Every trial is a realistic book (realistic.RealExecutor: the live bot's measured latency drawn per trade with the key
"F3" for every trial, so trials differ by their rules and not their draws, fills at landing, failures, fees) at 0.1 SOL
without a slot limit (smallwallet.Rec) in one replay of the record per batch of trials; the select models and
et_alive5m are trained at the end of each UTC day for the next (trends10.day_models), once a night, and every batch
reads them (walk-forward: a day is traded with models of the days before it). Scored days: the search's full days on
which every select model exists. The wallet: smallwallet.simulate with the trial's sizing on a START_SOL wallet, PATHS
paths of HORIZON days drawn from the scored days. Objective: the median end wallet less RUIN_PENALTY x START_SOL x the
chance of losing 80 % (the wallet at or under 20 % of its start).

The bar: every trial ever run is a line in <data>/pumpfun_rt/factory/ledger.jsonl, which only grows. A trial's Sharpe
per entry (P&L of each entry at 0.1 SOL, failed buys included) is deflated (metrics.deflated_sharpe) by the number of
trials in the ledger and the variance of the Sharpes of those with MIN_ENTRIES (one with no entries has a Sharpe of 0,
one with a handful a wild one: neither is a strategy's noise). The entries of one day share its market, so a trial is
scored per day: its mean per entry gets a standard error clustered by UTC day, and the deflation counts the effective
entries that error implies, not the entries. It passes at BAR_P with MIN_ENTRIES, at least MIN_DAYS scored days and a
median above the start. The last HOLD_DAYS full recorded days are never in the search, and neither are the days the
night before held back (replayed for the walk-forward, not scored); the TOP_HOLD best of a night are scored on them
once (a line "holdback" in the ledger). A winner passed the bar and made money on the held-back days too. Reports give
the mean per entry with its band and the mean without the best and worst TRIM, not only the bootstrap's medians (30
days drawn from a dozen days are no forecast).

Paper books (books): a winner becomes the realistic paper book F3_<id> in the collector (live.Shadow,
realistic.factory_books) on its own START_SOL paper wallet with its sizing fixed; at most MAX_BOOKS at a time. Each
night its P&L is set against what REF_BOOK made since the same start: after PROBATION_DAYS without beating it the
weakest book is retired (one a night, more only to make room for a winner); a book that beat it on each of the last
PROBATION_DAYS nights is written as a proposal for the owner (proposals/F3_<id>.md). Never live: nothing here holds
a wallet, reads a key, signs or sends.

Model settings (tune_models): an Optuna search over the LightGBM settings of R2's realistic labels (labels_r2.REAL_ROW)
on the decision rows before the held-back days, scored by the mean log loss of model.evaluate's purged walk-forward
folds; the night's best is adopted (params.json, which model.params_for hands the daily retrain) only when its log
loss is lower than the current setting's in at least ADOPT_FOLDS of the FOLDS folds and on the held-back days.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import curve as C
from . import pipeline as P
from . import realistic as R
from . import smallwallet as SW

TRIALS = 300                               # per night, PYTHIA_PF_FACTORY_TRIALS
BUDGET_S = 8_400                           # the night's run stops asking for trials after this (the job's limit 2.5 h)
MODEL_TRIALS = 12                          # per label and night, PYTHIA_PF_FACTORY_MODEL_TRIALS
MODEL_BUDGET_S = 1_500
BATCH = 75                                 # trials per replay (300 a night: four replays of the search days)
WINDOW_DAYS = 15                           # the full days replayed: the search's and the held-back ones (MIN_DAYS
                                           # scored: less the first two without every model and three held back)
HOLD_DAYS = 2
TOP_HOLD = 3
START_SOL = R.START_SOL                    # 0.55 SOL, about 50 EUR
PATHS = 1_000
HORIZON = 30
SEED = 20261026
LOST = SW.LOST                             # the wallet at 20 % of its start: lost 80 %
RUIN_PENALTY = 1.0
BAR_P = 0.95
MIN_ENTRIES = 20
MIN_DAYS = 10                              # scored days before a winner
TRIM = 0.02                                # the trimmed mean leaves out this share at each end (one at least)
STAKE_SOL = SW.STAKE_SOL
TAIL_MS = 35 * 60_000                      # no entry this close to the replay's end: the 1800 s time stops close
KEY = "F3"                                 # every trial's latency draws
MAX_BOOKS = 5
PROBATION_DAYS = 14
REF_BOOK = "P_pool5_top30t_sw10o3n"
PREFIX = "F3_"
ADOPT_FOLDS = 4
DAY_MS = 86_400_000
# Y16's R3 rule and the select labels the filters read
R3 = dict(P.RUG_CUT or {})
SELECT = ("win0", "rug0", "win5", "rug5", "win0t", "rug0t", "win5t", "rug5t")
# the R2 reference as a first trial each night (P_pool5_top30t at 10 %, 3 open, brake off)
REFERENCE = {"entry": "migration", "delay_s": 5, "wait_pool_s": 0, "win": "top", "trend_models": True, "rug": "none",
             "heat": False, "liq": False, "buyers": False, "r3": False, "block": False, "tp": 0.30, "sl": 0.20,
             "time_s": 300, "lock": False, "partial": False, "share": 0.10, "max_open": 3, "brake": False}
LGB_KEEP = dict(verbose=-1, n_jobs=2, subsample_freq=1)


def factory_dir() -> Path:
    from .store import base
    return base() / "factory"


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, default)))
    except ValueError:
        return default


def day_of(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the space and the strategy

def space(trial) -> dict:
    """One trial's parameters (Optuna's define-by-run: a branch's parameters exist only where it is taken)."""
    s = trial.suggest_categorical
    f, i = trial.suggest_float, trial.suggest_int
    p = {"entry": s("entry", ["migration", "fresh"])}
    if p["entry"] == "migration":
        p["delay_s"] = i("delay_s", 0, 60)
        p["wait_pool_s"] = s("wait_pool_s", [0, 5])
    else:
        p["top"] = i("top", 1, 5)
        p["from_s"] = i("from_s", 60, 600, step=30)
        p["span_s"] = i("span_s", 60, 1200, step=60)
    p["win"] = s("win", ["none", "top", "min"])
    if p["win"] == "min":
        p["win_k"] = f("win_k", 0.8, 2.5)
    p["rug"] = s("rug", ["none", "max"])
    if p["rug"] == "max":
        p["rug_k"] = f("rug_k", 0.3, 1.5)
    if p["win"] != "none" or p["rug"] != "none":
        p["trend_models"] = s("trend_models", [True, False])
    p["heat"] = s("heat", [False, True])
    if p["heat"]:
        p["heat_k"] = f("heat_k", 0.5, 2.0)
    p["liq"] = s("liq", [False, True])
    if p["liq"]:
        p["liq_sol"] = f("liq_sol", 30.0, 150.0)
    p["buyers"] = s("buyers", [False, True])
    if p["buyers"]:
        p["buyers_min"] = i("buyers_min", 5, 100, log=True)
    p["r3"] = s("r3", [False, True])
    p["block"] = s("block", [False, True])
    p["tp"] = f("tp", 0.10, 1.50, log=True)
    p["sl"] = f("sl", 0.05, 0.50)
    p["time_s"] = i("time_s", 30, 1800, log=True)
    p["lock"] = s("lock", [False, True])
    if p["lock"]:
        p["lock_arm"] = f("lock_arm", 0.05, 0.25)
    p["partial"] = s("partial", [False, True])
    if p["partial"]:
        p["part_share"] = f("part_share", 0.3, 0.7)
        p["part_mult"] = f("part_mult", 2.0, 5.0)
    p["share"] = f("share", 0.05, 0.25)
    p["max_open"] = i("max_open", 1, 3)
    p["brake"] = s("brake", [False, True])
    return p


def _at(p: dict) -> str:
    """The select models' entry: 0 at a delay under 3 s, else 5 (the pool's first seconds known)."""
    return "0" if p.get("entry") == "migration" and int(p.get("delay_s") or 0) < 3 else "5"


def strategy_of(p: dict, name: str, stake_sol: float = STAKE_SOL) -> P.Strategy:
    """A trial's parameters as a pipeline strategy (family E: a PumpSwap pool), its latency key KEY."""
    tag = "t" if p.get("trend_models") else ""
    if p["entry"] == "migration":
        entry, ep = "migration", {"delay_s": int(p["delay_s"])}
        if p.get("wait_pool_s"):
            ep["wait_pool_s"] = int(p["wait_pool_s"])
        what = [f"PumpSwap, migration + {int(p['delay_s'])} s" + (", waiting up to 5 s for the pool's first trade"
                                                                  if p.get("wait_pool_s") else "")]
    else:
        entry = "trend"
        ep = {"list": "fresh", "top": int(p["top"]), "from_s": int(p["from_s"]),
              "to_s": int(p["from_s"]) + int(p["span_s"])}
        what = [f"a pool in the top {ep['top']} of the fresh pools, {ep['from_s']} to {ep['to_s']} s after its "
                "migration"]
    ep["base"] = KEY
    flt, sel, cut = {}, {}, {}
    if p.get("win") == "top":
        sel[f"win{_at(p)}{tag}"] = ("top", 0.3)
        what.append(f"P(win{_at(p)}{tag}) in its top 30 %")
    elif p.get("win") == "min":
        sel[f"win{_at(p)}{tag}"] = ("min", round(float(p["win_k"]), 3))
        what.append(f"P(win{_at(p)}{tag}) at least {float(p['win_k']):.2f}x its base rate")
    if p.get("rug") == "max":
        sel[f"rug{_at(p)}{tag}"] = ("max", round(float(p["rug_k"]), 3))
        what.append(f"P(rug{_at(p)}{tag}) at most {float(p['rug_k']):.2f}x its base rate")
    if sel:
        flt["select"] = sel
    if p.get("heat"):
        flt["trend"] = {"heat": round(float(p["heat_k"]), 3)}
        what.append(f"market heat at least {float(p['heat_k']):.2f}x its 6 h median")
    if p.get("liq"):
        cut["pool_sol"] = ("min", round(float(p["liq_sol"]), 1))
        what.append(f"pool SOL at least {float(p['liq_sol']):.0f}")
    if p.get("buyers"):
        cut["unique_buyers"] = ("min", int(p["buyers_min"]))
        what.append(f"{int(p['buyers_min'])}+ distinct buyers")
    if p.get("r3") and R3:
        cut.update(R3)
        what.append("Y16 R3 rug rule")
    if cut:
        flt["cut"] = cut
    if p.get("block"):
        flt["block"] = True                                   # read by the book (blocked), not by Pipeline.signal
        what.append("the block list")
    tp, sl = float(p["tp"]), float(p["sl"])
    if p.get("partial"):
        ladder = ((round(tp, 4), round(float(p["part_share"]), 3)),
                  (round(tp * float(p["part_mult"]), 4), 1.0))
        what.append(f"{float(p['part_share']) * 100:.0f} % at +{tp * 100:.0f} %, the rest at "
                    f"+{tp * float(p['part_mult']) * 100:.0f} %")
    else:
        ladder = ((round(tp, 4), 1.0),)
        what.append(f"+{tp * 100:.0f} %")
    lock = None
    if p.get("lock"):
        a = float(p["lock_arm"])
        lock = ((round(a, 4), round(a * 0.2, 4), 1.0), (round(2 * a, 4), round(a, 4), 1.0))
        what.append(f"lock: once +{a * 100:.0f} % out at +{a * 20:.0f} %, once +{a * 200:.0f} % out at "
                    f"+{a * 100:.0f} %")
    what.append(f"stop -{sl * 100:.0f} %, {int(p['time_s'])} s")
    ex = P.Exits(int(p["time_s"]), round(sl, 4), ladder, dev_sell=False, pull=False, lock=lock)
    return P._strategy(name, "E", entry, ep, flt, ex, "; ".join(what), stake_sol=stake_sol)


def book_label(p: dict) -> str:
    return (f"{p['share'] * 100:.0f} % of the wallet, at most {int(p['max_open'])} open, brake "
            f"{'on' if p.get('brake') else 'off'}")


class Unminted:
    """The owner's block list without its mint lines (a coin goes on the list after it rugged: hindsight in a
    replay); for the strategies whose filter names it."""

    def __init__(self, names=None, paths=None):
        from .blocklist import BlockWatch
        self.names = names
        self.watch = BlockWatch(paths=paths, rules=None)

    def __call__(self, rule: str, tok) -> str | None:
        if self.names is not None and rule not in self.names:
            return None
        try:
            self.watch.refresh()
        except Exception as e:                                # noqa: BLE001 - the last list stays
            print(f"f3: block list not re-read ({type(e).__name__}: {e})", flush=True)
        devs = getattr(tok, "devs", None) or ()
        creators = (getattr(tok, "creator", None), *sorted(x for x in devs if x))
        return self.watch.list.why("", creators, getattr(tok, "symbol", "") or "", getattr(tok, "name", "") or "")


# ---------------------------------------------------------------- the replay

class Days:
    """The night's days: the replayed window (the last WINDOW_DAYS full UTC days before now), the warm-up before it,
    the held-back days at its end, the replay's days before them and the search's: the replay's without the days
    `held` back on the night before (held_before)."""

    def __init__(self, now_ms: int, root=None, window: int = WINDOW_DAYS, hold: int = HOLD_DAYS, held=()):
        from . import store
        from .study import WARM_DAYS
        today = day_of(now_ms)
        full = [d for d in store.days(root) if d < today]
        self.days = full[-window:]
        self.warm = [d for d in full if self.days and d < self.days[0]][-WARM_DAYS:]
        self.hold = self.days[-hold:] if len(self.days) > hold else []
        self.replay = self.days[:len(self.days) - len(self.hold)]
        self.held = [x for x in self.replay if x in set(held)]
        self.search = [x for x in self.replay if x not in self.held]


def held_before(ledger: list[dict], night: str) -> list[str]:
    """The days the last night before `night` with held-back lines scored them on."""
    hb = [r for r in ledger if r.get("kind") == "holdback" and str(r.get("night") or "") < night]
    last = max((str(r.get("night")) for r in hb), default=None)
    return sorted({x for r in hb if r.get("night") == last for x in r.get("days") or ()})


class Replayer:
    """One replay of the record per batch of trials; the day models trained once (the first replay with a label book)
    and kept for every later one, the held-back days' models trained by the hold-out replay."""

    def __init__(self, days: Days, model: R.Model, root=None, log=print):
        self.d, self.model, self.root, self.log = days, model, root, log
        self.by_day: dict[str, dict] = {}
        self.trained: dict[str, list] = {}
        self.block = None

    def run(self, specs: list[tuple[str, dict]], days: list[str]) -> dict[str, list[dict]]:
        """{name: entries (smallwallet.entries)} of each (name, params) over `days` (from the window's first)."""
        from . import early as EA
        from . import labels_r2 as L2
        from . import select9 as S9
        from . import selmodel as SM
        from . import sim
        from . import trends10 as T10
        from . import wallets as W
        from .study import span_of, warm_book
        root, d = self.root, self.d
        t_lo, t_hi = span_of(days, root)
        t_hi = min(t_hi, SW.day_start(days[-1]) + DAY_MS)
        nxt = lambda day: (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        train = any(x not in self.by_day for x in days[1:])
        t0 = time.time()
        eng = sim.Engine([], book=warm_book(d.warm, root), decisions=False, entry_until=t_hi - TAIL_MS,
                         wallets=W.warm(d.warm, root), snipers=EA.warm_snipers(d.warm, root), select=True,
                         trend=True, early_rows=train)
        dm = S9.DayModels()
        dm.eng = eng
        dm.by_day = self.by_day
        eng.models = dm
        lab = None
        if train:
            eng.early.keep_frac = 0.0                         # rows only: et_alive5m
            lab = eng.add_pipe(L2.RealLabelPipe(eng, self.model))
        pipes = {}
        for name, p in specs:
            s = strategy_of(p, name)
            eng.rule_costs[name] = R.RealCosts(model=self.model)
            pipes[name] = eng.add_pipe(SW.Rec(eng, [s], R.RealExecutor(self.model), name=name))
            pipes[name].risk[name].limits = SW.LIMITS          # a measuring book: every signal its outcome
            if p.get("block"):
                if self.block is None:
                    self.block = Unminted()
                pipes[name].blocked = self.block

        def next_day(day: str, n: int) -> None:
            nd = nxt(day)
            if lab is not None and nd in days and nd not in self.by_day:
                self.by_day[nd] = T10.day_models(lab.table(), T10.early_snapshot(eng.early), SM.day_start(nd))
                self.trained[nd] = T10.usable(self.by_day[nd])
            self.log(f"f3: {day} done ({n:,} events, {time.time() - t0:.0f} s)")
        sim.replay(days, eng, root, progress=next_day, until_ms=t_hi)
        self.log(f"f3: replay of {len(specs)} trial(s) over {len(days)} day(s) in {time.time() - t0:.0f} s")
        return {n: SW.entries(p) for n, p in pipes.items()}

    def scored(self) -> list[str]:
        """The search's days on which every select model exists (trained on the days before)."""
        need = {x for x in SELECT}
        return [x for x in self.d.search if need <= set(self.trained.get(x) or ())]


# ---------------------------------------------------------------- scoring

def draws(n_days: int, paths: int = PATHS, horizon: int = HORIZON, seed: int = SEED) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, max(1, n_days), size=(paths, horizon))


def by_day(pnl: np.ndarray, day: np.ndarray, n_days: int) -> dict:
    """The mean per entry of `pnl` (a fraction of the stake) by day: its standard error clustered by `day` (the
    sandwich with G/(G-1), G the days with entries), the 95 % band (t with G-1 degrees of freedom), the effective
    entries that error implies (at most the entries; 0 under two days), the mean without the TRIM best and worst
    entries, and the P&L per day."""
    from scipy import stats
    n = len(pnl)
    m = float(pnl.mean()) if n else 0.0
    per = np.bincount(day, weights=pnl, minlength=n_days) if n else np.zeros(n_days)
    g = int(len(np.unique(day))) if n else 0
    se, n_eff, lo, hi = 0.0, 0.0, m, m
    if g >= 2 and n >= 2:
        res = np.bincount(day, weights=pnl - m, minlength=n_days)
        se = float(math.sqrt(g / (g - 1) * float((res ** 2).sum())) / n)
        sd = float(pnl.std(ddof=1))
        n_eff = float(n) if se <= 0 else float(min(n, (sd / se) ** 2))
        w = float(stats.t.ppf(0.975, g - 1)) * se
        lo, hi = m - w, m + w
    k = max(1, int(TRIM * n))
    xs = np.sort(pnl)
    trimmed = float(xs[k:n - k].mean()) if n > 2 * k else m
    return {"days_traded": g, "se_day": se, "n_eff": n_eff, "lo": lo, "hi": hi, "trimmed": trimmed,
            "day_pnl": [float(x) for x in per]}


def score(es: list[dict], p: dict, days: list[str], dr: np.ndarray | None = None) -> dict:
    """A trial on `days`: the wallet bootstrap with its sizing (median, 10 and 90 %, the chances to lose 80 %, to be
    ruined, to double), the objective, the entries' Sharpe at 0.1 SOL and their mean per day (by_day)."""
    starts = [SW.day_start(d) for d in days]
    es = [e for e in es if any(t <= e["signal_ms"] < t + DAY_MS for t in starts)]
    pnl = np.array([e["pnl"] / STAKE_SOL for e in es], dtype=float)
    day = np.array([next(i for i, t in enumerate(starts) if t <= e["signal_ms"] < t + DAY_MS) for e in es], dtype=int)
    sd = float(pnl.std(ddof=1)) if len(pnl) > 1 else 0.0
    out = {"days": list(days), "entries": len(es), "trades": sum(1 for e in es if not e["failed"]),
           "mean": float(pnl.mean()) if len(pnl) else 0.0, "sharpe": float(pnl.mean() / sd) if sd > 0 else 0.0,
           "pnl_sol": float(sum(e["pnl"] for e in es)),
           "skew": float(((pnl - pnl.mean()) ** 3).mean() / sd ** 3) if sd > 0 else 0.0,
           "kurt": float(((pnl - pnl.mean()) ** 4).mean() / sd ** 4) if sd > 0 else 3.0}
    out |= by_day(pnl, day, len(days))
    if not days:
        return out | {"median": START_SOL, "p10": START_SOL, "p90": START_SOL, "p_lost80": 0.0, "p_ruin": 0.0,
                      "p_double": 0.0, "score": START_SOL}
    dr = draws(len(days)) if dr is None else dr
    dl = [SW.day_arrays(es, d) for d in days]
    sim = SW.simulate(dl, dr, int(p["max_open"]), [float(p["share"])], [bool(p["brake"])], [START_SOL])
    o = SW.outcome(sim, 0, START_SOL, 2 * START_SOL)
    out.update({k: o[k] for k in ("median", "p10", "p90", "p_lost80", "p_ruin", "p_double")})
    out["score"] = o["median"] - RUIN_PENALTY * START_SOL * o["p_lost80"]
    return out


def pool(ledger: list[dict]) -> tuple[list[float], int]:
    """The bar's trials: the Sharpes its variance comes from (the trials with MIN_ENTRIES) and how many count (all)."""
    tr = trials_of(ledger)
    return [float(r.get("sharpe", 0.0)) for r in tr if r.get("entries", 0) >= MIN_ENTRIES], len(tr)


def bar(sharpes: list[float], n: int | None = None) -> float:
    """The Sharpe per entry the best of n trials of no skill reaches (metrics.deflated_sharpe's SR0), the noise's
    variance from `sharpes` (n: len(sharpes))."""
    from scipy import stats
    xs = [x for x in sharpes if math.isfinite(x)]
    n = len(xs) if n is None else n
    if n <= 1 or len(xs) < 2:
        return 0.0
    g = 0.5772156649
    return float(math.sqrt(float(np.var(xs, ddof=1))) * ((1 - g) * stats.norm.ppf(1 - 1 / n)
                                                          + g * stats.norm.ppf(1 - 1 / (n * math.e))))


def deflated(r: dict, sharpes: list[float], n: int | None = None) -> float:
    """The trial's deflated Sharpe probability against n trials (pool), on its effective entries by day."""
    from ..metrics import deflated_sharpe
    xs = [x for x in sharpes if math.isfinite(x)]
    n = len(xs) if n is None else n
    n_obs = float(r.get("n_eff", r.get("entries", 0)))
    if r.get("entries", 0) < 2 or n_obs < 2 or n < 1:
        return 0.0
    var = float(np.var(xs, ddof=1)) if len(xs) > 1 else 0.0
    try:
        return deflated_sharpe(r["sharpe"], n_obs, n, var, r.get("skew", 0.0), r.get("kurt", 3.0))
    except ValueError:
        return 0.0


def passes(r: dict, dsr: float) -> bool:
    return r.get("entries", 0) >= MIN_ENTRIES and len(r.get("days") or ()) >= MIN_DAYS and dsr >= BAR_P \
        and r.get("median", 0.0) > START_SOL


# ---------------------------------------------------------------- the ledger

def read_ledger(path: Path) -> list[dict]:
    out = []
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return out


def append_ledger(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str) + "\n")


def trials_of(ledger: list[dict]) -> list[dict]:
    return [r for r in ledger if r.get("kind") == "trial"]


def book_id(n: int) -> str:
    return f"{PREFIX}{n:05d}"


# ---------------------------------------------------------------- the strategy search

def study_of(d: Path, night: str, seed: int = SEED):
    import optuna
    from optuna.storages import JournalStorage
    from optuna.storages.journal import JournalFileBackend
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    d.mkdir(parents=True, exist_ok=True)
    storage = JournalStorage(JournalFileBackend(str(d / "optuna.journal")))
    h = int(hashlib.blake2b(night.encode(), digest_size=4).hexdigest(), 16)
    sampler = optuna.samplers.TPESampler(seed=(seed + h) % 2 ** 31, constant_liar=True, n_startup_trials=40)
    return optuna.create_study(study_name=f"f3_{night}", storage=storage, sampler=sampler, direction="maximize",
                               load_if_exists=True)


def search(rp: Replayer, d: Path, night: str, budget: int, deadline: float, log=print) -> list[dict]:
    """The night's trials (resumed: the ones the ledger has for this night count), in batches of one replay each;
    every trial into the ledger. Returns the night's trial lines."""
    import optuna
    path = d / "ledger.jsonl"
    led = read_ledger(path)
    mine = [r for r in trials_of(led) if r.get("night") == night]
    study = study_of(d, night)
    if not study.trials:                                      # a new night: the R2 reference and the best of before
        study.enqueue_trial(REFERENCE)
        best = sorted((r for r in trials_of(led) if r.get("entries", 0) >= MIN_ENTRIES),
                      key=lambda r: -r.get("score", 0.0))[:5]
        for r in best:
            study.enqueue_trial(r["params"])
    for t in study.trials:                                    # asked but never told (a run killed mid-batch)
        if t.state == optuna.trial.TrialState.RUNNING:
            study.tell(t.number, state=optuna.trial.TrialState.FAIL)
    left = budget - len(mine)
    per_s = None
    while left > 0:
        if per_s is not None and deadline - time.time() < 2 * per_s:   # a batch and the held-back replay must fit
            log(f"f3: {left} trial(s) left for a rerun of this night (time)")
            break
        k = min(BATCH, left)
        trials = [study.ask() for _ in range(k)]
        n0 = len(trials_of(read_ledger(path)))
        specs = [(book_id(n0 + j), space(t)) for j, t in enumerate(trials)]
        t0 = time.time()
        ent = rp.run(specs, rp.d.replay)
        per_s = time.time() - t0
        days = rp.scored()
        dr = draws(len(days))
        rows = []
        for (name, p), t in zip(specs, trials):
            r = score(ent[name], p, days, dr)
            study.tell(t, r["score"])
            rows.append({"kind": "trial", "id": name, "n": n0 + len(rows), "night": night, "trial": t.number,
                         "t_ms": int(time.time() * 1000), "params": p} | r)
        append_ledger(path, rows)
        mine += rows
        left -= k
        best = max(rows, key=lambda r: r["score"])
        log(f"f3: {len(mine)} trial(s) tonight; batch best {best['id']} median {best['median']:.3f} SOL, "
            f"lost 80 % {best['p_lost80'] * 100:.0f} %, {best['entries']} entries")
    return mine


def holdback(rp: Replayer, d: Path, night: str, mine: list[dict], log=print) -> list[dict]:
    """The night's TOP_HOLD trials by their objective (with MIN_ENTRIES), scored once on the held-back days; the
    lines into the ledger. A night that has its lines (a rerun) and a trial scored there before are not scored
    again."""
    path = d / "ledger.jsonl"
    led = read_ledger(path)
    prev = [r for r in led if r.get("kind") == "holdback" and r.get("night") == night]
    done = {r["id"] for r in led if r.get("kind") == "holdback"}
    top = [r for r in sorted(mine, key=lambda r: -r["score"]) if r.get("entries", 0) >= MIN_ENTRIES
           and r["id"] not in done][:TOP_HOLD]
    if prev or not top or not rp.d.hold:
        return prev
    ent = rp.run([(r["id"], r["params"]) for r in top], rp.d.days)
    dr = draws(len(rp.d.hold), seed=SEED + 1)
    rows = []
    for r in top:
        h = score(ent[r["id"]], r["params"], rp.d.hold, dr)
        rows.append({"kind": "holdback", "id": r["id"], "night": night, "t_ms": int(time.time() * 1000)} | h)
        log(f"f3: held back {r['id']}: median {h['median']:.3f} SOL, {h['entries']} entries, P&L "
            f"{h['pnl_sol']:+.3f} SOL at 0.1 SOL")
    append_ledger(path, rows)
    return rows


def winners(mine: list[dict], held: list[dict], ledger: list[dict]) -> list[dict]:
    """The night's trials that passed the bar in the search and made money on the held-back days."""
    sh, n = pool(ledger)
    hb = {r["id"]: r for r in held}
    out = []
    for r in mine:
        h = hb.get(r["id"])
        dsr = deflated(r, sh, n)
        if h is not None and passes(r, dsr) and h.get("median", 0.0) > START_SOL and h.get("pnl_sol", 0.0) > 0:
            out.append(r | {"dsr": dsr, "holdback": h})
    return sorted(out, key=lambda r: -r["score"])


# ---------------------------------------------------------------- the model settings

def model_space(trial) -> dict:
    f, i = trial.suggest_float, trial.suggest_int
    return {"n_estimators": i("n_estimators", 100, 600, step=50), "learning_rate": f("learning_rate", 0.01, 0.2,
                                                                                         log=True),
            "num_leaves": i("num_leaves", 7, 63), "min_child_samples": i("min_child_samples", 20, 1000, log=True),
            "colsample_bytree": f("colsample_bytree", 0.5, 1.0), "subsample": f("subsample", 0.5, 1.0),
            "reg_lambda": f("reg_lambda", 1e-3, 10.0, log=True)} | LGB_KEEP


def _f4(x) -> str:
    return "n/a" if x is None else f"{x:.4f}"


def fold_loss(ev: dict) -> dict[int, float]:
    return {f["fold"]: f["model"]["logloss"] for f in ev.get("folds") or []}


def hold_loss(table: dict, label: str, feats: list[str], params: dict, hold_ms: int) -> float | None:
    """Trained on the rows whose label window ended before the held-back days (purged as model.evaluate), the log
    loss on the held-back rows."""
    from . import model as M
    rs = M.labelled(table, label)
    tr = rs["t"] + M.LABELS[label] * 1000 + M.EMBARGO_MS < hold_ms
    te = rs["t"] >= hold_ms
    if tr.sum() < M.MIN_TRAIN or te.sum() < M.MIN_TEST:
        return None
    X = M.matrix(rs, feats)
    m = M.fit(X[tr], rs[label][tr], feats, params)
    return M.logloss(m.predict(X[te]), rs[label][te])


def tune_models(d: Path, night: str, hold_ms: int, trials: int, deadline: float, table: dict | None = None,
                log=print, params_file: Path | None = None) -> dict:
    """Per realistic label: the search on the rows before the held-back days, the night's best against the current
    setting fold by fold and on the held-back days; adopted into params.json when it wins both."""
    import optuna
    from optuna.storages import JournalStorage
    from optuna.storages.journal import JournalFileBackend
    from . import labels_r2 as L2
    from . import model as M
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    params_file = params_file or (d / "params.json")
    if table is None:
        from .retrain import load_rows
        try:
            raw, _ = load_rows()
        except Exception as e:                               # no rows: nothing to tune
            return {"error": f"no decision rows ({type(e).__name__}: {e})"}
        table = L2.realistic_rows(raw)
        if table is None:
            return {"error": "the rows have no realistic labels"}
    sets = ((R.read_json(R.reports_dir() / "models.json") or {}).get("labels") or {})
    search = {k: v[table["t"] < hold_ms] for k, v in table.items()}
    try:
        adopted = json.loads(params_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        adopted = {}
    out = {}
    for label in L2.REAL_ROW:
        if time.time() > deadline:
            out[label] = {"skipped": "time"}
            continue
        feats = M.SETS.get((sets.get(label) or {}).get("set") or "base", M.SETS["base"])
        cur = M.params_for(label, params_file)
        ev_cur = M.evaluate(search, label, M.FOLDS, feats, params=cur)
        if not ev_cur.get("folds"):
            out[label] = {"skipped": ev_cur.get("verdict", "too few rows")}
            continue
        cl = fold_loss(ev_cur)
        d.mkdir(parents=True, exist_ok=True)
        storage = JournalStorage(JournalFileBackend(str(d / "optuna.journal")))
        st = optuna.create_study(study_name=f"f3m_{label}_{night}", storage=storage, direction="minimize",
                                 sampler=optuna.samplers.TPESampler(seed=SEED, n_startup_trials=5),
                                 load_if_exists=True)
        evs = {}
        for _ in range(max(0, trials - len([t for t in st.trials if t.state.is_finished()]))):
            if time.time() > deadline:
                break
            t = st.ask()
            prm = {**M.PARAMS, **model_space(t)}
            t.set_user_attr("params", prm)
            ev = M.evaluate(search, label, M.FOLDS, feats, params=prm)
            fl = fold_loss(ev)
            v = float(np.mean(list(fl.values()))) if fl else math.inf
            st.tell(t, v if math.isfinite(v) else None, state=None if math.isfinite(v) else
                    optuna.trial.TrialState.FAIL)
            evs[t.number] = fl
        done = [t for t in st.trials if t.state == optuna.trial.TrialState.COMPLETE]
        if not done:
            out[label] = {"skipped": "no trial", "current": cur}
            continue
        best = min(done, key=lambda t: t.value)
        prm = best.user_attrs.get("params") or {**M.PARAMS, **best.params, **LGB_KEEP}
        bl = evs.get(best.number) or fold_loss(M.evaluate(search, label, M.FOLDS, feats, params=prm))
        won = sum(1 for k, v in bl.items() if k in cl and v < cl[k])
        h_new, h_cur = hold_loss(table, label, feats, prm, hold_ms), hold_loss(table, label, feats, cur, hold_ms)
        ok = won >= min(ADOPT_FOLDS, len(cl)) and len(cl) >= ADOPT_FOLDS and h_new is not None \
            and h_cur is not None and h_new < h_cur
        out[label] = {"trials": len(done), "best": prm, "current": cur, "folds": len(cl), "folds_won": won,
                      "loss_best": float(np.mean(list(bl.values()))), "loss_current": float(np.mean(list(cl.values()))),
                      "hold_best": h_new, "hold_current": h_cur, "adopted": bool(ok)}
        if ok:
            adopted[label] = {"params": prm, "adopted_ms": int(time.time() * 1000), "night": night,
                              "folds_won": won, "folds": len(cl), "hold_logloss": h_new, "was": h_cur}
            params_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = params_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(adopted, indent=1), encoding="utf-8")
            tmp.replace(params_file)
        log(f"f3: {label} best log loss {out[label]['loss_best']:.4f} against {out[label]['loss_current']:.4f}, "
            f"{won} of {len(cl)} folds, held back {_f4(h_new)} against {_f4(h_cur)}: "
            f"{'adopted' if ok else 'kept'}")
    return out


# ---------------------------------------------------------------- the paper books

def read_books(d: Path) -> dict:
    return R.read_json(d / "books.json") or {"books": []}


def write_books(d: Path, b: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "books.json.tmp"
    tmp.write_text(json.dumps(b, indent=1, default=str), encoding="utf-8")
    tmp.replace(d / "books.json")


def _pnl(state: dict | None, name: str) -> float | None:
    w = ((state or {}).get("paper_wallets") or {}).get(name)
    return R.PaperWallet.from_json(w).pnl_l / C.LAMPORTS if w else None


def manage(b: dict, new: list[dict], state: dict | None, now_ms: int, d: Path | None = None) -> dict:
    """The night's step: every active book's P&L against REF_BOOK's since its start (the collector's state.json),
    proposals after PROBATION_DAYS nights in a row ahead, the weakest book PROBATION_DAYS old and not ahead retired
    (one, and more to make room), the winners added while fewer than MAX_BOOKS are active."""
    day = day_of(now_ms)
    ref = _pnl(state, REF_BOOK)
    books = b.setdefault("books", [])
    act = [x for x in books if x.get("state") == "active"]
    for x in act:
        if x.get("ref0") is None and ref is not None:
            x["ref0"] = ref
        mine = _pnl(state, x["book"])
        if mine is None or ref is None or x.get("ref0") is None:
            continue
        h = [y for y in x.setdefault("history", []) if y.get("day") != day]
        h.append({"day": day, "pnl": mine, "ref": ref - x["ref0"]})
        x["history"] = h
    age = lambda x: (now_ms - x["added_ms"]) / DAY_MS
    ahead = lambda x: bool(x.get("history")) and x["history"][-1]["pnl"] > x["history"][-1]["ref"]
    for x in act:
        last = (x.get("history") or [])[-PROBATION_DAYS:]
        if age(x) >= PROBATION_DAYS and len(last) >= PROBATION_DAYS and all(y["pnl"] > y["ref"] for y in last) \
                and not x.get("proposed_ms"):
            x["proposed_ms"] = now_ms
            if d is not None:
                write_proposal(d, x)
    gap = lambda x: (x.get("history") or [{}])[-1].get("pnl", 0.0) - (x.get("history") or [{}])[-1].get("ref", 0.0)
    weak = sorted((x for x in act if age(x) >= PROBATION_DAYS and not ahead(x)), key=gap)
    have = {x["book"] for x in books}
    need = len([r for r in new if r["id"] not in have]) - (MAX_BOOKS - len(act) + min(1, len(weak)))
    for x in weak[:1 + max(0, need)]:
        x.update(state="retired", retired_ms=now_ms, why=f"{PROBATION_DAYS} days without beating {REF_BOOK}")
    act = [x for x in books if x.get("state") == "active"]
    for r in new:
        if r["id"] in have:
            continue
        if len(act) >= MAX_BOOKS:
            b.setdefault("waiting", []).append({"book": r["id"], "day": day})
            continue
        x = {"book": r["id"], "params": r["params"], "label": strategy_of(r["params"], r["id"]).label,
             "sizing": book_label(r["params"]), "added_ms": now_ms, "added_day": day, "state": "active",
             "ref0": ref, "history": [], "search": {k: r.get(k) for k in ("score", "median", "p_lost80", "entries",
                                                                          "dsr")},
             "holdback": {k: (r.get("holdback") or {}).get(k) for k in ("median", "pnl_sol", "entries")}}
        books.append(x)
        act.append(x)
    b["updated_ms"] = now_ms
    return b


def write_proposal(d: Path, x: dict) -> None:
    p = d / "proposals" / f"{x['book']}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    last = x["history"][-1]
    p.write_text("\n".join([
        f"# Proposal: {x['book']} (pump.fun factory F3)", "",
        f"The paper book {x['book']} beat {REF_BOOK} on each of the last {PROBATION_DAYS} nights since "
        f"{x['added_day']}: {last['pnl']:+.3f} SOL against {last['ref']:+.3f} SOL on a {START_SOL} SOL paper wallet.",
        "", f"Strategy: {x['label']}.", f"Sizing: {x['sizing']}.", "",
        "Paper only. Nothing goes live without the owner: the live bot's strategy, sizing and caps are his to change.",
        ""]), encoding="utf-8")


def status(b: dict, state: dict | None, eur: float | None) -> list[dict]:
    """The active books' paper wallets (state.json) in SOL and euro, and REF_BOOK's P&L since each one's start."""
    pw = (state or {}).get("paper_wallets") or {}
    ref = _pnl(state, REF_BOOK)
    out = []
    for x in b.get("books") or []:
        if x.get("state") != "active":
            continue
        w = R.PaperWallet.from_json(pw.get(x["book"])) if x["book"] in pw else None
        sol = (w.start_l + w.pnl_l) / C.LAMPORTS if w is not None else START_SOL
        out.append({"book": x["book"], "label": x.get("label", ""), "sizing": x.get("sizing", ""),
                    "added_day": x.get("added_day"), "sol": sol, "eur": sol * eur if eur else None,
                    "pnl_sol": w.pnl_l / C.LAMPORTS if w else 0.0, "trades": w.n if w else 0,
                    "refills": w.refills if w else 0, "ref_sol": None if ref is None or x.get("ref0") is None
                    else ref - x["ref0"], "proposed": bool(x.get("proposed_ms"))})
    return out


def status_md(rows: list[dict], eur: float | None) -> list[str]:
    if not rows:
        return []
    md = [f"Factory paper books (F3, reports/pumpfun_rt/factory.md): {START_SOL} SOL each from their start, sizing "
          f"fixed as found, against {REF_BOOK} since the same start; 1 SOL = "
          f"{'n/a' if not eur else format(eur, '.2f')} EUR.", "",
          f"| book | since | sizing | wallet SOL | wallet EUR | P&L SOL | {REF_BOOK} SOL | trades | top-ups |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        md.append(f"| {r['book']}{' (proposal)' if r['proposed'] else ''} | {r['added_day']} | {r['sizing']} | "
                  f"{r['sol']:.3f} | {'n/a' if r['eur'] is None else format(r['eur'], '.2f')} | "
                  f"{r['pnl_sol']:+.3f} | {'n/a' if r['ref_sol'] is None else format(r['ref_sol'], '+.3f')} | "
                  f"{r['trades']} | {r['refills']} |")
    return md + [""]


def active_specs(d: Path | None = None) -> list[tuple[str, dict]]:
    """The active books for the collector: (name, params)."""
    b = read_books(d or factory_dir())
    return [(x["book"], x["params"]) for x in b.get("books") or [] if x.get("state") == "active"
            and isinstance(x.get("params"), dict)]


# ---------------------------------------------------------------- the report

def summary(night: str, now_ms: int, days: Days, scored: list[str], ledger: list[dict], mine: list[dict],
            held: list[dict], won: list[dict], models: dict, adopted: dict, books: dict, state: dict | None,
            eur: float | None) -> dict:
    sh, n = pool(ledger)
    best = sorted(mine, key=lambda r: -r["score"])[:10]
    return {"updated_ms": now_ms, "night": night, "trials_ever": n, "trials_tonight": len(mine),
            "bar": {"sharpe": bar(sh, n), "p": BAR_P, "min_entries": MIN_ENTRIES, "min_days": MIN_DAYS, "trials": n,
                    "variance_trials": len(sh)},
            "days": days.days, "search_days": days.search, "scored_days": scored, "hold_days": days.hold,
            "held_before": getattr(days, "held", []),
            "best": [r | {"dsr": deflated(r, sh, n), "label": strategy_of(r["params"], r["id"]).label,
                          "sizing": book_label(r["params"])} for r in best],
            "holdback": held, "winners": [r["id"] for r in won], "models": models, "adopted": adopted,
            "books": status(books, state, eur),
            "retired": [x for x in books.get("books") or [] if x.get("state") == "retired"][-10:],
            "proposals": [x["book"] for x in books.get("books") or [] if x.get("proposed_ms")],
            "sol_eur": eur, "start_sol": START_SOL}


def markdown(s: dict) -> str:
    eur = s.get("sol_eur")
    pct = lambda x: "n/a" if x is None else f"{x * 100:+.1f} %"
    b = s["bar"]
    before = f" (out of the search: {', '.join(s['held_before'])}, held back the night before)" \
        if s.get("held_before") else ""
    md = ["# pump.fun factory (F3)", "",
          f"Night {s['night']}: {s['trials_tonight']} strategy trials tonight, {s['trials_ever']} in the ledger. "
          f"Search days {', '.join(s['search_days']) or 'none'} (scored: {', '.join(s['scored_days']) or 'none'}), "
          f"held back {', '.join(s['hold_days']) or 'none'}"
          f"{before}. Every trial realistic (the live bot's latency, fills, "
          f"failures, fees) on a {START_SOL} SOL wallet, {PATHS:,} paths of {HORIZON} days.", "",
          f"The bar: a deflated Sharpe per entry with p at least {b['p']:.2f} against {b['trials']} trials, the noise "
          f"from the {b.get('variance_trials', b['trials'])} with at least {b['min_entries']} entries (the best of "
          f"that many with no skill reaches {b['sharpe']:.3f}), on the effective entries of a standard error by day; "
          f"at least {b['min_entries']} entries, {b.get('min_days', MIN_DAYS)} scored days and a median wallet above "
          f"the start.", "",
          "The night's best by the objective (median end wallet less the ruin penalty). Mean per entry at 0.1 SOL "
          f"with its 95 % band by day, and without the best and worst {TRIM * 100:.0f} % of entries; the medians are "
          f"the bootstrap's {HORIZON} days drawn from the scored days, no forecast:", "",
          "| trial | mean per entry | band by day | trimmed | days | entries | Sharpe | deflated p | median SOL | "
          "lost 80 % | strategy | sizing |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in s["best"]:
        md.append(f"| {r['id']} | {pct(r.get('mean'))} | {pct(r.get('lo'))} to {pct(r.get('hi'))} | "
                  f"{pct(r.get('trimmed'))} | {r.get('days_traded', 0)} of {len(r.get('days') or ())} | "
                  f"{r['entries']} | {r['sharpe']:+.3f} | {r['dsr']:.2f} | {r['median']:.3f} | "
                  f"{r['p_lost80'] * 100:.0f} % | {r['label']} | {r['sizing']} |")
    md += ["", "Held back (scored once):", ""]
    if s["holdback"]:
        md += ["| trial | mean per entry | band by day | trimmed | entries | P&L at 0.1 SOL |",
               "|---|---|---|---|---|---|"]
        md += [f"| {r['id']} | {pct(r.get('mean'))} | {pct(r.get('lo'))} to {pct(r.get('hi'))} | "
               f"{pct(r.get('trimmed'))} | {r['entries']} | {r['pnl_sol']:+.3f} SOL |" for r in s["holdback"]]
    else:
        md.append("none tonight.")
    md += ["", "Winners tonight: " + (", ".join(s["winners"]) if s["winners"] else "none (nothing passed the bar "
                                                                                   "and the held-back days)."), "",
           "Model settings (LightGBM, R2's realistic labels; adopted when better in "
           f"{ADOPT_FOLDS} of 5 folds and on the held-back days):", ""]
    mods = s.get("models") or {}
    if mods.get("error"):
        md.append(f"not tuned: {mods['error']}.")
    else:
        md += ["| label | trials | log loss best | current | folds won | held back best | current | |",
               "|---|---|---|---|---|---|---|---|"]
        for k, v in mods.items():
            if "skipped" in v:
                md.append(f"| {k} | | | | | | | skipped: {v['skipped']} |")
                continue
            hb = lambda x: "n/a" if x is None else f"{x:.4f}"
            md.append(f"| {k} | {v['trials']} | {v['loss_best']:.4f} | {v['loss_current']:.4f} | "
                      f"{v['folds_won']} of {v['folds']} | {hb(v['hold_best'])} | {hb(v['hold_current'])} | "
                      f"{'adopted' if v['adopted'] else 'kept'} |")
    ad = s.get("adopted") or {}
    md += ["", "Adopted settings in use: " + ("; ".join(f"{k} since {v.get('night')}" for k, v in ad.items())
                                              if ad else "none (the code's PARAMS)") + "."]
    md += ["", *(status_md(s["books"], eur) or ["Factory paper books: none yet."])]
    if s.get("proposals"):
        md += ["", "Proposals for the owner (factory/proposals/): " + ", ".join(s["proposals"]) + "."]
    md += ["", "Paper only: nothing here trades real money."]
    return "\n".join(md) + "\n"


# ---------------------------------------------------------------- the night

def run(now_ms: int | None = None, trials: int | None = None, model_trials: int | None = None,
        d: Path | None = None, out: Path | None = None, budget_s: float | None = None, root=None,
        log=print) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    t0 = time.time()
    deadline = t0 + (BUDGET_S if budget_s is None else budget_s)
    d = d or factory_dir()
    out = out or R.reports_dir()
    trials = _env_int("PYTHIA_PF_FACTORY_TRIALS", TRIALS) if trials is None else trials
    model_trials = _env_int("PYTHIA_PF_FACTORY_MODEL_TRIALS", MODEL_TRIALS) if model_trials is None else model_trials
    night = day_of(now_ms)
    days = Days(now_ms, root, held=held_before(read_ledger(d / "ledger.jsonl"), night))
    if len(days.search) < 2:
        log(f"f3: too few recorded days ({len(days.days)})")
        return {"empty": True}
    hold_ms = SW.day_start(days.hold[0]) if days.hold else now_ms
    log(f"f3: night {night}, search {days.search[0]} to {days.search[-1]}, held back {days.hold}"
        f"{f', out of the search {days.held}' if days.held else ''}")
    models = tune_models(d, night, hold_ms, model_trials, min(deadline, t0 + MODEL_BUDGET_S), log=log,
                         params_file=d / "params.json") if model_trials else {"error": "no trials asked"}
    fit_ = R.fit(R._measured(), hold_ms)                      # the live orders up to the held-back days
    rp = Replayer(days, R.Model(fit_, R.LiveConfig()), root, log)
    mine = search(rp, d, night, trials, deadline, log) if trials else []
    held = holdback(rp, d, night, mine, log) if mine else []
    led = read_ledger(d / "ledger.jsonl")
    won = winners(mine, held, led)
    from .live import paper_dir
    state = R.read_json(paper_dir() / "state.json")
    books = manage(read_books(d), won, state, now_ms, d)
    write_books(d, books)
    eur = R.sol_eur()
    s = summary(night, now_ms, days, rp.scored(), led, mine, held, won, models,
                R.read_json(d / "params.json") or {}, books, state, eur)
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "factory.json.tmp"
    tmp.write_text(json.dumps(s, default=str), encoding="utf-8")
    tmp.replace(out / "factory.json")
    (out / "factory.md").write_text(markdown(s), encoding="utf-8")
    log(f"f3: done in {time.time() - t0:.0f} s")
    return s


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.factory")
    ap.add_argument("--trials", type=int, default=None, help="strategy trials tonight (PYTHIA_PF_FACTORY_TRIALS)")
    ap.add_argument("--model-trials", type=int, default=None, help="per label (PYTHIA_PF_FACTORY_MODEL_TRIALS)")
    ap.add_argument("--dir", default=None, help="the factory's files (default <data>/pumpfun_rt/factory)")
    ap.add_argument("--out", default=None, help="the reports (default reports/pumpfun_rt)")
    ap.add_argument("--budget-s", type=float, default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    s = run(trials=a.trials, model_trials=a.model_trials, d=Path(a.dir) if a.dir else None,
            out=Path(a.out) if a.out else None, budget_s=a.budget_s)
    if s.get("empty"):
        return 1
    print(markdown(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
