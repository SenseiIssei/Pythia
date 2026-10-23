"""The stage-2 guard: refuses every transaction but the one planned swap inside our own wallet.

Pure functions: no key, no network. Modelled on pumpfun_rt.txbuild.check_own and
docs/ONCHAIN-STAGE2.md, section 1. Three checks, all of which must pass before
anything is signed (live_exec.py runs them in this order):

  check_message   the COMPLETE message as read back from the bytes (tx.decompile):
                  exactly one signer, the wallet, paying; only the programs below;
                  ComputeBudget only a unit limit (<= MAX_UNITS) and price (price x
                  limit <= MAX_PRIORITY_L); the ATA program only creating the wallet's
                  own account of an allowed mint under the classic Token program;
                  Token only closing or syncing the wallet's own wrapped-SOL account,
                  back to the wallet; System only the wrap into that account (when SOL
                  is sold) and at most one Helius Sender tip of at most
                  txbuild.HELIUS_MAX_TIP_LAMPORTS; Jupiter v6 exactly one route_v2 or
                  shared_accounts_route_v2 with the planned amount, our slippage, no
                  platform fee, the wallet as the only authority, source and
                  destination the wallet's own associated accounts, both mints allowed.
                  No transfer out, no approve or delegate, no SetAuthority, no close to
                  anyone else, no other program: there is no instruction here that moves
                  funds out of the wallet.
  check_accounts  every writable account of the message as read from the chain: a token
                  account owned by the wallet must be one of the expected ones and carry
                  no delegate or close authority; no Token-2022 account at all in stage 2.
  check_effect    the simulation's account diff: the input falls by at most the amount,
                  the output rises by at least our minimum, SOL falls by at most fees, tip
                  and rent (plus the amount when SOL is sold), no other account of ours
                  falls, closes or changes owner, delegate or close authority.

The Jupiter instruction's account roles and argument offsets come from the owner's copy
of Jupiter's on-chain IDL (`JupIdl`, checked by `check_idl`, the gate refuses on any
difference), as txbuild does for pump.fun. Without an IDL (tests) the defaults below.
"""

from __future__ import annotations

import base64
import struct
from dataclasses import dataclass

from ..pumpfun_rt import txbuild as X
from ..pumpfun_rt.events import WSOL, b58
from . import mints as M
from .tx import Message

JUPITER = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
USDT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
JITOSOL = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
ROUTES = ("route_v2", "shared_accounts_route_v2")
MAX_UNITS = 1_400_000
MAX_PRIORITY_L = 500_000                 # 0.0005 SOL a transaction, whatever Jupiter suggests
BASE_FEE_L = 5_000
ATA_RENT_L = 2_039_280                   # a classic token account's rent (165 bytes)
ALLOWED_PROGRAMS = {X.COMPUTE_BUDGET, X.ATA_PROGRAM, X.TOKEN, X.SYSTEM, JUPITER}
# Mints a route may pass through (in Jupiter's program accounts, never ours): docs/ONCHAIN-STAGE2.md, section 1.
ROUTE_MINTS = frozenset({WSOL, M.USDC.mint, USDT, JITOSOL} | {m.mint for m in M.COINS.values()})

# Account roles of the two route instructions, by the IDL's names. Every account under a source or
# destination name must be the wallet's own associated account (or Jupiter's id, Anchor's "none"); a
# platform fee account must be "none".
SIGNER_NAMES = ("user_transfer_authority",)
SOURCE_NAMES = ("user_source_token_account", "source_token_account")
DEST_NAMES = ("user_destination_token_account", "destination_token_account")
IN_MINT_NAMES = ("source_mint", "input_mint")
OUT_MINT_NAMES = ("destination_mint", "output_mint")
FEE_NAMES = ("platform_fee_account",)
ARG_NAMES = ("in_amount", "quoted_out_amount", "slippage_bps", "platform_fee_bps")
# Defaults without an IDL (tests): the layout docs/ONCHAIN-STAGE2.md observed.
DEFAULT_ACCOUNTS = {
    "route_v2": ["user_transfer_authority", "user_source_token_account", "user_destination_token_account",
                 "source_mint", "destination_mint", "source_token_program", "destination_token_program",
                 "event_authority", "program"],
    "shared_accounts_route_v2": ["program_authority", "user_transfer_authority", "source_token_account",
                                 "program_source_token_account", "program_destination_token_account",
                                 "destination_token_account", "source_mint", "destination_mint",
                                 "source_token_program", "destination_token_program", "event_authority", "program"]}
