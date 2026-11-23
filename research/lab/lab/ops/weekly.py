"""W1: one weekly page of what matters (results/weekly_page_w1_prereg.md), Sunday 18:00 UTC.

The owner's goal on top (180 EUR net profit a month): how far the live bot and the paper books are from it this
week, and per candidate on the ladder the capital it would need (W2, results/weekly_capital_line_prereg.md: 30 days of
record, the lower end of the 95 % band, pump.fun per trade less P2's gap at the live stake cap, a fill gap taken
off). Then what moved on
the ladder, the books' week, paper minus live, the lanes' results, what is red and since when, disk and data, the
registry's count and noise bar. German, plain, at most about 40 lines; every line names the file it comes from, a
missing report is said as missing ("fehlt").

  reports/ladder/latest.json            steps, the one trial total (R5 plus F3, else ladder.register_total), A4's
                                        promotions (promotions/live_ready.json)
  reports/pumpfun_rt/realistic.json     the calibration line, P2's gap, R2's and P3's books, sol_eur
  reports/pumpfun_rt/live_status.json   the live bot's total P&L (live_trades.json: its newest closed trades)
  reports/paper_review/latest.json      paper against backtest
  lab.ops.paper_books                   every paper book's wallet
  reports/lanes/*.json                  the lanes' tasks closed in the week
  _health/jobs.json                     the red jobs and since when
  reports/leak/latest.json              T1's red leaks, each a red line in the health check
  _ops/disk/latest.json                 disk and data growth

No new number: the reports' numbers and the pre-registered arithmetic (a week against the page's own snapshot of
the week before, reports/weekly/<date>.json; times 30/7 for a month; W2's capital line). No trial. Reads only and writes nothing but reports/weekly/; never arms, changes or sends anything but the page.

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
MIN_RECORD_DAYS = 30.0          # W2: no capital figure under 30 days of record
Z95 = 1.96                      # W2: the 95 % band's lower end, normal
CAPITAL_RULE = "research/lab/results/weekly_capital_line_prereg.md"
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
LEAK = "reports/leak/latest.json"
LEAK_RED = ("feature", "candles", "zoo", "book")    # jobs.LEAK_RED: the kinds the health check makes red
LEAK_ROWS = 4                   # red leaks named on the page, the rest counted
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


# ---------------------------------------------------------------- W2: the capital line

def _hist_point(d: dict, name: str) -> tuple[float, float, str, str] | None:
    """(value, paid in, start, last run) of a book in one dated report: forward's books list (1 + return since start,
    its journal's last date), the small-account and ETF books (equity_eur; paid_eur or capital_eur), the on-chain
    book (equity_usdc, start_usdc); last run "" where the report has none."""
    bs = d.get("books")
    if isinstance(bs, list):
        b = next((x for x in bs if isinstance(x, dict) and x.get("name") == name), None)
        v = _n((b or {}).get("return_pct"))
        return (1 + v / 100, 0.0, str(b.get("since")), str(b.get("last") or "")) if v is not None else None
    b = bs.get(name) if isinstance(bs, dict) else (d if (d.get("book") or "onchain_longterm") == name else None)
    if not isinstance(b, dict):
        return None
    def f(k: str) -> float | None:
        try:
            return _n(float(b[k])) if isinstance(b.get(k), str) else _n(b.get(k))
        except ValueError:
            return None
    v = f("equity_eur") if f("equity_eur") is not None else f("equity_usdc")
    paid = next((x for x in (f("paid_eur"), f("capital_eur"), f("start_usdc")) if x is not None), 0.0)
    return (v, paid, str(b.get("started") or b.get("since") or ""), "") if v is not None else None


def history(root: Path, report: str, name: str, cache: dict) -> list[tuple[int, float, float]]:
    """[(day_ms, value, paid)] of a book from the dated reports next to its report (reports/<folder>/<date>.json),
    only the points since its current start. A report whose book did not run since the one before (the same last
    run) is no point: the days without a run are missing, not days of zero return, and their moves arrive with the
    next run's step over all its days (results/m4_perps_forward_audit.md)."""
    folder = (root / "reports" / report).parent
    if folder not in cache:
        cache[folder] = [(p.stem, notify.read_json(p)) for p in sorted(folder.glob("????-??-??.json"))] \
            if folder.is_dir() else []
    pts = []
    for stem, d in cache[folder]:
        pt = _hist_point(d, name) if isinstance(d, dict) else None
        t = _iso_ms(stem + "T00:00:00+00:00")
        if pt and t is not None:
            pts.append((t, *pt))
    start = pts[-1][3] if pts else None
    out, seen = [], None
    for t, v, paid, st, last in pts:
        if st != start or (last and last == seen):
            continue
        out.append((t, v, paid))
        seen = last or None
    return out


