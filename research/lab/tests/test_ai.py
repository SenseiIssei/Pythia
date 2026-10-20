"""The AI brief, the weekly review, the engine client and the scoring. No network:
every call goes to a fake engine.

Run from research/lab:  python -m pytest tests/test_ai.py
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from lab.ai import brief, chat, critic, director, engine, facts, score, weekly
from lab.ops import notify

NOW = int(datetime(2026, 10, 15, 6, 50, tzinfo=timezone.utc).timestamp() * 1000)
DAY_MS = 86_400_000


@pytest.fixture(autouse=True)
def lab(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("PYTHIA_REPORTS", str(tmp_path / "data" / "reports"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.delenv("PYTHIA_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("PYTHIA_ALERT_WEBHOOK", raising=False)
    return tmp_path


def series(n: int = 800, start: str = "2024-08-07", drift: float = 0.001, wiggle: float = 0.03) -> score.Closes:
    """Daily closes ending the day before NOW, a trend with a weekly wiggle."""
    d0 = date.fromisoformat(start)
    out, c = [], 100.0
    for i in range(n):
        c *= math.exp(drift + wiggle * math.sin(i * 0.9))
        out.append(((d0 + timedelta(days=i)).isoformat(), c))
    return out


def closes_until(last_day: str, n: int = 800) -> score.Closes:
    start = (date.fromisoformat(last_day) - timedelta(days=n - 1)).isoformat()
    return series(n, start)


STATE = {"autopilots": [
    {"state": "running", "config": {"name": "Core", "mode": "paper", "venue": "alpaca"}, "pnlPct": 1.5,
     "drawdownPct": 0.4, "trades": 12,
     "bySleeve": [{"name": "momentum", "weight": 0.6, "markets": ["crypto:SOL/USD", "crypto:BTC/USD"]},
                  {"name": "old", "weight": 0.0, "dropped": True, "markets": ["crypto:DOGE/USD"]},
                  {"name": "shares", "weight": 0.4, "markets": ["equity:AAPL"]}]},
    {"state": "stopped", "config": {"name": "Gone"}, "bySleeve": [{"markets": ["crypto:XRP/USD"]}]},
]}


def answer_for(coins, p=0.55, summary=("Market flat.", "Core autopilot up 1.5 %.", "Watch funding."), cost=0.0004):
    return {"text": "{}", "json": {"predictions": [{"coin": c, "pUp7d": p, "reason": f"{c} reason"} for c in coins],
                                    "summary": list(summary)},
            "parseError": None, "model": engine.ROUTINE, "servedBy": engine.ROUTINE,
            "usage": {"inputTokens": 3000, "outputTokens": 400}, "costUsd": cost, "batchId": "msgbatch_1"}


class Fake:
    """The engine's POST /api/ai/complete: records each body, answers in turn."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    def __call__(self, url, body, tok, timeout):
        self.calls.append({"url": url, "body": body, "token": tok, "timeout": timeout})
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return a if isinstance(a, tuple) else (200, a)


def closes_map(coins, last_day="2026-10-14"):
    return {c: closes_until(last_day) for c in coins}


# ---------------------------------------------------------------- the engine client

def test_the_token_is_the_engines_and_not_the_key():
    assert engine.token("sk-test") == "61fcf2d7f8fdb52a7489f7821d53c9e5250d5d42b0902a47a6c7b7fe3aefc224"
    assert engine.token("  ") == ""
    assert "sk-test" not in engine.token("sk-test")


def test_nothing_is_called_without_a_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    fake = Fake(answer_for(["BTC"]))
    with pytest.raises(engine.AiError) as e:
        engine.complete("brief", "s", "u", 100, poster=fake)
    assert e.value.kind == "nokey"
    assert fake.calls == []


@pytest.mark.parametrize("code,kind", [(402, "budget"), (503, "nokey"), (504, "timeout"), (502, "failed"), (403, "failed")])
def test_engine_refusals_become_kinds(code, kind):
    with pytest.raises(engine.AiError) as e:
        engine.complete("brief", "s", "u", 100, poster=Fake((code, {"error": "no"})))
    assert e.value.kind == kind


def test_an_answer_that_did_not_parse_is_unreadable_and_keeps_its_cost():
    bad = {"text": "nope", "json": None, "parseError": "not a JSON object: nope", "costUsd": 0.0003}
    with pytest.raises(engine.AiError) as e:
        engine.complete("brief", "s", "u", 100, schema=brief.SCHEMA, poster=Fake(bad))
    assert e.value.kind == "unreadable" and e.value.cost_usd == 0.0003


def test_the_request_carries_the_token_and_the_job():
    fake = Fake(answer_for(["BTC"]))
    engine.complete("brief", "sys", "facts", 1500, schema=brief.SCHEMA, batch=True, batch_wait_sec=600, poster=fake)
    c = fake.calls[0]
    assert c["token"] == engine.token("sk-test")
    assert c["body"]["job"] == "brief" and c["body"]["batch"] is True and c["body"]["batchWaitSec"] == 600
    assert c["body"]["model"] == "claude-haiku-5-5" and c["body"]["maxTokens"] == 1500
    assert "sk-test" not in json.dumps(c["body"])
    assert c["timeout"] > 600, "the HTTP wait covers the batch wait"


# ---------------------------------------------------------------- parsing the brief

def test_a_good_answer_parses():
    preds, summary, problems = brief.parse_answer(answer_for(["BTC", "ETH"])["json"], ["BTC", "ETH"])
    assert set(preds) == {"BTC", "ETH"} and preds["BTC"]["p"] == 0.55
    assert len(summary) == 3 and problems == []


@pytest.mark.parametrize("obj,problem", [
    ("not a dict", "not a JSON object"),
    ({"summary": ["a", "b", "c"]}, "no predictions list"),
    ({"predictions": [{"coin": "DOGE", "pUp7d": 0.5, "reason": "x"}], "summary": []}, "DOGE was not asked for"),
    ({"predictions": [{"coin": "BTC", "pUp7d": 1.7, "reason": "x"}], "summary": []}, "outside 0 to 1"),
    ({"predictions": [{"coin": "BTC", "pUp7d": "high", "reason": "x"}], "summary": []}, "not a number"),
    ({"predictions": [{"coin": "BTC", "pUp7d": float("nan"), "reason": "x"}], "summary": []}, "outside 0 to 1"),
    ({"predictions": [{"coin": "btc", "pUp7d": 0.6, "reason": "x"}, {"coin": "BTC", "pUp7d": 0.4, "reason": "y"}],
      "summary": []}, "BTC twice"),
    ({"predictions": ["BTC"], "summary": []}, "not an object"),
])
def test_bad_parts_are_dropped_and_named(obj, problem):
    preds, summary, problems = brief.parse_answer(obj, ["BTC"])
    assert any(problem in p for p in problems), problems
    assert all(0 <= v["p"] <= 1 for v in preds.values())


