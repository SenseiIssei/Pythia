"""Plain pump.fun and PumpSwap buy and sell transactions, built byte by byte.

Pure functions: no key, no signing, no network. live_exec.py (LOCKED) signs and
sends what this builds; the tests check it with a fake signer.

Only the programs' own public buy and sell instructions, with a compute-unit
limit and price, the associated token accounts they need, and (in the pool)
wrapping and unwrapping SOL. No bundles, no private relays, nothing that
front-runs, sandwiches or moves a price on purpose. The one exception, off
unless the owner sets PYTHIA_PUMPFUN_JITO=1: a tip of at most
MAX_TIP_LAMPORTS to a published Jito tip account inside our OWN single buy or
sale (never a bundle with anyone else's transaction).

`compile_template` compiles a message once with the places of the blockhash and
of each instruction's data recorded, so the fast path (fastpath.py) only patches
the amounts, the compute-unit price and the blockhash at the signal.

The account lists and argument names are the ones in pump.fun's public IDLs
(github.com/pump-fun/pump-public-docs, idl/pump.json and idl/pump_amm.json) as
written here. `check_idl` compares them with the owner's copy of the IDL and
the live gate refuses on any difference; writability and signer flags, the
instruction discriminators and the on-chain account offsets are taken from
that IDL when it is given, so a program upgrade that reorders or adds an
account stops the executor instead of sending something wrong.
"""

from __future__ import annotations

import functools
import hashlib
import struct
from dataclasses import dataclass

from .events import PUMP, PUMP_AMM, WSOL, b58, b58decode

SYSTEM = "11111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuJvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
FEE_PROGRAM = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"

PUMP_BUY = ["global", "fee_recipient", "mint", "bonding_curve", "associated_bonding_curve", "associated_user", "user",
            "system_program", "token_program", "creator_vault", "event_authority", "program",
            "global_volume_accumulator", "user_volume_accumulator", "fee_config", "fee_program"]
PUMP_SELL = ["global", "fee_recipient", "mint", "bonding_curve", "associated_bonding_curve", "associated_user", "user",
             "system_program", "creator_vault", "token_program", "event_authority", "program", "fee_config",
             "fee_program"]
AMM_COMMON = ["pool", "user", "global_config", "base_mint", "quote_mint", "user_base_token_account",
              "user_quote_token_account", "pool_base_token_account", "pool_quote_token_account",
              "protocol_fee_recipient", "protocol_fee_recipient_token_account", "base_token_program",
              "quote_token_program", "system_program", "associated_token_program", "event_authority", "program",
              "coin_creator_vault_ata", "coin_creator_vault_authority"]
AMM_BUY = AMM_COMMON + ["global_volume_accumulator", "user_volume_accumulator", "fee_config", "fee_program"]
AMM_SELL = AMM_COMMON + ["fee_config", "fee_program"]
ARGS = {("pump", "buy"): ["amount", "max_sol_cost", "track_volume"],
        ("pump", "sell"): ["amount", "min_sol_output"],
        ("amm", "buy"): ["base_amount_out", "max_quote_amount_in", "track_volume"],
        ("amm", "sell"): ["base_amount_in", "min_quote_amount_out"]}
ACCOUNTS = {("pump", "buy"): PUMP_BUY, ("pump", "sell"): PUMP_SELL, ("amm", "buy"): AMM_BUY, ("amm", "sell"): AMM_SELL}
# Writable accounts when no IDL is given (tests); the IDL's flags win otherwise.
WRITABLE = {"fee_recipient", "bonding_curve", "associated_bonding_curve", "associated_user", "user", "creator_vault",
            "global_volume_accumulator", "user_volume_accumulator", "pool", "user_base_token_account",
            "user_quote_token_account", "pool_base_token_account", "pool_quote_token_account",
            "protocol_fee_recipient_token_account", "coin_creator_vault_ata"}
SIGNERS = {"user"}
# Field offsets in the programs' accounts (after the 8-byte discriminator), used only without an IDL.
OFFSETS = {("Global", "fee_recipient"): 41, ("BondingCurve", "creator"): 49,
           ("GlobalConfig", "protocol_fee_recipients"): 57, ("Pool", "base_mint"): 43, ("Pool", "quote_mint"): 75,
           ("Pool", "pool_base_token_account"): 139, ("Pool", "pool_quote_token_account"): 171,
           ("Pool", "coin_creator"): 211}


# ---------------------------------------------------------------- keys and addresses

