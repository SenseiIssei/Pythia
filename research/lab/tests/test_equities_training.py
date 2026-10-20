"""X16: the equity panel with opens, the next-open simulator, exits, capture, EDGAR events.

Synthetic data only; nothing is downloaded. Run from research/lab:
python -m pytest tests/test_equities_training.py
"""

from __future__ import annotations

import io
import json
import math
from datetime import date

import numpy as np
import polars as pl
import pytest

from lab.equities import books as bk
from lab.equities import edgar
from lab.equities import features as fe
from lab.equities import panel as pn
from lab.experiments import equities_training as et


def days(n: int, start: str = "2010-01-04") -> np.ndarray:
    d = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(3 * n, "D"), dtype="datetime64[D]")
    d = d[((d.astype(np.int64) + 3) % 7) < 5]
    return d[:n]


def flat_panel(T: int = 300, N: int = 3) -> pn.Panel:
    """Prices that move only where a test says so; open = previous close."""
    close = np.full((T, N), 100.0)
    return pn.panel_from_arrays(days(T), [f"S{j}" for j in range(N)], close, open_=close.copy(),
                                high=close.copy(), low=close.copy(), dv=np.full((T, N), 1e6))


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

def frames():
    d = days(400)
    rows = []
    for j, s in enumerate(["AAA", "BBB", "DEAD-201101"]):
        n = 400 if j < 2 else 250
        px = 50 * np.cumprod(1 + np.full(n, 0.001 * (j + 1)))
        rows.append(pl.DataFrame({"date": d[:n], "ticker": s, "open": px * 0.99, "high": px * 1.01, "low": px * 0.98,
                                  "close": px, "volume": 1e5, "adj_close": px * (0.5 if s == "AAA" else 1.0)}))
    spy = 100 * np.cumprod(1 + np.full(400, 0.0005))
    for s in ("SPY", "XLK", "XLE"):
        rows.append(pl.DataFrame({"date": d, "ticker": s, "open": spy, "high": spy, "low": spy, "close": spy,
                                  "volume": 1e7, "adj_close": spy}))
    prices = pl.concat(rows).with_columns(pl.col("date").cast(pl.Datetime("us")))
    mem = pl.DataFrame([{"ticker": "AAA", "start": date(2010, 1, 1), "end": None},
                        {"ticker": "BBB", "start": date(2010, 6, 1), "end": None},
                        {"ticker": "DEAD-201101", "start": date(2010, 1, 1), "end": date(2010, 12, 1)}],
                       schema={"ticker": pl.Utf8, "start": pl.Date, "end": pl.Date})
    return prices, mem


def test_panel_adjusts_opens_by_the_days_factor_and_marks_membership():
    S, E = pn.build(*frames(), start=np.datetime64("2010-01-01"))
    a = S.col("AAA")
    # adj_close = 0.5 x close: S.close is that, and the open (0.99 x the raw close) gets the same factor
    assert np.allclose(S.open[:, a], 0.99 * S.close[:, a], equal_nan=True)
    assert np.allclose(S.dv[:, a], 2 * S.close[:, a] * 1e5, equal_nan=True)
    b = S.col("BBB")
    assert not S.member[0, b] and S.member[-1, b]
    dead = S.col("DEAD-201101")
    assert S.alive[249, dead] and not S.alive[250, dead]
    assert E.names == ["SPY", "XLE", "XLK"] or set(E.names) == {"SPY", "XLE", "XLK"}


def test_a_dead_name_is_closed_at_its_last_close():
    S, _ = pn.build(*frames(), start=np.datetime64("2010-01-01"))
    j = S.col("DEAD-201101")
    F = S.fill()
    assert F[250, j] == pytest.approx(S.close[249, j])
    assert F[260, j] == pytest.approx(S.close[249, j])
    assert S.r_oo()[251:, j].max() == 0.0


# ---------------------------------------------------------------------------
# Simulator
# ---------------------------------------------------------------------------