def test_reasons_and_summary_are_cleaned():
    dash = chr(0x2014)
    obj = {"predictions": [{"coin": "BTC", "pUp7d": 0.6, "reason": f"up {dash} because\n" + "x" * 400}],
           "summary": [f"one {dash} two", "", 5, "three", "four", "five"]}
    preds, summary, problems = brief.parse_answer(obj, ["BTC"])
    assert dash not in preds["BTC"]["reason"] and "\n" not in preds["BTC"]["reason"]
    assert len(preds["BTC"]["reason"]) <= 200
    assert summary == ["one - two", "three", "four"]


# ---------------------------------------------------------------- the references and the scores

def test_comparators_read_the_past_only():
    up = [(f"d{i}", 100 * 1.01 ** i) for i in range(800)]
    c = score.comparators(up)
    assert c["base"] > 0.95 and c["momentum"] > 0.95 and c["momentum_sign"] == "up"
    # Changing the future cannot change them: they use the closes they are given.
    assert score.comparators(up[:500]) == score.comparators(up[:500])
    assert score.comparators(up[:5]) == {"base": 0.5, "momentum": 0.5, "momentum_sign": None}


def test_metrics_and_paired_math():
    m = score.metrics([0.8, 0.2, 0.5], [1, 0, 1])
    assert m["n"] == 3
    assert m["brier"] == pytest.approx((0.04 + 0.04 + 0.25) / 3)
    assert m["hitRate"] == 1.0, "a 0.5 is no call"
    assert m["logloss"] == pytest.approx(-(math.log(0.8) + math.log(0.8) + math.log(0.5)) / 3)
    p = score.paired([0.9] * 20, [0.5] * 20, [1] * 20)
    assert p["diff"] == pytest.approx(0.01 - 0.25)
    assert p["t"] is None, "no spread, no t"


def test_verdict_waits_for_enough_weeks():
    assert score.verdict(5, {}, {}).startswith("Too early: 5 resolved")
    v = score.verdict(60, {"t": -3.0}, {"t": 0.4})
    assert "better than the momentum rule" in v and "no measurable difference to the base rate" in v
    assert "worse than the momentum rule" in score.verdict(60, {"t": 2.5}, {"t": None})


def test_predictions_resolve_seven_days_after_their_close():
    cl = {"BTC": [("2026-10-01", 100.0), ("2026-10-08", 110.0)], "ETH": [("2026-10-01", 100.0)]}
    rows = [{"date": "2026-10-02", "coin": "BTC", "ref_day": "2026-10-01", "ref_close": 100.0,
             "p_llm": 0.6, "p_base": 0.5, "p_momentum": 0.55},
            {"date": "2026-10-02", "coin": "ETH", "ref_day": "2026-10-01", "ref_close": 100.0,
             "p_llm": 0.6, "p_base": 0.5, "p_momentum": 0.55}]
    out = score.outcomes(rows, cl)
    assert out[0]["outcome"] == 1 and out[0]["end_close"] == 110.0
    assert out[1]["outcome"] is None, "ETH's week has no close yet"
    s = score.score(rows, cl, NOW)
    assert s["resolved"] == 1 and s["pending"] == 1
    assert s["sources"]["llm"]["brier"] == pytest.approx(0.16)
    assert s["sources"]["base"]["brier"] == pytest.approx(0.25)
    json.dumps(s, allow_nan=False)


# ---------------------------------------------------------------- the daily brief

def test_the_brief_asks_once_and_keeps_shadow_predictions(lab):
    coins = ["BTC", "ETH", "SOL"]
    fake = Fake(answer_for(coins))
    rc = brief.run(NOW, state=STATE, closes=closes_map(coins), poster=fake, funding_loader=lambda c: None)
    assert rc == 0 and len(fake.calls) == 1
    body = fake.calls[0]["body"]
    assert body["job"] == "brief" and body["batch"] is True and body["model"] == "claude-sonnet-5-5"
    assert body["effort"] == "medium"
    assert body["schema"] == brief.SCHEMA and body["maxTokens"] == brief.MAX_TOKENS
    assert body["system"] == brief.SYSTEM, "the fixed system prompt never changes, so it can be cached"
    assert "PREDICT: BTC, ETH, SOL" in body["user"]
    assert "DOGE" not in body["user"].split("PREDICT:")[1], "a dropped sleeve's coin is not asked"
    assert "Core (paper, alpaca, running)" in body["user"] and "rules: no stop rules" in body["user"]
    assert "Gone" not in body["user"], "a stopped autopilot without a stop time is left out"

    rows = score.read_predictions()
    assert [r["coin"] for r in rows] == coins
    r = rows[0]
    assert r["ref_day"] == "2026-10-14" and r["resolve_day"] == "2026-10-21" and r["p_llm"] == 0.55
    assert 0 < r["p_base"] < 1 and 0 < r["p_momentum"] < 1
    feed = notify.read_json(notify.reports_root() / "ai_brief" / "latest.json")
    assert feed["title"] == "AI brief" and feed["status"] == "ok" and feed["date"] == "2026-10-15"
    assert feed["summary"][0] == "Market flat." and len(feed["items"]) == 3
    assert "Shadow only" in feed["caveat"]
    sc = notify.read_json(notify.reports_root() / "ai" / "scores.json")
    assert sc["predictions"] == 3 and sc["pending"] == 3 and sc["verdict"].startswith("Too early")

    # The same day again: no second call, no second set of predictions.
    again = Fake(answer_for(coins))
    assert brief.run(NOW + 3_600_000, state=STATE, closes=closes_map(coins), poster=again) == 0
    assert again.calls == [] and len(score.read_predictions()) == 3


def test_a_budget_refusal_writes_nothing_and_is_not_a_failure(lab):
    fake = Fake((402, {"error": "AI budget: the daily cap of $1.50 would be crossed"}))
    assert brief.run(NOW, state=STATE, closes=closes_map(["BTC", "ETH", "SOL"]), poster=fake,
                     funding_loader=lambda c: None) == 0
    assert score.read_predictions() == []
    assert notify.read_json(notify.reports_root() / "ai_brief" / "latest.json") is None


