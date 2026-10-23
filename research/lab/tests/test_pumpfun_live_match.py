"""The live book decides like its paper twin on the same events (2026-10-23: the live bot took 1 of the 8 coins the
paper P_pool0_wait book took): a migration that comes before its coin's creation (the links race), a short copy of a
transaction from one feed before the full one from another, the coins made in the minute before a start; every coin
not bought has its reason (the status's "skipped", one log line, skipped.jsonl) and the daily report matches the
live book against the paper book.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_match.py
"""

from __future__ import annotations

import csv
import json

import pytest

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import study as ST
from test_pumpfun_pipeline import FakeBuilder, FakeSigner, OpenGate
from test_pumpfun_rt import DEV, MINT, POOL, SOL, T0, create_vals, key, logs_for, note

RULE = "P_pool0_wait"
PROVIDER, PUBLIC = "wss://provider.example", "wss://api.mainnet-beta.solana.com"
LIMITS = P.Limits(0.05, 5, 0.6, 0.3)
MIG = {"user": DEV, "mint": MINT, "mint_amount": 206_900_000 * 10 ** 6, "sol_amount": 85 * SOL,
       "pool_migration_fee": 0, "bonding_curve": key(4), "timestamp": 1, "pool": POOL}
BUY = {"timestamp": 1, "base_amount_out": 10 ** 9, "quote_amount_in": SOL // 10,
       "pool_base_token_reserves": 206_900_000 * 10 ** 6, "pool_quote_token_reserves": 85 * SOL, "pool": POOL,
       "user": key(9)}
CREATE = logs_for((E.PUMP, "CreateEvent", create_vals()))
MIGRATE = logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", MIG))
POOL_BUY = logs_for((E.PUMP_AMM, "BuyEvent", BUY))


@pytest.fixture(autouse=True)
def folders(monkeypatch, tmp_path):
    from lab import report as rep
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(P, "kill_paths", lambda: [tmp_path / "etc-kill", tmp_path / "data-kill"])
    return tmp_path


def service(collector=LS.LiveCollector):
    """The live service's path from a websocket message to the live book, with an executor that sends nothing."""
    gate = OpenGate()
    gate.rule, gate.mode = RULE, "test"
    ex = LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), LIMITS, clock=lambda: T0, start=False, mode="test",
                         max_total_sol=1.0, rule=RULE,
                         totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
    eng = sim.Engine([])
    pipe = eng.add_pipe(P.Pipeline(eng, [P.BY_NAME[RULE]], ex, limits=LIMITS, name="live", record=False))
    book = LX.LiveBook(pipe, ex, RULE, alerts=False)
    pipe.on_skip, pipe.on_event = book.on_skip, book.on_event                # as live_exec.attach
    svc = LS.Service(gate=gate, engine=eng, alerts=False, start_worker=False)
    svc.book = book
    return svc, collector(None, svc.on_row, amm=True, meta=False), pipe


def shown(pipe) -> dict:
    """The status's "skipped" (LiveBook.status): the live rule's counts by reason."""
    return {k[1]: v for k, v in pipe.eng.skipped.items() if k[0] == RULE}


def decisions(pipe) -> int:
    return pipe.eng.counts["pipe_signals"] + sum(v for k, v in pipe.eng.skipped.items() if k[0] == RULE)


def test_the_same_events_over_a_provider_and_a_public_link_give_exactly_one_decision():
    svc, col, pipe = service()
    # the provider's PumpSwap link hands on the migration before its pump.fun link the creation (same slot)
    col.handle(note("m", 101, MIGRATE), T0, PROVIDER)
    col.handle(note("c", 101, CREATE), T0 + 5, PROVIDER)
    col.handle(note("b", 102, POOL_BUY), T0 + 400, PROVIDER)
    for i, (sig, slot, logs) in enumerate((("c", 101, CREATE), ("m", 101, MIGRATE), ("b", 102, POOL_BUY))):
        col.handle(note(sig, slot, logs), T0 + 15_000 + i, PUBLIC)            # the public copies, late
    svc.tick(T0 + 20_000)
    assert decisions(pipe) == 1 and pipe.eng.counts["pipe_signals"] == 1
    assert len(pipe.pos) == 1 and next(iter(pipe.pos.values()))["mint"] == MINT
    assert col.counts["duplicate"] == 3 and not svc.held

    # before: the migration reached the engine before the coin and was dropped without a word
    svc, col, pipe = service(COL.Collector)
    svc.on_row = lambda tb, r: svc._feed(tb, r)
    col.on_row = svc.on_row
    col.handle(note("m", 101, MIGRATE), T0, PROVIDER)
    col.handle(note("c", 101, CREATE), T0 + 5, PROVIDER)
    col.handle(note("b", 102, POOL_BUY), T0 + 400, PROVIDER)
    svc.tick(T0 + 20_000)
    assert decisions(pipe) == 0


