"""The shared harness of delist_hazard, kr_premium_xs and xs_factors on small arrays.

Run from research/lab:  python -m pytest tests/test_crypto_own.py
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from lab.experiments import crypto_own as co
from lab.experiments import delist_hazard as dh


def test_filter_zeroes_flagged_coins_also_where_the_book_holds():
    W = np.array([[0.5, np.nan, 0.2], [0.3, 0.3, np.nan]])
    flag = np.array([[True, True, False], [False, False, True]])
    out = co.filt(W, flag)
    assert out[0, 0] == 0 and out[0, 1] == 0 and out[0, 2] == 0.2
    assert out[1, 2] == 0 and out[1, 0] == 0.3


def test_tilt_moves_weight_to_better_coins_and_keeps_the_sum():
    W = np.array([[0.4, 0.4, np.nan, 0.0]])
    q = np.array([[1.0, 0.25, 0.5, np.nan]])
    out = co.tilt(W, q)
    assert np.isnan(out[0, 2]) and out[0, 3] == 0.0
    assert out[0, 0] + out[0, 1] == pytest.approx(0.8)
    assert out[0, 1] > out[0, 0]
    # m = 0.5 and 1.25: the ratio of the two weights is 2.5
    assert out[0, 1] / out[0, 0] == pytest.approx(2.5)


def test_tilt_leaves_coins_without_a_value_alone_when_alone():
    W = np.array([[0.3, 0.0]])
    q = np.array([[np.nan, 0.9]])
    assert co.tilt(W, q)[0, 0] == pytest.approx(0.3)


def test_late_shifts_one_close():
    f = np.array([[True, False], [False, True], [False, False]])
    assert co.late(f).tolist() == [[False, False], [True, False], [False, True]]
    q = np.array([[0.1], [0.2]])
    lq = co.late(q)
    assert np.isnan(lq[0, 0]) and lq[1, 0] == 0.1


def test_worst_third():
    q = np.array([[0.2, 0.66, 0.7, np.nan, 1.0]])
    assert co.worst_third(q).tolist() == [[False, False, True, False, True]]


def test_sorted_auc_matches_pairs_and_weights_duplicate_rows():
    rng = np.random.default_rng(1)
    s = np.round(rng.normal(size=300), 1)          # ties on purpose
    y = (rng.random(300) < 0.2).astype(int)
    pos, neg = s[y == 1], s[y == 0]
    pairs = ((pos[:, None] > neg[None, :]) + 0.5 * (pos[:, None] == neg[None, :])).mean()
    a = dh.SortedAUC(s, y)
    assert a() == pytest.approx(pairs)
    w = rng.integers(0, 3, 300).astype(float)
    rep = np.repeat(np.arange(300), w.astype(int))
    assert a(w) == pytest.approx(dh.SortedAUC(s[rep], y[rep])())


def test_events_need_a_month_without_a_bar():
    # T = 200 days. A: ends at 100, never again (event). B~0 ends at 50, B restarts at 60 (not an event,
    # a split), B (the last segment) runs to the end. C ends at 180 (too close to the panel end).
    P = SimpleNamespace(T=200, N=4, names=["AUSDT", "BUSDT~0", "BUSDT", "CUSDT"],
                        extra={"last": np.array([100, 50, 199, 180]), "first": np.array([0, 0, 60, 0])})
    assert dh.events(P).tolist() == [True, False, False, False]


def test_fwd_log_return_keeps_a_dead_coins_last_close():
    T = 10
    px = np.full((T, 2), np.nan)
    px[:, 0] = np.arange(1, T + 1, dtype=float)
    px[:5, 1] = [10, 10, 10, 10, 5]
    alive = np.isfinite(px)
    P = SimpleNamespace(T=T, N=2, px=px, alive=alive, extra={"last": np.array([T - 1, 4])})
    f = co.fwd_log_return(P, 3)
    assert f[0, 0] == pytest.approx(np.log(4 / 1))
    assert np.isnan(f[8, 0])                       # alive coin, horizon past the end
    assert f[3, 1] == pytest.approx(np.log(5 / 10))  # dies inside the horizon
    assert np.isnan(f[6, 1])


def test_trial_counts_add_up_to_the_registration():
    assert sum(co.STUDY_TRIALS.values()) == co.REG_TRIALS == 94


# ---------------------------------------------------------------- the tsmom_tranches filter shadow books

DAY_US = 86_400_000_000
COINS = ("BTC", "AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "III", "JJJ", "KKK")


def _panel(T: int = 400):
    import polars as pl
    from lab.experiments import memecoins as w7
    rng = np.random.default_rng(3)
    day0 = 1_700_000_000_000_000 // DAY_US * DAY_US
    frames = {}
    for i, c in enumerate(COINS):
        r = 0.003 + 0.01 * rng.standard_normal(T)
        if c == "AAA":
            r[T - 10] = 0.6                         # one lottery day, ten days ago
        close = np.exp(np.cumsum(r))
        frames[f"{c}USDT"] = pl.DataFrame({"day": [day0 + k * DAY_US for k in range(T)], "open": close,
                                           "high": close * 1.01, "low": close * 0.99, "close": close,
                                           "volume": np.full(T, 1e9), "qv": np.full(T, 5e7 * (i + 1)),
                                           "n": np.full(T, 1000, dtype=np.int64), "taker_qv": np.full(T, 2e7)})
    return w7.build_panel(frames)


def test_lowmax_book_drops_the_lottery_coin_and_its_signal_is_experimental():
    from lab.paper import experimental as ex
    from lab.paper import tranches_filtered as tf
    P = _panel()
    t = P.T - 1
    W, flags = tf.targets(P, "tsmom_tranches_lowmax")
    a = P.names.index("AAAUSDT")
    assert flags[t, a] and W[t, a] == 0.0
    assert flags[t].sum() == 4, "the worst third of twelve coins"
    sig = tf.signal("tsmom_tranches_lowmax", P, W, t, 1)
    assert sig["experimental"] and sig["autopilot_only"] and sig["variant"].startswith(ex.LABEL)
    assert "AAA" not in sig["weights"]
    assert sig["evidence"]["report"] == "xs_factors" and not sig["evidence"].get("missing")


def test_lowkr_book_drops_the_coin_hot_in_korea_and_guards_ticker_clashes(tmp_path, monkeypatch):
    import polars as pl
    from lab.collect import flow
    from lab.experiments import kr_premium_xs as kr
    from lab.paper import tranches_filtered as tf
    monkeypatch.setattr(flow, "FLOW", tmp_path)
    P = _panel()
    fx = 1300.0
    prem = {"BBB": 0.05, "CCC": -0.01, "KKK": 3.0}   # KKK on Upbit is another asset (a ticker clash)
    rows = []
    for c in COINS:
        j = P.names.index(f"{c}USDT")
        for t in range(P.T):
            rows.append({"market": f"KRW-{c}", "day_us": int(P.days[t]),
                         "close": float(P.close[t, j]) * fx * (1 + prem.get(c, 0.0)), "open": 0.0, "high": 0.0,
                         "low": 0.0, "value_krw": 1.0})
    pl.DataFrame(rows).write_parquet(tmp_path / "upbit_krw_1d.parquet")
    pl.DataFrame({"day_us": [int(P.days[0])], "usdkrw": [fx]}).write_parquet(tmp_path / "fx_usdkrw.parquet")
    sig = kr.signal(P)
    assert sig["dropped"] == ["KKKUSDT"]
    t = P.T - 1
    b = P.names.index("BBBUSDT")
    assert sig["s"][t, b] == pytest.approx(np.log(1.05), abs=1e-9)
    W, flags = tf.targets(P, "tsmom_tranches_lowkr")
    assert flags[t, b] and W[t, b] == 0.0
    assert not flags[t, P.names.index("CCCUSDT")]
    assert tf.signal("tsmom_tranches_lowkr", P, W, t, 1)["evidence"]["report"] == "kr_premium_xs"