def test_an_unreadable_answer_is_a_failure_and_keeps_nothing(lab):
    bad = {"text": "I think BTC goes up", "json": None, "parseError": "not a JSON object", "costUsd": 0.0004}
    assert brief.run(NOW, state=STATE, closes=closes_map(["BTC", "ETH", "SOL"]), poster=Fake(bad),
                     funding_loader=lambda c: None) == 1
    assert score.read_predictions() == []


def test_a_partly_wrong_answer_keeps_the_good_part(lab):
    a = answer_for(["BTC"])
    a["json"]["predictions"].append({"coin": "ETH", "pUp7d": 3, "reason": "x"})
    a["json"]["predictions"].append({"coin": "XYZ", "pUp7d": 0.5, "reason": "x"})
    assert brief.run(NOW, state=None, closes=closes_map(["BTC", "ETH"]), poster=Fake(a),
                     funding_loader=lambda c: None) == 0
    assert [r["coin"] for r in score.read_predictions()] == ["BTC"]
    feed = notify.read_json(notify.reports_root() / "ai_brief" / "latest.json")
    assert feed["status"] == "watch" and any("outside 0 to 1" in p for p in feed["problems"])


def test_a_batch_that_does_not_finish_falls_back_to_one_direct_call(lab):
    fake = Fake((504, {"error": "batch msgbatch_1 did not finish in time; cancelled"}), answer_for(["BTC", "ETH"]))
    assert brief.run(NOW, state=None, closes=closes_map(["BTC", "ETH"]), poster=fake,
                     funding_loader=lambda c: None) == 0
    assert [c["body"]["batch"] for c in fake.calls] == [True, False]
    assert fake.calls[1]["body"]["job"] == "brief-direct"
    assert len(score.read_predictions()) == 2


def test_a_dry_run_calls_nothing(lab, capsys):
    fake = Fake(answer_for(["BTC"]))
    assert brief.run(NOW, dry_run=True, state=None, closes=closes_map(["BTC", "ETH"]), poster=fake,
                     funding_loader=lambda c: None) == 0
    assert fake.calls == []
    assert "nothing called" in capsys.readouterr().out


def test_coins_come_from_running_autopilots_only():
    assert facts.autopilot_coins(STATE) == ["SOL", "BTC"]
    assert brief.pick_coins(STATE) == ["BTC", "ETH", "SOL"]
    assert facts.coin_of("equity:AAPL") is None and facts.coin_of("crypto:PEPE-USD") == "PEPE"


# ---------------------------------------------------------------- the digest

def test_the_digest_quotes_a_fresh_brief_only():
    b = {"date": "2026-10-15", "generated_ms": NOW - 3_600_000, "summary": [f"one {chr(0x2014)} a", "two", "three"]}
    assert notify.ai_lines({**b, "date": "2026-10-14"}, NOW) == [], "yesterday's brief is not today's news"
    lines = notify.ai_lines(b, NOW)
    assert [ln.text for ln in lines] == ["one - a", "two", "three"]
    assert lines[0].lead == "AI brief (shadow)"
    assert notify.ai_lines({**b, "generated_ms": NOW - 30 * 3_600_000}, NOW) == []
    card, _ = notify.digest_card(None, None, None, {}, NOW, ai=b)
    assert "AI brief (shadow)" in card.render("telegram")
    card, _ = notify.digest_card(None, None, None, {}, NOW)
    assert "AI brief" not in card.render("telegram")


# ---------------------------------------------------------------- the weekly review

def test_the_weekly_review_writes_proposals_and_runs_once_a_week(lab, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "breakout_study.md").write_text("# Breakout\n\nFails after costs at 41 bps.\n", encoding="utf-8")
    notify.write_json(notify.reports_root() / "forward" / "latest.json",
                      {"title": "Forward tests", "status": "watch", "headline": "2 of 5 inside their band", "items": []})
    ans = {"text": "## 1. Test funding carry\n- Why now: ...", "json": None, "model": engine.REVIEW,
           "servedBy": engine.REVIEW, "costUsd": 0.041, "batchId": "msgbatch_9"}
    fake = Fake(ans)
    assert weekly.run(NOW, state=STATE, results=results, poster=fake) == 0
    body = fake.calls[0]["body"]
    assert body["model"] == "claude-sonnet-5-5" and body["job"] == "weekly" and body["batch"] is True
    assert "schema" not in body
    assert "[breakout_study] Breakout: Fails after costs" in body["user"]
    assert "[Forward tests] status watch" in body["user"]
    md = (notify.reports_root() / "ai" / "weekly.md").read_text(encoding="utf-8")
    assert md.startswith("# Weekly AI review, 2026-10-15") and "Proposals only" in md and "Test funding carry" in md
    assert (notify.reports_root() / "ai" / "weekly-2026-10-15.md").exists()
    again = Fake(ans)
    assert weekly.run(NOW + DAY_MS, state=STATE, results=results, poster=again) == 0
    assert again.calls == [], "once per ISO week"


def test_the_weekly_review_without_budget_is_not_a_failure(lab, tmp_path):
    assert weekly.run(NOW, state=None, results=tmp_path, poster=Fake((402, {"error": "lifetime cap"}))) == 0
    assert not (notify.reports_root() / "ai" / "weekly.md").exists()


def test_an_evidence_line_keeps_the_status_date_apart_from_the_records_length():
    v = {"status": "below", "since": "2026-10-17", "return_pct": -4.545, "days": 13.0}
    line = weekly.evidence_line("book:tsmom_regime", v)
    assert line == "book:tsmom_regime: below since 2026-10-17 (forward record -4.5 % over 13 days)"
    assert "after 13 days since" not in line
    short = weekly.evidence_line("autopilot:ap_1", {"status": "early", "return_pct": 0.1, "days": 0.25})
    assert short == "autopilot:ap_1: early (forward record +0.1 % over 6 hours)"


# ---------------------------------------------------------------- models per job

