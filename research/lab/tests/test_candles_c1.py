"""C1, the candle store: timeframes built from 1m, the complete flag and point in time, the layers (1d before
the 1m archive), the store's parts, manifest and compaction, the Binance REST fill, 1m candles from Kraken
trades against Binance's, GeckoTerminal and Yahoo from recorded answers (tests/fixtures/candles_c1,
addresses replaced), the health check, the gap report and the candle features in lab.features with a
leakage test. No network, no lab data.

Run from research/lab:  python -m pytest tests/test_candles_c1.py
"""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab import features
from lab.candles import live as L
from lab.candles import store as S
from lab.features import registry as R
from lab.features import store as fstore
from lab.onchain import mints as M

FIX = Path(__file__).parent / "fixtures" / "candles_c1"
MIN, HOUR, DAY = S.MIN, S.HOUR, S.DAY
T0 = S.to_us("2026-10-26")                  # a Monday
CFG = {"rest_max_days": 3, "rest_base": "https://api.binance.com", "tokens": ["SPYx"], "coins": ["SOL"],
       "yahoo": ["SPY"], "yahoo_from": "2026-01-01", "yahoo_1h_days": 30, "yahoo_every_h": 6, "gecko_gap_s": 0,
       "gecko_calls_per_run": 40, "gecko_hour_days": 180, "pool_refresh_days": 7,
       "stale_min": {"binance_rest": 30, "kraken": 30, "gecko": 180}}


