"""The live chart's feed (live_feed.py): which coins it watches, the points it keeps, the closed
coin's exit and how long it stays, and that it never breaks the live service.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_feed.py
"""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

from lab.pumpfun_rt import live_feed as LF
from lab.pumpfun_rt import pipeline as P

T0 = 1_792_700_000_000
MINT, OTHER = "Coin1pump", "Coin2pump"


class Tok:
    def __init__(self, price):
        self.p = price

    def price(self):
        return self.p


def book(positions, closed=()):
    s = P.BY_NAME["P_pool0"]
    pipe = NS(pos={p["pid"]: p for p in positions}, strats={s.name: s})
    return NS(pipe=pipe, closed_today=list(closed))


def pos(pid=1, mint=MINT, state="open", land=T0):
    return {"pid": pid, "rule": "P_pool0", "mint": mint, "symbol": "TST", "name": "Test", "venue": "pool",
            "state": state, "signal_ms": land - 500, "land_ms": land, "entry_price": 2e-6, "signal_price": 1.9e-6,
            "cost_l": 100_000_000, "mark_l": 110_000_000}


def test_only_held_coins_get_points_in_the_unit_of_the_entry_price():
    f = LF.LiveFeed()
    eng = NS(tokens={MINT: Tok(2.2e-6), OTHER: Tok(5e-6)})
    f.observe("amm", {"mint": MINT, "t": T0, "quote": 3_000_000_000, "buy": True}, eng)
    assert f.coins == {}                                                    # not held yet
    f.sync(book([pos()]), T0)
    f.observe("amm", {"mint": MINT, "t": T0 + 1_000, "quote": 3_000_000_000, "buy": True}, eng)
    f.observe("amm", {"mint": OTHER, "t": T0 + 1_000, "quote": 1, "buy": False}, eng)
    f.observe("trades", {"mint": MINT, "t": T0 + 2_000, "sol": 500_000_000, "buy": False}, eng)
    f.observe("other", {"mint": MINT, "t": T0 + 3_000}, eng)                # not a trade
    snap = f.snapshot({"balance_sol": 0.7, "pnl_today_sol": 0.06})
    c = snap["coins"][0]
    assert [p[0] for p in c["points"]] == [T0 + 1_000, T0 + 2_000]
    assert c["points"][0] == [T0 + 1_000, 2.2e-6, 3.0, 1] and c["points"][1][2:] == [0.5, 0]
    assert c["entry_price"] == 2e-6 and c["tp"] == 0.3 and c["sl"] == 0.2 and c["time_s"] == 300
    assert c["cost_sol"] == 0.1 and c["mark_sol"] == 0.11 and c["exit"] is None
    assert snap["balance_sol"] == 0.7 and snap["pnl_today_sol"] == 0.06
    json.dumps(snap)                                                        # what the service writes


def test_a_closed_coin_keeps_its_exit_for_a_while_then_goes():
    f = LF.LiveFeed(keep_ms=60_000)
    f.sync(book([pos()]), T0)
    rec = {"mint": MINT, "land_ms": T0, "exit_ms": T0 + 300_000, "exit_price": 2.5e-6, "exit_why": "time",
           "ret": 0.25, "pnl_sol": 0.025}
    f.dirty = False
    f.sync(book([], closed=[rec]), T0 + 301_000)
    c = f.coins[MINT]
    assert c["state"] == "closed" and c["exit"] == {"ms": T0 + 300_000, "price": 2.5e-6, "why": "time",
                                                    "ret": 0.25, "pnl_sol": 0.025} and f.dirty
    f.sync(book([], closed=[rec]), T0 + 350_000)
    assert MINT in f.coins
    f.sync(book([], closed=[rec]), T0 + 361_000)
    assert MINT not in f.coins


def test_an_old_close_of_the_same_coin_is_not_taken_for_the_new_position():
    f = LF.LiveFeed()
    old = {"mint": MINT, "land_ms": T0 - 900_000, "exit_ms": T0 - 600_000, "exit_price": 1e-6, "ret": -0.2}
    f.sync(book([pos()], closed=[old]), T0)
    f.sync(book([], closed=[old]), T0 + 10_000)
    assert f.coins[MINT]["exit"] is None                                    # its own close has not come yet


def test_a_feed_error_never_reaches_the_live_service(capsys):
    from lab.pumpfun_rt import live_service as LS
    svc = LS.Service(gate=NS(), engine=NS(tokens={MINT: NS()}), alerts=False, start_worker=False)
    svc.book = NS(pipe=None)

    def boom(*a):
        raise RuntimeError("chart")
    svc.feed.observe = boom
    import lab.pumpfun_rt.sim as sim
    real = sim.feed_row
    sim.feed_row = lambda eng, table, row: None
    try:
        svc.on_row("amm", {"mint": MINT})
        svc.on_row("amm", {"mint": MINT})
    finally:
        sim.feed_row = real
    assert capsys.readouterr().out.count("live feed RuntimeError") == 1    # said once, not per row
