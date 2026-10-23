"""The stage-2 on-chain trader (lab.onchain: tx, guard, swapapi, live_gate, live_exec, live_service, wallet):
the v0 message against solders, every forbidden transaction the guard must refuse, the gate, the caps, the
executor end to end on a fake chain, the journal and the reconciliation, the converts, a book's swaps.
No network, no key of anyone: every address here is a hash of a made-up name.

Run from research/lab:  python -m pytest tests/test_onchain_live.py
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import struct

import pytest

from lab.onchain import guard as G
from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import live_service as SV
from lab.onchain import mints as M
from lab.onchain import swapapi as S
from lab.onchain import tx as T
from lab.onchain import wallet as OW
from lab.onchain.jupiter import Jupiter, QuoteError
from lab.pumpfun_rt import txbuild as X
from lab.pumpfun_rt.events import WSOL, b58


def A(name: str) -> str:
    return b58(hashlib.sha256(name.encode()).digest())


W = A("our wallet")
OTHER = A("someone else")
TABLE = A("lookup table")
DEX = A("a dex program")
POOL = [A(f"pool account {i}") for i in range(6)]
USDC, SOL, BTC = M.USDC.mint, M.SOL.mint, M.COINS["BTC"].mint
ALLOWED = frozenset({USDC, SOL, BTC})
NOW = 1_792_712_000_000
JUP_DATA = A("jupiter programdata")
JUP_SLOT = 300_000_000
PIN = {"program": G.JUPITER, "programdata": JUP_DATA, "slot": JUP_SLOT, "t": NOW}


# ---------------------------------------------------------------- building blocks

def route_ix(in_mint=USDC, out_mint=SOL, amount=10_000_000, quoted=100_000_000, slip=30, fee_bps=0, wallet=W,
             src=None, dst=None, name="shared_accounts_route_v2", extra=None, disc=None) -> X.Ix:
    names = G.DEFAULT_ACCOUNTS[name]
    vals = {"program_authority": A("jup authority"), "user_transfer_authority": wallet,
            "source_token_account": src or X.ata(wallet, in_mint), "user_source_token_account": src or X.ata(wallet, in_mint),
            "program_source_token_account": A("jup src"), "program_destination_token_account": A("jup dst"),
            "destination_token_account": dst or X.ata(wallet, out_mint),
            "user_destination_token_account": dst or X.ata(wallet, out_mint),
            "source_mint": in_mint, "destination_mint": out_mint, "source_token_program": X.TOKEN,
            "destination_token_program": X.TOKEN, "event_authority": A("jup events"), "program": G.JUPITER}
    accts = [(vals[n], n == "user_transfer_authority", n not in ("source_mint", "destination_mint", "program",
                                                                    "event_authority", "source_token_program",
                                                                    "destination_token_program", "program_authority",
                                                                    "user_transfer_authority"))
             for n in names]
    accts[names.index("user_transfer_authority")] = (wallet, True, True)
    accts += [(k, False, True) for k in POOL] + (extra or [])
    head = (b"\x03" if name == "shared_accounts_route_v2" else b"")
    data = (disc or X.discriminator(name)) + head + struct.pack("<QQHHH", amount, quoted, slip, fee_bps, 0) + b"\x01\x02"
    return X.Ix(G.JUPITER, accts, data)


def plan(in_mint=USDC, out_mint=SOL, amount=10_000_000, quoted=100_000_000, slip=30) -> G.Plan:
    return G.Plan(W, in_mint, out_mint, amount, G.min_out(quoted, slip), slip, ALLOWED)


def good_ixs(in_mint=USDC, out_mint=SOL, units=300_000, price=80_000, tip=5_000, **kw) -> list[X.Ix]:
    ixs = [X.compute_limit(units), X.compute_price(price)]
    if in_mint == SOL:
        ixs += [X.create_ata(W, W, WSOL), X.wrap_sol(W, kw.get("amount", 10_000_000)), X.sync_native(X.ata(W, WSOL))]
    ixs += [X.create_ata(W, W, out_mint), route_ix(in_mint, out_mint, **kw)]
    if out_mint == SOL or in_mint == SOL:
        ixs.append(X.close_own(X.ata(W, WSOL), W))
    if tip:
        ixs.append(X.tip(W, sorted(X.HELIUS_TIP_ACCOUNTS)[0], tip))
    return ixs


def message(ixs, tables=None):
    tables = {TABLE: POOL} if tables is None else tables
    b = T.compile_v0(W, ixs, A("blockhash"), tables)
    return T.decompile(b, tables)


def check(ixs, p=None, tip_ok=True):
    return G.check_message(p or plan(), message(ixs), sender_tip_ok=tip_ok)


# ---------------------------------------------------------------- the v0 message

def test_v0_message_matches_solders_and_reads_back():
    from solders.address_lookup_table_account import AddressLookupTableAccount
    from solders.hash import Hash
    from solders.instruction import AccountMeta, Instruction
    from solders.message import MessageV0
    from solders.pubkey import Pubkey
    ixs = good_ixs()
    ours = T.compile_v0(W, ixs, A("blockhash"), {TABLE: POOL})
    sm = MessageV0.try_compile(
        Pubkey.from_string(W),
        [Instruction(Pubkey.from_string(i.program), i.data, [AccountMeta(Pubkey.from_string(k), s, w)
                                                              for k, s, w in i.accounts]) for i in ixs],
        [AddressLookupTableAccount(Pubkey.from_string(TABLE), [Pubkey.from_string(x) for x in POOL])],
        Hash.from_string(A("blockhash")))
    assert ours == bytes([0x80]) + bytes(sm)
    m = T.decompile(ours, {TABLE: POOL})
    assert m.signers == 1 and m.keys[0] == W and m.blockhash == A("blockhash") and len(m.lookups) == 1
    assert [(i.program, i.data, [a[0] for a in i.accounts]) for i in m.ixs] == \
        [(i.program, i.data, [a[0] for a in i.accounts]) for i in ixs]
    assert set(POOL) <= set(m.writable_keys()) and not any(k in m.keys[:len(m.keys) - 6] for k in POOL)
    tx = T.transaction(ours, bytes(64))
    assert tx[0] == 1 and tx[65:] == ours and len(tx) <= T.MAX_TX_BYTES


def test_v0_read_back_refuses_what_it_cannot_resolve():
    b = T.compile_v0(W, good_ixs(), A("blockhash"), {TABLE: POOL})
    with pytest.raises(ValueError, match="did not read"):
        T.decompile(b, {})
    with pytest.raises(ValueError, match="outside"):
        T.decompile(b, {TABLE: POOL[:2]})
    with pytest.raises(ValueError, match="trailing"):
        T.decompile(b + b"\x00", {TABLE: POOL})
    with pytest.raises(ValueError, match="v0"):
        T.decompile(X.compile_message(W, good_ixs(), A("blockhash")), {TABLE: POOL})
    with pytest.raises(ValueError):
        T.transaction(b, bytes(63))


def test_lookup_tables_parse_only_active_tables():
    meta = struct.pack("<IQQB", 1, 2 ** 64 - 1, 5, 0) + b"\x00" * 35
    assert len(meta) == T.ALT_META
    data = meta + b"".join(X.key(k) for k in POOL)
    assert T.parse_table(data) == POOL
    with pytest.raises(ValueError, match="deactivated"):
        T.parse_table(struct.pack("<IQQB", 1, 7, 5, 0) + b"\x00" * 35 + X.key(POOL[0]))
    with pytest.raises(ValueError):
        T.parse_table(b"\x02" + data[1:])


# ---------------------------------------------------------------- the guard: what passes

def test_the_planned_swap_passes_buy_and_sale():
    info = check(good_ixs())
    assert info == {"units": 300_000, "price": 80_000, "priority_l": 24_000, "tip_l": 5_000,
                    "max_fee_l": 5_000 + 24_000 + 5_000}
    assert check(good_ixs(SOL, USDC, quoted=9_000_000), plan(SOL, USDC, quoted=9_000_000))["units"] == 300_000
    assert check(good_ixs(name="route_v2"))["tip_l"] == 5_000
    assert check(good_ixs(tip=0), tip_ok=False)["tip_l"] == 0


# ---------------------------------------------------------------- the guard: every forbidden variant

def _swap(ixs, i, new):
    ixs = list(ixs)
    ixs[i] = new
    return ixs


def _route_at(ixs):
    return next(i for i, ix in enumerate(ixs) if ix.program == G.JUPITER)


@pytest.mark.parametrize("make, why", [
    # the output into a foreign token account
    (lambda: _swap(good_ixs(), 3, route_ix(dst=X.ata(OTHER, SOL))), "not our own"),
    # the input from a foreign token account
    (lambda: _swap(good_ixs(), 3, route_ix(src=X.ata(OTHER, USDC))), "source"),
    # an unknown program
    (lambda: good_ixs() + [X.Ix(A("evil program"), [(W, True, True)], b"\x00")], "not part of a plain swap"),
    # a mint not on the allowlist
    (lambda: _swap(good_ixs(out_mint=M.COINS["BONK"].mint), 3, route_ix(out_mint=M.COINS["BONK"].mint)), "allowlist"),
    # a transfer out of the wallet
    (lambda: good_ixs() + [X.Ix(X.SYSTEM, [(W, True, True), (OTHER, False, True)], struct.pack("<IQ", 2, 1))],
     "transfer out"),
    # a token transfer out of our account
    (lambda: good_ixs() + [X.Ix(X.TOKEN, [(X.ata(W, USDC), False, True), (X.ata(OTHER, USDC), False, True),
                                          (W, True, False)], b"\x03" + struct.pack("<Q", 5))], "token instruction"),
    # a close of an account to someone else
    (lambda: good_ixs() + [X.Ix(X.TOKEN, [(X.ata(W, WSOL), False, True), (OTHER, False, True), (W, True, False)],
                                b"\x09")], "someone else"),
    # closing our USDC account
    (lambda: good_ixs() + [X.close_own(X.ata(W, USDC), W)], "not our wrapped SOL"),
    # approve and delegate
    (lambda: good_ixs() + [X.Ix(X.TOKEN, [(X.ata(W, USDC), False, True), (OTHER, False, False), (W, True, False)],
                                b"\x04" + struct.pack("<Q", 10 ** 12))], "approve"),
    # SetAuthority
    (lambda: good_ixs() + [X.Ix(X.TOKEN, [(X.ata(W, USDC), False, True), (W, True, False)], b"\x06\x02\x01"
                                + X.key(OTHER))], "token instruction"),
    # a tip above the hard cap
    (lambda: good_ixs(tip=X.HELIUS_MAX_TIP_LAMPORTS + 1), "above the hard cap"),
    # two tips
    (lambda: good_ixs() + [X.tip(W, sorted(X.HELIUS_TIP_ACCOUNTS)[1], 5_000)], "more than one tip"),
    # the compute unit limit too high
    (lambda: good_ixs(units=G.MAX_UNITS + 1), "compute unit limit"),
    # a priority fee above the cap
    (lambda: good_ixs(units=1_000_000, price=600_000), "priority fee"),
    # a second compute budget price
    (lambda: good_ixs() + [X.compute_price(1)], "compute budget"),
    # a heap frame request
    (lambda: good_ixs() + [X.Ix(X.COMPUTE_BUDGET, [], b"\x01" + struct.pack("<I", 256 * 1024))], "compute budget"),
    # an associated account for someone else
    (lambda: _swap(good_ixs(), 2, X.create_ata(W, OTHER, SOL)), "someone else"),
    # an associated account under Token-2022
    (lambda: _swap(good_ixs(), 2, X.create_ata(W, W, SOL, X.TOKEN_2022)), "another token program"),
    # an ExactOut route
    (lambda: _swap(good_ixs(), 3, route_ix(disc=X.discriminator("exact_out_route_v2"))), "ExactOut"),
    # a platform fee
    (lambda: _swap(good_ixs(), 3, route_ix(fee_bps=50)), "platform fee"),
    # more input than planned
    (lambda: _swap(good_ixs(), 3, route_ix(amount=10_000_001)), "in_amount"),
    # a looser slippage than ours
    (lambda: _swap(good_ixs(), 3, route_ix(slip=500)), "slippage"),
    # a quote below our bound
    (lambda: _swap(good_ixs(), 3, route_ix(quoted=90_000_000)), "minimum out"),
    # two Jupiter instructions
    (lambda: good_ixs() + [route_ix()], "more than one Jupiter"),
    # no Jupiter instruction at all
    (lambda: [ix for ix in good_ixs() if ix.program != G.JUPITER], "no Jupiter"),
    # another authority in the swap
    (lambda: _swap(good_ixs(), 3, route_ix(wallet=OTHER)), "signer"),
    # a wrap while USDC is sold
    (lambda: good_ixs() + [X.wrap_sol(W, 1)], "wrap"),
])
def test_the_guard_refuses(make, why):
    with pytest.raises(G.Refused, match=why):
        check(make())


def test_the_guard_refuses_a_tip_without_sender_and_a_foreign_payer():
    with pytest.raises(G.Refused, match="Sender is not switched on"):
        check(good_ixs(), tip_ok=False)
    with pytest.raises(G.Refused, match="exactly one signer"):
        G.check_message(plan(), T.decompile(T.compile_v0(OTHER, good_ixs(), A("bh"), {TABLE: POOL}), {TABLE: POOL}),
                        sender_tip_ok=True)
    with pytest.raises(G.Refused, match="into itself"):
        check(good_ixs(), plan(USDC, USDC))


def test_the_guard_refuses_a_platform_fee_account_and_a_foreign_destination_slot():
    idl = G.JupIdl(None)
    names = ["user_transfer_authority", "user_source_token_account", "user_destination_token_account",
             "destination_token_account", "source_mint", "destination_mint", "platform_fee_account", "program"]
    G.DEFAULT_ACCOUNTS["route_v3_test"] = names
    G.DEFAULT_ARGS["route_v3_test"] = G.DEFAULT_ARGS["route_v2"]
    try:
        def ix(fee=G.JUPITER, dest=G.JUPITER):
            vals = [W, X.ata(W, USDC), X.ata(W, SOL), dest, USDC, SOL, fee, G.JUPITER]
            return X.Ix(G.JUPITER, [(v, i == 0, True) for i, v in enumerate(vals)],
                        X.discriminator("route_v3_test") + struct.pack("<QQHHH", 10_000_000, 100_000_000, 30, 0, 0))
        G.ROUTES, old = ("route_v3_test",), G.ROUTES
        try:
            G._check_route(plan(), ix(), idl)
            with pytest.raises(G.Refused, match="platform fee account"):
                G._check_route(plan(), ix(fee=OTHER), idl)
            with pytest.raises(G.Refused, match="not our own"):            # v1's optional "send it elsewhere"
                G._check_route(plan(), ix(dest=X.ata(OTHER, SOL)), idl)
        finally:
            G.ROUTES = old
    finally:
        del G.DEFAULT_ACCOUNTS["route_v3_test"], G.DEFAULT_ARGS["route_v3_test"]


# ---------------------------------------------------------------- the guard: accounts and the simulation's diff

def tok_data(mint, owner, amount, delegate=None, close=None, state=1) -> bytes:
    d = X.key(mint) + X.key(owner) + struct.pack("<Q", amount)
    d += (b"\x01\x00\x00\x00" + X.key(delegate)) if delegate else b"\x00" * 36
    d += bytes([state]) + b"\x00" * 12 + struct.pack("<Q", 0)
    d += (b"\x01\x00\x00\x00" + X.key(close)) if close else b"\x00" * 36
    assert len(d) == 165
    return d


def tacc(mint, owner, amount, **kw) -> G.Account:
    return G.Account(G.ATA_RENT_L, X.TOKEN, tok_data(mint, owner, amount, **kw))


def test_check_accounts_refuses_other_token_accounts_of_ours_and_token_2022():
    p = plan()
    ok = {X.ata(W, USDC): tacc(USDC, W, 50_000_000), POOL[0]: tacc(USDC, A("pool authority"), 10 ** 12),
          POOL[1]: G.Account(1, DEX, b"pool state"), X.ata(W, SOL): None}
    G.check_accounts(p, ok)
    with pytest.raises(G.Refused, match="another token account of ours"):
        G.check_accounts(p, {**ok, POOL[2]: tacc(BTC, W, 5)})
    with pytest.raises(G.Refused, match="Token-2022"):
        G.check_accounts(p, {**ok, POOL[2]: G.Account(1, X.TOKEN_2022, b"\x00" * 170)})
    with pytest.raises(G.Refused, match="delegate"):
        G.check_accounts(p, {**ok, X.ata(W, USDC): tacc(USDC, W, 50_000_000, delegate=OTHER)})
    with pytest.raises(G.Refused, match="Token-2022"):
        G.check_mint(USDC, G.Account(1, X.TOKEN_2022, b""))
    G.check_mint(USDC, G.Account(1, X.TOKEN, b"\x00" * 82))


def _states(usdc_after=40_000_000, sol_after=None, out_after=None, extra_pre=None, extra_post=None):
    pre = {W: G.Account(1_000_000_000, X.SYSTEM, b""), X.ata(W, USDC): tacc(USDC, W, 50_000_000),
           X.ata(W, BTC): tacc(BTC, W, 7), X.ata(W, SOL): None}
    post = {W: G.Account(sol_after if sol_after is not None else 1_000_000_000 + 99_800_000 - 34_000, X.SYSTEM, b""),
            X.ata(W, USDC): tacc(USDC, W, usdc_after), X.ata(W, BTC): tacc(BTC, W, 7), X.ata(W, SOL): None}
    pre.update(extra_pre or {})
    post.update(extra_post or {})
    return pre, post


def test_check_effect_passes_the_planned_change_and_refuses_everything_else():
    p = plan()                                          # 10 USDC for at least 99.7 M lamports
    pre, post = _states()
    eff = G.check_effect(p, pre, post, 34_000)
    assert eff["tok"][X.ata(W, USDC)] == -10_000_000 and eff["sol_l"] == 99_766_000
    # a drain of a third account of ours
    pre, post = _states(extra_post={X.ata(W, BTC): tacc(BTC, W, 0)})
    with pytest.raises(G.Refused, match="another token account of ours fell"):
        G.check_effect(p, pre, post, 34_000)
    # more input than planned
    pre, post = _states(usdc_after=30_000_000)
    with pytest.raises(G.Refused, match="more than the planned"):
        G.check_effect(p, pre, post, 34_000)
    # less output than our minimum
    pre, post = _states(sol_after=1_000_000_000 + 50_000_000)
    with pytest.raises(G.Refused, match="less than our minimum"):
        G.check_effect(p, pre, post, 34_000)
    # a delegate set on our account
    pre, post = _states(extra_post={X.ata(W, BTC): tacc(BTC, W, 7, delegate=OTHER)})
    with pytest.raises(G.Refused, match="delegate"):
        G.check_effect(p, pre, post, 34_000)
    # our account handed to someone else
    pre, post = _states(extra_post={X.ata(W, BTC): tacc(BTC, OTHER, 7)})
    with pytest.raises(G.Refused, match="changed owner"):
        G.check_effect(p, pre, post, 34_000)
    # our account closed
    pre, post = _states(extra_post={X.ata(W, BTC): None})
    with pytest.raises(G.Refused, match="was closed"):
        G.check_effect(p, pre, post, 34_000)
    # SOL fell by more than fees when USDC is sold for BTC
    pb = G.Plan(W, USDC, BTC, 10_000_000, 9, 30, ALLOWED)
    pre, post = _states(sol_after=1_000_000_000 - 900_000,
                        extra_post={X.ata(W, BTC): tacc(BTC, W, 20)})
    with pytest.raises(G.Refused, match="SOL fell"):
        G.check_effect(pb, pre, post, 34_000)
    pre, post = _states(sol_after=1_000_000_000 - 34_000, extra_post={X.ata(W, BTC): tacc(BTC, W, 20)})
    assert G.check_effect(pb, pre, post, 34_000)["tok"][X.ata(W, BTC)] == 13


def test_check_effect_counts_the_rent_of_a_new_output_account():
    pb = G.Plan(W, USDC, BTC, 10_000_000, 9, 30, ALLOWED)
    pre, post = _states(extra_pre={X.ata(W, BTC): None},
                        extra_post={X.ata(W, BTC): tacc(BTC, W, 10)},
                        sol_after=1_000_000_000 - 34_000 - G.ATA_RENT_L)
    assert G.check_effect(pb, pre, post, 34_000)["created"] == 1


# ---------------------------------------------------------------- Jupiter's IDL

def jup_idl() -> dict:
    def ix(name, accounts, head):
        args = head + [{"name": "in_amount", "type": "u64"}, {"name": "quoted_out_amount", "type": "u64"},
                       {"name": "slippage_bps", "type": "u16"}, {"name": "platform_fee_bps", "type": "u16"},
                       {"name": "positive_slippage_bps", "type": "u16"},
                       {"name": "route_plan", "type": {"vec": {"defined": {"name": "RoutePlanStepV2"}}}}]
        return {"name": name, "discriminator": list(X.discriminator(name)),
                "accounts": [{"name": a, "writable": True} for a in accounts], "args": args}
    return {"instructions": [ix("route_v2", G.DEFAULT_ACCOUNTS["route_v2"], []),
                             ix("shared_accounts_route_v2", G.DEFAULT_ACCOUNTS["shared_accounts_route_v2"],
                                [{"name": "id", "type": "u8"}])]}


def test_the_idl_check_and_the_argument_offsets_from_it():
    doc = jup_idl()
    assert G.check_idl(doc) == []
    j = G.JupIdl(doc)
    assert j.args("shared_accounts_route_v2")["in_amount"] == (9, 8) and j.args("route_v2")["platform_fee_bps"] == (26, 2)
    G.check_message(plan(), message(good_ixs()), j, sender_tip_ok=True)
    assert G.check_idl(None)
    bad = jup_idl()
    bad["instructions"][0]["args"].insert(0, {"name": "route_plan", "type": {"vec": "u8"}})   # amounts after a vec
    assert any("fixed place" in w for w in G.check_idl(bad))
    bad = jup_idl()
    bad["instructions"][1]["discriminator"] = [0] * 8
    assert any("discriminator" in w for w in G.check_idl(bad))
    bad = jup_idl()
    bad["instructions"][0]["accounts"] = [{"name": "program"}]
    assert any("no signer" in w for w in G.check_idl(bad))


# ---------------------------------------------------------------- the build answer

def build_answer(in_mint=USDC, out_mint=SOL, amount=10_000_000, out=100_000_000, slip=30, route=None, extra=None):
    def enc(ix):
        return {"programId": ix.program, "data": base64.b64encode(ix.data).decode(),
                "accounts": [{"pubkey": k, "isSigner": s, "isWritable": w} for k, s, w in ix.accounts]}
    ixs = good_ixs(in_mint, out_mint, amount=amount, quoted=out, slip=slip, tip=0)
    setup = [ix for ix in ixs if ix.program in (X.ATA_PROGRAM, X.SYSTEM) or ix.data == b"\x11"]
    cleanup = [ix for ix in ixs if ix.program == X.TOKEN and ix.data == b"\x09"]
    d = {"quote": {"inputMint": in_mint, "inAmount": str(amount), "outputMint": out_mint, "outAmount": str(out),
                   "otherAmountThreshold": str(G.min_out(out, slip)), "slippageBps": slip, "swapMode": "ExactIn",
                   "priceImpactPct": "0.0001",
                   "routePlan": route or [{"percent": 100, "swapInfo": {"label": "Whirlpool", "inputMint": in_mint,
                                                                         "outputMint": out_mint, "inAmount": str(amount),
                                                                         "outAmount": str(out)}}]},
         "computeBudgetInstructions": [enc(X.compute_price(80_000))],
         "setupInstructions": [enc(ix) for ix in setup],
         "swapInstruction": enc(next(ix for ix in ixs if ix.program == G.JUPITER)),
         "cleanupInstruction": enc(cleanup[0]) if cleanup else None, "otherInstructions": [],
         "addressesByLookupTableAddress": {TABLE: ["ignored, read from the chain"]}}
    d.update(extra or {})
    return d


def test_parse_build_takes_instructions_and_only_the_table_addresses():
    b = S.parse_build(build_answer())
    assert b.in_amount == 10_000_000 and b.out_amount == 100_000_000 and b.threshold == G.min_out(100_000_000, 30)
    assert b.tables == [TABLE] and b.cu_price == 80_000 and b.swap.program == G.JUPITER
    assert b.route_mints == [USDC, SOL] and b.labels == ["Whirlpool"]
    assert [ix.program for ix in b.ixs()][-2:] == [G.JUPITER, X.TOKEN]      # the swap, then closing our wrapped SOL
    with pytest.raises(QuoteError, match="other or tip"):
        S.parse_build(build_answer(extra={"otherInstructions": [build_answer()["swapInstruction"]]}))
    with pytest.raises(QuoteError, match="no swap"):
        S.parse_build(build_answer(extra={"swapInstruction": None}))
    with pytest.raises(QuoteError, match="ExactIn"):
        a = build_answer()
        a["quote"]["swapMode"] = "ExactOut"
        S.parse_build(a)


def test_build_checks_the_answer_is_the_swap_asked_for_and_sends_the_key_as_a_header():
    seen = []

    def fetch(url, timeout, headers=None):
        seen.append((url, headers))
        return 200, {}, json.dumps(build_answer()).encode()
    jup = S.client({S.ENV_KEY: "k-123"}, fetch=fetch, sleep=lambda s: None)
    assert jup.base == S.KEYED_BASE
    b = S.build(jup, USDC, SOL, 10_000_000, W, 30)
    assert b.out_amount == 100_000_000
    assert "/swap/v2/build?" in seen[0][0] and f"taker={W}" in seen[0][0] and "k-123" not in seen[0][0]
    assert seen[0][1] == {"x-api-key": "k-123"}
    with pytest.raises(QuoteError, match="not the swap asked for"):
        S.build(jup, USDC, SOL, 9_000_000, W, 30)
    with pytest.raises(QuoteError, match="more slippage"):
        S.build(jup, USDC, SOL, 10_000_000, W, 10)
    assert S.client({}).base == S.KEYLESS_BASE


# ---------------------------------------------------------------- the ack and the gate

ACK = """mode=test
books=onchain_breakout_top10_live
mints=SOL,USDC,BTC,ETH
book_usd=150
max_total_usd=200
max_trade_usd=100
max_daily_loss_usd=30
max_convert_usd=100
expires=2026-12-31
I accept that I can lose all of it
"""
TODAY = dt.date(2026, 10, 23)


def test_the_ack_reads_and_refuses_above_the_hard_maxima(tmp_path):
    p = tmp_path / "ack"
    p.write_text(ACK)
    a = LG.read_ack(p, TODAY)
    assert a.problems == () and a.mode == "test" and a.mints == ("SOL", "USDC", "BTC", "ETH")
    assert (a.max_total_usd, a.max_trade_usd, a.max_daily_loss_usd, a.max_convert_usd, a.book_usd) == (200, 100, 30, 100, 150)
    assert a.allowed_mints() == {SOL, USDC, BTC, M.COINS["ETH"].mint} and a.on_kill == "hold"
    for line, why in [("max_total_usd=501", "hard maximum 500"), ("max_trade_usd=101", "hard maximum 100"),
                      ("max_daily_loss_usd=150", "hard maximum 100"), ("max_convert_usd=251", "hard maximum 250"),
                      ("max_trade_usd=-1", "above 0"), ("mints=SOL,DOGE", "DOGE is not on the stage-2 list"),
                      ("book_usd=300", "book_usd is above"), ("expires=2026-10-01", "expired"),
                      ("expires=2027-06-01", "90 days"), ("on_kill=burn", "on_kill")]:
        key = line.split("=")[0]
        p.write_text("\n".join(x for x in ACK.splitlines() if not x.startswith(key + "=")) + "\n" + line + "\n")
        assert any(why in w for w in LG.read_ack(p, TODAY).problems), line
    p.write_text(ACK.replace("I accept that I can lose all of it\n", ""))
    assert any("lacks the line" in w for w in LG.read_ack(p, TODAY).problems)
    p.write_text(ACK.replace("mode=test", "mode=full"))
    assert "mode must be test" in LG.read_ack(p, TODAY).problems[0]
    assert "no owner confirmation" in LG.read_ack(tmp_path / "none", TODAY).problems[0]


def armed(tmp_path, **env_over):
    """Everything the gate needs, in tmp_path: ack, wallet file and .pub, IDL, a fresh simulation."""
    (tmp_path / "ack").write_text(ACK)
    kp = tmp_path / "etc" / "onchain-keypair.json"
    kp.parent.mkdir(exist_ok=True)
    kp.write_text("[]")
    os.chmod(kp, 0o600)
    (tmp_path / "etc" / "onchain-keypair.json.pub").write_text(W + "\n")
    (tmp_path / "jupiter.json").write_text(json.dumps(jup_idl()))
    now = int(dt.datetime(2026, 10, 23, 12, tzinfo=dt.timezone.utc).timestamp() * 1000)
    (tmp_path / "sim.json").write_text(json.dumps({"t": now - 3_600_000, "ok": True, "pubkey": W}))
    (tmp_path / "pin.json").write_text(json.dumps(PIN))
    env = {LG.ENV_LIVE: "1", LG.ENV_KEYPAIR: str(kp), **env_over}
    return LG.Gate(ack_path=tmp_path / "ack", env=env, kill=lambda: False, now_ms=lambda: now,
                   idl_file=tmp_path / "jupiter.json", simulate_file=tmp_path / "sim.json",
                   pumpfun_wallet_json=tmp_path / "pf_wallet.json", pin_file=tmp_path / "pin.json")


def test_the_gate_opens_only_when_every_condition_holds(tmp_path):
    g = armed(tmp_path)
    assert g.check() == [] and g.address == W and g.ack.mode == "test"
    g.env[LG.ENV_LIVE] = "0"
    assert any("PYTHIA_ONCHAIN_LIVE" in w for w in g.check())
    g = armed(tmp_path)
    g.kill = lambda: True
    assert "the kill switch file is there" in g.check()
    g = armed(tmp_path)
    (tmp_path / "sim.json").write_text(json.dumps({"t": 0, "ok": True, "pubkey": W}))
    assert any("simulation is" in w for w in g.check())
    g = armed(tmp_path)
    (tmp_path / "sim.json").write_text(json.dumps({"t": g.now_ms(), "ok": True, "pubkey": OTHER}))
    assert any("another wallet" in w for w in g.check())
    g = armed(tmp_path)
    (tmp_path / "jupiter.json").unlink()
    assert any("Jupiter IDL" in w for w in g.check())
    g = armed(tmp_path)
    os.chmod(tmp_path / "etc" / "onchain-keypair.json", 0o644)
    assert any("chmod 600" in w for w in g.check())
    g = armed(tmp_path, PYTHIA_ONCHAIN_RPC="http://plain.example/")
    assert any("https" in w for w in g.check())
    g = armed(tmp_path, PYTHIA_ONCHAIN_SENDER="https://x-sender.helius-rpc.com/fast?swqos_only=true")
    assert any("mev-protect" in w for w in g.check())
    g = armed(tmp_path, PYTHIA_ONCHAIN_SENDER="https://x-sender.helius-rpc.com/fast?swqos_only=true&mev-protect=true")
    assert any("no Sender tip" in w for w in g.check())          # the simulation must have carried the tip


def test_the_gate_refuses_the_pump_fun_wallet(tmp_path):
    g = armed(tmp_path)
    (tmp_path / "pf_wallet.json").write_text(json.dumps({"address": W}))
    assert any("pump.fun wallet's address" in w for w in g.check())
    g = armed(tmp_path)
    g.env["PYTHIA_PUMPFUN_KEYPAIR"] = g.env[LG.ENV_KEYPAIR]
    assert any("is the pump.fun wallet file" in w for w in g.check())


def test_book_problems_need_the_ack_and_the_passed_proof():
    a = LG.Ack(mode="test", books=("onchain_breakout_top10_live",), mints=("SOL", "USDC"))
    name = "onchain_breakout_top10_live"
    assert any("no proof report" in w for w in LG.book_problems(name, a, None, NOW))
    proof = {"updated_ms": NOW - 3_600_000, "books": {name: {"passed": True}}}
    assert LG.book_problems(name, a, proof, NOW) == []
    assert any("has not passed" in w for w in LG.book_problems(name, a, {**proof, "books": {name: {"passed": "yes"}}}, NOW))
    assert any("older than 36 h" in w for w in LG.book_problems(name, a, {**proof, "updated_ms": 0}, NOW))
    assert any("does not name" in w for w in LG.book_problems(name, LG.Ack(mode="test"), proof, NOW))


def test_the_wallet_tool_refuses_the_pump_fun_file_and_publishes_to_its_own_folder(tmp_path, monkeypatch):
    said = []
    assert OW.cmd_new(tmp_path / "pumpfun-keypair.json", say=said.append) == 1 and "pump.fun" in said[0]
    monkeypatch.setattr(LG, "reports_dir", lambda: tmp_path / "reports" / "onchain_live")
    got = {}

    def fake_new(out, say=print, publish=None, **kw):
        got["out"], got["published"] = out, publish(W, 5)
        return 0
    monkeypatch.setattr(OW.W, "cmd_new", fake_new)
    assert OW.cmd_new(tmp_path / "onchain-keypair.json") == 0
    assert json.loads((tmp_path / "reports" / "onchain_live" / "wallet.json").read_text())["address"] == W


# ---------------------------------------------------------------- a fake chain for the executor

PRICES = {USDC: 1.0, SOL: 0.1 * 1e9 / 1e9 * 1000 / 10, BTC: 100_000.0, M.COINS["ETH"].mint: 4_000.0}
# SOL at 10 USD: 10 USDC buy 1 SOL; the quotes below give 0.999 SOL


def alt_data(keys):
    return struct.pack("<IQQB", 1, 2 ** 64 - 1, 5, 0) + b"\x00" * 35 + b"".join(X.key(k) for k in keys)


def b64acc(a: G.Account | None):
    if a is None:
        return None
    return {"lamports": a.lamports, "owner": a.owner, "data": [base64.b64encode(a.data).decode(), "base64"],
            "executable": False}


class FakeChain:
    """getMultipleAccounts over a dict, simulateTransaction applying the planned swap, sends recorded,
    statuses after `land_after` sends, getTransaction with the wallet's balances."""

    def __init__(self, usdc=50_000_000, sol=1_000_000_000, out_raw=999_000_000, sim_err=None, land_after=1,
                 drain=False, never_land=False):
        self.acc = {W: G.Account(sol, X.SYSTEM, b""), X.ata(W, USDC): tacc(USDC, W, usdc),
                    TABLE: G.Account(1, T.ALT_PROGRAM, alt_data(POOL)),
                    USDC: G.Account(1, X.TOKEN, b"\x00" * 82), SOL: G.Account(1, X.TOKEN, b"\x00" * 82),
                    BTC: G.Account(1, X.TOKEN, b"\x00" * 82), X.ata(W, BTC): tacc(BTC, W, 1_000),
                    G.JUPITER: G.Account(1, G.UPGRADEABLE_LOADER, struct.pack("<I", 2) + X.key(JUP_DATA)),
                    JUP_DATA: G.Account(1, G.UPGRADEABLE_LOADER, struct.pack("<IQ", 3, JUP_SLOT) + b"\x00")}
        for k in POOL:
            self.acc[k] = G.Account(1, DEX, b"pool")
        self.out_raw, self.sim_err, self.land_after, self.drain, self.never_land = out_raw, sim_err, land_after, drain, never_land
        self.sent: list[bytes] = []
        self.sims = 0
        self.height = 100
        self.calls: list[str] = []

    def __call__(self, method, params):
        self.calls.append(method)
        if method == "getMultipleAccounts":
            return {"result": {"value": [b64acc(self.acc.get(k)) for k in params[0]]}}
        if method == "getTokenAccountsByOwner":
            if params[1]["programId"] != X.TOKEN:
                return {"result": {"value": []}}
            return {"result": {"value": [{"pubkey": k, "account": b64acc(a)} for k, a in self.acc.items()
                                         if a and a.owner == X.TOKEN and len(a.data) == 165
                                         and G.parse_token(a.data).owner == W]}}
        if method == "getBalance":
            return {"result": {"value": self.acc[W].lamports}}
        if method == "getLatestBlockhash":
            return {"result": {"value": {"blockhash": A("blockhash"), "lastValidBlockHeight": 150}}}
        if method == "getBlockHeight":
            self.height += 30
            return {"result": self.height}
        if method == "simulateTransaction":
            self.sims += 1
            if self.sim_err:
                return {"result": {"value": {"err": self.sim_err, "logs": ["Program log: Error: slippage"]}}}
            addrs = params[1]["accounts"]["addresses"]
            post = dict(self.acc)
            src = X.ata(W, USDC)
            t = G.parse_token(post[src].data)
            post[src] = tacc(USDC, W, t.amount - 10_000_000)
            post[W] = G.Account(self.acc[W].lamports + self.out_raw - 40_000, X.SYSTEM, b"")
            if self.drain:
                post[X.ata(W, BTC)] = tacc(BTC, W, 0)
            return {"result": {"value": {"err": None, "unitsConsumed": 200_000,
                                         "accounts": [b64acc(post.get(k)) for k in addrs]}}}
        if method == "sendTransaction":
            raw = base64.b64decode(params[0])
            self.sent.append(raw)
            return {"result": b58(raw[1:65])}
        if method == "getSignatureStatuses":
            landed = len(self.sent) >= self.land_after and not self.never_land
            return {"result": {"value": [{"confirmationStatus": "confirmed", "err": None} if landed else None]}}
        if method == "getTransaction":
            return {"result": {"blockTime": 1_792_712_000, "transaction": {"message": {"accountKeys": [W]}},
                               "meta": {"err": None, "fee": 40_000, "preBalances": [1_000_000_000],
                                        "postBalances": [1_000_000_000 + self.out_raw - 40_000],
                                        "preTokenBalances": [{"mint": USDC, "owner": W,
                                                              "uiTokenAmount": {"amount": "50000000"}}],
                                        "postTokenBalances": [{"mint": USDC, "owner": W,
                                                               "uiTokenAmount": {"amount": "40000000"}}]}}}
        raise AssertionError(method)


