"""Buffered parquet writer, one directory per table, partitioned by UTC day.

Layout: <root>/<source>/<table>/date=YYYY-MM-DD/part-<HHMMSS>-<id>.parquet
Parts are compacted into a single day.parquet once the day is over.

Every row carries ts_recv_us, the moment this machine knew the value. Research
code must join on that column, never on the exchange timestamp alone, or the
backtest sees data before it could have arrived.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

log = logging.getLogger("sink")


def now_us() -> int:
    return time.time_ns() // 1000


def day_of(ts_us: int) -> str:
    return datetime.fromtimestamp(ts_us / 1e6, tz=timezone.utc).strftime("%Y-%m-%d")


class Table:
    def __init__(self, root: Path, source: str, name: str, schema: pa.Schema, heavy: bool = False):
        self.dir = root / source / name
        self.key = f"{source}/{name}"
        self.schema = schema
        self.heavy = heavy  # dropped first when the disk runs low
        self.rows: list[dict] = []
        self.written = 0
        self.dropped = 0

    def add(self, row: dict) -> None:
        self.rows.append(row)

    def take(self) -> list[dict]:
        rows, self.rows = self.rows, []
        return rows

    def write(self, rows: list[dict]) -> None:
        by_day: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            by_day[day_of(r["ts_recv_us"])].append(r)
        for day, part in by_day.items():
            d = self.dir / f"date={day}"
            d.mkdir(parents=True, exist_ok=True)
            name = f"part-{time.strftime('%H%M%S', time.gmtime())}-{uuid.uuid4().hex[:6]}.parquet"
            tmp = d / (name + ".tmp")
            pq.write_table(pa.Table.from_pylist(part, schema=self.schema), tmp, compression="zstd")
            os.replace(tmp, d / name)
            self.written += len(part)


class Sinks:
    def __init__(self, root: Path, min_free_gb: float):
        self.root = root
        self.min_free_gb = min_free_gb
        self.tables: dict[str, Table] = {}
        self.heavy_allowed = True

    def table(self, source: str, name: str, schema: pa.Schema, heavy: bool = False) -> Table:
        t = Table(self.root, source, name, schema, heavy)
        self.tables[t.key] = t
        return t

    def free_gb(self) -> float:
        return shutil.disk_usage(self.root).free / 1e9

    async def flush(self) -> None:
        free = self.free_gb()
        allowed = free >= self.min_free_gb
        if allowed != self.heavy_allowed:
            log.warning("disk %.1f GB free, heavy tables %s", free, "resumed" if allowed else "PAUSED")
            self.heavy_allowed = allowed
        for t in self.tables.values():
            rows = t.take()
            if not rows:
                continue
            if t.heavy and not self.heavy_allowed:
                t.dropped += len(rows)
                continue
            try:
                await asyncio.to_thread(t.write, rows)
            except Exception:
                log.exception("write failed for %s, %d rows lost", t.key, len(rows))

    async def flush_loop(self, every_s: float) -> None:
        while True:
            await asyncio.sleep(every_s)
            await self.flush()

    # ---- compaction -----------------------------------------------------

    def compact_finished_days(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for t in self.tables.values():
            if not t.dir.exists():
                continue
            for d in sorted(t.dir.glob("date=*")):
                if d.name.removeprefix("date=") >= today:
                    continue
                parts = sorted(d.glob("part-*.parquet"))
                if not parts:
                    continue
                compact_dir(d, parts)


def compact_dir(d: Path, parts: list[Path]) -> None:
    existing = d / "day.parquet"
    inputs = ([existing] if existing.exists() else []) + parts
    tables = [pq.read_table(p) for p in inputs]
    merged = pa.concat_tables(tables, promote_options="default").sort_by("ts_recv_us")
    tmp = d / "day.parquet.tmp"
    pq.write_table(merged, tmp, compression="zstd", row_group_size=250_000)
    if pq.ParquetFile(tmp).metadata.num_rows != merged.num_rows:
        tmp.unlink()
        raise RuntimeError(f"compaction row count mismatch in {d}")
    os.replace(tmp, existing)
    for p in parts:
        p.unlink()
    log.info("compacted %s: %d parts -> %d rows", d, len(parts), merged.num_rows)
