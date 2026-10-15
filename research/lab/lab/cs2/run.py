"""The hourly CS2 job after the collector: models (refit once a day), alerts,
the paper portfolio (weekly), the weekly report and the board for the app.

  python -m lab.cs2.run              everything that is due
  python -m lab.cs2.run --dry-run    compute and print, post nothing, write nothing to the paper book
  python -m lab.cs2.run --refit      refit the models now

Writes:
  <data>/cs2/model/preds.parquet, model.json    today's predictions and how they were made
  <data>/cs2/paper/state.json, journal.csv       the play-money portfolio
  <data>/cs2/alerts_state.json, alerts.jsonl     what was sent and when
  <data>/cs2/model/research.json                 today's research summary (verdict, spread, history)
  <reports>/cs2/latest.json                      hourly: the lab feed header (docs/LAB-FEEDS.md) for the
                                                 Research page and Home, plus the board for the CS2 page
                                                 (`rows`, `portfolio`, `alerts`, `research`)
  <reports>/cs2/<date>.md, latest.md             the research report, daily (results/cs2.md)
  <reports>/cs2_weekly/                          the weekly report, at each paper rebalance (also a feed)

Alerts and the weekly summary go out through lab.ops.notify (Telegram with
PYTHIA_TELEGRAM_BOT_TOKEN and PYTHIA_TELEGRAM_CHAT_ID, or the webhook).
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import polars as pl

from .. import report
from ..collect.cs2 import load_watchlist
from ..ops import i18n, notify
from . import book, market, model

BOARD = "cs2"
FEED_TITLE = "CS2 skins"
STALE_COLLECTOR_MS = 3 * 3_600_000


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def fit_models(root: Path | None, snap: pl.DataFrame, today: date) -> tuple[pl.DataFrame, dict, dict | None]:
    """(predictions per item, model report, daily matrix). The walk-forward
    model's predictions replace the bootstrap's per horizon once it scores."""
    boot_rep, preds = model.bootstrap(snap, today)
    preds = preds.with_columns(src7=pl.lit("bootstrap"), src30=pl.lit("bootstrap"))
    mx = model.daily_matrix(market.daily_skinport(root))
    wf = model.walk_forward(mx)
    for h in (7, 30):
        res = wf.get(f"h{h}") or {}
        last = res.pop("pred_last", None)
        if res.get("status") == "ok" and last:
            wfp = pl.DataFrame({"name": list(last), f"wf{h}": list(last.values())})
            preds = (preds.join(wfp, on="name", how="left")
                     .with_columns(pl.coalesce(f"wf{h}", f"pred{h}").alias(f"pred{h}"),
                                   pl.when(pl.col(f"wf{h}").is_not_null()).then(pl.lit("walk_forward"))
                                   .otherwise(pl.col(f"src{h}")).alias(f"src{h}"))
                     .drop(f"wf{h}"))
    rep = {"date": today.isoformat(), "bootstrap": boot_rep, "walk_forward": wf}
    return preds, rep, mx


def change7(root: Path | None, snap: pl.DataFrame, today: date) -> tuple[dict[str, float], str]:
    """7-day change per item: against the collector's own snapshot a week ago
    when there is one, else Skinport's 7-day median (basis says which)."""
    f = market.cs2_root(root) / "daily" / "skinport" / f"date={(today - timedelta(days=7)).isoformat()}.parquet"
    now = dict(zip(snap["name"].to_list(), snap["ref"].to_list()))
    if f.exists():
        old = pl.read_parquet(f)
        old = old.with_columns(ref=market.ref_price(old))
        prev = dict(zip(old["name"].to_list(), old["ref"].to_list()))
        return {n: now[n] / prev[n] - 1 for n in now if now[n] and prev.get(n)}, "snapshot 7 days ago"
    med = dict(zip(snap["name"].to_list(), snap["s7_median"].to_list()))
    return {n: now[n] / med[n] - 1 for n in now if now[n] and med.get(n)}, "Skinport 7-day median"