class FakeSigner:
    pubkey = W

    def __init__(self):
        self.signed: list[bytes] = []

    def sign(self, message: bytes) -> bytes:
        self.signed.append(message)
        return hashlib.sha512(message).digest()


def trader(tmp_path, monkeypatch, chain=None, answer=None, signer=True, kraken=10.0):
    monkeypatch.setattr(LG, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(LG, "reports_dir", lambda: tmp_path / "reports")
    monkeypatch.setattr(LG, "kill_paths", lambda: [tmp_path / "KILL"])
    g = armed(tmp_path)
    assert g.check() == []
    fc = chain or FakeChain()
    from lab.pumpfun_rt import live_exec as PX
    rpc = PX.Rpc("https://rpc.example.org", poster=fc)
    jup = Jupiter(base="https://jup.example.org", min_interval=0, sleep=lambda s: None,
                  fetch=lambda url, timeout: (200, {}, json.dumps(answer or build_answer(out=999_000_000)).encode()))
    prices = {USDC: 1.0, SOL: 10.0, BTC: 100_000.0, M.COINS["ETH"].mint: 4_000.0}
    tr = LX.Trader(g, LX.Chain(rpc), jup, signer=FakeSigner() if signer else None, prices=lambda mints: prices,
                   kraken=lambda code: {"USDC": 1.0, "SOL": kraken, "BTC": 100_000.0, "ETH": 4_000.0}.get(code),
                   clock=iter(range(0, 10 ** 6)).__next__, sleep=lambda s: None)
    return tr, fc


def view(tr):
    return LX.read_view(tr.chain, W, tr.prices_of)


def test_execute_builds_guards_simulates_signs_sends_and_books_from_the_chain(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)
    v = view(tr)
    assert v.held("USDC") == 50_000_000 and v.total_usd() == pytest.approx(50 + 10 + 1)
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000, ref="c1"), v)
    assert r["status"] == "filled" and r["out_raw"] == 999_000_000 - 0
    assert fc.sims == 2                                     # guarded and simulated again with the measured units
    assert len(tr.signer.signed) == 1 and fc.sent and fc.sent[0][65:] == tr.signer.signed[0]
    msg = T.decompile(tr.signer.signed[0], {TABLE: POOL})
    assert msg.ixs[0].data == X.compute_limit(250_000).data       # 1.2 x 200,000 + 10,000
    rows = LX.read_ledger()
    assert len(rows) == 1 and rows[0]["status"] == "filled" and rows[0]["in_raw"] == "10000000"
    assert rows[0]["sol_delta_l"] == str(999_000_000 - 40_000) and rows[0]["fee_l"] == "40000" and rows[0]["unread"] == ""
    whats = [o["what"] for o in LX._read_jsonl(LX.orders_path())]
    assert whats == ["planned", "sent", "filled"]
    day = LX.realised(LX.day_of(LX.now_ms()))
    assert day["converts"] == 1 and day["convert_usd"] == pytest.approx(10.0)


