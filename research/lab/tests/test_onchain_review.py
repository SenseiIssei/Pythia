"""The stage-2 review of the BUILT on-chain trader (docs/ONCHAIN-REVIEW.md, part 2): each high and medium finding
with the test that failed before its fix. Built on the fakes of test_onchain_live (no network, no key of anyone).

Run from research/lab:  python -m pytest tests/test_onchain_review.py
"""

from __future__ import annotations

import json
import struct

import pytest

import test_onchain_live as L
from lab.onchain import guard as G
from lab.onchain import live_exec as LX
from lab.onchain import live_gate as LG
from lab.onchain import live_service as SV
from lab.pumpfun_rt import txbuild as X
from lab.pumpfun_rt.events import WSOL

W, SOL, USDC, BTC = L.W, L.SOL, L.USDC, L.BTC


class Crash(BaseException):
    """The container stopped (SIGKILL after docker's grace) while a swap waited for its landing."""


def confirmed_convert(tmp_path, svc, cid):
    d = L.write_req(tmp_path, cid)
    svc.converts()
    prop = json.loads((d / f"{cid}.proposal.json").read_text())
    assert prop["status"] == "proposed"
    (d / f"{cid}.confirm.json").write_text(json.dumps({"id": cid, "proposal_t": prop["t"],
                                                       "min_out_raw": prop["min_out_raw"], "t": prop["t"] + 1_000}))
    return d


# ---------------------------------------------------------------- R1: a confirm is sent once, whatever happens

def test_a_confirm_is_sent_once_even_when_the_round_fails_after_the_send(tmp_path, monkeypatch):
    svc, tr, fc = L.service(tmp_path, monkeypatch)
    cid = "c1792712000000-0e01"
    d = confirmed_convert(tmp_path, svc, cid)
    real = LX.write_row

    def full_disk(row):
        raise OSError("no space left on device")
    monkeypatch.setattr(LX, "write_row", full_disk)
    with pytest.raises(OSError):
        svc.converts()                                      # landed, then the ledger row failed: no result file
    assert len(fc.sent) == 1 and not (d / f"{cid}.result.json").exists()
    monkeypatch.setattr(LX, "write_row", real)
    svc.converts()                                          # the next round 2 s later
    assert len(fc.sent) == 1 and len(tr.signer.signed) == 1
    res = json.loads((d / f"{cid}.result.json").read_text())
    assert res["status"] == "failed" and "not sent again" in res["why"] and res["sig"]


def test_a_restart_reads_back_a_sent_swap_and_never_sends_the_confirm_again(tmp_path, monkeypatch):
    svc, tr, fc = L.service(tmp_path, monkeypatch)
    cid = "c1792712000000-0e02"
    d = confirmed_convert(tmp_path, svc, cid)

    def stop(tx, sig, lvbh):
        tr._send(tx)
        raise Crash()
    tr._land = stop
    with pytest.raises(Crash):
        svc.converts()
    assert len(fc.sent) == 1 and LX.read_ledger() == []
    del tr._land
    svc2 = SV.Service(gate=tr.gate, trader=tr, load=lambda p: tr.signer, alerts=False)
    svc2.start()                                            # the restart, the confirm still valid
    svc2.converts()
    assert len(fc.sent) == 1 and len(tr.signer.signed) == 1
    assert "not sent again" in json.loads((d / f"{cid}.result.json").read_text())["why"]
    rows = LX.read_ledger()
    assert len(rows) == 1 and rows[0]["unread"] == "1" and rows[0]["ref"] == cid and rows[0]["kind"] == "convert"
    assert LX.realised(LX.day_of(LX.now_ms()))["converts"] == 1        # it counts for the day's caps at once
    assert tr.reread() == 1 and LX.read_ledger()[0]["status"] == "filled"
    assert LX.recover() == []                               # booked once


# ---------------------------------------------------------------- R2: the kill switch right before every signature

class KillOn(L.FakeChain):
    """Writes the kill file when the swap is simulated (or first sent): the owner pressed the button meanwhile."""

    def __init__(self, path, on="simulateTransaction", **kw):
        super().__init__(**kw)
        self.path, self.on = path, on

    def __call__(self, method, params):
        if method == self.on:
            self.path.write_text("kill")
        return super().__call__(method, params)


def test_a_kill_set_while_the_swap_is_built_stops_the_signature(tmp_path, monkeypatch):
    tr, fc = L.trader(tmp_path, monkeypatch, chain=KillOn(tmp_path / "KILL"))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr), gate_why=lambda: [])
    assert r["status"] == "refused" and "kill switch" in r["why"] and not tr.signer.signed and not fc.sent


def test_a_kill_set_after_the_first_send_stops_the_retries(tmp_path, monkeypatch):
    tr, fc = L.trader(tmp_path, monkeypatch, chain=KillOn(tmp_path / "KILL", on="sendTransaction", never_land=True))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr), gate_why=lambda: [])
    assert r["status"] == "refused" and "kill switch" in r["why"] and len(tr.signer.signed) == 1


# ---------------------------------------------------------------- R3: the minimum out at Kraken's mids

