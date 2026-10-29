"""RF1, a forecast of tomorrow's range as a filter: recursions, fits, the walk-forward, the groups, the filters and
the judgement. Synthetic data only, no lab data.

Run from research/lab:  python -m pytest tests/test_range_forecast_rf1.py
"""

from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from lab import metrics
from lab.experiments import fam_breakout, fam_common as fc
from lab.experiments import intraday_equities as ie
from lab.experiments import range_forecast_rf1 as rf

from test_intraday_equities import synthetic
from test_tsmom_tranches import make_panel


def ohlc(n: int, seed: int = 0, start: str = "2016-01-01", vol=None):
    """A daily GARCH-like path with open = previous close (a coin's day) and a range around it."""
    rng = np.random.default_rng(seed)
    days = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(n, "D"), dtype="datetime64[D]")
    s = np.full(n, 0.03) if vol is None else vol
    r = rng.normal(0, 1, n) * s
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * np.exp(np.abs(rng.normal(0, 1, n)) * s * 0.5)
    l = np.minimum(o, c) * np.exp(-np.abs(rng.normal(0, 1, n)) * s * 0.5)
    return days, o, h, l, c


def garch_vol(n: int, w=0.02, a=0.08, b=0.9, seed: int = 3) -> np.ndarray:
    rng = np.random.default_rng(seed)
    s2 = np.empty(n)
    s2[0] = w / (1 - a - b)
    for t in range(1, n):
        s2[t] = w + a * s2[t - 1] * rng.normal() ** 2 + b * s2[t - 1]
    return np.sqrt(s2) / 100


# --- recursions and fits ----------------------------------------------------------

def test_recursion_is_the_loop():
    x = np.random.default_rng(1).random(50)
    s = rf.recursion(x, 0.1, 0.2, 0.7, 1.5)
    ref = [1.5]
    for v in x:
        ref.append(0.1 + 0.2 * v + 0.7 * ref[-1])
    assert np.allclose(s, ref)


def test_garch_fit_recovers_its_parameters():
    rng = np.random.default_rng(5)
    n, w, a, b = 6000, 0.05, 0.1, 0.85
    r, s2 = np.empty(n), w / (1 - a - b)
    for t in range(n):
        r[t] = rng.normal() * np.sqrt(s2)
        s2 = w + a * r[t] ** 2 + b * s2
    W, A, Bt = rf.fit_garch(r ** 2)
    assert abs(A - a) < 0.04 and abs(Bt - b) < 0.06 and A + Bt < 0.999


def test_carr_fit_recovers_its_parameters():
    rng = np.random.default_rng(6)
    n, w, a, b = 6000, 0.002, 0.2, 0.7
    R, lam = np.empty(n), w / (1 - a - b)
    for t in range(n):
        R[t] = lam * rng.exponential()
        lam = w + a * R[t] + b * lam
    W, A, Bt = rf.fit_carr(R)
    assert abs(A - a) < 0.05 and abs(Bt - b) < 0.07


def test_rolling_mean_needs_a_full_window_without_gaps():
    x = np.array([1.0, 2, 3, np.nan, 5, 6, 7])
    m = rf.rolling_mean(x, 3)
    assert np.isnan(m[:2]).all() and m[2] == 2.0 and np.isnan(m[3:6]).all() and m[6] == 6.0


def test_series_true_range_takes_the_previous_close():
    o, h, l, c = (np.array(v, dtype=float) for v in ([10, 12], [11, 13], [9, 12.5], [10, 12.8]))
    S = rf.series(o, h, l, c)
    assert S["tr"][1] == pytest.approx(13 - 10)              # the gap from 10 counts
    assert S["z_tr"][1] == pytest.approx(0.3) and S["z_hl"][1] == pytest.approx(0.05)
    assert (S["RS"] >= 0).all() and (S["GK"] >= 0).all()


# --- the walk-forward --------------------------------------------------------------

def test_forecasts_start_after_a_year_and_a_quarter_start_and_are_positive():
    days, o, h, l, c = ohlc(1200, start="2017-06-01")
    F = rf.asset_forecasts(days, o, h, l, c, (1, 7, 30))
    first = days[np.flatnonzero(np.isfinite(F["tr"]["GARCH"]))[0]]
    assert first == np.datetime64("2018-07-01")              # 365 rows before 2018-07-01, first quarter start after
    for t in rf.TARGETS:
        for k in rf.KEYS:
            f = F[t][k][days >= first]
            assert np.isfinite(f).all() and (f > 0).all(), (t, k)


