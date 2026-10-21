"""A Yellowstone gRPC (Geyser) feed of pump.fun transactions for the collector. Read only.

Used only when the owner configures a provider: PYTHIA_SOLANA_GRPC_URL (https://host:port of the
provider's Yellowstone endpoint) and PYTHIA_SOLANA_GRPC_TOKEN (its x-token, read from the
environment, never written into a file of this repository, never printed). Needs the grpcio
package; without it, or when the endpoint fails, the collector keeps its websocket links (the
public endpoint at the least), so the record goes on either way.

The few protobuf messages needed are encoded and decoded here by hand (wire format), with the
field numbers of Yellowstone's published geyser.proto and solana-storage.proto:

  SubscribeRequest      transactions = 3 (map<string, SubscribeRequestFilterTransactions>),
                        commitment = 6, ping = 9 (SubscribeRequestPing { id = 1 })
  ...FilterTransactions vote = 1, failed = 2, account_include = 3
  SubscribeUpdate       filters = 1, transaction = 4, ping = 6, pong = 9
  ...UpdateTransaction  transaction = 1 (SubscribeUpdateTransactionInfo), slot = 2
  ...TransactionInfo    signature = 1 (bytes), is_vote = 2, meta = 4 (TransactionStatusMeta), index = 5
  TransactionStatusMeta err = 1, log_messages = 6

So a provider's stream turns into the same (slot, signature, failed, logs) the websocket gives,
plus the transaction's index in its block (its order inside the slot). Check against the
provider's own documentation before relying on it; a mismatch shows as zero decoded events in
the heartbeat ("first_by_source" has no "grpc" entry).
"""

from __future__ import annotations

import asyncio
import sys
import time
import urllib.parse

from . import events as E

METHOD = "/geyser.Geyser/Subscribe"
COMMITMENT = {"processed": 0, "confirmed": 1, "finalized": 2}
PING_S = 10.0


# ---------------------------------------------------------------- wire format

def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _field(num: int, wire: int, payload: bytes | int) -> bytes:
    tag = _varint((num << 3) | wire)
    if wire == 0:
        return tag + _varint(int(payload))
    return tag + _varint(len(payload)) + payload


def subscribe_request(programs: list[str], commitment: str = "confirmed", name: str = "pump") -> bytes:
    """SubscribeRequest: every successful non-vote transaction that mentions one of the programs."""
    flt = _field(1, 0, 0) + _field(2, 0, 0) + b"".join(_field(3, 2, p.encode()) for p in programs)
    entry = _field(1, 2, name.encode()) + _field(2, 2, flt)
    return _field(3, 2, entry) + _field(6, 0, COMMITMENT.get(commitment, 1))


def ping_request(i: int) -> bytes:
    return _field(9, 2, _field(1, 0, i))


def fields(buf: bytes):
    """(field number, wire type, value) of a message: an int for varints, bytes for the rest."""
    pos, n = 0, len(buf)
    while pos < n:
        key, pos = _read_varint(buf, pos)
        num, wire = key >> 3, key & 7
        if wire == 0:
            v, pos = _read_varint(buf, pos)
        elif wire == 1:
            v, pos = buf[pos:pos + 8], pos + 8
        elif wire == 2:
            ln, pos = _read_varint(buf, pos)
            v, pos = buf[pos:pos + ln], pos + ln
        elif wire == 5:
            v, pos = buf[pos:pos + 4], pos + 4
        else:
            raise ValueError(f"wire type {wire}")
        if pos > n:
            raise ValueError("truncated message")
        yield num, wire, v


def _read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    out = shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        out |= (b & 0x7F) << shift
        if not b & 0x80:
            return out, pos
        shift += 7


def parse_update(buf: bytes) -> tuple[str, dict | None]:
    """("tx", {slot, sig, failed, logs, index}), ("ping", None), ("pong", None) or ("other", None)."""
    for num, wire, v in fields(buf):
        if num == 4 and wire == 2:
            return "tx", _transaction(v)
        if num == 6 and wire == 2:
            return "ping", None
        if num == 9 and wire == 2:
            return "pong", None
    return "other", None


def _transaction(buf: bytes) -> dict:
    out = {"slot": 0, "sig": "", "failed": False, "logs": [], "index": None, "vote": False}
    for num, wire, v in fields(buf):
        if num == 2 and wire == 0:
            out["slot"] = v
        elif num == 1 and wire == 2:
            for n2, w2, v2 in fields(v):
                if n2 == 1 and w2 == 2:
                    out["sig"] = E.b58(v2)
                elif n2 == 2 and w2 == 0:
                    out["vote"] = bool(v2)
                elif n2 == 5 and w2 == 0:
                    out["index"] = v2
                elif n2 == 4 and w2 == 2:
                    for n3, w3, v3 in fields(v2):
                        if n3 == 1 and w3 == 2 and v3:
                            out["failed"] = True
                        elif n3 == 6 and w3 == 2:
                            out["logs"].append(v3.decode("utf-8", "replace"))
    return out


# ---------------------------------------------------------------- the stream

def target(url: str) -> str:
    """host:port of an https URL (the channel's target)."""
    u = urllib.parse.urlsplit(url)
    return f"{u.hostname}:{u.port or 443}"


def available() -> bool:
    try:
        import grpc  # noqa: F401
    except ImportError:
        return False
    return True


async def stream(url: str, token: str, programs: list[str], commitment: str, on_tx, stop: asyncio.Event,
                 on_up=None, on_down=None, log=None) -> None:
    """Subscribe and hand every transaction to on_tx(slot, sig, failed, logs, recv_ms, index), reconnecting
    with backoff until stop is set. Errors are printed without the URL or the token."""
    import grpc
    log = log or (lambda s: print(s, file=sys.stderr))
    backoff = 0.5
    while not stop.is_set():
        t_conn = time.monotonic()
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put(subscribe_request(programs, commitment))

        async def requests():
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item

        try:
            async with grpc.aio.secure_channel(target(url), grpc.ssl_channel_credentials(),
                                               options=[("grpc.max_receive_message_length", 64 << 20)]) as ch:
                call = ch.stream_stream(METHOD, request_serializer=lambda b: b, response_deserializer=lambda b: b)
                meta = [("x-token", token)] if token else None
                responses = call(requests(), metadata=meta)
                if on_up:
                    on_up()
                pings = 0
                last_ping = time.monotonic()
                async for raw in responses:
                    if stop.is_set():
                        break
                    kind, tx = parse_update(raw)
                    if kind == "tx" and tx is not None and not tx["vote"]:
                        on_tx(tx["slot"], tx["sig"], tx["failed"], tx["logs"], int(time.time() * 1000), tx["index"])
                    elif kind == "ping" or time.monotonic() - last_ping > PING_S:
                        pings += 1
                        last_ping = time.monotonic()
                        await queue.put(ping_request(pings))
        except Exception as e:                                  # grpc.aio raises its own error types
            log(f"collector: grpc feed {type(e).__name__}")
        finally:
            await queue.put(None)
        if on_down:
            on_down()
        if stop.is_set():
            break
        if time.monotonic() - t_conn > 60:
            backoff = 0.5
        await asyncio.sleep(backoff)
        backoff = min(60.0, backoff * 2)