def test_a_short_copy_from_one_feed_does_not_hide_the_full_copy_from_the_other():
    cut = CREATE[:3] + [LS.TRUNCATED]                                        # the data line cut off
    for collector, want in ((LS.LiveCollector, 1), (COL.Collector, 0)):
        svc, col, pipe = service(collector)
        col.handle(note("c", 101, cut), T0, PROVIDER)
        col.handle(note("c", 101, CREATE), T0 + 9_000, PUBLIC)
        col.handle(note("c", 101, CREATE), T0 + 9_500, PUBLIC)                 # a third copy: a duplicate
        col.handle(note("m", 102, MIGRATE), T0 + 10_000, PUBLIC)
        col.handle(note("b", 103, POOL_BUY), T0 + 10_400, PUBLIC)
        svc.tick(T0 + 20_000)
        assert pipe.eng.counts["pipe_signals"] == want, collector
    assert col.counts["short_copy"] == 0                                    # the plain collector never looks


def test_the_events_a_short_copy_lacked_keep_their_transactions_number():
    rows = []
    col = LS.LiveCollector(None, lambda tb, r: rows.append((tb, r)), amm=True, meta=False)
    trade = {"mint": MINT, "sol_amount": SOL, "token_amount": 10 ** 9, "is_buy": True, "user": DEV, "timestamp": 1,
             "virtual_sol_reserves": 31 * SOL, "virtual_token_reserves": 10 ** 15, "real_sol_reserves": SOL,
             "real_token_reserves": 7 * 10 ** 14, "fee_basis_points": 95, "creator_fee_basis_points": 30,
             "ix_name": "buy"}
    full = logs_for((E.PUMP, "CreateEvent", create_vals()), (E.PUMP, "TradeEvent", trade))
    col.handle(note("x", 100, logs_for((E.PUMP, "CreateEvent", create_vals())) + []), T0, PROVIDER)
    col.handle(note("y", 100, POOL_BUY), T0 + 1, PROVIDER)                  # another transaction in between
    col.handle(note("x", 100, full), T0 + 2, PUBLIC)
    col.handle(note("x", 100, full), T0 + 3, PROVIDER)
    kinds = [tb for tb, _ in rows]
    assert kinds == ["creates", "trades"]                                   # each event once (the pool is unknown)
    assert rows[0][1]["tx"] == rows[1][1]["tx"]                             # the dev buy is the creation's
    assert col.counts["short_copy"] == 1 and col.counts["duplicate"] == 1


def test_a_migration_whose_coin_never_shows_up_is_a_skip_with_its_reason(capsys):
    svc, col, pipe = service()
    col.handle(note("m", 101, MIGRATE), T0, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 400, PUBLIC)
    svc.tick(T0 + 1_000)
    assert MINT in svc.held and not pipe.eng.skipped                        # still waiting for the creation
    svc.held[MINT] = [(t - LS.HOLD_MS / 1000 - 1, tb, r) for t, tb, r in svc.held[MINT]]
    svc.tick(T0 + 2_000)
    svc.tick(T0 + 3_000)
    assert not svc.held and pipe.eng.skipped[(RULE, "creation not seen")] == 1
    assert shown(pipe) == {"creation not seen": 1}
    out = capsys.readouterr().out
    assert out.count(f"live: skipped {MINT[:8]}: creation not seen") == 1
    rec = [json.loads(x) for x in (LX.data_dir() / "skipped.jsonl").read_text().splitlines()]
    assert rec == [{"t": rec[0]["t"], "mint": MINT, "rule": RULE, "why": "creation not seen", "run": LX.RUN_ID}]
    # trades of a coin made before the adopted hours wait and go quietly
    other = key(40)
    svc.on_row("trades", {"t": T0, "mint": other, "buy": True})
    svc.held[other] = [(t - LS.HOLD_MS / 1000 - 1, tb, r) for t, tb, r in svc.held[other]]
    svc.tick(T0 + 5_000)
    assert other not in svc.held and sum(pipe.eng.skipped.values()) == 1


