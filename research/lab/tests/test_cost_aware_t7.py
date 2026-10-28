"""T7: G2's net target (positions from a forecast, the next day's return less the cost of the change, the net Sharpe
as fitness, ridge_net in closed form), its looks and shadows; meta-labelling as a size (never above the rule, the
late label at the era's round trip, no lookahead in the features); the study end to end on synthetic data, every
spec and variant in the registry before a validation number.

Synthetic panels only, no lab data. Run from research/lab:  python -m pytest tests/test_cost_aware_t7.py
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab import universe as U
from lab.experiments import cost_aware_t7 as t7
from lab.experiments import director_common as dc
from lab.experiments import pit_universe_t5 as t5
from lab.models import daily
from lab.models import factory as F
from lab.models import metalabel as ML

DAY_US = 86_400_000_000
NOW_MS = 1_793_059_200_000                       # 2026-10-27


@pytest.fixture(scope="module")
def raw():
    return daily.enrich(daily.synthetic_daily(3220, bases=("BTC", "ETH", "SOL", "XRP", "ADA"), seed=3))


def planted(raw: pl.DataFrame, edge: float) -> pl.DataFrame:
    """net1's panel with a next-day return that qv_z (the volume shock, not the trend) explains, open on the last
    day."""
    p = F.net_panel(raw)
    rng = np.random.default_rng(1)
    x = p["qv_z"].fill_null(0.0).to_numpy()
    y = edge * 0.02 * x / (np.std(x) + 1e-12) + rng.normal(0, 0.02, p.height)
    last = p["ts_us"].max()
    return p.with_columns(target=pl.when(pl.col("ts_us") == last).then(None).otherwise(pl.Series(y)))


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_MODEL_FACTORY_DIR", str(tmp_path / "mf"))
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "reports"))
    return tmp_path


def net_spec(features=("qv_z", "ret1", "h7"), alpha=0.1, kappa=0.0, window=None):
    return F.canonical_spec({"target": "net1", "features": list(features), "trees": [], "learner": "ridge_net",
                             "params": {"alpha": alpha, "kappa": kappa}, "window": window})


# ---------------------------------------------------------------- the net target on a toy series

def test_the_net_book_on_a_toy_series_is_the_return_less_the_cost_of_the_change():
    # one coin, four days: positions 1, 1, -1, then none; returns 2 %, -1 %, 3 %; cost 10 bps one way
    di, sj = np.array([0, 1, 2]), np.array([0, 0, 0])
    pos = np.array([1.0, 1.0, -1.0])
    r = np.array([0.02, -0.01, 0.03])
    c = np.full(3, 0.001)
    b = F.net_book(di, sj, 4, 1, pos, r, c)
    assert b["gross"] == pytest.approx([0.02, -0.01, -0.03, 0.0])
    assert b["cost"][:3] == pytest.approx([0.001, 0.0, 0.002])           # in, hold, flip through zero
    assert b["net"][:3] == pytest.approx([0.019, -0.01, -0.032])
    assert b["cost"][3] == pytest.approx(t5.PERP_FEE + t5.SPREAD_BELOW)  # no row: out at the highest tier
    assert b["turnover"] == pytest.approx([1.0, 0.0, 2.0, 1.0]) and list(b["on"]) == [True] * 4


def test_two_coins_share_the_book_and_in_and_out_is_one_round_trip():
    di, sj = np.array([0, 0, 1, 1]), np.array([0, 1, 0, 1])
    b = F.net_book(di, sj, 3, 2, np.array([1.0, -1.0, 0.0, -1.0]), np.array([0.04, 0.02, 0.0, 0.01]),
                   np.array([0.002, 0.001, 0.002, 0.001]))
    assert b["gross"][0] == pytest.approx(0.5 * 0.04 - 0.5 * 0.02)       # pos / N, the gross at most 1
    assert b["cost"][0] == pytest.approx(0.5 * 0.002 + 0.5 * 0.001)
    assert b["cost"][1] == pytest.approx(0.5 * 0.002)                     # coin 0 out, coin 1 held
    assert b["cost"][0] + b["cost"][1] == pytest.approx(0.5 * 0.002 * 2 + 0.5 * 0.001)


def test_a_position_is_the_sign_and_a_capped_size():
    f = np.array([-5.0, -0.5, 0.0, 0.25, 3.0])
    assert F.positions(f, 1.0) == pytest.approx([-1.0, -0.5, 0.0, 0.25, 1.0])
    assert F.positions(f, 0.0) == pytest.approx([-1.0, -1.0, 0.0, 1.0, 1.0])
    assert np.abs(F.positions(np.random.default_rng(0).normal(0, 9, 500), 0.3)).max() <= F.NET_CAP


def test_prev_rows_finds_the_same_coins_day_before_inside_the_mask():
    di = np.array([0, 0, 1, 1, 3, 3])
    sj = np.array([0, 1, 0, 1, 0, 1])
    m = np.array([True, True, True, False, True, True])
    assert list(F.prev_rows(di, sj, m)) == [-1, -1, 0, -1, -1]


def test_ridge_net_without_the_penalty_is_the_plain_ridge_and_the_penalty_cuts_turnover():
    rng = np.random.default_rng(2)
    n = 1500
    slow = np.cumsum(rng.normal(0, 0.1, n))
    fast = rng.normal(0, 1, n)
    X = np.column_stack([slow, fast])
    y = 0.01 * (slow / slow.std()) + 0.01 * fast + rng.normal(0, 0.02, n)
    prev = np.r_[-1, np.arange(n - 1)]
    c = np.full(n, 0.003)
    m0 = F.RidgeNet(0.0, 0.0).fit(X, y, prev, c)
    Z = np.column_stack([np.ones(n), m0.prep(X)])
    assert m0.b == pytest.approx(np.linalg.lstsq(Z, y, rcond=None)[0], rel=1e-6)
    m1 = F.RidgeNet(0.0, 16.0).fit(X, y, prev, c)
    tov = [np.abs(np.diff(F.positions(m.predict(X), m.s))).mean() for m in (m0, m1)]
    assert tov[1] < tov[0]                            # the net objective trades the fast input less
    assert abs(m1.b[2] / m1.b[1]) < abs(m0.b[2] / m0.b[1])


def test_the_walk_is_purged_and_a_planted_edge_beats_the_plain_signal(raw):
    P = F.Panels({"net1": lambda: planted(raw, 0.3)})
    seen = []
    real = F.net_fit
    F_fit = lambda spec, X, y, c, di, sj, tr: seen.append(P.get("net1")["ts_us"].to_numpy()[tr].max()) or \
        real(spec, X, y, c, di, sj, tr)
    import unittest.mock as um
    with um.patch.object(F, "net_fit", F_fit):
        pos, base = F.walk_net(P, "net1", net_spec(), F.SCREEN_FROM, F.HOLD_FROM)
    for (lo, _), last in zip(F.blocks(F.SCREEN_FROM, F.HOLD_FROM), seen):
        assert last + DAY_US < lo                      # a training row's next day is known before the block
    j, ser = F.judge_net(P, "net1", pos, base, F.SCREEN_FROM, F.HOLD_FROM)
    assert j["days"] == len(ser["net"]) > 1000 and j["sharpe"] > j["base_sharpe"] + 1
    r = F.net_trial(P, net_spec(), "t")
    assert r["fitness"] == pytest.approx(j["sharpe"]) and r["screen_pass"]
    noise = F.Panels({"net1": lambda: planted(raw, 0.0)})
    assert F.net_trial(noise, net_spec(), "t")["fitness"] < 1.0
    row = F.net_registry_row(r)
    assert row["id"] == f"factory:t7_net:{r['key']}" and row["family"] == "factory" and row["sharpe"] == r["fitness"]


def test_a_net_spec_is_drawn_and_mutated_inside_its_own_space(raw):
    import random
    P = F.Panels({"net1": lambda: F.net_panel(raw)})
    rng = random.Random(0)
    rows, have = [], set()
    for i in range(6):
        s = F.net_draw(rng, P, "net1", rows, have, 1.0 if i < 3 else 0.0)
        assert s["learner"] == "ridge_net" and not s["trees"] and s["params"]["kappa"] in (0.0, 1.0, 4.0, 16.0)
        assert F.spec_key(s) not in have and "target" not in s["features"] and "cost" not in s["features"]
        rows.append(F.net_trial(P, s, "t"))
        have.add(rows[-1]["key"])
    assert all(r.get("error") is None for r in rows)


def test_the_look_is_written_before_it_is_scored_and_needs_the_deflated_bar(raw, dirs):
    P = F.Panels({"net1": lambda: planted(raw, 0.3)})
    r = F.net_trial(P, net_spec(), "t")
    seen = []
    real = F.walk_net
    import unittest.mock as um
    with um.patch.object(F, "walk_net", lambda *a, **k: seen.append(
            [x["status"] for x in F._jl(F.net_holdout_path())]) or real(*a, **k)):
        small = F.net_look(P, r, {"n_trials": 2, "var": 1e-6, "sr0_annual": 0.0}, "t")
    assert seen == [["looking"]] and small["passed"] and small["dsr"] >= 0.95
    big = F.net_look(P, r, {"n_trials": 10 ** 9, "var": 1.0, "sr0_annual": 99.0}, "t")
    assert not big["passed"] and big["held"]["sharpe"] > big["held"]["base_sharpe"]
    assert [x["status"] for x in F._jl(F.net_holdout_path())] == ["looking", "done", "looking", "done"]
    assert not F._jl(F.holdout_path())             # G2's own looks untouched


def test_the_cpcv_of_a_net_spec_has_every_path(raw):
    P = F.Panels({"net1": lambda: planted(raw, 0.3)})
    cp = F.net_cpcv(P, "net1", net_spec())
    assert cp["paths"] == 5 and cp["splits"] == 15 and cp["p10"] <= cp["median"] and cp["median"] > 0


def test_a_net_shadow_logs_positions_before_the_outcome_and_is_scored_by_the_net(raw, dirs):
    p = planted(raw, 0.3)
    last = p["ts_us"].max()
    P = F.Panels({"net1": lambda: p})
    m = {"key": "abc", "target": "net1", "spec": net_spec(), "what": "x", "added_day": "2026-10-27",
         "status": "shadow", "scored_days": 0}
    assert F.net_shadow_forecast(P, m, NOW_MS) == 5
    logged = F._jl(F.shadow_log("abc"))
    assert {r["ts_us"] for r in logged} == {last} and all(abs(r["pos"]) <= 1 for r in logged)
    assert F.net_shadow_forecast(P, m, NOW_MS) == 0                       # never twice
    # the outcome arrives: the same rows with a known target, plus the shadow's earlier days
    rows = [{"ts_us": int(t), "symbol": s, "pos": 1.0, "baseline": -1.0, "recorded_ms": 0}
            for t, s in zip(p["ts_us"].to_numpy()[-40:-5], p["symbol"].to_numpy()[-40:-5])]
    d = F.net_daily(rows, p)
    assert d.height == 7 and set(d.columns) == {"ts_us", "model", "baseline", "incumbent"}
    sub = p.filter(pl.col("ts_us") == d["ts_us"][3])
    assert d["model"][3] == pytest.approx(-sub["target"].mean())         # long all five, held, no cost
    assert d["baseline"][3] == pytest.approx(sub["target"].mean())
    F._write_json(F.shadows_path(), {"members": [m]})
    sh = F.shadow_step(P, NOW_MS, log=lambda *_: None)
    assert sh["members"][0]["status"] == "shadow" and "net1" not in sh["picks"]


# ---------------------------------------------------------------- meta-labelling as a size

def toy_rule(T: int = 300, n: int = 4, seed: int = 0):
    rng = np.random.default_rng(seed)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, (T, n)), axis=0))
    W = (rng.random((T, n)) < 0.5).astype(float)
    W = np.repeat(W[::5], 5, axis=0)[:T] * 0.25
    return px, W


@pytest.mark.parametrize("p", [np.array([0.3, 1.7, -0.4, 0.99]), np.array([np.nan, 0.5, 2.0, 1.0])])
def test_the_meta_size_is_never_above_one(p):
    px, W = toy_rule()
    tr = ML.trades(W)
    pk = np.resize(p, len(tr))
    S = ML.sized(W, tr, pk)
    assert np.all(S <= W + 1e-15) and np.all(S >= 0)
    f = ML.sized(np.ones_like(W), tr, pk)
    assert f.max() <= 1.0 and f.min() >= 0.0
    for (j, a, b), q in zip(tr, pk):
        want = 1.0 if not np.isfinite(q) else min(max(q, 0.0), 1.0)
        assert S[a: b if b >= 0 else len(W), j] == pytest.approx(W[a: b if b >= 0 else len(W), j] * want)
    assert np.array_equal(ML.sized(W, tr, np.full(len(tr), np.nan)), W)   # no model yet: the rule


def test_the_late_label_pays_the_round_trip_of_its_era_and_is_known_a_close_later():
    px = np.array([[100.0], [101.0], [104.0], [103.0], [106.0], [106.0]])
    W = np.array([[0.0], [1.0], [1.0], [0.0], [0.0], [0.0]])
    tr = ML.trades(W)
    assert tr == [(0, 1, 3)]
    C = np.full((6, 1), 0.001)
    assert ML.labels(px, tr, 0.0)[0] == 1.0                               # on time: 101 to 103
    C[2, 0], C[4, 0] = 0.005, 0.005
    assert ML.labels(px, tr, C, lag=1)[0] == 1.0                          # late: 104 to 106 is 1.9 %, less 1 %
    C[4, 0] = 0.015
    assert ML.labels(px, tr, C, lag=1)[0] == 0.0                          # less 2 %
    assert ML.known_at(tr, 6, 1)[0] == 4 and ML.known_at(tr, 6)[0] == 3
    open_ = ML.trades(np.array([[0.0], [0.0], [0.0], [0.0], [1.0], [0.0]]))
    assert np.isnan(ML.labels(px, open_, C, lag=1)[0]) and ML.known_at(open_, 6, 1)[0] == 6


def test_the_meta_features_have_no_lookahead():
    px, W = toy_rule(T=400, n=5, seed=4)
    tr = ML.trades(W)
    X = ML.features(px, W, tr, 0)
    rng = np.random.default_rng(9)
    for cut in (150, 250, 330):
        px2, W2 = px.copy(), W.copy()
        px2[cut + 1:] *= np.exp(rng.normal(0, 0.5, px2[cut + 1:].shape))
        W2[cut + 1:] = (rng.random(W2[cut + 1:].shape) < 0.5) * 0.25
        tr2 = ML.trades(W2)
        X2 = ML.features(px2, W2, tr2, 0)
        # every trade opened at or before the cut has the same features, whatever comes after
        a = {(j, s): X[k] for k, (j, s, _) in enumerate(tr) if s <= cut}
        b = {(j, s): X2[k] for k, (j, s, _) in enumerate(tr2) if s <= cut}
        assert a.keys() == b.keys()
        for k in a:
            assert np.array_equal(a[k], b[k], equal_nan=True)


def test_the_meta_walk_trains_only_on_trades_whose_late_label_is_known():
    px, W = toy_rule(T=1200, n=6, seed=2)
    days = dc.us("2020-01-01") + np.arange(1200) * DAY_US
    blocks = t7.yearly_blocks(days)
    seen = []
    real = F.walk

    def spy(X, y, t, known, blocks_, names, min_train=50, log=print):
        for lo, _ in blocks_:
            seen.append(known[known < lo].max() if (known < lo).any() else -1)
        return real(X, y, t, known, blocks_, names, min_train, log)
    import unittest.mock as um
    with um.patch.object(F, "walk", spy):
        mp = t7.meta_probability(px, W, 0, np.full(px.shape, 0.001), blocks, log=lambda *_: None)
    assert all(k < lo for k, (lo, _) in zip(seen, blocks))
    t = mp["t"].astype(int)
    assert np.isnan(mp["p"][t < blocks[0][0]]).all() and np.isfinite(mp["p"][t >= blocks[1][0]]).any()


def test_held_keeps_the_targets_between_rebalances():
    W = np.array([[0.5, np.nan], [0.1, 0.1], [np.nan, 0.3], [0.0, 0.2]])
    reb = np.array([True, False, True, True])
    assert t7.held(W, reb) == pytest.approx(np.array([[0.5, 0.0], [0.5, 0.0], [0.5, 0.3], [0.0, 0.2]]))
    f = np.full(W.shape, 0.5)
    v = t7.variant(W, f)
    assert np.isnan(v[0, 1]) and v[1, 0] == pytest.approx(0.05)


# ---------------------------------------------------------------- the study end to end

def test_the_net_part_registers_every_spec_first_and_admits_only_a_pass(raw, dirs, monkeypatch):
    monkeypatch.setattr(t7, "N_SPECS", 6)
    monkeypatch.setattr(t7, "N_RANDOM", 3)
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    monkeypatch.setattr(dc, "BOOT_DRAWS", 200)
    seen = []
    real = F.net_look
    monkeypatch.setattr(F, "net_look", lambda *a, **k: seen.append(
        sum(1 for r in metrics.read_registry() if r["id"].startswith("factory:t7_net:"))) or real(*a, **k))
    P = F.Panels({"net1": lambda: planted(raw, 0.3)})
    out = t7.net_part(P, log=lambda *_: None)
    ids = [r["id"] for r in metrics.read_registry()]
    assert sum(1 for i in ids if i.startswith("factory:t7_net:")) == 7 and "factory:t7_net:plain_signal" in ids
    assert all(n == 7 for n in seen)                        # every trial registered before a look
    assert len(F._jl(F.net_ledger_path())) == 6 and len(out["looks"]) <= t7.N_LOOKS
    sh = F._read_json(F.shadows_path(), {"members": []})["members"]
    assert {m["key"] for m in sh} == {h["key"] for h in out["looks"] if h.get("passed")} == set(out["admitted"])
    md = t7.markdown(json.loads(json.dumps({"generated": "test", "costs": "test", "A": out,
                                            "B": {"rows": [], "pool": out["pool"]}}, default=float)))
    assert "## A. The net target" in md and "\u2014" not in md


def test_the_meta_part_registers_its_variants_first(monkeypatch):
    from test_pit_universe_t5 import toy_panel
    P = dc.cut_panel(toy_panel(monkeypatch, days=2400, extra=20, seed=7), t7.VAL_TO)
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    monkeypatch.setattr(dc, "BOOT_DRAWS", 200)
    seen = []
    real = metrics.register
    monkeypatch.setattr(metrics, "register", lambda rows, path=None: seen.append(len(rows)) or real(rows, path))
    vol = U.median_volume(P)
    out = t7.meta_part(P, vol, None, log=lambda *_: None)
    assert seen == [9]
    ids = {r["id"] for r in metrics.read_registry()}
    for rule in t7.RULES:
        assert f"hand:t5_pit:{rule}:PIT20" in ids
        assert {f"hand:t7_meta:{rule}:filter", f"hand:t7_meta:{rule}:size"} <= ids
    for r in out["rows"]:
        assert r["max_scale"] <= 1.0
        assert set(r["val"]) == set(t7.VARIANTS) and r["passes"] is all(r["conditions"].values())
    # the plain rule is T5's run_rule on PIT20
    plain = t5.run_rule(P, "tsmom1", U.pit(P, 20, vol=vol), 20, t5.era_cost(vol, False))
    assert out["rows"][0]["val"]["plain"]["sharpe"] == pytest.approx(
        t5.stats_of(plain[t5.window(P, t7.VAL_FROM, t7.VAL_TO)])["sharpe"])
    md = t7.markdown(json.loads(json.dumps({"generated": "test", "costs": "test", "B": out,
                                            "A": {"plain_screen": None, "by_kappa": [], "specs": [], "pbo": None,
                                                  "looks": [], "admitted": [], "trials": []}}, default=float)))
    assert md.count("| breakout_top10 |") == 1 and "\u2014" not in md
