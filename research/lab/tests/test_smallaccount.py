"""S1, small accounts (lab.experiments.smallaccount) and its two paper books (lab.paper.smallaccount):
the venues' costs and minimums, the wallet, the pre-registered picks. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_smallaccount.py
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
from lab.paper import smallaccount as book

KR = {"BTC": {"pair": "XBT/EUR", "ordermin": 0.00006, "costmin": 0.45, "lot_decimals": 8, "bid": 72000.0, "ask": 72001.0},
      "ETH": {"pair": "ETH/EUR", "ordermin": 0.002, "costmin": 0.45, "lot_decimals": 8, "bid": 2000.0, "ask": 2000.4},
      "PEPE": {"pair": "PEPE/EUR", "ordermin": 1_100_000, "costmin": 0.45, "lot_decimals": 0, "bid": 4e-6, "ask": 4.1e-6}}
LADDER = {"BTC": [(5.0, 1.0), (50.0, 2.0), (500.0, 8.0)], "ETH": [(5.0, 1.0), (500.0, 1.0)],
          "SOL": [(5.0, 0.5), (500.0, 0.5)]}


def kraken(maker=False) -> s1.Venue:
    return s1.Venue("kraken", 1.12, kraken=KR, maker=maker)


def jupiter() -> s1.Venue:
    return s1.Venue("jupiter", 1.12, ladder=LADDER)


# ---------------------------------------------------------------- venues

def test_kraken_minimum_fee_spread_and_lot():
    k = kraken()
    assert k.min_eur("BTC") == pytest.approx(0.00006 * 72000.5)          # ordermin x mid beats costmin
    assert k.min_eur("PEPE") == pytest.approx(max(1_100_000 * 4.05e-6, 0.45))
    assert k.cost("BTC", 100.0, 0.0) == pytest.approx(100 * (0.0040 + 1.0 / 144001.0))
    assert kraken(maker=True).cost("BTC", 100.0, 0.0) == pytest.approx(0.25)
    assert k.lot("BTC", 0.123456789) == pytest.approx(0.12345678)
    assert k.lot("PEPE", 1_234_567.9) == 1_234_567
    assert not k.tradable("DOGE") and k.tradable("ETH")
    assert k.setup(50.0, 3, 90.0) == (0.0, 0.0), "Kraken: nothing idle, nothing paid up front"


def test_jupiter_route_cost_network_fee_minimum_and_setup():
    j = jupiter()
    assert j.half_rt_bps("BTC", 2.0) == 1.0, "flat below the ladder"
    assert j.half_rt_bps("BTC", math.sqrt(5 * 50)) == pytest.approx(1.5), "log interpolation"
    assert j.half_rt_bps("BTC", 2000.0) == pytest.approx(8.0 * 2), "square root above it"
    sol_eur = 90.0
    eur = 10.0
    assert j.cost("BTC", eur, sol_eur) == pytest.approx(eur * j.half_rt_bps("BTC", eur * 1.12) / 1e4
                                                         + s1.SWAP_FEE_SOL * sol_eur)
    assert j.min_eur("BTC") == pytest.approx(5.0 / 1.12)
    assert not j.tradable("DOGE")
    idle, once = j.setup(50.0, 1, sol_eur)
    assert idle == pytest.approx((0.01 + 0.00204 * 2) * sol_eur)
    assert once == pytest.approx(50 * 0.004 + 1.0 / 1.12)
    # A swap of 5 USD pays the network fee on top: about 20 bps at a SOL of 100 USD.
    assert j.cost("ETH", 5 / 1.12, 100 / 1.12) / (5 / 1.12) * 1e4 == pytest.approx(1.0 + 0.000105 * 100 / 5 * 1e4)


def test_ideal_is_a_flat_cost_without_minimum():
    v = s1.Venue("ideal", 1.12, ideal=0.0041)
    assert v.tradable("ANY") and v.min_eur("ANY") == 0 and v.cost("ANY", 100, 0) == pytest.approx(0.41)


def test_kraken_rows_from_the_api_answers():
    pairs = {"XXBTZEUR": {"wsname": "XBT/EUR", "altname": "XBTEUR", "ordermin": "0.00006", "costmin": "0.45",
                          "lot_decimals": 8, "status": "online"},
             "XDGEUR": {"wsname": "XDG/EUR", "altname": "XDGEUR", "ordermin": "50", "costmin": "0.45",
                        "lot_decimals": 8},
             "ZEURZUSD": {"wsname": "EUR/USD", "altname": "EURUSD", "ordermin": "4", "costmin": "0.5", "lot_decimals": 8},
             "SOLUSD": {"wsname": "SOL/USD", "altname": "SOLUSD", "ordermin": "0.05"},
             "OLDEUR": {"wsname": "OLD/EUR", "status": "delisted"}}
    tick = {"XXBTZEUR": {"a": ["72001", "1"], "b": ["72000", "1"]}, "XDGEUR": {"a": ["0.07", "1"], "b": ["0.069", "1"]},
            "ZEURZUSD": {"a": ["1.1195", "1"], "b": ["1.1194", "1"]}, "SOLUSD": {"a": ["1", "1"], "b": ["1", "1"]},
            "OLDEUR": {"a": ["1", "1"], "b": ["1", "1"]}}
    rows = {r["coin"]: r for r in s1.kraken_rows(pairs, tick)}
    assert set(rows) == {"BTC", "DOGE", "EURUSD"}, "EUR pairs and EUR/USD, online only"
    assert rows["BTC"]["ordermin"] == 0.00006 and rows["DOGE"]["pair"] == "XDG/EUR"


def test_jupiter_rows_from_quotes():
    from lab.onchain import mints as M

    class Q:
        def __init__(self, i, o, a, out):
            self.in_mint, self.out_mint, self.in_amount, self.out_amount = i, o, a, out
            self.price_impact_pct, self.labels = 0.001, ["Pool"]

    class Client:
        def quote(self, i, o, amount):
            return Q(i, o, amount, amount * 2 if i == M.USDC.mint else int(amount / 2 * 0.998))

    rows = s1.jupiter_rows(Client(), {"BTC": M.COINS["BTC"]}, M.USDC, rungs=(5.0, 50.0))
    assert [r["usd"] for r in rows] == [5.0, 50.0]
    assert rows[0]["half_rt_bps"] == pytest.approx(10.0, abs=0.01), "0.2 % round trip, halved"


def test_the_recorded_snapshot_loads():
    vs = s1.venues()
    assert 1.0 < vs["kraken"].eurusd < 1.3
    for c in ("BTC", "ETH", "SOL"):
        assert vs["kraken"].tradable(c) and vs["jupiter"].tradable(c)
        assert 2.0 < vs["kraken"].min_eur(c) < 15.0, "Kraken's minimum is a few EUR"
    assert not vs["jupiter"].tradable("DOGE"), "no mint, no Jupiter"


# ---------------------------------------------------------------- the wallet

def test_ffill_and_cadence():
    W = np.array([[np.nan, 0.5], [0.3, np.nan], [np.nan, 0.0], [np.nan, np.nan]])
    assert s1.ffill(W).tolist() == [[0.0, 0.5], [0.3, 0.5], [0.3, 0.0], [0.3, 0.0]]
    days = s1.ANCHOR_US + np.arange(21) * fc.DAY_US
    assert sum(s1.rebalance_day(d, 7) for d in days) == 3 and all(s1.rebalance_day(d, 1) for d in days)


def test_rebalance_minimums_dust_and_retry():
    k = kraken()
    p = {"BTC": 72000.5, "ETH": 2000.2}
    w = s1.Wallet(cash=50.0)
    # 5 % of 50 EUR is 2.50 EUR, under BTC's 4.32 EUR: not sent, tried again later.
    s1.rebalance(w, {"BTC": 0.05, "ETH": 0.5}, p, k, 0.0)
    assert "BTC" not in w.units and w.skipped == 1 and "BTC" not in w.last
    assert w.units["ETH"] * p["ETH"] == pytest.approx(25.0 - k.cost("ETH", 25.0, 0.0), rel=1e-6)
    assert w.costs == pytest.approx(k.cost("ETH", 25.0, 0.0), rel=1e-3)
    # Trimming ETH from 50 % to 45 % is a 2.50 EUR order: under the minimum, left as it is.
    s1.rebalance(w, {"BTC": 0.05, "ETH": 0.45}, p, k, 0.0)
    assert w.skipped == 3 and w.orders == 1
    # Down to 5 %: the rest would be under the minimum, so it all goes.
    s1.rebalance(w, {"BTC": 0.05, "ETH": 0.05}, p, k, 0.0)
    assert "ETH" not in w.units and w.orders == 2
    # A position under the minimum cannot be sold: dust, counted once, kept.
    w.units["ETH"] = 0.001
    s1.rebalance(w, {"ETH": 0.0}, p, k, 0.0)
    s1.rebalance(w, {"ETH": 0.0}, p, k, 0.0)
    assert w.units["ETH"] == 0.001 and w.dust == 1
    # A coin the venue does not list is cash.
    w2 = s1.Wallet(cash=100.0)
    s1.rebalance(w2, {"DOGE": 0.5}, {"DOGE": 0.07}, k, 0.0)
    assert w2.units == {} and w2.cash == 100.0 and w2.last == {"DOGE": 0.0}


def test_buys_are_scaled_to_the_cash():
    w = s1.Wallet(cash=100.0)
    s1.rebalance(w, {"BTC": 0.8, "ETH": 0.8}, {"BTC": 72000.5, "ETH": 2000.2}, kraken(), 0.0)
    assert w.cash >= -1e-9 and w.orders == 2
    assert w.value({"BTC": 72000.5, "ETH": 2000.2}) == pytest.approx(100.0 - w.costs, rel=1e-6)


T = 700
NAMES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "LUNAUSDT~0"]


def make_panel() -> fc.Panel:
    N = len(NAMES)
    rng = np.random.default_rng(5)
    ret = rng.normal(0.002, 0.035, (T, N))
    idx = np.arange(T)[:, None]
    alive = np.ones((T, N), dtype=bool)
    alive[500:, 4] = False
    px = 100 * np.cumprod(1 + ret, axis=0)
    px[~alive] = np.nan
    r = np.full((T, N), np.nan)
    r[1:] = np.where(alive[1:] & alive[:-1], px[1:] / px[:-1] - 1, np.nan)
    days = s1.ANCHOR_US + np.arange(T, dtype=np.int64) * fc.DAY_US
    return fc.Panel(days=days, names=list(NAMES), bases=[fc.base_of(n) for n in NAMES], close=px, px=px, high=px,
                    low=px, ret=r, alive=alive, traded=alive.copy(), age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan), sigma=np.full((T, N), 0.03),
                    eligible=alive & (idx >= 60), perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=np.arange(T) % 120 < 80, btc=0)


@pytest.mark.parametrize("key", ["breakout_top10", "tsmom_top20", "btc_gated"])
def test_the_ideal_wallet_is_the_sweeps_simulator(key):
    P = make_panel()
    W = s1.candidate(P, key, 3 if key != "btc_gated" else None)
    g, tv, _, _ = fc.simulate(P, W, start=60)
    net = g - s1.IDEAL_COST * np.r_[0, tv[:-1]]
    t0, t1 = 60, 650
    res = s1.simulate(P, W, s1.Venue("ideal", 1.0, ideal=s1.IDEAL_COST), 10_000.0, t0, t1, 1, 3)
    mine = res["equity"][1:] / res["equity"][:-1] - 1
    # Both start in cash at t0; the sweep books a close's costs on the next day, the wallet at once.
    assert res["equity"][-1] / 10_000 == pytest.approx(np.prod(1 + net[t0 + 1:t1 + 1]), rel=0.01)
    assert np.corrcoef(mine, net[t0 + 1:t1 + 1])[0, 1] > 0.99


def test_small_wallets_miss_orders_and_costs_add_up():
    P = make_panel()
    W = s1.candidate(P, "breakout_top10", None)
    k = kraken()
    small = s1.simulate(P, W, k, 20.0, 100, 650, 1, 10)
    big = s1.simulate(P, W, k, 10_000.0, 100, 650, 1, 10)
    assert small["skipped"] > 0 and big["skipped"] == 0
    m = s1.measure(big, 10_000.0)
    assert m["cost_share"] == pytest.approx(big["costs"] / (big["equity"][-1] - 10_000 + big["costs"]))
    weekly = s1.simulate(P, W, k, 10_000.0, 100, 650, 7, 10)
    assert weekly["orders"] < big["orders"], "weekly trades less"
    # The dead segment is sold at its last close; nothing stays in it.
    W2 = np.zeros((T, len(NAMES)))
    W2[:, 4] = 0.5
    k2 = s1.Venue("ideal", 1.0, ideal=0.0041)
    r = s1.simulate(P, W2, k2, 1000.0, 400, 650)
    assert r["equity"][-1] == pytest.approx(r["equity"][100], rel=1e-9), "cash after LUNA~0 died"


def test_old_segments_are_cash_and_jupiter_holds_only_mints():
    P = make_panel()
    W = np.zeros((T, len(NAMES)))
    W[:, 3] = 0.5      # DOGE: no mint
    W[:, 0] = 0.5      # BTC
    r = s1.simulate(P, W, jupiter(), 100.0, 100, 200)
    assert r["orders"] == 1


# ---------------------------------------------------------------- the decisions

def _row(key, cap, venue, is_s, oos_s, cagr=0.1, cs=0.2):
    return {"key": key, "capital": cap, "venue": venue, "is_sharpe": is_s, "oos_sharpe": oos_s, "oos_cagr": cagr,
            "oos_cost_share": cs, "variant": f"{key} {venue}"}


def test_picks_are_in_sample_and_never_btc_hold():
    rows = [_row("btc_hold", 50.0, "kraken", 5.0, 0.7), _row("a", 50.0, "ideal", 9.0, 2.0),
            _row("a", 50.0, "jupiter", 1.5, 0.1), _row("b", 50.0, "kraken", 1.2, 3.0),
            _row("a", 100.0, "jupiter", 1.6, 0.1), _row("b", 100.0, "kraken", 1.1, 3.0)]
    a = s1.pick(rows, 50.0)
    assert a["key"] == "a" and a["venue"] == "jupiter", "in-sample Sharpe decides, the ideal row never"
    assert s1.pick(rows, 100.0, {a["key"]})["key"] == "b"


def test_worth_running_needs_cagr_sharpe_above_hold_and_costs_under_half():
    rows = [_row("btc_hold", 50.0, "kraken", 0, 0.7), _row("a", 50.0, "kraken", 0, 0.9),
            _row("b", 50.0, "kraken", 0, 0.9, cs=0.6), _row("c", 50.0, "kraken", 0, 0.6),
            _row("d", 50.0, "kraken", 0, 1.0, cagr=-0.01), _row("e", 50.0, "kraken", 0, 0.9, cs=None)]
    assert [r["key"] for r in s1.worth(rows, 50.0)] == ["a"]


def test_the_paper_books_are_the_registered_picks():
    md = (s1.RESULTS / "smallaccount_s1.md").read_text(encoding="utf-8")
    sec = md.split("## 6.")[1]
    for name, b in book.BOOKS.items():
        label = s1.variant_label(b["key"], b["n"], b["cadence"])
        line = next(ln for ln in sec.splitlines() if ln.startswith(f"| {b['capital']:.0f} EUR | {label} |"))
        assert f"| {b['venue']} |" in line, name


def test_no_em_dash_in_the_new_files():
    here = Path(__file__).resolve().parents[1]
    for p in (here / "lab/experiments/smallaccount.py", here / "lab/paper/smallaccount.py",
              here / "results/smallaccount_s1.md", here / "results/smallaccount_s1_prereg.md", Path(__file__)):
        assert chr(0x2014) not in p.read_text(encoding="utf-8"), p


# ---------------------------------------------------------------- the paper books

def ms(y, m, d, h=5) -> int:
    return int(datetime(y, m, d, h, tzinfo=timezone.utc).timestamp() * 1000)


def test_a_book_buys_marks_and_journals_in_eur():
    v = s1.Venue("jupiter", 1.12, ladder=LADDER)
    st = book.new_state("small50_tsmom1", v, 90.0, ms(2026, 10, 24))
    assert st["cash"] < 50.0 and st["costs_eur"] == pytest.approx(50 * 0.004 + 1 / 1.12)
    prices = {"BTC": 64_000.0, "SOL": 90.0}
    st, row, fills = book.step("small50_tsmom1", st, {"BTC": 0.8}, prices, v, 90.0, ms(2026, 10, 24), "2026-10-23",
                               True)
    assert len(fills) == 1 and fills[0]["side"] == "buy" and fills[0]["coin"] == "BTC"
    assert row["equity"] == pytest.approx(row["equity_eur"] / 50.0 * 10_000, rel=1e-5), "the 10,000 basis"
    assert 0.6 < row["exposure"] < 0.85 and row["paper_cost_bps"] > 0 and row["rebalanced"]
    assert "50 EUR paper wallet" in st["variant"] and "EUR" in st["variant"]
    json.dumps(st)
    # Next day, same target: nothing trades, the coin is marked.
    st2, row2, fills2 = book.step("small50_tsmom1", st, {"BTC": 0.8}, {"BTC": 66_000.0, "SOL": 90.0}, v, 90.0,
                                  ms(2026, 10, 25), "2026-10-24", True)
    assert fills2 == [] and row2["equity_eur"] > row["equity_eur"]
    # No price for BTC: the last mark stays and nothing in BTC trades, even when the target goes.
    st3, row3, fills3 = book.step("small50_tsmom1", st2, {}, {"SOL": 90.0}, v, 90.0, ms(2026, 10, 26), "2026-10-25",
                                  True)
    assert fills3 == [] and row3["equity_eur"] == pytest.approx(row2["equity_eur"])
    # Stale targets (None): mark only.
    st4, row4, fills4 = book.step("small50_tsmom1", st3, None, {"BTC": 60_000.0, "SOL": 90.0}, v, 90.0,
                                  ms(2026, 10, 27), None, False)
    assert fills4 == [] and row4["signal"] == "" and row4["equity_eur"] < row3["equity_eur"]


def test_the_book_targets_come_from_the_candidate(monkeypatch):
    P = make_panel()
    for name in book.BOOKS:
        tg = book.targets(P, name, 650)
        assert set(tg) <= {"BTC", "ETH", "SOL"} and sum(tg.values()) <= 1.0 + 1e-9


def test_the_report_is_in_eur_with_a_feed(tmp_path, monkeypatch):
    from lab import report
    monkeypatch.setattr(report, "REPORTS", tmp_path)
    v = s1.Venue("jupiter", 1.12, ladder=LADDER)
    books = {}
    for name in book.BOOKS:
        st = book.new_state(name, v, 90.0, ms(2026, 10, 24))
        books[name], _, _ = book.step(name, st, {"BTC": 0.5}, {"BTC": 64_000.0, "SOL": 90.0}, v, 90.0,
                                      ms(2026, 10, 24), "2026-10-23", True)
    data = book.write_report(books, ms(2026, 10, 24))
    md = (tmp_path / "smallaccount" / "latest.md").read_text(encoding="utf-8")
    assert "50 EUR" in md and "100 EUR" in md and "costs paid" in md
    assert data["title"] and data["status"] in ("ok", "watch") and "EUR" in data["headline"]
    assert len(data["items"]) == 2 and chr(0x2014) not in md