def test_every_coin_not_bought_has_a_reason_and_one_log_line(capsys):
    svc, col, pipe = service()
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    svc.tick(T0 + 10_000)                                                  # no pool trade within 5 s
    assert shown(pipe) == {"no pool state": 1}
    pipe.on_skip(RULE, MINT, "something else")                              # a second reason: no second line
    assert capsys.readouterr().out.count(f"live: skipped {MINT[:8]}") == 1

    svc, col, pipe = service()
    pipe.exec.balance_l = int(0.01 * SOL)                                   # the executor's caps refuse it
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    svc.tick(T0 + 10_000)
    assert not pipe.pos and shown(pipe) == {"refused: wallet balance too low": 1}
    assert "live: skipped" in capsys.readouterr().out


def test_coins_written_after_the_start_are_adopted_and_their_held_rows_follow():
    svc, col, pipe = service()
    col.handle(note("m", 101, MIGRATE), T0, PUBLIC)                        # made just before the start
    col.handle(note("b", 102, POOL_BUY), T0 + 400, PUBLIC)
    made = {"t": T0 - 30_000, "tx": 1, "mint": MINT, "creator": DEV, "vs": 30 * SOL, "vt": 10 ** 15, "rt": 10 ** 14,
            "name": "x", "symbol": "x", "uri": "", "mayhem": False, "cashback": False, "quote": None, "user": DEV}
    assert svc.rewarm([made], T0 + 1_000) == 1 and not svc.held
    svc.tick(T0 + 10_000)
    assert pipe.eng.counts["pipe_signals"] == 1 and len(pipe.pos) == 1


def write_csv(path, cols, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)


def test_the_daily_report_matches_the_live_book_against_the_paper_book(tmp_path):
    paper = tmp_path / "paper"
    write_csv(paper / "ledger.csv", ["rule", "mint", "signal_ms"],
              [{"rule": RULE, "mint": m, "signal_ms": T0 + i} for i, m in enumerate("abcd")]
              + [{"rule": "P_pool0", "mint": "z", "signal_ms": T0}, {"rule": RULE, "mint": "old", "signal_ms": 1}])
    write_csv(paper / "failed.csv", ["rule", "mint", "signal_ms"], [{"rule": RULE, "mint": "e", "signal_ms": T0}])
    d = LX.data_dir()
    d.mkdir(parents=True)
    (d / "orders.jsonl").write_text("\n".join(json.dumps(o) for o in [
        {"t": T0 + 900, "what": "sent", "side": "buy", "mint": "a"},
        {"t": T0 + 990, "what": "filled", "side": "buy", "mint": "a"},
        {"t": T0 + 950, "what": "sent", "side": "buy", "mint": "x"},
        {"t": T0 + 990, "what": "sent", "side": "sell", "mint": "b"}]) + "\n")
    (d / "skipped.jsonl").write_text("\n".join(json.dumps(k) for k in [
        {"t": T0 + 5, "mint": "b", "rule": RULE, "why": "no pool state"},
        {"t": T0 + 6, "mint": "c", "rule": RULE, "why": "creation not seen"}]) + "\nnot json\n")
    m = LX.paper_match(T0 - 1_000, T0 + 60_000, RULE, paper)
    assert m["paper"] == 5 and m["live"] == 2 and m["matched"] == 1 and m["live_only"] == 1
    assert m["missed"] == {"no pool state": 1, "creation not seen": 1, "no record": 2}
    line = LX.match_line(m)
    assert line.startswith("Live against paper (P_pool0_wait): the paper book entered 5 coins, the live book 2; "
                           "1 matched; missed: ")
    LX.write_json(LX.reports_dir() / "live_status.json", {"rule": RULE})
    assert LX.paper_match(T0 - 1_000, T0 + 60_000, paper=paper)["matched"] == 1     # the status's rule
    assert LX.match_line({"rule": None, "missed": {}}) == "No live book has run."
    assert ST.live_match(T0)["line"]                                       # the study's section never fails