DEFAULT_ARGS = {"route_v2": {"in_amount": (8, 8), "quoted_out_amount": (16, 8), "slippage_bps": (24, 2),
                             "platform_fee_bps": (26, 2)},
                "shared_accounts_route_v2": {"in_amount": (9, 8), "quoted_out_amount": (17, 8),
                                             "slippage_bps": (25, 2), "platform_fee_bps": (27, 2)}}


class Refused(ValueError):
    """The guard said no: nothing is signed."""


@dataclass(frozen=True)
class Plan:
    """The one swap we mean to sign: amounts in raw units, our own minimum and slippage."""
    wallet: str
    in_mint: str
    out_mint: str
    in_raw: int
    min_out_raw: int
    slippage_bps: int
    allowed: frozenset                   # the mints the owner's ack allows (and USDC / wSOL as listed there)

    def expected(self) -> set[str]:
        return {X.ata(self.wallet, self.in_mint), X.ata(self.wallet, self.out_mint), X.ata(self.wallet, WSOL)}


# ---------------------------------------------------------------- Jupiter's IDL

class JupIdl:
    """The parts of Jupiter's IDL the guard needs: per route instruction the account names in order,
    the discriminator and the offsets of the fixed arguments (before any variable-size one)."""

    def __init__(self, doc: dict | None):
        self.doc = doc
        self.idl = X.Idl(doc) if doc else None

    def accounts(self, ix: str) -> list[str]:
        if self.idl is None:
            return DEFAULT_ACCOUNTS[ix]
        return [X._snake(a.get("name", "")) for a in self.idl.accounts(ix)]

    def disc(self, ix: str) -> bytes:
        return self.idl.disc(ix) if self.idl is not None else X.discriminator(ix)

    def args(self, ix: str) -> dict[str, tuple[int, int]]:
        """{name: (offset in the data, size)} of every argument at a fixed place."""
        if self.idl is None:
            return DEFAULT_ARGS[ix]
        out, pos = {}, 8
        for a in (self.idl.ix.get(ix) or {}).get("args") or []:
            n = X._size(a.get("type"))
            if n is None:
                break
            out[X._snake(a.get("name", ""))] = (pos, n)
            pos += n
        return out


def check_idl(doc: dict | None) -> list[str]:
    """Every reason the owner's Jupiter IDL does not match what the guard reads; empty when it does."""
    if not doc:
        return ["no Jupiter IDL (the owner's copy of JUP6's on-chain IDL)"]
    j = JupIdl(doc)
    out = []
    for ix in ROUTES:
        if ix not in j.idl.ix:
            out.append(f"jupiter {ix}: not in the IDL")
            continue
        if j.disc(ix) != X.discriminator(ix):
            out.append(f"jupiter {ix}: the IDL's discriminator is not the Anchor one the guard expects")
        args = j.args(ix)
        for n in ARG_NAMES:
            if n not in args:
                out.append(f"jupiter {ix}: {n} is not at a fixed place in the IDL's arguments")
        names = j.accounts(ix)
        for role, cands in (("signer", SIGNER_NAMES), ("source", SOURCE_NAMES), ("destination", DEST_NAMES),
                            ("input mint", IN_MINT_NAMES), ("output mint", OUT_MINT_NAMES)):
            if not any(c in names for c in cands):
                out.append(f"jupiter {ix}: no {role} account in the IDL")
    return out


# ---------------------------------------------------------------- the message

def _u(data: bytes, off: int, size: int) -> int:
    if len(data) < off + size:
        raise Refused("a Jupiter instruction too short for its arguments")
    return int.from_bytes(data[off:off + size], "little")


def min_out(quoted: int, slippage_bps: int) -> int:
    """What Jupiter's program enforces: the quoted amount less the slippage, rounded down."""
    return quoted * (10_000 - slippage_bps) // 10_000


