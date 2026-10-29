"""R10, the small-account path honestly costed (lab.experiments.smallaccount_r10): the late fill, the venue of its era,
the daily EUR/USD with the way in and back, the ETF tokens at 00:00 UTC, the cleaned premiums, the benchmarks, the
bar, and the hooks it adds to S1's, S2's, F2's and L1's wallets. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_smallaccount_r10.py
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import smallaccount as s1
from lab.experiments import smallaccount_r10 as r10
from lab.experiments import smallaccount_s2 as s2
from lab.factory import small as f2
from lab.metrics import trial_pool
from lab.onchain import longterm as L

from test_smallaccount_s2 import LADDER, T, make_etf, make_panel

CEX = {"BTC": 0.0041, "ETH": 0.0042, "SOL": 0.0043}


def day(s: str) -> int:
    return r10.us_of(s)


def test_late_trades_what_was_known_one_close_earlier():
    W = np.arange(12, dtype=float).reshape(4, 3)
    x = r10.late(W)
    assert (x[0] == 0).all() and np.array_equal(x[1:], W[:-1])
    assert list(r10.late_mask(np.array([True, False, True]))) == [False, True, False]


def test_the_ecb_rates_skip_days_without_a_fixing():
    text = "Date,USD,JPY,\n2026-10-27,1.1650,170.1,\n2026-10-26,N/A,N/A,\n2016-12-30,1.0541,123.4,\n"
    assert r10.ecb_rows(text) == [{"date": "2026-10-27", "eurusd": 1.165}]


def test_a_00utc_price_closes_the_day_before_against_the_last_us_close():
    ms = lambda d: day(d) // 1000
    closes = {"2026-10-23": 100.0, "2026-10-26": 102.0}                  # Friday, Monday
    pts = [[ms("2026-10-24"), 100.5], [ms("2026-10-25"), 101.0], [ms("2026-10-27"), 101.0],
           [ms("2026-10-27") + 3_600_000, 99.0]]                         # not 00:00: ignored
    rows = r10.overnight_rows("SPY", pts, closes)
    assert [(r["date"], r["close_date"], r["us_day"]) for r in rows] == [
        ("2026-10-23", "2026-10-23", True), ("2026-10-24", "2026-10-23", False), ("2026-10-26", "2026-10-26", True)]
    assert rows[0]["dev_bps"] == pytest.approx(50.0) and rows[2]["dev_bps"] == pytest.approx((101 / 102 - 1) * 1e4, abs=1e-3)
    gold = r10.overnight_rows("GOLD", [[ms("2026-10-24"), 4000.0]], {"2026-10-23": 400.0}, per_unit=True)
    assert gold[0]["dev_bps"] == pytest.approx(0.0)


def test_the_cleaning_drops_the_1094_bps_print_and_nothing_else(tmp_path):
    rng = np.random.default_rng(1)
    x = list(45 + rng.normal(0, 25, 120)) + [-1094.209]
    kept = s2.clean(x)
    assert len(kept) == 120 and kept.min() > -500
    assert len(s2.clean([1.0, 2.0])) == 2 and len(s2.clean([5.0] * 10 + [9.0])) == 11     # no spread: kept whole
    p = tmp_path / "prem.csv"
    s1.write_csv(p, [{"symbol": "SPYx", "date": f"d{i}", "premium_bps": round(v, 3)} for i, v in enumerate(x)])
    n = f2.premium_noise(p)["SPY"]
    assert len(n) == 120 and abs(n.mean()) < 1e-9 and n.min() > -200
    snap = {"picks": {"SPY": {"symbol": "SPYx"}}}
    assert len(s2.premiums(p, snap)["SPY"]) == 120


def test_the_venue_charges_kraken_before_the_asset_was_on_chain_and_the_quote_after():
    v = r10.era_venue(LADDER, s2.SWAP_FEE_SOL, CEX)
    v.at(day("2021-06-01"))
    assert not v.on_chain("SOL") and v.tradable("DOGE")
    assert v.cost("BTC", 100.0, 150.0) == pytest.approx(0.41)
    assert v.cost("PEPE", 100.0, 150.0) == pytest.approx(100 * (0.0080 + r10.CEX_HALF_SPREAD))
    assert v.setup(40.0, 1, 150.0) == (0.0, 0.0)
    v.at(day("2023-01-01"))                       # SOL on chain, BTC not yet (cbBTC 2024-11-07)
    assert v.on_chain("SOL") and not v.on_chain("BTC") and not v.tradable("DOGE")
    assert v.cost("SOL", 100.0, 150.0) == pytest.approx(100 * 0.5 / 1e4 + s2.SWAP_FEE_SOL * 150)
    assert v.cost("BTC", 100.0, 150.0) == pytest.approx(0.41)
    reserve, once = v.setup(40.0, 1, 150.0)
    assert reserve == pytest.approx((s1.SOL_FEE_RESERVE + 2 * s1.RENT_SOL) * 150) and once == 0.0
    v.at(day("2024-11-07"))
    assert v.cost("BTC", 100.0, 150.0) == pytest.approx(100 * 2.0 / 1e4 + s2.SWAP_FEE_SOL * 150)
    v.at(day("2025-06-29"))
    assert v.cost("SPY", 50.0, 150.0) == pytest.approx(50 * (0.0080 + r10.CEX_HALF_SPREAD))
    v.at(day("2025-06-30"))
    assert v.cost("SPY", 50.0, 150.0) == pytest.approx(50 * 6.0 / 1e4 + s2.SWAP_FEE_SOL * 150)
    today = r10.era_venue(LADDER, s2.SWAP_FEE_SOL, CEX, today=True)
    today.at(day("2020-08-01"))
    assert today.on_chain("BTC") and today.cost("BTC", 100.0, 150.0) == pytest.approx(100 * 2.0 / 1e4 + s2.SWAP_FEE_SOL * 150)


def test_the_way_in_and_the_way_back_are_paid():
    assert r10.way_in(40.0, 1.10, 0.004, True) == pytest.approx(40 * 1.10 * 0.996 - 1.0)
    assert r10.way_in(40.0, 1.10, 0.004, False) == pytest.approx(40 * 1.10 * 0.996)
    v = r10.era_venue(LADDER, s2.SWAP_FEE_SOL, CEX)
    v.at(day("2021-01-01"))
    eur = r10.way_back(110.0, {"BTC": 50.0}, v, 150.0, 1.10, 0.004)
    assert eur == pytest.approx((110 - 50 * 0.0041) * 0.996 / 1.10 - r10.SEPA_EUR)


def test_a_usd_wallet_in_cash_moves_in_eur_with_the_rate():
    fx = np.array([1.0, 1.1, 1.25])
    v = r10.era_venue(LADDER, s2.SWAP_FEE_SOL, CEX)
    days = np.array([day("2021-01-01"), day("2021-01-02"), day("2021-01-03")])
    eq = r10.in_eur({"equity": np.array([100.0, 100.0, 100.0]), "end_held": {}}, 100.0, fx, 0, 2, v, days, 150.0, 0.0)
    assert eq[0] == pytest.approx(100.0) and eq[1] == pytest.approx(100 / 1.1)
    assert eq[2] == pytest.approx(100 / 1.25 - r10.SEPA_EUR)


def test_the_token_draws_from_the_weekend_on_days_without_a_us_close():
    base = np.full(2000, 100.0)
    us = np.arange(2000) % 7 < 5
    dev = {"us": np.array([-10.0, 10.0]), "shut": np.array([-80.0, 80.0])}
    p = r10.token_price(base, us, dev, 10, 0)
    assert set(np.round(p[us], 6)) == {99.9, 100.1} and set(np.round(p[~us], 6)) == {99.2, 100.8}
    assert np.array_equal(r10.token_price(base, us, dev, 10, 0), p)
    assert np.array_equal(r10.token_price(base, us, None, 10, 0), base)


def test_the_deviations_are_cleaned_and_centred_on_the_us_days(tmp_path):
    p = tmp_path / "tok.csv"
    rows = [{"key": "SPY", "date": f"d{i}", "token_usd": 1, "close_date": "x", "close": 1, "us_day": i % 3 != 0,
             "dev_bps": (30.0 + (i % 5)) if i != 7 else -1094.0} for i in range(60)]
    s1.write_csv(p, rows)
    d = r10.deviations(p)["SPY"]
    assert d["dropped"] == 1 and abs(d["us"].mean()) < 1e-9 and d["n_us"] + d["n_shut"] == 59


class Recording(r10.EraVenue):
    def at(self, day_us: int) -> None:
        super().at(day_us)
        self.__dict__.setdefault("seen", []).append(int(day_us))


def test_every_wallet_tells_its_venue_the_day_and_reports_what_it_holds_at_the_end():
    P = make_panel()
    v = Recording("jupiter", 1.0, ladder=LADDER, cex=CEX, default_from=r10.EARLY)
    W = np.zeros((T, P.N))
    W[:, P.btc] = 1.0
    res = s1.simulate(P, W, v, 100.0, 400, 420)
    assert set(int(d) for d in P.days[400:421]) <= set(v.seen) and set(res["end_held"]) == {"BTC"}
    m = s2.market(P, {"SPY": make_etf(), "GLD": make_etf(seed=4)}, 1.0, {})
    keys, Ws, due, rw = s2.candidate("spy_hold", m, P)
    v.seen = []
    res = s2.simulate(s2.coin_prices("spy_hold", keys, m, P, 1.0), keys, Ws, due, rw, m.sol_eur, v, 100.0, 400, 420, 1,
                      days=P.days)
    assert v.seen[0] == P.days[400] and int(P.days[420]) in v.seen and set(res["end_held"]) == {"SPY"}
    assert "end_held" in s2.simulate(s2.coin_prices("spy_hold", keys, m, P, 1.0), keys, Ws, due, rw, m.sol_eur,
                                     s2.S2Venue("jupiter", 1.0, ladder=LADDER), 100.0, 400, 420, 1)


def test_l1_takes_a_swap_cost_by_day_and_the_late_targets():
    P = make_panel()
    W = L.rule(P)
    seen = []

    def cost(c, usd, sol, t):
        seen.append((c, t))
        return 0.0
    res = L.simulate(P, 400, 600, 100.0, W=W, swap_cost=cost)
    assert seen and all(400 <= t <= 600 for _, t in seen) and {c for c, _ in seen} <= {"BTC", "ETH"}
    late = L.simulate(P, 400, 600, 100.0, W=r10.late(W), swap_cost=cost)
    assert not np.array_equal(res["equity"], late["equity"])
    assert set(res["end_held"]) <= {"BTC", "ETH"}


def market() -> r10.Market:
    P = make_panel()
    etf = {"SPY": make_etf(), "GLD": make_etf(seed=4, mu=0.0002)}
    m = s2.market(P, etf, 1.0, {})
    fx = np.linspace(1.10, 1.20, T)
    ve = lambda today: r10.era_venue(LADDER, s2.SWAP_FEE_SOL, CEX, today)
    return r10.Market(P=P, m=m, fx=fx, v1=ve(False), v2=ve(False), v1_today=ve(True), v2_today=ve(True), rate=0.004,
                      devs={"SPY": {"us": np.array([-20.0, 20.0]), "shut": np.array([-60.0, 60.0])}})


def test_the_rules_run_on_time_and_late_in_eur():
    mk = market()
    memo: dict = {}
    for run in (lambda lt: r10.run_s1(mk, "tsmom1", 40.0, lt, 400, T - 1, memo=memo),
                lambda lt: r10.run_s2(mk, "trend_mix", 40.0, lt, 400, T - 1, memo=memo),
                lambda lt: r10.run_l1(mk, 40.0, lt, 400, T - 1, memo=memo)):
        a, b = run(False), run(True)
        assert len(a) == len(b) == T - 400 and np.isfinite(a).all() and np.isfinite(b).all()
        assert a[0] < 40.0 and not np.array_equal(a, b)                  # the way in, and the fill matters
    eq = r10.bench_pair(mk.P.px[:, [0, 1]], mk.m.sol_eur, mk.P.days, mk.v2, 40.0, mk.fx, mk.rate, 400, T - 1)
    assert eq[0] < 40.0 and np.isfinite(eq).all()


def test_the_fund_is_bought_free_and_sold_at_one_euro():
    eq = r10.bench_fund(np.array([np.nan, 100.0, 110.0]), 40.0, 1, 2)
    assert eq[0] == pytest.approx(40 * 0.9995) and eq[1] == pytest.approx(40 * 0.9995 * 1.1 * 0.9995 - 1.0)


def _row(crypto, late, on, bench):
    row = {"crypto": crypto}
    for cap in r10.CAPITALS:
        row[f"bench@{cap:g}"] = bench
        row[f"on_time@{cap:g}"] = on
        row[f"late@{cap:g}"] = late
    return row


def test_the_bar_is_late_at_both_sizes():
    good = {"cagr": 0.30, "max_dd": 0.15, "sharpe": 1.5, "dsr": 0.97}
    crypto_b = {"cagr": 0.10, "max_dd": 0.5, "sharpe": 0.8}
    assert r10.verdict(_row(True, good, good, crypto_b))["late"]["passes"]
    weak = {**good, "dsr": 0.6}
    v = r10.verdict(_row(True, weak, good, crypto_b))
    assert v["on_time"]["passes"] and not v["late"]["passes"] and "40 EUR: DSR >= 0.95" in v["late"]["why"]
    fund = {"cagr": 0.18, "max_dd": 0.23, "sharpe": 1.2}
    deep = {**good, "max_dd": 0.21}
    v = r10.verdict(_row(False, deep, good, fund))
    assert not v["late"]["passes"] and "100 EUR: DD < 20 %" in v["late"]["why"]
    slow = {**good, "cagr": 0.165}
    assert not r10.verdict(_row(False, slow, slow, fund))["late"]["passes"]
    assert r10.verdict(_row(False, {**good, "cagr": 0.175}, good, fund))["late"]["passes"]


def test_the_f2_genomes_are_every_held_back_key_once(tmp_path, monkeypatch):
    seed, server = tmp_path / "seed", tmp_path / "small"
    for d in (seed, server):
        d.mkdir()
    g = f2.hold_genome("BTC")
    h = f2.hold_genome("SPY")
    import json
    (seed / "ledger.jsonl").write_text(json.dumps({"key": "a", "name": "A", "genome": g}) + "\n")
    (seed / "holdout.jsonl").write_text(json.dumps({"key": "a"}) + "\n")
    (server / "ledger.jsonl").write_text(json.dumps({"key": "b", "name": "B", "genome": h}) + "\n")
    (server / "holdout.jsonl").write_text(json.dumps({"key": "a"}) + "\n" + json.dumps({"key": "b"}) + "\n")
    monkeypatch.setattr(f2, "seed_dir", lambda: seed)
    monkeypatch.setattr(f2, "small_dir", lambda: server)
    got = r10.f2_genomes()
    assert [x["key"] for x in got] == ["a", "b"]
    assert r10.is_crypto_genome(got[0]["genome"]) and not r10.is_crypto_genome(got[1]["genome"])


def test_the_dsr_pools_come_from_the_r5_registry_with_l1_counted():
    small = trial_pool("small")
    assert small["n_trials"] >= 61 + 8 + 1
    from lab.metrics import read_registry
    assert any(r["id"] == "small:l1" and r["family"] == "small" for r in read_registry())
    p = r10.dsr_pools()
    assert p["all"]["n_trials"] >= p["small"]["n_trials"] >= small["n_trials"]


def test_the_report_says_late_against_on_time_and_the_dsr_direction():
    m = {"cagr": 0.1, "max_dd": 0.1, "sharpe": 1.0, "end_eur": 44.0, "dsr": 0.2, "dsr_small": 0.5}
    row = {"name": "tsmom1", "study": "S1", "crypto": True, "benchmark": "BTC/ETH held",
           "is_sharpe": {"today_on_time": 2.0, "era_on_time": 1.8, "era_late": 1.4}}
    for cap in r10.CAPITALS:
        row.update({f"on_time@{cap:g}": m, f"late@{cap:g}": m, f"bench@{cap:g}": m})
    row["verdict"] = r10.verdict(row)
    pool = {"n_trials": 2767, "sr0_annual": 2.8}
    out = {"generated": "now", "val_to": "2026-06-30", "fx": {"min": 1.02, "max": 1.2}, "rate": 0.004, "cex": CEX,
           "pools": {"all": pool, "small": {"n_trials": 190, "sr0_annual": 1.4}}, "devs": {}, "cleaned": {},
           "rows": [row], "bench": [{"bench": "btc_eth", "capital": 40.0, **m}]}
    md = r10.markdown(out)
    assert "late DSR, pass at 0.95 or more (all / small)" in md and "higher is" in md
    assert "**For real money: nothing.**" in md and chr(0x2014) not in md


def test_the_kraken_fee_rerun_is_s1_on_the_validation_window_only(monkeypatch):
    mk = market()
    days = mk.P.days
    monkeypatch.setattr(r10, "VAL_FROM", str((days[400] // fc.DAY_US).astype("datetime64[D]")))
    monkeypatch.setattr(r10, "VAL_TO", str((days[-1] // fc.DAY_US).astype("datetime64[D]")))
    pools = {"all": {"n_trials": 100, "var": 1e-4}, "small": {"n_trials": 10, "var": 1e-4}}
    seen = []
    run = r10.run_rule
    monkeypatch.setattr(r10, "run_rule", lambda *a, **k: seen.append(a[4]) or run(*a, **k))
    rows = r10.evaluate(mk, pools, log=lambda *_: None, only=[r for r in r10.rules(mk) if r["study"] == "S1"],
                        val_only=True)
    assert [r["name"] for r in rows] == list(r10.S1_RULES) and set(seen) == {"val"}       # no in-sample number
    assert all("is_sharpe" not in r and "verdict" in r and "late@100" in r for r in rows)
    t = r10.kraken_fee_trials()
    assert len(t) == 8 == len({x["id"] for x in t}) and {x["family"] for x in t} == {"small"}
    out = {"generated": "now", "val_to": "2026-06-30", "taker": 0.008, "stable": 0.002, "source": "Kraken", "rate": 0.0021,
           "cex": CEX, "trials": 8, "pools": {"all": {"n_trials": 9, "sr0_annual": 1.0},
                                              "small": {"n_trials": 8, "sr0_annual": 1.0}}, "rows": rows}
    md = r10.kraken_fee_markdown(out)
    assert "spot taker 0.80 %" in md and "S1 tsmom1" in md and "higher is better" in md and chr(0x2014) not in md
