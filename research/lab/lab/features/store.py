"""The feature cache: the hourly tables of the recorded data as Parquet partitions, one per group and UTC day.

  <data>/features/<group>/date=YYYY-MM-DD/hourly.parquet
  <data>/features/<group>/_built.json      date -> signature of the raw files it was built from
  <data>/features/coverage.json            per feature: from when, until when, assets, gap days

A day is (re)built when it has no partition yet or its raw files changed (today's parts compacted into
day.parquet, a late part). Only finished days are written; today is computed from the raw rows when asked.
A day whose raw files the recorder's retention has removed keeps its partition, so the features outlive
the raw books. Nothing here deletes raw data. Reads look in the write folder first (PYTHIA_WRITE_ROOT) and
then in the data folder's, so a read-only copy of the lab's cache is used as it is.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

from .. import data

ROOT = data.ROOT                         # the recorder's tables, read only
OUT = data.WRITE_ROOT / "features"       # where the cache is written
BUILDERS: dict[str, tuple] = {}          # group -> (raw sources, date -> hourly rows), filled by micro.py


def cache_dirs() -> list[Path]:
    return list(dict.fromkeys([OUT, ROOT / "features"]))


def raw_files(source: str, date: str) -> list[Path]:
    """A day's files: the compacted day.parquet when it exists, else the parts written so far."""
    d = ROOT / source / f"date={date}"
    day = d / "day.parquet"
    return [day] if day.exists() else sorted(d.glob("part-*.parquet"))


def read_raw(source: str, date: str, columns: list[str]) -> pl.DataFrame:
    files = raw_files(source, date)
    if not files:
        return pl.DataFrame()
    return pl.concat([pl.read_parquet(f, columns=columns) for f in files], how="vertical_relaxed")


def raw_dates(sources) -> set[str]:
    out = set()
    for s in sources:
        d = ROOT / s
        if d.is_dir():
            out |= {p.name.removeprefix("date=") for p in d.glob("date=*") if any(p.glob("*.parquet"))}
    return out


def signature(sources, date: str) -> str | None:
    """Names, sizes and modification times of a day's raw files; None when there are none."""
    files = [f for s in sources for f in raw_files(s, date)]
    if not files:
        return None
    text = "|".join(f"{f.parent.parent.name}/{f.name}:{f.stat().st_size}:{f.stat().st_mtime_ns}" for f in files)
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _built(d: Path, group: str) -> dict:
    try:
        return json.loads((d / group / "_built.json").read_text())
    except (OSError, ValueError):
        return {}


def cached(group: str) -> dict[str, tuple[Path, str]]:
    """date -> (partition, signature) over the cache folders, the write folder first."""
    out: dict[str, tuple[Path, str]] = {}
    for d in cache_dirs():
        sigs = _built(d, group)
        for p in sorted((d / group).glob("date=*/hourly.parquet")):
            day = p.parent.name.removeprefix("date=")
            out.setdefault(day, (p, sigs.get(day, "")))
    return out


def hourly(group: str) -> pl.DataFrame:
    """A cached group's hourly rows over every day there is: the partition where it is current, else
    built from the raw rows now (not written)."""
    sources, build_day = BUILDERS[group]
    have = cached(group)
    parts = []
    for day in sorted(raw_dates(sources) | set(have)):
        sig = signature(sources, day)
        if day in have and (sig is None or have[day][1] == sig):
            parts.append(pl.read_parquet(have[day][0]))
        elif sig is not None:
            parts.append(build_day(day))
    parts = [p for p in parts if p.height]
    return pl.concat(parts, how="diagonal_relaxed") if parts else pl.DataFrame(
        schema={"ts_us": pl.Int64, "asset": pl.String})


def today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def build(groups=None, until: str | None = None, log=print) -> dict:
    """Write every finished day (before `until`, default today UTC) that has no current partition in the
    write folder. Returns {group: {"built": n, "kept": n}}."""
    until = until or today()
    out = {}
    for g in groups or list(BUILDERS):
        sources, build_day = BUILDERS[g]
        sigs = _built(OUT, g)
        n = kept = 0
        for day in sorted(raw_dates(sources)):
            if day >= until:
                continue
            sig = signature(sources, day)
            p = OUT / g / f"date={day}" / "hourly.parquet"
            if sig is None or (p.exists() and sigs.get(day) == sig):
                kept += 1
                continue
            h = build_day(day)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            h.write_parquet(tmp, compression="zstd")
            os.replace(tmp, p)
            sigs[day] = sig
            _write_json(OUT / g / "_built.json", sigs)
            n += 1
            log(f"  {g} {day}: {h.height} rows")
        out[g] = {"built": n, "kept": kept}
    return out


def _write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1, sort_keys=True))
    os.replace(tmp, path)


def write_coverage(cov: dict) -> Path:
    p = OUT / "coverage.json"
    _write_json(p, cov)
    return p


def read_coverage() -> dict:
    for d in cache_dirs():
        try:
            return json.loads((d / "coverage.json").read_text())
        except (OSError, ValueError):
            continue
    return {}
