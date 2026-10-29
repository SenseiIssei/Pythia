"""E2, entry filters for P_pool0 (entry_e2): the registered trials and latency, the curve record at the signal
(the completing transaction and the idle time before it, wash transactions, early wallets linked by transaction or
slot and their drop, the snipers' share along the path), a failed buy's path kept, the late entry (F5), the regime
and its clustering test (F4), the filters, the band of the difference of means, the in-sample fit and the whole
evaluation on synthetic recordings. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_entry_e2.py
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import entry_e2 as E2
from lab.pumpfun_rt import flowexit as FX
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt.tokens import SUPPLY
from test_pumpfun_exit_runners import BASE0, QUOTE0
from test_pumpfun_rt import BUYERS, MINT, POOL, SOL, T0, Curve, Fixed


# ---------------------------------------------------------------- what the prereg says

def test_the_trials_latency_and_grids_are_the_registered_ones():
    ids = [t["id"] for t in E2.trials()]
    assert len(ids) == 29 and len(set(ids)) == 29 and all(i.startswith("pumpfun:entry_e2:") for i in ids)
    assert {t["family"] for t in E2.trials()} == {"pumpfun"} and all(t["sharpe"] is None for t in E2.trials())
    assert len(E2.LIVE_BUY_MS) == 34 and len(E2.LIVE_SELL_MS) == 34 and E2.LIVE_BUY_MS[-1] == -59
    c = E2.costs()
    assert c.tx_lamports() == E2.LIVE_FEE_L and min(c.latency("P_pool0", f"m{i}", "buy") for i in range(200)) >= 200
    assert len(E2.F1_GRID) == 19 and (None, None) not in E2.F1_GRID
    assert E2.F5_D == (0, 5, 15, 30, 60, 120) and E2.F5_Q == (25, 50, 75) and len(E2.F5_CELLS) == 18
    assert E2.F2_DROP == FX.SL == 0.20 and E2.KEEP_MIN == 0.30 and E2.OOS_FROM == "2026-10-24"
    late = (max(E2.F5_D) + 60 + FX.TIME_S + 60) * 1000          # a 120 s late entry, its buy, 300 s, its sale
    assert E2.TAIL_MS >= late and E2.PATH_MS >= late
    assert E2.SIZINGS["live"] == P.Limits(0.05, 1, 0.6, 0.12) and E2.SIZINGS["wide"] == P.Limits(0.1, 4, 0.6, 1.0)


# ---------------------------------------------------------------- the curve as the record holds it

def test_wash_transactions_and_linked_groups():
    assert E2.washes({"a": [100, 95], "b": [100, 80], "c": [100, 0], "": [5, 5]}) == 1
    g = E2.link_groups([(1, 10, "a"), (1, 10, "b"), (2, 11, "c"), (3, 11, "d"), (4, 12, "e"), (5, 13, "a")])
    assert sorted(sorted(x) for x in g) == [["a", "b"], ["c", "d"]]          # e alone is not a group
    g = E2.link_groups([(1, 10, "a"), (2, 10, "b"), (2, 11, "c"), (3, 12, "d")])
    assert sorted(sorted(x) for x in g) == [["a", "b", "c"]]                  # chained: slot then transaction
    assert E2.link_drop(100.0, 0.0) == 0.0 and E2.link_drop(100.0, 100.0) == pytest.approx(0.75)
    assert E2.link_drop(100.0, 100 / math.sqrt(0.8) - 100) == pytest.approx(0.20)


def e2_engine():
    s = dataclasses.replace(P.BY_NAME["P_pool0"], name="P_pool0@N", p={"delay_s": 0, "base": "P_pool0"},
                            stake_sol=E2.STAKE_SOL)
    eng = E2.E2Engine([], costs=Fixed(), rule_costs={s.name: Fixed()})
    pipe = eng.add_pipe(E2.E2Pipe(eng, s, {}))
    return eng, pipe


def farmed(eng, gap=False):
    """A curve with a bundle (two wallets in one transaction), two wallets in one slot, a wash transaction, an idle
    stretch and a large completing buy, then its pool and the migration at T0."""
    t = T0 - 120_000
    c = Curve(eng, t=t, slot=1000)
    tok = {}
    tok[0] = c.buy(t + 500, SOL, BUYERS[0])
    tok[1] = c.buy(t + 500, SOL, BUYERS[1], same_tx=True)        # one transaction
    tok[2] = c.buy(t + 1_000, SOL // 2, BUYERS[2])
    c.tx += 1
    tok[3] = c.buy(t + 1_000, SOL // 2, BUYERS[3], same_tx=True)  # the same slot, another transaction
    w = c.buy(t + 5_000, SOL, BUYERS[5])
    c.tx -= 1
    c.slot -= 1
    c.sell(t + 5_000, w, BUYERS[5])                              # bought and sold back in one transaction
    c.buy(t + 60_000, SOL, BUYERS[6])
    if gap:
        eng.gap(t + 70_000, t + 80_000)
    c.buy(T0 - 1_000, 20 * SOL, BUYERS[7])                       # 59 s idle, then a 20 SOL completing buy
    eng.complete(T0, MINT)
    eng.amm(T0, MINT, True, int(BASE0 * SOL // 1000 / (QUOTE0 + SOL // 1000)), SOL // 1000, BASE0, QUOTE0, 20, 5, 5,
            slot=5000, user=BUYERS[9])
    eng.migrate(T0, MINT, POOL, 85 * SOL, BASE0)
    return c, tok


def test_the_features_at_the_signal_and_the_snipers_along_the_path():
    eng, pipe = e2_engine()
    c, tok = farmed(eng)
    eng.advance(T0 + 1_000 + E2.PATH_MS + 10_000)
    assert len(pipe.paths) == 1 and not pipe.recs
    d = pipe.paths[0]
    f = d["feat"]
    assert f["curve_seen"] and not f["idle_gap"] and f["idle_s"] == pytest.approx(59.0)
    assert f["done_share"] == pytest.approx(20 * SOL / c.rs) and f["wash_n"] == 1.0
    assert f["link_n"] == 2 and f["early_n"] == 5                # B0..B3 and B5 within 30 s
    x = float(d["sig_pb"])
    h = float(tok[0] + tok[1])                                   # the bundle holds more than the slot pair
    assert f["link_h"] == pytest.approx(h / SUPPLY) and f["link_drop"] == pytest.approx(1 - (x / (x + h)) ** 2)
    assert f["snip_known"] and d["snip"][0] == pytest.approx(sum(tok.values()) / SUPPLY, rel=1e-6)
    assert "X" not in d and len(d["snip"]) == len(d["t"]) == len(d["fee0"]) and d["land_ms"] == T0 + 1_000
    assert d["t"][-1] <= d["land_ms"] + E2.PATH_MS and not d["x0_failed"]


def test_a_gap_before_the_completing_buy_leaves_the_idle_time_unknown():
    eng, pipe = e2_engine()
    farmed(eng, gap=True)
    f = E2.curve_features(eng, eng.tokens[MINT])
    assert f["idle_gap"] and math.isnan(f["idle_s"]) and f["wash_n"] == 1.0
    assert E2.keeps("F1", (60.0, None), f)                       # an unknown idle time never skips


def test_a_failed_buy_keeps_its_path_from_the_signal():
    eng, pipe = e2_engine()
    farmed(eng)
    eng.advance(T0 + 400)                                        # the signal at T0, the buy in flight
    tok = eng.tokens[MINT]
    sol = 60 * SOL                                               # the price runs away before it lands
    eng.amm(T0 + 500, MINT, True, int(tok.pb * sol / (tok.pq + sol)), sol, tok.pb, tok.pq, 20, 5, 5, slot=5001,
            user=BUYERS[8])
    eng.advance(T0 + 1_500)
    assert pipe.failed and pipe.failed[0]["why"] == "slippage" and next(iter(pipe.recs.values())).x0_failed
    eng.advance(T0 + 1_000 + E2.PATH_MS + 10_000)
    assert len(pipe.paths) == 1 and pipe.paths[0]["x0_failed"] and pipe.paths[0]["land_ms"] is None


def test_the_curve_record_is_dropped_with_the_coin():
    eng, _ = e2_engine()
    Curve(eng, t=T0, slot=1000).buy(T0 + 100, SOL, BUYERS[0])
    assert MINT in eng.curve
    del eng.tokens[MINT]
    eng._a_evict(T0 + 10 ** 9, MINT)
    assert MINT not in eng.curve


# ---------------------------------------------------------------- the late entry (F5)

def rec(prices, snip=None, t0=None, mint="m", fail_at=None, x0_failed=False):
    """A recorded signal: a pool of 1e15 tokens priced by `prices` at 1 s steps from the signal."""
    t0 = t0 if t0 is not None else T0
    n = len(prices)
    t = np.asarray([t0 + 1_000 * i for i in range(n)], dtype=float)
    x = np.full(n, 1e15)
    y = np.asarray(prices, dtype=float) * 1e11
    d = {"t": t, "x": x, "y": y, "dq": np.zeros(n), "amt": np.zeros(n), "fee": np.zeros(n, dtype=np.float32),
         "fee0": np.zeros(n, dtype=np.float32), "buy": np.ones(n, dtype=np.float32),
         "uid": np.arange(n, dtype=np.float32), "slot": np.arange(n, dtype=np.int64), "pid": 0, "mint": mint,
         "symbol": "M", "signal_ms": int(t0), "mig_ms": int(t0), "sig_pb": 1e15, "sig_pq": 1e11, "complete": True,
         "bb_buys": [], "snip": np.asarray(snip if snip is not None else [0.0] * n, dtype=np.float32),
         "feat": {"snip_known": True}, "x0_failed": x0_failed, "land_ms": None, "j_land": 0, "tokens": 0,
         "cost_l": 0, "tx_l": 0}
    if not x0_failed:
        stake = min(int(E2.STAKE_SOL * C.LAMPORTS), int(P.MAX_IMPACT * y[1]))
        d.update(land_ms=int(t0 + 1_000), j_land=1, cost_l=stake, tokens=C.pool_buy(stake, int(x[1]), int(y[1]), 0))
    return d


class One(C.Costs):
    def latency(self, *key):
        return 1000.0


def test_the_late_entry_at_delay_zero_is_x0_and_the_snipers_condition_skips():
    d = rec([1.0, 1.0, 1.0, 1.35, 1.35, 1.35])
    r = E2.late_entry(d, 0.0, None, One(), 0)
    x0 = FX.simulate(FX.Path_(d), lambda leg: 1000.0, 0)
    assert r["ret"] == pytest.approx(x0["pnl_l"] / (E2.STAKE_SOL * C.LAMPORTS)) and r["why"] == "take"
    assert r["mig_ms"] == T0 and r["signal_ms"] == T0 and E2.key(r) == (T0, "m")
    d = rec([1.0] * 8, snip=[0.5, 0.5, 0.3, 0.1, 0.1, 0.1, 0.1, 0.1])
    assert E2.late_entry(d, 0.0, 0.2, One(), 0) is None
    r = E2.late_entry(d, 3_000.0, 0.2, One(), 0)
    assert r is not None and r["signal_ms"] == T0 + 3_000 and r["mig_ms"] == T0 and r["exit_ms"] > T0 + 4_000
    d["feat"] = {"snip_known": False}
    assert E2.late_entry(d, 3_000.0, 0.2, One(), 0) is None and E2.late_entry(d, 3_000.0, None, One(), 0)


def test_the_late_entry_fails_when_the_price_runs_away_and_works_after_a_failed_x0():
    d = rec([1.0, 1.0, 1.0, 3.0, 3.0, 3.0], x0_failed=True)
    r = E2.late_entry(d, 2_000.0, None, One(), 7_000)
    assert r["failed"] and r["why"] == "failed buy" and r["pnl_l"] == -7_000
    d = rec([1.0, 1.0, 1.0, 1.0, 0.7, 0.7, 0.7], x0_failed=True)
    r = E2.late_entry(d, 1_000.0, None, One(), 0)
    assert not r["failed"] and r["why"] == "stop" and r["ret"] < -0.2


# ---------------------------------------------------------------- the regime (F4)

def xrow(ret, day, why=None, i=0, t=None, mint=None):
    s = FX._utc(2026, 10, day, 12) + 60_000 * i if t is None else t
    return {"i": i, "mint": mint or f"m{i}", "signal_ms": s, "mig_ms": s, "day": FX.day_of(s), "ret": ret,
            "pnl_sol": ret * 0.05, "why": why or ("stop" if ret < 0 else "take"), "exit_ms": s + 30_000, "legs": 1,
            "failed": False, "hold_s": 30.0, "best_l": 1e7, "pnl_l": ret * 0.05 * C.LAMPORTS, "gapped": False}


def test_the_regime_reads_only_closed_entries():
    rows = [xrow(-0.2 if i < 3 else 0.1, 21, i=i) for i in range(6)]
    mig = [rows[0]["signal_ms"] - 10_000, rows[0]["signal_ms"] - 4_000_000]
    reg = E2.regime(rows, mig, n_list=(2,))
    assert math.isnan(reg[E2.key(rows[0])]["stop_rate_2"]) and math.isnan(reg[E2.key(rows[1])]["stop_rate_2"])
    assert reg[E2.key(rows[2])]["stop_rate_2"] == 1.0 and reg[E2.key(rows[5])]["stop_rate_2"] == 0.0
    assert reg[E2.key(rows[0])]["mig_1h"] == 1.0 and reg[E2.key(rows[3])]["lost_3"] and reg[E2.key(rows[3])]["lost_1"]
    assert not reg[E2.key(rows[5])]["lost_1"]


def test_the_runs_test_and_the_cluster_gate():
    alt = E2.runs_test(np.array([i % 2 == 0 for i in range(40)]))
    assert alt["runs"] == 40 and alt["p"] > 0.99
    blk = E2.runs_test(np.array([i < 20 for i in range(40)]))
    assert blk["runs"] == 2 and blk["p"] < 0.001
    rows = [xrow(0.1 if (i // 10) % 2 else -0.2, 21, i=i) for i in range(60)]
    reg = E2.regime(rows, [])
    assert E2.cluster_test(rows, reg)["clusters"]
    rows = [xrow(0.1 if i % 2 else -0.2, 21, i=i) for i in range(60)]
    ct = E2.cluster_test(rows, E2.regime(rows, []))
    assert ct["runs"]["p"] > 0.5 and set(ct["after_losses"]) == {1, 2, 3}


# ---------------------------------------------------------------- filters, band, fit

def test_the_filters_keep_or_skip_and_a_missing_feature_never_skips():
    f = {"idle_s": 400.0, "done_share": 0.15, "wash_n": 3.0, "link_drop": 0.3, "stop_rate_20": 0.55}
    assert not E2.keeps("F1", (300.0, None), f) and E2.keeps("F1", (1800.0, None), f)
    assert not E2.keeps("F1", (None, 0.1), f) and E2.keeps("F1", (1800.0, 0.2), f)
    assert not E2.keeps("F2", None, f) and E2.keeps("F2", None, {"link_drop": 0.2})
    assert not E2.keeps("F3", 2, f) and E2.keeps("F3", 5, f)
    assert not E2.keeps("F4", (20, 0.5), f) and E2.keeps("F4", (20, 0.6), f)
    for v, th in (("F1", (60.0, 0.05)), ("F2", None), ("F3", 1), ("F4", (20, 0.4))):
        assert E2.keeps(v, th, {}) and E2.keeps(v, th, {"idle_s": math.nan, "link_drop": None})


def test_the_band_of_the_difference_of_means_and_the_rule():
    base = [xrow(-0.2 if (i // 6) % 3 == 0 else 0.1, 24 + i % 6, i=i) for i in range(120)]
    kept = [x for x in base if x["ret"] > 0 or (x["i"] // 6) % 2]   # drops half the losers, every day alike
    j = E2.judge(kept, base)
    assert j["diff"] == pytest.approx(np.mean([x["ret"] for x in kept]) - np.mean([x["ret"] for x in base]))
    assert j["band"][0] > 0 and j["kept_enough"] and j["passes"] and j["skipped_mean"] == pytest.approx(-0.2)
    few = base[:10]
    assert not E2.judge(few, base)["kept_enough"] or not E2.judge(few, base)["passes"]
    four = [x for x in base if x["day"] < "2026-10-28"]
    assert math.isnan(E2.judge(four, four)["band"][0]) and not E2.judge(four, four)["passes"]


def test_the_fit_needs_thirty_percent_kept():
    base = [xrow(0.1 * (i % 5) - 0.1, 21, i=i) for i in range(50)]
    rows = {1: base[:10], 2: base[:20], 3: [x for x in base if x["ret"] >= 0]}
    th, grid = E2.fit((1, 2, 3), lambda g: rows[g], base)
    assert th == 3 and grid[0][2] == 0.2
    assert E2.fit((1,), lambda g: rows[g], base)[0] is None


# ---------------------------------------------------------------- the whole evaluation

def test_the_evaluation_on_synthetic_recordings(monkeypatch):
    monkeypatch.setattr(E2, "costs", lambda: One())             # the recordings' own landing, 1 s after the signal
    recs, k = [], 0
    for day in range(20, 30):
        for j in range(8):
            t0 = FX._utc(2026, 10, day, 1) + 900_000 * j
            run = [1.0, 1.0, 1.0] + ([1.35] * 4 if (j + day) % 3 else [0.7] * 4)
            d = rec(run, snip=[0.05 * (j % 4)] * len(run), t0=t0, mint=f"m{k}")
            d["feat"] = {"snip_known": True, "idle_s": 10.0 * j, "done_share": 0.05 * j, "wash_n": float(j % 3),
                         "link_drop": 0.1 * (j % 4), "curve_seen": True, "link_n": 2}
            recs.append(d)
            k += 1
    res = {"recs": recs, "failed": [], "tx_l": 1_000, "gaps": [], "mig_ms": [r["signal_ms"] for r in recs],
           "days": ["2026-10-20"], "span": (recs[0]["signal_ms"], recs[-1]["signal_ms"]),
           "entry_until_ms": recs[-1]["signal_ms"]}
    ev = E2.evaluate(res, log=lambda *a: None)
    assert ev["entries"] == 80 and ev["oos"] == 48 and ev["f5"]["x0_check"]["match"] == 1.0
    assert set(ev["filters"]) == set(E2.FILTERS) and set(ev["f5"]["cells"]) == set(E2.F5_CELLS + E2.F5_ALL)
    assert ev["f5"]["pick"] is None or ev["f5"]["pick"] in E2.F5_CELLS
    assert ev["filters"]["F2"]["ran"] and ev["filters"]["F2"]["theta"] is None
    assert "F4 test" in E2.report_md(res, ev) and "| X0 (P_pool0) |" in E2.report_md(res, ev)
