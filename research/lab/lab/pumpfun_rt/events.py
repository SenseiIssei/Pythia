"""Decoding pump.fun and PumpSwap events from transaction logs. Read only.

Both programs publish their events as Anchor events: a log line
"Program data: <base64>" whose first 8 bytes are the event's discriminator
(sha256("event:<Name>")[:8]) and whose rest is the event's fields in Borsh.
The layouts are the public IDLs (github.com/pump-fun/pump-public-docs,
idl/pump.json and idl/pump_amm.json, as of 2026-10-20). Fields are only ever
appended to an event, so the decoder reads them in order and stops where the
bytes end: an older, shorter event decodes to its prefix, a newer, longer one
to the fields known here.

A "Program data:" line is attributed to the program on top of the invoke
stack the logs describe ("Program <id> invoke [n]" ... "Program <id>
success"), so an event logged by some other program with the same leading
bytes is never taken for one of these.
"""

from __future__ import annotations

import base64
import struct

PUMP = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
PUMP_AMM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
DEFAULT_KEY = "11111111111111111111111111111111"

_B58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def b58(raw: bytes) -> str:
    """Base58 of a public key (the usual Solana text form)."""
    n = int.from_bytes(raw, "big")
    out = []
    while n:
        n, r = divmod(n, 58)
        out.append(_B58[r])
    pad = len(raw) - len(raw.lstrip(b"\0"))
    return "1" * pad + "".join(reversed(out))


def b58decode(s: str) -> bytes:
    n = 0
    for ch in s:
        n = n * 58 + _B58.index(ch)
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\0" * pad + body


# ---------------------------------------------------------------- layouts

PUBKEY, U8, U16, U64, I64, I128, BOOL, STRING, SHAREHOLDERS = (
    "pubkey", "u8", "u16", "u64", "i64", "i128", "bool", "string", "shareholders")

LAYOUTS: dict[str, list[tuple[str, str]]] = {
    "CreateEvent": [
        ("name", STRING), ("symbol", STRING), ("uri", STRING), ("mint", PUBKEY), ("bonding_curve", PUBKEY),
        ("user", PUBKEY), ("creator", PUBKEY), ("timestamp", I64), ("virtual_token_reserves", U64),
        ("virtual_sol_reserves", U64), ("real_token_reserves", U64), ("token_total_supply", U64),
        ("token_program", PUBKEY), ("is_mayhem_mode", BOOL), ("is_cashback_enabled", BOOL), ("quote_mint", PUBKEY),
        ("virtual_quote_reserves", U64), ("creator_fee_bps", U64), ("is_holder_reward", BOOL), ("depth", U8)],
    "TradeEvent": [
        ("mint", PUBKEY), ("sol_amount", U64), ("token_amount", U64), ("is_buy", BOOL), ("user", PUBKEY),
        ("timestamp", I64), ("virtual_sol_reserves", U64), ("virtual_token_reserves", U64),
        ("real_sol_reserves", U64), ("real_token_reserves", U64), ("fee_recipient", PUBKEY),
        ("fee_basis_points", U64), ("fee", U64), ("creator", PUBKEY), ("creator_fee_basis_points", U64),
        ("creator_fee", U64), ("track_volume", BOOL), ("total_unclaimed_tokens", U64),
        ("total_claimed_tokens", U64), ("current_sol_volume", U64), ("last_update_timestamp", I64),
        ("ix_name", STRING), ("mayhem_mode", BOOL), ("cashback_fee_basis_points", U64), ("cashback", U64),
        ("buyback_fee_basis_points", U64), ("buyback_fee", U64), ("shareholders", SHAREHOLDERS),
        ("quote_mint", PUBKEY), ("quote_amount", U64), ("virtual_quote_reserves", U64),
        ("real_quote_reserves", U64)],
    "CompleteEvent": [("user", PUBKEY), ("mint", PUBKEY), ("bonding_curve", PUBKEY), ("timestamp", I64),
                      ("quote_mint", PUBKEY)],
    "CompletePumpAmmMigrationEvent": [
        ("user", PUBKEY), ("mint", PUBKEY), ("mint_amount", U64), ("sol_amount", U64), ("pool_migration_fee", U64),
        ("bonding_curve", PUBKEY), ("timestamp", I64), ("pool", PUBKEY), ("quote_mint", PUBKEY)],
    "BuyEvent": [
        ("timestamp", I64), ("base_amount_out", U64), ("max_quote_amount_in", U64),
        ("user_base_token_reserves", U64), ("user_quote_token_reserves", U64), ("pool_base_token_reserves", U64),
        ("pool_quote_token_reserves", U64), ("quote_amount_in", U64), ("lp_fee_basis_points", U64), ("lp_fee", U64),
        ("protocol_fee_basis_points", U64), ("protocol_fee", U64), ("quote_amount_in_with_lp_fee", U64),
        ("user_quote_amount_in", U64), ("pool", PUBKEY), ("user", PUBKEY), ("user_base_token_account", PUBKEY),
        ("user_quote_token_account", PUBKEY), ("protocol_fee_recipient", PUBKEY),
        ("protocol_fee_recipient_token_account", PUBKEY), ("coin_creator", PUBKEY),
        ("coin_creator_fee_basis_points", U64), ("coin_creator_fee", U64)],
    "SellEvent": [
        ("timestamp", I64), ("base_amount_in", U64), ("min_quote_amount_out", U64),
        ("user_base_token_reserves", U64), ("user_quote_token_reserves", U64), ("pool_base_token_reserves", U64),
        ("pool_quote_token_reserves", U64), ("quote_amount_out", U64), ("lp_fee_basis_points", U64), ("lp_fee", U64),
        ("protocol_fee_basis_points", U64), ("protocol_fee", U64), ("quote_amount_out_without_lp_fee", U64),
        ("user_quote_amount_out", U64), ("pool", PUBKEY), ("user", PUBKEY), ("user_base_token_account", PUBKEY),
        ("user_quote_token_account", PUBKEY), ("protocol_fee_recipient", PUBKEY),
        ("protocol_fee_recipient_token_account", PUBKEY), ("coin_creator", PUBKEY),
        ("coin_creator_fee_basis_points", U64), ("coin_creator_fee", U64)],
}

