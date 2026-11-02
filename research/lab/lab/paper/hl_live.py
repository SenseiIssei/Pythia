"""Hyperliquid executor for the M4H book, BUILT FOR LIVE BUT NOT ARMED. No job, cron or container runs its send path.

results/m4l.md (M4L, pre-registered in results/m4l_prereg.md). lab.paper.hl_dryrun builds the orders a bot would send
and lab.paper.m4_hl_small fills them on paper; this module is the rest of the way to real orders, for the day the
owner says yes (after at least 30 days of forward record, with an API wallet he makes himself on Hyperliquid):

  signing         Hyperliquid's L1 action (msgpack of the action, the nonce, no vault, keccak-256, the phantom
                  agent, EIP-712 typed data signed with secp256k1 by the API wallet), in plain Python (no new
                  dependency); tests/test_hl_live.py checks it against the test vectors of Hyperliquid's official
                  Python SDK, version 0.24.0 (tests/signing_test.py there)
  reconcile       read only, from the public info endpoint by the account's address (clearinghouseState,
                  openOrders, userFills): the held positions against the paper book's targets (its positions scaled
                  to the live account), the drift, the funding paid, the open orders, the last day's fills
  send            refuses unless every gate holds, each refusal a line in live/log.jsonl and a card:
                    env      ENV_FILE names the account's address (ADDRESS_VAR) and the API wallet's key file
                             (KEY_FILE_VAR), and that file exists
                    ack      ACK_FILE exists with ACK_LINE and a line date=YYYY-MM-DD not in the future
                    account  the account value at most MAX_ACCOUNT_USD (hl_dryrun's 250 USD)
                    gross    held and target gross at most MAX_GROSS (2x) of the account value
                    stop     the account above STOP_DRAWDOWN (-20 %) of the value at its first armed send; once
                             hit, stopped for good (live/state.json, only the owner clears it)
                    flat     no GO_FLAT in the book's folder (the owner closes in Hyperliquid's app)
                  then hl_dryrun.plan on the live positions (its own limits again), the orders signed and posted
                  to the exchange endpoint. The key is read only there, after every gate, and never printed.

Nothing here moves money out of the account: it signs order actions only (no transfer, no withdrawal; an API
wallet cannot withdraw). Variable names only in the repository; the owner fills the files on the server
(results/m4l.md has the runbook).

  python -m lab.paper.hl_live                 reconcile (read only); without ENV_FILE it does nothing
  python -m lab.paper.hl_live --send          the gated send path (no job calls it)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from . import hl_dryrun as hx
from .m4_hl_small import DIR as BOOK_DIR

ENV_FILE = Path("/etc/pythia/hl-live.env")
ACK_FILE = Path("/etc/pythia/hl-live.ack")
ADDRESS_VAR = "HL_LIVE_ADDRESS"            # the account's public address (the master account, not the API wallet)
KEY_FILE_VAR = "HL_LIVE_AGENT_KEY_FILE"    # the path of the file holding the API wallet's private key (hex)
ACK_LINE = "I accept that I can lose all of it"
MAX_ACCOUNT_USD = hx.MAX_ACCOUNT_USD
MAX_GROSS = hx.MAX_GROSS
STOP_DRAWDOWN = hx.STOP_DRAWDOWN
HL_API = "https://api.hyperliquid.xyz"
MAINNET = True
DAY_MS = 86_400_000


# ---------------------------------------------------------------- keccak-256 (Ethereum's, padding 0x01)

_M64 = (1 << 64) - 1
_ROT = (0, 1, 62, 28, 27, 36, 44, 6, 55, 20, 3, 10, 43, 25, 39, 41, 45, 15, 21, 8, 18, 2, 61, 56, 14)


def _round_constants() -> list[int]:
    out, r = [], 1
    for _ in range(24):
        rc = 0
        for j in range(7):
            r = ((r << 1) ^ ((r >> 7) * 0x71)) % 256
            if r & 2:
                rc ^= 1 << ((1 << j) - 1)
        out.append(rc)
    return out


_RC = _round_constants()


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & _M64 if n else x


def _permute(a: list[int]) -> list[int]:
    """Keccak-f[1600] on 25 lanes, lane (x, y) at x + 5y."""
    for rc in _RC:
        c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rol(c[(x + 1) % 5], 1) for x in range(5)]
        a = [a[i] ^ d[i % 5] for i in range(25)]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rol(a[x + 5 * y], _ROT[x + 5 * y])
        a = [b[i] ^ (~b[(i % 5 + 1) % 5 + 5 * (i // 5)] & b[(i % 5 + 2) % 5 + 5 * (i // 5)]) & _M64 for i in range(25)]
        a[0] ^= rc
    return a


def sponge256(data: bytes, pad: int) -> bytes:
    """A 256-bit Keccak sponge (rate 136 bytes): pad 0x01 is Ethereum's keccak-256, 0x06 is SHA3-256."""
    rate = 136
    msg = bytearray(data) + bytes([pad]) + bytes((-len(data) - 1) % rate)
    msg[-1] |= 0x80
    a = [0] * 25
    for off in range(0, len(msg), rate):
        for i in range(rate // 8):
            a[i] ^= int.from_bytes(msg[off + 8 * i:off + 8 * i + 8], "little")
        a = _permute(a)
    return b"".join(a[i].to_bytes(8, "little") for i in range(4))


def keccak256(data: bytes) -> bytes:
    return sponge256(data, 0x01)


# ---------------------------------------------------------------- msgpack (what msgpack.packb does by default)

def _head(n: int, fix: int | None, fix_max: int, tags: tuple) -> bytes:
    """A length header: the fix form below fix_max, else the 8 (None: none), 16 or 32 bit form."""
    if fix is not None and n < fix_max:
        return bytes([fix | n])
    for tag, size in zip(tags, (1, 2, 4)):
        if tag is not None and n < 1 << (8 * size):
            return bytes([tag]) + n.to_bytes(size, "big")
    raise ValueError(f"msgpack: {n} items is too long")


def packb(v) -> bytes:
    """msgpack of None, bools, ints, floats (as doubles), str, bytes, lists and dicts in their order."""
    if v is None:
        return b"\xc0"
    if v is True:
        return b"\xc3"
    if v is False:
        return b"\xc2"
    if isinstance(v, int):
        if 0 <= v < 128:
            return bytes([v])
        if -32 <= v < 0:
            return bytes([v & 0xFF])
        for lo, hi, tag, n in ((0, 1 << 8, 0xCC, 1), (0, 1 << 16, 0xCD, 2), (0, 1 << 32, 0xCE, 4),
                               (0, 1 << 64, 0xCF, 8), (-(1 << 7), 0, 0xD0, 1), (-(1 << 15), 0, 0xD1, 2),
                               (-(1 << 31), 0, 0xD2, 4), (-(1 << 63), 0, 0xD3, 8)):
            if lo <= v < hi:
                return bytes([tag]) + v.to_bytes(n, "big", signed=v < 0)
        raise ValueError(f"int out of msgpack's range: {v}")
    if isinstance(v, float):
        import struct
        return b"\xcb" + struct.pack(">d", v)
    if isinstance(v, str):
        b = v.encode("utf-8")
        return _head(len(b), 0xA0, 32, (0xD9, 0xDA, 0xDB)) + b
    if isinstance(v, (bytes, bytearray)):
        return _head(len(v), None, 0, (0xC4, 0xC5, 0xC6)) + bytes(v)
    if isinstance(v, (list, tuple)):
        return _head(len(v), 0x90, 16, (None, 0xDC, 0xDD)) + b"".join(packb(x) for x in v)
    if isinstance(v, dict):
        return _head(len(v), 0x80, 16, (None, 0xDE, 0xDF)) + b"".join(packb(k) + packb(x) for k, x in v.items())
    raise TypeError(f"msgpack: cannot pack {type(v).__name__}")


# ---------------------------------------------------------------- secp256k1, RFC 6979, Ethereum's (r, s, v)

_P = 2 ** 256 - 2 ** 32 - 977
_N = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_G = (0x79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798,
      0x483ADA7726A3C4655DA4FBFC0E1108A8FD17B448A68554199C47D08FFB10D4B8)


def _add(p, q):
    if p is None:
        return q
    if q is None:
        return p
    if p[0] == q[0] and (p[1] + q[1]) % _P == 0:
        return None
    if p == q:
        m = 3 * p[0] * p[0] * pow(2 * p[1], -1, _P) % _P
    else:
        m = (q[1] - p[1]) * pow(q[0] - p[0], -1, _P) % _P
    x = (m * m - p[0] - q[0]) % _P
    return x, (m * (p[0] - x) - p[1]) % _P


def _mul(k: int, p=_G):
    out = None
    while k:
        if k & 1:
            out = _add(out, p)
        p = _add(p, p)
        k >>= 1
    return out


def _rfc6979(d: int, h: bytes):
    """RFC 6979's deterministic nonces (HMAC-SHA256) for key d and digest h, as libsecp256k1 draws them."""
    x, z = d.to_bytes(32, "big"), (int.from_bytes(h, "big") % _N).to_bytes(32, "big")
    k, v = b"\x00" * 32, b"\x01" * 32
    k = hmac.new(k, v + b"\x00" + x + z, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    k = hmac.new(k, v + b"\x01" + x + z, hashlib.sha256).digest()
    v = hmac.new(k, v, hashlib.sha256).digest()
    while True:
        v = hmac.new(k, v, hashlib.sha256).digest()
        t = int.from_bytes(v, "big")
        if 1 <= t < _N:
            yield t
        k = hmac.new(k, v + b"\x00", hashlib.sha256).digest()
        v = hmac.new(k, v, hashlib.sha256).digest()


def sign_digest(digest: bytes, d: int) -> dict:
    """{"r", "s", "v"} of a 32-byte digest, s in the lower half and v 27 + the recovery id (eth_account's)."""
    if not 1 <= d < _N:
        raise ValueError("not a secp256k1 private key")
    e = int.from_bytes(digest, "big")
    for k in _rfc6979(d, digest):
        R = _mul(k)
        r = R[0] % _N
        if r == 0:
            continue
        s = pow(k, -1, _N) * (e + r * d) % _N
        if s == 0:
            continue
        rec = (R[1] & 1) | (2 if R[0] >= _N else 0)
        if s > _N // 2:
            s, rec = _N - s, rec ^ 1
        return {"r": hex(r), "s": hex(s), "v": 27 + rec}


def recover(digest: bytes, sig: dict):
    """The public key (x, y) that made sig over digest."""
    r, s, rec = int(sig["r"], 16), int(sig["s"], 16), int(sig["v"]) - 27
    x = r + (_N if rec & 2 else 0)
    y = pow((x ** 3 + 7) % _P, (_P + 1) // 4, _P)
    if (y & 1) != (rec & 1):
        y = _P - y
    e = int.from_bytes(digest, "big")
    ri = pow(r, -1, _N)
    return _add(_mul(s * ri % _N, (x, y)), _mul((-e * ri) % _N))


def address_of(pub) -> str:
    """The Ethereum address (lower case) of a public key."""
    return "0x" + keccak256(pub[0].to_bytes(32, "big") + pub[1].to_bytes(32, "big"))[-20:].hex()


# ---------------------------------------------------------------- Hyperliquid's L1 action

def action_hash(action, nonce: int, vault: str | None = None, expires_after: int | None = None) -> bytes:
    data = packb(action) + int(nonce).to_bytes(8, "big")
    data += b"\x00" if vault is None else b"\x01" + bytes.fromhex(vault[2:] if vault.startswith("0x") else vault)
    if expires_after is not None:
        data += b"\x00" + int(expires_after).to_bytes(8, "big")
    return keccak256(data)


def phantom_agent(h: bytes, mainnet: bool = MAINNET) -> dict:
    return {"source": "a" if mainnet else "b", "connectionId": h}


def _domain_separator() -> bytes:
    t = keccak256(b"EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)")
    return keccak256(t + keccak256(b"Exchange") + keccak256(b"1") + (1337).to_bytes(32, "big") + bytes(32))


def l1_digest(agent: dict) -> bytes:
    """EIP-712's digest of the phantom agent: domain Exchange, version 1, chain 1337, the zero contract."""
    t = keccak256(b"Agent(string source,bytes32 connectionId)")
    struct = keccak256(t + keccak256(agent["source"].encode()) + agent["connectionId"])
    return keccak256(b"\x19\x01" + _domain_separator() + struct)


def sign_l1_action(d: int, action, nonce: int, mainnet: bool = MAINNET, vault: str | None = None,
                   expires_after: int | None = None) -> dict:
    return sign_digest(l1_digest(phantom_agent(action_hash(action, nonce, vault, expires_after), mainnet)), d)


def float_to_wire(x) -> str:
    """The SDK's float_to_wire: at most 8 decimals, no trailing zeros; a value that would round raises."""
    rounded = f"{float(x):.8f}"
    if abs(float(rounded) - float(x)) >= 1e-12:
        raise ValueError(f"float_to_wire would round {x}")
    if rounded == "-0":
        rounded = "0"
    return f"{Decimal(rounded).normalize():f}"


def order_wire(asset: int, is_buy: bool, px, sz, reduce_only: bool, tif: str = "Ioc", cloid: str | None = None) -> dict:
    w = {"a": int(asset), "b": bool(is_buy), "p": float_to_wire(px), "s": float_to_wire(sz), "r": bool(reduce_only),
         "t": {"limit": {"tif": tif}}}
    if cloid is not None:
        w["c"] = cloid
    return w


def order_action(wires: list[dict]) -> dict:
    return {"type": "order", "orders": wires, "grouping": "na"}


def plan_action(orders: list[dict], assets: dict[str, int]) -> dict:
    """hl_dryrun.plan's orders as one order action (IOC limits, reduce-only where the plan says)."""
    return order_action([order_wire(assets[o["coin"]], o["side"] == "buy", o["limit_px"], o["size"], o["reduce_only"],
                                    o.get("tif", "Ioc")) for o in orders])


# ---------------------------------------------------------------- the owner's files

def read_env(path: Path = ENV_FILE) -> dict[str, str]:
    """KEY=VALUE lines (comments and blanks skipped, quotes stripped); {} without the file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def ack_problem(path: Path = ACK_FILE, now_ms: int | None = None) -> str | None:
    """None when the ack file holds ACK_LINE and a line date=YYYY-MM-DD not after today, else why not."""
    try:
        lines = [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines()]
    except OSError:
        return f"no ack file {path}"
    if ACK_LINE not in lines:
        return f"the ack file lacks the line '{ACK_LINE}'"
    dates = [m.group(1) for m in (re.fullmatch(r"date=(\d{4}-\d{2}-\d{2})", x) for x in lines) if m]
    if not dates:
        return "the ack file lacks a line date=YYYY-MM-DD"
    try:
        day = datetime.strptime(dates[-1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return f"the ack file's date {dates[-1]} is not a date"
    now = datetime.fromtimestamp((now_ms or time.time() * 1000) / 1000, timezone.utc)
    if day > now:
        return f"the ack file's date {dates[-1]} is in the future"
    return None


# ---------------------------------------------------------------- read only: the account against the book

def info(body: dict):
    req = urllib.request.Request(HL_API + "/info", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def account(address: str, fetch=info, now_ms: int | None = None) -> dict:
    """The account by its address: value, positions (signed units), their notional, the funding they paid since
    opened (Hyperliquid's cumFunding.sinceOpen), open orders and the last day's fills."""
    now_ms = now_ms or int(time.time() * 1000)
    cs = fetch({"type": "clearinghouseState", "user": address})
    pos, ntl, fund = {}, {}, {}
    for a in cs.get("assetPositions") or []:
        p = a.get("position") or {}
        u = float(p.get("szi") or 0)
        if u:
            pos[p["coin"]] = u
            ntl[p["coin"]] = abs(float(p.get("positionValue") or 0))
            fund[p["coin"]] = float((p.get("cumFunding") or {}).get("sinceOpen") or 0)
    orders = fetch({"type": "openOrders", "user": address}) or []
    fills = [f for f in fetch({"type": "userFills", "user": address}) or [] if int(f.get("time", 0)) > now_ms - DAY_MS]
    ms = cs.get("marginSummary") or {}
    return {"value": float(ms.get("accountValue") or 0), "positions": pos, "notional": ntl,
            "gross": sum(ntl.values()), "funding_since_open": fund, "funding_paid": sum(fund.values()),
            "open_orders": len(orders), "fills_24h": len(fills),
            "fees_24h": sum(float(f.get("fee") or 0) for f in fills)}


def book_targets(book: dict, value: float) -> dict[str, float]:
    """The paper book's positions (after today's fill) scaled from its equity to the live account's value."""
    eq = float(book.get("equity_usd") or 0)
    scale = hx.sizing_equity(value) / eq if eq > 0 else 0.0
    return {c: float(u) * scale for c, u in (book.get("units") or {}).items()}


def drift(positions: dict[str, float], targets: dict[str, float], mids: dict[str, float], value: float) -> float:
    """Half the sum of |live weight - target weight| over every coin either holds."""
    if not value > 0:
        return 0.0
    coins = set(positions) | set(targets)
    return 0.5 * sum(abs(positions.get(c, 0.0) - targets.get(c, 0.0)) * mids.get(c, 0.0) for c in coins) / value


def reconcile(env: dict, book: dict, mids: dict[str, float], fetch=info, now_ms: int | None = None) -> dict | None:
    """Read only: the live account against the paper book's targets; None without the address (nothing done)."""
    addr = env.get(ADDRESS_VAR)
    if not addr:
        return None
    acc = account(addr, fetch, now_ms)
    tgt = book_targets(book, acc["value"])
    return {**acc, "targets": tgt, "drift": drift(acc["positions"], tgt, mids, acc["value"]),
            "missing": sorted(c for c in tgt if c not in acc["positions"]),
            "extra": sorted(c for c in acc["positions"] if c not in tgt)}


# ---------------------------------------------------------------- the send path, behind every gate

def gates(env: dict, ack: str | None, acc: dict | None, target_gross: float, live: dict, flat: bool) -> list[str]:
    """Every reason not to send (empty: send). acc None: the account could not be read."""
    out = []
    if not env.get(ADDRESS_VAR):
        out.append(f"env: {ADDRESS_VAR} is not set in {ENV_FILE}")
    key = env.get(KEY_FILE_VAR)
    if not key:
        out.append(f"env: {KEY_FILE_VAR} is not set in {ENV_FILE}")
    elif not Path(key).is_file():
        out.append(f"env: {KEY_FILE_VAR} names no file")
    if ack:
        out.append(f"ack: {ack}")
    if acc is None:
        out.append("account: not read")
        return out
    v = acc["value"]
    if not 0 < v <= MAX_ACCOUNT_USD:
        out.append(f"account: value {v:.2f} USD is not in (0, {MAX_ACCOUNT_USD:.0f}] USD")
    if v > 0 and (acc["gross"] > MAX_GROSS * v + 1e-9 or target_gross > MAX_GROSS * v + 1e-9):
        out.append(f"gross: held {acc['gross']:.2f} or target {target_gross:.2f} USD above {MAX_GROSS:.0f}x "
                   f"the value {v:.2f} USD")
    start = live.get("start_usd")
    if live.get("stopped"):
        out.append("stop: stopped for good (live/state.json; only the owner clears it)")
    elif start and v <= start * (1 - STOP_DRAWDOWN):
        out.append(f"stop: the value {v:.2f} USD is at or below {1 - STOP_DRAWDOWN:.0%} of the start {start:.2f} USD")
    if flat:
        out.append(f"flat: {hx.FLAT_FILE} is set")
    return out


def refusal_card(why: list[str]):
    from ..ops import notify
    return notify.Card("⛔", "M4 live (Hyperliquid): nothing sent", f"{len(why)} gate(s) refused the send",
                       [notify.Line(w) for w in why], footer="lab.paper.hl_live")


def log_line(folder: Path, event: str, **kw) -> dict:
    row = {"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"), "event": event, **kw}
    (folder / "live").mkdir(parents=True, exist_ok=True)
    with (folder / "live" / "log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def exchange(payload: dict):
    req = urllib.request.Request(HL_API + "/exchange", data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def send(folder: Path = BOOK_DIR, env_file: Path = ENV_FILE, ack_file: Path = ACK_FILE, fetch=info, post=exchange,
         card=None, now_ms: int | None = None) -> dict:
    """The gated send: the live positions to the paper book's targets through hl_dryrun.plan, signed and posted.
    Any gate that fails: nothing read from the key file, nothing signed or sent, a log line and a card."""
    now_ms = now_ms or int(time.time() * 1000)
    folder = Path(folder)
    sf = folder / "live" / "state.json"
    live = json.loads(sf.read_text()) if sf.exists() else {}
    env = read_env(env_file)
    book = json.loads((folder / "state.json").read_text()) if (folder / "state.json").exists() else {}
    acc, plan, assets, mids, dec, why = None, None, {}, {}, {}, []
    if env.get(ADDRESS_VAR):
        try:
            meta, ctxs = fetch({"type": "metaAndAssetCtxs"})
            uni = meta.get("universe") or []
            assets = {u["name"]: i for i, u in enumerate(uni)}
            mids = {u["name"]: float(c.get("midPx") or c.get("markPx")) for u, c in zip(uni, ctxs)
                    if not u.get("isDelisted") and (c.get("midPx") or c.get("markPx"))}
            dec = {u["name"]: int(u.get("szDecimals", 0)) for u in uni}
            acc = account(env[ADDRESS_VAR], fetch, now_ms)
        except Exception as e:  # noqa: BLE001 - an unread account is a refusal, not a crash
            why.append(f"account: {type(e).__name__}: {e}")
    tgt = book_targets(book, acc["value"]) if acc else {}
    tgross = sum(abs(u) * mids.get(c, float("inf")) for c, u in tgt.items())
    flat = hx.flat_switch(folder)
    why += gates(env, ack_problem(ack_file, now_ms), acc, tgross, live, flat)
    if acc and not why:
        start = float(live.get("start_usd") or acc["value"])
        plan = hx.plan(acc["positions"], tgt, mids, dec, acc["value"], start, flat=flat,
                       stopped=bool(live.get("stopped")))
        if plan["mode"] != "trade":
            why.append(f"plan: {plan['mode']}: {plan['why']}")
        elif any(o["coin"] not in assets for o in plan["orders"]):
            why.append("plan: an order for a coin Hyperliquid does not list")
    if acc and live.get("start_usd") and acc["value"] <= live["start_usd"] * (1 - STOP_DRAWDOWN):
        live["stopped"] = True
    if why:
        log_line(folder, "refused", why=why)
        c = refusal_card(why)
        if card is None:
            from ..ops import notify
            notify.send("trades", c)
        else:
            card(c)
        if live:
            sf.write_text(json.dumps(live, indent=2))
        return {"sent": False, "why": why}
    if not plan["orders"]:
        log_line(folder, "nothing to send", value=acc["value"])
        return {"sent": False, "why": [], "orders": 0}
    d = int(Path(env[KEY_FILE_VAR]).read_text(encoding="utf-8").strip().removeprefix("0x"), 16)
    nonce = max(now_ms, int(live.get("last_nonce") or 0) + 1)
    action = plan_action(plan["orders"], assets)
    sig = sign_l1_action(d, action, nonce)
    del d
    answer = post({"action": action, "nonce": nonce, "signature": sig, "vaultAddress": None, "expiresAfter": None})
    live.update(start_usd=live.get("start_usd") or acc["value"], last_nonce=nonce, stopped=bool(live.get("stopped")))
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps(live, indent=2))
    log_line(folder, "sent", orders=len(plan["orders"]), nonce=nonce, value=acc["value"], answer=answer)
    return {"sent": True, "orders": len(plan["orders"]), "answer": answer}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--send" in argv:
        res = send()
        print(json.dumps(res))
        return 0 if res.get("sent") or not res.get("why") else 1
    env = read_env()
    if not env.get(ADDRESS_VAR):
        print(f"no {ADDRESS_VAR} in {ENV_FILE}: nothing to do")
        return 0
    meta, ctxs = info({"type": "metaAndAssetCtxs"})
    mids = {u["name"]: float(c.get("midPx") or c.get("markPx") or 0) for u, c in zip(meta.get("universe") or [], ctxs)}
    book = json.loads((BOOK_DIR / "state.json").read_text()) if (BOOK_DIR / "state.json").exists() else {}
    rec = reconcile(env, book, mids)
    (BOOK_DIR / "live").mkdir(parents=True, exist_ok=True)
    (BOOK_DIR / "live" / "reconcile.json").write_text(json.dumps(rec, indent=2))
    print(json.dumps({k: rec[k] for k in ("value", "gross", "drift", "funding_paid", "open_orders", "fills_24h",
                                          "missing", "extra")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
