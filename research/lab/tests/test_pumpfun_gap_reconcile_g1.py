"""G1 (results/pumpfun_gap_reconcile_g1_prereg.md): paper minus twin split exactly into its parts, the three records
of a trade, the sample's reasons, P2's eras and the stale pool state check; and the engine's drop of a fresher pool
read the study found (HEXN 2026-10-29: the paper filled 34 s after the migration on the first pool trade's state,
three times under the pool's read), kept as a strict xfail until sim.Engine.pool_state takes a read of a later slot.

Run from research/lab:  python -m pytest tests/test_pumpfun_gap_reconcile_g1.py
"""

from __future__ import annotations

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live_twin as LT
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import reconcile_g1 as G
from lab.pumpfun_rt import selection_p2 as P2
from test_pumpfun_exit_runners import BASE0, QUOTE0, engine
from test_pumpfun_exits_y8 import LatePool
from test_pumpfun_rt import MINT, POOL, T0

CUT = G.CUT_MS


def rec(**kw) -> dict:
    base = {"signal_ms": 0.0, "land_ms": 2_000.0, "xdec_ms": 60_000.0, "E": 1.0, "X": 1.2, "S": 0.05, "ret": 0.19,
            "exit_why": "take", "bought": True}
    return base | kw


PATH = [(0.0, 1.0), (1_000.0, 1.02), (2_000.0, 1.05), (3_000.0, 1.08), (50_000.0, 1.15), (60_000.0, 1.2),
        (70_000.0, 1.1)]


def test_the_parts_sum_to_paper_minus_twin_exactly():
    p = rec(signal_ms=-1_000.0, land_ms=1_000.0, xdec_ms=50_000.0, E=0.97, X=1.13, S=0.10, ret=0.15, exit_why="stop")
    t = rec(signal_ms=0.0, land_ms=3_000.0, xdec_ms=70_000.0, E=1.07, X=1.09, S=0.05, ret=0.0)
    pp = G.parts(p, t, PATH, q=85.0)
    assert pp["total"] == pytest.approx((0.15 - 0.0) * 100)
    assert sum(pp[k] for k in G.PARTS) == pytest.approx(pp["total"], abs=1e-9)
    assert pp["exit_rule"] != 0 and pp["exit_time"] == 0          # the exit reasons differ: the rule's part
    assert pp["size"] < 0 and pp["stake"] != 0 and pp["failed"] == 0
    same = G.parts(p | {"exit_why": "take"}, t | {"exit_why": "take"}, PATH, q=None)
    assert same["exit_rule"] == 0 and same["exit_time"] == pp["exit_rule"] and same["size"] == 0


def test_a_twin_without_a_buy_is_all_failed_buys():
    pp = G.parts(rec(), {"bought": False, "ret": -0.002, "S": 0.05}, PATH, q=85.0)
    assert pp["failed"] == pytest.approx((0.19 + 0.002) * 100) and pp["total"] == pp["failed"]
    assert all(pp[k] == 0 for k in G.PARTS if k != "failed")


def test_the_paper_record_takes_the_realised_exit_not_the_spot():
    r = {"signal_ms": "10", "land_ms": "20", "exit_signal_ms": "30", "exit_ms": "35", "entry_price": "2e-6",
         "stake_sol": "0.05", "proceeds_sol": "0.06", "ret": "0.18", "exit_why": "take", "exit_price": "9e-6"}
    p = G.paper_record(r)
    assert p["X"] == pytest.approx(0.06 * 2e-6 / 0.05) and p["spot_exit"] == 9e-6 and p["xdec_ms"] == 30
    assert G.paper_record({"ret": ""}) is None


class Book:
    def __init__(self, twin, done=None, fails=None):
        self.twin, self.done, self.fails = twin, done or {}, fails or {}


def test_the_twin_record_on_the_record_clock():
    lv = {"i": 0, "signal_ms": 1_000.0, "stake_l": 50_000_000}
    d = {"tokens": 25 * C.TOKEN_UNIT, "cost_l": 50_000_000, "proceeds_l": 60_000_000, "fees_l": 100_000,
         "stake_l": 50_000_000, "land_ms": 4_000, "exit_signal_ms": 9_000, "at": 9_500, "exit_why": "take"}
    t = G.twin_record(lv, Book({0: {"pid": 7, "offset": 500.0}}, {7: d}))
    assert t["signal_ms"] == 1_500 and t["bought"] and t["E"] == pytest.approx(0.05 / 25)
    assert t["ret"] == pytest.approx((60_000_000 - 50_000_000 - 100_000) / 50_000_000)
    f = G.twin_record(lv, Book({0: {"pid": 7, "offset": 0.0}}, fails={7: {"why": "6040", "fee_l": 5_000,
                                                                          "stake_l": 50_000_000}}))
    assert not f["bought"] and f["ret"] == pytest.approx(-0.0001) and f["how"] == "buy failed: 6040"
    assert G.twin_record(lv, Book({0: {"miss": LT.NO_POOL}})) is None


