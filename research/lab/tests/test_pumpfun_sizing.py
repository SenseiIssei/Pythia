"""The live stake follows the wallet (sizing.py): the rules with examples, the wiring into the live book
(limits, buys, closes, the pause, the daily limit), and the paper strategies' fixed 0.1 SOL.

Temp folders only, fake signers: no network, no real key, nothing sent.

Run from research/lab:  python -m pytest tests/test_pumpfun_sizing.py
"""

from __future__ import annotations

import dataclasses
import json

from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import sizing as Z
from lab.pumpfun_rt import strategies as S
from test_pumpfun_live import BalanceRpc, ack_file, folders, make_gate  # noqa: F401 (folders: every file in tmp)
from test_pumpfun_pipeline import FakeBuilder, FakeSigner, OpenGate, paper, strat
from test_pumpfun_rt import MINT, SOL, T0, Curve, Fixed


def stake(balance, open_cost=0.0, peak=0.0, pnl=0.0, trades=0, mean=None, ceiling=0.25):
    return Z.sized(balance_sol=balance, open_cost_sol=open_cost, peak_pnl_sol=peak, pnl_sol=pnl, live_trades=trades,
                   live_mean=mean, ceiling_sol=ceiling)


# ---------------------------------------------------------------- the rules

def test_the_stake_is_a_tenth_of_the_wallet_between_the_minimum_and_the_maximum():
    assert stake(0.9, ceiling=0.1) == (0.09, "10 % of 0.90 SOL")         # today's wallet and ack
    assert stake(0.7)[0] == 0.07 and stake(0.97)[0] == 0.09            # rounded down, 0.07 stays 0.07
    assert stake(0.4)[0] == Z.MIN_STAKE_SOL == 0.05
    assert stake(0.2) == (0.0, "stake paused: wallet under 0.25 SOL")
    assert stake(0.15, open_cost=0.15)[0] == 0.05                      # the open positions' cost counts
    assert stake(1.5, trades=50, mean=0.0)[0] == 0.15
    assert stake(3.0, trades=50, mean=0.02)[0] == Z.MAX_STAKE_SOL == 0.25
    assert Z.stake_for(balance_sol=0.9, open_cost_sol=0.0, peak_pnl_sol=0.0, pnl_sol=0.0, live_trades=0,
                       live_mean=None, ceiling_sol=0.1) == 0.09


def test_until_the_rule_has_proved_itself_live_at_most_a_tenth_of_a_sol():
    for trades, mean in ((0, None), (49, 0.5), (50, -0.01), (50, None)):
        sol, why = stake(3.0, trades=trades, mean=mean)
        assert sol == Z.PROOF_CAP_SOL == 0.1 and "until 50 live trades" in why, (trades, mean)
    assert stake(3.0, trades=50, mean=0.0)[0] == 0.25


def test_a_drawdown_halves_the_stake_and_a_deep_one_drops_it_to_the_minimum():
    proved = {"trades": 60, "mean": 0.01}
    assert stake(2.0, **proved)[0] == 0.2
    sol, why = stake(2.0, peak=0.4, pnl=0.0, **proved)                # 0.4 / 2.4 = 17 %
    assert sol == 0.1 and "drawdown 17 %: half" in why
    assert stake(2.0, peak=1.0, pnl=0.0, **proved)[0] == 0.05          # 1.0 / 3.0 = 33 %
    assert stake(0.6, peak=0.15, pnl=0.0, **proved)[0] == 0.05         # half of 0.06 is under the minimum
    assert stake(2.0, peak=0.1, pnl=0.0, **proved)[0] == 0.2           # 5 %: no brake
    assert stake(2.0, peak=0.0, pnl=0.3, **proved)[0] == 0.2           # above the peak: no drawdown


def test_the_owners_ceiling_rules_even_under_the_minimum_and_nothing_is_negative():
    assert stake(0.4, ceiling=0.02)[0] == 0.02
    assert stake(0.4, ceiling=0.015)[0] == 0.01                        # rounded down
    sol, why = stake(0.9, ceiling=0.0)
    assert sol == 0.0 and why.startswith("stake paused")
    assert stake(-1.0)[0] == 0.0


