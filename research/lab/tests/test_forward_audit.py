"""The forward record audit (results/forward_audit_prereg.md) and the fixes it led to, on
synthetic journals and panels. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_forward_audit.py
"""

from __future__ import annotations

import csv
import json

import numpy as np
import pytest

from lab import report
from lab.experiments import fam_common as fc
from lab.paper import families
from lab.paper import forward_audit as fa
from lab.paper import forward_report as fr

DAY_US = fc.DAY_US
START = 1_759_276_800_000_000          # 2025-10-01 00:00 UTC


# ---------------------------------------------------------------- check 1

def test_a_coin_day_is_a_mismatch_past_one_percent_of_the_book_or_on_the_other_side():
    rows = fa.reconcile_day({"BTC": 0.10, "ETH": 0.05, "SOL": 0.004}, {"BTC": 0.105, "ETH": 0.03, "XRP": -0.002})
    by = {r["coin"]: r for r in rows}
    assert not by["BTC"]["mismatch"], "half a percent of the book apart is the same holding"
    assert by["ETH"]["mismatch"], "two percent of the book apart is not"
    assert not by["SOL"]["mismatch"], "held by one side only, but under 1 %"
    assert not by["XRP"]["mismatch"]
    assert fa.reconcile_day({"XRP": 0.004}, {"XRP": -0.004})[0]["mismatch"], "opposite signs always count"
    assert fa.reconcile_day({}, {"BTC": 0.0}) == [], "nothing held either side is no coin-day"


def test_a_book_is_reconciled_day_by_day_against_the_close_before_its_run():
    journal = [{"date": "2026-10-07", "weights": json.dumps({"BTC": 0.1, "NEAR": 0.033})},
               {"date": "2026-10-08", "weights": json.dumps({"NEARUSDT": 0.035})},
               {"date": "2026-10-09", "weights": "{}"}]
    asked = []

    def target_for(date):
        asked.append(date)
        return {"2026-10-07": {"BTC": 0.0994, "NEAR": 0.0512}, "2026-10-08": {"NEAR": 0.0543}}.get(date)

    r = fa.reconcile_book(journal, target_for)
    assert asked == ["2026-10-07", "2026-10-08", "2026-10-09"]
    assert (r["coin_days"], r["mismatches"]) == (3, 2) and r["missing"] == ["2026-10-09"]
    assert r["kill"] and not r["pass"], "2 of 3 coin-days is far past 5 %"
    assert [w["coin"] for w in r["worst"]] == ["NEAR", "NEAR"]


# ---------------------------------------------------------------- check 2

def test_rolling_windows_compound_and_the_percentile_counts_windows_below():
    net = np.array([0.01, -0.02, 0.03, 0.0, 0.01])
    w = fa.rolling_returns(net, 2)
    assert w == pytest.approx([1.01 * 0.98 - 1, 0.98 * 1.03 - 1, 1.03 - 1, 1.01 - 1])
    assert len(fa.rolling_returns(net, 6)) == 0
    p = fa.percentile_of(0.0, w)
    assert p["windows"] == 4 and p["percentile"] == pytest.approx(25.0)
    assert p["pass"] and not p["kill"]
    low = fa.percentile_of(-0.5, w)
    assert low["percentile"] == 0.0 and low["kill"] and not low["pass"]


def test_the_percentile_check_uses_out_of_sample_days_before_the_record_and_the_same_days_beside_it():
    days = np.array([fa.day_of("2023-12-30") + i * DAY_US for i in range(20)])
    gross = np.full(20, 0.001)
    tov = np.zeros(20)
    journal = [{"date": "2024-01-10", "equity": "10000"}, {"date": "2024-01-13", "equity": "10100"}]
    out = fa.percentile_check(journal, days, gross, tov)
    assert out["days"] == 3 and out["forward_pct"] == pytest.approx(1.0)
    c = out["costs"]["35 bps"]
    # Windows only from 2024-01-01 to the day before the record started (2024-01-09): 9 days, 7 windows of 3.
    assert out["oos_days"] == 9 and c["windows"] == 7
    assert c["backtest_same_days_pct"] == pytest.approx((1.001 ** 3 - 1) * 100)
    assert c["percentile"] == 100.0, "1 % in 3 days beats every 0.3 % window"


# ---------------------------------------------------------------- check 3

def test_slippage_counts_each_filled_autopilot_order_once():
    o = {"id": "o1", "book": "ap_1", "filledQty": 1.0, "realisedSlippageBps": 4.0, "marketId": "crypto:BTC/USD",
         "strategyId": "lab:tsmom_top20", "ts": 1}
    orders = [o, dict(o), dict(o, id="o2", realisedSlippageBps=30.0, ts=2),
              dict(o, id="o3", book=None), dict(o, id="o4", filledQty=0.0), dict(o, id="o5", realisedSlippageBps=None)]
    s = fa.slippage(orders)
    assert s["overall"]["fills"] == 2 and s["overall"]["median_bps"] == pytest.approx(17.0)
    assert s["pass"] is False and s["raise_cost"] is False
    assert s["per_coin"][0]["market"] == "crypto:BTC/USD"


