"""A local language model for words around the numbers, never for the numbers (B4). No API credit, no key.

The metered Claude jobs (ai-brief, ai-news, ai-critic, ai-weekly) are off since the credit ran out. What they gave
the briefing comes from a small model on this machine now, or from the owner's larger one when his PC is online:

  1. the owner's PC through the relay on the VPS (OpenAI-compatible at <relay>/v1), when PYTHIA_LOCAL_LLM_RELAY_URL
     and PYTHIA_LOCAL_LLM_TOKEN are set (the owner's env file, /etc/pythia/local-llm.env, never the repo) and the
     relay's status route (PYTHIA_LOCAL_LLM_RELAY_STATUS, /status) says the PC is online; asked with
     reasoning_effort "none" (PYTHIA_LOCAL_LLM_RELAY_REASONING, "default" leaves it to the model): with thinking on
     the PC's model wrote four times the tokens for the same answer, past the 45 s every short call has;
  2. the VPS model: llama.cpp's server with Qwen3 4B Instruct Q4_K_M on 127.0.0.1:8091 (research/ops/local-llm.sh,
     PYTHIA_LOCAL_LLM_URL), 3 CPUs at a low CPU share, at most 4 GB;
  3. no text: every user keeps its template (also with PYTHIA_LOCAL_LLM=off).

What it writes (the model decides nothing, never touches trading and never sees a key or a wallet):

  summary(facts, fallback, lang)   two short sentences (or one) over facts a report already computed; every number
                                   in the answer must appear in the facts, else the fallback (and the log says why).
                                   The briefing's summary line (60 s budget) and the 20:00 lab card's top line (one
                                   sentence) use it.
  tag_news()                       each headline of <data>/ai/news/<day>.jsonl (today and yesterday, UTC) gets a
                                   topic from TOPICS and a relevance for the lab from 1 to 5, kept in
                                   <data>/ai/news_tags/<day>.json; the briefing shows the three most relevant.

Every call is a line in <data>/ai/local_llm.jsonl (when, what for, which backend, tokens, seconds, ok or why not;
never the text).

  python -m lab.ai.local --news      tag the new headlines (job llm-news, after news-collect); exits 1 when every
                                     model call failed
  python -m lab.ai.local --probe     which backend answers now, and how fast
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..ops import notify

VPS_URL = "http://127.0.0.1:8091"          # research/ops/local-llm.sh binds the server here, nowhere else
VPS_MODEL = "qwen3-4b-instruct"
STATUS_ROUTE = "/status"
MAX_TOKENS = 160
CALL_TIMEOUT = 45.0
STATUS_TIMEOUT = 3.0
MAX_SUMMARY = 320                          # characters; a longer answer is not two short sentences
TOPICS = ("bitcoin", "ethereum", "solana", "memecoins", "defi", "stablecoins", "etf", "regulation", "macro",
          "exchanges", "security", "stocks", "other")
NEWS_BATCH = 8                             # 15 a call shifted tags to the next headline
NEWS_ASKS = 2                              # a headline the model skips is asked this often, then left
NEWS_BUDGET_SEC = 8 * 60
DAY_MS = 86_400_000
THINK = re.compile(r"<think>.*?(</think>|$)", re.S)
# A number as written in a report: digits with "." or "," inside, an explicit sign only when it does not follow a
# letter or digit (so "2026-10-26" and "F3" carry no minus or sign).
NUMBER = re.compile(r"(?:(?<![\w.,])[-−+])?\d+(?:[.,]\d+)*")


# ---------------------------------------------------------------- the backends

def _env(env: dict | None) -> dict:
    return os.environ if env is None else env


def _get_json(url: str, token: str | None, timeout: float):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8") or "null")


def relay_online(env: dict | None = None) -> tuple[bool, str]:
    """(the owner's PC answers through the relay, why not). Online when the status route answers 200 and, if its
    JSON has one of online, connected, pc_online, up or ok, that is true."""
    e = _env(env)
    base, token = (e.get("PYTHIA_LOCAL_LLM_RELAY_URL") or "").rstrip("/"), e.get("PYTHIA_LOCAL_LLM_TOKEN") or ""
    if not base or not token:
        return False, "relay not configured"
    try:
        st = _get_json(base + (e.get("PYTHIA_LOCAL_LLM_RELAY_STATUS") or STATUS_ROUTE), token, STATUS_TIMEOUT)
    except (OSError, ValueError) as ex:
        return False, f"relay status: {type(ex).__name__}"
    if isinstance(st, dict):
        if "pc" in st:   # the llm relay: {"pc": "online" | "offline", "queued": n, "running": n}
            return (True, "") if str(st["pc"]).lower() == "online" else (False, f"relay says pc={st['pc']}")
        for k in ("online", "connected", "pc_online", "up", "ok"):
            if k in st:
                return (True, "") if st[k] else (False, f"relay says {k}=false")
    return True, ""


def backends(env: dict | None = None) -> list[dict]:
    """The backends to try, in order: the owner's PC through the relay when it is online, then the VPS model; none
    when PYTHIA_LOCAL_LLM is off (every user keeps its template)."""
    e = _env(env)
    if str(e.get("PYTHIA_LOCAL_LLM") or "").lower() in ("off", "0", "false"):
        return []
    out = []
    ok, why = relay_online(e)
    if ok:
        out.append({"name": "relay", "url": e["PYTHIA_LOCAL_LLM_RELAY_URL"].rstrip("/") + "/v1",
                    "token": e["PYTHIA_LOCAL_LLM_TOKEN"], "model": e.get("PYTHIA_LOCAL_LLM_RELAY_MODEL") or "default",
                    "reasoning": e.get("PYTHIA_LOCAL_LLM_RELAY_REASONING") or "none"})
    elif why != "relay not configured":
        notify.say(f"local-llm: {why}, the VPS model instead")
    out.append({"name": "vps", "url": (e.get("PYTHIA_LOCAL_LLM_URL") or VPS_URL).rstrip("/") + "/v1", "token": None,
                "model": e.get("PYTHIA_LOCAL_LLM_MODEL") or VPS_MODEL})
    return out


def log_call(row: dict) -> None:
    p = notify.data_root() / "ai" / "local_llm.jsonl"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def chat(messages: list[dict], use: str, max_tokens: int = MAX_TOKENS, deadline: float | None = None,
         timeout: float = CALL_TIMEOUT, env: dict | None = None, bks: list[dict] | None = None,
         schema: dict | None = None) -> dict | None:
    """One OpenAI-compatible chat call on the first backend that answers, within `deadline` (time.monotonic()):
    {"text", "backend", "model", "tokens", "seconds"}, or None when none answered in time. At most `max_tokens`
    out, temperature 0.2; a <think> block is dropped. `schema`: a JSON schema the answer must follow, sent as
    response_format (llama.cpp and the relay's server constrain the answer to it); the caller still checks it."""
    for b in bks if bks is not None else backends(env):
        left = timeout if deadline is None else min(timeout, deadline - time.monotonic())
        if left < 1:
            notify.say(f"local-llm: {use}: no time left")
            return None
        t0 = time.monotonic()
        body = {"model": b["model"], "messages": messages, "max_tokens": int(max_tokens), "temperature": 0.2,
                "stream": False}
        if schema is not None:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "answer", "schema": schema}}
        if b.get("reasoning", "default") != "default":
            body["reasoning_effort"] = b["reasoning"]
        headers = {"Content-Type": "application/json"}
        if b["token"]:
            headers["Authorization"] = f"Bearer {b['token']}"
        row = {"ts_ms": notify.clock_ms(), "use": use, "backend": b["name"]}
        try:
            req = urllib.request.Request(b["url"] + "/chat/completions", json.dumps(body).encode("utf-8"), headers)
            with urllib.request.urlopen(req, timeout=left) as r:
                d = json.loads(r.read().decode("utf-8"))
            text = THINK.sub("", str(d["choices"][0]["message"]["content"] or "")).strip()
        except (OSError, ValueError, KeyError, IndexError, TypeError) as ex:
            why = f"{type(ex).__name__}" + (f" {ex.code}" if isinstance(ex, urllib.error.HTTPError) else "")
            log_call({**row, "ok": False, "why": why, "seconds": round(time.monotonic() - t0, 2)})
            notify.say(f"local-llm: {use}: {b['name']} did not answer ({why})")
            continue
        sec = time.monotonic() - t0
        tokens = (d.get("usage") or {}).get("completion_tokens")
        log_call({**row, "ok": True, "tokens": tokens, "seconds": round(sec, 2),
                  "tokens_per_s": round(tokens / sec, 1) if tokens and sec > 0 else None})
        return {"text": text, "backend": b["name"], "model": b["model"], "tokens": tokens, "seconds": sec}
    return None


