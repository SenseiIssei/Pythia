"""The daily pump.fun activity series on a tiny synthetic record.

Run from research/lab:  python -m pytest tests/test_pumpfun_activity.py
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lab.pumpfun_rt import activity, store
from lab.pumpfun_rt.events import PUMP, PUMP_AMM

DAY = "2026-10-21"
D0 = activity.day_ms(DAY)
H = 3_600_000


def put(root, table, day, name, rows):
    d = root / table / f"date={day}"
    d.mkdir(parents=True, exist_ok=True)
    sch = store.SCHEMAS[table]
    cols = {f.name: [r.get(f.name) for r in rows] for f in sch}
    pq.write_table(pa.Table.from_pydict(cols, schema=sch), d / name)


def test_coverage_edges_and_merged_gaps():
    # Events from the first minute to the last: the whole day, minus two overlapping gaps (2 h in all).
    gaps = [(D0 + 1 * H, D0 + 2 * H), (D0 + 90 * 60_000, D0 + 3 * H)]
    assert activity.coverage(D0 + 30_000, D0 + 24 * H - 30_000, gaps, D0) == pytest.approx(22 / 24)
    # The collector started at 12:00: half a day.
    assert activity.coverage(D0 + 12 * H, D0 + 24 * H - 1000, [], D0) == pytest.approx(0.5)
    # A gap of the other program does not count (filtered before), and no events is no coverage.
    assert activity.coverage(None, None, [], D0) == 0.0


def test_day_row_counts_once_even_with_synced_duplicates(tmp_path):
    creates = [{"t": D0 + 60_000 * i, "slot": i, "mint": f"m{i}"} for i in range(4)]
    trades = [{"t": D0 + 1000, "slot": 1, "tx": 1, "mint": "m0", "buy": True, "sol": 2_000_000_000, "user": "a"},
              {"t": D0 + 24 * H - 2000, "slot": 9, "tx": 2, "mint": "m1", "buy": False, "sol": 1_000_000_000,
               "user": "b"},
              {"t": D0 + 5000, "slot": 2, "tx": 3, "mint": "m2", "buy": True, "sol": 7_000_000_000, "user": "a",
               "quote": "USDCmint"}]
    other = [{"kind": "complete", "t": D0 + 2 * H, "mint": "m0"},
             {"kind": "migrate", "t": D0 + 2 * H + 1, "mint": "m0"},
             {"kind": "gap", "t": D0 + 7 * H, "t0": D0 + 6 * H, "user": PUMP},
             {"kind": "gap", "t": D0 + 9 * H, "t0": D0 + 8 * H, "user": PUMP_AMM}]
    for name in ("000000-all.parquet", "120000-1-5.parquet"):   # the same rows twice, as a sync can leave them
        put(tmp_path, "creates", DAY, name, creates)
        put(tmp_path, "trades", DAY, name, trades)
        put(tmp_path, "other", DAY, name, other)
    r = activity.day_row(DAY, tmp_path)
    assert r["creations"] == 4 and r["completions"] == 1 and r["migrations"] == 1
    assert r["migration_rate"] == pytest.approx(0.25)
    assert r["sol_volume"] == pytest.approx(3.0)        # the USDC-quoted curve is left out
    assert r["traders"] == 2
    assert r["coverage"] == pytest.approx(23 / 24)      # only the pump program's gap counts
    assert r["complete"] and r["creations_adj"] == pytest.approx(4 / (23 / 24))


def test_series_round_trip(tmp_path):
    p = tmp_path / "s.csv"
    activity.write_series(p, {"2026-10-21": {"day": "2026-10-21", "creations": 3, "complete": True}})
    back = activity.read_series(p)
    assert back["2026-10-21"]["creations"] == "3" and activity.as_bool(back["2026-10-21"]["complete"])
