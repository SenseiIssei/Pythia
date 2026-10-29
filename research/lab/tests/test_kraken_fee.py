"""Kraken's fee, the lab's one source (lab.exec.kraken_fee, results/kraken_fee_s1_prereg.md): the dry run, S1's
paper books and R10's cost model get the same fee for the same volume; a book's costs follow the fee (the
ladder's era line: tests/test_ladder.py). No network,
no key, no account, no order.

Run from research/lab:  python -m pytest tests/test_kraken_fee.py
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lab.exec import dryrun as D
from lab.exec import kraken_fee as kf
from lab.experiments import smallaccount as s1
from lab.experiments import smallaccount_r10 as r10
from lab.paper import smallaccount as book

LADDER = {"BTC": [(5.0, 1.0), (500.0, 8.0)], "SOL": [(5.0, 0.5), (500.0, 0.5)]}
VOLS = (0.0, 2_499.0, 2_500.0, 30_000.0, 20_000_000.0)


def _csv(tmp_path: Path) -> Path:
    p = tmp_path / "kraken.csv"
    p.write_text("coin,pair,ordermin,costmin,lot_decimals,bid,ask\nBTC,XBT/EUR,0.00006,0.45,8,72000,72000\n"
                 "USDC,USDC/EUR,1,0.45,8,0.86,0.86\n", encoding="utf-8")
    return p


def test_the_schedule_is_the_published_new_account_tier():
    assert kf.kraken_fee() == pytest.approx(0.0080) and kf.kraken_fee(maker=True) == pytest.approx(0.0040)
    assert kf.kraken_fee(stable=True) == pytest.approx(0.0020) and kf.kraken_fee(1e9, stable=True) == pytest.approx(0.0020)
    assert kf.kraken_fee(2_500.0) == pytest.approx(0.0060) and kf.kraken_fee(2_499.0) == pytest.approx(0.0080)
    assert kf.kraken_fee(60_000.0, tiers=[[0, "0.26"], [50_000, "0.24"]]) == pytest.approx(0.0024)
    assert kf.URL in kf.source() and kf.READ in kf.source() and chr(0x2014) not in kf.source()


def test_the_three_callers_get_the_same_fee_for_the_same_volume(tmp_path):
    eur = {"quote": "EUR", "fees": [], "fees_maker": []}
    usd = {**eur, "quote": "USD"}
    path = _csv(tmp_path)
    for vol in VOLS:
        cex, rate = r10.kraken_costs(path, vol)                                       # R10, spread 0
        spot = D.fee_rate(eur, vol)                                                   # the dry run
        assert spot == pytest.approx(kf.kraken_fee(vol)) == pytest.approx(cex["BTC"])
        stable = D.fee_rate(usd, vol) - spot                                          # its FX leg
        v = book.s1_venue({"jupiter": s1.Venue("jupiter", 1.12, ladder=LADDER)}, vol)  # S1's paper books
        assert v.onramp == pytest.approx(stable) == pytest.approx(rate) == pytest.approx(kf.kraken_fee(vol, stable=True))
    assert r10.CEX_TAKER == pytest.approx(D.fee_rate(eur, 0.0))
    assert D.FEE_SCHEDULE is kf.FEE_SCHEDULE and D.FX_FEE == pytest.approx(kf.kraken_fee(stable=True))


def test_a_books_costs_scale_with_the_fee():
    paid = {}
    for fee in (0.002, 0.004, 0.008):
        v = s1.Venue("jupiter", 1.12, ladder=LADDER, onramp=fee)
        st = book.new_state("small50_tsmom1", v, 90.0, 0)
        paid[fee] = st["costs_eur"] - s1.ONRAMP_WITHDRAW_USD / 1.12
        assert st["onramp_fee"] == fee and st["cash"] == pytest.approx(50.0 - st["idle"] - st["costs_eur"])
    assert paid[0.004] == pytest.approx(2 * paid[0.002]) and paid[0.008] == pytest.approx(4 * paid[0.002])
    assert paid[0.002] == pytest.approx(50 * 0.002)
    assert "onramp_fee" not in book.new_state("small40_spy_trend", v, 90.0, 0)       # S2 goes there by a SOL swap


def test_a_book_started_at_the_old_fee_is_restated_once():
    v = s1.Venue("jupiter", 1.12, ladder=LADDER)                                     # S1's 0.40 % as it started
    st = book.new_state("small100_breakout_sol3", v, 90.0, 0)
    st.pop("onramp_fee")                                                             # a state from before the field
    new = book.restate("small100_breakout_sol3", st, 0.002, 86_400_000)
    d = 100.0 * (0.002 - 0.004)
    assert new["cash"] == pytest.approx(st["cash"] - d) and new["costs_eur"] == pytest.approx(st["costs_eur"] + d)
    assert new["restated"] == {"date": "1970-01-02", "eur": pytest.approx(d), "from": 0.004, "to": 0.002}
    again = book.restate("small100_breakout_sol3", new, 0.002, 2 * 86_400_000)
    assert again["cash"] == new["cash"] and again["restated"]["date"] == "1970-01-02"
    s2 = book.new_state("small40_spy_trend", v, 90.0, 0)
    assert book.restate("small40_spy_trend", s2, 0.008, 0) == s2


def test_the_books_report_names_the_fee_and_its_source(tmp_path, monkeypatch):
    monkeypatch.setattr(book.report, "REPORTS", tmp_path)
    v = s1.Venue("jupiter", 1.12, ladder=LADDER, onramp=kf.kraken_fee(stable=True))
    st = book.new_state("small50_tsmom1", v, 90.0, 0)
    data = book.write_report({"small50_tsmom1": st}, 0)
    md = (tmp_path / "smallaccount" / "latest.md").read_text(encoding="utf-8")
    assert "Kraken fee used" in md and "0.20 %" in md and kf.URL in md and kf.READ in md
    assert data["kraken_fee"]["onramp_pct"] == pytest.approx(0.20)
