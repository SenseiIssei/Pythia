"""lab.paper.hl_live, the Hyperliquid executor built for live but not armed: keccak-256, msgpack, secp256k1 with
RFC 6979, the L1 action against the test vectors of Hyperliquid's official Python SDK 0.24.0
(tests/signing_test.py there), the read-only reconciliation, and every gate of the send path. No network: every
call to Hyperliquid is a stub; the keys are the SDK's published test key and throwaway keys made here.

Run from research/lab:  python -m pytest tests/test_hl_live.py
"""

from __future__ import annotations

import hashlib
import inspect
import json
import secrets

import pytest

from lab.paper import hl_dryrun as hx
from lab.paper import hl_live as hl

# The SDK tests' wallet: the digits 0 to 9 repeated to 64 hex digits, a published test value, never a real one.
SDK_TEST = int(("0123456789" * 7)[:64], 16)
NOW = 1_793_600_000_000                                  # 2026-11-02, ms


# ---------------------------------------------------------------- hashing and encoding

def test_keccak256_is_ethereums_and_the_sponge_is_sha3():
    assert hl.keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    for n in (0, 1, 55, 135, 136, 137, 271, 272, 500):
        m = secrets.token_bytes(n)
        assert hl.sponge256(m, 0x06) == hashlib.sha3_256(m).digest()


def test_packb_matches_msgpacks_defaults():
    assert hl.packb({"a": 1, "b": True}) == b"\x82\xa1a\x01\xa1b\xc3"
    assert hl.packb([None, False, -1, -33, 200, 70_000, 1 << 40]) == (
        b"\x97\xc0\xc2\xff\xd0\xdf\xcc\xc8\xce\x00\x01\x11\x70\xcf\x00\x00\x01\x00\x00\x00\x00\x00")
    assert hl.packb("x" * 40)[:2] == b"\xd9\x28" and hl.packb(1.5) == b"\xcb?\xf8\x00\x00\x00\x00\x00\x00"
    with pytest.raises(TypeError):
        hl.packb({1, 2})


def test_float_to_wire_as_the_sdk():
    assert hl.float_to_wire(0.0147) == "0.0147" and hl.float_to_wire(100) == "100"
    assert hl.float_to_wire("1670.1") == "1670.1" and hl.float_to_wire(0.0) == "0"
    with pytest.raises(ValueError):
        hl.float_to_wire(0.000012312312)


# ---------------------------------------------------------------- the SDK's vectors

def test_phantom_agent_matches_production():
    action = hl.order_action([hl.order_wire(4, True, 1670.1, 0.0147, False, "Ioc")])
    h = hl.action_hash(action, 1677777606040)
    assert hl.phantom_agent(h, True)["connectionId"].hex() == (
        "0fcbeda5ae3c4950a548021552a4fea2226858c4453571bf3f24ba017eac2908")


SDK_VECTORS = [
    # (action, mainnet r, s, v, testnet r, s, v)
    ({"type": "dummy", "num": 100_000_000_000},
     "0x53749d5b30552aeb2fca34b530185976545bb22d0b3ce6f62e31be961a59298",
     "0x755c40ba9bf05223521753995abb2f73ab3229be8ec921f350cb447e384d8ed8", 27,
     "0x542af61ef1f429707e3c76c5293c80d01f74ef853e34b76efffcb57e574f9510",
     "0x17b8b32f086e8cdede991f1e2c529f5dd5297cbe8128500e00cbaf766204a613", 28),
    (hl.order_action([hl.order_wire(1, True, 100, 100, False, "Gtc")]),
     "0xd65369825a9df5d80099e513cce430311d7d26ddf477f5b3a33d2806b100d78e",
     "0x2b54116ff64054968aa237c20ca9ff68000f977c93289157748a3162b6ea940e", 28,
     "0x82b2ba28e76b3d761093aaded1b1cdad4960b3af30212b343fb2e6cdfa4e3d54",
     "0x6b53878fc99d26047f4d7e8c90eb98955a109f44209163f52d8dc4278cbbd9f5", 27),
    (hl.order_action([hl.order_wire(1, True, 100, 100, False, "Gtc", "0x00000000000000000000000000000001")]),
     "0x41ae18e8239a56cacbc5dad94d45d0b747e5da11ad564077fcac71277a946e3",
     "0x3c61f667e747404fe7eea8f90ab0e76cc12ce60270438b2058324681a00116da", 27,
     "0xeba0664bed2676fc4e5a743bf89e5c7501aa6d870bdb9446e122c9466c5cd16d",
     "0x7f3e74825c9114bc59086f1eebea2928c190fdfbfde144827cb02b85bbe90988", 28),
    ({"type": "scheduleCancel"},
     "0x6cdfb286702f5917e76cd9b3b8bf678fcc49aec194c02a73e6d4f16891195df9",
     "0x6557ac307fa05d25b8d61f21fb8a938e703b3d9bf575f6717ba21ec61261b2a0", 27,
     "0xc75bb195c3f6a4e06b7d395acc20bbb224f6d23ccff7c6a26d327304e6efaeed",
     "0x342f8ede109a29f2c0723bd5efb9e9100e3bbb493f8fb5164ee3d385908233df", 28),
    ({"type": "scheduleCancel", "time": 123456789},
     "0x609cb20c737945d070716dcc696ba030e9976fcf5edad87afa7d877493109d55",
     "0x16c685d63b5c7a04512d73f183b3d7a00da5406ff1f8aad33f8ae2163bab758b", 28,
     "0x4e4f2dbd4107c69783e251b7e1057d9f2b9d11cee213441ccfa2be63516dc5bc",
     "0x706c656b23428c8ba356d68db207e11139ede1670481a9e01ae2dfcdb0e1a678", 27),
]


