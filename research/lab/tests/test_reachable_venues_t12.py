"""T12 without a data folder: the venue listings (Kraken's later of openingDate and first funding, Hyperliquid's
kPEPE and delisted perps) and no coin on a venue before its first record, in the universe, M4's and carry's books
and the low-vol PIT50; funding summed at each venue's schedule (Hyperliquid 8-hourly then hourly, Kraken hourly)
over T6's windows on a toy series; the venue's cost one tier wider; ERC weighted on Binance's legs before the
venue's start; the survive rule; the 17 trials registered before any judged number; a planted look-ahead caught by
T1's harness on the venue's low-vol weight function.

Run from research/lab:  python -m pytest tests/test_reachable_venues_t12.py
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.experiments import director_common as dc
from lab.experiments import fam_common as fc
from lab.experiments import pit_universe_t5 as t5
from lab.experiments import reachable_venues_t12 as t12
from lab.experiments import two_leads_t6 as t6
from lab.experiments import xs_daily as xs

D, H = fc.DAY_US, t12.HOUR_US


# ---------------------------------------------------------------- listings: no coin before its first record

def test_listings_take_krakens_later_first_record_and_hyperliquids_base_and_last_day():
    hl = {"kPEPE": {"base": "PEPE", "first_ts_us": dc.us("2023-05-12"), "delisted": False},
          "AI": {"base": "AI", "first_ts_us": dc.us("2024-02-19") + 6 * H, "delisted": True,
                 "last_ts_us": dc.us("2025-04-11") + 13 * H},
          "GONE": {"base": "GONE", "first_ts_us": None}}
    lst = t12.listings("hyperliquid", hl)
    assert set(lst) == {"PEPE", "AI"}
    assert lst["AI"] == (dc.us("2024-02-19") + 6 * H, dc.us("2025-04-11"))
    kf = {"PF_XBTUSD": {"base": "BTC", "first_ts_us": dc.us("2025-10-15"), "opening_us": dc.us("2022-01-01")},
          "PF_AAPLXUSD": {"base": "AAPLx", "first_ts_us": dc.us("2026-02-06") + 2 * H,
                          "opening_us": dc.us("2026-02-06") + 3 * H}}
    lst = t12.listings("kraken_futures", kf)
    assert lst["BTC"][0] == dc.us("2025-10-15") and lst["AAPLx"][0] == dc.us("2026-02-06") + 3 * H
    days = dc.us("2025-10-13") + np.arange(6) * D
    on = t12.on_venue(days, ["BTC", "ETH", ""], lst)
    assert on[:, 0].tolist() == [False, False, False, True, True, True]   # listed during 10-15: on from 10-16
    assert not on[:, 1:].any()                                             # unlisted and a reused ticker's old asset


def test_a_delisted_perp_leaves_on_the_day_of_its_last_settlement():
    lst = {"AI": (dc.us("2024-02-19"), dc.us("2025-04-11"))}
    days = dc.us("2025-04-09") + np.arange(4) * D
    assert t12.on_venue(days, ["AI"], lst)[:, 0].tolist() == [True, True, False, False]
    assert t12.coin_key("1000PEPEUSDT") == "PEPE" and t12.coin_key("LUNAUSDT~0") == ""


def toy_m(T: int = 90, N: int = 24, seed: int = 4) -> dict:
    rng = np.random.default_rng(seed)
    syms = np.array(["BTCUSDT", "ETHUSDT"] + [f"C{i:02d}USDT" for i in range(N - 2)])
    return {"days": dc.us("2025-10-01") + np.arange(T) * D, "syms": syms, "R": rng.normal(0, 0.03, (T, N)),
            "fund": rng.normal(1e-4, 2e-4, (T, N)), "perp_adv28": 10 ** rng.uniform(6, 9.5, (T, N)),
            "adv28_raw": 10 ** rng.uniform(6, 9.5, (T, N)), "fund7_raw": rng.normal(1e-4, 5e-4, (T, N)),
            "reg7n": rng.normal(0, 1, (T, N)), "s_F7": rng.normal(0, 1, (T, N))}


def toy_fund(M: dict, lst: dict, seed: int = 1) -> pl.DataFrame:
    """Hourly settlements for every listed coin from its first record."""
    rng = np.random.default_rng(seed)
    rows = []
    for b, (first, _) in lst.items():
        ts = np.arange(first, int(M["days"][-1]) + 2 * D, H)
        rows.append(pl.DataFrame({"base": [b] * len(ts), "ts_us": ts, "rate": rng.normal(1e-5, 3e-5, len(ts))}))
    return pl.concat(rows)


def test_m4_and_carry_never_trade_a_coin_before_its_listing_on_the_venue():
    M = toy_m()
    j = 7                                              # C05 is listed on day 40 at 10:00
    t_list = 40
    lst = {t12.coin_key(s): (int(M["days"][0]) - 10 * D, None) for s in M["syms"]}
    lst[t12.coin_key(M["syms"][j])] = (int(M["days"][t_list]) + 10 * H, None)
    M["reg7n"][:, j] = 9.0                             # always the best score: picked as soon as it may be
    M["s_F7"][:, j] = 9.0
    M["perp_adv28"][:, j] = 1e12
    out = t12.xs_venue(M, M, "hyperliquid", lst, toy_fund(M, lst))
    one = np.zeros(M["R"].shape)
    one[:, j] = 1.0
    from lab.experiments import funding_carry as fcy
    on = t12.on_venue(M["days"], [t12.coin_key(s) for s in M["syms"]], lst)
    assert not on[:t_list + 1, j].any() and on[t_list + 1:, j].all()
    sc = fcy.late(np.where(on, M["reg7n"], np.nan))
    _, cost, _, _ = xs.book_buffer(M, sc, 3, 0.5, 100, C=one)
    first = int(np.flatnonzero(cost > 0)[0])
    assert first == t_list + 2                         # on from day 41, decided at its close, filled one close late
    assert out["counts"]["M4"][:t_list + 1].max() == M["R"].shape[1] - 1
    sv = t12.fund7(t12.daily(toy_fund(M, lst), "known"), M["days"], [t12.coin_key(s) for s in M["syms"]])
    assert np.isnan(sv[:t_list, j]).all()              # no funding before the first record either


def test_the_low_vol_pit50_holds_no_coin_before_its_listing(monkeypatch):
    from lab import universe as U
    from test_pit_universe_t5 import toy_panel
    P = toy_panel(monkeypatch)
    keys = [t12.coin_key(n) for n in P.names]
    lst = {k: (int(P.days[0]) + (60 + 7 * i) * D + 5 * H, None) for i, k in enumerate(keys) if k}
    vol = U.median_volume(P)
    out = t12.lowvol_venue(P, vol, pl.DataFrame({"base": [], "kind": [], "known_us": []}), "kraken_futures", lst,
                           pl.DataFrame(schema={"base": pl.String, "ts_us": pl.Int64, "rate": pl.Float64}))
    on = t12.on_venue(P.days, keys, lst)
    uni = U.pit(P, 50, table=pl.DataFrame({"base": [], "kind": [], "known_us": []}), vol=np.where(on, vol, np.nan))
    assert not (uni & ~on).any()
    for j, k in enumerate(keys):
        if k:
            t0 = int(np.searchsorted(P.days, lst[k][0]))     # the first day starting after its first record
            assert P.days[t0 - 1] < lst[k][0] < P.days[t0] and not uni[:t0, j].any()
    assert (out["counts"] == uni.sum(1)).all()


# ---------------------------------------------------------------- funding at each venue's schedule

def test_funding_is_summed_at_each_venues_schedule_over_t6s_windows():
    d0 = dc.us("2023-06-07")
    # Hyperliquid: 8-hourly to 2023-06-08 00:00, hourly after; each settlement worth 1 / its count of the day
    hl = [d0 + h * H for h in range(0, 24, 8)] + [d0 + D] + [d0 + D + h * H for h in range(1, 48)]
    rate = [0.0008] * 4 + [0.0001] * 47
    kr = [d0 + h * H for h in range(1, 72)]
    f = pl.concat([pl.DataFrame({"base": "BTC", "ts_us": hl, "rate": rate}),
                   pl.DataFrame({"base": "ETH", "ts_us": kr, "rate": [1e-5] * len(kr)})])
    days = d0 + np.arange(3) * D
    utc = t12.matrix(t12.daily(f, "utc"), days, ["BTC", "ETH"], 0.0)
    assert utc[0, 0] == pytest.approx(3 * 0.0008) and utc[1, 0] == pytest.approx(0.0008 + 23 * 0.0001)
    assert utc[0, 1] == pytest.approx(23e-5) and utc[1, 1] == pytest.approx(24e-5)
    known = t12.matrix(t12.daily(f, "known"), days, ["BTC", "ETH"], 0.0)
    assert known[0, 0] == pytest.approx(3 * 0.0008)    # 08:00, 16:00 and 00:00 of the next day, known at the close
    assert known[1, 0] == pytest.approx(24 * 0.0001)
    hold = t12.matrix(t12.daily(f, "hold"), days, ["BTC", "ETH"], 0.0)
    # decided at the close of d0, held from 01:00 of d0 + 1 to 01:00 of d0 + 2: 01:00 is the last one paid
    want = sum(r for t, r in zip(hl, rate) if d0 + D + H < t <= d0 + 2 * D + H)
    assert hold[0, 0] == pytest.approx(want) and hold[0, 1] == pytest.approx(24e-5)
    assert hold[1, 1] == pytest.approx(sum(1e-5 for t in kr if d0 + 2 * D + H < t <= d0 + 3 * D + H))


def test_the_funding_of_a_day_is_the_binance_convention_on_a_venue_with_8_hour_settlements():
    """Binance's perp_daily: fund_hold of d is the settlements in (01:00 of d + 1, 01:00 of d + 2]; on an 8-hour
    schedule that is 08:00, 16:00 of d + 1 and 00:00 of d + 2."""
    d0 = dc.us("2024-03-01")
    ts = [d0 + D + h * H for h in (0, 8, 16, 24, 32)]
    f = pl.DataFrame({"base": "X", "ts_us": ts, "rate": [1.0, 2.0, 4.0, 8.0, 16.0]})
    hold = t12.matrix(t12.daily(f, "hold"), np.array([d0]), ["X"], 0.0)
    assert hold[0, 0] == pytest.approx(2.0 + 4.0 + 8.0)


def test_funding_is_cut_before_the_lockbox(tmp_path, monkeypatch):
    from lab.collect import pit
    monkeypatch.setattr(pit, "FREE", tmp_path)
    d = tmp_path / "perps_all" / "hyperliquid" / "funding"
    d.mkdir(parents=True)
    ts = [t12.CUT_US - H, t12.CUT_US, t12.CUT_US + H]
    pl.DataFrame({"ts_us": ts, "coin": "kPEPE", "funding_rate": [1.0, 2.0, 3.0]}).write_parquet(d / "kPEPE.parquet")
    f = t12.read_funding("hyperliquid", {"kPEPE": {"base": "PEPE"}})
    assert f["ts_us"].to_list() == [t12.CUT_US - H] and f["base"].to_list() == ["PEPE"]


# ---------------------------------------------------------------- costs

def test_the_venue_cost_is_its_taker_of_the_era_plus_t5s_tier_one_wider():
    vol = np.array([[5e9, 5e8, 5e7, 5e6, 5e5]])
    assert np.allclose(t12.wider_half_spread(vol), [[3e-4, 10e-4, 25e-4, 50e-4, 50e-4]])
    assert (t12.wider_half_spread(vol) >= t5.half_spread(vol)).all()
    days = np.array([dc.us("2023-12-31"), dc.us("2024-01-01"), dc.us("2025-05-01")])
    assert np.allclose(t12.venue_fee("hyperliquid", days), [2.5e-4, 3.5e-4, 4.5e-4])
    assert np.allclose(t12.venue_fee("kraken_futures", days), 5e-4)
    c = t12.venue_cost("kraken_futures", days[:1], vol)
    assert np.allclose(c, 5e-4 + t12.wider_half_spread(vol))


# ---------------------------------------------------------------- the book on a venue

def test_erc_before_the_venue_start_is_weighted_on_binances_legs_and_returns_are_the_venues():
    rng = np.random.default_rng(2)
    T = 200
    days = dc.us("2023-01-01") + np.arange(T) * D
    Rb = rng.normal(0, [0.01, 0.02, 0.04], (T, 3))
    Rv = rng.normal(0, [0.04, 0.02, 0.01], (T, 3))
    Rv[:120] = np.nan
    out = t12.mixed_combos(days, Rv, Rb)
    assert np.isnan(out["ERC"][:120]).all() and np.isfinite(out["ERC"][120:]).all()
    from lab.experiments.perps_neutral_portfolio import erc
    w = erc(np.cov(Rb[30:120], rowvar=False))
    # Binance's risk, the venue's return, the first reweight charged
    assert out["ERC"][120] == pytest.approx(float(w @ Rv[120]) - t6.REWEIGHT_COST)
    assert w[0] > w[2]


def test_a_leg_starts_with_its_first_position():
    x = np.array([np.nan, 0.0, 0.0, 0.01, 0.0, -0.02])
    y = t12.lead_zeros_out(x)
    assert np.isnan(y[:3]).all() and y[3:].tolist() == [0.01, 0.0, -0.02]


# ---------------------------------------------------------------- judging

def _series(T, seed, edge):
    rng = np.random.default_rng(seed)
    return rng.normal(edge, 0.01, T)


@pytest.mark.parametrize("edge,want", [(0.003, "survives"), (0.0012, "partly"), (-0.001, "no")])
def test_the_survive_rule(edge, want):
    T = 900
    days = dc.us("2024-01-01") + np.arange(T) * D
    pool = {"n_trials": 10, "var": 1e-5}
    btc = np.random.default_rng(9).normal(0, 0.03, T)
    r = t12.judge(days, _series(T, 1, edge), _series(T, 2, 0.004), btc, True, pool, pool)
    assert r["verdict"] == want
    assert set(r["conditions"]) == {"Sharpe 1.0 or more", "at least half of Binance's", "bootstrap 5 % above 0",
                                    "correlation with BTC within +-0.3", "positive in 2 of 2024, 2025, 2026"}
    assert r["kept"] == pytest.approx(r["sharpe"] / r["binance"])


def test_half_of_binance_fails_a_venue_that_keeps_less():
    T = 900
    days = dc.us("2024-01-01") + np.arange(T) * D
    pool = {"n_trials": 10, "var": 1e-5}
    r = t12.judge(days, _series(T, 1, 0.0012), _series(T, 2, 0.004), np.zeros(T) + 1e-9 * np.arange(T), False,
                  pool, pool)
    assert not r["conditions"]["at least half of Binance's"] and r["verdict"] == "partly"
    assert "positive in 2 of 2024, 2025, 2026" not in r["conditions"]   # Kraken: the overlap only


def test_the_17_trials_are_registered_before_any_judged_number(tmp_path, monkeypatch):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    monkeypatch.setattr(dc, "ledger_trials", lambda: [])
    T = 1300
    days = dc.us("2023-01-01") + np.arange(T) * D
    S = {}
    for v, start in (("hyperliquid", 140), ("kraken_futures", 1020)):
        s = {k: _series(T, i, 0.002) for i, k in enumerate(t12.TRIALS)}
        for k in s:
            s[k][:start] = np.nan
        S[v] = s
    B = {k: _series(T, 40 + i, 0.002) for i, k in enumerate(t6.CANDIDATES)}
    seen = []
    real = t12.judge

    def spy(*a, **k):
        seen.append({r["id"] for r in metrics.read_registry(reg)})
        return real(*a, **k)
    monkeypatch.setattr(t12, "judge", spy)
    out = t12.evaluate(days, S, B, np.zeros(T) + 1e-9 * np.arange(T), log=lambda *_: None)
    rows = [json.loads(x) for x in reg.read_text().splitlines()]
    mine = [r for r in rows if r["id"].startswith("hand:t12:")]
    assert len(mine) == 17 and len(out["trials"]) == 17 and all(r["family"] == "hand" for r in mine)
    assert all(len({r["id"] for r in mine} - s) == 0 for s in seen) and len(seen) == 2
    hl = [r for r in mine if r["id"].startswith("hand:t12:hyperliquid:")]
    assert len(hl) == 8 and all(r["sharpe"] is not None for r in hl)
    assert all(r["sharpe"] is None for r in mine if not r["id"].startswith("hand:t12:hyperliquid:"))
    assert "hand:t12:binance:erc_kraken_days" in out["trials"]
    k = out["venues"]["kraken_futures"]
    assert k["from"] == dc.day_str(days[1020]) and k["table"]["ERC"]["is"] is None and not k["years"]
    assert out["venues"]["hyperliquid"]["from"] == "2024-01-01"


# ---------------------------------------------------------------- T1's harness on the venue's weight function

def venue_weights(lst):
    from lab import universe as U
    from lab.experiments.fam_lowvol import weights

    def fn(Q):
        on = t12.on_venue(Q.days, [t12.coin_key(n) for n in Q.names], lst)
        uni = U.pit(Q, 50, table=pl.DataFrame({"base": [], "kind": [], "known_us": []}),
                    vol=np.where(on, U.median_volume(Q), np.nan))
        return weights(t5.on(Q, uni), "vol 60d", 50, "beta-neutral BAB")
    return fn


def test_t1s_harness_passes_the_venues_low_vol_weights_and_catches_a_planted_look_ahead(monkeypatch):
    from lab.leak import checks
    from test_pit_universe_t5 import toy_panel
    P = toy_panel(monkeypatch, days=300)
    lst = {t12.coin_key(n): (int(P.days[0]) + 20 * D, None) for n in P.names if t12.coin_key(n)}
    fn = venue_weights(lst)
    assert checks.book("t12 venue lowvol", fn, P, n_cuts=2)["ok"]

    def peek(Q):
        W = fn(Q).copy()
        up = np.zeros(W.shape)
        up[:-1] = np.nan_to_num(Q.ret[1:]) > 0                 # plus whatever rises tomorrow
        return np.nan_to_num(W) + 0.01 * up
    res = checks.book("t12 venue lowvol peek", peek, P, n_cuts=2)
    assert not res["ok"] and res["first"]["column"] in P.names