def fx(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("no network in tests")
    monkeypatch.setattr(L.urllib.request, "urlopen", refuse)


def minutes(n: int, t0: int = T0, seed: int = 1) -> pl.DataFrame:
    """n 1m bars in the archive's columns (Binance's close time is the end minus 1 ms)."""
    rng = np.random.default_rng(seed)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    o = np.r_[100.0, c[:-1]]
    hi = np.maximum(o, c) * (1 + rng.uniform(0, 0.001, n))
    lo = np.minimum(o, c) * (1 - rng.uniform(0, 0.001, n))
    v = rng.uniform(1, 3, n)
    t = t0 + MIN * np.arange(n, dtype=np.int64)
    return pl.DataFrame({"open_time_us": t, "close_time_us": t + MIN - 1000, "open": o, "high": hi, "low": lo,
                         "close": c, "volume": v, "quote_volume": v * c, "taker_buy_volume": 0.4 * v,
                         "taker_buy_quote_volume": 0.4 * v * c, "trades": rng.integers(1, 50, n)})


def put_archive(root: Path, tf: str, asset: str, df: pl.DataFrame, name: str = "2026-10") -> None:
    d = root / "hist" / "binance_spot" / S.ARCHIVE[tf] / f"symbol={asset}USDT"
    d.mkdir(parents=True, exist_ok=True)
    df.write_parquet(d / f"{name}.parquet")


@pytest.fixture
def lake(tmp_path):
    root = tmp_path / "data"
    put_archive(root, "1m", "TST", minutes(2 * 1440))
    return root


# ---------------------------------------------------------------- timeframes and point in time

def test_every_timeframe_is_built_from_the_1m_bars(lake):
    m = minutes(2 * 1440)
    for tf in ("5m", "15m", "1h", "4h", "1d"):
        b = S.candles("TST", tf, T0, T0 + 2 * DAY, as_of=T0 + 3 * DAY, root=lake)
        p = S.TF[tf]
        assert b.height == 2 * DAY // p and b["complete"].all() and (b["bars"] == p // MIN).all()
        want = (m.with_columns(b_=pl.col("open_time_us") // p * p).group_by("b_", maintain_order=True)
                .agg(pl.col("open").first(), pl.col("high").max(), pl.col("low").min(), pl.col("close").last(),
                     pl.col("volume").sum(), pl.col("quote_volume").sum(), pl.col("trades").sum()))
        for c in ("open", "high", "low", "close", "volume", "quote_volume"):
            np.testing.assert_allclose(b[c].to_numpy(), want[c].to_numpy(), rtol=1e-12)
        assert b["trades"].to_list() == want["trades"].to_list()
        np.testing.assert_allclose(b["taker_buy_share"].to_numpy(), 0.4, rtol=1e-12)
        np.testing.assert_allclose(b["vwap"].to_numpy(), (want["quote_volume"] / want["volume"]).to_numpy(), rtol=1e-12)
        assert set(b["source"]) == {"binance"} and b["close_time_us"].to_list() == (b["open_time_us"] + p).to_list()
    w = S.candles("TST", "1w", T0, T0 + 7 * DAY, as_of=T0 + 3 * DAY, root=lake)
    assert w["open_time_us"].to_list() == [T0] and w["complete"].to_list() == [False]   # the week's data ends on day 2
    assert S.bucket(T0 + 3 * DAY, "1w") == T0 and S.bucket(T0 - 1, "1w") == T0 - 7 * DAY


def test_a_forming_bar_is_never_complete_and_nothing_after_as_of_is_read(lake):
    t = T0 + 10 * HOUR + 30 * MIN
    b = S.candles("TST", "1h", T0, T0 + DAY, as_of=t, root=lake)
    assert b["open_time_us"][-1] == T0 + 10 * HOUR and not b["complete"][-1] and b["complete"][:-1].all()
    last = b.row(-1, named=True)
    m = minutes(2 * 1440).filter(pl.col("open_time_us").is_between(T0 + 10 * HOUR, t, closed="left"))
    assert last["bars"] == 30 and last["close"] == m["close"][-1] and last["high"] == m["high"].max()
    assert S.candles("TST", "1h", T0, T0 + DAY, as_of=t, complete_only=True, root=lake)["complete"].all()
    one = S.candles("TST", "1m", T0, T0 + DAY, as_of=t, root=lake)
    assert one["open_time_us"].max() == t - MIN and one["complete"].all()      # 1m bars are whole or absent


def test_bars_before_the_1m_archive_come_from_the_daily_one(lake):
    d = pl.DataFrame({"day": [T0 - 2 * DAY, T0 - DAY, T0], "open": [90.0, 95.0, 1.0], "high": [99.0, 101.0, 1.0],
                      "low": [89.0, 94.0, 1.0], "close": [95.0, 100.0, 1.0], "volume": [5.0, 6.0, 1.0],
                      "qv": [450.0, 600.0, 1.0], "n": [7, 8, 1], "taker_qv": [200.0, 300.0, 1.0]})
    put_archive(lake, "1d", "TST", d)
    b = S.candles("TST", "1d", T0 - 3 * DAY, T0 + 2 * DAY, as_of=T0 + 3 * DAY, root=lake)
    assert b["open_time_us"].to_list() == [T0 - 2 * DAY, T0 - DAY, T0, T0 + DAY]
    assert b["source"].to_list() == ["binance_1d", "binance_1d", "binance", "binance"]   # the 1m wins where it is
    assert b["close"][1] == 100.0 and b["taker_buy_share"][1] == 0.5 and b["vwap"][1] == 100.0
    assert b["bars"][2] == 1440
    # a 1m archive starting mid-day: that day is the daily archive's bar, whole
    root = lake.parent / "mid"
    put_archive(root, "1m", "TST", minutes(1440 + 600, T0 + 600 * MIN - DAY))
    put_archive(root, "1d", "TST", d)
    b = S.candles("TST", "1d", T0 - 3 * DAY, T0 + 2 * DAY, as_of=T0 + 3 * DAY, root=root)
    assert b.filter(pl.col("open_time_us") == T0 - DAY)["source"].to_list() == ["binance_1d"]
    assert S.default_source("TST", lake) == "binance" and S.default_source("NOPE", lake) is None
    assert S.candles("NOPE", "1h", root=lake).height == 0 and S.candles("TSTUSDT", "1h", T0, T0 + HOUR,
                                                                        as_of=T0 + DAY, root=lake).height == 1
    with pytest.raises(ValueError):
        S.candles("TST", "2h", root=lake)


def test_measures_body_shadows_range_vwap_and_returns(lake):
    b = S.candles("TST", "1h", T0, T0 + 2 * DAY, as_of=T0 + 3 * DAY, root=lake)
    m = S.measures(b)
    r = m.row(30, named=True)
    rng = r["high"] - r["low"]
    assert r["body"] == pytest.approx((r["close"] - r["open"]) / rng)
    assert r["upper"] == pytest.approx((r["high"] - max(r["open"], r["close"])) / rng)
    assert r["lower"] == pytest.approx((min(r["open"], r["close"]) - r["low"]) / rng)
    assert r["upper"] + r["lower"] + abs(r["body"]) == pytest.approx(1.0)
    assert r["range"] == pytest.approx(np.log(r["high"] / r["low"]))
    assert r["vwap_dist"] == pytest.approx(r["close"] / r["vwap"] - 1)
    assert r["ret_4"] == pytest.approx(r["close"] / b["close"][26] - 1)
    assert r["ret_24"] == pytest.approx(r["close"] / b["close"][6] - 1)
    assert m["ret_24"][:24].is_null().all() and m["ret_168"].is_null().all()
    gap = S.measures(b.filter(pl.col("open_time_us") != T0 + 29 * HOUR))       # no return across a missing bar
    assert gap.filter(pl.col("open_time_us") == T0 + 30 * HOUR)["ret_1"].is_null().all()


# ---------------------------------------------------------------- the store

def test_parts_the_newest_row_wins_compaction_and_the_manifest(tmp_path):
    root = tmp_path / "d"
    sep, octo = S.to_us("2026-09-30T23:58"), S.to_us("2026-10-27")
    rows = minutes(4, sep).drop("close_time_us").with_columns(close_time_us=pl.col("open_time_us") + MIN)
    assert S.write("binance_rest", "TST", "1m", rows, now=octo, root=root) == 4
    fixed = rows.tail(1).with_columns(close=pl.lit(123.0))
    S.write("binance_rest", "TST", "1m", fixed, now=octo + 1, root=root)
    d = S.key_dir(root / "candles", "binance_rest", "TST", "1m")
    assert len(list(d.glob("2026-09/part-*.parquet"))) == 1 and len(list(d.glob("2026-10/part-*.parquet"))) == 2
    r = S.read_store("binance_rest", "TST", "1m", root=root)
    assert r.height == 4 and r["close"][-1] == 123.0
    e = S.read_manifest(root)["markets"]["binance_rest/TST/1m"]
    assert e["rows"] == 4 and e["first_us"] == sep and e["last_end_us"] == sep + 4 * MIN
    assert e["months"]["2026-10"]["parts"] == 2 and not e["months"]["2026-09"]["final"]
    res = S.compact(now=octo, root=root, log=lambda *_: None)
    assert res == {"merged_months": 2, "final_months": 1}
    assert not list(d.glob("*/part-*.parquet")) and (d / "2026-09.parquet").exists() and (d / "2026-10.parquet").exists()
    assert S.read_store("binance_rest", "TST", "1m", root=root).equals(r)
    e = S.read_manifest(root)["markets"]["binance_rest/TST/1m"]
    assert e["months"]["2026-09"]["final"] and not e["months"]["2026-10"]["final"] and e["rows"] == 4
    S.write("binance_rest", "TST", "1m", fixed.with_columns(close=pl.lit(7.0)), now=octo + 2, root=root)
    assert S.read_store("binance_rest", "TST", "1m", root=root)["close"][-1] == 7.0   # a part after the month file
    with pytest.raises(ValueError):
        S.write("nasdaq", "TST", "1m", rows, root=root)


# ---------------------------------------------------------------- Binance REST

def test_binance_rows_drop_the_forming_bar():
    p = fx("binance_klines_btc.json")
    last_open = p[-1][0] * 1000
    r = L.binance_rows(p, last_open + 30_000_000)
    assert r.height == len(p) - 1 and r["close_time_us"].max() == last_open
    assert r["taker_buy_quote_volume"][0] == float(p[0][10]) and r["trades"][0] == p[0][8]
    assert L.binance_rows(p, last_open + MIN).height == len(p)


def test_the_rest_fill_starts_where_the_archive_ends_and_the_archive_wins(lake):
    now = T0 + 2 * DAY + 5 * MIN + 20_000_000
    calls = []

    def get(url):
        calls.append(url)
        start = int(url.split("startTime=")[1].split("&")[0]) * 1000
        return [[(start + i * MIN) // 1000, "1", "2", "0.5", "1.5", "10", (start + (i + 1) * MIN) // 1000 - 1, "15",
                 3, "4", "6", "0"] for i in range(10)]               # bars not closed by the fetch are dropped

    res = L.fill_binance(get, ["TST"], now, CFG, lake)
    assert f"startTime={(T0 + 2 * DAY) // 1000}" in calls[0] and res["rows"]["TST"] == 5 and not res["errors"]
    st = S.read_store("binance_rest", "TST", "1m", root=lake)
    assert st["open_time_us"].to_list() == [T0 + 2 * DAY + i * MIN for i in range(5)]
    L.fill_binance(get, ["TST"], now + 2 * MIN, CFG, lake)
    assert f"startTime={(T0 + 2 * DAY + 5 * MIN) // 1000}" in calls[-1]
    b = S.candles("TST", "1h", T0 + 47 * HOUR, T0 + 49 * HOUR, as_of=now + 2 * MIN, root=lake)
    assert b["source"].to_list() == ["binance", "binance_rest"] and b["complete"].to_list() == [True, False]
    assert b["close"][1] == 1.5 and b["bars"][1] == 7
    # an overlap: the archive's row wins over the REST one
    S.write("binance_rest", "TST", "1m", st.head(1).with_columns(open_time_us=pl.lit(T0), close=pl.lit(9e9)), root=lake)
    assert S.candles("TST", "1m", T0, T0 + MIN, as_of=now, root=lake)["close"][0] != 9e9
    # never further back than rest_max_days
    calls.clear()
    L.fill_binance(get, ["NEW"], now, {**CFG, "rest_max_days": 1}, lake)
    assert f"startTime={(now - DAY) // 1000}" in calls[0]


# ---------------------------------------------------------------- Kraken

def trades(rows) -> pl.DataFrame:
    return pl.DataFrame(rows, schema={"ts_recv_us": pl.Int64, "ts_exch_us": pl.Int64, "symbol": pl.String,
                                      "side": pl.String, "price": pl.Float64, "qty": pl.Float64,
                                      "ord_type": pl.String, "trade_id": pl.Int64}, orient="row")


def test_kraken_minutes_split_buy_and_sell():
    t = T0 + 5 * MIN
    tr = trades([(t + 1, t, "TST/USD", "buy", 10.0, 1.0, "limit", 1), (t + 11, t + 10, "TST/USD", "sell", 12.0, 2.0, "market", 2),
                 (t + 21, t + 20, "TST/USD", "buy", 9.0, 1.0, "limit", 3), (t + MIN + 1, t + MIN, "TST/USD", "sell", 11.0, 1.0, "limit", 4),
                 (t + 5, t + 4, "TST/EUR", "buy", 1.0, 1.0, "limit", 5)])
    m = L.kraken_minutes(tr)
    a = m.row(0, named=True)
    assert m.height == 2 and set(m["asset"]) == {"TST"}
    assert (a["open"], a["high"], a["low"], a["close"], a["trades"]) == (10.0, 12.0, 9.0, 9.0, 3)
    assert a["volume"] == 4.0 and a["quote_volume"] == 43.0 and a["taker_buy_volume"] == 2.0 and a["taker_buy_quote_volume"] == 19.0
    assert a["open_time_us"] == t and a["close_time_us"] == t + MIN
    assert m.row(1, named=True)["taker_buy_volume"] == 0.0


def put_trades(root: Path, day: str, df: pl.DataFrame, name: str) -> Path:
    d = root / "kraken" / "trades" / f"date={day}"
    d.mkdir(parents=True, exist_ok=True)
    df.write_parquet(d / name)
    return d


def test_kraken_build_today_past_days_and_the_disagreement_flag(lake):
    m = minutes(2 * 1440)
    px = dict(zip(m["open_time_us"].to_list(), m["close"].to_list()))
    t1 = T0 + DAY + 10 * HOUR                                     # today is the archive's second day
    rows = []
    for i in range(6):                                            # one trade a minute at Binance's close, minute 3 off by 1 %
        t = t1 + i * MIN + 30_000_000
        rows.append((t + 1000, t, "TST/USD", "buy", px[t1 + i * MIN] * (1.01 if i == 3 else 1.0), 1.0, "limit", i))
    put_trades(lake, "2026-10-27", trades(rows), "part-000001-a.parquet")
    now = t1 + 7 * MIN
    state = {}
    res = L.build_kraken(now, state, lake)
    k = S.read_store("kraken", "TST", "1m", root=lake)
    # trades were received up to minute 5 + 30 s: minutes ending a minute before that are built
    assert k["open_time_us"].to_list() == [t1 + i * MIN for i in range(4)] and res["rows"] == 4
    np.testing.assert_allclose(k["ref_dev_bps"].to_numpy(), [0, 0, 0, 100], atol=1e-6)
    assert res["flagged"] == 1 and S.disagreements("TST", root=lake)["open_time_us"].to_list() == [t1 + 3 * MIN]
    more = [(t1 + 6 * MIN + 30_000_000 + 1000, t1 + 6 * MIN + 30_000_000, "TST/USD", "sell", px[t1 + 6 * MIN], 2.0, "limit", 9),
            (t1 + 8 * MIN, t1 + 8 * MIN - 1, "TST/USD", "sell", 1.0, 2.0, "limit", 10)]
    put_trades(lake, "2026-10-27", trades(more), "part-000002-b.parquet")
    L.build_kraken(t1 + 9 * MIN, state, lake)
    k = S.read_store("kraken", "TST", "1m", root=lake)
    assert k["open_time_us"].to_list() == [t1 + i * MIN for i in range(7)]
    # the day after: the finished day is rebuilt whole once, again only when its files change
    d = put_trades(lake, "2026-10-27", trades(rows + more), "day.parquet")
    res = L.build_kraken(T0 + 2 * DAY + HOUR, state, lake)
    assert res["rows"] == 8 and state["kraken"]["days"]["2026-10-27"]
    assert L.build_kraken(T0 + 2 * DAY + 2 * HOUR, state, lake)["rows"] == 0
    (d / "day.parquet").unlink()
    trades(rows).write_parquet(d / "day.parquet")
    assert L.build_kraken(T0 + 2 * DAY + 3 * HOUR, state, lake)["rows"] == 6
    b = S.candles("TST", "1h", t1, t1 + HOUR, source="kraken", as_of=T0 + 3 * DAY, root=lake)
    assert b["source"].to_list() == ["kraken"] and b["ref_dev_bps"][0] < -5000   # the hour shows its worst minute (7)


# ---------------------------------------------------------------- GeckoTerminal

def pools_answer(mint: str) -> dict:
    def pool(addr, base, quote, liq):
        return {"attributes": {"address": addr, "reserve_in_usd": str(liq)},
                "relationships": {"base_token": {"data": {"id": f"solana_{base}"}},
                                  "quote_token": {"data": {"id": f"solana_{quote}"}}}}
    return {"data": [pool("POOL_SMALL", mint, M.USDC.mint, 1_000), pool("POOL_DEEP", M.SOL.mint, mint, 50_000),
                     pool("POOL_OTHER", mint, "SOMETHING_ELSE", 9_000_000)]}


def test_the_deepest_usdc_or_sol_pool_and_gecko_rows():
    assert L.pick_pool(pools_answer("MINT_X"), "MINT_X") == {"pool": "POOL_DEEP", "side": "quote", "liquidity_usd": 50_000.0}
    assert L.pick_pool({"data": []}, "MINT_X") is None
    p = fx("gecko_ohlcv_hour.json")
    newest = 1793095200 * 1_000_000
    r = L.gecko_rows(p, "1h", newest + 30 * MIN, liquidity=400_000.0)       # the newest bar is still forming
    assert r["open_time_us"].to_list() == [newest - 2 * HOUR, newest - HOUR]
    assert r["liquidity_usd"].to_list() == [None, 400_000.0] and r["volume"].is_null().all()
    assert r["quote_volume"][1] == pytest.approx(41722.8365950623)
    assert L.gecko_rows(p, "1h", newest + HOUR)["open_time_us"].max() == newest


class FakeGecko:
    def __init__(self, now: int, history_from: int):
        self.now, self.history_from, self.urls = now, history_from, []
        self.limit_after = None

    def __call__(self, url: str):
        self.urls.append(url)
        if self.limit_after is not None and len(self.urls) > self.limit_after:
            raise L.RateLimited("api.geckoterminal.com HTTP 429")
        if "/tokens/" in url:
            return pools_answer(url.split("/tokens/")[1].split("/")[0])
        if "/pools/multi/" in url:
            return {"data": [{"attributes": {"address": "POOL_DEEP", "reserve_in_usd": "52000.5"}}]}
        tf = "1h" if "/ohlcv/hour" in url else "1d"
        p = S.TF[tf] // 1_000_000
        limit = int(url.split("limit=")[1].split("&")[0])
        before = int(url.split("before_timestamp=")[1]) if "before_timestamp=" in url else self.now // 1_000_000
        top = before // p * p
        ts = [t for t in range(top, top - limit * p, -p) if t * 1_000_000 >= self.history_from]
        if "before_timestamp=" in url:
            ts = [t for t in ts if t < before]
        return {"data": {"attributes": {"ohlcv_list": [[t, 1.0, 2.0, 0.5, 1.5, 100.0] for t in ts]}}}


def test_gecko_run_pools_bars_liquidity_backfill_and_backoff(tmp_path):
    root, now = tmp_path / "d", T0 + 30 * MIN
    csv = tmp_path / "tokens.csv"
    csv.write_text("symbol,mint,kind\nSPYx,MINT_SPYX,sp500\nNVDAx,MINT_NVDAX,share\n")
    g = FakeGecko(now, T0 - 60 * DAY)
    state = {}
    res = L.run_gecko(g, CFG, state, now, root, csv)
    assert not res["errors"] and set(state["gecko"]["pools"]) == {"SOL", "SPYx"}
    h = S.read_store("gecko", "SPYx", "1h", root=root)
    assert h["open_time_us"].max() == T0 - HOUR and h["liquidity_usd"].drop_nulls().to_list() == [52000.5]
    assert S.read_store("gecko", "SOL", "1d", root=root)["open_time_us"].max() == T0 - DAY
    for _ in range(6):                                            # the backfill walks back to the API's first bar
        L.run_gecko(g, CFG, state, now, root, csv)
    assert state["gecko"]["backfilled"] == {"SOL": True, "SPYx": True}
    h = S.read_store("gecko", "SPYx", "1h", root=root)
    assert h["open_time_us"].min() == T0 - 60 * DAY and h.height == 60 * 24 and state["gecko"]["backfilled"]["SPYx"]
    n = len(g.urls)
    L.run_gecko(g, CFG, state, now + 10 * MIN, root, csv)         # nothing new closed: no calls
    assert len(g.urls) == n
    L.run_gecko(g, CFG, state, now + HOUR, root, csv)             # one new hour each, pools cached
    assert len(g.urls) == n + 3 and S.read_store("gecko", "SPYx", "1h", root=root)["open_time_us"].max() == T0
    g.limit_after = len(g.urls)
    res = L.run_gecko(g, CFG, state, now + 2 * HOUR, root, csv)
    assert "429" in res["errors"][0] and state["gecko"]["backoff"]["secs"] == 120
    res = L.run_gecko(g, CFG, state, now + 2 * HOUR + 60_000_000, root, csv)
    assert "backing off" in res["errors"][0] and len(g.urls) == n + 4
    g.limit_after = None
    L.run_gecko(g, CFG, state, now + 2 * HOUR + 3 * MIN, root, csv)
    assert "backoff" not in state["gecko"]
    c = S.candles("SPYx", "4h", T0 - DAY, T0 + 2 * HOUR, as_of=now + 3 * HOUR, root=root)
    assert set(c["source"]) == {"gecko"} and c["complete"].to_list() == [True] * 6 + [False] and c["vwap"].is_null().all()
    assert S.default_source("SPYx", root) == "gecko"


def test_gecko_work_puts_empty_first_then_the_cursor_then_the_stalest():
    now = T0
    due = {"1h/SOL": now - 2 * HOUR, "1h/WIF": 0, "1d/SOL": now - 3 * DAY, "1d/WIF": 0, "1h/BTC": now - 5 * HOUR,
           "1h/ETH": now - HOUR}
    assert L.gecko_work(due, ["back/SOL"], [], now) == ["1h/WIF", "1d/WIF", "1h/BTC", "1d/SOL", "1h/SOL", "1h/ETH",
                                                        "back/SOL"]
    assert L.gecko_work(due, ["back/SOL"], ["1h/ETH", "back/SOL", "1h/SOL"], now) == \
        ["1h/WIF", "1d/WIF", "1h/ETH", "1h/SOL", "1h/BTC", "1d/SOL", "back/SOL"]


def test_gecko_429_stops_the_run_saves_the_cursor_and_the_next_run_resumes(tmp_path):
    root, now = tmp_path / "d", T0 + 30 * MIN
    csv = tmp_path / "tokens.csv"
    csv.write_text("symbol,mint,kind\nSPYx,MINT_SPYX,sp500\nQQQx,MINT_QQQX,nasdaq\n")
    cfg = {**CFG, "tokens": ["SPYx", "QQQx"], "coins": ["SOL"]}
    g = FakeGecko(now, T0 - 10 * DAY)
    state = {}
    old = FakeGecko(now - 3 * HOUR, T0 - 10 * DAY)                 # SOL 1h has bars to 3 h ago, every other is empty
    S.write("gecko", "SOL", "1h", L.gecko_rows(old(L._ohlcv_url({"pool": "P", "side": "base"}, "1h", 3)), "1h",
                                               now - 3 * HOUR), now, root)
    g.limit_after = 3 + 1 + 2                                        # 3 pool lookups, the liquidity, 2 bars
    res = L.run_gecko(g, cfg, state, now, root, csv)
    assert res["stopped"] == "HTTP 429" and res["fetched"] == ["1h/SPYx", "1h/QQQx"]
    assert res["left"] == ["1d/SOL", "1d/SPYx", "1d/QQQx", "1h/SOL", "back/SOL", "back/SPYx", "back/QQQx"]
    cur = json.loads((root / "candles" / L.CURSOR).read_text())
    assert cur["left"] == res["left"] and cur["stopped"] == "HTTP 429"
    said = L.gecko_said(res)
    assert "2 pools fetched" in said and "3 pools left (7 items: 1d/SOL" in said and "stopped on HTTP 429, cursor saved" in said
    assert chr(0x2014) not in said
    g.limit_after, n = None, len(g.urls)
    state["gecko"].pop("backoff")
    res = L.run_gecko(g, cfg, state, now + 5 * MIN, root, csv)      # resumes at 1d/SOL, no lookup again
    ohlcv = [u for u in g.urls[n:] if "/ohlcv/" in u]
    assert "/ohlcv/day" in ohlcv[0] and "/pools/multi/" in g.urls[n] and not any("/tokens/" in u for u in g.urls[n:])
    assert res["fetched"][:4] == ["1d/SOL", "1d/SPYx", "1d/QQQx", "1h/SOL"] and res["stopped"] is None
    assert res["left"] == [] and json.loads((root / "candles" / L.CURSOR).read_text())["left"] == []
    assert S.read_manifest(root)["markets"]["gecko/QQQx/1d"]["last_end_us"] == T0
    assert "not stopped" in L.gecko_said(res)


def test_gecko_run_stops_on_its_time_budget_and_keeps_the_rest(tmp_path):
    root, now = tmp_path / "d", T0 + 30 * MIN
    csv = tmp_path / "tokens.csv"
    csv.write_text("symbol,mint,kind\nSPYx,MINT_SPYX,sp500\n")
    clock = [0.0]
    g = FakeGecko(now, T0 - 10 * DAY)

    def get(url):
        clock[0] += 50.0
        return g(url)
    get.clock = lambda: clock[0]
    res = L.run_gecko(get, {**CFG, "gecko_run_s": 200}, {}, now, root, csv)  # 2 lookups and the liquidity: 150 s
    assert res["stopped"] == "the run's time budget" and res["fetched"] == ["1h/SOL"]
    assert res["left"][0] == "1h/SPYx" and json.loads((root / "candles" / L.CURSOR).read_text())["left"] == res["left"]


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_markets_run_paces_gecko_backs_off_once_on_429_then_stops(tmp_path, monkeypatch):
    root, now = tmp_path / "d", T0 + 30 * MIN
    csv = tmp_path / "tokens.csv"
    csv.write_text("symbol,mint,kind\nSPYx,MINT_SPYX,sp500\n")
    monkeypatch.setattr(S, "config", lambda: {**CFG, "gecko_gap_s": 2.5, "gecko_retry_s": 60, "yahoo": []})
    clock, slept, urls = [0.0], [], []
    monkeypatch.setattr(L.time, "sleep", lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)))
    monkeypatch.setattr(L.time, "monotonic", lambda: clock[0])
    g = FakeGecko(now, T0 - 10 * DAY)

    def urlopen(req, timeout):
        urls.append(req.full_url)
        if len(urls) >= 5:                                            # the 5th call and after: 429, Retry-After 7
            raise urllib.error.HTTPError(req.full_url, 429, "too many", {"Retry-After": "7"}, None)
        return Resp(json.dumps(g(req.full_url)).encode())
    monkeypatch.setattr(L.urllib.request, "urlopen", urlopen)
    res = L.run_markets(now=now, root=root, tokens_csv=csv)
    assert slept == [2.5] * 4 + [7.0] and len(urls) == 6 and urls[4] == urls[5]
    assert res["gecko_stopped"] == "HTTP 429" and res["gecko_fetched"] == 1 and res["gecko_left"] > 0
    assert "stopped on HTTP 429, cursor saved" in res["said"] and "after one backoff" in res["errors"][0]
    cur = json.loads((root / "candles" / L.CURSOR).read_text())
    assert cur["left"][0] == "1h/SPYx" and len(cur["left"]) == res["gecko_left"] and cur["stopped"] == "HTTP 429"


