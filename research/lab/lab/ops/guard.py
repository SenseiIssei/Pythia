"""Guardrails of the learning loop: what it may write, read and change.

The loop updates evidence, costs and models. It must never change a live
setting, arm live trading, move money or raise a risk limit. Three rules
enforce that in code rather than by convention:

  1. Writes go through `write_text` / `write_json` / `copy_tree`, which refuse
     any path outside the allowlist (the loop's own folders, the learned cost
     file, the model registry and the published model folders). The engine's
     state file, its settings, the vault and the paper books are outside it.
  2. The engine is only ever read, with a plain GET of `/api/state` or from
     an exported file. `read_only_url` refuses anything else.
  3. A learned cost table must keep every venue fact of the base table (fees,
     borrow, minimum notional, depth) and may move a measured symbol's spread
     and impact only inside fixed bounds (`cost_violations`).

Every path written is recorded in `WRITTEN`, which the digest lists.
"""

from __future__ import annotations

import json
import math
import os
import shutil
from pathlib import Path
from urllib.parse import urlparse

from .. import report
from ..data import ROOT

# Cost fields the loop may change, per symbol, and the range a value must stay in.
COST_BOUNDS = {"halfSpreadBps": (0.05, 50.0), "impactCoeff": (0.1, 100.0)}
# Never more than this factor away from the base table's value in one go.
COST_MAX_FACTOR = 4.0

WRITTEN: list[str] = []

# The model zoo's own published folders (lab.models); a new zoo model is added here on purpose.
ZOO_MODELS = ("m8_direction", "m8_quantiles", "m8_upper", "m10_vol_regime", "m11_slippage", "m12_cross_asset")


class GuardError(RuntimeError):
    """The loop tried something it must not do."""


def allowed_roots() -> list[Path]:
    models = ROOT / "models"
    out = Path(os.environ.get("PYTHIA_AGENT_OUT", str(ROOT / "agent-strategies")))
    return [
        ROOT / "learn",
        report.REPORTS / "learn",
        # The real money readiness check (lab.ops.readiness): its record and its report.
        ROOT / "readiness",
        report.REPORTS / "readiness",
        ROOT / "costs" / "learned.json",
        ROOT / "costs" / "learned.json.tmp",
        models / "registry",
        models / "vol_1h",
        models / "picks_7d",
        # The model zoo: its state and shadow records, its report, its published models.
        models / "zoo",
        report.REPORTS / "models",
        *(models / n for n in ZOO_MODELS),
        # The sweep's published reports and run caches (a monthly gate refresh), never its panel cache.
        out / "reports",
        out / "runs",
    ]


def check_write(path: Path) -> Path:
    p = Path(os.path.abspath(path))
    for root in allowed_roots():
        r = Path(os.path.abspath(root))
        if p == r or r in p.parents:
            return p
    raise GuardError(f"refusing to write {p}: outside what the learning loop may touch")


def write_text(path: Path, text: str) -> Path:
    """Write atomically (temp file, then rename) inside the allowlist."""
    p = check_write(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)
    WRITTEN.append(str(p))
    return p


def write_json(path: Path, data) -> Path:
    return write_text(path, json.dumps(finite(data), indent=2, default=str, allow_nan=False))


def append_jsonl(path: Path, rows: list[dict]) -> Path:
    p = check_write(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(finite(r), default=str, allow_nan=False) + "\n")
    WRITTEN.append(str(p))
    return p


def copy_tree(src: Path, dst: Path, skip: tuple[str, ...] = ()) -> Path:
    """Copy a model folder to its published place. Never overwrites an existing version."""
    d = check_write(dst)
    if d.exists():
        raise GuardError(f"refusing to overwrite {d}")
    shutil.copytree(src, d, ignore=shutil.ignore_patterns(*skip) if skip else None)
    WRITTEN.append(str(d))
    return d


def copy_file(src: Path, dst: Path) -> Path:
    d = check_write(dst)
    d.parent.mkdir(parents=True, exist_ok=True)
    tmp = d.with_name(d.name + ".tmp")
    shutil.copyfile(src, tmp)
    os.replace(tmp, d)
    WRITTEN.append(str(d))
    return d


def read_only_url(url: str) -> str:
    """The engine is read through GET /api/state and nothing else."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.path.rstrip("/").endswith("/api/state") or u.query:
        raise GuardError(f"refusing to call {url}: the loop only reads the engine's /api/state")
    return url


def finite(v):
    """NaN and infinity become null: the engine parses these files as strict JSON."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: finite(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [finite(x) for x in v]
    return v


def cost_violations(base: dict, learned: dict) -> list[str]:
    """Everything wrong with a learned cost table against the base one; empty means it may be written.

    The learned table must have the same venues, the same venue-level model and
    the same per-symbol fields as the base, except halfSpreadBps and
    impactCoeff of a symbol, which must be finite, inside COST_BOUNDS and
    within COST_MAX_FACTOR of what the base table resolves for that symbol.
    """
    out = []
    bv, lv = base.get("venues", {}), learned.get("venues", {})
    if set(bv) != set(lv):
        out.append(f"venues differ: {sorted(set(bv) ^ set(lv))}")
    for name in set(bv) & set(lv):
        b, l = bv[name], lv[name]
        for k, v in b.items():
            if k != "symbols" and l.get(k) != v:
                out.append(f"{name}.{k} changed from {v} to {l.get(k)}")
        for k in l:
            if k not in b:
                out.append(f"{name}.{k} added")
        bs, ls = b.get("symbols", {}), l.get("symbols", {})
        for sym, ov in ls.items():
            if sym not in bs:
                out.append(f"{name}/{sym} added: the loop only adjusts symbols the base table lists")
                continue
            base_ov = bs[sym]
            for f, v in ov.items():
                if f in COST_BOUNDS:
                    lo, hi = COST_BOUNDS[f]
                    ref = base_ov.get(f, b.get(f))
                    if not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi:
                        out.append(f"{name}/{sym}.{f} = {v} outside [{lo}, {hi}]")
                    elif ref and not (ref / COST_MAX_FACTOR <= v <= ref * COST_MAX_FACTOR):
                        out.append(f"{name}/{sym}.{f} = {v} more than {COST_MAX_FACTOR:g}x from {ref}")
                elif base_ov.get(f) != v:
                    out.append(f"{name}/{sym}.{f} changed from {base_ov.get(f)} to {v}: not a field the loop may set")
        for sym in bs:
            if sym not in ls:
                out.append(f"{name}/{sym} removed")
    return out
