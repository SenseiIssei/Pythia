"""Live twin (results/pumpfun_live_twin_prereg.md): a synthetic live trade whose twin is known exactly leaves no
residual, a planted latency gap shows up in the entry latency part, the leave-one-day-out fit never sees the judged
day, every miss is named, the parts add up to the total, the day-clustered band and the haircut, the live trades'
stake and exit decision from the orders, the record read for the live coins only on the slot clock, the trials.
No network, no wallet, nothing live written.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_twin_replay.py
"""

from __future__ import annotations

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from lab import metrics
from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import events as E
from lab.pumpfun_rt import live_twin as LT
from lab.pumpfun_rt import realistic as R
from lab.pumpfun_rt import store
from test_pumpfun_exit_runners import Pool
from test_pumpfun_rt import BUYERS, MINT, SOL, T0, Curve, key

DAY = LT.day_of(T0)
STAKE = int(0.05 * SOL)


def fixed_fit(buy=5_000.0, sell=4_000.0, send=500.0) -> R.Fit:
    return R.Fit(R.Empirical((buy,)), R.Empirical((sell,)), R.Empirical((send,)), 200_000, 5_000, {})


def live(i=0, rule="P_pool0", mint=MINT, sig=T0 + 1_000, **kw) -> dict:
    return {"i": i, "rule": rule, "mint": mint, "symbol": "TST", "day": LT.day_of(sig), "signal_ms": sig,
            "land_ms": sig + 5_000, "exit_ms": sig + 310_000, "xdec_ms": sig + 306_000, "entry_price": 1.0,
            "exit_price": 1.0, "ret": 0.0, "stake_l": STAKE, "stake_src": "order", "exit_why": "time", **kw}