@pytest.mark.parametrize("vec", SDK_VECTORS)
def test_l1_action_signing_matches_the_sdk(vec):
    action, mr, ms, mv, tr, ts, tv = vec
    assert hl.sign_l1_action(SDK_TEST, action, 0, mainnet=True) == {"r": mr, "s": ms, "v": mv}
    assert hl.sign_l1_action(SDK_TEST, action, 0, mainnet=False) == {"r": tr, "s": ts, "v": tv}


def test_a_throwaway_key_signs_and_recovers():
    d = secrets.randbelow(hl._N - 1) + 1
    action = hl.order_action([hl.order_wire(3, False, "0.2762", "41", True)])
    digest = hl.l1_digest(hl.phantom_agent(hl.action_hash(action, NOW)))
    sig = hl.sign_l1_action(d, action, NOW)
    assert int(sig["s"], 16) <= hl._N // 2 and sig["v"] in (27, 28)
    assert hl.recover(digest, sig) == hl._mul(d)
    assert hl.address_of(hl.recover(digest, sig)).startswith("0x") and len(hl.address_of(hl._mul(d))) == 42
    assert hl.sign_l1_action(d, action, NOW) == sig                                  # RFC 6979: deterministic
    assert hl.sign_l1_action(d, action, NOW + 1) != sig                              # the nonce is signed


def test_plan_action_carries_the_dry_runs_orders():
    p = hx.plan({"MET": -41.0}, {"XPL": -143.0}, {"MET": 0.28, "XPL": 0.081}, {"MET": 0, "XPL": 0}, 230.0, 230.0)
    a = hl.plan_action(p["orders"], {"MET": 7, "XPL": 9})
    assert a["type"] == "order" and a["grouping"] == "na"
    assert a["orders"][0] == {"a": 7, "b": True, "p": p["orders"][0]["limit_px"], "s": "41", "r": True,
                              "t": {"limit": {"tif": "Ioc"}}}
    assert a["orders"][1]["b"] is False and a["orders"][1]["r"] is False


def test_it_signs_orders_only_and_moves_no_money():
    src = inspect.getsource(hl)
    for word in ("withdraw3", "usdSend", "usdClassTransfer", "spotSend", "sendAsset", "vaultTransfer", "approveAgent",
                 "subAccountTransfer", "HyperliquidSignTransaction"):
        assert word not in src
    assert '"type": "order"' in src


# ---------------------------------------------------------------- the owner's files

def test_read_env_and_nothing_without_it(tmp_path):
    assert hl.read_env(tmp_path / "missing.env") == {}
    p = tmp_path / "hl.env"
    p.write_text(f"# comment\n{hl.ADDRESS_VAR}=0xabc\nexport {hl.KEY_FILE_VAR}='/x/y'\n")
    assert hl.read_env(p) == {hl.ADDRESS_VAR: "0xabc", hl.KEY_FILE_VAR: "/x/y"}
    assert hl.reconcile({}, {}, {}, fetch=lambda b: pytest.fail("no call without an address")) is None


