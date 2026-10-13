"""The fast-strategy study's bars, rules and accounting on synthetic data. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import numpy as np
import pytest

from lab.experiments import fam_common as fc
from lab.experiments import fast_strategies as fs

DAYS, N = 120, 3
T0 = 1_577_836_800_000_000      # 2020-01-01 UTC, us


def hourly(seed: int = 3, drift: float = 0.0) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    rng = np.random.default_rng(seed)
    H = DAYS * 24
    out = {}
    for j in range(N):
        r = rng.normal(drift, 0.01, H)
        c = 100 * np.exp(np.cumsum(r))
        ot = T0 + np.arange(H, dtype=np.int64) * fc.HOUR_US
        if j == 2:                               # coin 2 is delisted after day 90
            ot, c = ot[: 90 * 24], c[: 90 * 24]
        out[f"C{j}USDT"] = (ot, c)
    return out


def bars(hours: int, **kw) -> fs.Bars:
    h = hourly(**kw)
    return fs.from_hourly(list(h), T0, T0 + DAYS * fc.DAY_US, h, hours, T0)


def daily_panel() -> fc.Panel:
    T = DAYS
    z = np.zeros((T, N))
    days = T0 + np.arange(T, dtype=np.int64) * fc.DAY_US
    return fc.Panel(days=days, names=[f"C{j}USDT" for j in range(N)], bases=[f"C{j}" for j in range(N)],
                    close=z, px=z, high=z, low=z, ret=z, alive=np.ones((T, N), dtype=bool),
                    traded=np.ones((T, N), dtype=bool), age=z, adv28=z, sigma=z,
                    eligible=np.ones((T, N), dtype=bool), perp_ok=np.zeros((T, N), dtype=bool), funding=z,
                    btc_on=np.arange(T) % 20 < 10, btc=0)


def test_four_hour_bars_are_the_last_hourly_close():
    b1, b4 = bars(1), bars(4)
    assert b4.T == b1.T // 4
    assert np.allclose(b4.px[:, 0], b1.px[3::4, 0])
    r4 = b4.px[1:, 0] / b4.px[:-1, 0] - 1
    assert np.allclose(b4.ret[1:, 0], r4)


def test_delisted_coin_dies_and_is_never_entered_after():
    b = bars(4)
    last = 90 * 6 - 1
    assert b.alive[last, 2] and not b.alive[last + 1, 2]
    W, tr = fs.rule_weights(b, "R reversal", {"k": 0.5, "h": 6}, None, None, start=10)
    assert np.nansum(np.abs(W[last + 1:, 2])) == 0
    assert np.all(tr.t_out[tr.col == 2] <= last)


def rebuilt(h: dict, hours: int) -> fs.Bars:
    return fs.from_hourly(list(h), T0, T0 + DAYS * fc.DAY_US, h, hours, T0)


def test_vol_is_known_before_the_signal_bar():
    """A jump on one bar does not raise the vol that same bar is judged against."""
    h = hourly()
    t = 2000
    ot, c = h["C0USDT"]
    c = c.copy()
    c[t:] *= 1.2
    h2 = {**h, "C0USDT": (ot, c)}
    b, b2 = rebuilt(h, 1), rebuilt(h2, 1)
    assert b2.sig_prev[t, 0] == pytest.approx(b.sig_prev[t, 0])
    assert b2.sig_prev[t + 1, 0] > b.sig_prev[t + 1, 0]
    _, tr = fs.rule_weights(b2, "V vol breakout", {"k": 3, "h": 6}, None, None, start=800)
    assert t in tr.t_in[tr.col == 0]


@pytest.mark.parametrize("fam,p", [("T1 Donchian", {"n": 20, "vf": True}),
                                   ("T2 EMA", {"fast": 12, "slow": 48, "vf": True}),
                                   ("R reversal", {"k": 2, "h": 6}),
                                   ("V vol breakout", {"k": 2, "h": 6})])
def test_no_lookahead_future_prices_do_not_change_past_decisions(fam, p):
    h = hourly(seed=5)
    cut = 400                                    # a 4h bar
    h2 = {}
    for k, (ot, c) in h.items():
        c = c.copy()
        after = ot >= T0 + (cut + 1) * 4 * fc.HOUR_US
        c[after] *= np.linspace(0.5, 2.0, after.sum())
        h2[k] = (ot, c)
    W_full, _ = fs.rule_weights(rebuilt(h, 4), fam, p, None, None, start=60)
    W_cut, _ = fs.rule_weights(rebuilt(h2, 4), fam, p, None, None, start=60)
    assert np.array_equal(np.isnan(W_full[: cut + 1]), np.isnan(W_cut[: cut + 1]))
    assert np.allclose(np.nan_to_num(W_full[: cut + 1]), np.nan_to_num(W_cut[: cut + 1]))


def test_time_stop_holds_exactly_h_bars():
    b = bars(4)
    _, tr = fs.rule_weights(b, "R reversal", {"k": 1, "h": 6}, None, None, start=200)
    closed = (tr.t_out < b.T - 1) & b.alive[np.minimum(tr.t_out + 1, b.T - 1), tr.col]
    assert closed.any()
    assert np.all(tr.t_out[closed] - tr.t_in[closed] == 6)


def test_gate_off_sells_everything_and_blocks_entries():
    b = bars(4)
    gate = np.zeros(b.T, dtype=bool)
    gate[: 300] = True
    W, tr = fs.rule_weights(b, "T2 EMA", {"fast": 12, "slow": 48, "vf": False}, gate, None, start=100)
    assert np.nansum(W[301:]) == 0
    assert np.all(tr.t_in < 300)


def test_trade_returns_and_costs_add_up():
    b = bars(4, drift=0.0005)
    P = daily_panel()
    W, tr = fs.rule_weights(b, "T1 Donchian", {"n": 20, "vf": False}, None, None, start=60)
    run = fs.simulate(b, W, tr, P, "x", "T1 Donchian", "4h", False, 60)
    # Daily compounding keeps the total growth of the bar series.
    g, tv, _, _ = fc.simulate(fs.bar_panel(b), W, start=60)
    assert np.prod(1 + run.net[0.0]) == pytest.approx(np.prod(1 + g), rel=1e-9)
    c = fs.COSTS["taker 35bps"]
    assert np.prod(1 + run.net[c]) == pytest.approx(np.prod(1 + g - c * np.r_[0.0, tv[:-1]]), rel=1e-9)
    # Each round trip's return is the price move from entry close to exit close.
    k = 0
    assert run.trade_ret[k] == pytest.approx(b.px[tr.t_out[k], tr.col[k]] / b.px[tr.t_in[k], tr.col[k]] - 1)


def test_one_bar_late_fill_shifts_entries():
    b = bars(4, drift=0.0005)
    P = daily_panel()
    W, tr = fs.rule_weights(b, "T1 Donchian", {"n": 20, "vf": False}, None, None, start=60)
    on_time = fs.simulate(b, W, tr, P, "x", "T1 Donchian", "4h", False, 60)
    late = fs.simulate(b, W, tr, P, "x", "T1 Donchian", "4h", False, 60, lag=1)
    assert late.trade_ret[0] == pytest.approx(b.px[tr.t_out[0] + 1, tr.col[0]] / b.px[tr.t_in[0] + 1, tr.col[0]] - 1)
    assert not np.allclose(on_time.net[0.0], late.net[0.0])


def test_walk_forward_uses_only_the_past():
    P = daily_panel()
    r1 = fs.Run("a", "f", "4h", False, *(np.zeros(P.T),) * 2, fs.Trades(*(np.zeros(0, dtype=int),) * 3),
                np.zeros(0), np.zeros(0), np.zeros(0))
    r2 = fs.Run("b", "f", "4h", False, *(np.zeros(P.T),) * 2, fs.Trades(*(np.zeros(0, dtype=int),) * 3),
                np.zeros(0), np.zeros(0), np.zeros(0))
    for r, sign in ((r1, 1), (r2, -1)):
        x = np.random.default_rng(1).normal(0.001, 0.01, P.T) * sign
        r.net = {c: x for c in fs.COSTS.values()}
    out, picks = fs.walk_forward([r1, r2], P)
    # The synthetic panel ends before 2024: nothing out of sample to pick for.
    assert picks == [] and not out.any()


def test_pooled_variance_grows_with_far_off_trials():
    v_same, _ = fs.pooled_var([0.5] * 10)
    v_far, info = fs.pooled_var([-3.0] * 10)
    assert v_far > v_same
    assert info["n_total"] == 184 + 10
