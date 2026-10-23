"""The live bot's watcher (research/ops/pumpfun_live_watch.py): what counts as a problem, that each
is posted once and then hourly, and the all clear.

Run from research/lab:  python -m pytest tests/test_pumpfun_live_watch.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_p = Path(__file__).resolve().parents[2] / "ops" / "pumpfun_live_watch.py"
if not _p.exists():                                     # the lab code alone (a deploy), without research/ops
    pytest.skip("research/ops is not next to the lab", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("pumpfun_live_watch", _p)
W = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(W)

NOW = 1_792_712_000.0


def status(**over):
    s = {"t": NOW * 1000 - 10_000, "running": True, "on": True, "mode": "test", "gate": [], "refusing": None,
         "stops": {"daily": False, "total": False}, "kill": False, "positions": [], "leftovers": [],
         "simulate": {"t": NOW * 1000 - 3 * 3_600_000, "ok": True}}
    s.update(over)
    return s


def test_a_bot_that_trades_has_no_problem():
    assert W.problems(status(), True, NOW) == {}


def test_down_stale_off_and_its_reason():
    assert "down" in W.problems(status(), False, NOW)
    assert "stale" in W.problems(status(t=NOW * 1000 - 600_000), True, NOW)
    off = W.problems(status(on=False, stops={"daily": True, "total": False}), True, NOW)
    assert "Tagesverlust" in off["off"]
    assert "Notschalter" in W.problems(status(on=False, kill=True), True, NOW)["off"]
    assert "Gesamtbudget" in W.problems(status(on=False, stops={"daily": False, "total": True}), True, NOW)["off"]
    assert "the gate" in W.problems(status(on=False, gate=["the gate"]), True, NOW)["off"]
    assert W.problems(None, True, NOW) == {"status": "Kein Status vom Live-Bot lesbar."}


def test_the_test_gate_is_warned_before_it_shuts():
    assert "sim" in W.problems(status(simulate={"t": NOW * 1000 - 21 * 3_600_000, "ok": True}), True, NOW)
    assert "sim" in W.problems(status(simulate={"t": NOW * 1000, "ok": False}), True, NOW)


def test_stuck_positions_and_leftovers():
    p = W.problems(status(positions=[{"state": "stuck", "symbol": "TST"}], leftovers=[{"pid": 1}]), True, NOW)
    assert "TST" in p["stuck"] and "1 Position" in p["leftovers"]


def test_posted_once_then_hourly_then_all_clear():
    posts, st = W.decide({"down": "x"}, {}, NOW)
    assert posts == [("pump.fun Live-Bot: Achtung", "x")]
    posts, st = W.decide({"down": "x"}, st, NOW + 120)
    assert posts == []
    posts, st = W.decide({"down": "x"}, st, NOW + W.REPEAT_S + 1)
    assert len(posts) == 1
    posts, st = W.decide({}, st, NOW + W.REPEAT_S + 121)
    assert posts == [("pump.fun Live-Bot: wieder in Ordnung", "Er läuft und handelt wieder normal.")]
    assert W.decide({}, st, NOW + W.REPEAT_S + 240)[0] == []                 # said once


def test_a_dry_run_posts_nothing_and_writes_nothing(tmp_path, capsys):
    (tmp_path / "reports" / "pumpfun_rt").mkdir(parents=True)
    assert W.main(["--data", str(tmp_path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "[dry-run] pump.fun Live-Bot: Achtung" in out
    assert not (tmp_path / "_health").exists()


def test_a_post_is_urgent_so_quiet_hours_never_hold_it(monkeypatch):
    calls = []
    monkeypatch.setattr(W.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    W.post("t", "x", dry=False)
    cmd = calls[0]
    assert cmd[2:] == ["--urgent", "--event", "risk", "t", "x"]


def test_on_but_every_buy_refused_by_the_daily_limit_is_a_problem():
    s = status(pnl_today_sol=-0.1276, stake={"sol": 0.05}, limits={"max_daily_loss_sol": 0.1854})
    assert "Tageslimit" in W.problems(s, True, NOW)["daylimit"]
    assert "daylimit" not in W.problems(status(pnl_today_sol=-0.05, stake={"sol": 0.05},
                                               limits={"max_daily_loss_sol": 0.1854}), True, NOW)
    held = status(pnl_today_sol=-0.1276, stake={"sol": 0.05}, limits={"max_daily_loss_sol": 0.1854},
                  positions=[{"state": "open"}])
    assert "daylimit" not in W.problems(held, True, NOW), "with a position open it is only waiting"


def test_with_limits_wallet_no_alarm_about_limits_that_do_not_exist_but_a_too_small_wallet_is_said():
    wl = {"kind": "wallet", "max_trade_sol": 0.45, "max_daily_loss_sol": None, "max_total_sol": None}
    s = status(pnl_today_sol=-3.0, stake={"sol": 0.45}, limits=wl, control={"limits": "wallet", "paused": False})
    assert W.problems(s, True, NOW) == {}                   # a big day's loss: no daily limit, no alarm
    low = status(on=False, refusing="stake paused: wallet under 0.25 SOL", limits=wl,
                 low={"have": 0.2, "need": 0.25, "unit": "SOL"})
    p = W.problems(low, True, NOW)
    assert set(p) == {"low"} and "0.200 SOL" in p["low"] and "0.250 SOL" in p["low"]


def test_the_owners_pause_is_no_alarm_but_the_kill_switch_still_is():
    paused = status(on=False, refusing="paused by the owner since 14:05 UTC", control={"paused": True})
    assert W.problems(paused, True, NOW) == {}
    assert "off" in W.problems(status(on=False, refusing="paused by the owner since 14:05 UTC",
                                      control={"paused": False}), True, NOW)
    assert "down" in W.problems(paused, False, NOW)          # a stopped container is still said
