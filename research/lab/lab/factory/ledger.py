"""The global trial ledger: every genome the factory ever evaluated is one trial, forever.

<data>/factory/ledger.jsonl holds one line per distinct genome (its key, the
run that first tried it, its in-sample numbers). It only grows. A genome tried
again in a later run is the same trial, not a new one, so it is not appended
twice.

The deflation pool is the lab's hand-study pool (PRIOR_TRIALS, whose variance
of trial Sharpes is backed out of the published bar, as the hand studies do)
plus every ledger line. So each factory run raises the bar for everything that
comes after it, its own candidates included: the more the factory tries, the
better a survivor has to be.

The trial Sharpes of the factory's own trials are their in-sample Sharpes at
the judging cost, winsorised at +-3 like fam_common.deflate; the out-of-sample
window is only ever seen by the few the search sends to the holdout, and those
are judged against the whole pool.
"""

from __future__ import annotations

import json
import math
import os
from contextlib import contextmanager
from pathlib import Path

import numpy as np
from scipy import stats

from ..data import ROOT
from ..experiments import fam_common as fc
from ..metrics import deflated_sharpe

try:
    import fcntl
except ImportError:          # Windows, where the first real run was made
    fcntl = None
    import msvcrt

# Every trial the hand studies counted up to alpaca_universe (C16), and the
# bar it published: the best of 377 noise trials at an annual Sharpe of 2.43.
PRIOR_TRIALS, PRIOR_SR0 = 377, 2.43
G = 0.5772156649


def factory_dir() -> Path:
    return Path(os.environ.get("PYTHIA_FACTORY_DIR", str(ROOT / "factory")))


def ledger_path() -> Path:
    return factory_dir() / "ledger.jsonl"


def seed_dir() -> Path:
    """Factory state made elsewhere and committed (results/factory_seed): the first run was
    made on the PC, and its trials must count on the server too, or the bar would start low."""
    default = Path(__file__).resolve().parents[2] / "results" / "factory_seed"
    return Path(os.environ.get("PYTHIA_FACTORY_SEED", str(default)))


def import_seed(src: Path | None = None) -> dict:
    """Merge a seed into the factory folder: ledger lines by key, holdout lines by
    (run, key), shadow books whose file is not there yet. Idempotent; never removes
    or rewrites anything already in the folder."""
    src = src or seed_dir()
    out = {"ledger": 0, "holdout": 0, "shadow": 0}
    if not src.is_dir():
        return out
    out["ledger"] = len(Ledger().add(read_jsonl(src / "ledger.jsonl")))
    hp = factory_dir() / "holdout.jsonl"
    have = {(h.get("run"), h.get("key")) for h in read_jsonl(hp)}
    new = [h for h in read_jsonl(src / "holdout.jsonl") if (h.get("run"), h.get("key")) not in have]
    append_jsonl(hp, new)
    out["holdout"] = len(new)
    sd = factory_dir() / "shadow"
    for f in sorted((src / "shadow").glob("*.json")) if (src / "shadow").is_dir() else []:
        if not (sd / f.name).exists():
            try:
                write_json(sd / f.name, json.loads(f.read_text(encoding="utf-8")))
                out["shadow"] += 1
            except ValueError:
                continue
    return out


def export_seed(dest: Path | None = None) -> dict:
    """Write this folder's ledger, holdout log and shadow books (their definitions, not
    their journals, which the server rebuilds from its own panel) as a seed."""
    dest = dest or seed_dir()
    (dest / "shadow").mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(ledger_path())
    hold = read_jsonl(factory_dir() / "holdout.jsonl")
    for name, data in (("ledger.jsonl", rows), ("holdout.jsonl", hold)):
        (dest / name).write_text("".join(json.dumps(r, separators=(",", ":"), default=float) + "\n"
                                         for r in data), encoding="utf-8")
    n = 0
    for f in sorted((factory_dir() / "shadow").glob("*.json")):
        meta = json.loads(f.read_text(encoding="utf-8"))
        if meta.get("status") == "active":
            # The seed carries the definition; the status after review is the server's own.
            write_json(dest / "shadow" / f.name, meta)
            n += 1
    return {"ledger": len(rows), "holdout": len(hold), "shadow": n}


