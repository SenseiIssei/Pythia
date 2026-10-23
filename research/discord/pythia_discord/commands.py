"""The slash commands: read only, for the owner only.

Every answer is built from the files the lab and the live bot write (the reports folder,
mounted read only); no command trades, arms, changes a limit or touches the kill switch,
and there is no code here that could. respond() checks the user's id against the owner's
first; anyone else gets "nicht erlaubt" ("not allowed") and nothing is read. An answer is in
the language of the channel it was asked in (channel_lang: English in a 🇬🇧 channel, German in a
🇩🇪 one and in the DM), with the texts of TEXT.

  /status   pump.fun live: on or off, mode, wallet, today's and the total P&L, stake, open
            positions (reports/pumpfun_rt/live_status.json)
  /trades   the last 10 real-money pump.fun trades (reports/pumpfun_rt/live_trades.json)
  /konten   the real-money accounts (the pump.fun wallet, live autopilots) and the paper ones
            (reports/forward/latest.json)
  /lab      the newest study reports and the model zoo (reports/<study>, reports/models)
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

COMMANDS: list[tuple[str, str]] = [
    ("status", "pump.fun live: an/aus, Wallet, P&L heute, Einsatz, offene Positionen"),
    ("trades", "Die letzten 10 Echtgeld-Trades"),
    ("konten", "Echtgeld- und Paper-Konten"),
    ("lab", "Die neuesten Studien und der Modell-Zoo"),
]
# The same in English, Discord's description for an English client (description_localizations).
COMMANDS_EN = {"status": "pump.fun live: on/off, wallet, P&L today, stake, open positions",
               "trades": "The last 10 real-money trades", "konten": "Real-money and paper accounts",
               "lab": "The newest studies and the model zoo"}
NOT_ALLOWED = "nicht erlaubt"
NOT_ALLOWED_EN = "not allowed"
GREEN, RED, GREY, BLUE, ORANGE = 0x2FB344, 0xE66767, 0xA3A29A, 0x3987E5, 0xE8A33D
STALE_MS = 5 * 60_000
STATUS_DE = {"early": "noch früh", "on_track": "im Plan", "ok": "in Ordnung", "watch": "beobachten",
             "below": "darunter", "behind": "im Rückstand", "unknown": "unbekannt", "in use": "im Einsatz",
             "shadow": "Schattenlauf", "retired": "ausgemustert", "failed its gate": "an der Schwelle gescheitert"}
STATUS_EN = {"early": "too early", "on_track": "on track", "ok": "ok", "watch": "watch", "below": "below",
             "behind": "behind", "unknown": "unknown", "in use": "in use", "shadow": "shadow", "retired": "retired",
             "failed its gate": "failed its gate"}
# Every text of an answer, German and English (test_discord_bot checks both have the same keys and placeholders).
TEXT: dict[str, dict[str, str]] = {
    "de": {
        "na": "k. A.", "footer": "Pythia · Alpha", "read_only": "nur lesen", "as_of": "Stand {t} · nur lesen",
        "unknown_command": "unbekannter Befehl",
        "live": "pump.fun live", "no_status": "Kein Status: reports/pumpfun_rt/live_status.json fehlt.",
        "not_running": "⚪ läuft nicht", "stale": " (Status {m} min alt)", "kill": "🛑 Notschalter an",
        "on": "🟢 an", "off": "🟠 aus", "mode_test": "Test (Alpha-Phase)", "mode_full": "voll",
        "f_mode": "Modus", "f_wallet": "Wallet", "f_today": "P&L heute",
        "today": "{pnl} · {n} Trades, {wins} gewonnen", "f_total": "P&L gesamt", "total": "{pnl} · {n} Trades",
        "f_stake": "Einsatz", "stuck": " · hängt", "f_open": "Offene Positionen ({n})", "none": "keine",
        "f_limits": "Grenzen", "limits": "Tagesverlust {day} · Budget {total} · max. {n} offen",
        "why": "Warum: {why}", "stops": "Stopp: {stops}", "stop_daily": "Tagesverlust", "stop_total": "Budget",
        "trades_none_title": "Letzte Echtgeld-Trades", "trades_none": "Noch keine Trades.",
        "trades_title": "Letzte {n} Echtgeld-Trades", "trades_footer": "Summe {pnl} · pump.fun · nur lesen",
        "wallet": "pump.fun Wallet {a}: {bal}, gesamt {pnl}", "f_real": "💰 Echtgeld", "nothing": "keins",
        "f_paper": "📄 Paper und Demo ({n})", "more": "+{n} weitere", "f_books": "📒 Paper-Bücher ({n})",
        "accounts": "Konten", "accounts_desc": "Echtgeld und Paper, aus dem Live-Status und dem Forward-Bericht.",
        "forward_footer": "Forward-Bericht {gen}", "no_verdict": "kein Urteil", "f_zoo": "🧠 Modell-Zoo ({n})",
        "lab": "Lab", "no_studies": "Keine Studienberichte.",
    },
    "en": {
        "na": "n/a", "footer": "Pythia · Alpha phase", "read_only": "read only", "as_of": "As of {t} · read only",
        "unknown_command": "unknown command",
        "live": "pump.fun live", "no_status": "No status: reports/pumpfun_rt/live_status.json is missing.",
        "not_running": "⚪ not running", "stale": " (status {m} min old)", "kill": "🛑 kill switch on",
        "on": "🟢 on", "off": "🟠 off", "mode_test": "test (Alpha phase)", "mode_full": "full",
        "f_mode": "Mode", "f_wallet": "Wallet", "f_today": "P&L today",
        "today": "{pnl} · {n} trades, {wins} won", "f_total": "P&L total", "total": "{pnl} · {n} trades",
        "f_stake": "Stake", "stuck": " · stuck", "f_open": "Open positions ({n})", "none": "none",
        "f_limits": "Limits", "limits": "daily loss {day} · budget {total} · max. {n} open",
        "why": "Why: {why}", "stops": "Stopped: {stops}", "stop_daily": "daily loss", "stop_total": "budget",
        "trades_none_title": "Last real-money trades", "trades_none": "No trades yet.",
        "trades_title": "Last {n} real-money trades", "trades_footer": "Total {pnl} · pump.fun · read only",
        "wallet": "pump.fun wallet {a}: {bal}, total {pnl}", "f_real": "💰 Real money", "nothing": "none",
        "f_paper": "📄 Paper and demo ({n})", "more": "+{n} more", "f_books": "📒 Paper books ({n})",
        "accounts": "Accounts", "accounts_desc": "Real money and paper, from the live status and the forward report.",
        "forward_footer": "Forward report {gen}", "no_verdict": "no verdict", "f_zoo": "🧠 Model zoo ({n})",
        "lab": "Lab", "no_studies": "No study reports.",
    },
}
# Reports that are not studies (the same set as the briefing's, lab.ops.briefing.NOT_STUDIES).
NOT_STUDIES = {"learn", "forward", "notify", "trending", "listings", "models", "pokemon", "cs2", "cs2_trends",
               "cs2_weekly", "readiness", "pumpfun", "pumpfun_rt", "pumpfun_activity", "polymarket", "agent",
               "exit_shadow", "factory", "paper_review", "studies", "ai", "ai_brief", "ai_news", "ai_analyst",
               "costs"}


def tx(key: str, lang: str = "de", **kw) -> str:
    s = TEXT["en" if lang == "en" else "de"][key]
    return s.format(**kw) if kw else s


def channel_lang(channel_id, state: dict | None, parent_id=None) -> str:
    """The language of the channel a command was used in: English in a channel of the bot's English
    map (or under one of its 🇬🇧 categories), German anywhere else, a DM included."""
    st = state if isinstance(state, dict) else {}
    en = {str(v) for v in (st.get("en") or {}).values()}
    en |= {str(v) for k, v in (st.get("categories") or {}).items() if str(k).startswith("🇬🇧")}
    return "en" if str(channel_id or "") in en or (parent_id and str(parent_id) in en) else "de"


def reports_root() -> Path:
    data = Path(os.environ.get("PYTHIA_DATA", "/data"))
    return Path(os.environ.get("PYTHIA_REPORTS", str(data / "reports")))


def read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def allowed(user_id, owner_id) -> bool:
    """Only the owner: the owner's user id, compared as text; no owner set means nobody."""
    owner = str(owner_id or "").strip()
    return bool(owner) and str(user_id or "").strip() == owner