def test_a_job_model_and_effort_can_be_changed_from_the_environment(monkeypatch):
    assert engine.model_for("brief", engine.REVIEW) == "claude-sonnet-5-5"
    monkeypatch.setenv("PYTHIA_AI_MODEL_BRIEF", "haiku")
    monkeypatch.setenv("PYTHIA_AI_MODEL_ASK", "claude-opus-5-5")
    monkeypatch.setenv("PYTHIA_AI_MODEL_CRITIC", "gpt-9")
    monkeypatch.setenv("PYTHIA_AI_EFFORT_DIRECTOR", "max")
    monkeypatch.setenv("PYTHIA_AI_EFFORT_ASK", "turbo")
    assert engine.model_for("brief", engine.REVIEW) == "claude-haiku-5-5"
    assert engine.model_for("ask", engine.REVIEW) == "claude-opus-5-5"
    assert engine.model_for("critic", engine.ROUTINE) == "claude-haiku-5-5", "not a Claude model: the default"
    assert engine.effort_for("director", "high") == "max"
    assert engine.effort_for("ask", "low") == "low"


# ---------------------------------------------------------------- the fact sheet

def test_the_fact_sheet_reads_every_part_and_leaves_out_what_is_missing(lab):
    rep = notify.reports_root()
    notify.write_json(rep / "readiness" / "latest.json", {"title": "Real money readiness", "status": "watch",
                                                          "headline": "none ready, closest Core 5 of 7", "items": []})
    notify.write_json(rep / "cs2" / "latest.json", {"title": "CS2", "status": "ok", "headline": "3 movers",
                                                    "items": [{"label": f"Skin {i}", "value": f"+{i} %"} for i in range(9)]})
    data = notify.data_root()
    notify.write_json(data / "pumpfun_rt" / "heartbeat.json",
                      {"t": NOW - 60_000, "connected": {"a": True, "b": False}, "reconnects": 4, "pools": 12})
    notify.write_json(data / "paper" / "pumpfun_rt" / "state.json",
                      {"pick": "early_buyers", "open": [{}],
                       "totals": {"early_buyers": {"n": 4, "wins": 1, "pnl_sol": -0.02, "ret_sum": -0.4}}})
    stopped = {"state": "stopped", "stoppedMs": NOW - 2 * DAY_MS, "stopReason": "max loss 10 % reached",
               "config": {"name": "Old", "mode": "demo", "venue": "alpaca", "stop": {"maxLossPct": 10}}}
    long_ago = {"state": "stopped", "stoppedMs": NOW - 30 * DAY_MS, "config": {"name": "Ancient"}}
    state = {"autopilots": STATE["autopilots"] + [stopped, long_ago]}
    sheet = facts.fact_sheet("2026-10-15", ["BTC"], closes_map(["BTC"]), state, ["BTC: last +0.0100 % per 8h"],
                             flow=[], now_ms=NOW)
    assert "PRICES" in sheet and "BTC: close" in sheet and "FUNDING" in sheet
    assert "FLOW AND POSITIONING" not in sheet, "an empty section is left out"
    assert "Old (demo, alpaca, stopped)" in sheet and "rules: max loss 10 %" in sheet and "max loss 10 % reached" in sheet
    assert "Ancient" not in sheet
    assert "[Real money readiness] status watch" in sheet
    assert "Skin 8 +8 %" in sheet, "a movers feed shows ten items"
    assert "1 of 2 streams connected" in sheet and "early_buyers: 4 paper trades, 25 % winners" in sheet
    assert chr(0x2014) not in sheet


def test_flow_lines_read_the_flow_lake(lab, tmp_path):
    import polars as pl
    flow = tmp_path / "flow"
    flow.mkdir()
    day0 = int(datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp() * 1e6)
    days = [day0 + i * 86_400_000_000 for i in range(44)]
    pl.DataFrame({"day_us": days * 2, "currency": ["BTC"] * 44 + ["ETH"] * 44,
                  "open": [1.0] * 88, "high": [1.0] * 88, "low": [1.0] * 88,
                  "close": [40.0 + i * 0.1 for i in range(44)] + [60.0] * 44}).write_parquet(flow / "dvol.parquet")
    pl.DataFrame({"day_us": days, "usdt": [1.0] * 44, "usdc": [1.0] * 44,
                  "total": [200e9 * (1 + 0.001 * i) for i in range(44)]}).write_parquet(flow / "stables.parquet")
    pl.DataFrame({"ts_us": [days[-1]] * 2, "currency": ["BTC", "BTC"], "days": [7.0, 29.0], "rr25": [0.01, 0.03],
                  "atm_iv": [0.4, 0.45], "call25_iv": [0.5, 0.5], "put25_iv": [0.5, 0.5], "n_options": [10, 10]}
                 ).write_parquet(flow / "skew.parquet")
    btc_day = datetime.fromtimestamp(days[-1] / 1e6, timezone.utc).strftime("%Y-%m-%d")
    pl.DataFrame({"ts_us": [days[-1] + 23 * 3_600_000_000], "open": [1.0], "high": [1.0], "low": [1.0],
                  "close": [100_100.0], "volume": [1.0]}).write_parquet(flow / "coinbase_btcusd_1h.parquet")
    lines = facts.flow_lines(flow, closes={"BTC": [(btc_day, 100_000.0)]})
    text = "\n".join(lines)
    assert "BTC DVOL (implied vol index) 44.3, 7d ago 43.6, 30d ago 41.3" in text
    assert "ETH DVOL" in text
    assert "BTC options 29d: 25-delta risk reversal +3.0 vol pts, ATM IV 45.0 %" in text, "the tenor nearest 30 days"
    assert "stablecoin supply $208.6 bn" in text
    assert "Coinbase premium over Binance at the daily close: +10.0 bps" in text
    assert facts.flow_lines(tmp_path / "nothing") == []


# ---------------------------------------------------------------- the brief in German

def test_a_german_chat_gets_german_lines_and_the_app_keeps_english(lab, monkeypatch):
    monkeypatch.setenv("PYTHIA_ALERT_LANG", "de")
    coins = ["BTC", "ETH"]
    a = answer_for(coins)
    a["json"]["summaryDe"] = ["Markt ruhig.", "Core liegt 1,5 % vorn.", "Finanzierung beobachten."]
    fake = Fake(a)
    assert brief.run(NOW, state=None, closes=closes_map(coins), poster=fake, funding_loader=lambda c: None) == 0
    body = fake.calls[0]["body"]
    assert body["schema"] == brief.SCHEMA_DE and "summaryDe" in body["user"]
    assert body["system"] == brief.SYSTEM, "the language goes into the prompt, never the cached system"
    feed = notify.read_json(notify.reports_root() / "ai_brief" / "latest.json")
    assert feed["summary"][0] == "Market flat." and feed["summary_de"][0] == "Markt ruhig."
    assert [ln.text for ln in notify.ai_lines(feed, NOW, "de")][0] == "Markt ruhig."
    assert [ln.text for ln in notify.ai_lines(feed, NOW, "en")][0] == "Market flat."


