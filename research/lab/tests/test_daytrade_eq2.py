"""EQ2 without a data folder: the cost model, a fill one bar late (and the next bar), the stop and the forced 15:55
sale, the pattern day trader counter of the margin account, settled cash only in the cash account, the lockbox cut
at load, the opening range rule on relative volume, the classifier's features read nothing after their bar, the leak
harness passes the classifier's whole path and catches a planted leak, and the study end to end with its 16 trials
registered before any validation number.

Run from research/lab:  python -m pytest tests/test_daytrade_eq2.py
"""

from __future__ import annotations

import json

import numpy as np
import polars as pl
import pytest

from lab import leak
from lab.experiments import daytrade_eq2 as eq2
from lab.experiments import intraday_equities as ie

NB = eq2.NB


def bdays(a: str, z: str) -> np.ndarray:
    d = np.arange(np.datetime64(a), np.datetime64(z) + np.timedelta64(1, "D"))
    return d[np.is_busday(d)]


def bars(syms=("SPY", "AAPL", "MSFT", "NVDA"), a="2017-01-02", z="2019-06-28", seed=3) -> ie.Bars:
    """Random-walk 5 minute bars with a little intraday persistence, every session full."""
    rng = np.random.default_rng(seed)
    d = bdays(a, z)
    S, D = len(syms), len(d)
    r = rng.normal(0, 0.002, (S, D, NB))
    r[:, :, 1:] += 0.15 * r[:, :, :-1]
    c = 100 * np.exp(np.cumsum(r.reshape(S, -1), 1)).reshape(S, D, NB)
    o = np.concatenate([c[:, :, :1] / np.exp(r[:, :, :1]), c[:, :, :-1]], 2)
    h, l = np.maximum(o, c) * 1.0005, np.minimum(o, c) * 0.9995
    v = rng.lognormal(10, 0.5, (S, D, NB))
    return ie.Bars(d, list(syms), o, h, l, c, v, (h + l + c) / 3, np.ones(S), "synthetic")


def flat_bars(px=100.0, D=3, syms=("SPY", "AAPL")) -> ie.Bars:
    d = bdays("2024-01-02", "2024-03-01")[:D]
    S = len(syms)
    o = np.full((S, D, NB), px) + np.arange(NB)[None, None, :] * 0.01     # each bar's open distinct
    c = o + 0.005
    return ie.Bars(d, list(syms), o, o + 0.01, o - 0.01, c, np.ones((S, D, NB)), c, np.ones(S), "synthetic")


# ---------------------------------------------------------------- costs and fills

def test_cost_model():
    assert eq2.cost(np.array(100.0), 10) == pytest.approx(5e-4)          # 5 bps above a cent
    assert eq2.cost(np.array(10.0), 10) == pytest.approx(1e-3)           # a cent on 10 USD is 10 bps
    assert eq2.cost(np.array(100.0), 0) == pytest.approx(1e-3)           # doubled in the first three bars
    assert eq2.cost(np.array(100.0), 3) == pytest.approx(5e-4)
    assert eq2.cost(np.array(100.0), 10, 2.0) == pytest.approx(1e-3)     # stress


def test_fill_one_bar_late_and_the_next_bar():
    B = flat_bars()
    sym, ent = np.array([1, -1, 1]), np.array([10, -1, 75])
    late = eq2.trade_returns(B, sym, ent, lag=1)
    nxt = eq2.trade_returns(B, sym, ent, lag=0)
    o = B.o[1, 0]

    def want(fe):
        pe = o[fe] * (1 + eq2.cost(o[fe], fe))
        ps = o[eq2.EXIT_BAR] * (1 - eq2.cost(o[eq2.EXIT_BAR], eq2.EXIT_BAR))
        return (ps * (1 - ie.SEC_FEE) - ie.TAF_PER_SHARE) / pe - 1

    assert late[0] == pytest.approx(want(12))      # decided at bar 10, bought at the open of bar 12
    assert nxt[0] == pytest.approx(want(11))
    assert late[0] < nxt[0]                        # the opens rise, so later is dearer
    assert np.isnan(late[1])                       # no plan, no trade
    assert np.isnan(late[2]) and not np.isnan(nxt[2])  # a buy filled at 15:55 or later is not made


def test_stop_is_checked_from_the_fill_bar_and_exits_late():
    B = flat_bars()
    B.c[1, 0, 11] = 50.0                           # a close below the stop before the fill (bar 12): ignored
    B.c[1, 0, 20] = 50.0                           # the first close below it after the fill
    r = eq2.trade_returns(B, np.array([1, -1, -1]), np.array([10, -1, -1]), np.array([99.0, np.nan, np.nan]), lag=1)
    o = B.o[1, 0]
    pe, ps = o[12] * (1 + eq2.cost(o[12], 12)), o[22] * (1 - eq2.cost(o[22], 22))
    assert r[0] == pytest.approx((ps * (1 - ie.SEC_FEE) - ie.TAF_PER_SHARE) / pe - 1)
    B.c[1, 0, 76] = 50.0
    B.c[1, 0, 20] = B.o[1, 0, 20]
    r2 = eq2.trade_returns(B, np.array([1, -1, -1]), np.array([10, -1, -1]), np.array([99.0, np.nan, np.nan]), lag=1)
    ps2 = o[eq2.EXIT_BAR] * (1 - eq2.cost(o[eq2.EXIT_BAR], eq2.EXIT_BAR))
    assert r2[0] == pytest.approx((ps2 * (1 - ie.SEC_FEE) - ie.TAF_PER_SHARE) / pe - 1)   # a late stop is the 15:55 sale


