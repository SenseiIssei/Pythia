"""T11 without a data folder: funding accrued at both venues' schedules (Hyperliquid hourly, Binance every 8 or 4
hours) on a toy series, the decision at 23:00 blind to the 23:00 settlement and filled at the next 00:00, no pair
before both venues list the coin, entry and exit by the gap's level and persistence, the era's fees and the wider
tiers at 10k, the marks, T1's harness on the decision, and the run end to end: its 5 trials registered before any
validation number.

Run from research/lab:  python -m pytest tests/test_hl_funding_t11.py
"""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.experiments import director_common as dc
from lab.experiments import hl_funding_t11 as t11

H, DAY = t11.H, t11.DAY_US


def frames(Td: int, coins: list[str], hl_rate, bn_rate, iv: int = 8, hl_from: int = 0, bn_from: int = 0,
           d0: str = "2024-01-01") -> tuple[np.ndarray, np.ndarray, pl.DataFrame, pl.DataFrame]:
    """Day and hour grids and the two venues' rows; hl_rate(k, j) and bn_rate(k, j) at hour k; a venue's first
    row at hour hl_from / bn_from. Stamps a few ms after the hour, as the venues' are."""
    days = dc.us(d0) + np.arange(Td, dtype=np.int64) * DAY
    hours = days[0] + np.arange(24 * Td + 1, dtype=np.int64) * H
    hl, bn = [], []
    for j, c in enumerate(coins):
        for k in range(len(hours)):
            if k >= hl_from:
                ts = int(hours[k]) + 48_000
                hl.append({"ts_us": ts, "coin": c, "funding_rate": float(hl_rate(k, j)), "premium": 0.0,
                           "known_us": ts})
            if k >= bn_from and k % iv == 0:
                ts = int(hours[k]) + 1_000
                bn.append({"coin": c, "funding_time_us": ts, "interval_hours": float(iv),
                           "funding_rate": float(bn_rate(k, j)), "known_us": ts})
    return days, hours, pl.DataFrame(hl), pl.DataFrame(bn)


def toy(Td: int = 10, coins=("AAA", "BBB"), hl_rate=lambda k, j: 0.0, bn_rate=lambda k, j: 0.0, **kw) -> dict:
    coins = list(coins)
    days, hours, hl, bn = frames(Td, coins, hl_rate, bn_rate, **kw)
    N = len(coins)
    return {"days": days, "hours": hours, "coins": coins, "spot": np.full((Td, N), 100.0),
            "perp": np.full((Td, N), 100.0), "vol": np.full((Td, N), 2e9), "uni": np.ones((Td, N), dtype=bool),
            "btc": np.zeros(Td), **t11.hourly(hl, bn, coins, hours),
            "frames": {"hl": hl.drop("premium"), "bn": bn}}


# ---------------------------------------------------------------- funding at both schedules

