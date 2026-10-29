"""S1w, the small-account books traded weekly (lab.experiments.smallaccount_weekly): the weekday, the no-trade band,
the wallet with both, on time and late, the costs in EUR, the rule to follow, the trials, the leak harness and the
report. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_smallaccount_weekly.py
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import smallaccount as s1
from lab.experiments import smallaccount_s2 as s2
from lab.experiments import smallaccount_weekly as wk

from test_smallaccount_r10 import market
from test_smallaccount_s2 import LADDER, T

WED = 2                                         # numpy's weekday of 1970-01-01 is Thursday: (days + 3) % 7, Monday 0


def weekday_of(days_us: np.ndarray) -> np.ndarray:
    return ((days_us // fc.DAY_US) + 3) % 7


def test_the_weekday_is_wednesday():
    days = s1.ANCHOR_US + np.arange(60, dtype=np.int64) * fc.DAY_US
    m = wk.weekday(days)
    assert m.sum() == 9 and (weekday_of(days[m]) == WED).all() and (weekday_of(days[~m]) != WED).all()


def test_the_band_skips_a_small_trade_and_lets_an_exit_and_a_big_move_through():
    w = s1.Wallet(cash=40.0, units={"BTC": 0.5, "ETH": 0.1})           # BTC 50 of 100, ETH 10 of 100
    px = {"BTC": 100.0, "ETH": 100.0, "SOL": 10.0}
    tg = {"BTC": 0.55, "ETH": 0.0, "SOL": 0.08}
    assert wk.banded(w, tg, px, 0.10) == {"ETH": 0.0}                  # +5 and +8 points wait, the exit goes
    assert wk.banded(w, {"BTC": 0.65, "SOL": 0.10}, px, 0.10) == {"BTC": 0.65, "SOL": 0.10}
    assert wk.banded(w, tg, px, 0.0) == tg
    v = s2.S2Venue("jupiter", 1.0, ladder={**LADDER, "ETH": LADDER["BTC"]})
    fills = s1.rebalance(w, wk.banded(w, tg, px, 0.10), px, v, 100.0)
    assert [f["key"] for f in fills] == ["ETH"] and "BTC" not in w.last and w.units["BTC"] == 0.5


def _wallet(due, band=0.0, W=None, cap=300.0):
    days = s1.ANCHOR_US + np.arange(70, dtype=np.int64) * fc.DAY_US
    px = np.column_stack([np.full(70, 100.0), np.full(70, 50.0)])
    if W is None:
        W = np.column_stack([0.4 + 0.3 * (np.arange(70) % 2), np.full(70, 0.2)])      # BTC 40 / 70 % every other day
    v = s2.S2Venue("jupiter", 1.0, ladder={**LADDER, "ETH": LADDER["BTC"]})
    return days, wk.simulate(px, ["BTC", "ETH"], W, due, np.full(70, 100.0), v, cap, 0, 69, 2, days, band)


def test_a_weekly_wallet_trades_only_on_the_weekday_and_late_on_thursday():
    days = s1.ANCHOR_US + np.arange(70, dtype=np.int64) * fc.DAY_US
    _, daily = _wallet(np.ones(70, dtype=bool))
    _, weekly = _wallet(wk.weekday(days))
    tdays = np.flatnonzero(weekly["traded"] > 0)
    assert len(tdays) and (weekday_of(days[tdays[tdays > 0]]) == WED).all()
    assert len(np.flatnonzero(daily["traded"] > 0)) > len(tdays) and weekly["orders"] < daily["orders"]
    assert wk.wednesdays_only(days, tdays, 0, False) and not wk.wednesdays_only(days, tdays, 0, True)
    _, late = _wallet(np.r_[False, wk.weekday(days)[:-1]])
    lt = np.flatnonzero(late["traded"] > 0)
    assert (weekday_of(days[lt[lt > 0]]) == WED + 1).all() and wk.wednesdays_only(days, lt, 0, True)


def test_the_band_cuts_the_small_moves_and_their_costs():
    days = s1.ANCHOR_US + np.arange(70, dtype=np.int64) * fc.DAY_US
    W = np.column_stack([0.60 + 0.05 * (np.arange(70) // 7 % 2), np.full(70, 0.2)])  # BTC 60 / 65 % week by week
    _, plain = _wallet(wk.weekday(days), 0.0, W)
    _, band = _wallet(wk.weekday(days), wk.BAND, W)
    assert band["paid"].sum() < plain["paid"].sum() and band["orders"] == 2      # the first buys only
    assert plain["costs"] > band["costs"] > 0


def test_the_variants_run_on_time_and_late_and_their_costs_add_up_in_eur():
    mk = market()
    memo: dict = {}
    for book in wk.BOOKS:
        assert wk.variants(book) == (["as_run", "weekly_band"] if book == "small40_vol_target" else list(wk.VARIANTS))
    for book in ("small50_tsmom1", "small40_spy_trend"):
        cap = wk.BOOKS[book]["capital"]
        got = {}
        for v in wk.variants(book):
            r = wk.run(mk, book, v, True, 400, T - 1, memo=memo)
            m = wk.measure(r, cap)
            assert len(r["eq"]) == T - 400 and np.isfinite(r["eq"]).all() and r["eq"][0] < cap
            assert m["costs_eur"] == pytest.approx(m["trading_eur"] + m["way_in_eur"] + m["way_back_eur"])
            assert m["costs_share"] == pytest.approx(m["costs_eur"] / cap) and m["way_in_eur"] > 0
            if v != "as_run":
                assert wk.wednesdays_only(mk.P.days, r["trade_days"], 400, True)
            got[v] = m
        assert got["weekly"]["orders_yr"] <= got["as_run"]["orders_yr"]
        assert got["weekly_band"]["orders_yr"] <= got["weekly"]["orders_yr"]
    on = wk.run(mk, "small50_tsmom1", "weekly", False, 400, T - 1, memo=memo)
    assert wk.wednesdays_only(mk.P.days, on["trade_days"], 400, False)


def _row(trading, sharpe, cagr, leak=True):
    a = {"trading_eur": 2.0, "sharpe": 1.0, "cagr": 0.20}
    return {"late": {"as_run": a, "weekly_band": {"trading_eur": trading, "sharpe": sharpe, "cagr": cagr}},
            "leak": {"ok": leak}}


def test_the_rule_to_follow_needs_lower_costs_the_signal_kept_and_no_leak():
    assert wk.follows(_row(1.0, 0.91, 0.195))["follow"]
    assert wk.follows(_row(2.0, 1.2, 0.3))["fails"] == ["trading costs below as run"]
    assert wk.follows(_row(1.0, 0.89, 0.25))["fails"] == ["Sharpe >= as run - 0.10"]
    assert wk.follows(_row(1.0, 1.0, 0.185))["fails"] == ["CAGR >= as run - 1 pt"]
    assert wk.follows(_row(1.0, 1.0, 0.2, leak=False))["fails"] == ["no leak"]


def test_every_new_variant_is_one_small_trial_and_the_as_run_books_none(tmp_path, monkeypatch):
    from lab import metrics
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    trials = [wk.trial(b, v, 1.0) for b in wk.BOOKS for v in wk.variants(b) if v != "as_run"]
    assert len(trials) == 7 and len({t["id"] for t in trials}) == 7
    assert all(t["family"] == "small" and t["id"].startswith("small:s1w:") for t in trials)
    before = metrics.trial_pool("small")["n_trials"]
    metrics.register(trials)
    metrics.register(trials)                                             # once per id
    assert metrics.trial_pool("small")["n_trials"] == before + 7


def test_the_leak_harness_finds_nothing_in_the_weekly_band_wallets():
    mk = market()
    for book in ("small50_tsmom1", "small40_spy_trend"):
        res = wk.leak_check(mk, book, n_cuts=2)
        assert res["ok"], res["reason"]
        assert res["runs"] == 8


def test_the_report_says_the_band_the_dsr_direction_and_the_verdict():
    m = {"cagr": 0.1, "max_dd": 0.2, "sharpe": 0.8, "end_eur": 55.0, "costs_eur": 3.0, "trading_eur": 1.0,
         "way_in_eur": 1.2, "way_back_eur": 0.8, "costs_share": 0.06, "trading_share_yr": 0.008, "turnover_yr": 4.0,
         "orders_yr": 20.0, "skipped_yr": 1.0, "dsr": 0.1, "dsr_small": 0.4, "dsr_ex": None, "dsr_ex_small": None}
    rows = {}
    for book in wk.BOOKS:
        vs = {v: dict(m, dsr_ex=None if v == "as_run" else 0.3, dsr_ex_small=None if v == "as_run" else 0.5)
              for v in wk.variants(book)}
        rows[book] = {"late": vs, "on_time": vs, "today": vs, "is_sharpe": {v: 1.0 for v in vs},
                      "leak": {"ok": True, "reason": "no leak (8 runs)"}, "verdict": {"follow": False,
                                                                                      "fails": ["trading costs below as run"]}}
    out = {"generated": "now", "val_to": "2026-06-30", "rows": rows, "trials": ["small:s1w:x:weekly"],
           "pools": {"all": {"n_trials": 2800, "sr0_annual": 2.8}, "small": {"n_trials": 200, "sr0_annual": 1.4}},
           "pbo": {**{b: {"pbo": 0.5} for b in wk.BOOKS}, "all": None}}
    md = wk.markdown(out)
    assert "band 10 points" in md and "higher is better, pass at 0.95 or more" in md and "all n/a" in md
    assert "| small40_vol_target | weekly_band |" in md and "| small40_vol_target | weekly |" not in md
    assert chr(0x2014) not in md


# ---------------------------------------------------------------- the paper books that follow

def test_the_weekly_books_sit_beside_the_ones_that_passed_with_the_same_wallet():
    from lab.paper import smallaccount as book
    assert set(book.S1W_BOOKS) == {"small50_tsmom1_wk", "small40_spy_trend_wk", "small40_vol_target_wk"}
    for name, b in book.S1W_BOOKS.items():
        src = book.ALL_BOOKS[name[:-3]]
        assert b["capital"] == src["capital"] and b["key"] == src["key"] and b["n"] == src["n"]
        assert b["cadence"] == "weekly" and b["band"] == wk.BAND and b["study"] == "S1w"
        assert "Wednesday" in book.variant(name)
    assert {b["path"] for b in book.S1W_BOOKS.values()} == {"S1", "S2"}
    assert not set(book.S1W_BOOKS) & set(book.BOOKS) and not set(book.S1W_BOOKS) & set(book.S2_BOOKS)
    days = s1.ANCHOR_US + np.arange(21, dtype=np.int64) * fc.DAY_US
    cad = s1.CADENCES[book.S1W_BOOKS["small50_tsmom1_wk"]["cadence"]]
    assert [s1.rebalance_day(d, cad) for d in days] == list(wk.weekday(days))


def test_a_weekly_paper_book_skips_a_small_trade_and_still_exits():
    from datetime import datetime, timezone
    from lab.paper import smallaccount as book
    ms = lambda d: int(datetime(2026, 10, d, 5, tzinfo=timezone.utc).timestamp() * 1000)    # noqa: E731
    v = s1.Venue("jupiter", 1.12, ladder={"BTC": [(5.0, 1.0), (500.0, 8.0)], "SOL": [(5.0, 0.5), (500.0, 0.5)]})
    st = book.new_state("small50_tsmom1_wk", v, 90.0, ms(22))
    px = {"BTC": 64_000.0, "SOL": 90.0}
    st, _, fills = book.step("small50_tsmom1_wk", st, {"BTC": 0.8}, px, v, 90.0, ms(22), "2026-10-21", True, band=wk.BAND)
    assert len(fills) == 1 and fills[0]["side"] == "buy"
    plain, _, f_plain = book.step("small50_tsmom1_wk", st, {"BTC": 0.6}, px, v, 90.0, ms(29), "2026-10-28", True)
    banded, row, f_band = book.step("small50_tsmom1_wk", st, {"BTC": 0.88}, px, v, 90.0, ms(29), "2026-10-28", True,
                                    band=wk.BAND)
    assert len(f_plain) == 1 and f_band == [] and not row["rebalanced"] and banded["last"]["BTC"] == 0.8
    out, _, f_exit = book.step("small50_tsmom1_wk", st, {"BTC": 0.0}, px, v, 90.0, ms(29), "2026-10-28", True,
                               band=wk.BAND)
    assert [f["side"] for f in f_exit] == ["sell"] and not out["units"]


def test_no_em_dash_in_the_new_files():
    from pathlib import Path
    here = Path(__file__).resolve().parents[1]
    for p in (here / "lab/experiments/smallaccount_weekly.py", here / "lab/paper/smallaccount.py",
              here / "results/smallaccount_weekly.md", here / "results/smallaccount_weekly_prereg.md", Path(__file__)):
        assert chr(0x2014) not in p.read_text(encoding="utf-8"), p