def test_the_minimum_out_must_hold_at_krakens_mids(tmp_path, monkeypatch):
    # Jupiter's SOL at 10, Kraken's at 9.81: 1.9 % apart, inside the 2 %; the quote costs 10 bps at Jupiter's
    # prices, but at Kraken's mids 10 USDC are worth 1.019 SOL and the minimum is 0.996 SOL: 2.3 % short.
    tr, fc = L.trader(tmp_path, monkeypatch, kraken=9.81)
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr))
    assert r["status"] == "refused" and "Kraken's mids" in r["why"] and fc.sims == 0 and not fc.sent
    tr, fc = L.trader(tmp_path, monkeypatch, kraken=10.0)
    assert tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr))["status"] == "filled"


# ---------------------------------------------------------------- R4: Jupiter's deployed code, pinned

def test_the_gate_needs_the_pin_and_a_new_deploy_of_jupiter_signs_nothing(tmp_path, monkeypatch):
    g = L.armed(tmp_path)
    (tmp_path / "pin.json").unlink()
    assert any("no pin of Jupiter" in w for w in g.check())
    (tmp_path / "pin.json").write_text(json.dumps({**L.PIN, "slot": "300000000"}))
    assert any("malformed" in w for w in g.check())
    tr, fc = L.trader(tmp_path, monkeypatch)
    fc.acc[L.JUP_DATA] = G.Account(1, G.UPGRADEABLE_LOADER, struct.pack("<IQ", 3, L.JUP_SLOT + 1) + b"\x00")
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr))
    assert r["status"] == "refused" and "deployed again" in r["why"] and not tr.signer.signed and fc.sims == 0
    fc.acc[G.JUPITER] = G.Account(1, G.UPGRADEABLE_LOADER, struct.pack("<I", 2) + X.key(L.A("another programdata")))
    r = tr.execute(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr))
    assert r["status"] == "refused" and "another ProgramData" in r["why"] and not tr.signer.signed
    fc.acc[G.JUPITER] = G.Account(1, X.SYSTEM, b"")
    with pytest.raises(G.Refused, match="not an upgradeable program"):
        tr.prepare(LX.Swap("convert", "USDC", "SOL", 10_000_000), L.view(tr))


def test_the_owner_pins_jupiter_only_with_a_matching_idl(tmp_path, monkeypatch):
    tr, fc = L.trader(tmp_path, monkeypatch)
    from lab.pumpfun_rt import live_exec as PX
    rpc = PX.Rpc("https://rpc.example.org", poster=fc)
    rec = LX.pin(tr.gate, rpc)
    assert {k: rec[k] for k in ("program", "programdata", "slot")} == {k: L.PIN[k] for k in ("program", "programdata", "slot")}
    assert json.loads(LG.pin_path().read_text())["slot"] == L.JUP_SLOT and not fc.sent
    (tmp_path / "jupiter.json").unlink()
    with pytest.raises(G.Refused, match="the IDL first"):
        LX.pin(tr.gate, rpc)


# ---------------------------------------------------------------- R5: our wrapped SOL closed to someone else

def test_a_wrapped_sol_account_closed_to_someone_else_is_refused():
    pb = G.Plan(W, USDC, BTC, 10_000_000, 9, 30, L.ALLOWED)
    held = G.Account(5_000_000_000 + G.ATA_RENT_L, X.TOKEN, L.tok_data(WSOL, W, 5_000_000_000))
    wsol = X.ata(W, WSOL)
    # inside the route our wSOL (5 SOL) is closed, its lamports go elsewhere; the wallet pays only the fee
    pre, post = L._states(sol_after=1_000_000_000 - 34_000, extra_pre={wsol: held},
                          extra_post={wsol: None, X.ata(W, BTC): L.tacc(BTC, W, 20)})
    with pytest.raises(G.Refused, match="SOL fell"):
        G.check_effect(pb, pre, post, 34_000)
    # closed back to the wallet: its lamports arrive, that passes
    pre, post = L._states(sol_after=1_000_000_000 - 34_000 + held.lamports, extra_pre={wsol: held},
                          extra_post={wsol: None, X.ata(W, BTC): L.tacc(BTC, W, 20)})
    assert G.check_effect(pb, pre, post, 34_000)["tok"][X.ata(W, BTC)] == 13


# ---------------------------------------------------------------- R6: --once never opens the wallet file

def test_once_checks_and_writes_the_status_but_never_opens_the_wallet_file(tmp_path, monkeypatch):
    tr, fc = L.trader(tmp_path, monkeypatch)
    svc = SV.Service(gate=tr.gate, trader=tr, load=lambda p: pytest.fail("--once must not open the wallet file"),
                     alerts=False)
    monkeypatch.setattr(SV, "Service", lambda: svc)
    assert SV.main(["--once"]) == 0
    st = json.loads((tmp_path / "reports" / "status.json").read_text())
    assert not st["on"] and any("--once" in w for w in st["gate"]) and not fc.sent
    assert [j for j in LX.read_journal() if j["kind"] == "baseline"] == []     # no new baseline either
