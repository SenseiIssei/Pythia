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
MAX_COMPLEXITY and costs fitness. Since G1 the signal, a coin filter or a gate may
also be an expression tree over the panel's series (see "expression trees" below),
which counts its nodes instead of 1 and is bounded by MAX_COMPLEXITY_TREES; a genome
without a tree has the same key and complexity as before, so old ledger rows stay the
same trials. Everything here is pure: no data, no I/O.
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
    """Filters sorted by kind, keys in a fixed order, trees in their canonical form: one genome, one text."""
    g = copy.deepcopy(g)
    g["filters"] = sorted(g["filters"], key=lambda f: f["kind"])
    for part in [g["signal"]] + g["filters"]:
        if isinstance(part.get("tree"), dict):
            part["tree"] = canonical_cond(part["tree"], part["cut"]) if "cut" in part else canonical_tree(part["tree"])
    return {k: g[k] for k in PARTS}


def key(g: dict) -> str:
    """Stable 12-character id of a genome."""
    text = json.dumps(canonical(g), sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(text.encode()).hexdigest()[:12]


def complexity(g: dict) -> int:
    """Moving parts; a tree counts its nodes where a family or filter counts 1."""
    trees = trees_of(g)
    return (1 + len(g["filters"]) + (g["weight"]["scheme"] == "invvol") + (g["rebalance"]["band"] > 0)
            + (g["rebalance"]["every"] > 1) + (g["rebalance"]["tranches"] > 1) + (g["select"]["rank"] != "signal")
            + sum(nodes(t) - 1 for _, t in trees))


def max_complexity(g: dict) -> int:
    return MAX_COMPLEXITY_TREES if has_tree(g) else MAX_COMPLEXITY


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
        why = valid_signal_filters(g, SIGNALS, FILTERS, MAX_FILTERS, LEAVES)
        if why:
            return False, why
        for part, space in (("select", SELECT), ("weight", WEIGHT), ("rebalance", REBALANCE)):
            if set(g[part]) != set(space) or any(g[part][k] not in v for k, v in space.items()):
                return False, f"{part} {g[part]}"
        if g["rebalance"]["tranches"] > 1 and g["rebalance"]["every"] != 7:
            return False, "tranches only for a weekly book"
        if u["kind"] != "top" and g["select"]["k"] > (20 if u["kind"] == "core" else 15):
            return False, "K larger than the list"
        if complexity(g) > max_complexity(g):
            return False, f"complexity {complexity(g)} above {max_complexity(g)}"
    except (KeyError, TypeError, AttributeError) as e:
        return False, f"malformed ({type(e).__name__})"
    return True, ""


def valid_signal_filters(g: dict, signals: dict, filters: dict, max_filters: int, leaves: tuple) -> str:
    """Why the signal and filters are outside the grammar, or "". Shared with the small-account mode."""
    s = g["signal"]
    if s["kind"] == "expr":
        if set(s) != {"kind", "tree"}:
            return f"signal {s}"
        ok, why = valid_tree(s["tree"])
        if not ok or not leaves_of(s["tree"]) <= set(leaves):
            return f"signal tree: {why or 'a series this market does not have'}"
    else:
        if s["kind"] not in signals or set(s) - {"kind"} != set(signals[s["kind"]]):
            return f"signal {s}"
        if any(s[k] not in v for k, v in signals[s["kind"]].items()):
            return f"signal {s}"
        if s["kind"] == "ma" and s["fast"] >= s["slow"]:
            return "ma fast must be below slow"
    kinds = [f["kind"] for f in g["filters"]]
    if len(kinds) > max_filters or len(set(kinds)) != len(kinds):
        return "too many or repeated filters"
    for f in g["filters"]:
        if f["kind"] in ("xfilter", "xgate"):
            if set(f) != {"kind", "tree", "cut"} or f["cut"] not in CUTS:
                return f"filter {f}"
            ok, why = valid_tree(f["tree"], market=f["kind"] == "xgate")
            if not ok or not leaves_of(f["tree"]) <= set(leaves):
                return f"{f['kind']} tree: {why or 'a series this market does not have'}"
            continue
        if f["kind"] not in filters or set(f) - {"kind"} != set(filters[f["kind"]]):
            return f"filter {f}"
        if any(f[k] not in v for k, v in filters[f["kind"]].items()):
            return f"filter {f}"
    return ""


def mutate(g: dict, rng: random.Random, tries: int = 50, trees: bool = False) -> dict:
    """One small change: a parameter, the signal kind, or a filter added or removed. With `trees` (a tree
    slot of the search) also a tree changed or a new one put in, and the child keeps at least one tree;
    without, exactly the families' moves as before G1."""
    for _ in range(tries):
        m = copy.deepcopy(g)
        moves = ["universe", "signal_param", "signal_kind", "filter_param", "filter_add",
                 "filter_drop", "select", "weight", "rebalance"]
        if trees:
            moves += ["tree"] * 4 + ["tree_new"]
        what = rng.choice(moves)
        if what in ("tree", "tree_new"):
            if not tree_move(m, rng, what == "tree_new", LEAVES, MAX_FILTERS):
                continue
        elif what == "universe":
            u = rng.choice(list(UNIVERSES))
            m["universe"] = {"kind": u, **_pick(rng, UNIVERSES[u])}
        elif what == "signal_kind":
            s = rng.choice([k for k in SIGNALS if k != m["signal"]["kind"]])
            m["signal"] = {"kind": s, **_pick(rng, SIGNALS[s])}
        elif what == "signal_param":
            space = SIGNALS.get(m["signal"]["kind"])
            if not space:
                continue
            p = rng.choice(list(space))
            m["signal"][p] = rng.choice(space[p])
        elif what == "filter_param":
            if not m["filters"]:
                continue
            f = rng.choice(m["filters"])
            if f["kind"] not in FILTERS:
                continue
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
        if valid(m)[0] and key(m) != key(g) and (has_tree(m) or not trees):
            return m
    return random_tree_genome(rng) if trees else random_genome(rng)


def tree_move(m: dict, rng: random.Random, new: bool, leaves: tuple, max_filters: int) -> bool:
    """In place: mutate one of the genome's trees (or, with `new` or none there yet, put a new tree in
    as the signal, a coin filter or a gate). False when nothing could be done. Shared with small.py."""
    have = trees_of(m)
    if have and not new:
        where, t = rng.choice(have)
        market = where == "xgate"
        kin = [x for w, x in have if x is not t and (w == "xgate") == market]
        if kin and rng.random() < 0.25:                      # a subtree from another of its own trees
            t2 = crossover_tree(t, rng.choice(kin), rng, market=market)
        else:
            t2 = mutate_tree(t, rng, leaves, market=market)
        part = m["signal"] if where == "expr" else next(f for f in m["filters"] if f["kind"] == where)
        part["tree"] = t2
        if where != "expr" and rng.random() < 0.2:
            part["cut"] = rng.choice(CUTS)
        return True
    where, part = random_tree_part(rng, leaves)
    if where == "expr":
        m["signal"] = part
        return True
    m["filters"] = [f for f in m["filters"] if f["kind"] != where]
    if len(m["filters"]) >= max_filters:
        m["filters"].pop(rng.randrange(len(m["filters"])))
    m["filters"].append(part)
    return True


def random_tree_genome(rng: random.Random) -> dict:
    """A random genome with at least one tree: a family genome with a tree put in (twice, a third of the time)."""
    while True:
        g = random_genome(rng)
        for _ in range(1 + (rng.random() < 1 / 3)):
            tree_move(g, rng, True, LEAVES, MAX_FILTERS)
        g = canonical(_repair(g))
        if valid(g)[0] and has_tree(g):
            return g


def crossover(a: dict, b: dict, rng: random.Random) -> dict:
    """Each part from one parent or the other; when both have a tree signal, half the time the child's
    signal is the two trees crossed (a subtree of one put into the other)."""
    for _ in range(20):
        c = {p: copy.deepcopy(rng.choice((a, b))[p]) for p in PARTS}
        if a["signal"].get("kind") == b["signal"].get("kind") == "expr" and rng.random() < 0.5:
            c["signal"] = {"kind": "expr", "tree": crossover_tree(a["signal"]["tree"], b["signal"]["tree"], rng)}
        c = canonical(_repair(c))
        if valid(c)[0]:
            return c
    return copy.deepcopy(a)


def describe(g: dict) -> str:
    """One line a person can read, e.g. "mom 28 · top 20 · regime 200 · top 10 by signal · equal slots · daily"."""
    u, s = g["universe"], g["signal"]
    uni = f"top {u['n']}" if u["kind"] == "top" else {"core": "core 20", "alpaca": "Alpaca 15"}[u["kind"]]
    sig = describe_signal(s)
    fl = []
    for f in g["filters"]:
        fl.append({"regime": lambda: f"BTC > MA{f['ma']}", "btcmom": lambda: f"BTC {f['lb']}d up",
                   "vol": lambda: f"vol < {int(f['max'] * 100)} %",
                   "volume": lambda: f"volume 7/{f['slow']} >= {f['min']:g}",
                   "trend": lambda: f"coin > MA{f['ma']}",
                   "xfilter": lambda: "coin " + show_cond(f["tree"], f["cut"]),
                   "xgate": lambda: "where " + show_cond(f["tree"], f["cut"])}[f["kind"]]())
    sel, w, r = g["select"], g["weight"], g["rebalance"]
    cad = {1: "daily", 3: "every 3d", 7: "weekly"}[r["every"]] + (" in 7 tranches" if r["tranches"] > 1 else "")
    band = f" band {int(r['band'] * 100)} %" if r["band"] else ""
    parts = [sig, uni] + fl + [f"best {sel['k']} by {sel['rank']}", f"{w['scheme']} {w['fill']}", cad + band]
    return " · ".join(parts)


def describe_signal(s: dict) -> str:
    if s["kind"] == "expr":
        return show_tree(s["tree"])
    return {"mom": lambda: f"mom {s['lb']}d", "rev": lambda: f"reversal {s['lb']}d",
            "donchian": lambda: f"Donchian {s['n']}/{max(2, round(s['n'] * s['exit']))}",
            "ma": lambda: f"MA {s['fast']}/{s['slow']}", "lowvol": lambda: "low vol"}[s["kind"]]()


# ---------------------------------------------------------------- expression trees (G1)
#
# Small expression trees over the panel's series, so the menu of signals is open-ended.
# A tree is plain JSON: a leaf {"op": "close"}, or an operator with its children in
# "args" and its parameter ("n" a window, "c" a clip bound). Every operator only
# reads rows up to the one it scores (build.tree_values; tests/test_factory_trees.py
# changes every bar after t and checks nothing at or before t moves).
#
#   leaves     close, volume (quote volume), range ((high - low) / close), vol
#              (annualised vol), btc (BTC's close, the same for every coin)
#   windowed   ret n     x[t] / x[t-n] - 1           (on a leaf)
#              ma n      x / its n-day average - 1   (on a leaf; "x > ma_n" when above 0)
#              z n       (x - n-day mean) / n-day sd
#   unary      rank      cross-sectional rank in (0, 1] among the coins the universe holds
#              sign, clip c (to -c..c)
#   binary     diff, ratio, min, max
#
# close, volume and btc are levels (a price, a dollar amount): they appear only inside
# ret, ma or z, which make them scale-free; range and vol are scale-free already and may
# stand anywhere but at the root. Depth is the number of operator levels (a leaf is 0),
# at most MAX_DEPTH; at most MAX_NODES nodes. A coin tree (a score or a filter) needs a coin series; a market tree
# (a gate) is made of btc alone and has no rank. A genome uses a tree as its signal
# ({"kind": "expr", "tree": ...}: every coin with a score is a candidate, the best K by
# it), as a coin filter ({"kind": "xfilter", "tree", "cut"}: score above cut) or as a
# gate ({"kind": "xgate", "tree", "cut"}: the whole book in cash unless above cut).
# complexity() counts a tree's nodes where a hand-made family counts 1.

LEAVES = ("close", "volume", "range", "vol", "btc")
MARKET_LEAVES = ("btc",)
LEVELS = ("close", "volume", "btc")          # only inside ret, ma or z
WINDOWED = ("ret", "ma", "z")
UNARY = ("rank", "sign", "clip")
BINARY = ("diff", "ratio", "min", "max")
COMMUTATIVE = ("min", "max")
WINDOWS = [3, 5, 10, 20, 50, 100, 200]
CLIPS = [0.1, 0.5, 1.0, 3.0]
CUTS = [0.0, 0.5]
MAX_DEPTH = 3
MAX_NODES = 9
MAX_COMPLEXITY_TREES = 14
TREE_KINDS = ("expr", "xfilter", "xgate")


def _arity(op: str) -> int:
    return 0 if op in LEAVES else 2 if op in BINARY else 1


def nodes(t: dict) -> int:
    return 1 + sum(nodes(a) for a in t.get("args", []))


def depth(t: dict) -> int:
    return 1 + max(depth(a) for a in t["args"]) if t.get("args") else 0


def leaves_of(t: dict) -> set[str]:
    return {t["op"]} if not t.get("args") else set().union(*(leaves_of(a) for a in t["args"]))


def tree_text(t: dict) -> str:
    return json.dumps(t, sort_keys=True, separators=(",", ":"))


def canonical_tree(t: dict) -> dict:
    """One form for equal trees: min and max with their arguments sorted, rank(rank x) and sign(sign x)
    as one, nested clips as the tighter one, a clip that cannot bite on a sign or a rank dropped."""
    op = t["op"]
    if op in LEAVES:
        return {"op": op}
    args = [canonical_tree(a) for a in t["args"]]
    if op in COMMUTATIVE:
        args.sort(key=tree_text)
    out = {"op": op, "args": args}
    if op in WINDOWED:
        out["n"] = t["n"]
    if op == "clip":
        out["c"] = t["c"]
    a = args[0]
    if op in ("rank", "sign") and a["op"] == op:
        return a
    if op == "clip" and a["op"] == "clip":
        return {"op": "clip", "args": a["args"], "c": min(out["c"], a["c"])}
    if op == "clip" and a["op"] in ("sign", "rank") and out["c"] >= 1.0:
        return a
    return out


def canonical_cond(t: dict, cut: float) -> dict:
    """A tree used as a condition (tree > cut): z_n(x) > 0 is x above its n-day average, so it is written
    as ma_n(x) > 0, one trial."""
    t = canonical_tree(t)
    if cut == 0 and t["op"] == "z" and t["args"][0]["op"] in LEAVES:
        return {"op": "ma", "args": t["args"], "n": t["n"]}
    return t


def valid_tree(t, market: bool = False) -> tuple[bool, str]:
    """(ok, why not) for a canonical tree; `market`: a gate tree (btc only, no rank)."""
    try:
        def check(x: dict) -> str:
            op = x["op"]
            if op not in LEAVES + WINDOWED + UNARY + BINARY:
                return f"unknown op {op}"
            want = {"op"} | ({"args"} if _arity(op) else set()) | ({"n"} if op in WINDOWED else set()) \
                | ({"c"} if op == "clip" else set())
            if set(x) != want:
                return f"{op}: fields {sorted(x)}"
            if op in LEAVES:
                return "" if not market or op in MARKET_LEAVES else f"leaf {op} in a market tree"
            if op not in WINDOWED and any(a["op"] in LEVELS for a in x["args"]):
                return f"{op} of a level (close, volume, btc need ret, ma or z first)"
            if op == "sign" and x["args"][0]["op"] == "rank":
                return "sign of a rank is 1"
            if len(x["args"]) != _arity(op):
                return f"{op}: {len(x['args'])} arguments"
            if op in WINDOWED and x["n"] not in WINDOWS:
                return f"{op}: window {x['n']}"
            if op == "clip" and x["c"] not in CLIPS:
                return f"clip {x['c']}"
            if op in ("ret", "ma") and x["args"][0]["op"] not in LEAVES:
                return f"{op} only on a series"
            if op == "rank" and market:
                return "rank in a market tree"
            if op in BINARY and tree_text(x["args"][0]) == tree_text(x["args"][1]):
                return f"{op} of a tree with itself"
            return next((w for w in (check(a) for a in x["args"]) if w), "")
        why = check(t)
        if why:
            return False, why
        if t["op"] in LEAVES:
            return False, "a bare series is not a signal"
        if depth(t) > MAX_DEPTH or nodes(t) > MAX_NODES:
            return False, f"depth {depth(t)} or {nodes(t)} nodes too big"
        if not market and leaves_of(t) <= set(MARKET_LEAVES):
            return False, "a coin score needs a coin series"
        if tree_text(canonical_tree(t)) != tree_text(t):
            return False, "not in canonical form"
    except (KeyError, TypeError, AttributeError, IndexError) as e:
        return False, f"malformed tree ({type(e).__name__})"
    return True, ""


def _term(rng: random.Random, room: int, leaves: tuple) -> dict:
    """A scale-free end of a tree: a window op on a series, or range or vol themselves."""
    free = [x for x in leaves if x not in LEVELS]
    if room < 1 or (free and rng.random() < 0.2):
        return {"op": rng.choice(free or list(leaves))}
    return {"op": rng.choice(WINDOWED), "n": rng.choice(WINDOWS), "args": [{"op": rng.choice(leaves)}]}


def _grow(rng: random.Random, room: int, leaves: tuple, market: bool, root: bool = False) -> dict:
    if room <= 1 or (not root and rng.random() < 0.4):
        return _term(rng, room, leaves)
    ops = ["z"] + list(BINARY + UNARY)
    if market:
        ops.remove("rank")
    op = rng.choice(ops)
    t = {"op": op, "args": [_grow(rng, room - 1, leaves, market) for _ in range(_arity(op))]}
    if op == "z":
        t["n"] = rng.choice(WINDOWS)
    if op == "clip":
        t["c"] = rng.choice(CLIPS)
    return t


def random_tree(rng: random.Random, leaves: tuple = LEAVES, market: bool = False) -> dict:
    """A random valid tree (grown, redrawn until it fits)."""
    leaves = MARKET_LEAVES if market else leaves
    while True:
        t = canonical_tree(_grow(rng, rng.choice(range(1, MAX_DEPTH + 1)), leaves, market, root=True))
        if valid_tree(t, market)[0]:
            return t


def _paths(t: dict, at: tuple = ()) -> list[tuple]:
    return [at] + [p for i, a in enumerate(t.get("args", [])) for p in _paths(a, at + (i,))]


def _get(t: dict, p: tuple) -> dict:
    for i in p:
        t = t["args"][i]
    return t


def _put(t: dict, p: tuple, sub: dict) -> dict:
    if not p:
        return copy.deepcopy(sub)
    t = copy.deepcopy(t)
    parent = _get(t, p[:-1])
    parent["args"][p[-1]] = copy.deepcopy(sub)
    return t


def mutate_tree(t: dict, rng: random.Random, leaves: tuple = LEAVES, market: bool = False, tries: int = 50) -> dict:
    """One change: a window or bound, an operator for another of its kind, a leaf, a new subtree,
    a subtree hoisted up (smaller), or a node wrapped in rank, sign, clip or z."""
    leaves = MARKET_LEAVES if market else leaves
    for _ in range(tries):
        p = rng.choice(_paths(t))
        node = copy.deepcopy(_get(t, p))
        what = rng.choice(["param", "op", "leaf", "subtree", "hoist", "wrap"])
        op = node["op"]
        if what == "param" and op in WINDOWED:
            node["n"] = rng.choice(WINDOWS)
        elif what == "param" and op == "clip":
            node["c"] = rng.choice(CLIPS)
        elif what == "op" and op in BINARY:
            node["op"] = rng.choice(BINARY)
        elif what == "op" and op in WINDOWED:
            node["op"] = rng.choice(WINDOWED)
        elif what == "op" and op in UNARY:
            new = rng.choice([u for u in UNARY if not (market and u == "rank")])
            node = {"op": new, "args": node["args"], **({"c": rng.choice(CLIPS)} if new == "clip" else {})}
        elif what == "leaf" and op in LEAVES:
            node = {"op": rng.choice(leaves)}
        elif what == "subtree":
            node = _grow(rng, MAX_DEPTH - len(p), leaves, market, root=not p)
        elif what == "hoist" and node.get("args"):
            node = copy.deepcopy(rng.choice(node["args"]))
        elif what == "wrap":
            w = rng.choice([u for u in ("rank", "sign", "clip", "z") if not (market and u == "rank")])
            node = {"op": w, "args": [node], **({"c": rng.choice(CLIPS)} if w == "clip" else {}),
                    **({"n": rng.choice(WINDOWS)} if w == "z" else {})}
        else:
            continue
        m = canonical_tree(_put(t, p, node))
        if valid_tree(m, market)[0] and tree_text(m) != tree_text(t):
            return m
    return random_tree(rng, leaves, market)


def crossover_tree(a: dict, b: dict, rng: random.Random, market: bool = False, tries: int = 20) -> dict:
    """A random subtree of a replaced by a random subtree of b."""
    for _ in range(tries):
        c = canonical_tree(_put(a, rng.choice(_paths(a)), _get(b, rng.choice(_paths(b)))))
        if valid_tree(c, market)[0]:
            return c
    return copy.deepcopy(a)


def show_tree(t: dict) -> str:
    """rank(ret_20), z_50(volume), min(ma_100, ret_5(btc)); a window op on close names no series."""
    op = t["op"]
    if op in LEAVES:
        return op
    args = [show_tree(a) for a in t["args"]]
    if op in ("ret", "ma"):
        return f"{op}_{t['n']}" + ("" if args[0] == "close" else f"({args[0]})")
    if op == "z":
        return f"z_{t['n']}" + ("" if args[0] == "close" else f"({args[0]})")
    if op == "clip":
        return f"clip({args[0]}, {t['c']:g})"
    return f"{op}({', '.join(args)})"


def show_cond(t: dict, cut: float) -> str:
    """A tree compared with its cut, ma n above 0 written as "x > ma_n": "btc > ma_100"."""
    if t["op"] == "ma" and cut == 0:
        x = t["args"][0]["op"]
        return f"{'price' if x == 'close' else x} > ma_{t['n']}"
    return f"{show_tree(t)} > {cut:g}"


def trees_of(g: dict) -> list[tuple[str, dict]]:
    """(where, tree) of every tree in a genome: "expr" for the signal, "xfilter" and "xgate" for filters."""
    out = [("expr", g["signal"]["tree"])] if g["signal"].get("kind") == "expr" else []
    return out + [(f["kind"], f["tree"]) for f in g["filters"] if f.get("kind") in ("xfilter", "xgate")]


def has_tree(g: dict) -> bool:
    return bool(trees_of(g))


def tree_nodes(g: dict) -> int:
    return sum(nodes(t) for _, t in trees_of(g))


def expression(g: dict) -> str:
    """The invented part of a genome, readable: "rank(ret_20) where btc > ma_100 and z_20(volume) > 0"."""
    s = g["signal"]
    head = show_tree(s["tree"]) if s.get("kind") == "expr" else describe_signal(s)
    conds = [("where " if f["kind"] == "xgate" else "coin ") + show_cond(f["tree"], f["cut"])
             for f in g["filters"] if f["kind"] in ("xfilter", "xgate")]
    return " ".join([head] + [c if i == 0 else "and " + c for i, c in enumerate(conds)])


def random_tree_part(rng: random.Random, leaves: tuple = LEAVES) -> tuple[str, dict]:
    """A place for a new tree and the part it makes: the signal (most often), a coin filter or a gate."""
    where = rng.choice(["expr", "expr", "expr", "xfilter", "xgate"])
    if where == "expr":
        return where, {"kind": "expr", "tree": random_tree(rng, leaves)}
    return where, {"kind": where, "tree": random_tree(rng, leaves, market=where == "xgate"),
                   "cut": rng.choice(CUTS)}
