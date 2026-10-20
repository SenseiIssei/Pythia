"""The AI brief, the weekly review, the engine client and the scoring. No network:
every call goes to a fake engine.

Run from research/lab:  python -m pytest tests/test_ai.py
"""

from __future__ import annotations

import json
import math
from datetime import date, datetime, timedelta, timezone

import pytest

from lab.ai import brief, engine, facts, score, weekly
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
