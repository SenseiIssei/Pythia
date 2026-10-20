"""The Polymarket data folder, its files and its size budget.

  <data>/polymarket/                 (PYTHIA_PM_DIR moves it)
    resolved/markets/<YYYY-MM>.parquet   sampled resolved markets, by end month
    resolved/history/<YYYY-MM>.parquet   their YES price history (daily whole life,
                                         hourly last 14 days, 10-minute for short ones)
    resolved/strata.json                 universe counts per month, category and kind
    live/<YYYY-MM-DD>.parquet            the daily snapshot of every open market
    books/<YYYY-MM-DD>.parquet           order book depth of the candidates
    forecasts/ledger.jsonl               every Claude forecast, append only, never edited
    paper/                               the paper book (positions, fills, daily marks)
    model/                               the fitted calibration model
    state.json                           what the backfill has finished

Budget: PYTHIA_PM_BUDGET_GB (default 6). Over it, `prune` deletes whole days
of books first, then of live snapshots, oldest first and never today. The
resolved set, the forecast ledger and the paper book are never deleted.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import polars as pl

from ..data import ROOT

BUDGET_GB = float(os.environ.get("PYTHIA_PM_BUDGET_GB", "6"))


def root() -> Path:
    return Path(os.environ.get("PYTHIA_PM_DIR", str(ROOT / "polymarket")))


def path(*parts: str) -> Path:
    return root().joinpath(*parts)


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str), encoding="utf-8")
    os.replace(tmp, p)


def write_parquet(df: pl.DataFrame, p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".parquet.tmp")
    df.write_parquet(tmp, compression="zstd")
    os.replace(tmp, p)


def read_parquet(p: Path) -> pl.DataFrame | None:
    try:
        return pl.read_parquet(p) if p.exists() else None
    except Exception:
        return None


def read_all(folder: str) -> pl.DataFrame | None:
    files = sorted(path(*folder.split("/")).glob("*.parquet"))
    frames = [f for f in (read_parquet(x) for x in files) if f is not None and f.height]
    return pl.concat(frames, how="diagonal_relaxed") if frames else None


def append_jsonl(p: Path, rows: list[dict]) -> None:
    if not rows:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, default=str, sort_keys=True) + "\n")


def read_jsonl(p: Path) -> list[dict]:
    out = []
    if not p.exists():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def size_bytes(p: Path | None = None) -> int:
    p = p or root()
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.exists() else 0


def prune(budget_bytes: float | None = None, today: str | None = None) -> list[str]:
    """Delete whole days of books, then of live snapshots, oldest first, until the folder
    fits the budget. Never today, never anything else."""
    budget_bytes = BUDGET_GB * 1e9 if budget_bytes is None else budget_bytes
    total = size_bytes()
    gone = []
    for folder in ("books", "live"):
        for f in sorted(path(folder).glob("*.parquet")):
            if total <= budget_bytes:
                return gone
            if today and f.stem >= today:
                continue
            total -= f.stat().st_size
            f.unlink()
            gone.append(f"{folder}/{f.name}")
    return gone
