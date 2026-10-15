"""The intraday study (W4) on synthetic 5-minute bars. No market data, no keys.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
from datetime import date

import numpy as np
import polars as pl
import pytest

from lab.experiments import intraday_equities as ie

NB, EXIT = ie.NB, ie.EXIT_BAR


def business_days(start: str, n: int) -> np.ndarray:
    d = np.arange(np.datetime64(start), np.datetime64(start) + np.timedelta64(3 * n, "D"), dtype="datetime64[D]")
    return d[((d.astype(np.int64) + 3) % 7) < 5][:n]


def synthetic(D: int = 700, syms=("SPY", "QQQ", "IWM", "AAPL", "MSFT", "XOM"), start: str = "2019-06-03",
              seed: int = 1, drift_after_break: float = 0.0) -> ie.Bars:
    """Random-walk sessions; with drift_after_break > 0 a close above the 30-minute
    high is followed by a small up-drift for the rest of the day (an ORB edge)."""
    rng = np.random.default_rng(seed)
    dates = business_days(start, D)
    S = len(syms)
    o, h, l, c = (np.zeros((S, D, NB)) for _ in range(4))
    v = rng.uniform(1e5, 2e5, (S, D, NB)) * np.arange(1, S + 1)[:, None, None]
    prev = np.full(S, 100.0)
    for d in range(D):
        px = prev * (1 + rng.normal(0, 0.004, S))
        H = np.full(S, -np.inf)
        broke = np.zeros(S, dtype=bool)
        for k in range(NB):
            op = px.copy()
            r = rng.normal(0, 0.0012, S) + np.where(broke, drift_after_break, 0.0)
            cl = op * (1 + r)
            hi = np.maximum(op, cl) * (1 + np.abs(rng.normal(0, 0.0004, S)))
            lo = np.minimum(op, cl) * (1 - np.abs(rng.normal(0, 0.0004, S)))
            o[:, d, k], h[:, d, k], l[:, d, k], c[:, d, k] = op, hi, lo, cl
            if k < 6:
                H = np.maximum(H, hi)
            else:
                broke |= cl > H
            px = cl
        prev = px
    tp = (h + l + c) / 3
    return ie.Bars(dates=dates, syms=list(syms), o=o, h=h, l=l, c=c, v=v, tp=tp, scale=np.ones(S),
                   source="synthetic")


def flat_day(B: ie.Bars, s: int, d: int, price: float = 100.0) -> None:
    for a in (B.o, B.h, B.l, B.c, B.tp):
        a[s, d] = price


# --- data plumbing ------------------------------------------------------------

def test_frame_to_blocks_fills_missing_bars():
    df = pl.DataFrame({"date": [date(2020, 1, 2)] * 3, "bar": [1, 2, 5],
                       "open": [10.0, 11.0, 12.0], "high": [10.5, 11.5, 12.5], "low": [9.5, 10.5, 11.5],
                       "close": [10.2, 11.2, 12.2], "volume": [5.0, 6.0, 7.0]})
    days, a = ie.frame_to_blocks(df)
    assert list(days.astype(str)) == ["2020-01-02"]
    assert a["open"][0, 0] == 10.0 and a["close"][0, 0] == 10.0          # leading gap takes the first open
    assert a["close"][0, 3] == 11.2 and a["open"][0, 4] == 11.2           # inner gap repeats the last close
    assert a["volume"][0, 3] == 0.0 and a["close"][0, NB - 1] == 12.2


def test_session_maps_new_york_time_across_dst():
    rows = [{"t": "2020-01-02T14:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},     # 09:30 EST
            {"t": "2020-07-01T13:30:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},     # 09:30 EDT
            {"t": "2020-07-01T19:55:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},     # 15:55 EDT
            {"t": "2020-07-01T20:00:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1},     # 16:00, after the close
            {"t": "2020-07-01T13:25:00Z", "o": 1, "h": 1, "l": 1, "c": 1, "v": 1}]     # pre-market
    df = ie.alpaca_frame(rows)
    assert df["bar"].to_list() == [0, 0, 77]
    assert [str(x) for x in df["date"].to_list()] == ["2020-01-02", "2020-07-01", "2020-07-01"]


def test_proxy_month_resamples_the_regular_session():
    lines = ["time,close,high,low,open,volume"]
    # 2017-03-01 is EST: 14:30 UTC = 09:30 New York.
    for m in range(0, 400):
        hh, mm = divmod(14 * 60 + 25 + m, 60)
        lines.append(f"2017-03-01 {hh:02d}:{mm:02d}:00,{100 + m},{101 + m},{99 + m},{100 + m},2")
    df = ie.proxy_month("\n".join(lines))
    assert df["bar"].min() == 0 and df["bar"].max() == NB - 1
    first = df.filter(pl.col("bar") == 0).row(0, named=True)
    assert first["open"] == 105 and first["close"] == 109 and first["minutes"] == 5 and first["volume"] == 10


def test_proxy_valid_drops_short_and_quiet_days():
    mins = np.array([390] * 25 + [210, 390, 390])
    vol = np.array([1000.0] * 25 + [900.0, 200.0, 800.0])
    ok = ie.proxy_valid(mins, vol)
    assert ok[:25].all()
    assert not ok[25]          # a half day
    assert not ok[26]          # a holiday quote: 20 % of the usual activity
    assert ok[27]


def test_alpaca_loader_reads_keys_only_from_env_and_caches(tmp_path, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    monkeypatch.delenv("APCA_API_SECRET", raising=False)
    assert ie.alpaca_keys() is None
    with pytest.raises(ie.DataUnavailable):
        ie.load_alpaca()
    monkeypatch.setenv("APCA_API_KEY_ID", "k")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "s")
    assert ie.alpaca_keys() == {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}

    monkeypatch.setattr(ie, "CACHE_ROOT", tmp_path)
    monkeypatch.setattr(ie, "ALPACA_FROM", (2020, 1))
    monkeypatch.setattr(ie, "CANDIDATES", ("AAPL",))
    calls = []

    def fake_get(url):
        calls.append(url)
        assert "feed=sip" in url and "adjustment=all" in url and "timeframe=5Min" in url
        sym = url.split("symbols=")[1].split("&")[0]
        if "page_token" not in url:
            bars = [{"t": f"2020-01-02T{14 + (30 + 5 * k) // 60:02d}:{(30 + 5 * k) % 60:02d}:00Z", "o": 100 + k,
                     "h": 101 + k, "l": 99 + k, "c": 100.5 + k, "v": 1000, "vw": 100.2 + k} for k in range(40)]
            return {"bars": {sym: bars}, "next_page_token": "p2"} if "start=2020-01" in url else {"bars": {}}
        bars = [{"t": f"2020-01-02T{14 + (30 + 5 * k) // 60:02d}:{(30 + 5 * k) % 60:02d}:00Z", "o": 100 + k,
                 "h": 101 + k, "l": 99 + k, "c": 100.5 + k, "v": 1000} for k in range(40, NB)]
        return {"bars": {sym: bars}}

    today = ie.datetime(2020, 2, 15, tzinfo=ie.timezone.utc)
    B = ie.load_alpaca(get=fake_get, today=today)
    assert B.syms == ["SPY", "QQQ", "IWM", "AAPL"] and B.D == 1
    assert B.o[0, 0, 0] == 100 and B.c[0, 0, NB - 1] == 100.5 + NB - 1
    assert B.tp[0, 0, 0] == pytest.approx(100.2) and B.tp[0, 0, 50] == pytest.approx((151 + 149 + 150.5) / 3)
    n_first = len(calls)
    assert (tmp_path / "alpaca-sip" / "SPY" / "2020-01.parquet").exists()
    for f in (tmp_path / "alpaca-sip").rglob("*.parquet"):        # nothing but bars is cached
        assert pl.read_parquet(f).columns == ["date", "bar", "open", "high", "low", "close", "volume", "tp"]
    ie.load_alpaca(get=fake_get, today=today)
    # The second run reads the finished months from the cache; only the running month is fetched again.
    assert len(calls) - n_first == 4


# --- rules ----------------------------------------------------------------

def test_orb_enters_after_the_first_close_above_the_range_and_is_flat_by_the_close():
    B = synthetic(D=30, seed=2)
    s, d = 0, 25
    flat_day(B, s, d, 100.0)
    B.h[s, d, :3] = 101.0
    B.l[s, d, :3] = 99.0
    for a in (B.o, B.h, B.l, B.c):
        a[s, d, 10:] = 102.0                   # bar 10 closes above the 15-minute high
    B.o[s, d, 11:] = 103.0                    # the fill at bar 11's open
    B.o[s, d, EXIT:] = 106.0                  # and the exit at 15:55
    F = ie.features(B)
    tgt = ie.rule_orb(B, F, 15, longshort=False, stop=False)
    held = ie.held_from_targets(tgt)
    assert held[s, d, :11].sum() == 0 and (held[s, d, 11:EXIT] == 1).all() and held[s, d, EXIT] == 0
    sim = ie.simulate(B, held)
    assert sim.gross[s, d] == pytest.approx(106 / 103 - 1)
    assert sim.turnover[s, d] == 2 and sim.entries[s, d] == 1
    one_late = ie.simulate(B, ie.held_from_targets(tgt, lag=1))
    assert one_late.gross[s, d] == pytest.approx(106 / 103 - 1)    # bar 12's open is also 103


def test_orb_long_only_sits_out_a_first_break_down():
    B = synthetic(D=30, seed=2)
    s, d = 1, 25
    flat_day(B, s, d, 100.0)
    B.h[s, d, :1] = 101.0
    B.l[s, d, :1] = 99.0
    B.c[s, d, 3] = 98.0                       # first break: down
    B.c[s, d, 5] = 102.0                      # then up
    F = ie.features(B)
    assert ie.rule_orb(B, F, 5, longshort=False, stop=False)[s, d].sum() == 0
    ls = ie.rule_orb(B, F, 5, longshort=True, stop=False)[s, d]
    assert ls[3] == -1 and ls[5] == -1        # one entry a day: the short stays


def test_rules_never_look_ahead():
    B = synthetic(D=60, seed=4)
    F = ie.features(B)
    k = 40
    B2 = ie.Bars(**{**B.__dict__})
    for name in ("o", "h", "l", "c", "v", "tp"):
        a = getattr(B, name).copy()
        a[:, -1, k + 1:] *= 1.05              # change the future of the last day only
        setattr(B2, name, a)
    F2 = ie.features(B2)
    for v in ie.grid():
        t1, t2 = ie.targets(B, F, v), ie.targets(B2, F2, v)
        assert np.array_equal(t1[:, :, :k + 1], t2[:, :, :k + 1]), v["name"]


def test_no_entries_after_the_last_decision_and_flat_at_the_exit_bar():
    B = synthetic(D=60, seed=5)
    F = ie.features(B)
    for v in ie.grid():
        tgt = ie.targets(B, F, v)
        held = ie.held_from_targets(tgt)
        assert (held[:, :, EXIT:] == 0).all()
        prev = np.concatenate([np.zeros(held.shape[:2] + (1,)), held[:, :, :-1]], 2)
        new = (held != 0) & (held != prev)
        assert not new[:, :, ie.LAST_ENTRY + 2:].any(), v["name"]


def test_gap_fade_exits_when_the_gap_fills():
    B = synthetic(D=40, seed=6)
    s, d = 2, 35
    F = ie.features(B)
    pc = F.prev_close[s, d]
    flat_day(B, s, d, pc * 0.97)              # a 3 % gap down, z far below -1.5
    B.c[s, d, 20] = pc * 1.001                # the gap fills at bar 20's close
    F = ie.features(B)
    tgt = ie.rule_gap(B, F, 1.0, "fade", longshort=False)
    assert tgt[s, d, 0] == 1 and tgt[s, d, 19] == 1 and tgt[s, d, 20] == 0
    go = ie.rule_gap(B, F, 1.0, "go", longshort=True)
    assert go[s, d, 0] == -1


def test_vwap_and_momentum_rules_respect_their_windows():
    B = synthetic(D=60, seed=7)
    F = ie.features(B)
    tv = ie.rule_vwap(B, F, 1.0, True)
    assert not tv[:, :, :ie.BAR_1000].any()
    tm = ie.rule_momentum(B, F, "first", True)
    assert not tm[:, :, :ie.LAST_ENTRY].any() and (np.abs(tm[:, 25:, ie.LAST_ENTRY]) == 1).mean() > 0.9
    tl = ie.rule_momentum(B, F, "first+12th", False)
    assert set(np.unique(tl)) <= {0.0, 1.0}


# --- costs, filters, universe ------------------------------------------------

def test_costs_and_sell_fees():
    B = synthetic(D=30, seed=8)
    s = B.syms.index("AAPL")
    d = 20
    flat_day(B, s, d, 50.0)
    held = np.zeros((B.S, B.D, NB))
    held[s, d, 10:EXIT] = -1.0                # a short: the sell is the entry
    sim = ie.simulate(B, held)
    cost = ie.cost_per_side(B.syms)
    assert cost[s] == pytest.approx(5e-4) and cost[0] == pytest.approx(2e-4) and cost[2] == pytest.approx(3e-4)
    fee = ie.SEC_FEE + ie.TAF_PER_SHARE / 50.0
    assert sim.fees[s, d] == pytest.approx(fee)
    assert sim.net(cost)[s, d] == pytest.approx(-2 * 5e-4 - fee)
    assert sim.net(cost, 2.0)[s, d] == pytest.approx(-4 * 5e-4 - fee)


def test_book_is_one_over_n_and_a_member_without_a_session_holds_cash():
    B = synthetic(D=30, seed=9)
    B.o[3, 10] = np.nan                        # AAPL has no session that day
    held = ie.drift_held(B)
    sim = ie.simulate(B, held)
    U = np.zeros((B.S, B.D), dtype=bool)
    U[[0, 3], :] = True
    x = ie.book(sim, U, ie.cost_per_side(B.syms))
    assert x[10] == pytest.approx(sim.net(ie.cost_per_side(B.syms))[0, 10] / 2)


def test_macro_days_are_first_fridays():
    d = np.arange(np.datetime64("2024-01-01"), np.datetime64("2024-04-01"), dtype="datetime64[D]")
    got = d[ie.macro_days(d)]
    assert [str(x) for x in got] == ["2024-01-05", "2024-02-02", "2024-03-01"]
    extra = ie.macro_days(d, {np.datetime64("2024-01-31")})
    assert extra.sum() == 4


def test_universe_is_point_in_time_by_dollar_volume():
    syms = ("SPY", "QQQ", "IWM") + ie.CANDIDATES[:25]
    B = synthetic(D=70, syms=syms, seed=10)
    j_late = B.syms.index(ie.CANDIDATES[24])
    B.v[j_late] *= 100                          # the most liquid name ...
    B.o[j_late, :45] = np.nan                   # ... lists late
    F = ie.features(B)
    U = ie.universe(B, F)
    assert U[:3].all()
    month = B.dates.astype("datetime64[M]")
    for t in np.flatnonzero(np.r_[True, month[1:] != month[:-1]]):
        if t >= ie.LOOKBACK:
            assert U[3:, t].sum() == ie.TOP_STOCKS
    first_in = np.flatnonzero(U[j_late])
    assert first_in.size and first_in[0] >= 45 + 15


def test_abnormal_open_filter():
    B = synthetic(D=40, seed=11)
    F = ie.features(B)
    j, d = 0, 30
    B.o[j, d, 0] = F.prev_close[j, d] * 1.2
    F = ie.features(B)
    assert ie.abnormal_open(F)[j, d]


# --- statistics and the whole study -------------------------------------------

def test_stationary_bootstrap_and_pooled_deflation():
    rng = np.random.default_rng(0)
    good = rng.normal(0.002, 0.01, 1500)
    b = ie.stationary_bootstrap(good, rng.normal(0, 0.01, 1500), draws=500)
    assert 0 < b["p05"] < b["p50"] < b["p95"] and b["share_above_0"] > 0.95
    row = {"oos_sharpe": 1.0, "oos_days": 1000, "oos_skew": 0.0, "oos_kurt": 3.0}
    small = ie.pooled_deflation(row, [0.0, 0.5, -0.5], 10, 1.5)
    big = ie.pooled_deflation(row, [0.0, 0.5, -0.5], 677, 2.45)
    assert big["n_total"] == 680 and big["p"] < small["p"] and big["bar_annual"] > small["bar_annual"]


def test_full_run_finds_a_planted_edge_and_counts_46_trials(tmp_path, monkeypatch):
    B = synthetic(D=640, start="2019-01-02", seed=12, drift_after_break=0.00012)
    res = ie.run(B)
    assert len(res["rows"]) == 46
    assert sum(1 for r in res["rows"] if r.get("robustness")) == 12
    assert res["pick"].startswith("ORB")
    assert set(res["verdicts"]) == {"overall", "ORB", "Gap", "VWAP", "Momentum"}
    assert len(res["verdicts"]["overall"]["gates"]) == 6
    assert res["pools"]["global ledger now"]["n_total"] == 677 + 46

    pre = "# W4 pre-registration\n\nFixed text.\n\n## Results\n\nSee below.\n"
    monkeypatch.setattr(ie, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(ie, "REPORTS", tmp_path / "reports")
    (tmp_path / f"{ie.NAME}.md").write_text(pre, encoding="utf-8")
    md = ie.write(res)
    assert "### Every trial" in md and chr(0x2014) not in md
    text = (tmp_path / f"{ie.NAME}.md").read_text(encoding="utf-8")
    assert text.startswith(pre.rstrip())
    ie.write(res)                                  # a second run replaces its own section only
    again = (tmp_path / f"{ie.NAME}.md").read_text(encoding="utf-8")
    assert again.count(ie._begin("synthetic")) == 1 and again.startswith(pre.rstrip())
    js = json.loads((tmp_path / "reports" / ie.NAME / "synthetic-latest.json").read_text(encoding="utf-8"))
    assert js["status"] in ("ok", "bad") and js["source"] == "synthetic"


def test_splice_keeps_other_sections():
    t = ie.splice("# x\n", "proxy", "P1")
    t = ie.splice(t, "alpaca", "A1")
    t = ie.splice(t, "proxy", "P2")
    assert "P2" in t and "P1" not in t and "A1" in t and t.index("P2") < t.index("A1")


def test_main_without_keys_or_data_says_so(monkeypatch, capsys):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    assert ie.main(["--source", "alpaca"]) == 2
    assert "nothing judged" in capsys.readouterr().err
