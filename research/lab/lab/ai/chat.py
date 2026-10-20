"""Questions to Pythia in the owner's Telegram chat, answered by Claude
(Sonnet 5.5) from the same fact sheet the daily brief reads.

A long-running service (a container, research/ops/README.md "Questions in
Telegram"): it long-polls the bot's getUpdates, takes messages from the
configured owner chat only (PYTHIA_TELEGRAM_CHAT_ID; any other chat is
ignored without a reply) and answers each in the language it was asked in.

  /start, /help        what it does
  /real ID, /notreal ID  the owner's verdict on a strategy critic finding
  anything else        a question

It only answers. A message that asks it to trade, to start, stop or change an
autopilot, to change a setting or to reveal a key, token, password or server
detail is refused, first by a plain check here (nothing is called) and again
by the model's instructions. Nothing in this module can place an order or
write a setting: it reads the engine's state, the lab's reports and the
Claude answer, and sends text to the chat.

At most PYTHIA_AI_ASK_PER_DAY questions (default 40) a UTC day. Every
question is written to <data>/ai/chat.jsonl with its answer, the model and
its cost. The fixed instructions and the fact sheet form the cached prefix
(rebuilt every FACTS_TTL_S), so questions asked close together read it from
the prompt cache at a tenth of the price.

  python -m lab.ai.chat            run until stopped
  python -m lab.ai.chat --once     one poll, then exit (a cron alternative)

Environment: PYTHIA_TELEGRAM_BOT_TOKEN, PYTHIA_TELEGRAM_CHAT_ID,
ANTHROPIC_API_KEY (only its hash goes to the engine), PYTHIA_AI_ASK_PER_DAY,
PYTHIA_AI_MODEL_ASK, PYTHIA_AI_EFFORT_ASK. The bot token is a secret: never
printed, logged or written.
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

from ..ops import i18n, notify
from . import brief, critic, engine, facts, score

DEFAULT_MODEL = engine.REVIEW
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 6000
PER_DAY = 40
FACTS_TTL_S = 15 * 60
POLL_S = 50
HISTORY = 3
MAX_QUESTION = 1500
TELEGRAM_LIMIT = 4000

SYSTEM = """You are Pythia's assistant in the owner's Telegram chat. Pythia is a paper-first trading research \
system run by one person: autopilots that trade paper or demo money, a research lab with studies, models, a \
strategy factory and watchers. You answer the owner's questions from the FACTS below, which are today's \
state of the system and the market as Pythia sees it. That is everything you know: no news feed, no internet. \
If the facts do not answer a question, say so plainly and say where in the app the owner could look. Never \
invent numbers, trades, prices or results.

Answer in the language of the question (German or English). Plain text for a phone: no markdown headings, no \
tables, no em dashes, short paragraphs or a few lines starting with "- ". At most about 200 words unless the \
question asks for more detail. Numbers as in the facts, with their units and dates.

You only answer questions. You cannot and must not place, change or cancel orders, start, stop, pause or \
change an autopilot, or change any setting, cap or limit; if the message asks for any of that, set kind to \
refuse_trade. You never reveal API keys, tokens, passwords, chat ids, host names, IP addresses, file paths on \
the server or anything else that looks like a secret or credential; if the message asks for any of that, set \
kind to refuse_secret. Do not give personal investment advice or tell the owner to buy or sell anything: \
explain what the facts and the lab say instead. Otherwise kind is answer.

