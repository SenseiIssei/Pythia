"""The real money readiness rule on synthetic histories: each rule, its edges, the report and the alert.

No network, no lab data. Run from research/lab:  python -m pytest tests
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from lab import report
from lab.ops import guard, hurdles, notify, readiness

DAY_MS = 86_400_000
# A Thursday morning, after the learning loop.
NOW = int(datetime(2026, 10, 15, 6, 45, tzinfo=timezone.utc).timestamp() * 1000)
CAPITAL = 10_000.0


@pytest.fixture()
def root(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    for mod in (guard, readiness, hurdles):
        monkeypatch.setattr(mod, "ROOT", data)
    monkeypatch.setattr(report, "REPORTS", data / "reports")
    monkeypatch.setenv("PYTHIA_REPORTS", str(data / "reports"))
    monkeypatch.setenv("PYTHIA_DATA", str(data))
    monkeypatch.delenv("PYTHIA_RESULTS", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    monkeypatch.delenv("PYTHIA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    guard.WRITTEN.clear()
    return data


def curve(days: float, daily: float = 0.004, dips: dict[int, float] | None = None, start_ms: int | None = None,
          capital: float = CAPITAL) -> list[list[float]]:
    """Equity every 6 hours from the start: a steady daily gain, with dips
    (day -> fraction lost that day) where asked."""
    start_ms = start_ms if start_ms is not None else NOW - int(days * DAY_MS)
    out, eq, t = [], capital, start_ms
    steps = int(days * 4)
    dips = dips or {}
    for i in range(steps + 1):
        d = i // 4
        if i and i % 4 == 0:
            eq *= 1 + daily
            if d in dips:
                eq *= 1 - dips[d]
        out.append([t + i * 6 * 3_600_000, round(eq, 4)])
    return out


def autopilot(days: float = 40, trades: int = 30, daily: float = 0.004, dips=None, ap_id: str = "ap-1",
              bench_ret: float | None = 1.0, mode: str = "demo", venue: str = "alpaca", sleeves=None,
              state: str = "running", started_ms: int | None = None) -> dict:
    started_ms = started_ms if started_ms is not None else NOW - int(days * DAY_MS)
    hist = curve(days, daily, dips, started_ms)
    eq = hist[-1][1]
    ret = (eq / CAPITAL - 1) * 100
    peak, dd = 0.0, 0.0
    for _, e in hist:
        peak = max(peak, e)
        dd = max(dd, (1 - e / peak) * 100)
    b = None if bench_ret is None else {"symbol": "SPY", "name": "SPY buy and hold", "returnPct": bench_ret,
                                        "excessPct": ret - bench_ret}
    return {"config": {"id": ap_id, "name": f"Autopilot {ap_id}", "mode": mode, "venue": venue, "capitalUsd": CAPITAL,
                       "sleeves": []},
            "state": state, "startedMs": started_ms, "stoppedMs": None, "startCapital": CAPITAL, "equity": eq,
            "pnl": eq - CAPITAL, "pnlPct": ret, "trades": trades, "fees": 12.5, "history": hist,
            "benchmark": b, "maxDrawdownPct": dd, "drawdownPct": 0.0, "bySleeve": sleeves or []}


def clean_history(days: int = 8, ap: dict | None = None) -> list[dict]:
    """The job's daily records of the last `days` days, every reconciliation clean."""
    out = []
    for k in range(days, 0, -1):
        ts = NOW - k * DAY_MS
        out.append({"date": readiness._date(ts), "ts_ms": ts, "autopilots": {},
                    "reconcile": {"checked_at": ts - 60_000, "mismatches": 0, "fresh": True}})
    return out


def write_history(rows: list[dict]) -> None:
    p = readiness.history_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def state_of(*aps, mismatches: int = 0, events=None, at: int = NOW) -> dict:
    return {"autopilots": list(aps), "events": events or [],
            "live": {"demoExchange": "alpaca", "demoReconcile": {"checkedAt": at - 5 * 60_000, "mismatches": mismatches,
                                                                 "pairs": []}}}


