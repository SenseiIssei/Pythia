"""The book calibration on synthetic books: empty arrays are skipped, real ones measured.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import polars as pl

from lab.experiments import costs

LIST = pl.List(pl.Float64)


def books(rows: list[tuple[list[float], list[float], list[float], list[float]]]) -> pl.DataFrame:
    return pl.DataFrame(
        {"bid_px": [r[0] for r in rows], "bid_qty": [r[1] for r in rows],
         "ask_px": [r[2] for r in rows], "ask_qty": [r[3] for r in rows]},
        schema={"bid_px": LIST, "bid_qty": LIST, "ask_px": LIST, "ask_qty": LIST})


def test_empty_book_arrays_are_skipped_not_an_index_error():
    # The weekly job died on bp[:, 0] when every recorded row of a symbol was empty.
    assert costs.measure(books([([], [], [], [])] * 1500)) is None


def test_no_rows_is_skipped():
    assert costs.measure(books([])) is None


def test_one_empty_side_is_skipped():
    assert costs.measure(books([([100.0], [1.0], [], [])] * 1500)) is None


def test_a_real_book_is_measured_and_stray_empty_rows_are_dropped():
    bid = [100.0 - 0.01 * i for i in range(20)]
    ask = [100.02 + 0.01 * i for i in range(20)]
    qty = [5.0] * 20
    rows = [(bid, qty, ask, qty)] * 1200 + [([], [], [], [])] * 10
    m = costs.measure(books(rows))
    assert m is not None
    assert m["samples"] == 1200
    assert abs(m["halfSpreadBps"] - 1.0) < 0.01