def post(text: str, dry_run: bool) -> bool:
    url, fmt, _ = notify.config()
    text = notify.clip(text, lang=notify.alert_lang())
    print(text)
    if dry_run or not url:
        return False
    ok, err = notify.post(url, fmt, text)
    if not ok:
        print(f"not delivered: {err}", file=sys.stderr)
    return ok


def weekly_message(prefix: str, verdict: str, eq: float, st: dict, lang: str = "en") -> str:
    """The weekly line to the chat, in `lang`; English says the report's verdict."""
    if lang == "de":
        verdict = i18n.t("cs2_verdict", lang, ret=i18n.frac_pct(eq / book.START_EQUITY - 1, 2, lang),
                         n=len(st["positions"]))
    return i18n.t("cs2_weekly", lang, prefix=prefix, verdict=verdict, n=len(st.get("last_trades") or []))


def weekly_report(st: dict, eq: float, prices: dict, board_rows: list[dict], model_rep: dict, history_days: int,
                  today: date) -> tuple[str, dict]:
    ret = eq / book.START_EQUITY - 1
    picks = [r for r in board_rows if r["signal"] == "buy"][:10]
    gaps = sorted([r for r in board_rows if r["gap"] is not None], key=lambda r: -r["gap"])[:5]
    lines = [f"# CS2 weekly {today.isoformat()}", "",
             f"Paper portfolio (play money, EUR): equity {eq:,.2f} after the sale fee, {ret:+.2%} since "
             f"{(st.get('started') or '')[:10]}, cash {st['cash']:,.2f}, {len(st['positions'])} positions.",
             f"History collected: {history_days} day{'' if history_days == 1 else 's'}. Predictions: 7 days from {model_rep.get('src7', 'bootstrap')}, "
             f"30 days from {model_rep.get('src30', 'bootstrap')}.", "", "## Trades this week", ""]
    tr = st.get("last_trades") or []
    lines += [f"- {t['side']} {t['qty']} x {t['name']} at {t['price']:.2f}" + (f", P&L {t['pnl']:+.2f}" if "pnl" in t else "")
              for t in tr] or ["- none"]
    lines += ["", "## Positions", ""]
    lines += [f"- {n}: {p['qty']} x, bought {p['bought']} at {p['cost']:.2f}, now {prices.get(n) or p.get('last_price') or 0:.2f}"
              for n, p in st["positions"].items()] or ["- none"]
    lines += ["", "## Top picks after fees", ""]
    lines += [f"- {r['name']}: {r['price']:.2f}, expected {r['expectedNet']:+.1%} net over {r['horizon']} days" for r in picks] or ["- none clear the fees"]
    lines += ["", "## Largest cross-market gaps after fees", ""]
    lines += [f"- {r['name']}: {r['gap']:+.1%} (Skinport {r['ask']}, Steam {r['steamPrice']})" for r in gaps] or ["- none"]
    md = "\n".join(lines) + "\n"
    data = {"date": today.isoformat(), "equity": eq, "return": ret, "cash": st["cash"], "positions": st["positions"],
            "trades": tr, "picks": picks, "gaps": gaps,
            "verdict": f"Paper {ret:+.2%} since start, {len(st['positions'])} positions."}
    items = [{"label": f"{t['side'].capitalize()} {t['name']}", "value": f"{t['qty']} x {t['price']:.2f} EUR",
              "detail": (f"P&L {t['pnl']:+.2f} EUR, {t.get('why', '')}" if "pnl" in t
                         else f"expected {t.get('expected', 0):+.1%} over {t.get('horizon_days')} days before the fee"),
              "importance": 20} for t in tr]
    data.update(report.feed_header(
        "CS2 paper portfolio (weekly)", "ok",
        f"The play-money skins portfolio is {ret:+.2%} since it started, with {len(st['positions'])} items and "
        f"{len(tr)} paper trades this week; it only uses {history_days} day{'' if history_days == 1 else 's'} of collected prices.",
        items or ["No paper trades this week: nothing cleared the fees."]))
    return md, data


