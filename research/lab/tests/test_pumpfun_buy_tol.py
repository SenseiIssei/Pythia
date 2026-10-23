"""The live pool buy's tolerance and its pre-send price check (2026-10-23, after five buys failed on chain with
PumpSwap's 6040): the bound at 0.60 live and 0.30 on paper, the owner's PYTHIA_PUMPFUN_BUY_TOL, the check on the
stream's reserves and on one read when they are old, the skip without a send or a fee, sales and curve buys as
before, the paper twin P_pool0_wait_tol60, and a 6040 on landing booked quietly without a card. No network, no
wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_buy_tol.py
"""

from __future__ import annotations

import json

import pytest

from lab.pumpfun_rt import card as CD
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt.live_feed import LiveFeed
from test_pumpfun_exit_runners import Pool, engine
from test_pumpfun_live import LIMITS, ChainRpc, CountingSigner
from test_pumpfun_pipeline import FakeBuilder, FakeSigner, OpenGate
from test_pumpfun_rt import BUYERS, MINT, POOL, SOL, T0, Fixed

E6040 = {"InstructionError": [6, {"Custom": 6040}]}


@pytest.fixture(autouse=True)
def folders(monkeypatch, tmp_path):
    from lab import report as rep
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(P, "kill_paths", lambda: [tmp_path / "etc-kill", tmp_path / "data-kill"])
    monkeypatch.delenv(LX.ENV_BUY_TOL, raising=False)
    return tmp_path


class OrderBuilder(FakeBuilder):
    """Keeps every order it builds; `reserves` answers the pre-send check's read when the test sets them."""

    def __init__(self):
        super().__init__()
        self.orders, self.reads, self.res = [], 0, None

    def build(self, user, o, pool, close):
        self.orders.append(o)
        return super().build(user, o, pool, close)

    def reserves(self, pool, mint):
        self.reads += 1
        if self.res is None:
            raise RuntimeError("no read in this test")
        return self.res


def pool_book(now, builder=None):
    """A live book running P_pool0 on a pool that migrates at T0 (its state known from a trade at T0); the buy is
    queued, not sent yet."""
    gate = OpenGate()
    gate.rule, gate.mode = "P_pool0", "test"
    b = builder or OrderBuilder()
    b.rpc = ChainRpc()
    ex = LX.LiveExecutor(gate, CountingSigner(), b, LIMITS, clock=lambda: now[0], start=False, mode="test",
                         max_total_sol=1.0, rule="P_pool0", totals={"pnl_l": 0, "since_ms": None, "trades": 0,
                                                                    "total_alerted": False})
    ex.verify_sales = False
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(P.Pipeline(eng, [P.BY_NAME["P_pool0"]], ex, limits=LIMITS, name="live", record=False))
    book = LX.LiveBook(pipe, ex, "P_pool0", alerts=False)
    pipe.on_close, pipe.on_event, pipe.on_skip = book.on_close, book.on_event, book.on_skip
    cards = []
    book._post = lambda make: cards.extend(make("en"))
    pool = Pool(eng)
    eng.advance(T0 + 1)
    assert ex.pending and pipe.pos[0]["venue"] == "pool"
    return ex, b, pipe, pool, book, cards


def skipped_rows(tmp_path):
    f = tmp_path / "live" / "skipped.jsonl"
    return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []


# ---------------------------------------------------------------- the bounds

def test_the_live_pool_bound_is_the_quote_over_1_60_and_the_paper_keeps_0_30():
    assert C.SLIP_TOL == 0.30 and LX.LIVE_POOL_BUY_TOL == 0.60
    o = P.Order(1, "buy", MINT, "pool", 1_600_000, int(0.13 * SOL), T0, stake_l=int(0.1 * SOL))
    assert LX.pool_buy_amounts(o) == (int(0.1 * SOL), 1_000_000)
    assert LX.pool_buy_amounts(o, C.SLIP_TOL) == (int(0.1 * SOL), int(1_600_000 / 1.3))
    # the pre-send check's bound is taken when it is tighter, never a looser one
    assert LX.pool_buy_amounts(P.Order(1, "buy", MINT, "pool", 1_600_000, 0, T0, stake_l=1, least=1_200_000))[1] \
        == 1_200_000
    assert LX.pool_buy_amounts(P.Order(1, "buy", MINT, "pool", 1_600_000, 0, T0, stake_l=1, least=10))[1] == 1_000_000
    # the order's cost limit, which the stake cap, the exposure and the room count, stays stake x (1 + SLIP_TOL)
    eng = engine("P_pool0")
    pipe = eng.pipes[0]
    Pool(eng)
    eng.advance(T0 + 1)
    p = next(iter(pipe.pos.values()))
    assert p["limit_l"] == int(p["stake_l"] * (1 + C.SLIP_TOL))


