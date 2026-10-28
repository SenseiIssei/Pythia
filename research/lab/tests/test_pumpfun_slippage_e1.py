"""E1, slippage bounds for pump.fun on realistic paper: a pool buy beyond its bound fails as 6040 with its fee, the
pre-send skip at the book's bound, a tighter bound never fills worse than it allows (pool and curve), a sale under its
bound fails with its fee and waits the live backoff, the sandwich arithmetic (none when it does not pay, never past the
bound, the attacker's profit what the pool says), the grid, the trials, the forward books in the shadow and their
table in the daily report. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_slippage_e1.py
"""

from __future__ import annotations

import json
import math

import pytest

from lab import metrics
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import slippage_e1 as E
from test_pumpfun_exit_runners import BASE0, QUOTE0, Pool
from test_pumpfun_realistic import files, fixed_fit, write_csv  # noqa: F401 - the fixture
from test_pumpfun_rt import MINT, SOL, T0, Fixed


def books(*pairs, view="none", rule="P_pool0", fit=None, wallet=False):
    eng = sim.Engine([], costs=Fixed())
    model = R.Model(fit or fixed_fit(), R.LiveConfig())
    out = {k: E.add_book(eng, rule, k, view, model, R.PaperWallet() if wallet else None) for k in pairs}
    return eng, out


def fails(book):
    return [f["why"] for f in book.failed]


# ---------------------------------------------------------------- the grid and the live numbers

def test_the_grid_is_the_registered_one_and_the_live_numbers_are_the_live_executors():
    assert list(E.PAIRS) == ["b02", "b05", "b10", "b20", "b30", "b60", "b100", "s05", "s15", "s30"]
    assert E.PAIRS[E.LIVE] == (LX.LIVE_POOL_BUY_TOL, None) and E.PAIRS["b100"][0] == LX.BUY_TOL_MAX
    assert E.SELL_MAX_FAILS == LX.SELL_MAX_FAILS and E.SELL_BACKOFF_MAX_S == LX.SELL_BACKOFF_MAX_S
    assert [E.backoff_ms(n) for n in range(1, 9)] == [LX.backoff_ms(n) for n in range(1, 9)]
    ids = [t["id"] for t in E.trials()]
    assert len(ids) == len(set(ids)) == 60 and all(t["family"] == "hand" for t in E.trials())
    assert E.RULES == ("P_pool0", "P_pool0_wait", "P_cmig_model")


def test_the_live_books_are_unchanged_by_the_hooks():
    ex = R.RealExecutor(R.Model(fixed_fit(), R.LiveConfig()))
    o = P.Order(1, "buy", MINT, "curve", 10, 130_000_000, T0, stake_l=100_000_000)
    assert ex.buy_tol == R.POOL_BUY_TOL and ex.curve_cap(o) == o.limit_l
    assert ex.squeeze_pool_buy(o, None, 1, 7, 5, None) == 7 and ex.squeeze_sell(o, None, 9, None) == 9


def test_names_parse_back():
    assert E.parse("P_pool0_wait@e1_b60") == ("P_pool0_wait", "b60", None)
    assert E.parse("P_pool0@e1_b100_sandwichC") == ("P_pool0", "b100", "sandwich")
    assert E.parse("P_cmig_model@e1_s05_noneW") == ("P_cmig_model", "s05", "none")
    assert E.parse("P_pool0_wait") is None and E.parse("P_pool0_wait@e1_b07") is None


# ---------------------------------------------------------------- buys