def test_event_book_fills_at_the_next_open_and_holds_H_days():
    P = flat_panel()
    t = 260
    # The name jumps 10 % overnight into t+2 and 10 % more overnight into t+5.
    P.open[t + 2:, 0] = 110.0
    P.close[t + 2:, 0] = 110.0
    P.open[t + 5:, 0] = 121.0
    P.close[t + 5:, 0] = 121.0
    P.extra.clear()
    sig = np.zeros((P.T, P.N), dtype=bool)
    sig[t, 0] = True
    run = bk.simulate(P, sig=sig, strength=np.ones((P.T, P.N)), K=20, exit=bk.Exit("time", H=3))
    # bought at the open of t+1 (100), held 3 days, sold at the open of t+4 (110): +10 % on 5 % of the book
    assert run.trades[0]["entry"] == t + 1 and run.trades[0]["exit"] == t + 4
    assert np.prod(1 + run.gross) - 1 == pytest.approx(0.05 * 0.10, rel=1e-9)
    assert run.turnover[t + 1] == pytest.approx(0.05) and run.sells[t + 4] == pytest.approx(0.05 * 1.1 / (1 + 0.005))
    # a day late: bought at the open of t+2 (110), sold at t+5 (121)
    late = bk.simulate(P, sig=sig, strength=np.ones((P.T, P.N)), K=20, exit=bk.Exit("time", H=3), lag=2)
    assert late.trades[0]["entry"] == t + 2 and late.trades[0]["exit_px"] == pytest.approx(121.0)


def test_decisions_do_not_see_the_future():
    rng = np.random.default_rng(1)
    T, N = 400, 30
    close = 100 * np.cumprod(1 + rng.normal(0, 0.02, (T, N)), axis=0)
    opn = close * (1 + rng.normal(0, 0.005, (T, N)))
    dv = rng.lognormal(14, 0.6, (T, N))
    P1 = pn.panel_from_arrays(days(T), [f"S{j}" for j in range(N)], close, opn, close * 1.01, close * 0.99, dv)
    close2, opn2, dv2 = close.copy(), opn.copy(), dv.copy()
    cut = 350
    close2[cut + 1:] *= 3.0
    opn2[cut + 1:] *= 3.0
    dv2[cut + 1:] *= 5.0
    P2 = pn.panel_from_arrays(days(T), [f"S{j}" for j in range(N)], close2, opn2, close2 * 1.01, close2 * 0.99, dv2)
    for P in (P1, P2):
        P.member[:] = P.alive
    X1, X2 = bk.inputs(P1), bk.inputs(P2)
    s1, _ = bk.breakout(P1, X1, 20, 1.2)
    s2, _ = bk.breakout(P2, X2, 20, 1.2)
    assert (s1[:cut + 1] == s2[:cut + 1]).all()
    r1 = bk.simulate(P1, sig=s1, strength=np.ones((T, N)), K=5, exit=bk.Exit("atr", k=2, cap=20), record=True)
    r2 = bk.simulate(P2, sig=s2, strength=np.ones((T, N)), K=5, exit=bk.Exit("atr", k=2, cap=20), record=True)
    # everything decided up to the cut (filled up to the next open) is the same in both worlds
    e1 = sorted({(j, e) for t, j, e, _, _ in r1.held if e <= cut + 1})
    e2 = sorted({(j, e) for t, j, e, _, _ in r2.held if e <= cut + 1})
    assert e1 == e2 and len(e1) > 10
    x1 = sorted((x["j"], x["exit"]) for x in r1.trades if x["exit"] <= cut + 1)
    x2 = sorted((x["j"], x["exit"]) for x in r2.trades if x["exit"] <= cut + 1)
    assert x1 == x2
    assert np.allclose(r1.gross[:cut], r2.gross[:cut])