# ---------------------------------------------------------------- Yahoo

def test_yahoo_rows_daily_at_utc_midnight_and_hourly():
    p = fx("yahoo_spy_1d.json")
    ts = p["chart"]["result"][0]["timestamp"]
    last_day = ts[-1] * 1_000_000 // DAY * DAY
    d = L.yahoo_rows(p, "1d", last_day + DAY)
    assert d.height == len(ts) and d["open_time_us"].max() == last_day and (d["open_time_us"] % DAY == 0).all()
    assert d["close"][-1] == pytest.approx(p["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1])
    assert L.yahoo_rows(p, "1d", last_day + 20 * HOUR).height == len(ts) - 1     # known from the next UTC midnight
    h = L.yahoo_rows(fx("yahoo_spy_1h.json"), "1h", S.to_us("2026-10-27"))
    assert h.height >= 10 and ((h["close_time_us"] - h["open_time_us"]) == HOUR).all()
    assert L.yahoo_rows({"chart": {"result": None}}, "1d", 0).height == 0


def test_yahoo_run_every_few_hours(tmp_path):
    root, urls = tmp_path / "d", []
    now = S.to_us("2026-10-27T10:00")

    def get(url):
        urls.append(url)
        return fx("yahoo_spy_1d.json") if "interval=1d" in url else fx("yahoo_spy_1h.json")

    state = {}
    res = L.run_yahoo(get, CFG, state, now, root)
    assert res["rows"] > 10 and len(urls) == 2 and f"period1={S.to_us('2026-01-01') // 1_000_000}" in urls[0]
    assert "interval=60m" in urls[1]
    assert L.run_yahoo(get, CFG, state, now + HOUR, root)["skipped"] and len(urls) == 2
    L.run_yahoo(get, CFG, state, now + 7 * HOUR, root)
    last = S.read_manifest(root)["markets"]["yahoo/SPY/1d"]["last_end_us"]
    assert f"period1={(last - 10 * DAY) // 1_000_000}" in urls[2]
    assert S.candles("SPY", "1w", "2026-10-01", as_of=now, root=root)["source"].to_list()[-1] == "yahoo"


# ---------------------------------------------------------------- http, health, the gap report

def test_http_paces_budgets_and_stops_a_host_after_a_429():
    clock, slept = [0.0], []

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout):
        if "bad" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 429, "too many", {}, None)
        return Resp(b"[1]")

    h = L.Http(gaps={"a.example": 5.0}, budgets={"a.example": 2}, sleep=lambda s: (slept.append(s), clock.__setitem__(0, clock[0] + s)),
               clock=lambda: clock[0], opener=opener)
    assert h("https://a.example/x") == [1] and h("https://a.example/y") == [1] and slept == [5.0]
    with pytest.raises(L.RateLimited):
        h("https://a.example/z")
    with pytest.raises(L.RateLimited):
        h("https://b.example/bad")
    with pytest.raises(L.RateLimited):
        h("https://b.example/fine")