@pytest.mark.parametrize("iv", [8, 4])
def test_funding_accrues_hourly_and_at_binance_settlements(iv):
    D = toy(Td=4, hl_rate=lambda k, j: 1e-5, bn_rate=lambda k, j: 1e-4, iv=iv)
    hf, bf = t11.daily_funding(D, 4)
    assert np.allclose(hf, 24 * 1e-5)                           # every hour after 00:00 up to the next 00:00
    assert np.allclose(bf, 24 // iv * 1e-4)                     # 3 settlements a day at 8 h, 6 at 4 h
    T = np.zeros((4, 2), dtype=np.int8)
    T[1, 0] = 1                                                 # decided day 1, held over day 2 only
    B = t11.book(D, T)
    assert B["funding"][2] == pytest.approx(t11.LEG * (24 * 1e-5 - 24 // iv * 1e-4))
    assert B["funding"][1] == 0 and B["funding"][3] == 0       # not before the fill, not after the exit


def test_settlement_at_the_fill_hour_belongs_to_the_day_before():
    # only the 00:00 settlements carry a rate: the one at the fill (start of day 2) is day 1's, the next is day 2's
    D = toy(Td=4, hl_rate=lambda k, j: 1e-3 if k % 24 == 0 else 0.0, bn_rate=lambda k, j: 0.0)
    T = np.zeros((4, 2), dtype=np.int8)
    T[1, 0] = 1
    B = t11.book(D, T)
    assert B["funding"][2] == pytest.approx(t11.LEG * 1e-3)    # exactly one 00:00 settlement
    hf, _ = t11.daily_funding(D, 4)
    assert np.allclose(hf[:, 0], 1e-3)                          # each day its closing 00:00 only


def test_direction_short_the_higher_venue():
    D = toy(Td=6, hl_rate=lambda k, j: 1e-4, bn_rate=lambda k, j: 0.0)   # HL 88 % a year above
    T = t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)
    assert (T[1:, 0] == 1).all()                                # short Hyperliquid, long Binance
    D = toy(Td=6, hl_rate=lambda k, j: 0.0, bn_rate=lambda k, j: 8e-4)
    T = t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)
    assert (T[1:, 0] == -1).all()
    B = t11.book(D, T)
    assert (B["funding"][2:] > 0).all()                         # long Hyperliquid pays 0, short Binance receives


# ---------------------------------------------------------------- the late hour

def test_decision_blind_to_the_23_settlement_and_filled_next_day():
    base = lambda k, j: 0.0                                     # noqa: E731
    spike = lambda k, j: 1e-3 if k >= 24 * 3 + 23 else 0.0     # noqa: E731 (from 23:00 of day 3 on)
    a = toy(Td=6, hl_rate=base)
    b = toy(Td=6, hl_rate=spike)
    Ta = t11.decide(a, a["hours"], t11.eligible(a), 0.15, 8)
    Tb = t11.decide(b, b["hours"], t11.eligible(b), 0.15, 8)
    assert (Tb[:4] == Ta[:4]).all() and (Tb[:4] == 0).all()    # day 3's decision does not see it
    early = toy(Td=6, hl_rate=lambda k, j: 1e-3 if k >= 24 * 3 + 15 else 0.0)
    Te = t11.decide(early, early["hours"], t11.eligible(early), 0.15, 8)
    assert (Te[3] == 1).all() and (Te[2] == 0).all()           # 15:00 to 22:00 is the window at 23:00
    B = t11.book(early, Te)
    assert B["pairs"][3] == 0 and B["pairs"][4] == 2           # held from 00:00 of day 4


def test_a_late_row_waits_for_its_known_time():
    D = toy(Td=6, hl_rate=lambda k, j: 1e-3)
    late = D["frames"]["hl"].with_columns(known_us=pl.col("known_us") + 2 * H)   # each row known 2 h late
    Hm = t11.hourly(late, D["frames"]["bn"], D["coins"], D["hours"])
    G, share, _ = t11.signals(Hm, D["hours"], 8)
    assert share[3, 0] == pytest.approx(6 / 8)                  # the two newest hours not known yet


# ---------------------------------------------------------------- listing

def test_no_pair_before_both_venues_list_the_coin():
    hl_from, bn_from = 24 * 2 + 5, 24 * 4 + 2                   # HL from day 2, Binance from day 4
    D = toy(Td=8, hl_rate=lambda k, j: 1e-3, bn_rate=lambda k, j: 0.0, hl_from=hl_from, bn_from=bn_from)
    T = t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)
    first = int(np.flatnonzero(T[:, 0])[0])
    K = 24 * first + t11.DECIDE_H
    assert K - 8 > bn_from and K - 8 >= hl_from                 # both first rows before the window
    assert first == 4 and (T[:4] == 0).all()
    _, _, listed = t11.signals(D, D["hours"], 8)
    assert not listed[:4].any() and listed[4:].all()