def test_a_guard_refusal_signs_and_sends_nothing(tmp_path, monkeypatch):
    evil = build_answer(out=999_000_000)
    evil["setupInstructions"].append({"programId": X.SYSTEM, "data": base64.b64encode(struct.pack("<IQ", 2, 10 ** 9)).decode(),
                                      "accounts": [{"pubkey": W, "isSigner": True, "isWritable": True},
                                                   {"pubkey": OTHER, "isSigner": False, "isWritable": True}]})
    tr, fc = trader(tmp_path, monkeypatch, answer=evil)
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "refused" and "transfer out" in r["why"]
    assert not tr.signer.signed and not fc.sent and fc.sims == 0 and LX.read_ledger() == []


def test_a_simulation_that_drains_another_account_or_fails_sends_nothing(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(drain=True))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "refused" and "another token account of ours fell" in r["why"] and not fc.sent
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(sim_err={"InstructionError": [3, "Custom"]}))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "refused" and "simulation failed" in r["why"] and not fc.sent


def test_prices_cost_and_route_are_checked_before_anything_is_built(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, kraken=11.0)            # Jupiter's SOL 10 % off Kraken's
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "refused" and "Kraken" in r["why"] and fc.sims == 0
    tr, fc = trader(tmp_path, monkeypatch, answer=build_answer(out=900_000_000))   # 10 % worse than the price
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "refused" and "bps" in r["why"] and fc.sims == 0
    hop = [{"percent": 100, "swapInfo": {"inputMint": USDC, "outputMint": A("unknown mint")}},
           {"percent": 100, "swapInfo": {"inputMint": A("unknown mint"), "outputMint": SOL}}]
    tr, fc = trader(tmp_path, monkeypatch, answer=build_answer(out=999_000_000, route=hop))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "refused" and "route list" in r["why"]


