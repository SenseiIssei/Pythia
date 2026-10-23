"""The live book and its paper twin decide alike on the same events, and every coin either does not buy has its
reason (2026-10-23 after 202703a: the paper P_pool0_wait took SHEKEL, Samsung and JEW, the live bot SHEKEL, TRUMP and
GTA6; Samsung and JEW had no live record at all). What the record showed: the collector's PumpSwap stream was down
when TRUMP and GTA6 migrated, so the paper book saw no pool trade within 5 s; Samsung's migration reached the paper
feed 13 s late and was stamped with a later slot's time, so a pool trade 50 slots on counted as 0.3 s late; the paper
engine dropped a migration that came before its coin's creation, which the live service holds. Here: the wait on
the chain's clock, "no pool state (PumpSwap stream down)", the paper books holding like the live service, the paper
twin's skipped.jsonl, the live service's seen.jsonl and its "no decision", and the match line's live-only coins
with the paper side's reason.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_twin.py
"""

from __future__ import annotations

import json
import time

import pytest

from lab.pumpfun_rt import collector as COL
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import live
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import pipeline as P
from test_pumpfun_live_match import BUY, CREATE, MIG, MIGRATE, POOL_BUY, PUBLIC, RULE, service, shown, write_csv
from test_pumpfun_live_match import folders  # noqa: F401 - the live files in the test's folder
from test_pumpfun_rt import MINT, T0, key, logs_for, note


@pytest.fixture()
def twin(tmp_path, monkeypatch):
    """The paper twin as the collector runs it (live.Shadow behind a Collector), files in the test's folder."""
    monkeypatch.setattr(live, "paper_dir", lambda: tmp_path / "paper")
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0,
                     strategies=[P.BY_NAME[RULE], P.BY_NAME["P_pool0"]])
    return sh, COL.Collector(None, on_row=sh.on_row, amm=True, meta=False)


def twin_held(sh) -> list:
    return [p["mint"] for p in sh.engine.pipes[0].pos.values() if p["rule"] == RULE]


def paper_skips(sh) -> dict:
    sh.save()
    p = live.paper_dir() / "skipped.jsonl"
    rows = map(json.loads, p.read_text().splitlines()) if p.exists() else ()
    return {(k["rule"], k["mint"]): k["why"] for k in rows}


def late_migration(c, pool_bts: int) -> None:
    """9yDeBAsG's order: slot 120 (another pool's trade) and the pool's trade 50 slots on come first, the creation
    and the migration of slot 100 after them, so the slot clock stamps those with slot 120's time: the pool's trade
    looks 0.3 s after the migration, its block time says 10 s (pool_bts 11 against the migration's 1)."""
    c.handle(note("x", 120, logs_for((E.PUMP_AMM, "BuyEvent", dict(BUY, pool=key(70))))), T0, PUBLIC)
    c.handle(note("b", 150, logs_for((E.PUMP_AMM, "BuyEvent", dict(BUY, timestamp=pool_bts)))), T0 + 300, PUBLIC)
    c.handle(note("c", 100, CREATE), T0 + 600, PUBLIC)
    c.handle(note("m", 100, logs_for((E.PUMP, "CompletePumpAmmMigrationEvent", dict(MIG, timestamp=1)))), T0 + 600,
             PUBLIC)


@pytest.mark.parametrize("pool_bts,bought", [(11, False), (5, True)])
def test_the_pools_first_trade_counts_on_the_chains_clock_on_both_sides(twin, pool_bts, bought):
    sh, col = twin
    svc, lcol, pipe = service()
    for c in (col, lcol):
        late_migration(c, pool_bts)
    sh.tick(T0 + 10_000)
    svc.tick(T0 + 10_000)
    assert (twin_held(sh) == [MINT]) == bought and (len(pipe.pos) == 1) == bought
    if not bought:                                                          # 10 s on the chain, 0 s on the stamps
        assert shown(pipe) == {"no pool state": 1}
        assert paper_skips(sh) == {(RULE, MINT): "no pool state"}
    tok = sh.engine.tokens[MINT]
    assert tok.migrate_bts == 1 and tok.amm_bts == pool_bts


def test_no_pool_state_says_when_the_pumpswap_stream_was_down(twin, monkeypatch):
    now = [T0]
    monkeypatch.setattr(COL, "now_ms", lambda: now[0])
    sh, col = twin
    sh.watch_feed(col)
    col.link_up(E.PUMP_AMM, 0)
    col.link_down(E.PUMP_AMM, 0)                                            # every PumpSwap link down from T0
    now[0] = T0 + 30_000
    col.link_up(E.PUMP_AMM, 0)
    assert col.was_down(E.PUMP_AMM, T0 + 1_000, T0 + 6_000) and not col.was_down(E.PUMP_AMM, T0 + 31_000, T0 + 40_000)
    assert not col.was_down(E.PUMP, T0, T0 + 40_000)
    col.handle(note("c", 100, CREATE), T0 + 1_000, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 1_400, PUBLIC)
    sh.tick(T0 + 10_000)
    assert paper_skips(sh) == {(RULE, MINT): "no pool state (PumpSwap stream down)"}
    assert sh.engine.skipped[("P_pool0", "no pool state")] == 1             # waits for nothing: as before

    svc, lcol, pipe = service()                                             # the live service the same way
    pipe.feed_down = lambda a, b: lcol.was_down(E.PUMP_AMM, a, b)
    lcol.link_down(E.PUMP_AMM, 0)
    lcol.handle(note("c", 100, CREATE), now[0] + 100, PUBLIC)
    lcol.handle(note("m", 101, MIGRATE), now[0] + 200, PUBLIC)
    svc.tick(now[0] + 10_000)
    assert shown(pipe) == {"no pool state (PumpSwap stream down)": 1}