def test_health_is_red_when_a_live_source_is_stale(tmp_path, monkeypatch):
    root = tmp_path / "d"
    monkeypatch.setattr(S, "config", lambda: CFG)
    now = T0 + DAY
    ok, msg = S.health(now, root)
    assert not ok and "no candles yet" in msg
    bar = lambda t, p: pl.DataFrame({"open_time_us": [t], "close_time_us": [t + p], "open": [1.0], "high": [1.0],
                                     "low": [1.0], "close": [1.0]})
    S.write("binance_rest", "BTC", "1m", bar(now - 2 * MIN, MIN), now, root)
    S.write("binance_rest", "ETH", "1m", bar(now - HOUR, MIN), now, root)
    S.write("kraken", "BTC", "1m", bar(now - 3 * MIN, MIN), now, root)
    S.write("gecko", "SPYx", "1h", bar(now - 2 * HOUR, HOUR), now, root)
    ok, msg = S.health(now, root)
    assert not ok and "gecko 1h: 1 of 2 pools over 3 h (SOL none)" in msg and "gecko 1d: 2 of 2 pools" in msg
    for a in ("SPYx", "SOL"):
        S.write("gecko", a, "1h", bar(now - 2 * HOUR, HOUR), now, root)
        S.write("gecko", a, "1d", bar(now - DAY - 2 * HOUR, DAY), now, root)
    ok, msg = S.health(now, root)
    assert ok and "stale: ETH" in msg and "gecko 1h 2 pools" in msg and "gecko 1d 2 pools" in msg
    ok, msg = S.health(now + 40 * MIN, root)
    assert not ok and "binance_rest 1m: newest bar" in msg and "kraken" in msg


