"""Real money readiness: the pre-registered rule for when an autopilot may be proposed for real money.

The owner's decision: real money on Alpaca only once an autopilot makes profit
actively and consistently on the Alpaca paper account. This job turns that
into numbers, every day, right after the learning loop (research/ops/jobs.yaml,
job `readiness`, depends_on learn). The rule, its thresholds and the date they
were set are in docs/LIVE-READINESS.md; the constants below are the only place
the code keeps them. A change to either shows in git.

Per autopilot, and per sleeve of an autopilot with several sleeves (a sleeve
has its own P&L and trade count), on the paper/demo record only, after fees:

  1  record     on the Alpaca paper account (mode demo) for at least the risk
                step's minimum days, with at least MIN_CLOSED_TRADES closed
                trades; NO_BAND_EXTRA_DAYS more when there is no backtest band
  2  profit     net P&L above zero over the whole period
  3  weeks      positive in at least the risk step's number of the last
                WEEKS_LOOKED_AT complete calendar weeks (Monday 00:00 UTC)
  4  benchmark  ahead of its benchmark (BTC, SPY or the blend) over the period
  5  drawdown   max drawdown at most the risk step's limit, and not deeper than
                the backtest band's 95th percentile dip where there is one
  6  band       the forward report has it inside (or above) its backtest band;
                no band: allowed, but rule 1 then asks for more days
  7  reconcile  the Alpaca paper reconciliation clean on each of the last
                RECONCILE_DAYS days, no unexplained mismatch in the engine's log
  8  inflation  annualised net return above the higher of US CPI and euro area
                HICP year over year (lab.ops.hurdles)
  9  etf        annualised net return above the risk step's ETF hurdle; the
                S&P 500 over the same days is shown next to it for information

The risk slider (Autopilot page, saved by the engine to
reports/readiness/settings.json) picks one of RISK_PROFILES; it moves the
drawdown limit, the ETF hurdle, the weeks and the days together. Every report
says which step it used.

What it can never do: arm live, change an autopilot, place an order or move
money. It reads the engine's GET /api/state (or an exported file), the forward
report and the two public price indices, writes its own report and record
(lab.ops.guard), and sends one Telegram post when something newly meets every
rule. Only the owner can arm live.

  python -m lab.ops.readiness             the daily check
  python -m lab.ops.readiness --dry-run   print the result and the alert, post nothing

Environment as for lab.ops.learn: PYTHIA_AUTOPILOT_STATE_URL,
PYTHIA_LEARN_ORDERS_FILE; and notify's for the alert.
"""

from __future__ import annotations

import json
import math
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import report
from ..data import ROOT
from . import guard, hurdles

NAME = "readiness"
DAY_MS = 86_400_000
WEEK_MS = 7 * DAY_MS

# ---------------------------------------------------------------- the pre-registered rule
# Set on RULE_DATE (docs/LIVE-READINESS.md has the same numbers and why).
# Changing a number here means changing the doc in the same commit, with the
# new date: the rule is only worth something if it was fixed before the
# results it judges.
RULE_DATE = "2026-10-15"
MIN_CLOSED_TRADES = 20          # rule 1: closed trades on the paper record
NO_BAND_EXTRA_DAYS = 15         # rule 1: more days when the forward report has no backtest band
WEEKS_LOOKED_AT = 4             # rule 3: the last this many complete calendar weeks
BAND_ABOVE_PASSES = True        # rule 6: above the band passes (better than expected); below fails
RECONCILE_DAYS = 7              # rule 7: clean on each of the last this many days
RECONCILE_FRESH_H = 6           # rule 7: a reconciliation older than this does not count as today's
FORWARD_FRESH_H = 36            # rule 6: an older forward report does not count
ALERT_COOLDOWN_DAYS = 7         # the same autopilot is announced again at most this often
DEFAULT_RISK_STEP = 3
# The risk slider, careful (1) to bold (5): one step sets all four together.
# Bold accepts a deeper drawdown and fewer good weeks after fewer days, so it
# must also earn more: the ETF hurdle rises with the step.
RISK_PROFILES: dict[int, dict] = {
    1: {"label": "careful", "max_dd_pct": 5.0, "etf_hurdle_pct": 7.0, "min_positive_weeks": 4, "min_days": 45},
    2: {"label": "cautious", "max_dd_pct": 7.5, "etf_hurdle_pct": 8.5, "min_positive_weeks": 4, "min_days": 41},
    3: {"label": "balanced", "max_dd_pct": 10.0, "etf_hurdle_pct": 10.0, "min_positive_weeks": 3, "min_days": 38},
    4: {"label": "brave", "max_dd_pct": 17.5, "etf_hurdle_pct": 11.5, "min_positive_weeks": 3, "min_days": 34},
    5: {"label": "bold", "max_dd_pct": 25.0, "etf_hurdle_pct": 13.0, "min_positive_weeks": 2, "min_days": 30},
}