def test_the_ledger_gives_the_rules_trades_and_the_pnl_curve_with_its_peak(folders):
    for i, (rule, ret, pnl) in enumerate((("P_pool0", 0.1, 0.01), ("P_pool0", -0.2, -0.02), ("P_pool60", 0.5, 0.05))):
        LX.write_close({"mode": "test", "rule": rule, "mint": MINT, "exit_ms": 1_000 * (i + 1), "ret": ret,
                        "pnl_sol": pnl, "stake_sol": 0.1, "pid": i})
    LX.journal({"t": 4_000, "pnl_l": -1_000_000, "sig": "s1"})        # a failed transaction's fee
    got = Z.from_ledger("P_pool0")
    assert got["live_trades"] == 2 and abs(got["live_mean"] + 0.05) < 1e-12
    assert abs(got["peak_pnl_sol"] - 0.04) < 1e-9 and abs(got["pnl_sol"] - 0.039) < 1e-9
    assert abs(got["pnl_sol"] - LX.realised(0)["total_l"] / SOL) < 1e-9
    assert Z.from_ledger("P_none") == {"live_trades": 0, "live_mean": None, "peak_pnl_sol": got["peak_pnl_sol"],
                                       "pnl_sol": got["pnl_sol"]}


# ---------------------------------------------------------------- the live book

def live(tmp_path, balance=0.9, x=0.1, d=0.3, clock=None):
    gate = OpenGate()
    gate.rule, gate.mode, gate.env = "X", "test", {}
    gate.ack = LX.read_ack(ack_file(tmp_path, t=1.0, d=d, x=x))
    ex = LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), P.Limits(x, 5, 0.6, d), clock=clock or (lambda: T0),
                         start=False, mode="test", max_total_sol=1.0, rule="X",
                         totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False})
    ex.balance_l = None if balance is None else int(balance * SOL)
    eng = sim.Engine([], costs=Fixed())
    s = dataclasses.replace(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600), stake_sol=P.HARD_STAKE_SOL)
    pipe = eng.add_pipe(P.Pipeline(eng, [s], ex, name="live", record=False))
    book = LX.LiveBook(pipe, ex, "X", alerts=False)
    pipe.on_close = book.on_close
    return eng, pipe, book, ex


def test_the_live_book_takes_the_stake_from_the_wallet_and_a_buy_spends_it(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path)
    book.refresh_limits()
    assert ex.limits.stake_sol == 0.09 and pipe.risk["X"].limits.stake_sol == 0.09
    assert ex.stake == {"sol": 0.09, "why": "10 % of 0.90 SOL"}
    big = P.Order(9, "buy", MINT, "curve", 10, int(0.1 * 1.3 * SOL), T0)
    assert ex._caps(big) == "above the stake cap"                      # the same number as the order's
    assert ex._caps(P.Order(9, "buy", MINT, "curve", 10, int(0.09 * 1.3 * SOL), T0)) is None
    Curve(eng)
    eng.advance(T0 + 1)
    o = ex.pending[0]["order"]
    assert o.stake_l == int(0.09 * SOL) and pipe.pos[0]["stake_l"] == int(0.09 * SOL)
    st = book.status(None, None, None, [])
    assert st["stake"] == {"sol": 0.09, "why": "10 % of 0.90 SOL"} and st["limits"]["max_trade_sol"] == 0.09
    assert st["on"] and st["refusing"] is None


def test_a_close_sizes_the_stake_again(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path)
    book.refresh_limits()
    assert ex.limits.stake_sol == 0.09
    book.on_close({"pid": 1, "rule": "X", "mint": MINT, "exit_ms": T0, "pnl_sol": -0.3, "ret": -1.0,
                   "stake_sol": 0.3})                                  # 0.3 / (0.9 + 0.3) = 25 % down: half
    assert ex.limits.stake_sol == 0.05 and pipe.risk["X"].limits.stake_sol == 0.05
    assert "drawdown 25 %" in ex.stake["why"]


