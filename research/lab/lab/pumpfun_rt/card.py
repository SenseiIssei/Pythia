"""The real-time pump.fun lab's Telegram cards (English or German, lab.ops.i18n).

  daily_card       once a day after the retrain: yesterday's record, our measured detection
                   latency (latency.py), the paper P&L of every shadow book, the study's bar,
                   the models, the readiness of each strategy for live, and the live
                   executor's state
  (live.winner_card: a paper winner over +200 %, at most one an hour)
  live_trade_card  every live order's fill or failure, coloured by outcome (a buy blue, a win
                   green, a loss red, break-even grey), the result first in the title, one block
                   of SOL and euro, the measured latency; test mode is the "Alpha phase"
  trade_chart      the closed trade's picture: the coin's price around it from the live feed
  day_chart        the daily card's picture: the day's cumulative P&L
  live_stop_card   the daily loss stop or the total budget stop fired
  live_leftover_card  a position from before a restart sold, or not sellable
  live_daily_card  the live service's day: balance, P&L, trades, measured latency vs assumed

Paper unless a card says real money or Alpha phase (the owner's small real-money test).
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
    lat = data.get("latency") or {}
    if lat.get("n") and lat.get("p50_ms") is not None:
        lines.append(t("prt_daily_latency", lang, med=i18n.num(lat["p50_ms"] / 1000, 1, lang),
                       p90=i18n.num((lat.get("p90_ms") or 0) / 1000, 1, lang),
                       fast=i18n.frac_pct(lat.get("within_1s") or 0.0, 0, lang, sign=False),
                       slot2=i18n.frac_pct(lat.get("within_2_slots") or 0.0, 0, lang, sign=False)))
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
        lines.append(t("prt_live_on_test" if live.get("mode") == "test" else "prt_live_on", lang,
                       rule=live.get("rule") or "?", n=live.get("trades_today", 0),
                       pnl=f"{i18n.num(live.get('pnl_today_sol', 0.0), 3, lang, True)} SOL"))
    elif live and live.get("asked"):
        lines.append(t("prt_live_refused", lang, why=(live.get("why") or ["?"])[0][:120]))
    else:
        lines.append(t("prt_live_locked", lang))
    parts = []
    if rows:
        parts.append(notify.Table([t("prt_col_book", lang), t("prt_col_closed", lang), t("prt_col_mean", lang),
                                   t("prt_col_pnl", lang)], rows))
    # One thought a line: a paragraph of eight sentences does not read on a phone.
    parts += [notify.Line(ln) for ln in lines]
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


def _tagged(title: str, mode: str | None, lang: str) -> str:
    from ..ops import i18n
    return f"{title} · {i18n.t('prl_test_tag', lang)}" if mode == "test" else title


def _head(rule, mode: str | None, lang: str) -> str:
    """The line under a trade card's title: pump.fun, the Alpha phase (or real money), the rule."""
    from ..ops import i18n
    return i18n.t("prl_head" if mode == "test" else "prl_head_full", lang, rule=rule or "?")


def _money(v_sol: float, eur: float | None, lang: str, sign: bool = False) -> str:
    """0.0525 SOL, with its euro value when the rate is known: +0.0113 SOL · +€1.98."""
    from ..ops import i18n
    s = i18n.sol(v_sol, 4, lang, sign)
    return f"{s} · {i18n.eur(v_sol * eur, 2, lang, sign)}" if eur else s


def outcome_emoji(ret: float | None) -> str:
    """🟢 a win, 🔴 a loss, ⚪ break-even (within half a percent) or unknown."""
    if ret is None or not math.isfinite(ret) or abs(ret) < 0.005:
        return "⚪"
    return "🟢" if ret > 0 else "🔴"


def _measured_line(measured: dict | None, lang: str):
    from ..ops import i18n, notify
    if not measured or measured.get("lat_ms") is None:
        return None
    t = i18n.t
    # A fill booked from the chain has the block's whole-second time, so it can read a hair before the signal.
    kw = {"lat": i18n.secs(max(0, measured["lat_ms"]), lang), "assumed": i18n.secs(C.Costs().lat_median_ms, lang)}
    if measured.get("slip") is None:
        return notify.Line(t("prl_measured_noslip", lang, **kw))
    return notify.Line(t("prl_measured", lang, slip=i18n.frac_pct(measured["slip"], 1, lang), **kw))


