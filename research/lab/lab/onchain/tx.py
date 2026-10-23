"""Versioned (v0) Solana messages with address lookup tables, built and read back byte by byte.

Pure functions: no key, no signing, no network. The stage-2 executor (live_exec.py)
compiles Jupiter's instructions into one v0 message with `compile_v0`, reads the
SAME bytes back with `decompile` (the lookup tables' contents as read from the
chain by us, never as Jupiter's answer lists them) and runs the guard over what
came back, so the guard judges exactly what would be signed.

Layout (solana-program, message/versions/v0): a 0x80 prefix, the header (signers,
read-only signers, read-only non-signers among the static keys), the static keys,
the recent blockhash, the instructions (program index, account indexes, data) and
the lookups (table, writable indexes, read-only indexes). Account indexes run over
the static keys, then every table's writable addresses, then every table's
read-only ones. Signers and invoked programs are always static.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from ..pumpfun_rt.events import b58
from ..pumpfun_rt.txbuild import Ix, key, shortvec

ALT_PROGRAM = "AddressLookupTab1e1111111111111111111111111"
ALT_META = 56                       # LookupTableMeta before the addresses
MAX_TX_BYTES = 1232                 # a transaction's packet limit (signatures included)
V0 = 0x80


def parse_table(data: bytes) -> list[str]:
    """An address lookup table account's addresses. Refuses a table that is not one, or is deactivated."""
    if len(data) < ALT_META or (len(data) - ALT_META) % 32:
        raise ValueError("not an address lookup table")
    if struct.unpack_from("<I", data, 0)[0] != 1:
        raise ValueError("not an address lookup table")
    if struct.unpack_from("<Q", data, 4)[0] != 2 ** 64 - 1:
        raise ValueError("the lookup table is deactivated")
    return [b58(data[i:i + 32]) for i in range(ALT_META, len(data), 32)]


@dataclass
class Lookup:
    table: str
    writable: list[int]
    readonly: list[int]


@dataclass
class Message:
    """A message read back: every account key in index order with its flags, the instructions with
    their accounts resolved, the lookups as written."""
    version: int
    signers: int
    keys: list[str]
    writable: list[bool]
    blockhash: str
    ixs: list[Ix]
    lookups: list[Lookup]

    def is_signer(self, i: int) -> bool:
        return i < self.signers

    def writable_keys(self) -> list[str]:
        return [k for k, w in zip(self.keys, self.writable) if w]


def compile_v0(payer: str, ixs: list[Ix], blockhash: str, tables: dict[str, list[str]]) -> bytes:
    """One v0 message. Keys that sign, are invoked programs or the payer stay static; every other key found
    in one of `tables` (in the dict's order) is loaded from the first table that has it."""
    flags: dict[str, list[bool]] = {payer: [True, True]}
    order = [payer]
    invoked = set()
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
        invoked.add(ix.program)
    order = [payer] + sorted(order[1:], key=key)       # by key bytes, as solana's own compiler does
    loaded: dict[str, tuple[str, int]] = {}
    for t, addrs in tables.items():
        pos = {a: i for i, a in enumerate(addrs) if i < 256}
        for k in order:
            if k in loaded or flags[k][0] or k in invoked or k == payer:
                continue
            if k in pos:
                loaded[k] = (t, pos[k])
    static = [k for k in order if k not in loaded]
    groups = ([k for k in static if flags[k][0] and flags[k][1]], [k for k in static if flags[k][0] and not flags[k][1]],
              [k for k in static if not flags[k][0] and flags[k][1]],
              [k for k in static if not flags[k][0] and not flags[k][1]])
    skeys = [k for g in groups for k in g]
    if skeys[0] != payer:
        raise ValueError("the payer must sign and pay")
    lookups = []
    for t in tables:
        w = [(k, i) for k, (tt, i) in loaded.items() if tt == t and flags[k][1]]
        r = [(k, i) for k, (tt, i) in loaded.items() if tt == t and not flags[k][1]]
        if w or r:
            lookups.append((t, w, r))
    allkeys = skeys + [k for _, w, _ in lookups for k, _ in w] + [k for _, _, r in lookups for k, _ in r]
    if len(allkeys) > 256:
        raise ValueError("more than 256 accounts")
    idx = {k: i for i, k in enumerate(allkeys)}
    out = bytearray([V0, len(groups[0]) + len(groups[1]), len(groups[1]), len(groups[3])])
    out += shortvec(len(skeys))
    for k in skeys:
        out += key(k)
    out += key(blockhash)
    out += shortvec(len(ixs))
    for ix in ixs:
        out.append(idx[ix.program])
        out += shortvec(len(ix.accounts))
        out += bytes(idx[k] for k, _, _ in ix.accounts)
        out += shortvec(len(ix.data))
        out += ix.data
    out += shortvec(len(lookups))
    for t, w, r in lookups:
        out += key(t)
        out += shortvec(len(w)) + bytes(i for _, i in w)
        out += shortvec(len(r)) + bytes(i for _, i in r)
    return bytes(out)


