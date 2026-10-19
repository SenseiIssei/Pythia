"""Shadow score: M2 averaged with low volatility (X9 e). Off by default; it never trades.

X9 (results/model_review.md) found, as pre-registered, that the mean of M2's
daily percentile rank and the low-volatility rank (minus the 30-day realised
vol) ranks coins better than M2 alone out of sample: rank IC 0.158 against
0.149 on 7-day returns from 2024, Newey-West t of the difference 3.13, better
in 2024, 2025 and 2026, and a weaker bottom decile. That is a ranking result,
not money: no book uses it.

Switched on with PYTHIA_M2_LOWVOL_SHADOW=1 in the environment of the
market-neutral M2 paper book (`python -m lab.paper.picks_ls`). On every
rebalance day it then writes down, before the outcome is known, both rankings
of the day's coins (M2 alone and the average with M2's own vol28 input, the
28-day realised vol), and scores every earlier entry whose 7 days have
passed: the rank IC of each against the realised 7-day return, per week and
overall. The book itself is untouched either way.

Files, next to the book's journal: shadow_m2_lowvol.jsonl (one line per
scored day, written before the outcome) and shadow_m2_lowvol.json (the
scores so far).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl

ENV = "PYTHIA_M2_LOWVOL_SHADOW"
HORIZON_D = 7
DAY_US = 86_400_000_000


def enabled() -> bool:
    return os.environ.get(ENV, "").strip().lower() in ("1", "true", "yes", "on")


def pct(x: np.ndarray) -> np.ndarray:
    """Percentile ranks 0 to 1 (ties averaged); NaN stays NaN."""
    out = np.full(len(x), np.nan)
    ok = np.isfinite(x)
    if ok.sum() > 1:
        r = pl.Series(x[ok]).rank("average").to_numpy()
        out[ok] = (r - 1) / (ok.sum() - 1)
    return out


def rankings(symbols: list[str], m2_score: np.ndarray, vol28: np.ndarray) -> dict[str, list[float]]:
    """{symbol: [M2 percentile, ensemble percentile]} for one day. The ensemble is the
    mean of M2's percentile and the low-vol percentile (low vol ranks high)."""
    m = pct(np.asarray(m2_score, float))
    lv = pct(-np.asarray(vol28, float))
    ens = pct(np.where(np.isfinite(m) & np.isfinite(lv), (m + lv) / 2, np.nan))
    return {s: [float(a), float(b)] for s, a, b in zip(symbols, m, ens) if np.isfinite(a) and np.isfinite(b)}


def spearman(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 10:
        return float("nan")
    ra = pl.Series(a[ok]).rank("average").to_numpy()
    rb = pl.Series(b[ok]).rank("average").to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def record(folder: Path, day_us: int, ranks: dict[str, list[float]], now_ms: int) -> None:
    """Append the day's rankings unless that day is already recorded."""
    f = folder / "shadow_m2_lowvol.jsonl"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("day_us") == day_us:
                    return
            except ValueError:
                continue
    with f.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"day_us": int(day_us), "recorded_ms": int(now_ms), "ranks": ranks}) + "\n")


def score(folder: Path, realised: pl.DataFrame) -> dict:
    """Score every recorded day whose label is known. `realised`: (day, symbol, fwd)
    with fwd the 7-day log return from that day's close, symbols as recorded."""
    f = folder / "shadow_m2_lowvol.jsonl"
    rows = []
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    fwd = {(int(d), str(s)): float(v) for d, s, v in realised.select("day", "symbol", "fwd").iter_rows()
           if v is not None and np.isfinite(v)}
    days = []
    for r in rows:
        syms = [s for s in r["ranks"] if (r["day_us"], s) in fwd]
        if len(syms) < 10:
            continue
        y = np.array([fwd[(r["day_us"], s)] for s in syms])
        m = np.array([r["ranks"][s][0] for s in syms])
        e = np.array([r["ranks"][s][1] for s in syms])
        days.append({"day": datetime.fromtimestamp(r["day_us"] / 1e6, timezone.utc).strftime("%Y-%m-%d"),
                     "coins": len(syms), "ic_m2": spearman(m, y), "ic_ensemble": spearman(e, y)})
    out = {"what": "rank IC on the realised 7-day return, M2 alone against M2 averaged with low vol",
           "recorded_days": len(rows), "scored_days": len(days), "days": days}
    if days:
        a = np.array([d["ic_m2"] for d in days])
        b = np.array([d["ic_ensemble"] for d in days])
        out.update(mean_ic_m2=float(np.nanmean(a)), mean_ic_ensemble=float(np.nanmean(b)),
                   ensemble_better_share=float(np.mean(b > a)))
    (folder / "shadow_m2_lowvol.json").write_text(json.dumps(out, indent=1), encoding="utf-8", newline="\n")
    return out