# Discriminators from the IDLs (sha256("event:<Name>")[:8]).
DISC: dict[bytes, tuple[str, str]] = {
    bytes([27, 114, 169, 77, 222, 235, 99, 118]): (PUMP, "CreateEvent"),
    bytes([189, 219, 127, 211, 78, 230, 97, 238]): (PUMP, "TradeEvent"),
    bytes([95, 114, 97, 156, 212, 46, 152, 8]): (PUMP, "CompleteEvent"),
    bytes([189, 233, 93, 185, 92, 148, 234, 148]): (PUMP, "CompletePumpAmmMigrationEvent"),
    bytes([103, 244, 82, 31, 44, 245, 119, 119]): (PUMP_AMM, "BuyEvent"),
    bytes([62, 47, 55, 10, 165, 3, 220, 42]): (PUMP_AMM, "SellEvent"),
}
# What each event needs at the least to be of any use; shorter is dropped.
REQUIRED = {"CreateEvent": "virtual_sol_reserves", "TradeEvent": "real_token_reserves",
            "CompleteEvent": "mint", "CompletePumpAmmMigrationEvent": "pool",
            "BuyEvent": "user", "SellEvent": "user"}

_FIXED = {U8: (1, "<B"), U16: (2, "<H"), U64: (8, "<Q"), I64: (8, "<q"), BOOL: (1, "<?")}


def decode(name: str, buf: bytes, pos: int = 8) -> dict:
    """The fields of event `name` from buf[pos:], in order, up to where the bytes end."""
    out: dict = {}
    n = len(buf)
    for field, kind in LAYOUTS[name]:
        if kind == PUBKEY:
            if pos + 32 > n:
                break
            out[field] = b58(buf[pos:pos + 32])
            pos += 32
        elif kind in _FIXED:
            size, fmt = _FIXED[kind]
            if pos + size > n:
                break
            out[field] = struct.unpack_from(fmt, buf, pos)[0]
            pos += size
        elif kind == I128:
            if pos + 16 > n:
                break
            out[field] = int.from_bytes(buf[pos:pos + 16], "little", signed=True)
            pos += 16
        elif kind == STRING:
            if pos + 4 > n:
                break
            ln = struct.unpack_from("<I", buf, pos)[0]
            if pos + 4 + ln > n or ln > 4096:
                break
            out[field] = buf[pos + 4:pos + 4 + ln].decode("utf-8", "replace")
            pos += 4 + ln
        elif kind == SHAREHOLDERS:
            if pos + 4 > n:
                break
            k = struct.unpack_from("<I", buf, pos)[0]
            if k > 64 or pos + 4 + k * 34 > n:
                break
            pos += 4 + k * 34
            out[field] = k
        else:                                                    # pragma: no cover
            raise ValueError(kind)
    return out


