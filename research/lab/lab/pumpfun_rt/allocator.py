"""A1 (results/pumpfun_adaptive_a1_prereg.md): the strategy allocator for the pump.fun paper wallets. PAPER ONLY.

    python -m lab.pumpfun_rt.allocator            reports/pumpfun_rt/allocator.{json,md} (the daily retrain runs it too)

A Thompson sampling bandit over the pre-registered candidates (ARMS): the live bot's P_pool0_wait and R2's two
winners, P_pool0_wait_lock and P_pool5_top30t. Y16 found no rug filter that held out of sample (pumpfun_rugfilter.md),
so there is no rug-filtered arm; a new arm is one line in ARMS and a new registration.

The reward of an arm on a UTC day: its realistic paper trades closed that day (paper/pumpfun_rt/ledger.csv, the books
of that name since the collector's realistic_since; failed buys from failed.csv at their fee) as the log growth of a
wallet that puts SHARE of itself into each trade, sum(log(1 + SHARE x return)); a day without a trade is 0. Days are
full UTC days before today. The posterior per arm: normal with unknown mean and variance (normal-inverse-gamma), the
days weighted by HALF_LIFE_DAYS so that the posterior follows changing conditions; P(best) from DRAWS joint draws.

  floor     every arm not guarded keeps at least FLOOR of the weight (exploration)
  guard     an arm whose wallet over the last GUARD_DAYS days is GUARD_DD or more under its peak there gets no
            weight; with every arm guarded the choice is to stay out
  choice    one draw from the weights, seeded by the day (Thompson sampling with the floor)

It never changes the live bot: the live bot keeps the strategy the owner set (live_status.json's rule); the report
says which one the allocator would pick and why. Arming it for the live bot would need the owner's ack in the live
service, which is not built (ARMED is False). Nothing here holds a wallet, reads a key, signs or sends.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ARMS = ("P_pool0_wait", "P_pool0_wait_lock", "P_pool5_top30t")
SHARE = 0.10                                   # R2's sizing: 10 % of the wallet a trade
FAIL_STAKE_SOL = 0.055                         # a failed buy's fee over SHARE of the 0.55 SOL paper wallet
HALF_LIFE_DAYS = 7.0
FLOOR = 0.05
GUARD_DAYS = 14
GUARD_DD = 0.30
DRAWS = 10_000
PRIOR_KAPPA, PRIOR_ALPHA, PRIOR_VAR = 1.0, 2.0, 0.01
ARMED = False                                  # the live bot is never steered from here
DAY_MS = 86_400_000
NAME = "pumpfun_rt"


def day_of(ms: float) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- the rewards

def _float(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def paper_trades(paper: Path, since_ms: float, arms=ARMS) -> dict[str, list[tuple[float, float]]]:
    """{arm: [(close ms, return over the stake)]} of the arms' realistic paper books: closed trades from ledger.csv,
    failed buys from failed.csv at their fee over FAIL_STAKE_SOL."""
    out: dict[str, list] = {a: [] for a in arms}
    for fn, t_col, ret_of in (("ledger.csv", "exit_ms", lambda r: _float(r.get("ret"))),
                              ("failed.csv", "land_ms", lambda r: (_float(r.get("pnl_sol")) or 0.0) / FAIL_STAKE_SOL)):
        try:
            with (paper / fn).open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    a = r.get("rule")
                    t = _float(r.get(t_col))
                    if a in out and t is not None and t >= since_ms:
                        v = ret_of(r)
                        if v is not None:
                            out[a].append((t, v))
        except OSError:
            continue
    return out


def day_rewards(trades: dict[str, list[tuple[float, float]]], days: list[str],
                share: float = SHARE) -> dict[str, dict[str, float]]:
    """{arm: {day: sum(log(1 + share x return))}} on the given days, 0 on a day without a trade."""
    out = {}
    for a, xs in trades.items():
        r = {d: 0.0 for d in days}
        for t, v in xs:
            d = day_of(t)
            if d in r:
                r[d] += math.log(max(1e-9, 1 + share * v))
        out[a] = r
    return out


def full_days(since_ms: float, now_ms: float) -> list[str]:
    """The full UTC days from the first one after since_ms to yesterday."""
    lo = (int(since_ms) // DAY_MS + (1 if since_ms % DAY_MS else 0)) * DAY_MS
    return [day_of(t) for t in range(lo, int(now_ms) // DAY_MS * DAY_MS, DAY_MS)]


# ---------------------------------------------------------------- the posterior

def posterior(r: np.ndarray, age: np.ndarray, prior_var: float, half_life: float = HALF_LIFE_DAYS) -> dict:
    """Normal-inverse-gamma posterior of the mean daily reward, the days weighted 0.5 ** (age / half_life)."""
    w = 0.5 ** (age / half_life) if half_life and half_life > 0 else np.ones(len(r))
    n = float(w.sum())
    m = float((w * r).sum() / n) if n > 0 else 0.0
    s = float((w * (r - m) ** 2).sum()) if n > 0 else 0.0
    k = PRIOR_KAPPA + n
    mu = n * m / k
    a = PRIOR_ALPHA + n / 2
    b = prior_var * (PRIOR_ALPHA - 1) + s / 2 + PRIOR_KAPPA * n * m ** 2 / (2 * k)
    return {"n": n, "mean": m, "mu": mu, "kappa": k, "alpha": a, "beta": b,
            "sd_mean": math.sqrt(b / (a - 1) / k) if a > 1 else math.inf}


def draw_means(post: dict, rng: np.random.Generator, n: int = DRAWS) -> np.ndarray:
    var = post["beta"] / rng.gamma(post["alpha"], 1.0, n)
    return rng.normal(post["mu"], np.sqrt(var / post["kappa"]))


def drawdown(r: list[float]) -> float:
    """How far the wallet (exp of the cumulated rewards, start 1) ends under its peak, as a share of the peak."""
    w = np.exp(np.cumsum(np.r_[0.0, r]))
    return float(1 - w[-1] / w.max())


def decide(rewards: dict[str, dict[str, float]], days: list[str], seed_day: str, floor: float = FLOOR,
           guard_dd: float = GUARD_DD, guard_days: int = GUARD_DAYS, half_life: float = HALF_LIFE_DAYS) -> dict:
    """The allocator on `days` (the days before seed_day): per arm the posterior, P(best), the drawdown and the guard,
    the weights with the floor, and the choice (one draw seeded by seed_day); None when every arm is guarded."""
    arms = list(rewards)
    seed = int(seed_day.replace("-", "")) if seed_day else 0
    rng = np.random.default_rng(seed)
    allr = np.array([rewards[a][d] for a in arms for d in days if d in rewards[a]], dtype=float)
    pv = float(np.var(allr, ddof=1)) if len(allr) > 2 else PRIOR_VAR
    pv = pv if pv > 0 else PRIOR_VAR
    out = {}
    for a in arms:
        ds = [d for d in days if d in rewards[a]]
        r = np.array([rewards[a][d] for d in ds], dtype=float)
        age = np.arange(len(ds))[::-1].astype(float)
        p = posterior(r, age, pv, half_life)
        dd = drawdown([rewards[a][d] for d in ds[-guard_days:]])
        out[a] = {"days": len(ds), "post": p, "drawdown": dd, "guarded": bool(len(ds) and dd >= guard_dd),
                  "wallet": float(math.exp(sum(r))) if len(r) else 1.0}
    live = [a for a in arms if not out[a]["guarded"]]
    if live:
        dr = np.column_stack([draw_means(out[a]["post"], rng) for a in live])
        best = np.bincount(dr.argmax(axis=1), minlength=len(live)) / len(dr)
    for a in arms:
        out[a]["p_best"] = float(best[live.index(a)]) if a in live else 0.0
    k = len(live)
    fl = min(floor, 1.0 / k) if k else 0.0
    for a in arms:
        out[a]["weight"] = (fl + (1 - k * fl) * out[a]["p_best"]) if a in live else 0.0
    choice = None
    if live:
        w = np.array([out[a]["weight"] for a in live])
        choice = live[int(rng.choice(len(live), p=w / w.sum()))]
    return {"arms": out, "choice": choice, "days": list(days)}


def why(res: dict, live_rule: str | None) -> str:
    c = res["choice"]
    if c is None:
        return "every candidate is under its drawdown guard: stay out"
    a = res["arms"][c]
    g = [k for k, v in res["arms"].items() if v["guarded"]]
    s = (f"{c}: P(best) {a['p_best'] * 100:.0f} %, weight {a['weight'] * 100:.0f} %, mean daily growth at "
         f"{SHARE * 100:g} % a trade {a['post']['mean'] * 100:+.1f} % over {a['days']} days, the 10 % wallet "
         f"x{a['wallet']:.2f}")
    if g:
        s += "; guarded: " + ", ".join(g)
    if live_rule:
        s += (f"; the live bot keeps the owner's {live_rule}" + (" (the same)" if live_rule == c else ""))
    return s


# ---------------------------------------------------------------- the daily run

def live_rule(path: Path | None = None) -> str | None:
    """The live bot's strategy as its status file says (only that field is read)."""
    from . import realistic as R
    d = R.read_json(path or (R.reports_dir() / "live_status.json")) or {}
    v = d.get("rule")
    return str(v) if v else None