def test_universe_and_bars_lag_a_day():
    D = toy(Td=6, hl_rate=lambda k, j: 1e-3)
    D["uni"][:3, 0] = False                                     # in PIT50 from the close of day 3
    D["perp"][4, 1] = np.nan                                    # no Binance bar on day 4
    T = t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)
    assert (T[:4, 0] == 0).all() and T[4, 0] == 1
    assert T[4, 1] == 1 and T[5, 1] == 0                        # out at the decision after the missing bar


# ---------------------------------------------------------------- entry and exit

def test_threshold_persistence_and_exit():
    # 20 % a year: in at theta 15 %, not at 30 %
    r = 0.20 / t11.YEAR_H
    D = toy(Td=6, hl_rate=lambda k, j: r)
    assert t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)[1:, 0].all()
    assert not t11.decide(D, D["hours"], t11.eligible(D), 0.30, 8).any()
    # one hour in three on the other side: mean above theta, share 5/8 below 75 %
    D = toy(Td=6, hl_rate=lambda k, j: -2e-4 if k % 3 == 0 else 3e-4)
    G, share, _ = t11.signals(D, D["hours"], 8)
    assert G[2, 0] > 0.30 and share[2, 0] < t11.PERSIST
    assert not t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8).any()
    # in on days 1 to 3, the gap turns at 12:00 of day 4: out at day 4's decision
    D = toy(Td=7, hl_rate=lambda k, j: 1e-3 if k < 24 * 4 + 12 else -1e-6)
    T = t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)
    assert (T[1:4, 0] == 1).all() and T[4, 0] == 0


def test_limit_ranks_by_the_gap():
    coins = [f"C{i:02d}" for i in range(12)]
    D = toy(Td=4, coins=coins, hl_rate=lambda k, j: 1e-4 * (j + 1))
    T = t11.decide(D, D["hours"], t11.eligible(D), 0.15, 8)
    assert (T[2] != 0).sum() == t11.MAX_POS and (T[2, :2] == 0).all()   # the two smallest gaps left out


# ---------------------------------------------------------------- costs and marks

def test_costs_of_their_era_and_capacity():
    days = np.array([dc.us("2023-06-01"), dc.us("2024-06-01"), dc.us("2025-06-01")])
    vol = np.array([[2e9], [2e9], [2e9]])                       # tier 0 (1 bp) known from the day before
    c1, c10 = t11.costs(days, vol), t11.costs(days, vol, "10k")
    assert c1[1, 0] == pytest.approx(0.0005 + 0.0001 + 0.00035 + 0.0003)
    assert c1[2, 0] == pytest.approx(0.0005 + 0.0001 + 0.00045 + 0.0003)
    assert c10[2, 0] == pytest.approx(0.0005 + 0.0003 + 0.00045 + 0.0010)
    assert c1[0, 0] == pytest.approx(0.0005 + 0.0050 + 0.00025 + 0.0050)   # no volume known yet: the widest tier
    assert t11.hl_fee(np.array([dc.us("2025-05-01")]))[0] == 0.00045


def test_round_trip_and_marks():
    D = toy(Td=5)
    D["perp"][3:, 0] = 110.0                                    # Binance perp up 10 % on day 3
    D["spot"][3:, 0] = 110.0
    D["prem"][24 * 4, 0] = 0.01                                 # HL 1 % rich at day 3's close
    D["prem"][24 * 4 + 1:, 0] = np.nan                          # and no premium after it
    T = np.zeros((5, 2), dtype=np.int8)
    T[1:4, 0] = 1                                               # in at day 1's close, out at day 4's
    B = t11.book(D, T)
    c = t11.costs(D["days"], D["vol"])
    assert B["cost"][1] == pytest.approx(t11.LEG * c[1, 0]) and B["cost"][4] == pytest.approx(t11.LEG * c[4, 0])
    assert B["entries"].sum() == 1
    assert B["fee"][1] == pytest.approx(t11.LEG * (t11.BN_FEE + 0.00035)) and (B["fee"] <= B["cost"]).all()
    rb, rh = t11.marks(D)
    assert rb[3, 0] == pytest.approx(0.10) and rh[3, 0] == pytest.approx(1.1 * 1.01 - 1)
    assert B["price"][3] == pytest.approx(t11.LEG * (0.10 - (1.1 * 1.01 - 1)))   # long Binance, short HL rich
    assert rh[4, 0] == pytest.approx(0.0)                       # the premium carries forward when missing