def program_data(logs: list[str]) -> list[tuple[str, bytes]]:
    """(program, bytes) of every "Program data:" line, attributed by the invoke stack."""
    stack: list[str] = []
    out = []
    for line in logs:
        if line.startswith("Program data: "):
            if stack:
                try:
                    out.append((stack[-1], base64.b64decode(line[14:], validate=False)))
                except ValueError:
                    pass
            continue
        if not line.startswith("Program "):
            if line.startswith("Log truncated"):
                break
            continue
        parts = line.split(" ")
        if len(parts) >= 4 and parts[2] == "invoke":
            stack.append(parts[1])
        elif len(parts) >= 3 and parts[2] in ("success", "failed", "failed:"):
            if stack and stack[-1] == parts[1]:
                stack.pop()
    return out


def events_of(logs: list[str]) -> list[tuple[str, dict]]:
    """Every known pump.fun and PumpSwap event in one transaction's logs, in order."""
    out = []
    for prog, buf in program_data(logs):
        hit = DISC.get(buf[:8])
        if hit is None or hit[0] != prog:
            continue
        name = hit[1]
        ev = decode(name, buf)
        if REQUIRED[name] in ev:
            out.append((name, ev))
    return out


def sol_quoted(quote_mint: str | None) -> bool:
    """A curve or pool quoted in SOL (older events carry no quote mint: SOL)."""
    return quote_mint in (None, "", WSOL, DEFAULT_KEY)


def compact(name: str, ev: dict, t: int, slot: int, tx: int, sig: str = "") -> tuple[str, dict] | None:
    """The compact record the store keeps, as (table, row); None for what is not kept."""
    if name == "CreateEvent":
        return "creates", {
            "t": t, "slot": slot, "tx": tx, "sig": sig, "mint": ev["mint"], "bc": ev.get("bonding_curve"),
            "user": ev.get("user"), "creator": ev.get("creator") or ev.get("user"), "name": ev.get("name", "")[:64],
            "symbol": ev.get("symbol", "")[:32], "uri": ev.get("uri", "")[:200],
            "vt": ev.get("virtual_token_reserves"), "vs": ev.get("virtual_sol_reserves"),
            "rt": ev.get("real_token_reserves"), "supply": ev.get("token_total_supply"),
            "mayhem": bool(ev.get("is_mayhem_mode", False)), "cashback": bool(ev.get("is_cashback_enabled", False)),
            "quote": None if sol_quoted(ev.get("quote_mint")) else ev.get("quote_mint"),
            "cfb": ev.get("creator_fee_bps"), "bts": ev.get("timestamp")}
    if name == "TradeEvent":
        q = ev.get("quote_mint")
        return "trades", {
            "t": t, "slot": slot, "tx": tx, "mint": ev["mint"], "buy": bool(ev["is_buy"]), "sol": ev["sol_amount"],
            "tok": ev["token_amount"], "user": ev["user"], "vs": ev["virtual_sol_reserves"],
            "vt": ev["virtual_token_reserves"], "rs": ev["real_sol_reserves"], "rt": ev["real_token_reserves"],
            "fb": ev.get("fee_basis_points"), "cfb": ev.get("creator_fee_basis_points"),
            "ix": (ev.get("ix_name") or "")[:24], "quote": None if sol_quoted(q) else q, "bts": ev.get("timestamp")}
    if name == "CompleteEvent":
        return "other", {"kind": "complete", "t": t, "slot": slot, "tx": tx, "mint": ev["mint"],
                         "user": ev.get("user"), "pool": None, "sol": None, "tok": None, "bts": ev.get("timestamp")}
    if name == "CompletePumpAmmMigrationEvent":
        return "other", {"kind": "migrate", "t": t, "slot": slot, "tx": tx, "mint": ev["mint"],
                         "user": ev.get("user"), "pool": ev["pool"], "sol": ev.get("sol_amount"),
                         "tok": ev.get("mint_amount"), "bts": ev.get("timestamp")}
    if name in ("BuyEvent", "SellEvent"):
        buy = name == "BuyEvent"
        return "amm", {
            "t": t, "slot": slot, "tx": tx, "pool": ev.get("pool"), "mint": None, "buy": buy,
            "base": ev.get("base_amount_out") if buy else ev.get("base_amount_in"),
            "quote": ev.get("quote_amount_in") if buy else ev.get("quote_amount_out"),
            "user": ev.get("user"), "pb": ev.get("pool_base_token_reserves"), "pq": ev.get("pool_quote_token_reserves"),
            "lpb": ev.get("lp_fee_basis_points"), "pfb": ev.get("protocol_fee_basis_points"),
            "cfb": ev.get("coin_creator_fee_basis_points"), "bts": ev.get("timestamp")}
    return None