def run(now_ms: int | None = None, paper: Path | None = None, out: Path | None = None, log=print) -> dict:
    from . import realistic as R
    from .live import paper_dir
    now_ms = now_ms or int(time.time() * 1000)
    paper = paper or paper_dir()
    st = R.read_json(paper / "state.json") or {}
    since = float(st.get("realistic_since") or 0)
    days = full_days(since, now_ms) if since else []
    rw = day_rewards(paper_trades(paper, since), days)
    res = decide(rw, days, day_of(now_ms))
    lr = live_rule()
    doc = {"updated_ms": now_ms, "day": day_of(now_ms), "since_ms": since, "share": SHARE, "floor": FLOOR,
           "guard_dd": GUARD_DD, "half_life_days": HALF_LIFE_DAYS, "armed": ARMED, "live_rule": lr,
           "choice": res["choice"], "why": why(res, lr),
           "arms": {a: {"days": v["days"], "mean": v["post"]["mean"], "posterior_mean": v["post"]["mu"],
                        "posterior_sd": v["post"]["sd_mean"], "p_best": v["p_best"], "weight": v["weight"],
                        "drawdown": v["drawdown"], "guarded": v["guarded"], "wallet_x": v["wallet"],
                        "rewards": rw.get(a, {})}
                    for a, v in res["arms"].items()}}
    out = out or R.reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / "allocator.json").write_text(json.dumps(doc, indent=1, default=str), encoding="utf-8")
    (out / "allocator.md").write_text(markdown(doc), encoding="utf-8")
    log(f"{NAME} allocator: {doc['why']}")
    return doc