# ---------------------------------------------------------------- the accounts

def test_pdt_counter_three_day_trades_in_five_sessions():
    w = eq2.Wallet("margin", 100.0)
    took = [w.round_trip(s, 0.0) for s in range(8)]
    # sessions 0, 1, 2 trade; 3 and 4 would be a fourth in five; 5 sees 1, 2 in its five, 7 sees 5, 6
    assert took == [True, True, True, False, False, True, True, True]
    assert w.skipped_pdt == 2
    assert not w.round_trip(8, 0.0)                # 5, 6, 7 in the five sessions to 8
    w2 = eq2.Wallet("margin", 100.0)
    assert [w2.round_trip(0, 0.0) for _ in range(4)] == [True, True, True, False]     # three in one session
    cash = eq2.Wallet("cash", 100.0)
    assert all(cash.round_trip(s, 0.0) for s in range(8))                             # no PDT rule in cash


def test_cash_account_uses_settled_cash_only():
    w = eq2.Wallet("cash", 100.0)
    assert w.round_trip(0, 0.10)
    assert w.equity == pytest.approx(110.0)
    assert w.buying_power(0) == 0.0                # the sale settles the next session
    assert not w.round_trip(0, 0.0) and w.skipped_cash == 1
    assert w.buying_power(1) == pytest.approx(110.0)
    assert w.round_trip(1, -0.5) and w.equity == pytest.approx(55.0)
    m = eq2.Wallet("margin", 100.0)
    assert m.round_trip(0, 0.10) and m.round_trip(0, 0.0)            # margin may use unsettled cash
    assert m.equity == pytest.approx(110.0)


def test_run_book_one_trade_a_session_equity():
    r = np.array([0.1, np.nan, -0.1, 0.0])
    out = eq2.run_book(r, "cash", 50.0)
    assert out["equity"] == pytest.approx([55.0, 55.0, 49.5, 49.5])
    assert len(out["trades"]) == 3
    m = eq2.run_book(np.zeros(6), "margin", 50.0)
    assert m["skipped_pdt"] == 2 and len(m["trades"]) == 4


# ---------------------------------------------------------------- data and rules

def test_load_drops_the_lockbox(tmp_path):
    B0 = bars(("SPY", "AAPL"), "2026-05-01", "2026-08-31")
    for j, s in enumerate(B0.syms):
        for m in np.unique(B0.dates.astype("datetime64[M]")):
            k = np.flatnonzero(B0.dates.astype("datetime64[M]") == m)
            rows = [{"date": B0.dates[d].astype(object), "bar": b, "open": B0.o[j, d, b], "high": B0.h[j, d, b],
                     "low": B0.l[j, d, b], "close": B0.c[j, d, b], "volume": B0.v[j, d, b], "tp": B0.tp[j, d, b]}
                    for d in k for b in range(NB)]
            (tmp_path / s).mkdir(exist_ok=True)
            pl.DataFrame(rows).write_parquet(tmp_path / s / f"{m}.parquet")
    B = eq2.load(tmp_path, syms=("SPY", "AAPL"))
    assert B.dates.max() <= np.datetime64(eq2.VAL_TO) and B.dates.min() == B0.dates.min()
    assert np.allclose(B.c[1, 0], B0.c[1, 0])


def test_orb_picks_the_stock_in_play_and_buys_the_break():
    B = bars(("SPY", "AAPL", "MSFT"), "2024-01-02", "2024-03-29")
    d = B.D - 1
    for j in (1, 2):                               # both ranges close up, MSFT on more relative volume
        B.c[j, d, 0] = B.o[j, d, 0] * 1.002
        B.h[j, d, 0] = B.c[j, d, 0]
    B.v[1, d, 0] *= 4
    B.v[2, d, 0] *= 8
    B.c[2, d, 1:8] = B.l[2, d, 0] + 1e-6           # MSFT does not break until bar 8
    B.c[2, d, 8] = B.h[2, d, 0] * 1.01
    sym, ent, stop = eq2.plan_orb(B, ie.features(B), 5, 3.0)
    assert sym[d] == 2 and ent[d] == 8 and stop[d] == pytest.approx(B.l[2, d, 0])
    assert (sym[: eq2.RVOL_DAYS] == -1).all()      # no relative volume without 14 sessions before
    B.c[0, d, 0] = B.o[0, d, 0] * 1.01
    B.v[0, d, 0] *= 100                            # SPY is never a pick
    assert eq2.plan_orb(B, ie.features(B), 5, 3.0)[0][d] == 2


