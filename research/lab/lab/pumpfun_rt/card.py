"""The real-time pump.fun lab's Telegram cards (English or German, lab.ops.i18n).

  daily_card       once a day after the retrain: yesterday's record, the paper P&L of
                   every shadow book, the study's bar, the models, the readiness of each
                   strategy for live, and the live executor's state
  (live.winner_card: a paper winner over +200 %, at most one an hour)
  live_trade_card  every live order's fill or failure, if the live executor were ever on

Paper unless a card says LIVE.
"""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone

import numpy as np

from . import curve as C

DAY_MS = 86_400_000
GATE_DAYS, GATE_TRADES, SHADOW_DAYS = 14, 300, 30


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def shadow_yesterday(now_ms: int, path=None) -> dict[str, dict]:
    """The live paper books' trades closed yesterday (UTC), from the paper ledger."""
    from .live import paper_dir
    y = _day(now_ms - DAY_MS)
    out: dict[str, list] = defaultdict(list)
    p = path or (paper_dir() / "ledger.csv")
    if p.exists():
        with p.open(newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if not r.get("exit_ms") or r.get("exit_why") == "restart" or r.get("gap") == "True" or not r.get("ret"):
                    continue
                try:
                    if _day(int(float(r["exit_ms"]))) == y:
                        out[r["rule"]].append({"ret": float(r["ret"]), "pnl_sol": float(r["pnl_sol"])})
                except ValueError:
                    continue
    return {k: {"n": len(v), "wins": sum(t["ret"] > 0 for t in v), "mean": float(np.mean([t["ret"] for t in v])),
                "pnl_sol": float(sum(t["pnl_sol"] for t in v))} for k, v in out.items()}


def daily_card(data: dict, models: dict | None, shadow: dict, live: dict | None, now_ms: int, lang: str = "en"):
    """`data` the study's latest.json, `models` the retrain's summary, `shadow` the books'
    yesterday, `live` the live executor's state (live_exec.status())."""
    from ..ops import i18n, notify
    t = i18n.t
    y = _day(now_ms - DAY_MS)
    rec = (data.get("record") or {}).get(y) or {"tokens": 0, "trades": 0, "completed": 0}
    summary = t("prt_daily_record", lang, tokens=i18n.num(rec["tokens"], 0, lang),
                trades=i18n.num(rec["trades"], 0, lang), done=i18n.num(rec["completed"], 0, lang))
    lines = []
    rows = []
    books = sorted(shadow.items(), key=lambda kv: -kv[1]["pnl_sol"])
    for book, s in books[:10]:
        rows.append([book[:22], str(s["n"]), i18n.frac_pct(s["mean"], 1, lang), i18n.num(s["pnl_sol"], 3, lang, True)])
    if not rows:
        lines.append(t("prt_daily_book_none", lang, book=t("prt_all_books", lang)))
    else:
        tot = sum(s["pnl_sol"] for s in shadow.values())
        lines.append(t("prt_daily_books", lang, n=len(shadow), pnl=f"{i18n.num(tot, 3, lang, True)} SOL"))
    n_days = len(data.get("days") or [])
    results = data.get("results") or []
    if n_days < GATE_DAYS:
        lines.append(t("prt_daily_early", lang, days=n_days))
    if results:
        lines.append(t("prt_daily_study", lang, passed=sum(1 for r in results if r.get("passes")),
                       rules=len(results), pick=data.get("pick") or "?"))
    if models:
        labels = models.get("labels") or {}
        lines.append(t("prt_daily_models", lang, useful=models.get("useful", 0), labels=len(labels),
                       wallet=models.get("wallet_adopted", 0), cat=models.get("cat_adopted", 0)))
        x = models.get("x14") or {}
        if x.get("pick"):
            def pc(v, sign=True):
                return i18n.frac_pct(v, 0, lang, sign) if v is not None and math.isfinite(v) else "n/a"
            lift = x.get("lift5_peak3x")
            lines.append(t("prt_daily_x14", lang, pick=x["pick"], cap=pc(x.get("capture_pick")),
                           base=x.get("base_pick") or "?", cap_base=pc(x.get("capture_base")),
                           prec=pc(x.get("prec5_peak3x"), False), rate=pc(x.get("rate_peak3x"), False),
                           lift=i18n.num(lift, 1, lang) if lift is not None and math.isfinite(lift) else "n/a"))
    ready = data.get("readiness") or {}
    if ready:
        def progress(v):
            return (min(v["days"] / GATE_DAYS, 1) + min(v["trades"] / GATE_TRADES, 1)
                    + min(v["shadow_days"] / SHADOW_DAYS, 1) + v["gates_ok"] + v["positive_ok"])
        best_k, best = max(ready.items(), key=lambda kv: progress(kv[1]))
        lines.append(t("prt_daily_ready", lang, rule=best_k, days=best["days"], trades=best["trades"],
                       shadow=best["shadow_days"], gates=t("prt_gates_pass" if best["gates_ok"] else "prt_gates_fail",
                                                           lang)))
        lines.append(t("prt_daily_ready_n", lang, n=sum(1 for v in ready.values() if v["ready"]), total=len(ready)))
    if live and live.get("on"):
        lines.append(t("prt_live_on", lang, rule=live.get("rule") or "?", n=live.get("trades_today", 0),
                       pnl=f"{i18n.num(live.get('pnl_today_sol', 0.0), 3, lang, True)} SOL"))
    elif live and live.get("asked"):
        lines.append(t("prt_live_refused", lang, why=(live.get("why") or ["?"])[0][:120]))
    else:
        lines.append(t("prt_live_locked", lang))
    parts = []
    if rows:
        parts.append(notify.Table([t("prt_col_book", lang), t("prt_col_closed", lang), t("prt_col_mean", lang),
                                   t("prt_col_pnl", lang)], rows))
    parts.append(notify.Line(" ".join(lines)))
    parts.append(notify.Line(t("prt_caveat", lang)))
    return notify.Card("⚡", t("prt_daily_title", lang, day=i18n.iso_day(y, lang)), summary, parts,
                       footer=t("prt_footer", lang))


def daily_card_now(now_ms: int, models: dict | None, lang: str = "en"):
    """The daily card from what is on disk: the study's report, the paper ledger, the live state."""
    from .. import report as rep
    try:
        data = json.loads((rep.REPORTS / "pumpfun_rt" / "latest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    try:
        from . import live_exec
        live = live_exec.status()
    except Exception:                                        # the card goes out whatever the live module says
        live = None
    return daily_card(data, models, shadow_yesterday(now_ms), live, now_ms, lang)


def live_trade_card(kind: str, p: dict, kw: dict, lang: str = "en", day_pnl_sol: float | None = None):
    """One live order's outcome: bought, sold (a leg or the close), or a failure."""
    from ..ops import i18n, notify
    t = i18n.t
    name = str(p.get("symbol") or p.get("name") or p.get("mint", "")[:8])[:20]
    sol = lambda lam: f"{i18n.num(lam / C.LAMPORTS, 4, lang)} SOL"          # noqa: E731
    if kind == "bought":
        title = t("prl_buy_title", lang, name=name)
        summary = t("prl_buy_summary", lang, rule=p["rule"], sol=sol(kw.get("cost_l", 0)),
                    tokens=i18n.num(kw.get("tokens", 0) / C.TOKEN_UNIT, 0, lang))
    elif kind == "sold":
        title = t("prl_sell_title", lang, name=name)
        summary = t("prl_sell_summary", lang, rule=p["rule"], sol=sol(kw.get("got_l", 0)),
                    why=t(WHY.get(p.get("exit_why") or "take", "prt_why_time"), lang))
    elif kind == "closed":
        rec = kw.get("rec") or {}
        title = t("prl_close_title", lang, name=name, ret=i18n.frac_pct(rec.get("ret", 0.0), 1, lang))
        summary = t("prl_close_summary", lang, rule=p["rule"], pnl=f"{i18n.num(rec.get('pnl_sol', 0.0), 4, lang, True)} SOL",
                    day=f"{i18n.num(day_pnl_sol or 0.0, 4, lang, True)} SOL")
    else:
        title = t("prl_fail_title", lang, name=name)
        summary = t("prl_fail_summary", lang, rule=p.get("rule", "?"), why=str(kw.get("why") or kind)[:120])
    return notify.Card("🔴", title, summary, [notify.Line(t("prl_caveat", lang))], footer=t("prl_footer", lang))


WHY = {"take": "prt_why_take", "take_part": "prt_why_take", "stop": "prt_why_stop", "time": "prt_why_time",
       "stuck": "prt_why_stuck", "trail": "prt_why_trail", "dev_sell": "prt_why_dev", "pull": "prt_why_pull",
       "risk": "prt_why_risk", "hazard": "prt_why_hazard", "kill": "prt_why_kill"}