def _pct(v: float | None, digits: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:+.{digits}f} %".replace("-", "−")


def feed(board_rows: list[dict], found: list[dict], eq: float, history: int, collector: dict, now_ms: int,
         research_verdict: str | None = None) -> dict:
    """The lab feed header for reports/cs2/latest.json (docs/LAB-FEEDS.md).

    Status: bad when the collector failed or has not run for three hours,
    watch when there is a cross-market gap or a big drop to look at by hand,
    ok otherwise. Items: what is worth a look (strongest first), the best
    buy ideas after fees, the paper portfolio and how much history there is."""
    ts = collector.get("ts_ms")
    stale = not ts or now_ms - int(ts) > STALE_COLLECTOR_MS
    failed = collector.get("ok") is False or not collector.get("skinport_items")
    ret = eq / book.START_EQUITY - 1
    items: list[dict] = []
    for a in found[:6]:
        if a["kind"] == "gap":
            items.append({"label": a["name"], "value": _pct(a["strength"]), "status": "watch",
                          "detail": f"Price gap between Skinport and Steam after fees: {a['text']}. Paper only, check by hand.",
                          "importance": int(min(85, 50 + a["strength"] * 300))})
        else:
            items.append({"label": a["name"], "value": _pct(-a["strength"]), "status": "watch",
                          "detail": f"Big drop in a liquid item: {a['text']}.",
                          "importance": int(min(80, 45 + a["strength"] * 100))})
    buys = sorted([r for r in board_rows if r["signal"] == "buy" and r.get("expectedNet") is not None],
                  key=lambda r: -r["expectedNet"])[:5]
    for r in buys:
        items.append({"label": r["name"], "value": _pct(r["expectedNet"]), "status": "ok",
                      "detail": f"The model expects {_pct(r['expectedNet'])} after fees over {r['horizon']} days "
                                f"(price {r['price']:.2f} EUR). A guess from {history} days of history, not advice.",
                      "importance": 25})
    items.append({"label": "Paper portfolio", "value": _pct(ret, 2), "status": "ok" if ret >= 0 else "watch",
                  "detail": "Play money in euro on Skinport prices after the sale fee; nothing is bought or sold for real.",
                  "importance": 15})
    items.append({"label": "History collected", "value": f"{history} day" + ("" if history == 1 else "s"),
                  "detail": research_verdict or "The forecaster is a bootstrap until there are about two months of prices.",
                  "link": "study:cs2", "importance": 10})
    if failed or stale:
        status = "bad"
        why = "has not run for three hours" if stale else "failed"
        headline = f"The CS2 price collector {why}, so the skins prices and alerts are out of date."
        items.insert(0, {"label": "Collector", "value": "late" if stale else "failed", "status": "bad",
                         "detail": "; ".join(collector.get("errors") or []) or "See /var/log/pythia-cs2.log on the lab machine.",
                         "importance": 60})
    elif found:
        status = "watch"
        top = found[0]
        what = "a price gap between Skinport and Steam" if top["kind"] == "gap" else "a big drop"
        headline = (f"{len(found)} skin{'s' if len(found) != 1 else ''} worth a look by hand; the strongest is "
                    f"{what} in {top['name']}. Paper only: Pythia never buys or sells skins.")
    else:
        status = "ok"
        nb = len(buys)
        headline = (f"No price gap or big drop after fees right now; {nb} buy idea{'s' if nb != 1 else ''} on paper, "
                    f"portfolio {_pct(ret, 2)}, {history} day{'s' if history != 1 else ''} of history.")
    return report.feed_header(FEED_TITLE, status, headline, items, updated_ms=now_ms)