def test_base_of():
    assert t11.base_of("kPEPE") == "PEPE" and t11.base_of("kBONK") == "BONK"
    assert t11.base_of("BTC") == "BTC" and t11.base_of("KAS") == "KAS"


# ---------------------------------------------------------------- the leak harness and the run

def test_leak_harness_passes_the_decision():
    from lab import leak
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 3e-4, (24 * 20 + 1, 3))
    D = toy(Td=20, coins=("AAA", "BBB", "CCC"), hl_rate=lambda k, j: noise[k, j], bn_rate=lambda k, j: 1e-4)
    res = leak.check(t11.targets_frame(D, 0.15, 8), D["frames"], time="known_us", out_time="ts_us", keys=("coin",))
    assert res["ok"], res
    out = t11.targets_frame(D, 0.15, 8)(D["frames"])
    assert out.height == 20 * 3 and (out["side"] != 0).any()


def test_run_registers_its_five_trials_first(monkeypatch):
    rng = np.random.default_rng(7)
    Td = 120
    noise = rng.normal(0, 4e-4, (24 * Td + 1, 4))
    D = toy(Td=Td, coins=("AAA", "BBB", "CCC", "DDD"), hl_rate=lambda k, j: noise[k, j],
            bn_rate=lambda k, j: 1e-4, d0="2023-11-01")
    D["btc"] = rng.normal(0, 0.03, Td)
    monkeypatch.setattr(t11, "START", "2023-11-02")
    monkeypatch.setattr(t11, "VAL_TO", "2024-02-28")
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    seen = []
    real = metrics.register

    def spy(rows, path=None):
        seen.append([r["id"] for r in rows])
        return real(rows, path)
    monkeypatch.setattr(metrics, "register", spy)
    r = t11.run(D, register=True, leak=False, log=lambda *_: None)
    assert len(seen) == 1 and len(seen[0]) == 5
    assert seen[0][-1] == f"hand:t11:hl_funding:{r['pick']}:10k"
    ids = {x["id"] for x in metrics.read_registry()}
    assert set(r["trials"]) <= ids
    assert r["pick"] == max(r["is_sharpe"], key=r["is_sharpe"].get)
    assert set(r["conditions"]) == {"1 gates", "2 DSR all", "3 DSR family", "4 PBO", "5 leak"}
    assert not r["conditions"]["5 leak"]                        # not run is not a pass
    md = t11.markdown({"generated": "now", "run": r, "capacity": [], "costs": "toy"})
    assert "Every variant" in md and "\u2014" not in md


def test_leak_harness_catches_a_window_that_reads_ahead(monkeypatch):
    from lab import leak
    rng = np.random.default_rng(5)
    noise = rng.normal(0, 3e-4, (24 * 20 + 1, 3))
    D = toy(Td=20, coins=("AAA", "BBB", "CCC"), hl_rate=lambda k, j: noise[k, j], bn_rate=lambda k, j: 1e-4)
    real = t11.signals

    def ahead(Hm, hours, W, decide_h=t11.DECIDE_H):
        return real({**Hm, "hl": np.roll(Hm["hl"], -3, axis=0)}, hours, W, decide_h)   # sees 3 hours ahead
    monkeypatch.setattr(t11, "signals", ahead)
    res = leak.check(t11.targets_frame(D, 0.15, 8), D["frames"], time="known_us", out_time="ts_us", keys=("coin",))
    assert not res["ok"] and res["first"]["column"] == "side"