Answer with the JSON object only: {"kind": "answer" | "refuse_trade" | "refuse_secret", "answer": "..."}."""

SCHEMA = {
    "type": "object",
    "properties": {"kind": {"type": "string", "enum": ["answer", "refuse_trade", "refuse_secret"]},
                   "answer": {"type": "string"}},
    "required": ["kind", "answer"],
    "additionalProperties": False,
}

# A request to act, at the start of the message (a question about a trade
# that happened is fine: "why did it sell ETH?").
ACT = re.compile(
    r"^\s*(?:please\s+|bitte\s+|pythia[,:]?\s+)?(?:buy|sell|short|close|cancel|liquidate|stop|start|pause|resume|"
    r"restart|arm|disarm|set|change|raise|lower|increase|decrease|turn\s+(?:on|off)|enable|disable|place|execute|"
    r"kaufe|verkaufe|schließe|schliesse|storniere|stoppe|starte|pausiere|setze|ändere|aendere|erhöhe|erhoehe|"
    r"senke|schalte|platziere|aktiviere|deaktiviere)(?![\w-])",
    re.IGNORECASE)
SECRET = re.compile(
    r"api[\s_-]?key|\btoken\b|passw(?:or)?d|passwort|secret|geheim|private[\s_-]?key|seed[\s_-]?phrase|"
    r"\bssh\b|chat[\s_-]?id|ip[\s-]?ad(?:d)?ress|hostname|server[\s-]?ad(?:d)?ress|\.env\b|alerts\.env|"
    r"credential|zugangsdaten|schlüssel|schluessel",
    re.IGNORECASE)
GERMAN = re.compile(r"[äöüß]|\b(?:ich|ist|und|nicht|wie|warum|wieso|weshalb|heute|gestern|der|das|mein|"
                    r"meine|wird|wurde|gibt|kannst|bitte|danke|lief|welche|welcher|haben|sind|alles|sofort|"
                    r"zeig|zeige|mir|mit|noch|schon|jetzt|gerade|seit|wieviel|kaufe|verkaufe|stoppe|starte|"
                    r"setze|ändere|aendere|erhöhe|erhoehe|senke)\b", re.IGNORECASE)


def ai_dir() -> Path:
    return notify.data_root() / "ai"


def log_path() -> Path:
    return ai_dir() / "chat.jsonl"


def state_path() -> Path:
    return ai_dir() / "chat_state.json"


def per_day() -> int:
    try:
        return max(0, int(os.environ.get("PYTHIA_AI_ASK_PER_DAY") or PER_DAY))
    except ValueError:
        return PER_DAY


def lang_of(text: str) -> str:
    """de when the text reads German, else en (only for the fixed replies; the
    model answers in the question's language by itself)."""
    return "de" if len(GERMAN.findall(text or "")) >= 1 else "en"


def screen(text: str) -> str | None:
    """refuse_trade, refuse_secret or None: the plain check before any call."""
    if SECRET.search(text or ""):
        return "refuse_secret"
    if ACT.search(text or ""):
        return "refuse_trade"
    return None


def day_of(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def asked_today(now_ms: int) -> int:
    d = day_of(now_ms)
    return sum(1 for r in critic.read_jsonl(log_path()) if r.get("date") == d and r.get("called"))


def recent_exchanges(n: int = HISTORY) -> list[dict]:
    rows = [r for r in critic.read_jsonl(log_path()) if r.get("kind") == "answer" and r.get("answer")]
    return rows[-n:]


# ---------------------------------------------------------------- the facts

class Sheet:
    """The fact sheet, rebuilt at most every FACTS_TTL_S so the cached prefix
    stays the same between questions asked close together."""

    def __init__(self, builder=None, ttl_s: int = FACTS_TTL_S):
        self.builder = builder or build_sheet
        self.ttl_s = ttl_s
        self.text = ""
        self.at = 0.0

    def get(self, now_ms: int) -> str:
        if not self.text or now_ms / 1000 - self.at >= self.ttl_s:
            try:
                self.text = self.builder(now_ms)
            except Exception as e:  # noqa: BLE001 - an old sheet beats none
                notify.say(f"fact sheet not rebuilt: {type(e).__name__}: {e}", err=True)
                if not self.text:
                    self.text = f"DATE: {day_of(now_ms)} (UTC). The fact sheet could not be built: {type(e).__name__}."
            self.at = now_ms / 1000
        return self.text


def extra_sections(now_ms: int) -> list[tuple[str, list[str]]]:
    """What the AI jobs themselves know: today's brief, its score, the critic's
    open findings, the director's drafts, and the Claude spend."""
    rep = notify.reports_root()
    out: list[tuple[str, list[str]]] = []
    b = notify.read_json(rep / "ai_brief" / "latest.json")
    if isinstance(b, dict):
        rows = [f"{b.get('date')}: " + " / ".join(str(s) for s in b.get("summary") or [])]
        rows += [f"{p.get('coin')}: {100 * float(p.get('p_llm') or 0):.0f} % up in 7 days ({p.get('reason')})"
                 for p in (b.get("predictions") or [])[:12] if isinstance(p, dict)]
        out.append(("DAILY AI BRIEF (shadow, never traded)", rows))
    sc = notify.read_json(score.scores_path())
    if isinstance(sc, dict) and sc.get("verdict"):
        out.append(("AI BRIEF SCORE", [str(sc["verdict"])]))
    cs = notify.read_json(critic.score_path())
    if isinstance(cs, dict):
        rows = [str(cs.get("verdict") or "")]
        rows += [f"[{r.get('id')}] {r.get('date')} {r.get('autopilot')}: {r.get('kind')}, {r.get('claim')} "
                 f"({r.get('label') or r.get('auto')})" for r in (cs.get("recent") or [])[-8:]]
        out.append(("STRATEGY CRITIC (findings and how they were judged)", [r for r in rows if r]))
    dj = notify.read_json(rep / "ai" / "director.json")
    if isinstance(dj, dict):
        out.append((f"RESEARCH DIRECTOR DRAFTS ({dj.get('date')}, not started)",
                    [f"{p.get('title')}: {p.get('question')}" for p in dj.get("proposals") or []]))
    spend = notify.ai_spend_by_job(now_ms - 7 * 86_400_000, now_ms + 1)
    if spend:
        today_spend = notify.ai_spend_by_job(now_ms - (now_ms % 86_400_000), now_ms + 1)
        out.append(("CLAUDE API SPEND", [
            "last 7 days: " + ", ".join(f"{j} ${u:.2f} ({n} calls)" for j, (u, n) in sorted(spend.items())),
            "today (UTC): " + (", ".join(f"{j} ${u:.2f}" for j, (u, _) in sorted(today_spend.items())) or "nothing")]))
    return out


_CLOSES: dict[tuple, dict] = {}


def daily_closes(coins: list[str], now_ms: int) -> dict[str, score.Closes]:
    """Daily closes end yesterday, so they are fetched once a UTC day, not at
    every rebuild of the sheet (each fetch lists and downloads the archive)."""
    key = (day_of(now_ms), tuple(sorted(set(coins))))
    if key not in _CLOSES:
        _CLOSES.clear()
        _CLOSES[key] = score.closes_for(set(coins))
    return _CLOSES[key]


def build_sheet(now_ms: int) -> str:
    state = notify.engine_state()
    coins = brief.pick_coins(state)
    closes = daily_closes(coins, now_ms)
    usable = [c for c in coins if len(closes.get(c) or []) >= 31]
    return facts.fact_sheet(day_of(now_ms), usable, closes, state, facts.funding_lines(usable), now_ms=now_ms,
                            extra=extra_sections(now_ms))


# ---------------------------------------------------------------- answering

def user_prompt(question: str, history: list[dict]) -> str:
    parts = []
    if history:
        parts.append("EARLIER IN THIS CHAT (oldest first):")
        for h in history:
            parts += [f"Q: {notify.short(str(h.get('question') or ''), 400)}",
                      f"A: {notify.short(str(h.get('answer') or ''), 600)}"]
        parts.append("")
    parts.append("QUESTION: " + question)
    return "\n".join(parts)


def scrub(text: str) -> str:
    """Belt and braces: nothing that looks like a key, a token or an address leaves."""
    text = re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "[removed]", text)
    text = re.sub(r"\b\d{6,}:[A-Za-z0-9_\-]{20,}\b", "[removed]", text)
    text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "[removed]", text)
    return notify.nodash(text).strip()


