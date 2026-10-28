"""W1: one weekly page of what matters (results/weekly_page_w1_prereg.md), Sunday 18:00 UTC.

The owner's goal on top (180 EUR net profit a month): how far the live bot and the paper books are from it this
week, and per candidate on the ladder the capital it would need at its paper return since start. Then what moved on
the ladder, the books' week, paper minus live, the lanes' results, what is red and since when, disk and data, the
registry's count and noise bar. German, plain, at most about 40 lines; every line names the file it comes from, a
missing report is said as missing ("fehlt").

  reports/ladder/latest.json            steps, the registry's count and noise bar (else metrics.trial_pool())
  reports/pumpfun_rt/realistic.json     the calibration line, P2's gap, R2's and P3's books, sol_eur
  reports/pumpfun_rt/live_status.json   the live bot's total P&L (live_trades.json: its newest closed trades)
  reports/paper_review/latest.json      paper against backtest
  lab.ops.paper_books                   every paper book's wallet
  reports/lanes/*.json                  the lanes' tasks closed in the week
  _health/jobs.json                     the red jobs and since when
  _ops/disk/latest.json                 disk and data growth

No new number: the reports' numbers and the pre-registered arithmetic (a week against the page's own snapshot of
the week before, reports/weekly/<date>.json; times 30/7 for a month; capital = 180 EUR over the monthly return). No
trial. Reads only and writes nothing but reports/weekly/; never arms, changes or sends anything but the page.

  python -m lab.ops.weekly             write the page and post the short version (category "studies")
  python -m lab.ops.weekly --print     print the page, write and post nothing
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from . import i18n, notify, paper_books

GOAL_EUR = 180.0                # the owner's subscription, net profit a month
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS
MONTH_DAYS = 30.0
MAX_LINES = 40
CAPITAL_ROWS = 5                # candidates with a capital line, the cheapest first; the rest counted
LANE_TITLES = 6                 # titles of the week's lanes on the page, the rest counted
STATE_DE = {"failed": "fehlgeschlagen", "late": "überfällig", "never": "nie gelaufen"}
VERDICT_DE = {"not yet": "noch nicht", "calibrated": "kalibriert", "not calibrated": "nicht kalibriert"}
STEP_DE = {0: "keine", 1: "Idee", 2: "getestet", 3: "Schatten", 4: "Lockbox", 5: "Ausführung", 6: "größer"}

LADDER = "reports/ladder/latest.json"
REALISTIC = "reports/pumpfun_rt/realistic.json"
LIVE_STATUS = "reports/pumpfun_rt/live_status.json"
LIVE_TRADES = "reports/pumpfun_rt/live_trades.json"
REVIEW = "reports/paper_review/latest.json"
JOBS = "_health/jobs.json"
DISK = "_ops/disk/latest.json"
PAPER = "reports/{pumpfun_rt/realistic,smallaccount/latest,onchain_longterm/latest,forward/latest}.json"  # paper_books


def _n(v) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def de(v: float, dp: int = 2, sign: bool = False) -> str:
    return i18n.num(v, dp, "de", sign)


def eur(v: float, sign: bool = False) -> str:
    return i18n.eur(v, 2, "de", sign)


def pct(frac: float) -> str:
    return i18n.frac_pct(frac, 1, "de")


def day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _iso_ms(s) -> int | None:
    try:
        return int(datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return None


def src(*files: str) -> str:
    return " (" + ", ".join(f"`{f}`" for f in files) + ")"


def missing(what: str, f: str) -> str:
    return f"{what}: fehlt{src(f)}"


def previous(root: Path, today: str) -> dict | None:
    """The newest snapshot of an earlier page (reports/weekly/<date>.json), None on the first page."""
    d = root / "reports" / "weekly"
    for p in sorted(d.glob("????-??-??.json"), reverse=True) if d.is_dir() else []:
        if p.stem < today:
            s = notify.read_json(p)
            if isinstance(s, dict):
                return s | {"file": f"reports/weekly/{p.name}"}
    return None


# ---------------------------------------------------------------- the books

def book_rows(root: Path, now: int, sol_eur: float | None) -> list[dict]:
    """paper_books.books() with each book's start value and return since start (r, a fraction), its days, its value
    in EUR (SOL at sol_eur; USDC and % books none)."""
    reps = root / "reports"
    real = notify.read_json(reps / "pumpfun_rt/realistic.json") or {}
    small = {b.get("book"): b for b in (real.get("small") or []) if isinstance(b, dict)}
    sa = (notify.read_json(reps / "smallaccount/latest.json") or {}).get("books") or {}
    lt = notify.read_json(reps / "onchain_longterm/latest.json") or {}
    out = []
    for b in paper_books.books(root):
        v, cur, start = b["value"], b["currency"], None
        if cur == "SOL" and b.get("p3"):
            start = _n(b["p3"].get("start_sol"))
        elif cur == "SOL" and b["name"] in small and v is not None and _n(small[b["name"]].get("pnl_sol")) is not None:
            start = v - small[b["name"]]["pnl_sol"]
        elif cur == "EUR" and isinstance(sa.get(b["name"]), dict):
            start = _n(sa[b["name"]].get("capital_eur"))
        elif cur == "USDC":
            start = _n(lt.get("start_usdc"))
        if v is None:
            r = None
        elif cur == "% since start":
            r = v / 100
        else:
            r = v / start - 1 if start else None
        t0 = _iso_ms(b["start"]) if b.get("start") else None
        rate = {"EUR": 1.0, "SOL": sol_eur}.get(cur)
        out.append(b | {"r": r, "days": (now - t0) / DAY_MS if t0 else None,
                        "eur": v * rate if v is not None and rate else None,
                        "pnl_eur": (v - start) * rate if v is not None and start and rate else None})
    return out


def monthly(b: dict) -> float | None:
    """A book's net return a month: since its start times 30 over its days; none under a day."""
    return b["r"] * MONTH_DAYS / b["days"] if b.get("r") is not None and (b.get("days") or 0) >= 1 else None