def test_a_confirmed_minimum_binds_the_new_quote(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000, min_out_raw=999_000_000), view(tr))
    assert r["status"] == "refused" and "worse than the confirmed minimum" in r["why"] and not fc.sent


def test_an_expired_blockhash_gets_a_new_quote_at_most_three_times(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(never_land=True))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))
    assert r["status"] == "failed" and "3 tries" in r["why"]
    whats = [o["what"] for o in LX._read_jsonl(LX.orders_path())]
    assert whats.count("expired") == 3 and whats.count("sent") == 3 and len(tr.signer.signed) == 3
    assert LX.read_ledger() == []


def test_no_signer_means_nothing_is_ever_sent(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, signer=False)
    assert tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))["status"] == "refused"
    assert not fc.sent
    p = tr.prepare(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr))   # the dry run still works
    assert p.plan.min_out_raw == G.min_out(999_000_000, 30) and p.units == 200_000 and not fc.sent


# ---------------------------------------------------------------- the caps

def test_the_caps(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)                  # 50 USDC, 1 SOL, 0.00001 cbBTC: 61 USD
    v = view(tr)
    ok = LX.Swap("convert", "USDC", "SOL", 10_000_000)
    assert tr.caps(ok, v, killed=False) is None
    assert "kill switch" in tr.caps(ok, v, killed=True)
    assert "not among" in tr.caps(LX.Swap("convert", "USDC", "JUP", 10_000_000), v, killed=False)
    assert "holds less" in tr.caps(LX.Swap("convert", "USDC", "SOL", 60_000_000), v, killed=False)
    assert "does not name" in tr.caps(LX.Swap("book", "SOL", "USDC", 100_000_000, book="other"), v, killed=False)
    assert "unknown kind" in tr.caps(LX.Swap("x", "SOL", "USDC", 100_000_000), v, killed=False)
    assert "kill sale without" in tr.caps(LX.Swap("kill", "SOL", "USDC", 100_000_000), v, killed=False)
    assert "a swap between two coins" in tr.caps(LX.Swap("convert", "USDC", "USDC", 1), v, killed=False)
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(usdc=400_000_000, sol=30_000_000_000))
    v = view(tr)                                            # 400 + 300 + 0.1 USD, above max_total_usd 200
    assert "above the 100 USD" in tr.caps(LX.Swap("convert", "USDC", "SOL", 150_000_000), v, killed=False)
    assert "only sales into USDC" in tr.caps(ok, v, killed=False)
    assert tr.caps(LX.Swap("convert", "SOL", "USDC", 1_000_000_000), v, killed=False) is None
    kill_sale = LX.Swap("kill", "SOL", "USDC", 1_000_000_000)
    assert "kill switch" in tr.caps(kill_sale, v, killed=True)                  # on_kill=hold
    tr.gate.ack = LG.Ack(**{**tr.gate.ack.__dict__, "on_kill": "usdc"})
    assert tr.caps(kill_sale, v, killed=True) is None
    assert "kill switch" in tr.caps(LX.Swap("convert", "SOL", "USDC", 1_000_000_000), v, killed=True)
    assert "kill switch" in tr.caps(LX.Swap("kill", "USDC", "SOL", 10_000_000), v, killed=True)


