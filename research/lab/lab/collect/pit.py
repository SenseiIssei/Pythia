"""Point-in-time storage and data health for the free collectors of D2. Data only.

Every stored row carries three times next to its values:
  ts_us         the time the value describes (an hour or a snapshot time; a day as its 00:00 UTC)
  collected_us  when this collector got it
  known_us      when it became known: collected_us for a live row; for a row
                from a backfill the source's publication time, estimated
                conservatively per source (see each module), never earlier
  backfilled    true for rows taken from a source's history, not seen live

A feature at time t uses only rows with known_us <= t (`as_of`). Stored rows
are never replaced: the first value seen for a key wins, so a later revision
by the source cannot leak into the past.

Each run writes <lake>/<source>/health.json (the newest value of each table,
gaps in the last 7 days, the schema, errors), which `jobs.py checks` turns into
one health row per source (the `feeds` section of research/ops/jobs.yaml), so a
dead collector goes red in the morning briefing.

Lake: $PYTHIA_FREE, default $PYTHIA_DATA/free, one folder per source.
"""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import polars as pl

from ..data import ROOT

FREE = Path(os.environ.get("PYTHIA_FREE", str(ROOT / "free")))
UTC = timezone.utc
HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
UA = "pythia-lab free data collector (research; github.com/SenseiIssei/Pythia)"
PIT = ["ts_us", "collected_us", "known_us", "backfilled"]
GAP_WINDOW_US = 7 * DAY_US

Fetch = Callable[..., object]


# ---------------------------------------------------------------------------
# HTTP: GET or POST, JSON or text, 429 and 5xx retried with backoff
# ---------------------------------------------------------------------------

def request(url: str, body: dict | None = None, text: bool = False, tries: int = 5, pause: float = 0.0,
            timeout: float = 60) -> object:
    last: Exception | None = None
    data = None if body is None else json.dumps(body).encode()
    for k in range(tries):
        if pause:
            time.sleep(pause)
        headers = {"User-Agent": UA, "Accept": "text/csv" if text else "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read().decode("utf-8")
            return raw if text else json.loads(raw)
        except urllib.error.HTTPError as e:
            last = e
            if e.code != 429 and e.code < 500:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 0) or min(60.0, 2.0 ** k))
        except (OSError, http.client.HTTPException, json.JSONDecodeError) as e:
            last = e
            time.sleep(min(60.0, 2.0 ** k))
    raise RuntimeError(f"{url}: no answer after {tries} tries ({last})")


def paced(pause: float) -> Fetch:
    """fetch(url, body=None, text=False), at most one request every `pause` seconds."""
    return lambda url, body=None, text=False: request(url, body, text, pause=pause)


def now_us() -> int:
    return int(datetime.now(UTC).timestamp() * 1e6)


def us_of(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp() * 1e6)


def day_of(ts_us: int) -> date:
    return datetime.fromtimestamp(ts_us / 1e6, UTC).date()


def stamp(df: pl.DataFrame, collected: int, known: pl.Expr | int | None = None,
          backfilled: bool = False) -> pl.DataFrame:
    """Add collected_us, known_us (collected_us unless given) and backfilled."""
    k = pl.lit(collected, pl.Int64) if known is None else (pl.lit(known, pl.Int64) if isinstance(known, int)
                                                           else known.cast(pl.Int64))
    return df.with_columns(collected_us=pl.lit(collected, pl.Int64), known_us=k,
                           backfilled=pl.lit(backfilled)).with_columns(
        known_us=pl.max_horizontal("known_us", "ts_us"))


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def path(source: str, table: str) -> Path:
    return FREE / source / f"{table}.parquet"


def read(source: str, table: str) -> pl.DataFrame | None:
    p = path(source, table)
    return pl.read_parquet(p) if p.exists() else None


def append(source: str, table: str, new: pl.DataFrame, keys: list[str], dry: bool = False) -> dict:
    """Store the rows of `new` whose keys are not stored yet (the first value seen wins)."""
    old = read(source, table)
    if old is not None and not old.is_empty() and not new.is_empty():
        new = new.select(old.columns).join(old.select(keys), on=keys, how="anti")
    new = new.unique(keys, keep="first")
    out = new if old is None or old.is_empty() else (old if new.is_empty() else
                                                    pl.concat([old, new], how="vertical_relaxed"))
    out = out.sort(keys)
    if not dry and (new.height or old is None):
        p = path(source, table)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        out.write_parquet(tmp)
        os.replace(tmp, p)
    print(f"  {source}/{table}: {new.height} new, {out.height} stored", flush=True)
    return {"new": new.height, "stored": out.height}


def last_ts(source: str, table: str, by: str | None = None, value=None, live_only: bool = False) -> int | None:
    df = read(source, table)
    if df is None or df.is_empty():
        return None
    if by is not None:
        df = df.filter(pl.col(by) == value)
    if live_only:
        df = df.filter(~pl.col("backfilled"))
    return None if df.is_empty() else int(df["ts_us"].max())


def as_of(df: pl.DataFrame, t_us: int) -> pl.DataFrame:
    """The rows known at t_us."""
    return df.filter(pl.col("known_us") <= t_us)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def gaps(ts: list[int], step_us: int, now: int, weekdays_only: bool = False) -> int:
    """Missing steps in the last 7 days (from the first stored step in that window), the newest step's
    lag not counted (that is the age's job)."""
    lo = now - GAP_WINDOW_US
    have = sorted({t // step_us for t in ts if t >= lo})
    if not have:
        return 0
    n = 0
    for s in range(have[0], have[-1] + 1):
        if s in have:
            continue
        if weekdays_only and datetime.fromtimestamp(s * step_us / 1e6, UTC).weekday() >= 5:
            continue
        n += 1
    return n


def table_health(source: str, table: str, expect: list[str], step_us: int, now: int, by: str | None = None,
                 weekdays_only: bool = False) -> dict:
    """Newest value, row count, gaps and missing columns of one table (per `by` group for the gaps;
    the newest value is the oldest group's newest, so one dead group shows)."""
    df = read(source, table)
    if df is None or df.is_empty():
        return {"rows": 0, "last_ts_us": None, "gaps": 0, "missing": [], "schema_ok": True}
    missing = [c for c in expect + PIT if c not in df.columns]
    groups = [df] if by is None or by not in df.columns else [g for _, g in df.group_by(by)]
    lasts = [int(g["ts_us"].max()) for g in groups]
    gp = sum(gaps(g["ts_us"].to_list(), step_us, now, weekdays_only) for g in groups)
    return {"rows": df.height, "last_ts_us": min(lasts), "gaps": gp, "missing": missing, "schema_ok": not missing,
            "backfilled": int(df["backfilled"].sum()) if "backfilled" in df.columns else None}


def write_health(source: str, tables: dict[str, dict], errors: dict[str, str], dry: bool = False) -> dict:
    doc = {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "source": source, "tables": tables,
           "errors": errors}
    if not dry:
        p = FREE / source / "health.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, p)
    return doc


def step(errors: dict[str, str], name: str, fn: Callable[[], None]) -> None:
    """Run one part of a collector; a failure is recorded and the others go on."""
    try:
        fn()
    except Exception as e:  # one part failing does not stop the others
        errors[name] = f"{type(e).__name__}: {e}"[:300]
        print(f"  {name}: FAILED {errors[name]}", flush=True)


def exit_code(errors: dict[str, str], parts: int) -> int:
    """Every part failing is a failed job; one failing is logged, shown red by the health check and retried."""
    return 1 if errors and len(errors) >= parts else 0
