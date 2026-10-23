"""The on-chain trader's watcher (research/ops/onchain_live_watch.py): quiet before anything was started,
what counts as a problem, hanging swaps, each posted once and then hourly, and the all clear.

Run from research/lab:  python -m pytest tests/test_onchain_live_watch.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_p = Path(__file__).resolve().parents[2] / "ops" / "onchain_live_watch.py"
if not _p.exists():                                     # the lab code alone (a deploy), without research/ops
    pytest.skip("research/ops is not next to the lab", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("onchain_live_watch", _p)
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

NOW = 1_792_712_000.0


def status(**over):
    s = {"t": NOW * 1000 - 10_000, "running": True, "on": True, "mode": "test", "gate": [], "kill": False,
         "stops": {"daily": False, "total": False}, "reconcile": {"t": 1, "ok": True, "diffs": []}, "frozen": [],
         "simulate": {"t": NOW * 1000 - 3 * 3_600_000, "ok": True}}
    s.update(over)
    return s


def test_quiet_until_the_owner_ever_started_it_and_quiet_when_all_is_well():
    assert W.problems(None, "missing", [], NOW) == {}
    assert W.problems(status(), "running", [], NOW) == {}


def test_each_problem():
    assert "down" in W.problems(status(), "stopped", [], NOW)
    assert "down" in W.problems(status(), "missing", [], NOW)
    assert "status" in W.problems(None, "running", [], NOW)
    assert "stale" in W.problems(status(t=NOW * 1000 - 600_000), "running", [], NOW)
    off = W.problems(status(on=False, gate=["PYTHIA_ONCHAIN_LIVE is not 1"]), "running", [], NOW)
    assert "PYTHIA_ONCHAIN_LIVE" in off["off"]
    assert "Notschalter" in W.problems(status(on=False, kill=True), "running", [], NOW)["off"]
    assert "daily" in W.problems(status(stops={"daily": True, "total": False}), "running", [], NOW)
    assert "total" in W.problems(status(stops={"daily": False, "total": True}), "running", [], NOW)
    assert "sim" in W.problems(status(simulate={"t": NOW * 1000, "ok": False}), "running", [], NOW)
    assert "sim" in W.problems(status(simulate={"t": NOW * 1000 - 21 * 3_600_000, "ok": True}), "running", [], NOW)
    led = W.problems(status(reconcile={"ok": False, "diffs": ["BTC: 5 raw units fewer"]}), "running", [], NOW)
    assert "BTC" in led["ledger"]
    assert "frozen" in W.problems(status(frozen=["x"]), "running", [], NOW)


def test_a_swap_sent_long_ago_without_a_result_is_hanging():
    t = (NOW - 600) * 1000
    sent = {"t": t, "what": "sent", "sig": "s1"}
    assert W.hanging([sent], NOW) == ["s1"]
    assert W.hanging([sent, {"t": t, "what": "filled", "sig": "s1"}], NOW) == []
    assert W.hanging([sent, {"t": t, "what": "expired", "sig": "s1"}], NOW) == []
    assert W.hanging([{"t": NOW * 1000 - 5_000, "what": "sent", "sig": "s2"}], NOW) == []
    assert "hang" in W.problems(status(), "running", [sent], NOW)


def test_posted_once_then_hourly_and_the_all_clear():
    found = {"down": "x"}
    posts, st = W.decide(found, {}, NOW)
    assert posts == [("On-Chain-Wallet: Achtung", "x")]
    assert W.decide(found, st, NOW + 60)[0] == []
    assert len(W.decide(found, st, NOW + 3_600)[0]) == 1
    posts, _ = W.decide({}, st, NOW + 120)
    assert posts == [("On-Chain-Wallet: wieder in Ordnung", "Der On-Chain-Händler läuft wieder normal.")]
