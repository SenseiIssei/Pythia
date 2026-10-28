"""T5 on a synthetic panel (no data folder): the point-in-time universe never holds a coin before its first or
after its last bar, ranks by the 30-day median dollar volume, leaves out pegs and wrapped coins and drops a coin
from its delisting day; the per-coin cost simulator against fam_common's and trend_shorts' own; F2's Donchian
100/50 against the factory's code; the late fill; the era's cost tiers; the study end to end, its 18 trials in
the registry.

Run from research/lab:  python -m pytest tests/test_pit_universe_t5.py
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab import universe as U
from lab.experiments import director_common as dc
from lab.experiments import fam_common as fc
from lab.experiments import pit_universe_t5 as t5
from lab.factory import small as f2

D = fc.DAY_US
D0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)


def toy_panel(monkeypatch, days: int = 400, extra: int = 14, seed: int = 5) -> fc.Panel:
    """BTC, ETH and SOL plus `extra` coins with random lives and gaps, a stablecoin, a wrapped BTC and an old
    segment of a reused ticker; perps (with funding) for half of them."""
    rng = np.random.default_rng(seed)
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "USDCUSDT", "WBTCUSDT", "LUNAUSDT~0"] + [f"C{i:02d}USDT" for i in range(extra)]
    rows, perp = [], []
    for k, s in enumerate(syms):
        a = 0 if k < 4 else int(rng.integers(0, days // 2))
        b = days if k < 4 else int(rng.integers(a + 40, days + 1))
        if s == "LUNAUSDT~0":
            a, b = 10, 250
        px = 10.0 * np.exp(np.cumsum(rng.normal(0.0005, 0.04, b - a)))
        scale = {"BTCUSDT": 3e9, "ETHUSDT": 1e9, "USDCUSDT": 5e9, "WBTCUSDT": 4e9}.get(s, 10 ** rng.uniform(5, 8.5))
        for i, t in enumerate(range(a, b)):
            if k >= 4 and rng.random() < 0.05:
                continue                                  # a day without a bar
            c = float(px[i])
            rows.append({"day": D0 + t * D, "symbol": s, "close": c, "high": c * 1.02, "low": c * 0.98,
                         "rv": float(rng.uniform(0.0004, 0.003)), "qv": float(scale * rng.lognormal(0, 0.5)), "n": 24})
            if k % 2 == 0:
                perp.append({"day": D0 + t * D, "base": fc.base_of(s), "funding": float(rng.normal(1e-4, 3e-4)),
                             "perp_qv": 1e7})
    pp = pl.DataFrame(perp)
    monkeypatch.setattr(fc, "perp_daily_for", lambda last: pp)
    return fc.panel_from(pl.DataFrame(rows))


# ---------------------------------------------------------------- the universe

def test_median_volume_is_the_median_of_the_bars_in_the_last_30_days(monkeypatch):
    P = toy_panel(monkeypatch)
    v = U.median_volume(P, rows=37)                     # an odd chunk size: the chunks join seamlessly
    qv = np.where(P.traded, P.extra["qv"], np.nan)
    for t in (0, 19, 25, 29, 30, 200, P.T - 1):
        for j in range(P.N):
            w = qv[max(0, t - 29):t + 1, j]
            w = w[np.isfinite(w)]
            want = np.median(w) if len(w) >= 20 else np.nan
            assert (np.isnan(want) and np.isnan(v[t, j])) or v[t, j] == pytest.approx(want)


@pytest.mark.parametrize("n", [1, 3, 5, 20])
def test_pit_never_holds_a_coin_before_its_first_or_after_its_last_trading_day(monkeypatch, n):
    P = toy_panel(monkeypatch)
    m = U.pit(P, n, table=pl.DataFrame({"base": [], "kind": [], "known_us": []}))
    traded = np.asarray(P.traded)
    first, last = P.extra["first"], P.extra["last"]
    idx = np.arange(P.T)[:, None]
    assert not (m & ((idx < first[None, :]) | (idx > last[None, :]))).any()
    assert not (m & ~traded).any()                      # and only on days with a bar
    assert (m.sum(1) <= n).all() and m.any()
    for j, b in enumerate(P.bases):
        if b in ("USDC", "WBTC"):
            assert not m[:, j].any()                    # pegs and wrapped coins never
    assert m[:, P.names.index("LUNAUSDT~0")].any() or n < 3    # an old segment of a reused ticker counts


def test_pit_takes_the_n_largest_by_median_volume(monkeypatch):
    P = toy_panel(monkeypatch)
    v = U.median_volume(P)
    m = U.pit(P, 3, vol=v, table=pl.DataFrame({"base": [], "kind": [], "known_us": []}))
    coin = np.array([b not in U.NOT_COINS for b in P.bases])
    for t in range(30, P.T, 17):
        ok = np.flatnonzero(P.traded[t] & np.isfinite(v[t]) & coin)
        want = set(ok[np.argsort(-v[t, ok], kind="stable")][:3].tolist())
        assert set(np.flatnonzero(m[t]).tolist()) == want
    assert m[60:, P.btc].all()                          # BTC trades every day at the top


def test_pit_drops_a_coin_from_the_day_its_delisting_was_announced(monkeypatch):
    P = toy_panel(monkeypatch)
    t_ann = 150
    table = pl.DataFrame({"base": ["ETH"], "kind": ["spot"], "known_us": [D0 + t_ann * D + 3_600_000_000]})
    e = P.col("ETHUSDT")
    m = U.pit(P, 5, table=table)
    assert m[t_ann - 1, e] and not m[t_ann:, e].any()
    assert U.pit(P, 5, drop_delisting=False, table=table)[t_ann:, e].any()


# ---------------------------------------------------------------- costs, fills, the simulator

def test_half_spread_follows_the_coins_volume_of_the_day():
    v = np.array([[2e9, 1e9, 5e8, 1e8, 5e7, 1e7, 5e6, 1e6, 5e5, np.nan]])
    assert (t5.half_spread(v)[0] * 1e4).round(6).tolist() == [1, 1, 3, 3, 10, 10, 25, 25, 50, 50]
    assert t5.era_cost(v, True)[0, 0] == pytest.approx(0.0006) and t5.era_cost(v, False)[0, 0] == pytest.approx(0.0011)


def test_late_trades_the_targets_one_close_later():
    W = np.arange(12.0).reshape(4, 3)
    reb = np.array([True, False, True, False])
    W2, r2 = t5.late(W, reb)
    assert np.isnan(W2[0]).all() and (W2[1:] == W[:-1]).all() and r2.tolist() == [False, True, False, True]


def test_the_simulator_matches_fam_common_and_trend_shorts_at_a_flat_cost(monkeypatch):
    from lab.experiments import trend_shorts as ts
    P = toy_panel(monkeypatch)
    rng = np.random.default_rng(1)
    W = np.where(rng.random((P.T, P.N)) < 0.3, rng.uniform(-0.1, 0.15, (P.T, P.N)), 0.0)
    W[:, [P.names.index(s) for s in ("USDCUSDT",)]] = 0.0
    reb = fc.every(P, 3)
    C = np.full((P.T, P.N), 0.002)
    net, gross = t5.simulate(P, W, reb, C, False, 30)
    g, tov, _, _ = fc.simulate(P, W, reb, 30)
    assert np.allclose(gross, g) and np.allclose(net, g - 0.002 * np.r_[0.0, tov[:-1]])
    Wn = np.where(reb[:, None], W, np.nan)
    net, gross = t5.simulate(P, Wn, np.ones(P.T, dtype=bool), C, True, 30)
    o = ts.sim(P, Wn, start=30)
    assert np.allclose(gross, o["gross"]) and np.allclose(net, ts.net(o, 0.002))


def test_the_simulator_charges_each_coin_its_own_cost(monkeypatch):
    P = toy_panel(monkeypatch)
    W = np.zeros((P.T, P.N))
    W[100:, P.btc] = 0.5
    W[100:, P.col("ETHUSDT")] = 0.5
    C = np.zeros((P.T, P.N))
    C[:, P.col("ETHUSDT")] = 0.01
    net, gross = t5.simulate(P, W, np.ones(P.T, dtype=bool), C)
    assert gross[101] - net[101] == pytest.approx(0.005)            # only ETH's half pays, on the next day
    assert np.allclose(np.delete(gross - net, 101)[100:], 0.0, atol=1e-3)


# ---------------------------------------------------------------- the rules

def test_donchian_100_50_is_f2s_genome_on_its_six_assets():
    rng = np.random.default_rng(3)
    T = 700
    sig = 50 * np.exp(np.cumsum(rng.normal(0.001, 0.03, (T, 6)), axis=0))
    sig[:120, 2] = np.nan                                         # one asset starts late
    days = D0 + np.arange(T, dtype=np.int64) * D
    c = f2.Ctx(days=days, px=sig.copy(), sig=sig, sol_eur=np.ones(T), fresh=T - 1, eurusd=1.0)
    g = {"universe": {"set": "all"}, "signal": {"kind": "donchian", "n": 100, "exit": 0.5},
         "filters": [{"kind": "trend", "ma": 100}], "select": {"k": 1, "rank": "mom90"},
         "weight": {"scheme": "equal", "fill": "full", "target": 0.2}, "rebalance": {"every": 7, "band": 0.0}}
    want = f2.weights(c, g)
    got = t5.donchian_weights(sig, np.ones((T, 6), dtype=bool))
    assert np.allclose(got, want) and (want > 0).any()
    some = np.zeros((T, 6), dtype=bool)
    some[:, :3] = True
    assert not (t5.donchian_weights(sig, some)[:, 3:] > 0).any()   # never outside the universe


def test_every_rule_stays_inside_its_universe(monkeypatch):
    P = toy_panel(monkeypatch)
    uni = U.pit(P, 5, table=pl.DataFrame({"base": [], "kind": [], "known_us": []}))
    Pu = t5.on(P, uni)
    for rule in t5.RULES:
        for W, reb, _ in t5.books(Pu, rule, 5):
            x = np.where(reb[:, None], np.nan_to_num(W), 0.0)
            if rule == "breakout_top10":
                # a held breakout coin is kept until its own exit; only entries need the universe
                prev = np.r_[np.zeros((1, P.N)), np.nan_to_num(W[:-1])]
                x = np.where(np.isfinite(W) & (W != 0) & (prev == 0), W, 0.0)
            assert not ((x != 0) & ~uni).any(), rule


# ---------------------------------------------------------------- end to end

def test_the_study_end_to_end_registers_its_18_trials_first(monkeypatch, tmp_path):
    P = toy_panel(monkeypatch, days=1700, extra=24)
    P = dc.cut_panel(P, t5.VAL_TO)
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    monkeypatch.setattr(dc, "BOOT_DRAWS", 200)
    vol = U.median_volume(P)
    unis = t5.universes(P, vol, pl.DataFrame({"base": [], "kind": [], "known_us": []}))
    seen = []
    real = metrics.register
    monkeypatch.setattr(metrics, "register", lambda rows, path=None: seen.append(len(rows)) or real(rows, path))
    out = t5.evaluate(P, unis, vol, log=lambda *_: None)
    assert seen == [18]
    reg = metrics.read_registry()
    ids = {r["id"] for r in reg}
    assert all(f"hand:t5_pit:{r}:{u}" in ids for r in t5.RULES for u in t5.UNIVERSES)
    assert len(out["rows"]) == 18 and len(out["gaps"]) == 6
    for g in out["gaps"]:
        by = {r["universe"]: r for r in out["rows"] if r["rule"] == g["rule"]}
        assert g["val_sharpe_gap_PIT20"] == pytest.approx(by["LAB20"]["val"]["sharpe"] - by["PIT20"]["val"]["sharpe"])
        assert g["band_lo"] <= g["band_hi"]
    assert all(r["val"]["days"] > 0 and np.isfinite(r["is"]["sharpe"]) for r in out["rows"])
    out["about"] = t5.about(P, unis, t5.window(P, t5.IS_FROM, t5.IS_TO), t5.window(P, t5.VAL_FROM, t5.VAL_TO), None)
    out["generated"] = "test"
    md = t5.markdown(json.loads(json.dumps(out, default=float)))
    assert "survivorship premium" in md and md.count("| tsmom1 |") == 4 and "\u2014" not in md