def test_health_is_red_per_pool_not_on_the_newest_one(tmp_path, monkeypatch):
    root, now = tmp_path / "d", T0 + DAY
    monkeypatch.setattr(S, "config", lambda: {**CFG, "tokens": ["SPYx", "QQQx"], "coins": ["SOL"]})
    bar = lambda t, p: pl.DataFrame({"open_time_us": [t], "close_time_us": [t + p], "open": [1.0], "high": [1.0],
                                     "low": [1.0], "close": [1.0]})
    S.write("binance_rest", "BTC", "1m", bar(now - 2 * MIN, MIN), now, root)
    S.write("kraken", "BTC", "1m", bar(now - 2 * MIN, MIN), now, root)
    for a in ("SPYx", "SOL"):                                        # SOL fresh, SPYx 5 h late, QQQx never fetched
        S.write("gecko", a, "1h", bar(now - (HOUR if a == "SOL" else 5 * HOUR), HOUR), now, root)
        S.write("gecko", a, "1d", bar(now - DAY - (0 if a == "SOL" else 3 * DAY), DAY), now, root)
    S.write("gecko", "JUP", "1h", bar(now - HOUR, HOUR), now, root)   # in the store, not configured: still watched
    ok, msg = S.health(now, root)
    assert not ok and "gecko 1h: 2 of 4 pools over 3 h (SPYx 4 h, QQQx none)" in msg
    assert "gecko 1d: 3 of 4 pools over 48 h (SPYx 72 h, QQQx none, JUP none)" in msg and "SOL" not in msg


