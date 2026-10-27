"""D3, the point-in-time feature store: the registry, every feature on a tiny recorded sample (two hours of the
recorder's BTC and ETH rows of 2026-10-26, books cut to one snapshot in 5 minutes and 10 levels, every fifth
Kraken trade), known-at timing, the leakage test (every raw row after t changed, nothing at or before t
moves), the Parquet cache, the adapters and the strategy factory's feature leaves.

No network, no lab data. Run from research/lab:  python -m pytest tests/test_features.py
"""

from __future__ import annotations

import json
import math
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import polars as pl
import pytest

from lab import features
from lab.factory import build, grammar, search
from lab.features import adapter, external, micro, store, study
from lab.features import registry as R
from test_factory import synthetic_panel

FIX = Path(__file__).resolve().parent / "fixtures" / "features_d3"
HOUR, DAY = R.HOUR, R.DAY
H0 = int(datetime(2026, 10, 26, 10, tzinfo=timezone.utc).timestamp() * 1e6)   # the sample is 10:00 to 12:00
TABLES = ["kraken/book20", "binance/book20", "bybit/book20", "okx/book20", "coinbase/book20", "kraken/trades",
          "binance_um/premium", "binance_um/open_interest", "binance_um/liquidations"]


def us(day: str) -> int:
    return int(datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


@pytest.fixture
def lake(tmp_path, monkeypatch):
    root = tmp_path / "data"
    shutil.copytree(FIX, root)
    monkeypatch.setattr(store, "ROOT", root)
    monkeypatch.setattr(store, "OUT", tmp_path / "out" / "features")
    monkeypatch.delenv("PYTHIA_FLOW", raising=False)
    R.clear()
    yield root
    R.clear()


def raw(root: Path, table: str) -> pl.DataFrame:
    return pl.concat([pl.read_parquet(f) for f in sorted((root / table).glob("date=*/*.parquet"))])


def same(b: pl.DataFrame, a: pl.DataFrame) -> None:
    """The same rows, the same nulls, the same values (to the last bits a sum's order may change)."""
    assert b.columns == a.columns and b.select("ts_us", "asset").equals(a.select("ts_us", "asset"))
    for c in b.columns[2:]:
        assert b[c].is_null().equals(a[c].is_null()), c
        x, y = b[c].drop_nulls().to_numpy(), a[c].drop_nulls().to_numpy()
        np.testing.assert_allclose(x, y, rtol=1e-12, atol=0, err_msg=c)


def at(names, assets, t, freq="1h") -> dict:
    """{asset: {feature: value}} known at t."""
    f = features.frame(names, assets, [t], freq)
    return {r["asset"]: r for r in f.to_dicts()}


# ---------------------------------------------------------------- registry

def test_every_feature_says_what_it_reads_how_often_and_when_it_is_known():
    assert len(features.names()) == len(set(features.names())) >= 30
    for n in features.names():
        f = features.get(n)
        assert f.group in R.GROUPS and f.sources and f.native and f.delay_us >= 0 and f.about
        assert set(f.freqs) <= {"1h", "1d"}
        assert n not in grammar.LEAVES and grammar.FEATURE + n in grammar.FEATURE_LEAVES
    want = {"spread_bps", "depth10_usd", "depth50_usd", "book_imb", "book_imb_chg", "trade_imb", "rv_trades",
            "xvenue_disp_bps", "funding_est", "funding_8h", "oi_chg", "liq_long_usd", "liq_short_usd",
            "dvol_btc", "stables_chg7", "fear_greed", "hl_funding", "event_next24h", "macro_spx_chg5"}
    assert want <= set(features.names())


def test_frame_refuses_an_unknown_frequency(lake):
    with pytest.raises(ValueError):
        features.frame(["spread_bps"], ["BTC"], [H0], "5m")


# ---------------------------------------------------------------- the book on the recorded sample

def book_by_hand(rows: list[dict]) -> dict:
    """Spread, 10 and 50 bp notional and imbalance of each snapshot, averaged: loops, no polars."""
    sp, d10, d50, imb = [], [], [], []
    for r in rows:
        b, a = r["bid_px"][0], r["ask_px"][0]
        mid = (a + b) / 2
        sp.append((a - b) / mid * 1e4)
        w = {}
        for bp in (10, 50):
            bid = sum(p * q for p, q in zip(r["bid_px"], r["bid_qty"]) if 1 - p / mid <= bp * 1e-4)
            ask = sum(p * q for p, q in zip(r["ask_px"], r["ask_qty"]) if p / mid - 1 <= bp * 1e-4)
            w[bp] = (bid, ask)
        d10.append(sum(w[10]))
        d50.append(sum(w[50]))
        imb.append((w[50][0] - w[50][1]) / sum(w[50]))
    return {"spread": np.mean(sp), "d10": np.mean(d10), "d50": np.mean(d50), "imb": np.mean(imb)}


@pytest.mark.parametrize("venue,pre,symbol", [("binance", "", "BTCUSDT"), ("kraken", "kraken_", "ETH/USD")])
def test_book_features_on_the_recorded_sample(lake, venue, pre, symbol):
    b = raw(lake, f"{venue}/book20").filter(pl.col("symbol") == symbol)
    asset = symbol[:3]
    names = [f"{pre}{x}" for x in ("spread_bps", "depth10_usd", "depth50_usd", "book_imb", "book_imb_chg")]
    hand = []
    for h in (H0, H0 + HOUR):
        rows = b.filter((pl.col("ts_recv_us") >= h) & (pl.col("ts_recv_us") < h + HOUR)).to_dicts()
        assert len(rows) == 12
        hand.append(book_by_hand(rows))
    for i, t in enumerate((H0 + HOUR, H0 + 2 * HOUR)):
        v = at(names, [asset], t)[asset]
        assert v[f"{pre}spread_bps"] == pytest.approx(hand[i]["spread"], rel=1e-9)
        assert v[f"{pre}depth10_usd"] == pytest.approx(hand[i]["d10"], rel=1e-9)
        assert v[f"{pre}depth50_usd"] == pytest.approx(hand[i]["d50"], rel=1e-9)
        assert v[f"{pre}book_imb"] == pytest.approx(hand[i]["imb"], rel=1e-9)
    assert at(names, [asset], H0 + HOUR)[asset][f"{pre}book_imb_chg"] is None        # no hour before
    assert at(names, [asset], H0 + 2 * HOUR)[asset][f"{pre}book_imb_chg"] == pytest.approx(
        hand[1]["imb"] - hand[0]["imb"], rel=1e-9)


def test_depth_and_imbalance_count_only_levels_inside_the_band(lake):
    """One hand-made book: mid 100, levels at 5, 9, 40 and 60 bp."""
    for v in micro.VENUES:
        shutil.rmtree(lake / v, ignore_errors=True)
    d = lake / "binance/book20/date=2026-10-26"
    d.mkdir(parents=True)
    pl.DataFrame({"ts_recv_us": [H0 + 60_000_000], "ts_exch_us": [None], "update_id": [1], "symbol": ["BTCUSDT"],
                  "bid_px": [[99.95, 99.91, 99.60, 99.40]], "bid_qty": [[1.0, 2.0, 3.0, 4.0]],
                  "ask_px": [[100.05, 100.09, 100.40, 100.60]], "ask_qty": [[1.0, 1.0, 1.0, 1.0]]},
                 schema_overrides={"ts_exch_us": pl.Int64}).write_parquet(d / "day.parquet")
    v = at(["spread_bps", "depth10_usd", "depth50_usd", "book_imb"], ["BTC"], H0 + HOUR)["BTC"]
    assert v["spread_bps"] == pytest.approx(10.0)
    assert v["depth10_usd"] == pytest.approx(99.95 + 2 * 99.91 + 100.05 + 100.09)
    b50, a50 = 99.95 + 2 * 99.91 + 3 * 99.60, 100.05 + 100.09 + 100.40
    assert v["depth50_usd"] == pytest.approx(b50 + a50)
    assert v["book_imb"] == pytest.approx((b50 - a50) / (b50 + a50))


def test_cross_venue_dispersion_puts_usdt_books_in_usd(lake):
    mids = []
    for v in micro.VENUES:
        b = raw(lake, f"{v}/book20").with_columns(
            minute=pl.col("ts_recv_us") // 60_000_000, mid=(pl.col("bid_px").list.first() + pl.col("ask_px").list.first()) / 2,
            asset=pl.col("symbol").str.slice(0, 3).str.replace("/", ""))
        mids += [(v, r["asset"], r["minute"], r["mid"]) for r in b.sort("ts_recv_us").iter_rows(named=True)]
    last = {}
    for v, a, m, x in mids:
        last[(v, a, m)] = x
    usdt = {m: x for (v, a, m), x in last.items() if v == "kraken" and a == "USD"}   # USDT/USD sliced to "USD"
    per = {}
    for (v, a, m), x in last.items():
        if a != "BTC":
            continue
        if v in micro.USDT_QUOTED:
            if m not in usdt:
                continue
            x *= usdt[m]
        per.setdefault(m, []).append(x)
    ds = [(max(x) - min(x)) / float(np.median(x)) * 1e4 for m, x in per.items()
          if len(x) >= 2 and H0 <= m * 60_000_000 < H0 + HOUR]
    assert ds, "the sample has minutes with two venues"
    got = at(["xvenue_disp_bps"], ["BTC"], H0 + HOUR)["BTC"]["xvenue_disp_bps"]
    assert got == pytest.approx(np.mean(ds), rel=1e-9)


# ---------------------------------------------------------------- trades, perp, liquidations

def test_trade_flow_and_realised_vol_from_kraken_trades(lake):
    t = raw(lake, "kraken/trades").filter((pl.col("symbol") == "BTC/USD") & (pl.col("ts_recv_us") >= H0)
                                          & (pl.col("ts_recv_us") < H0 + HOUR)).sort("ts_recv_us")
    buy = sum(r["price"] * r["qty"] for r in t.iter_rows(named=True) if r["side"] == "buy")
    sell = sum(r["price"] * r["qty"] for r in t.iter_rows(named=True) if r["side"] == "sell")
    last = {}
    for r in t.iter_rows(named=True):
        last[r["ts_recv_us"] // 60_000_000] = r["price"]
    px = [last[m] for m in sorted(last)]
    rv2 = sum(math.log(b / a) ** 2 for a, b in zip(px, px[1:]))
    v = at(["trade_imb", "trade_usd", "rv_trades"], ["BTC"], H0 + HOUR)["BTC"]
    assert v["trade_usd"] == pytest.approx(buy + sell, rel=1e-9)
    assert v["trade_imb"] == pytest.approx((buy - sell) / (buy + sell), rel=1e-9)
    assert v["rv_trades"] == pytest.approx(math.sqrt(rv2 * 365 * 24), rel=1e-9)


def test_funding_premium_and_open_interest_from_the_recorder(lake):
    p = raw(lake, "binance_um/premium").filter(pl.col("symbol") == "ETHUSDT").sort("ts_recv_us")
    o = raw(lake, "binance_um/open_interest").filter(pl.col("symbol") == "ETHUSDT").sort("ts_recv_us")
    h1 = p.filter(pl.col("ts_recv_us") >= H0 + HOUR)
    prem = np.mean([(m / i - 1) * 1e4 for m, i in zip(h1["mark_price"], h1["index_price"])])
    oi0 = o.filter(pl.col("ts_recv_us") < H0 + HOUR)["open_interest"][-1]
    oi1 = o["open_interest"][-1]
    v = at(["funding_est", "premium_bps", "oi_chg"], ["ETH"], H0 + 2 * HOUR)["ETH"]
    assert v["funding_est"] == pytest.approx(h1["funding_rate"][-1])
    assert v["premium_bps"] == pytest.approx(prem, rel=1e-9)
    assert v["oi_chg"] == pytest.approx(oi1 / oi0 - 1, rel=1e-9)        # no archive here: the recorder's


def test_liquidations_by_side_and_a_quiet_hour_is_zero(lake):
    q = raw(lake, "binance_um/liquidations")
    hours = {}
    for r in q.iter_rows(named=True):
        a = r["symbol"].removesuffix("USDT").removeprefix("1000")
        h = r["ts_recv_us"] // HOUR * HOUR
        k = hours.setdefault((a, h), [0.0, 0.0])
        k[0 if r["side"] == "SELL" else 1] += r["avg_price"] * r["filled_qty"]
    for (a, h), (lng, sht) in hours.items():
        v = at(["liq_long_usd", "liq_short_usd"], [a], h + HOUR)[a]
        assert v["liq_long_usd"] == pytest.approx(lng, rel=1e-9) and v["liq_short_usd"] == pytest.approx(sht, rel=1e-9)
    assert ("PEPE", H0) in hours                       # 1000PEPEUSDT is PEPE
    # SOL had no short liquidation in the first hour: 0, not missing.
    assert at(["liq_short_usd"], ["SOL"], H0 + HOUR)["SOL"]["liq_short_usd"] == 0.0


# ---------------------------------------------------------------- known at

def test_a_bucket_is_known_at_its_end_and_not_older_than_one_bucket(lake):
    def spread(t):
        return at(["spread_bps"], ["BTC"], t)["BTC"]["spread_bps"]
    assert spread(H0 + HOUR - 1) is None                 # the first hour is not over
    first = spread(H0 + HOUR)
    assert first is not None and spread(H0 + 2 * HOUR - 1) == first
    assert spread(H0 + 2 * HOUR) != first                # the second hour
    assert spread(H0 + 3 * HOUR - 1) is not None
    assert spread(H0 + 3 * HOUR) is None                 # nothing recorded after 12:00: stale, not carried


def scramble(root: Path, t: int, seed: int = 0) -> None:
    """Change every raw row received after t (prices, sizes, sides) and add rows after t."""
    rng = np.random.default_rng(seed)
    for tb in TABLES:
        for f in sorted((root / tb).glob("date=*/*.parquet")):
            d = pl.read_parquet(f)
            late = pl.col("ts_recv_us") > t
            n = d.height
            k = pl.Series(rng.uniform(0.5, 2.0, n))
            num = [c for c in ("price", "qty", "avg_price", "filled_qty", "mark_price", "open_interest",
                               "funding_rate") if c in d.columns]
            d = d.with_columns(_k=k).with_columns(*(pl.when(late).then(pl.col(c) * pl.col("_k")).otherwise(pl.col(c))
                                                    for c in num))
            for c in ("bid_px", "ask_px", "bid_qty", "ask_qty"):
                if c in d.columns:
                    d = d.with_columns(pl.when(late).then(pl.col(c) * pl.col("_k")).otherwise(pl.col(c)).alias(c))
            if "side" in d.columns:
                flip = {"buy": "sell", "sell": "buy", "BUY": "SELL", "SELL": "BUY"}
                d = d.with_columns(pl.when(late).then(pl.col("side").replace(flip)).otherwise(pl.col("side")))
            extra = d.filter(late).head(5).with_columns(ts_recv_us=pl.col("ts_recv_us") + 1)
            pl.concat([d.drop("_k"), extra.drop("_k")]).write_parquet(f)


@pytest.mark.parametrize("cut", [30, 60, 61, 95])
def test_no_raw_row_after_t_moves_anything_at_or_before_t(lake, cut):
    t = H0 + cut * 60_000_000 - (1 if cut == 61 else 0)
    grid = list(range(H0, t + 1, 5 * 60_000_000)) + [t]
    assets = ["BTC", "ETH", "SOL", "PEPE"]
    before = features.frame(features.names(), assets, grid, "1h")
    later = features.frame(features.names(), assets, [H0 + 2 * HOUR], "1h")
    if cut >= 60:
        assert all(before[n].drop_nulls().len() for n in ("spread_bps", "trade_imb", "xvenue_disp_bps", "liq_long_usd"))
    scramble(lake, t)
    R.clear()
    same(before, features.frame(features.names(), assets, grid, "1h"))
    # the rows after t did change what is known later
    assert not later.equals(features.frame(features.names(), assets, [H0 + 2 * HOUR], "1h"))


# ---------------------------------------------------------------- a synthetic lake of whole days

def synth_lake(root: Path, days: list[str], seed: int = 1) -> None:
    """Every table for BTC and ETH: books every 20 minutes, trades every 5, perp rows every 15, a liquidation an hour."""
    rng = np.random.default_rng(seed)
    for day in days:
        t0 = us(day)
        bk, tr, pr, oi, lq = [], [], [], [], []
        for i in range(0, 1440, 5):
            ts = t0 + i * 60_000_000 + 1_000_000
            for sym, base in (("BTC", 100.0), ("ETH", 10.0)):
                mid = base * (1 + 0.01 * rng.standard_normal())
                if i % 20 == 0:
                    for venue, s in (("kraken", f"{sym}/USD"), ("binance", f"{sym}USDT"), ("okx", f"{sym}-USDT")):
                        bk.append((venue, ts, s, [mid * (1 - k * 2e-4) for k in range(1, 6)], list(rng.uniform(1, 5, 5)),
                                   [mid * (1 + k * 2e-4) for k in range(1, 6)], list(rng.uniform(1, 5, 5))))
                tr.append((ts, f"{sym}/USD", "buy" if rng.random() < 0.5 else "sell", mid, float(rng.uniform(0.1, 1))))
                if i % 15 == 0:
                    pr.append((ts, f"{sym}USDT", mid * 1.0001, mid, 1e-4 * rng.standard_normal()))
                    oi.append((ts, f"{sym}USDT", 1000 + 10 * rng.standard_normal()))
                if i % 60 == 30:
                    lq.append((ts, f"{sym}USDT", "SELL" if rng.random() < 0.5 else "BUY", mid, 2.0))
            if i % 20 == 0:
                bk.append(("kraken", ts, "USDT/USD", [0.9995], [1e6], [1.0005], [1e6]))

        def write(tb, df):
            p = root / tb / f"date={day}"
            p.mkdir(parents=True, exist_ok=True)
            df.write_parquet(p / "day.parquet")
        for venue in ("kraken", "binance", "okx"):
            rows = [r[1:] for r in bk if r[0] == venue]
            write(f"{venue}/book20", pl.DataFrame(rows, schema=["ts_recv_us", "symbol", "bid_px", "bid_qty", "ask_px",
                                                                "ask_qty"], orient="row"))
        write("kraken/trades", pl.DataFrame(tr, schema=["ts_recv_us", "symbol", "side", "price", "qty"], orient="row"))
        write("binance_um/premium", pl.DataFrame(pr, schema=["ts_recv_us", "symbol", "mark_price", "index_price",
                                                             "funding_rate"], orient="row"))
        write("binance_um/open_interest", pl.DataFrame(oi, schema=["ts_recv_us", "symbol", "open_interest"], orient="row"))
        write("binance_um/liquidations", pl.DataFrame(lq, schema=["ts_recv_us", "symbol", "side", "avg_price",
                                                                  "filled_qty"], orient="row")
              .with_columns(price=pl.col("avg_price"), qty=pl.col("filled_qty")))


def flow_files(root: Path) -> None:
    """The archive and flow series a few days around the synthetic lake, D2 files included."""
    f = root / "hist/binance_um/funding/symbol=BTCUSDT"
    f.mkdir(parents=True)
    pl.DataFrame({"funding_time_us": [us("2026-10-01") + k * 8 * HOUR for k in range(12)],
                  "interval_hours": [8] * 12, "funding_rate": [1e-4 * (k + 1) for k in range(12)]},
                 schema_overrides={"interval_hours": pl.Int32}).write_parquet(f / "2026-10.parquet")
    fl = root / "flow"
    fl.mkdir(parents=True)
    days = [us("2026-09-20") + k * DAY for k in range(16)]
    pl.DataFrame({"day_us": days, "currency": ["BTC"] * 16, "close": [40.0 + k for k in range(16)]}).write_parquet(fl / "dvol.parquet")
    pl.DataFrame({"day_us": days, "total": [100.0 + k for k in range(16)]}).write_parquet(fl / "stables.parquet")
    pl.DataFrame({"day_us": days, "value": [float(k) for k in range(16)]}).write_parquet(fl / "fear_greed.parquet")
    pl.DataFrame({"day_us": days * 2, "series": ["spx"] * 16 + ["us10y"] * 16,
                  "value": [100.0 + k for k in range(16)] + [4.0 + 0.1 * k for k in range(16)]}).write_parquet(fl / "macro.parquet")
    pl.DataFrame({"ts_us": [us("2026-10-02") + 14 * HOUR], "known_us": [us("2026-09-25")]}).write_parquet(fl / "events.parquet")
    pl.DataFrame({"ts_us": [us("2026-10-01") + h * HOUR for h in range(48)], "asset": ["BTC"] * 48,
                  "funding": [1e-5 * h for h in range(48)]}).write_parquet(fl / "hyperliquid_funding.parquet")
    pl.DataFrame({"ts_us": [us("2026-10-01") + 6 * HOUR, us("2026-10-02") + 6 * HOUR], "currency": ["BTC", "BTC"],
                  "rr25": [-0.02, -0.03]}).write_parquet(fl / "skew.parquet")


@pytest.fixture
def days(tmp_path, monkeypatch):
    root = tmp_path / "data"
    synth_lake(root, ["2026-10-01", "2026-10-02", "2026-10-03"])
    flow_files(root)
    monkeypatch.setattr(store, "ROOT", root)
    monkeypatch.setattr(store, "OUT", tmp_path / "out" / "features")
    monkeypatch.delenv("PYTHIA_FLOW", raising=False)
    R.clear()
    yield root
    R.clear()


def test_daily_rows_are_known_at_the_end_of_the_day(days):
    d1 = us("2026-10-01")
    v = at(["trade_usd", "spread_bps", "book_imb_chg"], ["BTC"], d1 + DAY - 1, "1d")["BTC"]
    assert v["trade_usd"] is None
    t = raw(days, "kraken/trades").filter((pl.col("symbol") == "BTC/USD") & (pl.col("ts_recv_us") < d1 + DAY))
    v = at(["trade_usd", "book_imb_chg"], ["BTC"], d1 + DAY, "1d")["BTC"]
    assert v["trade_usd"] == pytest.approx(float((t["price"] * t["qty"]).sum()), rel=1e-9)
    assert v["book_imb_chg"] is None
    assert at(["book_imb_chg"], ["BTC"], d1 + 2 * DAY, "1d")["BTC"]["book_imb_chg"] is not None
    # A daily weighted mean is the mean of the snapshots, not of the hours.
    h = features.frame(["spread_bps"], ["BTC"], [d1 + (k + 1) * HOUR for k in range(24)], "1h")["spread_bps"]
    assert at(["spread_bps"], ["BTC"], d1 + DAY, "1d")["BTC"]["spread_bps"] == pytest.approx(h.mean(), rel=1e-9)


def test_archive_and_flow_features_with_their_delays(days):
    d1 = us("2026-10-01")
    # funding_8h: hourly the last settled rate (on 8 h), daily the day's sum, known at the settlement.
    assert at(["funding_8h"], ["BTC"], d1 + 8 * HOUR - 1)["BTC"]["funding_8h"] == pytest.approx(1e-4)
    assert at(["funding_8h"], ["BTC"], d1 + 8 * HOUR)["BTC"]["funding_8h"] == pytest.approx(2e-4)
    assert at(["funding_8h"], ["BTC"], d1 + 17 * HOUR)["BTC"]["funding_8h"] == pytest.approx(3e-4)
    assert at(["funding_8h"], ["BTC"], d1 + 97 * HOUR - 1)["BTC"]["funding_8h"] == pytest.approx(12e-4)
    assert at(["funding_8h"], ["BTC"], d1 + 97 * HOUR)["BTC"]["funding_8h"] is None    # 9 h after the last one
    assert at(["funding_8h"], ["BTC"], d1 + 2 * DAY, "1d")["BTC"]["funding_8h"] == pytest.approx(
        sum(1e-4 * (k + 1) for k in range(4, 7)))                     # 08:00, 16:00 and the next 00:00
    # dvol: the day's close, known an hour after the day; stables: 7-day change; both one value for every coin.
    day = us("2026-10-02")
    k = (day - us("2026-09-20")) // DAY
    v = at(["dvol_btc", "stables_chg7", "fear_greed"], ["BTC", "ETH"], day + DAY + HOUR, "1d")
    assert v["BTC"]["dvol_btc"] == v["ETH"]["dvol_btc"] == 40.0 + k
    assert v["BTC"]["stables_chg7"] == pytest.approx((100.0 + k) / (100.0 + k - 7) - 1)
    assert v["BTC"]["fear_greed"] == float(k)
    assert at(["dvol_btc"], ["BTC"], day + DAY + HOUR - 1, "1d")["BTC"]["dvol_btc"] == 40.0 + k - 1
    # macro: known a day after the day, a 5-observation change (us10y a difference).
    m = at(["macro_spx_chg5", "macro_us10y_chg5"], ["BTC"], day + 2 * DAY, "1d")["BTC"]
    assert m["macro_spx_chg5"] == pytest.approx((100.0 + k) / (100.0 + k - 5) - 1)
    assert m["macro_us10y_chg5"] == pytest.approx(0.5)
    # events: the release at 14:00 on the 2nd counts in the 24 hours before it.
    assert at(["event_next24h"], ["BTC"], us("2026-10-01") + 13 * HOUR)["BTC"]["event_next24h"] == 0.0
    assert at(["event_next24h"], ["BTC"], us("2026-10-01") + 14 * HOUR)["BTC"]["event_next24h"] == 1.0
    assert at(["event_next24h"], ["BTC"], us("2026-10-01") + 15 * HOUR)["BTC"]["event_next24h"] == 1.0
    assert at(["event_next24h"], ["BTC"], us("2026-10-02") + 14 * HOUR)["BTC"]["event_next24h"] == 0.0
    assert at(["hl_funding"], ["BTC"], d1 + 5 * HOUR)["BTC"]["hl_funding"] == pytest.approx(4e-5)
    assert at(["skew_rr25_btc"], ["ETH"], d1 + 7 * HOUR)["ETH"]["skew_rr25_btc"] == -0.02


def test_open_interest_takes_the_archive_and_the_recorder_after_it(days):
    m = days / "hist/binance_um/metrics/symbol=BTCUSDT"
    m.mkdir(parents=True)
    d1 = us("2026-10-01")
    pl.DataFrame({"ts_us": [d1 + k * 300_000_000 for k in range(12)],                # the first hour only
                  "sum_open_interest": [2000.0 + k for k in range(12)]}).write_parquet(m / "2026-10.parquet")
    o = raw(days, "binance_um/open_interest").filter(pl.col("symbol") == "BTCUSDT").sort("ts_recv_us")
    live = o.filter((pl.col("ts_recv_us") >= d1 + HOUR) & (pl.col("ts_recv_us") < d1 + 2 * HOUR))["open_interest"][-1]
    v = at(["oi_chg"], ["BTC"], d1 + 2 * HOUR)["BTC"]["oi_chg"]
    assert v == pytest.approx(live / 2011.0 - 1)                       # the archive's 00:55 value, then the recorder
    assert features.frame(["oi_chg_24h"], ["BTC"], [d1 + 2 * DAY], "1d")["oi_chg_24h"].to_list() == [None]


def test_missing_d2_files_give_empty_columns(lake):
    v = at(["fear_greed", "hl_funding", "macro_dxy_chg5", "event_next24h", "dvol_btc"], ["BTC"], H0 + HOUR)["BTC"]
    assert all(v[k] is None for k in ("fear_greed", "hl_funding", "macro_dxy_chg5", "event_next24h", "dvol_btc"))


def scramble_flow(root: Path, t: int) -> None:
    """Change every archive and flow row whose information is not complete by t."""
    f = root / "hist/binance_um/funding/symbol=BTCUSDT/2026-10.parquet"
    pl.read_parquet(f).with_columns(funding_rate=pl.when(pl.col("funding_time_us") > t).then(-1.0)
                                    .otherwise(pl.col("funding_rate"))).write_parquet(f)
    for name, col in (("dvol", "close"), ("stables", "total"), ("fear_greed", "value"), ("macro", "value")):
        p = root / "flow" / f"{name}.parquet"
        pl.read_parquet(p).with_columns(pl.when(pl.col("day_us") + DAY > t).then(pl.col(col) * 3 + 1)
                                        .otherwise(pl.col(col))).write_parquet(p)
    for name, col in (("hyperliquid_funding", "funding"), ("skew", "rr25")):
        p = root / "flow" / f"{name}.parquet"
        pl.read_parquet(p).with_columns(pl.when(pl.col("ts_us") > t).then(pl.col(col) * 5 + 1)
                                        .otherwise(pl.col(col))).write_parquet(p)


@pytest.mark.parametrize("cut", [us("2026-10-02"), us("2026-10-02") + 7 * HOUR + 1_234_567, us("2026-10-03") - 1])
def test_no_row_after_t_moves_a_daily_or_hourly_value_at_or_before_t(days, cut):
    grid_h = list(range(us("2026-10-01"), cut + 1, HOUR)) + [cut]
    grid_d = list(range(us("2026-10-01"), cut + 1, DAY)) + [cut]
    before = [features.frame(features.names(), ["BTC", "ETH"], g, f) for g, f in ((grid_h, "1h"), (grid_d, "1d"))]
    scramble(days, cut, seed=3)
    scramble_flow(days, cut)
    R.clear()
    after = [features.frame(features.names(), ["BTC", "ETH"], g, f) for g, f in ((grid_h, "1h"), (grid_d, "1d"))]
    for b, a in zip(before, after):
        same(b, a)


# ---------------------------------------------------------------- the cache

def test_build_caches_finished_days_and_rebuilds_only_what_changed(days, monkeypatch):
    names = ["spread_bps", "trade_imb", "premium_bps", "liq_long_usd", "xvenue_disp_bps"]
    grid = [us("2026-10-01") + k * HOUR for k in range(1, 72)]
    fresh = features.frame(names, ["BTC", "ETH"], grid, "1h")
    res = store.build(until="2026-10-03", log=lambda *a: None)
    assert res["book"] == {"built": 2, "kept": 0}
    assert sorted(p.parent.name for p in (store.OUT / "book").glob("date=*/hourly.parquet")) == \
        ["date=2026-10-01", "date=2026-10-02"]                      # the unfinished day is not written
    assert store.build(until="2026-10-03", log=lambda *a: None)["book"] == {"built": 0, "kept": 2}
    R.clear()
    assert features.frame(names, ["BTC", "ETH"], grid, "1h").equals(fresh)
    # A changed raw file is rebuilt; a day whose raw files are gone keeps its partition.
    f = days / "kraken/trades/date=2026-10-01/day.parquet"
    pl.read_parquet(f).with_columns(qty=pl.col("qty") * 2).write_parquet(f)
    assert store.build(until="2026-10-03", log=lambda *a: None)["trades"]["built"] == 1
    R.clear()
    changed = features.frame(names, ["BTC", "ETH"], grid, "1h")
    for tb in TABLES:
        shutil.rmtree(days / tb / "date=2026-10-02", ignore_errors=True)
    R.clear()
    assert features.frame(names, ["BTC", "ETH"], grid, "1h").equals(changed)
    # The partitions do not use the build's own clock: built from the raw rows they match them.
    built = pl.read_parquet(store.OUT / "trades/date=2026-10-01/hourly.parquet")
    assert built.equals(micro.trades_day("2026-10-01"))


def test_coverage_is_written_and_read_back(days):
    cov = study.coverage(log=lambda *a: None)
    assert cov["trade_imb"]["first_us"] is not None and cov["trade_imb"]["gap_days"] == 0
    assert cov["funding_8h"]["assets"] == 1 and cov["dvol_btc"]["assets"] == 1
    assert cov["kraken_spread_bps"]["first_us"] >= us("2026-10-01")
    store.write_coverage({"features": cov})
    assert store.read_coverage()["features"]["trade_imb"] == json.loads(json.dumps(cov["trade_imb"]))


# ---------------------------------------------------------------- adapters

def test_model_frame_keeps_the_rows_order_and_marks_the_unknown(days):
    d1 = us("2026-10-01")
    rows = pl.DataFrame({"ts_us": [d1 + 5 * HOUR, d1 + 2 * HOUR, d1 - DAY, d1 + 5 * HOUR],
                         "asset": ["ETH", "BTC", "BTC", "XYZ"]})
    X, names = adapter.model_frame(["trade_imb", "dvol_btc"], rows)
    assert X.shape == (4, 2) and names == ["trade_imb", "dvol_btc"]
    fr = features.frame(["trade_imb"], ["ETH", "BTC"], [d1 + 5 * HOUR, d1 + 2 * HOUR])
    want = {(r["ts_us"], r["asset"]): r["trade_imb"] for r in fr.to_dicts()}
    assert X[0, 0] == want[(d1 + 5 * HOUR, "ETH")] and X[1, 0] == want[(d1 + 2 * HOUR, "BTC")]
    assert np.isnan(X[2, 0]) and np.isnan(X[3, 0])
    assert X[3, 1] == X[0, 1]                                         # a market feature for any asset


def test_daily_matrix_is_the_value_known_at_each_close(days):
    closes = np.array([us("2026-10-01") + k * DAY for k in range(1, 4)])
    m = adapter.daily_matrix("trade_usd", ["ETH", "BTC", "ZZZ"], closes)
    assert m.shape == (3, 3) and np.isnan(m[:, 2]).all()
    fr = features.frame(["trade_usd"], ["BTC"], closes.tolist(), "1d")["trade_usd"].to_numpy()
    np.testing.assert_allclose(m[:, 1], fr)
    assert adapter.daily_matrix("dvol_btc", [], closes).shape == (3, 1)


def test_drawable_needs_coverage_over_half_the_window():
    cov = {"features": {"funding_8h": {"first_us": us("2020-01-01"), "last_us": us("2026-10-25")},
                        "oi_chg": {"first_us": us("2022-01-01"), "last_us": us("2026-10-25")},
                        "spread_bps": {"first_us": us("2026-09-30"), "last_us": us("2026-10-25")},
                        "fear_greed": {"first_us": None, "last_us": None}}}
    assert adapter.drawable(us("2018-01-01"), us("2024-01-01"), 0.5, cov) == ["funding_8h"]
    assert adapter.drawable(us("2018-01-01"), us("2024-01-01"), 0.3, cov) == ["funding_8h", "oi_chg"]
    assert adapter.drawable(us("2018-01-01"), us("2024-01-01"), 0.5, {}) == []


# ---------------------------------------------------------------- the strategy factory's feature leaves

def f(name):
    return {"op": grammar.FEATURE + name}


def test_trees_may_read_features_with_the_grammar_rules():
    ok = [{"op": "rank", "args": [f("funding_8h")]},
          {"op": "z", "n": 20, "args": [f("trade_usd")]},              # a level inside z
          {"op": "diff", "args": [{"op": "ret", "n": 5, "args": [{"op": "close"}]}, f("dvol_btc")]}]
    for t in ok:
        assert grammar.valid_tree(grammar.canonical_tree(t))[0], t
    bad = [{"op": "rank", "args": [f("trade_usd")]},                   # a level without a window
           {"op": "z", "n": 20, "args": [f("dvol_btc")]},              # a coin score from a market feature alone
           {"op": "rank", "args": [{"op": "f.nonsense"}]}]
    for t in bad:
        assert not grammar.valid_tree(t)[0], t
    gate = {"op": "ma", "n": 20, "args": [f("dvol_btc")]}
    assert grammar.valid_tree(gate, market=True)[0]
    assert not grammar.valid_tree({"op": "ma", "n": 20, "args": [f("funding_8h")]}, market=True)[0]
    assert grammar.show_tree(ok[0]) == "rank(funding_8h)" and grammar.show_cond(gate, 0.0) == "dvol_btc > ma_20"


def test_feature_leaves_change_nothing_unless_a_search_draws_them():
    for seed in range(20):
        a = grammar.random_tree_genome(random.Random(seed))
        b = grammar.random_tree_genome(random.Random(seed), grammar.LEAVES)
        assert a == b and not any(x.startswith(grammar.FEATURE) for _, t in grammar.trees_of(a)
                                  for x in grammar.leaves_of(t))
    leaves = grammar.LEAVES + ("f.funding_8h", "f.stables_chg7", "f.trade_usd")
    rng = random.Random(5)
    seen = set()
    for _ in range(300):
        g = grammar.random_tree_genome(rng, leaves)
        assert grammar.valid(g)[0] and grammar.canonical(g) == g
        seen |= {x for _, t in grammar.trees_of(g) for x in grammar.leaves_of(t)}
        g2 = grammar.mutate(g, rng, trees=True, leaves=leaves)
        assert grammar.valid(g2)[0]
    assert {"f.funding_8h", "f.stables_chg7", "f.trade_usd"} <= seen


@pytest.fixture
def panel_lake(tmp_path, monkeypatch):
    """Settled funding of BTC and ETH over the synthetic panel's first 300 days, and a stablecoin series."""
    P = synthetic_panel()
    root = tmp_path / "data"
    for sym, k in (("BTCUSDT", 1.0), ("ETHUSDT", -1.0)):
        d = root / "hist/binance_um/funding" / f"symbol={sym}"
        d.mkdir(parents=True)
        ts = [int(P.days[0]) + j * 8 * HOUR for j in range(900)]
        pl.DataFrame({"funding_time_us": ts, "interval_hours": [8] * 900,
                      "funding_rate": [k * 1e-5 * (j % 7) for j in range(900)]},
                     schema_overrides={"interval_hours": pl.Int32}).write_parquet(d / "all.parquet")
    (root / "flow").mkdir(parents=True)
    pl.DataFrame({"day_us": P.days[:400], "total": np.linspace(1, 2, 400)}).write_parquet(root / "flow/stables.parquet")
    monkeypatch.setattr(store, "ROOT", root)
    monkeypatch.setattr(store, "OUT", tmp_path / "out" / "features")
    monkeypatch.delenv("PYTHIA_FLOW", raising=False)
    R.clear()
    yield P
    R.clear()


def test_a_feature_leaf_is_the_value_known_at_each_close(panel_lake):
    P = panel_lake
    c = build.make_ctx(P)
    x = build.leaf(c, "f.funding_8h")
    j = c.names.index("BTCUSDT")
    t = 100
    want = sum(1e-5 * (k % 7) for k in range(900) if
               int(P.days[t]) < int(P.days[0]) + k * 8 * HOUR <= int(P.days[t]) + DAY)
    assert x[t, j] == pytest.approx(want)
    assert np.isnan(x[400:, j]).all()                                # no data after day 300: nothing carried
    assert np.isnan(x[:, c.names.index("C00USDT")]).all()
    assert build.leaf(c, "f.stables_chg7").shape == (c.T, 1)
    tree = {"op": "rank", "args": [f("funding_8h")]}
    s = build.tree_score(c, tree, c.uni["top30"], "top30")
    assert np.isfinite(s[t]).sum() >= 1


def test_the_weekly_search_draws_features_with_data_in_sample(panel_lake):
    c = build.make_ctx(panel_lake)
    cov = {"features": {"funding_8h": {"first_us": int(c.days[0]), "last_us": int(c.days[-1]) + DAY},
                        "spread_bps": {"first_us": int(c.days[-1]), "last_us": int(c.days[-1]) + DAY}}}
    feats = build.feature_leaves(c, cov)
    assert feats == ("f.funding_8h",)
    assert build.feature_leaves(c, {}) == ()
    res = search.search(c, set(), [], "d3-test", budget=24, seed=4, share=1.0, leaves=grammar.LEAVES + feats,
                        log=lambda *a: None)
    used = [r for r in res["rows"] if any("f.funding_8h" in grammar.leaves_of(t) for _, t in grammar.trees_of(r["genome"]))]
    assert used and all(math.isfinite(r["fitness"]) for r in res["rows"])


# ---------------------------------------------------------------- the study

def test_benjamini_hochberg_and_newey_west():
    assert study.bh([0.001, 0.02, 0.03, 0.5]) == [True, True, True, False]
    assert study.bh([0.04, 0.5]) == [False, False]
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 4000)
    slow = np.repeat(rng.normal(0.05, 1, 100), 40)                   # the same value 40 times in a row
    assert abs(study.hac_t(x, 0) - x.mean() / x.std() * math.sqrt(len(x))) < 1e-9
    assert abs(study.hac_t(slow, 100)) < abs(study.hac_t(slow, 0)) / 3


def test_rank_ic_finds_a_planted_signal(days, monkeypatch):
    """A test feature that is the next hour's return plus noise has a clearly positive IC."""
    rng = np.random.default_rng(2)
    ts = np.arange(us("2026-10-01"), us("2026-10-08"), HOUR)
    assets = [f"A{i}" for i in range(8)]
    y = pl.DataFrame({"ts_us": np.repeat(ts, 8), "asset": assets * len(ts), "y": rng.normal(0, 0.01, 8 * len(ts))})
    tab = y.select(ts_us=pl.col("ts_us") - HOUR, asset="asset", end_us="ts_us",
                   v=pl.col("y") + pl.Series(rng.normal(0, 0.01, y.height)))
    monkeypatch.setitem(R.GROUPS, "planted", R.Group("planted", ("test",), lambda freq, a: tab))
    monkeypatch.setitem(R.REGISTRY, "planted", R.Feature("planted", "planted", ("test",), "1h", 0, lambda p: pl.col("v")))
    r = study.ic("planted", "1h", y)
    assert r["ic"] > 0.4 and r["t"] > 10 and r["p"] < 1e-6
    noise = y.with_columns(y=pl.Series(rng.normal(0, 0.01, y.height)))
    assert abs(study.ic("planted", "1h", noise)["t"]) < 4
