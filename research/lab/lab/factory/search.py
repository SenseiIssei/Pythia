"""The search: random draws plus mutation and crossover of the best, on the in-sample window only.

A run has a fixed budget of NEW genomes (default BUDGET). A genome already in
the ledger is not evaluated again and does not use budget; it is not a new
trial. The first part of the budget is random (RANDOM_SHARE of it, or
FIRST_RANDOM_SHARE on the first run, when the ledger has nothing to breed from
yet), the rest breeds from the elite: the best
ELITE genomes by fitness among everything ever tried plus this run so far,
picked by tournament, mutated, sometimes crossed first. Every evaluation is a
trial in the ledger. The random generator is seeded from the run id, so a run
can be repeated exactly on the same ledger and panel.

Since G1 a share of the budget (TREE_SHARE, PYTHIA_FACTORY_TREE_SHARE) goes to
genomes with an expression tree (grammar.py), the rest to the old families; the
two kinds take turns slot by slot and each breeds from its own elite (a tree slot
from the best tree genomes, a family slot from the best family genomes, with the
families' moves only), so the trees do not crowd the families out. Both
modes (this weekly one and small.py) read the same share.
"""

from __future__ import annotations

import hashlib
import os
import random
import time

from . import build, evaluate, grammar

BUDGET = 300
RANDOM_SHARE = 0.35
FIRST_RANDOM_SHARE = 0.5
ELITE = 20
TOURNAMENT = 3
CROSSOVER = 0.3
MAX_ATTEMPTS_PER_SLOT = 25
TREE_SHARE = 0.30


def tree_share() -> float:
    """The share of a run's budget for tree genomes, 0 to 1 (PYTHIA_FACTORY_TREE_SHARE, else TREE_SHARE)."""
    try:
        x = float(os.environ.get("PYTHIA_FACTORY_TREE_SHARE", TREE_SHARE))
    except ValueError:
        x = TREE_SHARE
    return min(max(x, 0.0), 1.0) if x == x else TREE_SHARE


def tree_turn(n_trees: int, n_done: int, share: float) -> bool:
    """Is the next slot a tree slot? Keeps the trees at `share` of the slots so far, slot by slot."""
    return n_trees < round(share * (n_done + 1))


def seed_of(run_id: str, n_ledger: int) -> int:
    return int(hashlib.sha1(f"{run_id}/{n_ledger}".encode()).hexdigest()[:12], 16)


def search(c: build.Ctx, tried: set[str], elite_rows: list[dict], run_id: str, budget: int = BUDGET,
           seed: int | None = None, log=print, share: float | None = None) -> dict:
    """Evaluate `budget` new genomes. `tried`: keys already in the ledger; `elite_rows`: their best rows
    (the best of both kinds); `share`: of the budget for tree genomes (default tree_share()).

    Returns {"rows": in-sample rows of the new genomes, "origin": counts by how each was made,
    "trees": how many of them have a tree, "duplicates": proposals skipped because they had been
    tried, "seconds": wall time}.
    """
    share = tree_share() if share is None else share
    rng = random.Random(seed if seed is not None else seed_of(run_id, len(tried)))
    t0 = time.time()
    rows: list[dict] = []
    seen = set(tried)
    origin = {"random": 0, "mutation": 0, "crossover": 0}
    dup = 0
    n_random = max(1, int(budget * (RANDOM_SHARE if elite_rows else FIRST_RANDOM_SHARE)))

    def evaluate_new(g: dict, how: str) -> bool:
        nonlocal dup
        k = grammar.key(g)
        if k in seen:
            dup += 1
            return False
        seen.add(k)
        r = evaluate.in_sample(c, g, run_id)
        r["origin"] = how
        rows.append(r)
        origin[how] += 1
        n_trees[0] += grammar.has_tree(g)
        if len(rows) % 50 == 0:
            best = max(rows, key=lambda x: x["fitness"])
            log(f"  {len(rows)}/{budget} evaluated, best fitness {best['fitness']:.2f} ({best['name']}), "
                f"{time.time() - t0:.0f} s")
        return True

    n_trees = [0]
    attempts = 0
    while len(rows) < n_random and attempts < budget * MAX_ATTEMPTS_PER_SLOT:
        attempts += 1
        tree = tree_turn(n_trees[0], len(rows), share)
        evaluate_new(grammar.random_tree_genome(rng) if tree else grammar.random_genome(rng), "random")
    while len(rows) < budget and attempts < budget * MAX_ATTEMPTS_PER_SLOT:
        attempts += 1
        tree = tree_turn(n_trees[0], len(rows), share)
        pool = sorted((r for r in elite_rows + rows if grammar.has_tree(r["genome"]) == tree),
                      key=lambda r: r["fitness"], reverse=True)[:ELITE]
        if not pool:
            evaluate_new(grammar.random_tree_genome(rng) if tree else grammar.random_genome(rng), "random")
            continue
        a = _tournament(pool, rng)
        if rng.random() < CROSSOVER and len(pool) > 1:
            b = _tournament(pool, rng)
            child = grammar.crossover(a["genome"], b["genome"], rng)
            if rng.random() < 0.5 or grammar.key(child) in seen or tree and not grammar.has_tree(child):
                child = grammar.mutate(child, rng, trees=tree)
            evaluate_new(child, "crossover")
        else:
            evaluate_new(grammar.mutate(a["genome"], rng, trees=tree), "mutation")
    return {"rows": rows, "origin": origin, "trees": n_trees[0], "duplicates": dup, "seconds": time.time() - t0}


def elite_of(rows: list[dict]) -> list[dict]:
    """The best ELITE family genomes and the best ELITE tree genomes of these rows."""
    out = []
    for tree in (False, True):
        out += sorted((r for r in rows if grammar.has_tree(r["genome"]) == tree),
                      key=lambda r: r["fitness"], reverse=True)[:ELITE]
    return out


def _tournament(pool: list[dict], rng: random.Random) -> dict:
    pick = rng.sample(pool, min(TOURNAMENT, len(pool)))
    return max(pick, key=lambda r: r["fitness"])