class _Reader:
    def __init__(self, b: bytes):
        self.b, self.p = b, 0

    def u8(self) -> int:
        if self.p >= len(self.b):
            raise ValueError("the message ends early")
        v = self.b[self.p]
        self.p += 1
        return v

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.b):
            raise ValueError("the message ends early")
        v = self.b[self.p:self.p + n]
        self.p += n
        return v

    def vec(self) -> int:
        n, shift = 0, 0
        while True:
            c = self.u8()
            n |= (c & 0x7F) << shift
            if not c & 0x80:
                return n
            shift += 7
            if shift > 21:
                raise ValueError("a bad length")


def decompile(message: bytes, tables: dict[str, list[str]]) -> Message:
    """Read a v0 message back with the lookup tables' real contents. Raises on anything malformed, on a
    legacy message, on a table we do not have, an index outside a table, or trailing bytes."""
    r = _Reader(message)
    if r.u8() != V0:
        raise ValueError("not a v0 message")
    nsig, nro_sig, nro = r.u8(), r.u8(), r.u8()
    skeys = [b58(r.take(32)) for _ in range(r.vec())]
    if not 0 < nsig <= len(skeys) or nro_sig >= nsig or nro > len(skeys) - nsig:
        raise ValueError("a bad message header")
    writable = [i < nsig - nro_sig if i < nsig else i < len(skeys) - nro for i in range(len(skeys))]
    blockhash = b58(r.take(32))
    raw_ixs = []
    for _ in range(r.vec()):
        prog = r.u8()
        accts = list(r.take(r.vec()))
        data = r.take(r.vec())
        raw_ixs.append((prog, accts, data))
    lookups = []
    for _ in range(r.vec()):
        t = b58(r.take(32))
        lookups.append(Lookup(t, list(r.take(r.vec())), list(r.take(r.vec()))))
    if r.p != len(message):
        raise ValueError("trailing bytes after the message")
    lw, lr = [], []
    for lk in lookups:
        addrs = tables.get(lk.table)
        if addrs is None:
            raise ValueError(f"a lookup table we did not read ({lk.table[:8]})")
        for i in lk.writable + lk.readonly:
            if i >= len(addrs):
                raise ValueError("a lookup index outside its table")
        lw += [addrs[i] for i in lk.writable]
        lr += [addrs[i] for i in lk.readonly]
    keys = skeys + lw + lr
    writable += [True] * len(lw) + [False] * len(lr)
    ixs = []
    for prog, accts, data in raw_ixs:
        if prog >= len(skeys) or any(a >= len(keys) for a in accts):
            raise ValueError("an index outside the accounts")
        ixs.append(Ix(keys[prog], [(keys[a], a < nsig, writable[a]) for a in accts], bytes(data)))
    return Message(0, nsig, keys, writable, blockhash, ixs, lookups)


def transaction(message: bytes, signature: bytes) -> bytes:
    """The wire transaction of a one-signer v0 message."""
    if len(message) < 2 or message[0] != V0 or message[1] != 1 or len(signature) != 64:
        raise ValueError("one 64-byte signature for a one-signer v0 message")
    return shortvec(1) + signature + message


def unsigned(message: bytes) -> bytes:
    """The transaction with an empty signature, for simulateTransaction with sigVerify off."""
    return transaction(message, bytes(64))
