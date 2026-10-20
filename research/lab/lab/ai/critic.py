"""The strategy critic: every morning, for each autopilot, one short Claude call
(Haiku 5.5, through the Batches API at half price) checks the last day's
orders against the autopilot's own rules and the market: churn (buying and
selling the same coin back and forth), fees out of line with what the cost
model expects, a stop that should have fired and did not, sizing against the
sleeve weights, anything else that looks wrong.

The numbers it is shown are computed here first (orders, round trips, side
flips, fees in bps of what traded, realised against modelled cost, the
equity's low against the stop floor, the drawdown against the trailing rule),
so every finding can be checked against them:

  confirmed       the numbers show what the finding says (churn, fees, stop)
  not confirmed   the numbers do not
  unchecked       a kind the numbers cannot settle (sizing, drift, rules, other)

The owner settles the rest from the chat: /real ID or /notreal ID (lab.ai.chat)
writes <data>/ai/critic_labels.jsonl. Every finding goes to
<data>/ai/critic.jsonl, and reports/ai/critic_score.json scores the critic
over time: of the findings decided (by the owner, else by the numbers), how
many were real.

A Telegram card (category "autopilot") goes out only when there is a finding
of medium or high severity; low ones are logged. The critic reads; it never
changes, pauses or stops anything.

  python -m lab.ai.critic             daily (jobs.yaml: ai-critic)
  python -m lab.ai.critic --dry-run   print the prompts, call nothing
  python -m lab.ai.critic --force     again today (more calls)
  python -m lab.ai.critic --score     rescore only, no call
"""

from __future__ import annotations

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from ..ops import i18n, notify
from . import engine, facts

DEFAULT_MODEL = engine.ROUTINE
DEFAULT_EFFORT = "medium"
MAX_TOKENS = 1500
BATCH_WAIT_SEC = 20 * 60
WINDOW_MS = 86_400_000
MAX_ORDER_LINES = 60
MAX_EVENT_LINES = 25
WORKERS = 4
KINDS = ("churn", "fees", "stop", "sizing", "drift", "rules", "other")
SEVERITIES = ("low", "medium", "high")
POST_FROM = "medium"
# What "confirmed" means for the kinds the numbers can settle.
CHURN_ROUND_TRIPS = 2
CHURN_FLIPS = 3
FEE_RATIO = 1.5
FEE_BPS_OF_EQUITY = 20.0

SYSTEM = """You are the strategy critic of Pythia, an automated trading system that runs autopilots on paper \
or demo money. Each morning you check one autopilot's last day: its orders against its own rules and against \
the market. You look for what a careful risk manager would flag:
- churn: buying and selling the same market back and forth, round trips that pay fees for nothing;
- fees: fees or realised costs out of line with what the cost model expected or with the equity;
- stop: a stop rule (max loss, trailing stop, the stop floor) that the numbers say should have fired but the \
autopilot is still running, or a stop that fired for no visible reason;
- sizing: positions or orders far from what the sleeve weights and the capital imply;
- drift: realised slippage far above the modelled slippage, or fills far from the market;
- rules: anything else against the autopilot's stated rules;
- other: something else that looks wrong.

You get the autopilot's rules, its state, numbers computed from its orders (trust these over your own \
arithmetic), its orders and events of the last day, and how the markets it trades moved. That is all you know. \
Do not invent orders, prices or rules. A quiet day with nothing wrong is the normal and best answer: then ok is \
true and findings is empty. Flag only what the numbers support, quote the numbers in evidence, and say in check \
what the owner should look at. severity: high when money is at risk now (a stop that should have fired), medium \
when it costs money over time (churn, fees), low for something to keep an eye on. At most three findings, one \
plain sentence each for claim, evidence and check, no em dashes. You never recommend trades; you only point \
at what looks wrong. Answer with the JSON object only."""

SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "claim": {"type": "string"},
                    "evidence": {"type": "string"},
                    "check": {"type": "string"},
                },
                "required": ["kind", "severity", "claim", "evidence", "check"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ok", "findings"],
    "additionalProperties": False,
}


def ai_dir() -> Path:
    return notify.data_root() / "ai"


def log_path() -> Path:
    return ai_dir() / "critic.jsonl"


def labels_path() -> Path:
    return ai_dir() / "critic_labels.jsonl"


def score_path() -> Path:
    return notify.reports_root() / "ai" / "critic_score.json"


def today(now_ms: int) -> str:
    return datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _when(ms) -> str:
    return datetime.fromtimestamp((_num(ms) or 0) / 1000, timezone.utc).strftime("%m-%d %H:%M")


def read_jsonl(p: Path) -> list[dict]:
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            v = json.loads(line)
        except ValueError:
            continue
        if isinstance(v, dict):
            out.append(v)
    return out


def append_jsonl(p: Path, rows: list[dict]) -> None:
    if not rows:
        return
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- what is checked

def autopilots_to_check(rows: list[dict], now_ms: int) -> list[tuple[dict, dict, str]]:
    """(autopilot, its engine's state, account) for every running or paused
    autopilot, and any that stopped inside the window."""
    out = []
    for r in rows:
        st = r.get("state")
        if not isinstance(st, dict):
            continue
        for a in st.get("autopilots") or []:
            s = a.get("state")
            stopped = _num(a.get("stoppedMs"))
            if s in ("running", "paused") or (stopped is not None and now_ms - stopped <= WINDOW_MS):
                out.append((a, st, r.get("account") or ""))
    return out


def ap_id(a: dict) -> str:
    return str((a.get("config") or {}).get("id") or "")


def strategy_ids(a: dict) -> set[str]:
    return {str(s.get("strategyId")) for s in a.get("bySleeve") or [] if s.get("strategyId")}


def own_orders(a: dict, state: dict, since: int, until: int) -> list[dict]:
    """The autopilot's orders in the window: its book, or one of its sleeves'
    strategies when the order names no book."""
    aid, sids = ap_id(a), strategy_ids(a)
    out = []
    for o in state.get("orders") or []:
        ts = _num(o.get("ts"))
        if ts is None or not since <= ts < until:
            continue
        book = o.get("book")
        if (book and book == aid) or (not book and o.get("strategyId") in sids):
            out.append(o)
    return sorted(out, key=lambda o: _num(o.get("ts")) or 0)


def own_events(a: dict, state: dict, since: int, until: int) -> list[dict]:
    sids, name = strategy_ids(a), str((a.get("config") or {}).get("name") or "")
    out = []
    for e in (state.get("journal") or []) + (state.get("events") or []):
        ts = _num(e.get("ts"))
        if ts is None or not since <= ts < until:
            continue
        msg = str(e.get("message") or "")
        if e.get("strategyId") in sids or (name and name in msg):
            out.append(e)
    seen, uniq = set(), []
    for e in sorted(out, key=lambda e: _num(e.get("ts")) or 0):
        k = (e.get("id"), e.get("ts"), e.get("message"))
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return uniq