# ---------------------------------------------------------------- the page

def build(root: Path, now: int) -> dict:
    """{"date", "lines" (the page, markdown), "short" (the Telegram lines), "snapshot"} from what exists."""
    today = day(now)
    prev = previous(root, today)
    reps = root / "reports"
    read = lambda rel: notify.read_json(root / rel)  # noqa: E731
    lad, real, live, trades = read(LADDER), read(REALISTIC), read(LIVE_STATUS), read(LIVE_TRADES)
    real = real if isinstance(real, dict) else None
    sol_eur = _n((real or {}).get("sol_eur"))
    books = book_rows(root, now, sol_eur)
    snap = {"date": today, "now_ms": now, "books": {}, "ladder": {}, "failing": [], "live_pnl_sol": None}
    for b in books:
        snap["books"][b["name"]] = [b["value"], b["currency"]]
    lines = [f"# Pythia, Woche bis {today}", ""]
    if prev:
        lines.append(f"Vorwoche: {prev.get('date')}{src(prev['file'])}")
    else:
        lines.append("Vorwoche: kein Stand (erste Seite), die Woche ist nur messbar, wo ein Bericht sie selbst nennt.")
    short: list[str] = []

    # ---- the goal
    lines += ["", f"## Ziel: {de(GOAL_EUR, 0)} EUR Nettogewinn im Monat"]
    if not isinstance(live, dict):
        lines.append(missing("Live (pump.fun-Bot)", LIVE_STATUS))
        short.append("Live: fehlt")
    else:
        tot = _n(live.get("pnl_total_sol"))
        snap["live_pnl_sol"] = tot
        ptot = _n((prev or {}).get("live_pnl_sol"))
        how, files = None, [LIVE_STATUS]
        if tot is not None and ptot is not None:
            week, how = tot - ptot, f"Gesamt-P&L gegen {prev['date']}"
        else:
            rows = [t for t in (trades or {}).get("trades") or [] if isinstance(t, dict)]
            got = [t for t in rows if (_n(t.get("exit_ms")) or 0) > now - WEEK_MS and _n(t.get("pnl_sol")) is not None]
            week = sum(t["pnl_sol"] for t in got) if rows else None
            files = [LIVE_TRADES]
            if rows:
                how = f"{len(got)} Trades in der Woche"
                if len(got) == len(rows):
                    how += f", der Bericht hält nur die letzten {len(rows)}"
        if week is None:
            lines.append(missing("Live (pump.fun-Bot), Woche", LIVE_TRADES))
            short.append("Live: Woche fehlt")
        elif sol_eur is None:
            lines.append(f"Live (pump.fun-Bot): Woche {i18n.sol(week, 4, 'de', True)} ({how}), EUR-Kurs fehlt"
                         + src(*files, REALISTIC))
            short.append(f"Live: Woche {i18n.sol(week, 4, 'de', True)}")
        else:
            m = week * sol_eur * MONTH_DAYS / 7
            lines.append(f"Live (pump.fun-Bot): Woche {i18n.sol(week, 4, 'de', True)} = {eur(week * sol_eur, True)} "
                         f"({how}), auf 30 Tage {eur(m, True)}, zum Ziel fehlen {eur(max(GOAL_EUR - m, 0))}"
                         + src(*files, REALISTIC))
            short.append(f"Live: Woche {eur(week * sol_eur, True)}, Monat {eur(m, True)}, fehlen {eur(max(GOAL_EUR - m, 0))}")
    pb = {k: v for k, v in ((prev or {}).get("books") or {}).items() if isinstance(v, list) and len(v) == 2}
    priced = [b for b in books if b["eur"] is not None]
    if not priced:
        lines.append("Papier: kein Buch in EUR oder SOL" + src(REALISTIC, "reports/smallaccount/latest.json"))
    elif prev:
        rate = {"EUR": 1.0, "SOL": sol_eur}
        both = [b for b in priced if b["name"] in pb and pb[b["name"]][1] == b["currency"] and _n(pb[b["name"]][0]) is not None]
        week = sum((b["value"] - pb[b["name"]][0]) * rate[b["currency"]] for b in both)
        m = week * MONTH_DAYS / 7
        lines.append(f"Papier: Woche {eur(week, True)} über {len(both)} Bücher in EUR und SOL, auf 30 Tage "
                     f"{eur(m, True)}, zum Ziel fehlen {eur(max(GOAL_EUR - m, 0))}" + src(prev["file"], PAPER))
        short.append(f"Papier: Woche {eur(week, True)}, Monat {eur(m, True)}")
    else:
        got = [b for b in priced if b["pnl_eur"] is not None and (b.get("days") or 0) >= 1]
        m = sum(b["pnl_eur"] * MONTH_DAYS / b["days"] for b in got)
        lines.append(f"Papier: {len(got)} Bücher in EUR und SOL, seit Start auf 30 Tage {eur(m, True)}, zum Ziel "
                     f"fehlen {eur(max(GOAL_EUR - m, 0))} (keine Vorwoche)" + src(PAPER))
        short.append(f"Papier: Monat seit Start {eur(m, True)}")

    # capital per ladder candidate at its paper return
    rows = (lad or {}).get("rows") if isinstance(lad, dict) else None
    if rows is None:
        lines.append(missing("Kapital je Kandidat", LADDER))
    else:
        by = {b["name"]: b for b in books}
        need, none, unknown = [], [], 0
        for r in rows:
            b = by.get(r.get("name")) if r.get("kind") == "book" else None
            m = monthly(b) if b else None
            if m is None:
                unknown += 1
            elif m <= 0:
                none.append(r["name"])
            else:
                need.append((GOAL_EUR / m, r["name"], m, b))
        for cap, name, m, b in sorted(need)[:CAPITAL_ROWS]:
            lines.append(f"Kapital für {de(GOAL_EUR, 0)} EUR im Monat, {name}: {eur(cap)} (Papier, {pct(m)} im Monat, "
                         f"{de(b['days'], 0)} Tage){src('reports/' + b['report'])}")
        if len(need) > CAPITAL_ROWS:
            lines.append(f"Kapital: {len(need) - CAPITAL_ROWS} weitere Kandidaten mit Rendite über 0" + src(PAPER))
        if none:
            lines.append(f"Kapital: keins bei {len(none)} Kandidaten (Papierrendite nicht über 0): "
                         + ", ".join(none[:8]) + (", ..." if len(none) > 8 else "") + src(PAPER))
        if unknown:
            lines.append(f"Kapital: {unknown} Kandidaten ohne gemessene Rendite (kein Buch oder unter einem Tag)"
                         + src(LADDER))

    # ---- the ladder
    lines += ["", "## Leiter"]
    if rows is None:
        lines.append(missing("Leiter", LADDER))
        short.append("Leiter: fehlt")
    else:
        old = (prev or {}).get("ladder") or {}
        up, down, new = [], [], 0
        for r in rows:
            k, st = str(r.get("id") or r.get("name")), int(_n(r.get("step")) or 0)
            snap["ladder"][k] = st
            if k not in old:
                new += 1
            elif st > old[k]:
                up.append(f"{r.get('short') or r.get('name')} {old[k]} {STEP_DE.get(old[k], '')} -> {st} {STEP_DE.get(st, '')}")
            elif st < old[k]:
                down.append(f"{r.get('short') or r.get('name')} {old[k]} -> {st} ({r.get('next_de') or r.get('next') or ''})")
        top = max((int(_n(r.get("step")) or 0) for r in rows), default=0)
        lines.append(f"{len(rows)} Kandidaten, höchste Stufe {top} ({STEP_DE.get(top, '')}), "
                     f"{sum(1 for r in rows if r.get('step') == top)} dort{src(LADDER)}")
        if not prev:
            lines.append("Bewegung: keine Vorwoche, nicht messbar")
        else:
            lines.append("Nach oben: " + ("; ".join(up) if up else "nichts") + src(LADDER, prev["file"]))
            lines.append("Zurück (gescheitert): " + ("; ".join(down) if down else "nichts") + src(LADDER, prev["file"]))
            if new:
                lines.append(f"Neu auf der Leiter: {new}{src(LADDER)}")
        short.append(f"Leiter: höchste Stufe {top}, nach oben {len(up)}, zurück {len(down)}" if prev
                     else f"Leiter: höchste Stufe {top}")

    # ---- the books' week
    lines += ["", "## Bücher"]
    if not books:
        lines.append("Paper-Bücher: kein Bericht" + src(REALISTIC, "reports/smallaccount/latest.json"))
    fwd = [b for b in books if b["currency"] == "% since start" and b["value"] is not None]
    for b in books:
        if b in fwd or b["currency"] == "% since start":
            continue
        cur, v = b["currency"], b["value"]
        if v is None:
            lines.append(f"{b['name']} ({b['study']}): Stand fehlt{src('reports/' + b['report'])}")
            continue
        dp = 4 if cur == "SOL" else 2
        txt = f"{b['name']} ({b['study']}): {de(v, dp)} {cur}"
        if b["eur"] is not None and cur != "EUR":
            txt += f" = {eur(b['eur'])}"
        p = pb.get(b["name"])
        if p and p[1] == cur and _n(p[0]) is not None:
            txt += f", Woche {de(v - p[0], dp, True)} {cur}"
        elif b["r"] is not None and b.get("days") is not None:
            txt += f", seit Start {pct(b['r'])} in {de(b['days'], 0)} Tagen"
        if b.get("p3"):
            t = b["p3"]
            txt += f", {int(_n(t.get('trades')) or 0)} Trades, Tor: " + ("besteht" if t.get("pass") else "nicht")
        lines.append(txt + src(b["report"]))
    if real is not None and not real.get("ten"):
        lines.append("P3 (10-EUR-Bücher): noch keine Zahlen" + src(REALISTIC))
    elif real is None:
        lines.append(missing("P3 (10-EUR-Bücher)", REALISTIC))
    if fwd:
        best, worst = max(fwd, key=lambda b: b["value"]), min(fwd, key=lambda b: b["value"])
        lines.append(f"Forward: {len(fwd)} Bücher, bestes {best['name']} {i18n.signed_pct(best['value'], 1, 'de')}, "
                     f"schlechtestes {worst['name']} {i18n.signed_pct(worst['value'], 1, 'de')} seit Start"
                     + src("reports/forward/latest.json"))
    rv = read(REVIEW)
    if not isinstance(rv, dict):
        lines.append(missing("Papier gegen Backtest", REVIEW))
    else:
        parts = [f"{b['book']} {i18n.signed_pct(_n(b.get('paper_return_pct')), 1, 'de')} gegen "
                 f"{i18n.signed_pct(_n(b.get('backtest_return_pct')), 1, 'de')} nach {int(_n(b.get('days')) or 0)} Tagen"
                 for b in rv.get("books") or [] if isinstance(b, dict) and b.get("book")]
        lines.append("Papier gegen Backtest: " + ("; ".join(parts) or "keine Bücher") + src(REVIEW))

    # ---- paper minus live
    lines += ["", "## Papier minus live"]
    cal = (real or {}).get("calibration")
    if not isinstance(cal, dict):
        lines.append(missing("Kalibrierung (pump.fun)", REALISTIC))
    else:
        dp_, dm = _n(cal.get("d_pts")), _n(cal.get("d_pts_mean"))
        days_ = _n(cal.get("days"))
        if days_ is None and _n(cal.get("from_ms")) and _n(cal.get("to_ms")):
            days_ = (cal["to_ms"] - cal["from_ms"]) / DAY_MS
        word = VERDICT_DE.get(str(cal.get("verdict") or ""), str(cal.get("verdict") or "k. A."))
        lines.append(f"Kalibrierung {cal.get('rule')}: {int(_n(cal.get('n')) or 0)} Paare aus {int(_n(cal.get('live')) or 0)} "
                     f"live und {int(_n(cal.get('paper')) or 0)} Papier"
                     + (f" in {de(days_, 1)} Tagen" if days_ is not None else "")
                     + (f", Median {de(dp_, 1, True)} Punkte je Trade" if dp_ is not None else "")
                     + (f", Mittel {de(dm, 1, True)} Punkte" if dm is not None else "")
                     + (f": {word}" if cal.get("verdict") else "") + src(REALISTIC))
    sel = (real or {}).get("selection")
    if isinstance(sel, dict) and _n(sel.get("pts")) is not None:
        lines.append(f"P2 alle Live-Signale: {de(sel['pts'], 1, True)} Punkte je Trade, Tor unter "
                     f"{de(_n(sel.get('gate_pts')) or 2, 0)}: " + ("besteht" if sel.get("pass") else "nicht")
                     + src(REALISTIC))
        short.append(f"Papier minus live (P2): {de(sel['pts'], 1, True)} Punkte")
    elif real is not None:
        lines.append("P2 alle Live-Signale: nicht gemessen" + src(REALISTIC))

    # ---- the lanes
    lines += ["", "## Aufgaben (Lanes)"]
    ld = reps / "lanes"
    week = []
    for p in sorted(ld.glob("*.json")) if ld.is_dir() else []:
        r = notify.read_json(p)
        if isinstance(r, dict) and r.get("name") and r.get("status") in ("done", "stopped") \
                and (_n(r.get("at")) or 0) * 1000 > now - WEEK_MS:
            week.append(r)
    if not ld.is_dir():
        lines.append(missing("Lanes", "reports/lanes/"))
    else:
        done = [r for r in week if r["status"] == "done"]
        stopped = [r for r in week if r["status"] == "stopped"]
        lines.append(f"Woche: {len(done)} fertig, {len(stopped)} gestoppt" + src("reports/lanes/*.json"))
        if done:
            lines.append("Fertig: " + "; ".join(str(r.get("title") or r["name"]) for r in done[-LANE_TITLES:])
                         + (f" und {len(done) - LANE_TITLES} weitere" if len(done) > LANE_TITLES else ""))
        if stopped:
            lines.append("Gestoppt: " + "; ".join(f"{r.get('title') or r['name']}" for r in stopped[-LANE_TITLES:]))
        short.append(f"Lanes: {len(done)} fertig, {len(stopped)} gestoppt")

    # ---- red jobs
    lines += ["", "## Rot"]
    jd = read(JOBS)
    if not isinstance(jd, dict):
        lines.append(missing("Jobs", JOBS))
        short.append("Jobs: fehlt")
    else:
        red = [j for j in jd.get("jobs") or [] if isinstance(j, dict) and j.get("ok") is False]
        snap["failing"] = [j.get("name") for j in red]
        for j in red:
            since = _iso_ms(j.get("lastOk")) if j.get("lastOk") else None
            how = (f"rot seit dem letzten Erfolg {str(j['lastOk'])[:16].replace('T', ' ')} UTC "
                   f"({de((now - since) / DAY_MS, 1)} Tage)" if since else "noch nie erfolgreich")
            n = int(_n(j.get("consecutiveFailures")) or 0)
            lines.append(f"{j.get('name')}: {STATE_DE.get(j.get('state'), j.get('state'))}, {how}"
                         + (f", {n} Fehlschläge in Folge" if n else "") + src(JOBS))
        if not red:
            lines.append("Alle Jobs grün" + src(JOBS))
        back = [n for n in (prev or {}).get("failing") or [] if n not in snap["failing"]]
        if back:
            lines.append("Wieder grün seit der Vorwoche: " + ", ".join(back) + src(JOBS, prev["file"]))
        short.append(f"Rot: {len(red)} Jobs" + (f" ({', '.join(snap['failing'][:4])})" if red else ""))

    # ---- disk, data, the registry
    lines += ["", "## Platte, Daten, Register"]
    dk = read(DISK)
    if not isinstance(dk, dict):
        lines.append(missing("Platte", DISK))
    else:
        left = _n(dk.get("daysLeft"))
        lines.append(f"Platte: {de(_n(dk.get('freeGb')) or 0, 1)} von {de(_n(dk.get('totalGb')) or 0, 1)} GB frei, "
                     f"Daten {de(_n(dk.get('trackedGb')) or 0, 1)} GB, wachsen {de(_n(dk.get('growthGbPerDay')) or 0, 2)} "
                     f"GB am Tag, " + (f"voll in {de(left, 0)} Tagen" if left is not None else "kein Volllaufen absehbar")
                     + src(DISK))
        short.append(f"Platte: {de(_n(dk.get('freeGb')) or 0, 0)} GB frei")
    reg = (lad or {}).get("registry") if isinstance(lad, dict) else None
    f = LADDER
    if not isinstance(reg, dict) or _n(reg.get("n_trials")) is None:
        try:
            from .. import metrics
            reg, f = metrics.trial_pool(), "trials/registry.jsonl"
        except Exception:                                    # noqa: BLE001 - the page goes out without it
            reg = None
    if reg is None:
        lines.append(missing("Register", "trials/registry.jsonl"))
    else:
        lines.append(f"Register: {de(reg['n_trials'], 0)} Versuche, Rauschbalken (bester Sharpe aus reinem Rauschen) "
                     f"{de(_n(reg.get('sr0_annual')) or 0, 2)} im Jahr" + src(f))
    return {"date": today, "lines": lines, "short": short, "snapshot": snap}


def card(page: dict) -> notify.Card:
    return notify.Card("🗓", f"Pythia, Woche bis {page['date']}",
                       f"Ziel {de(GOAL_EUR, 0)} EUR Nettogewinn im Monat",
                       [notify.Line(s) for s in page["short"]], "reports/weekly/latest.md")


def run(root: Path | None = None, now: int | None = None, write: bool = True, poster=None) -> dict:
    root = Path(root) if root is not None else notify.data_root()
    now = now or int(datetime.now(timezone.utc).timestamp() * 1000)
    page = build(root, now)
    text = "\n".join(page["lines"]) + "\n"
    if not write:
        print(text)
        return page
    d = root / "reports" / "weekly"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{page['date']}.md").write_text(text, encoding="utf-8")
    (d / "latest.md").write_text(text, encoding="utf-8")
    notify.write_json(d / f"{page['date']}.json", page["snapshot"])
    page["sent"] = notify.send("studies", [card(page)], now=now, poster=poster)
    return page


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    run(write="--print" not in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