# ---------------------------------------------------------------- formatting (German or English)

def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def de(v: float, dp: int = 2, sign: bool = False, lang: str = "de") -> str:
    """1.234,56 (English 1,234.56) with an optional sign."""
    s = f"{abs(v):,.{dp}f}"
    if lang != "en":
        s = s.replace(",", "_").replace(".", ",").replace("_", ".")
    return ("+" if v > 0 else "-" if v < 0 else "") + s if sign else ("-" + s if v < 0 else s)


def sol(v, dp: int = 4, sign: bool = False, lang: str = "de") -> str:
    v = _num(v)
    return tx("na", lang) if v is None else f"{de(v, dp, sign, lang)} SOL"


def usd(v, lang: str = "de") -> str:
    v = _num(v)
    return tx("na", lang) if v is None else (f"{de(v, 2, lang=lang)} $" if lang != "en" else
                                             ("-" if v < 0 else "") + f"${de(abs(v), 2, lang=lang)}")


def pct(frac, dp: int = 1, lang: str = "de") -> str:
    v = _num(frac)
    return tx("na", lang) if v is None else f"{de(v * 100, dp, True, lang)} %"


def berlin(ms) -> datetime:
    """Europe/Berlin without tzdata: CET, CEST from the last Sunday of March to that of October (01:00 UTC)."""
    t = datetime.fromtimestamp(float(ms) / 1000, timezone.utc)

    def last_sunday(month: int) -> datetime:
        d = datetime(t.year, month, 31, 1, tzinfo=timezone.utc)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    summer = last_sunday(3) <= t < last_sunday(10)
    return t + timedelta(hours=2 if summer else 1)