def _caveat(mode: str | None, lang: str):
    from ..ops import i18n, notify
    return notify.Line(i18n.t("prl_test_caveat" if mode == "test" else "prl_caveat", lang))


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def live_trade_card(kind: str, p: dict, kw: dict, lang: str = "en", day_pnl_sol: float | None = None,
                    mode: str | None = None, measured: dict | None = None, eur: float | None = None):
    """One live order's outcome: bought (blue), sold (a leg, blue), the position closed (green
    a win, red a loss, grey break-even; the result first in the title) or a failure (orange).
    One tidy block of numbers in SOL and, with `eur` (SOL in euro), in euro; then the measured
    latency and the short caveat. A test-mode trade is the Alpha phase."""
    from ..ops import i18n, notify
    t = i18n.t
    name = str(p.get("symbol") or p.get("name") or p.get("mint", "")[:8])[:20]
    why = lambda w: t(WHY.get(w or "take", "prt_why_time"), lang)          # noqa: E731
    rows: list[tuple] = []
    emoji = "🔵"
    if kind == "bought":
        title = t("prl_buy_title", lang, name=name)
        rows = [(t("prl_row_stake", lang), _money(kw.get("cost_l", 0) / C.LAMPORTS, eur, lang)),
                (t("prl_row_tokens", lang), i18n.num(kw.get("tokens", 0) / C.TOKEN_UNIT, 0, lang))]
    elif kind == "sold":
        title = t("prl_sell_title", lang, name=name)
        rows = [(t("prl_row_proceeds", lang), _money(kw.get("got_l", 0) / C.LAMPORTS, eur, lang)),
                (t("prl_row_exit", lang), why(p.get("exit_why")))]
    elif kind == "closed":
        rec = kw.get("rec") or {}
        ret = _num(rec.get("ret"))
        emoji = outcome_emoji(ret)
        title = t("prl_close_title", lang, name=name, ret=i18n.frac_pct(ret or 0.0, 1, lang))
        stake, got, pnl = (_num(rec.get(k)) for k in ("stake_sol", "proceeds_sol", "pnl_sol"))
        if stake is not None:
            rows.append((t("prl_row_stake", lang), _money(stake, eur, lang)))
        if got is not None:
            rows.append((t("prl_row_proceeds", lang), _money(got, eur, lang)))
        rows.append((t("prl_row_pnl", lang), _money(pnl or 0.0, eur, lang, True)))
        hold = _num(rec.get("hold_s"))
        if hold is not None:
            rows.append((t("prl_row_hold", lang), i18n.duration(hold, lang)))
        rows.append((t("prl_row_exit", lang), why(rec.get("exit_why") or p.get("exit_why"))))
        if day_pnl_sol is not None:
            rows.append((t("prl_row_today", lang), _money(day_pnl_sol, eur, lang, True)))
        if measured is None and rec.get("lat_buy_ms") is not None:
            measured = {"lat_ms": rec["lat_buy_ms"], "slip": _num(rec.get("slip"))}
    else:
        emoji = "🟠"
        title = t("prl_fail_title", lang, name=name)
    summary = (_head(p.get("rule"), mode, lang) if kind != "buy_failed" and kind != "sell_failed"
               else t("prl_fail_summary", lang, rule=p.get("rule", "?"), why=str(kw.get("why") or kind)[:120]))
    parts = ([notify.Rows(rows)] if rows else []) + [x for x in (_measured_line(measured, lang), _caveat(mode, lang))
                                                     if x is not None]
    return notify.Card(emoji, title, summary, parts, footer=t("prl_footer", lang))


def live_stop_card(kind: str, lost_sol: float, limit_sol: float, mode: str | None = None, lang: str = "en"):
    """The daily loss stop or the total budget stop fired: no more buys."""
    from ..ops import i18n, notify
    t = i18n.t
    k = "daily" if kind == "daily" else "total"
    sol = lambda v: i18n.sol(v, 4, lang)                     # noqa: E731
    return notify.Card("🛑", _tagged(t(f"prl_stop_{k}_title", lang), mode, lang),
                       t(f"prl_stop_{k}_summary", lang, lost=sol(lost_sol), limit=sol(limit_sol)),
                       [_caveat(mode, lang)], footer=t("prl_footer", lang))