def test_slots_rank_by_strength_and_never_rebuy_a_held_name():
    P = flat_panel(N=4)
    sig = np.zeros((P.T, P.N), dtype=bool)
    sig[260, :] = True
    sig[261, 0] = True
    strength = np.tile(np.array([1.0, 4.0, 3.0, 2.0]), (P.T, 1))
    run = bk.simulate(P, sig=sig, strength=strength, K=2, exit=bk.Exit("time", H=10))
    entered = sorted((x["entry"], x["j"]) for x in run.trades)
    assert entered == [(261, 1), (261, 2)]


def test_atr_trail_and_target_exits():
    P = flat_panel(N=1)
    t = 260
    P.close[t + 1:t + 4, 0] = [105, 110, 100]
    P.open[t + 1:t + 4, 0] = [100, 105, 110]
    P.close[t + 4:, 0] = 100
    P.open[t + 4:, 0] = 100
    P.high[:] = P.close + 1
    P.low[:] = P.close - 1
    P.extra.clear()
    sig = np.zeros((P.T, P.N), dtype=bool)
    sig[t, 0] = True
    r = bk.simulate(P, sig=sig, strength=np.ones((P.T, 1)), K=1, exit=bk.Exit("atr", k=2, cap=50))
    # peak 110 at t+2, ATR(14) small, the close of t+3 (100) is far below: sold at the open of t+4
    assert r.trades[0]["exit"] == t + 4
    r = bk.simulate(P, sig=sig, strength=np.ones((P.T, 1)), K=1, exit=bk.Exit("target", m=1, H=30))
    # 63-day vol is 0 on a flat history, so any close above the entry is the target: the close of t+1
    assert r.trades[0]["exit"] == t + 2


def test_model_exit_reads_the_forecast_function():
    P = flat_panel(N=1)
    t = 260
    sig = np.zeros((P.T, P.N), dtype=bool)
    sig[t, 0] = True
    calls = []

    def fn(tt, js, entries, pxs, peaks):
        calls.append(tt)
        return np.full(len(js), -0.01 if tt >= t + 5 else 0.01)

    r = bk.simulate(P, sig=sig, strength=np.ones((P.T, 1)), K=1,
                    exit=bk.Exit("model", cap=40, thr=-0.001, model_fn=fn))
    assert r.trades[0]["exit"] == t + 6 and min(calls) == t + 1


def test_rebalanced_book_holds_equal_weights_and_atr_leaves_cash_until_the_next_rebalance():
    P = flat_panel(N=4)
    tg = {259: np.array([0, 1]), 279: np.array([0, 1])}
    r = bk.simulate(P, targets=tg)
    assert r.expo[260] == pytest.approx(1.0) and r.turnover[260] == pytest.approx(1.0)
    assert r.turnover[280] == pytest.approx(0.0)
    P.close[265:, 0] = 80.0
    P.open[266:, 0] = 80.0
    P.extra.clear()
    r = bk.simulate(P, targets=tg, exit=bk.Exit("atr", k=2))
    assert r.expo[266] == pytest.approx(0.5 / (0.5 * 0.8 + 0.5) * 1.0, rel=1e-6) or r.expo[266] < 1.0
    assert r.expo[280] == pytest.approx(1.0)


def test_costs_and_sec_fee():
    run = bk.Run(np.array([0.01, 0.0]), np.array([1.0, 0.5]), np.array([0.0, 0.5]), np.zeros(2))
    n = run.net(5)
    assert n[0] == pytest.approx(0.01 - 0.0005) and n[1] == pytest.approx(-0.00025 - 0.5 * bk.SEC_FEE)


def test_capture_ratio():
    P = flat_panel(N=1)
    P.close[261:264, 0] = [110, 120, 105]
    P.extra.clear()
    run = bk.Run(np.zeros(P.T), np.zeros(P.T), np.zeros(P.T), np.zeros(P.T),
                 trades=[{"j": 0, "entry": 261, "exit": 264, "entry_px": 100.0, "exit_px": 105.0, "peak": 120.0}])
    c = bk.capture(run, P)
    assert c["trades"] == 1 and c["mfe_q"][1] == pytest.approx(0.20) and c["capture_q"][1] == pytest.approx(0.25)