def test_the_paper_books_hold_a_migration_that_came_before_its_creation_like_the_live_service(twin):
    sh, col = twin
    svc, lcol, pipe = service()
    for c in (col, lcol):                                                   # JF9Du1tr: the creation a minute late
        c.handle(note("m", 101, MIGRATE), T0, PUBLIC)
        c.handle(note("b", 102, POOL_BUY), T0 + 400, PUBLIC)
        c.handle(note("c", 100, CREATE), T0 + 60_000, PUBLIC)
    assert not sh.hold.held and not svc.held
    sh.tick(T0 + 70_000)
    svc.tick(T0 + 70_000)
    assert twin_held(sh) == [MINT] and len(pipe.pos) == 1 and pipe.eng.counts["pipe_signals"] == 1


def test_a_paper_migration_whose_creation_never_comes_is_a_skip_of_the_twin(twin):
    sh, col = twin
    t = [100.0]
    sh.hold.clock = lambda: t[0]
    col.handle(note("m", 101, MIGRATE), T0, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 400, PUBLIC)
    sh.tick(T0 + 1_000)
    assert MINT in sh.hold.held
    t[0] += live.HOLD_MS / 1000 + 1
    sh.tick(T0 + 200_000)
    assert not sh.hold.held and sh.engine.skipped[(RULE, "creation not seen")] == 1
    assert sh.engine.skipped[("P_pool0", "creation not seen")] == 1
    assert paper_skips(sh) == {(RULE, MINT): "creation not seen"}           # the twin only, once
    sh._skipped(RULE, MINT, "something else")
    assert not sh.skips


def test_the_live_service_writes_what_it_saw_and_a_migration_without_a_decision_is_a_skip(capsys):
    svc, col, pipe = service()                                              # a coin bought: no "no decision"
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 500, PUBLIC)                   # a second copy: written once
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    svc.tick(T0 + 10_000)
    assert len(pipe.pos) == 1 and MINT in svc.book.bought
    seen = [json.loads(x) for x in (LX.data_dir() / "seen.jsonl").read_text().splitlines()]
    assert [(k["mint"], k["rule"]) for k in seen] == [(MINT, RULE)]
    svc.watch[MINT] = time.monotonic() - LS.NO_DECISION_S - 1
    svc.tick(T0 + 20_000)
    assert "no decision" not in shown(pipe)

    svc, col, pipe = service()                                              # the engine fails on the coin
    pipe.signal = lambda *a: 1 / 0
    col.handle(note("c", 100, CREATE), T0, PUBLIC)
    col.handle(note("m", 101, MIGRATE), T0 + 400, PUBLIC)
    col.handle(note("b", 102, POOL_BUY), T0 + 800, PUBLIC)
    out = capsys.readouterr().out
    assert f"live service: a amm row of {MINT[:8]} failed (ZeroDivisionError" in out and col.counts["shadow_error"] == 0
    svc.tick(T0 + 10_000)
    assert not shown(pipe)                                                  # not yet: it may still come
    svc.watch[MINT] = time.monotonic() - LS.NO_DECISION_S - 1
    svc.tick(T0 + 20_000)
    svc.tick(T0 + 21_000)
    assert shown(pipe) == {"no decision": 1}
    assert capsys.readouterr().out.count(f"live: skipped {MINT[:8]}: no decision") == 1
    rec = [json.loads(x) for x in (LX.data_dir() / "skipped.jsonl").read_text().splitlines()]
    assert [(k["mint"], k["why"]) for k in rec] == [(MINT, "no decision")]


def test_the_match_names_the_live_only_coins_with_the_paper_twins_reason(tmp_path):
    paper = tmp_path / "paper"
    write_csv(paper / "ledger.csv", ["rule", "mint", "signal_ms"],
              [{"rule": RULE, "mint": "3AVqrLKa", "signal_ms": T0}])
    write_csv(paper / "failed.csv", ["rule", "mint", "signal_ms"], [])
    (paper / "state.json").write_text(json.dumps({"open": [{"rule": RULE, "mint": "5ScfM97p", "signal_ms": T0 + 5}]}))
    (paper / "skipped.jsonl").write_text("\n".join(json.dumps(k) for k in [
        {"t": T0 + 1, "mint": "4gzLLN98", "rule": RULE, "why": "no pool state (PumpSwap stream down)"},
        {"t": T0 + 2, "mint": "14kEap9i", "rule": "P_pool0", "why": "no pool state"}]) + "\n")
    d = LX.data_dir()
    d.mkdir(parents=True)
    (d / "orders.jsonl").write_text("\n".join(json.dumps({"t": T0 + i, "what": "sent", "side": "buy", "mint": m})
                                              for i, m in enumerate(("3AVqrLKa", "4gzLLN98", "14kEap9i"))) + "\n")
    m = LX.paper_match(T0 - 1_000, T0 + 60_000, RULE, paper)
    assert m["paper"] == 2 and m["matched"] == 1 and m["missed"] == {"never seen by the live service": 1}
    assert m["live_only_why"] == {"14kEap9i": "no paper record", "4gzLLN98": "no pool state (PumpSwap stream down)"}
    assert LX.match_line(m).endswith("live only: 2 (14kEap9i (paper: no paper record); "
                                     "4gzLLN98 (paper: no pool state (PumpSwap stream down))).")
    many = dict(m, live_only=12, live_only_why={f"c{i:02d}": "no pool state" for i in range(12)})
    assert LX.match_line(many).endswith("c09 (paper: no pool state); 2 more).")
