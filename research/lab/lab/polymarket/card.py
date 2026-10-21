"""The Polymarket paper books' report (lab feed) and Telegram cards, English or German.

  report(res)      reports/polymarket/latest.{md,json} with the lab feed header, so the
                   books show on the Research page and in the Home insights
  daily_card(res)  once a day: equity, P&L since start, open and resolved positions, hit
                   rate per book; Claude and the model scored against the market
  alert_card(f)    a book opened a position with an edge of BIG_EDGE or more (at most
                   MAX_ALERTS a day)

Paper only: nothing here can place an order.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import report as R
from . import book as B

BIG_EDGE = 0.10
MAX_ALERTS = 3
FEED = "polymarket"


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def book_rows(res: dict) -> dict[str, dict]:
    out = {}
    for row in res.get("daily") or []:
        n = int(row["closed_total"])
        out[row["book"]] = {"equity": float(row["equity"]), "pnl": float(row["equity"]) - B.START_USD,
                            "open": int(row["open"]), "resolved": n, "won": int(row["won_total"]),
                            "opened": int(row["opened"]), "settled": int(row["settled"]),
                            "realized": float(row["realized"])}
    return out


def score_text(sc: dict, lang: str) -> str:
    from ..ops import i18n
    if not sc.get("resolved") or sc.get("brier_model") is None:
        return i18n.t("pm_score_wait", lang)
    return i18n.t("pm_score", lang, model=i18n.num(sc["brier_model"], 3, lang),
                  market=i18n.num(sc["brier_market"], 3, lang))


def ensemble_text(e: dict, lang: str) -> str:
    from ..ops import i18n
    if e.get("status") == "waiting":
        return i18n.t("pm_ensemble_wait", lang, need=e.get("needed", 200))
    key = "pm_ensemble_pass" if e.get("status") == "pass" else "pm_ensemble_fail"
    return i18n.t(key, lang, w=i18n.num(e.get("w") or 0.0, 2, lang))


def daily_card(res: dict, lang: str = "en"):
    from ..ops import i18n, notify
    t = i18n.t
    rows = book_rows(res)
    # One row per book, so both fit a phone screen at a glance.
    table = [[t(f"pm_book_{name}", lang), i18n.money(r["equity"], 0, lang), i18n.signed_money(r["pnl"], 0, lang),
              str(r["open"]), f"{r['won']}/{r['resolved']}" if r["resolved"] else "0/0"]
             for name, r in rows.items()]
    parts: list = [notify.Table([t("pm_col_book", lang), t("pm_equity", lang), t("pm_col_start", lang),
                                 t("pm_open", lang), t("pm_col_hit", lang)], table)]
    cs, ms = res.get("claude_score") or {}, res.get("model_score") or {}
    parts.append(notify.Line(t("pm_claude_line", lang, n=cs.get("forecasts", 0), r=cs.get("resolved", 0))
                             + score_text(cs, lang)))
    if res.get("model_ready"):
        parts.append(notify.Line(t("pm_model_line", lang, n=ms.get("forecasts", 0), r=ms.get("resolved", 0))
                                 + score_text(ms, lang)))
    else:
        parts.append(notify.Line(t("pm_no_model", lang)))
    parts.append(notify.Line(ensemble_text(res.get("ensemble") or {}, lang)))
    parts.append(notify.Line(t("pm_ai_cost", lang, usd=i18n.money(res.get("ai_cost_usd") or 0.0, 2, lang))))
    opened = sum(r["opened"] for r in rows.values())
    settled = sum(r["settled"] for r in rows.values())
    open_n = sum(r["open"] for r in rows.values())
    summary = t("pm_summary", lang, day=i18n.iso_day(res["day"], lang), open=open_n, opened=opened, settled=settled)
    return notify.Card("🎯", t("pm_title", lang), summary, parts, t("pm_foot", lang))


def alert_card(f: dict, lang: str = "en"):
    from ..ops import i18n, notify
    t = i18n.t
    line = t("pm_alert_line", lang, book=t(f"pm_book_{f['book']}", lang), side=t(f"pm_side_{f['side']}", lang),
             ask=i18n.num(f["ask"], 3, lang), q=i18n.num(f["q"], 3, lang), edge=i18n.num(f["edge"] * 100, 1, lang),
             usd=i18n.money(f["usd"], 0, lang))
    parts = [notify.Line(line)]
    if f.get("end_ms"):
        parts.append(notify.Line(t("pm_alert_ends", lang, day=i18n.iso_day(_day(int(f["end_ms"])), lang))))
    return notify.Card("🎯", t("pm_alert_title", lang), notify.short(f.get("question") or "", 200), parts,
                       t("pm_foot", lang))


def big_edges(res: dict) -> list[dict]:
    fills = sorted((f for f in res.get("fills") or [] if f["edge"] >= BIG_EDGE), key=lambda f: -f["edge"])
    return fills[:MAX_ALERTS]


def post(res: dict, dry_run: bool = False, poster=None) -> list[dict]:
    from ..ops import notify
    lang = notify.alert_lang()
    out = [notify.send("studies", [daily_card(res, lang)], dry_run=dry_run, poster=poster)]
    for f in big_edges(res):
        out.append(notify.send("studies", [alert_card(f, lang)], dry_run=dry_run, poster=poster))
    return out


def feed(res: dict) -> dict:
    rows = book_rows(res)
    cs, ms = res.get("claude_score") or {}, res.get("model_score") or {}
    items = []
    for name, r in rows.items():
        items.append({"label": "Model book" if name == "pm_model" else "Claude book",
                      "value": f"${r['pnl']:+,.0f}",
                      "status": "ok" if r["pnl"] >= 0 else "watch",
                      "detail": f"{r['open']} open, {r['resolved']} resolved ({r['won']} won), paper, $10,000 start",
                      "link": "study:polymarket", "importance": 40})
    for label, sc in (("Claude vs market", cs), ("Model vs market (live)", ms)):
        if sc.get("resolved"):
            items.append({"label": label, "value": f"{sc['brier_model']:.3f} vs {sc['brier_market']:.3f}",
                          "status": "ok" if sc.get("passes") else "watch",
                          "detail": f"Brier on {sc['resolved']} resolved of {sc['forecasts']} forecasts; lower is better",
                          "link": "study:polymarket", "importance": 35})
        else:
            items.append({"label": label, "value": f"{sc.get('forecasts', 0)} open",
                          "detail": "no forecast has resolved yet; scored only on markets resolved after it was written",
                          "link": "study:polymarket", "importance": 20})
    for f in sorted(res.get("fills") or [], key=lambda f: -f["edge"])[:8]:
        items.append({"label": (f.get("question") or f["market_id"])[:90], "value": f"{f['side'].upper()} {f['ask']:.3f}",
                      "detail": f"{'Model' if f['book'] == 'pm_model' else 'Claude'} book, forecast {f['q']:.3f}, "
                                f"edge {f['edge'] * 100:.1f} points, stake ${f['usd']:,.0f}",
                      "importance": min(80, int(30 + f["edge"] * 300)), "at_ms": f["ts_ms"]})
    n_open = sum(r["open"] for r in rows.values())
    head = (f"Paper only. {n_open} open positions in two books; Claude has {cs.get('forecasts', 0)} forecasts on "
            f"record ({cs.get('resolved', 0)} resolved). Nothing has beaten the market price yet.")
    if cs.get("passes") or ms.get("passes"):
        head = "Paper only. A forecaster beats the market price on resolved markets; see the study before reading more into it."
    return R.feed_header("Polymarket (paper)", "watch", head, items, updated_ms=res["ts_ms"])


def markdown(res: dict) -> str:
    rows = book_rows(res)
    out = [f"# Polymarket paper books, {res['day']}\n", "Paper only: no wallet, no orders.\n",
           f"Open markets in the snapshot: {res['open_markets']:,}; candidates with books: {res['candidates']:,}; "
           f"tradable by the rule today: {res['eligible']:,}; model forecasts {res['q_model']:,}; "
           f"fresh Claude forecasts {res['q_claude']:,}.\n",
           R.table([{"book": k, **v} for k, v in rows.items()],
                   ["book", "equity", "pnl", "open", "resolved", "won", "opened", "settled", "realized"])]
    for label, key in (("Claude", "claude_score"), ("Model (live)", "model_score")):
        sc = res.get(key) or {}
        out.append(f"\n**{label}**: {sc.get('forecasts', 0)} forecasts, {sc.get('resolved', 0)} resolved")
        if sc.get("brier_model") is not None:
            out.append(f"; Brier {sc['brier_model']:.4f} vs market {sc['brier_market']:.4f}, log loss "
                       f"{sc['logloss_model']:.4f} vs {sc['logloss_market']:.4f}, passes: {sc.get('passes')}")
    out.append(f"\n\nEnsemble: {res.get('ensemble')}\n")
    if res.get("fills"):
        out.append("\n## Opened today\n")
        out.append(R.table(res["fills"], ["book", "side", "ask", "q", "edge", "usd", "category", "question"]))
    if res.get("settled"):
        out.append("\n## Resolved today\n")
        out.append(R.table(res["settled"], ["book", "side", "outlay", "payout", "pnl", "category", "question"]))
    return "\n".join(out)


def report(res: dict, write: bool = True) -> dict:
    data = {k: v for k, v in res.items() if k not in ("history",)}
    data["equity_history"] = {b: [{"day": r.get("day"), "equity": r.get("equity")} for r in rows]
                              for b, rows in (res.get("history") or {}).items()}
    data.update(feed(res))
    if write:
        R.write(FEED, markdown(res), data)
    return data