def _check_route(p: Plan, ix: X.Ix, idl: JupIdl) -> None:
    name = next((n for n in ROUTES if ix.data[:8] == idl.disc(n)), None)
    if name is None:
        raise Refused("a Jupiter instruction other than route_v2 or shared_accounts_route_v2 (no ExactOut, no "
                      "token ledger, nothing else)")
    names = idl.accounts(name)
    if len(ix.accounts) < len(names):
        raise Refused(f"{name} with fewer accounts than the IDL names")
    acc = {n: ix.accounts[i] for i, n in enumerate(names)}
    sig = [acc[n] for n in SIGNER_NAMES if n in acc]
    if not sig or any(a[0] != p.wallet for a in sig):
        raise Refused(f"{name}: the authority is not our wallet")
    if any(a[1] and a[0] != p.wallet for a in ix.accounts):
        raise Refused(f"{name}: another signer")
    src, dst = X.ata(p.wallet, p.in_mint), X.ata(p.wallet, p.out_mint)
    for n in SOURCE_NAMES:
        if n in acc and acc[n][0] not in (src, JUPITER):
            raise Refused(f"{name}: the source is not our own {p.in_mint[:6]} account")
    if not any(n in acc and acc[n][0] == src for n in SOURCE_NAMES):
        raise Refused(f"{name}: the source is not our own {p.in_mint[:6]} account")
    for n in DEST_NAMES:
        if n in acc and acc[n][0] not in (dst, JUPITER):
            raise Refused(f"{name}: the output goes to an account that is not our own")
    if not any(n in acc and acc[n][0] == dst for n in DEST_NAMES):
        raise Refused(f"{name}: the output goes to an account that is not our own")
    for n in IN_MINT_NAMES:
        if n in acc and acc[n][0] != p.in_mint:
            raise Refused(f"{name}: the input mint is not the planned one")
    for n in OUT_MINT_NAMES:
        if n in acc and acc[n][0] != p.out_mint:
            raise Refused(f"{name}: the output mint is not the planned one")
    for n in FEE_NAMES:
        if n in acc and acc[n][0] != JUPITER:
            raise Refused(f"{name}: a platform fee account (fees to a third party)")
    args = idl.args(name)
    if any(n not in args for n in ARG_NAMES):
        raise Refused(f"{name}: the IDL puts the amounts where the guard cannot read them")
    a = {n: _u(ix.data, *args[n]) for n in ARG_NAMES}
    if a["in_amount"] != p.in_raw:
        raise Refused(f"{name}: in_amount {a['in_amount']} is not the planned {p.in_raw}")
    if a["platform_fee_bps"] != 0:
        raise Refused(f"{name}: a platform fee")
    if a["slippage_bps"] > p.slippage_bps:
        raise Refused(f"{name}: slippage {a['slippage_bps']} bps above ours ({p.slippage_bps})")
    if min_out(a["quoted_out_amount"], a["slippage_bps"]) < p.min_out_raw:
        raise Refused(f"{name}: the minimum out is below our bound")


