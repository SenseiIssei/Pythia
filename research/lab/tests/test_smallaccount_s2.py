"""S2, a fairly safe small wallet on Solana against the ETF token (lab.experiments.smallaccount_s2) and its two paper
books (lab.paper.smallaccount S2_BOOKS): the token list, the tracking measures, the venue, the candidates, the
wallet, the bar, the books. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_smallaccount_s2.py
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import smallaccount as s1
from lab.experiments import smallaccount_s2 as s2
from lab.paper import smallaccount as book

LADDER = {"SPY": [(5.0, 4.0), (50.0, 6.0), (100.0, 9.0)], "GOLD": [(5.0, 8.0), (100.0, 12.0)],
          "BTC": [(5.0, 1.0), (100.0, 2.0)], "SOL": [(5.0, 0.5), (100.0, 0.5)]}


def venue() -> s2.S2Venue:
    return s2.S2Venue("jupiter", 1.16, ladder=LADDER)


def tok(sym, name, tags, liq, mint="M" * 32):
    return {"symbol": sym, "name": name, "tags": ["verified", *tags], "liquidity": liq, "id": f"{sym}{mint}",
            "decimals": 8, "holderCount": 10}


# ---------------------------------------------------------------- the snapshot

def test_tokens_are_classified_by_issuer_and_kind():
    c = s2.classify
    assert c(tok("SPYx", "SP500 xStock", ["xstocks", "stocks", "rwa"], 1)) == {
        "family": "xstocks", "root": "SPY", "kind": "sp500", "underlying": "SPY"}
    assert c(tok("SPYon", "SPDR S&P 500 ETF (Ondo Tokenized)", ["ondo", "stocks"], 1))["kind"] == "sp500"
    assert c(tok("QQQx", "Nasdaq xStock", ["xstocks"], 1))["kind"] == "ndx"
    assert c(tok("GLDx", "Gold xStock", ["xstocks"], 1))["kind"] == "gold"
    g = c(tok("XAUt0", "Tether Gold", ["rwa", "commodities"], 1))
    assert g["kind"] == "gold" and g["family"] == "Tether Gold" and g["underlying"] == "GLD"
    assert c(tok("NVDAx", "NVIDIA xStock", ["xstocks", "equities"], 1))["kind"] == "share"
    assert c(tok("URA", "Global X Uranium ETF - Backpack Securities", ["backpack"], 1))["kind"] == "etf"
    assert c(tok("OPENAI", "OpenAI PreStocks", ["prestocks", "stocks"], 1))["kind"] == "pre_ipo"
    assert c(tok("GOLD", "GOLD", ["commodities", "rwa"], 1))["kind"] == "other", "an unknown issuer is not gold"


def test_the_list_keeps_liquid_assets_and_every_etf_or_gold_token():
    rows = s2.token_rows([tok("SPYx", "SP500 xStock", ["xstocks"], 3e6), tok("VOOx", "Vanguard S&P 500 xStock",
                          ["xstocks"], 0), tok("NVDAx", "NVIDIA xStock", ["xstocks"], 2e6),
                          tok("TINY", "Tiny xStock", ["xstocks"], 10), tok("BONK", "Bonk", ["meme"], 9e6)])
    assert [r["symbol"] for r in rows] == ["SPYx", "NVDAx", "VOOx"], "liquidity first; no RWA tag, no row"
    assert rows[0]["mint"].startswith("SPYx") and rows[0]["decimals"] == 8
    assert [r["symbol"] for r in s2.shortlist(rows)] == ["SPYx", "VOOx", "NVDAx"]


def test_the_pick_is_the_cheapest_liquid_token_of_its_kind_at_50_usd():
    rows = [{"symbol": "SPYx", "kind": "sp500", "liquidity_usd": 3e6}, {"symbol": "SPYon", "kind": "sp500",
             "liquidity_usd": 9e3}, {"symbol": "IVVx", "kind": "sp500", "liquidity_usd": 2e5}]
    quotes = [{"symbol": "SPYx", "usd": "50.0", "half_rt_bps": "6"}, {"symbol": "SPYon", "usd": "50.0",
              "half_rt_bps": "1"}, {"symbol": "IVVx", "usd": "50.0", "half_rt_bps": "9"},
              {"symbol": "IVVx", "usd": "5.0", "half_rt_bps": "0.1"}]
    assert s2.pick(rows, quotes, "sp500")["symbol"] == "SPYx", "SPYon is too thin"
    assert s2.pick(rows, quotes, "gold") is None


def test_the_us_close_hour_follows_new_york_summer_and_winter_time():
    assert s2.ny_close_utc("2026-07-01").hour == 20 and s2.ny_close_utc("2026-12-01").hour == 21
    s = int(datetime(2026, 7, 1, 19, tzinfo=timezone.utc).timestamp())
    candles = [[s - 3600, 1, 1, 1, 99.0, 0], [s, 1, 1, 1, 100.0, 0], [s + 3600, 1, 1, 1, 101.0, 0]]
    assert s2.at_close(candles, ["2026-07-01", "2026-07-02"]) == {"2026-07-01": 100.0}, "the candle ending at 20:00"


def test_tracking_measures_premium_error_and_drift():
    days = [str(np.datetime64("2026-01-02") + np.timedelta64(i, "D")) for i in range(300)]
    rng = np.random.default_rng(1)
    under = {d: 500 * math.exp(0.001 * i + 0.01 * rng.standard_normal()) for i, d in enumerate(days)}
    same = s2.tracking_stats({d: p * 1.002 for d, p in under.items()}, under)
    assert same["premium_mean_bps"] == pytest.approx(20, abs=1e-6) and same["te_yr_pct"] < 1e-9
    assert abs(same["drift_yr_pct"]) < 1e-6 and same["corr"] == pytest.approx(1.0)
    t = {d: p * math.exp(-0.01 * i / 365.25) for i, (d, p) in enumerate(under.items())}
    assert s2.tracking_stats(t, under)["drift_yr_pct"] == pytest.approx(-1.0, abs=0.05), "1 % a year behind"
    assert s2.tracking_stats({days[0]: 1.0}, under) == {"days": 1}


def test_dividend_yield_from_adjusted_against_unadjusted_closes():
    rows = [(f"{2021 + y}-01-04", 100.0, 100.0 * math.exp(-0.015 * (4 - y))) for y in range(5)]
    assert s2.dividend_yield(rows) == pytest.approx(0.015, rel=0.01)
    assert s2.dividend_yield(rows[:1]) == 0.0


def test_weekend_moves_are_friday_close_to_sunday_same_hour():
    fri = "2026-07-03"
    s = int(s2.ny_close_utc(fri).timestamp()) - 3600
    candles = [[s, 1, 1, 1, 100.0, 0], [s + 2 * 86_400, 1, 1, 1, 101.0, 0]]
    assert s2.weekend_moves(candles, [fri, "2026-07-06"]) == pytest.approx([0.01])


def test_paced_get_waits_on_429_and_gives_up_on_a_bad_request():
    answers = iter([(429, b""), (200, b'{"ok": 1}'), (404, b"no")])
    slept = []
    g = s2.Paced(sleep=slept.append, fetch=lambda url: next(answers))
    assert g.get("https://example.org/a") == {"ok": 1} and slept
    assert g.get("https://example.org/b") is None


def test_issuer_words_keep_sentences_about_who_may_hold():
    page = "<p>Buy now. xStocks are not available in the U.S. or to U.S. persons. Nice.</p>"
    out = s2.issuer_words(lambda u: page if "xstocks" in u else None)
    assert out["xStocks (Backed Assets)"] == ["xStocks are not available in the U.S. or to U.S. persons."]
    assert out["Paxos (PAXG)"] == [], "no answer: nothing claimed"


# ---------------------------------------------------------------- the venue

def test_the_venue_adds_the_sender_tip_and_starts_from_sol():
    v = venue()
    assert s2.SWAP_FEE_SOL == pytest.approx(0.000205)
    assert v.cost("SPY", 10.0, 150.0) == pytest.approx(10 * v.half_rt_bps("SPY", 11.6) / 1e4 + 0.000205 * 150)
    idle, once = v.setup(40.0, 2, 150.0)
    assert idle == pytest.approx((0.01 + 0.00204 * 3) * 150)
    assert once == pytest.approx(v.cost("SOL", 40.0 - idle, 150.0)) and once < 0.1, "one SOL swap, no Kraken fee"


def test_the_venue_reads_the_ladder_under_the_rules_keys(tmp_path):
    q = tmp_path / "q.csv"
    s1.write_csv(q, [{"symbol": "SPYx", "usd": 5.0, "half_rt_bps": 4.0, "impact_pct": 0, "route": "x"},
                     {"symbol": "XAUt0", "usd": 5.0, "half_rt_bps": 9.0, "impact_pct": 0, "route": "x"},
                     {"symbol": "BTC", "usd": 5.0, "half_rt_bps": 1.0, "impact_pct": 0, "route": "x"}])
    k = tmp_path / "k.csv"
    s1.write_csv(k, [{"coin": "EURUSD", "pair": "EUR/USD", "ordermin": 1, "costmin": 1, "lot_decimals": 5,
                      "bid": 1.15, "ask": 1.17}])
    v = s2.venue(q, {"picks": {"SPY": {"symbol": "SPYx"}, "GOLD": {"symbol": "XAUt0"}}}, k)
    assert set(v.ladder) == {"SPY", "GOLD", "BTC"} and v.eurusd == pytest.approx(1.16)


def test_drift_takes_withholding_off_the_dividends_but_not_off_gold():
    row = {"drift_yr_pct": "-0.2", "div_yield_pct": "1.3"}
    assert s2.drift(row, "SPY") == pytest.approx(-0.002 - 0.3 * 0.013)
    assert s2.drift(row, "GOLD") == pytest.approx(-0.002) and s2.drift(None, "SPY") == 0.0


# ---------------------------------------------------------------- the market and the candidates

T = 900
NAMES = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def make_panel() -> fc.Panel:
    N = len(NAMES)
    rng = np.random.default_rng(7)
    px = 100 * np.cumprod(1 + rng.normal(0.001, 0.03, (T, N)), axis=0)
    r = np.full((T, N), np.nan)
    r[1:] = px[1:] / px[:-1] - 1
    idx = np.arange(T)[:, None]
    alive = np.ones((T, N), dtype=bool)
    days = s1.ANCHOR_US + np.arange(T, dtype=np.int64) * fc.DAY_US
    return fc.Panel(days=days, names=NAMES, bases=[fc.base_of(n) for n in NAMES], close=px, px=px, high=px, low=px,
                    ret=r, alive=alive, traded=alive.copy(), age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan), sigma=np.full((T, N), 0.03),
                    eligible=alive & (idx >= 60), perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=np.arange(T) % 150 < 100, btc=0)


def make_etf(start="2019-01-01", n=1400, seed=3, mu=0.0004) -> tuple[np.ndarray, np.ndarray]:
    d = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(int(n * 1.45), "D"))
    d = d[(d.astype("datetime64[D]").view("int64") + 3) % 7 < 5][:n]     # weekdays only (1970-01-01 a Thursday)
    rng = np.random.default_rng(seed)
    return d, 300 * np.cumprod(1 + rng.normal(mu, 0.01, n))


def market(P=None) -> s2.Market:
    P = P or make_panel()
    return s2.market(P, {"SPY": make_etf(), "GLD": make_etf(seed=4, mu=0.0002)}, 1.16, {"SPY": -0.004})


def test_the_etf_is_carried_over_weekends_and_drifts_as_measured():
    P = make_panel()
    etf = {"SPY": make_etf(), "GLD": make_etf(seed=4)}
    flat = s2.market(P, etf, 1.0, {})
    m = s2.market(P, etf, 1.0, {"SPY": -0.004})
    sat = [t for t in range(1, T) if (P.days[t] // fc.DAY_US + 3) % 7 == 5][0]      # 1970-01-01 was a Thursday
    assert flat.px["SPY"][sat] == flat.px["SPY"][sat - 1] and not flat.us_day[sat]
    yrs = (P.days[-1] - P.days[0]) / (365.25 * fc.DAY_US)
    assert m.px["SPY"][-1] / flat.px["SPY"][-1] == pytest.approx(math.exp(-0.004 * yrs))
    assert np.array_equal(m.btc_up, P.btc_on) and (m.sol_eur > 0).all()


def test_the_trend_uses_spy_trading_days_only():
    d, c = make_etf()
    sma = s2.sma_on_trading_days(d, c, 200)
    assert np.isnan(sma[198]) and sma[199] == pytest.approx(c[:200].mean())


@pytest.mark.parametrize("key", list(s2.CANDIDATES))
def test_every_candidate_is_long_only_and_never_above_the_wallet(key):
    P = make_panel()
    keys, W, due, rw = s2.candidate(key, market(P), P)
    assert W.shape == (T, len(keys)) and np.isfinite(W).all()
    assert (W >= -1e-12).all() and (W.sum(1) <= 1 + 1e-9).all() and due.any()


def test_the_rules_say_what_they_were_registered_to_say():
    P = make_panel()
    m = market(P)
    _, W, due, _ = s2.candidate("spy_trend", m, P)
    assert set(np.unique(W)) <= {0.0, 1.0} and np.array_equal(W[:, 0] > 0, m.spy_up) and due.all()
    keys, W, due, rw = s2.candidate("mix_6040", m, P)
    assert keys == ["SPY", "BTC"] and np.allclose(W, [0.6, 0.4]) and np.array_equal(due, rw)
    assert 25 <= due.sum() <= 31, "monthly"
    _, W, _, rw = s2.candidate("trend_mix", m, P)
    assert np.array_equal(W[:, 1] > 0, m.btc_up) and set(np.unique(W[:, 0])) <= {0.0, 0.6} and rw.sum() == due.sum()
    keys, W, due, _ = s2.candidate("dual_mom", m, P)
    assert keys == ["SPY", "BTC", "GOLD"] and set(np.unique(W.sum(1))) <= {0.0, 1.0}
    assert not W[:365].any(), "a year of history first"
    assert 120 <= due.sum() <= 130, "weekly"
    keys, W, _, _ = s2.candidate("tsmom1", m, P)
    assert set(keys) <= {"BTC", "ETH", "SOL"}


def test_vol_target_holds_the_risk_budget():
    P = make_panel()
    m = market(P)
    w = s2.vol_weights(m, T - 1)
    idx = np.flatnonzero(m.us_day)[-(s2.VOL_WIN + 1):]
    R = np.column_stack([np.diff(np.log(m.px[k][idx])) for k in s2.KEYS])
    x = np.array([w[k] for k in s2.KEYS])
    assert float(np.sqrt(x @ (np.cov(R, rowvar=False) * 252) @ x)) == pytest.approx(0.10, rel=1e-6)
    assert w["BTC"] < w["SPY"], "the wildest asset gets the least"
    assert s2.vol_weights(m, 10) == {k: 0.0 for k in s2.KEYS}, "too little history: USDC"


# ---------------------------------------------------------------- the wallet and the measures

def run_one(key, cap=40.0, t0=400, t1=T - 1):
    P = make_panel()
    m = market(P)
    keys, W, due, rw = s2.candidate(key, m, P)
    px = s2.coin_prices(key, keys, m, P, 1.16)
    return s2.simulate(px, keys, W, due, rw, m.sol_eur, venue(), cap, t0, t1, s2.SLOTS[key]), m


def test_hold_buys_once_and_the_costs_add_up():
    r, m = run_one("spy_hold")
    assert r["orders"] == 1 and r["costs"] > 0
    meas = s1.measure(r, 40.0)
    assert meas["end_eur"] == pytest.approx(r["equity"][-1])


def test_the_6040_goes_back_to_target_monthly_but_not_under_the_minimum():
    r, _ = run_one("mix_6040", cap=400.0)
    small, _ = run_one("mix_6040", cap=20.0)
    assert r["orders"] > small["orders"] >= 2, "a 20 EUR wallet cannot send most of the monthly re-weights"
    assert small["skipped"] > 0


def test_months_and_the_share_that_beat_the_etf():
    days = s1.ANCHOR_US + np.arange(62, dtype=np.int64) * fc.DAY_US      # January and February 2020, 2 days of March
    eq = np.linspace(100, 130, 62)
    lab, mr = s2.months(days, eq)
    assert len(lab) == 3 and np.prod(1 + mr) == pytest.approx(1.3)
    res = {"equity": eq, "costs": 1.0, "orders": 2, "skipped": 0, "dust": 0}
    m = s2.measure(res, 100.0, days, np.full(62, 100.0))
    assert m["months_beat"] == 1.0 and m["worst_month"] > 0


def test_the_bootstrap_and_the_dsr():
    rng = np.random.default_rng(0)
    y = rng.normal(0.0005, 0.01, 1000)
    b = s2.bootstrap(y.copy(), y, draws=200)
    assert b["diff_p05"] == pytest.approx(0.0, abs=1e-12) and b["diff_above_0"] == 0.0
    good = s2.bootstrap(y + 0.002, y, draws=200)
    assert good["diff_p05"] > 0 and good["diff_above_0"] == 1.0
    diffs = {"edge": rng.normal(0.003, 0.01, 1000), "noise": rng.normal(0.0, 0.01, 1000),
             "worse": rng.normal(-0.001, 0.01, 1000)}
    reg = {"n_trials": s2.TRIALS, "var": s2.diff_var(diffs)}
    p = s2.dsr(diffs, reg)                                 # the DSR: higher is better, pass at 0.95
    assert p["edge"] > s2.DSR_PASS > p["noise"] and p["worse"] < p["noise"]
    pools = s2.dsr_pools(diffs)
    assert pools["all"]["n_trials"] > pools["small"]["n_trials"] >= 70 and pools["registered"] == reg
    assert all(0.0 <= x <= 1.0 for x in s2.dsr(diffs).values())   # the registry's pool of all by default
    assert s2.dsr({"flat": np.zeros(50)}, reg) == {"flat": 0.0}


def row(cagr, dd, sharpe=1.0, is_dd=0.1, is_sharpe=1.0, diff_p05=-0.1, dsr=0.5):
    return {"oos": {"cagr": cagr, "max_dd": dd, "sharpe": sharpe}, "is": {"max_dd": is_dd, "sharpe": is_sharpe},
            "boot": {"diff_p05": diff_p05}, "dsr": dsr}


def test_the_bar_and_the_paper_picks_as_registered():
    rows = {"spy_hold": row(0.15, 0.19), "btc_hold": row(0.40, 0.50, is_sharpe=3.0),
            "spy_trend": row(0.145, 0.12, is_sharpe=0.9), "dual_mom": row(0.30, 0.35, is_sharpe=2.0, is_dd=0.4),
            "mix_6040": row(0.20, 0.19, is_sharpe=1.2, is_dd=0.25), "trend_mix": row(0.17, 0.10, is_sharpe=0.8,
                                                                                  diff_p05=0.01, dsr=0.99),
            "tsmom1": row(0.3, 0.1, is_sharpe=5.0), "vol_target": row(0.08, 0.05, is_sharpe=0.7)}
    v = s2.verdict(rows)
    assert v["spy_trend"]["passes"] and not v["spy_trend"]["convincing"], "within a point of the ETF, safe"
    assert not v["dual_mom"]["passes"] and not v["vol_target"]["passes"] and v["mix_6040"]["passes"]
    assert not s2.verdict({**rows, "trend_mix": row(0.17, 0.10, diff_p05=0.01, dsr=0.94)})["trend_mix"]["convincing"]
    assert v["trend_mix"]["convincing"] and not v["btc_hold"]["passes"] and not v["spy_hold"]["passes"]
    assert s2.paper_picks(rows) == ["spy_trend", "trend_mix"], "safe in sample first; never tsmom1 or a reference"


def test_the_paper_books_are_the_registered_picks_of_the_result():
    md = (s2.RESULTS / "smallaccount_s2.md").read_text(encoding="utf-8")
    sec = md.split("## 6. Paper books")[1]
    assert sec.split("\n\n")[1].strip() == ", ".join(f"`{k}`" for k in book.S2_PICKS)
    assert set(book.S2_BOOKS) == {f"small40_{k}" for k in book.S2_PICKS}
    assert all(b["capital"] == 40.0 and b["study"] == "S2" for b in book.S2_BOOKS.values())


def test_nothing_goes_live():
    from lab.onchain import mints as M
    snap = json.loads(s2.SNAPSHOT_JSON.read_text(encoding="utf-8"))
    tokens = {p["mint"] for p in snap["picks"].values() if p}
    assert tokens and not tokens & {m.mint for m in M.COINS.values()}, "the live trader's allowlist is unchanged"


def test_no_em_dash_in_the_new_files():
    here = Path(__file__).resolve().parents[1]
    for p in (here / "lab/experiments/smallaccount_s2.py", here / "lab/paper/smallaccount.py",
              here / "results/smallaccount_s2.md", here / "results/smallaccount_s2_prereg.md", Path(__file__)):
        assert chr(0x2014) not in p.read_text(encoding="utf-8"), p


# ---------------------------------------------------------------- the paper books

def ms(y, m, d, h=5) -> int:
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_an_s2_book_starts_from_sol_and_goes_back_to_target_on_reweigh_days():
    name = next(iter(book.S2_BOOKS))
    v = venue()
    st = book.new_state(name, v, 150.0, ms(2026, 10, 24))
    assert st["capital_eur"] == 40.0 and st["setup_eur"] < 0.1 and "S2 small account" in st["variant"]
    prices = {"SPY": 650.0, "BTC": 60_000.0, "GOLD": 3_300.0, "SOL": 150.0}
    st, row, fills = book.step(name, st, {"SPY": 0.6, "BTC": 0.4, "GOLD": 0.0}, prices, v, 150.0,
                               ms(2026, 10, 24), "2026-10-23", True)
    assert {f["coin"] for f in fills} == {"SPY", "BTC"} and row["equity"] == pytest.approx(row["equity_eur"] / 40 * 1e4)
    moved = {**prices, "BTC": 90_000.0}
    _, _, same = book.step(name, st, {"SPY": 0.6, "BTC": 0.4, "GOLD": 0.0}, moved, v, 150.0, ms(2026, 10, 25),
                           "2026-10-24", True)
    assert same == [], "an unchanged target does not trade"
    _, _, back = book.step(name, st, {"SPY": 0.6, "BTC": 0.4, "GOLD": 0.0}, moved, v, 150.0, ms(2026, 11, 1),
                           "2026-10-31", True, reweigh=True)
    assert {f["side"] for f in back} == {"sell", "buy"}, "BTC sold back to 40 %, SPY bought up"


def test_the_s2_plan_is_the_candidates_row():
    P = make_panel()
    m = market(P)
    for name, b in book.S2_BOOKS.items():
        tgt, due, rw = book.s2_plan(P, name, 700, m)
        keys, W, d, r = s2.candidate(b["key"], m, P)
        assert tgt == {k: float(W[700, j]) for j, k in enumerate(keys)} and due == bool(d[700]) and rw == bool(r[700])


def test_live_prices_name_the_picked_tokens():
    class Fake:
        def prices(self, mints):
            return {m: 2.32 for m in mints}
    got = book.prices_eur({"SPY", "BTC"}, 1.16, client=Fake(), extra={"SPY": "SPYMINT"})
    assert got == {"SPY": 2.0, "BTC": 2.0, "SOL": 2.0}
    assert "GOLD" not in book.prices_eur({"GOLD"}, 1.16, client=Fake()), "no mint, no price"


def test_stale_etf_closes_only_mark():
    d = np.array(["2026-10-20", "2026-10-21"], dtype="datetime64[D]")
    etf = {"SPY": (d, np.ones(2)), "GLD": (d, np.ones(2))}
    assert book.etf_fresh(etf, "2026-10-24") and not book.etf_fresh(etf, "2026-10-28")
    assert not book.etf_fresh(etf, "2026-10-19"), "a close after the decision is not known yet"


def test_the_report_shows_both_studies(tmp_path, monkeypatch):
    from lab import report
    monkeypatch.setattr(report, "REPORTS", tmp_path)
    books = {}
    for name, v in [(next(iter(book.BOOKS)), s1.Venue("jupiter", 1.16, ladder=LADDER)),
                    (next(iter(book.S2_BOOKS)), venue())]:
        books[name] = book.new_state(name, v, 150.0, ms(2026, 10, 24))
    data = book.write_report(books, ms(2026, 10, 24))
    md = (tmp_path / "smallaccount" / "latest.md").read_text(encoding="utf-8")
    assert "| S2 | 40 EUR |" in md and "| S1 | 50 EUR |" in md and "from SOL" in md
    assert len(data["items"]) == 2 and chr(0x2014) not in md


def test_an_ounce_of_gold_is_measured_on_the_gld_scale():
    under = {f"2026-07-{d:02d}": 300.0 + d for d in range(1, 29)}
    token = {d: p * 10.9 * (1.001 if i % 2 else 0.999) for i, (d, p) in enumerate(under.items())}
    st = s2.tracking_stats(s2.per_unit(token, under), under)
    assert abs(st["premium_mean_bps"]) < 1 and st["premium_abs_p95_bps"] == pytest.approx(10, abs=0.5)


def test_a_reweight_under_the_minimum_waits_for_the_next_month():
    P = make_panel()
    m = market(P)
    keys, W, due, rw = s2.candidate("trend_mix", m, P)
    px = s2.coin_prices("trend_mix", keys, m, P, 1.16)
    r = s2.simulate(px, keys, W, due, rw, m.sol_eur, venue(), 40.0, 400, T - 1, 2)
    flips = int((np.abs(np.diff(W[400:], axis=0)) > 0).any(1).sum())
    assert r["skipped"] <= 2 * (flips + rw[400:].sum()), "not retried every day"