def metrics(a: dict, orders: list[dict], since: int) -> dict:
    """What the orders and the state say, computed once, for the model and the check."""
    filled = [o for o in orders if str(o.get("status") or "").lower() in ("filled", "partial")]
    rejected = [o for o in orders if str(o.get("status") or "").lower() == "rejected"]
    notional, fees = 0.0, 0.0
    sides: dict[str, list[str]] = {}
    real, model = [], []
    for o in filled:
        q, px = _num(o.get("filledQty")) or _num(o.get("qty")) or 0.0, _num(o.get("avgFillPrice")) or 0.0
        notional += abs(q * px)
        fees += _num(o.get("fee")) or 0.0
        sides.setdefault(str(o.get("marketId")), []).append(str(o.get("side") or "").lower())
        r = _num(o.get("realisedCostBps"))
        m = _num(o.get("modelledCostBps"))
        if r is None:
            r, m = _num(o.get("realisedSlippageBps")), _num(o.get("modelledSlippageBps"))
        if r is not None and m is not None:
            real.append(r)
            model.append(m)
    flips = {mk: sum(1 for x, y in zip(s, s[1:]) if x != y) for mk, s in sides.items()}
    round_trips = sum(1 for s in sides.values() if "buy" in s and "sell" in s)
    equity = _num(a.get("equity")) or 0.0
    cfg = a.get("config") or {}
    stop = cfg.get("stop") or {}
    start = _num(a.get("startCapital")) or _num(cfg.get("capitalUsd")) or 0.0
    hist = [(_num(t), _num(v)) for t, v in (a.get("history") or []) if _num(t) is not None and _num(v) is not None]
    window = [v for t, v in hist if t >= since] + ([equity] if equity else [])
    low = min(window) if window else None
    peak = _num(a.get("peakEquity"))
    med = (lambda xs: sorted(xs)[len(xs) // 2] if xs else None)
    m_real, m_model = med(real), med(model)
    pnl_pct = _num(a.get("pnlPct"))
    dd = _num(a.get("drawdownPct"))
    floor = _num(a.get("floorEquity"))
    return {
        "orders": len(orders), "filled": len(filled), "rejected": len(rejected),
        "markets_traded": len(sides), "round_trips": round_trips, "max_flips": max(flips.values(), default=0),
        "notional_usd": round(notional, 2), "turnover_x": round(notional / equity, 3) if equity else None,
        "fees_usd": round(fees, 4), "fee_bps_of_traded": round(1e4 * fees / notional, 2) if notional else None,
        "fee_bps_of_equity": round(1e4 * fees / equity, 2) if equity else None,
        "median_realised_cost_bps": m_real, "median_modelled_cost_bps": m_model,
        "cost_ratio": round(m_real / m_model, 2) if m_real is not None and m_model and m_model > 1e-9 else None,
        "equity": equity, "equity_low_in_window": low, "floor_equity": floor, "peak_equity": peak,
        "below_floor": bool(floor is not None and low is not None and low <= floor),
        "drawdown_pct": dd, "trailing_pct": _num(stop.get("trailingPct")),
        "pnl_pct": pnl_pct, "max_loss_pct": _num(stop.get("maxLossPct")),
        "max_loss_usd": _num(stop.get("maxLossUsd")), "pnl_usd": round(equity - start, 2) if start else None,
        "state": a.get("state"),
    }


def stop_breached(m: dict) -> bool:
    """A stop rule the numbers say should have fired, while the autopilot runs."""
    if m.get("state") not in ("running", "paused"):
        return False
    if m.get("below_floor"):
        return True
    if m.get("trailing_pct") is not None and m.get("drawdown_pct") is not None and m["drawdown_pct"] >= m["trailing_pct"]:
        return True
    if m.get("max_loss_pct") is not None and m.get("pnl_pct") is not None and m["pnl_pct"] <= -m["max_loss_pct"]:
        return True
    if m.get("max_loss_usd") is not None and m.get("pnl_usd") is not None and m["pnl_usd"] <= -m["max_loss_usd"]:
        return True
    return False


def verify(kind: str, m: dict) -> str:
    """confirmed, not_confirmed or unchecked: does the finding hold in the numbers."""
    if kind == "churn":
        ok = m.get("round_trips", 0) >= CHURN_ROUND_TRIPS or m.get("max_flips", 0) >= CHURN_FLIPS
    elif kind == "fees":
        ratio, fe = m.get("cost_ratio"), m.get("fee_bps_of_equity")
        ok = (ratio is not None and ratio >= FEE_RATIO) or (fe is not None and fe >= FEE_BPS_OF_EQUITY)
    elif kind == "stop":
        ok = stop_breached(m)
    else:
        return "unchecked"
    return "confirmed" if ok else "not_confirmed"


def market_lines(state: dict, orders: list[dict], a: dict) -> list[str]:
    want = {str(o.get("marketId")) for o in orders} | {str(h) for h in a.get("held") or []}
    want |= {m for s in a.get("bySleeve") or [] for m in (s.get("markets") or [])[:4]}
    out = []
    for mk in state.get("markets") or []:
        if mk.get("id") in want or str(mk.get("symbol") or "").upper().startswith("BTC/"):
            ch = _num(mk.get("change24h"))
            out.append(f"{mk.get('id')}: price {_num(mk.get('price')) or 0:,.6g}"
                       + (f", 24h {ch:+.2f} %" if ch is not None else ""))
    return out[:20]


def order_line(o: dict) -> str:
    q = _num(o.get("filledQty")) or _num(o.get("qty")) or 0.0
    px = _num(o.get("avgFillPrice")) or _num(o.get("limitPrice"))
    bits = [_when(o.get("ts")), str(o.get("side") or "?"), f"{q:.6g}", str(o.get("marketId") or "?"),
            f"at {px:,.6g}" if px else None, str(o.get("status") or "?"), str(o.get("route") or "")]
    if _num(o.get("fee")) is not None:
        bits.append(f"fee ${_num(o.get('fee')):.4f}")
    for k, label in (("realisedCostBps", "cost"), ("modelledCostBps", "modelled cost"),
                     ("realisedSlippageBps", "slippage"), ("modelledSlippageBps", "modelled slippage")):
        if _num(o.get(k)) is not None:
            bits.append(f"{label} {_num(o.get(k)):.1f} bps")
    if o.get("rejectReason"):
        bits.append(f"rejected: {o.get('rejectReason')}")
    return " ".join(b for b in bits if b)


def build_prompt(a: dict, state: dict, account: str, now_ms: int) -> tuple[str, dict]:
    since = now_ms - WINDOW_MS
    orders = own_orders(a, state, since, now_ms)
    m = metrics(a, orders, since)
    events = own_events(a, state, since, now_ms)
    lines = [f"WINDOW: {_when(since)} to {_when(now_ms)} UTC (the last 24 hours).", "",
             "AUTOPILOT:", "- " + facts.autopilot_detail({**a, "account": account} if account else a), "",
             "NUMBERS FROM ITS ORDERS IN THE WINDOW (computed, trust these):"]
    lines += [f"- {k}: {v}" for k, v in m.items() if v is not None]
    lines += ["", f"ORDERS ({len(orders)}, oldest first):"]
    lines += ["- " + order_line(o) for o in orders[-MAX_ORDER_LINES:]] or ["- none"]
    if len(orders) > MAX_ORDER_LINES:
        lines.append(f"- ({len(orders) - MAX_ORDER_LINES} earlier orders not listed)")
    lines += ["", "EVENTS:"] + (["- " + f"{_when(e.get('ts'))} {e.get('kind')}: {notify.short(notify.nodash(str(e.get('message'))), 200)}"
                                  for e in events[-MAX_EVENT_LINES:]] or ["- none"])
    mk = market_lines(state, orders, a)
    if mk:
        lines += ["", "MARKETS:"] + ["- " + x for x in mk]
    return "\n".join(lines), m


# ---------------------------------------------------------------- the call and the log

def ask(prompt: str, poster=None) -> dict:
    model, effort = engine.model_for("critic", DEFAULT_MODEL), engine.effort_for("critic", DEFAULT_EFFORT)
    try:
        return engine.complete("critic", SYSTEM, prompt, MAX_TOKENS, model=model, schema=SCHEMA, effort=effort,
                               batch=True, batch_wait_sec=BATCH_WAIT_SEC, poster=poster)
    except engine.AiError as e:
        if e.kind != "timeout":
            raise
    return engine.complete("critic-direct", SYSTEM, prompt, MAX_TOKENS, model=model, schema=SCHEMA, effort=effort,
                           batch=False, poster=poster)


def parse_findings(obj) -> list[dict]:
    if not isinstance(obj, dict):
        return []
    out = []
    for f in (obj.get("findings") or [])[:3]:
        if not isinstance(f, dict) or not str(f.get("claim") or "").strip():
            continue
        kind = f.get("kind") if f.get("kind") in KINDS else "other"
        sev = f.get("severity") if f.get("severity") in SEVERITIES else "low"
        out.append({"kind": kind, "severity": sev,
                    **{k: notify.short(notify.nodash(" ".join(str(f.get(k) or "").split())), 300)
                       for k in ("claim", "evidence", "check")}})
    return out


def next_ids(day: str, n: int, existing: list[dict]) -> list[str]:
    """Short ids the owner can type: MMDD-k, counting on from the day's last."""
    pre = day[5:7] + day[8:10]
    used = [int(str(r.get("id", "")).split("-")[-1]) for r in existing
            if str(r.get("id", "")).startswith(pre + "-") and str(r.get("id", "")).split("-")[-1].isdigit()]
    start = max(used, default=0) + 1
    return [f"{pre}-{k}" for k in range(start, start + n)]


def label(fid: str, verdict: str, now_ms: int | None = None, source: str = "telegram") -> bool:
    """The owner's verdict on a finding (real or notreal). False when there is no such finding."""
    fid = str(fid or "").strip()
    if verdict not in ("real", "notreal") or not any(r.get("id") == fid for r in read_jsonl(log_path())):
        return False
    append_jsonl(labels_path(), [{"id": fid, "verdict": verdict, "ts": now_ms or notify.clock_ms(), "source": source}])
    rescore(now_ms)
    return True


def rescore(now_ms: int | None = None) -> dict:
    """reports/ai/critic_score.json from the log and the owner's labels."""
    now = now_ms or notify.clock_ms()
    rows = read_jsonl(log_path())
    labels: dict[str, str] = {}
    for lb in read_jsonl(labels_path()):
        labels[str(lb.get("id"))] = str(lb.get("verdict"))
    runs = read_jsonl(ai_dir() / "critic_runs.jsonl")
    real = notreal = undecided = 0
    by_kind: dict[str, dict] = {}
    for r in rows:
        v = labels.get(r.get("id"))
        decided = v or {"confirmed": "real", "not_confirmed": "notreal"}.get(r.get("auto"))
        k = by_kind.setdefault(r.get("kind") or "other", {"n": 0, "real": 0, "notreal": 0, "undecided": 0})
        k["n"] += 1
        if decided == "real":
            real += 1
            k["real"] += 1
        elif decided == "notreal":
            notreal += 1
            k["notreal"] += 1
        else:
            undecided += 1
            k["undecided"] += 1
    checks = sum(int(_num(r.get("checked")) or 0) for r in runs)
    precision = real / (real + notreal) if real + notreal else None
    if not rows:
        verdict = f"No findings yet in {len(runs)} runs ({checks} autopilot days checked)."
    else:
        verdict = (f"{len(rows)} findings in {len(runs)} runs ({checks} autopilot days checked); "
                   f"{real} of {real + notreal} decided were real"
                   + (f" ({100 * precision:.0f} %)" if precision is not None else "")
                   + f", {undecided} undecided. The owner's /real and /notreal decide over the numbers.")
    data = {"generated_ms": now, "findings": len(rows), "runs": len(runs), "autopilot_days": checks,
            "real": real, "notreal": notreal, "undecided": undecided, "precision": precision,
            "owner_labels": len(labels), "by_kind": by_kind, "verdict": verdict,
            "recent": [{**r, "label": labels.get(r.get("id"))} for r in rows[-30:]]}
    notify.write_json(score_path(), data)
    return data


def card(found: list[dict], lang: str) -> notify.Card:
    words = {"confirmed": "critic_confirmed", "not_confirmed": "critic_unconfirmed", "unchecked": "critic_unchecked"}
    parts = [notify.Line(f"{r['autopilot']}: {r['claim']} {r['evidence']} ({i18n.t(words[r['auto']], lang)})",
                         f"[{r['id']}] {i18n.word(r['kind'], lang)}") for r in found]
    return notify.Card("🔍", i18n.t("critic_title", lang, n=len(found)), i18n.t("critic_summary", lang), parts)


def run(now_ms: int | None = None, dry_run: bool = False, force: bool = False, rows: list[dict] | None = None,
        poster=None, send_poster=None) -> int:
    now = now_ms or notify.clock_ms()
    day = today(now)
    runs = read_jsonl(ai_dir() / "critic_runs.jsonl")
    if any(r.get("date") == day for r in runs) and not force and not dry_run:
        notify.say(f"the critic ran for {day}; nothing called (--force for another)")
        rescore(now)
        return 0
    if rows is None:
        rows = notify.engine_states()
    todo = autopilots_to_check(rows, now)
    if not todo:
        notify.say("no autopilot to check")
        return 0
    prompts = [(a, acc, *build_prompt(a, st, acc, now)) for a, st, acc in todo]
    if dry_run:
        for a, acc, p, _ in prompts:
            notify.say(SYSTEM + "\n\n" + p + "\n")
        chars = sum(len(SYSTEM) + len(p) for _, _, p, _ in prompts)
        notify.say(f"[dry run] {len(prompts)} calls, about {chars // 4:,} input tokens in all; nothing called")
        return 0

    def one(item):
        a, acc, p, m = item
        try:
            return item, ask(p, poster), None
        except engine.AiError as e:
            return item, None, e

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        results = list(ex.map(one, prompts))
    existing = read_jsonl(log_path())
    new, failed, cost, budget_stop = [], 0, 0.0, False
    for (a, acc, _, m), answer, err in results:
        if err is not None:
            failed += err.kind not in ("budget", "nokey")
            budget_stop |= err.kind in ("budget", "nokey")
            notify.say(f"critic: {(a.get('config') or {}).get('name')}: {err}", err=err.kind not in ("budget", "nokey"))
            continue
        cost += float(answer.get("costUsd") or 0.0)
        name = (a.get("config") or {}).get("name") or ap_id(a)
        for f in parse_findings(answer.get("json")):
            new.append({"date": day, "made_ms": now, "autopilot": f"{name} · {acc}" if acc else name,
                        "autopilot_id": ap_id(a), "account": acc, **f, "auto": verify(f["kind"], m),
                        "metrics": {k: v for k, v in m.items() if v is not None},
                        "model": answer.get("servedBy") or answer.get("model")})
    for r, fid in zip(new, next_ids(day, len(new), existing)):
        r["id"] = fid
    append_jsonl(log_path(), new)
    checked = sum(1 for _, ans, _ in results if ans is not None)
    append_jsonl(ai_dir() / "critic_runs.jsonl", [{"date": day, "ts": now, "checked": checked, "findings": len(new),
                                                     "failed": failed, "costUsd": round(cost, 6)}])
    sc = rescore(now)
    notify.write_json(notify.reports_root() / "ai" / "critic.json",
                      {"date": day, "generated_ms": now, "checked": checked, "findings": new, "costUsd": cost,
                       "verdict": sc["verdict"], "note": "The critic reads only; it never changes an autopilot."})
    notify.say(f"critic {day}: {checked} autopilots checked, {len(new)} findings, ${cost:.4f}. {sc['verdict']}")
    post = [r for r in new if SEVERITIES.index(r["severity"]) >= SEVERITIES.index(POST_FROM)]
    if post:
        notify.send("autopilot", card(post, notify.alert_lang()), now=now, poster=send_poster)
    if checked == 0 and budget_stop:
        return 0
    return 1 if failed and checked == 0 else 0


def main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if "--score" in argv:
        notify.say(rescore()["verdict"])
        return 0
    return run(dry_run="--dry-run" in argv, force="--force" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