_P = 2 ** 255 - 19
_D = (-121665 * pow(121666, _P - 2, _P)) % _P


def on_curve(b: bytes) -> bool:
    """Whether 32 bytes decompress to a point of ed25519 (a program address must not)."""
    y = int.from_bytes(b, "little") & ((1 << 255) - 1)
    y %= _P
    y2 = y * y % _P
    u = (y2 - 1) % _P
    v = (_D * y2 + 1) % _P
    # x^2 = u / v has a root when u / v is a square, i.e. when u * v is (Legendre(1/v) = Legendre(v)); the
    # Jacobi symbol equals the Legendre symbol for the prime p and is four times faster than Euler's power
    return u == 0 or _jacobi(u * v % _P, _P) == 1


def _jacobi(a: int, n: int) -> int:
    a %= n
    r = 1
    while a:
        z = (a & -a).bit_length() - 1
        a >>= z
        if z & 1 and n & 7 in (3, 5):
            r = -r
        if a & 3 == 3 and n & 3 == 3:
            r = -r
        a, n = n % a, a
    return r if n == 1 else 0


def key(s: str | bytes) -> bytes:
    return s if isinstance(s, bytes) else _key(s)


@functools.lru_cache(maxsize=65_536)
def _key(s: str) -> bytes:
    return b58decode(s).rjust(32, b"\0")


def pda(seeds: list[bytes | str], program: str) -> str:
    """find_program_address: the first bump from 255 down whose hash is off the curve (memoised: the
    fast path asks for the same program-wide addresses again and again)."""
    return _pda(tuple(s if isinstance(s, bytes) else key(s) for s in seeds), program)


@functools.lru_cache(maxsize=65_536)
def _pda(raw: tuple, program: str) -> str:
    prog = key(program)
    for bump in range(255, -1, -1):
        h = hashlib.sha256(b"".join(raw) + bytes([bump]) + prog + b"ProgramDerivedAddress").digest()
        if not on_curve(h):
            return b58(h)
    raise ValueError("no program address")


def ata(owner: str, mint: str, token_program: str = TOKEN) -> str:
    return pda([key(owner), key(token_program), key(mint)], ATA_PROGRAM)


def discriminator(name: str) -> bytes:
    return hashlib.sha256(f"global:{name}".encode()).digest()[:8]


# ---------------------------------------------------------------- instructions and messages

@dataclass
class Ix:
    program: str
    accounts: list[tuple[str, bool, bool]]          # (key, signer, writable)
    data: bytes