# ---------------------------------------------------------------- the fixes

def _panel() -> fc.Panel:
    """Three coins over 100 days; coin A doubles from day 70 on."""
    T, names = 100, ["AUSDT", "BTCUSDT", "CUSDT"]
    N = len(names)
    px = np.full((T, N), 100.0)
    px[70:, 0] = np.linspace(100, 200, T - 70)
    ret = np.full((T, N), np.nan)
    ret[1:] = px[1:] / px[:-1] - 1
    ones = np.ones((T, N), dtype=bool)
    days = START + np.arange(T, dtype=np.int64) * DAY_US
    return fc.Panel(days, names, [fc.base_of(n) for n in names], px.copy(), px, px, px, ret, ones, ones.copy(),
                    np.tile(np.arange(T)[:, None], (1, N)), np.full((T, N), 1e8), np.full((T, N), 0.03), ones.copy(),
                    np.zeros((T, N), dtype=bool), np.zeros((T, N)), np.ones(T, dtype=bool), 1)


def test_a_new_breakout_book_starts_with_the_weights_the_backtest_holds_not_its_entry_weights(tmp_path, monkeypatch):
    monkeypatch.setattr(families, "ROOT", tmp_path)
    P = _panel()
    W = np.full((P.T, P.N), np.nan)
    W[:70] = 0.0
    W[70, 0] = 0.05                               # A entered at 5 % of the book on day 70, held since ("leave it")
    t = P.T - 1
    held = families.backtest_weights(P, W, t)
    assert held[0] > 0.09, "A doubled, so the backtest holds about twice its entry weight"
    quotes = {"AUSDT": (199.9, 200.1)}
    row = families.step("breakout_test", W[t], P, t, quotes, int(P.days[t]) + 4 * 3600 * 10**6, held)
    assert json.loads(row["weights"])["A"] == pytest.approx(round(float(held[0]), 4))
    assert abs(json.loads(row["weights"])["A"] - 0.05) > 0.03, "not the entry weight"


def test_a_frozen_record_counts_from_the_first_run_after_its_cut(tmp_path, monkeypatch):
    monkeypatch.setattr(report, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(fr, "FROZEN", {"bk": ("2026-10-03", "a test freeze")})
    journal = [{"date": f"2026-10-{d:02d}", "equity": str(e), "turnover": "0.1", "paper_cost_bps": "1",
                "model_cost_bps": "1"} for d, e in ((1, 9990), (2, 9000), (3, 8000), (4, 8080), (5, 8160))]
    row = fr.book_row("bk", journal)
    assert row["frozen"]["through"] == "2026-10-03" and row["frozen"]["frozen_days"] == 3
    assert row["since"] == "2026-10-04" and row["days"] == 2 and row["elapsed_days"] == 2.0
    assert row["return_pct"] == pytest.approx(2.0), "measured from the equity at the cut, not from $10,000"
    assert row["max_dd_pct"] == pytest.approx(0.0), "the dips before the cut are not this record's"
    assert row["sentence"].startswith("Fresh record since 2026-10-03")
    only_frozen = fr.book_row("bk", journal[:3])
    assert only_frozen["days"] == 0 and "frozen" in only_frozen["sentence"] and only_frozen["status"] == "early"
    ev = fr.evidence({"generated_ms": 1, "books": [only_frozen], "autopilots": []})
    assert ev["books"]["bk"]["status"] == "early" and ev["books"]["bk"]["frozen"]["why"] == "a test freeze"
    assert fr.book_row("other", journal)["return_pct"] == pytest.approx(-18.4), "other books are untouched"


def test_the_breakout_record_is_frozen_through_the_audit():
    assert fr.FROZEN["breakout_top10"][0] == "2026-10-20"


def test_an_audit_reads_journals_and_lists_what_it_cannot_replay(tmp_path):
    d = tmp_path / "paper" / "pumpfun_migration"
    d.mkdir(parents=True)
    with (d / "journal.csv").open("w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=["date", "equity"])
        wr.writeheader()
        wr.writerows([{"date": "2026-10-15", "equity": "7262.91"}, {"date": "2026-10-20", "equity": "54.55"}])
    res = fa.audit({}, root=tmp_path)
    pf = res["books"]["pumpfun_migration"]
    assert not pf["replayed"] and pf["forward_pct"] == pytest.approx(-99.45, abs=0.01) and pf["days"] == 5
    assert res["books"]["tsmom"] == {"replayed": False, "why": "no journal"}
    md = fa.markdown({**res, "generated": "2026-10-21", "slippage": None})
    assert "pumpfun_migration" in md and "no backtest signal" in md