def test_ack_needs_the_line_and_a_date_not_in_the_future(tmp_path):
    p = tmp_path / "ack"
    assert "no ack file" in hl.ack_problem(p, NOW)
    p.write_text("date=2026-11-01\n")
    assert "lacks the line" in hl.ack_problem(p, NOW)
    p.write_text(f"{hl.ACK_LINE}\n")
    assert "lacks a line date" in hl.ack_problem(p, NOW)
    p.write_text(f"{hl.ACK_LINE}\ndate=2026-13-01\n")
    assert "not a date" in hl.ack_problem(p, NOW)
    p.write_text(f"{hl.ACK_LINE}\ndate=2026-12-01\n")
    assert "future" in hl.ack_problem(p, NOW)
    p.write_text(f"{hl.ACK_LINE}\ndate=2026-11-01\n")
    assert hl.ack_problem(p, NOW) is None


# ---------------------------------------------------------------- read only

META = [{"universe": [{"name": "BTC", "szDecimals": 5}, {"name": "ETH", "szDecimals": 4},
                      {"name": "MET", "szDecimals": 0}]},
        [{"midPx": "60000.0"}, {"midPx": "3000.0"}, {"midPx": "0.25"}]]


def stub(value=230.0, positions=(("BTC", 0.0002), ("MET", -46.0)), fills=(), calls=None):
    def fetch(body):
        if calls is not None:
            calls.append(body["type"])
        mids = {"BTC": 60000.0, "ETH": 3000.0, "MET": 0.25}
        if body["type"] == "metaAndAssetCtxs":
            return META
        if body["type"] == "clearinghouseState":
            return {"marginSummary": {"accountValue": str(value)},
                    "assetPositions": [{"position": {"coin": c, "szi": str(u), "positionValue": str(abs(u) * mids[c]),
                                                     "cumFunding": {"sinceOpen": "0.01"}}} for c, u in positions]}
        if body["type"] == "openOrders":
            return [{"coin": "BTC"}]
        if body["type"] == "userFills":
            return list(fills)
        raise AssertionError(body)
    return fetch


def test_reconcile_reads_the_account_against_the_books_targets():
    book = {"equity_usd": 230.0, "units": {"BTC": 0.0002, "ETH": 0.004}}
    fills = [{"time": NOW - 1000, "fee": "0.005"}, {"time": NOW - 2 * hl.DAY_MS, "fee": "1"}]
    r = hl.reconcile({hl.ADDRESS_VAR: "0xabc"}, book, {"BTC": 60000.0, "ETH": 3000.0, "MET": 0.25},
                     fetch=stub(fills=fills), now_ms=NOW)
    assert r["value"] == 230.0 and r["positions"] == {"BTC": 0.0002, "MET": -46.0}
    assert r["targets"] == {"BTC": pytest.approx(0.0002), "ETH": pytest.approx(0.004)}
    assert r["drift"] == pytest.approx(0.5 * (12.0 + 11.5) / 230.0)
    assert r["missing"] == ["ETH"] and r["extra"] == ["MET"]
    assert r["funding_paid"] == pytest.approx(0.02) and r["open_orders"] == 1
    assert r["fills_24h"] == 1 and r["fees_24h"] == pytest.approx(0.005)


def test_targets_scale_to_the_live_account_and_its_cap():
    book = {"equity_usd": 200.0, "units": {"BTC": 0.001}}
    assert hl.book_targets(book, 100.0)["BTC"] == pytest.approx(0.0005)
    assert hl.book_targets(book, 400.0)["BTC"] == pytest.approx(0.00125)               # sized on 250 at most
    assert hl.book_targets({}, 100.0) == {}


# ---------------------------------------------------------------- the send path: every gate

def armed(tmp_path, value=230.0, ack=True, env=True, key=True, positions=(("BTC", 0.0002),), book_units=None,
          live=None, flat=False):
    folder = tmp_path / "book"
    folder.mkdir()
    (folder / "state.json").write_text(json.dumps({"equity_usd": 230.0, "units": book_units or {"BTC": 0.0002,
                                                                                               "ETH": 0.004}}))
    if live is not None:
        (folder / "live").mkdir()
        (folder / "live" / "state.json").write_text(json.dumps(live))
    if flat:
        (folder / hx.FLAT_FILE).write_text("")
    kf = tmp_path / "agent.hex"
    if key:
        kf.write_text(hex(secrets.randbelow(hl._N - 1) + 1))
    envf = tmp_path / "hl.env"
    if env:
        envf.write_text(f"{hl.ADDRESS_VAR}=0xabc\n{hl.KEY_FILE_VAR}={kf}\n")
    ackf = tmp_path / "hl.ack"
    if ack:
        ackf.write_text(f"{hl.ACK_LINE}\ndate=2026-11-01\n")
    sent, cards = [], []
    kw = dict(folder=folder, env_file=envf, ack_file=ackf, fetch=stub(value, positions), post=lambda p: sent.append(p)
              or {"status": "ok"}, card=cards.append, now_ms=NOW)
    return kw, sent, cards, folder


