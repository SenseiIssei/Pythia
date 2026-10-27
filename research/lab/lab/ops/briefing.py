"""The morning briefing: one message at 09:00 Europe/Berlin to Telegram and Discord.

Built only from the files the lab and the engines already write, and the engines'
GET /api/state (read only); no model is asked anything. One card, short sections,
numbers formatted in the messages' language, one overview chart:

  real money             the pump.fun bot's state, yesterday's real-money trades (Berlin day), P&L in
                         SOL and euro, the total, the wallet and the stake (live/pumpfun_rt/ledger.csv,
                         reports/pumpfun_rt/live_status.json at any age), and every running real-money
                         autopilot (Kraken, Alpaca; mode live)
  paper and autopilots   the digest's table of autopilots (reports/learn), the forward
                         test's books by status (reports/forward), real money readiness, the
                         small-account paper books in EUR (reports/smallaccount, S1 and S2), the
                         on-chain long-term book's 0.5 SOL paper wallet (reports/onchain_longterm, L1)
  lab                    the model zoo (reports/models) and the study reports that are new
  research factory       per factory one line (reports/pumpfun_rt/factory.json F3, reports/smallaccount/factory.json
                         F2): trials, the bar, the best new candidate held back, books, model settings adopted;
                         A1's allocator (reports/pumpfun_rt/allocator.json): its pick and why, never the live bot
  Pokemon, CS2, coins,   reports/pokemon, reports/cs2 and cs2_trends, reports/trending and
  stocks and ETFs, news  listings, the engines' US shares and the ETF closes, the news
                         collector's headlines (<data>/ai/news), the three most relevant when the local
                         model tagged them (<data>/ai/news_tags, lab.ai.local), else the newest

First "To decide (n)": what needs the owner today by fixed rules (decisions(): real money stopped or losing, the
API budget overspent, a red check that touches real money or the briefing, a book crossing its bar). The real-money
card is always there, coloured by its state (stopped is never green). A section whose report is there but stale is
named in the footer ("Missing today"); the whole post stays under 2,000 characters, the last sections giving way.

The summary line on top: the local model's two sentences over the facts the cards hold (lab.ai.local, the
owner's PC through the relay or the VPS model, 60 s for both languages), used only when every number in them is
in the facts; else the template (the sections' few words). The model decides nothing else.

A section whose data is missing or older than two days is left out (and named, see above). The briefing
replaces the old morning digest's schedule: it moves the digest's snapshot of the
autopilots (so "today" keeps counting from it) and writes reports/notify/latest.json,
which the engine's GET /api/alerts shows.

  python -m lab.ops.briefing             send it when it is 9 o'clock in Berlin and it has
                                         not gone out today (the job runs hourly in the
                                         morning, UTC, so summer and winter time both hit 9)
  python -m lab.ops.briefing --force     now, whatever the hour
  python -m lab.ops.briefing --dry-run   print it, post nothing
"""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from ..ai import local
from . import i18n, notify
from .notify import Card, Line, Links, Rows, _num, nodash, short, tr

HOUR = 9
LLM_BUDGET_SEC = 60                        # the local model's summary, both languages together
MAX_FACTS = 16
DAY_MS = notify.DAY_MS
STALE_MS = 2 * DAY_MS
# Reports that are not studies: the jobs of every day, shown in their own sections or nowhere.
NOT_STUDIES = {"learn", "forward", "notify", "trending", "listings", "models", "pokemon", "cs2", "cs2_trends",
               "cs2_weekly", "readiness", "pumpfun", "pumpfun_rt", "pumpfun_activity", "polymarket", "agent",
               "exit_shadow", "factory", "paper_review", "studies", "ai", "ai_brief", "ai_news", "ai_analyst",
               "costs", "research", "smallaccount", "onchain_longterm", "notify_sent"}
ETFS = ("SPY", "QQQ", "GLD")


# ---------------------------------------------------------------- when

def due(now_ms: int, last_day: str | None) -> bool:
    """Nine o'clock in Berlin (summer or winter time) and not sent today yet."""
    t = notify.local_time(now_ms)
    return t.hour == HOUR and last_day != t.date().isoformat()