def test_clf_features_read_nothing_after_their_bar():
    B = bars()
    k, d = 5, 300
    base = eq2.clf_features(B, ie.features(B), k)
    B2 = ie.Bars(B.dates, B.syms, *(getattr(B, a).copy() for a in ("o", "h", "l", "c", "v", "tp")), B.scale)
    for a in ("o", "h", "l", "c", "v", "tp"):
        getattr(B2, a)[:, d, k + 1:] *= 1.5
        getattr(B2, a)[:, d + 1:] *= 0.7
    got = eq2.clf_features(B2, ie.features(B2), k)
    assert np.allclose(base[:, : d + 1], got[:, : d + 1], equal_nan=True)
    assert not np.allclose(base[:, d + 1:], got[:, d + 1:], equal_nan=True)
    assert base.shape[2] == len(eq2.CLF_FEATURES)


def test_clf_walk_forward_trains_only_on_the_past():
    B = bars()
    P = eq2.clf_predict(B, ie.features(B), "logit", 5, "2018-01-01")
    assert np.isnan(P[:, B.dates < np.datetime64("2018-01-01")]).all()
    assert np.isfinite(P[1:, B.dates >= np.datetime64("2018-01-01")]).mean() > 0.9
    assert np.isnan(P[0]).all()                    # SPY is not a row
    sym, ent = eq2.plan_clf(B, P, 5, 0.0)
    assert (ent[sym >= 0] == 5).all() and (sym != 0).all()


@pytest.mark.parametrize("model", ["logit", "gbm"])
def test_leak_harness_passes_the_classifier(model):
    B = bars(("SPY", "AAPL", "MSFT"), "2017-01-02", "2018-12-31")
    P = eq2.flat_panel(B)
    assert np.allclose(eq2.unflat(P).c, B.c)
    T = len(P["days"])
    cuts = [int(np.searchsorted(B.dates, np.datetime64("2018-04-02"))) * NB + 40, T - 3 * NB + 2]
    fn = eq2.clf_flat(model, 5)
    assert np.isfinite(fn(P)[cuts[0] + 1:]).any()     # the models were trained and predict after the first cut
    res = leak.check(fn, P, cuts=cuts, columns=P["syms"])
    assert res["ok"], res


def test_leak_harness_catches_a_planted_leak(monkeypatch):
    B = bars(("SPY", "AAPL", "MSFT"), "2017-01-02", "2018-12-31")
    real = eq2.clf_features

    def leaky(B, F, k):
        X = real(B, F, k)
        X[:, :, 0] = np.log(B.c[:, :, k + 1] / B.o[:, :, 0])     # the next bar's close
        return X

    monkeypatch.setattr(eq2, "clf_features", leaky)
    P = eq2.flat_panel(B)
    t = int(np.searchsorted(B.dates, np.datetime64("2018-06-01"))) * NB + 5
    res = leak.check(eq2.clf_flat("logit", 5), P, cuts=[t], columns=P["syms"])
    assert not res["ok"] and res["first"]["column"] != "(error)"


# ---------------------------------------------------------------- end to end

def test_study_end_to_end_registers_before_validation(tmp_path, monkeypatch):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    B = bars(("SPY", "AAPL", "MSFT"), "2016-01-04", "2026-06-30", seed=5)
    seen = {}
    real_books = eq2.books

    def spy_books(B_, pl_, win, fx):
        if win == "val":
            seen["registered"] = sum("small:eq2:" in x for x in reg.read_text().splitlines())
        return real_books(B_, pl_, win, fx)

    monkeypatch.setattr(eq2, "books", spy_books)
    monkeypatch.setattr(eq2, "LEAK_SYMS", 2)
    monkeypatch.setattr(eq2, "LEAK_TO", "2018-06-29")
    monkeypatch.setattr(eq2, "CLF_GRID", (("logit", 5),))
    monkeypatch.setattr(eq2, "RULES", {k: v for k, v in eq2.RULES.items() if k in ("rvol_orb_m5_r1.5",
                                                                                      "pattern_clf_logit_1000")})
    out = eq2.evaluate(B, log=lambda *_: None)
    assert seen["registered"] == 4                  # every trial in the registry before the validation books
    ids = [json.loads(x)["id"] for x in reg.read_text().splitlines() if "small:eq2:" in x]
    assert ids == ["small:eq2:rvol_orb_m5_r1.5:cash", "small:eq2:rvol_orb_m5_r1.5:margin",
                   "small:eq2:pattern_clf_logit_1000:cash", "small:eq2:pattern_clf_logit_1000:margin"]
    judged = [r for r in out["rows"] if r["account"] == "cash"]
    assert len(judged) == 2 and all("pass" in r for r in judged)
    assert all("pass" not in r for r in out["rows"] if r["account"] == "margin")
    assert "leak harness clean" in judged[1]["conditions"] and out["leaks"]["logit:5"]["ok"]
    assert out["sessions"]["val"][1] <= eq2.VAL_TO
    md = eq2.markdown(out, {"generated": "test"})
    assert "doing nothing" in md and "SPY held" in md and "\u2014" not in md
    s = eq2.summary(out)
    assert len(s["trials"]) == 4 and json.dumps(s, default=float)