def test_forecasts_are_scaled_to_the_mean_range():
    days, o, h, l, c = ohlc(1500, start="2016-01-01")
    F = rf.asset_forecasts(days, o, h, l, c, (1, 7, 30))
    z = rf.series(o, h, l, c)["z_tr"]
    m = days >= np.datetime64("2018-01-01")
    for k in rf.KEYS:
        if k != "RW1":
            assert np.nanmean(F["tr"][k][m]) == pytest.approx(np.nanmean(z[m]), rel=0.05), k
    assert np.nanmean(F["tr"]["RW1"][m]) > np.nanmean(z[m])    # QLIKE's scale of a noisy forecast, mean(y / g)


def test_forecasts_never_move_with_the_future():
    days, o, h, l, c = ohlc(1400, start="2016-06-01", vol=garch_vol(1400))
    F = rf.asset_forecasts(days, o, h, l, c, (1, 5, 22), targets=("tr",))
    cut = 1100
    rng = np.random.default_rng(9)
    p = rng.permutation(np.arange(cut + 1, 1400))
    o2, h2, l2, c2 = (np.r_[x[:cut + 1], x[p]] for x in (o, h, l, c))
    G = rf.asset_forecasts(days, o2, h2, l2, c2, (1, 5, 22), targets=("tr",))
    for k in rf.KEYS:
        assert np.allclose(F["tr"][k][:cut + 1], G["tr"][k][:cut + 1], equal_nan=True), k


def test_garch_beats_the_flat_average_when_volatility_clusters():
    n = 2600
    days, o, h, l, c = ohlc(n, start="2019-04-01", vol=garch_vol(n, 0.01, 0.15, 0.83))
    G = {"name": "coins", "names": ["AUSDT"], "days": days, "days_us": days.astype("datetime64[us]").astype(np.int64),
         "o": o[:, None], "h": h[:, None], "l": l[:, None], "c": c[:, None]}
    R = rf.group_forecasts(G)
    A = rf.part_a(G, R)
    rows = {r["model"]: r for r in A["targets"]["tr"]["rows"]}
    assert rows["GARCH"]["qlike validation"] < rows["MA20"]["qlike validation"]
    assert rows["GARCH"]["gain vs MA20 %"] > 0 and rows["GARCH"]["p vs MA20"] < 0.5
    assert isinstance(rows["GARCH"]["pass"], bool) and "pass" not in rows["MA20"]
    assert set(A["targets"]["tr"]["windows32"]) == set(rf.KEYS) | {"persistence"}
    assert 0 < A["targets"]["tr"]["persistence"]["acc validation"] < 1


def test_group_rows_line_up_target_and_yardsticks():
    days, o, h, l, c = ohlc(900, start="2017-01-01")
    o[400] = np.nan                                           # a day without a bar
    G = {"name": "coins", "names": ["AUSDT"], "days": days, "days_us": days.astype("datetime64[us]").astype(np.int64),
         "o": o[:, None], "h": h[:, None], "l": l[:, None], "c": c[:, None]}
    R = rf.group_forecasts(G, keys=("RW1",))
    tr = R["tr"][:, 0]
    assert np.isnan(tr[400]) and R["tr_next"][399, 0] == pytest.approx(tr[401])
    assert R["y"]["tr"][399, 0] == pytest.approx(tr[401] / c[399])
    assert R["atr20"][500, 0] == pytest.approx(np.mean(tr[481:501]))


def test_chosen_takes_the_lowest_in_sample_loss_of_the_passing_models():
    A = {"targets": {"tr": {"rows": [{"model": "GARCH", "pass": True, "qlike 2018-2023": 0.3},
                                     {"model": "CARR", "pass": True, "qlike 2018-2023": 0.2},
                                     {"model": "HAR-RS", "pass": False, "qlike 2018-2023": 0.1}]}}}
    assert rf.chosen(A) == "CARR"
    A["targets"]["tr"]["rows"][1]["pass"] = A["targets"]["tr"]["rows"][0]["pass"] = False
    assert rf.chosen(A) is None


def test_dm_one_sided_says_which_is_better():
    d = np.random.default_rng(2).normal(-0.1, 1, 2000)
    st, p = rf.dm_one_sided(d)
    assert st < 0 and p < 0.05
    assert rf.dm_one_sided(-d)[1] > 0.95


def test_friend_band_is_wide():
    lo, hi = rf.friend_band()
    assert lo < 0.6 < 0.72 < hi


# --- data -------------------------------------------------------------------------