def check_message(p: Plan, msg: Message, idl: JupIdl | None = None, sender_tip_ok: bool = False) -> dict:
    """Refuse (Refused) anything but the planned swap; returns what it read (units, price, tip) for the fee bound."""
    idl = idl or JupIdl(None)
    if p.in_mint == p.out_mint:
        raise Refused("a swap of a mint into itself")
    for m in (p.in_mint, p.out_mint):
        if m not in p.allowed:
            raise Refused(f"the mint {m[:6]} is not on the allowlist")
    if msg.version != 0 or msg.signers != 1 or not msg.keys or msg.keys[0] != p.wallet or not msg.writable[0]:
        raise Refused("the message must have exactly one signer, our wallet, paying")
    wsol = X.ata(p.wallet, WSOL)
    units = price = None
    tip_l, tips, routes = 0, 0, 0
    for ix in msg.ixs:
        if ix.program not in ALLOWED_PROGRAMS:
            raise Refused(f"program {ix.program[:8]} is not part of a plain swap")
        if any(s and k != p.wallet for k, s, _ in ix.accounts):
            raise Refused("an instruction with another signer")
        if ix.program == X.COMPUTE_BUDGET:
            if ix.data[:1] == b"\x02" and len(ix.data) == 5 and units is None:
                units = struct.unpack_from("<I", ix.data, 1)[0]
            elif ix.data[:1] == b"\x03" and len(ix.data) == 9 and price is None:
                price = struct.unpack_from("<Q", ix.data, 1)[0]
            else:
                raise Refused("a compute budget instruction other than one unit limit and one price")
            continue
        if ix.program == X.ATA_PROGRAM:
            if ix.data not in (b"", b"\x00", b"\x01") or len(ix.accounts) != 6:
                raise Refused("an associated-account instruction other than create")
            a = [k for k, _, _ in ix.accounts]
            if a[0] != p.wallet or a[2] != p.wallet or a[4] != X.SYSTEM or a[5] != X.TOKEN:
                raise Refused("an associated account created for someone else or under another token program")
            if a[3] not in p.allowed and a[3] != WSOL:
                raise Refused(f"an associated account for a mint not on the allowlist ({a[3][:6]})")
            if a[1] != X.ata(p.wallet, a[3]):
                raise Refused("an associated account at an address that is not the derived one")
            continue
        if ix.program == X.TOKEN:
            a = [k for k, _, _ in ix.accounts]
            if ix.data == b"\x09" and len(a) == 3:
                if a[0] != wsol or a[1] != p.wallet or a[2] != p.wallet:
                    raise Refused("a token account closed that is not our wrapped SOL, or to someone else")
                continue
            if ix.data == b"\x11" and len(a) == 1 and a[0] == wsol:
                continue
            raise Refused("a token instruction other than closing or syncing our wrapped SOL (no transfer, "
                          "approve, delegate, SetAuthority or burn)")
        if ix.program == X.SYSTEM:
            a = [k for k, _, _ in ix.accounts]
            if len(a) != 2 or len(ix.data) != 12 or ix.data[:4] != struct.pack("<I", 2) or a[0] != p.wallet:
                raise Refused("a system instruction that is not a plain transfer from the wallet")
            amount = struct.unpack_from("<Q", ix.data, 4)[0]
            if a[1] == wsol:
                if p.in_mint != WSOL or amount > p.in_raw:
                    raise Refused("a wrap of more SOL than the planned sale")
                continue
            if a[1] in X.HELIUS_TIP_ACCOUNTS:
                if not sender_tip_ok:
                    raise Refused("a Sender tip, and Sender is not switched on")
                if amount > X.HELIUS_MAX_TIP_LAMPORTS:
                    raise Refused("a Sender tip above the hard cap")
                tips += 1
                if tips > 1:
                    raise Refused("more than one tip")
                tip_l = amount
                continue
            raise Refused("a transfer out of the wallet")
        if ix.program == JUPITER:
            routes += 1
            if routes > 1:
                raise Refused("more than one Jupiter instruction")
            _check_route(p, ix, idl)
    if routes != 1:
        raise Refused("no Jupiter swap in the message")
    if units is None or units > MAX_UNITS:
        raise Refused(f"the compute unit limit must be set and at most {MAX_UNITS:,}")
    priority_l = (price or 0) * units // 1_000_000
    if priority_l > MAX_PRIORITY_L:
        raise Refused("a priority fee above the hard cap")
    return {"units": units, "price": price or 0, "priority_l": priority_l, "tip_l": tip_l,
            "max_fee_l": BASE_FEE_L + priority_l + tip_l}


# ---------------------------------------------------------------- the accounts on chain

@dataclass(frozen=True)
class TokenAccount:
    mint: str
    owner: str
    amount: int
    delegate: str | None
    close_authority: str | None


def parse_token(data: bytes) -> TokenAccount | None:
    """A classic SPL token account (165 bytes), None for anything else."""
    if len(data) != 165:
        return None
    dlg = b58(data[76:108]) if data[72:76] == b"\x01\x00\x00\x00" else None
    close = b58(data[133:165]) if data[129:133] == b"\x01\x00\x00\x00" else None
    return TokenAccount(b58(data[0:32]), b58(data[32:64]), int.from_bytes(data[64:72], "little"), dlg, close)


@dataclass(frozen=True)
class Account:
    lamports: int
    owner: str
    data: bytes


def account_of(v) -> Account | None:
    """An RPC account object (getMultipleAccounts or a simulation's accounts, base64) to an Account."""
    if not isinstance(v, dict):
        return None
    try:
        d = v.get("data")
        raw = base64.b64decode(d[0]) if isinstance(d, list) else b""
        return Account(int(v.get("lamports") or 0), str(v.get("owner") or ""), raw)
    except (TypeError, ValueError):
        return None


