"""The factory's grammar: a typed, bounded description of a long-only daily strategy.

A genome is a plain JSON object with six parts, each drawn from building
blocks the hand studies already use:

  universe   where it may buy
               top N    the N most liquid eligible coins of each day (survivorship-free)
               core     the lab's 20 engine coins (today's list, so survivorship-biased:
                        judged together with its point-in-time twin)
               alpaca   the 15 coins Alpaca lists (today's list, same caveat)
  signal     which coins are "on"
               mom      L-day return above 0 (time-series momentum)
               donchian close above the highest close of the last N days, held until
                        it falls below the lowest close of the last N*exit days
               ma       fast moving average above the slow one
               rev      L-day return below 0 (short-term reversal)
               lowvol   every eligible coin, ranked by low volatility
  filters    up to MAX_FILTERS extra conditions, each kind at most once
               regime   BTC above its M-day average, else the whole book is cash
               btcmom   BTC's L-day return above 0, else cash
               vol      the coin's annualised vol below a cap
               volume   7-day over S-day quote volume at least a ratio (volume confirmation)
               trend    the coin above its own M-day average
  select     at most K coins, ranked by the signal's strength, by liquidity or by low vol
  weight     equal or inverse vol; "slots" leaves empty slots in cash (1/K each, or 40 %
             annual vol over K), "full" spreads the whole book over what is held
  rebalance  every 1, 3 or 7 days, with a no-trade band of 0, 25 or 50 % of the target;
             a weekly book may be split into 7 tranches, one rebalanced each day
             (as tsmom_tranches): the same targets, a seventh of the timing luck

Complexity counts the moving parts (signal 1, each filter 1, inverse vol 1, a
band 1, a slower cadence 1, tranches 1, a non-default ranking 1); it is bounded by
MAX_COMPLEXITY and costs fitness. Everything here is pure: no data, no I/O.
"""

from __future__ import annotations

import copy
import hashlib
import json
import random

UNIVERSES = {"top": {"n": [10, 20, 30, 50]}, "core": {}, "alpaca": {}}
SIGNALS = {
    "mom": {"lb": [7, 14, 28, 56, 90]},
    "donchian": {"n": [10, 20, 30, 55, 100], "exit": [0.5, 0.33]},
    "ma": {"fast": [5, 10, 20, 50], "slow": [50, 100, 200]},
    "rev": {"lb": [3, 7]},
    "lowvol": {},
}
FILTERS = {
    "regime": {"ma": [100, 200]},
    "btcmom": {"lb": [28, 56]},
    "vol": {"max": [0.8, 1.2, 1.6]},
    "volume": {"slow": [28, 56], "min": [1.0, 1.2]},
    "trend": {"ma": [50, 100, 200]},
}
SELECT = {"k": [3, 5, 10, 20], "rank": ["signal", "liquidity", "lowvol"]}
WEIGHT = {"scheme": ["equal", "invvol"], "fill": ["slots", "full"]}
REBALANCE = {"every": [1, 3, 7], "tranches": [1, 7], "band": [0.0, 0.25, 0.5]}
MAX_FILTERS = 3
MAX_COMPLEXITY = 7
PARTS = ("universe", "signal", "filters", "select", "weight", "rebalance")


class GenomeError(ValueError):
    """A genome outside the grammar."""


def _pick(rng: random.Random, space: dict) -> dict:
    return {k: rng.choice(v) for k, v in space.items()}


def random_genome(rng: random.Random) -> dict:
    """A uniformly drawn valid genome (redrawn until it fits the bounds)."""
    while True:
        u = rng.choice(list(UNIVERSES))
        s = rng.choice(list(SIGNALS))
        n_f = rng.choice([0, 0, 1, 1, 2, 3])
        kinds = rng.sample(list(FILTERS), n_f)
        g = {
            "universe": {"kind": u, **_pick(rng, UNIVERSES[u])},
            "signal": {"kind": s, **_pick(rng, SIGNALS[s])},
            "filters": [{"kind": k, **_pick(rng, FILTERS[k])} for k in kinds],
            "select": _pick(rng, SELECT),
            "weight": _pick(rng, WEIGHT),
            "rebalance": _pick(rng, REBALANCE),
        }
        g = canonical(_repair(g))
        if valid(g)[0]:
            return g


