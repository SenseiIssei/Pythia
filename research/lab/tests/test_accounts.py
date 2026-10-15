"""Two autopilot engines, one per Alpaca paper account (main and safe): the URL
list, the merged state for the digest and the chart, the learning loop's
autopilot list and the real money readiness check, against two mock engines
on 127.0.0.1.

No network beyond 127.0.0.1. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from lab import report
from lab.ops import guard, hurdles, learn, notify, readiness

from test_readiness import (DAY_MS, MACRO, NOW, autopilot, clean_history, forward_for, settle, state_of,  # noqa: F401
                            write_history)


def serve(state: dict | None):
    """A mock engine answering GET /api/state with `state` (None: 500)."""

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            if state is None or not self.path.startswith("/api/state"):
                self.send_response(500)
                self.end_headers()
                return
            body = json.dumps(state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/api/state"


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    for mod in (guard, readiness, hurdles, learn):
        monkeypatch.setattr(mod, "ROOT", data)
    monkeypatch.setattr(report, "REPORTS", data / "reports")
    monkeypatch.setenv("PYTHIA_REPORTS", str(data / "reports"))
    monkeypatch.setenv("PYTHIA_DATA", str(data))
    for k in ("PYTHIA_RESULTS", "PYTHIA_ALERT_WEBHOOK", "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_LEARN_ORDERS_FILE",
              "PYTHIA_AUTOPILOT_STATE_URL", "PYTHIA_AUTOPILOT_STATE_URLS"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    guard.WRITTEN.clear()
    return data


@pytest.fixture()
def two(root, monkeypatch):
    """The main engine with ap-1 (40 days, ready) and the safe one with its
    own ap-1 (a different run, 10 days); the list names neither account."""
    main_ap = autopilot(days=40, ap_id="ap-1")
    safe_ap = autopilot(days=10, ap_id="ap-1")
    safe_ap["config"]["name"] = "Small and safe"
    servers = [serve(state_of(main_ap)), serve(state_of(safe_ap))]
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URLS", ",".join(u for _, u in servers))
    yield main_ap, safe_ap, [u for _, u in servers]
    for s, _ in servers:
        s.shutdown()


# ---------------------------------------------------------------- the URL list

def test_the_default_is_both_engines(monkeypatch):
    monkeypatch.delenv("PYTHIA_AUTOPILOT_STATE_URLS", raising=False)
    monkeypatch.delenv("PYTHIA_AUTOPILOT_STATE_URL", raising=False)
    assert notify.state_urls() == [("main", "http://127.0.0.1:8788/api/state"),
                                   ("safe", "http://127.0.0.1:8789/api/state")]


def test_the_old_single_url_still_works(monkeypatch):
    monkeypatch.delenv("PYTHIA_AUTOPILOT_STATE_URLS", raising=False)
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "http://10.0.0.1:9000/api/state")
    assert notify.state_urls() == [("main", "http://10.0.0.1:9000/api/state")]
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    assert notify.state_urls() == []
    assert notify.engine_state() is None
    # The list wins over the single URL.
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URLS", "http://a/api/state")
    assert notify.state_urls() == [("main", "http://a/api/state")]


def test_a_name_parameter_names_the_account_and_is_taken_off(monkeypatch):
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URLS",
                       "http://a/api/state?name=big, http://b/api/state , http://c/api/state?x=1&name=tiny,http://d/api/state")
    assert notify.state_urls() == [("big", "http://a/api/state"), ("safe", "http://b/api/state"),
                                   ("tiny", "http://c/api/state?x=1"), ("account 4", "http://d/api/state")]


# ---------------------------------------------------------------- digest and chart

def test_the_merged_state_labels_every_autopilot_and_skips_a_silent_engine(two, monkeypatch):
    main_ap, safe_ap, urls = two
    merged = notify.engine_state()
    assert [(a["account"], a["config"]["name"]) for a in merged["autopilots"]] == [
        ("main", "Autopilot ap-1"), ("safe", "Small and safe")]
    data = notify.chart_data(merged, None, NOW)
    assert [line["name"] for line in data["autopilots"]] == ["Autopilot ap-1 (main)", "Small and safe (safe)"]
    # The safe engine down: skipped quietly, the main one still there.
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URLS", f"{urls[0]},http://127.0.0.1:9/api/state")
    merged = notify.engine_state(timeout=2)
    assert [a["account"] for a in merged["autopilots"]] == ["main"]
    assert notify.chart_data(merged, None, NOW)["autopilots"][0]["name"] == "Autopilot ap-1"


def test_the_learning_loop_lists_both_accounts_for_the_digest(two):
    rows = learn.engines()
    assert [r["account"] for r in rows] == ["main", "safe"] and all(r["state"] for r in rows)
    aps = learn.autopilot_pnl(notify.merge_states(rows), NOW, lambda ms: 60_000.0)
    assert sorted((a["account"], a["name"]) for a in aps) == [("main", "Autopilot ap-1"), ("safe", "Small and safe")]
    parts, snap, _, _ = notify.autopilot_parts({"autopilots": aps}, {}, NOW)
    assert sorted(p.title for p in parts) == ["Autopilot ap-1 · main · demo", "Small and safe · safe · demo"]
    # The same id on two accounts does not share tomorrow's snapshot.
    assert set(snap) == {"ap-1", "safe:ap-1"}


def test_the_weekly_card_keeps_the_accounts_apart(two):
    card, snap = notify.weekly_card(notify.engine_state(), {}, NOW, 1.0)
    assert set(snap) == {"ap-1", "safe:ap-1"}
    assert "Small and safe · safe · demo" in [p.title for p in card.parts if hasattr(p, "rows")]


# ---------------------------------------------------------------- readiness

def test_readiness_judges_both_accounts_each_on_its_own_record(two):
    main_ap, safe_ap, urls = two
    settle(None)
    write_history(clean_history(8))
    fwd = {**forward_for(main_ap), "engine": {"url": urls[0]}}
    rep = readiness.run(NOW, forward=fwd, macro=MACRO, sender=lambda t: (True, None))
    by = {i["account"]: i for i in rep["autopilots"]}
    assert set(by) == {"main", "safe"}
    assert by["main"]["ready"] and by["main"]["name"] == "Autopilot ap-1"
    assert by["safe"]["name"] == "Small and safe (safe)" and not by["safe"]["ready"]
    assert by["main"]["key"] != by["safe"]["key"]
    # The forward report reads the main engine only: the safe one has no band, so 15 more days.
    safe_band = next(r for r in by["safe"]["rules"] if r["id"] == "band")
    assert safe_band["pass"] and "does not read the safe account" in safe_band["detail"]
    assert by["safe"]["need_days"] == 38 + 15
    # The safe account has no reconciliation record of its own before today.
    safe_rec = next(r for r in by["safe"]["rules"] if r["id"] == "reconcile")
    assert not safe_rec["pass"] and safe_rec["value"] == "1/7 days"
    # Its day is recorded under its own key.
    last = readiness.read_history()[-1]
    assert set(last["autopilots"]) == {"ap-1", "safe:ap-1"} and set(last["reconcile"]) == {"main", "safe"}


def test_a_mismatch_on_the_safe_account_does_not_hold_back_the_main_one(root):
    main_ap, safe_ap = autopilot(ap_id="m"), autopilot(ap_id="s")
    settle(root)
    history = clean_history(8)
    for h in history:
        h["reconcile"] = {"main": h["reconcile"], "safe": dict(h["reconcile"])}
    write_history(history)
    rows = [{"account": "main", "url": "u1", "state": state_of(main_ap), "error": None},
            {"account": "safe", "url": "u2", "state": state_of(safe_ap, mismatches=2), "error": None}]
    fwd = forward_for(main_ap)
    rep = readiness.run(NOW, engines_=rows, forward=fwd, macro=MACRO, sender=lambda t: (True, None))
    rec = {i["account"]: next(r for r in i["rules"] if r["id"] == "reconcile") for i in rep["autopilots"]}
    assert rec["main"]["pass"] and not rec["safe"]["pass"]


def test_an_account_that_is_down_keeps_its_ready_state(root):
    a, b = autopilot(ap_id="m"), autopilot(ap_id="s", days=60)
    settle(root)
    history = clean_history(8)
    for h in history:
        h["reconcile"] = {"main": h["reconcile"], "safe": dict(h["reconcile"])}
    write_history(history)
    posts: list[str] = []

    def rows(at, safe_up=True):
        return [{"account": "main", "url": "u1", "state": state_of(a, at=at), "error": None},
                {"account": "safe", "url": "u2", "state": state_of(b, at=at) if safe_up else None,
                 "error": None if safe_up else "URLError"}]

    def go(at, safe_up=True):
        return readiness.run(at, engines_=rows(at, safe_up), forward=forward_for(a, at=at), macro=MACRO,
                             sender=lambda t: (posts.append(t) or True, None))

    rep = go(NOW)
    assert {i["account"]: i["ready"] for i in rep["autopilots"]} == {"main": True, "safe": True}
    assert len(posts) == 2
    rep = go(NOW + DAY_MS, safe_up=False)
    assert [i["account"] for i in rep["autopilots"]] == ["main"] and rep["status"] == "ok"
    # Back the day after: not announced again.
    go(NOW + 2 * DAY_MS)
    assert len(posts) == 2