def test_the_owner_sets_the_tolerance_from_0_05_to_1_0():
    assert LX.buy_tol({}) == LX.buy_tol({LX.ENV_BUY_TOL: " "}) == 0.60
    assert LX.buy_tol({LX.ENV_BUY_TOL: "0.45"}) == 0.45
    assert LX.buy_tol({LX.ENV_BUY_TOL: "3"}) == 1.0 and LX.buy_tol({LX.ENV_BUY_TOL: "0"}) == 0.05
    assert LX.buy_tol({LX.ENV_BUY_TOL: "lots"}) == 0.60 and LX.buy_tol({LX.ENV_BUY_TOL: "nan"}) == 0.60
    gate = OpenGate()
    gate.env = {LX.ENV_BUY_TOL: "0.8"}
    b = OrderBuilder()
    ex = LX.LiveExecutor(gate, FakeSigner(), b, LIMITS, clock=lambda: T0, start=False,
                         totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
    assert ex.buy_tol == b.buy_tol == 0.8


def test_6040_is_recognised_on_a_pool_buy_only():
    buy = {"side": "buy", "order": P.Order(1, "buy", MINT, "pool", 1, 1, T0)}
    assert LX.is_6040(E6040) and not LX.is_6040({"InstructionError": [6, {"Custom": 6003}]}) and not LX.is_6040("x")
    assert LX.chain_why(buy, E6040) == LX.RAN_AWAY_LANDING
    assert LX.chain_why({"side": "buy", "order": P.Order(1, "buy", MINT, "curve", 1, 1, T0)}, E6040).startswith("failed")
    assert LX.chain_why({"side": "sell", "order": P.Order(1, "sell", MINT, "pool", 1, 0, T0)}, E6040) \
        .startswith("failed on chain")
    assert LX.ran_away_text(0.724) == "price ran away (+72 %)"


# ---------------------------------------------------------------- the pre-send check

def test_a_price_run_away_on_fresh_stream_reserves_is_a_skip_without_a_send_a_fee_or_a_card(folders):
    now = [T0 + 500]
    ex, b, pipe, pool, book, cards = pool_book(now)
    pool.trade(T0 + 400, True, sol=40 * SOL, user=BUYERS[5])         # the price about 2.5x before the send
    ex.drain()
    pipe.poll(T0 + 600)
    ex.poll(T0 + 600)
    assert not b.rpc.sent and not b.orders and b.reads == 0         # the stream's reserves were fresh: no read
    assert not ex.pending and not ex.exposure and not pipe.pos
    assert ex.day_pnl_l == 0 and not cards                           # no fee, no card
    sk = {k[1]: v for k, v in pipe.eng.skipped.items() if k[0] == "P_pool0"}
    assert sk == {"price ran away": 1}
    rows = skipped_rows(folders)
    assert len(rows) == 1 and rows[0]["mint"] == MINT and rows[0]["why"].startswith("price ran away (+")
    feed = LiveFeed()
    feed.sync(book, T0 + 1_000)
    c = feed.coins[MINT]
    assert c["state"] == "skipped" and c["exit"]["why"].startswith("price ran away (+") and c["exit"]["pnl_sol"] == 0
    feed.sync(book, int(rows[0]["t"]) + feed.keep_ms + 1)            # and goes like any closed coin
    assert MINT not in feed.coins


def test_a_small_move_sends_with_the_bound_from_the_fresher_quote_never_looser_than_the_signals(folders):
    now = [T0 + 500]
    ex, b, pipe, pool, book, cards = pool_book(now)
    want = pipe.pos[0]["want"]
    pool.trade(T0 + 400, True, sol=5 * SOL, user=BUYERS[5])          # a little up: fewer tokens now
    tok = pipe.eng.tokens[MINT]
    fresh = C.pool_buy(pipe.pos[0]["stake_l"], tok.pb, tok.pq, tok.amm_fee_bps)
    assert want / 1.6 < fresh < want
    ex.drain()
    o = b.orders[0]
    assert len(b.rpc.sent) == 1 and o.least == int(want / 1.6)        # the signal's bound is the tighter one
    assert LX.pool_buy_amounts(o) == (pipe.pos[0]["stake_l"], int(want / 1.6))
    # the price fell instead: the bound follows the fresher, larger quote
    now2 = [T0 + 500]
    ex2, b2, pipe2, pool2, *_ = pool_book(now2)
    pool2.trade(T0 + 400, False, base=pool2.pb // 10, user=BUYERS[6])
    tok2 = pipe2.eng.tokens[MINT]
    fresh2 = C.pool_buy(pipe2.pos[0]["stake_l"], tok2.pb, tok2.pq, tok2.amm_fee_bps)
    ex2.drain()
    assert fresh2 > pipe2.pos[0]["want"] and b2.orders[0].least == int(fresh2 / 1.6)


def test_old_stream_reserves_are_read_once_and_the_read_decides(folders):
    now = [T0 + LX.FRESH_MS + 1]                                     # the last pool trade was at T0
    ex, b, pipe, pool, book, cards = pool_book(now)
    tok = pipe.eng.tokens[MINT]
    b.res = (tok.pb // 3, tok.pq * 2)                                 # the pool now: the price 6x
    ex.drain()
    ex.poll(T0 + 3_000)
    assert b.reads == 1 and not b.rpc.sent and not pipe.pos and ex.fresh_reads == 1
    assert skipped_rows(folders)[0]["why"].startswith("price ran away (+")
    # a read that fails: the stream's older reserves, and here the buy goes out with the signal's bound
    now2 = [T0 + LX.FRESH_MS + 1]
    ex2, b2, pipe2, *_ = pool_book(now2)
    ex2.drain()
    assert b2.reads == 1 and len(b2.rpc.sent) == 1 and b2.orders[0].least == int(pipe2.pos[0]["want"] / 1.6)
    # fresh enough: no read at all
    now3 = [T0 + LX.FRESH_MS]
    ex3, b3, *_ = pool_book(now3)
    ex3.drain()
    assert b3.reads == 0 and len(b3.rpc.sent) == 1


def test_sales_and_curve_buys_are_untouched(folders):
    now = [T0 + 500]
    ex, b, pipe, pool, book, cards = pool_book(now)
    ex.drain()
    reads = b.reads
    sale = P.Order(0, "sell", MINT, "pool", 1_000, 12_345, T0 + 600, "stop")
    curve = P.Order(7, "buy", MINT, "curve", 2_000, 6_500, T0 + 600, stake_l=5_000)
    for o in (sale, curve):
        ex.step(("send", o, POOL, False))
    assert b.orders[-2:] == [sale, curve] and b.reads == reads        # built exactly as given, no check
    assert b.orders[-2].limit_l == 12_345 and b.orders[-1].least == 0 and b.orders[-1].limit_l == 6_500


# ---------------------------------------------------------------- 6040 on landing

def test_a_6040_on_landing_is_booked_quietly_with_its_fee_and_other_failures_keep_their_card(folders):
    now = [T0 + 500]
    ex, b, pipe, pool, book, cards = pool_book(now)
    ex.drain()
    pipe.poll(T0 + 600)
    sig = ex.pending[0]["sig"]
    b.rpc.status[sig] = {"err": E6040, "confirmationStatus": "confirmed"}
    now[0] += LX.CONFIRM_MS + 1
    ex.poll(T0 + 700)
    ex.drain()
    ex.poll(T0 + 700)
    fee = ex._fee(failed=True)
    assert not ex.pending and not pipe.pos and ex.day_pnl_l == -fee   # the fee is paid and counted
    assert not cards and book.day_stats["failed"] == 0 and book.day_stats["ran_away"] == 1
    lines = [json.loads(x) for x in (folders / "live" / "orders.jsonl").read_text(encoding="utf-8").splitlines()]
    failed = [x for x in lines if x["what"] == "failed"]
    assert failed[0]["why"] == LX.RAN_AWAY_LANDING and "6040" in failed[0]["err"]
    assert book.ran_away[-1]["why"] == LX.RAN_AWAY_LANDING and not skipped_rows(folders)
    # the daily card says it in one quiet line
    for lang, words in (("en", "Price ran away on landing: 1"), ("de", "Preis bei der Landung davongelaufen: 1")):
        c = CD.live_daily_card(1, book.day_stats, 10 ** 9, 0.0, None, "test", "P_pool0", lang)
        assert words in c.render("telegram", lang)
    # another failure on chain: its card as before
    now2 = [T0 + 500]
    ex2, b2, pipe2, pool2, book2, cards2 = pool_book(now2)
    ex2.drain()
    pipe2.poll(T0 + 600)
    b2.rpc.status[ex2.pending[0]["sig"]] = {"err": {"InstructionError": [6, {"Custom": 6003}]},
                                            "confirmationStatus": "confirmed"}
    now2[0] += LX.CONFIRM_MS + 1
    ex2.poll(T0 + 700)
    ex2.drain()
    ex2.poll(T0 + 700)
    assert len(cards2) == 1 and book2.day_stats["failed"] == 1 and not book2.day_stats.get("ran_away")


# ---------------------------------------------------------------- the paper twin

def test_the_paper_twin_differs_from_p_pool0_wait_only_in_the_bound():
    a, t = P.BY_NAME["P_pool0_wait"], P.BY_NAME["P_pool0_wait_tol60"]
    assert t.exits == a.exits and t.stake_sol == a.stake_sol == 0.1 and (t.family, t.entry) == (a.family, a.entry)
    assert t.p == {**a.p, "base": "P_pool0_wait", "buy_tol": 0.60} and "buy_tol" not in a.p
    assert P.base_name(t) == "P_pool0_wait"                          # the same latency draws
    assert sum("buy_tol" in s.p for s in P.STRATEGIES) == 1


def test_on_paper_a_run_of_45_percent_fails_p_pool0_wait_and_fills_the_twin():
    eng = engine("P_pool0_wait", "P_pool0_wait_tol60")
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.to(T0 + 2, 1.45)                                             # +45 % before both land (the same latency)
    eng.advance(T0 + 10_000)
    pos = {p["rule"]: p for pp in eng.pipes for p in pp.pos.values()}
    failed = {f["rule"]: f["why"] for pp in eng.pipes for f in pp.failed}
    assert failed == {"P_pool0_wait": "slippage"} and pos["P_pool0_wait_tol60"]["state"] == "open"
