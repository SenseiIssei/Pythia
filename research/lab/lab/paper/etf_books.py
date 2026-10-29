"""EQ1's ten ETF paper books at 50 EUR, each with a Trade Republic, a Scalable and an Interactive Brokers wallet. No real money.

    python -m lab.paper.etf_books              step every wallet over the Xetra closes since its last run, journal, report
    python -m lab.paper.etf_books --dry-run    print what is new and each wallet's state; write nothing

Pre-registered in results/etf_books_eq1_prereg.md, numbers in results/etf_books_eq1.md and .json. The books of
lab.experiments.etf_books_eq1 (BOOKS: SXR8 held, the benchmark; EUNL held; dual momentum 252 days top 3 over the
eight UCITS funds; SXR8 above its 200-day mean else XEON; SXR8 at a 15 % vol target, the rest XEON), each `once`
(50 EUR) and `plus50` (50 EUR more on the first Xetra day of every month), with the study's own wallet code
(eq1.step): decided at close t, filled at close t+1 at the half spread, the brokers' fees, fractions or whole units,
savings plans and the minimums below which an order is not sent. Each wallet starts in cash at the last close of the
book's first run (its day 0; `started` is the run's date); the first orders go out at the next close.

Closes: the lab's copy in <data>/etf/daily (job etf-daily, Yahoo's adjusted closes, 22:30 UTC on weekdays); this job
runs after it. Every Xetra day since the last run is stepped once, in order; closes older than STALE_DAYS only mark.
The two distributing funds' (EXSA, EUNH) distributions are not credited here (the study's adjusted closes reinvest
them), taxes are left out. The study's 30 trials go into R5's registry on every run (only once each).

Per book: <data>/paper/<book>/state.json, journal.csv (one row per date and broker) and trades.csv; the report:
reports/etf_books/latest.md and .json (a feed for the app, read by lab.ops.paper_books and the ladder, which judges
the Trade Republic wallet). Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import metrics, report
from ..data import WRITE_ROOT
from ..experiments import etf_books_eq1 as eq1
from .smallaccount import _append, _read_csv, load_state, save_state

REPORT = "etf_books"
STUDY = "EQ1"
BOOKS = {f"eq1_{bk}_{v}": (bk, v) for bk in eq1.BOOKS for v in eq1.VARIANTS}
LABELS = {"hold_sp500": "SXR8 (S&P 500) held, the benchmark", "hold_world": "EUNL (MSCI World) held",
          "dual_mom": "dual momentum 252 days, top 3 of 8 UCITS funds, weekly",
          "trend_sp500": "SXR8 above its 200-day mean, else XEON, monthly",
          "voltarget_sp500": "SXR8 at a 15 % vol target, the rest XEON, monthly"}
STALE_DAYS = 5
JOURNAL_COLS = ["date", "broker", "equity_eur", "paid_eur", "flow_eur", "cash_eur", "decided", "plan_lines", "orders",
                "not_sent", "fees_eur", "targets", "held"]
TRADE_COLS = ["date", "broker", "side", "fund", "units", "eur"]


def variant(name: str, equity_eur: float | None = None) -> str:
    bk, v = BOOKS[name]
    now = f" · now {equity_eur:,.2f} EUR" if equity_eur is not None else ""
    top = "50 EUR once" if v == "once" else "50 EUR and 50 EUR a month"
    return (f"EXPERIMENT, paper only · {STUDY} ETF book · {top} · {LABELS[bk]} · one close late · Trade Republic, "
            f"Scalable, Interactive Brokers{now}")


def book_dir(name: str, root: Path | None = None) -> Path:
    return (WRITE_ROOT if root is None else root) / "paper" / name


def new_state(name: str, day: str, started: str | None = None) -> dict:
    """A book in cash at close `day` (its day 0); `started` the date of its first run (its first number)."""
    return {"variant": variant(name), "started": started or day, "last": day,
            "wallets": {br: eq1.new_wallet(day) for br in eq1.BROKERS}}


def advance(name: str, st: dict, C: eq1.Closes) -> tuple[dict, list[dict], list[dict]]:
    """Every Xetra close after the state's last, in order, for every wallet. Returns (state, journal rows, trades)."""
    bk, v = BOOKS[name]
    rows, trades = [], []
    for s in np.flatnonzero(C.days > np.datetime64(st["last"])):
        if s == 0:
            continue
        day = str(C.days[s])
        for br, b in eq1.BROKERS.items():
            w = st["wallets"][br]
            sent0, ns0 = w["sent"], w["not_sent"]
            r = eq1.step(w, bk, v, b, C, int(s))
            rows.append({"date": day, "broker": br, "equity_eur": round(r["equity"], 4), "paid_eur": w["paid"],
                         "flow_eur": r["flow"], "cash_eur": round(w["cash"], 4), "decided": r["decided"],
                         "plan_lines": r["plan_lines"], "orders": w["sent"] - sent0, "not_sent": w["not_sent"] - ns0,
                         "fees_eur": round(w["fees"], 4),
                         "targets": json.dumps({k: round(x, 4) for k, x in sorted(r["targets"].items())}),
                         "held": json.dumps({k: round(u, 6) for k, u in sorted(w["units"].items())})})
            trades += [{"date": day, "broker": br, "side": f["side"], "fund": f["fund"], "units": round(f["units"], 6),
                        "eur": round(f["eur"], 4)} for f in r["fills"]]
        st["last"] = day
    st["variant"] = variant(name, st["wallets"][eq1.JUDGED]["equity"])
    return st, rows, trades


