"""The owner's live pump.fun test: the wallet tool, the test-mode gate, the limits the app may only
lower, the stops, the measurements, the simulation, the live service's status and the cards.

Temp folders only, fake signers and a mocked RPC: no network, no real key, nothing sent.

Run from research/lab:  python -m pytest tests/test_pumpfun_live.py
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

from lab.pumpfun_rt import curve as C
from lab.pumpfun_rt import live_exec as LX
from lab.pumpfun_rt import live_service as LS
from lab.pumpfun_rt import measure as MS
from lab.pumpfun_rt import pipeline as P
from lab.pumpfun_rt import sim
from lab.pumpfun_rt import tokens as T
from lab.pumpfun_rt import txbuild as X
from lab.pumpfun_rt import wallet as WT
from test_pumpfun_pipeline import FakeBuilder, FakeSigner, OpenGate, idl_docs, strat
from test_pumpfun_rt import BUYERS, MINT, POOL, SOL, T0, Curve, Fixed, key


@pytest.fixture(autouse=True)
def folders(monkeypatch, tmp_path):
    """Every file the live code writes stays in the test: data, reports, the kill paths."""
    from lab import report as rep
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path / "live")
    monkeypatch.setattr(rep, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(P, "kill_paths", lambda: [tmp_path / "etc-kill", tmp_path / "data-kill"])
    monkeypatch.setattr(LX, "crypto_ok", lambda: True)
    return tmp_path


def fake_keypair(seed: int = 7):
    """64 bytes in the wallet file's layout, made by the test (the tool's own maker is solders). A real
    pair when `cryptography` is installed, so the live signer can read it back; else stand-in bytes."""
    sk = bytes([seed]) * 32
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        pub = Ed25519PrivateKey.from_private_bytes(sk).public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    except ImportError:
        pub = bytes([seed + 100]) * 32
    return lambda: (sk + pub, X.b58(pub))


def private_folder(_p):
    import stat
    return stat.S_IFDIR | 0o700


# ---------------------------------------------------------------- the wallet tool

def test_the_wallet_tool_writes_a_private_file_and_shows_the_backup_once_after_yes(tmp_path):
    out = tmp_path / "etc" / "pumpfun-keypair.json"
    out.parent.mkdir()
    said = []
    make = fake_keypair()
    raw, pub = make()
    rc = WT.cmd_new(out, ask=lambda q: "YES", say=said.append, interactive=True, mode_of=private_folder,
                    posix=True, make=make, publish=lambda a: None)
    assert rc == 0
    assert json.loads(out.read_text()) == list(raw)
    if os.name == "posix":
        assert out.stat().st_mode & 0o777 == 0o600
    assert WT.address_path(out).read_text().strip() == pub
    text = "\n".join(said)
    assert pub in text and text.count(X.b58(raw)) == 1          # the backup, exactly once
    try:
        import cryptography  # noqa: F401
    except ImportError:
        return
    assert LX.load_signer(str(out)).pubkey == pub               # the live signer reads what the tool wrote


def test_the_backup_is_not_shown_without_yes_or_without_a_terminal(tmp_path):
    for k, (answer, interactive) in enumerate((("no", True), ("YES", False), ("yes please", True))):
        out = tmp_path / f"w{k}" / "kp.json"
        out.parent.mkdir()
        said = []
        make = fake_keypair(10 + k)
        raw, pub = make()
        assert WT.cmd_new(out, ask=lambda q: answer, say=said.append, interactive=interactive,
                          mode_of=private_folder, posix=True, make=make, publish=lambda a: None) == 0
        text = "\n".join(said)
        assert pub in text and X.b58(raw) not in text, (answer, interactive)
        assert out.exists()


def test_the_wallet_tool_never_overwrites_and_refuses_an_open_folder(tmp_path):
    out = tmp_path / "kp.json"
    out.write_text("[1]")
    said = []
    assert WT.cmd_new(out, ask=lambda q: "YES", say=said.append, interactive=True, mode_of=private_folder,
                      posix=True, make=fake_keypair(), publish=lambda a: None) == 1
    assert out.read_text() == "[1]" and "already exists" in said[0]
    import stat
    fresh = tmp_path / "open" / "kp.json"
    fresh.parent.mkdir()
    said = []
    assert WT.cmd_new(fresh, say=said.append, interactive=True, posix=True, make=fake_keypair(),
                      mode_of=lambda p: stat.S_IFDIR | 0o755, publish=lambda a: None) == 1
    assert "read or written by everyone" in said[0] and not fresh.exists()
    assert WT.folder_problems(tmp_path / "missing", posix=True)[0].startswith("the folder")
    assert any("code folder" in w for w in WT.folder_problems(Path(WT.__file__).parent, mode_of=private_folder,
                                                                posix=True))


def test_address_reads_only_the_public_file(tmp_path):
    kp = tmp_path / "kp.json"                                  # no keypair file at all: address never opens it
    WT.address_path(kp).write_text(key(77) + "\n")
    said = []
    assert WT.cmd_address(kp, say=said.append) == 0 and said == [key(77)]
    assert WT.cmd_address(tmp_path / "other.json", say=said.append) == 1


def test_the_tool_publishes_the_public_address_for_the_app(folders):
    p = WT.publish_address(key(77), now_ms=T0)
    assert json.loads(p.read_text()) == {"address": key(77), "created_ms": T0}


def test_a_real_solders_keypair_has_the_signers_layout():
    pytest.importorskip("solders")
    raw, pub = WT.new_keypair()
    assert len(raw) == 64 and X.b58(raw[32:]) == pub


def test_only_the_wallet_tool_makes_a_key():
    root = Path(WT.__file__).resolve().parents[1]
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        if p.name == "wallet.py" and p.parent.name == "pumpfun_rt":
            assert "Keypair()" in src
            continue
        for w in ("Keypair()", "Ed25519PrivateKey.generate", "solders"):
            assert w not in src, f"{p}: {w}"


def test_nothing_transfers_or_withdraws():
    root = Path(WT.__file__).resolve().parents[1]
    for p in root.rglob("*.py"):
        src = p.read_text(encoding="utf-8").lower()
        for w in ("def withdraw", "def transfer", "transfer_sol", "def send_sol"):
            assert w not in src, f"{p}: {w}"


# ---------------------------------------------------------------- what a transaction may contain

def test_check_own_refuses_anything_but_a_plain_trade():
    user = key(77)
    p = X.PoolInfo(key(60), MINT, X.WSOL, key(61), key(62), X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[0])
    X.check_own(user, X.amm_buy(user, p, 5_000, 1_000, 1_000))
    X.check_own(user, X.amm_sell(user, p, 1_000, 0, 1_000, True))
    X.check_own(user, X.round_trip(X.amm_buy(user, p, 5_000, 1_000, 1_000), X.amm_sell(user, p, 1_000, 0, 1, True)))
    import struct
    away = X.Ix(X.SYSTEM, [(user, True, True), (key(99), False, True)], struct.pack("<IQ", 2, 10 ** 9))
    with pytest.raises(ValueError, match="system instruction"):
        X.check_own(user, [away])
    with pytest.raises(ValueError, match="closed to someone else"):
        X.check_own(user, [X.Ix(X.TOKEN, [(key(5), False, True), (key(99), False, True), (user, True, False)],
                                bytes([9]))])
    with pytest.raises(ValueError, match="token instruction"):
        X.check_own(user, [X.Ix(X.TOKEN, [(key(5), False, True)], bytes([3]) + bytes(8))])   # a token transfer
    with pytest.raises(ValueError, match="not part of a plain"):
        X.check_own(user, [X.Ix(key(42), [], b"")])
    with pytest.raises(ValueError, match="buy or sell"):
        X.check_own(user, [X.Ix(X.PUMP, [], X.discriminator("withdraw"))])
    rt = X.round_trip(X.amm_buy(user, p, 5, 1, 1), X.amm_sell(user, p, 1, 0, 1, True))
    assert sum(ix.program == X.COMPUTE_BUDGET for ix in rt) == 1


def _swap(ixs, program=X.PUMP_AMM):
    return next(i for i, ix in enumerate(ixs) if ix.program == program)


def test_check_own_takes_the_v2_and_v3_trades_only_as_the_wallets_own():
    user = key(77)
    p = X.PoolInfo(key(60), MINT, X.WSOL, key(61), key(62), X.TOKEN_2022, X.BUYBACK_FEE_RECIPIENTS[3])
    c = X.CurveInfo(MINT, X.TOKEN_2022, X.BUYBACK_FEE_RECIPIENTS[4])
    for ixs in (X.amm_buy(user, p, 5_000, 1_000, 1), X.amm_sell(user, p, 1_000, 0, 1, True),
                X.pump_buy(user, c, 1_000, 5_000, 1), X.pump_sell(user, c, 1_000, 0, 1, True)):
        X.check_own(user, ixs)

    def changed(ixs, name, value, program=X.PUMP_AMM):
        """A copy of the trade with one named account replaced."""
        ixs = list(ixs)
        k = _swap(ixs, program)
        names = X.AMM_V2 if program == X.PUMP_AMM else X.PUMP_V3
        accts = list(ixs[k].accounts)
        i = names.index(name)
        accts[i] = (value, *accts[i][1:])
        ixs[k] = X.Ix(program, accts, ixs[k].data)
        return ixs

    buy = X.amm_buy(user, p, 5_000, 1_000, 1)
    with pytest.raises(ValueError, match="buyback fee account"):
        X.check_own(user, changed(buy, "buyback_fee_recipient", key(99)))
    with pytest.raises(ValueError, match="buyback fee account"):       # the wallet itself, not its token account
        X.check_own(user, changed(buy, "buyback_fee_recipient", X.BUYBACK_FEE_RECIPIENTS[3]))
    with pytest.raises(ValueError, match="not the wallet's own"):
        X.check_own(user, changed(buy, "user_base_token_account", X.ata(key(98), MINT, X.TOKEN_2022)))
    with pytest.raises(ValueError, match="not the wallet's own"):
        X.check_own(user, changed(buy, "user", key(98)))
    sell = X.pump_sell(user, c, 1_000, 0, 1, False)
    with pytest.raises(ValueError, match="not the wallet's own"):
        X.check_own(user, changed(sell, "associated_base_user", X.ata(key(98), MINT, X.TOKEN_2022), X.PUMP))
    with pytest.raises(ValueError, match="buyback fee account"):
        X.check_own(user, changed(sell, "buyback_fee_recipient", key(99), X.PUMP))
    # the v1 pool trades and the legacy curve trades are refused, whatever their accounts
    v1 = list(buy)
    k = _swap(v1)
    v1[k] = X.Ix(X.PUMP_AMM, v1[k].accounts, X.discriminator("buy") + v1[k].data[8:])
    with pytest.raises(ValueError, match="must be v2"):
        X.check_own(user, v1)
    legacy = X.pump_buy(user, c, 1, 1, 1)
    k = _swap(legacy, X.PUMP)
    legacy[k] = X.Ix(X.PUMP, legacy[k].accounts, X.discriminator("buy") + legacy[k].data[8:])
    with pytest.raises(ValueError, match="must be v3"):
        X.check_own(user, legacy)
    with pytest.raises(ValueError, match="for someone else"):
        X.check_own(user, [X.create_ata(user, key(98), MINT)])


def test_v2_and_v3_instruction_data_and_accounts_follow_the_docs():
    user = key(77)
    # PUMP_SWAP_TRADE_V2.md and TRADE_V3.md, the account tables in order
    assert X.AMM_V2 == ["pool", "user", "global_config", "base_mint", "quote_mint", "user_base_token_account",
                        "user_quote_token_account", "pool_base_token_account", "pool_quote_token_account",
                        "base_token_program", "quote_token_program", "system_program", "user_volume_accumulator",
                        "fee_config", "buyback_fee_recipient", "event_authority", "program"]
    assert X.PUMP_V3 == ["global", "base_mint", "quote_mint", "base_token_program", "quote_token_program",
                         "bonding_curve", "associated_base_bonding_curve", "associated_quote_bonding_curve", "user",
                         "associated_base_user", "associated_quote_user", "user_volume_accumulator", "fee_config",
                         "buyback_fee_recipient", "system_program", "event_authority", "program"]
    p = X.PoolInfo(key(60), MINT, X.WSOL, key(61), key(62), X.TOKEN_2022, X.BUYBACK_FEE_RECIPIENTS[5])
    buy = X.amm_buy(user, p, 10_000_000, 2_000, 1)
    ix = buy[_swap(buy)]
    assert ix.data == bytes([194, 171, 28, 70, 104, 77, 91, 47]) + struct.pack("<QQ", 10_000_000, 2_000)
    a = dict(zip(X.AMM_V2, [k for k, _, _ in ix.accounts]))
    assert len(ix.accounts) == 17
    assert a["global_config"] == "ADyA8hdefvWN2dbGGWFotbzWxrAvLW83WG6QCVXvJKqw"        # the docs' addresses
    assert a["fee_config"] == "5PHirr8joyTMp9JMm6nW7hNDVyEYdkzDqazxPD7RaTjx"
    assert a["buyback_fee_recipient"] == X.ata(X.BUYBACK_FEE_RECIPIENTS[5], X.WSOL, X.TOKEN)
    assert a["user_base_token_account"] == X.ata(user, MINT, X.TOKEN_2022)            # the coin's token program
    assert a["user_quote_token_account"] == X.ata(user, X.WSOL, X.TOKEN)
    assert (a["base_token_program"], a["quote_token_program"], a["program"]) == (X.TOKEN_2022, X.TOKEN, X.PUMP_AMM)
    flags = {n: (s, w) for n, (_, s, w) in zip(X.AMM_V2, ix.accounts)}
    assert flags["user"] == (True, True) and flags["buyback_fee_recipient"] == (False, True)
    # the user's accounts exist before the trade: the base account made with the right program, SOL wrapped
    creates = [x for x in buy if x.program == X.ATA_PROGRAM]
    assert {x.accounts[1][0] for x in creates} == {X.ata(user, X.WSOL, X.TOKEN), X.ata(user, MINT, X.TOKEN_2022)}
    assert next(x for x in creates if x.accounts[3][0] == MINT).accounts[5][0] == X.TOKEN_2022
    order = [x.program for x in buy]
    assert order.index(X.SYSTEM) < order.index(X.PUMP_AMM) and buy[-1].data == bytes([9])   # wrap first, close last
    sell = X.amm_sell(user, p, 3_000, 4_000, 1, True)
    six = sell[_swap(sell)]
    assert six.data == bytes([93, 246, 130, 60, 231, 233, 64, 178]) + struct.pack("<QQ", 3_000, 4_000)
    assert [k for k, _, _ in six.accounts] == [k for k, _, _ in ix.accounts]
    assert sell[-1].accounts[0][0] == X.ata(user, MINT, X.TOKEN_2022)               # the emptied account closed
    c = X.CurveInfo(MINT, X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[6])
    cb = X.pump_buy(user, c, 123, 456, 1)
    cix = cb[_swap(cb, X.PUMP)]
    assert cix.data == bytes([7, 5, 29, 196, 245, 23, 101, 80]) + struct.pack("<QQ", 123, 456) + b"\x00"
    a = dict(zip(X.PUMP_V3, [k for k, _, _ in cix.accounts]))
    assert a["fee_config"] == "8Wf5TiAheLUqBrKXeYg2JtAFFMWtKdG2BSFgqUcPVwTt"
    assert a["buyback_fee_recipient"] == X.BUYBACK_FEE_RECIPIENTS[6]                 # a SOL coin pays the wallet
    assert a["quote_mint"] == X.WSOL and a["associated_quote_user"] == X.ata(user, X.WSOL, X.TOKEN)
    cs = X.pump_sell(user, c, 123, 7, 1, False)
    assert cs[_swap(cs, X.PUMP)].data == bytes([28, 146, 222, 119, 38, 196, 105, 213]) + struct.pack("<QQ", 123, 7)


def test_cashback_coins_are_refused_and_never_traded_with_the_old_instructions():
    user = key(77)
    p = X.PoolInfo(key(60), MINT, X.WSOL, key(61), key(62), X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[0], cashback=True)
    assert not p.supports_v2()
    with pytest.raises(ValueError, match="cashback"):
        X.amm_buy(user, p, 5_000, 1_000, 1)
    with pytest.raises(ValueError, match="cashback"):
        X.amm_sell(user, p, 1_000, 0, 1, True)
    c = X.CurveInfo(MINT, X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[0], cashback=True)
    with pytest.raises(ValueError, match="cashback"):
        X.pump_buy(user, c, 1, 1, 1)
    with pytest.raises(ValueError, match="quoted in SOL"):
        X.amm_buy(user, X.PoolInfo(key(60), MINT, key(9), key(61), key(62), X.TOKEN, X.BUYBACK_FEE_RECIPIENTS[0]),
                  5_000, 1_000, 1)
    rpc = SimRpc(cashback=True)
    b = LX.Builder(rpc, (None, None))
    o = P.Order(1, "buy", MINT, "pool", 1_000, 1_300, T0, stake_l=1_000)
    with pytest.raises(RuntimeError, match="no v2 trade"):
        b.ixs(user, o, POOL, False)
    gate = LX.LiveGate(Path("none"), Path("none.json"), env={}, kill=lambda: False, now_ms=lambda: T0,
                       idl_path=Path("none"))
    rec = LX.simulate(gate, rpc, user, mint=MINT, pool=POOL, now_ms=T0)
    assert not rec["ok"] and "no v2 trade" in rec["error"] and not rpc.simulated


def test_a_pool_buy_spends_the_stake_and_wants_the_quote_less_the_tolerance():
    o = P.Order(1, "buy", MINT, "pool", 1_300_000, int(0.13 * SOL), T0, stake_l=int(0.1 * SOL))
    spend, least = LX.pool_buy_amounts(o)
    assert spend == int(0.1 * SOL) and least == int(1_300_000 / (1 + C.SLIP_TOL))
    old = P.Order(1, "buy", MINT, "pool", 1_300_000, int(0.13 * SOL), T0)              # without the stake
    assert LX.pool_buy_amounts(old)[0] == int(0.13 * SOL / (1 + C.SLIP_TOL))


def test_the_pool_account_gives_its_signed_virtual_quote_reserves_and_flags():
    pool = bytearray(300)
    for off, k in ((43, MINT), (75, X.WSOL), (139, key(61)), (171, key(62))):
        pool[off:off + 32] = X.key(k)
    pool[245:261] = (-1_234_567).to_bytes(16, "little", signed=True)
    cfg = bytearray(1000)
    cfg[643 + 32:643 + 64] = X.key(X.BUYBACK_FEE_RECIPIENTS[7])                     # one listed, the rest unknown
    info = X.pool_info(POOL, bytes(pool), bytes(cfg), X.TOKEN)
    assert info.virtual_quote == -1_234_567 and not info.cashback and info.supports_v2()
    assert info.buyback_recipient == X.BUYBACK_FEE_RECIPIENTS[7]
    assert info.effective_quote(80 * SOL) == 80 * SOL - 1_234_567
    pool[244] = 1
    assert X.pool_info(POOL, bytes(pool), bytes(cfg), X.TOKEN).cashback
    short = X.pool_info(POOL, bytes(pool[:243]), bytes(cfg), X.TOKEN)              # written before the fields
    assert short.virtual_quote == 0 and not short.cashback
    with pytest.raises(ValueError, match="buyback"):
        X.pool_info(POOL, bytes(pool), bytes(1000), X.TOKEN)
    glob = bytearray(1100)
    glob[741:741 + 32] = X.key(X.BUYBACK_FEE_RECIPIENTS[2])
    curve = bytearray(200)
    curve[83:115] = X.key(X.SYSTEM)                                                  # a SOL coin: the default key
    ci = X.curve_info(MINT, X.TOKEN_2022, bytes(glob), bytes(curve))
    assert (ci.quote_mint, ci.buyback_recipient, ci.token_program, ci.cashback) == \
        (X.WSOL, X.BUYBACK_FEE_RECIPIENTS[2], X.TOKEN_2022, False)


def test_effective_quote_reserves_price_every_pool_quote():
    base, vault = 200_000_000 * 10 ** 6, 80 * SOL
    assert C.effective_quote(vault, -2 * SOL) == 78 * SOL and C.effective_quote(vault, None) == vault
    assert C.effective_quote(SOL, -2 * SOL) == 0                                     # never below zero
    raw = C.pool_buy(SOL, base, vault, 30)
    eff = C.pool_buy(SOL, base, C.effective_quote(vault, -2 * SOL), 30)
    assert eff > raw                       # fees waiting in the vault are not liquidity: less quote, more tokens
    assert C.pool_sell(10 ** 12, base, C.effective_quote(vault, -2 * SOL), 30) < C.pool_sell(10 ** 12, base, vault, 30)
    tok = T.Token(MINT, key(3), T0, 1, 30 * SOL, 10 ** 15, 8 * 10 ** 14, {})
    tok.amm(True, 10 ** 9, SOL // 100, base, vault, 20, 5, 5, slot=1, vq=-2 * SOL)
    assert tok.pq == 78 * SOL + SOL // 100 and tok.pb == base - 10 ** 9
    tok.amm(False, 10 ** 9, SOL // 100, base, vault, 20, 5, 5, slot=2)                # an old row: no vq
    assert tok.pq == vault - SOL // 100
    assert C.price(tok.pq, tok.pb) == pytest.approx((tok.pq / SOL) / (tok.pb / 10 ** 6))


# ---------------------------------------------------------------- the test-mode confirmation

ACK = ("mode=test\nstrategy={s}\nmax_total_sol={t}\nmax_daily_loss_sol={d}\nmax_trade_sol={x}\n"
       "I accept that I can lose all of it\n")


def ack_file(tmp_path, s="P_pool60", t=1.0, d=0.3, x=0.02, line=True) -> Path:
    p = tmp_path / "ack"
    text = ACK.format(s=s, t=t, d=d, x=x)
    p.write_text(text if line else text.replace(LX.ACCEPT_LINE, ""))
    return p


def test_the_test_ack_needs_every_value_under_its_hard_maximum_and_the_line(tmp_path):
    a = LX.read_ack(ack_file(tmp_path))
    assert (a.mode, a.rule, a.max_total_sol, a.max_daily_loss_sol, a.max_trade_sol, a.problems) == \
        ("test", "P_pool60", 1.0, 0.3, 0.02, ())
    for kw, words in (({"t": 2.5}, "max_total_sol=2.5 is above the hard maximum 2"),
                      ({"d": 0.6}, "max_daily_loss_sol=0.6 is above"), ({"x": 0.1}, "max_trade_sol=0.1 is above"),
                      ({"line": False}, "lacks the line"), ({"s": "P_nothing"}, "not a pipeline strategy"),
                      ({"d": 0}, "must be above 0")):
        why = " | ".join(LX.read_ack(ack_file(tmp_path, **kw)).problems)
        assert words in why, (kw, why)
    assert LX.read_ack(ack_file(tmp_path, s="auto")).problems == ()


def test_auto_picks_the_least_bad_post_migration_pool_strategy():
    rep = {"results": [{"rule": "P_pool60", "family": "E", "pipeline": True, "stats": {"mean": -0.06}},
                       {"rule": "P_p90", "family": "D", "pipeline": True, "stats": {"mean": 0.5}},
                       {"rule": "E_d60_x1", "family": "E", "pipeline": False, "stats": {"mean": 0.2}}]}
    assert LX.resolve_rule("auto", rep) == "P_pool60"
    assert LX.resolve_rule("auto", None) == LX.DEFAULT_TEST_RULE == "P_pool60"
    assert LX.resolve_rule("P_p90", rep) == "P_p90"


def make_gate(tmp_path, ack=None, sim_rec="ok", env=None, kill=False) -> LX.LiveGate:
    idl = tmp_path / "idl"
    idl.mkdir(exist_ok=True)
    pump, amm = idl_docs()
    (idl / "pump.json").write_text(json.dumps(pump))
    (idl / "pump_amm.json").write_text(json.dumps(amm))
    wallet = tmp_path / "wallet-file"
    wallet.write_text("never read by the gate")
    if hasattr(wallet, "chmod"):
        wallet.chmod(0o600)
    WT.address_path(wallet).write_text(FakeSigner.pubkey)
    simf = tmp_path / "simulate.json"
    if sim_rec == "ok":
        simf.write_text(json.dumps({"t": T0 - 3_600_000, "ok": True, "pubkey": FakeSigner.pubkey, "venue": "pool"}))
    elif sim_rec is not None:
        simf.write_text(json.dumps(sim_rec))
    e = {"PYTHIA_PUMPFUN_LIVE": "1", "PYTHIA_PUMPFUN_KEYPAIR": str(wallet),
         "PYTHIA_PUMPFUN_RPC": "https://rpc.example.org"}
    e.update(env or {})
    return LX.LiveGate(ack or ack_file(tmp_path), tmp_path / "no-report.json", env=e, kill=lambda: kill,
                       now_ms=lambda: T0, idl_path=idl, simulate_file=simf)


def test_the_test_gate_skips_readiness_but_needs_a_fresh_simulation_for_this_wallet(tmp_path):
    g = make_gate(tmp_path)
    assert g.check() == [] and g.mode == "test" and g.rule == "P_pool60" and g.address == FakeSigner.pubkey
    for kw, words in (({"sim_rec": None}, "no successful simulation"),
                      ({"sim_rec": {"t": T0 - 25 * 3_600_000, "ok": True, "pubkey": FakeSigner.pubkey}}, "25 h old"),
                      ({"sim_rec": {"t": T0, "ok": False, "pubkey": FakeSigner.pubkey}}, "simulation failed"),
                      ({"sim_rec": {"t": T0, "ok": True, "pubkey": key(9)}}, "another wallet"),
                      ({"sim_rec": {"t": T0, "ok": True, "pubkey": FakeSigner.pubkey, "venue": "curve"}},
                       "simulation was on the curve"),
                      ({"env": {"PYTHIA_PUMPFUN_LIVE": "0"}}, "is not 1"), ({"kill": True}, "kill switch")):
        d = tmp_path / str(abs(hash(str(kw))))
        d.mkdir()
        why = " | ".join(make_gate(d, **kw).check())
        assert words in why, (kw, why)
    d = tmp_path / "nopub"
    d.mkdir()
    g = make_gate(d)
    WT.address_path(Path(g.env["PYTHIA_PUMPFUN_KEYPAIR"])).unlink()
    assert any("public address" in w for w in g.check())


def test_the_apps_kill_file_stops_the_live_book_only(folders):
    assert not LX.live_killed()
    (LX.reports_dir()).mkdir(parents=True, exist_ok=True)
    (LX.reports_dir() / "KILL").write_text("from the app")
    assert LX.live_killed() and not P.killed()               # the paper books keep going


# ---------------------------------------------------------------- limits: the app can only lower them

def test_the_effective_limits_are_the_lowest_of_code_ack_app_and_env(tmp_path):
    a = LX.read_ack(ack_file(tmp_path, t=1.5, d=0.4, x=0.04))
    lim, total = LX.effective(a, {}, env={})
    assert (lim.stake_sol, lim.max_daily_loss_sol, total, lim.max_exposure_sol) == (0.04, 0.4, 1.5, 0.6)
    lim, total = LX.effective(a, {"max_trade_sol": 0.01, "max_daily_loss_sol": 0.1, "max_total_sol": 0.5,
                                  "max_open": 2}, env={})
    assert (lim.stake_sol, lim.max_daily_loss_sol, total, lim.max_open, lim.max_exposure_sol) == \
        (0.01, 0.1, 0.5, 2, 0.5)
    lim, total = LX.effective(a, {"max_trade_sol": 5, "max_daily_loss_sol": 9, "max_total_sol": 99, "max_open": 50},
                              env={})
    assert (lim.stake_sol, lim.max_daily_loss_sol, total, lim.max_open) == (0.04, 0.4, 1.5, 5)   # never raised
    lim, _ = LX.effective(a, {}, env={"PYTHIA_PUMPFUN_STAKE_SOL": "0.02"})
    assert lim.stake_sol == 0.02


def test_settings_from_the_app_ignore_anything_that_is_not_a_positive_number(folders):
    LX.settings_path().parent.mkdir(parents=True)
    LX.settings_path().write_text(json.dumps({"max_trade_sol": 0.01, "max_total_sol": -1, "max_open": True,
                                              "max_daily_loss_sol": "0.2", "extra": 5}))
    assert LX.read_settings() == {"max_trade_sol": 0.01}


# ---------------------------------------------------------------- the executor in test mode

LIMITS = P.Limits(0.05, 5, 0.6, 0.3)


def executor(tmp_path, limits=None, total=1.0, clock=None, **kw) -> LX.LiveExecutor:
    gate = OpenGate()
    gate.rule, gate.mode = "X", "test"
    return LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), limits or LIMITS,
                           clock=clock or (lambda: T0), start=False, mode="test", max_total_sol=total, rule="X",
                           totals={"pnl_l": 0, "since_ms": None, "trades": 0, "total_alerted": False}, **kw)


def test_the_daily_and_the_total_stop_fire_once_and_refuse_buys(tmp_path):
    fired = []
    now = [T0]
    ex = executor(tmp_path, total=0.5, clock=lambda: now[0], on_stop=lambda k, v: fired.append((k, round(v, 3))))
    o = P.Order(1, "buy", MINT, "curve", 10, int(0.02 * SOL), T0)
    assert ex._caps(o) is None
    ex.booked(-int(0.31 * SOL))
    assert fired == [("daily", 0.31)] and ex._caps(o) == "daily loss stop"
    ex.booked(-int(0.01 * SOL))
    assert fired == [("daily", 0.31)]                          # once a day
    now[0] += P.DAY_MS                                         # the next day: the daily stop is gone ...
    assert ex._caps(o) is None
    ex.booked(-int(0.2 * SOL))
    assert ("total", 0.52) in fired and ex._caps(o) == "total budget stop"     # ... the total is not
    ex.booked(-1)
    assert sum(1 for k, _ in fired if k == "total") == 1
    assert json.loads((LX.totals_path()).read_text())["total_alerted"] is True


def test_the_owner_hears_when_the_running_gate_shuts_and_opens_again(tmp_path):
    ex = executor(tmp_path)
    heard = []
    ex.on_gate = heard.append
    assert ex.ready() is None and heard == []                  # open from the start: nothing to say
    ex.gate.why = ["the last simulation is 25 h old (at most 24 h; run live_exec simulate)"]
    ex.last_check = -1e18
    assert "25 h old" in ex.ready() and "25 h old" in heard[-1]
    ex.last_check = -1e18
    ex.ready()
    assert len(heard) == 1                                     # once per change, not every minute
    ex.gate.why = []
    ex.last_check = -1e18
    assert ex.ready() is None and heard[-1] is None


def test_a_buy_that_would_cross_the_budget_or_the_reserve_is_refused(tmp_path):
    ex = executor(tmp_path, total=0.1)
    ex.totals["pnl_l"] = -int(0.09 * SOL)
    o = P.Order(1, "buy", MINT, "curve", 10, int(0.02 * SOL), T0)
    assert ex._caps(o) == "total budget"
    ex = executor(tmp_path)
    ex.balance_l = int(0.025 * SOL)
    assert ex._caps(o) == "wallet balance too low"            # 0.02 + the 0.01 fee reserve
    ex.balance_l = int(0.04 * SOL)
    assert ex._caps(o) is None


def test_a_test_fill_is_measured_tagged_and_its_fee_asked_for(tmp_path):
    ex = executor(tmp_path)
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(P.Pipeline(eng, [strat(sl=0.99, ladder=((0.3, 1.0),), time_s=600)], ex, limits=LIMITS,
                                   name="live", record=False))
    book = LX.LiveBook(pipe, ex, "X", alerts=False)
    pipe.on_close = book.on_close
    cv = Curve(eng)
    eng.advance(T0 + 1)
    ex.drain()
    pipe.poll(T0 + 100)
    cv.buy(T0 + 1_400, int(0.05 * SOL), FakeSigner.pubkey)    # our buy lands 1.4 s after the signal
    rows = MS.read_measured()
    fill = [r for r in rows if r.get("what") == "fill"][0]
    assert fill["mode"] == "test" and fill["side"] == "buy" and fill["lat_ms"] == 1_400
    assert fill["slip"] is not None and ex.meas[0]["lat_ms"] == fill["lat_ms"]
    assert ex.q.queue[-1][0] == "fee"                          # the network fee is asked for after the fill
    ex.builder.rpc.fee_of = lambda sig: 10_000
    ex.drain()
    pipe.poll(T0 + 1_500)
    assert any(r.get("what") == "fee" and r["fee_l"] == 10_000 for r in MS.read_measured())
    p = pipe.pos[0]
    cv.buy(T0 + 2_000, 15 * SOL, BUYERS[0])
    ex.drain()
    pipe.poll(T0 + 2_100)
    cv.sell(T0 + 2_600, p["tokens"], FakeSigner.pubkey)
    led = LX.read_ledger()
    assert led[0]["mode"] == "test" and led[0]["lat_buy_ms"] == fill["lat_ms"]
    assert ex.totals["trades"] == 1 and ex.totals["pnl_l"] != 0
    orders = [json.loads(x) for x in (LX.data_dir() / "orders.jsonl").read_text().splitlines()]
    assert all(o.get("mode") == "test" for o in orders)


def test_settings_lower_the_running_book(tmp_path, folders):
    ex = executor(tmp_path)
    ex.gate.ack = LX.read_ack(ack_file(tmp_path, t=1.0, d=0.3, x=0.05))
    ex.gate.env = {}
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(P.Pipeline(eng, [strat()], ex, name="live", record=False))
    book = LX.LiveBook(pipe, ex, "X", alerts=False)
    LX.settings_path().parent.mkdir(parents=True, exist_ok=True)
    LX.settings_path().write_text(json.dumps({"max_trade_sol": 0.01, "max_total_sol": 0.2}))
    book.refresh_limits()
    assert ex.limits.stake_sol == 0.01 and ex.max_total_l == int(0.2 * SOL)
    assert pipe.risk["X"].limits.stake_sol == 0.01


def test_leftovers_from_before_a_restart_are_sold(tmp_path):
    ex = executor(tmp_path)
    eng = sim.Engine([], costs=Fixed())
    pipe = eng.add_pipe(P.Pipeline(eng, [strat()], ex, name="live", record=False))
    got = []
    book = LX.LiveBook(pipe, ex, "X", alerts=True, poster=lambda make: got.append(make("en")))
    book._post = lambda make: got.append(make("en"))
    LX.write_json(LX.data_dir() / "open.json", [{"mint": MINT, "venue": "curve", "pool": None, "symbol": "TST",
                                                  "cost_l": int(0.05 * SOL)},
                                                 {"mint": key(55), "venue": "curve", "pool": None, "cost_l": 1}])
    assert book.adopt_leftovers({MINT: 1_000_000}) == 1      # the other one is no longer in the wallet
    ex.drain()
    assert ex.builder.built[-1][0] == "sell" and ex.builder.built[-1][3] is True
    pipe.poll(T0)
    ex.on_trade("trades", {"t": T0 + 500, "mint": MINT, "buy": False, "sol": int(0.03 * SOL), "tok": 1_000_000,
                           "user": FakeSigner.pubkey, "fee_bps": 100})
    assert not ex.leftovers and ex.totals["pnl_l"] < 0
    assert "leftover sold" in got[-1][0].title and "TEST" in got[-1][0].title


# ---------------------------------------------------------------- the simulation (mocked RPC, nothing sent)

class SimRpc:
    """Every account read gets the same bytes: a pool (and GlobalConfig's buyback list) at their offsets."""

    def __init__(self, err=None, cashback=False, vq=0):
        self.err = err
        self.simulated = []
        self.cashback, self.vq = cashback, vq

    def account(self, pubkey):
        data = bytearray(1000)
        for off, k in ((43, MINT), (75, X.WSOL), (139, key(61)), (171, key(62))):
            data[off:off + 32] = X.key(k)
        data[244] = int(self.cashback)
        data[245:261] = self.vq.to_bytes(16, "little", signed=True)
        for i, r in enumerate(X.BUYBACK_FEE_RECIPIENTS):
            data[643 + 32 * i:675 + 32 * i] = X.key(r)
        return bytes(data), X.TOKEN

    def token_balance(self, acct):
        return 200_000_000 * 10 ** 6 if acct == key(61) else 80 * SOL

    def blockhash(self):
        return key(5)

    def simulate(self, tx):
        self.simulated.append(tx)
        return {"value": {"err": self.err if len(self.simulated) == 2 else None, "unitsConsumed": 90_000,
                          "logs": ["Program log: Instruction: Buy"]}}

    def send(self, tx):
        raise AssertionError("simulate must never send")


def test_simulate_builds_a_buy_and_a_round_trip_and_records_the_result(tmp_path, folders):
    pools = tmp_path / "pools.json"
    pools.write_text(json.dumps({POOL: [MINT, T0 - 60_000], key(66): [key(67), T0 - 600_000]}))
    gate = LX.LiveGate(tmp_path / "none", tmp_path / "none.json", env={}, kill=lambda: False, now_ms=lambda: T0,
                       idl_path=tmp_path)
    rpc = SimRpc(vq=-SOL)
    rec = LX.simulate(gate, rpc, FakeSigner.pubkey, sol=0.5, now_ms=T0, pools_file=pools)
    assert rec["ok"] and rec["venue"] == "pool" and rec["pool"] == POOL and rec["mint"] == MINT
    assert rec["reserves"] == {"base": 200_000_000 * 10 ** 6, "quote_vault": 80 * SOL, "virtual_quote": -SOL,
                               "effective": 79 * SOL}                               # priced on the effective reserves
    assert X.discriminator("buy_exact_quote_in_v2") in rpc.simulated[0]
    assert X.discriminator("sell_v2") in rpc.simulated[1] and X.discriminator("buy") not in rpc.simulated[1]
    assert LX.simulate_problems(rec, FakeSigner.pubkey, T0, "P_pool60") == []
    assert "on the pool" in LX.simulate_problems(rec, FakeSigner.pubkey, T0, "P_p90")[0]   # a curve strategy
    assert rec["sol"] == LX.TEST_MAX_TRADE_SOL and len(rpc.simulated) == 2       # capped; buy, then the round trip
    assert all(tx[1:65] == bytes(64) for tx in rpc.simulated)                  # unsigned
    assert json.loads(LX.simulate_path().read_text())["ok"] is True
    bad = LX.simulate(gate, SimRpc(err={"InstructionError": [3, "Custom"]}), FakeSigner.pubkey, now_ms=T0,
                      pools_file=pools)
    assert not bad["ok"] and LX.simulate_problems(bad, FakeSigner.pubkey, T0) == \
        ["the last simulation failed (live_exec simulate shows why)"]
    none = LX.simulate(gate, SimRpc(), FakeSigner.pubkey, now_ms=T0, pools_file=tmp_path / "missing.json")
    assert not none["ok"] and "no recent pool" in none["error"]


# ---------------------------------------------------------------- the service and its status file

class BalanceRpc:
    def balance(self, pubkey):
        return int(1.25 * SOL)

    def holdings(self, owner):
        return {MINT: 5}


def test_a_shut_service_still_shows_the_address_balance_and_every_reason(tmp_path, folders):
    g = make_gate(tmp_path, sim_rec=None)
    svc = LS.Service(gate=g, engine=sim.Engine([]), rpc=BalanceRpc(), alerts=False, start_worker=False)
    svc.start()
    assert svc.book is None
    svc.periodic()
    svc.save()
    st = json.loads((LX.reports_dir() / "live_status.json").read_text())
    assert st["running"] and not st["on"] and st["mode"] == "test" and st["address"] == FakeSigner.pubkey
    assert st["balance_sol"] == 1.25 and st["holdings"] == [{"mint": MINT, "amount": 5}]
    assert any("simulation" in w for w in st["gate"])
    assert st["ack"]["max_total_sol"] == 1.0 and st["limits"]["max_trade_sol"] == 0.02
    assert st["hard"]["test"] == {"max_total_sol": 2.0, "max_daily_loss_sol": 0.5, "max_trade_sol": 0.05}
    assert json.loads((LX.reports_dir() / "live_trades.json").read_text())["trades"] == []
    svc.stopped()
    assert json.loads((LX.reports_dir() / "live_status.json").read_text())["running"] is False


def test_an_open_service_attaches_the_book_and_reports_it(tmp_path, folders):
    g = make_gate(tmp_path)

    def attach(engine, gate, rpc=None, alerts=True, start=True):
        ex = LX.LiveExecutor(gate, FakeSigner(), FakeBuilder(), P.Limits(0.02, 5, 0.6, 0.3), start=False,
                             mode="test", max_total_sol=1.0, rule=gate.rule)
        book = LX.LiveBook(None, ex, gate.rule, alerts=False)
        book.pipe = engine.add_pipe(P.Pipeline(engine, [P.BY_NAME[gate.rule]], ex, name="live", record=False))
        ex.builder.rpc = BalanceRpc()
        return book
    svc = LS.Service(gate=g, engine=sim.Engine([]), attach=attach, alerts=False, start_worker=False)
    svc.start()
    assert svc.book is not None and svc.address == FakeSigner.pubkey
    svc.periodic()
    svc.save()
    st = json.loads((LX.reports_dir() / "live_status.json").read_text())
    assert st["on"] and st["mode"] == "test" and st["rule"] == "P_pool60" and st["balance_sol"] == 1.25
    assert st["limits"]["max_total_sol"] == 1.0 and st["stops"] == {"daily": False, "total": False}
    (LX.reports_dir() / "KILL").write_text("app")
    svc.save()
    st = json.loads((LX.reports_dir() / "live_status.json").read_text())
    assert st["kill"] and not st["on"]


def test_attach_refuses_a_wallet_whose_pub_file_does_not_match(tmp_path, folders, capsys):
    g = make_gate(tmp_path)

    class Other:
        pubkey = key(9)
    assert LX.attach(sim.Engine([]), g, rpc=BalanceRpc(), load=lambda p: Other(), alerts=False, start=False) is None
    assert "do not match" in capsys.readouterr().out
    book = LX.attach(sim.Engine([]), g, rpc=BalanceRpc(), load=lambda p: FakeSigner(), alerts=False, start=False)
    assert book is not None and book.exec.mode == "test" and book.exec.limits.stake_sol == 0.02
    assert book.exec.max_total_l == int(1.0 * SOL) and book.rule == "P_pool60"


# ---------------------------------------------------------------- measurement and cards

def test_the_execution_report_compares_measured_with_assumed(folders):
    rows = [{"what": "fill", "mode": "test", "side": "buy", "rule": "P_pool60", "lat_ms": ms, "send_to_land_ms": 900,
             "slip": 0.02, "sig": f"s{ms}"} for ms in (1500, 2000, 2500)]
    rows += [{"what": "fee", "sig": "s1500", "fee_l": 1_010_000}, {"what": "failed", "why": "slippage", "fee_l": 0}]
    s = MS.summarise(rows, C.Costs(1000, 400, 3000, 0.001, 0.3))
    assert s["lat_buy_ms"]["median"] == 2000 and s["lat_ratio"] == 2.0 and s["failed"] == 1
    assert "slower than the paper assumption" in s["verdict"] and "flatters" in s["verdict"]
    assert s["fee_sol"]["n"] == 1 and abs(s["fee_sol"]["median"] - 0.00101) < 1e-12
    assert "| buy latency" in MS.markdown(s)
    assert MS.summarise([])["verdict"].startswith("No live fills")
    out = MS.write_report(rows)
    assert json.loads((LX.reports_dir() / "execution.json").read_text())["fills"] == 3 and out["buys"] == 3


def test_every_new_live_card_in_english_and_german():
    from lab.ops import i18n
    from lab.pumpfun_rt import card as CARD
    for lang in i18n.LANGS:
        c = CARD.live_trade_card("bought", {"rule": "P_pool60", "symbol": "TST", "mint": MINT},
                                 {"cost_l": SOL // 50, "tokens": 10 ** 9}, lang, 0.0, mode="test",
                                 measured={"lat_ms": 1500, "slip": 0.03})
        assert "TEST" in c.title and "1" in c.parts[0].text
        c = CARD.live_stop_card("daily", 0.31, 0.3, "test", lang)
        assert "TEST" in c.title and "0" in c.summary
        c = CARD.live_stop_card("total", 1.0, 1.0, "test", lang)
        assert "2 SOL" in c.summary
        for what in ("sold", "stuck"):
            c = CARD.live_leftover_card(what, {"symbol": "TST", "got_l": SOL // 100, "why": "x"}, "test", lang)
            assert c.title
        c = CARD.live_daily_card(T0 // 86_400_000, {"n": 3, "wins": 1, "pnl_sol": -0.01, "failed": 1},
                                 int(0.9 * SOL), -0.05, {"lat_buy_ms": {"n": 3, "median": 2000},
                                                         "assumed": {"lat_median_ms": 1000}}, "test", "P_pool60",
                                 lang)
        text = " ".join(p.text for p in c.parts[:3])
        assert "2" in text and "1" in text and "TEST" in c.title
        assert [p.text.count(". ") for p in c.parts[:3]] == [0, 0, 0], "one sentence a line"
        c = CARD.live_daily_card(T0 // 86_400_000, {"n": 0}, None, 0.0, None, "test", "P_pool60", lang)
        assert c.parts[0].text
        c = CARD.live_gate_card("the kill switch file is there", "test", lang)
        assert "kill switch" in c.summary and "TEST" in c.title
        assert CARD.live_gate_card(None, "test", lang).title


def test_the_dry_run_finds_a_fresh_curve_by_itself(tmp_path):
    import polars as pl
    now = 1_792_687_800_000
    day = "2026-10-22"
    (tmp_path / "creates" / f"date={day}").mkdir(parents=True)
    pl.DataFrame({"t": [now - 900_000, now - 60_000, now - 30_000, now - 20_000],
                  "mint": ["OLDpump", "OKpump", "NEWESTpump", "CASHpump"],
                  "cashback": [False, False, False, True]}).write_parquet(tmp_path / "creates" / f"date={day}" / "a.parquet")
    assert LX.newest_create(tmp_path, now_ms=now) == "NEWESTpump"         # the newest, cashback left out
    assert LX.newest_create(tmp_path, now_ms=now + 3_600_000) is None     # nothing in the last ten minutes
    assert LX.newest_create(tmp_path / "empty", now_ms=now) is None


def test_closed_trades_are_corrected_to_what_the_wallet_really_saw(tmp_path, monkeypatch):
    from lab.pumpfun_rt import chain_pnl as CP
    wallet = "W" * 44
    # The first live trade: booked at +0.000674 SOL, the wallet lost 0.000672 SOL.
    deltas = {"BUY": -11_775_858, "SELL": 11_103_855}
    asked = []

    class Rpc:
        def call(self, method, params):
            asked.append(params[0])
            return {"meta": {"preBalances": [10_000_000_000, 5], "postBalances": [10_000_000_000 + deltas[params[0]], 5],
                             "fee": 1_005_000}, "transaction": {"message": {"accountKeys": [wallet, "X"]}}}

    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path)
    LX.write_close({"mode": "test", "rule": "P_cmig_model", "mint": "DLMpump", "symbol": "DLM",
                    "signal_ms": 1_000, "land_ms": 9_000, "exit_ms": 18_000, "stake_sol": 0.01,
                    "proceeds_sol": 0.010595, "pnl_sol": 0.000674198, "ret": 0.067})
    with (tmp_path / "orders.jsonl").open("w", encoding="utf-8") as fh:
        for side, sig, t in (("buy", "BUY", 9_000), ("sell", "SELL", 18_000)):
            fh.write(json.dumps({"what": "sent", "side": side, "mint": "DLMpump", "sig": sig, "t": t - 10}) + "\n")
            fh.write(json.dumps({"what": "filled", "side": side, "mint": "DLMpump", "sig": sig, "t": t}) + "\n")
    adjust, changed = CP.reconcile(Rpc(), wallet, tmp_path)
    assert changed and adjust == -672_003 - 674_198
    row = LX.read_ledger(1)[0]
    assert row["pnl_sol"] == -0.000672003 and row["stake_sol"] == 0.011775858
    assert row["proceeds_sol"] == 0.011103855 and row["ret"] < 0
    n = len(asked)
    assert CP.reconcile(Rpc(), wallet, tmp_path) == (0, False)           # checked once, read once
    assert len(asked) == n


def test_a_trade_the_node_has_not_got_yet_waits_for_the_next_round(tmp_path):
    from lab.pumpfun_rt import chain_pnl as CP

    class Rpc:
        def call(self, method, params):
            return None
    (tmp_path / "ledger.csv").write_text("mint,signal_ms,exit_ms,pnl_sol\nAAApump,1000,5000,0.001\n", encoding="utf-8")
    (tmp_path / "orders.jsonl").write_text(
        json.dumps({"what": "filled", "side": "buy", "mint": "AAApump", "sig": "B", "t": 2000}) + "\n"
        + json.dumps({"what": "filled", "side": "sell", "mint": "AAApump", "sig": "S", "t": 5000}) + "\n",
        encoding="utf-8")
    assert CP.reconcile(Rpc(), "W", tmp_path, now_ms=6_000) == (0, False)     # fresh: the node may still get it
    assert "0.001" in (tmp_path / "ledger.csv").read_text(encoding="utf-8")


def test_the_book_takes_the_chain_correction_into_its_stops(tmp_path):
    ex = executor(tmp_path)
    seen = []
    ex.on_chain = lambda: seen.append(1)
    ex.results.put(("chain", None, -1_346_201))
    ex.poll(T0)
    assert ex.totals["pnl_l"] == -1_346_201 and ex.day_pnl_l == -1_346_201 and seen == [1]


def test_a_restart_keeps_the_days_losses_for_the_daily_stop(tmp_path, monkeypatch):
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path)
    today, yesterday = T0 - T0 % P.DAY_MS + 1_000, T0 - T0 % P.DAY_MS - 1_000
    for exit_ms, pnl in ((yesterday, -0.5), (today, -0.006174367), (today, -0.000672003)):
        LX.write_close({"mint": "M", "exit_ms": exit_ms, "pnl_sol": pnl})
    ex = executor(tmp_path)
    ex._roll()
    assert ex.day_pnl_l == -6_846_370


def test_a_failed_sale_that_landed_counts_its_fee_and_one_that_never_landed_counts_nothing(tmp_path):
    from lab.pumpfun_rt import chain_pnl as CP
    wallet = "W" * 44
    deltas = {"BUY": -37_823_278, "SELL": 34_759_695, "FAILED": -1_005_000}

    class Rpc:
        def call(self, method, params):
            if params[0] not in deltas:
                return None
            return {"meta": {"preBalances": [10**10], "postBalances": [10**10 + deltas[params[0]]]},
                    "transaction": {"message": {"accountKeys": [wallet]}}}
    (tmp_path / "ledger.csv").write_text("mint,signal_ms,exit_ms,pnl_sol\nCCCpump,1000,9000,0\n", encoding="utf-8")
    lines = [{"what": "filled", "side": "buy", "mint": "CCCpump", "sig": "BUY", "t": 5000},
             {"what": "filled", "side": "sell", "mint": "CCCpump", "sig": "SELL", "t": 9000},
             {"what": "failed", "side": "sell", "mint": "CCCpump", "sig": "FAILED", "t": 20_000},
             {"what": "failed", "side": "sell", "mint": "CCCpump", "sig": "NEVER", "t": 21_000},
             {"what": "failed", "side": "sell", "mint": "CCCpump", "sig": None, "t": 22_000}]
    (tmp_path / "orders.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    assert CP.reconcile(Rpc(), wallet, tmp_path, now_ms=100_000) == (0, False)        # NEVER: too fresh to judge
    adjust, changed = CP.reconcile(Rpc(), wallet, tmp_path, now_ms=10_000_000)
    assert changed and adjust == -37_823_278 + 34_759_695 - 1_005_000


def test_a_leftover_already_sold_on_chain_is_dropped_not_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(LX, "data_dir", lambda: tmp_path)
    ex = executor(tmp_path)
    o = P.Order(-1, "sell", MINT, "curve", 1_000, 0, T0, "leftover")
    pend = {"side": "sell", "order": o, "sig": None, "sent_ms": T0, "leftover": True}
    ex.leftovers[-1] = {"mint": MINT, "tokens": 1_000, "tries": 1}
    ex.verifying[-1] = (pend, "simulation failed", 0)
    ex._holds(-1, 0, T0)
    assert -1 not in ex.leftovers and not ex.pending
    ex.leftovers[-2] = {"mint": MINT, "tokens": 1_000, "tries": 1}
    ex.verifying[-2] = ({**pend, "order": P.Order(-2, "sell", MINT, "curve", 1_000, 0, T0, "leftover")}, "x", 0)
    ex._holds(-2, 1_000, T0)                                                       # still held: sell it again
    assert -2 in ex.pending and ex.leftovers[-2]["tries"] == 2