def refused(tmp_path, word, **arm):
    kw, sent, cards, folder = armed(tmp_path, **arm)
    res = hl.send(**kw)
    assert not res["sent"] and not sent and any(word in w for w in res["why"]), res
    log = [json.loads(x) for x in (folder / "live" / "log.jsonl").read_text().splitlines()]
    assert log[-1]["event"] == "refused" and any(word in w for w in log[-1]["why"])
    assert len(cards) == 1 and any(word in getattr(p, "text", "") for p in cards[0].parts)
    return res, folder


def test_all_gates_hold_signs_and_posts_once(tmp_path):
    kw, sent, cards, folder = armed(tmp_path)
    res = hl.send(**kw)
    assert res["sent"] and res["orders"] == 1 and not cards and len(sent) == 1
    p = sent[0]
    assert p["nonce"] == NOW and p["vaultAddress"] is None and set(p["signature"]) == {"r", "s", "v"}
    assert p["action"]["orders"] == [{"a": 1, "b": True, "p": hx.limit_price(3000.0, True, 4), "s": "0.004",
                                      "r": False, "t": {"limit": {"tif": "Ioc"}}}]
    st = json.loads((folder / "live" / "state.json").read_text())
    assert st["start_usd"] == 230.0 and st["last_nonce"] == NOW and not st["stopped"]
    assert hl.send(**kw)["sent"] and sent[1]["nonce"] == NOW + 1                      # the nonce only rises


def test_gate_env_address(tmp_path):
    kw, sent, cards, folder = armed(tmp_path, env=False)
    res = hl.send(**kw)
    assert not res["sent"] and not sent and any(hl.ADDRESS_VAR in w for w in res["why"])
    assert any(hl.KEY_FILE_VAR in w for w in res["why"]) and len(cards) == 1


def test_gate_env_key_file(tmp_path):
    refused(tmp_path, "names no file", key=False)


def test_gate_ack(tmp_path):
    refused(tmp_path, "ack:", ack=False)


def test_gate_account_value(tmp_path):
    refused(tmp_path, "account: value 250.01", value=250.01)
    (tmp_path / "zero").mkdir()
    refused(tmp_path / "zero", "account: value 0.00", value=0.0)


def test_gate_gross_held(tmp_path):
    refused(tmp_path, "gross:", positions=(("BTC", 0.008),))                          # 480 USD on 230


def test_gate_gross_target(tmp_path):
    refused(tmp_path, "gross:", book_units={"BTC": 0.008})


def test_gate_stop_and_it_sticks(tmp_path):
    res, folder = refused(tmp_path, "stop:", value=184.0, live={"start_usd": 230.0})
    assert json.loads((folder / "live" / "state.json").read_text())["stopped"] is True
    (tmp_path / "again").mkdir()
    refused(tmp_path / "again", "stopped for good", live={"start_usd": 230.0, "stopped": True})


def test_gate_go_flat(tmp_path):
    refused(tmp_path, "flat:", flat=True)


def test_gate_go_flat_in_the_live_folder_leaves_the_paper_book(tmp_path):
    kw, sent, cards, folder = armed(tmp_path, live={})
    (folder / "live" / hx.FLAT_FILE).write_text("")
    res = hl.send(**kw)
    assert not res["sent"] and not sent and any("flat:" in w for w in res["why"])
    assert not hx.flat_switch(folder)                                        # the paper book keeps trading


def test_an_unread_account_is_a_refusal(tmp_path):
    kw, sent, cards, folder = armed(tmp_path)

    def down(body):
        raise OSError("down")
    res = hl.send(**{**kw, "fetch": down})
    assert not res["sent"] and not sent and any("account:" in w for w in res["why"]) and len(cards) == 1


def test_the_key_is_read_only_after_every_gate(tmp_path, monkeypatch):
    kw, sent, cards, folder = armed(tmp_path, ack=False)
    read = []
    real = hl.Path.read_text

    def spy(self, *a, **k):
        read.append(self.name)
        return real(self, *a, **k)
    monkeypatch.setattr(hl.Path, "read_text", spy)
    hl.send(**kw)
    assert "agent.hex" not in read and not sent


def test_no_job_runs_the_send_path():
    from pathlib import Path
    root = Path(hl.__file__).resolve().parents[4]
    jobs = (root / "research" / "ops" / "jobs.yaml").read_text(encoding="utf-8")
    assert "hl_live" not in jobs
    assert "hl_live" not in inspect.getsource(__import__("lab.paper.m4_hl_small", fromlist=["x"]))