def forward_for(*aps, position="inside", band=True, dd_p95=12.0, at: int = NOW) -> dict:
    rows = []
    for a in aps:
        exp = {"low_pct": -5.0, "high_pct": 30.0, "median_pct": 5.0, "dd_p95_pct": dd_p95, "method": "bootstrap"} \
            if band else None
        rows.append({"name": a["config"]["id"], "started_ms": a["startedMs"], "expected": exp,
                     "position": position if band else None})
    return {"generated_ms": at - 30 * 60_000, "autopilots": rows}


MACRO = {"inflation": hurdles.inflation({"pct": 2.9, "month": "2026-09", "source": "US CPI (FRED CPIAUCSL)"},
                                        {"pct": 3.8, "month": "2026-09", "source": "euro area HICP (Eurostat)"}),
         "sp500": {"closes": [(readiness._date(NOW - k * DAY_MS), 7000 + 10 * (200 - k)) for k in range(200, -1, -1)]}}


def settle(root, step: int = 3) -> None:
    p = readiness.settings_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"risk_step": step}))


def run(root, *aps, step: int = 3, forward=None, history_days: int = 8, posts=None, **kw):
    settle(root, step)
    write_history(clean_history(history_days))
    st = kw.pop("state", None) or state_of(*aps)
    fwd = forward if forward is not None else forward_for(*aps)
    sender = (lambda text: (posts.append(text) or True, None)) if posts is not None else (lambda text: (True, None))
    return readiness.run(NOW, state=st, forward=fwd, macro=kw.pop("macro", MACRO), sender=sender, **kw)


def rules(item: dict) -> dict[str, dict]:
    return {r["id"]: r for r in item["rules"]}


def first(rep: dict) -> dict:
    return rep["autopilots"][0]


# ---------------------------------------------------------------- the whole rule

def test_a_steady_winner_meets_every_rule_and_is_announced_once(root):
    posts: list[str] = []
    ap = autopilot(days=40, trades=30)
    rep = run(root, ap, posts=posts)
    item = first(rep)
    assert item["ready"], [r for r in item["rules"] if not r["pass"]]
    assert item["passed"] == item["total"] == 9
    assert rep["status"] == "ok" and rep["title"] == "Real money readiness"
    assert len(posts) == 1 and "Ready for a real money proposal" in posts[0]
    assert "Only the owner can arm live" in posts[0]
    # The next day it is not new: no second post.
    rep2 = readiness.run(NOW + 60_000, state=state_of(ap), forward=forward_for(ap), macro=MACRO,
                         sender=lambda t: (posts.append(t) or True, None))
    assert rep2["autopilots"][0]["ready"] and len(posts) == 1


def test_the_report_has_the_feed_header_and_the_numbers(root):
    rep = run(root, autopilot())
    saved = json.loads((root / "reports" / "readiness" / "latest.json").read_text())
    for k in ("title", "updated_ms", "status", "headline", "items"):
        assert k in saved
    assert saved["items"][0]["label"] == "Autopilot ap-1"
    assert saved["profile"]["step"] == 3 and len(saved["profiles"]) == 5
    assert saved["inflation"]["pct"] == 3.8 and "euro area" in saved["inflation"]["source"]
    assert {r["id"] for r in saved["autopilots"][0]["rules"]} == {r for r, _ in readiness.RULES}
    assert rep["autopilots"][0]["sp500_pct"] is not None


# ---------------------------------------------------------------- rule 1: days and trades

def test_exactly_the_minimum_days_passes_and_a_minute_less_does_not(root):
    # Bold step: 30 days.
    ok = first(run(root, autopilot(days=30), step=5))
    assert rules(ok)["record"]["pass"], rules(ok)["record"]
    short = first(run(root, autopilot(days=30 - 1 / 1440), step=5))
    assert not rules(short)["record"]["pass"]
    assert short["days_to_go"] == 1


def test_too_few_closed_trades_fail_the_record(root):
    item = first(run(root, autopilot(days=40, trades=19)))
    assert not rules(item)["record"]["pass"] and not item["ready"]
    assert rules(run(root, autopilot(days=40, trades=20))["autopilots"][0])["record"]["pass"]


