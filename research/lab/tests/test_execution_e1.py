"""E1's slippage and tip study on synthetic live files: the run past the quote, each limit's counterfactual (a buy
over it fails and pays the 6040 fee), the pre-set pick, the fee terciles, the sandwich check, the replay's bound.

Run from research/lab:  python -m pytest tests/test_execution_e1.py
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from lab.experiments import execution_e1 as e1
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live_exec, realistic
from lab.pumpfun_rt.pipeline import Order

L = e1.LAMPORTS


def test_constants_follow_the_live_bot():
    assert e1.LIVE_LIMIT == live_exec.LIVE_POOL_BUY_TOL == realistic.POOL_BUY_TOL
    assert e1.LIVE_LIMIT in e1.LIMITS and e1.LIVE_LIMIT in e1.REPLAY_LIMITS


def live_files(buys):
    """measured, orders and ledger rows of pool buys given as (asked tokens, got tokens, pnl SOL, stake SOL)."""
    measured, orders, ledger = [], [], []
    for i, (want, got, pnl, stake) in enumerate(buys):
        sig, t = f"s{i}", 1_000_000 + i * 60_000
        orders.append({"what": "sent", "side": "buy", "sig": sig, "tokens": want, "mint": f"m{i}"})
        measured.append({"what": "fill", "side": "buy", "venue": "pool", "sig": sig, "mint": f"m{i}", "land_ms": t,
                         "tokens": got, "slip": 0.0, "send_to_land_ms": 500, "lat_ms": 5_000, "sol_l": int(stake * L)})
        measured.append({"what": "fee", "sig": sig, "fee_l": 100_000})
        ledger.append({"mint": f"m{i}", "land_ms": str(t), "pnl_sol": str(pnl), "stake_sol": str(stake)})
    return measured, orders, ledger


def test_pool_buys_run_past_the_quote_and_the_ledger_match():
    m, o, led = live_files([(110, 100, 0.01, 0.1), (100, 100, -0.02, 0.1)])
    m.append({"what": "fill", "side": "buy", "venue": "pool", "sig": "lost", "mint": "x", "land_ms": 5, "tokens": 1})
    m.append({"what": "fill", "side": "sell", "venue": "pool", "sig": "s0", "mint": "m0", "land_ms": 9, "tokens": 1})
    b = e1.pool_buys(m, o, led)
    assert len(b) == 2
    assert b[0]["run"] == pytest.approx(0.10) and b[1]["run"] == 0.0
    assert b[0]["ret"] == pytest.approx(0.1) and b[1]["fee_l"] == 100_000


def test_failed_buys_6040_and_the_pre_send_skip():
    m = [{"what": "failed", "side": "buy", "t": 1, "why": "failed on chain: {'InstructionError': [6, {'Custom': 6040}]}",
          "fee_l": 200_000},
         {"what": "failed", "side": "buy", "t": 2, "why": "price ran away on landing", "fee_l": 300_000},
         {"what": "failed", "side": "buy", "t": 3, "why": "not landed", "fee_l": 0},
         {"what": "failed", "side": "sell", "t": 4, "why": "failed on chain: 6040", "fee_l": 9}]
    s = [{"t": 5, "why": "price ran away (+167 %)"}, {"t": 6, "why": "no pool state"}]
    f = e1.failed_buys(m, s)
    assert [x["kind"] for x in f] == ["6040", "6040", "ran away"]
    assert e1.fail_fee_l(f, []) == 250_000


def test_a_limit_drops_the_buys_over_it_and_charges_the_fee():
    # runs 0 %, 8 %, 25 %, 40 %: the two over 20 % lost, the 8 % one won
    m, o, led = live_files([(100, 100, 0.02, 0.1), (108, 100, 0.03, 0.1), (125, 100, -0.05, 0.1),
                            (140, 100, -0.04, 0.1)])
    b = e1.pool_buys(m, o, led)
    fails = [{"t": 1, "kind": "6040", "fee_l": 100_000}]
    rows = {r["limit"]: r for r in e1.limit_rows(b, fails, limits=(0.05, 0.20, 0.60), boot=50)}
    fee = 100_000 / L
    assert rows[0.60]["dropped"] == 0 and rows[0.60]["pnl_sol"] == pytest.approx(-0.04 - fee)
    r = rows[0.20]
    assert r["dropped"] == 2 and r["missed"] == 0 and r["avoided_sol"] == pytest.approx(0.09)
    assert r["pnl_sol"] == pytest.approx(0.02 + 0.03 - 2 * fee - fee)
    assert r["mean_sol"] == pytest.approx(r["pnl_sol"] / 5)          # four buys and the live failure
    assert r["d_mean_sol"] == pytest.approx((0.09 - 2 * fee) / 5)
    r = rows[0.05]
    assert r["missed"] == 1 and r["missed_sol"] == pytest.approx(0.03) and r["missed_share"] == pytest.approx(0.6)


def test_the_pick_needs_both_halves_and_few_missed_winners():
    rows = [{"limit": 0.05, "missed_share": 0.3, "d_half1": 1, "d_half2": 1, "mean_sol": 9},
            {"limit": 0.20, "missed_share": 0.05, "d_half1": 1, "d_half2": 1, "mean_sol": 2},
            {"limit": 0.30, "missed_share": 0.0, "d_half1": 0, "d_half2": 5, "mean_sol": 3},
            {"limit": 0.60, "missed_share": 0.0, "d_half1": 0, "d_half2": 0, "mean_sol": 1}]
    assert e1.pick(rows)["limit"] == 0.20
    assert e1.pick([rows[0], rows[2], rows[3]]) is None


def test_run_buckets():
    b = [{"run": -0.01, "ret": -0.2}, {"run": 0.03, "ret": 0.1}, {"run": 0.04, "ret": 0.3}, {"run": 0.5, "ret": -0.4}]
    r = {x["lo"]: x for x in e1.run_buckets(b)}
    assert r[0.0]["n"] == 2 and r[0.0]["mean"] == pytest.approx(0.2) and r[0.0]["win"] == 1.0
    assert r[0.3]["n"] == 1 and r[0.1]["n"] == 0 and r[0.1]["mean"] is None


def test_fee_terciles_leave_out_the_fixed_fee():
    xs = [{"fee_l": 10_000 * (i + 1), "send_ms": 1_000 - 10 * i} for i in range(30)]
    xs += [{"fee_l": 1_005_000, "send_ms": 1} for _ in range(10)]
    f = e1.fee_rows(xs)
    assert f["n"] == 30 and len(f["rows"]) == 3
    assert f["rho"] == pytest.approx(-1.0)
    assert f["rows"][0]["fee_hi"] < f["rows"][1]["fee_lo"]
    assert e1.fee_rows(xs[:5])["rows"] == []
    assert e1.fee_share(100_000, 5_000, 0.1) == pytest.approx(2 * 105_000 / L / 0.1)


def row(t, slot, tx, mint, buy, user, base=1):
    return {"t": t, "slot": slot, "tx": tx, "mint": mint, "buy": buy, "user": user, "base": base}


def test_sandwich_needs_both_legs_around_ours():
    amm = [row(0, 10, 1, "a", True, "bot"), row(0, 10, 2, "a", True, "me"), row(0, 11, 1, "a", False, "bot"),
           row(0, 20, 1, "b", True, "x"), row(0, 20, 2, "b", True, "me"), row(0, 25, 1, "b", False, "x"),
           row(0, 30, 2, "c", False, "me"), row(0, 30, 3, "c", True, "y"), row(0, 30, 1, "c", True, "y")]
    s = e1.sandwiches(amm, "me")
    assert s["buy"] == {"n": 2, "front": 2, "sandwich": 1}      # b's back leg comes 5 slots later: not counted
    assert s["sell"] == {"n": 1, "front": 0, "sandwich": 0}      # y bought before and after: not a sandwich


def test_own_wallet_from_the_fills():
    fills = [{"venue": "pool", "side": "buy", "mint": "a", "tokens": 1_000, "land_ms": 10_000},
             {"venue": "pool", "side": "sell", "mint": "a", "tokens": 1_000, "land_ms": 50_000},
             {"venue": "curve", "side": "buy", "mint": "b", "tokens": 7, "land_ms": 1}]
    amm = [row(12_000, 1, 1, "a", True, "me", 1_005), row(11_000, 1, 2, "a", True, "other", 2_000),
           row(52_000, 2, 1, "a", False, "me", 1_000), row(1, 1, 1, "b", True, "curve", 7)]
    assert e1.own_wallet(fills, amm) == "me"
    assert e1.own_wallet([], amm) is None


def test_pool_tol_is_restored():
    old = realistic.POOL_BUY_TOL
    with pytest.raises(ValueError):
        with e1.pool_tol(0.05):
            assert realistic.POOL_BUY_TOL == 0.05
            raise ValueError
    assert realistic.POOL_BUY_TOL == old


def test_the_replay_executor_applies_its_limit_before_the_send():
    """A pool whose price ran 10 % between the signal and the send: skipped at 5 %, sent at 60 % with the bound
    from the signal's quote."""
    base, quote, stake = 10 ** 15, 100 * L, L // 10
    want = C.pool_buy(stake, base, quote, 100)
    tok = SimpleNamespace(pb=int(base / 1.10), pq=int(quote * 1.10 ** 0), amm_fee_bps=100)

    def ex(tol):
        calls = []
        x = e1.tol_executor(realistic.Model(realistic.Fit(), realistic.LiveConfig()), tol)  # not the live bot's files
        x.pipe = SimpleNamespace(eng=SimpleNamespace(tokens={"m": tok}, push=lambda *a: calls.append(("push", a))),
                                 buy_failed=lambda pid, at, why, fee: calls.append(("failed", why, fee)),
                                 skip=lambda *a: calls.append(("skip",) + a),
                                 strat_of=lambda pid: SimpleNamespace(name="s"))
        o = Order(1, "buy", "m", "pool", want, int(stake * 1.3), 0, stake_l=stake)
        x._presend(5, (o, 9))
        return calls
    a = ex(0.05)
    assert a[0][0] == "failed" and a[0][1].startswith("price ran away (+") and a[0][2] == 0
    b = ex(0.60)
    assert [c[0] for c in b] == ["push"]
    o = b[0][1][2][2][1]
    assert o.least == max(int(C.pool_buy(stake, tok.pb, tok.pq, 100) / 1.6), int(want / 1.6))
    assert realistic.POOL_BUY_TOL == e1.LIVE_LIMIT


