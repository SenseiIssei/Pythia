"""B4, the local language model (lab.ai.local): the call helper against a fake OpenAI-compatible server (the
relay to the owner's PC first when it is online, then the VPS model, then nothing), the number rule of the
summaries, the news tags, and their users (the briefing's summary line and news, the lab card's top line). No real
model anywhere.

Run from research/lab:  python -m pytest tests/test_ai_local.py
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from lab.ai import local
from lab.ops import briefing, labor, notify

OPS = Path(__file__).resolve().parents[2] / "ops"
TOKEN = "client-token-for-tests"


def utc(*a) -> int:
    return int(datetime(*a, tzinfo=timezone.utc).timestamp() * 1000)


class Fake:
    """A fake OpenAI-compatible server: answer(body) gives the chat text (or an int: that HTTP status), status the
    JSON of the status route (or an int). Every request is kept (path, headers, body)."""

    def __init__(self, answer=None, status=None):
        self.answer = answer or (lambda body: "Alles ruhig.")
        self.status = {"online": True} if status is None else status
        self.seen: list[dict] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, d):
                b = json.dumps(d).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_GET(self):
                fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
                st = fake.status
                self._send(st, {}) if isinstance(st, int) else self._send(200, st)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.seen.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
                a = fake.answer(body)
                if isinstance(a, int):
                    return self._send(a, {"error": "x"})
                self._send(200, {"choices": [{"message": {"role": "assistant", "content": a}}],
                                 "usage": {"completion_tokens": 12}})

        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def chats(self) -> list[dict]:
        return [r for r in self.seen if r["path"].endswith("/chat/completions")]


@pytest.fixture()
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("PYTHIA_DATA", str(tmp_path))
    for k in ("PYTHIA_REPORTS", "PYTHIA_LOCAL_LLM", "PYTHIA_LOCAL_LLM_URL", "PYTHIA_LOCAL_LLM_RELAY_URL",
              "PYTHIA_LOCAL_LLM_TOKEN", "PYTHIA_LOCAL_LLM_RELAY_STATUS", "PYTHIA_ALERT_LANG"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


@pytest.fixture()
def servers():
    made = []

    def make(**kw):
        f = Fake(**kw)
        made.append(f)
        return f
    yield make
    for f in made:
        f.srv.shutdown()


def dead_url() -> str:
    """A local port nothing listens on."""
    s = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    url = f"http://127.0.0.1:{s.server_address[1]}"
    s.server_close()
    return url


def calls(root: Path) -> list[dict]:
    p = root / "ai" / "local_llm.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ---------------------------------------------------------------- the number rule

def test_numbers_must_come_from_the_facts_in_either_notation():
    facts = ["pump.fun gestern: 3 Trades, +0,0123 SOL · Wallet 1.234,50 €", "papier today +$4.20", "F3 2026-10-26"]
    assert local.foreign_numbers("3 Trades brachten +0,0123 SOL, Wallet 1.234,50 €.", facts) == []
    assert local.foreign_numbers("3 trades made 0.0123 SOL; wallet €1,234.50; paper 4,20 $.", facts) == []
    assert local.foreign_numbers("F3 lief am 2026-10-26.", facts) == [], "dates and names carry no sign"
    assert local.foreign_numbers("4 Trades brachten 0,0123 SOL.", facts) == ["4"]
    assert local.foreign_numbers("Der Bot verlor -0,0123 SOL.", facts) == ["-0,0123"], "a sign flip is caught"
    assert local.foreign_numbers("Die Wallet hat 1.234 €.", facts) == ["1.234"], "no rounding"
    assert local.foreign_numbers("Rund 12 % mehr.", facts) == ["12"]


# ---------------------------------------------------------------- the backends

def test_the_owners_pc_first_when_the_relay_says_online(data, servers, monkeypatch):
    relay, vps = servers(answer=lambda b: "Vom PC."), servers(answer=lambda b: "Vom VPS.")
    env = {"PYTHIA_LOCAL_LLM_RELAY_URL": relay.url, "PYTHIA_LOCAL_LLM_TOKEN": TOKEN, "PYTHIA_LOCAL_LLM_URL": vps.url}
    ans = local.chat([{"role": "user", "content": "hi"}], "t", max_tokens=33, env=env)
    assert ans["text"] == "Vom PC." and ans["backend"] == "relay" and not vps.seen
    st, ch = relay.seen[0], relay.chats()[0]
    assert st["path"] == "/status" and ch["path"] == "/v1/chat/completions"
    assert ch["auth"] == f"Bearer {TOKEN}" and ch["body"]["max_tokens"] == 33
    assert TOKEN not in (data / "ai" / "local_llm.jsonl").read_text(), "the token is never logged"

    relay.status = {"online": False}
    ans = local.chat([{"role": "user", "content": "hi"}], "t", env=env)
    assert ans["backend"] == "vps" and ans["text"] == "Vom VPS." and vps.chats()[0]["auth"] is None, \
        "the VPS model never gets the token"
    relay.status = 503
    assert local.chat([{"role": "user", "content": "hi"}], "t", env=env)["backend"] == "vps"
    relay.status, relay.answer = {"pc": "x"}, (lambda b: 502)
    assert local.chat([{"role": "user", "content": "hi"}], "t", env=env)["backend"] == "vps", \
        "online but its answer failed: the VPS model"
    assert [b["name"] for b in local.backends({"PYTHIA_LOCAL_LLM_RELAY_URL": relay.url})] == ["vps"], "no token"


def test_no_text_when_nothing_answers_or_the_switch_is_off(data, servers):
    env = {"PYTHIA_LOCAL_LLM_URL": dead_url()}
    assert local.chat([{"role": "user", "content": "hi"}], "t", env=env) is None
    assert calls(data)[-1]["ok"] is False and calls(data)[-1]["backend"] == "vps"
    assert local.summary(["3 Trades"], "VORLAGE", "de", env=env) == "VORLAGE"
    vps = servers()
    assert local.backends({"PYTHIA_LOCAL_LLM": "off", "PYTHIA_LOCAL_LLM_URL": vps.url}) == []
    assert local.summary(["3 Trades"], "VORLAGE", "de", env={"PYTHIA_LOCAL_LLM": "off",
                                                              "PYTHIA_LOCAL_LLM_URL": vps.url}) == "VORLAGE"
    assert not vps.seen
    assert local.chat([{"role": "user", "content": "hi"}], "t", deadline=time.monotonic(),
                      env={"PYTHIA_LOCAL_LLM_URL": vps.url}) is None and not vps.seen, "no time left: no call"


def test_a_slow_model_is_cut_off_by_the_timeout(data, servers):
    vps = servers(answer=lambda b: time.sleep(3) or "spät")
    t0 = time.monotonic()
    assert local.chat([{"role": "user", "content": "hi"}], "t", deadline=time.monotonic() + 1.5,
                      env={"PYTHIA_LOCAL_LLM_URL": vps.url}) is None
    assert time.monotonic() - t0 < 2.8
    assert calls(data)[-1]["why"].startswith(("TimeoutError", "URLError", "timeout"))


# ---------------------------------------------------------------- the summary

FACTS = ["pump.fun gestern: 3 Trades, 2 gewonnen, +0,0123 SOL", "Wallet 12,34 €", "Forschung: 2 Aufgaben fertig"]


@pytest.mark.parametrize("said, ok, why", [
    ("Der Bot hat gestern mit 3 Trades +0,0123 SOL gewonnen. Die Wallet steht bei 12,34 €.", True, None),
    ("<think>12 + 3 = 15</think>Der Bot hat 3 Trades gemacht. Sonst ist es ruhig.", True, None),
    ("Der Bot hat mit 3 Trades +0,0123 SOL gewonnen, das sind 1,97 €.", False, "numbers not in the facts: 1,97"),
    ("Der Bot hat 4 Trades gemacht.", False, "numbers not in the facts: 4"),
    ("", False, "empty answer"),
    ("Ruhig. " * 60, False, "too long"),
])
def test_the_summary_keeps_only_numbers_from_the_facts(data, servers, said, ok, why):
    vps = servers(answer=lambda b: said)
    out = local.summary(FACTS, "VORLAGE", "de", use="briefing:de", env={"PYTHIA_LOCAL_LLM_URL": vps.url})
    body = vps.chats()[0]["body"]
    assert "zwei kurze" in body["messages"][0]["content"] and "- Wallet 12,34 €" in body["messages"][1]["content"]
    assert body["max_tokens"] == local.MAX_TOKENS
    if ok:
        assert out != "VORLAGE" and "<think>" not in out and "\u2014" not in out
    else:
        assert out == "VORLAGE"
        assert calls(data)[-1]["why"].startswith(why) and calls(data)[-1]["use"] == "briefing:de"


def test_one_budget_and_one_backend_check_for_both_languages(data, servers):
    relay = servers(answer=lambda b: "Der Bot hat 3 Trades gemacht.")
    env = {"PYTHIA_LOCAL_LLM_RELAY_URL": relay.url, "PYTHIA_LOCAL_LLM_TOKEN": TOKEN}
    run = local.summarizer(60, "briefing", env=env)
    assert run(FACTS, "T", "de") == "Der Bot hat 3 Trades gemacht."
    assert run(FACTS, "T", "en") == "Der Bot hat 3 Trades gemacht."
    assert sum(1 for r in relay.seen if r["path"] == "/status") == 1, "the relay is asked once"
    assert "two short" in relay.chats()[1]["body"]["messages"][0]["content"]
    gone = local.summarizer(0, "briefing", env=env)
    assert gone(FACTS, "T", "de") == "T" and len(relay.chats()) == 2, "budget spent: the template, no call"
    one = local.summarizer(60, "labor", env=env, sentences=1)
    one(FACTS, "T", "de")
    assert "genau einen kurzen" in relay.chats()[-1]["body"]["messages"][0]["content"]


# ---------------------------------------------------------------- the news

def write_news(root: Path, day: str, titles: list[str], at: int) -> None:
    p = root / "ai" / "news" / f"{day}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps({"title": t, "link": f"https://news.example/{i}", "source": "X",
                                     "published_us": (at - i * 60_000) * 1000, "coins": ["BTC"] if i == 0 else []})
                         + "\n" for i, t in enumerate(titles)))


def test_parse_tags_takes_only_known_topics_and_relevances():
    text = "1|solana|4\n2 | regulation | 5\n3|weather|3\n4|bitcoin|9\n9|macro|2\n2|etf|1\nnoise"
    assert local.parse_tags(text, 5) == {0: {"topic": "solana", "relevance": 4},
                                         1: {"topic": "regulation", "relevance": 5}}


def test_news_tags_every_new_headline_once(data, servers, monkeypatch):
    now = utc(2026, 10, 26, 12, 0)
    titles = [f"Headline {i}" for i in range(11)]
    write_news(data, "2026-10-26", titles, now)

    def answer(body):
        n = len(body["messages"][1]["content"].splitlines())
        return "\n".join(f"{j}|{'solana' if j % 2 else 'macro'}|{1 + j % 5}" for j in range(1, n + 1) if j != 2)
    vps = servers(answer=answer)
    monkeypatch.setenv("PYTHIA_LOCAL_LLM_URL", vps.url)
    monkeypatch.setattr(local, "NEWS_BATCH", 4)
    assert local.tag_news(now) == 8, "three batches, the second line of each left out"
    tags = local.read_tags("2026-10-26")
    assert tags["https://news.example/0"] == {"topic": "solana", "relevance": 2, "by": "vps"}
    assert tags["https://news.example/1"] == {"asked": 1}
    assert len(vps.chats()) == 3 and "Topics: bitcoin" in vps.chats()[0]["body"]["messages"][0]["content"]
    assert local.tag_news(now) == 2 and len(vps.chats()) == 4, "only the three skipped ones again, in one call"
    tags = local.read_tags("2026-10-26")
    assert "relevance" in tags["https://news.example/1"] and tags["https://news.example/5"] == {"asked": 2}
    assert local.tag_news(now) == 0 and len(vps.chats()) == 4, "asked twice: left alone"


def test_news_without_a_model_leaves_the_headlines_untagged(data, monkeypatch):
    now = utc(2026, 10, 26, 12, 0)
    write_news(data, "2026-10-26", ["A", "B"], now)
    monkeypatch.setenv("PYTHIA_LOCAL_LLM_URL", dead_url())
    assert local.tag_news(now) == 0 and local.read_tags("2026-10-26") == {}
    assert local.main(["--news"]) == 0


def test_the_briefing_shows_the_three_most_relevant_headlines(data):
    now = utc(2026, 10, 26, 12, 0)
    write_news(data, "2026-10-26", ["Coin news, newest", "Dull", "Big one", "Second", "Third"], now)
    newest = [ln.links[0][0] for ln in briefing.news_section(now, "en")]
    assert newest == ["Coin news, newest", "Dull", "Big one"], "untagged: coins first, then the newest"
    notify.write_json(data / "ai" / "news_tags" / "2026-10-26.json", {
        "https://news.example/2": {"topic": "regulation", "relevance": 5},
        "https://news.example/4": {"topic": "solana", "relevance": 4},
        "https://news.example/3": {"topic": "macro", "relevance": 4},
        "https://news.example/1": {"asked": 2}})
    top = [ln.links[0][0] for ln in briefing.news_section(now, "en")]
    assert top == ["Big one", "Second", "Third"]


# ---------------------------------------------------------------- the briefing and the lab card

def fill(root: Path, now: int) -> None:
    def w(rel, d):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(d))
    w("reports/research/latest.json", {"updated_ms": now - 600_000, "queued": 2, "held": [],
                                       "done": [{"title": "R1", "ok": True, "at": now - 3_600_000, "why": "ja"}]})
    w("reports/pumpfun_rt/factory.json", {
        "updated_ms": now - 3_600_000, "night": "2026-10-26", "trials_ever": 330, "trials_tonight": 30,
        "bar": {"sharpe": 0.1234, "trials": 330}, "start_sol": 0.55, "best": [], "books": [], "models": {}})


def test_the_briefing_summary_comes_from_the_model_only_with_its_facts(data, servers, monkeypatch):
    now = utc(2026, 10, 26, 7, 0)
    fill(data, now)
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    seen = []

    def fake(facts, template, lang):
        seen.append((list(facts), template, lang))
        return "Eine Aufgabe ist fertig."
    cards, _ = briefing.build(now, "de", [], [], 158.2, {}, summarize=fake)
    facts, template, lang = seen[0]
    assert cards[0].summary == "Eine Aufgabe ist fertig." and lang == "de"
    assert template == "1 Aufgabe fertig", "the template is what the briefing wrote before"
    assert any("330" in f for f in facts) and any("R1" in f for f in facts) and len(facts) <= briefing.MAX_FACTS
    assert briefing.build(now, "de", [], [], 158.2, {})[0][0].summary == template, "no model: the template"

    vps = servers(answer=lambda b: "Die Fabrik hat 30 Versuche gemacht. Sie hat 99 Gewinner.")
    monkeypatch.setenv("PYTHIA_LOCAL_LLM_URL", vps.url)
    cards, _ = briefing.build(now, "de", [], [], 158.2, {}, summarize=local.summarizer(60, "briefing"))
    assert cards[0].summary == template, "99 is in no fact: the template"
    vps.answer = lambda b: "Die Fabrik hat 30 Versuche gemacht. Eine Aufgabe ist fertig."
    cards, _ = briefing.build(now, "de", [], [], 158.2, {}, summarize=local.summarizer(60, "briefing"))
    assert cards[0].summary == "Die Fabrik hat 30 Versuche gemacht. Eine Aufgabe ist fertig."


def test_the_briefing_run_asks_the_model_within_its_budget(data, servers, monkeypatch):
    now = utc(2026, 10, 23, 7, 0)
    fill(data, now)
    monkeypatch.setenv("PYTHIA_AUTOPILOT_STATE_URL", "off")
    monkeypatch.setenv("PYTHIA_QUIET_HOURS", "off")
    vps = servers(answer=lambda b: "Eine Aufgabe ist fertig.")
    monkeypatch.setenv("PYTHIA_LOCAL_LLM_URL", vps.url)
    tg = []
    assert briefing.LLM_BUDGET_SEC == 60
    assert briefing.run(now, engines=[], eur=150.0, chart=False, dry_run=False,
                        poster=lambda text: tg.append(text) or (True, None)) == 0
    assert tg and "Eine Aufgabe ist fertig." in tg[0] and len(vps.chats()) >= 1


def test_the_lab_card_gets_one_sentence_on_top(data, servers, monkeypatch):
    now = utc(2026, 10, 26, 18, 30)
    fill(data, now)
    vps = servers(answer=lambda b: "Die Fabrik F3 hat 30 Versuche gemacht.")
    monkeypatch.setenv("PYTHIA_LOCAL_LLM_URL", vps.url)
    card = labor.build(now, "de", 160.0, summarize=local.summarizer(60, "labor", sentences=1))
    assert card.summary == "Die Fabrik F3 hat 30 Versuche gemacht."
    body = vps.chats()[0]["body"]
    assert "genau einen kurzen" in body["messages"][0]["content"] and "330" in body["messages"][1]["content"]
    vps.answer = lambda b: "Die Fabrik F3 hat 31 Versuche gemacht."
    card = labor.build(now, "de", 160.0, summarize=local.summarizer(60, "labor", sentences=1))
    assert card.summary == notify.tr("lb_summary", "de"), "31 is not in the lines: the fixed line"
    assert labor.build(now, "de", 160.0).summary == notify.tr("lb_summary", "de")


# ---------------------------------------------------------------- ops

def test_the_server_script_pins_the_model_and_binds_localhost_only():
    s = (OPS / "local-llm.sh").read_text()
    assert re.search(r"^sha=[0-9a-f]{64}$", s, re.M) and re.search(r"^rev=[0-9a-f]{40}$", s, re.M)
    assert re.search(r"^file=Qwen3-4B-Instruct-2507-Q4_K_M\.gguf$", s, re.M)
    assert "sha256sum -c" in s and "@sha256:" in s, "the model by hash, the image by digest"
    assert '-p "127.0.0.1:$port:8080"' in s and "0.0.0.0:$port" not in s
    assert "--memory 4g" in s and "--cpus 3" in s and "--cpu-shares" in s and "--cap-drop ALL" in s
    assert "TOKEN" not in s and "/etc/pythia" not in s, "the server never sees a key or the owner's env files"
    assert '"$here/local-llm.sh"' in (OPS / "deploy_ops.sh").read_text()
    assert "\u2014" not in s


def test_the_jobs_table_has_the_local_model_jobs():
    from lab.ops import jobs
    t = jobs.load_table(OPS / "jobs.yaml").jobs
    assert t["llm-news"]["depends_on"] == ["news-collect"] and t["llm-news"]["command"] == "python -m lab.ai.local --news"
    assert t["local-llm"]["kind"] == "host" and t["local-llm"]["enabled"]
    for name in ("briefing", "labor", "llm-news"):
        envs = t[name]["env_file"] if isinstance(t[name]["env_file"], list) else [t[name]["env_file"]]
        assert "/etc/pythia/local-llm.env?" in envs, name
        assert t[name]["network"] == "host", "127.0.0.1:8090 and the relay"
    for name in ("ai-brief", "ai-news", "ai-critic", "ai-weekly"):
        assert not t[name]["enabled"], "the metered jobs stay off"