def study_rows(path: Path = eq1.SUMMARY) -> dict:
    """The study's validation numbers by (book, variant, broker), {} when results/etf_books_eq1.json is missing."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {(r["book"], r["variant"], r["broker"]): r for r in d.get("rows") or []}


def register_trials(path: Path = eq1.SUMMARY) -> int:
    """The study's 30 trials into R5's registry (each id once); the number appended."""
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return len(metrics.register(d.get("trials") or []))
    except (OSError, ValueError) as e:
        print(f"trials not registered: {e}", file=sys.stderr)
        return 0


def write_report(books: dict[str, dict], study: dict, now_ms: int, last_close: str, stale: bool) -> dict:
    md = ["# EQ1 ETF paper books (UCITS in EUR), at 50 EUR\n",
          "EXPERIMENT, paper only. Pre-registered in results/etf_books_eq1_prereg.md; the study: "
          "results/etf_books_eq1.md. One close late, each broker's stated costs and minimums, taxes left out. "
          f"Last Xetra close {last_close}" + (" (stale: only marked)" if stale else "") + ".\n"]
    rows, items = [], []
    for name, st in books.items():
        bk, v = BOOKS[name]
        for br, w in st["wallets"].items():
            held = ", ".join(f"{s} {u:.4f}" for s, u in sorted(w["units"].items())) or "cash"
            sr = study.get((bk, v, br), {}).get("val") or {}
            rows.append({"book": name, "broker": br, "now": f"{w['equity']:,.2f} EUR", "paid in": f"{w['paid']:,.0f} EUR",
                         "result": f"{w['equity'] - w['paid']:+.2f} EUR", "orders": w["sent"], "not sent": w["not_sent"],
                         "fees": f"{w['fees']:.2f} EUR", "held": held, "since": st["started"],
                         "study CAGR / DD / months under water": f"{eq1._pct(sr.get('cagr'))} / "
                         f"{eq1._pct(sr.get('max_dd'))} / {sr.get('under_water_months', float('nan')):.0f}" if sr else ""})
        w = st["wallets"][eq1.JUDGED]
        items.append({"label": f"{name} (Trade Republic)", "value": f"{w['equity']:,.2f} EUR ({w['equity'] - w['paid']:+.2f})",
                      "detail": f"{LABELS[bk]}; paid in {w['paid']:,.0f} EUR", "status": "ok" if w["equity"] >= w["paid"]
                      else "watch"})
    md.append(report.table(rows, list(rows[0]) if rows else []))
    md.append("The study's columns are its validation window (2024-01-01 to 2026-06-30), time-weighted. Distributions of "
              "EXSA and EUNH are not credited in the paper wallets.\n")
    total = sum(st["wallets"][eq1.JUDGED]["equity"] for st in books.values())
    paid = sum(st["wallets"][eq1.JUDGED]["paid"] for st in books.values())
    out = {}
    for name, st in books.items():
        bk, v = BOOKS[name]
        w = st["wallets"][eq1.JUDGED]
        out[name] = {"variant": st["variant"], "started": st["started"], "last": st["last"], "study": STUDY,
                     "book": bk, "topup": v, "judged": eq1.JUDGED, "equity_eur": w["equity"], "paid_eur": w["paid"],
                     "wallets": {br: {k: x[k] for k in ("equity", "paid", "cash", "units", "fees", "sent", "not_sent",
                                                        "topups")} for br, x in st["wallets"].items()},
                     "study_val": {br: (study.get((bk, v, br)) or {}).get("val") for br in eq1.BROKERS}}
    data = {**report.feed_header("EQ1 ETF paper books", "watch" if stale or total < paid else "ok",
                                 f"{total:,.2f} EUR from {paid:,.0f} EUR paid in (Trade Republic wallets)", items=items,
                                 updated_ms=now_ms), "last_close": last_close, "stale": stale, "books": out}
    report.write(REPORT, "\n".join(md), data)
    return data


def main(argv: list[str] | None = None, now_ms: int | None = None, root: Path | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    now_ms = now_ms or int(time.time() * 1000)
    C = eq1.load(to=None)
    last = str(C.days[-1])
    today = np.datetime64(datetime.fromtimestamp(now_ms / 1000, timezone.utc).date())
    stale = int((today - C.days[-1]).astype(int)) > STALE_DAYS
    states = {n: load_state(book_dir(n, root)) for n in BOOKS}
    if "--dry-run" in argv:
        for n, st in states.items():
            new = int((C.days > np.datetime64(st["last"])).sum()) if st else 0
            print(n, "new" if st is None else f"last {st['last']}, {new} new closes", json.dumps(
                {br: round(w["equity"], 2) for br, w in (st or {}).get("wallets", {}).items()}))
        print("last close", last, "stale" if stale else "fresh")
        return 0
    register_trials()
    books = {}
    for n in BOOKS:
        d = book_dir(n, root)
        st = states[n] or new_state(n, last, str(today))
        rows, trades = [], []
        if not stale:
            st, rows, trades = advance(n, st, C)
        done = {(r.get("date"), r.get("broker")) for r in _read_csv(d / "journal.csv")[-3 * len(eq1.BROKERS):]}
        _append(d / "journal.csv", JOURNAL_COLS, [r for r in rows if (r["date"], r["broker"]) not in done])
        _append(d / "trades.csv", TRADE_COLS, trades)
        save_state(d, st)
        books[n] = st
        print(n, json.dumps({br: round(w["equity"], 2) for br, w in st["wallets"].items()}))
    write_report(books, study_rows(), now_ms, last, stale)
    return 0


if __name__ == "__main__":
    sys.exit(main())