FENCE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.S)


def json_object(text: str) -> dict | None:
    """The answer as one JSON object (a ```json fence around it is fine), else None. Nothing is repaired."""
    t = (text or "").strip()
    m = FENCE.match(t)
    try:
        obj = json.loads(m.group(1) if m else t)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None


# ---------------------------------------------------------------- the number rule

def _values(tok: str) -> set[tuple[bool, float]]:
    """A number token read both ways ("1.234,5" German, "1,234.5" English): {(negative, value)}."""
    neg = tok[:1] in "-−"
    t = tok.lstrip("-−+")
    out = set()
    if re.fullmatch(r"\d{1,3}(,\d{3})+(\.\d+)?|\d+(\.\d+)?", t):
        out.add((neg, round(float(t.replace(",", "")), 9)))
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?|\d+(,\d+)?", t):
        out.add((neg, round(float(t.replace(".", "").replace(",", ".")), 9)))
    return out


def foreign_numbers(text: str, facts: list[str]) -> list[str]:
    """The numbers in `text` that appear in none of the facts (same value and sign, in either notation)."""
    have: set = set()
    for f in facts:
        for tok in NUMBER.findall(str(f)):
            have |= _values(tok)
    return [tok for tok in NUMBER.findall(text) if not (_values(tok) & have)]