def test_the_daily_loss_reserve_eth_and_ledger_caps(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(usdc=50_000_000, sol=1_000_000_000))
    v = view(tr)
    buy = LX.Swap("convert", "USDC", "SOL", 10_000_000)
    LX.day_start_usd(v, 200.0)                              # the day began at 200 USD, the wallet is worth 61
    assert "day's loss" in tr.caps(buy, v, killed=False)
    assert tr.caps(LX.Swap("convert", "SOL", "USDC", 100_000_000), v, killed=False) is None    # sales go on
    (tmp_path / "live" / "days.json").unlink()
    assert tr.caps(buy, v, killed=False) is None
    tr.reconciled = {"ok": False}
    assert "does not match the chain" in tr.caps(buy, v, killed=False)
    tr.reconciled = {"ok": True}
    assert "SOL reserve" in tr.caps(LX.Swap("convert", "SOL", "USDC", 990_000_000), v, killed=False)
    v.prices[M.COINS["ETH"].mint] = 4_000.0
    v.tokens[M.COINS["ETH"].mint] = 1_200_000            # 0.012 WETH, 48 USD already
    assert "quarter" in tr.caps(LX.Swap("convert", "USDC", "ETH", 5_000_000), v, killed=False)


def test_converts_per_day_and_their_usd_limit(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)
    v = view(tr)
    for i in range(LG.MAX_CONVERTS_DAY):
        LX.write_row({"t": LX.now_ms(), "kind": "convert", "from": "USDC", "to": "SOL", "in_usd": 1.0, "status": "filled"})
    assert "already 10 converts" in tr.caps(LX.Swap("convert", "USDC", "SOL", 1_000_000), v, killed=False)
    (tmp_path / "live" / "ledger.csv").unlink()
    LX.write_row({"t": LX.now_ms(), "kind": "convert", "from": "USDC", "to": "SOL", "in_usd": 95.0, "status": "filled"})
    assert "convert limit" in tr.caps(LX.Swap("convert", "USDC", "SOL", 10_000_000), v, killed=False)