def _repair(g: dict) -> dict:
    """Small fixes that keep a draw or a mutation inside the grammar."""
    s = g["signal"]
    if g["rebalance"]["every"] != 7:
        g["rebalance"]["tranches"] = 1
    if s["kind"] == "ma" and s["fast"] >= s["slow"]:
        s["fast"] = max(f for f in SIGNALS["ma"]["fast"] if f < s["slow"])
    if g["universe"]["kind"] != "top":
        g["universe"].pop("n", None)
        size = 20 if g["universe"]["kind"] == "core" else 15
        if g["select"]["k"] > size:
            g["select"]["k"] = 10
    return g


def canonical(g: dict) -> dict:
    """Filters sorted by kind, keys in a fixed order: one genome, one text."""
    g = copy.deepcopy(g)
    g["filters"] = sorted(g["filters"], key=lambda f: f["kind"])
    return {k: g[k] for k in PARTS}


def key(g: dict) -> str:
    """Stable 12-character id of a genome."""
    text = json.dumps(canonical(g), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def complexity(g: dict) -> int:
    return (1 + len(g["filters"]) + (g["weight"]["scheme"] == "invvol") + (g["rebalance"]["band"] > 0)
            + (g["rebalance"]["every"] > 1) + (g["rebalance"]["tranches"] > 1) + (g["select"]["rank"] != "signal"))


def valid(g: dict) -> tuple[bool, str]:
    """(ok, why not). Checks every part against the grammar and the bounds."""
    try:
        if list(g) != list(PARTS):
            return False, "parts missing or out of order"
        u, s = g["universe"], g["signal"]
        if u["kind"] not in UNIVERSES or set(u) - {"kind"} != set(UNIVERSES[u["kind"]]):
            return False, f"universe {u}"
        if any(u[k] not in v for k, v in UNIVERSES[u["kind"]].items()):
            return False, f"universe {u}"
        if s["kind"] not in SIGNALS or set(s) - {"kind"} != set(SIGNALS[s["kind"]]):
            return False, f"signal {s}"
        if any(s[k] not in v for k, v in SIGNALS[s["kind"]].items()):
            return False, f"signal {s}"
        if s["kind"] == "ma" and s["fast"] >= s["slow"]:
            return False, "ma fast must be below slow"
        kinds = [f["kind"] for f in g["filters"]]
        if len(kinds) > MAX_FILTERS or len(set(kinds)) != len(kinds):
            return False, "too many or repeated filters"
        for f in g["filters"]:
            if f["kind"] not in FILTERS or set(f) - {"kind"} != set(FILTERS[f["kind"]]):
                return False, f"filter {f}"
            if any(f[k] not in v for k, v in FILTERS[f["kind"]].items()):
                return False, f"filter {f}"
        for part, space in (("select", SELECT), ("weight", WEIGHT), ("rebalance", REBALANCE)):
            if set(g[part]) != set(space) or any(g[part][k] not in v for k, v in space.items()):
                return False, f"{part} {g[part]}"
        if g["rebalance"]["tranches"] > 1 and g["rebalance"]["every"] != 7:
            return False, "tranches only for a weekly book"
        if u["kind"] != "top" and g["select"]["k"] > (20 if u["kind"] == "core" else 15):
            return False, "K larger than the list"
        if complexity(g) > MAX_COMPLEXITY:
            return False, f"complexity {complexity(g)} above {MAX_COMPLEXITY}"
    except (KeyError, TypeError, AttributeError) as e:
        return False, f"malformed ({type(e).__name__})"
    return True, ""


def mutate(g: dict, rng: random.Random, tries: int = 50) -> dict:
    """One small change: a parameter, the signal kind, or a filter added or removed."""
    for _ in range(tries):
        m = copy.deepcopy(g)
        what = rng.choice(["universe", "signal_param", "signal_kind", "filter_param", "filter_add",
                           "filter_drop", "select", "weight", "rebalance"])
        if what == "universe":
            u = rng.choice(list(UNIVERSES))
            m["universe"] = {"kind": u, **_pick(rng, UNIVERSES[u])}
        elif what == "signal_kind":
            s = rng.choice([k for k in SIGNALS if k != m["signal"]["kind"]])
            m["signal"] = {"kind": s, **_pick(rng, SIGNALS[s])}
        elif what == "signal_param":
            space = SIGNALS[m["signal"]["kind"]]
            if not space:
                continue
            p = rng.choice(list(space))
            m["signal"][p] = rng.choice(space[p])
        elif what == "filter_param":
            if not m["filters"]:
                continue
            f = rng.choice(m["filters"])
            p = rng.choice(list(FILTERS[f["kind"]]))
            f[p] = rng.choice(FILTERS[f["kind"]][p])
        elif what == "filter_add":
            free = [k for k in FILTERS if k not in {f["kind"] for f in m["filters"]}]
            if not free or len(m["filters"]) >= MAX_FILTERS:
                continue
            k = rng.choice(free)
            m["filters"].append({"kind": k, **_pick(rng, FILTERS[k])})
        elif what == "filter_drop":
            if not m["filters"]:
                continue
            m["filters"].pop(rng.randrange(len(m["filters"])))
        else:
            space = {"select": SELECT, "weight": WEIGHT, "rebalance": REBALANCE}[what]
            p = rng.choice(list(space))
            m[what][p] = rng.choice(space[p])
        m = canonical(_repair(m))
        if valid(m)[0] and key(m) != key(g):
            return m
    return random_genome(rng)


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    """Each part from one parent or the other."""
    for _ in range(20):
        c = {p: copy.deepcopy(rng.choice((a, b))[p]) for p in PARTS}
        c = canonical(_repair(c))
        if valid(c)[0]:
            return c
    return copy.deepcopy(a)


def describe(g: dict) -> str:
    """One line a person can read, e.g. "mom 28 · top 20 · regime 200 · top 10 by signal · equal slots · daily"."""
    u, s = g["universe"], g["signal"]
    uni = f"top {u['n']}" if u["kind"] == "top" else {"core": "core 20", "alpaca": "Alpaca 15"}[u["kind"]]
    sig = {"mom": lambda: f"mom {s['lb']}d", "rev": lambda: f"reversal {s['lb']}d",
           "donchian": lambda: f"Donchian {s['n']}/{max(2, round(s['n'] * s['exit']))}",
           "ma": lambda: f"MA {s['fast']}/{s['slow']}", "lowvol": lambda: "low vol"}[s["kind"]]()
    fl = []
    for f in g["filters"]:
        fl.append({"regime": lambda: f"BTC > MA{f['ma']}", "btcmom": lambda: f"BTC {f['lb']}d up",
                   "vol": lambda: f"vol < {int(f['max'] * 100)} %",
                   "volume": lambda: f"volume 7/{f['slow']} >= {f['min']:g}",
                   "trend": lambda: f"coin > MA{f['ma']}"}[f["kind"]]())
    sel, w, r = g["select"], g["weight"], g["rebalance"]
    cad = {1: "daily", 3: "every 3d", 7: "weekly"}[r["every"]] + (" in 7 tranches" if r["tranches"] > 1 else "")
    band = f" band {int(r['band'] * 100)} %" if r["band"] else ""
    parts = [sig, uni] + fl + [f"best {sel['k']} by {sel['rank']}", f"{w['scheme']} {w['fill']}", cad + band]
    return " · ".join(parts)