RULES = [
    ("record", "Time and trades on the Alpaca paper account"),
    ("profit", "Net P&L above zero after fees"),
    ("weeks", "Positive weeks"),
    ("benchmark", "Ahead of its benchmark"),
    ("drawdown", "Max drawdown"),
    ("band", "Inside its backtest band"),
    ("reconcile", "Alpaca reconciliation clean"),
    ("inflation", "Beats inflation"),
    ("etf", "Beats a plain ETF"),
]

# Every sentence that goes to the phone, in one place (English).
TEXT = {
    "alert_title": "Ready for a real money proposal",
    "alert_summary": "{name} meets every real money rule on the Alpaca paper account (risk step {step}, {label}).",
    "alert_footer": "Only the owner can arm live. Nothing was armed or changed.",
    "sleeve_name": "{sleeve} (sleeve of {name})",
}
# The digest line's words are in notify.READINESS_TEXT, next to the rest of the digest.


def profile(step) -> dict:
    try:
        s = int(step)
    except (TypeError, ValueError):
        s = DEFAULT_RISK_STEP
    s = s if s in RISK_PROFILES else DEFAULT_RISK_STEP
    return {"step": s, **RISK_PROFILES[s]}


def settings_path() -> Path:
    return report.REPORTS / NAME / "settings.json"


def load_settings() -> dict:
    """The risk step the owner chose in the app; the middle step without a file."""
    try:
        s = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        s = {}
    step = s.get("risk_step", s.get("riskStep")) if isinstance(s, dict) else None
    return profile(step)


# ---------------------------------------------------------------- small helpers