def check_accounts(p: Plan, accounts: dict[str, Account | None]) -> None:
    """Every writable account of the message as the chain has it now (None: does not exist yet)."""
    exp = p.expected()
    for k, a in accounts.items():
        if a is None:
            continue
        if a.owner == X.TOKEN_2022:
            raise Refused("a Token-2022 account in the swap (refused in stage 2)")
        if a.owner != X.TOKEN:
            continue
        t = parse_token(a.data)
        if t is None or t.owner != p.wallet:
            continue
        if k not in exp:
            raise Refused(f"the swap writes to another token account of ours ({k[:6]})")
        if t.delegate or t.close_authority:
            raise Refused(f"our token account {k[:6]} has a delegate or close authority; it is not touched")


def check_mint(mint: str, a: Account | None) -> None:
    """A mint must exist under the classic Token program (no Token-2022 in stage 2)."""
    if a is None:
        raise Refused(f"the mint {mint[:6]} does not exist")
    if a.owner != X.TOKEN:
        raise Refused(f"the mint {mint[:6]} is not a classic SPL token (Token-2022 is refused in stage 2)")


def check_effect(p: Plan, pre: dict[str, Account | None], post: dict[str, Account | None], max_fee_l: int) -> dict:
    """The simulation's diff over the wallet and every token account of ours (pre from the chain right
    before, post from simulateTransaction's accounts). Returns the deltas; Refused on anything else."""
    w = p.wallet
    if post.get(w) is None or pre.get(w) is None:
        raise Refused("the simulation did not return the wallet")
    src, dst, wsol = X.ata(w, p.in_mint), X.ata(w, p.out_mint), X.ata(w, WSOL)
    created = 0
    tok: dict[str, int] = {}
    for k in set(pre) | set(post):
        if k == w:
            continue
        a, b = pre.get(k), post.get(k)
        ta = parse_token(a.data) if a is not None and a.owner == X.TOKEN else None
        tb = parse_token(b.data) if b is not None and b.owner == X.TOKEN else None
        if (a is not None and a.owner == X.TOKEN_2022) or (b is not None and b.owner == X.TOKEN_2022):
            if a != b:
                raise Refused(f"a Token-2022 account of ours changed ({k[:6]})")
            continue
        if ta is None and tb is None:
            continue
        if ta is not None and ta.owner != w:
            continue                                    # not ours
        if tb is not None and tb.owner != w and ta is not None:
            raise Refused(f"our token account {k[:6]} changed owner")
        if tb is None:                                  # closed
            if k != wsol:
                raise Refused(f"our token account {k[:6]} was closed")
            continue
        if ta is None:                                  # created
            if k not in (dst, src, wsol):
                raise Refused(f"a token account of ours appeared that is not expected ({k[:6]})")
            if k != wsol:
                created += 1
        if tb.delegate or tb.close_authority:
            raise Refused(f"our token account {k[:6]} got a delegate or close authority")
        if ta is not None and (ta.delegate != tb.delegate or ta.close_authority != tb.close_authority):
            raise Refused(f"the authority of our token account {k[:6]} changed")
        d = tb.amount - (ta.amount if ta else 0)
        if k == wsol:
            if ta is not None and ta.amount > 0 and d < 0:
                raise Refused("the swap spends wrapped SOL the wallet held")
            continue
        tok[k] = d
        if k == src:
            if d < -p.in_raw:
                raise Refused(f"the input fell by {-d}, more than the planned {p.in_raw}")
        elif k == dst:
            if d < p.min_out_raw:
                raise Refused(f"the output rose by {d}, less than our minimum {p.min_out_raw}")
        elif d < 0:
            raise Refused(f"another token account of ours fell ({k[:6]})")
    if p.out_mint != WSOL and tok.get(dst, 0) < p.min_out_raw:
        raise Refused("the output did not arrive in our account")
    sol = post[w].lamports - pre[w].lamports
    allow = max_fee_l + created * ATA_RENT_L
    if p.in_mint == WSOL:
        allow += p.in_raw + ATA_RENT_L               # the wrapped-SOL account's rent comes back when it closes
    if p.out_mint == WSOL:
        if sol < p.min_out_raw - allow:
            raise Refused(f"SOL rose by {sol}, less than our minimum {p.min_out_raw} after fees")
    elif sol < -allow:
        raise Refused(f"SOL fell by {-sol}, more than fees, tip and rent ({allow})")
    if post[w].owner and pre[w].owner and post[w].owner != pre[w].owner:
        raise Refused("the wallet's owner changed")
    return {"sol_l": sol, "tok": tok, "created": created}