def lower_monthly(pts: list[tuple[int, float, float]]) -> float | None:
    """The lower end of the 95 % band of the mean daily return times 30; each step net of money paid in, over its
    days. None under 2 steps."""
    x = []
    for (t0, v0, p0), (t1, v1, p1) in zip(pts, pts[1:]):
        g = (t1 - t0) / DAY_MS
        if g > 0 and v0:
            x.append((v1 - v0 - (p1 - p0)) / v0 / g)
    if len(x) < 2:
        return None
    mu = sum(x) / len(x)
    sd = (sum((a - mu) ** 2 for a in x) / (len(x) - 1)) ** 0.5
    return MONTH_DAYS * (mu - Z95 * sd / len(x) ** 0.5)


def fill_gap(fwd: dict, name: str) -> tuple[float, float] | None:
    """(ratio, monthly discount) of a forward book with a measured fill gap above 1: its modelled costs a month times
    (ratio - 1); None without one."""
    b = next((x for x in fwd.get("books") or [] if isinstance(x, dict) and x.get("name") == name), None)
    c = (b or {}).get("costs")
    if not isinstance(c, dict) or c.get("modelled_only"):
        return None
    ratio, model, days = _n(c.get("ratio")), _n(c.get("model_pct")), _n(b.get("elapsed_days")) or _n(b.get("days"))
    if ratio is None or ratio <= 1 or model is None or not days:
        return None
    return ratio, model / 100 * MONTH_DAYS / days * (ratio - 1)


def record_days(b: dict, fwd: dict) -> float:
    """A book's days of record: its days since its start, and for a forward book at most the days it ran on
    (forward's `days`): a day without a run is no day of record (results/m4_perps_forward_audit.md)."""
    days = b.get("days") or 0
    fb = next((x for x in fwd.get("books") or [] if isinstance(x, dict) and x.get("name") == b.get("name")), None)
    ran = _n((fb or {}).get("days"))
    return min(days, ran) if ran is not None else days