def shortvec(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def compile_message(payer: str, ixs: list[Ix], blockhash: str) -> bytes:
    """A legacy transaction message: header, account keys, recent blockhash, instructions."""
    flags: dict[str, list[bool]] = {payer: [True, True]}
    order = [payer]
    for ix in ixs:
        for k, s, w in ix.accounts:
            if k not in flags:
                flags[k] = [False, False]
                order.append(k)
            flags[k][0] |= s
            flags[k][1] |= w
        if ix.program not in flags:
            flags[ix.program] = [False, False]
            order.append(ix.program)
    groups = ([k for k in order if flags[k][0] and flags[k][1]], [k for k in order if flags[k][0] and not flags[k][1]],
              [k for k in order if not flags[k][0] and flags[k][1]],
              [k for k in order if not flags[k][0] and not flags[k][1]])
    keys = [k for g in groups for k in g]
    if keys[0] != payer:
        raise ValueError("the payer must sign and pay")
    idx = {k: i for i, k in enumerate(keys)}
    out = bytearray([len(groups[0]) + len(groups[1]), len(groups[1]), len(groups[3])])
    out += shortvec(len(keys))
    for k in keys:
        out += key(k)
    out += key(blockhash)
    out += shortvec(len(ixs))
    for ix in ixs:
        out.append(idx[ix.program])
        out += shortvec(len(ix.accounts))
        out += bytes(idx[k] for k, _, _ in ix.accounts)
        out += shortvec(len(ix.data))
        out += ix.data
    return bytes(out)


@dataclass
class Compiled:
    """A compiled message and where to patch it: the blockhash's offset and each instruction's data offset."""
    message: bytes
    blockhash_at: int
    data_at: list[int]


def compile_template(payer: str, ixs: list[Ix], blockhash: str = SYSTEM) -> Compiled:
    """compile_message with the offsets of the blockhash and of every instruction's data recorded."""
    msg = compile_message(payer, ixs, blockhash)
    nkeys_at = 3
    n = 0
    shift = 0
    pos = nkeys_at
    while True:                                            # the shortvec of the key count
        b = msg[pos]
        n |= (b & 0x7F) << shift
        pos += 1
        if not b & 0x80:
            break
        shift += 7
    bh = pos + 32 * n
    pos = bh + 32
    pos += len(shortvec(len(ixs)))
    data_at = []
    for ix in ixs:
        pos += 1                                           # program index
        pos += len(shortvec(len(ix.accounts))) + len(ix.accounts)
        pos += len(shortvec(len(ix.data)))
        data_at.append(pos)
        pos += len(ix.data)
    if pos != len(msg):                                    # pragma: no cover (a layout change here)
        raise ValueError("template offsets do not add up")
    return Compiled(msg, bh, data_at)


def signers_of(message: bytes) -> int:
    return message[0]


def transaction(message: bytes, signatures: list[bytes]) -> bytes:
    if len(signatures) != signers_of(message) or any(len(s) != 64 for s in signatures):
        raise ValueError("one 64-byte signature per signer")
    return shortvec(len(signatures)) + b"".join(signatures) + message


def compute_limit(units: int) -> Ix:
    return Ix(COMPUTE_BUDGET, [], bytes([2]) + struct.pack("<I", units))


def compute_price(micro_lamports: int) -> Ix:
    return Ix(COMPUTE_BUDGET, [], bytes([3]) + struct.pack("<Q", micro_lamports))


def create_ata(payer: str, owner: str, mint: str, token_program: str = TOKEN) -> Ix:
    """CreateIdempotent: a no-op when the account exists."""
    return Ix(ATA_PROGRAM, [(payer, True, True), (ata(owner, mint, token_program), False, True), (owner, False, False),
                            (mint, False, False), (SYSTEM, False, False), (token_program, False, False)], bytes([1]))


def close_own(account: str, user: str, token_program: str = TOKEN) -> Ix:
    """Close one of the wallet's own token accounts; the rent goes back to the wallet itself."""
    return Ix(token_program, [(account, False, True), (user, False, True), (user, True, False)], bytes([9]))


def wrap_sol(user: str, lamports: int) -> Ix:
    """Move SOL into the wallet's OWN wrapped-SOL account (the pool trades in wrapped SOL). There is
    no other transfer here: the destination is derived from the wallet, never given."""
    return Ix(SYSTEM, [(user, True, True), (ata(user, WSOL, TOKEN), False, True)], struct.pack("<IQ", 2, lamports))


def sync_native(account: str) -> Ix:
    return Ix(TOKEN, [(account, False, True)], bytes([17]))


ALLOWED_PROGRAMS = {COMPUTE_BUDGET, ATA_PROGRAM, TOKEN, TOKEN_2022, SYSTEM, PUMP, PUMP_AMM}

# Jito's published tip accounts (its block engine's getTipAccounts). A tip is a plain SOL payment from the
# wallet to one of them inside our OWN transaction; only the owner's PYTHIA_PUMPFUN_JITO=1 lets one through
# (live_exec), never more than MAX_TIP_LAMPORTS, never more than one, never in a bundle with anyone else's.
JITO_TIP_ACCOUNTS = frozenset({
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5", "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY", "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh", "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL", "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT"})
MAX_TIP_LAMPORTS = 10_000_000             # 0.01 SOL: a hard cap in code, whatever a setting says


def tip(user: str, account: str, lamports: int) -> Ix:
    """Our own transaction's tip to a Jito tip account (a system transfer). check_own refuses it unless the
    caller says tips are allowed (the owner's flag), the account is a published tip account and the amount
    is at most MAX_TIP_LAMPORTS."""
    return Ix(SYSTEM, [(user, True, True), (account, False, True)], struct.pack("<IQ", 2, int(lamports)))


def is_tip(user: str, ix: Ix) -> bool:
    return (ix.program == SYSTEM and len(ix.accounts) == 2 and ix.accounts[0][0] == user
            and ix.accounts[1][0] in JITO_TIP_ACCOUNTS and len(ix.data) == 12 and ix.data[:4] == struct.pack("<I", 2))


def check_own(user: str, ixs: list[Ix], tip_ok: bool = False) -> None:
    """Refuse anything but a buy or a sale for the wallet itself: only the programs a trade needs,
    a system instruction only as the wrap into the wallet's own wrapped-SOL account (or, with tip_ok,
    one tip of at most MAX_TIP_LAMPORTS to a published Jito tip account), and a token account closed
    only back to the wallet. Raises ValueError otherwise (nothing is signed)."""
    tips = 0
    for ix in ixs:
        if ix.program not in ALLOWED_PROGRAMS:
            raise ValueError(f"program {ix.program[:8]} is not part of a plain buy or sale")
        if ix.program == SYSTEM and is_tip(user, ix):
            if not tip_ok:
                raise ValueError("a tip, and tips are not switched on (PYTHIA_PUMPFUN_JITO)")
            if struct.unpack_from("<Q", ix.data, 4)[0] > MAX_TIP_LAMPORTS:
                raise ValueError("a tip above the hard cap")
            tips += 1
            if tips > 1:
                raise ValueError("more than one tip")
            continue
        if ix.program == SYSTEM:
            ok = (len(ix.accounts) == 2 and ix.accounts[0][0] == user and ix.accounts[1][0] == ata(user, WSOL, TOKEN)
                  and ix.data[:4] == struct.pack("<I", 2))
            if not ok:
                raise ValueError("a system instruction that is not the wrap into the wallet's own account")
        if ix.program in (TOKEN, TOKEN_2022) and ix.data[:1] == bytes([9]):
            if ix.accounts[1][0] != user or ix.accounts[2][0] != user:
                raise ValueError("a token account closed to someone else")
        if ix.program in (TOKEN, TOKEN_2022) and ix.data[:1] not in (bytes([9]), bytes([17])):
            raise ValueError("a token instruction other than close or sync")
        if ix.program == ATA_PROGRAM and ix.data != bytes([1]):
            raise ValueError("an associated-account instruction other than create")
        if ix.program in (PUMP, PUMP_AMM) and ix.data[:8] not in (discriminator("buy"), discriminator("sell")):
            raise ValueError("a program instruction other than buy or sell")


# ---------------------------------------------------------------- the IDL

class Idl:
    """The owner's copy of a program's IDL: instruction accounts, flags, args, discriminators,
    account field offsets. Anchor's new (0.30+) and old shapes."""

    def __init__(self, doc: dict):
        self.doc = doc or {}
        self.ix = {i.get("name"): i for i in self.doc.get("instructions") or []}
        self.types = {t.get("name"): t for t in (self.doc.get("types") or [])}
        for a in self.doc.get("accounts") or []:          # the old shape has the struct inline
            if "type" in a:
                self.types.setdefault(a.get("name"), a)

    def accounts(self, ix: str) -> list[dict]:
        return list((self.ix.get(ix) or {}).get("accounts") or [])

    def args(self, ix: str) -> list[str]:
        return [a.get("name") for a in (self.ix.get(ix) or {}).get("args") or []]

    def flags(self, ix: str) -> dict[str, tuple[bool, bool]]:
        out = {}
        for a in self.accounts(ix):
            n = _snake(a.get("name", ""))
            out[n] = (bool(a.get("signer", a.get("isSigner", False))), bool(a.get("writable", a.get("isMut", False))))
        return out

    def disc(self, ix: str) -> bytes:
        d = (self.ix.get(ix) or {}).get("discriminator")
        return bytes(d) if isinstance(d, list) and len(d) == 8 else discriminator(ix)

    def offset(self, type_name: str, field: str) -> int | None:
        """Where a field starts in the account's data (after the discriminator), when every field
        before it has a fixed size."""
        t = self.types.get(type_name)
        fields = ((t or {}).get("type") or {}).get("fields")
        if not fields:
            return None
        pos = 8
        for f in fields:
            if f.get("name") == field or _snake(f.get("name", "")) == field:
                return pos
            n = _size(f.get("type"))
            if n is None:
                return None
            pos += n
        return None


def _snake(name: str) -> str:
    out = []
    for ch in name:
        if ch.isupper() and out:
            out.append("_")
        out.append(ch.lower())
    return "".join(out)


_SIZES = {"bool": 1, "u8": 1, "i8": 1, "u16": 2, "i16": 2, "u32": 4, "i32": 4, "u64": 8, "i64": 8, "u128": 16,
          "i128": 16, "pubkey": 32, "publicKey": 32}


def _size(t) -> int | None:
    if isinstance(t, str):
        return _SIZES.get(t)
    if isinstance(t, dict) and "array" in t:
        inner, n = t["array"]
        s = _size(inner)
        return s * int(n) if s is not None else None
    return None


def check_idl(pump: dict | None, amm: dict | None) -> list[str]:
    """Every difference between the IDLs and what this module builds; empty when they agree."""
    out = []
    for prog, doc in (("pump", pump), ("amm", amm)):
        if not doc:
            out.append(f"no {prog} IDL")
            continue
        idl = Idl(doc)
        for side in ("buy", "sell"):
            names = [_snake(a.get("name", "")) for a in idl.accounts(side)]
            if names != ACCOUNTS[(prog, side)]:
                out.append(f"{prog} {side}: the IDL's accounts differ from the builder's ({len(names)} vs "
                           f"{len(ACCOUNTS[(prog, side)])})")
            args = [_snake(a) for a in idl.args(side)]
            if args != ARGS[(prog, side)]:
                out.append(f"{prog} {side}: the IDL's arguments are {args}, the builder's {ARGS[(prog, side)]}")
    return out


def _flags(idl: Idl | None, ix: str, name: str) -> tuple[bool, bool]:
    if idl is not None:
        f = idl.flags(ix).get(name)
        if f is not None:
            return f
    return name in SIGNERS, name in WRITABLE


def _offset(idl: Idl | None, type_name: str, field: str) -> int:
    if idl is not None:
        o = idl.offset(type_name, field)
        if o is None:
            raise ValueError(f"the IDL has no fixed offset for {type_name}.{field}")
        return o
    return OFFSETS[(type_name, field)]


# ---------------------------------------------------------------- reading the programs' accounts

def read_key(data: bytes, off: int) -> str:
    if len(data) < off + 32:
        raise ValueError("account data too short")
    return b58(data[off:off + 32])


@dataclass
class CurveInfo:
    mint: str
    token_program: str
    fee_recipient: str
    creator: str


@dataclass
class PoolInfo:
    pool: str
    base_mint: str
    quote_mint: str
    pool_base: str
    pool_quote: str
    coin_creator: str
    base_token_program: str
    protocol_fee_recipient: str


def curve_info(mint: str, mint_owner: str, global_data: bytes, curve_data: bytes, idl: Idl | None = None) -> CurveInfo:
    return CurveInfo(mint, mint_owner, read_key(global_data, _offset(idl, "Global", "fee_recipient")),
                     read_key(curve_data, _offset(idl, "BondingCurve", "creator")))


def pool_info(pool: str, pool_data: bytes, config_data: bytes, base_owner: str, idl: Idl | None = None) -> PoolInfo:
    return PoolInfo(pool, read_key(pool_data, _offset(idl, "Pool", "base_mint")),
                    read_key(pool_data, _offset(idl, "Pool", "quote_mint")),
                    read_key(pool_data, _offset(idl, "Pool", "pool_base_token_account")),
                    read_key(pool_data, _offset(idl, "Pool", "pool_quote_token_account")),
                    read_key(pool_data, _offset(idl, "Pool", "coin_creator")), base_owner,
                    read_key(config_data, _offset(idl, "GlobalConfig", "protocol_fee_recipients")))


# ---------------------------------------------------------------- the trades

def _pump_accounts(side: str, user: str, c: CurveInfo, idl: Idl | None) -> list[tuple[str, bool, bool]]:
    bc = pda([b"bonding-curve", key(c.mint)], PUMP)
    vals = {"global": pda([b"global"], PUMP), "fee_recipient": c.fee_recipient, "mint": c.mint, "bonding_curve": bc,
            "associated_bonding_curve": ata(bc, c.mint, c.token_program),
            "associated_user": ata(user, c.mint, c.token_program), "user": user, "system_program": SYSTEM,
            "token_program": c.token_program, "creator_vault": pda([b"creator-vault", key(c.creator)], PUMP),
            "event_authority": pda([b"__event_authority"], PUMP), "program": PUMP,
            "global_volume_accumulator": pda([b"global_volume_accumulator"], PUMP),
            "user_volume_accumulator": pda([b"user_volume_accumulator", key(user)], PUMP),
            "fee_config": pda([b"fee_config", key(PUMP)], FEE_PROGRAM), "fee_program": FEE_PROGRAM}
    return [(vals[n], *_flags(idl, side, n)) for n in ACCOUNTS[("pump", side)]]


def _amm_accounts(side: str, user: str, p: PoolInfo, idl: Idl | None) -> list[tuple[str, bool, bool]]:
    auth = pda([b"creator_vault", key(p.coin_creator)], PUMP_AMM)
    vals = {"pool": p.pool, "user": user, "global_config": pda([b"global_config"], PUMP_AMM),
            "base_mint": p.base_mint, "quote_mint": p.quote_mint,
            "user_base_token_account": ata(user, p.base_mint, p.base_token_program),
            "user_quote_token_account": ata(user, p.quote_mint, TOKEN), "pool_base_token_account": p.pool_base,
            "pool_quote_token_account": p.pool_quote, "protocol_fee_recipient": p.protocol_fee_recipient,
            "protocol_fee_recipient_token_account": ata(p.protocol_fee_recipient, p.quote_mint, TOKEN),
            "base_token_program": p.base_token_program, "quote_token_program": TOKEN, "system_program": SYSTEM,
            "associated_token_program": ATA_PROGRAM, "event_authority": pda([b"__event_authority"], PUMP_AMM),
            "program": PUMP_AMM, "coin_creator_vault_ata": ata(auth, p.quote_mint, TOKEN),
            "coin_creator_vault_authority": auth,
            "global_volume_accumulator": pda([b"global_volume_accumulator"], PUMP_AMM),
            "user_volume_accumulator": pda([b"user_volume_accumulator", key(user)], PUMP_AMM),
            "fee_config": pda([b"fee_config", key(PUMP_AMM)], FEE_PROGRAM), "fee_program": FEE_PROGRAM}
    return [(vals[n], *_flags(idl, side, n)) for n in ACCOUNTS[("amm", side)]]


def budget(units: int, priority_lamports: int) -> list[Ix]:
    """A compute-unit limit and the price that makes the priority fee `priority_lamports` in all."""
    micro = max(0, priority_lamports * 1_000_000 // max(1, units))
    return [compute_limit(units), compute_price(micro)]


UNITS = 200_000


def pump_buy(user: str, c: CurveInfo, tokens: int, max_cost_l: int, priority_l: int, idl: Idl | None = None) -> list[Ix]:
    data = (idl.disc("buy") if idl else discriminator("buy")) + struct.pack("<QQ", tokens, max_cost_l) + b"\x00"
    return budget(UNITS, priority_l) + [create_ata(user, user, c.mint, c.token_program),
                                        Ix(PUMP, _pump_accounts("buy", user, c, idl), data)]


def pump_sell(user: str, c: CurveInfo, tokens: int, min_out_l: int, priority_l: int, close: bool,
              idl: Idl | None = None) -> list[Ix]:
    data = (idl.disc("sell") if idl else discriminator("sell")) + struct.pack("<QQ", tokens, min_out_l)
    ixs = budget(UNITS, priority_l) + [Ix(PUMP, _pump_accounts("sell", user, c, idl), data)]
    if close:                                              # the rent of the token account comes back
        ixs.append(close_own(ata(user, c.mint, c.token_program), user, c.token_program))
    return ixs


def amm_buy(user: str, p: PoolInfo, tokens: int, max_quote_l: int, priority_l: int, idl: Idl | None = None) -> list[Ix]:
    wsol = ata(user, WSOL, TOKEN)
    data = (idl.disc("buy") if idl else discriminator("buy")) + struct.pack("<QQ", tokens, max_quote_l) + b"\x00"
    return budget(UNITS + 100_000, priority_l) + [
        create_ata(user, user, WSOL, TOKEN), wrap_sol(user, max_quote_l), sync_native(wsol),
        create_ata(user, user, p.base_mint, p.base_token_program),
        Ix(PUMP_AMM, _amm_accounts("buy", user, p, idl), data), close_own(wsol, user, TOKEN)]


def amm_sell(user: str, p: PoolInfo, tokens: int, min_out_l: int, priority_l: int, close: bool,
             idl: Idl | None = None) -> list[Ix]:
    wsol = ata(user, WSOL, TOKEN)
    data = (idl.disc("sell") if idl else discriminator("sell")) + struct.pack("<QQ", tokens, min_out_l)
    ixs = budget(UNITS + 100_000, priority_l) + [create_ata(user, user, WSOL, TOKEN),
                                                 Ix(PUMP_AMM, _amm_accounts("sell", user, p, idl), data),
                                                 close_own(wsol, user, TOKEN)]
    if close:
        ixs.append(close_own(ata(user, p.base_mint, p.base_token_program), user, p.base_token_program))
    return ixs


def round_trip(buy: list[Ix], sell: list[Ix], units: int = 3 * UNITS) -> list[Ix]:
    """A buy followed by the sale of what it bought, in one message, for the dry run only
    (live_exec simulate): the program checks both against the real accounts and nothing is sent.
    Each side's compute budget is dropped for one budget over both (a duplicate is an error)."""
    body = [ix for ix in buy + sell if ix.program != COMPUTE_BUDGET]
    return [compute_limit(units)] + body
