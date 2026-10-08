"""The forward report's band and sentence rules on synthetic journals. No network, no lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import csv
import json
import math

import numpy as np
import pytest

from lab import report
from lab.paper import forward_report as fr

START = fr.START_EQUITY


@pytest.fixture()
def reports(tmp_path, monkeypatch):
    """Reports (and the exported backtest series) in a temp folder."""
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    return tmp_path


def write_series(book: str, returns, period_days: float = 1.0) -> None:
    d = fr.backtest_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{book}.json").write_text(json.dumps({"book": book, "source": "synthetic", "period_days": period_days,
                                                "max_dd_pct": 10.0, "returns": list(map(float, returns))}))


def journal(root, book: str, equity: list[float], start_day: int = 1, **cols) -> list[dict]:
    rows = []
    for i, e in enumerate(equity):
        row = {"date": f"2026-10-{start_day + i:02d}", "equity": f"{e:.2f}", "turnover": "0.5" if i == 0 else "0.0",
               "paper_cost_bps": "5.0" if i == 0 else "0.0", "model_cost_bps": "7.5" if i == 0 else "0.0"}
        row.update({k: v[i] for k, v in cols.items()})
        rows.append(row)
    d = root / "paper" / book
    d.mkdir(parents=True, exist_ok=True)
    with (d / "journal.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return fr.read_journal(book, root)


# ---------------------------------------------------------------- band

def test_constant_returns_give_a_point_band():
    b = fr.bootstrap_band(np.full(500, 0.001), 20)
    want = (1.001 ** 20 - 1) * 100
    assert b["low_pct"] == pytest.approx(want) and b["high_pct"] == pytest.approx(want)
    assert b["median_pct"] == pytest.approx(want)
    assert b["dd_p95_pct"] == pytest.approx(0.0)


def test_band_widens_like_the_square_root_of_time():
    r = np.random.default_rng(1).normal(0.0, 0.02, 3000)
    short, long_ = fr.bootstrap_band(r, 5, block_days=1), fr.bootstrap_band(r, 20, block_days=1)
    assert short["low_pct"] < 0 < short["high_pct"]
    ratio = (long_["high_pct"] - long_["low_pct"]) / (short["high_pct"] - short["low_pct"])
    assert 1.7 < ratio < 2.3        # sqrt(4) = 2, give or take compounding and sampling
    assert abs(long_["median_pct"]) < 1.0


def test_weekly_series_scale_the_last_week():
    weekly = np.full(100, 0.07)
    assert fr.bootstrap_band(weekly, 14, period_days=7)["median_pct"] == pytest.approx((1.07 ** 2 - 1) * 100)
    # 10.5 days: one full week and half of another.
    assert fr.bootstrap_band(weekly, 10.5, period_days=7)["median_pct"] == pytest.approx((1.07 * 1.035 - 1) * 100)


def test_no_band_without_horizon_or_history():
    assert fr.bootstrap_band(np.full(100, 0.01), 0) is None
    assert fr.bootstrap_band(np.array([0.01]), 5) is None


def test_worst_dip_band_sees_losing_stretches():
    r = np.r_[np.full(50, -0.01), np.full(50, 0.01)]
    assert fr.bootstrap_band(r, 10)["dd_p95_pct"] > 5


def test_normal_band_from_growth_and_volatility():
    b = fr.normal_band(0.0, 0.20, 365)
    assert b["median_pct"] == pytest.approx(0.0)
    assert b["low_pct"] == pytest.approx(math.expm1(-1.6448536 * 0.2) * 100, rel=1e-6)
    assert fr.normal_band(0.1, 0.0, 30) is None


def test_position():
    band = {"low_pct": -2.0, "high_pct": 3.0}
    assert fr.position(-2.5, band) == "below"
    assert fr.position(0.0, band) == "inside"
    assert fr.position(3.5, band) == "above"
    assert fr.position(1.0, None) is None


# ---------------------------------------------------------------- sentence rules

def test_sentences_for_books():
    assert fr.book_verdict(0, 0, None, False, None, False, 0.0)[0] == "none"
    s, t = fr.book_verdict(3, 2, "inside", False, None, False, 0.4)
    assert s == "early" and t.startswith("Too early to say: 3 days of practice")
    s, t = fr.book_verdict(3, 2, "below", False, None, False, -3.0)
    assert s == "watch" and "worth watching" in t and "very little" in t
    s, t = fr.book_verdict(12, 11, "below", False, None, False, -6.0)
    assert (s, t) == ("watch", "Below the backtest's range after 11 days, worth watching.")
    assert fr.book_verdict(12, 11, "inside", False, None, False, 1.0) == (
        "on_track", "On track: inside the backtest's range after 11 days.")
    assert fr.book_verdict(12, 11, "above", False, None, False, 9.0)[0] == "ahead"
    assert fr.book_verdict(12, 11, None, False, None, False, 1.0)[0] == "unknown"
    s, t = fr.book_verdict(12, 11, "inside", True, None, False, -1.0)
    assert s == "watch" and "worst dip" in t
    assert "costs" not in fr.book_verdict(12, 11, "inside", False, 1.2, False, 1.0)[1]
    assert "2.0x what the backtest assumes" in fr.book_verdict(12, 11, "inside", False, 2.0, False, 1.0)[1]
    assert fr.book_verdict(31, 30, "inside", False, None, True, 1.0)[1].startswith("Ready for the gate 7 review.")


def test_sentences_for_autopilots():
    s, t = fr.autopilot_verdict("stopped", "stopped by you", 2.0, -0.5, 1.0, None, False, 10.0, -40.0)
    assert s == "stopped" and t.startswith("Stopped (stopped by you) after 2 days at -0.50 % (BTC +1.00 %).")
    assert "lost money even before fees" in t
    s, t = fr.autopilot_verdict("running", None, 0.25, -0.5, None, None, False, 2.0, -3.0)
    assert s == "early" and "6 hours running" in t
    assert fr.autopilot_verdict("running", None, 10, -9.0, None, None, True, 5.0, -800.0)[0] == "watch"
    s, t = fr.autopilot_verdict("running", None, 10, 1.0, 3.0, None, False, 120.0, 180.0)
    assert s == "unknown" and "behind BTC by 2.00 points" in t and "Fees took 67 %" in t
    assert "Fees" not in fr.autopilot_verdict("running", None, 10, 1.0, 3.0, None, False, 60.0, 180.0)[1]
    assert fr.autopilot_verdict("running", None, 10, 1.0, 0.0, "inside", False, 1.0, 2.0)[0] == "on_track"
    assert fr.fees_share_of_gross(10.0, -5.0) is None


# ---------------------------------------------------------------- synthetic journals

def test_book_below_its_backtest_is_worth_watching(reports):
    write_series("tsmom", np.random.default_rng(2).normal(0.001, 0.005, 800))
    j = journal(reports, "tsmom", [START * (1 - 0.01 * i) for i in range(1, 13)])
    row = fr.book_row("tsmom", j)
    assert row["days"] == 12 and row["elapsed_days"] == 11
    assert row["position"] == "below" and row["status"] == "watch"
    assert row["expected"]["method"] == "bootstrap"
    assert row["max_dd_pct"] == pytest.approx(12.0, abs=0.01)
    assert row["costs"]["ratio"] == pytest.approx(5.0 / 7.5)
    assert row["gate7"] == {"days": 12, "days_needed": 30, "trades": 1, "trades_needed": 30,
                            "trades_label": "rebalances", "progress": pytest.approx(1 / 30), "ready": False}


def test_book_inside_its_backtest_is_on_track(reports):
    write_series("tsmom_regime", np.random.default_rng(3).normal(0.001, 0.01, 800))
    eq = [START * (1.001 ** i) for i in range(1, 13)]
    row = fr.book_row("tsmom_regime", journal(reports, "tsmom_regime", eq))
    assert (row["position"], row["status"]) == ("inside", "on_track")


def test_modelled_only_books_and_funding(reports):
    eq = [9990.0, 10010.0, 10030.0]
    j = journal(reports, "picks_ls", eq, rebalanced=["True", "False", "False"], funding_pnl=["0", "-2", "-3"])
    row = fr.book_row("picks_ls", j)
    assert row["costs"]["modelled_only"] and row["costs"]["ratio"] is None
    assert row["costs"]["paper_pct"] == pytest.approx(0.05)     # 0.5 turnover at 10 bps
    assert row["funding_pct"] == pytest.approx(-0.05)
    assert row["expected"] is None and row["status"] == "early"


def test_missing_journal_is_not_started(reports):
    row = fr.book_row("m4_ls", [])
    assert row["status"] == "none" and row["gate7"]["progress"] == 0.0


# ---------------------------------------------------------------- autopilots

def state(**over) -> dict:
    ap = {"config": {"id": "ap_1", "name": "Practice", "mode": "paper", "venue": "kraken", "capitalUsd": 10000,
                     "sleeves": []},
          "state": "running", "stopReason": None, "startedMs": 0, "stoppedMs": None, "startCapital": 10000.0,
          "equity": 10100.0, "pnl": 100.0, "fees": 20.0, "trades": 12, "floorEquity": 8500.0, "drawdownPct": 1.0,
          "bySleeve": [{"strategyId": "lab:breakout_top10", "name": "Lab breakout", "weight": 1.0}]}
    ap.update(over)
    return ap


ORDERS = [
    {"strategyId": "lab:breakout_top10", "status": "filled", "ts": 1000, "route": "paper",
     "realisedSlippageBps": 2.0, "modelledSlippageBps": 1.0},
    {"strategyId": "lab:breakout_top10", "status": "filled", "ts": 2000, "route": "paper",
     "realisedSlippageBps": 4.0, "modelledSlippageBps": 1.0},
    {"strategyId": "lab:breakout_top10", "status": "filled", "ts": 3000, "route": "demo",
     "realisedSlippageBps": 1.0, "modelledSlippageBps": 2.0},
    {"strategyId": "other", "status": "filled", "ts": 1500, "route": "paper",
     "realisedSlippageBps": 50.0, "modelledSlippageBps": 1.0},
    {"strategyId": "lab:breakout_top10", "status": "rejected", "ts": 1500, "route": "paper"},
]


def test_slippage_per_route_only_counts_its_own_fills():
    rows = fr.slippage_by_route(ORDERS, {"lab:breakout_top10"}, 0, 2500)
    assert rows == [{"route": "paper", "fills": 2, "median_realised_bps": 3.0, "median_modelled_bps": 1.0,
                     "ratio": 3.0}]
    assert [r["route"] for r in fr.slippage_by_route(ORDERS, {"lab:breakout_top10"}, 0, 9999)] == ["demo", "paper"]


def test_autopilot_row_against_btc_and_its_lab_book(reports):
    write_series("breakout_top10", np.random.default_rng(4).normal(0.0005, 0.01, 800))
    now = 10 * fr.DAY_MS
    prices = {0: 100.0, now: 103.0}
    row = fr.autopilot_row(state(), ORDERS, now, price_at=lambda ms: prices.get(ms))
    assert row["return_pct"] == pytest.approx(1.0) and row["btc_return_pct"] == pytest.approx(3.0)
    assert row["fees_share_of_gross"] == pytest.approx(20 / 120)
    assert row["trades_per_day"] == pytest.approx(1.2)
    assert row["lab_book"] == "breakout_top10" and row["expected"]["method"] == "bootstrap"
    assert row["status"] in ("on_track", "ahead")
    assert row["gate7"]["trades_label"] == "closed trades" and row["gate7"]["days"] == 10


def test_autopilot_near_its_floor_and_without_prices(reports):
    row = fr.autopilot_row(state(equity=9000.0, pnl=-1000.0, bySleeve=[]), [], 10 * fr.DAY_MS, price_at=lambda ms: None)
    assert row["btc_return_pct"] is None and row["status"] == "watch"
    assert "Closer to its stop than to its start" in row["sentence"]


def test_engine_down_is_reported_not_raised(reports, tmp_path):
    data = fr.build(now_ms=fr.DAY_MS, url="http://127.0.0.1:9/api/state", price_at=lambda ms: None, root=tmp_path)
    assert data["engine"]["reachable"] is False and data["engine"]["error"]
    assert data["autopilots"] == []
    assert "not reachable" in data["verdict"]
    assert len(data["books"]) == len(fr.BOOKS)          # every book listed, all "not started"
    assert "# Forward tests" in fr.markdown(data)
    off = fr.build(now_ms=fr.DAY_MS, url="off", price_at=lambda ms: None, root=tmp_path)
    assert "switched off" in off["engine"]["error"]


def test_engine_state_from_a_file(reports, tmp_path):
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"autopilots": [state(state="stopped", stopReason="stopped by you", stoppedMs=fr.DAY_MS)],
                             "orders": ORDERS, "slippage": [{"venue": "kraken", "route": "paper", "fills": 3,
                                                             "medianRealisedBps": 1.0, "medianModelledBps": 2.0,
                                                             "ratio": 0.5, "enough": False}]}))
    data = fr.build(now_ms=2 * fr.DAY_MS, url=f.as_uri(), price_at=lambda ms: 100.0, root=tmp_path)
    assert data["engine"]["reachable"] and data["autopilots"][0]["status"] == "stopped"
    assert data["engine"]["slippage"][0]["ratio"] == 0.5
    assert "Practice" in fr.markdown(data)