def test_month_ends_and_sector_blend():
    d = days(300)
    me = bk.month_ends(d)
    assert me.sum() >= 13 and not me[-1]
    assert all(d[i].astype("datetime64[M]") != d[i + 1].astype("datetime64[M]") for i in np.flatnonzero(me))


def test_pead_window_and_z():
    P = flat_panel(T=300, N=2)
    rng = np.random.default_rng(3)
    P.close[:, :] = 100 * np.cumprod(1 + rng.normal(0, 0.01, (300, 2)), axis=0)
    P.open[:, :] = P.close
    P.close[201:, 0] *= 1.08          # an 8 % jump on the first window day
    P.open[201:, 0] *= 1.08
    E = pn.panel_from_arrays(P.dates, ["SPY"], np.full((300, 1), 100.0), np.full((300, 1), 100.0))
    P.extra.clear()
    start = np.zeros((P.T, P.N), dtype=bool)
    start[201, 0] = True
    pd = bk.pead_inputs(P, E, bk.inputs(P), start, np.array([True, False]))
    assert np.isfinite(pd.z[202, 0]) and pd.z[202, 0] > 2 and np.isnan(pd.z[201, 0])


# ---------------------------------------------------------------------------
# EDGAR
# ---------------------------------------------------------------------------

def test_earnings_events_from_filings():
    fl = [{"form": "8-K", "filingDate": "2010-01-25", "items": "2.02,9.01"},
          {"form": "10-Q", "filingDate": "2010-02-05", "items": ""},       # covered by the 8-K
          {"form": "8-K", "filingDate": "2010-03-01", "items": "5.02"},    # not earnings
          {"form": "10-Q", "filingDate": "2010-05-10", "items": ""},       # no 8-K before: an event
          {"form": "8-K", "filingDate": "2003-07-20", "items": "12"},      # item 12 before 2004-08-23
          {"form": "8-K", "filingDate": "2006-07-20", "items": "12"}]      # item 12 after: not earnings
    ev = edgar.earnings_events(fl)
    assert ev == [("2003-07-20", "8-K"), ("2010-01-25", "8-K"), ("2010-05-10", "10-Q")]


def test_cik_mapping_follows_renames_and_never_matches_a_suffixed_ticker():
    tick = {"COR": 1, "BRK-B": 2, "AAL": 3}
    ren = {"ABC": "COR"}
    assert edgar.cik_for("ABC", tick, ren) == 1
    assert edgar.cik_for("BRK.B", tick, ren) == 2
    assert edgar.cik_for("AAL-199702", tick, ren) is None


def test_client_is_polite_and_retries():
    sleeps = []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    calls = []

    def opener(req, timeout):
        calls.append(req.get_header("User-agent"))
        if len(calls) == 1:
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 429, "slow down", {}, None)
        return Resp(b'{"ok": 1}')

    c = edgar.Client(ua="Test lab test@example.com", opener=opener, sleep=sleeps.append)
    assert json.loads(c.get("https://data.sec.gov/x")) == {"ok": 1}
    assert calls[0] == "Test lab test@example.com" and len(calls) == 2 and any(s >= 2 for s in sleeps)


# ---------------------------------------------------------------------------
# Study plumbing
# ---------------------------------------------------------------------------

def test_grid_counts_match_the_preregistration():
    g = et.grid_a()
    assert len(g) == 52
    assert sum(v["fam"] == "A1" for v in g) == 16 and sum(v["fam"] == "A5" for v in g) == 16
    assert len({v["label"] for v in g}) == 52
    assert sum(et.TRIALS.values()) + et.B2_TRIALS == 120


def test_holm():
    assert et.holm({"a": 0.01, "b": 0.02, "c": 0.04}) == {"a": True, "b": True, "c": True}
    assert et.holm({"a": 0.01, "b": 0.03, "c": 0.5}) == {"a": True, "b": False, "c": False}