# ---------------------------------------------------------------- uses

SUMMARY_SYSTEM = {
    "de": "Du schreibst die Kopfzeile des täglichen Berichts eines Forschungslabors, das auf Papier handelt, für seinen "
          "Besitzer. Schreib {count} auf Deutsch (mit Verb) über das Wichtigste aus den Fakten, nicht mehr als {words} "
          "Wörter. Jede Zahl, die du schreibst, muss genau so in den Fakten stehen; lieber weniger Zahlen. Rechne "
          "nichts, erfinde nichts, keine Ratschläge, keine Prognosen, keine Liste, kein Gedankenstrich.\n"
          "Beispiel: Fakten: - pump.fun gestern: 2 Trades, 1 gewonnen, -0,0040 SOL - Alles grün. "
          "Antwort: Der pump.fun-Bot hat gestern mit 2 Trades -0,0040 SOL verloren.{more}",
    "en": "You write the top line of the daily report of a paper-trading research lab for its owner. Write {count} in "
          "English (with a verb) about what matters most in the facts, at most {words} words. Every number you write "
          "must appear exactly so in the facts; fewer numbers are better. Do no arithmetic, invent nothing, no "
          "advice, no forecast, no list, no dashes.\n"
          "Example: Facts: - pump.fun yesterday: 2 trades, 1 won, -0.0040 SOL - All green. "
          "Answer: The pump.fun bot lost -0.0040 SOL over 2 trades yesterday.{more}",
}
SUMMARY_COUNT = {("de", 1): ("genau einen kurzen, ganzen Satz", 25, ""),
                 ("de", 2): ("genau zwei kurze, ganze Sätze", 40, " Sonst läuft alles normal."),
                 ("en", 1): ("exactly one short, complete sentence", 25, ""),
                 ("en", 2): ("exactly two short, complete sentences", 40, " Everything else runs normally.")}