# ---------------------------------------------------------------- the journal and the reconciliation

def test_reconcile_books_deposits_and_stops_buys_on_an_unexplained_fall(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)
    v = view(tr)
    assert LX.reconcile(v)["ok"]                            # the first look is the baseline
    assert [j["kind"] for j in LX.read_journal()] == ["baseline"]
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), v)
    assert r["status"] == "filled"
    fc.acc[W] = G.Account(1_000_000_000 + 999_000_000 - 40_000, X.SYSTEM, b"")
    fc.acc[X.ata(W, USDC)] = tacc(USDC, W, 40_000_000)
    v = view(tr)
    assert LX.reconcile(v) == {"t": v.t, "ok": True, "diffs": []}
    fc.acc[X.ata(W, USDC)] = tacc(USDC, W, 140_000_000)     # the owner sent 100 USDC
    rec = LX.reconcile(view(tr))
    assert rec["ok"] and [j for j in LX.read_journal() if j["kind"] == "deposit"][0]["raw"] == 100_000_000
    assert LX.reconcile(view(tr))["ok"]                     # booked once
    fc.acc[X.ata(W, BTC)] = tacc(BTC, W, 0)                 # cbBTC gone without a swap of ours
    rec = LX.reconcile(view(tr))
    assert not rec["ok"] and "BTC" in rec["diffs"][0]
    assert not LX.reconcile(view(tr))["ok"]                 # stays shut until the next start
    tr.reconciled = rec
    assert "does not match" in tr.caps(LX.Swap("convert", "USDC", "SOL", 10_000_000), view(tr), killed=False)
    assert tr.caps(LX.Swap("convert", "SOL", "USDC", 100_000_000), view(tr), killed=False) is None