def local_midnight(now_ms: int) -> int:
    """The ms of today's 00:00 in Berlin."""
    t = notify.local_time(now_ms)
    return now_ms - int((t - t.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() * 1000)


# ---------------------------------------------------------------- reading

def stamp_ms(d: dict | None, path: Path | None = None) -> int | None:
    """When a report was written: its own time field, else the file's."""
    if isinstance(d, dict):
        for k in ("updated_ms", "updatedMs", "generated_ms", "generatedMs", "ts_ms", "t"):
            v = _num(d.get(k))
            if v and v > 1e12:
                return int(v)
    try:
        return int(path.stat().st_mtime * 1000) if path is not None else None
    except OSError:
        return None


def fresh(d, now: int, path: Path | None = None) -> dict | None:
    """The report when it is there and at most two days old, else None."""
    if not isinstance(d, dict):
        return None
    at = stamp_ms(d, path)
    return d if at is not None and now - at <= STALE_MS else None


def report(name: str, now: int, file: str = "latest.json") -> dict | None:
    p = notify.reports_root() / name / file
    return fresh(notify.read_json(p), now, p)


def read_ledger(path: Path | None = None) -> list[dict]:
    """The live pump.fun ledger (live/pumpfun_rt/ledger.csv) as dicts with numbers."""
    p = path or notify.data_root() / "live" / "pumpfun_rt" / "ledger.csv"
    try:
        with p.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    except OSError:
        return []
    out = []
    for r in rows:
        rec = {k: v for k, v in r.items() if k}
        for k in ("exit_ms", "pnl_sol", "stake_sol", "ret"):
            rec[k] = _num(r.get(k))
        if rec["exit_ms"] is not None:
            out.append(rec)
    return out


# ---------------------------------------------------------------- the sections

def _sol(v: float, eur: float | None, lang: str, sign: bool = False, dp: int = 4) -> str:
    s = i18n.sol(v, dp, lang, sign)
    return f"{s} · {i18n.eur(v * eur, 2, lang, sign)}" if eur else s


PF_SILENT_MS = 2 * 3_600_000                # a running bot that wrote no status for this long has gone quiet


def pumpfun_state(status: dict | None, now: int) -> tuple[str, int | None]:
    """The live bot's state from its status file at any age (a stopped service writes no more): "running",
    "paused" (running, its gate shut), "stopped", "silent" (says running, wrote nothing for two hours) or "none"
    (no file); and when the file was written."""
    if not isinstance(status, dict):
        return "none", None
    at = stamp_ms(status)
    if not status.get("running"):
        return "stopped", at
    if at is None or now - at > PF_SILENT_MS:
        return "silent", at
    return ("running" if status.get("on") else "paused"), at


def _since(at: int | None, lang: str) -> str:
    return notify.day_label(at, lang) if at else "?"


def pumpfun_section(ledger: list[dict], status: dict | None, now: int, eur: float | None,
                    lang: str) -> tuple[list, str | None, float | None]:
    """(parts, a few words for the summary, yesterday's P&L in SOL when it traded). Yesterday is the
    Berlin day before today. The state line first; the rows of yesterday only when it traded, the wallet and the
    total always, the stake while it runs."""
    mid = local_midnight(now)
    day = [r for r in ledger if mid - DAY_MS <= r["exit_ms"] < mid]
    state, at = pumpfun_state(status, now)
    if state == "none" and not day:
        return [], None, None
    st = status or {}
    parts: list = []
    if state == "running":
        parts.append(Line(tr("bf_pf_running", lang)))
    elif state == "paused":
        why = "; ".join(str(w) for w in (st.get("gate") or [])[:2]) or str(st.get("refusing") or "?")
        parts.append(Line(short(nodash(why), 120), tr("bf_paused", lang)))
    elif state in ("stopped", "silent"):
        parts.append(Line(tr("bf_pf_" + state, lang, day=_since(at, lang))))
    rows = []
    pnl = sum(r["pnl_sol"] or 0.0 for r in day)
    if day:
        wins = sum(1 for r in day if (r["pnl_sol"] or 0) > 0)
        rows.append((tr("bf_yesterday", lang), tr("prl_trades_won", lang, n=len(day), wins=wins)))
        rows.append((tr("prl_row_pnl", lang), _sol(pnl, eur, lang, True)))
        best = max(day, key=lambda r: r["ret"] if r["ret"] is not None else -9)
        worst = min(day, key=lambda r: r["ret"] if r["ret"] is not None else 9)
        if best["ret"] is not None and len(day) > 1:
            rows.append((tr("bf_best_worst", lang), f"{i18n.frac_pct(best['ret'], 1, lang)} / "
                                                    f"{i18n.frac_pct(worst['ret'] or 0.0, 1, lang)}"))
    if _num(st.get("pnl_total_sol")) is not None:
        rows.append((tr("prl_row_total", lang), _sol(st["pnl_total_sol"], eur, lang, True)))
    if _num(st.get("balance_sol")) is not None:
        rows.append((tr("prl_row_wallet", lang), _sol(st["balance_sol"], eur, lang)))
    stake = _num((st.get("stake") or {}).get("sol")) or _num((st.get("limits") or {}).get("max_trade_sol"))
    if stake and state in ("running", "paused"):
        rows.append((tr("prl_row_stake", lang), _sol(stake, eur, lang)))
    if rows:
        parts.append(Rows(rows))
    words = tr("bf_sum_pumpfun", lang, pnl=i18n.sol(pnl, 4, lang, True)) if day else None
    if _num(st.get("balance_sol")) is not None and eur and state in ("running", "paused"):
        words = " · ".join(w for w in (words, tr("bf_sum_wallet", lang, eur=i18n.eur(st["balance_sol"] * eur, 2, lang)))
                           if w)
    return parts, words, (pnl if day else None)


def live_autopilots(rows: list[dict]) -> list[dict]:
    """Every real-money autopilot (mode live) running or paused, of every engine that answered."""
    return [a for r in rows for a in (r.get("state") or {}).get("autopilots") or []
            if (a.get("config") or {}).get("mode") == "live" and a.get("state") in ("running", "paused")]


def real_money_section(rows: list[dict], lang: str) -> list:
    """Every running real-money autopilot (mode live) of every engine that answered."""
    out = []
    for a in live_autopilots(rows):
        cfg = a.get("config") or {}
        eq, start = _num(a.get("equity")), _num(a.get("startCapital"))
        val = notify.money(eq, 2, lang) if eq is not None else ("k. A." if lang == "de" else "n/a")
        if eq is not None and start:
            val += f" · {notify.signed_pct((eq / start - 1) * 100, 1, lang)}"
        if a.get("state") == "paused":
            val += " · " + tr("bf_ap_paused", lang)
        venue = str(cfg.get("venue") or "").capitalize()
        out.append((notify.short_name(cfg.get("name"), 18) + (f" ({venue})" if venue else ""), val))
    return [Rows(out)] if out else []


def real_money_card(ledger: list[dict], status: dict | None, engines: list[dict], now: int, eur: float | None,
                    lang: str) -> tuple[Card, str | None, float | None]:
    """The real-money card, always there: the pump.fun bot and the live autopilots, coloured by their state:
    🛑 stopped or gone quiet, 🔴 lost yesterday or below its start, 🟠 paused, 🟢 running and not losing,
    ⚪ nothing with real money. (card, a few words for the summary, yesterday's pump.fun P&L)."""
    pf, words, pnl = pumpfun_section(ledger, status, now, eur, lang)
    aps = live_autopilots(engines)
    parts = pf + real_money_section(engines, lang)
    state, _ = pumpfun_state(status, now)
    below = any((_num(a.get("equity")) or 0) < (_num(a.get("startCapital")) or 0) for a in aps
                if _num(a.get("equity")) is not None and _num(a.get("startCapital")))
    if state in ("stopped", "silent"):
        emoji = "🛑"
    elif (pnl or 0) < 0 or below:
        emoji = "🔴"
    elif state == "paused" or any(a.get("state") == "paused" for a in aps):
        emoji = "🟠"
    elif state == "running" or aps:
        emoji = "🟢"
    else:
        emoji = "⚪"
    if not parts:
        parts = [Line(tr("bf_real_none", lang))]
    return Card(emoji, tr("bf_real_money", lang), None, parts), words, pnl


def small_line(small: dict | None, lang: str) -> Line | None:
    """The small-account paper books (S1, S2) in one line: each wallet now in EUR and its result since the start."""
    parts = []
    for name, st in sorted(((small or {}).get("books") or {}).items()):
        eq, cap = _num((st or {}).get("equity_eur")), _num((st or {}).get("capital_eur"))
        if eq is not None and cap:
            parts.append(f"{name} {i18n.eur(eq, 2, lang)} ({i18n.eur(eq - cap, 2, lang, sign=True)})")
    return Line(" · ".join(parts), tr("bf_small", lang)) if parts else None


def onchain_line(rep: dict | None, lang: str) -> Line | None:
    """The on-chain long-term book's paper wallet (L1) in one line: its value in USD, its result since the start
    and what it holds (USDC when nothing)."""
    eq, start = _num((rep or {}).get("equity_usdc")), _num((rep or {}).get("start_usdc"))
    if eq is None or not start:
        return None
    held = ", ".join(f"{c} {_num(w) * 100:.0f} %" for c, w in sorted(((rep or {}).get("held") or {}).items())
                     if _num(w)) or "USDC"
    return Line(f"{i18n.money(eq, 2, lang)} ({notify.signed_money(eq - start, 2, lang)}) · {held}",
                tr("bf_onchain_lt", lang))


def paper_section(learn: dict | None, forward: dict | None, readiness: dict | None, prev: dict, now: int,
                  lang: str, small: dict | None = None, onchain: dict | None = None) -> tuple[list, dict, str | None]:
    """One line on the autopilots (how many run, the best and the weakest since their start, today in $),
    the forward books by status, the small-account books in EUR, the on-chain long-term book and the readiness
    line; the snapshot for tomorrow (the digest's, so "today" keeps counting); a few words for the summary."""
    parts: list = []
    snap: dict = {}
    words = None
    if learn is not None:
        table, snap, today, n = notify.autopilot_parts(learn, prev, now, lang)
        if table:
            since = []
            for a in learn.get("autopilots") or []:
                eq, start = _num(a.get("equity")), _num(a.get("start_capital"))
                if a.get("state") == "running" and eq is not None and start:
                    since.append(((eq / start - 1) * 100, notify.short_name(a.get("name"), 22)))
            text = tr("bf_paper_lead", lang, n=n)
            if len(since) > 1:
                best, worst = max(since), min(since)
                text += " · " + tr("bf_paper_ends", lang, best=f"{best[1]} {notify.signed_pct(best[0], 1, lang)}",
                                   worst=f"{worst[1]} {notify.signed_pct(worst[0], 1, lang)}")
            if today:
                text += " · " + tr("bf_paper_today", lang, money=notify.signed_money(sum(today), lang=lang))
                words = tr("bf_sum_paper", lang, money=notify.signed_money(sum(today), lang=lang))
            parts.append(Line(text, tr("bf_autopilots", lang)))
    if forward is not None:
        books = [b for b in forward.get("books") or [] if b.get("name")]
        if books:
            counts: dict[str, int] = {}
            for b in books:
                counts[str(b.get("status") or "unknown")] = counts.get(str(b.get("status") or "unknown"), 0) + 1
            words_fw = ", ".join(f"{n} {tr('fw_' + k, lang) if 'fw_' + k in i18n.CATALOG['en'] else k.replace('_', ' ')}"
                                 for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
            parts.append(Line(tr("bf_books", lang, n=len(books), counts=words_fw), tr("forward_test", lang)))
    sl = small_line(small, lang)
    if sl is not None:
        parts.append(sl)
    ol = onchain_line(onchain, lang)
    if ol is not None:
        parts.append(ol)
    if readiness is not None:
        lead = (notify.READINESS_TEXT_DE if lang == "de" else notify.READINESS_TEXT)["lead"]
        parts.append(Line(short(nodash(notify.readiness_text(readiness, now, lang)), 130), lead))
    return parts, snap, words


def lab_section(models: dict | None, now: int, lang: str, root: Path | None = None) -> list:
    """The model zoo by status and its decisions of the last two days, and the study reports
    that are new since the day before yesterday."""
    lines = []
    if models is not None:
        ms = [m for m in models.get("models") or [] if isinstance(m, dict) and m.get("code")]
        if ms:
            use = [m["code"] for m in ms if m.get("status") == "in use"]
            shadow = [m["code"] for m in ms if m.get("status") == "shadow"]
            failed = [m["code"] for m in ms if str(m.get("status") or "").startswith("failed")]
            retired = sum(1 for m in ms if m.get("status") == "retired")
            lines.append(Line(tr("bf_zoo", lang, use=", ".join(use) or "-", shadow=", ".join(shadow) or "-",
                                 failed=len(failed), retired=retired), tr("bf_zoo_lead", lang)))
            since = datetime.fromtimestamp((now - STALE_MS) / 1000, timezone.utc).strftime("%Y-%m-%d")
            news = []
            for m in ms:
                for d in m.get("decisions") or []:
                    if str(d.get("date") or "") >= since and d.get("decision") in ("promoted", "rejected", "kept"):
                        news.append(f"{m['code']} {i18n.word(str(d['decision']), lang)}")
            if news:
                lines.append(Line(", ".join(news[:6]), tr("bf_zoo_news", lang)))
    root = root or notify.reports_root()
    new = []
    try:
        for d in sorted(root.iterdir()):
            p = d / "latest.json"
            if d.name in NOT_STUDIES or not p.is_file():
                continue
            at = stamp_ms(None, p)
            if at is not None and 0 <= now - at <= STALE_MS:
                new.append(d.name)
    except OSError:
        pass
    if new:
        lines.append(Line(", ".join(new[:6]) + (f" (+{len(new) - 6})" if len(new) > 6 else ""),
                          tr("bf_studies", lang)))
    return lines


def pokemon_section(rep: dict | None, lang: str) -> list:
    """One line: the play collection's value and return, how many cards look cheap and the first."""
    if rep is None:
        return []
    bits = []
    col = rep.get("collection") or {}
    eq, ret = _num(col.get("equity")), _num(col.get("returnPct"))
    if eq is not None:
        bits.append(notify.money(eq, 2, lang) + (f" ({notify.signed_pct(ret, 1, lang)})" if ret is not None else ""))
    cheap = [i for i in rep.get("items") or [] if isinstance(i, dict) and "fair" in str(i.get("value") or "")]
    if cheap:
        bits.append(tr("bf_cheap_n", lang, n=len(cheap), top=short(nodash(str(cheap[0].get("label"))), 26)))
    return [Line(" · ".join(bits), tr("bf_pokemon", lang))] if bits else []


def cs2_section(rep: dict | None, trends: dict | None, now: int, lang: str) -> list:
    """One line: the play portfolio, the hints of the last 24 h and the first, the liquid Steam items."""
    bits = []
    if rep is not None:
        pf = rep.get("portfolio") or {}
        eq, ret = _num(pf.get("equity")), _num(pf.get("returnPct"))
        if eq is not None:
            bits.append(i18n.eur(eq, 0, lang) + (f" ({notify.signed_pct(ret, 1, lang)})" if ret is not None else ""))
        alerts = [a for a in rep.get("alerts") or [] if isinstance(a, dict) and now - (_num(a.get("tsMs")) or 0) <= DAY_MS]
        if alerts:
            bits.append(tr("bf_hints_n", lang, n=len(alerts), top=short(nodash(str(alerts[0].get("name"))), 26)))
    if trends is not None:
        liquid = _num((trends.get("summary") or {}).get("liquid"))
        if liquid is not None:
            bits.append(tr("bf_liquid", lang, n=i18n.num(liquid, 0, lang)))
    return [Line(" · ".join(bits), tr("bf_cs2", lang))] if bits else []


def coins_section(trending: dict | None, listings: dict | None, now: int, lang: str) -> list:
    """BTC, ETH and SOL over 24 h and the top gainer as fields; new listings as a line."""
    rows = []
    if trending is not None:
        al = trending.get("alpaca") or {}
        for c in ("BTC", "ETH", "SOL"):
            ch = _num((al.get(c) or {}).get("change"))
            if ch is not None:
                rows.append((f"{c} 24 h", i18n.frac_pct(ch, 1, lang), ch))
        g = (trending.get("gainers") or [None])[0]
        if isinstance(g, dict) and g.get("coin") and _num(g.get("change")) is not None:
            rows.append((tr("bf_gainer", lang), f"{g['coin']} {i18n.frac_pct(g['change'], 0, lang)}"))
    parts: list = [Rows(rows)] if rows else []
    if listings is not None:
        new = [i.get("label") for i in listings.get("items") or []
               if isinstance(i, dict) and now - (_num(i.get("atMs")) or 0) <= DAY_MS and i.get("label")]
        if new:
            parts.append(Line(", ".join(str(x) for x in new[:5]), tr("bf_listings", lang)))
    return parts


def etf_closes(now: int, root: Path | None = None) -> list[tuple[str, float, float]]:
    """(symbol, last close, change in %) of a few ETFs from <data>/etf/daily, when the files are fresh."""
    root = root or notify.data_root() / "etf" / "daily"
    out = []
    for sym in ETFS:
        p = root / f"{sym}.csv"
        try:
            if now - p.stat().st_mtime * 1000 > STALE_MS:
                continue
            lines = p.read_text(encoding="utf-8").strip().splitlines()[-2:]
            a, b = (float(x.split(",")[1]) for x in lines)
        except (OSError, ValueError, IndexError):
            continue
        if a > 0:
            out.append((sym, b, (b / a - 1) * 100))
    return out


def stocks_section(rows: list[dict], etfs: list[tuple[str, float, float]], lang: str) -> list:
    """The ETF closes and the US shares the autopilots hold (Alpaca, no "/" in the market)."""
    out = [(sym, f"{notify.money(px, 2, lang)} · {notify.signed_pct(ch, 1, lang)}") for sym, px, ch in etfs]
    held: dict[str, float] = {}
    for r in rows:
        for p in (r.get("state") or {}).get("positions") or []:
            mid = str(p.get("marketId") or "")
            if mid.startswith("alpaca:") and "/" not in mid:
                v = abs((_num(p.get("qty")) or 0) * (_num(p.get("lastPrice")) or 0))
                if v > 0:
                    held[mid.split(":", 1)[1]] = held.get(mid.split(":", 1)[1], 0.0) + v
    for sym, v in sorted(held.items(), key=lambda kv: -kv[1])[:4]:
        out.append((tr("bf_held", lang, sym=sym), notify.money(v, 0, lang)))
    return [Line(" · ".join(f"{a} {b}" for a, b in out), tr("bf_stocks", lang))] if out else []


def news_section(now: int, lang: str, root: Path | None = None, n: int = 3) -> list:
    """The news collector's headlines of today's and yesterday's files (UTC): the most relevant for the lab first
    when the local model tagged them (<data>/ai/news_tags, 1 to 5), then those that name a coin, then the newest;
    each a link."""
    root = root or notify.data_root() / "ai" / "news"
    items = []
    for k in (0, 1):
        day = datetime.fromtimestamp((now - k * DAY_MS) / 1000, timezone.utc).strftime("%Y-%m-%d")
        try:
            text = (root / f"{day}.jsonl").read_text(encoding="utf-8")
        except OSError:
            continue
        tags = local.read_tags(day, root.parent / "news_tags")
        for line in text.splitlines():
            try:
                h = json.loads(line)
            except ValueError:
                continue
            at = (_num(h.get("published_us")) or 0) / 1000 if isinstance(h, dict) else 0
            if isinstance(h, dict) and h.get("title") and 0 <= now - at <= STALE_MS:
                rel = _num((tags.get(local.headline_key(h)) or {}).get("relevance")) or 0
                items.append((rel, bool(h.get("coins")), at, h))
    if not items:
        return []
    items.sort(key=lambda x: x[:3], reverse=True)
    seen, out = set(), []
    for *_, h in items:
        title = short(nodash(str(h["title"])), 90)
        if title in seen:
            continue
        seen.add(title)
        out.append(Links([(title, h.get("link"))], "•"))
        if len(out) == n:
            break
    return out


def research_section(rep: dict | None, now: int, lang: str, n: int = 5) -> tuple[list, str | None]:
    """The task lanes (reports/research/latest.json, written on the host by research-report.py): what
    finished in the last 24 hours with its verdict, what runs, what waits, the API credit. (parts,
    a few words for the summary)."""
    if rep is None:
        return [], None
    done = [d for d in rep.get("done") or [] if isinstance(d, dict) and 0 <= now - (_num(d.get("at")) or 0) <= DAY_MS]
    parts: list = []
    for d in done[:n]:
        mark = "✅" if d.get("ok") else "⚠️"
        why = short(nodash(str(d.get("why") or "")), 100)
        parts.append(Line("\n↳ " + (why or tr("bf_res_no_words", lang)),
                          f"{mark} {short(nodash(str(d.get('title'))), 60)}"))
    if len(done) > n:
        parts.append(Line(tr("bf_res_more", lang, n=len(done) - n)))
    running = [r for r in rep.get("running") or [] if isinstance(r, dict)]
    if running:
        names = ", ".join(short(nodash(str(r.get("title"))), 40) for r in running[:4])
        parts.append(Line(names, "⏳ " + tr("bf_res_running", lang)))
    waiting = int(_num(rep.get("queued")) or 0)
    held = rep.get("held") or []
    if waiting or held:
        parts.append(Line(tr("bf_res_queue", lang, n=waiting, held=len(held)), "🗂️ " + tr("bf_res_queue_lead", lang)))
    b = rep.get("budget") or {}
    # also at balance 0: an overspent, paused budget is exactly what the owner must see
    if isinstance(b, dict) and any(_num(b.get(k)) is not None for k in ("balance_usd", "left_usd")):
        text = tr("bf_res_budget", lang, left=notify.money(_num(b.get("left_usd")) or 0.0, 2, lang),
                  reserve=notify.money(_num(b.get("reserve_usd")) or 0.0, 0, lang))
        if b.get("paused"):
            text += " · " + tr("bf_res_paused", lang)
        parts.append(Line(text, "💳 " + tr("bf_res_budget_lead", lang)))
    ok = sum(1 for d in done if d.get("ok"))
    words = tr("bf_sum_research", lang, n=ok) if ok else None
    return parts, words


# The research factories: (code, the report's folder, its file). F3 is the pump.fun factory (lab.pumpfun_rt.factory);
# F2, the small-account factory, writes the same fields to reports/smallaccount/factory.json once it runs.
FACTORIES = (("F3", "pumpfun_rt", "factory.json"), ("F2", "smallaccount", "factory.json"))


def per_entry(r: dict, lang: str) -> str | None:
    """A trial's mean per entry at 0.1 SOL with its 95 % band by day and its trimmed mean (F3's fields), None
    without a mean. No 30-day wallet medians: a bootstrap of a few days is no forecast."""
    m = _num(r.get("mean"))
    if m is None:
        return None
    de, pc = lang == "de", (lambda x: i18n.frac_pct(x, 1, lang))
    lo, hi, tm = _num(r.get("lo")), _num(r.get("hi")), _num(r.get("trimmed"))
    out = f"{pc(m)} {'je Einstieg' if de else 'per entry'}"
    if lo is not None and hi is not None:
        out += f" ({'Band' if de else 'band'} {pc(lo)} {'bis' if de else 'to'} {pc(hi)})"
    if tm is not None:
        out += f", {'getrimmt' if de else 'trimmed'} {pc(tm)}"
    return out


def factory_line(code: str, rep: dict | None, lang: str) -> Line | None:
    """One factory in one line: its trials last night and in all, the bar, the night's best candidate (its mean per
    entry with the band and the trimmed mean, its scored days) with its held-back result, the paper books started and
    retired that night, the model settings adopted."""
    if not isinstance(rep, dict) or _num(rep.get("trials_ever")) is None:
        return None
    de = lang == "de"
    n = int(_num(rep.get("trials_tonight")) or 0)
    bits = [tr("bf_fac_trials", lang, n=n, ever=i18n.num(_num(rep.get("trials_ever")) or 0, 0, lang))]
    bar = rep.get("bar") or {}
    if _num(bar.get("sharpe")) is not None:
        bits.append(tr("bf_fac_bar", lang, sharpe=i18n.num(bar["sharpe"], 3, lang),
                       n=i18n.num(_num(bar.get("trials")) or 0, 0, lang)))
    best = next((r for r in rep.get("best") or [] if isinstance(r, dict) and r.get("id")), None)
    if best is None:
        bits.append(tr("bf_fac_none", lang))
    else:
        text = f"{'bester neuer' if de else 'best new'} {best['id']}"
        mean = per_entry(best, lang)
        if mean is not None:
            nd = len(best.get("days") or ()) if isinstance(best.get("days"), list) else 0
            text += f": {mean}" + (f", {nd} {'Tage' if de else 'days'}" if nd else "")
        held = next((h for h in rep.get("holdback") or [] if isinstance(h, dict) and h.get("id") == best["id"]), None)
        if held is None:
            text += ", " + tr("bf_fac_nohold", lang)
        else:
            hm = per_entry(held, lang)
            text += f", {'zurückgehalten' if de else 'held back'} {(hm + ', ') if hm else ''}" \
                    f"{i18n.sol(_num(held.get('pnl_sol')) or 0.0, 3, lang, True)} {'bei' if de else 'at'} " \
                    f"{i18n.sol(0.1, 1, lang)}"
        bits.append(text)
    night, at = str(rep.get("night") or ""), _num(rep.get("updated_ms")) or 0
    books = [b for b in rep.get("books") or [] if isinstance(b, dict)]
    started = sum(1 for b in books if night and b.get("added_day") == night)
    retired = sum(1 for b in rep.get("retired") or [] if isinstance(b, dict) and at - (_num(b.get("retired_ms")) or 0)
                  <= DAY_MS / 2)
    bits.append(tr("bf_fac_books", lang, started=started, retired=retired, active=len(books)))
    if rep.get("winners"):
        bits.append(tr("bf_fac_winners", lang, ids=", ".join(str(w) for w in rep["winners"][:3])))
    mods = rep.get("models") if isinstance(rep.get("models"), dict) else {}
    took = [k for k, v in mods.items() if isinstance(v, dict) and v.get("adopted")]
    bits.append(tr("bf_fac_models", lang, labels=", ".join(took)) if took else tr("bf_fac_models_none", lang))
    return Line(" · ".join(bits), tr("bf_fac_" + code, lang))


def alloc_line(rep: dict | None, lang: str) -> Line | None:
    """A1's allocator in one line: what it would pick and why (P(best), the weight, the posterior's daily growth
    and its days, the arms under the drawdown guard), and the live bot's own strategy, which it never changes."""
    arms = (rep or {}).get("arms") if isinstance(rep, dict) else None
    if not isinstance(arms, dict) or not arms:
        return None
    ch = rep.get("choice")
    if not ch:
        return Line(tr("prt_alloc_out", lang), tr("bf_alloc_lead", lang))
    a = arms.get(ch) or {}
    guarded = [k for k, v in arms.items() if isinstance(v, dict) and v.get("guarded")]
    text = tr("bf_alloc", lang, pick=ch, p=i18n.frac_pct(_num(a.get("p_best")) or 0.0, 0, lang, sign=False),
              w=i18n.frac_pct(_num(a.get("weight")) or 0.0, 0, lang, sign=False),
              g=i18n.frac_pct(_num(a.get("posterior_mean")) or 0.0, 1, lang), days=int(_num(a.get("days")) or 0),
              guard=tr("bf_alloc_guard", lang, arms=", ".join(guarded)) if guarded else "",
              live=rep.get("live_rule") or ("k. A." if lang == "de" else "n/a"))
    return Line(text, tr("bf_alloc_lead", lang))


def factory_section(reps: dict, alloc: dict | None, lang: str) -> list:
    """Per factory with a fresh report one line, then the allocator's line; nothing when no factory report is
    fresh. `reps` code -> the fresh report or None."""
    lines = [ln for code, _, _ in FACTORIES if (ln := factory_line(code, reps.get(code), lang)) is not None]
    if not lines:
        return []
    al = alloc_line(alloc, lang)
    return lines + ([al] if al is not None else [])


# ---------------------------------------------------------------- what needs the owner today

# Health checks whose red needs a decision: they touch real money, or the briefing itself (the job that sends it,
# the local model that words its summary, the reports it is built from). Any other red is in the head's red line.
REAL_MONEY_CHECKS = {"pythia-server", "pythia-autopilot", "pythia-pumpfun-live", "pythia-onchain-live", "autopilot",
                     "safe account", "job discord-live-fills", "job onchain-live-watch", "job pumpfun-live-watch"}
BRIEFING_CHECKS = {"job briefing", "job local-llm", "job llm-news", "job news-collect", "job health",
                   "job notify-pending", "job learn", "job forward", "job readiness", "data reports"}
# The health job's details in German (it writes English); a detail without one is left out of a German post.
DETAIL_DE = ((re.compile(r"^last run failed, exit (\d+), (\d+) in a row$"), "letzter Lauf mit Exit {0}, {1}-mal in Folge"),
             (re.compile(r"^last run failed, exit (\d+)$"), "letzter Lauf mit Exit {0}"),
             (re.compile(r"^not running$"), "läuft nicht"),
             (re.compile(r"^inactive$"), "inaktiv"))


def check_detail(detail, lang: str) -> str | None:
    d = " ".join(str(detail or "").split())
    if lang != "de":
        return short(nodash(d), 70) or None
    for pat, de in DETAIL_DE:
        m = pat.match(d)
        if m:
            return de.format(*m.groups())
    return None


def decisions(now: int, lang: str, status: dict | None, ledger: list[dict], engines: list[dict], research: dict | None,
              health: dict | None, readiness: dict | None, factories: dict, eur: float | None = None) -> list[str]:
    """What needs the owner today, by fixed rules, one short line each, in this order: real money stopped or losing
    (the pump.fun bot stopped, quiet, paused or down yesterday; a live autopilot paused or below its start), the API
    budget overspent, a red check that touches real money or the briefing, a book crossing its bar (an autopilot
    ready for real money, a factory winner)."""
    out = []
    state, at = pumpfun_state(status, now)
    st = status or {}
    if state in ("stopped", "silent"):
        total, wallet = _num(st.get("pnl_total_sol")), _num(st.get("balance_sol"))
        out.append(tr("bf_dec_pf_" + state, lang, day=_since(at, lang),
                      total=i18n.sol(total, 4, lang, True) if total is not None else "?",
                      wallet=i18n.sol(wallet, 4, lang) if wallet is not None else "?"))
    elif state == "paused":
        why = "; ".join(str(w) for w in (st.get("gate") or [])[:1]) or str(st.get("refusing") or "?")
        out.append(tr("bf_dec_pf_paused", lang, why=short(nodash(why), 70)))
    mid = local_midnight(now)
    day = [r for r in ledger if mid - DAY_MS <= r["exit_ms"] < mid]
    pnl = sum(r["pnl_sol"] or 0.0 for r in day)
    if day and pnl < 0:
        out.append(tr("bf_dec_pf_losing", lang, n=len(day), pnl=_sol(pnl, eur, lang, True)))
    for a in live_autopilots(engines):
        name = notify.short_name((a.get("config") or {}).get("name"), 22)
        eq, start = _num(a.get("equity")), _num(a.get("startCapital"))
        if a.get("state") == "paused":
            out.append(tr("bf_dec_ap_paused", lang, name=name))
        elif eq is not None and start and eq < start:
            out.append(tr("bf_dec_ap_losing", lang, name=name, pct=notify.signed_pct((eq / start - 1) * 100, 1, lang)))
    b = (research or {}).get("budget") or {}
    left, bal = _num(b.get("left_usd")), _num(b.get("balance_usd"))
    if (left is not None and left < 0) or (bal is not None and bal < 0):
        out.append(tr("bf_dec_budget", lang, left=notify.money(left if left is not None else bal, 2, lang),
                      paused=tr("bf_dec_budget_paused", lang) if b.get("paused") else ""))
    for c in (health or {}).get("checks") or []:
        name = str(c.get("name") or "")
        if c.get("ok") or name not in REAL_MONEY_CHECKS | BRIEFING_CHECKS:
            continue
        label = name.removeprefix("job ").removeprefix("data ")
        detail = check_detail(c.get("detail"), lang)
        out.append(tr("bf_dec_red", lang, name=label, detail=f": {detail}" if detail else ""))
    for i in (readiness or {}).get("autopilots") or []:
        if isinstance(i, dict) and i.get("on_account") and i.get("ready"):
            out.append(tr("bf_dec_ready", lang, name=notify.short_name(i.get("name"), 30)))
    for code, _, _ in FACTORIES:
        rep = factories.get(code)
        wins = [str(w) for w in (rep or {}).get("winners") or []] if isinstance(rep, dict) else []
        if wins:
            out.append(tr("bf_dec_winner", lang, code=code, ids=", ".join(wins[:3])))
    return out


def decide_card(items: list[str], lang: str) -> Card:
    """"To decide (n)" with a line each; green "nothing to decide" when there is nothing."""
    if not items:
        return Card("🟢", tr("bf_decide_none", lang))
    return Card("🟠", tr("bf_decide", lang, n=len(items)), None, [Line(short(x, 160), "•") for x in items])


# The sections whose report can go stale, for the "missing today" footer: (the words' key, folder, file). Only a
# report that is there but older than two days is named; one that never was is not missing.
SECTIONS = (("bf_sec_autopilots", "learn", "latest.json"), ("forward_test", "forward", "latest.json"),
            ("bf_sec_readiness", "readiness", "latest.json"), ("bf_research", "research", "latest.json"),
            ("bf_zoo_lead", "models", "latest.json"), ("bf_fac_F3", "pumpfun_rt", "factory.json"),
            ("bf_fac_F2", "smallaccount", "factory.json"), ("bf_sec_coins", "trending", "latest.json"),
            ("bf_sec_pokemon", "pokemon", "latest.json"), ("bf_sec_cs2", "cs2", "latest.json"),
            ("bf_sec_ai_brief", "ai_brief", "latest.json"))


def missing_today(read, raw, now: int, lang: str) -> list[str]:
    """Each section whose report is there but stale, with the day it was last written."""
    out = []
    for key, folder, file in SECTIONS:
        if read(folder, file) is not None:
            continue
        d = raw(folder, file)
        if not isinstance(d, dict):
            continue
        at = stamp_ms(d)
        out.append(tr("bf_missing_since", lang, name=tr(key, lang), day=_since(at, lang)) if at else tr(key, lang))
    return out


def text_of(cards: list[Card], lang: str) -> str:
    """The post as the owner reads it: plain text, whole."""
    return notify.plain(notify.render_post(cards, "telegram", 10 ** 6, lang))


BRIEF_CHARS = 1900                     # the whole briefing as plain text, under 2,000 with the footer's prefix
CUT_ORDER = ("bf_news", "bf_markets", "bf_factory", "bf_lab", "bf_research", "bf_paper")


# ---------------------------------------------------------------- the card and its chart

def card_facts(words: list[str], cards: list[Card], n: int = MAX_FACTS) -> list[str]:
    """What the local model may write about: the sections' few words for the summary, then each card's lines and
    rows as "title: lead text" (not the news, a headline's numbers are not ours), at most `n`."""
    out = [w for w in words if w]
    for c in cards:
        for p in c.parts:
            if isinstance(p, Line):
                out.append(short(f"{c.title}: {(p.lead + ' ') if p.lead else ''}{p.text}", 200))
            elif isinstance(p, Rows):
                out += [f"{c.title}: {label} {value}" for label, value, _ in p.rows]
    return out[:n]


def build(now: int, lang: str, engines: list[dict], ledger: list[dict], eur: float | None, prev: dict,
          read=None, summarize=None, raw=None) -> tuple[list[Card], dict]:
    """The briefing as a few short cards (one Telegram post with a bold head per section, one
    Discord embed per section with its own colour) and the autopilots' snapshot for tomorrow: what needs the owner
    today first ("To decide (n)", decisions()), then the morning's head with the summary and the red checks, the
    real-money card (always), research, paper, lab, research factory, markets, news. Another card without fresh
    data is left out and named in the "missing today" footer when its report is there but stale; under
    BRIEF_CHARS the last sections (CUT_ORDER) give way and are named too. `read(name, file)` gives a report (fresh
    ones only), `raw(name, file)` one at any age (tests pass their own). `summarize(facts, template, lang)` may word
    the summary line (lab.ai.local), which falls back to the template itself."""
    read = read or (lambda name, file="latest.json": report(name, now, file))
    raw = raw or (lambda name, file="latest.json": notify.read_json(notify.reports_root() / name / file))
    status = raw("pumpfun_rt", "live_status.json")
    status = status if isinstance(status, dict) else None
    health = notify.read_json(notify.data_root() / "_health" / "system.json")
    research, readiness = read("research"), read("readiness")
    facs = {code: read(folder, file) for code, folder, file in FACTORIES}
    decide = decide_card(decisions(now, lang, status, ledger, engines, research, health, readiness, facs, eur), lang)
    cards: list[tuple[str, Card]] = []
    summary: list[str] = []
    real, words, _ = real_money_card(ledger, status, engines, now, eur, lang)
    cards.append(("bf_real_money", real))
    summary += [words] if words else []
    res, words = research_section(research, now, lang, n=3)
    if res:
        cards.append(("bf_research", Card("🔵", tr("bf_research", lang), None, res)))
    summary += [words] if words else []
    paper, snap, words = paper_section(read("learn"), read("forward"), readiness, prev, now, lang,
                                       read("smallaccount"), read("onchain_longterm"))
    if paper:
        cards.append(("bf_paper", Card("📈", tr("bf_paper", lang), None, paper)))
    summary += [words] if words else []
    lab = lab_section(read("models"), now, lang)
    if lab:
        cards.append(("bf_lab", Card("🧪", tr("bf_lab", lang), None, lab)))
    fac = factory_section(facs, read("pumpfun_rt", "allocator.json"), lang)
    if fac:
        cards.append(("bf_factory", Card("🏭", tr("bf_factory", lang), None, fac)))
    markets = (coins_section(read("trending"), read("listings"), now, lang) + stocks_section(engines, etf_closes(now), lang)
               + pokemon_section(read("pokemon"), lang) + cs2_section(read("cs2"), read("cs2_trends"), now, lang))
    if markets:
        cards.append(("bf_markets", Card("🌍", tr("bf_markets", lang), None, markets)))
    news = news_section(now, lang)
    if news:
        cards.append(("bf_news", Card("📰", tr("bf_news", lang), None, news)))
    head_parts: list = []
    if health:
        red = [str(c.get("name") or "?").removeprefix("job ") for c in health.get("checks") or [] if not c.get("ok")]
        summary.append(notify.health_line(health, now, lang).text.split(":")[0])
        if red:
            head_parts.append(Line(short(", ".join(red), 160), tr("bf_red_lead", lang, n=len(red))))
    title = tr("bf_title", lang, day=notify.day_label(now, lang))
    missing = missing_today(read, raw, now, lang)
    line = " · ".join(summary) or tr("bf_summary", lang)
    if summarize is not None:
        line = summarize(card_facts(summary, [c for _, c in cards]), line, lang)
    head = Card("☀️", title, line, head_parts)
    cut: list[str] = []

    def footer() -> str:
        bits = [tr("bf_missing", lang, names=", ".join(missing))] if missing else []
        bits += [tr("bf_cut", lang, names=", ".join(cut))] if cut else []
        return " · ".join(bits + [tr("bf_footer", lang)])

    def post() -> list[Card]:
        out = [decide, head] + [c for _, c in cards]
        for c in out:
            c.footer = None
        out[-1].footer = footer()
        return out

    for key in CUT_ORDER:
        if len(text_of(post(), lang)) <= BRIEF_CHARS:
            break
        if any(k == key for k, _ in cards):
            cards = [(k, c) for k, c in cards if k != key]
            cut.append(tr(key, lang))
    return post(), snap


def overview_chart(engines: list[dict], ledger: list[dict], now: int, lang: str) -> bytes | None:
    """The autopilots' equity in % since their start (real money and paper alike) and the
    pump.fun real-money P&L of the last 14 days; None without matplotlib or data."""
    ch = notify._charts()
    if ch is None:
        return None
    data = notify.chart_data(notify.merge_states(engines), None, now) or {"autopilots": []}
    pts, run = [], 0.0
    for r in sorted((r for r in ledger if now - r["exit_ms"] <= 14 * DAY_MS), key=lambda r: r["exit_ms"]):
        if not pts:
            pts.append((int(r["exit_ms"]) - 60_000, 0.0))
        run += r["pnl_sol"] or 0.0
        pts.append((int(r["exit_ms"]), run))
    if not data["autopilots"] and not pts:
        return None
    data.update(pumpfun=pts, equity_title=tr("bf_chart_equity", lang), pumpfun_title=tr("bf_chart_pumpfun", lang),
                empty=tr("bf_chart_none", lang))
    path = notify.notify_dir() / "charts" / f"briefing-{now}.png"
    try:
        ch.render_overview(data, path, tr("bf_chart_title", lang), notify.day_label(now, lang), lang)
        return path.read_bytes()
    except Exception as e:  # noqa: BLE001 - the briefing goes without it
        notify.say(f"briefing chart not drawn: {type(e).__name__}: {e}", err=True)
        return None
    finally:
        for p in sorted((notify.notify_dir() / "charts").glob("briefing-*.png"))[:-3]:
            p.unlink(missing_ok=True)


def run(now: int | None = None, force: bool = False, dry_run: bool = False, engines: list[dict] | None = None,
        eur=notify.sol_eur, poster=None, discord_poster=None, chart: bool = True, summarize=None) -> int:
    now = now or notify.clock_ms()
    state_path = notify.data_root() / "notify" / "state.json"
    st = notify.read_json(state_path) or {}
    today = notify.local_time(now).date().isoformat()
    if not force and not due(now, st.get("last_briefing")):
        notify.say("not 9 o'clock in Berlin, or the briefing went out today: nothing (use --force)")
        return 0
    lang = notify.alert_lang()
    engines = engines if engines is not None else notify.engine_states()
    ledger = read_ledger()
    rate = eur() if callable(eur) else eur
    summarize = summarize or local.summarizer(LLM_BUDGET_SEC, "briefing")
    cards, snap = build(now, lang, engines, ledger, rate, st.get("autopilots") or {}, summarize=summarize)
    # With the lab switch "discordBoth" Discord posts the briefing in German and English: the same data, built once
    # more in the other language (once per language, shared by the cards; the sections that come out may differ by
    # what fits, a card past the end stays as it is). Without it, nothing is built twice.
    other: dict[str, list[Card]] = {}

    def remake(i: int, lg: str) -> Card:
        if lg not in other:
            other[lg] = build(now, lg, engines, ledger, rate, st.get("autopilots") or {}, summarize=summarize)[0]
        return other[lg][i] if i < len(other[lg]) else cards[i]

    for i, c in enumerate(cards):
        c.lang, c.remake = lang, (lambda lg, i=i: remake(i, lg))
    image = overview_chart(engines, ledger, now, lang) if chart and not dry_run else None
    res = notify.send("dailyPnl", cards, image=image, now=now, dry_run=dry_run, hold_in_quiet=False,
                      poster=poster, discord="briefing", discord_poster=discord_poster)
    if dry_run or res["reason"] in ("off", "quiet"):
        return 0
    notify.write_json(notify.notify_dir() / "latest.json", {"ts": now, "text": res["text"], "html": res["html"],
                                                            "delivered": res["delivered"], "photo": res["photo"]})
    discord_ok = (res.get("discord") or {}).get("delivered")
    if not res["delivered"] and not discord_ok and res["reason"] != "no destination":
        notify.say(f"briefing not delivered: {res['error']}", err=True)
        return 1
    new = {**st, "last_briefing": today, "last_digest_ms": now}
    if snap:
        new["autopilots"] = snap
    notify.write_json(state_path, new)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    return run(force="--force" in argv, dry_run="--dry-run" in argv)


if __name__ == "__main__":
    sys.exit(main())
