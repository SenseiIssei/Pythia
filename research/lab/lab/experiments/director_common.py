"""Shared by the three studies the research director drafted on 2026-10-20 and the
owner registered together (gated_btc, genome_gates, m4_residual): the pool they
count into, the bootstrap, a panel cut at a fixed day, and the results-file writer.

The pool: since R5 the trial registry's of all (metrics.trial_pool): every hand trial
(1,377 by the results files, the 9 registered here on 2026-10-20 among them, at the
variance backed out of the published bar, 377 trials at 2.43, as every hand study since
C16), every small-account trial and every factory genome at its in-sample Sharpe; the
factory ledgers are read as they are, so a hand study never needs to write the registry.
Before R5 it was 1,115 hand trials, the factory ledger and the 9 at their own variance.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from ..metrics import deflated_sharpe, trial_pool
from . import fam_common as fc

HAND_TRIALS = 1115        # the hand count these three studies were registered with (before R5)
TODAY_TRIALS = 9          # gated_btc 4 + genome_gates 4 + m4_residual 1, in the registry's hand family
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
BOOT_DRAWS, BOOT_BLOCK, BOOT_SEED = 4000, 20, 20261020
YEAR = 365
RESULTS = Path(__file__).resolve().parents[2] / "results"


def us(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp() * 1e6)


def day_str(t_us: int) -> str:
    return datetime.fromtimestamp(int(t_us) / 1e6, timezone.utc).strftime("%Y-%m-%d")


def years_of(days_us: np.ndarray) -> np.ndarray:
    return np.array([datetime.fromtimestamp(int(d) / 1e6, timezone.utc).year for d in days_us])


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

def cut_panel(P: fc.Panel, last_day: str) -> fc.Panel:
    """The panel up to and including last_day (every (T, ...) array sliced; per-column
    arrays kept). Everything in the panel is causal, so the kept days are unchanged."""
    keep = int(np.searchsorted(P.days, us(last_day), side="right"))
    T = P.T
    kw = {}
    for f in dataclasses.fields(P):
        v = getattr(P, f.name)
        if isinstance(v, np.ndarray) and v.ndim >= 1 and v.shape[0] == T:
            kw[f.name] = v[:keep]
        else:
            kw[f.name] = v
    kw["extra"] = {k: (v[:keep] if isinstance(v, np.ndarray) and v.ndim == 2 and v.shape[0] == T else v)
                   for k, v in P.extra.items()}
    return fc.Panel(**kw)


# ---------------------------------------------------------------------------
# Measuring
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    sd = x.std() if len(x) > 1 else 0.0
    return float(x.mean() / sd * math.sqrt(YEAR)) if sd > 0 else 0.0


def perf(x: np.ndarray) -> dict:
    return fc.perf(np.asarray(x, dtype=float))


def boot_band(x: np.ndarray, y: np.ndarray | None = None, seed: int = BOOT_SEED) -> tuple[float, float, float]:
    """Stationary bootstrap (mean block BOOT_BLOCK, BOOT_DRAWS draws) of the annual
    Sharpe of x, or of Sharpe(x) - Sharpe(y) on the same resampled days.
    Returns (5 %, 95 %, share of draws above 0)."""
    rng = np.random.default_rng(seed)
    n = len(x)
    idx = np.empty((BOOT_DRAWS, n), dtype=np.int64)
    idx[:, 0] = rng.integers(0, n, BOOT_DRAWS)
    jump = rng.random((BOOT_DRAWS, n)) < 1 / BOOT_BLOCK
    fresh = rng.integers(0, n, (BOOT_DRAWS, n))
    for i in range(1, n):
        idx[:, i] = np.where(jump[:, i], fresh[:, i], (idx[:, i - 1] + 1) % n)

    def sr(a: np.ndarray) -> np.ndarray:
        s = a[idx]
        sd = s.std(1)
        return np.where(sd > 0, s.mean(1) / np.where(sd > 0, sd, 1) * math.sqrt(YEAR), 0.0)

    v = sr(np.asarray(x, dtype=float)) if y is None else sr(np.asarray(x, dtype=float)) - sr(np.asarray(y, dtype=float))
    return float(np.percentile(v, 5)), float(np.percentile(v, 95)), float((v > 0).mean())


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------

def prior_var() -> float:
    g = 0.5772156649
    z = (1 - g) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + g * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(YEAR) / z) ** 2


def factory_sharpes() -> np.ndarray:
    from .fast_maker import factory_sharpes as fs
    return fs()


def ledger_trials() -> list[dict]:
    """The factory ledgers' genomes as registry trials (the weekly seed and ledger, F2's ledger), read only."""
    from ..factory import ledger as lg
    rows = {r["key"]: r for r in lg.read_jsonl(lg.seed_dir() / "ledger.jsonl")}
    rows.update({r["key"]: r for r in lg.read_jsonl(lg.ledger_path())})
    return (lg.trial_rows(list(rows.values()), lg.Ledger.FAMILY)
            + lg.trial_rows(lg.read_jsonl(lg.small_dir() / "ledger.jsonl"), "small"))


def pool(mine_annual: list[float]) -> dict:
    """The trial registry's pool of all, the factory ledgers counted with it (each genome once, by id).
    mine_annual: this study's trial Sharpes (annual), already counted in the registry's hand family."""
    p = trial_pool(extra=ledger_trials())
    f = p["families"]
    hand = f.get("hand", {}).get("n_trials", 0)
    return {"hand_trials": hand, "factory_trials": p["n_trials"] - hand, "today_trials": TODAY_TRIALS,
            "mine": len(mine_annual), "n_total": p["n_trials"], "var": p["var"], "sr0_annual": p["sr0_annual"],
            "families": {k: x["n_trials"] for k, x in f.items()}}


def deflated(x: np.ndarray, pl_: dict) -> float:
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    sd = x.std()
    if sd == 0:
        return 0.0
    s = x.mean() / sd
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s, len(x), pl_["n_total"], pl_["var"], sk, ku)


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def marker(name: str) -> str:
    return f"<!-- generated below by lab.experiments.{name}; edit above this line only -->"


def write_results(name: str, generated: str, head: str = "") -> Path:
    """results/<name>.md: the hand-written part above the marker is kept, the rest replaced."""
    path = RESULTS / f"{name}.md"
    mk = marker(name)
    above = head
    if path.exists():
        text = path.read_text(encoding="utf-8")
        if mk in text:
            above = text.split(mk)[0].rstrip() + "\n"
    path.write_text((above.rstrip() + "\n\n" if above.strip() else "") + mk + "\n\n" + generated.rstrip() + "\n",
                    encoding="utf-8")
    return path


def table(rows: list[dict], cols: list[str], fmt: str = ".2f") -> str:
    def f(v) -> str:
        if isinstance(v, bool):
            return "yes" if v else "no"
        if isinstance(v, (int, np.integer)):
            return str(int(v))
        if isinstance(v, (float, np.floating)):
            return "n/a" if not math.isfinite(v) else format(float(v), fmt)
        return "" if v is None else str(v)
    out = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for r in rows:
        out.append("| " + " | ".join(f(r.get(c)) for c in cols) + " |")
    return "\n".join(out)