def test_an_unread_row_is_read_again_and_waits_for_the_reconciliation(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)
    v = view(tr)
    LX.baseline(v)
    LX.write_row({"t": LX.now_ms() + 1, "kind": "convert", "from": "USDC", "to": "SOL", "in_raw": 10_000_000,
                  "status": "filled", "sig": A("sig"), "unread": "1"})
    assert LX.reconcile(v).get("pending")
    assert tr.reread() == 1
    row = LX.read_ledger()[0]
    assert row["unread"] == "" and row["out_raw"] == str(999_000_000) and row["fee_l"] == "40000"


# ---------------------------------------------------------------- a book's swaps

def test_book_swaps_sell_first_buy_from_the_books_cash_and_respect_the_wallet(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch, chain=FakeChain(usdc=150_000_000))
    ack = tr.gate.ack                                       # book_usd 150, mints SOL USDC BTC ETH
    v = view(tr)
    swaps = LX.book_swaps("onchain_breakout_top10_live", ack, v, {"SOL": 0.5, "DOGE": 0.3, "JUP": 0.2})
    assert [(s.src, s.dst, s.in_raw) for s in swaps] == [("USDC", "SOL", 75_000_000)]   # JUP not allowed, DOGE cash
    LX.write_row({"t": 1, "kind": "book", "book": "onchain_breakout_top10_live", "from": "USDC", "to": "SOL",
                  "in_raw": 75_000_000, "out_raw": 7_500_000_000, "status": "filled"})
    st = LX.book_state("onchain_breakout_top10_live", 150)
    assert st == {"usdc_raw": 75_000_000, "units": {"SOL": 7_500_000_000}}
    fc.acc[W] = G.Account(1_000_000_000, X.SYSTEM, b"")      # the wallet holds only 1 SOL of the book's 7.5
    swaps = LX.book_swaps("onchain_breakout_top10_live", ack, view(tr), {})
    assert [(s.src, s.dst, s.in_raw) for s in swaps] == [("SOL", "USDC", 1_000_000_000)]


