"""Bybit, OKX and Coinbase books, replayed from recorded public messages (FIL,
2026-10-07). No network: the fixtures are the venues' own messages, trimmed."""

from __future__ import annotations

import asyncio
import json
import zlib
from datetime import datetime
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from recorder import schemas
from recorder.books import CROSSED_LIMIT, ResyncGuard
from recorder.bybit import BybitBooks, parse_instruments as bybit_instruments
from recorder.coinbase import CoinbaseBooks, parse_products
from recorder.okx import OkxBook, OkxBooks, parse_instruments as okx_instruments
from recorder.sink import Sinks
from recorder.state import State

FIX = Path(__file__).parent / "fixtures"


def lines(name: str) -> list[str]:
    return (FIX / name).read_text(encoding="utf-8").splitlines()


class FakeWs:
    closed = False

    def __init__(self) -> None:
        self.sent: list = []

    async def send_json(self, x) -> None:
        self.sent.append(x)

    async def send_str(self, x) -> None:
        self.sent.append(x)


def feed(cls, tmp_path, symbols):
    f = cls(None, Sinks(tmp_path, 0), State(), list(symbols.values()))
    f.symbols = symbols
    f.ws = FakeWs()
    return f


def replay(f, msgs) -> None:
    for i, m in enumerate(msgs):
        f.handle(m, 1_000 + i)


def reference_top(snapshot_bids, snapshot_asks, changes):
    """The plain, obviously right replay to compare against: (side, px, qty) changes."""
    bids = {float(p): float(q) for p, q, *_ in snapshot_bids}
    asks = {float(p): float(q) for p, q, *_ in snapshot_asks}
    for is_bid, p, q in changes:
        side = bids if is_bid else asks
        if float(q) == 0:
            side.pop(float(p), None)
        else:
            side[float(p)] = float(q)
    return max(bids), min(asks)


# ---- Bybit ------------------------------------------------------------------

BYBIT = {"FILUSDT": "FIL"}


def bybit_msgs():
    return [m for m in lines("bybit_FILUSDT.jsonl") if '"topic"' in m]


def test_bybit_replay_builds_the_book_the_messages_describe(tmp_path):
    f = feed(BybitBooks, tmp_path, BYBIT)
    msgs = bybit_msgs()
    replay(f, lines("bybit_FILUSDT.jsonl"))
    bk = f.books["FILUSDT"]
    assert bk.live and bk.verified and bk.recordable()
    parsed = [json.loads(m) for m in msgs]
    assert len(parsed) > 30 and parsed[0]["type"] == "snapshot"
    bids = {float(p): float(q) for p, q in parsed[0]["data"]["b"]}
    asks = {float(p): float(q) for p, q in parsed[0]["data"]["a"]}
    for m in parsed[1:]:
        for side, key in ((bids, "b"), (asks, "a")):
            for p, q in m["data"][key]:
                if float(q) == 0:
                    side.pop(float(p), None)
                else:
                    side[float(p)] = float(q)
    assert bk.best() == (max(bids), min(asks))
    assert bk.update_id == parsed[-1]["data"]["u"]
    assert bk.ts_exch_us == parsed[-1]["ts"] * 1000
    q = f.state.quotes[("bybit", "FIL")]
    assert (q.bid, q.ask) == bk.best()


def test_bybit_lost_delta_resubscribes_once_the_sequence_has_held(tmp_path):
    f = feed(BybitBooks, tmp_path, BYBIT)
    msgs = bybit_msgs()
    replay(f, msgs[:10])
    assert f.books["FILUSDT"].verified
    f.handle(msgs[11], 99)          # msgs[10] lost
    bk = f.books["FILUSDT"]
    assert bk.broken and not bk.live and not bk.recordable()
    assert f.pending == ["FILUSDT"]
    asyncio.run(f.resync(f.pending.pop()))
    assert f.ws.sent == [{"op": "unsubscribe", "args": ["orderbook.200.FILUSDT"]},
                         {"op": "subscribe", "args": ["orderbook.200.FILUSDT"]}]
    f.handle(msgs[12], 100)         # a delta before the new snapshot is ignored
    assert not bk.live
    f.handle(msgs[0], 101)          # the snapshot the resubscribe brings
    assert bk.live and not bk.broken