def markdown(doc: dict) -> str:
    md = ["# pump.fun real-time lab: A1 strategy allocator", "",
          f"Paper only, never steers the live bot. Thompson sampling over {', '.join(doc['arms'])} on their realistic "
          f"paper trades since the realistic books started, a day's reward the log growth of a wallet at "
          f"{doc['share'] * 100:g} % a trade, days weighted with a half-life of {doc['half_life_days']:g} days; "
          f"floor {doc['floor'] * 100:g} %, drawdown guard {doc['guard_dd'] * 100:g} % in 14 days.", "",
          f"Would pick: **{doc['choice'] or 'none (stay out)'}**. Why: {doc['why']}.", "",
          "| strategy | days | mean daily growth | posterior mean | posterior sd | P(best) | weight | wallet x | "
          "drawdown | guarded |", "|---|---|---|---|---|---|---|---|---|---|"]
    for a, v in doc["arms"].items():
        md.append(f"| {a} | {v['days']} | {v['mean'] * 100:+.2f} % | {v['posterior_mean'] * 100:+.2f} % | "
                  f"{v['posterior_sd'] * 100:.2f} % | {v['p_best'] * 100:.0f} % | {v['weight'] * 100:.0f} % | "
                  f"{v['wallet_x']:.2f} | {v['drawdown'] * 100:.0f} % | {'yes' if v['guarded'] else 'no'} |")
    return "\n".join(md) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.allocator", description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    doc = run(out=Path(a.out) if a.out else None)
    print(markdown(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
