"""X14 r2, an order-flow exit for P_pool0 (flowexit): the registered trials and latencies, the full replay's
recording (every entry, paths from the signal, step rows with the flow features, the inferred buyback buyer), the
path simulator (P_pool0's exits, the take floor, the time stop, an own exit before or after the stop), the exits'
masks, the labels past the latency, the walk-forward, the one-transaction stops, the live stop split, the paired
day band, the verdict and the books. No network, no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_flow_exit_x14r2.py
"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import flowexit as F
from lab.pumpfun_rt import model as M
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from test_pumpfun_exit_runners import Pool
from test_pumpfun_rt import BUYERS, MINT, SOL, T0, Fixed


@pytest.fixture(autouse=True)
def small_models(monkeypatch):
    monkeypatch.setitem(M.PARAMS, "n_estimators", 20)


# ---------------------------------------------------------------- what the prereg says

def test_the_trials_scenarios_and_lags_are_the_registered_ones():
    ids = [t["id"] for t in F.trials()]
    assert len(ids) == 11 and len(set(ids)) == 11 and all(i.startswith("pumpfun:flow_x14r2:") for i in ids)
    assert {t["family"] for t in F.trials()} == {"pumpfun"} and all(t["sharpe"] is None for t in F.trials())
    assert F.VARIANTS == ("X0", "HZ", "F1", "F2", "DAR", "T", "BB") and len(F.LIVE_SELL_MS) == 32
    sc = F.scenarios()
    assert sc["N"].tx_lamports() == F.LIVE_FEE_L and sc["O"].tx_lamports() == 1_005_000
    assert F.lag_ms("N") == 595.0 and F.lag_ms("O") == pytest.approx(4371.0)
    assert sc["N"].sell.lo_ms == 200.0 and min(sc["N"].latency("P_pool0", f"m{i}", "sell") for i in range(200)) >= 200
    assert F.SIZINGS["live"] == P.Limits(0.05, 1, 0.6, 0.12) and F.SIZINGS["wide"].capped() == F.SIZINGS["wide"]
    s = P.BY_NAME["P_pool0"].exits
    assert (s.ladder, s.sl, s.time_s, s.dev_sell, s.pull) == (((F.TP, 1.0),), F.SL, F.TIME_S, False, False)


def test_every_entry_is_a_study_only_risk():
    r = F.EveryEntry(P.Limits(0.05, 1, 0.6, 0.12))
    assert r.why_not(T0, 10 ** 12) is None
    r.booked(T0, -10 ** 12)
    assert r.why_not(T0, 10 ** 9) is None and P.Risk(P.Limits(0.05, 1, 0.6, 0.12)).why_not(T0, 10 ** 12)
    assert not any(isinstance(x, F.EveryEntry) for p in [] for x in p)       # no paper book builds one


# ---------------------------------------------------------------- the recording

def flow_engine():
    s = dataclasses.replace(P.BY_NAME["P_pool0"], name="P_pool0@N", p={"delay_s": 0, "base": "P_pool0"},
                            stake_sol=F.STAKE_SOL)
    eng = sim.Engine([], costs=Fixed(), rule_costs={s.name: Fixed()})
    pipe = eng.add_pipe(F.FlowPipe(eng, s, {}))
    return eng, pipe


def test_the_replay_records_every_entry_from_the_signal_with_steps_and_the_buyback_buyer():
    eng, pipe = flow_engine()
    for i in range(5):
        pipe.users[BUYERS[50 + i]] = ""                        # these traded other pools before
    pool = Pool(eng)                                           # the migration at T0, the buy lands at T0 + 1 s
    pool.trade(T0 + 400, False, base=pool.pb // 50, user=BUYERS[30])     # in flight: before the landing
    ev = [(T0 + 10_000 + 20_000 * i, SOL // 2, BUYERS[40]) for i in range(5)]   # a pool-only buyer from 10 s on
    ev += [(T0 + 2_000 + 3_000 * i + 1, SOL // 100, BUYERS[50 + i % 5]) for i in range(40)]
    for t, sol, u in sorted(ev):
        pool.trade(t, True, sol=sol, user=u)
    eng.advance(T0 + F.PATH_MS + 10_000)
    assert len(pipe.paths) == 1 and not pipe.recs
    d = pipe.paths[0]
    assert d["signal_ms"] == T0 and d["land_ms"] == T0 + 1_000 and d["tokens"] > 0 and d["complete"]
    assert d["t"][0] == T0 and d["buy"][0] == -1 and d["t"][d["j_land"]] <= d["land_ms"] < d["t"][d["j_land"] + 1]
    assert d["buy"][1] == 0 and d["dq"][1] < 0                 # the sale in flight, SOL out of the pool
    assert len(d["step_pt"]) >= 30 and d["X"].shape == (len(d["step_pt"]), len(F.FEATURES))
    gaps = np.diff(d["t"][d["step_pt"]])
    assert (gaps >= F.STEP_EVERY_MS).all() and d["t"][d["step_pt"][-1]] <= d["land_ms"] + F.STEP_MS
    x = d["X"][0]
    assert x[F.FEATURES.index("sl_move")] < 0 and x[F.FEATURES.index("sl_sells")] == 1
    assert len(d["bb_buys"]) == 5 and d["bb_buys"][0] == T0 + 10_000
    assert np.nanmax(d["bbn"]) == 5 and pipe.closed and pipe.closed[0]["rule"] == "P_pool0@N"


def test_a_buyer_that_sold_or_traded_another_pool_is_not_the_buyback():
    eng, pipe = flow_engine()
    pipe.users[BUYERS[41]] = "another mint"                    # it traded another pool before
    pool = Pool(eng)
    for i in range(4):
        pool.trade(T0 + 5_000 + 1_000 * i, True, sol=SOL // 5, user=BUYERS[41])
        pool.trade(T0 + 5_500 + 1_000 * i, True, sol=SOL // 5, user=BUYERS[42])
    pool.trade(T0 + 9_900, False, base=10 ** 9, user=BUYERS[42])   # a sale after it was chosen changes nothing
    eng.advance(T0 + F.PATH_MS + 10_000)
    d = pipe.paths[0]
    assert d["bb_buys"][:3] == [T0 + 5_500, T0 + 6_500, T0 + 7_500]       # BUYERS[42] chose on its third buy
    eng2, pipe2 = flow_engine()
    pool2 = Pool(eng2)
    pool2.trade(T0 + 5_000, True, sol=SOL // 5, user=BUYERS[43])
    pool2.trade(T0 + 6_000, False, base=10 ** 9, user=BUYERS[43])
    for i in range(4):
        pool2.trade(T0 + 7_000 + 1_000 * i, True, sol=SOL // 5, user=BUYERS[43])
    pool2.trade(T0 + 130_000, True, sol=SOL // 5, user=BUYERS[44])
    for i in range(4):
        pool2.trade(T0 + 131_000 + 1_000 * i, True, sol=SOL // 5, user=BUYERS[44])  # first buy after 120 s
    eng2.advance(T0 + F.PATH_MS + 10_000)
    assert pipe2.paths[0]["bb_buys"] == []


def test_dar_and_the_group_sell_intensity():
    eng, pipe = flow_engine()
    pool = Pool(eng)
    eng.advance(T0 + 10)
    tok = eng.tokens[MINT]
    r = next(iter(pipe.recs.values()))
    assert set(tok.devs) <= r.group
    w = BUYERS[45]
    r.group.add(w)
    tok.hold[w] = tok.pb // 4
    pool.trade(T0 + 2_000, True, sol=SOL // 100, user=BUYERS[46])
    x, h = tok.pb, sum(tok.hold.get(u, 0) for u in r.group)
    assert r.cols["dar"][-1] == pytest.approx(1 - (x / (x + h)) ** 2, rel=1e-6)
    before = tok.pb
    pool.trade(T0 + 3_000, False, base=10 ** 12, user=w)
    assert r.cols["hk5"][-1] == pytest.approx(10 ** 12 / before, rel=1e-4)
    pool.trade(T0 + 8_000, True, sol=SOL // 100, user=BUYERS[46])
    assert r.cols["hk5"][-1] == pytest.approx(10 ** 12 / before * math.exp(-1.0), rel=1e-3)
    assert r.cols["hk30"][-1] == pytest.approx(10 ** 12 / before * math.exp(-5 / 30), rel=1e-3)


# ---------------------------------------------------------------- the path simulator

def path(prices, times=None, land_i=0, buys=None, extra=None):
    """A synthetic path: the value of the position moves with `prices` (1.0 at the landing)."""
    n = len(prices)
    t = np.asarray(times if times is not None else [T0 + 1_000 * i for i in range(n)], dtype=float)
    x = np.full(n, 1e15)
    y = np.asarray(prices, dtype=float) * 1e11
    d = {"t": t, "x": x, "y": y, "dq": np.zeros(n), "amt": np.zeros(n), "fee": np.zeros(n, dtype=np.float32),
         "buy": np.asarray(buys if buys is not None else [1.0] * n, dtype=np.float32),
         "uid": np.arange(n, dtype=np.float32), "dar": np.zeros(n, dtype=np.float32),
         "hk5": np.zeros(n, dtype=np.float32), "hk30": np.zeros(n, dtype=np.float32),
         "bbn": np.zeros(n, dtype=np.float32), "bblast": np.full(n, np.nan),
         "slot": np.arange(n, dtype=np.int64), "pid": 0, "mint": "m", "symbol": "M", "signal_ms": int(t[0]),
         "mig_ms": int(t[0]), "land_ms": int(t[land_i]), "tokens": 10 ** 9, "j_land": land_i, "sig_pb": 1e15,
         "sig_pq": 1e11, "complete": True, "bb_buys": [], "step_pt": np.arange(land_i, n), "X": np.zeros((0, 1)),
         "tx_l": 0}
    d["cost_l"] = int(1e11 * 1e9 / (1e15 + 1e9))
    d.update(extra or {})
    return F.Path_(d)


def test_the_stop_lands_at_the_state_one_latency_later_and_the_take_floor_retries():
    pa = path([1.0, 0.95, 0.79, 0.6, 0.5, 0.5])
    r = F.simulate(pa, lambda leg: 1_500.0, 0)
    assert r["why"] == "stop" and r["sig_ms"] == T0 + 2_000 and r["exit_ms"] == T0 + 3_500
    assert r["got_l"] == pytest.approx(pa.v[3]) and r["legs"] == 1
    pa = path([1.0, 1.31, 0.4, 1.35, 1.35])                    # the take lands at 0.4: under half, it fails
    r = F.simulate(pa, lambda leg: 1_000.0, 100)               # and the stop sells at the landing's state
    assert r["why"] == "stop" and r["legs"] == 2 and r["sig_ms"] == T0 + 2_000 and r["got_l"] == pytest.approx(pa.v[3])
    assert r["pnl_l"] == pytest.approx(pa.v[3] - pa.cost - 3 * 100)
    pa = path([1.0, 1.31, 1.2, 1.35])
    assert F.simulate(pa, lambda leg: 1_000.0, 0)["why"] == "take"
    pa = path([1.0, 1.1, 1.05], times=[T0, T0 + 1_000, T0 + 400_000])
    r = F.simulate(pa, lambda leg: 500.0, 0)
    assert r["why"] == "time" and r["sig_ms"] == T0 + F.TIME_S * 1000
    assert F.simulate(pa, lambda leg: 500.0, 0, time_s=180)["sig_ms"] == T0 + 180_000


def test_an_own_exit_sells_first_or_after_the_stop():
    pa = path([1.0, 0.9, 0.7, 0.7])
    own = np.array([False, False, True, False])
    assert F.simulate(pa, lambda leg: 500.0, 0, own, own_why="flow")["why"] == "stop"
    assert F.simulate(pa, lambda leg: 500.0, 0, own, own_why="hazard", own_first=True)["why"] == "hazard"
    own = np.array([False, True, False, False])
    r = F.simulate(pa, lambda leg: 500.0, 0, own)
    assert r["why"] == "flow" and r["got_l"] == pytest.approx(pa.v[1])
    assert F.best_gain(path([1.0, 1.5, 0.2]), 0) == pytest.approx(path([1.0, 1.5, 0.2]).v[1] - path([1.0]).cost)


def test_the_flow_rule_masks():
    pa = path([1.0, 1.0, 1.0, 1.0, 1.0], times=[T0, T0 + 1_000, T0 + 2_000, T0 + 6_000, T0 + 7_000], land_i=1)
    pa.d["dq"][:] = [0, -5e9, -2e9, -2e9, -2e9]                # 5 % of the pool's 100 SOL out, then 2 % each
    m = F.masks(pa, "F1", 0.04)
    assert m.tolist() == [False, True, True, False, False]     # 5 %, 7 %; 2 %; 2 + 2 within 3 s, not above 4 %
    assert not F.masks(pa, "F1", 0.08).any() and not F.masks(pa, "F1", 0.0)[0]   # nothing before the landing
    pa = path([1.0, 0.84, 0.8], land_i=1)
    pa.d["y"][1] = 0.84e11
    assert F.masks(pa, "F2", 0.15).tolist() == [False, True, False]
    assert not F.masks(pa, "F2", 0.20).any() and F.masks(pa, "F1", None) is None
    pa.d["dar"][:] = [0.9, 0.2, 0.8]
    assert F.masks(pa, "DAR", 0.5).tolist() == [False, False, True]
    pa = path([1.0, 1.2, 1.05, 1.06, 1.06], times=[T0 + 1_000 * i for i in (0, 1, 2, 50, 100)])
    pa.d["bbn"][:] = [0, 3, 3, 3, 3]
    pa.d["bblast"][:] = [np.nan, T0 + 1_000, T0 + 1_000, T0 + 49_000, T0 + 49_000]
    assert F.masks(pa, "BB", None).tolist() == [False, False, True, True, True]    # fell 12.5 %, 11.7 %; stopped 51 s
    pb = path([1.0, 1.2, 1.05, 1.2, 1.2], times=[T0 + 1_000 * i for i in (0, 1, 2, 50, 100)])
    pb.d["bbn"][:], pb.d["bblast"][:] = pa.d["bbn"], pa.d["bblast"]
    assert F.masks(pb, "BB", None).tolist() == [False, False, True, False, True]


def test_the_labels_skip_the_latency_window():
    pa = path([1.0, 0.5, 1.0, 1.0], times=[T0, T0 + 300, T0 + 600, T0 + 20_000])
    lb = F.labels(pa, 500.0)
    assert lb["dump10"][0] == 0                                 # the drop at 300 ms lies inside L: no label
    pa = path([1.0, 1.0, 0.7, 1.0], times=[T0, T0 + 300, T0 + 2_000, T0 + 20_000])
    lb = F.labels(pa, 500.0)
    assert lb["dump10"][0] == 1 and lb["drop10"][0] == pytest.approx(math.log(0.7), abs=1e-3)
    assert lb["up30"][0] == pytest.approx(0.0, abs=1e-9) and lb["dump10"][-1] == 0


def test_the_walk_forward_trains_on_earlier_days_only():
    rng = np.random.default_rng(1)
    paths = []
    for day in range(3):
        for i in range(40):
            t0 = F._utc(2026, 10, 20, 1) + day * 86_400_000 + i * 600_000
            n = 60
            pr = np.cumprod(np.r_[1.0, 1 + rng.normal(0, 0.05, n - 1)])
            pa = path(pr, times=[t0 + 2_000 * j for j in range(n)])
            pa.d["X"] = rng.normal(size=(n, len(F.FEATURES))).astype(np.float32)
            pa.d["signal_ms"] = t0
            paths.append(pa)
    late = path(np.ones(60), times=[F._utc(2026, 10, 20, 23, 58) + 2_000 * j for j in range(60)])
    late.d["X"] = np.zeros((60, len(F.FEATURES)), dtype=np.float32)
    paths.insert(40, late)                                     # its labels reach into the next day: not trained on
    st = F.step_table(paths, 500.0)
    assert st["n"] == 3 * 40 * 60 + 60 and len(set(st["day"].tolist())) == 3
    wf = F.walk_forward(st, paths, 500.0, log=lambda *a: None)
    d0 = st["day"] == min(st["day"].tolist())
    assert np.isnan(wf["pd"][d0]).all() and np.isfinite(wf["pd"][~d0]).all()
    assert list(wf["days"]) == sorted(set(st["day"].tolist()))[1:] and wf["days"][list(wf["days"])[0]]["train"] == 2400
    hz = F.hz_masks(st, wf, paths, 1e9)
    assert hz[0] is None and any(h is not None and h.any() for h in hz[41:])


# ---------------------------------------------------------------- measured first

def test_one_transaction_stops():
    pa = path([1.0, 0.95, 0.5, 0.5, 0.48])
    j = F.crossing(pa, 3)
    assert j == 2
    r = F.one_tx(pa, 3, pa.v[4])
    assert not r["tx"]                                          # landed at 0.48, under the run's 0.5: not all of it
    r = F.one_tx(pa, 3, pa.v[3])
    assert r["tx"] and r["slot"] and r["landed"] == pytest.approx(pa.v[3] / pa.cost - 1)
    pa = path([1.0, 0.9, 0.85, 0.75, 0.7])                      # a slide: the crossing trade alone took it 0.85 -> 0.75
    assert not F.one_tx(pa, 4, pa.v[4])["tx"]
    pa = path([1.0, 0.85, 0.6, 0.5])
    pa.d["slot"][:] = [0, 1, 2, 2]
    pa.d["uid"][:] = [0, 1, 2, 2]                               # one signer's two sales in one slot
    assert F.one_tx(pa, 3, pa.v[3])["tx"] and F.one_tx_share([F.one_tx(pa, 3, pa.v[3]), None])["share_tx"] == 1.0


def test_the_live_stop_split_adds_up():
    tokens, us, sw = 10 ** 12, "OURS", "SANDWICH"
    rows = []

    def tr(slot, tx, buy, base, quote, user, pb, pq):
        rows.append({"mint": "Z", "slot": slot, "tx": tx, "t": T0 + 20_000 + slot * 400, "buy": buy, "base": base,
                     "quote": quote, "user": user, "pb": pb, "pq": pq, "vq": 0, "lpb": 20, "pfb": 5, "cfb": 0})
    tr(1, 1, True, tokens, 10 ** 8, us, int(1e15) + tokens, int(1e11) - 10 ** 8)      # our buy
    tr(3, 1, False, 10 ** 13, 0, "A", int(1e15), int(1e11))                           # the market falls
    tr(5, 1, False, 10 ** 13, 0, "B", int(1.1e15), int(0.85e11))
    tr(6, 2, False, 10 ** 11, 0, sw, int(1.2e15), int(0.78e11))                       # the front leg
    tr(6, 3, False, tokens, 0, us, int(1.2e15) + 10 ** 11, int(0.70e11))              # our sale
    tr(6, 4, True, 10 ** 11, 0, sw, int(1.2e15) + 10 ** 11 + tokens, int(0.69e11))     # the back leg
    rows = rows[::-1]                                                                  # any order: placed by slot
    d = F.record_path(rows)
    assert d["slot"].tolist() == [1, 3, 5, 6, 6, 6] and d["amt"][4] == tokens and d["buy"][4] == 0
    cost = 1e8
    lv = {"tokens": tokens, "stake_l": cost, "lat_ms": 400.0, "proceeds_l": 0.62e8, "ret": -0.40, "symbol": "Z"}
    s = F.live_split(lv, d)
    assert s["found"] and s["sandwich_seen"] and s["slots"] == 1 and s["trades_between"] == 1
    parts = sum(s[k] for k in ("overshoot", "path", "sandwich", "impact", "pool_fee", "slippage_setting"))
    assert parts == pytest.approx(s["gap"]) and s["gap"] == pytest.approx(0.62 - 1 + 0.2)
    assert s["sandwich"] < 0 and s["rest"] == pytest.approx(-0.40 - (0.62 - 1))
    assert F.live_split(dict(lv, lat_ms=2_000.0), d)["slots"] == 5     # 5 slots back: our buy's slot
    assert not F.live_split(dict(lv, tokens=tokens + 1), d)["found"]


def test_the_executor_split_of_a_live_stop():
    lv = {"symbol": "Z", "ret": -0.30, "cost_l": 1e8, "sale_l": 0.70e8, "sale_slip": 0.70 / 0.77 - 1, "lat_ms": 400.0}
    x = F.exec_split(lv)
    assert x["mark_sig"] == pytest.approx(-0.23) and x["overshoot"] == pytest.approx(-0.03)
    assert x["latency"] == pytest.approx(-0.07) and x["fill"] == pytest.approx(-0.30) and x["worse"]
    assert not F.exec_split(dict(lv, sale_slip=0.05))["worse"] and F.exec_split(dict(lv, sale_slip=None)) is None


def test_the_buyback_summary():
    d = path([1.0] * 5, times=[T0, T0 + 100_000, T0 + 300_000, T0 + 330_000, T0 + 420_000]).d
    d["y"] = np.array([1e11, 1e11, 1.2e11, 1.0e11, 0.9e11])
    d["bb_buys"] = [T0 + 5_000, T0 + 300_000]
    b = F.buyback([d, dict(d, bb_buys=[])])
    assert b["pools"] == 2 and b["with_buyer"] == 1 and b["hist"]["270-300"] == 1
    assert b["after30"]["mean"] == pytest.approx(math.log(1.0 / 1.2)) and b["after120"]["mean"] == pytest.approx(
        math.log(0.9 / 1.2))


# ---------------------------------------------------------------- judging

def row(ret, day, why="take", failed=False, i=0, t=None):
    s = F._utc(2026, 10, day, 12) + i
    return {"i": i, "mint": f"m{i}", "signal_ms": s if t is None else t, "day": F.day_of(s), "ret": ret,
            "pnl_sol": ret * 0.05, "why": why, "exit_ms": s + 60_000, "legs": 1, "failed": failed, "hold_s": 60.0,
            "best_l": 1e7, "pnl_l": ret * 0.05 * C.LAMPORTS, "gapped": False}


def test_the_day_band_and_the_verdict():
    base = [row(-0.2 if i % 3 == 0 else 0.1, 24 + i % 6, "stop" if i % 3 == 0 else "take", i=i) for i in range(60)]
    better = [dict(b, ret=b["ret"] + 0.05 * (1 + (i % 2)), why=b["why"]) for i, b in enumerate(base)]
    v = F.verdict(better, base)
    assert v["n"] == 60 and v["diff"] == pytest.approx(0.075) and v["band"][0] > 0 and v["passes"]
    assert v["x0_stops"] == 20 and v["on_x0_stops"] == pytest.approx(0.075)
    worse_stops = [dict(b, ret=b["ret"] + (0.3 if b["why"] == "take" else -0.01)) for b in base]
    assert not F.verdict(worse_stops, base)["stops_better"] and not F.verdict(worse_stops, base)["passes"]
    four = [r for r in base if r["day"] < "2026-10-28"]
    assert math.isnan(F.verdict(four, four)["band"][0]) and not F.verdict(four, four)["passes"]
    sc = {"versus": {v_: {"passes": v_ in ("F1", "BB")} for v_ in F.VARIANTS[1:]},
          "table": {v_: {"mean": {"F1": 0.01, "BB": 0.02}.get(v_, 0.0)} for v_ in F.VARIANTS}}
    assert F.pick(sc) == "BB"


def test_the_books_apply_the_limits():
    xs = [row(-0.5, 25, "stop", i=i, t=F._utc(2026, 10, 25, 12) + 120_000 * i) for i in range(6)]
    live = F.book(xs, F.SIZINGS["live"], 100_000)
    assert live["n"] == 3 and live["skipped"] == {"daily loss limit": 3}     # 0.025 lost each: 0.075 + 0.065 > 0.12
    wide = F.book(xs, F.SIZINGS["wide"], 100_000)
    assert wide["n"] == 6 and wide["pnl_sol"] == pytest.approx(6 * (2 * -0.025 + 2 * 100_000 / C.LAMPORTS))
    xs = [row(0.1, 25, i=i, t=F._utc(2026, 10, 25, 12) + 10_000 * i) for i in range(3)]
    assert F.book(xs, F.SIZINGS["live"], 0)["skipped"] == {"max open positions": 2}