def test_internal_paper_or_another_venue_is_not_the_alpaca_paper_account(root):
    paper = first(run(root, autopilot(mode="paper")))
    assert not paper["on_account"] and not rules(paper)["record"]["pass"]
    kraken = autopilot(venue="kraken")
    st = state_of(kraken)
    st["live"]["demoExchange"] = "bybit"
    assert not first(run(root, kraken, state=st))["on_account"]
    st["live"]["demoExchange"] = "alpaca"
    assert first(run(root, kraken, state=st))["on_account"]


def test_live_and_stopped_autopilots_are_not_judged(root):
    rep = run(root, autopilot(ap_id="a", mode="live"), autopilot(ap_id="b", state="stopped"), autopilot(ap_id="c"))
    assert [i["id"] for i in rep["autopilots"]] == ["c"]


def test_without_a_band_it_needs_fifteen_more_days(root):
    ap = autopilot(days=40)
    item = first(run(root, ap, forward=forward_for(ap, band=False)))
    assert rules(item)["band"]["pass"]
    assert not rules(item)["record"]["pass"] and item["need_days"] == 38 + 15
    ap60 = autopilot(days=60)
    assert first(run(root, ap60, forward=forward_for(ap60, band=False)))["ready"]


def test_a_restarted_autopilot_starts_its_record_again(root):
    # The old run of ap-1 was 60 days long; the new one started 5 days ago.
    old_start = NOW - 70 * DAY_MS
    old = [{"date": readiness._date(NOW - k * DAY_MS), "ts_ms": NOW - k * DAY_MS,
            "autopilots": {"ap-1": {"started_ms": old_start, "equity": 5_000.0, "pnl": -5_000.0, "sleeves": {}}},
            "reconcile": {"fresh": True, "mismatches": 0}} for k in range(20, 6, -1)]
    settle(root)
    write_history(old + clean_history(6))
    ap = autopilot(days=5, trades=40)
    rep = readiness.run(NOW, state=state_of(ap), forward=forward_for(ap), macro=MACRO, sender=lambda t: (True, None))
    item = first(rep)
    assert item["days"] == pytest.approx(5, abs=0.01)
    assert not rules(item)["record"]["pass"] and item["days_to_go"] == 33
    # The old run's 50 % loss is not this run's drawdown.
    assert item["max_dd_pct"] < 1


# ---------------------------------------------------------------- rule 2: net P&L

def test_a_net_loss_fails_and_fees_are_already_in_it(root):
    item = first(run(root, autopilot(daily=-0.0005)))
    assert not rules(item)["profit"]["pass"]
    flat = autopilot(daily=0.0)
    assert not rules(first(run(root, flat)))["profit"]["pass"], "zero is not above zero"


# ---------------------------------------------------------------- rule 3: weeks

def test_one_losing_week_of_four_passes_the_middle_step_but_not_careful(root):
    # The last complete week runs from Monday 2026-10-05 to 2026-10-12. A 4 %
    # dip on Wednesday 2026-10-07 makes that week a loser.
    start = NOW - 40 * DAY_MS
    dip_day = (int(datetime(2026, 10, 7, tzinfo=timezone.utc).timestamp() * 1000) - start) // DAY_MS + 1
    ap = autopilot(days=40, dips={int(dip_day): 0.04})
    mid = first(run(root, ap, step=3))
    assert rules(mid)["weeks"]["value"] == "3 of 4" and rules(mid)["weeks"]["pass"]
    careful = first(run(root, ap, step=1, forward=forward_for(ap)))
    assert not rules(careful)["weeks"]["pass"]


def test_two_losing_weeks_fail_the_middle_step(root):
    start = NOW - 40 * DAY_MS

    def day(y, m, d):
        return int((int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000) - start) // DAY_MS + 1)

    ap = autopilot(days=40, dips={day(2026, 10, 7): 0.04, day(2026, 9, 30): 0.04})
    assert rules(first(run(root, ap)))["weeks"]["value"] == "2 of 4"
    assert not rules(first(run(root, ap)))["weeks"]["pass"]


def test_weeks_before_the_start_do_not_count_as_positive(root):
    # Started Monday 2026-10-05 06:45: the three weeks before have nothing, the
    # week it started in counts from its start.
    pts = [(NOW - 10 * DAY_MS, 100.0), (NOW - 4 * DAY_MS, 110.0), (NOW, 120.0)]
    w = readiness.weekly(pts, NOW - 10 * DAY_MS, NOW)
    assert [x["week"] for x in w] == ["2026-09-14", "2026-09-21", "2026-09-28", "2026-10-05"]
    assert [x["change"] for x in w] == [None, None, None, 10.0]
    assert [x["positive"] for x in w] == [False, False, False, True]