def test_a_pool_buy_beyond_its_bound_fails_as_6040_with_its_fee():
    eng, b = books("b05", "b60")
    pool = Pool(eng)
    eng.advance(T0 + 1)
    eng.advance(T0 + 5_500)                                   # checked at the send (4.5 s), landed at 5 s
    pool.trade(T0 + 6_000, True, QUOTE0 // 20)               # the first trade after the landing: price x 1.10
    assert fails(b["b05"]) == [R.RAN_AWAY_LANDING]
    assert b["b05"].failed[0]["pnl_sol"] == pytest.approx(-200_000 / SOL)   # the fee, no tip
    assert not fails(b["b60"]) and next(iter(b["b60"].pos.values()))["state"] == "open"
    s = E.stats(E.entries(b["b05"].closed, b["b05"].failed, b["b05"].worse))
    assert s["n6040"] == 1 and s["fee6040"] == pytest.approx(200_000 / SOL) and s["trades"] == 0


def test_the_pre_send_skip_uses_the_books_bound():
    eng, b = books("b05", "b60")
    pool = Pool(eng)
    eng.advance(T0 + 1)
    pool.to(T0 + 2_000, 1.10)                                 # at the send the price is up 10 %
    eng.advance(T0 + 4_600)
    assert b["b05"].failed[0]["why"].startswith(R.RAN_AWAY + " (+") and b["b05"].failed[0]["pnl_sol"] == 0
    assert not b["b60"].failed and next(iter(b["b60"].pos.values()))["state"] == "pending"


@pytest.mark.parametrize("ratio", [1.0, 1.03, 1.08, 1.15, 1.25, 1.45, 1.8, 2.5])
def test_a_tighter_bound_never_fills_worse_than_it_allows(ratio):
    eng, b = books(*E.BUYS)
    pool = Pool(eng)
    eng.advance(T0 + 5_500)
    pool.trade(T0 + 6_000, True, int(QUOTE0 * ratio ** 0.5 - pool.pq))   # the price x ratio before the fill
    for k in E.BUYS:
        tol = E.PAIRS[k][0]
        assert all(w <= tol + 1e-9 for w in b[k].worse.values()), k
        if ratio - 1 > tol + 0.01:
            assert fails(b[k]) == [R.RAN_AWAY_LANDING] and not b[k].worse, k
        elif ratio - 1 < tol - 0.01:
            assert not fails(b[k]) and next(iter(b[k].worse.values())) == pytest.approx(ratio - 1, abs=0.01), k


def test_a_curve_buys_cap_is_its_bound_and_never_above_the_live_room():
    ex = E.BoundExecutor(R.Model(fixed_fit(), R.LiveConfig()), pair="b05")
    o = P.Order(1, "buy", MINT, "curve", 10, int(100_000_000 * (1 + C.SLIP_TOL)), T0, stake_l=100_000_000)
    assert ex.curve_cap(o) == 105_000_000
    for k in E.BUYS:
        ex = E.BoundExecutor(R.Model(fixed_fit(), R.LiveConfig()), pair=k)
        assert ex.curve_cap(o) <= o.limit_l
        assert ex.curve_cap(o) == pytest.approx(100_000_000 * (1 + min(E.PAIRS[k][0], C.SLIP_TOL)), abs=2)


# ---------------------------------------------------------------- sales

def test_a_sale_under_its_bound_fails_with_its_fee_and_waits_the_backoff():
    eng, b = books("s05", "b60")
    pool = Pool(eng)
    eng.advance(T0 + 5_500)
    pool.trade(T0 + 6_000, True, SOL // 1000)                 # both buys fill at about the open
    assert all(p["state"] == "open" for x in b.values() for p in x.pos.values())
    pool.to(T0 + 10_000, 0.75)                                # the -20 % stop: both sell, landing 4 s later
    k = pool.pb * pool.pq                                     # the first trade after the landing: 13 % lower
    pool.trade(T0 + 14_500, False, base=int(k / (QUOTE0 * math.sqrt(0.65)) - pool.pb))
    s05, b60 = b["s05"], b["b60"]
    assert s05.sale_fails == 1 and s05.sale_fail_l == 200_000 and s05.exec.fails
    assert not b60.sale_fails and b60.closed and b60.closed[0]["exit_why"] == "stop"
    pool.trade(T0 + 17_000, True, SOL // 1000)               # inside the backoff: nothing lands yet
    assert s05.pos
    pool.trade(T0 + 30_000, True, SOL // 1000)
    eng.advance(T0 + 40_000)
    t = s05.closed[0]
    assert t["exit_ms"] >= T0 + 14_500 + 1_000 + 4_000 and not s05.exec.fails
    fee = t["proceeds_sol"] - t["stake_sol"] - t["pnl_sol"]
    assert fee == pytest.approx((2 * 205_000 + 200_000) / SOL)   # two landed and one failed transaction


def test_after_six_failed_sales_the_next_goes_without_a_bound(monkeypatch):
    sent = []
    monkeypatch.setattr(R.RealExecutor, "sell", lambda self, o: sent.append(o))
    ex = E.BoundExecutor(R.Model(fixed_fit(), R.LiveConfig()), pair="s05")
    ex.fails[7] = E.SELL_MAX_FAILS
    o = P.Order(7, "sell", MINT, "pool", 10, 0, T0, "stop")
    ex.sell(o)
    ex.sell(o)
    assert ex.given_up == 1 and [x.limit_l for x in sent] == [0, 0]
    assert sent[0].signal_ms == T0 + LX.backoff_ms(LX.SELL_MAX_FAILS)


# ---------------------------------------------------------------- sandwiches

def test_a_small_buy_is_not_worth_a_sandwich_and_a_large_one_is_pushed_to_its_bound():
    fee, cost = 125, 410_000
    plain = C.pool_buy(SOL // 10, BASE0, QUOTE0, fee)
    least = int(plain / 1.6)
    g, p = E.sandwich_buy(SOL // 10, QUOTE0, BASE0, fee, least, cost)
    assert p == 0 and g == pytest.approx(plain, rel=1e-9)     # 0.1 SOL into 67 SOL at 1.25 %: it does not pay
    big = 5 * SOL
    plain = C.pool_buy(big, BASE0, QUOTE0, fee)
    for tol in (0.05, 0.3, 0.6):
        least = int(plain / (1 + tol))
        g, p = E.sandwich_buy(big, QUOTE0, BASE0, fee, least, cost)
        assert p > 0 and least <= g < plain
        assert g == pytest.approx(least, rel=0.01)            # the attacker pushes to the bound
    g2, p2 = E.sandwich_buy(big, QUOTE0, BASE0, fee, int(plain / 1.05), cost)
    g6, p6 = E.sandwich_buy(big, QUOTE0, BASE0, fee, int(plain / 1.6), cost)
    assert p6 > p2 and g6 < g2                                # a looser bound feeds it more


def test_the_attackers_profit_is_what_the_pool_says():
    fee, cost, spend = 30, 410_000, 3 * SOL
    plain = C.pool_buy(spend, BASE0, QUOTE0, fee)
    g, p = E.sandwich_buy(spend, QUOTE0, BASE0, fee, int(plain / 1.2), cost)
    f = fee / 10_000
    lo, hi = 0.0, 50.0 * QUOTE0                               # the attacker's x that leaves us g, by bisection
    for _ in range(200):
        x = (lo + hi) / 2
        a, s1, t1 = E._buy(x, QUOTE0, BASE0, f)
        lo, hi = (x, hi) if E._buy(spend, s1, t1, f)[0] > g else (lo, x)
    a, s1, t1 = E._buy(x, QUOTE0, BASE0, f)
    _, s2, t2 = E._buy(spend, s1, t1, f)
    assert p == pytest.approx(E._sell(a, s2, t2, f)[0] - x - cost, rel=1e-3)
    assert E._buy(SOL, QUOTE0, BASE0, f)[0] == pytest.approx(C.pool_buy(SOL, BASE0, QUOTE0, fee), rel=1e-9)
    assert E._sell(10 ** 12, QUOTE0, BASE0, f)[0] == pytest.approx(C.pool_sell(10 ** 12, BASE0, QUOTE0, fee), rel=1e-9)


def test_sandwiched_sales_and_curve_buys_stay_inside_their_bounds():
    fee, cost = 30, 410_000
    tokens = BASE0 // 20
    plain = C.pool_sell(tokens, BASE0, QUOTE0, fee)
    for min_out in (0, int(plain / 1.3), int(plain / 1.05)):
        v, p = E.sandwich_sell(tokens, QUOTE0, BASE0, fee, min_out, cost)
        assert min_out <= v <= plain + 1 and (p > 0) == (v < plain)
    v, p = E.sandwich_sell(10 ** 9, QUOTE0, BASE0, fee, 0, cost)
    assert p == 0 and v == pytest.approx(C.pool_sell(10 ** 9, BASE0, QUOTE0, fee), rel=1e-9)
    vs, vt = 30 * SOL, 1_073_000_000 * 10 ** 6
    want = C.curve_buy(2 * SOL, vs, vt, 10 ** 18, 125)
    base = P.curve_cost(want, vs, vt, 125)
    for tol in (0.02, 0.1, 0.3):
        cap = int(base * (1 + tol))
        k, p = E.sandwich_curve_buy(want, vs, vt, 125, cap, cost)
        assert base - 2 <= k <= cap
    k, p = E.sandwich_curve_buy(C.curve_buy(SOL // 100, vs, vt, 10 ** 18, 125), vs, vt, 125, 10 ** 15, cost)
    assert p == 0


def test_a_sandwich_book_fills_a_large_buy_worse_inside_its_bound_and_counts_it():
    eng = sim.Engine([], costs=Fixed())
    model = R.Model(fixed_fit(), R.LiveConfig())
    out = {}
    for v in E.VIEWS:                                         # 5 SOL a trade (the depth cap makes it about 3)
        s = E.variant("P_pool0", "b30", v, stake_sol=5.0)
        eng.rule_costs[s.name] = R.RealCosts(model=model)
        out[v] = eng.add_pipe(E.Book(eng, [s], E.BoundExecutor(model, None, "b30", v), name=s.name,
                                     limits=P.Limits(5.0, 1_000, math.inf, math.inf)))
    pool = Pool(eng)
    eng.advance(T0 + 5_500)
    pool.trade(T0 + 6_000, True, SOL // 1000)
    none, sw = (next(iter(out[v].worse.values())) for v in E.VIEWS)
    assert out["sandwich"].exec.sw["buys"] == 1 and out["none"].exec.sw["buys"] == 0
    assert none + 0.05 < sw <= 0.30 + 1e-9                    # worse, never past the bound (here its optimum)


# ---------------------------------------------------------------- the measures

def test_paired_differences_match_signals_by_rule_and_coin():
    a = [{"rule": "r", "mint": m, "pnl_sol": x} for m, x in (("a", 0.02), ("b", -0.01), ("c", 0.0))]
    b = [{"rule": "r", "mint": m, "pnl_sol": x} for m, x in (("a", 0.01), ("b", -0.01), ("d", 5.0))]
    d = E.paired(a, b)
    assert d["n"] == 2 and d["diff"] == pytest.approx(0.05) and d["band"][0] <= d["diff"] <= d["band"][1]


def test_the_proposal_keeps_the_live_bound_unless_its_band_lies_above_zero():
    def book(pnls):
        e = [{"rule": E.TWIN, "mint": f"m{i}", "pnl_sol": x, "signal_ms": T0 + i, "failed": False, "ret": x / 0.1,
              "why": "take", "worse": 0.0} for i, x in enumerate(pnls)]
        return {"entries": e, "stats": E.stats(e)}
    base = [0.01 * ((-1) ** i) for i in range(200)]
    bs = {(E.TWIN, k, "sandwich"): book(base) for k in E.PAIRS}
    bs[(E.TWIN, "b10", "sandwich")] = book([x + 0.002 for x in base])          # better on every coin
    bs[(E.TWIN, "s15", "sandwich")] = book([x + (0.05 if i == 0 else 0) for i, x in enumerate(base)])   # one coin
    p = E.propose(bs)
    assert p["buy"]["best"] == "b10" and p["buy"]["proposed"] == "b10"
    assert p["sale"]["best"] == "s15" and p["sale"]["proposed"] == E.LIVE


# ---------------------------------------------------------------- forward

def test_the_shadow_runs_the_forward_books_on_their_own_paper_wallets():
    eng = sim.Engine([], costs=Fixed())
    wallets = {}
    bs = E.shadow_books(eng, R.Model(fixed_fit(), R.LiveConfig()), wallets)
    names = sorted(n for b in bs for n in b.strats)
    assert len(bs) == 30 and names == sorted(f"{r}@e1_{k}" for r in E.RULES for k in E.PAIRS)
    assert set(wallets) == set(names) and all(b.name == "realistic" and b.exec.wallet is wallets[n]
                                              for b in bs for n in b.strats)
    assert all(b.exec.view == "sandwich" for b in bs)
    sh = live.Shadow("A_all_x1", models=None, alerts=False, now_ms=T0, strategies=[P.BY_NAME["P_pool0"]],
                     realistic=True, real=R.Model(fixed_fit(), R.LiveConfig()))
    assert not any("@e1_" in n for p in sh.engine.pipes for n in p.strats)   # a narrow shadow: none


def test_the_forward_table_reads_the_ledger_without_tainted_rows_and_registers_the_trials(tmp_path):
    rows = [{"rule": "P_pool0_wait@e1_b05", "mint": "a", "signal_ms": R.FIX_MS + 1_000, "land_ms": R.FIX_MS + 6_000,
             "exit_ms": R.FIX_MS + 60_000, "exit_signal_ms": R.FIX_MS + 50_000, "hold_s": 54, "pnl_sol": 0.002,
             "ret": 0.04, "stake_sol": 0.05, "slip": 0.03, "exit_why": "take"},
            {"rule": "P_pool0_wait@e1_b05", "mint": "b", "signal_ms": R.FIX_MS + 9_000, "land_ms": R.FIX_MS + 8_000,
             "exit_ms": R.FIX_MS + 70_000, "hold_s": 5, "pnl_sol": 1.0, "ret": 20.0, "stake_sol": 0.05},
            {"rule": "P_pool0_wait", "mint": "a", "signal_ms": R.FIX_MS, "pnl_sol": 9.0, "ret": 9.0}]
    failed = [{"rule": "P_pool0_wait@e1_b05", "mint": "c", "signal_ms": R.FIX_MS + 2_000, "land_ms": R.FIX_MS + 7_000,
               "why": R.RAN_AWAY_LANDING, "pnl_sol": -0.0002}]
    fw = E.forward(rows, failed)
    s = fw["books"]["P_pool0_wait|b05"]
    assert s["signals"] == 2 and s["trades"] == 1 and s["n6040"] == 1 and s["mean"] == pytest.approx(0.04)
    assert s["worse2"] == 1.0 and len(fw["books"]) == 1
    assert {r["id"] for r in metrics.read_registry()} >= {t["id"] for t in E.trials()}
    md = "\n".join(E.forward_md(fw))
    assert "| b05 | 2 | 1 | 1 |" in md and "\u2014" not in md
    assert "no forward trades" in "\n".join(E.forward_md(None))


def test_the_daily_job_writes_the_forward_table(files):  # noqa: F811
    now = T0 + 8 * 86_400_000
    write_csv(files / "paper" / "ledger.csv", [{"rule": "P_pool0_wait@e1_b60", "mint": "a", "signal_ms": now - 9e5,
                                                "land_ms": now - 8e5, "exit_ms": now - 7e5, "hold_s": 100,
                                                "pnl_sol": 0.001, "ret": 0.02, "stake_sol": 0.05}])
    out = R.daily(now)
    assert out["slippage"]["books"]["P_pool0_wait|b60"]["trades"] == 1
    md = (files / "reports" / "pumpfun_rt" / "realistic.md").read_text()
    assert "E1 slippage bounds" in md and "| b60 | 1 | 1 |" in md
    assert json.loads((files / "reports" / "pumpfun_rt" / "realistic.json").read_text())["slippage"]
