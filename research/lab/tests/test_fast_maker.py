"""The maker-only fast study's fill model, accounting and book on synthetic bars. No lab data.

Run from research/lab:  python -m pytest tests/test_fast_maker.py
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from lab.experiments import fast_maker as fm


def coin(close: np.ndarray, spread: float = 0.002, qv: float = 1e9, bar_min: int = 60,
         name: str = "X") -> fm.Coin:
    """A coin on the global grid whose bars are close x (1 +- spread)."""
    n = fm.n_bars(bar_min)
    c = np.full(n, np.nan)
    c[: len(close)] = close
    traded = np.isfinite(c)
    first = int(np.argmax(traded))
    last = int(n - 1 - np.argmax(traded[::-1]))
    hi = (c * (1 + spread)).astype(np.float32)
    lo = (c * (1 - spread)).astype(np.float32)
    q = np.where(traded, qv, 0.0).astype(np.float32)
    return fm.Coin(name, bar_min, hi, lo, traded, q, c, first, last)


def walk(seed: int = 1, n: int | None = None, vol: float = 0.006) -> np.ndarray:
    n = n or fm.n_bars(60)
    rng = np.random.default_rng(seed)
    return 100 * np.exp(np.cumsum(rng.normal(0, vol, n)))


# ---------------------------------------------------------------------------
# The registration
# ---------------------------------------------------------------------------

def test_grid_is_the_registered_44_and_53_trials():
    v = fm.variants()
    assert len(v) == 44
    assert [sum(x.family == f for x in v) for f in "ABCD"] == [12, 16, 8, 8]
    assert len({x.label for x in v}) == 44
    assert fm.TRIALS_HERE == 44 + 4 + 4 + 1
    assert len(fm.SYMBOLS) == 33


def test_twin_leaves_out_stables_fiat_and_leveraged_tokens():
    assert fm.excluded_symbol("USDCUSDT") and fm.excluded_symbol("FDUSDUSDT") and fm.excluded_symbol("EURUSDT")
    assert fm.excluded_symbol("BTCUPUSDT") and fm.excluded_symbol("ETHBULLUSDT")
    assert not fm.excluded_symbol("BTCUSDT") and not fm.excluded_symbol("SUPERUSDT")
    assert not fm.excluded_symbol("LUNAUSDT~0")


# ---------------------------------------------------------------------------
# Fill model
# ---------------------------------------------------------------------------

def bars_coin(lows: list[float], highs: list[float], qv: float = 1e12) -> fm.Coin:
    c = coin(np.full(fm.n_bars(60), 100.0))
    c.low[: len(lows)] = lows
    c.high[: len(highs)] = highs
    c.qv[:] = qv
    return c


def test_buy_limit_needs_a_trade_through_and_fills_by_depth():
    L = 100.0
    # touched only: no fill
    b, s = fm._buy_fill(bars_coin([100.0, 100.0], [101, 101]), L, 0, 2, 1e4)
    assert len(b) == 0
    # 1 bp through fills 10 %, 5 bps 50 % (the largest depth so far), 20 bps all
    c = bars_coin([99.99, 99.95, 99.97, 99.8], [101] * 4)
    b, s = fm._buy_fill(c, L, 0, 4, 1e4)
    assert list(b) == [0, 1, 3]
    assert np.allclose(np.cumsum(s), [0.1, 0.5, 1.0], atol=1e-3)


def test_buy_fill_is_capped_at_ten_percent_of_volume():
    c = bars_coin([99.0, 99.0, 99.0], [101] * 3, qv=1000.0)
    b, s = fm._buy_fill(c, 100.0, 0, 3, usd=1000.0)
    # 10 % of 1000 a bar against a 1000 USD order: 10 % a bar
    assert np.allclose(s, [0.1, 0.1, 0.1], atol=1e-6)


def test_sell_limit_mirrors_the_buy():
    c = bars_coin([99] * 3, [100.0, 100.02, 100.5])
    b, s = fm._sell_fill(c, 100.0, 0, 3, 1e4)
    assert list(b) == [1, 2] and np.allclose(np.cumsum(s), [0.2, 1.0], atol=1e-3)


def test_exit_falls_back_to_taker_after_24_hours():
    n = fm.n_bars(60)
    c = coin(np.full(n, 100.0), spread=0.0)          # highs never trade through the close
    out, orders = fm.exit_maker(c, 10, 1.0, 1e4)
    assert orders == 24
    assert len(out) == 1 and out[0][0] == 10 + 24 and not out[0][3]
    c2 = coin(np.full(n, 100.0), spread=0.01)        # every bar trades 100 bps through
    out, orders = fm.exit_maker(c2, 10, 1.0, 1e4)
    assert orders == 1 and out == [(11, 1.0, 100.0, True)]


def test_exit_at_the_end_of_the_data_sells_at_the_last_close():
    c = coin(np.full(500, 100.0), spread=0.0)
    out, _ = fm.exit_maker(c, 495, 1.0, 1e4)
    assert out[-1][0] == 499 and not out[-1][3]


# ---------------------------------------------------------------------------
# Accounting
# ---------------------------------------------------------------------------

def test_pnl_is_marked_at_each_day_close():
    px = np.full(fm.n_bars(60), 100.0)
    px[23] = 110.0                                    # day 0 closes at 110
    px[24:] = 120.0
    c = coin(px)
    d0, g = fm.pnl_by_day(c, [(5, 0.01, 100.0), (30, -0.01, 120.0)])
    assert d0 == 0 and np.allclose(g, [0.1, 0.1])


def test_book_sizes_off_equity_and_respects_the_100_percent_limit():
    def tr(t, tgt=0.1, share=1.0, gross=0.01):
        x = fm.Trade("X", t, t // 24, 1.0, tgt, t + 1, t + 5, share, t // 24, np.array([gross]), np.array([2.0]),
                     np.array([0.0]))
        return x
    ts = [tr(100) for _ in range(15)]
    b = fm.run_book(ts, {"gross": (0.0, 0.0), "base": (0.0018, 0.0035)})
    assert len(b.taken) == 10 and b.skipped == 5
    d = 100 // 24
    assert b.rets["gross"][d] == pytest.approx(10 * 0.1 * 0.01)
    assert b.rets["base"][d] == pytest.approx(10 * 0.1 * (0.01 - 0.0018 * 2))
    # an order that did not fill frees its target when its window ends
    ts = [tr(100, tgt=0.6, share=0.0), tr(102, tgt=0.6)]
    ts[0].gross = None
    assert len(fm.run_book(ts, {"gross": (0.0, 0.0)}).taken) == 2
    ts = [tr(100, tgt=0.6, share=1.0), tr(102, tgt=0.6)]
    assert len(fm.run_book(ts, {"gross": (0.0, 0.0)}).taken) == 1


def test_splice_rescales_the_older_series():
    old = pl.DataFrame({"open_time_us": [0, 1, 2, 3], "open": [2.0] * 4, "high": [2.0] * 4, "low": [2.0] * 4,
                        "close": [2.0] * 4, "quote_volume": [5.0] * 4})
    new = pl.DataFrame({"open_time_us": [2, 3, 4], "open": [1.0] * 3, "high": [1.0] * 3, "low": [1.0] * 3,
                        "close": [1.0] * 3, "quote_volume": [7.0] * 3})
    s = fm.splice([old, new])
    assert s["open_time_us"].to_list() == [0, 1, 2, 3, 4]
    assert s["close"].to_list() == [1.0] * 5
    assert s["quote_volume"].to_list() == [5.0, 5.0, 7.0, 7.0, 7.0]


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def test_hour_runs_wrap_over_midnight():
    assert fm.hour_runs([23, 0, 5]) == [(5, 1), (23, 2)]
    assert fm.hour_runs([3, 4]) == [(3, 2)]


def test_sigma_on_1h_bars_excludes_the_decision_hour():
    c = coin(walk())
    f = fm.features(c)
    b = np.array([1000, 5000])
    assert np.allclose(fm.sigma_at(c, f, b), f["sig_prev"][b])
    r = f["hr"][1000 - fm.VOL_HOURS:1000]
    assert f["sig_prev"][1000] == pytest.approx(np.sqrt(np.mean(r ** 2)))


def test_weekend_orders_are_decided_at_the_saturday_open():
    c = coin(walk(2), spread=0.004)
    ctx = fm.Ctx(gate_d=np.ones(fm.N_DAYS, dtype=bool), hours=tuple(range(24)))
    v = next(x for x in fm.variants() if x.family == "D" and x.d["kind"] == "weekend" and x.d["N"] == 60)
    trades = fm.simulate_coin(c, v, ctx)
    assert trades
    for t in trades:
        live = date.fromordinal(fm.T0.toordinal() + t.dec_day)
        assert live.weekday() == 5 and (t.t_dec + 1) % 24 == 0
        if t.share > 0:
            assert t.stats["hold_h"] >= 47


def test_one_bar_late_shifts_every_decision():
    c = coin(walk(3), spread=0.004)
    ctx = fm.Ctx(gate_d=np.ones(fm.N_DAYS, dtype=bool), hours=(13, 22))
    v = next(x for x in fm.variants() if x.family == "D" and x.d["kind"] == "hours" and x.d["k"] == 2)
    a = fm.simulate_coin(c, v, ctx)
    b = fm.simulate_coin(c, v, ctx, lag=1)
    assert [t.t_dec + 1 for t in a[:20]] == [t.t_dec for t in b[:20]]


def test_taker_reference_fills_everything_at_the_close():
    c = coin(walk(4), spread=0.004)
    ctx = fm.Ctx(gate_d=np.ones(fm.N_DAYS, dtype=bool), hours=(13, 22))
    v = next(x for x in fm.variants() if x.family == "D" and x.d["kind"] == "hours" and x.d["k"] == 2)
    tk = fm.simulate_coin(c, v, ctx, taker=True)
    assert all(t.share == 1.0 for t in tk)
    t = tk[5]
    held = c.px[t.t_dec + 1] / c.px[t.t_dec] - 1           # hours 13 and 22 are not adjacent: one hour
    assert t.stats["gross_bps"] == pytest.approx(held * 1e4)
    assert t.fb.sum() == pytest.approx(1.0 + (1 + held))    # both legs pay taker cost


def test_maker_fills_need_the_price_to_come_down():
    """A coin that only rises never fills a buy limit at the close."""
    px = 100 * np.exp(np.arange(fm.n_bars(60)) * 1e-5)
    c = coin(px, spread=0.0)
    c.low[:] = c.px.astype(np.float32)                        # the low is the close: nothing trades below
    ctx = fm.Ctx(gate_d=np.ones(fm.N_DAYS, dtype=bool), hours=(13, 22))
    v = next(x for x in fm.variants() if x.family == "D" and x.d["kind"] == "hours" and x.d["k"] == 2)
    tr = fm.simulate_coin(c, v, ctx)
    assert tr and all(t.share == 0 for t in tr)