def test_gaps_and_the_report(lake):
    t = np.array([0, 1, 2, 5, 6, 10], dtype=np.int64) * HOUR
    g = S.gaps(t, "1h")
    assert g["missing"] == 5 and g["gaps"] == 2 and g["bars"] == 6 and "(3)" in g["largest"][0]
    week = np.array([0, 1, 4, 5, 6, 7, 8, 11], dtype=np.int64) * DAY        # weekends are not gaps for Yahoo
    assert S.gaps(week, "1d", session=True)["missing"] == 0 and S.gaps(week, "1d")["missing"] == 4
    assert S.gaps(np.empty(0, np.int64), "1m")["bars"] == 0
    S.write("kraken", "TST", "1m", minutes(3).with_columns(close_time_us=pl.col("open_time_us") + MIN,
                                                           ref_dev_bps=pl.Series([1.0, -60.0, 2.0])), root=lake)
    cov = S.coverage(lake, log=lambda *_: None)
    assert ("kraken", "1m") in {(r["source"], r["timeframe"]) for r in cov}
    dis = S.disagreement_summary(lake)
    assert dis == [{"asset": "TST", "minutes": 3, "flagged": 1, "median_abs_bps": 2.0, "worst_bps": 60.0,
                    "worst_at": "2026-10-26 00:01"}]
    md = S.report(cov + [{"market": "TSTUSDT", "source": "binance", "asset": "TST", "timeframe": "1m", **S.gaps(t, "1h")}],
                  dis, T0)
    assert "| TSTUSDT | binance | 1m | 1970-01-01 00:00 | 1970-01-01 10:00 | 6 | 5 | 2 |" in md and "| TST | 3 | 1 |" in md
    assert chr(0x2014) not in md