def answer(question: str, now_ms: int, sheet: Sheet, poster=None) -> dict:
    """One question to the end: the record that goes to the log, with `reply`
    the text for the chat."""
    q = " ".join(str(question or "").split())[:MAX_QUESTION]
    lang = lang_of(q)
    rec = {"ts": now_ms, "date": day_of(now_ms), "lang": lang, "question": q, "called": False}
    pre = screen(q)
    if pre:
        rec.update(kind=pre, reply=i18n.t("ask_" + pre, lang))
        return rec
    limit = per_day()
    used = asked_today(now_ms)
    if used >= limit:
        rec.update(kind="limit", reply=i18n.t("ask_limit", lang, n=limit))
        return rec
    model, effort = engine.model_for("ask", DEFAULT_MODEL), engine.effort_for("ask", DEFAULT_EFFORT)
    system = SYSTEM + "\n\nFACTS:\n" + sheet.get(now_ms)
    rec["called"] = True
    try:
        a = engine.complete("ask", system, user_prompt(q, recent_exchanges()), MAX_TOKENS, model=model,
                            schema=SCHEMA, effort=effort, batch=False, timeout=280, poster=poster)
    except engine.AiError as e:
        rec.update(kind="error", error=f"{e.kind}: {e}"[:300], costUsd=e.cost_usd,
                   reply=i18n.t("ask_failed", lang, why=e.kind if e.kind != "budget" else str(e)[:200]))
        return rec
    obj = a.get("json") or {}
    kind = obj.get("kind") if obj.get("kind") in ("answer", "refuse_trade", "refuse_secret") else "answer"
    text = scrub(str(obj.get("answer") or ""))
    cost = float(a.get("costUsd") or 0.0)
    served = a.get("servedBy") or a.get("model") or model
    if kind != "answer":
        reply = i18n.t("ask_" + kind, lang)
    else:
        foot = i18n.t("ask_footer", lang, model=str(served).replace("claude-", ""), cost=i18n.money(cost, 4, lang),
                      n=used + 1, limit=limit)
        reply = (text or "?")[: TELEGRAM_LIMIT - len(foot) - 4] + "\n\n" + foot
    rec.update(kind=kind, answer=text, reply=reply, model=served, costUsd=cost, usage=a.get("usage") or {},
               latencyMs=a.get("latencyMs"))
    return rec


