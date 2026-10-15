"""Experimental lab books: the labels, the evidence read from the studies, the memecoin
signals, the 4h pullback book's fills and exits. No network: klines are synthetic.

Run from research/lab:  python -m pytest tests/test_experiments.py
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl
import pytest

from lab.experiments import memecoins as w7
from lab.paper import experimental as ex
from lab.paper import memes, trend4h as t4

DAY_US = 86_400_000_000


# ---------------------------------------------------------------- labels and evidence

def test_every_experiment_is_labelled_and_reads_its_study():
    for name in ex.BOOKS:
        assert ex.BOOKS[name]["variant"].startswith(ex.LABEL), name
        ev = ex.evidence(name)
        assert ev["experimental"] is True and ev["experiment"] == ex.LABEL
        assert not ev.get("missing"), f"{name}: study write-up not found"
        assert ev["verdict"].startswith("experiment, fails")
        assert ev["deflated_p"] <= 0.95, "an experiment is one that failed deflation"
        assert ev["why_failed"] and ev["would_change"]


def test_evidence_numbers_are_the_studies():
    rot = ex.evidence("memes_rotation")
    assert rot["oos_sharpe"] == pytest.approx(1.15)
    assert rot["sharpe_2x_cost"] == pytest.approx(0.94)
    assert rot["oos_max_dd"] == pytest.approx(0.27)
    assert rot["oos_sharpe_survivorship_free"] == pytest.approx(1.11)
    assert rot["late_fill_sharpe"] == pytest.approx(1.06)
    assert rot["variants_tried"] == 427
    ts = ex.evidence("memes_tsmom")
    assert ts["oos_sharpe"] == pytest.approx(0.67) and ts["deflated_p"] == pytest.approx(0.0)
    tr = ex.evidence("trend4h_pullback")
    assert tr["oos_sharpe"] == pytest.approx(0.71)
    assert tr["sharpe_2x_cost"] == pytest.approx(0.51)
    assert tr["oos_sharpe_survivorship_free"] == pytest.approx(0.40)
    assert tr["variants_tried"] == 841
    # The engine reads these as numbers: nothing it parses may be null.
    for ev in (rot, ts, tr):
        for k in ("oos_sharpe", "deflated_p", "sharpe_2x_cost", "oos_max_dd", "variants_tried"):
            assert isinstance(ev[k], (int, float)), k


def test_mark_makes_a_signal_experimental_and_autopilot_only():
    sig = ex.mark({"strategy": "memes_rotation", "autopilot_only": False}, "memes_rotation")
    assert sig["experimental"] is True and sig["autopilot_only"] is True
    assert sig["experiment"]["label"] == ex.LABEL
    assert ex.is_experimental("memes_tsmom") and ex.is_experimental("trend4h_pullback@x")
    assert not ex.is_experimental("breakout_top10")


# ---------------------------------------------------------------- memecoin books

def _frames(T: int = 420, seed: int = 1) -> dict[str, pl.DataFrame]:
    rng = np.random.default_rng(seed)
    day0 = 1_700_000_000_000_000 // DAY_US * DAY_US
    out = {}
    for k, s in enumerate(memes.SYMBOLS):
        drift = {"BTCUSDT": 0.004, "PEPEUSDT": 0.01}.get(s, -0.001)
        r = drift + 0.01 * rng.standard_normal(T)
        close = 1.0 * np.exp(np.cumsum(r))
        out[s] = pl.DataFrame({"day": [day0 + i * DAY_US for i in range(T)], "open": close, "high": close * 1.01,
                               "low": close * 0.99, "close": close, "volume": np.full(T, 1e9),
                               "qv": np.full(T, 5e7), "n": np.full(T, 1000, dtype=np.int64),
                               "taker_qv": np.full(T, 2e7)})
    return out


def test_memes_signals_are_w7s_rules_marked_experimental():
    P = w7.build_panel(_frames())
    W = memes.targets(P)
    t = P.T - 1
    assert P.btc_on[t], "BTC trends up in the fixture"
    rot = memes.signal("memes_rotation", P, W["memes_rotation"], t, 1, coins=frozenset(w7.ALPACA_MEMES))
    assert rot["experimental"] and rot["autopilot_only"]
    assert rot["variant"].startswith(ex.LABEL)
    assert len(rot["weights"]) <= 1, "top 1 rotation holds one coin at most"
    assert rot["weights"] == {"PEPE": pytest.approx(float(W["memes_rotation"][t, P.col("PEPEUSDT")]), abs=1e-6)}
    tsm = memes.signal("memes_tsmom", P, W["memes_tsmom"], t, 1, coins=frozenset(w7.ALPACA_MEMES))
    assert tsm["weights"] and all(0 < x <= 1 / 6 + 1e-6 for x in tsm["weights"].values()), "6 slots, 1/6 each at most"
    assert "BTC" not in tsm["weights"], "BTC is the gate, never a holding"


def test_memes_signal_keeps_untradable_coins_in_cash():
    P = w7.build_panel(_frames())
    W = memes.targets(P)
    t = P.T - 1
    sig = memes.signal("memes_rotation", P, W["memes_rotation"], t, 1, coins=frozenset({"DOGE"}))
    assert sig["weights"] == {} and sig["dropped"] == ["PEPE"] and sig["dropped_weight"] > 0


def test_memes_gate_off_holds_nothing():
    fr = _frames()
    T = fr["BTCUSDT"].height
    crash = np.exp(np.cumsum(np.full(T, -0.005)))
    fr["BTCUSDT"] = fr["BTCUSDT"].with_columns(close=pl.Series(crash), high=pl.Series(crash), low=pl.Series(crash))
    P = w7.build_panel(fr)
    W = memes.targets(P)
    assert not P.btc_on[P.T - 1]
    assert float(np.nan_to_num(W["memes_rotation"][-1]).sum()) == 0.0
    assert float(np.nan_to_num(W["memes_tsmom"][-1]).sum()) == 0.0


# ---------------------------------------------------------------- the 4h pullback book

H = t4.HOUR_MS
NOW0 = 1_792_080_000_000                    # a 4h close (16:00 UTC)


def _kl(open_ms: np.ndarray, close: np.ndarray, iv_ms: int, low=None, high=None, qv=1e7) -> list:
    low = close * 0.999 if low is None else low
    high = close * 1.001 if high is None else high
    return [[int(o), "0", str(h), str(lo), str(c), "0", int(o + iv_ms - 1), str(qv), 10, "0", "0", "0"]
            for o, c, lo, h in zip(open_ms, close, low, high)]


class Market:
    """Synthetic Binance klines for BTC and one coin, editable per hour."""

    def __init__(self, trend: float = 0.0005, now: int = NOW0 + 7 * 60_000):
        self.now = now
        n = 4000                                                        # 1000 4h bars; 1h serves the last 1000
        self.h_open = NOW0 + 4 * H - np.arange(n, 0, -1) * H            # hours up to 4h ahead of NOW0
        noise = 0.004 * np.sin(np.arange(n) * 0.7)
        self.h_close = 100 * np.exp(np.cumsum(trend + noise))
        self.h_low = self.h_close * 0.999
        self.h_high = self.h_close * 1.001
        # BTC's own hourly series falls (its trend is off); its daily closes still clear the 200-day gate.
        self.b_close = 100 * np.exp(np.cumsum(-trend + noise))

    def get(self, url: str):
        sym = url.split("symbol=")[1].split("&")[0]
        iv = url.split("interval=")[1].split("&")[0]
        if sym not in ("BTCUSDT", "SOLUSDT"):
            import urllib.error
            raise urllib.error.HTTPError(url, 400, "Invalid symbol", None, None)
        close = self.h_close if sym == "SOLUSDT" else self.b_close
        if iv == "1h":
            if sym == "SOLUSDT":
                return _kl(self.h_open[-1000:], self.h_close[-1000:], H, self.h_low[-1000:], self.h_high[-1000:])
            return _kl(self.h_open[-1000:], close[-1000:], H)
        if iv == "4h":
            o = self.h_open[3::4] - 3 * H
            return _kl(o, close[3::4], 4 * H)
        d_open = (NOW0 // 86_400_000) * 86_400_000 - np.arange(260, 0, -1) * 86_400_000
        return _kl(d_open, np.linspace(50, 100, 260), 86_400_000)


def test_through_share_and_target():
    assert t4.through_share(0.00005) == 0.0, "touching is not filling"
    assert t4.through_share(0.0005) == pytest.approx(0.5)
    assert t4.through_share(0.01) == 1.0
    assert t4.target_of(0.01) == pytest.approx(min(0.4 / (0.01 * math.sqrt(8760)), 1) / 10)
    assert t4.target_of(float("nan")) == 0.0


def test_entry_rests_one_hour_and_fills_only_through_the_limit():
    m = Market()
    st, sig, trades, words = t4.run(m.get, m.now)
    assert any(w.startswith("bid SOL") for w in words), words
    o = st["pending"]["SOL"]
    assert o["window_ms"] == NOW0 and o["limit"] < float(m.h_close[np.flatnonzero(m.h_open == NOW0 - H)[0]])
    assert sig["experimental"] and sig["autopilot_only"] and sig["weights"] == {}
    # The hour after the close trades 20 bps through the limit: filled in full, at the limit.
    i = int(np.flatnonzero(m.h_open == NOW0)[0])
    m.h_low[i] = o["limit"] * (1 - 0.002)
    st, sig, trades, _ = t4.run(m.get, NOW0 + H + 7 * 60_000, st)
    assert "SOL" in st["positions"] and st["positions"]["SOL"]["share"] == pytest.approx(1.0)
    buy = [t for t in trades if t["side"] == "buy"][0]
    assert buy["price"] == pytest.approx(o["limit"]) and buy["kind"] == "maker"
    assert buy["cost_usd"] == pytest.approx(o["usd"] * (t4.MAKER_FEE + t4.HAIRCUT))
    assert set(sig["weights"]) == {"SOL"}
    g = sig["generated_ms"]
    # Unchanged holdings: the signal keeps its generated_ms, so the engine does not trade again.
    st, sig2, _, _ = t4.run(m.get, NOW0 + 2 * H + 7 * 60_000, st)
    assert sig2["generated_ms"] == g and sig2["weights"] == sig["weights"]
    assert sig2["valid_until_ms"] > sig["valid_until_ms"]


def test_a_missed_entry_stays_missed():
    m = Market()
    st, *_ = t4.run(m.get, m.now)
    st, sig, trades, _ = t4.run(m.get, NOW0 + H + 7 * 60_000, st)
    assert "SOL" not in st["positions"] and not st["pending"]
    assert [t["kind"] for t in trades] == ["missed"]


def test_exit_works_maker_then_falls_back_to_taker_after_24h():
    m = Market()
    st = t4.new_state(NOW0)
    st["positions"]["SOL"] = {"qty": 2.0, "entry": 100.0, "entry_ms": NOW0 - 10 * H, "target": 0.05, "share": 1.0}
    st["cash"] -= 200.0
    st["last_decision_ms"] = NOW0 - 4 * H
    feats = {"SOL": {"on": False, "close4": 100, "sig4": 0.01, "sig_h": 0.005, "adv": 1e8, "eligible": True}}
    t4.decide(st, feats, True, NOW0)
    assert "SOL" in st["exits"] and "SOL" not in st["positions"]
    # No hour trades through the re-placed limits for a day: everything goes at taker cost.
    h1 = {"open_ms": NOW0 + np.arange(-2, 30) * H, "close": np.full(32, 90.0), "high": np.full(32, 90.0),
          "low": np.full(32, 89.0), "qv": np.full(32, 1e9)}
    trades: list = []
    t4.process_exits(st, {"SOL": h1}, NOW0 + 26 * H, trades)
    assert not st["exits"]
    assert [t["kind"] for t in trades] == ["fallback"]
    assert trades[0]["cost_usd"] == pytest.approx(2.0 * 90.0 * t4.TAKER)


def test_the_book_never_goes_above_100_percent():
    st = t4.new_state(NOW0)
    feats = {c: {"on": True, "close4": 1.0, "sig4": 0.01, "sig_h": 0.0005, "adv": 1e9 - i, "eligible": True}
             for i, c in enumerate(("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "LTC", "DOT", "BCH", "UNI", "AAVE"))}
    did = t4.decide(st, feats, True, NOW0)
    assert sum(o["target"] for o in st["pending"].values()) <= 1.0 + 1e-9
    assert any("book full" in w for w in did)
    assert t4.decide(t4.new_state(NOW0), feats, False, NOW0) == [], "BTC gate off: no entries"