def test_bybit_gap_before_the_sequence_ever_held_is_counted_not_acted_on(tmp_path):
    f = feed(BybitBooks, tmp_path, BYBIT)
    msgs = bybit_msgs()
    f.handle(msgs[0], 1)
    f.handle(msgs[2], 2)            # gap right after the snapshot: never verified
    bk = f.books["FILUSDT"]
    assert bk.live and not bk.broken and f.pending == []
    assert f.state.counters["bybit_gap"] == 1


def test_bybit_subscribes_in_batches_of_ten(tmp_path):
    syms = {f"C{i}USDT": f"C{i}" for i in range(23)}
    f = feed(BybitBooks, tmp_path, syms)
    asyncio.run(f.subscribe(sorted(syms)))
    assert [len(m["args"]) for m in f.ws.sent] == [10, 10, 3]


# ---- OKX --------------------------------------------------------------------

OKX = {"FIL-USDT": "FIL"}


def okx_msgs():
    return [m for m in lines("okx_FIL-USDT.jsonl") if '"action"' in m]


def test_okx_replay_follows_the_sequence_chain(tmp_path):
    f = feed(OkxBooks, tmp_path, OKX)
    replay(f, lines("okx_FIL-USDT.jsonl"))
    bk = f.books["FIL-USDT"]
    assert bk.live and bk.verified and bk.recordable()
    parsed = [json.loads(m)["data"][0] for m in okx_msgs()]
    bids = {float(l[0]): float(l[1]) for l in parsed[0]["bids"]}
    asks = {float(l[0]): float(l[1]) for l in parsed[0]["asks"]}
    for d in parsed[1:]:
        for side, key in ((bids, "bids"), (asks, "asks")):
            for l in d[key]:
                if float(l[1]) == 0:
                    side.pop(float(l[0]), None)
                else:
                    side[float(l[0])] = float(l[1])
    assert bk.best() == (max(bids), min(asks))
    assert bk.update_id == parsed[-1]["seqId"]
    assert f.state.counters.get("okx_checksum_mismatch") is None, "OKX sends 0, which is no checksum"


def test_okx_lost_message_breaks_the_book(tmp_path):
    f = feed(OkxBooks, tmp_path, OKX)
    msgs = okx_msgs()
    replay(f, msgs[:5])
    f.handle(msgs[6], 9)
    assert f.books["FIL-USDT"].broken and f.pending == ["FIL-USDT"]


def test_okx_quiet_book_heartbeat_keeps_the_chain(tmp_path):
    f = feed(OkxBooks, tmp_path, OKX)
    msgs = okx_msgs()
    replay(f, msgs[:3])
    seq = f.books["FIL-USDT"].update_id
    hb = {"arg": {"channel": "books", "instId": "FIL-USDT"}, "action": "update",
          "data": [{"asks": [], "bids": [], "ts": "1791381486004", "checksum": 0, "seqId": seq, "prevSeqId": seq}]}
    f.handle(json.dumps(hb), 9)
    f.handle("pong", 10)
    assert not f.books["FIL-USDT"].broken and f.books["FIL-USDT"].live


def test_okx_checksum_string_alternates_bid_and_ask_as_sent():
    # The example from OKX's websocket documentation.
    bk = OkxBook(400)
    bk.reset()
    bk.apply([["3366.1", "7", "0", "3"], ["3366", "6", "3", "4"]], True)
    bk.apply([["3366.8", "9", "10", "3"], ["3368", "8", "3", "4"]], False)
    crc = zlib.crc32(b"3366.1:7:3366.8:9:3366:6:3368:8")
    assert bk.checksum() == (crc - (1 << 32) if crc >= 1 << 31 else crc)
    # A deleted level leaves the checksum too.
    bk.apply([["3366", "0", "0", "0"]], True)
    crc = zlib.crc32(b"3366.1:7:3366.8:9:3368:8")
    assert bk.checksum() == (crc - (1 << 32) if crc >= 1 << 31 else crc)


def with_checksum(msg: str, value: int) -> str:
    m = json.loads(msg)
    m["data"][0]["checksum"] = value
    return json.dumps(m)