def test_scores_are_split_by_model():
    closes = {"BTC": closes_until("2026-10-14")}
    by_day = dict(closes["BTC"])
    rows = []
    for i, model in enumerate(["claude-haiku-5-5"] * 3 + ["claude-sonnet-5-5"] * 2):
        d = (date(2026, 9, 1) + timedelta(days=i)).isoformat()
        rows.append({"date": d, "coin": "BTC", "ref_day": d, "ref_close": by_day[d],
                     "resolve_day": score.resolve_day(d), "p_llm": 0.6, "p_base": 0.5, "p_momentum": 0.5,
                     "model": model})
    s = score.score(rows, closes, NOW)
    assert [(m["model"], m["n"]) for m in s["by_model"]] == [("claude-haiku-5-5", 3), ("claude-sonnet-5-5", 2)]


# ---------------------------------------------------------------- the weekly report's spend line

def test_the_weekly_report_says_what_claude_cost_per_job(lab):
    led = notify.data_root() / "ai" / "ledger.jsonl"
    led.parent.mkdir(parents=True)
    rows = [{"ts": NOW - DAY_MS, "job": "ask", "costUsd": 1.2}, {"ts": NOW - DAY_MS, "job": "ask", "costUsd": 0.8},
            {"ts": NOW - 2 * DAY_MS, "job": "brief", "costUsd": 0.05},
            {"ts": NOW - 2 * DAY_MS, "job": "brief-direct", "costUsd": 0.05},
            {"ts": NOW - 3 * DAY_MS, "job": "director", "costUsd": 0.6},
            {"ts": NOW - 9 * DAY_MS, "job": "ask", "costUsd": 50.0}]
    led.write_text("\n".join(json.dumps(x) for x in rows) + "\nnot json\n", encoding="utf-8")
    spend = notify.ai_spend_by_job(NOW - 7 * DAY_MS, NOW)
    assert spend["ask"] == (2.0, 2) and spend["brief"] == (pytest.approx(0.1), 2), "a direct retry is its job"
    ln = notify.ai_week_line(NOW, "en")
    assert ln.lead == "Claude API" and ln.text.startswith("$2.70 this week, $0.39 a day: ask $2.00, director $0.60")
    de = notify.ai_week_line(NOW, "de")
    assert de.text.startswith("diese Woche 2,70 $") and "Fragen 2,00 $" in de.text and "Forschungsleitung" in de.text
    led.unlink()
    assert notify.ai_week_line(NOW, "en") is None


# ---------------------------------------------------------------- the research director

def draft(slug="funding-carry-alpaca", title="Funding carry on Alpaca coins", **kw):
    d = {"slug": slug, "title": title, "question": "Does a funding filter lift the momentum book's Sharpe at 35 bps?",
         "whyNow": "fam_funding showed X.", "builtOn": ["family_funding", "tsmom_tranches"],
         "data": "Settled funding since 2020.", "design": "Walk-forward from 2024-01-01.",
         "trials": ["2 thresholds x 3 books = 6"], "trialCount": 6, "costs": "35 bps, 15 and 70 reported",
         "passRule": "Sharpe +0.2 at 35 bps and deflated p > 0.95 over the pool.", "killRule": "Below the book at 35 bps.",
         "effort": "Two hours of compute.", "couldFoolUs": "Funding history before 2021 is thin.",
         "line": f"{title}: a funding filter on the momentum book, six trials."}
    d.update(kw)
    return d


def director_answer(drafts, cost=0.42, extra=None):
    obj = {"proposals": drafts, "stopDoing": "Stop watching the breakout family."}
    obj.update(extra or {})
    return {"text": json.dumps(obj), "json": obj, "model": engine.DEEP, "servedBy": engine.DEEP,
            "costUsd": cost, "batchId": "msgbatch_d"}


def test_a_study_summary_puts_the_verdict_first():
    md = ("# Breakout family\n\nOpening words.\n\n## Method\n\nLong method text.\n\n## Verdict\n\n"
          "Fails after costs at 41 bps.\n\n| a | b |\n")
    title, s = director.study_summary(md, 200)
    assert title == "Breakout family"
    assert s.index("[Verdict] Fails after costs") < s.index("[Method]")
    assert s.startswith("Opening words.")
    _, short_s = director.study_summary(md, 30)
    assert len(short_s) <= 30 and short_s.endswith("…")