MONTHS_EN = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def when(ms, lang: str = "de") -> str:
    if not _num(ms):
        return "?"
    b = berlin(ms)
    return f"{b.day} {MONTHS_EN[b.month - 1]} {b:%H:%M}" if lang == "en" else b.strftime("%d.%m. %H:%M")


def short_address(a, lang: str = "de") -> str:
    a = str(a or "")
    return f"{a[:4]}…{a[-4:]}" if len(a) > 12 else (a or tx("na", lang))


def clip(s, n: int) -> str:
    s = " ".join(str(s or "").split()).replace("**", "")
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def embed(title: str, description: str, color: int = BLUE, fields: list[tuple[str, str, bool]] | None = None,
          footer: str | None = None, lang: str = "de", now_ms: int | None = None) -> dict:
    """One answer, laid out like every Pythia post: the title, the description, the fields in a
    fixed order, the footer (what it is, then "Pythia · Alpha"), the time."""
    e: dict = {"title": clip(title, 250), "description": description[:4000], "color": color}
    if fields:
        e["fields"] = [{"name": clip(n, 250), "value": (v or "-")[:1024], "inline": i} for n, v, i in fields[:25]]
    e["footer"] = {"text": clip(" · ".join(x for x in (footer, tx("footer", lang)) if x), 200)}
    if now_ms:
        e["timestamp"] = datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return e


# ---------------------------------------------------------------- the answers

