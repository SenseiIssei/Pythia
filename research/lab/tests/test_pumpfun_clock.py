"""The engine's clock never runs backwards and the features of late rows are on chain time (audit of 2026-10-29 on
d84b252): a creation or migration released late (live.Hold) schedules nothing before the clock and fills nothing
before its landing, an action due before the clock runs before a late row, a wall-clock row (metadata, the pool
read) does not move the engine's clock, a pool read is not timed before its answer could exist, the features of
held rows equal those of the same rows in chain order, the creator book's last time never goes back, the tap
reader drains the rotated file and the tap survives a failed rotation, and the collector's held pool trades go out
once, with their signature. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_clock.py
"""

from __future__ import annotations

import heapq
import json
import math

from lab.pumpfun_rt import collector as CL
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import store
from lab.pumpfun_rt.tokens import CreatorBook
from test_pumpfun_exit_runners import BASE0, QUOTE0, Pool
from test_pumpfun_realistic import engine_with, fixed_fit
from test_pumpfun_rt import (BUYERS, DEV, MINT, POOL, SOL, T0, Curve, Fixed, create_vals, key, logs_for, note,
                             rule)

LATE = 60_000                                              # the clock when the held rows come


# ---------------------------------------------------------------- the clock

def test_a_late_creation_never_moves_the_clock_back_nor_fills_before_the_landing():
    eng = sim.Engine([rule("A", hold=600)], costs=Fixed())
    eng.advance(T0 + LATE)
    cv = Curve(eng)                                          # made at T0, released a minute late
    for i, dt in enumerate((500, 1_500, 2_500)):            # its held trades, timed by their slots
        cv.buy(T0 + dt, SOL // 10, BUYERS[i])
        assert eng.now == T0 + LATE, "a held row never sets the clock back"
    eng.advance(T0 + LATE + 1)
    p = next(iter(eng.positions.values()))
    assert p["signal_ms"] >= T0 + LATE and p["state"] == "pending"
    eng.advance(T0 + LATE + 2_000)
    assert p["state"] == "open" and p["land_ms"] >= T0 + LATE + 1_000, "landed one latency after the signal"
    assert eng.now == T0 + LATE + 2_000


def test_a_late_migration_signals_at_the_clock_and_the_held_pool_trades_never_fill_before_the_landing():
    eng, book = engine_with(fixed_fit(), ideal=False)
    eng.advance(T0 + LATE)
    clocks = []
    pool = Pool(eng)                                         # made, completed and migrated before the clock, late
    clocks.append(eng.now)
    pool.trade(T0 + 2_000, True, SOL // 100)                 # a held pool trade
    clocks.append(eng.now)
    eng.advance(T0 + LATE + 1)
    clocks.append(eng.now)
    assert clocks == sorted(clocks) and clocks[0] == T0 + LATE
    p = next(iter(book.pos.values()))
    assert p["signal_ms"] >= T0 + LATE and p["state"] == "pending"
    pool.trade(T0 + 3_000, True, SOL // 100)                 # another held one, before the landing (5 s)
    assert p["state"] == "pending", "nothing fills before the landing"
    eng.advance(T0 + LATE + 7_000)
    pool.trade(T0 + LATE + 7_000, True, SOL // 100)
    assert p["state"] == "open" and p["land_ms"] >= T0 + LATE + 5_000


class Probe:
    def __init__(self, eng):
        self.eng, self.ran = eng, []

    def hit(self, at, _):
        tok = self.eng.tokens.get(MINT)
        self.ran.append((at, tok.n_buys if tok else None))


def test_an_action_due_before_the_clock_runs_before_a_late_row_and_at_the_clock():
    eng = sim.Engine([], costs=Fixed())
    cv = Curve(eng)
    eng.advance(T0 + LATE)
    probe = Probe(eng)
    heapq.heappush(eng.heap, (T0 + 30_000, eng.seq, "pipe", (probe, "hit", None)))   # left before the clock
    eng.seq += 1
    cv.buy(T0 + 10_000, SOL // 10, BUYERS[0])                # a late row timed before the action
    assert probe.ran == [(T0 + LATE, 0)], "run before the row, at the clock, not back at its own time"
    assert eng.now == T0 + LATE


def test_push_never_schedules_before_the_clock():
    eng = sim.Engine([], costs=Fixed())
    eng.advance(T0 + LATE)
    eng.push(T0, "pipe", (Probe(eng), "hit", None))
    assert eng.heap[0][0] == T0 + LATE


# ---------------------------------------------------------------- wall-clock rows

def collector_into(eng):
    return CL.Collector(None, on_row=lambda tb, r: sim.feed_row(eng, tb, r), amm=True, meta=False)


def test_a_wall_clock_row_does_not_move_the_engine_clock():
    eng = sim.Engine([], costs=Fixed())
    col = collector_into(eng)
    assert col.handle(note("s1", 100, logs_for((E.PUMP, "CreateEvent", create_vals()))), T0) == 1
    assert eng.now == T0 and col.clock.latest == T0
    col.keep("meta", {"t": T0 + 900, "mint": MINT, "ok": True})          # the metadata fetch, by the wall clock
    assert eng.now == T0, "handed over on the chain clock"
    col.keep("other", {"kind": "pool_state", "t": T0 + 1_200, "slot": 100, "tx": None, "mint": MINT, "user": None,
                       "pool": POOL, "pb": BASE0, "pq": QUOTE0, "vq": 0})
    assert eng.now == T0 and eng.tokens[MINT].meta_t == T0


def test_a_gap_row_marks_what_is_open_and_moves_no_clock():
    eng = sim.Engine([rule("A", hold=600)], costs=Fixed())
    Curve(eng)
    eng.advance(T0 + 2_000)
    sim.feed_row(eng, "other", {"kind": "gap", "t": T0 + 95_000, "t0": T0 + 3_000, "user": E.PUMP})
    assert eng.now == T0 + 2_000 and eng.gaps == [(T0 + 3_000, T0 + 95_000)]
    assert all(p["gap"] for p in eng.positions.values()) and eng.positions


def test_the_stored_wall_clock_row_keeps_its_receive_time_and_without_a_chain_clock_the_row_goes_as_is():
    rows = []
    col = CL.Collector(None, on_row=lambda tb, r: rows.append(r))
    col.keep("meta", {"t": T0 + 900, "mint": MINT})
    assert rows[-1]["t"] == T0 + 900
    col.clock.stamp(100, T0)
    col.keep("meta", {"t": T0 + 900, "mint": MINT})
    assert rows[-1]["t"] == T0


def test_a_pool_read_is_not_timed_before_its_answer(tmp_path):
    w = store.Writer(tmp_path)
    base = {"mint": MINT, "buy": True, "sol": 1, "tok": 1, "user": DEV, "vs": 30 * SOL, "vt": 10 ** 15,
            "rs": 0, "rt": 793_100_000 * 10 ** 6, "fb": 95, "cfb": 30, "ix": "buy"}
    w.add("trades", {**base, "t": T0, "slot": 100, "tx": 1})
    w.add("other", {"kind": "pool_state", "t": T0 + 3_000, "slot": 100, "tx": None, "mint": MINT, "user": None,
                    "pool": POOL, "pb": BASE0, "pq": QUOTE0, "vq": 0})
    w.add("trades", {**base, "t": T0 + 2_000, "slot": 101, "tx": 2})
    w.flush(T0)
    got = [(tb, r["t"]) for tb, r in sim.day_events(store.days(tmp_path)[0], tmp_path)]
    assert got == [("trades", T0), ("trades", T0 + 2_000), ("other", T0 + 3_000)]


# ---------------------------------------------------------------- features on chain time

def held_or_not(late: bool):
    eng = sim.Engine([], costs=Fixed(), select=True, trend=True)
    if late:
        eng.advance(T0 + LATE)
    clocks = []
    cv = Curve(eng)
    for i, dt in enumerate((500, 1_500, 2_500, 4_000)):
        cv.buy(T0 + dt, SOL // 4, BUYERS[i])
        clocks.append(eng.now)
    cv.buy(T0 + 5_500, SOL // 10, BUYERS[0])
    cv.sell(T0 + 6_000, 10 ** 12, DEV)
    cv.buy(T0 + 7_000, SOL // 2, BUYERS[5])
    clocks.append(eng.now)
    eng.advance(T0 + LATE + 2_000)
    return eng, clocks


def same(a: dict, b: dict) -> list:
    return [k for k in a if not (a[k] == b.get(k) or (isinstance(a[k], float) and math.isnan(a[k])
                                                      and isinstance(b.get(k), float) and math.isnan(b[k])))]


def test_the_features_of_held_rows_equal_those_of_the_same_rows_in_chain_order():
    (chain, _), (held, clocks) = held_or_not(False), held_or_not(True)
    assert clocks == [T0 + LATE] * 5, "the held rows are handed at the clock (before the fix it ran back)"
    t = T0 + LATE + 2_000
    a, b = chain.tokens[MINT], held.tokens[MINT]
    assert same(chain.features(a, t), held.features(b, t)) == []
    assert same(chain.early.early_features(a, t), held.early.early_features(b, t)) == []
    assert (a.dev_sell_t, a.last_t, a.early.wallets) == (b.dev_sell_t, b.last_t, b.early.wallets)
    assert a.dev_sell_t == T0 + 6_000 and len(a.early.wallets) == 5
    assert list(chain.sel.flow[MINT]) == list(held.sel.flow[MINT])
    assert chain.early.st[MINT].top10_5 == held.early.st[MINT].top10_5, "the 5 s snapshot before the row past it"
    for t10 in (T0 + 8_000, T0 + 10_000):                     # the 10 s windows, as a replay sees them
        assert a.window(t10) == b.window(t10)


def test_the_creator_books_last_time_never_goes_back():
    book = CreatorBook()
    book.created("C", T0 + 5_000)
    book.created("C", T0)                                    # the older coin came second
    assert book.rows["C"][3] == T0 + 5_000 and book.rows["C"][0] == 2


# ---------------------------------------------------------------- the tap and the held pool trades

def test_the_tap_reader_drains_the_rotated_file_before_the_new_one(tmp_path):
    p = tmp_path / "creates.jsonl"
    tap = CL.Tap(p, max_bytes=10 ** 9)
    reader = CL.TapReader(p)
    tap.add({"mint": "A"})
    assert [r["mint"] for r in reader.poll()] == ["A"]
    tap.add({"mint": "B"})                                   # appended since the last poll, then rotated
    tap.max_bytes = 1
    tap.add({"mint": "C"})
    tap.max_bytes = 10 ** 9
    tap.add({"mint": "D"})
    assert [r["mint"] for r in reader.poll()] == ["B", "C", "D"] and reader.poll() == []
    tap.close()


def test_a_failed_rotation_leaves_the_tap_open(tmp_path, monkeypatch):
    p = tmp_path / "creates.jsonl"
    tap = CL.Tap(p, max_bytes=1)

    def fail(*a):
        raise OSError("busy")
    monkeypatch.setattr(CL.os, "replace", fail)
    tap.add({"mint": "A"})
    monkeypatch.undo()
    tap.max_bytes = 10 ** 9
    tap.add({"mint": "B"})
    tap.close()
    assert [json.loads(x)["mint"] for x in p.read_text().splitlines()] == ["A", "B"]


def test_the_held_pool_trades_go_out_once_with_their_signature():
    rows = []
    col = CL.Collector(None, on_row=lambda tb, r: rows.append((tb, r)))
    buy = {"timestamp": 1, "base_amount_out": 10, "quote_amount_in": 5, "pool_base_token_reserves": 1000,
           "pool_quote_token_reserves": 100, "pool": POOL, "user": DEV}
    assert col.handle(note("s3", 105, logs_for((E.PUMP_AMM, "BuyEvent", buy))), T0 + 10) == 0
    mig = {"user": DEV, "mint": MINT, "mint_amount": 206_900_000 * 10 ** 6, "sol_amount": 85 * SOL,
           "pool_migration_fee": 0, "bonding_curve": key(4), "timestamp": 1, "pool": POOL}
    assert col.handle(note("s4", 104, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig))), T0 + 20) == 2
    amm = [r for tb, r in rows if tb == "amm"]
    assert len(amm) == 1 and amm[0]["sig"] == "s3" and amm[0]["mint"] == MINT
    assert not col.amm_wait, "handed over, no longer held"
    mig2 = dict(mig, mint=key(9))                      # another migration naming the pool: nothing again
    assert col.handle(note("s6", 107, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", mig2))), T0 + 30) == 1