def test_the_director_writes_drafts_and_a_card_once_a_week(lab, tmp_path):
    results = tmp_path / "results"
    results.mkdir()
    (results / "breakout_study.md").write_text("# Breakout\n\n## Verdict\n\nFails after costs at 41 bps.\n", encoding="utf-8")
    factory = tmp_path / "factory"
    factory.mkdir()
    (factory / "ledger.jsonl").write_text(
        json.dumps({"key": "k1", "run": "2026-10-15", "name": "Donchian 100", "is_sharpe": 1.9, "is_h1": 3.0, "is_h2": 0.5})
        + "\n", encoding="utf-8")
    (factory / "holdout.jsonl").write_text(json.dumps({"key": "k1", "run": "2026-10-15", "name": "MA 10/100",
                                                       "oos_sharpe_35bps": 0.27, "oos_sharpe_70bps": -0.01,
                                                       "deflated_p": 0.0001, "pool_trials": 677,
                                                       "decision": "stopped", "why": "70 bps fails"}) + "\n",
                                           encoding="utf-8")
    drafts = tmp_path / "proposals"
    fake = Fake(director_answer([draft(), draft("vol-target-btc", "Vol target", trialCount="x"),
                                 draft("bad", "No pass", passRule=""), draft("funding-carry-alpaca", "Again")]))
    posts = []
    rc = director.run(NOW, state=STATE, results=results, factory=factory, drafts_dir=drafts, poster=fake,
                      send_poster=lambda text: posts.append(text) or (True, None))
    assert rc == 0 and len(fake.calls) == 1
    body = fake.calls[0]["body"]
    assert body["model"] == "claude-opus-5-5" and body["effort"] == "high" and body["batch"] is True
    assert body["maxTokens"] == 32000 and body["schema"] == director.SCHEMA and body["system"] == director.SYSTEM
    u = body["user"]
    assert "[breakout_study] Breakout: [Verdict] Fails after costs at 41 bps." in u
    assert "TRIAL LEDGER:" in u and "genome k1 (run 2026-10-15): Donchian 100; in-sample Sharpe 1.90, halves 3.00 / 0.50" in u
    assert "held-back check k1" in u and "70 bps fails" in u
    assert "DRAFTS ALREADY WRITTEN" in u and "- none yet" in u

    files = sorted(p.name for p in drafts.glob("*.md"))
    assert files == ["2026-10-15-funding-carry-alpaca-2.md", "2026-10-15-funding-carry-alpaca.md",
                     "2026-10-15-vol-target-btc.md"], "the draft without a pass rule is dropped, a repeated slug numbered"
    md = (drafts / "2026-10-15-funding-carry-alpaca.md").read_text(encoding="utf-8")
    assert md.startswith("# Funding carry on Alpaca coins: pre-registration draft (2026-10-15)")
    for head in ("## Question", "## Why now", "## Data", "## Design", "## Trials (6)", "## Pass rule", "## Kill rule",
                 "## What could fool us", "## Built on"):
        assert head in md, head
    assert "Nothing runs it" in md
    assert "## Trials (?)" in (drafts / "2026-10-15-vol-target-btc.md").read_text(encoding="utf-8")
    assert (notify.reports_root() / "ai" / "proposals" / "2026-10-15-vol-target-btc.md").exists(), "a copy for the PC"
    idx = notify.read_json(notify.reports_root() / "ai" / "director.json")
    assert idx["week"] == "2026-W42" and len(idx["proposals"]) == 3 and idx["costUsd"] == 0.42
    assert any("no question or no pass rule" in p for p in idx["problems"])
    assert len(posts) == 1 and "Research director: 3 study drafts" in posts[0] and "Stop doing" in posts[0]

    again = Fake(director_answer([draft()]))
    assert director.run(NOW + DAY_MS, state=STATE, results=results, factory=factory, drafts_dir=drafts,
                        poster=again) == 0
    assert again.calls == [], "once per ISO week"
    # The next week sees the drafts already written.
    nxt = Fake(director_answer([draft("x"), draft("y"), draft("z")]))
    director.run(NOW + 7 * DAY_MS, state=STATE, results=results, factory=factory, drafts_dir=drafts, poster=nxt,
                 send_poster=lambda t: (True, None))
    assert "2026-10-15-vol-target-btc: Vol target: pre-registration draft" in nxt.calls[0]["body"]["user"]


def test_the_director_in_german_and_without_budget(lab, tmp_path, monkeypatch):
    drafts = tmp_path / "proposals"
    assert director.run(NOW, state=None, results=tmp_path, factory=tmp_path, drafts_dir=drafts,
                        poster=Fake((402, {"error": "daily cap"}))) == 0
    assert not drafts.exists()
    monkeypatch.setenv("PYTHIA_ALERT_LANG", "de")
    ans = director_answer([draft("a"), draft("b"), draft("c")],
                          extra={"linesDe": ["Erster Entwurf.", "Zweiter.", "Dritter."], "stopDoingDe": "Ausbrüche ruhen lassen."})
    posts = []
    fake = Fake(ans)
    assert director.run(NOW, state=None, results=tmp_path, factory=tmp_path, drafts_dir=drafts, poster=fake,
                        send_poster=lambda t: posts.append(t) or (True, None)) == 0
    assert fake.calls[0]["body"]["schema"] == director.SCHEMA_DE
    assert "Forschungsleitung: 3 Studienentwürfe" in posts[0] and "Erster Entwurf." in posts[0]
    assert "Ausbrüche ruhen lassen." in posts[0] and "Kosten 0,42 $" in posts[0]


def test_a_dry_run_of_the_director_calls_nothing(lab, tmp_path, capsys):
    fake = Fake(director_answer([draft()]))
    assert director.run(NOW, dry_run=True, state=None, results=tmp_path, factory=tmp_path,
                        drafts_dir=tmp_path / "p", poster=fake) == 0
    assert fake.calls == [] and "nothing called" in capsys.readouterr().out


# ---------------------------------------------------------------- the strategy critic

H = 3_600_000


def order(ts, side, market="crypto:SOL/USD", qty=1.0, px=150.0, fee=0.06, book="ap1", **kw):
    o = {"id": f"o{ts}{side}", "ts": ts, "strategyId": "s1", "marketId": market, "side": side, "qty": qty,
         "filledQty": qty, "avgFillPrice": px, "status": "filled", "fee": fee, "route": "paper", "book": book,
         "realisedCostBps": 12.0, "modelledCostBps": 10.0}
    o.update(kw)
    return o


def critic_state(orders=None, **ap):
    a = {"state": "running", "config": {"id": "ap1", "name": "Core", "mode": "paper", "venue": "alpaca",
                                        "capitalUsd": 1000, "stop": {"trailingPct": 8}},
         "startCapital": 1000, "equity": 990, "pnlPct": -1.0, "drawdownPct": 2.0, "peakEquity": 1010,
         "floorEquity": 929, "trades": 10, "orders": 14, "fees": 3.1,
         "bySleeve": [{"strategyId": "s1", "name": "momentum", "weight": 1.0, "markets": ["crypto:SOL/USD"]}],
         "history": [[NOW - 20 * H, 1000.0], [NOW - 2 * H, 985.0]]}
    a.update(ap)
    return {"autopilots": [a], "orders": orders or [], "journal": [], "events": [],
            "markets": [{"id": "crypto:SOL/USD", "symbol": "SOL/USD", "price": 151.0, "change24h": -1.2}]}


def critic_answer(findings, cost=0.0002):
    obj = {"ok": not findings, "findings": findings}
    return {"text": json.dumps(obj), "json": obj, "model": engine.ROUTINE, "servedBy": engine.ROUTINE,
            "costUsd": cost, "batchId": "msgbatch_c"}


def finding(kind="churn", severity="medium", claim="SOL was bought and sold four times."):
    return {"kind": kind, "severity": severity, "claim": claim, "evidence": "4 round trips, $0.48 fees.",
            "check": "Look at the momentum sleeve's band."}