def status_embed(st: dict | None, now_ms: int, lang: str = "de") -> dict:
    T = lambda k, **kw: tx(k, lang, **kw)                    # noqa: E731
    if not isinstance(st, dict):
        return embed(T("live"), T("no_status"), GREY, lang=lang)
    on, running = bool(st.get("on")), bool(st.get("running"))
    age = now_ms - int(_num(st.get("t")) or 0)
    if not running or age > STALE_MS:
        head, color = T("not_running") + (T("stale", m=age // 60_000) if age > STALE_MS else ""), GREY
    elif st.get("kill"):
        head, color = T("kill"), RED
    elif on:
        head, color = T("on"), GREEN
    else:
        head, color = T("off"), ORANGE
    mode = {"test": T("mode_test"), "full": T("mode_full")}.get(str(st.get("mode")), str(st.get("mode") or T("na")))
    pnl = _num(st.get("pnl_today_sol"))
    stake = _num((st.get("stake") or {}).get("sol")) or _num((st.get("limits") or {}).get("max_trade_sol"))
    fields = [
        (T("f_mode"), f"{mode} · {st.get('rule') or '?'}", True),
        (T("f_wallet"), f"{short_address(st.get('address'), lang)} · {sol(st.get('balance_sol'), lang=lang)}", True),
        (T("f_today"), T("today", pnl=sol(pnl, sign=True, lang=lang), n=int(_num(st.get("trades_today")) or 0),
                         wins=int(_num(st.get("wins_today")) or 0)), False),
        (T("f_total"), T("total", pnl=sol(st.get("pnl_total_sol"), sign=True, lang=lang),
                         n=int(_num(st.get("trades_total")) or 0)), True),
        (T("f_stake"), sol(stake, lang=lang) + (f" ({clip((st.get('stake') or {}).get('why'), 80)})"
                                                if (st.get("stake") or {}).get("why") else ""), True),
    ]
    pos = [p for p in st.get("positions") or [] if isinstance(p, dict)]
    lines = []
    for p in pos[:10]:
        cost, mark = _num(p.get("cost_sol")), _num(p.get("mark_sol"))
        ret = f" · {pct(mark / cost - 1, lang=lang)}" if cost and mark is not None else ""
        lines.append(f"{clip(p.get('symbol') or p.get('name') or '?', 16)}: {sol(cost, lang=lang)}{ret}"
                     + (T("stuck") if p.get("state") == "stuck" else ""))
    fields.append((T("f_open", n=len(pos)), "\n".join(lines) or T("none"), False))
    lim = st.get("limits") or {}
    if lim:
        fields.append((T("f_limits"), T("limits", day=sol(lim.get("max_daily_loss_sol"), lang=lang),
                                        total=sol(lim.get("max_total_sol"), lang=lang),
                                        n=int(_num(lim.get("max_open")) or 0)), False))
    why = "; ".join(str(g) for g in (st.get("gate") or [])[:3]) or st.get("refusing")
    stops = [k for k, v in (st.get("stops") or {}).items() if v]
    desc = f"**{head}**"
    if not on and why:
        desc += "\n" + T("why", why=clip(why, 300))
    if stops:
        desc += "\n" + T("stops", stops=", ".join(T("stop_" + s) if s in ("daily", "total") else s for s in stops))
    return embed(T("live"), desc, color, fields, footer=T("as_of", t=when(st.get("t"), lang)), lang=lang)


def trades_embed(rows, n: int = 10, lang: str = "de") -> dict:
    trades = [t for t in (rows or []) if isinstance(t, dict) and _num(t.get("exit_ms"))]
    trades.sort(key=lambda t: _num(t["exit_ms"]), reverse=True)
    if not trades:
        return embed(tx("trades_none_title", lang), tx("trades_none", lang), GREY, lang=lang)
    lines = []
    for t in trades[:n]:
        p = _num(t.get("pnl_sol")) or 0.0
        dot = "🟢" if p > 0 else "🔴" if p < 0 else "⚪"
        lines.append(f"{dot} {when(t['exit_ms'], lang)} **{clip(t.get('symbol') or t.get('name') or '?', 14)}** "
                     f"{pct(t.get('ret'), lang=lang)} · {sol(p, sign=True, lang=lang)} · "
                     f"{clip(t.get('exit_why') or '?', 12)}")
    total = sum(_num(t.get("pnl_sol")) or 0.0 for t in trades[:n])
    return embed(tx("trades_title", lang, n=min(n, len(trades))), "\n".join(lines),
                 GREEN if total > 0 else RED if total < 0 else GREY,
                 footer=tx("trades_footer", lang, pnl=sol(total, sign=True, lang=lang)), lang=lang)


def konten_embed(status: dict | None, forward: dict | None, lang: str = "de") -> dict:
    T = lambda k, **kw: tx(k, lang, **kw)                    # noqa: E731
    words = STATUS_EN if lang == "en" else STATUS_DE
    real, paper = [], []
    if isinstance(status, dict) and status.get("address"):
        real.append(T("wallet", a=short_address(status.get("address"), lang),
                      bal=sol(status.get("balance_sol"), lang=lang), pnl=sol(status.get("pnl_total_sol"), sign=True,
                                                                             lang=lang)))
    aps = [a for a in ((forward or {}).get("autopilots") or []) if isinstance(a, dict)]
    for a in aps:
        ret = _num(a.get("return_pct"))
        line = (f"{clip(a.get('label') or a.get('name'), 40)} ({str(a.get('venue') or '?').replace('_', ' ')}): "
                f"{usd(a.get('equity'), lang)}" + (f" · {de(ret, 1, True, lang)} %" if ret is not None else ""))
        (real if a.get("mode") == "live" else paper).append(line)
    books = [b for b in ((forward or {}).get("books") or []) if isinstance(b, dict)]
    fields = [(T("f_real"), "\n".join(real[:10]) or T("nothing"), False),
              (T("f_paper", n=len(paper)), "\n".join(paper[:12]) + ("\n" + T("more", n=len(paper) - 12)
                                                                    if len(paper) > 12 else "") or T("nothing"),
               False)]
    if books:
        counts: dict[str, int] = {}
        for b in books:
            counts[str(b.get("status") or "unknown")] = counts.get(str(b.get("status") or "unknown"), 0) + 1
        fields.append((T("f_books", n=len(books)),
                       ", ".join(f"{n} {words.get(k, k.replace('_', ' '))}"
                                 for k, n in sorted(counts.items(), key=lambda kv: -kv[1])),
                       False))
    gen = (forward or {}).get("generated")
    return embed(T("accounts"), T("accounts_desc"), BLUE, fields,
                 footer=T("forward_footer", gen=gen) if gen else T("read_only"), lang=lang)


def newest_studies(root: Path, n: int = 6) -> list[tuple[str, int, dict]]:
    out = []
    try:
        dirs = list(root.iterdir())
    except OSError:
        return []
    for d in dirs:
        p = d / "latest.json"
        if d.name in NOT_STUDIES or not p.is_file():
            continue
        try:
            at = int(p.stat().st_mtime * 1000)
        except OSError:
            continue
        out.append((d.name, at, p))
    out.sort(key=lambda x: -x[1])
    return [(name, at, read_json(p) or {}) for name, at, p in out[:n]]


def lab_embed(models: dict | None, studies: list[tuple[str, int, dict]], lang: str = "de") -> dict:
    words = STATUS_EN if lang == "en" else STATUS_DE
    lines = []
    for name, at, rep in studies:
        verdict = rep.get("verdict") or rep.get("headline") if isinstance(rep, dict) else None
        lines.append(f"**{name}** ({when(at, lang)}): "
                     f"{clip(verdict, 160) if isinstance(verdict, str) else tx('no_verdict', lang)}")
    fields = []
    ms = [m for m in ((models or {}).get("models") or []) if isinstance(m, dict) and m.get("code")]
    if ms:
        by: dict[str, list[str]] = {}
        for m in ms:
            by.setdefault(str(m.get("status") or "?"), []).append(str(m["code"]))
        fields.append((tx("f_zoo", lang, n=len(ms)),
                       "\n".join(f"{words.get(k, k)}: {', '.join(v)}" for k, v in sorted(by.items())), False))
    return embed(tx("lab", lang), "\n".join(lines) or tx("no_studies", lang), BLUE, fields,
                 footer=tx("read_only", lang), lang=lang)


def respond(name: str, user_id, owner_id, now_ms: int, root: Path | None = None, lang: str = "de") -> dict:
    """The answer to one command in `lang` (the channel's, channel_lang): {"content", "embeds",
    "ephemeral"}. The owner check first."""
    lang = "en" if lang == "en" else "de"
    if not allowed(user_id, owner_id):
        return {"content": NOT_ALLOWED_EN if lang == "en" else NOT_ALLOWED, "embeds": [], "ephemeral": True}
    root = root or reports_root()
    if name == "status":
        e = status_embed(read_json(root / "pumpfun_rt" / "live_status.json"), now_ms, lang)
    elif name == "trades":
        d = read_json(root / "pumpfun_rt" / "live_trades.json")
        e = trades_embed(d.get("trades") if isinstance(d, dict) else d, lang=lang)
    elif name == "konten":
        e = konten_embed(read_json(root / "pumpfun_rt" / "live_status.json"),
                         read_json(root / "forward" / "latest.json"), lang)
    elif name == "lab":
        e = lab_embed(read_json(root / "models" / "latest.json"), newest_studies(root), lang)
    else:
        return {"content": tx("unknown_command", lang), "embeds": [], "ephemeral": True}
    e.setdefault("timestamp", datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
    return {"content": None, "embeds": [e], "ephemeral": True}