def _date(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _read_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def value_at(points: list[tuple[int, float]], ms: int) -> float | None:
    """The last value at or before ms; points sorted by time."""
    best = None
    for t, v in points:
        if t <= ms:
            best = v
        else:
            break
    return best


def max_drawdown_pct(points: list[tuple[int, float]]) -> float:
    peak, worst = None, 0.0
    for _, v in points:
        if v is None or v <= 0:
            continue
        peak = v if peak is None or v > peak else peak
        worst = max(worst, (1 - v / peak) * 100)
    return worst


def annualised_pct(ret_pct: float, days: float) -> float | None:
    """A return over `days` as a yearly rate, compounded. Noisy below a few months."""
    if days < 1:
        return None
    g = 1 + ret_pct / 100
    if g <= 0:
        return -100.0
    return (g ** (365.0 / days) - 1) * 100


def last_weeks(now_ms: int, n: int = WEEKS_LOOKED_AT) -> list[tuple[int, int]]:
    """The last n complete calendar weeks, Monday 00:00 UTC to Monday, oldest first."""
    d = datetime.fromtimestamp(now_ms / 1000, timezone.utc)
    monday = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - timedelta(days=d.weekday())
    end = int(monday.timestamp() * 1000)
    return [(end - (n - i) * WEEK_MS, end - (n - i - 1) * WEEK_MS) for i in range(n)]


def weekly(points: list[tuple[int, float]], since_ms: int, now_ms: int) -> list[dict]:
    """Each of the last complete weeks: its change in value, from the later of
    its Monday and the start. A week that ended before the start has none."""
    out = []
    for ws, we in last_weeks(now_ms):
        row = {"week": _date(ws), "change": None, "positive": False}
        if we > since_ms:
            a, b = value_at(points, max(ws, since_ms)), value_at(points, we)
            if a is not None and b is not None:
                row["change"] = b - a
                row["positive"] = b - a > 0
        out.append(row)
    return out


# ---------------------------------------------------------------- the inputs

def on_alpaca_paper(ap: dict, live: dict) -> bool:
    """A demo autopilot whose orders go to the Alpaca paper account."""
    cfg = ap.get("config") or {}
    if cfg.get("mode") != "demo":
        return False
    venue = str(cfg.get("venue") or "").lower()
    if venue == "alpaca":
        return True
    return str((live or {}).get("demoExchange") or "").lower() == "alpaca"


def forward_row(forward: dict | None, ap_id: str, started_ms: int) -> dict | None:
    for a in (forward or {}).get("autopilots") or []:
        if a.get("name") == ap_id and (a.get("started_ms") is None or int(a["started_ms"]) == started_ms):
            return a
    return None


UNSETTLED = (": Mismatch.", ": Untracked.", ": StrayOrder.")


def bad_reconcile_event(msg: str) -> bool:
    """An engine journal line that reports an unexplained difference."""
    if msg.startswith("Alpaca paper has an open order Pythia does not follow"):
        return True
    return msg.startswith("Alpaca paper reconcile ") and any(u in msg for u in UNSETTLED)


def reconcile_today(live: dict | None, now_ms: int) -> dict:
    d = (live or {}).get("demoReconcile") or None
    if not d:
        return {"checked_at": None, "mismatches": None, "fresh": False, "error": "no reconciliation reported"}
    at = int(d.get("checkedAt") or 0)
    return {"checked_at": at or None, "mismatches": int(d.get("mismatches") or 0),
            "fresh": bool(at) and now_ms - at <= RECONCILE_FRESH_H * 3_600_000, "error": d.get("error")}


def reconcile_rule(history: list[dict], events: list[dict], now_ms: int) -> dict:
    """Clean on each of the last RECONCILE_DAYS days (the daily records of this
    job, today's included) and no unsettled finding in the engine's log."""
    since = now_ms - RECONCILE_DAYS * DAY_MS
    days_clean, days_bad = set(), set()
    for h in history:
        if int(h.get("ts_ms") or 0) <= since:
            continue
        r = h.get("reconcile") or {}
        if r.get("fresh") and r.get("mismatches") == 0:
            days_clean.add(h["date"])
        elif r.get("fresh"):
            days_bad.add(h["date"])
    bad = [e for e in events or [] if int(e.get("ts") or 0) > since and bad_reconcile_event(str(e.get("message") or ""))]
    clean = len(days_clean - days_bad)
    ok = clean >= RECONCILE_DAYS and not days_bad and not bad
    if bad:
        detail = f"{len(bad)} unexplained finding{'s' if len(bad) != 1 else ''} in the last {RECONCILE_DAYS} days: " \
                 + str(bad[0].get("message"))[:160]
    elif days_bad:
        detail = f"differences on {', '.join(sorted(days_bad))}"
    else:
        detail = f"clean on {clean} of the last {RECONCILE_DAYS} days"
    return {"pass": ok, "value": f"{clean}/{RECONCILE_DAYS} days", "detail": detail,
            "days_to_go": 0 if ok or bad or days_bad else RECONCILE_DAYS - clean}


# ---------------------------------------------------------------- the record of this job

def history_path() -> Path:
    return ROOT / NAME / "history.jsonl"


def read_history() -> list[dict]:
    p = history_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def snapshot(state: dict, now_ms: int) -> dict:
    """Today's numbers of every autopilot and sleeve, for the weeks and
    drawdowns of tomorrow, keyed by id with its start (a restart is a new run)."""
    aps = {}
    for ap in state.get("autopilots") or []:
        cfg = ap.get("config") or {}
        b = ap.get("benchmark") or {}
        aps[str(cfg.get("id"))] = {
            "started_ms": ap.get("startedMs"), "equity": _num(ap.get("equity")), "pnl": _num(ap.get("pnl")),
            "trades": ap.get("trades"), "bench_pct": _num(b.get("returnPct")),
            "sleeves": {str(s.get("strategyId")): {"pnl": _num(s.get("pnl")), "trades": s.get("trades"),
                                                     "weight": _num(s.get("weight"))}
                        for s in ap.get("bySleeve") or []}}
    return {"date": _date(now_ms), "ts_ms": now_ms, "autopilots": aps,
            "reconcile": reconcile_today(state.get("live"), now_ms)}


def run_rows(history: list[dict], ap_id: str, started_ms: int) -> list[tuple[int, dict]]:
    return [(int(h["ts_ms"]), h["autopilots"][ap_id]) for h in history
            if ap_id in (h.get("autopilots") or {}) and h["autopilots"][ap_id].get("started_ms") == started_ms]


# ---------------------------------------------------------------- the rule, one unit at a time

def _rule(rid: str, ok: bool, value: str, need: str, detail: str = "") -> dict:
    return {"id": rid, "label": dict(RULES)[rid], "pass": bool(ok), "value": value, "need": need, "detail": detail}


def _pct(v, dp: int = 2) -> str:
    return "n/a" if v is None else f"{v:+.{dp}f} %"


def _money(v) -> str:
    return "n/a" if v is None else f"{v:+,.2f} $"


def judge(u: dict, prof: dict, ctx: dict) -> dict:
    """Every rule for one unit (an autopilot or a sleeve), from the numbers
    collected for it. `u` carries: days, trades, on_account, pnl, capital,
    ret_pct, bench (name, return, excess or None), points (value series),
    since_ms, dd_engine, band (dict or None), band_status, forward_ok, forward_detail."""
    has_band = u.get("band") is not None
    need_days = prof["min_days"] + (0 if has_band else NO_BAND_EXTRA_DAYS)
    days, trades = u["days"], u["trades"]
    rules = []

    rec_ok = u["on_account"] and days >= need_days and trades >= MIN_CLOSED_TRADES
    rec_detail = "" if u["on_account"] else "not on the Alpaca paper account (demo mode on Alpaca only)"
    if u["on_account"] and not has_band:
        rec_detail = f"no backtest band, so {NO_BAND_EXTRA_DAYS} more days"
    rules.append(_rule("record", rec_ok, f"{days:.1f} days, {trades} trades",
                       f"{need_days} days, {MIN_CLOSED_TRADES} trades", rec_detail))

    pnl = u["pnl"]
    rules.append(_rule("profit", pnl is not None and pnl > 0, "n/a" if pnl is None else f"{pnl:+,.2f} $", "> 0 $",
                       f"{_pct(u['ret_pct'])} on {u['capital']:,.0f} $" if u.get("capital") else ""))

    wk = weekly(u["points"], u["since_ms"], ctx["now_ms"])
    pos = sum(w["positive"] for w in wk)
    rules.append(_rule("weeks", pos >= prof["min_positive_weeks"], f"{pos} of {len(wk)}",
                       f"{prof['min_positive_weeks']} of {WEEKS_LOOKED_AT}",
                       " · ".join(f"{w['week']} {_money(w['change'])}" for w in wk)))

    b = u.get("bench")
    if b is None or b.get("excess") is None:
        rules.append(_rule("benchmark", False, "unknown", "> 0 pts",
                           (b or {}).get("why") or "no benchmark return for this period, so it cannot be judged"))
    else:
        rules.append(_rule("benchmark", b["excess"] > 0, f"{b['excess']:+.2f} pts", "> 0 pts",
                           f"{_pct(u['ret_pct'])} against {b['name']} {_pct(b['return'])}"))

    dd = max(max_drawdown_pct(u["points"]), u.get("dd_engine") or 0.0)
    band_dd = (u.get("band") or {}).get("dd_p95_pct")
    limit = prof["max_dd_pct"] if band_dd is None else min(prof["max_dd_pct"], band_dd)
    rules.append(_rule("drawdown", dd <= limit + 1e-9, f"{dd:.2f} %", f"<= {limit:.2f} %",
                       f"risk step limit {prof['max_dd_pct']:.1f} %"
                       + (f", backtest band dip {band_dd:.2f} %" if band_dd is not None else "")))

    rules.append(_rule("band", u["forward_ok"], u["band_status"], "inside" + (" or above" if BAND_ABOVE_PASSES else ""),
                       u.get("forward_detail") or ""))

    rules.append(_rule("reconcile", ctx["reconcile"]["pass"], ctx["reconcile"]["value"], f"{RECONCILE_DAYS}/{RECONCILE_DAYS} days",
                       ctx["reconcile"]["detail"]))

    ann = annualised_pct(u["ret_pct"], days) if u["ret_pct"] is not None else None
    infl = ctx["inflation"]
    if infl.get("pct") is None:
        rules.append(_rule("inflation", False, _pct(ann), "unknown", "no inflation figure could be read or was cached"))
    else:
        src = f"{infl['source']} {infl['month']}" + (" (cached)" if infl.get("cached") else "")
        rules.append(_rule("inflation", ann is not None and ann > infl["pct"], f"{_pct(ann)} a year",
                           f"> {infl['pct']:.2f} % a year", f"{src}; the higher of US CPI and euro area HICP"))

    idx = hurdles.index_return(ctx.get("sp500"), u["since_ms"], ctx["now_ms"])
    rules.append(_rule("etf", ann is not None and ann > prof["etf_hurdle_pct"], f"{_pct(ann)} a year",
                       f"> {prof['etf_hurdle_pct']:.1f} % a year",
                       f"S&P 500 over the same days {_pct(idx)} (price only, for information)"))

    passed = sum(r["pass"] for r in rules)
    togo = max(0.0, need_days - days) if u["on_account"] else None
    if togo is not None:
        togo = max(togo, ctx["reconcile"].get("days_to_go") or 0)
    return {"rules": rules, "passed": passed, "total": len(rules), "ready": passed == len(rules),
            "days_to_go": None if togo is None else int(math.ceil(togo)), "need_days": need_days,
            "annualised_pct": ann, "sp500_pct": idx, "max_dd_pct": dd, "positive_weeks": pos, "weeks": wk}


def autopilot_unit(ap: dict, live: dict, forward: dict | None, history: list[dict], now_ms: int) -> dict:
    cfg = ap.get("config") or {}
    ap_id = str(cfg.get("id"))
    started = int(ap.get("startedMs") or now_ms)
    end = int(ap.get("stoppedMs") or now_ms)
    capital = _num(ap.get("startCapital")) or _num(cfg.get("capitalUsd")) or 0.0
    equity = _num(ap.get("equity"))
    pnl = _num(ap.get("pnl"))
    if pnl is None and equity is not None and capital:
        pnl = equity - capital
    ret = pnl / capital * 100 if capital and pnl is not None else None
    pts = [(started, capital)] if capital else []
    for row in ap.get("history") or []:
        try:
            t, v = int(row[0]), float(row[1])
        except (TypeError, ValueError, IndexError):
            continue
        if t >= started:
            pts.append((t, v))
    pts += [(t, r["equity"]) for t, r in run_rows(history, ap_id, started) if r.get("equity") is not None]
    if equity is not None:
        pts.append((end, equity))
    pts.sort(key=lambda p: p[0])

    b = ap.get("benchmark") or None
    bench = None
    if b:
        r = _num(b.get("returnPct"))
        ex = _num(b.get("excessPct"))
        if ex is None and r is not None and ret is not None:
            ex = ret - r
        bench = {"name": b.get("name") or b.get("symbol") or "benchmark", "return": r,
                 "excess": ex if r is not None else None,
                 "why": b.get("note") or ("the benchmark's start price is still being looked for" if r is None else None)}

    fwd_fresh = forward is not None and now_ms - int(forward.get("generated_ms") or 0) <= FORWARD_FRESH_H * 3_600_000
    row = forward_row(forward, ap_id, started) if fwd_fresh else None
    band = (row or {}).get("expected") or None
    position = (row or {}).get("position")
    if not fwd_fresh:
        f_ok, f_status, f_detail = False, "no report", "no forward report from the last 36 hours"
    elif row is None:
        f_ok, f_status, f_detail = False, "not listed", "the forward report does not list this run"
    elif band is None:
        f_ok, f_status, f_detail = True, "no band", f"no backtest band; it needs {NO_BAND_EXTRA_DAYS} more days instead"
    else:
        f_ok = position == "inside" or (BAND_ABOVE_PASSES and position == "above")
        f_status = position or "unknown"
        f_detail = f"band {band.get('low_pct', 0):+.2f} to {band.get('high_pct', 0):+.2f} % ({band.get('method', '?')})"
    return {"kind": "autopilot", "key": f"autopilot:{ap_id}:{started}", "id": ap_id,
            "name": cfg.get("name") or "Autopilot", "parent": None, "mode": cfg.get("mode"), "state": ap.get("state"),
            "started_ms": started, "since_ms": started, "days": max(end - started, 0) / DAY_MS,
            "trades": int(ap.get("trades") or 0), "on_account": on_alpaca_paper(ap, live),
            "capital": capital, "pnl": pnl, "ret_pct": ret, "fees": _num(ap.get("fees")), "bench": bench, "points": pts,
            "dd_engine": max(_num(ap.get("maxDrawdownPct")) or 0.0, _num(ap.get("drawdownPct")) or 0.0),
            "band": band if fwd_fresh and row is not None else None, "band_status": f_status, "forward_ok": f_ok,
            "forward_detail": f_detail}


def sleeve_units(ap: dict, parent: dict, history: list[dict], now_ms: int) -> list[dict]:
    """The sleeves of an autopilot with several, each judged on its own P&L.

    A sleeve's record starts when this job first saw it in this run, or at
    the run's start when it was there in the job's first look within a day of
    the start: a sleeve a re-pick added later has not been there all along.
    Its value series is its budget (weight times the start amount) plus its
    P&L, from this job's daily records. Its benchmark is the autopilot's over
    the sleeve's own days. It has no backtest band of its own."""
    sleeves = [s for s in ap.get("bySleeve") or [] if not s.get("dropped") and (_num(s.get("weight")) or 0) > 0]
    if len(sleeves) < 2:
        return []
    started, ap_id = parent["started_ms"], parent["id"]
    rows = run_rows(history, ap_id, started)
    out = []
    for s in sleeves:
        sid = str(s.get("strategyId"))
        seen = [(t, r) for t, r in rows if sid in (r.get("sleeves") or {})]
        if seen and rows and seen[0][0] == rows[0][0] and seen[0][0] - started <= DAY_MS:
            since, pnl0, bench0 = started, 0.0, 0.0
        elif seen:
            since = seen[0][0]
            pnl0 = seen[0][1]["sleeves"][sid].get("pnl") or 0.0
            bench0 = seen[0][1].get("bench_pct")
        else:
            since, pnl0, bench0 = now_ms, _num(s.get("pnl")) or 0.0, (parent.get("bench") or {}).get("return")
        budget = (_num(s.get("weight")) or 0) * (parent["capital"] or 0)
        pnl_now = _num(s.get("pnl"))
        pnl = None if pnl_now is None else pnl_now - pnl0
        ret = pnl / budget * 100 if budget and pnl is not None else None
        pts = [(since, budget)] + [(t, budget + (r["sleeves"][sid].get("pnl") or 0.0) - pnl0) for t, r in seen
                                   if t > since]
        if pnl is not None:
            pts.append((now_ms, budget + pnl))
        pb = parent.get("bench") or {}
        bench = None
        if pb.get("return") is not None and bench0 is not None and ret is not None:
            br = ((1 + pb["return"] / 100) / (1 + bench0 / 100) - 1) * 100
            bench = {"name": pb["name"], "return": br, "excess": ret - br}
        out.append({"kind": "sleeve", "key": f"sleeve:{ap_id}:{started}:{sid}", "id": sid,
                    "name": TEXT["sleeve_name"].format(sleeve=s.get("name") or sid, name=parent["name"]),
                    "parent": ap_id, "mode": parent["mode"], "state": parent["state"], "started_ms": started,
                    "since_ms": since, "days": max(now_ms - since, 0) / DAY_MS, "trades": int(s.get("trades") or 0),
                    "on_account": parent["on_account"], "capital": budget, "pnl": pnl, "ret_pct": ret, "fees": None,
                    "bench": bench, "points": pts, "dd_engine": 0.0, "band": None, "band_status": "no band",
                    "forward_ok": True, "forward_detail": "a sleeve has no backtest band of its own"})
    return out


# ---------------------------------------------------------------- the alert

def alert_card(item: dict, prof: dict):
    from . import notify
    rows = [(r["label"], r["value"], 1) for r in item["rules"]]
    return notify.Card("🟢", TEXT["alert_title"],
                       TEXT["alert_summary"].format(name=item["name"], step=prof["step"], label=prof["label"]),
                       [notify.Rows(rows)], TEXT["alert_footer"])


def announce(items: list[dict], prof: dict, st: dict, now_ms: int, dry_run: bool, sender=None) -> list[dict]:
    """One post per unit that newly meets every rule; nothing else happens."""
    from . import notify
    sent = []
    prev = set(st.get("ready") or [])
    alerted = st.setdefault("alerted", {})
    for it in items:
        if not it["ready"] or it["key"] in prev:
            continue
        last = alerted.get(it["key"])
        if last and now_ms - int(last) < ALERT_COOLDOWN_DAYS * DAY_MS:
            continue
        res = notify.send("autopilot", [alert_card(it, prof)], now=now_ms, dry_run=dry_run, poster=sender)
        done = res.get("delivered") or res.get("reason") in ("quiet", "off", "no destination")
        if done and not dry_run:
            alerted[it["key"]] = now_ms
        sent.append({"key": it["key"], "name": it["name"], "delivered": bool(res.get("delivered")),
                     "reason": res.get("reason"), "error": res.get("error")})
    # Ready now and announced (or not newly ready): tomorrow it is not new.
    st["ready"] = sorted(it["key"] for it in items if it["ready"] and (it["key"] in prev or it["key"] in alerted))
    return sent


# ---------------------------------------------------------------- the report

def headline(items: list[dict], prof: dict) -> str:
    aps = [i for i in items if i["on_account"]]
    if not aps:
        return f"No autopilot runs on the Alpaca paper account yet, so none can be proposed for real money (risk step {prof['step']}, {prof['label']})."
    ready = [i for i in aps if i["ready"]]
    if ready:
        return (f"{', '.join(i['name'] for i in ready)} meet{'s' if len(ready) == 1 else ''} every real money rule "
                f"(risk step {prof['step']}, {prof['label']}). Only the owner can arm live.")
    best = max(aps, key=lambda i: (i["passed"], -(i["days_to_go"] or 0)))
    return (f"None ready for real money yet. Closest: {best['name']}, {best['passed']} of {best['total']} rules"
            + (f", {best['days_to_go']} days to go at the earliest" if best["days_to_go"] else "")
            + f" (risk step {prof['step']}, {prof['label']}).")


def digest_text(rep: dict | None) -> str:
    """The daily digest's line (its words live in notify.READINESS_TEXT)."""
    from . import notify
    return notify.readiness_text(rep)


def feed_items(items: list[dict]) -> list[dict]:
    out = []
    for i in items:
        failing = [r["label"] for r in i["rules"] if not r["pass"]]
        out.append({"label": i["name"],
                    "value": "ready" if i["ready"] else f"{i['passed']}/{i['total']}",
                    "status": "ok" if i["ready"] else ("watch" if i["on_account"] else "bad"),
                    "detail": ("Meets every rule; only the owner can arm live." if i["ready"] else
                               ("Not on the Alpaca paper account." if not i["on_account"] else
                                "Missing: " + ", ".join(failing)
                                + (f". {i['days_to_go']} days to go at the earliest." if i["days_to_go"] else "."))),
                    "importance": 90 if i["ready"] else (40 if i["kind"] == "autopilot" else 20)})
    return out


def markdown(d: dict) -> str:
    p = d["profile"]
    lines = ["# Real money readiness\n", f"{d['generated']}. {d['headline']}\n",
             f"Rule of {RULE_DATE} (docs/LIVE-READINESS.md), risk step {p['step']} ({p['label']}): "
             f"drawdown at most {p['max_dd_pct']} %, ETF hurdle {p['etf_hurdle_pct']} % a year, "
             f"{p['min_positive_weeks']} of {WEEKS_LOOKED_AT} weeks positive, {p['min_days']} days. "
             "This check never arms or changes anything.\n"]
    inf = d["inflation"]
    lines.append(f"Inflation used: {inf.get('pct')} % ({inf.get('source')}, {inf.get('month')}"
                 f"{', cached' if inf.get('cached') else ''}).\n")
    for i in d["autopilots"]:
        lines.append(f"## {i['name']}\n")
        lines.append(f"{'Ready' if i['ready'] else 'Not ready'}: {i['passed']} of {i['total']} rules"
                     + (f", {i['days_to_go']} days to go at the earliest" if i.get("days_to_go") else "") + ".\n")
        lines.append(report.table([{"rule": r["label"], "pass": "yes" if r["pass"] else "no", "value": r["value"],
                                    "need": r["need"], "detail": r["detail"]} for r in i["rules"]],
                                  ["rule", "pass", "value", "need", "detail"]))
    if not d["autopilots"]:
        lines.append(f"{d['engine'].get('error') or 'No active autopilot.'}\n")
    return "\n".join(lines) + "\n"


def _public(u: dict, verdict: dict) -> dict:
    keep = ("kind", "key", "id", "name", "parent", "mode", "state", "started_ms", "since_ms", "days", "trades",
            "on_account", "capital", "pnl", "ret_pct", "fees")
    out = {k: u.get(k) for k in keep}
    out["benchmark"] = u.get("bench")
    out.update({k: v for k, v in verdict.items()})
    return out


def engine_state() -> tuple[dict | None, str, str | None]:
    from .learn import engine_state as f
    return f()


def run(now_ms: int | None = None, state: dict | None = None, forward: dict | None = None, macro: dict | None = None,
        dry_run: bool = False, sender=None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    guard.WRITTEN.clear()
    source, err = "given", None
    if state is None:
        state, source, err = engine_state()
    if forward is None:
        forward = _read_json(report.REPORTS / "forward" / "latest.json")
    if macro is None:
        try:
            macro = hurdles.load(now_ms)
        except guard.GuardError:
            raise
        except Exception as e:  # noqa: BLE001 - no inflation figure fails rule 8, it does not stop the check
            macro = {"inflation": hurdles.inflation(None, None), "sp500": None, "error": str(e)}
    prof = load_settings()
    history = read_history()
    if state is not None:
        snap = snapshot(state, now_ms)
        history = [h for h in history if h.get("date") != snap["date"]] + [snap]
        history = history[-400:]
        if not dry_run:
            guard.write_text(history_path(), "".join(json.dumps(guard.finite(h), allow_nan=False) + "\n"
                                                      for h in history))
    live = (state or {}).get("live") or {}
    ctx = {"now_ms": now_ms, "inflation": macro.get("inflation") or {}, "sp500": macro.get("sp500"),
           "reconcile": reconcile_rule(history, (state or {}).get("events") or [], now_ms)}
    units = []
    for ap in (state or {}).get("autopilots") or []:
        cfg = ap.get("config") or {}
        if ap.get("state") not in ("running", "paused") or cfg.get("mode") == "live":
            continue
        u = autopilot_unit(ap, live, forward, history, now_ms)
        units.append(u)
        units += sleeve_units(ap, u, history, now_ms)
    items = [_public(u, judge(u, prof, ctx)) for u in units]
    items.sort(key=lambda i: (not i["on_account"], i["parent"] or i["id"], i["kind"] != "autopilot"))

    st = _read_json(ROOT / NAME / "state.json") or {}
    alerts = announce(items, prof, st, now_ms, dry_run, sender)
    if not dry_run:
        guard.write_json(ROOT / NAME / "state.json", st)

    data = {"generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "generated_ms": now_ms, "rule_date": RULE_DATE, "profile": prof,
            "profiles": [{"step": k, **v} for k, v in RISK_PROFILES.items()],
            "constants": {"min_closed_trades": MIN_CLOSED_TRADES, "no_band_extra_days": NO_BAND_EXTRA_DAYS,
                          "weeks_looked_at": WEEKS_LOOKED_AT, "reconcile_days": RECONCILE_DAYS},
            "inflation": ctx["inflation"], "reconcile": ctx["reconcile"], "autopilots": items, "alerts": alerts,
            "engine": {"source": source, "reachable": state is not None, "error": err}}
    data["headline"] = headline(items, prof)
    ready = any(i["ready"] for i in items)
    data.update(report.feed_header("Real money readiness", "ok" if ready or not items else "watch",
                                   data["headline"], feed_items(items), now_ms))
    data = guard.finite(data)
    if not dry_run:
        guard.check_write(report.REPORTS / NAME / "latest.json")
        report.write(NAME, markdown(data), data)
    else:
        print(markdown(data))
    return data


def main() -> int:
    run(dry_run="--dry-run" in sys.argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
