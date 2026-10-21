"""The autopilot cost and churn audit (lab.ops.autopilot_audit) on a synthetic engine state.

Run from research/lab:  python -m pytest tests/test_autopilot_audit.py
"""

from __future__ import annotations

import json

import pytest

from lab.ops import autopilot_audit as A

H = 3_600_000
T0 = 1_792_000_000_000


def fill(i, ts, market, side, usd, cost_bps=20.0, slip_bps=5.0, maker=1.0, book="ap_x", status="filled", px=100.0):
    q = usd / px
    return {"id": f"ord_{i}", "ts": ts, "book": book, "marketId": market, "side": side, "status": status,
            "filledQty": q, "avgFillPrice": px, "realisedCostBps": cost_bps, "realisedSlippageBps": slip_bps,
            "makerQty": q * maker, "takerQty": q * (1 - maker), "strategyId": "lab:x"}


def autopilot(book="ap_x", amount=10_000.0, start=T0, equity=10_100.0, sleeves=None, repick=None, btc=(100.0, None)):
    cfg = {"id": book, "name": "Test Â· X", "capitalUsd": amount, "sleeves": sleeves or []}
    if repick is not None:
        cfg["repickEveryHours"] = repick
    return {"config": cfg, "state": "running", "startedMs": start, "startCapital": amount,
            "history": [[start, amount], [start + 5 * 24 * H, equity]], "btcStart": btc[0], "btcEnd": btc[1],
            "sleeves": [{"strategyId": "lab:x", "weight": 1.0}]}


def test_fee_and_slippage_split_the_realised_cost():
    o = fill(1, T0, "crypto:BTC/USD", "buy", 1_000.0, cost_bps=20.0, slip_bps=5.0)
    fee, slip = A.cost_split(o)
    assert fee == pytest.approx(1.5) and slip == pytest.approx(0.5)
    assert A.cost_split({**o, "realisedCostBps": None}) == (0.0, 0.0)


def test_a_coin_bought_and_sold_within_72_hours_is_a_round_trip_and_later_is_not():
    f = [fill(1, T0, "crypto:SOL/USD", "buy", 300.0),
         fill(2, T0 + 10 * H, "crypto:SOL/USD", "sell", 100.0),
         fill(3, T0 + 20 * H, "crypto:ETH/USD", "sell", 50.0),
         fill(4, T0 + 100 * H, "crypto:SOL/USD", "sell", 200.0)]
    rt = A.round_trips(f)
    assert rt["pairs"] == 1
    assert rt["notional"] == pytest.approx(100.0), "only the part that came back inside the window"
    assert rt["cost"] == pytest.approx(100.0 * 0.004), "both legs, 20 bps each"


def test_fills_within_30_minutes_are_one_rebalance():
    f = [fill(1, T0, "a", "buy", 10.0), fill(2, T0 + 20 * 60_000, "b", "buy", 10.0), fill(3, T0 + 2 * H, "a", "sell", 10.0)]
    reb = A.rebalances(f)
    assert [r["orders"] for r in reb] == [2, 1]


def test_a_rebalance_right_after_a_scheduled_repick_is_counted_as_the_repicks_own():
    reb = [{"ts": T0 + 5 * 60_000, "cost": 9.0}, {"ts": T0 + 24 * H + 60_000, "cost": 2.0},
           {"ts": T0 + 30 * H, "cost": 1.0}, {"ts": T0 + 48 * H + 3 * 60_000, "cost": 4.0}]
    rp = A.at_repick(reb, T0, 24.0)
    assert [r["cost"] for r in rp] == [2.0, 4.0], "the start itself is not a re-pick"
    assert A.at_repick(reb, T0, None) == []


def test_the_audit_of_one_autopilot_adds_up():
    amount = 10_000.0
    orders = [fill(1, T0 + H, "crypto:BTC/USD", "buy", 2_000.0),
              fill(2, T0 + 25 * H, "crypto:BTC/USD", "sell", 50.0),           # a trim, and a round trip
              fill(3, T0 + 49 * H, "crypto:ETH/USD", "buy", 500.0, maker=0.0),
              fill(4, T0 + 50 * H, "crypto:ETH/USD", "buy", 500.0, book="ap_other"),
              {"id": "r", "ts": T0 + 2 * H, "book": "ap_x", "status": "rejected", "rejectReason": "too small"},
              {"id": "c", "ts": T0 + 2 * H, "book": "ap_x", "status": "cancelled"}]
    r = A.audit_autopilot(autopilot(btc=(100.0, 103.0)), orders, T0 + 5 * 24 * H)
    assert r["name"] == "Test · X", "the wrong code page is cleaned"
    assert r["fills"] == 3 and r["refused"] == 1 and r["cancelled"] == 1
    assert r["refused_reasons"] == {"too small": 1}
    assert r["traded"] == pytest.approx(2_550.0)
    assert r["turnover_day"] == pytest.approx(2_550.0 / amount / 5)
    assert r["cost"] == pytest.approx(2_550.0 * 0.002)
    assert r["cost_bps_traded"] == pytest.approx(20.0)
    assert r["maker_share"] == pytest.approx(2_050.0 / 2_550.0)
    assert r["trims"] == 1
    assert r["round_trips"] == 1 and r["round_trip_notional"] == pytest.approx(50.0)
    assert r["return_pct"] == pytest.approx(1.0) and r["btc_pct"] == pytest.approx(3.0)
    assert r["vs_btc_pts"] == pytest.approx(-2.0)
    assert r["cost_share_of_gap"] == pytest.approx(r["cost_pct"] / 2.0)


def test_opposite_trades_of_two_autopilots_in_one_window_are_what_netting_could_save():
    orders = [fill(1, T0, "crypto:SOL/USD", "buy", 300.0, book="a"),
              fill(2, T0 + 60_000, "crypto:SOL/USD", "sell", 100.0, book="b"),
              fill(3, T0 + 60_000, "crypto:ETH/USD", "sell", 100.0, book="b"),
              fill(4, T0 + 60_000, "crypto:ETH/USD", "sell", 100.0, book="a")]
    o = A.cross_book_overlap(orders, {"a", "b"}, T0)
    assert o["traded"] == pytest.approx(600.0)
    assert o["crossable"] == pytest.approx(100.0)
    assert o["saved_at_most"] == pytest.approx(2 * 100.0 * 0.002)


def test_the_audit_reads_state_files_and_writes_markdown(tmp_path, capsysbinary):
    st = {"orders": [fill(1, T0 + H, "crypto:BTC/USD", "buy", 1_000.0)], "prices": {"crypto:BTC/USD": [105.0, T0]},
          "autopilots": [autopilot(), {**autopilot("ap_old"), "state": "stopped"}]}
    d = tmp_path / "autopilot"
    d.mkdir()
    (d / "state.json").write_text(json.dumps(st), encoding="utf-8")
    assert A.main([str(d / "state.json")]) == 0
    out = capsysbinary.readouterr().out.decode("utf-8")
    assert "Test · X (main)" in out and "ap_old" not in out
    assert "5.00 %" in out, "BTC from its start price to the engine's last price"