def test_the_markets_config_and_mints():
    cfg = json.loads(S.CONFIG.read_text())
    assert {"SPYx", "QQQx", "PAXG"} <= set(cfg["tokens"]) and {"SPY", "QQQ", "GLD"} <= set(cfg["yahoo"])
    assert "PAXG" in cfg["binance_extra"] and cfg["gecko_gap_s"] >= 2 and cfg["gecko_calls_per_run"] <= 60
    ms = L.mints(cfg)
    assert set(cfg["coins"]) <= set(ms) and {"SPYx", "QQQx", "PAXG"} <= set(ms)


# ---------------------------------------------------------------- the features

@pytest.fixture
def flake(tmp_path, monkeypatch):
    root = tmp_path / "data"
    put_archive(root, "1m", "BTC", minutes(9 * 1440, T0 - 7 * DAY))
    monkeypatch.setattr(fstore, "ROOT", root)
    monkeypatch.setattr(fstore, "OUT", tmp_path / "out" / "features")
    R.clear()
    yield root
    R.clear()


def test_candle_features_are_registered_and_computed_from_the_bars(flake):
    names = [n for n in features.names() if n.startswith("cdl_")]
    assert {"cdl_body", "cdl_upper", "cdl_lower", "cdl_range", "cdl_taker", "cdl_vwap_dist", "cdl_ret",
            "cdl_ret_4h", "cdl_ret_1d", "cdl_ret_1w", "cdl_range_rel"} | {
        f"cdl_{s}_{w}" for s in ("body", "upper", "lower", "range") for w in ("4h", "1d", "1w")} == set(names)
    t = T0 + DAY + 5 * HOUR
    f = features.frame(names, ["BTC", "ETH"], [t], "1h").filter(pl.col("asset") == "BTC").row(0, named=True)
    b = S.measures(S.candles("BTC", "1h", T0 - 7 * DAY, t, as_of=t, root=flake))
    last = b.row(-1, named=True)
    assert last["close_time_us"] == t
    for n, c in (("cdl_body", "body"), ("cdl_upper", "upper"), ("cdl_lower", "lower"), ("cdl_range", "range"),
                 ("cdl_taker", "taker_buy_share"), ("cdl_vwap_dist", "vwap_dist"), ("cdl_ret", "ret_1"),
                 ("cdl_ret_4h", "ret_4"), ("cdl_ret_1d", "ret_24"), ("cdl_ret_1w", "ret_168")):
        assert f[n] == pytest.approx(last[c]), n
    d = features.frame(["cdl_ret", "cdl_ret_1w"], ["BTC"], [T0 + DAY], "1d").row(0, named=True)
    days = S.candles("BTC", "1d", T0 - 7 * DAY, T0 + DAY, as_of=T0 + DAY, root=flake)
    assert d["cdl_ret"] == pytest.approx(days["close"][-1] / days["close"][-2] - 1)
    assert d["cdl_ret_1w"] == pytest.approx(days["close"][-1] / days["close"][0] - 1)