# ---------------------------------------------------------------- rule 4: benchmark

def test_behind_the_benchmark_fails(root):
    item = first(run(root, autopilot(bench_ret=80.0)))
    assert not rules(item)["benchmark"]["pass"]


def test_a_missing_benchmark_fails_and_says_why(root):
    item = first(run(root, autopilot(bench_ret=None)))
    r = rules(item)["benchmark"]
    assert not r["pass"] and r["value"] == "unknown" and "cannot be judged" in r["detail"]
    ap = autopilot()
    ap["benchmark"] = {"symbol": "BTC/USD", "name": "BTC buy and hold", "returnPct": None, "excessPct": None}
    assert not rules(first(run(root, ap)))["benchmark"]["pass"]


# ---------------------------------------------------------------- rule 5: drawdown

def test_drawdown_exactly_at_the_limit_passes_and_just_over_fails(root):
    u = {"points": [(0, 100.0), (1, 90.0), (2, 120.0)], "dd_engine": 0.0}
    assert readiness.max_drawdown_pct(u["points"]) == pytest.approx(10.0)
    ap = autopilot()
    ap["maxDrawdownPct"] = 10.0
    item = first(run(root, ap, forward=forward_for(ap, dd_p95=None)))
    assert rules(item)["drawdown"]["pass"], rules(item)["drawdown"]
    ap["maxDrawdownPct"] = 10.01
    assert not rules(first(run(root, ap, forward=forward_for(ap, dd_p95=None))))["drawdown"]["pass"]


def test_the_backtest_band_can_make_the_drawdown_limit_tighter(root):
    ap = autopilot()
    ap["maxDrawdownPct"] = 6.0
    item = first(run(root, ap, forward=forward_for(ap, dd_p95=5.0)))
    assert not rules(item)["drawdown"]["pass"] and "5.00" in rules(item)["drawdown"]["need"]
    assert rules(first(run(root, ap, step=5, forward=forward_for(ap, dd_p95=None))))["drawdown"]["pass"]


# ---------------------------------------------------------------- rule 6: band

def test_below_the_band_fails_above_passes(root):
    ap = autopilot()
    assert not rules(first(run(root, ap, forward=forward_for(ap, position="below"))))["band"]["pass"]
    assert rules(first(run(root, ap, forward=forward_for(ap, position="above"))))["band"]["pass"]


def test_a_stale_or_missing_forward_report_fails_the_band(root):
    ap = autopilot()
    fwd = forward_for(ap)
    fwd["generated_ms"] = NOW - 40 * 3_600_000
    item = first(run(root, ap, forward=fwd))
    assert not rules(item)["band"]["pass"] and item["need_days"] == 38 + 15
    other = forward_for(autopilot(ap_id="zz"))
    assert rules(first(run(root, ap, forward=other)))["band"]["value"] == "not listed"


# ---------------------------------------------------------------- rule 7: reconcile

def test_reconcile_needs_seven_clean_days(root):
    ap = autopilot()
    # Five days of records and today's: six of seven.
    item = first(run(root, ap, history_days=5))
    assert not rules(item)["reconcile"]["pass"] and rules(item)["reconcile"]["value"] == "6/7 days"
    assert rules(first(run(root, ap, history_days=6)))["reconcile"]["pass"]