def test_the_numbers_settle_churn_fees_and_stops():
    flips = [order(NOW - (10 - i) * H, "buy" if i % 2 == 0 else "sell") for i in range(6)]
    m = critic.metrics(critic_state(flips)["autopilots"][0], flips, NOW - 24 * H)
    assert m["round_trips"] == 1 and m["max_flips"] == 5 and m["filled"] == 6
    assert m["fees_usd"] == pytest.approx(0.36) and m["cost_ratio"] == 1.2
    assert critic.verify("churn", m) == "confirmed"
    assert critic.verify("fees", m) == "not_confirmed", "cost 1.2x the model and 3.6 bps of equity"
    assert critic.verify("stop", m) == "not_confirmed"
    assert critic.verify("sizing", m) == "unchecked"
    quiet = critic.metrics(critic_state()["autopilots"][0], [], NOW - 24 * H)
    assert critic.verify("churn", quiet) == "not_confirmed"
    under = critic.metrics(critic_state(equity=920.0, history=[[NOW - 3 * H, 925.0]])["autopilots"][0], [], NOW - 24 * H)
    assert under["below_floor"] and critic.verify("stop", under) == "confirmed", "below the floor and still running"
    trail = critic.metrics(critic_state(drawdownPct=9.0)["autopilots"][0], [], NOW - 24 * H)
    assert critic.verify("stop", trail) == "confirmed"
    stopped = critic.metrics(critic_state(state="stopped", drawdownPct=9.0)["autopilots"][0], [], NOW - 24 * H)
    assert critic.verify("stop", stopped) == "not_confirmed", "it did stop"


def test_the_critic_checks_each_autopilot_logs_findings_and_posts_only_real_concerns(lab):
    flips = [order(NOW - (10 - i) * H, "buy" if i % 2 == 0 else "sell") for i in range(6)]
    old = order(NOW - 30 * H, "buy")
    other = order(NOW - 2 * H, "buy", book="ap9")
    rows = [{"account": "main", "state": critic_state(flips + [old, other])},
            {"account": "safe", "state": critic_state(config={"id": "ap2", "name": "Safe", "mode": "paper",
                                                              "venue": "alpaca", "capitalUsd": 500})}]
    fake = Fake(critic_answer([finding(), finding("sizing", "low", "Weights look off.")]), critic_answer([]))
    posts = []
    assert critic.run(NOW, rows=rows, poster=fake, send_poster=lambda t: posts.append(t) or (True, None)) == 0
    assert len(fake.calls) == 2
    bodies = sorted((c["body"] for c in fake.calls), key=lambda b: "Safe" in b["user"])
    b = bodies[0]
    assert b["model"] == "claude-haiku-5-5" and b["batch"] is True and b["job"] == "critic" and b["schema"] == critic.SCHEMA
    assert b["system"] == critic.SYSTEM
    assert "ORDERS (6, oldest first)" in b["user"], "the order before the window and another book's are left out"
    assert "- round_trips: 1" in b["user"] and "- max_flips: 5" in b["user"]
    assert "crypto:SOL/USD: price 151, 24h -1.20 %" in b["user"]
    log = critic.read_jsonl(critic.log_path())
    assert [(r["id"], r["kind"], r["auto"]) for r in log] == [("1015-1", "churn", "confirmed"),
                                                              ("1015-2", "sizing", "unchecked")]
    assert log[0]["autopilot"] == "Core · main" and log[0]["metrics"]["round_trips"] == 1
    assert len(posts) == 1, "one card, the low finding only logged"
    assert "Strategy check: 1 finding" in posts[0] and "[1015-1]" in posts[0] and "1015-2" not in posts[0]
    assert "the numbers confirm it" in posts[0]
    sc = notify.read_json(critic.score_path())
    assert sc["findings"] == 2 and sc["real"] == 1 and sc["undecided"] == 1 and sc["autopilot_days"] == 2

    # The owner settles the sizing finding; an unknown id is refused.
    assert critic.label("1015-2", "notreal", NOW) is True
    assert critic.label("9999-1", "real", NOW) is False
    sc = notify.read_json(critic.score_path())
    assert (sc["real"], sc["notreal"], sc["undecided"], sc["precision"]) == (1, 1, 0, 0.5)

    # Once a day; with --force the ids count on.
    again = Fake(critic_answer([finding()]))
    assert critic.run(NOW + H, rows=rows, poster=again) == 0 and again.calls == []
    assert critic.run(NOW + H, force=True, rows=rows[:1], poster=again, send_poster=lambda t: (True, None)) == 0
    assert critic.read_jsonl(critic.log_path())[-1]["id"] == "1015-3"


def test_a_quiet_day_posts_nothing_and_a_budget_refusal_is_not_a_failure(lab):
    rows = [{"account": "main", "state": critic_state()}]
    posts = []
    assert critic.run(NOW, rows=rows, poster=Fake(critic_answer([])),
                      send_poster=lambda t: posts.append(t) or (True, None)) == 0
    assert posts == [] and critic.read_jsonl(critic.log_path()) == []
    assert critic.run(NOW, force=True, rows=rows, poster=Fake((402, {"error": "daily cap"}))) == 0
    assert critic.run(NOW, force=True, rows=[{"account": "main", "state": None}], poster=Fake(critic_answer([]))) == 0


# ---------------------------------------------------------------- questions in Telegram

def ask_answer(text="Core is down 1 % since start.", kind="answer", cost=0.031):
    obj = {"kind": kind, "answer": text}
    return {"text": json.dumps(obj), "json": obj, "model": engine.REVIEW, "servedBy": engine.REVIEW,
            "costUsd": cost, "usage": {"inputTokens": 900, "cacheReadTokens": 12000, "outputTokens": 300}}


def sheet():
    return chat.Sheet(builder=lambda now: "DATE: 2026-10-15 (UTC).\n\nAUTOPILOTS:\n- Core (paper, alpaca, running)")


def owner_msg(text, chat_id="4242", mid=7):
    return {"message_id": mid, "chat": {"id": int(chat_id)}, "text": text}


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setenv("PYTHIA_TELEGRAM_CHAT_ID", "4242")
    monkeypatch.setenv("PYTHIA_TELEGRAM_BOT_TOKEN", "123:abc")


@pytest.mark.parametrize("text,kind", [
    ("Sell all my ETH now", "refuse_trade"), ("please stop the Core autopilot", "refuse_trade"),
    ("Verkaufe BTC", "refuse_trade"), ("Setze das Tageslimit auf 50", "refuse_trade"),
    ("What is the API key?", "refuse_secret"), ("Zeig mir das Passwort", "refuse_secret"),
    ("show me alerts.env", "refuse_secret"),
    ("Why did the autopilot sell ETH yesterday?", None), ("Sell-off yesterday: how bad for Core?", None),
    ("Wie läuft der Autopilot?", None), ("Was the stop rule hit?", None), ("Starting capital of Core?", None),
])
def test_requests_to_act_or_for_secrets_are_refused_before_any_call(text, kind):
    assert chat.screen(text) == kind