def handle(msg: dict, now_ms: int, sheet: Sheet, poster=None) -> dict | None:
    """One Telegram message: None when it is not the owner's chat or carries no text."""
    owner = notify.chat_id()
    chat = str(((msg or {}).get("chat") or {}).get("id") or "")
    text = str((msg or {}).get("text") or "").strip()
    if not owner or chat != owner or not text:
        return None
    lang = lang_of(text)
    cmd = text.split()[0].split("@")[0].lower() if text.startswith("/") else ""
    if cmd in ("/start", "/help"):
        return {"ts": now_ms, "date": day_of(now_ms), "kind": "help", "called": False, "reply": i18n.t("ask_help", lang)}
    if cmd in ("/real", "/notreal"):
        fid = text.split()[1] if len(text.split()) > 1 else ""
        verdict = cmd[1:]
        ok = critic.label(fid, verdict, now_ms)
        reply = (i18n.t("critic_marked", lang, id=fid, verdict=i18n.t(f"critic_{verdict}", lang)) if ok
                 else i18n.t("critic_unknown", lang, id=fid or "?"))
        return {"ts": now_ms, "date": day_of(now_ms), "kind": "label", "called": False, "question": text, "reply": reply}
    return answer(text, now_ms, sheet, poster)


# ---------------------------------------------------------------- Telegram