def summary_prompt(lang: str, sentences: int = 2) -> str:
    count, words, more = SUMMARY_COUNT[("de" if lang == "de" else "en", 1 if sentences == 1 else 2)]
    return SUMMARY_SYSTEM["de" if lang == "de" else "en"].format(count=count, words=words, more=more)


def summary(facts: list[str], fallback: str, lang: str, use: str = "summary", deadline: float | None = None,
            env: dict | None = None, bks: list[dict] | None = None, sentences: int = 2) -> str:
    """Two short sentences (or one) over `facts`, or `fallback` when no model answered, the answer is empty or too long, or
    it has a number that is not in the facts (logged with the reason)."""
    facts = [notify.nodash(str(f)).strip() for f in facts if str(f or "").strip()]
    bks = backends(env) if bks is None else bks
    if not facts or not bks:
        return fallback
    head = "Fakten" if lang == "de" else "Facts"
    msgs = [{"role": "system", "content": summary_prompt(lang, sentences)},
            {"role": "user", "content": f"{head}:\n" + "\n".join(f"- {f}" for f in facts)}]
    ans = chat(msgs, use, MAX_TOKENS, deadline, env=env, bks=bks)
    why = None
    text = " ".join(notify.nodash(ans["text"]).replace("**", "").split()) if ans else ""
    if ans is None:
        why = "no model answered"
    elif not text:
        why = "empty answer"
    elif len(text) > MAX_SUMMARY * min(sentences, 2) / 2:
        why = f"too long ({len(text)} characters)"
    elif bad := foreign_numbers(text, facts):
        why = "numbers not in the facts: " + ", ".join(bad[:5])
    if why:
        notify.say(f"local-llm: {use}: template summary, {why}")
        log_call({"ts_ms": notify.clock_ms(), "use": use, "backend": ans["backend"] if ans else None,
                  "ok": False, "why": why})
        return fallback
    return text


def summarizer(budget_sec: float = 60.0, use: str = "briefing", env: dict | None = None, sentences: int = 2):
    """summary() under one shared budget for every call it makes (the briefing builds a card per language), the
    backends checked once: (facts, fallback, lang) -> text."""
    deadline = time.monotonic() + budget_sec
    cache: dict = {}

    def run(facts: list[str], fallback: str, lang: str) -> str:
        if "bks" not in cache:
            cache["bks"] = backends(env)
        return summary(facts, fallback, lang, use=f"{use}:{lang}", deadline=deadline, env=env, bks=cache["bks"],
                       sentences=sentences)
    return run


NEWS_SYSTEM = ("You tag news headlines for a research lab that trades crypto on paper: pump.fun memecoins on Solana, "
               "momentum in the large coins, small on-chain wallets, tokenized ETFs. For each numbered headline write "
               "one line: its number, one topic, its relevance for the lab, separated by |, like 3|solana|4. Topics: "
               + ", ".join(TOPICS) + ". Relevance: 5 moves the whole crypto market or pump.fun and Solana memecoins "
               "directly; 4 news about Bitcoin, Ether or Solana themselves, crypto ETF flows, a large exchange or a big "
               "hack; 3 other crypto news; 2 a single small coin or company; 1 not about crypto or markets. Most "
               "headlines are 2 or 3. Nothing else, no headline text.")
TAG_LINE = re.compile(r"^\s*(\d+)\s*[|.:)]\s*([a-z]+)\s*\|\s*([1-5])\b", re.M)


def parse_tags(text: str, n: int) -> dict[int, dict]:
    """{index from 0: {"topic", "relevance"}} of the lines that name a known topic and a relevance of 1 to 5."""
    out = {}
    for m in TAG_LINE.finditer(text or ""):
        i, topic, rel = int(m.group(1)) - 1, m.group(2), int(m.group(3))
        if 0 <= i < n and topic in TOPICS and i not in out:
            out[i] = {"topic": topic, "relevance": rel}
    return out


def news_dir() -> Path:
    return notify.data_root() / "ai" / "news"


def tags_dir() -> Path:
    return notify.data_root() / "ai" / "news_tags"


