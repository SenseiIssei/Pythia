"""The hourly CS2 job after the collector: models (refit once a day), alerts,
the paper portfolio (weekly), the weekly report and the board for the app.

  python -m lab.cs2.run              everything that is due
  python -m lab.cs2.run --dry-run    compute and print, post nothing, write nothing to the paper book
  python -m lab.cs2.run --refit      refit the models now

Writes:
  <data>/cs2/model/preds.parquet, model.json    today's predictions and how they were made
  <data>/cs2/paper/state.json, journal.csv       the play-money portfolio
  <data>/cs2/alerts_state.json, alerts.jsonl     what was sent and when
  <reports>/cs2_board/latest.json                the CS2 page in the app
  <reports>/cs2/                                 the research report, daily (results/cs2.md)
  <reports>/cs2_weekly/                          the weekly report, at each paper rebalance

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
from ..ops import notify
from . import book, market, model

BOARD = "cs2_board"


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
    text = notify.clip(text)
    print(text)
    if dry_run or not url:
        return False
    ok, err = notify.post(url, fmt, text)
    if not ok:
        print(f"not delivered: {err}", file=sys.stderr)
    return ok


def weekly_report(st: dict, eq: float, prices: dict, board_rows: list[dict], model_rep: dict, history_days: int,
                  today: date) -> tuple[str, dict]:
    ret = eq / book.START_EQUITY - 1
    picks = [r for r in board_rows if r["signal"] == "buy"][:10]
    gaps = sorted([r for r in board_rows if r["gap"] is not None], key=lambda r: -r["gap"])[:5]
    lines = [f"# CS2 weekly {today.isoformat()}", "",
             f"Paper portfolio (play money, EUR): equity {eq:,.2f} after the sale fee, {ret:+.2%} since "
             f"{(st.get('started') or '')[:10]}, cash {st['cash']:,.2f}, {len(st['positions'])} positions.",
             f"History collected: {history_days} days. Predictions: 7 days from {model_rep.get('src7', 'bootstrap')}, "
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
    return md, data


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
        _write_json(reports / BOARD / "latest.json", {
            "generated": now.strftime("%Y-%m-%d %H:%M UTC"), "generatedMs": now_ms, "status": "no data",
            "verdict": "No CS2 data collected yet.", "items": [], "collector": collector})
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
        from ..experiments import cs2 as research
        md, data = research.build(root, today, snap, meta, mx)
        if not dry:
            if root is None:
                report.write("cs2", md, data)
            else:
                _write_json(reports / "cs2" / "latest.json", data)
                (reports / "cs2" / "latest.md").write_text(md, encoding="utf-8")
    else:
        preds_df = pl.read_parquet(preds_path)
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
        delivered = post(book.alert_text(fresh, notify.config()[2]), dry)
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
        post(f"{notify.config()[2]} CS2 weekly: {data['verdict']} "
             f"{len(st['last_trades'])} paper trades. Details on the CS2 page.", dry)
    elif not dry:
        book.save_state(root, st)

    recent = []
    log = base / "alerts.jsonl"
    if log.exists():
        recent = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()[-20:] if x.strip()][::-1]
    journal = book.read_journal(root)[-120:]
    history = _history_days(root)
    pos = [{"name": n, "qty": p["qty"], "cost": p["cost"], "bought": p["bought"],
            "price": prices.get(n) or p.get("last_price"), "returnPct": ((prices.get(n) or p["cost"]) / p["cost"] - 1) * 100}
           for n, p in st["positions"].items()]
    boardj = {
        "generated": now.strftime("%Y-%m-%d %H:%M UTC"), "generatedMs": now_ms, "status": "ok",
        "verdict": f"{len(rows)} items, {sum(r['signal'] == 'buy' for r in rows)} buy signals after fees, "
                   f"paper {eq / book.START_EQUITY - 1:+.2%}; {history} days of history.",
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
        "items": rows,
    }
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