def test_a_mismatch_today_or_in_the_log_fails_reconcile(root):
    ap = autopilot()
    assert not rules(first(run(root, ap, state=state_of(ap, mismatches=1))))["reconcile"]["pass"]
    ev = [{"ts": NOW - 3 * DAY_MS, "message": "Alpaca paper reconcile BTC/USD: Pythia 0.1 (crypto:BTC/USD), "
                                               "Alpaca 0.2, difference -0.1 ($-6000.00): Mismatch. "}]
    item = first(run(root, ap, state=state_of(ap, events=ev)))
    assert not rules(item)["reconcile"]["pass"] and "unexplained" in rules(item)["reconcile"]["detail"]
    # A settled finding (fees taken) is explained.
    ok = [{"ts": NOW - 3 * DAY_MS, "message": "Alpaca paper reconcile BTC/USD: ...: FeeTaken. fees"}]
    assert rules(first(run(root, ap, state=state_of(ap, events=ok))))["reconcile"]["pass"]
    # Older than the window: forgotten.
    old = [{**ev[0], "ts": NOW - 9 * DAY_MS}]
    assert rules(first(run(root, ap, state=state_of(ap, events=old))))["reconcile"]["pass"]


# ---------------------------------------------------------------- rules 8 and 9: inflation and ETF

def test_annualised_return_against_inflation_and_the_etf_hurdle(root):
    # 0.03 % a day is about 11.6 % a year: above 3.8 % inflation, above the
    # balanced 10 % hurdle, below the bold 13 %.
    ap = autopilot(days=40, daily=0.0003)
    item = first(run(root, ap))
    assert rules(item)["inflation"]["pass"] and rules(item)["etf"]["pass"]
    assert 10 < item["annualised_pct"] < 13
    assert not rules(first(run(root, ap, step=5)))["etf"]["pass"]
    slow = autopilot(days=40, daily=0.00005)
    assert not rules(first(run(root, slow)))["inflation"]["pass"]


def test_no_inflation_figure_fails_rule_eight(root):
    none = {"inflation": hurdles.inflation(None, None), "sp500": None}
    item = first(run(root, autopilot(), macro=none))
    assert not rules(item)["inflation"]["pass"] and rules(item)["inflation"]["need"] == "unknown"
    assert rules(item)["etf"]["pass"], "the ETF hurdle does not need the index"


def test_inflation_uses_the_higher_figure_and_falls_back_to_the_cache(root):
    csv = "observation_date,CPIAUCSL\n" + "".join(f"2025-{m:02d}-01,{300 + m}\n" for m in range(1, 13)) \
        + "".join(f"2026-{m:02d}-01,{310 + m}\n" for m in range(1, 10))
    ea = json.dumps({"value": {"0": 2.1, "1": 3.8}, "dimension": {"time": {"category": {"index": {"2026-08": 0,
                                                                                              "2026-09": 1}}}}})
    sp = "observation_date,SP500\n2026-10-13,7805.45\n2026-10-14,.\n"
    answers = {hurdles.US_CPI_URL: csv, hurdles.EA_HICP_URL: ea, hurdles.SP500_URL: sp}
    m = hurdles.load(NOW, fetch=lambda url: answers[url])
    assert m["inflation"]["us"]["pct"] == pytest.approx((319 / 309 - 1) * 100, abs=0.01)
    assert m["inflation"]["pct"] == pytest.approx(3.8) and "HICP" in m["inflation"]["source"]
    assert m["sp500"]["closes"] == [["2026-10-13", 7805.45]] or m["sp500"]["closes"] == [("2026-10-13", 7805.45)]

    def down(url):
        raise OSError("no network")

    tomorrow = NOW + DAY_MS
    m2 = hurdles.load(tomorrow, fetch=down)
    assert m2["inflation"]["pct"] == pytest.approx(3.8) and m2["inflation"]["cached"] is True


# ---------------------------------------------------------------- the slider

def test_the_risk_step_comes_from_the_settings_file_and_defaults_to_the_middle(root):
    assert readiness.load_settings()["step"] == 3
    settle(root, 1)
    assert readiness.load_settings()["max_dd_pct"] == 5.0
    readiness.settings_path().write_text(json.dumps({"riskStep": 5}))
    assert readiness.load_settings()["min_days"] == 30
    readiness.settings_path().write_text(json.dumps({"risk_step": 9}))
    assert readiness.load_settings()["step"] == 3
    steps = [readiness.RISK_PROFILES[s] for s in range(1, 6)]
    assert [s["max_dd_pct"] for s in steps] == sorted(s["max_dd_pct"] for s in steps)
    assert [s["min_days"] for s in steps] == sorted((s["min_days"] for s in steps), reverse=True)


# ---------------------------------------------------------------- sleeves

