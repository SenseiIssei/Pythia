"""Y17, the shape of a coin's first minutes: the paths point in time (a trade counts from the second it was received,
the price of the latest slot, the top holders at the start of the second, nothing after a second moves it), the
labels, a store end to end, the numpy CNN's gradient and that it learns a planted shape, the analog search, the
weighted measures against sklearn and scipy, Holm, the walk-forward's embargo, the twins and R2's bar. No network,
no wallet.

Run from research/lab:  python -m pytest tests/test_pumpfun_shapes_y17.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import shapes17 as Y17
from lab.pumpfun_rt import store
from lab.pumpfun_rt.tokens import SUPPLY

T0 = Y17.day_start("2026-10-24") + 3_600_000
VS, VT, RT = 30 * C.LAMPORTS, 1_073_000_000 * C.TOKEN_UNIT, C.INITIAL_RT
P0 = C.price(VS, VT)
DEV, A, B, D = "dev", "alice", "bob", "dora"


def tr(t, slot, buy, sol, tok, user, vs=VS, vt=VT, rt=RT, tx=0):
    return (t, slot, tx, buy, int(sol * C.LAMPORTS), int(tok), user, vs, vt, rt)


def ch(name):
    return Y17.CHANNELS.index(name)


# ---------------------------------------------------------------- the paths

def test_path_counts_a_trade_from_the_second_it_was_received():
    x = Y17.coin_path(T0, DEV, RT, P0, [tr(T0 + 3_500, 10, True, 1.0, 10 ** 12, A, vs=VS * 2, vt=VT // 2)])
    assert x.shape == (Y17.T_MAX, len(Y17.CHANNELS))
    assert (x[:3, ch("buys")] == 0).all() and x[3, ch("buys")] == pytest.approx(math.log(2))
    assert (x[:3, ch("lp")] == 0).all()
    assert x[3:, ch("lp")] == pytest.approx(math.log(4), rel=1e-5)          # carried after the trade
    assert x[4, ch("buys")] == 0 and x[119, ch("ubuyers")] == pytest.approx(math.log(2))


def test_path_price_is_the_latest_slot_received_and_ignores_after_t_max():
    late = [tr(T0 + 1_000, 20, True, 1.0, 1, A, vs=VS * 2, vt=VT),
            tr(T0 + 2_000, 15, True, 1.0, 1, B, vs=VS * 3, vt=VT),               # an older slot delivered late
            tr(T0 + Y17.T_MAX * 1000 + 5, 30, True, 9.0, 1, D, vs=VS * 9, vt=VT)]
    x = Y17.coin_path(T0, DEV, RT, P0, late)
    assert x[2, ch("lp")] == pytest.approx(math.log(2), rel=1e-5)
    assert x[2, ch("buys")] == pytest.approx(math.log(2))                      # it counts as a buy all the same
    assert x[-1, ch("lp")] == pytest.approx(math.log(2), rel=1e-5)


def test_path_top_holders_creator_and_shares():
    tok = SUPPLY // 10
    ev = [tr(T0, 1, True, 2.0, tok, DEV), tr(T0 + 100, 1, True, 1.0, tok, A, tx=1),
          tr(T0 + 200, 1, True, 0.5, tok // 2, B, tx=2),
          tr(T0 + 5_000, 5, False, 0.3, tok // 2, A), tr(T0 + 5_100, 5, False, 0.2, tok // 2, DEV, tx=1),
          tr(T0 + 5_200, 5, True, 0.1, 10, D, tx=2), tr(T0 + 5_300, 5, False, 0.05, 5, D, tx=3)]
    x = Y17.coin_path(T0, DEV, RT, P0, ev)
    assert x[0, ch("dev_buy_sol")] == pytest.approx(math.log1p(2.0))
    assert x[0, ch("dev_share")] == pytest.approx(0.1) and x[0, ch("top_share")] == pytest.approx(0.15)
    assert x[5, ch("dev_sell_sol")] == pytest.approx(math.log1p(0.2))
    # A was a top holder at the start of second 5; D bought and sold within it and was not
    assert x[5, ch("top_sell_sol")] == pytest.approx(math.log1p(0.3))
    assert x[5, ch("dev_share")] == pytest.approx(0.05)
    assert x[5, ch("sell_sol")] == pytest.approx(math.log1p(0.55))


def test_path_no_look_ahead():
    rng = np.random.default_rng(1)
    ev = sorted([tr(T0 + int(t), int(t // 400), bool(rng.random() < 0.6), float(rng.random()),
                    int(rng.integers(1, 10 ** 12)), f"w{rng.integers(0, 12)}", vs=int(VS * (1 + rng.random())),
                    vt=VT, rt=int(RT * rng.random()), tx=i)
                 for i, t in enumerate(rng.uniform(0, 120_000, 300))])
    full = Y17.coin_path(T0, DEV, RT, P0, ev)
    for s in (0, 9, 29, 59, 100):
        cut = [e for e in ev if e[0] < T0 + (s + 1) * 1000]
        changed = cut + [tr(e[0], e[1], not e[3], 5.0, 7, "zed", vs=VS * 7, rt=1, tx=e[2])
                         for e in ev if e[0] >= T0 + (s + 1) * 1000]
        assert np.array_equal(Y17.coin_path(T0, DEV, RT, P0, changed)[:s + 1], full[:s + 1])


# ---------------------------------------------------------------- the labels

def _coins(lph):
    return pl.DataFrame({"mint": ["m1", "m2"], "t0": [T0, T0],
                         **{f"lp_h{h}": [lph, 0.0] for h in Y17.HORIZONS}})


def test_labels_rug_peak_exit_mig_and_grid():
    h = 10
    th = T0 + h * 1000
    lp = pl.DataFrame({"mint": ["m1"] * 4 + ["m2"],
                       "t": [th + 20_000, th + 30_000, th + 400_000, th + 3_000_000, th + 1_000],
                       "lp": [math.log(3), math.log(2), math.log(0.4), math.log(6), math.log(0.9)]}).sort(["mint", "t"])
    out = Y17.labels(_coins(math.log(2)), lp, {"m1": T0 + 1_000_000, "m2": T0 + 5_000})
    j = Y17.HORIZONS.index(h)
    assert out["rug"][0, j] == 1 and out["rug"][1, j] == 0                     # 0.4 is under half of 2; 0.9 is not
    assert out["peak"][0, j] == pytest.approx(math.log(3))                      # 6 within the hour over 2
    assert out["exit_s"][0, j] == 20                                             # the high within 10 minutes
    assert out["exit_s"][1, j] == 0 and out["peak"][1, j] == 0                   # never above the price at H
    assert out["mig"][0, j] == 1 and math.isnan(out["mig"][1, j])               # m2 completed before H: left out
    g = out["grid"][0, j]
    assert g[0] == 0 and g[1] == 0                                              # 0 and 10 s: nothing yet
    assert g[2] == pytest.approx(math.log(1.5), rel=1e-5)                       # 20 s: the trade at 20 s
    assert g[3] == 0                                                             # 30 s: back to 2
    assert g[-1] == pytest.approx(math.log(0.2), rel=1e-5)


def _store(root):
    w = store.Writer(root)
    w.add("creates", {"t": T0, "slot": 1, "tx": 1, "mint": "M", "creator": DEV, "user": DEV, "vs": VS, "vt": VT,
                      "rt": RT, "name": "x", "symbol": "X"})
    w.add("creates", {"t": T0 + 5, "slot": 1, "tx": 2, "mint": "N", "creator": DEV, "user": DEV, "vs": VS, "vt": VT,
                      "rt": RT, "name": "y", "symbol": "Y"})
    for i, (dt, buy, vs) in enumerate([(500, True, VS * 2), (12_000, True, VS * 4), (200_000, False, VS)]):
        w.add("trades", {"t": T0 + dt, "slot": 2 + i, "tx": 10 + i, "mint": "M", "buy": buy, "sol": C.LAMPORTS,
                         "tok": 10 ** 12, "user": A, "vs": vs, "vt": VT, "rs": 0, "rt": RT - 10 ** 12 * (i + 1)})
    w.add("other", {"kind": "complete", "t": T0 + 20_000, "slot": 9, "tx": 20, "mint": "M", "user": "", "pool": "",
                    "sol": 0, "tok": 0, "t0": 0})
    w.flush(T0)


def test_build_day_end_to_end(tmp_path):
    _store(tmp_path)
    r = Y17.build_day("2026-10-24", {"M"}, set(), tmp_path, log=lambda *_: None)
    assert list(r["mint"]) == ["M"] and r["paths"].shape == (1, Y17.T_MAX, len(Y17.CHANNELS))
    assert r["paths"][0, 0, ch("lp")] == pytest.approx(math.log(2), rel=1e-5)
    assert r["paths"][0, 12, ch("lp")] == pytest.approx(math.log(4), rel=1e-5)
    j10, j30 = Y17.HORIZONS.index(10), Y17.HORIZONS.index(30)
    assert r["mig"][0, j10] == 1 and math.isnan(r["mig"][0, j30])
    assert r["peak"][0, j10] == pytest.approx(math.log(2), rel=1e-4)            # 4 over 2 at 12 s
    assert r["rug"][0, j10] == 1                                                 # back to 1 at 200 s
    r2 = Y17.build_day("2026-10-24", {"M"}, {"N"}, tmp_path, log=lambda *_: None)
    assert sorted(r2["mint"]) == ["M", "N"]


# ---------------------------------------------------------------- the sequence model

def test_cnn_gradient_matches_numerical():
    rng = np.random.default_rng(0)
    net = Y17.CNN(3, seed=1, filters=4, width=3, dense=5)
    X = rng.standard_normal((6, 9, 3))
    Y = np.column_stack([rng.integers(0, 2, 6), rng.integers(0, 2, 6), rng.standard_normal(6),
                         rng.standard_normal(6)]).astype(float)
    Y[1, 0] = np.nan
    o, cache = net.forward(X)
    _, do = net.loss(o, Y)
    gr = net.backward(cache, do)
    for name in ("W1", "b1", "W2", "Wd", "Wo", "bo"):
        p = net.p[name]
        for idx in list(np.ndindex(p.shape))[:6]:
            old = p[idx]
            p[idx] = old + 1e-6
            lp_, _ = net.loss(net.forward(X)[0], Y)
            p[idx] = old - 1e-6
            lm, _ = net.loss(net.forward(X)[0], Y)
            p[idx] = old
            assert gr[name][idx] == pytest.approx((lp_ - lm) / 2e-6, rel=1e-3, abs=1e-6), name


def _planted(n=1_200, T=20, seed=3):
    rng = np.random.default_rng(seed)
    X = rng.standard_normal((n, T, 2)).astype(np.float32)
    y = rng.random(n) < 0.3
    at = rng.integers(2, T - 2, n)
    X[y, at[y], 1] += 4.0                                                          # a spike anywhere: the shape
    Y = np.column_stack([y, ~y, y * 2.0 + rng.normal(0, 0.1, n), at * 1.0]).astype(float)
    return X, Y


def test_cnn_learns_a_planted_spike():
    from sklearn.metrics import roc_auc_score
    X, Y = _planted()
    net = Y17.CNN(2, seed=2)
    hist = net.fit(X[:900], Y[:900], epochs=30, batch=128, lr=3e-3)
    assert hist[-1] < hist[0]
    p = net.predict(X[900:])
    assert roc_auc_score(Y[900:, 0], p[:, 0]) > 0.9
    assert np.corrcoef(p[:, 2], Y[900:, 2])[0, 1] > 0.7                        # near what the AUC allows


def test_analog_finds_the_planted_neighbours():
    from sklearn.metrics import roc_auc_score
    X, Y = _planted(seed=4)
    X[:, :, 1] = np.where(Y[:, :1] == 1, 2.0, 0.0) + X[:, :, 1] * 0.1          # a level, not a spike
    a = Y17.Analog().fit(X[:900], Y[:900], k=20)
    p = a.predict(X[900:])
    assert p.shape == (300, 4) and roc_auc_score(Y[900:, 0], p[:, 0]) > 0.95
    assert Y17.blocks(np.zeros((2, 120, 3))).shape == (2, Y17.ANALOG_POINTS * 3)
    assert Y17.blocks(np.zeros((2, 10, 3))).shape == (2, 30)


# ---------------------------------------------------------------- measures

def test_weighted_measures_match_sklearn_and_scipy():
    from scipy.stats import spearmanr
    from sklearn.metrics import roc_auc_score
    rng = np.random.default_rng(5)
    s = np.round(rng.random(400), 2)                                              # ties
    y = (rng.random(400) < 0.3).astype(float)
    w = np.vstack([np.ones(400), rng.integers(0, 3, 400)])
    a = Y17.wauc(s, y, w)
    assert a[0] == pytest.approx(roc_auc_score(y, s))
    assert a[1] == pytest.approx(roc_auc_score(y, s, sample_weight=w[1]))
    v = rng.random(400)
    assert Y17.wspear(s, v, w[:1])[0] == pytest.approx(spearmanr(s, v)[0])
    assert Y17.wmae(s, v, w[:1])[0] == pytest.approx(np.mean(np.abs(s - v)))
    t = T0 + rng.integers(0, 50, 400) * 3_600_000
    m1, m2 = Y17.measure("rug", s, y, t), Y17.measure("rug", s, y, t)
    assert len(m1) == Y17.BOOT + 1 and np.array_equal(m1, m2) and m1[0] == pytest.approx(a[0])


def test_holm():
    assert Y17.holm([0.001, 0.04, 0.03]) == [True, False, False]
    assert Y17.holm([0.001, 0.02, 0.01]) == [True, True, True]
    assert Y17.holm([0.2, 0.001]) == [False, True]


# ---------------------------------------------------------------- the walk-forward

def _data(n_day=300, days=("2026-10-20", "2026-10-21", "2026-10-22"), seed=6):
    rng = np.random.default_rng(seed)
    t0 = np.concatenate([Y17.day_start(d) + rng.integers(0, Y17.DAY_MS, n_day) for d in days]).astype(np.int64)
    n = len(t0)
    X, Y = _planted(n=n, T=Y17.T_MAX, seed=seed)
    paths = np.concatenate([X, np.zeros((n, Y17.T_MAX, len(Y17.CHANNELS) - 2), dtype=np.float32)], axis=2)
    lab = {k: np.repeat(Y[:, i:i + 1], len(Y17.HORIZONS), axis=1).astype(np.float32) for i, k in enumerate(Y17.LABELS)}
    grid = np.zeros((n, len(Y17.HORIZONS), Y17.GRID), dtype=np.float32)
    return {"mint": np.array([f"m{i}" for i in range(n)]), "t0": t0, "paths": paths, "has_row": np.ones(n, bool),
            "grid": grid, **lab}


def test_walk_trains_only_on_closed_labels(monkeypatch):
    data = _data()
    seen = []
    real = Y17.Analog.fit

    def spy(self, X, Y, k=Y17.ANALOG_K):
        seen.append(len(X))
        return real(self, X, Y, k)
    monkeypatch.setattr(Y17.Analog, "fit", spy)
    wf = Y17.walk(data, None, days=("2026-10-22",), log=lambda *_: None, models=("analog",))
    lo = Y17.day_start("2026-10-22")
    for j, h in enumerate(Y17.HORIZONS):
        n_ok = int((data["t0"] + h * 1000 + Y17.PEAK_MS < lo).sum())
        assert seen[j] == n_ok and n_ok < 600                                   # the last hour of the 21st left out
        te = data["t0"] >= lo
        assert np.isfinite(wf["pred"]["analog"][te, j]).all()
        assert np.isnan(wf["pred"]["analog"][~te, j]).all()


def test_walk_cnn_queries_and_cuts():
    data = _data()
    q = {"2026-10-22": [700, 701]}
    wf = Y17.walk(data, None, days=("2026-10-22",), log=lambda *_: None, models=("cnn",), queries=q)
    for h in Y17.HORIZONS:
        assert ("2026-10-22", 700, h) in wf["qpred"] and ("2026-10-22", h) in wf["cuts"]
        c = wf["cuts"][("2026-10-22", h)]
        assert set(c) == {"rug", "peak"} and 0.8 in c["rug"] and 0.2 in c["peak"]


def test_evaluate_and_exit_test():
    data = _data(days=("2026-10-21", "2026-10-22"))
    n = len(data["t0"])
    y = data["mig"][:, 0]
    rng = np.random.default_rng(7)
    noise = rng.random(n)
    pred = {"cnn": np.repeat(np.stack([y + noise, y + noise, data["peak"][:, 0], data["exit_s"][:, 0]],
                                      axis=1)[:, None, :], len(Y17.HORIZONS), axis=1),
            "analog": np.repeat(np.stack([noise] * 4, axis=1)[:, None, :], len(Y17.HORIZONS), axis=1),
            "base": np.repeat(np.stack([noise * 0.5 + y * 0.2] * 4, axis=1)[:, None, :], len(Y17.HORIZONS), axis=1)}
    ev = Y17.evaluate(data, {"pred": pred}, days=("2026-10-22",))
    r = next(x for x in ev["rows"] if x["label"] == "mig" and x["h"] == 10)
    assert r["cnn"] > r["base"] > r["analog"] and r["cnn_beats"] and not r.get("analog_beats")
    assert ev["comparisons"] == 2 * len(Y17.LABELS) * len(Y17.HORIZONS)
    x = next(x for x in ev["rows"] if x["label"] == "exit_s")["exit"]
    assert {"at_best", "at_cnn", "at_median", "hold_600"} <= set(x)


# ---------------------------------------------------------------- the twins

def test_horizon_at():
    assert Y17.horizon_at(9_999) is None and Y17.horizon_at(10_000) == 10
    assert Y17.horizon_at(59_000) == 30 and Y17.horizon_at(10 ** 9) == 120


def _ledger(d):
    (d / "ledger.csv").write_text(
        "rule,mint,symbol,created_ms,signal_ms,exit_ms,ret,stake_sol\n"
        + "".join(f"{Y17.BASES[0]},m{i},S{i},{T0},{T0 + 86_400_000 * (i % 3) + 70_000},"
                  f"{T0 + 86_400_000 * (i % 3) + 99_000},{(0.3 if i % 2 else -0.2)},0.055\n" for i in range(12))
        + f"{Y17.BASES[0]},old,O,{T0},{T0 - 4 * 86_400_000},{T0},0.5,0.1\n"
        + f"{Y17.BASES[0]},x,X,{T0},{T0 + 1000},{T0 + 2000},0.5,\n", encoding="utf-8")
    (d / "failed.csv").write_text(f"rule,mint,signal_ms,land_ms,why,pnl_sol\n{Y17.BASES[0]},f1,{T0 + 5},{T0 + 9},"
                                  "slippage,-0.0002\n", encoding="utf-8")


def test_ledger_entries_and_twins(tmp_path):
    _ledger(tmp_path)
    es = Y17.ledger_entries(tmp_path)
    b = es[Y17.BASES[0]]
    assert len(b) == 13 and sum(e["failed"] for e in b) == 1                    # out of the days and no stake: out
    assert es[Y17.BASES[1]] == []
    assert b[1]["pnl"] == pytest.approx(b[1]["ret"] * Y17.STAKE_SOL)
    mints = [f"m{i}" for i in range(12)]
    data = {"mint": np.array(mints), "t0": np.array([T0 + 86_400_000 * (i % 3) for i in range(12)], dtype=np.int64)}
    wf = {"qpred": {}, "cuts": {}}
    for i in range(12):
        d = Y17.day_of(T0 + 86_400_000 * (i % 3))
        wf["qpred"][(d, i, 60)] = np.array([0.0, 0.9 if i % 2 == 0 else 0.1, 0.0, 0.0])
        wf["cuts"][(d, 60)] = {"rug": {0.8: 0.5}, "peak": {0.2: -1.0}}
    at = {m: i for i, m in enumerate(mints)}
    assert Y17.vetoed(b[1], data, at, wf, "V1") in (True, False)
    assert Y17.vetoed({"mint": "zz", "signal_ms": T0}, data, at, wf, "V1") is None
    res = Y17.twins(data, wf, {Y17.BASES[0]: b})[Y17.BASES[0]]
    v1 = res["twins"]["V1"]
    assert v1["skipped"] == 6 and v1["winners_skipped"] == 0 and v1["no_shape"] == 1      # every loser cut
    assert v1["skipped_pnl"]["sum"] == pytest.approx(6 * -0.02)
    assert v1["bar"]["skipped_band_below_zero"] and v1["bar"]["band_above_zero"]
    assert v1["wallet"]["median"] > res["base"]["wallet"]["median"]
    assert v1["passes"] == all(v1["bar"].values())
    assert res["twins"]["V2"]["skipped"] == 0 and not res["twins"]["V2"]["passes"]


def test_wallet_entries_scale_and_fees():
    es = [{"signal_ms": T0, "exit_ms": T0 + 1, "failed": False, "ret": 0.5, "pnl": 0.05},
          {"signal_ms": T0 + 2, "exit_ms": T0 + 3, "failed": True, "ret": NAN_, "pnl": -0.001}]
    w = Y17.wallet_entries(es)
    assert w[0]["proceeds"] == pytest.approx(0.15) and w[0]["cost"] == Y17.STAKE_SOL
    assert w[1]["fees"] == pytest.approx(0.001) and w[1]["cost"] == 0


NAN_ = float("nan")


def test_paper_only():
    import inspect
    src = inspect.getsource(Y17)
    for bad in ("live_exec", "txbuild", "live_service", "keypair", "sign(", "send_transaction"):
        assert bad not in src


def test_reserves_from_the_record(tmp_path):
    w = store.Writer(tmp_path)
    for dt, pq in ((0, 80 * C.LAMPORTS), (60_000, 120 * C.LAMPORTS)):
        w.add("amm", {"t": T0 + dt, "slot": 1, "tx": 1, "pool": "p", "mint": "m", "buy": True, "base": 1, "quote": 1,
                      "user": A, "pb": 10 ** 15, "pq": pq, "lpb": 0, "pfb": 0, "cfb": 0, "vq": -C.LAMPORTS})
    w.add("trades", {"t": T0, "slot": 1, "tx": 1, "mint": "z", "buy": True, "sol": 1, "tok": 1, "user": A})
    w.flush(T0)
    es = {"b": [{"mint": "m", "signal_ms": T0 + 1_000, "exit_ms": T0 + 90_000, "failed": False, "ret": 0.1,
                 "pnl": 0.01},
                {"mint": "m", "signal_ms": T0 + 2_000, "exit_ms": T0 + 3_000, "failed": True, "ret": NAN_,
                 "pnl": -0.001}]}
    Y17.reserves(es, tmp_path)
    e = es["b"][0]
    assert e["q_in"] == pytest.approx(79.0) and e["q_out"] == pytest.approx(119.0)
    assert "q_in" not in es["b"][1]
    assert Y17.wallet_entries(es["b"])[0]["q_in"] == pytest.approx(79.0)


def test_walk_saved_and_loaded(tmp_path):
    wf = {"pred": {"cnn": np.arange(24, dtype=float).reshape(2, 4, 3)},
          "qpred": {("2026-10-24", 3, 60): np.array([0.1, 0.2, 0.3, 4.0])},
          "cuts": {("2026-10-24", 60): {"rug": {0.8: 0.5}, "peak": {0.2: 0.01}}}}
    assert Y17.load_walk(tmp_path) is None
    Y17.save_walk(tmp_path, wf)
    back = Y17.load_walk(tmp_path)
    assert np.array_equal(back["pred"]["cnn"], wf["pred"]["cnn"])
    assert np.allclose(back["qpred"][("2026-10-24", 3, 60)], [0.1, 0.2, 0.3, 4.0])
    assert back["cuts"][("2026-10-24", 60)] == wf["cuts"][("2026-10-24", 60)]


def test_report_md_renders(tmp_path):
    _ledger(tmp_path)
    b = Y17.ledger_entries(tmp_path)[Y17.BASES[0]]
    data = {"mint": np.array([f"m{i}" for i in range(12)]), "t0": np.full(12, T0, dtype=np.int64)}
    tw = Y17.twins(data, {"qpred": {}, "cuts": {}}, {Y17.BASES[0]: b, Y17.BASES[1]: []})
    ev = {"rows": [{"h": 10, "label": "mig", "n": 3}], "comparisons": 0}
    md = Y17.report_md({"coins": 12, "with_row": 12, "span": ["2026-10-24", "2026-10-26"], "eval": ev, "twins": tw})
    assert "Y17" in md and Y17.BASES[0] in md and "none 1 " in md and chr(0x2014) not in md


def test_references_one_number_and_moved_subset():
    data = _data(days=("2026-10-21", "2026-10-22"))
    n = len(data["t0"])
    data["paths"][:, :, Y17.CHANNELS.index("lp")] = np.where(np.arange(n) % 2 == 0, 0.5, 0.0)[:, None]
    data["paths"][:, :, Y17.CHANNELS.index("progress")] = data["mig"][:, :1]
    pred = {m: np.full((n, len(Y17.HORIZONS), 4), 0.5) for m in ("cnn", "base")}
    rows = Y17.references(data, {"pred": pred}, days=("2026-10-22",))
    mig = next(r for r in rows if r["label"] == "mig" and r["coins"] == "all" and r["h"] == 10)
    assert mig["one_number"] == pytest.approx(1.0) and mig["cnn"] == pytest.approx(0.5)
    moved = [r for r in rows if r["coins"] == "moved"]
    assert moved and all(r["n"] < mig["n"] for r in moved)
