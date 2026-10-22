"""Plain pump.fun and PumpSwap buy and sell transactions, built byte by byte.

Pure functions: no key, no signing, no network. live_exec.py (LOCKED) signs and
sends what this builds; the tests check it with a fake signer.

Only the programs' own public buy and sell instructions, with a compute-unit
limit and price, the associated token accounts they need, and (in the pool)
wrapping and unwrapping SOL. The trades are the documented fixed-account ones:
buy_v3 and sell_v3 on the bonding curve, buy_exact_quote_in_v2 and sell_v2 on
PumpSwap (17 accounts each, no remaining accounts); the legacy curve trades and
the PumpSwap v1 trades are never built, and a cashback coin, which takes
neither, is refused. No bundles, no private relays, nothing that
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

from .curve import effective_quote
from .events import PUMP, PUMP_AMM, WSOL, b58, b58decode

SYSTEM = "11111111111111111111111111111111"
TOKEN = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022 = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"
ATA_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
COMPUTE_BUDGET = "ComputeBudget111111111111111111111111111111"
FEE_PROGRAM = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"

# The bonding curve's v3 trades (docs/instructions/TRADE_V3.md): the same 17 accounts for buy_v3,
# buy_exact_quote_in_v3 and sell_v3, no remaining accounts. The legacy buy and sell now need undocumented
# remaining accounts (BuybackFeeRecipientMissing, 6062, in a mainnet simulation) and are never built.
PUMP_V3 = ["global", "base_mint", "quote_mint", "base_token_program", "quote_token_program", "bonding_curve",
           "associated_base_bonding_curve", "associated_quote_bonding_curve", "user", "associated_base_user",
           "associated_quote_user", "user_volume_accumulator", "fee_config", "buyback_fee_recipient",
           "system_program", "event_authority", "program"]
PUMP_BUY_IX = "buy_v3"                       # exactly `amount` tokens for at most max_sol_cost, as the paper model
PUMP_SELL_IX = "sell_v3"
# PumpSwap's v2 trades (docs/instructions/PUMP_SWAP_TRADE_V2.md): the same 17 accounts for buy_v2,
# buy_exact_quote_in_v2 and sell_v2, no remaining accounts. The v1 buy and sell are never built.
AMM_V2 = ["pool", "user", "global_config", "base_mint", "quote_mint", "user_base_token_account",
          "user_quote_token_account", "pool_base_token_account", "pool_quote_token_account", "base_token_program",
          "quote_token_program", "system_program", "user_volume_accumulator", "fee_config", "buyback_fee_recipient",
          "event_authority", "program"]
AMM_BUY_IX = "buy_exact_quote_in_v2"         # spends exactly the stake, at least min_base_amount_out back
AMM_SELL_IX = "sell_v2"
ARGS = {("pump", PUMP_BUY_IX): ["amount", "max_sol_cost", "partial_fill"],
        ("pump", PUMP_SELL_IX): ["amount", "min_sol_output"],
        ("amm", AMM_BUY_IX): ["spendable_quote_in", "min_base_amount_out"],
        ("amm", AMM_SELL_IX): ["base_amount_in", "min_quote_amount_out"]}
ACCOUNTS = {("pump", PUMP_BUY_IX): PUMP_V3, ("pump", PUMP_SELL_IX): PUMP_V3, ("amm", AMM_BUY_IX): AMM_V2,
            ("amm", AMM_SELL_IX): AMM_V2}
# Writable accounts when no IDL is given (tests); the IDL's flags win otherwise.
WRITABLE = {"bonding_curve", "associated_base_bonding_curve", "associated_quote_bonding_curve", "user",
            "associated_base_user", "associated_quote_user", "user_volume_accumulator", "pool",
            "user_base_token_account", "user_quote_token_account", "pool_base_token_account",
            "pool_quote_token_account", "buyback_fee_recipient"}
SIGNERS = {"user"}
# Field offsets in the programs' accounts (after the 8-byte discriminator), used only without an IDL.
OFFSETS = {("Global", "buyback_fee_recipients"): 741, ("BondingCurve", "is_mayhem_mode"): 81,
           ("BondingCurve", "is_cashback_coin"): 82, ("BondingCurve", "quote_mint"): 83,
           ("GlobalConfig", "buyback_fee_recipients"): 643, ("Pool", "base_mint"): 43, ("Pool", "quote_mint"): 75,
           ("Pool", "pool_base_token_account"): 139, ("Pool", "pool_quote_token_account"): 171,
           ("Pool", "is_mayhem_mode"): 243, ("Pool", "is_cashback_coin"): 244, ("Pool", "virtual_quote_reserves"): 245}
# The fields the builder reads; the gate needs each at a fixed offset in the owner's IDL.
READS = {"pump": [("Global", "buyback_fee_recipients"), ("BondingCurve", "is_mayhem_mode"),
                  ("BondingCurve", "is_cashback_coin"), ("BondingCurve", "quote_mint")],
         "amm": [("GlobalConfig", "buyback_fee_recipients"), ("Pool", "base_mint"), ("Pool", "quote_mint"),
                 ("Pool", "pool_base_token_account"), ("Pool", "pool_quote_token_account"), ("Pool", "is_mayhem_mode"),
                 ("Pool", "is_cashback_coin"), ("Pool", "virtual_quote_reserves")]}
# The 8 buyback fee recipient wallets (docs/FEE_RECIPIENTS.md). A curve v3 trade of a SOL coin pays the
# buyback part of the protocol fee to one of them, a pool v2 trade to the wrapped-SOL account of one of
# them; check_own refuses any other account there.
BUYBACK_FEE_RECIPIENTS = (
    "5YxQFdt3Tr9zJLvkFccqXVUwhdTWJQc1fFg2YPbxvxeD", "9M4giFFMxmFGXtc3feFzRai56WbBqehoSeRE5GK7gf7",
    "GXPFM2caqTtQYC2cJ5yJRi9VDkpsYZXzYdwYpGnLmtDL", "3BpXnfJaUTiwXnJNe7Ej1rcbzqTTQUvLShZaWazebsVR",
    "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6", "EHAAiTxcdDwQ3U4bU6YcMsQGaekdzLS3B5SmYo46kJtL",
    "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD", "A7hAgCzFw14fejgCp387JUJRMNyz4j89JKnhtKU8piqW")


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

# Helius Sender's tip accounts (docs: sending-transactions/sender-swqos-only, 2026-10-22). With the owner's
# PYTHIA_PUMPFUN_SENDER our own single transaction carries one tip to one of them and goes out through Sender's
# stake-weighted path (swqos_only): a faster delivery to the validators, no bundle, nobody else's transaction.
HELIUS_TIP_ACCOUNTS = frozenset({
    "4ACfpUFoaSD9bfPdeu6DBt89gB6ENTeHBXCAi87NhDEE", "D2L6yPZ2FmmmTKPgzaMKdhu6EWZcTpLy1Vhx8uvZe7NZ",
    "9bnz4RShgq1hAnLnZbP8kbgBg1kEmcJBYQq3gQbmnSta", "5VY91ws6B2hMmBFRsXkoAAdsPHBJwRfBht4DXox3xkwn",
    "2nyhqdwKcJZR2vcqCyrYsaPVdAnFoJjiksCXJ7hfEYgD", "2q5pghRs6arqVjRvT5gfgWfWcHWmw1ZuCzphgd5KfWGJ",
    "wyvPkWjVZz1M8fHQnMMCDTQDbkManefNNhweYk5WkcF", "3KCKozbAaF75qEU33jtzozcJ29yJuaLJTy2jFdzUY8bT",
    "4vieeGHPYPG2MmyPRcYjdiDmmhN3ww7hsFNap8pVN3Ey", "4TQLFNWK8AovT1gFvda5jfw2oJeRMKEmw7aH6MGBJ3or"})
HELIUS_MIN_TIP_LAMPORTS = 5_000           # 0.000005 SOL, Sender's swqos_only minimum
HELIUS_MAX_TIP_LAMPORTS = 100_000         # 0.0001 SOL: a hard cap in code, whatever a setting says


def tip(user: str, account: str, lamports: int) -> Ix:
    """Our own transaction's tip to a Jito tip account (a system transfer). check_own refuses it unless the
    caller says tips are allowed (the owner's flag), the account is a published tip account and the amount
    is at most MAX_TIP_LAMPORTS."""
    return Ix(SYSTEM, [(user, True, True), (account, False, True)], struct.pack("<IQ", 2, int(lamports)))


def is_tip(user: str, ix: Ix) -> bool:
    return (ix.program == SYSTEM and len(ix.accounts) == 2 and ix.accounts[0][0] == user
            and ix.accounts[1][0] in JITO_TIP_ACCOUNTS | HELIUS_TIP_ACCOUNTS and len(ix.data) == 12
            and ix.data[:4] == struct.pack("<I", 2))


def _check_trade(user: str, ix: Ix) -> None:
    """A program trade must be the wallet's own: the wallet is the trader, the tokens come from and go
    to its own associated accounts, and a buyback fee only to a listed recipient's account."""
    accts = [a[0] for a in ix.accounts]
    if ix.program == PUMP:
        if len(accts) != len(PUMP_V3):
            raise ValueError("a curve trade with an unexpected number of accounts")
        a = dict(zip(PUMP_V3, accts))
        if a["user"] != user or a["program"] != PUMP:
            raise ValueError("a curve trade that is not the wallet's own")
        if a["associated_base_user"] != ata(user, a["base_mint"], a["base_token_program"]) or \
                a["associated_quote_user"] != ata(user, a["quote_mint"], a["quote_token_program"]):
            raise ValueError("a curve trade into token accounts that are not the wallet's own")
        if a["quote_mint"] != WSOL or a["buyback_fee_recipient"] not in BUYBACK_FEE_RECIPIENTS:
            raise ValueError("a curve trade whose buyback fee account is not a listed recipient")
        return
    if len(accts) != len(AMM_V2):
        raise ValueError("a pool trade with an unexpected number of accounts")
    a = dict(zip(AMM_V2, accts))
    if a["user"] != user or a["program"] != PUMP_AMM:
        raise ValueError("a pool trade that is not the wallet's own")
    if a["user_base_token_account"] != ata(user, a["base_mint"], a["base_token_program"]) or \
            a["user_quote_token_account"] != ata(user, a["quote_mint"], a["quote_token_program"]):
        raise ValueError("a pool trade into token accounts that are not the wallet's own")
    if a["buyback_fee_recipient"] not in {ata(r, a["quote_mint"], a["quote_token_program"])
                                          for r in BUYBACK_FEE_RECIPIENTS}:
        raise ValueError("a pool trade whose buyback fee account is not a listed recipient's")


TRADES = {PUMP: (PUMP_BUY_IX, PUMP_SELL_IX), PUMP_AMM: (AMM_BUY_IX, AMM_SELL_IX)}


def check_own(user: str, ixs: list[Ix], tip_ok: bool = False, sender_tip_ok: bool = False) -> None:
    """Refuse anything but a buy or a sale for the wallet itself: only the programs a trade needs,
    a system instruction only as the wrap into the wallet's own wrapped-SOL account (or, with tip_ok,
    one tip of at most MAX_TIP_LAMPORTS to a published Jito tip account; with sender_tip_ok, one tip of at
    most HELIUS_MAX_TIP_LAMPORTS to a Helius Sender tip account), an associated account only
    created for the wallet itself, a token account closed only back to the wallet, and the programs'
    own trade instructions only with the wallet as the trader and its own token accounts (a pool trade
    only as v2, its buyback fee only to a listed recipient). Raises ValueError otherwise (nothing is
    signed)."""
    tips = 0
    for ix in ixs:
        if ix.program not in ALLOWED_PROGRAMS:
            raise ValueError(f"program {ix.program[:8]} is not part of a plain buy or sale")
        if ix.program == SYSTEM and is_tip(user, ix):
            amount = struct.unpack_from("<Q", ix.data, 4)[0]
            if ix.accounts[1][0] in HELIUS_TIP_ACCOUNTS:
                if not sender_tip_ok:
                    raise ValueError("a Sender tip, and Sender is not switched on (PYTHIA_PUMPFUN_SENDER)")
                if amount > HELIUS_MAX_TIP_LAMPORTS:
                    raise ValueError("a Sender tip above the hard cap")
            else:
                if not tip_ok:
                    raise ValueError("a tip, and tips are not switched on (PYTHIA_PUMPFUN_JITO)")
                if amount > MAX_TIP_LAMPORTS:
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
        if ix.program == ATA_PROGRAM:
            if ix.data != bytes([1]):
                raise ValueError("an associated-account instruction other than create")
            if len(ix.accounts) != 6 or ix.accounts[0][0] != user or ix.accounts[2][0] != user:
                raise ValueError("an associated account created for someone else")
        if ix.program in TRADES:
            if ix.data[:8] not in {discriminator(n) for n in TRADES[ix.program]}:
                raise ValueError("a program instruction other than buy or sell"
                                 + (" (a pool trade must be v2)" if ix.program == PUMP_AMM else
                                    " (a curve trade must be v3)"))
            _check_trade(user, ix)


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
        for (p, ix), want in ACCOUNTS.items():
            if p != prog:
                continue
            if ix not in idl.ix:
                out.append(f"{prog} {ix}: not in the IDL")
                continue
            names = [_snake(a.get("name", "")) for a in idl.accounts(ix)]
            if names != want:
                out.append(f"{prog} {ix}: the IDL's accounts differ from the builder's ({len(names)} vs {len(want)})")
            args = [_snake(a) for a in idl.args(ix)]
            if args != ARGS[(p, ix)]:
                out.append(f"{prog} {ix}: the IDL's arguments are {args}, the builder's {ARGS[(p, ix)]}")
            if idl.disc(ix) != discriminator(ix):
                out.append(f"{prog} {ix}: the IDL's discriminator is not the one check_own expects")
        for type_name, fld in READS[prog]:
            if idl.offset(type_name, fld) is None:
                out.append(f"{prog}: the IDL has no fixed offset for {type_name}.{fld}")
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
    token_program: str                      # SPL Token, or Token-2022 for create_v2 coins
    buyback_recipient: str                  # one of BUYBACK_FEE_RECIPIENTS (a SOL coin's v3 trade pays the wallet)
    quote_mint: str = WSOL                  # wrapped SOL for a SOL coin (the curve holds the default key then)
    cashback: bool = False                  # a cashback coin: v3 trades fail there (6094)
    mayhem: bool = False

    def supports_v3(self) -> bool:
        return not self.cashback


@dataclass
class PoolInfo:
    pool: str
    base_mint: str
    quote_mint: str
    pool_base: str
    pool_quote: str
    base_token_program: str
    buyback_recipient: str                  # one of BUYBACK_FEE_RECIPIENTS (the wallet, not its token account)
    virtual_quote: int = 0                  # Pool::virtual_quote_reserves, signed, may be negative
    cashback: bool = False                  # a cashback coin's pool: v2 trades fail there (6079)
    mayhem: bool = False

    def supports_v2(self) -> bool:
        """What the TypeScript SDK's supportsTradeV2(pool) checks: every pool but a cashback coin's."""
        return not self.cashback

    def effective_quote(self, vault: int) -> int:
        """The quote reserves every price uses: the vault's balance plus virtual_quote_reserves."""
        return effective_quote(vault, self.virtual_quote)


def _field(data: bytes, off: int, size: int) -> bytes | None:
    """A field of an account written before the field was appended is missing: None (read as 0 / false)."""
    return data[off:off + size] if len(data) >= off + size else None


def buyback_recipients(data: bytes, type_name: str = "GlobalConfig", idl: Idl | None = None) -> list[str]:
    """The buyback fee recipients a program's global account lists (pump.fun's Global, PumpSwap's
    GlobalConfig) that are also the documented ones."""
    off = _offset(idl, type_name, "buyback_fee_recipients")
    listed = [read_key(data, off + 32 * i) for i in range(8)]
    return [r for r in listed if r in BUYBACK_FEE_RECIPIENTS]


def curve_info(mint: str, mint_owner: str, global_data: bytes, curve_data: bytes, idl: Idl | None = None,
               pick=None) -> CurveInfo:
    """The curve's token program, quote mint and flags, and one buyback fee recipient (`pick` chooses among
    the listed ones; the first without it)."""
    rec = buyback_recipients(global_data, "Global", idl)
    if not rec:
        raise ValueError("pump.fun's Global lists none of the documented buyback fee recipients")
    q = _field(curve_data, _offset(idl, "BondingCurve", "quote_mint"), 32)
    quote = b58(q) if q else SYSTEM
    cb = _field(curve_data, _offset(idl, "BondingCurve", "is_cashback_coin"), 1)
    mm = _field(curve_data, _offset(idl, "BondingCurve", "is_mayhem_mode"), 1)
    return CurveInfo(mint, mint_owner, (pick or (lambda xs: xs[0]))(rec), WSOL if quote in (SYSTEM, WSOL) else quote,
                     bool(cb and cb[0]), bool(mm and mm[0]))


def pool_info(pool: str, pool_data: bytes, config_data: bytes, base_owner: str, idl: Idl | None = None,
              pick=None) -> PoolInfo:
    """The pool's accounts and flags, and one buyback fee recipient (`pick` chooses among the listed
    ones; the first without it)."""
    rec = buyback_recipients(config_data, "GlobalConfig", idl)
    if not rec:
        raise ValueError("the GlobalConfig lists none of the documented buyback fee recipients")
    vq = _field(pool_data, _offset(idl, "Pool", "virtual_quote_reserves"), 16)
    cb = _field(pool_data, _offset(idl, "Pool", "is_cashback_coin"), 1)
    mm = _field(pool_data, _offset(idl, "Pool", "is_mayhem_mode"), 1)
    return PoolInfo(pool, read_key(pool_data, _offset(idl, "Pool", "base_mint")),
                    read_key(pool_data, _offset(idl, "Pool", "quote_mint")),
                    read_key(pool_data, _offset(idl, "Pool", "pool_base_token_account")),
                    read_key(pool_data, _offset(idl, "Pool", "pool_quote_token_account")), base_owner,
                    (pick or (lambda xs: xs[0]))(rec),
                    int.from_bytes(vq, "little", signed=True) if vq else 0, bool(cb and cb[0]), bool(mm and mm[0]))


# ---------------------------------------------------------------- the trades

def _pump_accounts(ix: str, user: str, c: CurveInfo, idl: Idl | None) -> list[tuple[str, bool, bool]]:
    """The 17 accounts of a bonding curve v3 trade of a SOL coin, in the documented order: the quote
    accounts are the derived wrapped-SOL addresses (not used, need not exist; SOL moves as lamports) and
    the buyback fee recipient is the listed wallet itself."""
    bc = pda([b"bonding-curve", key(c.mint)], PUMP)
    vals = {"global": pda([b"global"], PUMP), "base_mint": c.mint, "quote_mint": WSOL,
            "base_token_program": c.token_program, "quote_token_program": TOKEN, "bonding_curve": bc,
            "associated_base_bonding_curve": ata(bc, c.mint, c.token_program),
            "associated_quote_bonding_curve": ata(bc, WSOL, TOKEN), "user": user,
            "associated_base_user": ata(user, c.mint, c.token_program), "associated_quote_user": ata(user, WSOL, TOKEN),
            "user_volume_accumulator": pda([b"user_volume_accumulator", key(user)], PUMP),
            "fee_config": pda([b"fee_config", key(PUMP)], FEE_PROGRAM), "buyback_fee_recipient": c.buyback_recipient,
            "system_program": SYSTEM, "event_authority": pda([b"__event_authority"], PUMP), "program": PUMP}
    return [(vals[n], *_flags(idl, ix, n)) for n in ACCOUNTS[("pump", ix)]]


def _amm_accounts(ix: str, user: str, p: PoolInfo, idl: Idl | None) -> list[tuple[str, bool, bool]]:
    """The 17 accounts of a PumpSwap v2 trade, in the documented order."""
    vals = {"pool": p.pool, "user": user, "global_config": pda([b"global_config"], PUMP_AMM),
            "base_mint": p.base_mint, "quote_mint": p.quote_mint,
            "user_base_token_account": ata(user, p.base_mint, p.base_token_program),
            "user_quote_token_account": ata(user, p.quote_mint, TOKEN), "pool_base_token_account": p.pool_base,
            "pool_quote_token_account": p.pool_quote, "base_token_program": p.base_token_program,
            "quote_token_program": TOKEN, "system_program": SYSTEM,
            "user_volume_accumulator": pda([b"user_volume_accumulator", key(user)], PUMP_AMM),
            "fee_config": pda([b"fee_config", key(PUMP_AMM)], FEE_PROGRAM),
            "buyback_fee_recipient": ata(p.buyback_recipient, p.quote_mint, TOKEN),
            "event_authority": pda([b"__event_authority"], PUMP_AMM), "program": PUMP_AMM}
    return [(vals[n], *_flags(idl, ix, n)) for n in ACCOUNTS[("amm", ix)]]


def budget(units: int, priority_lamports: int) -> list[Ix]:
    """A compute-unit limit and the price that makes the priority fee `priority_lamports` in all."""
    micro = max(0, priority_lamports * 1_000_000 // max(1, units))
    return [compute_limit(units), compute_price(micro)]


UNITS = 200_000


def _v3_curve(c: CurveInfo) -> None:
    if not c.supports_v3():
        raise ValueError("the curve is a cashback coin's and takes no v3 trade; a legacy trade is never sent")
    if c.quote_mint != WSOL:
        raise ValueError("only curves quoted in SOL are traded")
    if c.buyback_recipient not in BUYBACK_FEE_RECIPIENTS:
        raise ValueError("the buyback fee recipient is not a documented one")


def pump_buy(user: str, c: CurveInfo, tokens: int, max_cost_l: int, priority_l: int, idl: Idl | None = None) -> list[Ix]:
    """buy_v3 of exactly `tokens` for at most `max_cost_l` lamports (fees included). partial_fill (an
    OptionBool, one byte) is off; it only matters on mayhem coins, which are not traded. The trade
    creates no account, so the wallet's token account is made first (idempotent, the coin's token
    program: Token-2022 for create_v2 coins)."""
    _v3_curve(c)
    data = (idl.disc(PUMP_BUY_IX) if idl else discriminator(PUMP_BUY_IX)) + struct.pack("<QQ", tokens, max_cost_l) \
        + b"\x00"
    return budget(UNITS, priority_l) + [create_ata(user, user, c.mint, c.token_program),
                                        Ix(PUMP, _pump_accounts(PUMP_BUY_IX, user, c, idl), data)]


def pump_sell(user: str, c: CurveInfo, tokens: int, min_out_l: int, priority_l: int, close: bool,
              idl: Idl | None = None) -> list[Ix]:
    """sell_v3 of `tokens` for at least `min_out_l` lamports; with `close` the emptied token account too."""
    _v3_curve(c)
    data = (idl.disc(PUMP_SELL_IX) if idl else discriminator(PUMP_SELL_IX)) + struct.pack("<QQ", tokens, min_out_l)
    ixs = budget(UNITS, priority_l) + [Ix(PUMP, _pump_accounts(PUMP_SELL_IX, user, c, idl), data)]
    if close:                                              # the rent of the token account comes back
        ixs.append(close_own(ata(user, c.mint, c.token_program), user, c.token_program))
    return ixs


def _v2_pool(p: PoolInfo) -> None:
    if not p.supports_v2():
        raise ValueError("the pool is a cashback coin's and takes no v2 trade; a v1 trade is never sent")
    if p.quote_mint != WSOL:
        raise ValueError("only pools quoted in SOL are traded")
    if p.buyback_recipient not in BUYBACK_FEE_RECIPIENTS:
        raise ValueError("the buyback fee recipient is not a documented one")


def amm_buy(user: str, p: PoolInfo, spend_l: int, min_tokens: int, priority_l: int,
            idl: Idl | None = None) -> list[Ix]:
    """buy_exact_quote_in_v2: spend exactly `spend_l` lamports (fees included) for at least `min_tokens`.
    The trade creates no account, so the wallet's token account and its wrapped-SOL account are made
    first (idempotent), the stake wrapped into the latter, and the wrapped-SOL account closed after."""
    _v2_pool(p)
    if spend_l <= 0 or min_tokens <= 0:
        raise ValueError("a pool buy needs a stake and a minimum above zero")
    wsol = ata(user, WSOL, TOKEN)
    data = (idl.disc(AMM_BUY_IX) if idl else discriminator(AMM_BUY_IX)) + struct.pack("<QQ", spend_l, min_tokens)
    return budget(UNITS + 100_000, priority_l) + [
        create_ata(user, user, WSOL, TOKEN), wrap_sol(user, spend_l), sync_native(wsol),
        create_ata(user, user, p.base_mint, p.base_token_program),
        Ix(PUMP_AMM, _amm_accounts(AMM_BUY_IX, user, p, idl), data), close_own(wsol, user, TOKEN)]


def amm_sell(user: str, p: PoolInfo, tokens: int, min_out_l: int, priority_l: int, close: bool,
             idl: Idl | None = None) -> list[Ix]:
    """sell_v2 of `tokens` for at least `min_out_l`, into the wallet's wrapped-SOL account (made first,
    closed after, so the proceeds arrive as SOL); with `close` the emptied token account too."""
    _v2_pool(p)
    if tokens <= 0:
        raise ValueError("a pool sale needs tokens")
    wsol = ata(user, WSOL, TOKEN)
    data = (idl.disc(AMM_SELL_IX) if idl else discriminator(AMM_SELL_IX)) + struct.pack("<QQ", tokens, min_out_l)
    ixs = budget(UNITS + 100_000, priority_l) + [create_ata(user, user, WSOL, TOKEN),
                                                 Ix(PUMP_AMM, _amm_accounts(AMM_SELL_IX, user, p, idl), data),
                                                 close_own(wsol, user, TOKEN)]
    if close:
        ixs.append(close_own(ata(user, p.base_mint, p.base_token_program), user, p.base_token_program))
    return ixs


def round_trip(buy: list[Ix], sell: list[Ix], units: int = 3 * UNITS) -> list[Ix]:
    """A buy followed by the sale of what it bought, in one message, for the dry run only
    (live_exec simulate): the program checks both against the real accounts and nothing is sent.
    Each side's compute budget is dropped for one budget over both (a duplicate is an error): one
    unit limit and the buy's unit price, as a live transaction carries. Each side's tip (Sender) is
    dropped for one tip at the end, as a live transaction carries one."""
    both = buy + sell
    price = next((ix for ix in both if ix.program == COMPUTE_BUDGET and ix.data[:1] == bytes([3])), None)
    tips = [ix for ix in both if ix.program == SYSTEM and len(ix.accounts) == 2 and len(ix.data) == 12
            and ix.data[:4] == struct.pack("<I", 2) and ix.accounts[1][0] in JITO_TIP_ACCOUNTS | HELIUS_TIP_ACCOUNTS]
    skip = {id(ix) for ix in tips}
    body = [ix for ix in both if ix.program != COMPUTE_BUDGET and id(ix) not in skip]
    return [compute_limit(units)] + ([price] if price is not None else []) + body + tips[:1]


def canonical_pool(mint: str) -> str:
    """The PumpSwap pool a completed curve migrates into: index 0, owned by the pump program's pool
    authority for the mint, quoted in wrapped SOL. Builder.pool reads it and refuses it unless its
    base mint is this token, so a wrong address never trades."""
    auth = pda([b"pool-authority", key(mint)], PUMP)
    return pda([b"pool", (0).to_bytes(2, "little"), key(auth), key(mint), key(WSOL)], PUMP_AMM)