def read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue   # a torn last line from a killed run is skipped, not fatal
    return out


def append_jsonl(p: Path, rows: list[dict]) -> None:
    if not rows:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, separators=(",", ":"), default=float) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=float), encoding="utf-8")
    os.replace(tmp, p)


def _try_lock(fh) -> bool:
    if fcntl is not None:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            return False
    try:   # Windows: lock the first byte of the file
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    if fcntl is not None:
        fcntl.flock(fh, fcntl.LOCK_UN)
    else:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


@contextmanager
def lock():
    """One factory process at a time (the weekly run and the daily shadow step share the files)."""
    p = factory_dir() / ".lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a+") as fh:
        fh.seek(0)
        if not _try_lock(fh):
            raise RuntimeError("another factory process holds the lock")
        try:
            yield
        finally:
            _unlock(fh)


class Ledger:
    def __init__(self, path: Path | None = None):
        self.path = path or ledger_path()
        self.rows = read_jsonl(self.path)
        self.by_key = {r["key"]: r for r in self.rows}

    def __contains__(self, key: str) -> bool:
        return key in self.by_key

    def __len__(self) -> int:
        return len(self.rows)

    def add(self, rows: list[dict]) -> list[dict]:
        """Append the genomes not yet in the ledger; returns what was appended."""
        new = []
        for r in rows:
            if r["key"] not in self.by_key:
                self.by_key[r["key"]] = r
                new.append(r)
        append_jsonl(self.path, new)
        self.rows += new
        return new

    def n_trials(self) -> int:
        return PRIOR_TRIALS + len(self.rows)

    def pool(self) -> dict:
        """Size, pooled variance of daily trial Sharpes, and the noise bar it implies."""
        v1, n1 = prior_var(), PRIOR_TRIALS
        x = np.array([r["is_sharpe"] for r in self.rows if r.get("is_sharpe") is not None
                      and math.isfinite(r["is_sharpe"])])
        x = np.clip(x, -fc.SR_CLIP, fc.SR_CLIP) / math.sqrt(365)
        n2, v2 = len(x), float(np.var(x)) if len(x) > 1 else 0.0
        n = n1 + n2
        v = (n1 * v1 + n2 * v2) / n
        return {"prior_trials": n1, "prior_var": v1, "factory_trials": n2, "factory_var": v2,
                "n_trials": n, "var": v, "sr0_annual": sr0(v, n) * math.sqrt(365)}


def sr0(var: float, n: int) -> float:
    """Expected best daily Sharpe of n noise trials with this variance of trial Sharpes."""
    if n <= 1:
        return 0.0
    return math.sqrt(var) * ((1 - G) * stats.norm.ppf(1 - 1 / n) + G * stats.norm.ppf(1 - 1 / (n * math.e)))


def prior_var() -> float:
    z = (1 - G) * stats.norm.ppf(1 - 1 / PRIOR_TRIALS) + G * stats.norm.ppf(1 - 1 / (PRIOR_TRIALS * math.e))
    return (PRIOR_SR0 / math.sqrt(365) / z) ** 2


def deflated(x: np.ndarray, pool: dict) -> float:
    """Deflated Sharpe p of a daily net return series against the whole pool."""
    x = x[np.isfinite(x)]
    if len(x) < 30 or x.std() == 0:
        return 0.0
    s = float(x.mean() / x.std())
    sk, ku = float(stats.skew(x)), float(stats.kurtosis(x, fisher=False))
    if 1 - sk * s + (ku - 1) / 4 * s ** 2 <= 0:
        return 0.0
    return deflated_sharpe(s, len(x), pool["n_trials"], pool["var"], sk, ku)