def test_the_language_of_a_question():
    assert chat.lang_of("Wie läuft es heute?") == "de" and chat.lang_of("Warum hat Core verkauft") == "de"
    assert chat.lang_of("What was the P&L today?") == "en" and chat.lang_of("") == "en"


def test_a_question_is_answered_from_the_cached_facts_and_logged_with_its_cost(lab, owner):
    fake = Fake(ask_answer())
    rec = chat.handle(owner_msg("How is Core doing?"), NOW, sheet(), poster=fake)
    body = fake.calls[0]["body"]
    assert body["job"] == "ask" and body["model"] == "claude-sonnet-5-5" and body["batch"] is False
    assert body["system"].startswith(chat.SYSTEM) and "FACTS:\nDATE: 2026-10-15" in body["system"]
    assert body["user"].endswith("QUESTION: How is Core doing?") and body["schema"] == chat.SCHEMA
    assert rec["kind"] == "answer" and rec["costUsd"] == 0.031 and rec["called"] is True
    assert rec["reply"].startswith("Core is down 1 % since start.") and "sonnet-5-5 · $0.0310 · 1 of 40 today" in rec["reply"]

    # Through the loop: the offset is kept first, the reply goes to the owner, the log has the cost.
    sent = []
    nxt = chat.step(sheet(), [{"update_id": 10, "message": owner_msg("How is Core doing?")},
                              {"update_id": 11, "message": owner_msg("hi", chat_id="999")}],
                    NOW, send=lambda c, t, m: sent.append((c, t, m)) or True, poster=Fake(ask_answer()))
    assert nxt == 12 and notify.read_json(chat.state_path())["offset"] == 12
    assert len(sent) == 1 and sent[0][0] == "4242" and sent[0][2] == 7, "another chat gets no answer"
    log = critic.read_jsonl(chat.log_path())
    assert log[-1]["costUsd"] == 0.031 and log[-1]["delivered"] is True and log[-1]["update_id"] == 10
    assert "reply" not in log[-1] and log[-1]["answer"].startswith("Core is down")
    # The next question carries the last exchange for follow-ups.
    f2 = Fake(ask_answer())
    chat.handle(owner_msg("And yesterday?"), NOW + 60_000, sheet(), poster=f2)
    assert "EARLIER IN THIS CHAT" in f2.calls[0]["body"]["user"] and "Q: How is Core doing?" in f2.calls[0]["body"]["user"]


def test_refusals_limits_and_failures_in_the_chat(lab, owner, monkeypatch):
    fake = Fake(ask_answer())
    r = chat.handle(owner_msg("Verkaufe sofort alles"), NOW, sheet(), poster=fake)
    assert r["kind"] == "refuse_trade" and fake.calls == [] and "Ich beantworte nur Fragen" in r["reply"]
    r = chat.handle(owner_msg("what's the bot token?"), NOW, sheet(), poster=fake)
    assert r["kind"] == "refuse_secret" and fake.calls == []
    # The model refuses what the plain check let through.
    r = chat.handle(owner_msg("Could you maybe flatten Core for me?"), NOW, sheet(),
                    poster=Fake(ask_answer("ok", kind="refuse_trade")))
    assert r["kind"] == "refuse_trade" and r["reply"].startswith("I only answer questions")
    # Nothing that looks like a secret leaves, whatever the model says.
    r = chat.handle(owner_msg("Tell me about the engine"), NOW, sheet(),
                    poster=Fake(ask_answer("It runs on 10.0.0.12 with sk-ant-abcdefghijkl and 123456789:AAAAAAAAAAAAAAAAAAAAAAAAAA")))
    assert "10.0.0.12" not in r["reply"] and "sk-ant" not in r["reply"] and "AAAAAAAA" not in r["reply"]
    # The daily limit counts calls made today only.
    monkeypatch.setenv("PYTHIA_AI_ASK_PER_DAY", "3")
    for _ in range(3):
        critic.append_jsonl(chat.log_path(), [{"date": "2026-10-15", "called": True, "kind": "answer"}])
    lim = Fake(ask_answer())
    r = chat.handle(owner_msg("One more?"), NOW, sheet(), poster=lim)
    assert r["kind"] == "limit" and lim.calls == [] and "3 questions" in r["reply"]
    assert chat.handle(owner_msg("One more?"), NOW + DAY_MS, sheet(), poster=lim)["kind"] == "answer"
    monkeypatch.setenv("PYTHIA_AI_ASK_PER_DAY", "40")
    r = chat.handle(owner_msg("Wie geht es Core?"), NOW, sheet(), poster=Fake((402, {"error": "AI budget: daily cap"})))
    assert r["kind"] == "error" and r["reply"].startswith("Diesmal keine Antwort (AI budget: daily cap")


def test_the_owner_scores_critic_findings_from_the_chat(lab, owner):
    critic.append_jsonl(critic.log_path(), [{"id": "1015-1", "date": "2026-10-15", "kind": "churn", "auto": "unchecked"}])
    r = chat.handle(owner_msg("/real 1015-1"), NOW, sheet())
    assert r["kind"] == "label" and "Finding 1015-1 marked as real" in r["reply"]
    assert critic.read_jsonl(critic.labels_path())[0]["verdict"] == "real"
    assert "Es gibt keinen Befund 77" in chat.handle(owner_msg("/notreal 77 bitte"), NOW, sheet())["reply"]
    assert "Ask me anything" in chat.handle(owner_msg("/help"), NOW, sheet())["reply"]
    assert chat.handle(owner_msg("/real 1015-1", chat_id="5"), NOW, sheet()) is None


def test_the_fact_sheet_is_reused_until_it_is_old():
    built = []
    s = chat.Sheet(builder=lambda now: built.append(now) or f"sheet {len(built)}", ttl_s=900)
    assert s.get(NOW) == "sheet 1" and s.get(NOW + 60_000) == "sheet 1", "the cached prefix stays the same"
    assert s.get(NOW + 901_000) == "sheet 2"
    boom = chat.Sheet(builder=lambda now: 1 / 0)
    assert "could not be built" in boom.get(NOW)