def live_gate_card(why: str | None, mode: str | None = None, lang: str = "en"):
    """The running live book's gate shut (no more buys, with the reason) or opened again."""
    from ..ops import i18n, notify
    t = i18n.t
    if why:
        return notify.Card("🟠", _tagged(t("prl_gate_shut_title", lang), mode, lang),
                           t("prl_gate_shut_summary", lang, why=str(why)[:200]), [_caveat(mode, lang)],
                           footer=t("prl_footer", lang))
    return notify.Card("🟢", _tagged(t("prl_gate_open_title", lang), mode, lang), t("prl_gate_open_summary", lang),
                       [_caveat(mode, lang)], footer=t("prl_footer", lang))


def live_leftover_card(what: str, info: dict, mode: str | None = None, lang: str = "en"):
    """A position from before a restart: sold (coloured by its result), or not sellable (the owner sells it by hand)."""
    from ..ops import i18n, notify
    t = i18n.t
    name = str(info.get("symbol") or str(info.get("mint", ""))[:8])[:20]
    if what == "sold":
        cost = _num(info.get("cost_l"))
        emoji = outcome_emoji((info.get("got_l", 0) - cost) / cost if cost else None)
        title = t("prl_left_sold_title", lang, name=name)
        summary = t("prl_left_sold_summary", lang, sol=i18n.sol(info.get("got_l", 0) / C.LAMPORTS, 4, lang))
    elif info.get("fails"):                                  # a running position whose sale was given up
        emoji = "🟠"
        title = t("prl_stuck_title", lang, name=name)
        summary = t("prl_stuck_summary", lang, n=info["fails"], why=str(info.get("why") or "?")[:120])
    else:
        emoji = "🟠"
        title = t("prl_left_stuck_title", lang, name=name)
        summary = t("prl_left_stuck_summary", lang, why=str(info.get("why") or "?")[:120])
    return notify.Card(emoji, _tagged(title, mode, lang), summary, [_caveat(mode, lang)], footer=t("prl_footer", lang))


def live_daily_card(day: int, stats: dict, balance_l: int | None, total_sol: float, execution: dict | None,
                    mode: str | None, rule: str | None, lang: str = "en", eur: float | None = None):
    """Once a day from the live service: the day's and the total P&L, the wallet, the trades, and the
    measured landing latency against the paper model's assumption; green, red or grey by the day."""
    from ..ops import i18n, notify
    t = i18n.t
    d = _day(day * DAY_MS)
    pnl = stats.get("pnl_sol", 0.0) or 0.0
    summary = t("prl_daily_summary", lang, rule=rule or "?", n=stats.get("n", 0), wins=stats.get("wins", 0))
    rows = [(t("prl_row_day", lang), _money(pnl, eur, lang, True)),
            (t("prl_row_total", lang), _money(total_sol, eur, lang, True)),
            (t("prl_row_wallet", lang), _money(balance_l / C.LAMPORTS, eur, lang) if balance_l is not None
             else t("prl_daily_balance_unknown", lang))]
    lb = (execution or {}).get("lat_buy_ms") or {}
    if lb.get("n"):
        lat = t("prl_daily_latency", lang, lat=i18n.secs(lb["median"], lang), n=lb["n"],
                assumed=i18n.secs((execution.get("assumed") or {}).get("lat_median_ms", C.Costs().lat_median_ms), lang))
    else:
        lat = t("prl_daily_latency_none", lang)
    lines = [notify.Line(lat, t("prl_row_latency", lang))]
    if stats.get("failed"):
        lines.append(notify.Line(t("prl_daily_failed", lang, n=stats["failed"])))
    emoji = "⚪" if abs(pnl) < 1e-4 else ("🟢" if pnl > 0 else "🔴")     # break-even: under 0.0001 SOL
    return notify.Card(emoji, _tagged(t("prl_daily_title", lang, day=i18n.iso_day(d, lang)), mode, lang),
                       summary, [notify.Rows(rows)] + lines + [_caveat(mode, lang)], footer=t("prl_footer", lang))


# ---------------------------------------------------------------- the pictures

def _png(draw) -> bytes | None:
    """Draw into a temporary file and return its bytes; None without matplotlib or on any error
    (the card then goes without its picture)."""
    import os
    import tempfile
    from ..ops import charts
    if not charts.available():
        return None
    fd, name = tempfile.mkstemp(suffix=".png", prefix="pythia-chart-")
    os.close(fd)
    try:
        draw(name)
        return open(name, "rb").read()
    except Exception as e:                                   # a chart never stops a card
        print(f"card: chart not drawn ({type(e).__name__}: {e})", flush=True)
        return None
    finally:
        os.unlink(name)