def test_each_limit_executor_carries_its_own_bound():
    """RealExecutor reads its class's buy_tol, so a limit executor sets its own there (patching the module's
    POOL_BUY_TOL alone ran every limit at the live 0.60); the plain executor keeps the live bound."""
    m = realistic.Model(realistic.Fit(), realistic.LiveConfig())
    a, b = e1.tol_executor(m, 0.05), e1.tol_executor(m, 1.00)
    assert (a.buy_tol, b.buy_tol) == (0.05, 1.00)
    assert realistic.RealExecutor(m).buy_tol == realistic.POOL_BUY_TOL == e1.LIVE_LIMIT


def test_replay_rows_count_missed_winners():
    ent = {"0.60": [{"mint": "a", "pnl_sol": 0.05, "ret": 0.5, "failed": False},
                    {"mint": "b", "pnl_sol": 0.01, "ret": 0.1, "failed": False},
                    {"mint": "c", "pnl_sol": -0.08, "ret": -0.8, "failed": False}],
           "0.10": [{"mint": "a", "pnl_sol": 0.05, "ret": 0.5, "failed": False},
                    {"mint": "b", "pnl_sol": 0.0, "ret": 0.0, "failed": True, "why": "price ran away"},
                    {"mint": "c", "pnl_sol": -0.0003, "ret": -0.003, "failed": True,
                     "why": "price ran away on landing"}]}
    r = {x["limit"]: x for x in e1.replay_rows(ent)}
    assert r[0.6]["missed"] == 0 and r[0.6]["pnl_sol"] == pytest.approx(-0.02)
    assert r[0.1]["trades"] == 1 and r[0.1]["ran_away"] == 1 and r[0.1]["on_landing"] == 1
    assert r[0.1]["missed"] == 1 and r[0.1]["missed_share"] == pytest.approx(0.01 / 0.06)
    assert r[0.1]["mean_sol"] == pytest.approx((0.05 - 0.0003) / 3)


def test_run_and_report_on_a_folder(tmp_path, monkeypatch):
    m, o, led = live_files([(100, 100, 0.02, 0.1), (140, 100, -0.05, 0.1)] * 3)
    d = tmp_path / "live"
    d.mkdir()
    (d / "measured.jsonl").write_text("\n".join(json.dumps(x) for x in m) + "\nnot json\n")
    (d / "orders.jsonl").write_text("\n".join(json.dumps(x) for x in o) + "\n")
    with (d / "ledger.csv").open("w") as fh:
        fh.write("mint,land_ms,pnl_sol,stake_sol\n" + "".join(
            f"{r['mint']},{r['land_ms']},{r['pnl_sol']},{r['stake_sol']}\n" for r in led))
    out = e1.run(d, root=tmp_path / "none", log=lambda *a: None)
    assert out["buys"] == 6 and out["pick"] == pytest.approx(0.30)      # the loosest of the equal limits
    p = tmp_path / "r.md"
    p.write_text("# head\n\nkept text\n")
    e1.write(out, p)
    e1.write(out, p)
    t = p.read_text()
    assert t.count(e1.MARKER) == 1 and "kept text" in t and "**30 %**" in t
    assert "\u2014" not in t
