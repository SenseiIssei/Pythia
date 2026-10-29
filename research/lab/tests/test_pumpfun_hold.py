"""live.Hold: rows of a coin the engine does not know wait for its creation and follow it in order; a row the engine
fails on is skipped alone (2026-10-29: one failing row dropped the rest of the coin's rows). No network.

Run from research/lab:  python -m pytest tests/test_pumpfun_hold.py
"""

from __future__ import annotations

from types import SimpleNamespace

from lab.pumpfun_rt.live import Hold


def test_held_rows_follow_the_creation_and_one_bad_row_drops_only_itself():
    eng = SimpleNamespace(tokens={})
    fed = []

    def feed(table, row):
        if row.get("bad"):
            raise ValueError("math domain error")
        fed.append((table, row["n"]))
    h = Hold(eng, feed, clock=lambda: 0.0)
    for n in range(4):
        assert h.row("trades", {"mint": "M", "n": n, "bad": n == 1})
    assert not h.row("creates", {"mint": "M"}) and not h.row("trades", {"mint": None, "n": 9})
    eng.tokens["M"] = object()
    h.release(["M"])
    assert fed == [("trades", 0), ("trades", 2), ("trades", 3)] and h.errors == 1 and not h.held


def test_rows_too_old_are_dropped_and_a_lost_migration_is_said():
    eng = SimpleNamespace(tokens={})
    now = {"t": 0.0}
    lost = []
    h = Hold(eng, lambda t, r: None, on_lost=lost.append, hold_ms=1000, clock=lambda: now["t"])
    h.row("other", {"mint": "A", "kind": "migrate"})
    h.row("trades", {"mint": "B"})
    now["t"] = 2.0
    h.purge()
    assert lost == ["A"] and not h.held