def bot_url(method: str) -> str | None:
    token = (os.environ.get("PYTHIA_TELEGRAM_BOT_TOKEN") or "").strip()
    return f"https://api.telegram.org/bot{token}/{method}" if token else None


def tg(method: str, body: dict, timeout: float) -> dict:
    """One Bot API call; {} on any failure (the reason without the URL, which holds the token)."""
    url = bot_url(method)
    if not url:
        return {}
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            v = json.loads(r.read().decode("utf-8") or "{}")
            return v if isinstance(v, dict) else {}
    except urllib.error.HTTPError as e:
        notify.say(f"telegram {method}: HTTP {e.code}", err=True)
    except (urllib.error.URLError, OSError, ValueError) as e:
        notify.say(f"telegram {method}: {type(e).__name__}", err=True)
    return {}


def reply(chat: str, text: str, to_message: int | None) -> bool:
    body = {"chat_id": chat, "text": text[:TELEGRAM_LIMIT], "disable_web_page_preview": True}
    if to_message:
        body["reply_parameters"] = {"message_id": to_message, "allow_sending_without_reply": True}
    return bool(tg("sendMessage", body, 20).get("ok"))


def poll(offset: int | None, timeout_s: int = POLL_S) -> list[dict]:
    body = {"timeout": timeout_s, "allowed_updates": ["message"]}
    if offset is not None:
        body["offset"] = offset
    v = tg("getUpdates", body, timeout_s + 15)
    return [u for u in v.get("result") or [] if isinstance(u, dict)] if v.get("ok") else []


def step(sheet: Sheet, updates: list[dict], now_ms: int | None = None, send=reply, poster=None) -> int | None:
    """Handle a batch of updates; returns the next offset (None when there were none).
    The offset is saved before answering, so a crash never answers a message twice."""
    if not updates:
        return None
    nxt = max(int(u.get("update_id") or 0) for u in updates) + 1
    notify.write_json(state_path(), {"offset": nxt, "ts": now_ms or notify.clock_ms()})
    for u in sorted(updates, key=lambda u: int(u.get("update_id") or 0)):
        msg = u.get("message") or {}
        now = now_ms or notify.clock_ms()
        rec = handle(msg, now, sheet, poster)
        if rec is None:
            continue
        rec["update_id"] = u.get("update_id")
        delivered = send(str(msg["chat"]["id"]), rec.pop("reply"), msg.get("message_id"))
        rec["delivered"] = delivered
        critic.append_jsonl(log_path(), [rec])
        notify.say(f"ask: {rec.get('kind')}, ${float(rec.get('costUsd') or 0):.4f}, "
                   f"{'delivered' if delivered else 'NOT delivered'}")
    return nxt


def run(once: bool = False) -> int:
    if not bot_url("getMe") or not notify.chat_id():
        notify.say("PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID are needed; nothing to listen to", err=True)
        return 1 if not once else 0
    sheet = Sheet()
    offset = (notify.read_json(state_path()) or {}).get("offset")
    notify.say(f"listening to the owner's chat, at most {per_day()} questions a day")
    beat = 0.0
    while True:
        updates: list[dict] = []
        try:
            updates = poll(offset, 0 if once else POLL_S)
            nxt = step(sheet, updates)
            if nxt is not None:
                offset = nxt
            if time.time() - beat >= 300:
                # Proof of life for a look from outside: when it last polled.
                beat = time.time()
                notify.write_json(ai_dir() / "chat_heartbeat.json",
                                  {"t": notify.clock_ms(), "offset": offset, "asked_today": asked_today(notify.clock_ms()),
                                   "per_day": per_day()})
        except Exception as e:  # noqa: BLE001 - one bad update never stops the service
            notify.say(f"chat loop: {type(e).__name__}: {e}", err=True)
            time.sleep(5)
        if once:
            return 0
        if not updates:
            time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    return run(once="--once" in list(argv or []))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
