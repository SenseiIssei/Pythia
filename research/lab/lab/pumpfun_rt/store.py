"""Compact daily partitions of the real-time pump.fun record, with a size budget.

Layout under <data>/pumpfun_rt/:

  <table>/date=YYYY-MM-DD/HHMMSS-<n>.parquet   one part per flush (every FLUSH_S seconds or
                                                 MAX_ROWS rows), zstd, sorted as received
  heartbeat.json                                 the collector's last word, every 30 s
  creators.json.gz                               the collector's creator history (live features)

Tables:

  creates  one row per token created: time (ms, as received), slot, tx (the collector's
           running transaction number), signature, mint, bonding curve, creator, name,
           symbol, metadata uri, the curve's starting reserves, mayhem and cashback flags,
           the quote mint when it is not SOL, the creator fee
  trades   every bonding curve trade: time, slot, tx, mint, side, SOL and token amounts,
           trader, the curve's virtual and real reserves after the trade, the protocol
           and creator fee in basis points, the instruction name
  amm      PumpSwap trades of pools that a token migrated into while the collector
           watched, for MIGRATED_KEEP_H hours: time, pool, mint, side, base and quote
           amounts, trader, the pool's reserves before the trade, fees
  other    curve completions, migrations (pool, SOL and tokens moved), and "gap" rows:
           a stream (program in `user`) was not connected from t0 to t, so nothing
           between is known for it
  meta     socials and description flags from a token's metadata file, when fetched

`t` is the collector's receive time in ms (UTC), `slot` the Solana slot and
`bts` the block time the program saw (seconds). Receive time is NOT event
time: the public endpoint delivers a third of the curve trades more than a
second after the first notification of their slot, a fifth more than five
seconds, and some out of slot order. Every study therefore orders by slot and
times an event by its slot (slot_times(): the earliest receive time of any
event of that slot or a later one), never by its own receive time; a late
delivery would otherwise look like a trade after our landing and hand us a
stale, better price. Trades of one transaction share the tx number, so the
creator's buy in the creation transaction is the dev buy.

Budget: when the folder grows over BUDGET_GB (PYTHIA_PF_BUDGET_GB), whole days
are deleted, oldest first, never today.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ..data import ROOT

BUDGET_GB = float(os.environ.get("PYTHIA_PF_BUDGET_GB", "40"))
FLUSH_S = 60.0
MAX_ROWS = 50_000

I64, STR, BOOL, I32 = pa.int64(), pa.string(), pa.bool_(), pa.int32()
SCHEMAS: dict[str, pa.Schema] = {
    "creates": pa.schema([("t", I64), ("slot", I64), ("tx", I64), ("sig", STR), ("mint", STR), ("bc", STR),
                          ("user", STR), ("creator", STR), ("name", STR), ("symbol", STR), ("uri", STR),
                          ("vt", I64), ("vs", I64), ("rt", I64), ("supply", I64), ("mayhem", BOOL),
                          ("cashback", BOOL), ("quote", STR), ("cfb", I32), ("bts", I64)]),
    "trades": pa.schema([("t", I64), ("slot", I64), ("tx", I64), ("mint", STR), ("buy", BOOL), ("sol", I64),
                         ("tok", I64), ("user", STR), ("vs", I64), ("vt", I64), ("rs", I64), ("rt", I64),
                         ("fb", I32), ("cfb", I32), ("ix", STR), ("quote", STR), ("bts", I64)]),
    "amm": pa.schema([("t", I64), ("slot", I64), ("tx", I64), ("pool", STR), ("mint", STR), ("buy", BOOL),
                      ("base", I64), ("quote", I64), ("user", STR), ("pb", I64), ("pq", I64), ("lpb", I32),
                      ("pfb", I32), ("cfb", I32), ("bts", I64)]),
    "other": pa.schema([("kind", STR), ("t", I64), ("slot", I64), ("tx", I64), ("mint", STR), ("user", STR),
                        ("pool", STR), ("sol", I64), ("tok", I64), ("t0", I64), ("bts", I64)]),
    "meta": pa.schema([("t", I64), ("mint", STR), ("ok", BOOL), ("twitter", BOOL), ("telegram", BOOL),
                       ("website", BOOL), ("desc_len", I32), ("image", BOOL)]),
}
I64_MAX = (1 << 63) - 1


def base() -> Path:
    return ROOT / "pumpfun_rt"


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _clean(table: str, row: dict) -> dict:
    out = {}
    for f in SCHEMAS[table]:
        v = row.get(f.name)
        if v is not None and f.type == I64 and isinstance(v, int) and not -I64_MAX <= v <= I64_MAX:
            v = None
        if v is not None and f.type == I32 and isinstance(v, int) and not -(1 << 31) < v < (1 << 31):
            v = None
        out[f.name] = v
    return out


class Writer:
    """Buffers rows per table and writes a parquet part per table and day on flush.
    Memory is bounded: a table at MAX_ROWS is flushed at once."""

    def __init__(self, root: Path | None = None, budget_gb: float | None = None):
        self.root = root or base()
        self.budget = (budget_gb if budget_gb is not None else BUDGET_GB) * 1e9
        self.buf: dict[str, list[dict]] = {k: [] for k in SCHEMAS}
        self.last_flush = time.monotonic()
        self.parts = 0
        self.rows_written = 0
        self.last_write_ms = 0

    def add(self, table: str, row: dict) -> bool:
        """Buffer a row; True when the table is full and a flush is due."""
        self.buf[table].append(_clean(table, row))
        return len(self.buf[table]) >= MAX_ROWS

    def due(self) -> bool:
        return time.monotonic() - self.last_flush >= FLUSH_S

    def take(self) -> dict[str, list[dict]]:
        """Hand the buffers over (for a flush in another thread) and start new ones."""
        out = {k: v for k, v in self.buf.items() if v}
        self.buf = {k: [] for k in SCHEMAS}
        self.last_flush = time.monotonic()
        return out

    def write(self, batches: dict[str, list[dict]], now_ms: int | None = None) -> int:
        """Write the rows, split by day of their time. Returns the number written."""
        now_ms = now_ms or int(time.time() * 1000)
        n = 0
        for table, rows in batches.items():
            by_day: dict[str, list[dict]] = {}
            for r in rows:
                by_day.setdefault(day_of(r.get("t") or now_ms), []).append(r)
            for day, rs in by_day.items():
                d = self.root / table / f"date={day}"
                d.mkdir(parents=True, exist_ok=True)
                self.parts += 1
                stamp = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%H%M%S")
                name = f"{stamp}-{os.getpid()}-{self.parts}.parquet"
                tbl = pa.Table.from_pylist(rs, schema=SCHEMAS[table])
                tmp = d / (name + ".tmp")
                pq.write_table(tbl, tmp, compression="zstd", compression_level=6)
                tmp.replace(d / name)
                n += len(rs)
        self.rows_written += n
        if n:
            self.last_write_ms = now_ms
        return n

    def flush(self, now_ms: int | None = None) -> int:
        return self.write(self.take(), now_ms)


def size_by_day(root: Path | None = None) -> dict[str, int]:
    root = root or base()
    out: dict[str, int] = {}
    for table in SCHEMAS:
        t = root / table
        if not t.is_dir():
            continue
        for d in t.iterdir():
            if d.is_dir() and d.name.startswith("date="):
                out[d.name[5:]] = out.get(d.name[5:], 0) + sum(f.stat().st_size for f in d.iterdir() if f.is_file())
    return out


def prune(root: Path | None = None, budget_bytes: float | None = None, today: str | None = None) -> list[str]:
    """Delete whole days, oldest first, until the record fits the budget. Never today."""
    root = root or base()
    budget_bytes = BUDGET_GB * 1e9 if budget_bytes is None else budget_bytes
    today = today or day_of(int(time.time() * 1000))
    sizes = size_by_day(root)
    total = sum(sizes.values())
    gone = []
    for day in sorted(sizes):
        if total <= budget_bytes or day >= today:
            break
        for table in SCHEMAS:
            p = root / table / f"date={day}"
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
        total -= sizes[day]
        gone.append(day)
    return gone


def days(root: Path | None = None) -> list[str]:
    root = root or base()
    t = root / "trades"
    if not t.is_dir():
        return []
    return sorted(d.name[5:] for d in t.iterdir() if d.is_dir() and d.name.startswith("date="))


def read(table: str, day_list: list[str], root: Path | None = None):
    """The rows of `table` for the given days as one polars frame (empty with the schema if none)."""
    import polars as pl
    root = root or base()
    files = []
    for day in day_list:
        d = root / table / f"date={day}"
        if d.is_dir():
            files += sorted(str(f) for f in d.glob("*.parquet"))
    if not files:
        return pl.from_arrow(SCHEMAS[table].empty_table())
    return pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")


def slot_times(pairs) -> dict[int, int]:
    """slot -> estimated time (ms) from (slot, receive ms) pairs: the earliest receive time of
    the slot or of any later slot (the lower envelope), so a slot that was delivered late is
    timed by the later slots that already arrived."""
    first: dict[int, int] = {}
    for s, t in pairs:
        if s is None or t is None:
            continue
        v = first.get(s)
        if v is None or t < v:
            first[s] = t
    out: dict[int, int] = {}
    run = None
    for s in sorted(first, reverse=True):
        run = first[s] if run is None else min(run, first[s])
        out[s] = run
    return out


def compact(day: str, root: Path | None = None) -> int:
    """Merge a finished day's part files into one file per table. Returns files merged."""
    root = root or base()
    n = 0
    for table in SCHEMAS:
        d = root / table / f"date={day}"
        if not d.is_dir():
            continue
        parts = sorted(d.glob("*.parquet"))
        if len(parts) <= 1:
            continue
        tbls = [pq.read_table(p) for p in parts]
        merged = pa.concat_tables([t.cast(SCHEMAS[table]) if t.schema.names == SCHEMAS[table].names
                                   else _widen(t, table) for t in tbls])
        tmp = d / "000000-all.parquet.tmp"
        pq.write_table(merged, tmp, compression="zstd", compression_level=9)
        for p in parts:
            p.unlink()
        tmp.replace(d / "000000-all.parquet")
        n += len(parts)
    return n


def _widen(t: pa.Table, table: str) -> pa.Table:
    """An older part without a later column: the column added as nulls."""
    cols = []
    for f in SCHEMAS[table]:
        cols.append(t.column(f.name).cast(f.type) if f.name in t.schema.names else pa.nulls(t.num_rows, f.type))
    return pa.Table.from_arrays(cols, schema=SCHEMAS[table])


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, default=str), encoding="utf-8")
    tmp.replace(path)