def main(argv: list[str] | None = None, root: Path | None = None, now_ms: int | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dry = "--dry-run" in argv
    now_ms = now_ms or int(time.time() * 1000)
    now = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    today = now.date()
    base = market.cs2_root(root)
    reports = Path(report.REPORTS) if root is None else root / "reports"

    items, sales = market.latest_hourly(root, "skinport_items"), market.latest_hourly(root, "skinport_sales")
    snap = book.snapshot(items, sales)
    collector = market.read_json(base / "collector.json") or {}
    if snap.is_empty():
        empty = {"generated": now.strftime("%Y-%m-%d %H:%M UTC"), "generatedMs": now_ms, "boardStatus": "no data",
                 "verdict": "No CS2 data collected yet.", "rows": [], "collector": collector}
        empty.update(report.feed_header(
            FEED_TITLE, "bad" if collector else "watch",
            "No CS2 skin prices collected yet" + (": the collector ran but got nothing." if collector else
                                                   ": the hourly collector has not run on the lab machine."),
            [{"label": "Collector", "value": "no data", "status": "bad" if collector else "watch",
              "detail": "; ".join(collector.get("errors") or []) or "python -m lab.collect.cs2, hourly",
              "importance": 30}], updated_ms=now_ms))
        if not dry:
            _write_json(reports / BOARD / "latest.json", empty)
        print("no CS2 snapshot yet")
        return 0

    # models, once a day
    meta_path = base / "model" / "model.json"
    meta = market.read_json(meta_path) or {}
    preds_path = base / "model" / "preds.parquet"
    if "--refit" in argv or meta.get("date") != today.isoformat() or not preds_path.exists():
        preds_df, meta, mx = fit_models(root, snap, today)
        if not dry:
            preds_path.parent.mkdir(parents=True, exist_ok=True)
            preds_df.write_parquet(preds_path)
            _write_json(meta_path, meta)
        research_due = (meta, mx)  # the daily report, written after the paper step below
    else:
        preds_df = pl.read_parquet(preds_path)
        research_due = None
    preds = {r["name"]: (r["pred7"], r["pred30"]) for r in preds_df.iter_rows(named=True)}
    srcs = {"src7": _mode(preds_df, "src7"), "src30": _mode(preds_df, "src30")}

    # alerts
    steam = market.latest_daily(root, "steam")
    ago = now_ms - 24 * 3_600_000
    ago24 = book.snapshot(market.hourly_at(root, "skinport_items", ago), market.hourly_at(root, "skinport_sales", ago))
    found = book.find_alerts(snap, steam, ago24)
    st_path = base / "alerts_state.json"
    fresh, alert_state = book.fresh_alerts(found, market.read_json(st_path) or {}, now_ms)
    if fresh:
        delivered = post(book.alert_text(fresh, notify.config()[2], lang=notify.alert_lang()), dry)
        if not dry:
            _write_json(st_path, alert_state)
            with (base / "alerts.jsonl").open("a", encoding="utf-8") as fh:
                for a in fresh:
                    fh.write(json.dumps({"ts_ms": now_ms, "delivered": delivered, **a}) + "\n")

    # paper portfolio
    st = book.load_state(root)
    if not st.get("started"):
        st["started"] = now.isoformat(timespec="seconds")
    prices = {n: p for n, p in zip(snap["name"].to_list(), snap["ref"].to_list()) if p}
    rebalanced, turnover = False, 0.0
    weekly = None
    if book.due(st, today):
        eq0, _ = book.value(st, prices)
        st = book.rebalance(st, snap, preds, today)
        turnover = sum(abs(t["net"]) for t in st["last_trades"]) / eq0 if eq0 > 0 else 0.0
        rebalanced = True
    jrow = book.journal(root, st, prices, today, rebalanced, turnover) if not dry else None
    eq, _ = book.value(st, prices)

    # board
    ch7, basis = change7(root, snap, today)
    watch = load_watchlist()
    watch_names = [c["name"] for c in watch.get("cases") or []] + list(watch.get("skins") or []) + list(watch.get("stickers") or [])
    rows = book.board(snap, preds, steam, ch7, found, watch_names, set(st["positions"]))
    if rebalanced:
        md, data = weekly_report(st, eq, prices, rows, srcs, _history_days(root), today)
        if not dry:
            if root is None:
                report.write("cs2_weekly", md, data)
            else:
                _write_json(reports / "cs2_weekly" / "latest.json", data)
            book.save_state(root, st)
        weekly = data["verdict"]
        post(weekly_message(notify.config()[2], data["verdict"], eq, st, notify.alert_lang()), dry)
    elif not dry:
        book.save_state(root, st)

    if research_due:
        # the daily research report, after the paper step so its portfolio
        # section is today's; the dated json keeps the full numbers and
        # latest.json is rewritten below as the hourly feed and board
        from ..experiments import cs2 as research
        md, data = research.build(root, today, snap, *research_due)
        if dry:
            print(md)
        elif root is None:
            report.write("cs2", md, data)
        else:
            (reports / "cs2").mkdir(parents=True, exist_ok=True)
            _write_json(reports / "cs2" / f"{today.isoformat()}.json", data)
            (reports / "cs2" / "latest.md").write_text(md, encoding="utf-8")
        if not dry:
            _write_json(base / "model" / "research.json", research.summary(data))

    recent = []
    log = base / "alerts.jsonl"
    if log.exists():
        recent = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()[-20:] if x.strip()][::-1]
    journal = book.read_journal(root)[-120:]
    history = _history_days(root)
    pos = [{"name": n, "qty": p["qty"], "cost": p["cost"], "bought": p["bought"],
            "price": prices.get(n) or p.get("last_price"), "returnPct": ((prices.get(n) or p["cost"]) / p["cost"] - 1) * 100}
           for n, p in st["positions"].items()]
    research_sum = market.read_json(base / "model" / "research.json") or {}
    boardj = {
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"), "generatedMs": now_ms, "boardStatus": "ok",
        "verdict": f"{len(rows)} items, {sum(r['signal'] == 'buy' for r in rows)} buy signals after fees, "
                   f"paper {eq / book.START_EQUITY - 1:+.2%}; {history} day{'' if history == 1 else 's'} of history.",
        "currency": "EUR", "historyDays": history, "change7Basis": basis,
        "model": {**srcs, "note": _model_note(srcs, history)},
        "hurdle": market.round_trip_cost(),
        "portfolio": {"equity": round(eq, 2), "startEquity": book.START_EQUITY, "cash": round(st["cash"], 2),
                      "returnPct": round((eq / book.START_EQUITY - 1) * 100, 3), "started": st.get("started"),
                      "lastRebalance": st.get("last_rebalance"), "positions": pos,
                      "lastTrades": st.get("last_trades") or [],
                      "dates": [r["date"] for r in journal], "equityCurve": [float(r["equity"]) for r in journal]},
        "alerts": [{"tsMs": a.get("ts_ms"), "kind": a.get("kind"), "name": a.get("name"), "text": a.get("text")} for a in recent],
        "collector": {k: collector.get(k) for k in ("at", "ok", "skinport_items", "steam_ok", "steam_requested", "errors")},
        "research": research_sum,
        "rows": rows,
    }
    boardj.update(feed(rows, found, eq, history, collector, now_ms, research_sum.get("verdict")))
    if not dry:
        _write_json(reports / BOARD / "latest.json", boardj)
    print(boardj["verdict"] + (f" Weekly: {weekly}" if weekly else ""))
    if jrow:
        print(f"paper {jrow}")
    return 0


def _mode(df: pl.DataFrame, col: str) -> str:
    if col not in df.columns or df.is_empty():
        return "none"
    return "walk_forward" if (df[col] == "walk_forward").any() else "bootstrap"


def _history_days(root: Path | None) -> int:
    return len(list((market.cs2_root(root) / "daily" / "skinport").glob("date=*.parquet")))


def _model_note(srcs: dict, history: int) -> str:
    if srcs.get("src7") == "walk_forward":
        return f"Walk-forward LightGBM on {history} days of collected prices."
    return ("Bootstrap: one snapshot of Skinport's 90-day sales windows, cross-sectional, not a time-series "
            f"backtest. The walk-forward model takes over after about {model.MIN_TRAIN_DAYS + 7} days of history "
            f"(now {history}).")


if __name__ == "__main__":
    sys.exit(main())