def flat(rp, until=T0 + 400_000):
    pool = Pool(rp.eng)
    for j, t in enumerate(range(T0 + 2_000, until, 1_000)):
        if j % 2 == 0:
            before = pool.pb
            pool.trade(t, True, sol=SOL // 100)
            got = before - pool.pb
        else:
            pool.trade(t, False, base=got)
    return pool


def rising(rp, step=1.002, until=T0 + 400_000):
    pool, states = Pool(rp.eng), []
    for t in range(T0 + 2_000, until, 1_000):
        pool.trade(t, True, sol=int(pool.pq * (step ** 0.5 - 1)))
        states.append((t, pool.pb, pool.pq))
    return pool, states


def one(trades, fit_=None, feed=flat, until=T0 + 500_000):
    rp = LT.Replay(trades, {d: fit_ or fixed_fit() for d in {t["day"] for t in trades}})
    feed(rp)
    return rp, rp.finish(until)


# ---------------------------------------------------------------- the twin, exactly

def test_a_live_trade_whose_twin_is_known_exactly_leaves_no_residual():
    rp, (r,) = one([live()])
    assert r["twin"] and r["twin_how"] == "bought" and r["twin_exit_why"] == "time"
    d = rp.books[DAY].done[0]
    # the fit's 5 s: the buy lands at signal + 5 s (T0 + 6 s) and fills at the next recorded trade (one a second)
    assert d["land_ms"] == T0 + 7_000 and d["cost_l"] == STAKE
    # the time stop 300 s after the fill, the sale landing 4 s later and filled at the next trade
    assert d["exit_signal_ms"] == T0 + 307_000 and d["at"] == T0 + 312_000
    e = (d["cost_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
    x = (d["proceeds_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
    twin_ret = (d["proceeds_l"] - d["cost_l"] - d["fees_l"]) / STAKE
    assert r["twin_ret"] == pytest.approx(twin_ret)
    # the live trade did exactly that: every part 0, the total 0
    same = live(land_ms=d["land_ms"], xdec_ms=d["exit_signal_ms"], exit_ms=d["at"], entry_price=e, exit_price=x,
                ret=twin_ret)
    _, (z,) = one([same])
    assert z["twin"] and z["parts"]["total"] == pytest.approx(0, abs=1e-12)
    assert all(z["parts"][k] == pytest.approx(0, abs=1e-12) for k in LT.PARTS)


def test_a_planted_latency_gap_shows_up_in_the_latency_part():
    """The price rises 0.2 % a second; live landed 20 s after the twin and paid the pool's price then, sold where the
    twin sold: the difference is the entry latency, the entry price part is only the stake's impact."""
    rp, (r,) = one([live()], feed=rising)
    d = rp.books[DAY].done[0]
    tok_fee = rp.eng.tokens[MINT].amm_fee_bps
    _, states = rising(LT.Replay([], {}))                    # the same pool, for the reserves at the live landing
    land_l = d["land_ms"] + 20_000
    _, pb, pq = next(s for s in states if s[0] >= land_l)
    el = (STAKE / C.LAMPORTS) / (C.pool_buy(STAKE, pb, pq, tok_fee) / C.TOKEN_UNIT)
    et = (d["cost_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
    xt = (d["proceeds_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
    tret = (d["proceeds_l"] - d["cost_l"] - d["fees_l"]) / STAKE
    lret = tret + (xt / el - xt / et)                         # the same sale and costs, the later fill
    _, (z,) = one([live(land_ms=land_l, xdec_ms=d["exit_signal_ms"], exit_ms=d["at"], entry_price=el,
                        exit_price=xt, ret=lret)], feed=rising)
    p = z["parts"]
    assert el > et * 1.03 and p["total"] < -3                  # 20 s of +0.2 % a second, paid
    assert p["latency"] == pytest.approx(p["total"], rel=0.02)
    assert abs(p["entry"]) < 0.02 * abs(p["latency"])
    assert p["exit_time"] == pytest.approx(0, abs=1e-12) and p["exit"] == pytest.approx(0, abs=1e-12)
    assert p["fees"] == pytest.approx(0, abs=1e-9) and p["failed"] == 0
    assert sum(p[k] for k in LT.PARTS) == pytest.approx(p["total"], abs=1e-9)


def test_the_parts_add_up_to_the_total_and_a_twin_that_did_not_buy_is_a_failed_buy():
    path = [(0.0, 1.0), (10.0, 1.1), (20.0, 1.3), (30.0, 0.9)]
    lv = {"entry_price": 1.2, "exit_price": 0.95, "ret": -0.25, "land_ms": 20.0, "xdec_ms": 30.0}
    tw = {"bought": True, "ret": 0.1, "E": 1.1, "X": 1.25, "land_ms": 10.0, "xdec_ms": 25.0}
    p = LT.parts(lv, tw, path)
    assert sum(p[k] for k in LT.PARTS) == pytest.approx(p["total"]) == pytest.approx(-35.0)
    assert p["latency"] < 0 and p["failed"] == 0
    f = LT.parts(lv, {"bought": False, "ret": -0.004}, path)
    assert f["failed"] == pytest.approx(f["total"]) == pytest.approx(-24.6)
    assert all(f[k] == 0 for k in LT.PARTS if k != "failed")


# ---------------------------------------------------------------- the fit, out of fit

def test_the_leave_one_day_out_fit_never_sees_the_judged_day():
    rows = []
    for d, lat in ((0, 1_000.0), (1, 99_000.0), (2, 2_000.0)):
        for i in range(35):
            t = T0 + d * R.DAY_MS + i
            rows += [{"t": t, "what": "fill", "mode": "test", "side": "buy", "lat_ms": lat + i, "send_to_land_ms": 400},
                     {"t": t, "what": "fill", "mode": "test", "side": "sell", "lat_ms": lat / 2 + i}]
    rows.append({"t": T0, "what": "fill", "mode": "paper", "side": "buy", "lat_ms": 7e6})   # not a live mode
    days = [LT.day_of(T0 + d * R.DAY_MS) for d in range(3)]
    fits = LT.lodo_fits(rows, days)
    judged = fits[days[1]]
    assert judged.live["buys"] == 70 and max(judged.buy.ms) < 3_000           # day 2's 99 s never in its own fit
    assert all(max(fits[d].buy.ms) >= 99_000 for d in (days[0], days[2]))      # but in the other days' fits
    assert all(max(f.buy.ms) < 7e6 for f in fits.values())
    rp = LT.Replay([live(sig=T0 + R.DAY_MS + 1_000)], fits)
    assert rp.books[days[1]].exec.model.fit is judged


# ---------------------------------------------------------------- the misses, named

def test_every_live_trade_without_a_twin_has_its_reason(monkeypatch):
    trades = [live(0, mint=key(77)),                                     # never recorded
              live(1, mint=key(78), sig=T0 + 1_000),                     # a curve that never migrated
              live(2, sig=T0 + 1_000),                                   # a gap over the twin's landing
              live(3, sig=T0 + 200_000)]                                 # still open when the record ends
    rp = LT.Replay(trades, {DAY: fixed_fit()})
    Curve(rp.eng, mint=key(78), t=T0 - 60_000, slot=10)
    flat(rp, until=T0 + 300_000)
    rp.gaps[E.PUMP_AMM].append((T0 + 5_500, T0 + 7_000))
    res = {r["i"]: r for r in rp.finish(T0 + 300_000)}
    assert [res[i]["why"] for i in range(4)] == [LT.NOT_RECORDED, LT.NO_POOL, LT.GAP, LT.OPEN]
    assert not any(res[i]["twin"] for i in range(4))
    # a gap of the other program, or short and away from every moment, is no reason
    rp = LT.Replay([live()], {DAY: fixed_fit()})
    flat(rp)
    rp.gaps[E.PUMP].append((T0, T0 + 400_000))
    rp.gaps[E.PUMP_AMM].append((T0 + 100_000, T0 + 101_000))
    (r,) = rp.finish(T0 + 500_000)
    assert r["twin"] and not r["no_gap"] and 0 < r["gap_share"] < LT.GAP_SHARE
    monkeypatch.setattr(R, "tainted", lambda row: True)                  # P1's rule on the twin's closed row
    _, (t,) = one([live()])
    assert not t["twin"] and t["why"] == LT.TAINT


def test_a_coin_the_record_holds_late_is_twinned_on_the_records_clock():
    """The record has the migration 8 s after the live signal: the twin signals then, and the live times move by the
    lag onto the record's clock (the same trade a lag later is no difference). P_pool0_wait waits for the pool's
    first recorded trade as the rule does."""
    rp, (r,) = one([live(sig=T0 - 7_000)])                    # the pool migrates at T0 in the record
    assert r["twin"] and 7_000 <= r["offset_ms"] < 7_000 + LT.POLL_MS
    assert rp.books[DAY].done[0]["signal_ms"] == T0 - 7_000 + r["offset_ms"]
    d = rp.books[DAY].done[0]
    off = r["offset_ms"]
    e = (d["cost_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
    x = (d["proceeds_l"] / C.LAMPORTS) / (d["tokens"] / C.TOKEN_UNIT)
    ret = (d["proceeds_l"] - d["cost_l"] - d["fees_l"]) / STAKE
    same = live(sig=T0 - 7_000, land_ms=d["land_ms"] - off, xdec_ms=d["exit_signal_ms"] - off, exit_ms=d["at"] - off,
                entry_price=e, exit_price=x, ret=ret)
    _, (z,) = one([same])
    assert all(z["parts"][k] == pytest.approx(0, abs=1e-12) for k in LT.PARTS)

    def pool_late(rp):                                         # migrated without a pool state, its first trade at +3 s
        cv = Curve(rp.eng, mint=MINT, t=T0 - 120_000, slot=10)
        cv.buy(T0 - 100_000, SOL, BUYERS[0])
        rp.eng.complete(T0, MINT)
        rp.eng.migrate(T0, MINT, key(3), 85 * SOL, 206_900_000 * 10 ** 6)
        pool = Pool.__new__(Pool)
        pool.eng, pool.mint, pool.slot, pool.pb, pool.pq = rp.eng, MINT, 60_000, 206_900_000 * 10 ** 6, 67 * SOL
        for t in range(T0 + 3_000, T0 + 400_000, 1_000):
            pool.trade(t, True, sol=SOL // 1000)
    _, (w,) = one([live(rule="P_pool0_wait", sig=T0 + 500)], feed=pool_late)
    _, (n,) = one([live(rule="P_pool0", sig=T0 + 500)], feed=pool_late)
    assert w["twin"] and w["twin_land_ms"] >= T0 + 3_000 + 5_000
    assert not n["twin"] and n["why"] == LT.NO_POOL


def test_a_twin_whose_buy_fails_is_a_twin_under_failed_buys():
    fit_ = fixed_fit()
    fit_.fail = {"not landed": 1.0}
    _, (r,) = one([live(ret=0.1)], fit_=fit_)
    assert r["twin"] and r["twin_how"].startswith("buy failed: not landed") and r["twin_ret"] == 0.0
    assert r["parts"]["failed"] == pytest.approx(10.0) and r["parts"]["total"] == pytest.approx(10.0)


# ---------------------------------------------------------------- the numbers

def fake(day, total, i):
    p = {"latency": total / 2, "entry": total / 4, "exit_time": total / 8, "exit": total / 8, "fees": 0.0,
         "failed": 0.0, "total": total}
    return {"i": i, "rule": "P_pool0_wait", "day": day, "twin": True, "ret": total / 100, "twin_ret": 0.0,
            "parts": p, "no_gap": True, "stake_src": "order", "twin_how": "bought"}


def test_the_day_clustered_band_the_sum_of_the_parts_and_the_haircut():
    res = [fake(f"2026-10-2{d}", -5.0 - d + 0.1 * j, 10 * d + j) for d in range(4) for j in range(5)]
    res.append({"i": 99, "rule": "P_pool0", "day": "2026-10-20", "twin": False, "why": LT.GAP, "ret": 0.0,
                "stake_src": "ledger"})
    c = LT.compute(res)
    a = c["all"]
    assert c["n_twin"] == 20 and c["n_live"] == 21 and c["misses"] == {("P_pool0", LT.GAP): 1}
    assert a["sum"] == pytest.approx(a["mean"]) and a["band"]["total"][1] < 0
    assert a["band"]["total"][0] >= -8.5 and a["band"]["total"][1] <= -4.9         # whole days drawn
    assert c["haircut"] == pytest.approx(a["mean"])
    assert set(c["by_day"]) == {"2026-10-20", "2026-10-21", "2026-10-22", "2026-10-23"}
    assert c["by_day"]["2026-10-20"]["n"] == 5 and c["by_rule"]["P_pool0"]["n"] == 0
    both = LT.compute([fake("2026-10-20", 5.0, 0), fake("2026-10-21", -5.0, 1)])
    assert both["all"]["band"]["total"][0] < 0 < both["all"]["band"]["total"][1] and both["haircut"] is None
    md = LT.markdown(c, {"2026-10-20": fixed_fit()})
    assert "haircut of" in md and "\u2014" not in md


# ---------------------------------------------------------------- the inputs

def test_the_live_trades_take_the_stake_sent_and_the_last_sales_decision():
    ledger = [{"mode": "test", "rule": "P_pool0_wait", "mint": MINT, "symbol": "A", "signal_ms": T0,
               "land_ms": T0 + 9_000, "exit_ms": T0 + 70_000, "entry_price": 2e-6, "exit_price": 1e-6,
               "stake_sol": 0.0717, "ret": -0.5, "buy_sig": "b1"},
              {"mode": "paper", "rule": "P_pool0_wait", "mint": key(5), "signal_ms": T0, "land_ms": T0, "exit_ms": T0,
               "ret": 0.0},
              {"mode": "test", "rule": "P_pool0", "mint": key(6), "signal_ms": T0, "land_ms": T0 + 1, "exit_ms": T0 + 2,
               "entry_price": 1, "exit_price": 1, "stake_sol": 0.02, "ret": 0.0}]
    orders = [{"what": "sent", "side": "buy", "mint": MINT, "t": T0 + 8_000, "limit_l": 91_000_000, "sig": "b1"},
              {"what": "sent", "side": "buy", "mint": MINT, "t": T0 + 1_000, "limit_l": 13_000_000, "sig": "b0"}]
    measured = [{"what": "fill", "side": "sell", "mint": MINT, "signal_ms": T0 + 30_000, "land_ms": T0 + 31_000},
                {"what": "fill", "side": "sell", "mint": MINT, "signal_ms": T0 + 69_000, "land_ms": T0 + 70_000}]
    a, b = LT.live_trades(ledger, orders, measured)
    assert a["stake_l"] == 70_000_000 and a["stake_src"] == "order" and a["xdec_ms"] == T0 + 69_000
    assert b["stake_l"] == int(0.02 * SOL) and b["stake_src"] == "ledger" and b["xdec_ms"] == T0 + 2


def write(root, table, day, rows):
    d = root / table / f"date={day}"
    d.mkdir(parents=True, exist_ok=True)
    sch = store.SCHEMAS[table]
    pq.write_table(pa.Table.from_pylist([{k: r.get(k) for k in sch.names} for r in rows], schema=sch),
                   d / "000000-0.parquet")


def test_the_record_is_read_for_the_live_coins_only_on_the_slot_clock(tmp_path):
    other = key(9)
    write(tmp_path, "amm", DAY, [
        {"t": T0 + 5_000, "slot": 100, "tx": 1, "mint": MINT, "pool": "p", "buy": True, "base": 1, "quote": 1},
        {"t": T0 + 1_000, "slot": 101, "tx": 2, "mint": other, "pool": "q", "buy": True, "base": 1, "quote": 1},
        {"t": T0 + 2_000, "slot": 102, "tx": 3, "mint": MINT, "pool": "p", "buy": False, "base": 1, "quote": 1}])
    write(tmp_path, "other", DAY, [{"kind": "gap", "t": T0 + 9_000, "t0": T0 + 8_000, "user": E.PUMP_AMM},
                                   {"kind": "migrate", "t": T0, "slot": 99, "mint": other, "pool": "q"}])
    got = list(LT.coin_events(DAY, [MINT], tmp_path))
    assert [(tb, r.get("slot"), r["t"]) for tb, r in got] == [
        ("amm", 100, T0 + 1_000),               # slot 100 timed by slot 101, the other coin's, which came first
        ("amm", 102, T0 + 2_000), ("other", None, T0 + 9_000)]
    assert got[0][1]["recv_t"] == T0 + 5_000


def test_the_trials_are_registered_counted_in_family_pumpfun(tmp_path):
    p = tmp_path / "registry.jsonl"
    metrics.register(LT.trials(), p)
    rows = [r for r in metrics._read(p) if r["id"].startswith("pumpfun:live_twin:")]
    assert len(rows) == 5 and {r["family"] for r in rows} == {"pumpfun"}
    assert all(r["sharpe"] is None and r["source"] == LT.PREREG for r in rows)
    assert metrics.trial_pool("pumpfun", path=p)["n_trials"] == 5