def test_a_stake_of_zero_buys_nothing_and_says_why(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path, balance=0.2)
    book.refresh_limits()
    assert ex.limits.stake_sol == 0.0
    assert ex.ready() == "stake paused: wallet under 0.25 SOL"
    Curve(eng)
    eng.advance(T0 + 1)
    assert not ex.pending and not pipe.pos
    assert eng.skipped[("X", "stake paused: wallet under 0.25 SOL")] == 1
    st = book.status(None, None, None, [])
    assert not st["on"] and st["refusing"] == "stake paused: wallet under 0.25 SOL"
    assert st["gate"] == ["stake paused: wallet under 0.25 SOL"] and st["stake"]["sol"] == 0.0


def test_without_a_balance_read_nothing_is_bought_and_the_first_read_sizes_the_stake(tmp_path, folders):
    eng, pipe, book, ex = live(tmp_path, balance=None)
    book.tick(T0, T0)
    assert ex.limits.stake_sol == 0.0 and "not read yet" in ex.ready()
    ex.balance_l = int(0.9 * SOL)                                      # the service's getBalance
    book.tick(T0 + 1_000, T0 + 1_000)                                  # before the minute is up
    assert ex.limits.stake_sol == 0.09 and ex.ready() is None


def test_the_daily_loss_limit_is_a_quarter_of_the_days_starting_base_never_above_the_ack(tmp_path, folders):
    now = [T0]
    eng, pipe, book, ex = live(tmp_path, clock=lambda: now[0])
    book.refresh_limits()
    assert abs(ex.limits.max_daily_loss_sol - 0.225) < 1e-12           # 25 % of 0.9, under the ack's 0.3
    ex.balance_l = int(0.5 * SOL)
    book.refresh_limits()
    assert abs(ex.limits.max_daily_loss_sol - 0.225) < 1e-12           # recorded once a day
    assert json.loads(LX.totals_path().read_text())["day_base"] == [T0 // P.DAY_MS, 0.9]
    now[0] += P.DAY_MS
    book.refresh_limits()
    assert abs(ex.limits.max_daily_loss_sol - 0.125) < 1e-12           # a new day, a new base
    ex.balance_l = int(10 * SOL)
    now[0] += P.DAY_MS
    book.refresh_limits()
    assert ex.limits.max_daily_loss_sol == 0.3                         # never above the ack


class SmallRpc(BalanceRpc):
    def balance(self, pubkey):
        return int(0.9 * SOL)


def test_attach_sizes_the_stake_and_the_live_strategy_buys_it_while_paper_keeps_its_tenth(tmp_path, folders):
    g = make_gate(tmp_path, ack=ack_file(tmp_path, x=0.1))
    book = LX.attach(sim.Engine([]), g, rpc=SmallRpc(), load=lambda p: FakeSigner(), alerts=False, start=False)
    assert book.exec.limits.stake_sol == 0.09 and book.pipe.risk["P_pool60"].limits.stake_sol == 0.09
    assert book.pipe.strats["P_pool60"].stake_sol == P.HARD_STAKE_SOL == 0.25
    assert P.BY_NAME["P_pool60"].stake_sol == 0.1


def test_the_caps_are_raised_but_every_strategy_still_stakes_a_tenth_on_paper():
    assert LX.TEST_MAX_TRADE_SOL == P.HARD_STAKE_SOL == 0.25
    assert all(s.stake_sol == 0.1 == S.STAKE_SOL for s in P.STRATEGIES)
    assert all(s.stake_sol == 0.1 for s in P.BY_NAME.values())
    eng = paper(strat(sl=0.99, ladder=((5.0, 1.0),), time_s=600))
    Curve(eng)
    eng.advance(T0 + 100)
    assert next(iter(eng.pipes[0].pos.values()))["stake_l"] == int(0.1 * SOL)