def test_candle_features_do_not_leak(flake):
    names = [n for n in features.names() if n.startswith("cdl_")]
    t = T0 + DAY + 5 * HOUR
    before = features.frame(names, ["BTC"], [t - HOUR, t], "1h")
    f = next((flake / "hist" / "binance_spot" / "klines_1m" / "symbol=BTCUSDT").glob("*.parquet"))
    m = pl.read_parquet(f)
    late = pl.col("open_time_us") >= t
    m.with_columns(*[pl.when(late).then(pl.col(c) * 3).otherwise(pl.col(c)).alias(c)
                     for c in ("open", "high", "low", "close", "volume", "quote_volume")]).write_parquet(f)
    R.clear()
    after = features.frame(names, ["BTC"], [t - HOUR, t], "1h")
    assert before.equals(after)
    assert not features.frame(names, ["BTC"], [t + 2 * HOUR], "1h").equals(
        before.with_columns(ts_us=pl.lit(t + 2 * HOUR)))


def test_window_candles_are_the_last_bars_as_one(flake):
    t = T0 + DAY + 5 * HOUR
    names = [f"cdl_{s}_{w}" for s in ("body", "upper", "lower", "range") for w in ("4h", "1d", "1w")] + ["cdl_range_rel"]
    f = features.frame(names, ["BTC"], [t], "1h").row(0, named=True)
    b = S.candles("BTC", "1h", T0 - 7 * DAY, t, as_of=t, root=flake)
    for w, k in (("4h", 4), ("1d", 24), ("1w", 168)):
        x = b.tail(k)
        o, h, lo, c = x["open"][0], x["high"].max(), x["low"].min(), x["close"][-1]
        assert f[f"cdl_body_{w}"] == pytest.approx((c - o) / (h - lo)), w
        assert f[f"cdl_upper_{w}"] == pytest.approx((h - max(o, c)) / (h - lo)), w
        assert f[f"cdl_lower_{w}"] == pytest.approx((min(o, c) - lo) / (h - lo)), w
        assert f[f"cdl_range_{w}"] == pytest.approx(np.log(h / lo)), w
        assert f[f"cdl_upper_{w}"] + f[f"cdl_lower_{w}"] + abs(f[f"cdl_body_{w}"]) == pytest.approx(1.0)
    r = np.log(b["high"] / b["low"]).to_numpy()
    assert f["cdl_range_rel"] == pytest.approx(r[-1] / r[-20:].mean())
    d = features.frame(["cdl_body_1w", "cdl_range_1w", "cdl_body_4h"], ["BTC"], [T0 + DAY], "1d").row(0, named=True)
    days = S.candles("BTC", "1d", T0 - 7 * DAY, T0 + DAY, as_of=T0 + DAY, root=flake).tail(7)
    h, lo = days["high"].max(), days["low"].min()
    assert d["cdl_body_1w"] == pytest.approx((days["close"][-1] - days["open"][0]) / (h - lo))
    assert d["cdl_range_1w"] == pytest.approx(np.log(h / lo)) and d["cdl_body_4h"] is None
    # fewer bars than the window: no window candle, the single-bar measures still there
    g = features.frame(["cdl_body_1w", "cdl_body"], ["BTC"], [T0 - 7 * DAY + 100 * HOUR], "1h").row(0, named=True)
    assert g["cdl_body_1w"] is None and g["cdl_body"] is not None


def test_window_candles_do_not_leak_daily(flake):
    names = ["cdl_body_1w", "cdl_upper_1w", "cdl_lower_1w", "cdl_range_1w", "cdl_range_rel", "cdl_body"]
    t = T0 + DAY
    before = features.frame(names, ["BTC"], [t - DAY, t], "1d")
    f = next((flake / "hist" / "binance_spot" / "klines_1m" / "symbol=BTCUSDT").glob("*.parquet"))
    m = pl.read_parquet(f)
    late = pl.col("open_time_us") >= t
    m.with_columns(*[pl.when(late).then(pl.col(c) * 3).otherwise(pl.col(c)).alias(c)
                     for c in ("open", "high", "low", "close")]).write_parquet(f)
    R.clear()
    assert before.equals(features.frame(names, ["BTC"], [t - DAY, t], "1d"))