def test_okx_checksum_mismatch_acts_only_after_one_has_matched(tmp_path):
    msgs = okx_msgs()
    # Never matched: counted, the book keeps recording (a formatting bug here
    # must not become a resubscribe loop).
    f = feed(OkxBooks, tmp_path, OKX)
    replay(f, msgs[:3])
    f.handle(with_checksum(msgs[3], 12345), 9)
    assert f.state.counters["okx_checksum_mismatch"] == 1
    assert f.books["FIL-USDT"].live and f.pending == []

    # Matched once, then a mismatch: broken.
    f = feed(OkxBooks, tmp_path / "b", OKX)
    replay(f, msgs[:3])
    probe = OkxBook(400)
    probe.reset()
    for m in msgs[:4]:
        d = json.loads(m)["data"][0]
        probe.apply(d["bids"], True)
        probe.apply(d["asks"], False)
    f.handle(with_checksum(msgs[3], probe.checksum()), 9)
    assert f.books["FIL-USDT"].checksum_ok
    f.handle(with_checksum(msgs[4], 12345), 10)
    assert f.books["FIL-USDT"].broken and f.pending == ["FIL-USDT"]


# ---- Coinbase ---------------------------------------------------------------

CB = {"FIL-USD": "FIL"}


def test_coinbase_replay_builds_the_book(tmp_path):
    f = feed(CoinbaseBooks, tmp_path, CB)
    msgs = lines("coinbase_FIL-USD.jsonl")
    replay(f, msgs)
    bk = f.books["FIL-USD"]
    parsed = [json.loads(m) for m in msgs]
    snap = next(m for m in parsed if m["type"] == "snapshot")
    changes = [(s == "buy", p, q) for m in parsed if m["type"] == "l2update" for s, p, q in m["changes"]]
    assert bk.best() == reference_top(snap["bids"], snap["asks"], changes)
    assert bk.recordable() and bk.sound
    last = datetime.fromisoformat(parsed[-1]["time"].replace("Z", "+00:00"))
    assert bk.ts_exch_us == int(last.timestamp() * 1_000_000)


def crossing(px: str) -> str:
    return json.dumps({"type": "l2update", "product_id": "FIL-USD", "changes": [["buy", px, "1.0"]],
                       "time": "2026-10-07T13:58:06.000000Z"})


def test_coinbase_crossed_book_breaks_only_after_it_stays_crossed(tmp_path):
    f = feed(CoinbaseBooks, tmp_path, CB)
    replay(f, lines("coinbase_FIL-USD.jsonl")[:5])
    bk = f.books["FIL-USD"]
    ask = bk.best()[1]
    for i in range(CROSSED_LIMIT - 1):
        f.handle(crossing(str(ask + 0.01)), 50 + i)
        assert not bk.recordable(), "a crossed book is never written"
        assert not bk.broken
    f.handle(crossing(str(ask + 0.01)), 60)
    assert bk.broken and f.pending == ["FIL-USD"]


def test_coinbase_book_crossed_from_its_snapshot_is_not_resubscribed(tmp_path):
    f = feed(CoinbaseBooks, tmp_path, CB)
    snap = json.loads(lines("coinbase_FIL-USD.jsonl")[1])
    snap["bids"] = [["9.0", "1"]] + snap["bids"]       # crossed from the start: our bug, not theirs
    f.handle(json.dumps(snap), 1)
    for i in range(CROSSED_LIMIT + 2):
        f.handle(crossing("9.5"), 2 + i)
    assert not f.books["FIL-USD"].broken and f.pending == []


# ---- shared -----------------------------------------------------------------

def test_resync_guard_cannot_loop():
    t = [0.0]
    g = ResyncGuard(min_interval_s=60, max_per_hour=10, clock=lambda: t[0])
    assert g.allow("X")
    assert not g.allow("X"), "a second resync within the minute"
    allowed = 1
    for _ in range(30):
        t[0] += 61
        allowed += g.allow("X")
    assert allowed == 10 and "X" in g.given_up
    t[0] += 10_000
    assert not g.allow("X"), "given up stays given up"
    assert g.allow("Y"), "other symbols are not affected"


