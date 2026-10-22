"""Coins made before the live service started (sim.Engine.adopt, live_service.warm_tokens): their
migration is seen after a restart, nothing is booked twice, and only the last WARM_H hours are read.

Run from research/lab:  python -m pytest tests/test_pumpfun_warm.py
"""

from __future__ import annotations

import datetime as dt

import polars as pl

from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import strategies as S

NOW = 1_792_712_000_000
MINT, POOL = "Old1pump", "Pool1111"
VS, VT, RT = 30 * 10**9, 1_073_000_000 * 10**6, 793_100_000 * 10**6


def row(mint=MINT, t=NOW - 3 * 3_600_000, **over):
    r = {"t": t, "tx": 1, "mint": mint, "creator": "Creator1", "vs": VS, "vt": VT, "rt": RT, "name": "Old",
         "symbol": "OLD", "uri": "", "mayhem": False, "cashback": False, "quote": None, "user": "Creator1"}
    r.update(over)
    return r


def engine():
    return sim.Engine([S.BY_NAME["E_d0_x1"]], decisions=False)


def migrate(e, mint=MINT, t=NOW + 1_000):
    e.migrate(t, mint, POOL, 85 * 10**9, 206_900_000 * 10**6)
    e.advance(t + 5_000)


def test_a_coin_made_before_the_start_is_traded_at_its_migration_once_adopted():
    blind = engine()
    migrate(blind)
    assert MINT not in blind.tokens and not blind.counts.get("signals")     # the restart's blind spot

    e = engine()
    created = e.book.snapshot("Creator1", NOW)
    assert e.adopt(row(), NOW) and not e.adopt(row(), NOW)                   # once
    assert e.book.snapshot("Creator1", NOW) == created                       # its creation is not booked again
    migrate(e)
    assert e.counts["signals"] == 1                                         # E_d0_x1 enters at the migration
    assert all(f["why"] == "no pool state" for f in e.failed)               # (the pool's first trade is not fed here)


def test_an_adopted_coin_stays_long_enough_to_show_it_is_alive():
    e = engine()
    e.adopt(row(t=NOW - 7 * 3_600_000), NOW)                                 # older than the engine keeps idle ones
    e.advance(NOW + sim.IDLE_MS - 1_000)
    assert MINT in e.tokens
    e.advance(NOW + sim.IDLE_MS + 1_000)
    assert MINT not in e.tokens                                              # nothing happened on it: gone as usual


def test_warm_reads_only_the_last_hours_of_the_record(tmp_path):
    rows = [row(mint=f"m{i}", t=NOW - h * 3_600_000) for i, h in enumerate((0.5, 3, 11, 13, 30))]
    df = pl.DataFrame(rows)
    for day in sorted({dt.datetime.fromtimestamp(r["t"] / 1000, dt.timezone.utc).strftime("%Y-%m-%d") for r in rows}):
        part = df.filter(pl.col("t").map_elements(
            lambda t, d=day: dt.datetime.fromtimestamp(t / 1000, dt.timezone.utc).strftime("%Y-%m-%d") == d,
            return_dtype=pl.Boolean))
        (tmp_path / "creates" / f"date={day}").mkdir(parents=True)
        part.write_parquet(tmp_path / "creates" / f"date={day}" / "a.parquet")
    e = engine()
    assert LS.warm_tokens(e, NOW, hours=12, root=tmp_path) == 3
    assert {"m0", "m1", "m2"} <= set(e.tokens) and "m3" not in e.tokens
    assert LS.warm_tokens(e, NOW, hours=12, root=tmp_path) == 0               # a second call adds nothing
    assert LS.warm_tokens(engine(), NOW, root=tmp_path / "empty") == 0
