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


def test_a_cut_amount_does_not_turn_dollars_into_a_bigger_return(reports):
    # ap_29742: $99,500 for nearly all of its run, cut to $20,000 minutes before its stop.
    ap = state(startCapital=20_000.0, equity=18_034.22, pnl=-1_965.78, fees=145.67, avgCapital=99_424.0,
               state="stopped", stopReason="stopped by you", stoppedMs=2 * fr.DAY_MS, bySleeve=[],
               curveNote="Curve repaired after the fact: 2 amount change(s).")
    row = fr.autopilot_row(ap, [], 2 * fr.DAY_MS, price_at=lambda ms: None)
    assert row["return_pct"] == pytest.approx(-1.977, abs=1e-3), "not -9.83 % of the new amount"
    assert row["fees_pct_of_capital"] == pytest.approx(0.1465, abs=1e-4), "not 0.73 %"
    assert "the $99,424 it worked with on average" in row["sentence"] and "Curve repaired" in row["sentence"]
    plain = fr.autopilot_row(state(), [], 10 * fr.DAY_MS, price_at=lambda ms: None)
    assert plain["return_pct"] == pytest.approx(1.0) and "worked with" not in plain["sentence"]


def test_trades_per_day_counts_orders_not_maker_child_fills(reports):
    # 12 closed-trade ticks from child fills, but 7 orders over ten days.
    row = fr.autopilot_row(state(orders=7), ORDERS, 10 * fr.DAY_MS, price_at=lambda ms: None)
    assert row["trades_per_day"] == pytest.approx(0.7)
    assert row["orders"] == 7 and row["trades"] == 12


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


# ---------------------------------------------------------------- evidence.json for the engine

def test_evidence_status_waits_ten_days():
    assert fr.EVIDENCE_MIN_DAYS == 10
    assert fr.evidence_status(9.9, "below", "watch") == "early"
    assert fr.evidence_status(10, "below", "watch") == "below"
    assert fr.evidence_status(12, "inside", "watch") == "watch"
    assert fr.evidence_status(12, "inside", "on_track") == "ok"
    assert fr.evidence_status(12, "above", "ahead") == "ok"
    assert fr.evidence_status(12, None, "unknown") == "none"


def test_evidence_file_per_book_and_autopilot(reports, tmp_path):
    write_series("tsmom", np.random.default_rng(2).normal(0.001, 0.005, 800))
    journal(tmp_path, "tsmom", [START * (1 - 0.01 * i) for i in range(1, 13)])          # 11 days, far below
    journal(tmp_path, "tsmom_regime", [START * 0.9, START * 0.8, START * 0.7])         # below, but 2 days
    f = tmp_path / "state.json"
    f.write_text(json.dumps({"autopilots": [state(bySleeve=[])], "orders": []}))
    data = fr.build(now_ms=3 * fr.DAY_MS, url=f.as_uri(), price_at=lambda ms: None, root=tmp_path)
    p = fr.write_evidence(data)
    assert p.name == "evidence.json" and p.parent == report.REPORTS / "forward"
    ev = json.loads(p.read_text(encoding="utf-8"))
    assert ev["min_days"] == 10 and ev["generated_ms"] == 3 * fr.DAY_MS
    ts = ev["books"]["tsmom"]
    assert ts["status"] == "below" and ts["days"] == 11
    assert ts["return_pct"] == pytest.approx(-12.0)
    assert ts["band_low_pct"] < ts["band_high_pct"] and ts["return_pct"] < ts["band_low_pct"]
    assert ts["band_method"] == "bootstrap"
    assert ev["books"]["tsmom_regime"]["status"] == "early"
    assert "m4_ls" not in ev["books"], "a book that has not started says nothing"
    ap = ev["autopilots"]["ap_1"]
    assert ap["status"] == "early" and ap["state"] == "running" and ap["band_low_pct"] is None
    assert not list(p.parent.glob("*.tmp"))


