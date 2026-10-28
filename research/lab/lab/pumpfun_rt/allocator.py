"""A1 (results/pumpfun_adaptive_a1_prereg.md): the strategy allocator for the pump.fun paper wallets. PAPER ONLY.

    python -m lab.pumpfun_rt.allocator            reports/pumpfun_rt/allocator.{json,md} (the daily retrain runs it too)

A bandit over the pre-registered candidates (ARMS): the live bot's P_pool0_wait and R2's two
winners, P_pool0_wait_lock and P_pool5_top30t. Y16 found no rug filter that held out of sample (pumpfun_rugfilter.md),
so there is no rug-filtered arm; a new arm is one line in ARMS and a new registration.

The reward of an arm on a UTC day: its realistic paper trades closed that day (paper/pumpfun_rt/ledger.csv, the books
of that name since the collector's realistic_since; failed buys from failed.csv at their fee) as the log growth of a
wallet that puts SHARE of itself into each trade, sum(log(1 + SHARE x return)); a day without a trade is 0. Days are
full UTC days before today. The posterior per arm: normal with unknown mean and variance (normal-inverse-gamma), the
days weighted by HALF_LIFE_DAYS so that the posterior follows changing conditions.

  shared    T9 (results/allocator_t9_prereg.md): the arms share entries (P_pool0_wait and its lock the same coins),
            so an entry held by k arms on a day counts 1 / k in each; a day's weight is multiplied by the mean of
            1 / k over the arm's entries that day (1 on a day without one). The arms' posteriors stay independent.
  P(best)   by quadrature over the posteriors' Student t marginals of the mean (deterministic: arms with the same
            posterior get the same P(best)); MODE "drawn" is A1 as it ran (DRAWS Monte Carlo draws, no sharing)
  floor     every arm not guarded keeps at least FLOOR of the weight (exploration)
  guard     an arm whose wallet over the last GUARD_DAYS days is GUARD_DD or more under its peak there gets no
            weight; with every arm guarded the choice is to stay out
  choice    weighted (T9, the default): the paper wallet is split by the weights, every arm's reward is seen anyway;
            "choice" is the arm with the largest weight. drawn (A1): one draw from the weights, seeded by the day

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
MODE = "weighted"                              # T9; "drawn" is A1's Thompson draw
GRID = 4001                                    # quadrature points of P(best)
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


def paper_trades(paper: Path, since_ms: float, arms=ARMS,
                 taint: dict | None = None) -> dict[str, list[tuple[float, float, str]]]:
    """{arm: [(close ms, return over the stake, mint)]} of the arms' realistic paper books: closed trades from
    ledger.csv, failed buys from failed.csv at their fee over FAIL_STAKE_SOL. A closed trade the late-row bug made
    (P1, realistic.tainted) is skipped and counted per arm in `taint` when given."""
    from .realistic import tainted
    out: dict[str, list] = {a: [] for a in arms}
    for fn, t_col, ret_of in (("ledger.csv", "exit_ms", lambda r: _float(r.get("ret"))),
                              ("failed.csv", "land_ms", lambda r: (_float(r.get("pnl_sol")) or 0.0) / FAIL_STAKE_SOL)):
        try:
            with (paper / fn).open(encoding="utf-8", newline="") as fh:
                for r in csv.DictReader(fh):
                    a = r.get("rule")
                    t = _float(r.get(t_col))
                    if a in out and t is not None and t >= since_ms:
                        if fn == "ledger.csv" and tainted(r):
                            if taint is not None:
                                taint[a] = taint.get(a, 0) + 1
                            continue
                        v = ret_of(r)
                        if v is not None:
                            out[a].append((t, v, r.get("mint") or ""))
        except OSError:
            continue
    return out


def day_rewards(trades: dict[str, list[tuple]], days: list[str],
                share: float = SHARE) -> dict[str, dict[str, float]]:
    """{arm: {day: sum(log(1 + share x return))}} on the given days, 0 on a day without a trade."""
    out = {}
    for a, xs in trades.items():
        r = {d: 0.0 for d in days}
        for t, v, *_ in xs:
            d = day_of(t)
            if d in r:
                r[d] += math.log(max(1e-9, 1 + share * v))
        out[a] = r
    return out


def day_shares(trades: dict[str, list[tuple]], days: list[str]) -> dict[str, dict[str, float]]:
    """{arm: {day: mean of 1 / k over the arm's entries that day}}, k the number of arms with an entry on the same
    mint that day (1 on a day without an entry; an entry without a mint is its own)."""
    held: dict[tuple[str, str], set] = {}
    for a, xs in trades.items():
        for t, _, *m in xs:
            if m and m[0]:
                held.setdefault((day_of(t), m[0]), set()).add(a)
    out = {}
    for a, xs in trades.items():
        acc = {d: [] for d in days}
        for t, _, *m in xs:
            d = day_of(t)
            if d in acc:
                acc[d].append(1.0 / len(held[(d, m[0])]) if m and m[0] else 1.0)
        out[a] = {d: (sum(v) / len(v) if v else 1.0) for d, v in acc.items()}
    return out


def full_days(since_ms: float, now_ms: float) -> list[str]:
    """The full UTC days from the first one after since_ms to yesterday."""
    lo = (int(since_ms) // DAY_MS + (1 if since_ms % DAY_MS else 0)) * DAY_MS
    return [day_of(t) for t in range(lo, int(now_ms) // DAY_MS * DAY_MS, DAY_MS)]


# ---------------------------------------------------------------- the posterior

def posterior(r: np.ndarray, age: np.ndarray, prior_var: float, half_life: float = HALF_LIFE_DAYS,
              share: np.ndarray | None = None) -> dict:
    """Normal-inverse-gamma posterior of the mean daily reward, the days weighted 0.5 ** (age / half_life), times
    `share` (day_shares) when given."""
    w = 0.5 ** (age / half_life) if half_life and half_life > 0 else np.ones(len(r))
    if share is not None:
        w = w * np.asarray(share, dtype=float)
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


def p_best(posts: list[dict], grid: int = GRID) -> np.ndarray:
    """P(each arm's mean is the largest), integrated on the union of a grid per arm over the Student t marginals of the means
    (2 alpha degrees of freedom, scale sqrt(beta / (alpha kappa))); sums to 1."""
    if not posts:
        return np.zeros(0)
    from scipy import stats
    loc = np.array([p["mu"] for p in posts])
    sc = np.array([math.sqrt(p["beta"] / (p["alpha"] * p["kappa"])) for p in posts])
    df = np.array([2 * p["alpha"] for p in posts])
    x = np.unique(np.concatenate([np.linspace(l - 30 * c, l + 30 * c, grid) for l, c in zip(loc, sc)]))
    lcdf = np.array([stats.t.logcdf(x, d, l, s) for d, l, s in zip(df, loc, sc)])
    pdf = np.array([stats.t.pdf(x, d, l, s) for d, l, s in zip(df, loc, sc)])
    tot = lcdf.sum(axis=0)
    out = np.array([np.trapezoid(pdf[i] * np.exp(tot - lcdf[i]), x) for i in range(len(posts))])
    return out / out.sum() if out.sum() > 0 else np.full(len(posts), 1.0 / len(posts))


def drawdown(r: list[float]) -> float:
    """How far the wallet (exp of the cumulated rewards, start 1) ends under its peak, as a share of the peak."""
    w = np.exp(np.cumsum(np.r_[0.0, r]))
    return float(1 - w[-1] / w.max())


def decide(rewards: dict[str, dict[str, float]], days: list[str], seed_day: str, floor: float = FLOOR,
           guard_dd: float = GUARD_DD, guard_days: int = GUARD_DAYS, half_life: float = HALF_LIFE_DAYS,
           shares: dict[str, dict[str, float]] | None = None, mode: str = MODE) -> dict:
    """The allocator on `days` (the days before seed_day): per arm the posterior, P(best), the drawdown and the guard,
    the weights with the floor, and the choice; None when every arm is guarded. mode "weighted": P(best) by
    quadrature on the posteriors with `shares` (day_shares; none: every day 1), the choice the largest weight.
    mode "drawn" (A1): P(best) from DRAWS draws, no shares, the choice one draw seeded by seed_day."""
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
        sh = np.array([shares[a].get(d, 1.0) for d in ds]) if shares and mode != "drawn" and a in shares else None
        p = posterior(r, age, pv, half_life, sh)
        dd = drawdown([rewards[a][d] for d in ds[-guard_days:]])
        out[a] = {"days": len(ds), "post": p, "drawdown": dd, "guarded": bool(len(ds) and dd >= guard_dd),
                  "wallet": float(math.exp(sum(r))) if len(r) else 1.0}
    live = [a for a in arms if not out[a]["guarded"]]
    if live and mode == "drawn":
        dr = np.column_stack([draw_means(out[a]["post"], rng) for a in live])
        best = np.bincount(dr.argmax(axis=1), minlength=len(live)) / len(dr)
    elif live:
        best = p_best([out[a]["post"] for a in live])
    for a in arms:
        out[a]["p_best"] = float(best[live.index(a)]) if a in live else 0.0
    k = len(live)
    fl = min(floor, 1.0 / k) if k else 0.0
    for a in arms:
        out[a]["weight"] = (fl + (1 - k * fl) * out[a]["p_best"]) if a in live else 0.0
    choice = None
    if live and mode == "drawn":
        w = np.array([out[a]["weight"] for a in live])
        choice = live[int(rng.choice(len(live), p=w / w.sum()))]
    elif live:
        choice = max(live, key=lambda a: out[a]["weight"])
    return {"arms": out, "choice": choice, "days": list(days), "mode": mode}


def split_reward(res: dict, rewards: dict[str, dict[str, float]], day: str) -> float:
    """The day's log growth of a wallet split by the weights, each part trading its arm at SHARE a trade:
    log(sum w exp(reward)); 0 when every arm is guarded (out)."""
    w = {a: v["weight"] for a, v in res["arms"].items() if v["weight"] > 0}
    s = sum(w.values())
    return float(math.log(sum(x / s * math.exp(rewards[a][day]) for a, x in w.items()))) if s > 0 else 0.0


def why(res: dict, live_rule: str | None) -> str:
    c = res["choice"]
    if c is None:
        return "every candidate is under its drawdown guard: stay out"
    a = res["arms"][c]
    g = [k for k, v in res["arms"].items() if v["guarded"]]
    s = "split by weight, the largest " if res.get("mode", MODE) != "drawn" else ""
    s += (f"{c}: P(best) {a['p_best'] * 100:.0f} %, weight {a['weight'] * 100:.0f} %, mean daily growth at "
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
    bad: dict[str, int] = {}
    tr = paper_trades(paper, since, taint=bad)
    rw = day_rewards(tr, days)
    res = decide(rw, days, day_of(now_ms), shares=day_shares(tr, days))
    lr = live_rule()
    doc = {"updated_ms": now_ms, "day": day_of(now_ms), "since_ms": since, "share": SHARE, "floor": FLOOR,
           "mode": res["mode"],
           "guard_dd": GUARD_DD, "half_life_days": HALF_LIFE_DAYS, "armed": ARMED, "live_rule": lr,
           "choice": res["choice"], "why": why(res, lr), "tainted": bad,
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
          f"Paper only, never steers the live bot. A split of the paper wallet by each strategy's posterior "
          f"probability of being best (T9) over {', '.join(doc['arms'])} on their realistic "
          f"paper trades since the realistic books started, a day's reward the log growth of a wallet at "
          f"{doc['share'] * 100:g} % a trade, days weighted with a half-life of {doc['half_life_days']:g} days, an "
          f"entry shared by k strategies counted 1 / k in each; floor {doc['floor'] * 100:g} %, drawdown guard "
          f"{doc['guard_dd'] * 100:g} % in 14 days.", "",
          f"Would pick: **{doc['choice'] or 'none (stay out)'}** (the largest weight). Why: {doc['why']}.", "",
          "| strategy | days | mean daily growth | posterior mean | posterior sd | P(best) | weight | wallet x | "
          "drawdown | guarded |", "|---|---|---|---|---|---|---|---|---|---|"]
    for a, v in doc["arms"].items():
        md.append(f"| {a} | {v['days']} | {v['mean'] * 100:+.2f} % | {v['posterior_mean'] * 100:+.2f} % | "
                  f"{v['posterior_sd'] * 100:.2f} % | {v['p_best'] * 100:.0f} % | {v['weight'] * 100:.0f} % | "
                  f"{v['wallet_x']:.2f} | {v['drawdown'] * 100:.0f} % | {'yes' if v['guarded'] else 'no'} |")
    md += taint_line(doc.get("tainted"))
    return "\n".join(md) + "\n"


def taint_line(bad: dict | None) -> list[str]:
    """The trades paper_trades skipped as the late-row bug's (P1), per arm; nothing when none."""
    if not bad or not sum(bad.values()):
        return []
    return ["", f"Skipped: {sum(bad.values())} paper trades the late-row bug made before d84b252's deploy ("
            + ", ".join(f"{a} {n}" for a, n in sorted(bad.items())) + "; P1, results/pumpfun_ledger_taint_p1.md)."]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lab.pumpfun_rt.allocator", description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=None)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)
    doc = run(out=Path(a.out) if a.out else None)
    print(markdown(doc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
