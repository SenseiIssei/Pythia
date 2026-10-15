"""The listings paper book: off unless the study passed, then buy, hold, sell. No network.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import csv
import json

import pytest

from lab.paper import listings_book as B

T0 = 1_791_000_000_000
RULE = {"entry": "first full hour after the listing", "horizon_days": 7, "cell": "B · first hour after · 7d"}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(B, "ROOT", tmp_path)
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "reports"))
    return tmp_path


def test_off_without_a_passing_study(root):
    assert B.verdict() is None
    assert B.step(now_ms=T0) is None
    (root / "reports" / "listing_effect").mkdir(parents=True)
    (root / "reports" / "listing_effect" / "latest.json").write_text(json.dumps({"passed": False, "rule": None}))
    assert B.step(now_ms=T0) is None
    assert not (root / "paper").exists(), "an off book writes nothing"
    (root / "reports" / "listing_effect" / "latest.json").write_text(json.dumps({"passed": True, "rule": RULE}))
    assert B.verdict() == RULE


def test_buys_holds_and_sells_with_a_cap(root):
    ls = [{"ts_ms": T0 - 60_000, "symbol": f"C{i}/USD", "base": f"C{i}"} for i in range(5)]
    px = {f"C{i}/USD": 10.0 for i in range(5)}
    st = B.step(now_ms=T0, rule=RULE, listings=ls, prices=lambda s: {k: px[k] for k in s if k in px})
    assert len(st["open"]) == 4 and "C4/USD" in st["seen"]
    assert st["cash"] == pytest.approx(10_000 - 4 * 500)
    assert st["equity"] == pytest.approx(10_000 - 4 * 500 * B.COST)
    # Prices double; after 7 days everything is sold.
    px = {k: 20.0 for k in px}
    st = B.step(now_ms=T0 + 3 * B.DAY_MS, rule=RULE, listings=ls, prices=lambda s: {k: px[k] for k in s if k in px})
    assert len(st["open"]) == 4
    st = B.step(now_ms=T0 + 7 * B.DAY_MS, rule=RULE, listings=ls, prices=lambda s: {k: px[k] for k in s if k in px})
    assert st["open"] == []
    gain = 4 * ((500 * (1 - B.COST) / 10) * 20 * (1 - B.COST) - 500)
    assert st["equity"] == pytest.approx(10_000 + gain)
    rows = list(csv.DictReader((root / "paper" / "listings" / "journal.csv").open()))
    assert [r["rebalanced"] for r in rows] == ["True", "False", "True"]
    trades = list(csv.DictReader((root / "paper" / "listings" / "trades.csv").open()))
    assert [t["side"] for t in trades].count("skip") == 1 and [t["side"] for t in trades].count("sell") == 4


def test_waits_for_a_first_trade(root):
    ls = [{"ts_ms": T0, "symbol": "NEW/USD", "base": "NEW"}]
    st = B.step(now_ms=T0, rule=RULE, listings=ls, prices=lambda s: {})
    assert st["open"] == [] and st["seen"] == []
    st = B.step(now_ms=T0 + 600_000, rule=RULE, listings=ls, prices=lambda s: {"NEW/USD": 2.0})
    assert [p["symbol"] for p in st["open"]] == ["NEW/USD"]
    rows = list(csv.DictReader((root / "paper" / "listings" / "journal.csv").open()))
    assert len(rows) == 1 and rows[0]["rebalanced"] == "True"


def test_reads_the_watchers_alpaca_rows(root):
    from lab.ops import listings as L
    ev = [{"event": "listed", "venue": "alpaca", "symbol": "NEW/USD", "base": "NEW", "quote": "USD", "status": "",
           "new_base": True},
          {"event": "listed", "venue": "alpaca", "symbol": "ETH/USDT", "base": "ETH", "quote": "USDT", "status": "",
           "new_base": False},
          {"event": "seed", "venue": "alpaca", "symbol": "BTC/USD", "base": "BTC", "quote": "USD", "status": "",
           "new_base": False}]
    L.write_lake(ev, T0, root / "listings" / "first_seen")
    assert B.alpaca_listings(T0) == [{"ts_ms": T0, "symbol": "NEW/USD", "base": "NEW"}]
    assert B.alpaca_listings(T0 + 1) == []
