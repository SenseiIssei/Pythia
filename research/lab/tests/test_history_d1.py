"""D1, the long daily history: the archive fetch before a month, the pre-2020 rows in the panel's format and
segments, the long panel, the overlap checks, the study's drawdown and period measures, and the factories'
new in-sample window.

No network, no lab data. Run from research/lab:  python -m pytest tests/test_history_d1.py
"""

from __future__ import annotations

import io
import json
import math
import zipfile
from datetime import datetime, timezone

import numpy as np
import polars as pl
import pytest

from lab import history
from lab import klines_daily as kd
from lab.experiments import fam_common as fc
from lab.experiments import smallaccount_d1 as d1
from lab.factory import evaluate
from lab.factory import small

DAY = fc.DAY_US


def us(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


def kline_zip(first: str, n: int, price: float = 100.0, step: float = 1.0) -> bytes:
    rows = []
    for i in range(n):
        t = (us(first) + i * DAY) // 1000
        c = price + step * i
        rows.append(f"{t},{c},{c * 1.02},{c * 0.97},{c},10,{t + 86_399_999},{c * 10},5,4,{c * 4},0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("k.csv", "\n".join(rows))
    return buf.getvalue()


@pytest.fixture
def lake(tmp_path, monkeypatch):
    monkeypatch.setattr(kd, "ROOT", tmp_path)
    monkeypatch.setattr(history, "ROOT", tmp_path)
    monkeypatch.setattr(fc, "OUT", tmp_path / "agent")
    monkeypatch.setattr(history, "_FRAME", None)
    return tmp_path


# ---------------------------------------------------------------- the fetch

def test_fetch_until_caches_only_the_early_months_and_no_daily_files(lake, monkeypatch):
    asked = []

    def get(path, timeout=30):
        asked.append(path)
        m = path.rsplit("-1d-", 1)[1][:7]
        return kline_zip(f"{m}-01", 28)

    monkeypatch.setattr(kd, "_get", get)
    df = kd.fetch("AAAUSDT", until="2020-02", months=["2019-12", "2020-01", "2020-02", "2020-03"])
    assert sorted(p.stem for p in kd.cache_dir("AAAUSDT").glob("*.parquet")) == ["2019-12", "2020-01"]
    assert all("/monthly/" in p for p in asked) and len(asked) == 2
    assert df.height == 56 and df["day"].min() == us("2019-12-01")


def test_fetch_long_lists_each_pair_once_and_retries_a_failure(lake):
    listed, got = [], []

    def listing(s):
        listed.append(s)
        if s == "BADUSDT":
            raise OSError("down")
        return {"OLDUSDT": ["2017-07", "2018-01", "2019-12", "2020-05"], "NEWUSDT": ["2021-01"]}[s]

    def getter(s, until, months):
        got.append((s, tuple(months)))

    st = history.fetch_long(["OLDUSDT", "NEWUSDT", "BADUSDT"], until="2020-04", listing=listing, getter=getter)
    assert st["symbols"] == {"OLDUSDT": ["2018-01", "2019-12"], "NEWUSDT": []}
    assert got == [("OLDUSDT", ("2018-01", "2019-12"))]       # before 2017-08 and from 2020-04 left out
    history.fetch_long(["OLDUSDT", "NEWUSDT", "BADUSDT"], until="2020-04", listing=lambda s: [], getter=getter)
    assert listed.count("OLDUSDT") == 1 and listed.count("BADUSDT") == 1
    assert "BADUSDT" in history.read_state()["symbols"]       # listed again on the next run


# ---------------------------------------------------------------- the pre-2020 rows

def daily(first: str, closes) -> pl.DataFrame:
    n = len(closes)
    return pl.DataFrame({"day": [us(first) + i * DAY for i in range(n)], "open": closes,
                         "high": [c * 1.1 for c in closes], "low": [c * 0.9 for c in closes], "close": closes,
                         "volume": [1.0] * n, "qv": [5e6] * n, "n": [9] * n, "taker_qv": [1.0] * n})


def base_frame(rows: dict[str, tuple[str, list[float]]]) -> pl.DataFrame:
    out = []
    for name, (first, closes) in rows.items():
        out.append(pl.DataFrame({"day": [us(first) + i * DAY for i in range(len(closes))], "symbol": name,
                                 "close": closes, "high": closes, "low": closes, "rv": [1e-4] * len(closes),
                                 "qv": [1e6] * len(closes), "n": [24] * len(closes)},
                                schema={"day": pl.Int64, "symbol": pl.Utf8, "close": pl.Float64, "high": pl.Float64,
                                        "low": pl.Float64, "rv": pl.Float64, "qv": pl.Float64, "n": pl.UInt32}))
    return pl.concat(out)


def test_pre_rows_join_the_first_segment_split_like_the_panel_and_keep_its_format():
    base = base_frame({"AAAUSDT": ("2020-01-01", [10.0] * 5), "LUNAUSDT~0": ("2020-01-01", [5.0] * 5),
                       "LUNAUSDT": ("2022-06-01", [1.0] * 5)})
    pre = history.pre_rows(base, {
        "AAAUSDT": daily("2019-12-20", [9.0] * 15),            # overlaps the panel by three days
        "LUNAUSDT": daily("2019-10-01", [4.0] * 10).vstack(daily("2019-12-29", [4.5] * 3)),   # a gap
        "GONEUSDT": daily("2018-01-01", [2.0] * 20 + [30.0] * 5),                           # a tenfold jump
    })
    names = pre.group_by("symbol").agg(n=pl.len(), first=pl.col("day").min(), last=pl.col("day").max())
    got = {r["symbol"]: r for r in names.iter_rows(named=True)}
    assert got["AAAUSDT"]["n"] == 12 and got["AAAUSDT"]["last"] == us("2019-12-31")
    assert got["LUNAUSDT~0"]["n"] == 3                         # joins the old segment, which is LUNAUSDT~0
    assert got["LUNAUSDT~p0"]["n"] == 10
    assert got["GONEUSDT~p0"]["n"] == 20 and got["GONEUSDT"]["n"] == 5   # no panel rows: the last part is plain
    assert pre.columns == history.COLS and pre.schema == base.select(history.COLS).schema
    r = pre.filter(pl.col("symbol") == "AAAUSDT").row(0, named=True)
    assert r["rv"] == pytest.approx(math.log(1.1 / 0.9) ** 2 / (4 * math.log(2))) and r["n"] == 24


def test_pre_rows_keep_a_jump_at_the_join_apart():
    base = base_frame({"AAAUSDT": ("2020-01-01", [1000.0] * 5)})
    pre = history.pre_rows(base, {"AAAUSDT": daily("2019-12-01", [1.0] * 31)})
    assert pre["symbol"].unique().to_list() == ["AAAUSDT~p0"]  # a redenomination is another asset


def write_kline_month(sym: str, month: str, closes) -> None:
    d = kd.cache_dir(sym)
    d.mkdir(parents=True, exist_ok=True)
    kd.parse_zip(kline_zip(f"{month}-01", len(closes), closes[0], 0.0)).write_parquet(d / f"{month}.parquet")


def test_long_frame_and_panel_start_in_2017_and_leave_load_panel_alone(lake):
    base = base_frame({"BTCUSDT": ("2020-01-01", list(np.linspace(7000, 9000, 260))),
                       "ETHUSDT": ("2020-01-01", list(np.linspace(130, 200, 260)))})
    (fc.OUT / "cache").mkdir(parents=True)
    base.write_parquet(fc.OUT / "cache" / "daily_panel.parquet")
    pl.DataFrame(schema={"day": pl.Int64, "base": pl.Utf8, "funding": pl.Float64, "perp_qv": pl.Float64}).write_parquet(
        fc.OUT / "cache" / "perp_daily.parquet")
    n = (us("2020-01-01") - us("2017-08-01")) // DAY
    write_kline_month("BTCUSDT", "2017-08", [4000.0] * n)    # one file of every day to 2019-12-31
    write_kline_month("BTCUSDT", "2020-01", [9.0] * 31)      # the overlap month: the panel's rows win
    history.write_state({"until": history.UNTIL, "symbols": {"BTCUSDT": ["2017-08", "2020-01"], "ETHUSDT": []}})
    f = history.long_frame()
    btc = f.filter(pl.col("symbol") == "BTCUSDT")
    assert btc["day"].min() == us("2017-08-01") and btc.height == 260 + n
    assert btc.filter(pl.col("day") >= us("2020-01-01"))["close"].min() == 7000
    assert (fc.OUT / "cache" / "daily_pre2020.parquet").exists()
    P = history.load_long_panel()
    assert P.days[0] == us("2017-08-01") and P.names == ["BTCUSDT", "ETHUSDT"]
    assert np.isnan(P.px[0, P.col("ETHUSDT")])               # ETH has no early bars here: not alive yet
    assert not P.btc_on[:200].any()                          # 200 days of warm-up before the regime exists
    monkey = fc._PANEL
    try:
        fc._PANEL = None
        short = fc.load_panel()
        assert short.days[0] == us("2020-01-01")
    finally:
        fc._PANEL = monkey


# ---------------------------------------------------------------- the checks

def test_compare_lists_the_closes_further_apart_than_half_a_percent():
    c = history.compare({"2020-01-01": 100.0, "2020-01-02": 101.0, "2020-01-03": 99.0},
                        {"2020-01-01": 100.2, "2020-01-02": 100.0, "2020-01-04": 1.0})
    assert c["days"] == 2 and c["over"] == 1 and c["rows"][0]["day"] == "2020-01-02"
    assert c["max_abs"] == pytest.approx(0.01)


def test_kraken_rows_drop_the_running_day():
    t = us("2025-01-01") // 1_000_000
    payload = {"result": {"XXBTZUSD": [[t, "1", "2", "0.5", "93000.1", "0", "0", 1],
                                       [t + 86_400, "1", "2", "0.5", "94000", "0", "0", 1]], "last": t}}
    assert history.kraken_rows(payload) == {"2025-01-01": 93000.1}


def test_kraken_vs_binance_uses_usd_pairs_and_skips_errors():
    d = {"BTCUSDT": daily("2025-01-01", [100.0, 101.0]), "ETHUSDT": daily("2025-01-01", [10.0, 10.0])}
    t = us("2025-01-01") // 1_000_000

    def get(url):
        if "ETHUSD" in url:
            raise OSError("down")
        return {"result": {"X": [[t, 0, 0, 0, "100.1", 0, 0, 0], [t + 86_400, 0, 0, 0, "103", 0, 0, 0],
                                 [t + 2 * 86_400, 0, 0, 0, "1", 0, 0, 0]]}}

    out = history.kraken_vs_binance(d, get=get)
    assert list(out) == ["BTCUSDT"] and out["BTCUSDT"]["days"] == 2 and out["BTCUSDT"]["over"] == 1


# ---------------------------------------------------------------- the study's measures

def test_drawdown_reports_depth_peak_and_recovery_length():
    days = np.array([us("2018-01-01") + i * DAY for i in range(8)])
    eq = np.array([100, 120, 90, 60, 80, 121, 110, 130.0])
    d = d1.drawdown(eq, days)
    assert d["max_dd"] == pytest.approx(0.5) and d["peak"] == "2018-01-02" and d["trough"] == "2018-01-04"
    assert d["recovered"] == "2018-01-06" and d["days"] == 4
    d = d1.drawdown(np.array([100, 90, 80.0]), days[:3])
    assert d["recovered"] is None and d["days"] == 2


def test_periods_measure_from_the_close_before():
    days = np.array([us("2017-12-31") + i * DAY for i in range(800)])
    eq = 50 * np.exp(np.linspace(0, 0.5, 800))
    p = d1.periods(eq, days, 0, 50.0)
    j = d1.t_of(days, "2018-12-31")
    assert p["2018"]["ret"] == pytest.approx(eq[j] / 50 - 1)
    i, k = d1.t_of(days, "2020-02-29"), d1.t_of(days, "2020-03-31")
    assert p["2020-03"]["ret"] == pytest.approx(eq[k] / eq[i] - 1) and p["2020-03"]["max_dd"] == 0
    assert "2022" not in p                                    # the curve ends before 2022


# ---------------------------------------------------------------- the factories

def test_small_factory_searches_from_2018_and_breeds_only_from_this_window():
    assert small.IS_FROM == "2018-01-01" and small.OOS_FROM == "2024-01-01"
    rows = [{"key": "a"}, {"key": "b", "is_from": "2018-01-01"}, {"key": "c", "is_from": "2020-08-01"}]
    assert [r["key"] for r in small.current(rows)] == ["b"]


def test_weekly_factory_window_starts_2018():
    days = np.array([us("2017-08-17") + i * DAY for i in range(3000)], dtype=np.int64)

    class C:
        T = len(days)

    C.days = days
    w = evaluate.windows(C)
    assert days[np.flatnonzero(w["is"])[0]] == us("2018-01-01")
    assert days[np.flatnonzero(w["oos"])[0]] == us("2024-01-01")
    assert [r["k"] for r in evaluate.current([{"k": 1}, {"k": 2, "is_from": "2018-01-01"}])] == [2]


def test_state_file_is_json_next_to_the_cache(lake):
    history.write_state({"until": "2020-04", "symbols": {"X": []}})
    assert json.loads(history.state_path().read_text())["symbols"] == {"X": []}
    assert history.state_path().parent == kd.cache_dir("X").parent


# ---------------------------------------------------------------- the re-run on a synthetic long panel

def long_panel(T: int = 2700) -> fc.Panel:
    names = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    N = len(names)
    rng = np.random.default_rng(3)
    px = 100 * np.cumprod(1 + rng.normal(0.0008, 0.03, (T, N)), axis=0)
    idx = np.arange(T)[:, None]
    alive = np.ones((T, N), dtype=bool)
    alive[:1090, 2] = False                                    # SOL from 2020-08
    px = np.where(alive, px, np.nan)
    r = np.full((T, N), np.nan)
    r[1:] = px[1:] / px[:-1] - 1
    days = us("2017-08-17") + np.arange(T, dtype=np.int64) * DAY
    return fc.Panel(days=days, names=names, bases=[fc.base_of(n) for n in names], close=px, px=px, high=px, low=px,
                    ret=r, alive=alive, traded=alive.copy(), age=np.where(alive, idx, -1),
                    adv28=np.where(alive, 1e7 * (N - np.arange(N))[None, :], np.nan), sigma=np.full((T, N), 0.03),
                    eligible=alive & (idx >= 60), perp_ok=np.zeros((T, N), dtype=bool), funding=np.zeros((T, N)),
                    btc_on=(np.arange(T) % 150 < 100) & (np.arange(T) >= 200), btc=0)


def etf_series(seed: int, n: int = 2300):
    d = np.arange(np.datetime64("2016-01-01"), np.datetime64("2016-01-01") + np.timedelta64(int(n * 1.45), "D"))
    d = d[(d.view("int64") + 3) % 7 < 5][:n]
    return d, 300 * np.cumprod(1 + np.random.default_rng(seed).normal(0.0004, 0.01, n))


def test_s2_rerun_measures_every_period_and_applies_the_bar(tmp_path):
    from lab.experiments import smallaccount_s2 as s2
    P = long_panel()
    etf = {"SPY": etf_series(1), "GLD": etf_series(2)}
    lad = {k: [(5.0, 1.0), (100.0, 2.0)] for k in ("SPY", "GOLD", "BTC", "ETH", "SOL")}
    v = s2.S2Venue("jupiter", 1.16, ladder=lad)
    t0, t1 = d1.t_of(P.days, d1.START), d1.end_index(P, etf)
    out = d1.run_s2(P, etf, v, {"SPY": 0.003}, t0, t1)
    assert set(out) == set(s2.CANDIDATES)
    for k, r in out.items():
        assert set(r["periods"]) == set(d1.PERIODS) and 0 <= r["dd"]["max_dd"] < 1
        assert r["passes"] == (k not in s2.REFERENCES and r["max_dd"] < 0.20
                               and r["cagr"] >= out["spy_hold"]["cagr"] - 0.01)
        assert ("boot" in r) == (k != "spy_hold") and "s2_window" in r
    assert out["spy_hold"]["periods"]["2018"]["ret"] != 0
    doc = {"generated": "now", "window": ["2017-12-31", "2024-01-01"], "eurusd": 1.16, "drifts": {"SPY": 0.003},
           "coverage": [{"pair": "BTCUSDT", "first": "2017-08-17", "last": "2024-01-01", "days": 2300}],
           "pairs_before_2020": 3, "etf_first": {"SPY": "2016-01-01"}, "etf_last": {"SPY": "2024-01-01"},
           "s2": out, "s1": {}, "checks": {}}
    p = tmp_path / "d1.md"
    p.write_text("# head\n\nhand-written\n\n" + d1.MARKER + "\n\nstale table\n")
    d1.write(doc, p)
    text = p.read_text()
    assert text.startswith("# head\n\nhand-written") and "stale table" not in text and "| tsmom1 |" in text
    assert "\u2014" not in text
