"""The morning briefing: one message at 09:00 Europe/Berlin to Telegram and Discord.

Built only from the files the lab and the engines already write, and the engines'
GET /api/state (read only); no model is asked anything. One card, short sections,
numbers formatted in the messages' language, one overview chart:

  pump.fun Alpha phase   yesterday's real-money trades (Berlin day), P&L in SOL and euro,
                         the total, the wallet and the stake (live/pumpfun_rt/ledger.csv,
                         reports/pumpfun_rt/live_status.json)
  real money             every running real-money autopilot (Kraken, Alpaca; mode live)
  paper and autopilots   the digest's table of autopilots (reports/learn), the forward
                         test's books by status (reports/forward), real money readiness
  lab                    the model zoo (reports/models) and the study reports that are new
  Pokemon, CS2, coins,   reports/pokemon, reports/cs2 and cs2_trends, reports/trending and
  stocks and ETFs, news  listings, the engines' US shares and the ETF closes, the news
                         collector's newest headlines (<data>/ai/news)

A section whose data is missing or older than two days is left out. The briefing
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
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import i18n, notify
from .notify import Card, Line, Links, Rows, _num, nodash, short, tr

HOUR = 9
DAY_MS = notify.DAY_MS
STALE_MS = 2 * DAY_MS
# Reports that are not studies: the jobs of every day, shown in their own sections or nowhere.
NOT_STUDIES = {"learn", "forward", "notify", "trending", "listings", "models", "pokemon", "cs2", "cs2_trends",
               "cs2_weekly", "readiness", "pumpfun", "pumpfun_rt", "pumpfun_activity", "polymarket", "agent",
               "exit_shadow", "factory", "paper_review", "studies", "ai", "ai_brief", "ai_news", "ai_analyst",
               "costs"}
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


def pumpfun_section(ledger: list[dict], status: dict | None, now: int, eur: float | None, lang: str) -> tuple[list, str | None]:
    """(parts, a few words for the summary). Yesterday is the Berlin day before today."""
    mid = local_midnight(now)
    day = [r for r in ledger if mid - DAY_MS <= r["exit_ms"] < mid]
    recent = any(now - r["exit_ms"] <= STALE_MS for r in ledger)
    if status is None and not recent:
        return [], None
    rows = []
    pnl = sum(r["pnl_sol"] or 0.0 for r in day)
    wins = sum(1 for r in day if (r["pnl_sol"] or 0) > 0)
    rows.append((tr("bf_yesterday", lang), tr("prl_trades_won", lang, n=len(day), wins=wins)))
    rows.append((tr("prl_row_pnl", lang), _sol(pnl, eur, lang, True)))
    if day:
        best = max(day, key=lambda r: r["ret"] if r["ret"] is not None else -9)
        worst = min(day, key=lambda r: r["ret"] if r["ret"] is not None else 9)
        if best["ret"] is not None and len(day) > 1:
            rows.append((tr("bf_best_worst", lang), f"{i18n.frac_pct(best['ret'], 1, lang)} / "
                                                    f"{i18n.frac_pct(worst['ret'] or 0.0, 1, lang)}"))
    st = status or {}
    if _num(st.get("pnl_total_sol")) is not None:
        rows.append((tr("prl_row_total", lang), _sol(st["pnl_total_sol"], eur, lang, True)))
    if _num(st.get("balance_sol")) is not None:
        rows.append((tr("prl_row_wallet", lang), _sol(st["balance_sol"], eur, lang)))
    stake = _num((st.get("stake") or {}).get("sol")) or _num((st.get("limits") or {}).get("max_trade_sol"))
    if stake:
        rows.append((tr("prl_row_stake", lang), _sol(stake, eur, lang)))
    parts: list = [Rows(rows, tr("bf_pumpfun", lang))]
    if status is not None and st.get("running") and not st.get("on"):
        why = "; ".join(str(w) for w in (st.get("gate") or [])[:2]) or str(st.get("refusing") or "?")
        parts.append(Line(short(nodash(why), 160), tr("bf_paused", lang)))
    elif status is not None and not st.get("running"):
        parts.append(Line(tr("bf_not_running", lang)))
    words = tr("bf_sum_pumpfun", lang, pnl=i18n.sol(pnl, 4, lang, True)) if day else None
    return parts, words


def real_money_section(rows: list[dict], lang: str) -> list:
    """Every running real-money autopilot (mode live) of every engine that answered."""
    out = []
    for r in rows:
        for a in (r.get("state") or {}).get("autopilots") or []:
            cfg = a.get("config") or {}
            if cfg.get("mode") != "live" or a.get("state") not in ("running", "paused"):
                continue
            eq, start = _num(a.get("equity")), _num(a.get("startCapital"))
            val = notify.money(eq, 2, lang) if eq is not None else ("k. A." if lang == "de" else "n/a")
            if eq is not None and start:
                val += f" · {notify.signed_pct((eq / start - 1) * 100, 1, lang)}"
            venue = str(cfg.get("venue") or "").capitalize()
            out.append((notify.short_name(cfg.get("name"), 18) + (f" ({venue})" if venue else ""), val))
    return [Rows(out, tr("bf_real", lang))] if out else []


def paper_section(learn: dict | None, forward: dict | None, readiness: dict | None, prev: dict, now: int,
                  lang: str) -> tuple[list, dict, str | None]:
    """The digest's table of autopilots, the forward books by status and the readiness line;
    the snapshot for tomorrow; a few words for the summary."""
    parts: list = []
    snap: dict = {}
    words = None
    if learn is not None:
        table, snap, today, n = notify.autopilot_parts(learn, prev, now, lang)
        if table:
            parts.append(Line(tr("bf_paper_lead", lang, n=n), tr("bf_paper", lang)))
            parts += table
            if today:
                words = tr("bf_sum_paper", lang, money=notify.signed_money(sum(today), lang=lang))
    if forward is not None:
        books = [b for b in forward.get("books") or [] if b.get("name")]
        if books:
            counts: dict[str, int] = {}
            for b in books:
                counts[str(b.get("status") or "unknown")] = counts.get(str(b.get("status") or "unknown"), 0) + 1
            words_fw = ", ".join(f"{n} {tr('fw_' + k, lang) if 'fw_' + k in i18n.CATALOG['en'] else k.replace('_', ' ')}"
                                 for k, n in sorted(counts.items(), key=lambda kv: -kv[1]))
            parts.append(Line(tr("bf_books", lang, n=len(books), counts=words_fw), tr("forward_test", lang)))
    if readiness is not None:
        lead = (notify.READINESS_TEXT_DE if lang == "de" else notify.READINESS_TEXT)["lead"]
        parts.append(Line(short(nodash(notify.readiness_text(readiness, now, lang)), 220), lead))
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
    return [Line("", tr("bf_lab", lang))] + lines if lines else []


def pokemon_section(rep: dict | None, lang: str) -> list:
    if rep is None:
        return []
    rows = []
    col = rep.get("collection") or {}
    eq, ret = _num(col.get("equity")), _num(col.get("returnPct"))
    if eq is not None:
        rows.append((tr("bf_collection", lang), notify.money(eq, 2, lang)
                     + (f" · {notify.signed_pct(ret, 1, lang)}" if ret is not None else "")))
    cheap = [i for i in rep.get("items") or [] if isinstance(i, dict) and "fair" in str(i.get("value") or "")]
    if cheap:
        rows.append((tr("bf_cheap", lang), str(len(cheap))))
        rows.append((tr("bf_top", lang), short(nodash(str(cheap[0].get("label"))), 30)))
    return [Rows(rows, tr("bf_pokemon", lang))] if rows else []


def cs2_section(rep: dict | None, trends: dict | None, now: int, lang: str) -> list:
    rows = []
    if rep is not None:
        pf = rep.get("portfolio") or {}
        eq, ret = _num(pf.get("equity")), _num(pf.get("returnPct"))
        if eq is not None:
            rows.append((tr("bf_portfolio", lang), i18n.eur(eq, 0, lang)
                         + (f" · {notify.signed_pct(ret, 1, lang)}" if ret is not None else "")))
        alerts = [a for a in rep.get("alerts") or [] if isinstance(a, dict) and now - (_num(a.get("tsMs")) or 0) <= DAY_MS]
        rows.append((tr("bf_hints_24h", lang), str(len(alerts))))
        if alerts:
            rows.append((tr("bf_top", lang), short(nodash(str(alerts[0].get("name"))), 30)))
    if trends is not None:
        liquid = _num((trends.get("summary") or {}).get("liquid"))
        if liquid is not None:
            rows.append(("Steam", tr("bf_liquid", lang, n=i18n.num(liquid, 0, lang))))
    return [Rows(rows, tr("bf_cs2", lang))] if rows else []


def coins_section(trending: dict | None, listings: dict | None, now: int, lang: str) -> list:
    rows = []
    if trending is not None:
        al = trending.get("alpaca") or {}
        for c in ("BTC", "ETH", "SOL"):
            ch = _num((al.get(c) or {}).get("change"))
            if ch is not None:
                rows.append((f"{c} 24 h", i18n.frac_pct(ch, 1, lang)))
        g = (trending.get("gainers") or [None])[0]
        if isinstance(g, dict) and g.get("coin") and _num(g.get("change")) is not None:
            rows.append((tr("bf_gainer", lang), f"{g['coin']} {i18n.frac_pct(g['change'], 0, lang)}"))
    parts: list = [Rows(rows, tr("bf_coins", lang))] if rows else []
    if listings is not None:
        new = [i.get("label") for i in listings.get("items") or []
               if isinstance(i, dict) and now - (_num(i.get("atMs")) or 0) <= DAY_MS and i.get("label")]
        if new:
            if not parts:
                parts.append(Line("", tr("bf_coins", lang)))
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
    return [Rows(out, tr("bf_stocks", lang))] if out else []


def news_section(now: int, lang: str, root: Path | None = None, n: int = 3) -> list:
    """The newest headlines of the news collector (today's and yesterday's files, UTC), those
    that name a coin first; each a link."""
    root = root or notify.data_root() / "ai" / "news"
    items = []
    for k in (0, 1):
        day = datetime.fromtimestamp((now - k * DAY_MS) / 1000, timezone.utc).strftime("%Y-%m-%d")
        try:
            text = (root / f"{day}.jsonl").read_text(encoding="utf-8")
        except OSError:
            continue
        for line in text.splitlines():
            try:
                h = json.loads(line)
            except ValueError:
                continue
            at = (_num(h.get("published_us")) or 0) / 1000 if isinstance(h, dict) else 0
            if isinstance(h, dict) and h.get("title") and 0 <= now - at <= STALE_MS:
                items.append((bool(h.get("coins")), at, h))
    if not items:
        return []
    items.sort(key=lambda x: (x[0], x[1]), reverse=True)
    seen, out = set(), []
    for _, _, h in items:
        title = short(nodash(str(h["title"])), 90)
        if title in seen:
            continue
        seen.add(title)
        out.append(Links([(title, h.get("link"))], "•"))
        if len(out) == n:
            break
    return [Line("", tr("bf_news", lang))] + out


# ---------------------------------------------------------------- the card and its chart

def build(now: int, lang: str, engines: list[dict], ledger: list[dict], eur: float | None, prev: dict,
          read=None) -> tuple[Card, dict]:
    """The briefing card and the autopilots' snapshot for tomorrow. `read(name, file)` gives
    a report (fresh ones only; tests pass their own)."""
    read = read or (lambda name, file="latest.json": report(name, now, file))
    status = fresh(read("pumpfun_rt", "live_status.json"), now)
    learn = read("learn")
    parts: list = []
    summary: list[str] = []
    pf, words = pumpfun_section(ledger, status, now, eur, lang)
    parts += pf
    if words:
        summary.append(words)
    parts += real_money_section(engines, lang)
    paper, snap, words = paper_section(learn, read("forward"), read("readiness"), prev, now, lang)
    parts += paper
    if words:
        summary.append(words)
    parts += lab_section(read("models"), now, lang)
    parts += pokemon_section(read("pokemon"), lang)
    parts += cs2_section(read("cs2"), read("cs2_trends"), now, lang)
    parts += coins_section(read("trending"), read("listings"), now, lang)
    parts += stocks_section(engines, etf_closes(now), lang)
    parts += news_section(now, lang)
    health = notify.read_json(notify.data_root() / "_health" / "system.json")
    if health:
        hl = notify.health_line(health, now, lang)
        parts.append(hl)
        summary.append(hl.text.split(":")[0])
    title = tr("bf_title", lang, day=notify.day_label(now, lang))
    if not parts:
        return Card("☀️", title, tr("bf_nothing", lang)), snap
    return Card("☀️", title, " · ".join(summary) or tr("bf_summary", lang), parts,
                footer=tr("bf_footer", lang)), snap


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
        eur=notify.sol_eur, poster=None, discord_poster=None, chart: bool = True) -> int:
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
    card, snap = build(now, lang, engines, ledger, rate, st.get("autopilots") or {})
    # Discord posts the briefing in German and English: the same data, built once more in the other language.
    card.lang, card.remake = lang, lambda lg: build(now, lg, engines, ledger, rate, st.get("autopilots") or {})[0]
    image = overview_chart(engines, ledger, now, lang) if chart and not dry_run else None
    res = notify.send("dailyPnl", [card], image=image, now=now, dry_run=dry_run, hold_in_quiet=False,
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