def test_sleeves_are_judged_on_their_own_record(root):
    a = {"strategyId": "lab:tsmom", "name": "Momentum", "weight": 0.5, "pnl": 600.0, "trades": 25}
    b = {"strategyId": "lab:breakout", "name": "Breakout", "weight": 0.5, "pnl": -50.0, "trades": 25}
    ap = autopilot(days=60, sleeves=[a, b])
    started = ap["startedMs"]
    rows = []
    for k in range(59, 0, -1):
        ts = NOW - k * DAY_MS
        frac = (60 - k) / 60
        rows.append({"date": readiness._date(ts), "ts_ms": ts, "reconcile": {"fresh": True, "mismatches": 0},
                     "autopilots": {"ap-1": {"started_ms": started, "equity": None, "pnl": None, "bench_pct": 1.0 * frac,
                                             "sleeves": {"lab:tsmom": {"pnl": 600.0 * frac},
                                                         "lab:breakout": {"pnl": -50.0 * frac}}}}})
    settle(root)
    write_history(rows)
    rep = readiness.run(NOW, state=state_of(ap), forward=forward_for(ap), macro=MACRO, sender=lambda t: (True, None))
    kinds = [(i["kind"], i["id"]) for i in rep["autopilots"]]
    assert kinds[0] == ("autopilot", "ap-1") and len(kinds) == 3
    by = {i["id"]: i for i in rep["autopilots"]}
    assert by["lab:tsmom"]["since_ms"] == started, "seen in the first look, a day after the start"
    assert rules(by["lab:tsmom"])["profit"]["pass"] and not rules(by["lab:breakout"])["profit"]["pass"]
    assert rules(by["lab:tsmom"])["benchmark"]["pass"]
    assert by["lab:tsmom"]["need_days"] == 38 + 15


def test_a_sleeve_added_later_starts_its_own_clock(root):
    a = {"strategyId": "lab:a", "name": "A", "weight": 0.5, "pnl": 10.0, "trades": 25}
    b = {"strategyId": "lab:b", "name": "B", "weight": 0.5, "pnl": 10.0, "trades": 25}
    ap = autopilot(days=60, sleeves=[a, b])
    started = ap["startedMs"]
    rows = [{"date": readiness._date(NOW - k * DAY_MS), "ts_ms": NOW - k * DAY_MS,
             "reconcile": {"fresh": True, "mismatches": 0},
             "autopilots": {"ap-1": {"started_ms": started, "bench_pct": 0.0,
                                     "sleeves": {"lab:a": {"pnl": 0.0}, **({"lab:b": {"pnl": 0.0}} if k <= 10 else {})}}}}
            for k in range(50, 0, -1)]
    settle(root)
    write_history(rows)
    rep = readiness.run(NOW, state=state_of(ap), forward=forward_for(ap), macro=MACRO, sender=lambda t: (True, None))
    by = {i["id"]: i for i in rep["autopilots"]}
    assert by["lab:a"]["since_ms"] == NOW - 50 * DAY_MS, "first look 10 days after the start: no claim before it"
    assert by["lab:b"]["days"] == pytest.approx(10, abs=0.01)


# ---------------------------------------------------------------- the digest line and the alert

def test_digest_line(root):
    assert readiness.digest_text(None) == "no readiness report yet"
    rep = run(root, autopilot(days=20))
    line = readiness.digest_text(rep)
    assert "closest Autopilot ap-1" in line and "days to go" in line
    rep = run(root, autopilot())
    assert "ready for a real money proposal" in readiness.digest_text(rep)
    card, _ = notify.digest_card(None, None, None, {}, NOW, readiness=rep)
    assert any(getattr(p, "lead", None) == "Real money" for p in card.parts)


def test_a_failed_delivery_is_tried_again_next_day(root):
    ap = autopilot()
    settle(root)
    write_history(clean_history())
    tries = []
    readiness.run(NOW, state=state_of(ap), forward=forward_for(ap), macro=MACRO,
                  sender=lambda t: (tries.append(t) or False, "500"))
    for k in (1, 2):
        rep = readiness.run(NOW + k * DAY_MS, state=state_of(ap, at=NOW + k * DAY_MS),
                            forward=forward_for(ap, at=NOW + k * DAY_MS), macro=MACRO,
                            sender=lambda t: (tries.append(t) or True, None))
        assert rep["autopilots"][0]["ready"]
    assert len(tries) == 2