def test_coin_group_keeps_alpaca_coins_and_drops_the_lockbox():
    d0 = rf.dc.us("2026-06-28")
    rows = []
    for s in ("BTCUSDT", "TRXUSDT", "ETHUSDT~0", "ETHUSDT"):
        for i in range(5):
            rows.append({"day": d0 + i * fc.DAY_US, "symbol": s, "close": 10.0 + i, "high": 11.0 + i, "low": 9.0 + i})
    G = rf.coin_group(pl.DataFrame(rows))
    assert G["names"] == ["BTCUSDT", "ETHUSDT"]
    assert G["days"][-1] == np.datetime64("2026-06-30")
    assert np.isnan(G["o"][0]).all() and G["o"][1, 0] == G["c"][0, 0]


def test_load_etf_bars_cuts_before_the_lockbox(tmp_path):
    for s in ie.ETFS:
        for d in (date(2026, 6, 29), date(2026, 6, 30), date(2026, 7, 1)):
            df = pl.DataFrame({"date": [d] * ie.NB, "bar": list(range(ie.NB)), "open": [100.0] * ie.NB,
                               "high": [101.0] * ie.NB, "low": [99.0] * ie.NB, "close": [100.5] * ie.NB,
                               "volume": [1e5] * ie.NB, "tp": [100.2] * ie.NB})
            (tmp_path / "alpaca-sip" / s).mkdir(parents=True, exist_ok=True)
            df.write_parquet(tmp_path / "alpaca-sip" / s / f"{d.isoformat()}.parquet")
    B = rf.load_etf_bars(tmp_path)
    assert B.syms == list(ie.ETFS) and B.dates[-1] == np.datetime64("2026-06-30") and B.D == 2
    G = rf.etf_group(B)
    assert G["o"].shape == (2, 3) and G["h"][0, 0] == 101.0 and G["c"][0, 0] == 100.5


def test_load_etf_bars_without_cache_says_so(tmp_path):
    with pytest.raises(ie.DataUnavailable):
        rf.load_etf_bars(tmp_path)


# --- Part B --------------------------------------------------------------------------

def test_breakout_gated_open_is_the_book_as_it_runs():
    P = make_panel()
    top = P.top_liquid(3)
    cols = np.flatnonzero(top.any(0))
    ref = fam_breakout.breakout_weights(P, cols, top, 20, 3, regime=False)
    assert np.allclose(rf.breakout_gated(P, cols, top, 20, 3), ref, equal_nan=True)
    assert np.allclose(rf.breakout_gated(P, cols, top, 20, 3, np.ones((P.T, P.N), dtype=bool)), ref, equal_nan=True)


def test_breakout_gated_blocks_entries_only_and_enters_later():
    P = make_panel()
    top = P.top_liquid(3)
    cols = np.flatnonzero(top.any(0))
    ref = fam_breakout.breakout_weights(P, cols, top, 20, 3, regime=False)
    t, j = next((t, j) for t in range(100, P.T) for j in cols if np.nan_to_num(ref[t, j]) > 0)
    gate = np.ones((P.T, P.N), dtype=bool)
    gate[t, j] = False
    W = rf.breakout_gated(P, cols, top, 20, 3, gate)
    assert np.isnan(W[t, j]) or W[t, j] == 0
    later = np.flatnonzero(np.nan_to_num(W[t + 1:, j]) > 0)
    hi = fc.rolling_extreme(P.px[:, [j]], 20, "max")[:, 0]
    if later.size:                                            # an entry later is again a breakout
        assert P.px[t + 1 + later[0], j] > hi[t + 1 + later[0]]
    none = rf.breakout_gated(P, cols, top, 20, 3, np.zeros((P.T, P.N), dtype=bool))
    assert not (np.nan_to_num(none) > 0).any()


def test_shift_next_and_runs():
    X = np.arange(10, dtype=float).reshape(5, 2)
    v = np.ones((5, 2), dtype=bool)
    v[2, 0] = False
    s = rf.shift_next(X, v)
    assert np.isnan(s[0]).all() and s[3, 0] == X[1, 0] and s[1, 1] == X[0, 1]
    on = np.array([[1, 0], [1, 1], [0, 1], [1, 1]], dtype=bool)
    assert sorted(rf.runs(on)) == [(0, 0, 2), (0, 3, 1), (1, 1, 3)]


def test_squeeze_flags_mark_the_five_closes_after_a_low_forecast():
    f = np.linspace(1.0, 2.0, 400)[:, None].copy()
    f[200, 0] = 0.1                                           # the lowest forecast so far
    flags = rf.squeeze_flags(f, np.ones_like(f, dtype=bool))[:, 0]
    assert flags[201:206].all() and not flags[200] and not flags[206]
    assert not flags[:rf.SQ_MIN + 1].any()