def test_the_sample_names_every_trade_left_out():
    live = {"ledger": [{"mint": "a", "exit_why": "take"}, {"mint": "b"}, {"mint": "c"}]}
    paper = {"ledger": [{"rule": "P_pool0", "mint": "a", "signal_ms": str(CUT + 900), "land_ms": str(CUT + 3_000),
                         "exit_signal_ms": str(CUT + 60_000), "entry_price": "1e-6", "stake_sol": "0.05",
                         "proceeds_sol": "0.06", "ret": "0.19", "exit_why": "take"}]}
    p2 = {"signals": [{"rule": "P_pool0", "mint": "a", "t": CUT + 900.0, "ret": 0.19, "live_key": 0,
                       "reason": P2.TRADED},
                      {"rule": "P_pool0", "mint": "c", "t": CUT + 7.0, "ret": 0.1, "live_key": 2, "reason": P2.TRADED}],
          "live_only": [{"mint": "b", "t": CUT + 5.0, "why": "no paper record"}]}
    tr = [{"i": i, "key": i, "rule": "P_pool0", "mint": m, "symbol": m.upper(), "day": "d",
           "signal_ms": CUT + s, "land_ms": CUT + s + 1_000, "xdec_ms": CUT + 60_000, "exit_ms": CUT + 61_000,
           "entry_price": 1e-6, "exit_price": 1.2e-6, "ret": 0.17, "stake_l": 50_000_000}
          for i, (m, s) in enumerate((("a", 1_000.0), ("b", 5.0), ("c", 7.0)))]
    d = {"tokens": 50_000 * C.TOKEN_UNIT, "cost_l": 50_000_000, "proceeds_l": 59_000_000, "fees_l": 0,
         "stake_l": 50_000_000, "land_ms": CUT + 2_500, "exit_signal_ms": CUT + 60_000, "at": CUT + 61_000,
         "exit_why": "take"}
    books = {"d": Book({0: {"pid": 1, "offset": 0.0}, 2: {"miss": LT.NO_POOL}}, {1: d})}
    s = G.sample(live, paper, p2, tr, books, {}, {}, stale_of=lambda r: True)
    assert len(s["in"]) == 1 and s["in"][0]["paper"]["stale"]
    x = s["in"][0]
    assert x["p_minus_l"] == pytest.approx(2.0) and x["l_minus_t"] == pytest.approx((0.17 - 0.18) * 100)
    assert x["p_minus_l"] == pytest.approx(x["parts"]["total"] - x["l_minus_t"])
    assert sorted(o["why"] for o in s["out"]) == ["no P2 paper row: no paper record", "no twin: no pool state in "
                                                                                       "the record"]
    st = G.stats(s["in"], draws=20)
    assert st["n"] == 1 and abs(st["sum"] - st["total"]) < 1e-9 and st["largest"] in G.PARTS


def test_p2s_same_coin_part_by_era():
    sig = [{"t": 10.0, "ret": 0.3, "live_ret": 0.0, "reason": P2.TRADED},
           {"t": 200.0, "ret": 0.0, "live_ret": 0.1, "reason": P2.TRADED},
           {"t": CUT + 1.0, "ret": 0.2, "live_ret": 0.1, "reason": P2.TRADED},
           {"t": CUT + 2.0, "ret": 0.5, "live_ret": None, "reason": P2.FAILED}]
    e = {x["era"]: x for x in G.eras(sig, since=100.0)}
    assert (e["ideal paper"]["n"], e["ideal paper"]["mean"]) == (1, pytest.approx(30.0))
    assert e["realistic, before the cut"]["mean"] == pytest.approx(-10.0)
    assert (e["from the cut"]["n"], e["from the cut"]["mean"]) == (1, pytest.approx(10.0))


def test_a_fill_on_a_stale_pool_state():
    row = {"land_ms": "10000"}
    read = (5_000.0, 300)
    assert G.stale_fill(row, read, [(1_000.0, 100), (13_000.0, 400)])          # no trade until after the fill
    assert not G.stale_fill(row, read, [(1_000.0, 100), (11_000.0, 400)])      # a trade within the fill wait
    assert not G.stale_fill(row, read, [(1_000.0, 100), (7_000.0, 301)])       # a trade between read and landing
    assert not G.stale_fill(row, read, [(6_000.0, 301)])                       # the read came first: it counts
    assert not G.stale_fill(row, (5_000.0, 50), [(1_000.0, 100)])              # an older read: dropped rightly
    assert not G.stale_fill({"land_ms": "4000"}, read, [(1_000.0, 100)])       # landed before the read
    rows = [{"rule": "P_pool0", "mint": "s", "land_ms": "10000", "ret": "0.5"},
            {"rule": "P_pool0", "mint": "f", "land_ms": "10000", "ret": "-0.1"}]
    sp = G.stale_split(rows, {"s": read}, {"s": [(1_000.0, 100)], "f": [(1_000.0, 100)]})["P_pool0"]
    assert sp["n"] == 2 and sp["stale"] == (1, pytest.approx(50.0)) and sp["fresh"] == (1, pytest.approx(-10.0))
    assert sp["mean"] == pytest.approx(20.0)


def test_the_trials_are_counted_in_the_pumpfun_family():
    ids = [t["id"] for t in G.trials() + G.posthoc_trials()]
    assert ids == ["pumpfun:gap_g1:total", "pumpfun:gap_g1:parts", "pumpfun:gap_g1:identity", "pumpfun:gap_g1:eras",
                   "pumpfun:gap_g1:stale_reads"]
    assert all(t["family"] == "pumpfun" and t["sharpe"] is None and t["source"] == G.PREREG
               for t in G.trials() + G.posthoc_trials())
    assert G.CUT_MS == R.FIX_MS


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="G1: sim.Engine.pool_state drops a pool read once the stream gave a pool "
                                       "trade, even a read of a later slot (outside this study's files)")
def test_a_pool_read_of_a_later_slot_than_the_streams_last_trade_is_the_state():
    eng = engine("P_pool0")
    pool = LatePool(eng)
    pool.open(T0 + 100)                                    # the stream's one trade, slot 50_001
    eng.pool_state(T0 + 200, MINT, POOL, BASE0 // 2, QUOTE0 * 2, slot=50_081)
    tok = eng.tokens[MINT]
    assert (tok.pb, tok.pq) == (BASE0 // 2, QUOTE0 * 2)