def _plan(rule: str | None) -> tuple[float | None, float | None]:
    """The strategy's first take-profit step and its stop, as fractions."""
    try:
        from . import pipeline as P
        ex = P.BY_NAME[rule].exits
        return (ex.ladder[0][0] if ex.ladder else None), ex.sl
    except Exception:                                        # an unknown rule: no lines
        return None, None


def trade_chart_data(rec: dict, feed: dict | None) -> dict | None:
    """What render_trade draws for a closed trade, from the live feed (reports/pumpfun_rt/
    live_feed.json): the coin's points from a minute before the landing to half a minute after
    the exit. None when the feed has no point of it."""
    if not isinstance(feed, dict):
        return None
    land, ex = _num(rec.get("land_ms")), _num(rec.get("exit_ms"))
    coin = next((c for c in feed.get("coins") or [] if isinstance(c, dict) and c.get("mint") == rec.get("mint")
                 and (land is None or _num(c.get("land_ms")) in (None, land))), None)
    if coin is None or land is None:
        return None
    end = (ex or land) + 30_000
    pts = [(int(q[0]), float(q[1])) for q in coin.get("points") or []
           if isinstance(q, (list, tuple)) and len(q) >= 2 and land - 60_000 <= q[0] <= end and (_num(q[1]) or 0) > 0]
    entry = _num(rec.get("entry_price")) or _num(coin.get("entry_price"))
    if not pts or not entry:
        return None
    tp, sl = _num(coin.get("tp")), _num(coin.get("sl"))
    if tp is None and sl is None:
        tp, sl = _plan(rec.get("rule"))
    out_px = _num(rec.get("exit_price")) or _num((coin.get("exit") or {}).get("price"))
    return {"points": pts, "entry": (int(land), entry), "exit": (int(ex), out_px) if ex and out_px else None,
            "tp": tp, "sl": sl, "ret": _num(rec.get("ret"))}


def trade_chart(rec: dict, lang: str = "en", feed: dict | None = None, wait_s: float = 0.0) -> bytes | None:
    """The PNG of a closed live trade (charts.render_trade), or None. `feed` None reads the live
    feed's file, after `wait_s` so the half minute after the exit is in it."""
    from ..ops import charts, i18n
    if feed is None:
        import time
        from .live_exec import read_json, reports_dir
        if wait_s > 0:
            time.sleep(wait_s)
        feed = read_json(reports_dir() / "live_feed.json")
    data = trade_chart_data(rec, feed)
    if data is None:
        return None
    name = str(rec.get("symbol") or rec.get("name") or str(rec.get("mint", ""))[:8])[:20]
    title = i18n.t("prl_chart_title", lang, name=name, ret=i18n.frac_pct(data["ret"] or 0.0, 1, lang))
    return _png(lambda path: charts.render_trade(data, path, title, i18n.t("prl_chart_sub", lang), lang))


def day_curve(day: int, ledger: list[dict]) -> list[tuple[int, float]]:
    """The UTC day's closed trades as a running P&L in SOL, from 0 at the day's start."""
    lo, hi = day * DAY_MS, (day + 1) * DAY_MS
    rows = sorted((int(_num(r.get("exit_ms")) or 0), _num(r.get("pnl_sol")) or 0.0) for r in ledger
                  if lo <= (_num(r.get("exit_ms")) or -1) < hi)
    out, run = [(lo, 0.0)], 0.0
    for t, v in rows:
        run += v
        out.append((t, run))
    return out if len(out) > 1 else []


def day_chart(day: int, ledger: list[dict], lang: str = "en") -> bytes | None:
    """The daily card's picture: the day's cumulative P&L (charts.render_curve), None without a trade."""
    from ..ops import charts, i18n
    pts = day_curve(day, ledger)
    if not pts:
        return None
    title = i18n.t("prl_chart_day_title", lang, day=i18n.iso_day(_day(day * DAY_MS), lang))
    return _png(lambda path: charts.render_curve(pts, path, title, i18n.t("prl_chart_day_sub", lang), lang))


WHY = {"take": "prt_why_take", "take_part": "prt_why_take", "stop": "prt_why_stop", "time": "prt_why_time",
       "stuck": "prt_why_stuck", "trail": "prt_why_trail", "dev_sell": "prt_why_dev", "pull": "prt_why_pull",
       "risk": "prt_why_risk", "hazard": "prt_why_hazard", "kill": "prt_why_kill", "press": "prt_why_press",
       "leftover": "prt_why_leftover"}