def test_the_alert_carries_the_numbers_and_the_owner_reminder(root):
    posts: list[str] = []
    run(root, autopilot(days=40, trades=30), posts=posts)
    text = notify.plain(posts[0])
    for word in ("40.0 days, 30 trades", "4 of 4", "7/7 days", "a year", "risk step 3, balanced",
                 "Only the owner can arm live. Nothing was armed or changed."):
        assert word in text, word
    assert "—" not in text


def test_the_alert_and_the_digest_line_in_german():
    from test_i18n import no_english
    item = {"name": "Momentum", "rules": [
        {"id": "record", "label": "Time and trades on the Alpaca paper account", "value": "40.0 days, 30 trades", "pass": True},
        {"id": "profit", "label": "Net P&L above zero after fees", "value": "+1,234.50 $", "pass": True},
        {"id": "weeks", "label": "Positive weeks", "value": "4 of 4", "pass": True},
        {"id": "band", "label": "Inside its backtest band", "value": "inside", "pass": True},
        {"id": "etf", "label": "Beats a plain ETF", "value": "+12.40 % a year", "pass": True}]}
    html = notify.render_post([readiness.alert_card(item, readiness.profile(3), "de")], lang="de")
    text = notify.plain(html)
    assert "Bereit für einen Echtgeld-Vorschlag" in text and "Risikostufe 3, ausgewogen" in text, text
    assert "40,0 Tage, 30 Abschlüsse" in text and "+1.234,50 $" in text and "4 von 4" in text, text
    assert "innerhalb" in text and "+12,40 % im Jahr" in text, text
    no_english(html)
    assert "Ready for a real money proposal" in notify.render_post([readiness.alert_card(item, readiness.profile(3), "en")])
    # The digest's line names the missing rules in German.
    rep = {"generated_ms": NOW, "autopilots": [{"name": "Momentum", "on_account": True, "passed": 7, "total": 9,
                                                "days_to_go": 0, "rules": [dict(r, **{"pass": r["id"] != "etf"})
                                                                           for r in item["rules"]]}]}
    line = notify.readiness_text(rep, NOW, "de")
    assert line == "noch keiner bereit; am nächsten Momentum: 7 von 9 Regeln, offen: ETF-Hürde", line
    assert notify.readiness_text({"status": "bad", "headline": "No autopilot engine answered"}, NOW, "de").startswith(
        "kein Autopilot-Server hat geantwortet")


def test_an_engine_that_does_not_answer_judges_nothing_and_forgets_nothing(root, monkeypatch):
    posts: list[str] = []
    ap = autopilot()
    run(root, ap, posts=posts)
    assert len(posts) == 1
    monkeypatch.setattr(readiness, "engines", lambda: [{"account": "main", "url": "http://engine", "state": None,
                                                        "error": "URLError: refused"}])
    rep = readiness.run(NOW + DAY_MS, forward=forward_for(ap), macro=MACRO,
                        sender=lambda t: (posts.append(t) or True, None))
    assert rep["status"] == "bad" and "No autopilot engine answered" in rep["headline"] and rep["autopilots"] == []
    assert "No autopilot engine answered" in readiness.digest_text(rep)
    # Back the next day and still ready: not announced again.
    readiness.run(NOW + 2 * DAY_MS, state=state_of(ap, at=NOW + 2 * DAY_MS), forward=forward_for(ap, at=NOW + 2 * DAY_MS),
                  macro=MACRO, sender=lambda t: (posts.append(t) or True, None))
    assert len(posts) == 1


def test_a_dry_run_writes_nothing(root):
    settle(root)
    readiness.run(NOW, state=state_of(autopilot()), forward=forward_for(autopilot()), macro=MACRO, dry_run=True,
                  sender=lambda t: (True, None))
    assert not readiness.history_path().exists()
    assert not (root / "reports" / "readiness" / "latest.json").exists()


def test_the_check_writes_only_its_own_files(root):
    run(root, autopilot())
    written = {str(p) for p in guard.WRITTEN}
    assert all("readiness" in p for p in written), written