def test_fold_lookup_never_uses_a_later_model():
    folds = [(100, 199, {"id": 1}), (200, 299, {"id": 2})]
    assert fe.fold_for(folds, 50) is None
    assert fe.fold_for(folds, 150)["id"] == 1 and fe.fold_for(folds, 250)["id"] == 2


def test_importance_stability():
    imps = [{"a": 3.0, "b": 2.0, "c": 1.0}, {"a": 3.0, "b": 2.5, "c": 1.0}, {"a": 1.0, "b": 2.0, "c": 3.0}]
    s = fe.importance_stability(imps)
    assert s["fits"] == 3 and s["mean"] == pytest.approx(0.0) and s["min"] == pytest.approx(-1.0)


# ---------------------------------------------------------------------------
# B2: spells and cuts on the crypto books
# ---------------------------------------------------------------------------

class _P:
    """The few crypto panel fields the exit helpers read."""

    def __init__(self, px: np.ndarray):
        T, N = px.shape
        self.px = px
        self.high = px * 1.01
        self.low = px * 0.99
        self.traded = np.ones((T, N), dtype=bool)
        self.alive = np.ones((T, N), dtype=bool)
        self.sigma = np.full((T, N), 0.02)
        self.days = np.arange(T, dtype=np.int64) * 86_400_000_000
        self.names = [f"C{j}USDT" for j in range(N)]
        self.btc = 0
        self.btc_on = np.ones(T, dtype=bool)
        self.extra = {"rv": np.full((T, N), 0.0004), "qv": np.full((T, N), 1e6)}

    @property
    def T(self):
        return self.px.shape[0]

    @property
    def N(self):
        return self.px.shape[1]


def test_spells_track_entry_and_peak_and_cuts_last_to_the_spell_end():
    from lab.experiments import exit_overlays as xo
    px = np.array([[100.0], [110.0], [120.0], [90.0], [95.0], [100.0], [105.0], [110.0]])
    held = np.array([[0.0], [0.1], [0.1], [0.1], [0.1], [0.0], [0.1], [0.1]])
    P = _P(px)
    sp = xo.spells(P, held)
    assert list(sp["start"][:, 0]) == [-1, 1, 1, 1, 1, -1, 6, 6]
    assert sp["entry"][3, 0] == 110.0 and sp["peak"][3, 0] == 120.0 and sp["peak"][6, 0] == 105.0
    fire = np.zeros((8, 1), dtype=bool)
    fire[3, 0] = True
    cut = xo.cut_from(fire, sp)
    assert list(cut[:, 0]) == [False, False, False, True, True, False, False, False]
    late = xo.cut_from(fire, sp, late=True)
    assert list(late[:, 0]) == [False, False, False, False, True, False, False, False]
    t20 = xo.fires(P, sp, "time", 2)
    assert list(t20[:, 0]) == [False, False, False, True, True, False, False, False]


def test_crypto_capture_counts_spells_from_close_to_close():
    from lab.experiments import exit_overlays as xo
    px = np.array([[100.0], [110.0], [120.0], [90.0], [95.0], [100.0]])
    held = np.array([[0.1], [0.1], [0.1], [0.0], [0.0], [0.0]])
    c = xo.capture(_P(px), held, np.ones(6, dtype=bool))
    # bought at the close of day 0 (100), sold at the close of day 3 (90); MFE 20 %
    assert c["trades"] == 1 and c["realised_q"][1] == pytest.approx(-0.10) and c["mfe_q"][1] == pytest.approx(0.20)


def test_failed_models_are_zoo_records_with_a_use_rule():
    from lab.models import zoo
    codes = {s.code: s for s in zoo.record_specs()}
    assert set(codes) == {"M13", "M14", "M15"}
    assert all(s.managed_by == "retired" and s.every_days == 0 and s.use_rule for s in codes.values())
    assert not set(zoo.RECORDS) & set(zoo.ZOO_MODULES)
