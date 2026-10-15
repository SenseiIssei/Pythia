"""The trending watcher: parsing, surges, alert rules, dedupe, digest, storage. No network.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
import urllib.error
from datetime import datetime, timezone

import pytest

from lab.ops import trending as tr

NOW = int(datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc).timestamp() * 1000)


def klines(qv: float, count: int, days: int = 29) -> list[list]:
    return [[0, "1", "1", "1", "1", "1", 0, str(qv), count, "0", "0", "0"] for _ in range(days)]


def fake(responses: dict):
    calls = []

    def get(url: str):
        calls.append(url)
        for k, v in responses.items():
            if k in url:
                if isinstance(v, Exception):
                    raise v
                return v
        raise urllib.error.URLError("unknown")
    get.calls = calls
    return get


@pytest.fixture()
def world():
    pair = {"chainId": "solana", "dexId": "raydium", "url": "https://dexscreener.com/solana/p1",
            "baseToken": {"address": "TokA", "name": "Alpha", "symbol": "ALP"},
            "priceUsd": "0.01", "priceChange": {"h1": 5, "h24": 300}, "volume": {"h24": 2_000_000},
            "liquidity": {"usd": 40_000}, "fdv": 5_000_000, "pairCreatedAt": NOW - 10 * 3_600_000,
            "txns": {"h24": {"buys": 900, "sells": 20}}}
    return {
        "/api/v3/ticker/24hr": [
            {"symbol": "BONKUSDT", "priceChangePercent": "25", "quoteVolume": "90000000", "count": 400000,
             "lastPrice": "0.00002"},
            {"symbol": "DOGEUSDT", "priceChangePercent": "2", "quoteVolume": "500000000", "count": 900000,
             "lastPrice": "0.2"},
            {"symbol": "XYZUSDT", "priceChangePercent": "60", "quoteVolume": "8000000", "count": 1000,
             "lastPrice": "1"},
            {"symbol": "USDCUSDT", "priceChangePercent": "0", "quoteVolume": "9e9", "count": 1, "lastPrice": "1"},
            {"symbol": "BTCUPUSDT", "priceChangePercent": "9", "quoteVolume": "9e7", "count": 1, "lastPrice": "1"},
        ],
        "symbol=BONKUSDT": klines(20_000_000, 100_000),
        "symbol=DOGEUSDT": klines(450_000_000, 850_000),
        "/token-boosts/top/v1": [{"chainId": "solana", "tokenAddress": "TokA", "totalAmount": 500},
                                 {"chainId": "solana", "tokenAddress": "TokA", "totalAmount": 500}],
        "/token-profiles/latest/v1": [{"chainId": "base", "tokenAddress": "TokB"}],
        "/tokens/v1/solana/": [pair],
        "/tokens/v1/base/": [],
        "/latest/dex/search": {"pairs": []},
    }


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    monkeypatch.setenv("PYTHIA_AGENT_OUT", str(tmp_path / "agent"))
    for k in ("PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_ALPACA_COINS"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def test_tickers_keep_usdt_coins_only(world):
    t = tr.tickers(fake(world))
    assert set(t) == {"BONK", "DOGE", "XYZ"}
    assert t["BONK"]["change"] == pytest.approx(0.25)


def test_kline_medians_drop_the_running_day(world):
    w = dict(world)
    k = klines(10, 5, 28) + [[0, "1", "1", "1", "1", "1", 0, "99999", 99999, "0", "0", "0"]]
    w["symbol=BONKUSDT"] = k
    m = tr.kline_medians(fake(w), "BONK")
    assert m == {"qv": 10.0, "count": 5.0, "days": 28}


def test_strong_surge_rules():
    assert tr.is_strong({"qv_ratio": 3.0, "change": 0.08})
    assert not tr.is_strong({"qv_ratio": 2.9, "change": 0.19})
    assert tr.is_strong({"qv_ratio": 2.0, "change": 0.20})
    assert not tr.is_strong({"qv_ratio": 5.0, "change": -0.1})
    assert not tr.is_strong({"qv_ratio": None, "change": 0.5})


def test_risk_flags():
    r = {"liquidity_usd": 40_000, "age_h": 10, "fdv": 5_000_000, "volume_h24": 2_000_000, "buys_h24": 900,
         "sells_h24": 20}
    f = tr.risk_flags(r)
    assert "thin liquidity" in f and "pair under 3 days old" in f and "FDV over 50x liquidity" in f
    assert any("wash" in x for x in f) and any("honeypot" in x for x in f)
    assert tr.risk_flags({"liquidity_usd": 5e6, "age_h": 1000, "fdv": 1e7, "volume_h24": 1e6}) == []


def test_run_alerts_once_per_coin_and_stores(world, data):
    posted = []
    poster = lambda text: posted.append(text) or (True, None)  # noqa: E731
    snap = tr.run(fake(world), now=NOW, poster=poster)
    assert [a["coin"] for a in snap["alerts_sent"]] == ["BONK"]
    assert snap["alpaca"]["BONK"]["qv_ratio"] == pytest.approx(4.5)
    assert "DOGE" not in [a["coin"] for a in snap["alerts_sent"]]
    alert = posted[0]
    assert "BONK on Alpaca" in alert and "Watch only" in alert and "—" not in alert
    # 09:00 UTC: the daily digest goes out on the first run, labelled high risk.
    assert snap["digest"]["delivered"]
    digest = posted[1]
    assert "HIGH RISK" in digest and "ALP (solana)" in digest and "honeypot" in digest
    assert len(digest) <= 1800
    # Stored.
    lines = (data / "trending" / "2026-10-15.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["alpaca"]["BONK"]
    assert (data / "reports" / "trending" / "latest.json").exists()
    # 15 minutes later: no second alert, no second digest.
    posted.clear()
    snap2 = tr.run(fake(world), now=NOW + 15 * 60_000, poster=poster)
    assert snap2["alerts_sent"] == [] and "digest" not in snap2 and posted == []
    # A day later it may alert again.
    snap3 = tr.run(fake(world), now=NOW + 21 * 3_600_000, poster=poster)
    assert [a["coin"] for a in snap3["alerts_sent"]] == ["BONK"]


def test_no_digest_before_the_hour(world, data):
    early = int(datetime(2026, 10, 15, 7, 45, tzinfo=timezone.utc).timestamp() * 1000)
    snap = tr.run(fake(world), now=early, poster=lambda t: (True, None))
    assert "digest" not in snap


def test_dry_run_writes_nothing(world, data):
    snap = tr.run(fake(world), now=NOW, dry_run=True, poster=lambda t: pytest.fail("posted"))
    assert snap["alerts_sent"][0]["error"] == "dry run"
    assert not (data / "trending").exists()


def test_sources_down_is_reported_not_raised(data):
    snap = tr.run(fake({}), now=NOW, poster=lambda t: (True, None))
    assert snap["errors"] and snap["alpaca"] == {} and snap["dex"] == []


def test_market_surges_need_a_week_of_history():
    tick = {"XYZ": {"qv": 8e7, "change": 0.3, "count": 1, "price": 1}}
    hist = {}
    for d in range(1, 7):
        tr.update_history(hist, {"XYZ": {"qv": 1e7}}, f"2026-10-0{d}")
    assert tr.market_surges(hist, tick, "2026-10-15") == []
    tr.update_history(hist, {"XYZ": {"qv": 1e7}}, "2026-10-07")
    s = tr.market_surges(hist, tick, "2026-10-15")
    assert s[0]["coin"] == "XYZ" and s[0]["qv_ratio"] == pytest.approx(8.0)


def test_history_keeps_one_value_per_day_and_28_days():
    hist = {}
    for d in range(40):
        tr.update_history(hist, {"A": {"qv": d}}, f"2026-{d // 28 + 1:02d}-{d % 28 + 1:02d}")
    tr.update_history(hist, {"A": {"qv": 999}}, "2026-02-12")
    assert len(hist["A"]) == 29
    assert hist["A"][-1] == ["2026-02-12", 999]


def test_alpaca_coins_override(monkeypatch):
    monkeypatch.setenv("PYTHIA_ALPACA_COINS", "doge, wif")
    assert tr.alpaca_coins() == ("DOGE", "WIF")