def headline_key(h: dict) -> str:
    return str(h.get("link") or h.get("title") or "")


def read_tags(day: str, root: Path | None = None) -> dict:
    """{headline key: {"topic", "relevance", "by"} or {"asked": n} for one the model skipped} of a UTC day."""
    d = notify.read_json((root or tags_dir()) / f"{day}.json")
    return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}


def tag_news(now: int | None = None, budget_sec: float = NEWS_BUDGET_SEC, env: dict | None = None,
             stats: dict | None = None) -> int:
    """Tag the headlines of today and yesterday (UTC) that have no tag yet, NEWS_BATCH a call, until the budget is
    spent. The number tagged; a headline the model left out is kept as {"asked": n} and asked again next run, at most
    NEWS_ASKS times. `stats` gets the calls made and those a model answered (none made while the model is off)."""
    now = now or notify.clock_ms()
    stats = {} if stats is None else stats
    stats.update(calls=0, answered=0)
    deadline = time.monotonic() + budget_sec
    bks = None
    done = 0
    for k in (0, 1):
        day = datetime.fromtimestamp((now - k * DAY_MS) / 1000, timezone.utc).strftime("%Y-%m-%d")
        try:
            lines = (news_dir() / f"{day}.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        tags = read_tags(day)
        todo, seen = [], set()
        for line in lines:
            try:
                h = json.loads(line)
            except ValueError:
                continue
            key = headline_key(h) if isinstance(h, dict) and h.get("title") else ""
            if key and key not in seen and "relevance" not in tags.get(key, {}) \
                    and int(tags.get(key, {}).get("asked") or 0) < NEWS_ASKS:
                seen.add(key)
                todo.append(h)
        for i in range(0, len(todo), NEWS_BATCH):
            if deadline - time.monotonic() < 20:
                notify.say(f"local-llm: news: budget spent, {len(todo) - i} headlines of {day} wait for the next run")
                return done
            if bks is None:
                bks = backends(env)
            if not bks:
                notify.say("local-llm: news: the model is off, the headlines stay untagged")
                return done
            batch = todo[i:i + NEWS_BATCH]
            user = "\n".join(f"{j + 1}. {notify.short(notify.nodash(str(h['title'])), 160)}" for j, h in enumerate(batch))
            ans = chat([{"role": "system", "content": NEWS_SYSTEM}, {"role": "user", "content": user}], "news",
                       12 * len(batch) + 20, deadline, env=env, bks=bks)
            stats["calls"] += 1
            if ans is None:
                notify.say("local-llm: news: no model answered, the headlines stay untagged")
                return done
            stats["answered"] += 1
            got = parse_tags(ans["text"], len(batch))
            for j, h in enumerate(batch):
                key = headline_key(h)
                tags[key] = {**got[j], "by": ans["backend"]} if j in got else \
                    {"asked": int(tags.get(key, {}).get("asked") or 0) + 1}
            done += len(got)
            notify.write_json(tags_dir() / f"{day}.json", tags)
    notify.say(f"local-llm: news: {done} headlines tagged")
    return done


def probe(env: dict | None = None) -> int:
    """Which backend answers and how fast: one short call."""
    ans = chat([{"role": "user", "content": "Say hello in five words."}], "probe", 32, env=env)
    if ans is None:
        notify.say("local-llm: no backend answered")
        return 1
    rate = f", {ans['tokens'] / ans['seconds']:.1f} tokens/s" if ans["tokens"] and ans["seconds"] else ""
    notify.say(f"local-llm: {ans['backend']} answered in {ans['seconds']:.1f} s{rate}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if "--probe" in argv:
        return probe()
    if "--news" in argv:
        stats: dict = {}
        tag_news(stats=stats)
        if stats["calls"] and not stats["answered"]:
            notify.say(f"local-llm: news: every model call failed ({stats['calls']}), see ai/local_llm.jsonl", err=True)
            return 1  # the job turns red instead of reporting ok
        return 0
    notify.say(__doc__.strip().splitlines()[0])
    return 2


if __name__ == "__main__":
    sys.exit(main())