def test_evidence_is_strict_json(reports):
    data = {"generated_ms": 1, "books": [{"name": "x", "days": 12, "elapsed_days": 11.0, "return_pct": float("nan"),
                                          "expected": None, "position": None, "status": "unknown"}],
            "autopilots": []}
    text = json.dumps(fr.evidence(data), allow_nan=False)
    assert json.loads(text)["books"]["x"] == {"days": 11.0, "return_pct": None, "band_low_pct": None,
                                              "band_high_pct": None, "band_method": None, "status": "none"}


# ---------------------------------------------------------------- BTC above its 200-day average

def test_the_gate_calendar_holds_btc_on_a_day_after_a_close_above_its_200_day_average():
    D = fr.DAY_MS
    t0 = 20_000 * D
    # 200 closes at 100, then 120 (above), then 90 (below), then today.
    closes = [(t0 + i * D, 100.0) for i in range(200)] + [(t0 + 200 * D, 120.0), (t0 + 201 * D, 90.0)]
    cal = fr.gate_calendar(closes, t0 + 202 * D + 3_600_000)
    days = {d["day_ms"]: d for d in cal["days"]}
    assert cal["sma_days"] == 200
    assert days[t0 + 200 * D]["on"] is False, "100 is not above an average of 100"
    assert days[t0 + 201 * D]["on"] is True and days[t0 + 201 * D]["close"] == 90.0
    assert days[t0 + 202 * D]["on"] is False and days[t0 + 202 * D]["close"] is None, "today: set by yesterday's close"
    assert max(days) == t0 + 202 * D, "nothing after today"
    assert fr.gate_calendar(closes[:150], t0 + 202 * D) is None, "fewer than 200 closes"
    assert fr.gate_calendar(closes[:100] + closes[101:], t0 + 202 * D) is None, "a gap in the days"

    # On day 201 (gate on) from noon at 110 to its close at 90; day 202 off.
    r = fr.gated_return_pct(cal, t0 + 201 * D + D // 2, 110.0, t0 + 202 * D + 3_600_000, 95.0)
    assert r == pytest.approx((90.0 / 110.0 - 1) * 100)
    assert fr.gated_return_pct(cal, t0 + 202 * D, 90.0, t0 + 202 * D + 60_000, 99.0) == 0.0, "off: cash"
    assert fr.gated_return_pct(None, 0, 1.0, 1, 1.0) is None
    assert fr.gated_return_pct(cal, t0 - 5 * D, 1.0, t0 + 202 * D, 1.0) is None, "a day the calendar does not have"


def test_autopilots_carry_gated_btc_and_the_evidence_file_carries_the_calendar(reports, tmp_path):
    D = fr.DAY_MS
    now = 300 * D
    closes = [(i * D, 100.0 + i) for i in range(300)]        # rising: the gate is on
    f = tmp_path / "state.json"
    ap = state(bySleeve=[])
    ap.update(startedMs=now - D, stoppedMs=None)
    f.write_text(json.dumps({"autopilots": [ap], "orders": []}))
    data = fr.build(now_ms=now, url=f.as_uri(), price_at=lambda ms: 100.0 + ms / D, root=tmp_path,
                    closes_fetch=lambda: closes)
    row = data["autopilots"][0]
    assert row["btc_gated_return_pct"] == pytest.approx(row["btc_return_pct"]), "on every day: gated BTC is BTC"
    assert "btc_gated" in fr.markdown(data)
    ev = json.loads(fr.write_evidence(data).read_text(encoding="utf-8"))
    assert ev["btc_gate"]["sma_days"] == 200 and ev["btc_gate"]["days"][-1]["day_ms"] == now
    # Without closes: no calendar, n/a, nothing guessed.
    data = fr.build(now_ms=now, url=f.as_uri(), price_at=lambda ms: 100.0, root=tmp_path)
    assert data["btc_gate"] is None and data["autopilots"][0]["btc_gated_return_pct"] is None
