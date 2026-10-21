"""Messages to the owner: the card design, escaping, quiet hours, the switches,
the daily digest, the weekly report and the health alarm, against a mock
Telegram on 127.0.0.1.

No network beyond 127.0.0.1. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
import math
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from lab.ops import notify

NOW = int(datetime(2026, 10, 14, 6, 50, tzinfo=timezone.utc).timestamp() * 1000)


def utc(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


@pytest.fixture()
def hook():
    """A webhook on 127.0.0.1 that records each post as (path, JSON body or
    the raw multipart bytes of a photo); `status` sets its answer, `status400`
    answers 400 to the first post with parse_mode (an HTML Telegram refuses)."""
    got: list[tuple[str, object]] = []
    state = {"status": 204, "status400": False}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            if (self.headers.get("Content-Type") or "").startswith("multipart/"):
                got.append((self.path, raw))
            else:
                body = json.loads(raw)
                got.append((self.path, body))
                if state["status400"] and "parse_mode" in body:
                    state["status400"] = False
                    self.send_response(400)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
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
    for k in ("PYTHIA_REPORTS", "PYTHIA_ALERT_FORMAT", "PYTHIA_ALERT_PREFIX", "PYTHIA_ALERT_WEBHOOK",
              "PYTHIA_TELEGRAM_BOT_TOKEN", "PYTHIA_TELEGRAM_CHAT_ID", "PYTHIA_ALERT_VIA", "PYTHIA_ALERT_EVENT_URL"):
        monkeypatch.delenv(k, raising=False)
    # No engine and no Binance in tests; quiet hours only where a test sets them.
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    monkeypatch.setattr(notify, "btc_closes", lambda a, b, timeout=15: [])
    return tmp_path


@pytest.fixture()
def telegram(hook, data, monkeypatch):
    """The mock as a Telegram chat: HTML posts with the chat id."""
    url, got, state = hook
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    monkeypatch.setenv("PYTHIA_ALERT_FORMAT", "telegram")
    monkeypatch.setenv("PYTHIA_TELEGRAM_CHAT_ID", "4242")
    return url, got, state


def texts(got) -> list[str]:
    return [b["text"] if "text" in b else b.get("content") for _, b in got if isinstance(b, dict)]


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


def write(root: Path, rel: str, d) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")


def balanced(html: str) -> bool:
    return all(html.count(f"<{t}>") == html.count(f"</{t}>") for t in ("b", "i", "pre"))


# ---------------------------------------------------------------- the card design

def test_numbers_have_signs_separators_and_percent():
    assert notify.money(12345.678) == "$12,345.68"
    assert notify.money(-12.3) == "-$12.30"
    assert notify.money(-0.001) == "$0.00", "no minus zero"
    assert notify.signed_money(1234.5) == "+$1,234.50"
    assert notify.signed_money(-87.654) == "-$87.65"
    assert notify.signed_pct(1.234) == "+1.23 %"
    assert notify.signed_pct(-0.004) == "+0.00 %"
    assert notify.signed_pct(None) == "n/a"
    assert (notify.dot(2), notify.dot(-2), notify.dot(0), notify.dot(None)) == ("🟢", "🔴", "⚪", "")


def test_a_card_is_title_summary_aligned_numbers_and_footer():
    card = notify.Card("🛑", "Momentum stopped", "Max loss reached.",
                       [notify.Rows([("Equity", "$9,412.30"), ("P&L", "-$587.70 -5.88 %", -587.7), ("Trades", "14")])],
                       footer="Pythia")
    assert card.render() == ("<b>🛑 Momentum stopped</b>\nMax loss reached.\n"
                             "<pre>Equity         $9,412.30\nP&amp;L     -$587.70 -5.88 % 🔴\nTrades                14</pre>\n"
                             "<i>Pythia</i>")
    assert card.render("discord").startswith("**🛑 Momentum stopped**\nMax loss reached.\n```\nEquity")
    assert card.render("slack").endswith("```\n_Pythia_")


def test_everything_is_escaped_for_telegram_html():
    card = notify.Card("🧪", "<script>&", "a < b & c > d",
                       [notify.Rows([("A&B", "<1>")], "Head <x>"), notify.Line("x & y", "Lead <z>"),
                        notify.Table(["<h>"], [["<c>"]])], footer="f & g")
    html = card.render()
    assert "<script>" not in html and "&lt;script&gt;&amp;" in html
    assert "a &lt; b &amp; c &gt; d" in html
    assert "<b>Head &lt;x&gt;</b>" in html and "<pre>A&amp;B  &lt;1&gt;</pre>" in html
    assert "<b>Lead &lt;z&gt;</b> x &amp; y" in html
    assert "<i>f &amp; g</i>" in html
    # Only the card's own tags are left once the escaped text is taken out.
    assert set(re.findall(r"</?[a-z]+>", html)) <= {"<b>", "</b>", "<i>", "</i>", "<pre>", "</pre>"}


def test_tables_put_words_left_and_numbers_right_and_long_posts_fit():
    t = notify.Table(["Coin", "Value"], [["BTC", "$1,220"], ["PEPE", "$80"]])
    assert t.block() == "Coin  Value\nBTC  $1,220\nPEPE    $80"
    big = notify.Card("🔁", "Rebalance", "60 trades", [notify.Table(["Coin", "Value"], [[f"C{i}", f"${i}"] for i in range(400)])])
    many = [notify.Card("🔔", f"Note {i}", "x" * 300) for i in range(30)]
    html = notify.render_post([big] + many)
    assert len(html) <= notify.MAX_CHARS and balanced(html)
    assert "more</pre>" in html and "more in the app" in html


# ---------------------------------------------------------------- settings and quiet hours

def test_quiet_hours_are_berlin_time_over_midnight(data, monkeypatch):
    monkeypatch.delenv("PYTHIA_QUIET_HOURS")
    s = notify.load_settings()
    assert s["quiet"] == notify.DEFAULT_QUIET
    # Summer time in October until the 25th: UTC+2.
    assert notify.in_quiet(s, utc(2026, 10, 14, 21, 0)), "23:00 Berlin"
    assert not notify.in_quiet(s, utc(2026, 10, 14, 20, 59)), "22:59 Berlin"
    assert notify.in_quiet(s, utc(2026, 10, 15, 4, 59)), "06:59 Berlin"
    assert not notify.in_quiet(s, utc(2026, 10, 15, 5, 0)), "07:00 Berlin"
    # Winter time: UTC+1.
    assert notify.in_quiet(s, utc(2026, 12, 1, 22, 0)) and not notify.in_quiet(s, utc(2026, 12, 1, 21, 30))
    assert notify.local_time(utc(2026, 3, 29, 0, 59)).hour == 1 and notify.local_time(utc(2026, 3, 29, 1, 0)).hour == 3
    # The engine's settings file, and the environment over it.
    write(data, "reports/notify/settings.json", {
        "categories": [{"id": "trending", "on": False}, {"id": "weekly", "on": True}],
        "quietHours": {"enabled": True, "start": "12:00", "end": "14:00", "timezone": "Europe/Berlin"}})
    s = notify.load_settings()
    assert not notify.enabled(s, "trending") and notify.enabled(s, "weekly") and notify.enabled(s, "cs2")
    assert notify.in_quiet(s, utc(2026, 10, 14, 10, 30)) and not notify.in_quiet(s, utc(2026, 10, 14, 21, 30))
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    assert not notify.in_quiet(notify.load_settings(), utc(2026, 10, 14, 10, 30))
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "22:00-06:00")
    assert notify.in_quiet(notify.load_settings(), utc(2026, 10, 14, 20, 30))


def test_a_switched_off_category_is_not_sent(telegram, data):
    _, got, _ = telegram
    write(data, "reports/notify/settings.json", {"categories": [{"id": "cs2", "on": False}]})
    res = notify.send("cs2", notify.Card("🎮", "AK-47 Redline +12 %"), now=NOW)
    assert res["reason"] == "off" and not res["delivered"] and got == []
    res = notify.send("cs2", notify.Card("🎮", "Urgent one"), now=NOW, urgent=True)
    assert res["delivered"] and len(got) == 1


def test_quiet_hours_hold_lab_posts_and_list_them_after(telegram, data, monkeypatch):
    _, got, _ = telegram
    monkeypatch.delenv("PYTHIA_QUIET_HOURS")
    night = utc(2026, 10, 14, 22, 30)  # 00:30 Berlin
    res = notify.send("trending", notify.Card("🔥", "BONK on Alpaca +25% in 24h"), now=night)
    assert res["reason"] == "quiet" and got == []
    notify.send("listings", notify.Card("🆕", "New on Kraken: ZK"), now=night + 3_600_000)
    assert notify.pending(now_ms=night + 2 * 3_600_000) == 0
    assert got == [], "still quiet"
    morning = utc(2026, 10, 15, 5, 5)  # 07:05 Berlin
    assert notify.pending(now_ms=morning) == 0
    assert len(got) == 1
    text = texts(got)[0]
    assert text.startswith("<b>🌙 Quiet hours are over</b>\n2 lab posts were held back from 23:00 to 07:00."), text
    assert "\n<b>Trending</b> BONK on Alpaca +25% in 24h\n<b>Listings</b> New on Kraken: ZK" in text, text
    assert not notify.held_path().exists()
    assert notify.pending(now_ms=morning + 60_000) == 0 and len(got) == 1, "said once"


def test_telegram_posts_html_and_a_refused_html_is_resent_as_plain_text(telegram):
    _, got, state = telegram
    state["status400"] = True
    res = notify.send("studies", notify.Card("🧪", "Factory <run>", "a & b"), now=NOW)
    assert res["delivered"]
    assert len(got) == 2
    assert got[0][1]["parse_mode"] == "HTML" and got[0][1]["chat_id"] == "4242"
    assert got[0][1]["text"].startswith("<b>🧪 Factory &lt;run&gt;</b>")
    assert "parse_mode" not in got[1][1] and got[1][1]["text"].startswith("🧪 Factory <run>\na & b")


def test_telegram_needs_token_and_chat_and_carries_the_chat_id(monkeypatch):
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    monkeypatch.setenv("PYTHIA_TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("PYTHIA_TELEGRAM_CHAT_ID", raising=False)
    assert notify.config()[0] is None
    monkeypatch.setenv("PYTHIA_TELEGRAM_CHAT_ID", "4242")
    url, fmt, _ = notify.config()
    assert fmt == "telegram" and url == "https://api.telegram.org/bot123:abc/sendMessage"
    assert notify.body(fmt, "<b>hi</b>") == {"chat_id": "4242", "text": "<b>hi</b>", "parse_mode": "HTML",
                                             "disable_web_page_preview": True}


def test_via_engine_posts_the_card_as_an_event(hook, data, monkeypatch):
    url, got, _ = hook
    monkeypatch.setenv("PYTHIA_ALERT_VIA", "engine")
    monkeypatch.setenv("PYTHIA_ALERT_EVENT_URL", url)
    card = notify.Card("🧪", "Factory 2026-10-17", "3 survived.",
                       [notify.Rows([("Tried", "120"), ("Best", "+1.40", 1.4)]), notify.Table(["Name", "Sharpe"], [["a", "1.4"]])])
    res = notify.send("studies", card, now=NOW)
    assert res["delivered"]
    ev = got[0][1]
    assert ev["category"] == "studies" and ev["title"] == "Factory 2026-10-17" and ev["text"] == "3 survived."
    assert ev["rows"] == [{"label": "Tried", "value": "120"}, {"label": "Best", "value": "+1.40", "sign": 1.4}]
    assert ev["table"] == {"header": ["Name", "Sharpe"], "rows": [["a", "1.4"]]}
    # A digest (several blocks, lines of words) is more than an event holds: straight to the chat.
    digest, _ = notify.digest_card(learn_report(), FORWARD, HEALTH_OK, {}, NOW)
    assert not notify.fits_event([digest]) and notify.fits_event([card])


# ---------------------------------------------------------------- the daily digest

def test_digest_says_what_the_money_did():
    text, snap = notify.digest(learn_report(), FORWARD, HEALTH_OK, {}, NOW)
    assert text.startswith("<b>📊 Daily · Wed 14 Oct</b>\n1 autopilot running, +$10.20 today 🟢 · BTC 24 h +0.50 %\n"), text
    # One table, one row per autopilot: value, today, since start, against BTC since start.
    assert "<pre>Autopilot Value Today Start  ±BTC\nMomentum  1,030 +1.00 +3.00 +1.50</pre>" in text, text
    assert "Value in $, Today and Start in %, ±BTC in points against BTC since start; all demo" in text
    assert "<b>Since start</b> 12 positions closed · fees $3.50" in text, "no snapshot yet: totals, said as such"
    assert "Old one" not in text, "only running autopilots"
    assert "<b>Forward test</b> tsmom ✅ on track · m4_ls 👀 watch · picks_ls 🌱 early" in text
    assert "<b>Health</b> ✅ all green" in text
    assert "<b>Learning</b> 2 cost updates" in text
    assert snap == {"ap1": {"equity": 1030.0, "start": 1000.0, "trades": 12, "fees": 3.5, "at": NOW}}
    assert text.count("\n") <= 12, "short enough for a phone"
    assert "\u2014" not in text and len(text) <= notify.MAX_CHARS and balanced(text)


def test_the_table_also_holds_each_autopilot_against_btc_above_its_200_day_average(monkeypatch):
    rep = learn_report()
    rep["autopilots"][0].update(btc_gated_total_pct=0.0, vs_gated_total_pts=3.0)
    text, _ = notify.digest(rep, FORWARD, HEALTH_OK, {}, NOW)
    assert "<pre>Autopilot Value Today Start  ±BTC    ±G\nMomentum  1,030 +1.00 +3.00 +1.50 +3.00</pre>" in text, text
    assert "±G against BTC held only above its 200-day average; all demo" in text, text
    monkeypatch.setenv("PYTHIA_ALERT_LANG", "de")
    text, _ = notify.digest(rep, FORWARD, HEALTH_OK, {}, NOW)
    assert "±G gegenüber BTC nur über seinem 200-Tage-Schnitt" in text, text
    # A report without the number (older engine, no calendar): no column, as before.
    text, _ = notify.digest(learn_report(), FORWARD, HEALTH_OK, {}, NOW)
    assert "±G" not in text


def test_today_and_its_trades_come_from_yesterdays_snapshot():
    prev = {"ap1": {"equity": 1_020.0, "start": 1_000.0, "trades": 9, "fees": 2.25, "orders": 20,
                    "at": NOW - 86_400_000}}
    rep = learn_report()
    rep["autopilots"][0]["orders"] = 26
    text, _ = notify.digest(rep, FORWARD, HEALTH_OK, prev, NOW)
    assert "+$10.00 today" in text and "Momentum  1,030 +0.98 +3.00 +1.50" in text, text
    assert "<b>Today</b> 6 orders filled · 3 positions closed · fees $1.25" in text, text
    # An older snapshot without equity: today from the learning report, trades still from it.
    old = {"ap1": {"trades": 9, "fees": 2.25, "at": NOW - 86_400_000}}
    text = notify.digest(learn_report(), FORWARD, HEALTH_OK, old, NOW)[0]
    assert "Momentum  1,030 +1.00 +3.00" in text and "<b>Today</b> 3 positions closed · fees $1.25" in text
    # Three days old: the totals since start.
    old = {"ap1": {"equity": 1_000.0, "trades": 9, "fees": 2.25, "at": NOW - 3 * 86_400_000}}
    text = notify.digest(learn_report(), FORWARD, HEALTH_OK, old, NOW)[0]
    assert "<b>Since start</b> 12 positions closed" in text and "Momentum  1,030 +1.00" in text
    # The amount it works with changed since: no "today" from the snapshot.
    moved = {"ap1": {"equity": 500.0, "start": 500.0, "trades": 9, "fees": 2.25, "at": NOW - 86_400_000}}
    assert "Momentum  1,030 +1.00" in notify.digest(learn_report(), FORWARD, HEALTH_OK, moved, NOW)[0]
    # Neither a snapshot nor a 24 h change: not known, not the change since start.
    rep = learn_report()
    rep["autopilots"][0]["pnl_day_pct"] = None
    text = notify.digest(rep, FORWARD, HEALTH_OK, {}, NOW)[0]
    assert "Momentum  1,030   n/a +3.00 +1.50" in text and "1 autopilot running · BTC 24 h +0.50 %" in text, text


def test_today_is_not_since_start_over_two_days_with_two_engines(telegram, data, monkeypatch):
    """2026-10-21: every autopilot read today equal to since start. Two digests
    a day apart, the main and the safe engine, starting from a snapshot an
    older digest wrote (the safe autopilot under its bare id, no equity)."""
    monkeypatch.setenv("PYTHIA_ALERT_LANG", "de")
    day1 = utc(2026, 10, 20, 5, 0)

    def rep(at, main_eq, safe_eq, trades):
        return {"generated": "x", "generated_ms": at - 600_000, "engine": {"reachable": True},
                "autopilots": [
                    {"id": "ap_autopick", "name": "Auto-Pick (main)", "account": "main", "mode": "demo",
                     "state": "running", "days": 5.0, "equity": main_eq, "start_capital": 20_000.0,
                     "fees": 8.0 + trades, "trades": trades, "orders": 3 * trades, "pnl_day_pct": None,
                     "btc_day_pct": 1.15, "btc_total_pct": 2.29, "vs_btc_total_pts": -1.87},
                    {"id": "ap_safe", "name": "Safe · BTC filter momentum", "account": "safe", "mode": "demo",
                     "state": "running", "days": 5.0, "equity": safe_eq, "start_capital": 95.0, "fees": 0.0,
                     "trades": 0, "orders": 0, "pnl_day_pct": None, "btc_day_pct": 1.15,
                     "vs_btc_total_pts": -2.29}]}

    notify.write_json(data / "notify" / "state.json",
                      {"autopilots": {"ap_autopick": {"trades": 30, "fees": 38.0, "at": day1 - notify.DAY_MS},
                                      "ap_safe": {"trades": 0, "fees": 0.0, "at": day1 - notify.DAY_MS}}})
    write(data, "reports/learn/latest.json", rep(day1, 20_083.69, 95.5, 38))
    assert notify.daily(now_ms=day1, chart=False) == 0
    text = json.loads((data / "reports/notify/latest.json").read_text(encoding="utf-8"))["text"]
    assert "2 Autopiloten laufen · BTC 24 h +1,15 %" in text, text
    assert "Auto-Pick    20.084 k. A. +0,42 -1,87" in text, "no snapshot equity, no 24 h change: not the change since start"
    assert "Heute 8 Positionen geschlossen · Gebühren 8,00 $" in text, "yesterday's old keys still count"
    st = json.loads((data / "notify/state.json").read_text())["autopilots"]
    assert set(st) == {"ap_autopick", "safe:ap_safe"}, "migrated to the keys of today"
    assert st["ap_autopick"]["equity"] == 20_083.69 and st["safe:ap_safe"]["equity"] == 95.5

    day2 = day1 + notify.DAY_MS
    write(data, "reports/learn/latest.json", rep(day2, 20_123.85, 95.95, 41))
    assert notify.daily(now_ms=day2, chart=False) == 0
    text = json.loads((data / "reports/notify/latest.json").read_text(encoding="utf-8"))["text"]
    assert "2 Autopiloten laufen, heute +40,61 $ 🟢 · BTC 24 h +1,15 %" in text, text
    assert "Auto-Pick    20.124 +0,20 +0,62 -1,87" in text, text
    assert "Safe BTC fi…     96 +0,47 +1,00 -2,29" in text, text
    assert "Heute 9 Orders ausgeführt · 3 Positionen geschlossen · Gebühren 3,00 $" in text, text
    assert "Konto safe: Safe BTC fi…" in text


def test_losses_red_health_and_a_stale_report_are_said():
    rep = learn_report(equity=950.0)
    rep["autopilots"][0]["pnl_day_pct"] = -2.0
    rep["generated_ms"] = NOW - 2 * 86_400_000
    text, _ = notify.digest(rep, None, health_bad("2026-10-14T06:07:00Z"), {}, NOW)
    assert "-$19.39 today 🔴" in text
    assert "Momentum    950 -2.00 -5.00 +1.50" in text, text
    assert "not today's" in text
    assert "<b>Forward test</b> no report" in text
    assert "<b>Health</b> 🔴 1 red: paper tsmom (last row none)" in text


def test_many_autopilots_are_cut_to_a_phone_screen():
    rep = learn_report()
    rep["autopilots"] = [dict(rep["autopilots"][0], id=f"a{i}", name=f"Autopilot number {i}") for i in range(40)]
    text, _ = notify.digest(rep, FORWARD, HEALTH_OK, {}, NOW)
    assert len(text) <= notify.MAX_CHARS and balanced(text)
    assert "+28 more</pre>" in text
    assert "40 autopilots running" in text


def test_a_name_is_cut_for_the_table():
    assert notify.short_name("Test · TSMOM tranches") == "TSMOM tranc…"
    assert notify.short_name("Test · Memecoin rotation (experiment)") == "Memecoin ro…"
    assert notify.short_name("Auto-Pick (main)") == "Auto-Pick"
    assert notify.short_name("Safe · BTC filter momentum") == "Safe BTC fi…"
    assert notify.short_name(None) == "Autopilot"


@pytest.mark.parametrize("fmt,key", [("discord", "content"), ("slack", "text")])
def test_daily_posts_to_a_webhook_in_its_format(hook, data, monkeypatch, capsys, fmt, key):
    url, got, _ = hook
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    monkeypatch.setenv("PYTHIA_ALERT_FORMAT", fmt)
    write(data, "reports/learn/latest.json", learn_report())
    write(data, "reports/forward/latest.json", FORWARD)
    write(data, "_health/system.json", HEALTH_OK)
    assert notify.daily(now_ms=NOW) == 0
    assert len(got) == 1 and list(got[0][1]) == [key]
    assert "📊 Daily · Wed 14 Oct" in got[0][1][key] and "<b>" not in got[0][1][key]
    st = json.loads((data / "notify" / "state.json").read_text())
    assert st["autopilots"]["ap1"]["trades"] == 12
    assert "secret-token" not in capsys.readouterr().out + json.dumps(st)


def test_a_failed_post_is_reported_without_the_url(telegram, data, capsys):
    url, got, state = telegram
    state["status"] = 500
    assert notify.daily(now_ms=NOW) == 1
    err = capsys.readouterr().err
    assert "HTTP 500" in err and "secret-token" not in err
    assert not (data / "notify" / "state.json").exists()
    ok, why = notify.post("http://127.0.0.1:9/secret-token", "discord", "x", timeout=2)
    assert not ok and "secret-token" not in why


def test_without_a_destination_it_only_prints(data, capsys):
    assert notify.daily(now_ms=NOW) == 0
    out = capsys.readouterr().out
    assert "No learning report found." in out and "printed only" in out


def test_every_digest_is_written_to_latest_json(telegram, data):
    url, got, state = telegram
    write(data, "reports/learn/latest.json", learn_report())
    assert notify.daily(now_ms=NOW) == 0
    latest = json.loads((data / "reports/notify/latest.json").read_text(encoding="utf-8"))
    assert latest["ts"] == NOW and latest["delivered"] is True and latest["photo"] is False
    assert latest["html"] == got[0][1]["text"]
    assert latest["text"] == notify.plain(latest["html"]) and latest["text"].startswith("📊 Daily · Wed 14 Oct")
    state["status"] = 500
    assert notify.daily(now_ms=NOW + 1) == 1
    latest = json.loads((data / "reports/notify/latest.json").read_text(encoding="utf-8"))
    assert latest["ts"] == NOW + 1 and latest["delivered"] is False
    assert url not in (data / "reports/notify/latest.json").read_text(encoding="utf-8")


def test_a_dry_run_writes_no_latest_and_no_destination_writes_undelivered(data):
    assert notify.daily(dry_run=True, now_ms=NOW) == 0
    assert not (data / "reports/notify/latest.json").exists()
    assert notify.daily(now_ms=NOW) == 0
    assert json.loads((data / "reports/notify/latest.json").read_text(encoding="utf-8"))["delivered"] is False


def test_the_digest_follows_its_switch_and_waits_out_quiet_hours(telegram, data, monkeypatch):
    _, got, _ = telegram
    write(data, "reports/notify/settings.json", {"categories": [{"id": "dailyPnl", "on": False}]})
    assert notify.daily(now_ms=NOW) == 0 and got == []
    write(data, "reports/notify/settings.json", {"categories": []})
    monkeypatch.delenv("PYTHIA_QUIET_HOURS")
    write(data, "reports/learn/latest.json", learn_report())
    assert notify.daily(now_ms=utc(2026, 10, 14, 23, 0)) == 0 and got == []
    assert not (data / "notify" / "state.json").exists(), "the snapshot waits for a digest that went out"
    assert notify.pending(now_ms=utc(2026, 10, 15, 2, 0)) == 0 and got == [], "still quiet"
    # Quiet hours over: the next --pending sends it, and it counts as the daily one.
    assert notify.pending(now_ms=utc(2026, 10, 15, 5, 5)) == 0
    assert len(got) == 1 and texts(got)[0].startswith("<b>📊 Daily · Thu 15 Oct</b>")
    assert json.loads((data / "notify" / "state.json").read_text())["autopilots"]["ap1"]["trades"] == 12


def test_pending_sends_once_per_request_newer_than_the_last_digest(telegram, data, capsys):
    _, got, _ = telegram
    write(data, "reports/learn/latest.json", learn_report())
    assert notify.pending(now_ms=NOW) == 0
    assert got == [] and "no digest request" in capsys.readouterr().out

    write(data, "reports/notify/request.json", {"ts": NOW - 60_000, "source": "api"})
    assert notify.pending(now_ms=NOW) == 0
    assert len(got) == 1 and texts(got)[0].startswith("<b>📊 Daily")
    assert notify.pending(now_ms=NOW + 300_000) == 0
    assert len(got) == 1, "the same request is answered once"

    # A request older than the last daily digest is already answered.
    assert notify.daily(now_ms=NOW + 600_000) == 0
    write(data, "reports/notify/request.json", {"ts": NOW + 500_000, "source": "api"})
    assert notify.pending(now_ms=NOW + 900_000) == 0
    assert len(got) == 2

    # The engine's clock ahead of this one: still answered once.
    write(data, "reports/notify/request.json", {"ts": NOW + 2_000_000, "source": "api"})
    assert notify.pending(now_ms=NOW + 1_000_000) == 0
    assert notify.pending(now_ms=NOW + 1_300_000) == 0
    assert len(got) == 3


def test_an_on_demand_digest_leaves_the_daily_snapshot_alone(telegram, data):
    write(data, "reports/learn/latest.json", learn_report())
    assert notify.daily(now_ms=NOW) == 0
    before = (data / "notify/state.json").read_text()
    write(data, "reports/learn/latest.json", learn_report(trades=20))
    write(data, "reports/notify/request.json", {"ts": NOW + 60_000})
    assert notify.main(["--pending"]) == 0
    assert (data / "notify/state.json").read_text() == before


# ---------------------------------------------------------------- the chart goes with it

def engine_state(now=NOW):
    start = now - 9 * notify.DAY_MS
    hist = [[start + i * (now - start) // 200, 1000 * (1 + 0.03 * i / 200 + 0.01 * math.sin(i / 13))] for i in range(200)]
    return {
        "autopilots": [
            {"config": {"id": "ap1", "name": "Momentum", "mode": "demo"}, "state": "running", "startedMs": start,
             "startCapital": 1000, "equity": hist[-1][1], "history": hist, "trades": 31, "drawdownPct": 1.2,
             "btcReturnPct": 2.1, "held": ["crypto:BTC/USD", "crypto:ETH/USD"],
             "bySleeve": [{"name": "tsmom", "pnl": 31.2}, {"name": "m4_ls", "pnl": -6.4}]},
            {"config": {"id": "ap0", "name": "Old", "mode": "demo"}, "state": "stopped", "startedMs": start,
             "startCapital": 1000, "equity": 900, "history": []},
        ],
        "positions": [
            {"marketId": "crypto:BTC/USD", "symbol": "BTC/USD", "qty": 0.004, "lastPrice": 67234.1},
            {"marketId": "crypto:ETH/USD", "symbol": "ETH/USD", "qty": 0.09, "lastPrice": 3412.0},
            {"marketId": "crypto:DOGE/USD", "symbol": "DOGE/USD", "qty": 100, "lastPrice": 0.2},
        ],
    }


def btc_series(a, b):
    return [(a + i * (b - a) // 50, 60_000 * (1 + 0.02 * i / 50)) for i in range(51)]


def test_chart_data_comes_from_the_engine_state():
    d = notify.chart_data(engine_state(), None, NOW, btc_series(NOW - 9 * notify.DAY_MS, NOW))
    assert [a["name"] for a in d["autopilots"]] == ["Momentum"], "only running ones"
    pts = d["autopilots"][0]["points"]
    assert pts[0][1] == pytest.approx(0.0) and pts[-1][0] == NOW
    assert d["btc"][0][1] == pytest.approx(0.0) and d["btc"][-1][1] == pytest.approx(2.0)
    assert d["sleeves"] == [("tsmom", 31.2), ("m4_ls", -6.4)]
    assert [p[0] for p in d["positions"]] == ["ETH", "BTC"], "only what the autopilots hold, largest first"
    # Without a price series, BTC is drawn from the engine's own number.
    d = notify.chart_data(engine_state(), None, NOW, [])
    assert d["btc"][-1] == (NOW, 2.1)
    assert notify.chart_data({"autopilots": []}, None, NOW) is None


def test_the_daily_digest_goes_with_its_chart_as_a_photo(telegram, data, monkeypatch):
    pytest.importorskip("matplotlib")
    _, got, _ = telegram
    monkeypatch.setattr(notify, "engine_state", lambda timeout=15: engine_state())
    monkeypatch.setattr(notify, "btc_closes", lambda a, b, timeout=15: btc_series(a, b))
    write(data, "reports/learn/latest.json", learn_report())
    write(data, "reports/forward/latest.json", FORWARD)
    assert notify.daily(now_ms=NOW) == 0
    photos = [(p, b) for p, b in got if isinstance(b, bytes)]
    assert len(photos) == 1 and photos[0][0].endswith("/sendPhoto")
    body = photos[0][1]
    assert b'name="parse_mode"\r\n\r\nHTML' in body and b"\x89PNG" in body
    assert "<b>📊 Daily · Wed 14 Oct</b>".encode() in body
    # The digest fits in a caption, so the photo is the whole message.
    assert texts(got) == []
    latest = json.loads((data / "reports/notify/latest.json").read_text(encoding="utf-8"))
    assert latest["photo"] is True and latest["delivered"] is True


# ---------------------------------------------------------------- the weekly report

def test_the_weekly_report_is_sunday_at_six_in_berlin_once(telegram, data):
    _, got, _ = telegram
    sunday_18 = utc(2026, 10, 18, 16, 5)  # 18:05 Berlin, summer time
    assert notify.weekly_due(sunday_18) and notify.weekly_due(utc(2026, 10, 18, 19, 5))
    assert not notify.weekly_due(utc(2026, 10, 18, 15, 5)) and not notify.weekly_due(utc(2026, 10, 17, 16, 5))
    assert not notify.weekly_due(utc(2026, 10, 18, 22, 5)), "Monday 00:05 in Berlin"
    st = engine_state(sunday_18)
    assert notify.weekly(now=utc(2026, 10, 18, 15, 5), state=st, btc_fetch=None) == 0
    assert got == [], "17:05 is not the time"
    assert notify.weekly(now=sunday_18, state=st, btc_fetch=btc_series) == 0
    assert len(got) == 1
    text = texts(got)[0] if texts(got) else got[0][1].decode("utf-8", "replace")
    assert "🗓️ Weekly · 11 to 18 Oct" in text
    assert "Autopilot Value  Week Start  ±BTC\nMomentum" in text, text
    assert "BTC this week +2.00 %" in text
    assert "<b>Best sleeve</b> tsmom +$31.20 · worst m4_ls -$6.40" in text
    assert notify.weekly(now=sunday_18 + 1_800_000, state=st, btc_fetch=None) == 0
    assert len(got) == 1, "once a week"
    assert notify.weekly(now=sunday_18 + 1_800_000, state=st, btc_fetch=None, force=True) == 0
    assert len(got) == 2, "--force sends anyway"


def test_the_weekly_card_counts_the_week():
    now = utc(2026, 10, 18, 16, 0)
    st = engine_state(now)
    card, snap = notify.weekly_card(st, {"ap1": {"trades": 20, "at": now - notify.WEEK_MS}}, now, 1.0)
    html = card.render()
    assert card.title == "Weekly · 11 to 18 Oct"
    assert "<b>This week</b> 11 positions closed" in html, html
    assert "<b>Below peak</b> deepest Momentum 1.20 %" in html
    assert snap == {"ap1": {"trades": 31, "at": now}}
    # An old key of the same autopilot (main:ap1) still counts the week.
    card, _ = notify.weekly_card(st, {"main:ap1": {"trades": 20, "at": now - notify.WEEK_MS}}, now, 1.0)
    assert "11 positions closed" in card.render()
    # Without last week's numbers: the total since start, said as such.
    card, _ = notify.weekly_card(st, {}, now, 1.0)
    assert "<b>Since start</b> 31 positions closed" in card.render()
    assert notify.weekly_card(None, {}, now, None)[0].summary.startswith("The engine did not answer")


# ---------------------------------------------------------------- the health alarm

def test_health_posts_once_after_two_bad_runs_and_once_when_green(telegram, data):
    _, got, _ = telegram
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
    text = texts(got)[0]
    assert text.startswith("<b>🩺 Health check red for 2 runs</b>\n1 check not ok at 2026-10-14T08:07:00Z."), text
    assert "<b>paper tsmom</b> last row none" in text
    run(health_bad("2026-10-14T09:07:00Z"))
    assert len(got) == 1, "posted once per episode"
    run(dict(HEALTH_OK, at="2026-10-14T10:07:00Z"))
    assert len(got) == 2 and texts(got)[1].startswith("<b>✅ Health check all green again</b>")
    run(health_bad("2026-10-14T11:07:00Z"))
    run(dict(HEALTH_OK, at="2026-10-14T12:07:00Z"))
    assert len(got) == 2, "a single bad run and its recovery stay quiet"


def test_health_retries_when_the_post_fails(telegram, data):
    _, got, state = telegram
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


def test_health_waits_for_the_end_of_quiet_hours(telegram, data, monkeypatch):
    _, got, _ = telegram
    monkeypatch.delenv("PYTHIA_QUIET_HOURS")
    sysj = data / "_health" / "system.json"
    night, morning = utc(2026, 10, 14, 23, 0), utc(2026, 10, 15, 6, 0)
    for i, at in enumerate(("2026-10-14T23:07:00Z", "2026-10-15T00:07:00Z", "2026-10-15T01:07:00Z")):
        write(data, "_health/system.json", health_bad(at))
        assert notify.health(sysj, now=night + i * 3_600_000) == 0
    assert got == []
    write(data, "_health/system.json", health_bad("2026-10-15T06:07:00Z"))
    assert notify.health(sysj, now=morning) == 0
    assert len(got) == 1 and "red for 4 runs" in texts(got)[0]


def test_an_event_from_the_shell(telegram, data):
    _, got, _ = telegram
    assert notify.main(["--event", "venue", "Disk almost full", "12 GB left"]) == 0
    assert texts(got)[0] == "<b>📡 Disk almost full</b>\n12 GB left\n<i>Pythia</i>"
    assert notify.main(["--event", "weather", "x"]) == 2


# ---------------------------------------------------------------- links and pictures

def test_links_render_per_format_and_bad_urls_are_only_labels():
    lk = notify.Links([("Steam", "https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline"),
                       ("A & B", "https://example.org/x?a=1&b=2"), ("Bad", "javascript:alert(1)"),
                       ("Quote", 'https://example.org/"onmouseover=x'), ("None", None)], lead="Look")
    tg = notify.Card("🎮", "T", parts=[lk]).render("telegram")
    assert '<a href="https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline">Steam</a>' in tg
    assert '<a href="https://example.org/x?a=1&amp;b=2">A &amp; B</a>' in tg
    assert "javascript" not in tg and "onmouseover" not in tg and "Bad" in tg and "None" in tg
    assert tg.startswith("<b>🎮 T</b>\n<b>Look</b> ")
    assert "[Steam](<https://steamcommunity.com/" in notify.Card("x", "T", parts=[lk]).render("discord")
    assert "<https://example.org/x?a=1&b=2|A & B>" in notify.Card("x", "T", parts=[lk]).render("slack")
    # The plain fallback keeps the URL next to its label.
    assert "Steam https://steamcommunity.com/market/listings/730/AK-47%20%7C%20Redline" in notify.plain(tg)
    assert "A & B https://example.org/x?a=1&b=2" in notify.plain(tg)
    assert not notify.fits_event([notify.Card("x", "T", parts=[lk])])


def test_safe_url_takes_only_plain_http_urls():
    assert notify.safe_url("https://a.org/x?q=1") == "https://a.org/x?q=1"
    for bad in ("ftp://a.org/x", "https://", "https://a.org/x y", "https://user@a.org/", "https://a.org/<b>", 7, None):
        assert notify.safe_url(bad) is None


def test_pictures_go_first_as_an_album_then_the_text(telegram, data):
    _, got, _ = telegram
    card = notify.Card("🃏", "Cheap cards", "Two", [notify.Links([("Cardmarket", "https://www.cardmarket.com/x")])])
    pics = [("https://images.pokemontcg.io/sv3/1.png", "<b>Cheap cards</b>\n1. A"),
            ("https://images.pokemontcg.io/sv3/2.png", "ignored"), ("not a url", "x")]
    res = notify.send("pokemon", [card], photos=pics)
    assert res["delivered"] and res["photo"]
    (p1, album), (p2, msg) = got
    assert p1.endswith("/sendMediaGroup") and p2.endswith("/hook/secret-token")
    assert [m["media"] for m in album["media"]] == ["https://images.pokemontcg.io/sv3/1.png",
                                                    "https://images.pokemontcg.io/sv3/2.png"]
    assert album["media"][0]["caption"] == "<b>Cheap cards</b>\n1. A" and "caption" not in album["media"][1]
    assert '<a href="https://www.cardmarket.com/x">Cardmarket</a>' in msg["text"]
    assert msg["disable_web_page_preview"] is True
    one = notify.photos_body("1", pics[:1])
    assert one[0] == "sendPhoto" and one[1]["photo"].endswith("1.png") and one[1]["parse_mode"] == "HTML"
    assert notify.photos_body("1", [("x", "y")]) is None
    long = notify.photos_body("1", [("https://a.org/1.png", "<b>x</b>" + "y" * 2000)])
    assert len(long[1]["caption"]) <= notify.CAPTION_LIMIT and "<b>" not in long[1]["caption"]


def test_a_refused_album_is_tried_as_one_picture(telegram, data, monkeypatch):
    calls = []
    monkeypatch.setattr(notify, "_request", lambda req, timeout: (calls.append(req.full_url), (False, "HTTP 400"))[1]
                        if req.full_url.endswith("sendMediaGroup") else (calls.append(req.full_url), (True, None))[1])
    res = notify.send("pokemon", [notify.Card("x", "T")], photos=[("https://a.org/1.png", "c"), ("https://a.org/2.png", "")])
    assert [c.rsplit("/", 1)[1] for c in calls] == ["sendMediaGroup", "sendPhoto", "secret-token"]
    assert res["photo"] and res["delivered"]


def test_a_webhook_gets_no_pictures_only_the_links(hook, data, monkeypatch):
    url, got, _ = hook
    monkeypatch.setenv("PYTHIA_ALERT_WEBHOOK", url)
    card = notify.Card("🃏", "T", parts=[notify.Links([("TCGplayer", "https://www.tcgplayer.com/product/1")])])
    notify.send("pokemon", [card], photos=[("https://a.org/1.png", "c")])
    assert len(got) == 1 and "[TCGplayer](<https://www.tcgplayer.com/product/1>)" in got[0][1]["content"]
