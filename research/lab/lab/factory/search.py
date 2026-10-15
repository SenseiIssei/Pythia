"""The search: random draws plus mutation and crossover of the best, on the in-sample window only.

A run has a fixed budget of NEW genomes (default BUDGET). A genome already in
the ledger is not evaluated again and does not use budget; it is not a new
trial. The first part of the budget is random (all of it on the first run,
when there is nothing to breed from), the rest breeds from the elite: the best
ELITE genomes by fitness among everything ever tried plus this run so far,
picked by tournament, mutated, sometimes crossed first. Every evaluation is a
trial in the ledger. The random generator is seeded from the run id, so a run
can be repeated exactly on the same ledger and panel.
"""

from __future__ import annotations

import hashlib
import random
import time

from . import build, evaluate, grammar

BUDGET = 300
RANDOM_SHARE = 0.35
ELITE = 20
TOURNAMENT = 3
CROSSOVER = 0.3
MAX_ATTEMPTS_PER_SLOT = 25


def seed_of(run_id: str, n_ledger: int) -> int:
    return int(hashlib.sha1(f"{run_id}/{n_ledger}".encode()).hexdigest()[:12], 16)


def search(c: build.Ctx, tried: set[str], elite_rows: list[dict], run_id: str, budget: int = BUDGET,
           seed: int | None = None, log=print) -> dict:
    """Evaluate `budget` new genomes. `tried`: keys already in the ledger; `elite_rows`: their best rows.

    Returns {"rows": in-sample rows of the new genomes, "origin": counts by how each was made,
    "duplicates": proposals skipped because they had been tried, "seconds": wall time}.
    """
    rng = random.Random(seed if seed is not None else seed_of(run_id, len(tried)))
    t0 = time.time()
    rows: list[dict] = []
    seen = set(tried)
    origin = {"random": 0, "mutation": 0, "crossover": 0}
    dup = 0
    n_random = budget if not elite_rows else max(1, int(budget * RANDOM_SHARE))

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
        if len(rows) % 50 == 0:
            best = max(rows, key=lambda x: x["fitness"])
            log(f"  {len(rows)}/{budget} evaluated, best fitness {best['fitness']:.2f} ({best['name']}), "
                f"{time.time() - t0:.0f} s")
        return True

    attempts = 0
    while len(rows) < n_random and attempts < budget * MAX_ATTEMPTS_PER_SLOT:
        attempts += 1
        evaluate_new(grammar.random_genome(rng), "random")
    while len(rows) < budget and attempts < budget * MAX_ATTEMPTS_PER_SLOT:
        attempts += 1
        pool = sorted(elite_rows + rows, key=lambda r: r["fitness"], reverse=True)[:ELITE]
        a = _tournament(pool, rng)
        if rng.random() < CROSSOVER and len(pool) > 1:
            b = _tournament(pool, rng)
            child = grammar.crossover(a["genome"], b["genome"], rng)
            if rng.random() < 0.5 or grammar.key(child) in seen:
                child = grammar.mutate(child, rng)
            evaluate_new(child, "crossover")
        else:
            evaluate_new(grammar.mutate(a["genome"], rng), "mutation")
    return {"rows": rows, "origin": origin, "duplicates": dup, "seconds": time.time() - t0}


def _tournament(pool: list[dict], rng: random.Random) -> dict:
    pick = rng.sample(pool, min(TOURNAMENT, len(pool)))
    return max(pick, key=lambda r: r["fitness"])
