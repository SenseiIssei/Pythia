"""The listings watcher on canned venue answers. No network.

Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from lab.ops import listings as L

T0 = 1_791_000_000_000


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    for k in ("PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def binance(*pairs):
    return L.parse_binance({"symbols": [{"symbol": b + q, "baseAsset": b, "quoteAsset": q, "status": "TRADING"}
                                        for b, q in pairs]})


def alpaca(*bases):
    return L.parse_alpaca([{"symbol": f"{b}/USD", "status": "active", "tradable": True} for b in bases])


BASE = {"binance": binance(("BTC", "USDT"), ("ETH", "USDT"), ("SOL", "USDT"), ("XRP", "USDT"), ("ADA", "USDT")),
        "coinbase": L.parse_coinbase([{"id": "BTC-USD", "base_currency": "BTC", "quote_currency": "USD",
                                       "status": "online"}]),
        "kraken": L.parse_kraken({"result": {"XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD",
                                                          "status": "online"}}}),
        "alpaca": alpaca("BTC", "ETH", "SOL")}


def fetcher_of(lists):
    def f(v):
        if isinstance(lists.get(v), Exception):
            raise lists[v]
        return lists[v]
    return f


def go(lists, now, news=(), posted=None):
    posted = posted if posted is not None else []
    return L.run(now_ms=now, fetcher=fetcher_of(lists), news_fetcher=lambda: list(news),
                 pricer=lambda v, s: 1.25, poster=lambda t: posted.append(t) or True)


def test_parsers_normalise_names():
    k = L.parse_kraken({"result": {"XXBTZUSD": {"altname": "XBTUSD", "wsname": "XBT/USD", "status": "online"},
                                   "XDGUSD": {"altname": "XDGUSD", "wsname": "XDG/USD", "status": "online"},
                                   "OLD.d": {"altname": "OLD", "wsname": "OLD/USD", "status": "online"},
                                   "HALTUSD": {"altname": "HALTUSD", "wsname": "HALT/USD", "status": "cancel_only"}}})
    assert k == {"XBTUSD": {"base": "BTC", "quote": "USD", "status": "online"},
                 "XDGUSD": {"base": "DOGE", "quote": "USD", "status": "online"}}
    a = L.parse_alpaca([{"symbol": "BTC/USD", "status": "active", "tradable": True},
                        {"symbol": "OLD/USD", "status": "inactive", "tradable": False}])
    assert list(a) == ["BTC/USD"] and a["BTC/USD"]["base"] == "BTC"
    c = L.parse_coinbase([{"id": "X-USD", "base_currency": "X", "quote_currency": "USD", "status": "online",
                           "trading_disabled": True}])
    assert c == {}
    n = L.parse_news({"data": {"catalogs": [{"articles": [
        {"id": 7, "title": "Binance Will List Foo (FOO) and Bar (BAR) with Seed Tag", "releaseDate": T0}]}]}})
    assert n[0]["bases"] == ["BAR", "FOO"] and n[0]["id"] == "7"


def test_first_run_seeds_quietly_then_alerts_new_coins(root):
    posted = []
    r = go(BASE, T0, posted=posted)
    assert r["text"] == "" and posted == []
    assert all(s["ok"] and s["seeded"] for v, s in r["venues"].items() if v in L.VENUES)
    seeds = pl.read_parquet(sorted((root / "lake" / "listings" / "first_seen").rglob("*.parquet")))
    assert set(seeds["event"]) == {"seed"} and seeds.height == 5 + 1 + 1 + 3

    lists = dict(BASE)
    lists["binance"] = {**BASE["binance"], **binance(("NEWC", "USDT"), ("NEWC", "BTC"), ("SOL", "BTC"))}
    lists["coinbase"] = {**BASE["coinbase"], **L.parse_coinbase([{"id": "SOL-USD", "base_currency": "SOL",
                                                                  "quote_currency": "USD", "status": "online"}])}
    r = go(lists, T0 + 600_000, posted=posted)
    listed = [e for e in r["events"] if e["event"] == "listed"]
    assert {(e["venue"], e["symbol"], e["new_base"]) for e in listed} == {
        ("binance", "NEWCUSDT", True), ("binance", "NEWCBTC", True), ("binance", "SOLBTC", False),
        ("coinbase", "SOL-USD", True)}
    text = posted[-1]
    assert "Binance new coin NEWC: NEWCBTC, NEWCUSDT. Alpaca: does not list it." in text
    assert "Coinbase new coin SOL: SOL-USD. Alpaca: lists it. First price 1.25 USD" in text
    assert "SOLBTC" not in text, "a new pair of a coin the venue already had is recorded, not posted"
    rec = json.loads((root / "reports" / "listings" / "recent.json").read_text())
    assert {e["symbol"] for e in rec["listings"]} == {"NEWCUSDT", "NEWCBTC", "SOLBTC", "SOL-USD"}
    assert rec["venues"]["binance"]["count"] == 8

    # Nothing changes: nothing is posted, nothing new recorded.
    n_before = len(posted)
    r = go(lists, T0 + 1_200_000, posted=posted)
    assert len(posted) == n_before and not [e for e in r["events"] if e["event"] != "seed"]


def test_a_failed_or_short_answer_is_skipped_not_a_delisting(root):
    go(BASE, T0)
    short = dict(BASE, binance=binance(("BTC", "USDT")), coinbase=OSError("down"))
    r = go(short, T0 + 600_000)
    assert r["events"] == []
    assert not r["venues"]["binance"]["ok"] and "against 5 known" in r["venues"]["binance"]["error"]
    assert r["venues"]["coinbase"] == {"ok": False, "count": 1, "error": "OSError"}
    # One real delisting, then the pair comes back: recorded, never posted as new.
    posted = []
    less = dict(BASE, binance={k: v for k, v in BASE["binance"].items() if k != "ADAUSDT"})
    r = go(less, T0 + 1_200_000, posted=posted)
    assert [(e["event"], e["symbol"]) for e in r["events"]] == [("removed", "ADAUSDT")]
    r = go(BASE, T0 + 1_800_000, posted=posted)
    assert [(e["event"], e["symbol"]) for e in r["events"]] == [("returned", "ADAUSDT")]
    assert posted == []


def test_alpaca_pairs_and_announcements_are_posted(root):
    news = [{"id": "1", "title": "old", "release_ms": T0, "bases": []}]
    go(BASE, T0, news=news)
    posted = []
    lists = dict(BASE, alpaca={**BASE["alpaca"], **alpaca("ADA"),
                               **L.parse_alpaca([{"symbol": "ETH/USDT", "status": "active"}])})
    news2 = news + [{"id": "2", "title": "Binance Will List Zed (ZED)", "release_ms": T0 + 1, "bases": ["ZED"]}]
    r = go(lists, T0 + 600_000, news=news2, posted=posted)
    text = posted[-1]
    assert "Alpaca new coin ADA: ADA/USD. Alpaca: lists it. First price 1.25 USD (ADA/USD)." in text
    assert "Alpaca new pair ETH: ETH/USDT." in text
    assert "Binance announcement: Binance Will List Zed (ZED). Alpaca: does not list it." in text
    ann = [e for e in r["events"] if e["event"] == "announced"]
    assert len(ann) == 1 and ann[0]["symbol"] == "ZED"


def test_without_alpaca_keys_the_answer_is_unknown(root, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    lists = {k: v for k, v in BASE.items() if k != "alpaca"}
    lists["alpaca"] = LookupError("no Alpaca keys")
    go(lists, T0)
    posted = []
    lists["kraken"] = {**BASE["kraken"], **L.parse_kraken({"result": {"NEWUSD": {"altname": "NEWUSD",
                                                                                "wsname": "NEW/USD",
                                                                                "status": "online"}}})}
    r = go(lists, T0 + 600_000, posted=posted)
    assert r["venues"]["alpaca"] == {"ok": False, "count": 0, "error": "no Alpaca keys"}
    assert "Kraken new coin NEW: NEWUSD. Alpaca: unknown (no keys)." in posted[-1]
    with pytest.raises(LookupError):
        L.fetch("alpaca")


def test_recent_keeps_ninety_days():
    old = {"listings": [{"ts_ms": T0 - 91 * L.notify.DAY_MS, "symbol": "OLD"}, {"ts_ms": T0 - 5, "symbol": "KEEP"}]}
    rec = L.update_recent(old, [{"event": "listed", "venue": "kraken", "symbol": "NEW", "base": "NEW"}], {}, T0)
    assert [e["symbol"] for e in rec["listings"]] == ["NEW", "KEEP"]


def test_dry_run_writes_nothing(root, capsys):
    L.run(dry_run=True, now_ms=T0, fetcher=fetcher_of(BASE), news_fetcher=list, pricer=None)
    assert not (root / "listings").exists() and not (root / "lake").exists()
