"""The operator notifications: the daily digest and the health alarm, against a mock webhook.

No network beyond 127.0.0.1. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from lab.ops import notify

NOW = int(datetime(2026, 10, 14, 6, 50, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture()
def hook():
    """A webhook on 127.0.0.1 that records each JSON body; `status` sets its answer."""
    got: list[dict] = []
    state = {"status": 204}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            got.append(json.loads(self.rfile.read(n)))
            self.send_response(state["status"])
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/hook/secret-token", got, state
    srv.shutdown()


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    monkeypatch.delenv("PYTHIA_REPORTS", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_FORMAT", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_PREFIX", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    return tmp_path


def learn_report(trades=12, fees=3.5, equity=1_030.0):
    return {
        "generated": "2026-10-14 06:30 UTC", "generated_ms": NOW - 20 * 60_000,
        "headline": "2 cost updates; 1 autopilot running, best +1.50 points against BTC since start.",
        "engine": {"reachable": True, "error": None},
        "autopilots": [
            {"id": "ap1", "name": "Momentum", "mode": "demo", "state": "running", "equity": equity,
             "start_capital": 1_000.0, "fees": fees, "trades": trades, "pnl_day_pct": 1.0, "btc_day_pct": 0.5,
             "pnl_total_pct": (equity / 1_000 - 1) * 100, "btc_total_pct": 1.5, "vs_btc_total_pts": 1.5},
            {"id": "ap0", "name": "Old one", "mode": "demo", "state": "stopped", "equity": 900.0,
             "start_capital": 1_000.0, "fees": 1, "trades": 3},
        ],
    }


FORWARD = {"generated": "2026-10-14 06:15 UTC",
           "books": [{"name": "tsmom", "status": "on_track"}, {"name": "m4_ls", "status": "watch"},
                     {"name": "picks_ls", "status": "early"}]}

HEALTH_OK = {"at": "2026-10-14T06:07:00Z", "ok": True, "checks": [{"name": "disk", "ok": True, "detail": "90 GB free"}]}


def health_bad(at: str) -> dict:
    return {"at": at, "ok": False, "checks": [{"name": "disk", "ok": True, "detail": "90 GB free"},
                                              {"name": "paper tsmom", "ok": False, "detail": "last row none"}]}


def write(root: Path, rel: str, data: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))


def test_digest_says_what_the_money_did():
    text, snap = notify.digest(learn_report(), FORWARD, HEALTH_OK, {}, NOW)
    assert text.startswith("Pythia daily 2026-10-14")
    assert "Running autopilots: 1, together +$10.20 today." in text
    assert "- Momentum (demo): equity $1,030.00, today +$10.20 (+1.00 %), since start +$30.00 (+3.00 %)" in text
    assert "vs BTC +1.50 pts (BTC +1.50 %)" in text
    assert "12 trades, fees $3.50 since start" in text, "no snapshot yet: totals, said as such"
    assert "Old one" not in text, "only running autopilots"
    assert "Forward test (2026-10-14 06:15 UTC): tsmom on track, m4_ls watch, picks_ls early." in text
    assert "Health: all green." in text
    assert "Learning loop: 2 cost updates" in text
    assert snap == {"ap1": {"trades": 12, "fees": 3.5, "at": NOW}}
    assert "\u2014" not in text and len(text) <= notify.MAX_CHARS


def test_trades_and_fees_today_come_from_yesterdays_snapshot():
    prev = {"ap1": {"trades": 9, "fees": 2.25, "at": NOW - 86_400_000}}
    text, _ = notify.digest(learn_report(), FORWARD, HEALTH_OK, prev, NOW)
    assert "today 3 trades, fees $1.25" in text
    old = {"ap1": {"trades": 9, "fees": 2.25, "at": NOW - 3 * 86_400_000}}
    assert "since start" in notify.digest(learn_report(), FORWARD, HEALTH_OK, old, NOW)[0].split("Momentum")[1]


def test_losses_red_health_and_a_stale_report_are_said():
    rep = learn_report(equity=950.0)
    rep["autopilots"][0]["pnl_day_pct"] = -2.0
    rep["generated_ms"] = NOW - 2 * 86_400_000
    text, _ = notify.digest(rep, None, health_bad("2026-10-14T06:07:00Z"), {}, NOW)
    assert "today -$19.39 (-2.00 %), since start -$50.00 (-5.00 %)" in text
    assert "not today's" in text
    assert "Forward test: no report." in text
    assert "Health: 1 red: paper tsmom (last row none)" in text


def test_digest_is_clipped_under_the_limit():
    rep = learn_report()
    rep["autopilots"] = [dict(rep["autopilots"][0], id=f"a{i}", name=f"Autopilot number {i}") for i in range(40)]
    text, _ = notify.digest(rep, FORWARD, HEALTH_OK, {}, NOW)
    assert len(text) <= 1800
    assert text.endswith("(more in the reports)")


@pytest.mark.parametrize("fmt,key", [("discord", "content"), ("slack", "text")])
def test_daily_posts_to_the_webhook_in_its_format(hook, data, monkeypatch, capsys, fmt, key):
    url, got, _ = hook
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    monkeypatch.setenv("PYTHIA_ALERT_FORMAT", fmt)
    write(data, "reports/learn/latest.json", learn_report())
    write(data, "reports/forward/latest.json", FORWARD)
    write(data, "_health/system.json", HEALTH_OK)
    assert notify.daily(now_ms=NOW) == 0
    assert len(got) == 1 and list(got[0]) == [key]
    assert got[0][key].startswith("Pythia daily")
    st = json.loads((data / "notify" / "state.json").read_text())
    assert st["autopilots"]["ap1"]["trades"] == 12
    assert "secret-token" not in capsys.readouterr().out + json.dumps(st)


def test_a_failed_post_is_reported_without_the_url(hook, data, monkeypatch, capsys):
    url, got, state = hook
    state["status"] = 500
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    assert notify.daily(now_ms=NOW) == 1
    err = capsys.readouterr().err
    assert "HTTP 500" in err and "secret-token" not in err
    assert not (data / "notify" / "state.json").exists()
    ok, why = notify.post("http://127.0.0.1:9/secret-token", "discord", "x", timeout=2)
    assert not ok and "secret-token" not in why


def test_without_a_webhook_it_only_prints(data, capsys):
    assert notify.daily(now_ms=NOW) == 0
    out = capsys.readouterr().out
    assert "Learning loop: no report found." in out and "printed only" in out


def test_health_posts_once_after_two_bad_runs_and_once_when_green(hook, data, monkeypatch):
    url, got, _ = hook
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    sysj = data / "_health" / "system.json"

    def run(d):
        write(data, "_health/system.json", d)
        assert notify.main(["--health", str(sysj)]) == 0

    run(HEALTH_OK)
    run(health_bad("2026-10-14T07:07:00Z"))
    assert got == [], "one bad run stays quiet"
    assert notify.main(["--health", str(sysj)]) == 0
    assert got == [], "the same run read twice counts once"
    run(health_bad("2026-10-14T08:07:00Z"))
    assert len(got) == 1
    assert got[0]["content"].startswith("Pythia Health check not ok for 2 runs in a row")
    assert "- paper tsmom: last row none" in got[0]["content"]
    run(health_bad("2026-10-14T09:07:00Z"))
    assert len(got) == 1, "posted once per episode"
    run(dict(HEALTH_OK, at="2026-10-14T10:07:00Z"))
    assert len(got) == 2 and "all green again" in got[1]["content"]
    run(health_bad("2026-10-14T11:07:00Z"))
    run(dict(HEALTH_OK, at="2026-10-14T12:07:00Z"))
    assert len(got) == 2, "a single bad run and its recovery stay quiet"


def test_health_retries_when_the_post_fails(hook, data, monkeypatch):
    url, got, state = hook
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    sysj = data / "_health" / "system.json"
    state["status"] = 503
    for at in ("2026-10-14T07:07:00Z", "2026-10-14T08:07:00Z"):
        write(data, "_health/system.json", health_bad(at))
        notify.main(["--health", str(sysj)])
    assert len(got) == 1
    state["status"] = 204
    write(data, "_health/system.json", health_bad("2026-10-14T09:07:00Z"))
    assert notify.main(["--health", str(sysj)]) == 0
    assert len(got) == 2, "not marked as posted until it went through"