def test_a_broken_book_is_retried_by_maintain_once_the_guard_allows(tmp_path):
    t = [0.0]
    f = feed(BybitBooks, tmp_path, BYBIT)
    f.guard = ResyncGuard(clock=lambda: t[0])
    msgs = bybit_msgs()
    replay(f, msgs[:5])
    f.guard.allow("FILUSDT")        # a resync a moment ago
    f.handle(msgs[7], 9)
    asyncio.run(f.resync(f.pending.pop()))
    assert f.ws.sent == [], "too soon after the last one"
    t[0] += 61
    asyncio.run(f.maintain())
    assert len(f.ws.sent) == 2


def test_samples_land_in_book20_with_the_shared_schema(tmp_path):
    sinks = Sinks(tmp_path, 0)
    f = BybitBooks(None, sinks, State(), ["FIL"])
    f.symbols = BYBIT
    replay(f, lines("bybit_FILUSDT.jsonl"))
    assert f.sample(1_791_381_490_000_000) == 1
    asyncio.run(sinks.flush())
    files = list((tmp_path / "bybit" / "book20").rglob("*.parquet"))
    assert len(files) == 1 and "date=2026-10-07" in str(files[0])
    t = pq.read_table(files[0])
    assert t.schema == schemas.BOOK
    row = t.to_pylist()[0]
    assert row["symbol"] == "FILUSDT" and len(row["bid_px"]) == 20 and len(row["ask_qty"]) == 20
    assert row["bid_px"] == sorted(row["bid_px"], reverse=True) and row["ask_px"] == sorted(row["ask_px"])
    assert row["bid_px"][0] < row["ask_px"][0]


def test_low_disk_pauses_the_new_books_like_the_old_ones(tmp_path):
    sinks = Sinks(tmp_path, min_free_gb=1e12)  # never enough
    f = OkxBooks(None, sinks, State(), ["FIL"])
    f.symbols = OKX
    replay(f, lines("okx_FIL-USDT.jsonl"))
    f.sample(1_791_381_490_000_000)
    asyncio.run(sinks.flush())
    assert sinks.tables["okx/book20"].dropped == 1
    assert not list(tmp_path.rglob("*.parquet"))


def test_symbol_lists_keep_only_trading_pairs_in_the_right_quote():
    assert bybit_instruments([
        {"symbol": "FILUSDT", "baseCoin": "FIL", "quoteCoin": "USDT", "status": "Trading"},
        {"symbol": "FILUSDC", "baseCoin": "FIL", "quoteCoin": "USDC", "status": "Trading"},
        {"symbol": "OLDUSDT", "baseCoin": "OLD", "quoteCoin": "USDT", "status": "Closed"},
    ]) == {"FIL": "FILUSDT"}
    assert okx_instruments([
        {"instId": "FIL-USDT", "baseCcy": "FIL", "quoteCcy": "USDT", "state": "live"},
        {"instId": "FIL-EUR", "baseCcy": "FIL", "quoteCcy": "EUR", "state": "live"},
        {"instId": "NEW-USDT", "baseCcy": "NEW", "quoteCcy": "USDT", "state": "preopen"},
    ]) == {"FIL": "FIL-USDT"}
    assert parse_products([
        {"id": "FIL-USD", "base_currency": "FIL", "quote_currency": "USD", "status": "online", "trading_disabled": False},
        {"id": "FIL-EUR", "base_currency": "FIL", "quote_currency": "EUR", "status": "online", "trading_disabled": False},
        {"id": "OFF-USD", "base_currency": "OFF", "quote_currency": "USD", "status": "delisted", "trading_disabled": True},
    ]) == {"FIL": "FIL-USD"}


def test_pick_logs_what_a_venue_does_not_list(tmp_path, caplog):
    f = BybitBooks(None, Sinks(tmp_path, 0), State(), ["BTC", "TRX"])
    with caplog.at_level("WARNING"):
        assert f.pick({"BTC": "BTCUSDT"}) == {"BTCUSDT": "BTC"}
    assert "TRX" in caplog.text


@pytest.mark.parametrize("cls", [BybitBooks, OkxBooks, CoinbaseBooks])
def test_a_feed_registers_its_stream_before_it_connects(tmp_path, cls):
    st = State()
    cls(None, Sinks(tmp_path, 0), st, ["BTC"])
    assert cls.name in st.streams, "a venue that never connects must show as stale in status.json"