def capital(r: dict, b: dict | None, pf: dict, fwd: dict, hist) -> dict:
    """One ladder candidate under W2: {"kind": "unknown" | "short" | "none" | "unreachable" | "cap", ...}."""
    p3 = (b or {}).get("p3")
    pr = r.get("pumpfun") if r.get("kind") == "rule" else None
    if isinstance(p3, dict) or isinstance(pr, dict):                         # pump.fun per trade
        if isinstance(p3, dict):
            band = p3.get("band") if isinstance(p3.get("band"), list) and len(p3["band"]) == 2 else [None]
            lo, n, days = _n(band[0]), _n(p3.get("trades")), _n(p3.get("days"))
        else:
            lo, n, days = _n(pr.get("lo")), _n(pr.get("entries")), _n(pr.get("days_record"))
        if lo is None or not n or not days:
            return {"kind": "unknown"}
        if days < MIN_RECORD_DAYS:
            return {"kind": "short", "days": days}
        if None in (pf["gap"], pf["cap"], pf["sol_eur"]):
            return {"kind": "unknown"}
        edge, tpm = lo - pf["gap"] / 100, n / days * MONTH_DAYS
        if edge <= 0:
            return {"kind": "none"}
        if edge * pf["cap"] * pf["sol_eur"] * tpm < GOAL_EUR:
            return {"kind": "unreachable", "most": edge * pf["cap"] * pf["sol_eur"] * tpm}
        stake = GOAL_EUR / (edge * tpm)
        return {"kind": "cap", "eur": stake / (pf["share"] or 1.0), "pumpfun": True, "edge": edge, "tpm": tpm,
                "stake_sol": stake / pf["sol_eur"], "days": days}
    if b is None or b.get("currency") == "SOL":                              # no book, or R2's without a band
        return {"kind": "unknown"}
    days = record_days(b, fwd)
    if days < MIN_RECORD_DAYS:
        return {"kind": "short", "days": days}
    m = lower_monthly(hist(b["report"], b["name"]))
    if m is None:
        return {"kind": "unknown"}
    gap = fill_gap(fwd, b["name"])
    if gap:
        m -= gap[1]
    if m <= 0:
        return {"kind": "none"}
    return {"kind": "cap", "eur": GOAL_EUR / m, "m": m, "gap": gap[0] if gap else None, "days": days}


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
    snap = {"date": today, "now_ms": now, "books": {}, "ladder": {}, "failing": [], "leaks": [], "live_pnl_sol": None}
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

    # capital per ladder candidate, W2 (results/weekly_capital_line_prereg.md)
    rows = (lad or {}).get("rows") if isinstance(lad, dict) else None
    if rows is None:
        lines.append(missing("Kapital je Kandidat", LADDER))
    else:
        by, cache = {b["name"]: b for b in books}, {}
        ack = (live or {}).get("ack") if isinstance(live, dict) else None
        ack = ack if isinstance(ack, dict) else {}
        sel = (real or {}).get("selection")
        pf = {"gap": _n(sel.get("pts")) if isinstance(sel, dict) else None, "cap": _n(ack.get("max_trade_sol")),
              "share": _n(ack.get("stake_share")), "sol_eur": sol_eur}
        fwd = read("reports/forward/latest.json")
        fwd = fwd if isinstance(fwd, dict) else {}
        got: dict[str, list] = {"cap": [], "none": [], "unreachable": [], "short": [], "unknown": []}
        for r in rows:
            b = by.get(r.get("name")) if r.get("kind") in ("book", "rule") else None
            c = capital(r, b, pf, fwd, lambda rel, name: history(root, rel, name, cache))
            got[c["kind"]].append((r.get("name"), c, b))
        cut = lambda xs: ", ".join(str(x[0]) for x in xs[:8]) + (", ..." if len(xs) > 8 else "")  # noqa: E731
        lines.append(f"Kapital-Regel: eine Zahl nur ab {de(MIN_RECORD_DAYS, 0)} Tagen Aufzeichnung, aus der unteren "
                     f"Grenze des 95-%-Bands; pump.fun je Trade (untere Grenze je Einstieg minus P2s Lücke "
                     + (f"{de(pf['gap'], 1, True)} Punkte" if pf["gap"] is not None else "(fehlt)")
                     + ", mal Trades im Monat beim Live-Einsatz von höchstens "
                     + (i18n.sol(pf["cap"], 2, "de") if pf["cap"] is not None else "(fehlt)")
                     + "), nie aus Wallet-Wachstum; eine gemessene Fill-Lücke wird abgezogen"
                     + src(CAPITAL_RULE))
        for name, c, b in sorted(got["cap"], key=lambda x: x[1]["eur"])[:CAPITAL_ROWS]:
            if c.get("pumpfun"):
                lines.append(f"Kapital für {de(GOAL_EUR, 0)} EUR im Monat, {name}: {eur(c['eur'])} (pump.fun je Trade, "
                             f"untere Grenze nach P2 {pct(c['edge'])} je Einstieg, {de(c['tpm'], 0)} Trades im Monat, "
                             f"Einsatz {i18n.sol(c['stake_sol'], 3, 'de')}, {de(c['days'], 0)} Tage)"
                             + src(REALISTIC, LIVE_STATUS) + ("" if b else src(LADDER)))
            else:
                lines.append(f"Kapital für {de(GOAL_EUR, 0)} EUR im Monat, {name}: {eur(c['eur'])} (Papier, untere "
                             f"Grenze {pct(c['m'])} im Monat, {de(c['days'], 0)} Tage"
                             + (f", Fill-Lücke {de(c['gap'], 1)}x abgezogen" if c["gap"] else "") + ")"
                             + src("reports/" + b["report"], *(["reports/forward/latest.json"] if c["gap"] else [])))
        if len(got["cap"]) > CAPITAL_ROWS:
            lines.append(f"Kapital: {len(got['cap']) - CAPITAL_ROWS} weitere Kandidaten mit unterer Grenze über 0"
                         + src(PAPER))
        if got["none"]:
            lines.append(f"Kapital: keins bei {len(got['none'])} Kandidaten (untere Grenze nach Abzügen nicht über 0): "
                         + cut(got["none"]) + src(PAPER, LADDER))
        if got["unreachable"]:
            lines.append(f"Kapital: nicht erreichbar bei {len(got['unreachable'])} Kandidaten (beim Live-Einsatz von "
                         f"höchstens {i18n.sol(pf['cap'], 2, 'de')} je Trade bei keinem Kapital {de(GOAL_EUR, 0)} EUR): "
                         + cut(got["unreachable"]) + src(REALISTIC, LIVE_STATUS))
        if got["short"]:
            lines.append(f"Kapital: {len(got['short'])} Kandidaten unter {de(MIN_RECORD_DAYS, 0)} Tagen Aufzeichnung: "
                         + cut(sorted(got["short"], key=lambda x: -x[1]["days"])) + src(PAPER, LADDER))
        if got["unknown"]:
            lines.append(f"Kapital: {len(got['unknown'])} Kandidaten ohne Band (kein Buch, kein Tagesverlauf oder kein "
                         f"Band je Trade)" + src(LADDER))

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
        pr = lad.get("promotions")
        if isinstance(pr, dict):
            sh = [x for x in pr.get("shadows") or [] if isinstance(x, dict)]
            n = {k: sum(1 for x in sh if x.get("status") == k) for k in ("active", "missing_tool", "passed", "failed")}
            lr = [str(c.get("name")) for c in pr.get("live_ready") or [] if isinstance(c, dict)]
            lines.append(f"Beförderungen (A4): {n['active']} Schatten laufen, {n['missing_tool']} ohne Werkzeug, "
                         f"Lockbox {n['passed']} bestanden, {n['failed']} endgültig gescheitert; bereit für Stufe 5: "
                         + (", ".join(lr) if lr else "keiner") + src(LADDER, "promotions/live_ready.json"))
            if lr:
                short.append(f"Bereit für Stufe 5: {', '.join(lr)}")

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
    # T1's red leaks (results/leak_coverage_prereg.md): every red line the health check has, not only red jobs.
    lk = read(LEAK)
    if not isinstance(lk, dict):
        lines.append(missing("Leck-Prüfung (T1)", LEAK))
    else:
        bad = [r for r in lk.get("results") or [] if isinstance(r, dict) and not r.get("ok")
               and r.get("kind") in LEAK_RED]
        snap["leaks"] = [f"{r.get('kind')} {r.get('name')}" for r in bad]
        lines.append(f"Leck-Prüfung (T1) vom {str(lk.get('generated') or '?')[:10]}: {len(bad)} rot von "
                     f"{int(_n(lk.get('checked')) or 0)} geprüft" + src(LEAK))
        lines += [f"Leck {r.get('kind')} {r.get('name')}: {str(r.get('why') or r.get('error') or 'Leck')[:160]}"
                  + src(LEAK) for r in bad[:LEAK_ROWS]]
        if len(bad) > LEAK_ROWS:
            lines.append(f"und {len(bad) - LEAK_ROWS} weitere" + src(LEAK))
        short.append(f"Lecks: {len(bad)} rot")

    # ---- disk, data, the registry
    lines += ["", "## Platte, Daten, Register"]
    dk = read(DISK)
    if not isinstance(dk, dict):
        lines.append(missing("Platte", DISK))
    else:
        # days left and the fall they come from (the faster of 3 and 7 days, as jobs.measure_disk), then the two
        # parts that grow most (reports/disk/breakdown.md) and the tracked datasets apart from them
        left = _n(dk.get("daysLeft"))
        fall = max((_n(v) for v in (dk.get("freeFallGbPerDay") or {}).values() if _n(v) is not None), default=None)
        top = [p for p in dk.get("topGrowing") or [] if isinstance(p, dict) and _n(p.get("gbPerDay")) is not None][:2]
        lines.append(f"Platte: {de(_n(dk.get('freeGb')) or 0, 1)} von {de(_n(dk.get('totalGb')) or 0, 1)} GB frei, "
                     + (f"fällt {de(fall, 2)} GB am Tag, voll in {de(left, 0)} Tagen" if left is not None and fall
                        else "kein Volllaufen absehbar")
                     + ("; wächst am meisten: " + ", ".join(f"{p.get('part')} {de(_n(p['gbPerDay']), 2, True)} GB am Tag"
                                                           for p in top) if top else "")
                     + f"; Datensätze {de(_n(dk.get('trackedGb')) or 0, 1)} GB, "
                     f"{de(_n(dk.get('growthGbPerDay')) or 0, 2, True)} GB am Tag"
                     + src(DISK, *(["reports/disk/breakdown.md"] if top else [])))
        short.append(f"Platte: {de(_n(dk.get('freeGb')) or 0, 0)} GB frei"
                     + (f", voll in {de(left, 0)} Tagen" if left is not None and fall else ""))
    reg = (lad or {}).get("registry") if isinstance(lad, dict) else None
    f = LADDER
    if not isinstance(reg, dict) or _n(reg.get("n_trials")) is None:
        from . import ladder                                 # the ladder's own total (results/trial_audit_prereg.md)
        reg, f = ladder.register_total(root), "trials/registry.jsonl"
    if reg is None:
        lines.append(missing("Register", "trials/registry.jsonl"))
    else:
        sums = (f" = R5-Register {de(reg['r5_trials'], 0)} ("
                + ", ".join(f"{k} {de(v, 0)}" for k, v in (reg.get("families") or {}).items())
                + f") + F3-Ledger {de(reg['f3_trials'], 0)}") if _n(reg.get("f3_trials")) is not None else ""
        lines.append(f"Register: {de(reg['n_trials'], 0)} Versuche{sums}, Rauschbalken (bester Sharpe aus reinem "
                     f"Rauschen, R5s Tagesversuche) {de(_n(reg.get('sr0_annual')) or 0, 2)} im Jahr" + src(f))
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