def test_judge_gates():
    rng = np.random.default_rng(4)
    xb = rng.normal(0.0005, 0.02, 900)
    pool = {"n_trials": 2000, "var": metrics.prior_var()}
    same = rf.judge(xb.copy(), xb, 365, pool)
    assert not same["gates"]["1 CE up"] and same["dce_p05"] == 0 and not same["pass"]
    better = rf.judge(xb * 0.5 + 0.003, xb, 365, pool)
    assert better["gates"]["1 CE up"] and better["gates"]["2 drawdown not worse"] and better["gates"]["3 band above 0"]
    assert isinstance(better["pass"], bool)
    assert rf.max_dd(np.array([0.1, -0.5, 0.2])) == pytest.approx(0.5)
    assert rf.ce(np.array([0.01, 0.01]), 365) == pytest.approx(3.65)


def test_etf_books_filters_change_entries_only_where_they_block():
    B = synthetic(D=700, syms=("SPY", "QQQ", "IWM"), start="2016-01-04", drift_after_break=0.0003)
    G = rf.etf_group(B)
    T, N = G["c"].shape
    R = {"f": {"tr": {"GARCH": np.full((T, N), 0.01)}}, "c": G["c"], "atr20": np.full((T, N), 0.5)}
    eb = rf.etf_books(B, G, R, "GARCH")
    assert set(eb["books"]) == set(rf.ETF_RULES)
    orb = eb["books"]["ORB 15m long"]
    assert set(orb) == {"base", "good", "cost", "squeeze"} and set(eb["books"]["VWAP k 2.0 long"]) == {"base", "good", "cost"}
    assert orb["good"][1].sum() <= orb["base"][1].sum()
    assert np.array_equal(orb["cost"][1][:, 1:], orb["base"][1][:, 1:])   # 1 % a day clears 12 to 18 bps
    assert 0 < eb["holds"]["ORB 15m long"] <= 1


def test_trials_are_counted_by_id():
    a = rf.a_trials()
    assert len(a) == 12 and all(t["family"] == "hand" and t["sharpe"] is None for t in a)
    b = rf.b_trials("coins", {"breakout_top10:base": 1.0, "breakout_top10:good": 0.5})
    assert [t["id"] for t in b] == ["hand:rf1:breakout_top10:base", "hand:rf1:breakout_top10:good"]


def test_part_b_registers_before_judging(tmp_path, monkeypatch):
    reg = tmp_path / "registry.jsonl"
    monkeypatch.setenv("PYTHIA_TRIALS_REGISTRY", str(reg))
    days = np.arange(np.datetime64("2022-01-01"), np.datetime64("2026-07-01"), dtype="datetime64[D]")
    rng = np.random.default_rng(8)
    x = rng.normal(0.0005, 0.02, len(days))
    out = rf.part_b("coins", {"breakout_top10": {"base": x, "good": x * 0.9}}, days, 365, True, "2022-03-01")
    ids = {r["id"] for r in metrics.read_registry(reg)}
    assert {"hand:rf1:breakout_top10:base", "hand:rf1:breakout_top10:good"} <= ids
    assert len(out["rows"]) == 1 and out["rows"][0]["filter"] == "good"


def test_leak_check_on_synthetic_coins_is_clean():
    n = 1100
    cols = {}
    for k, name in enumerate(("BTCUSDT", "ETHUSDT")):
        cols[name] = ohlc(n, seed=k, start="2017-01-01", vol=garch_vol(n, seed=k + 3))
    days = cols["BTCUSDT"][0]
    G = {"name": "coins", "names": list(cols), "days": days, "days_us": days.astype("datetime64[us]").astype(np.int64)}
    for i, k in enumerate(("o", "h", "l", "c")):
        G[k] = np.column_stack([cols[c][i + 1] for c in cols])
    res = rf.leak_check(G)
    assert res["ok"], res


def test_markdown_renders_without_part_b():
    days, o, h, l, c = ohlc(1300, start="2017-06-01")
    G = {"name": "etfs", "names": ["SPY"], "days": days, "days_us": days.astype("datetime64[us]").astype(np.int64),
         "o": o[:, None], "h": h[:, None], "l": l[:, None], "c": c[:, None]}
    A = rf.part_a(G, rf.group_forecasts(G))
    out = {"generated": "now", "a": {"etfs": A}, "chosen": {"etfs": None}, "b": {"etfs": None},
           "leak": {"ok": True, "runs": 3}, "friend_band": rf.friend_band(), "trials_a": ["x"], "passed": []}
    md = rf.markdown(out)
    assert "Part A, etfs" in md and "none passes" in md and "\u2014" not in md
