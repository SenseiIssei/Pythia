"""W7, memecoin strategies: kline parsing, the panel, surge signals, holds, sizing. No lab data.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import io
import zipfile

import numpy as np
import polars as pl
import pytest

from lab import klines_daily
from lab.experiments import fam_common as fc
from lab.experiments import memecoins as mc

DAY0 = 1_577_836_800_000_000          # 2020-01-01 in us


def _zip(lines: list[str]) -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("x.csv", "\n".join(lines) + "\n")
    return b.getvalue()


def test_parse_zip_reads_ms_and_us_timestamps_and_skips_a_header():
    ms = "1577836800000,1,2,0.5,1.5,10,1577923199999,15,7,4,6,0"
    us = "1735689600000000,3,4,2,3.5,20,1735775999999999,70,9,8,30,0"
    df = klines_daily.parse_zip(_zip(["open_time,open,high,low,close,volume,close_time,quote_volume,count,"
                                      "taker_buy_volume,taker_buy_quote_volume,ignore", ms, us]))
    assert df["day"].to_list() == [DAY0, 1_735_689_600_000_000]
    assert df["close"].to_list() == [1.5, 3.5]
    assert df["qv"].to_list() == [15.0, 70.0]
    assert df["n"].to_list() == [7, 9]


def _frame(closes, qv=None, n=None, start=0) -> pl.DataFrame:
    T = len(closes)
    qv = qv if qv is not None else [5e6] * T
    n = n if n is not None else [1000] * T
    c = np.asarray(closes, float)
    return pl.DataFrame({"day": [DAY0 + (start + i) * fc.DAY_US for i in range(T)], "open": c, "high": c, "low": c,
                         "close": c, "volume": [1.0] * T, "qv": [float(x) for x in qv], "n": n,
                         "taker_qv": [0.0] * T})


@pytest.fixture()
def panel() -> fc.Panel:
    rng = np.random.default_rng(3)
    T = 400
    frames = {"BTCUSDT": _frame(100 * np.cumprod(1 + rng.normal(0.001, 0.02, T)))}
    frames["DOGEUSDT"] = _frame(np.cumprod(1 + rng.normal(0.002, 0.05, T)))
    # SHIB starts 100 days later and dies at day 350.
    frames["SHIBUSDT"] = _frame(np.cumprod(1 + rng.normal(0, 0.06, 250)), start=100)
    qv = [2e6] * T
    qv[200] = 2e7
    frames["FLOKIUSDT"] = _frame(np.cumprod(1 + rng.normal(0, 0.06, T)), qv=qv)
    return mc.build_panel(frames)


def test_build_panel_lines_up_days_and_lifetimes(panel):
    P = panel
    assert P.names == ["BTCUSDT", "DOGEUSDT", "FLOKIUSDT", "SHIBUSDT"]
    j = P.col("SHIBUSDT")
    assert not P.alive[99, j] and P.alive[100, j] and P.alive[349, j] and not P.alive[350, j]
    assert np.isnan(P.ret[100, j]) and np.isfinite(P.ret[101, j])
    # Eligible from 60 days of age on.
    assert not P.eligible[159, j] and P.eligible[160, j]
    assert np.allclose(P.ret[1:, 1], P.close[1:, 1] / P.close[:-1, 1] - 1)


def test_universes_keep_a_to_the_alpaca_memecoins(panel):
    u = mc.universes(panel)
    assert not u["A"][:, panel.col("FLOKIUSDT")].any()
    assert u["A"][:, panel.col("DOGEUSDT")].any()
    assert u["M"][:, panel.col("FLOKIUSDT")].any()
    assert not u["A"][:, panel.btc].any() and not u["M"][:, panel.btc].any()


def test_surge_ratio_uses_only_the_previous_days():
    x = np.ones((60, 1))
    x[40] = 5.0
    r = mc.surge_ratio(x, 28)
    assert np.isnan(r[10, 0])                    # fewer than 14 past days
    assert r[40, 0] == pytest.approx(5.0)
    assert r[41, 0] == pytest.approx(1.0)        # one outlier does not move the median


def test_hold_after_holds_h_closes_from_the_last_signal(panel):
    sig = np.zeros((panel.T, panel.N), dtype=bool)
    j = panel.col("DOGEUSDT")
    sig[100, j] = True
    sig[102, j] = True                           # extends the hold
    W = mc.hold_after(panel, sig, 3)
    assert W[100, j] > 0
    assert np.isnan(W[101:105, j]).all()
    assert W[105, j] == 0.0
    g, tv, ex, held = mc.au.sim_daily(panel, W)
    assert (held[100:105, j] > 0).all() and held[105, j] == 0


def test_hold_after_closes_a_dead_coin(panel):
    sig = np.zeros((panel.T, panel.N), dtype=bool)
    j = panel.col("SHIBUSDT")
    sig[348, j] = True
    W = mc.hold_after(panel, sig, 7)
    assert W[350, j] == 0.0


def test_size_is_vol_over_slots_and_capped(panel):
    s = mc.size(panel, 6)
    assert (s <= 1 / 6 + 1e-12).all()
    t, j = 300, panel.col("DOGEUSDT")
    want = min(0.40 / (panel.sigma[t, j] * np.sqrt(365)) / 6, 1 / 6)
    assert s[t, j] == pytest.approx(want)


def test_trend_holds_only_rising_universe_coins_and_respects_the_gate(panel):
    u = mc.universes(panel)["A"]
    W = mc.trend(panel, u, 28, gated=True)
    assert (W[~u] == 0).all()
    assert (W[~panel.btc_on] == 0).all()
    past = mc.trailing_return(panel, 28)
    assert (W[np.nan_to_num(past, nan=-1) <= 0] == 0).all()


def test_rotation_holds_at_most_k(panel):
    u = mc.universes(panel)["M"]
    for k in (1, 2):
        W = mc.rotation(panel, u, k)
        assert ((W > 0).sum(1) <= k).all()


def test_variants_count_matches_the_preregistration(panel):
    v = mc.variants(panel, mc.universes(panel)["A"])
    assert len(v) == 22
    assert len({name for _, name, _ in v}) == 22
    assert 2 * 22 + len(mc.FAMILIES) == mc.HERE_TRIALS
    for _, _, W in v:
        assert np.nanmin(W) >= 0
        assert (np.nansum(W, 1) <= 1 + 1e-9).all()


def test_longest_underwater_and_worst_month():
    r = np.array([0.1, -0.2, 0.05, 0.05, 0.2, -0.01])
    assert mc.longest_underwater(r) == 3
    months = np.array(["a", "a", "b", "b", "c", "c"])
    assert mc.worst_month(r, months) == pytest.approx(1.1 * 0.8 - 1)