# ---------------------------------------------------------------- the service: status and converts

def service(tmp_path, monkeypatch, **kw):
    tr, fc = trader(tmp_path, monkeypatch, **kw)
    svc = SV.Service(gate=tr.gate, trader=tr, load=lambda p: tr.signer, alerts=False)
    svc.start()
    return svc, tr, fc


def test_the_status_file_has_what_the_app_reads(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    assert svc.on and [j["kind"] for j in LX.read_journal()] == ["baseline"]
    svc.write_status()
    st = json.loads((tmp_path / "reports" / "status.json").read_text())
    for k in ("t", "running", "on", "mode", "gate", "address", "sol_lamports", "balances", "total_usd", "day", "ack",
              "hard", "limits", "coins", "kill", "simulate", "books", "reconcile", "stops"):
        assert k in st, k
    assert st["on"] and st["address"] == W and st["hard"]["max_total_usd"] == 500
    assert {b["coin"] for b in st["balances"]} == {"SOL", "USDC", "BTC"}
    assert [c["coin"] for c in st["coins"] if c["allowed"]] == ["USDC", "SOL", "BTC", "ETH"]
    assert json.loads((tmp_path / "reports" / "trades.json").read_text()) == {"trades": []}


def test_a_shut_gate_writes_why_and_swaps_nothing(tmp_path, monkeypatch):
    tr, fc = trader(tmp_path, monkeypatch)
    tr.gate.env[LG.ENV_LIVE] = "0"
    svc = SV.Service(gate=tr.gate, trader=tr, load=lambda p: pytest.fail("the wallet file must not be read"),
                     alerts=False)
    svc.start()
    assert not svc.on and any("PYTHIA_ONCHAIN_LIVE" in w for w in svc.status()["gate"])


def write_req(tmp_path, cid, **kw):
    d = tmp_path / "reports" / "convert"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{cid}.request.json").write_text(json.dumps({"id": cid, "from": "USDC", "to": "SOL", "amount": 10.0,
                                                       "t": LX.now_ms(), **kw}))
    return d


def test_a_convert_goes_request_proposal_confirm_result(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    cid = "c1792712000000-ab12"
    d = write_req(tmp_path, cid)
    svc.converts()
    prop = json.loads((d / f"{cid}.proposal.json").read_text())
    assert prop["status"] == "proposed" and prop["min_out_raw"] == str(G.min_out(999_000_000, 30))
    assert prop["expires_ms"] - prop["t"] == 60_000 and prop["expected_out"] == pytest.approx(0.999)
    assert not fc.sent
    svc.converts()                                          # nothing happens without a confirm
    assert not fc.sent and not (d / f"{cid}.result.json").exists()
    (d / f"{cid}.confirm.json").write_text(json.dumps({"id": cid, "proposal_t": prop["t"],
                                                       "min_out_raw": prop["min_out_raw"], "t": prop["t"] + 5_000}))
    svc.converts()
    res = json.loads((d / f"{cid}.result.json").read_text())
    assert res["status"] == "filled" and res["out_amount"] == pytest.approx(0.999) and len(fc.sent) == 1
    svc.converts()
    assert len(fc.sent) == 1                                # done once
    svc.write_status()
    t = json.loads((tmp_path / "reports" / "trades.json").read_text())["trades"]
    assert t[0]["kind"] == "convert" and t[0]["in_amount"] == 10.0 and t[0]["status"] == "filled"


def test_a_convert_confirmed_late_or_for_another_proposal_never_swaps(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    for cid, conf in [("c1792712000000-0001", lambda p: {"id": "c1792712000000-0001", "proposal_t": p["t"] - 1,
                                                         "min_out_raw": p["min_out_raw"], "t": p["t"]}),
                      ("c1792712000000-0002", lambda p: {"id": "c1792712000000-0002", "proposal_t": p["t"],
                                                         "min_out_raw": "1", "t": p["t"]}),
                      ("c1792712000000-0003", lambda p: {"id": "c1792712000000-0003", "proposal_t": p["t"],
                                                         "min_out_raw": p["min_out_raw"], "t": p["t"] + 61_000})]:
        d = write_req(tmp_path, cid)
        svc.converts()
        p = json.loads((d / f"{cid}.proposal.json").read_text())
        (d / f"{cid}.confirm.json").write_text(json.dumps(conf(p)))
        svc.converts()
        assert json.loads((d / f"{cid}.result.json").read_text())["status"] in ("refused", "expired")
    assert not fc.sent


def test_a_convert_over_the_caps_or_while_off_is_refused_at_once(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    cid = "c1792712000000-00aa"
    d = write_req(tmp_path, cid, amount=500.0)
    svc.converts()
    assert json.loads((d / f"{cid}.proposal.json").read_text())["status"] == "refused"
    assert json.loads((d / f"{cid}.result.json").read_text())["status"] == "refused"
    write_req(tmp_path, "../../etc/x")                      # a bad id is never touched
    svc.on = False
    cid = "c1792712000000-00bb"
    d = write_req(tmp_path, cid)
    svc.converts()
    assert "off" in json.loads((d / f"{cid}.result.json").read_text())["why"] and not fc.sent


def test_books_trade_only_with_the_passed_proof(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    monkeypatch.setattr(LG, "proof_path", lambda: tmp_path / "proof.json")
    svc.run_books()
    assert svc.books[0]["allowed"] is False and "proof" in svc.books[0]["why"] and not fc.sent


def test_the_kill_switch_stops_converts_and_liquidates_only_with_on_kill_usdc(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    (tmp_path / "KILL").write_text("x")
    cid = "c1792712000000-0c0c"
    d = write_req(tmp_path, cid)
    svc.converts()
    assert "kill" in json.loads((d / f"{cid}.result.json").read_text())["why"]
    svc.liquidate()                                         # on_kill=hold: nothing
    assert not fc.sent and not svc.status()["on"]


def test_a_book_with_the_passed_proof_acts_once_per_signal(tmp_path, monkeypatch):
    svc, tr, fc = service(tmp_path, monkeypatch)
    name = "onchain_breakout_top10_live"
    monkeypatch.setattr(LG, "proof_path", lambda: tmp_path / "proof.json")
    (tmp_path / "proof.json").write_text(json.dumps({"updated_ms": LX.now_ms(), "books": {name: {"passed": True}}}))
    import lab.data
    monkeypatch.setattr(lab.data, "ROOT", tmp_path)
    sig = tmp_path / "signals" / "breakout_top10_live" / "latest.json"
    sig.parent.mkdir(parents=True)
    sig.write_text(json.dumps({"strategy": "breakout_top10_live", "as_of_ms": 1, "valid_until_ms": LX.now_ms() + 3_600_000,
                               "weights": {"SOL": 0.5}}))
    svc.run_books()
    assert svc.books == [{"book": name, "allowed": True, "why": None}]
    planned = [o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "planned"]
    assert len(planned) == 1 and planned[0]["kind"] == "book" and planned[0]["in_raw"] == 50_000_000   # the wallet's 50 USDC
    svc.run_books()                                         # the same signal: nothing again
    assert len([o for o in LX._read_jsonl(LX.orders_path()) if o["what"] == "planned"]) == 1
