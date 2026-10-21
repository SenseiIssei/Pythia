"""What the paper autopilots pay to trade: a cost and churn audit from the engine's own state.

    python -m lab.ops.autopilot_audit [state.json ...]     print the audit as markdown
    python -m lab.ops.autopilot_audit --json [state ...]   the same numbers as JSON

Read only. With no paths it reads <data>/autopilot/state.json and
<data>/autopilot-safe/state.json (each Alpaca paper account's engine saves one).
Every order the engine keeps carries its book (the autopilot's id), its route,
the maker and taker quantity, the realised cost against the decision price
(`realisedCostBps`, fee included) and the realised slippage alone
(`realisedSlippageBps`); the difference is the fee. Per running autopilot:

  turnover     notional traded / amount / days running
  cost         fees and slippage in dollars and in bps of the amount per day,
               and per unit traded against the 35 bps the backtests charge
  trims        orders under 1 % of the amount, their count and cost share
  round trips  a coin bought and sold (or sold and bought) in the same book
               within 72 hours, the notional that came back and its cost
  rebalances   fills of one book within 30 minutes count as one rebalance
  refused      orders the venue or the risk check refused, with the reason
  vs BTC       the autopilot's return against BTC bought and held since its
               start, and how much of the gap the costs explain

Results: results/autopilot_optimization.md.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from ..data import ROOT

DAY_MS = 86_400_000
ROUND_TRIP_MS = 72 * 3_600_000
REBALANCE_GAP_MS = 30 * 60_000
TRIM_SHARE = 0.01
MODEL_BPS = 35.0
FILLED = ("filled", "partial")


def default_paths() -> list[Path]:
    return [ROOT / "autopilot" / "state.json", ROOT / "autopilot-safe" / "state.json"]


def notional(o: dict) -> float:
    q, p = float(o.get("filledQty") or 0.0), float(o.get("avgFillPrice") or 0.0)
    return q * p if q > 0 and p > 0 else 0.0


def fills_of(orders: list[dict], book: str, since_ms: int = 0) -> list[dict]:
    """The filled (or partly filled) orders of one book from since_ms on, oldest first."""
    out = [o for o in orders if o.get("book") == book and o.get("status") in FILLED and notional(o) > 0
           and int(o.get("ts") or 0) >= since_ms]
    return sorted(out, key=lambda o: int(o["ts"]))


def cost_split(o: dict) -> tuple[float, float]:
    """($ fee, $ slippage) of one fill: realisedCostBps is fee plus slippage against the decision price."""
    n = notional(o)
    total = o.get("realisedCostBps")
    slip = o.get("realisedSlippageBps")
    if total is None:
        return 0.0, 0.0
    total = float(total)
    slip = float(slip) if slip is not None else 0.0
    return n * (total - slip) / 1e4, n * slip / 1e4


def round_trips(fills: list[dict], window_ms: int = ROUND_TRIP_MS) -> dict:
    """Notional that went one way and came back within window_ms, per coin, in one book.

    Every fill is matched against the earlier fills of the other side on the same
    coin still inside the window (oldest first); the matched notional is churn:
    the book paid twice for a position it ended up not changing."""
    open_: dict[tuple[str, str], list[list[float]]] = defaultdict(list)
    matched, cost, n = 0.0, 0.0, 0
    for o in fills:
        m, side, t = o["marketId"], o["side"], int(o["ts"])
        amt = notional(o)
        fee, slip = cost_split(o)
        per = (fee + slip) / amt if amt > 0 else 0.0
        other = open_[(m, "sell" if side == "buy" else "buy")]
        while other and amt > 1e-9:
            t0, left, per0 = other[0]
            if t - t0 > window_ms:
                other.pop(0)
                continue
            take = min(left, amt)
            matched += take
            cost += take * (per + per0)
            n += 1
            amt -= take
            other[0][1] -= take
            if other[0][1] <= 1e-9:
                other.pop(0)
        if amt > 1e-9:
            open_[(m, side)].append([float(t), amt, per])
    return {"pairs": n, "notional": matched, "cost": cost}


def rebalances(fills: list[dict], gap_ms: int = REBALANCE_GAP_MS) -> list[dict]:
    """Fills of one book grouped into rebalances: a fill more than gap_ms after the last starts a new one."""
    out: list[dict] = []
    for o in fills:
        t = int(o["ts"])
        fee, slip = cost_split(o)
        if not out or t - out[-1]["last"] > gap_ms:
            out.append({"ts": t, "last": t, "orders": 0, "notional": 0.0, "cost": 0.0})
        r = out[-1]
        r["last"] = t
        r["orders"] += 1
        r["notional"] += notional(o)
        r["cost"] += fee + slip
    return out


def at_repick(reb: list[dict], start_ms: int, every_hours: float | None, slack_ms: int = 10 * 60_000) -> list[dict]:
    """The rebalances that began within slack_ms after a scheduled re-pick (start + k x every
    hours): trades the re-pick sent by itself, apart from the lab signals' own rebalances."""
    if not every_hours or every_hours <= 0:
        return []
    step = int(every_hours * 3_600_000)
    out = []
    for r in reb:
        k = (r["ts"] - start_ms) // step
        if k >= 1 and 0 <= r["ts"] - (start_ms + k * step) <= slack_ms:
            out.append(r)
    return out


def maker_by_hour(fills: list[dict]) -> dict[int, tuple[float, float]]:
    """UTC hour -> (notional, maker share) of the fills sent in that hour."""
    by: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for o in fills:
        h = int(o["ts"]) // 3_600_000 % 24
        by[h][0] += notional(o)
        by[h][1] += float(o.get("makerQty") or 0.0) * float(o.get("avgFillPrice") or 0.0)
    return {h: (v[0], v[1] / v[0] if v[0] > 0 else 0.0) for h, v in sorted(by.items())}


def clean(name: str) -> str:
    """Names saved through a wrong code page carry "Â·" for "·"."""
    return str(name).replace("Â·", "·")


def btc_price(state: dict) -> float | None:
    for key in ("crypto:BTC/USD", "alpaca:BTC/USD"):
        v = (state.get("prices") or {}).get(key)
        if isinstance(v, list) and v and v[0]:
            return float(v[0])
    return None


def audit_autopilot(ap: dict, orders: list[dict], now_ms: int, btc_now: float | None = None,
                    account: str = "main") -> dict:
    cfg = ap.get("config") or {}
    book = cfg.get("id") or ""
    start_ms = int(ap.get("startedMs") or now_ms)
    end_ms = int(ap.get("stoppedMs") or now_ms)
    days = max((end_ms - start_ms) / DAY_MS, 1e-9)
    amount = float(ap.get("startCapital") or cfg.get("capitalUsd") or 0.0)
    hist = ap.get("history") or []
    equity = float(hist[-1][1]) if hist else amount
    f = fills_of(orders, book, start_ms)
    traded = sum(notional(o) for o in f)
    fees = sum(cost_split(o)[0] for o in f)
    slip = sum(cost_split(o)[1] for o in f)
    maker = sum(float(o.get("makerQty") or 0.0) * float(o.get("avgFillPrice") or 0.0) for o in f)
    trims = [o for o in f if amount > 0 and notional(o) < TRIM_SHARE * amount]
    trim_cost = sum(sum(cost_split(o)) for o in trims)
    mine = [o for o in orders if o.get("book") == book and int(o.get("ts") or 0) >= start_ms]
    refused = [o for o in mine if o.get("status") == "rejected"]
    reasons: dict[str, int] = defaultdict(int)
    for o in refused:
        reasons[str(o.get("rejectReason") or "?")[:90]] += 1
    rt = round_trips(f)
    reb = rebalances(f)
    rp = at_repick(reb, start_ms, cfg.get("repickEveryHours") if not cfg.get("sleeves") else None)
    cost = fees + slip
    ret = (equity / amount - 1) * 100 if amount > 0 else None
    btc0 = ap.get("btcStart")
    btc1 = ap.get("btcEnd") or btc_now
    btc_ret = (float(btc1) / float(btc0) - 1) * 100 if btc0 and btc1 else None
    gap = ret - btc_ret if ret is not None and btc_ret is not None else None
    cost_pct = cost / amount * 100 if amount > 0 else None
    return {
        "account": account, "id": book, "name": clean(cfg.get("name") or book), "state": ap.get("state"),
        "sleeves": [s.get("strategyId") for s in (ap.get("sleeves") or []) if (s.get("weight") or 0) > 0],
        "days": days, "amount": amount, "equity": equity, "return_pct": ret, "btc_pct": btc_ret, "vs_btc_pts": gap,
        "fills": len(f), "orders": len(mine), "cancelled": sum(o.get("status") == "cancelled" for o in mine),
        "partial": sum(o.get("status") == "partial" for o in mine), "refused": len(refused),
        "refused_reasons": dict(reasons),
        "traded": traded, "turnover_day": traded / amount / days if amount > 0 else None,
        "fees": fees, "slippage": slip, "cost": cost,
        "cost_bps_day": cost / amount / days * 1e4 if amount > 0 else None,
        "cost_bps_traded": cost / traded * 1e4 if traded > 0 else None,
        "fee_bps_traded": fees / traded * 1e4 if traded > 0 else None,
        "maker_share": maker / traded if traded > 0 else None,
        "trims": len(trims), "trim_cost_share": trim_cost / cost if cost > 0 else None,
        "median_order": sorted(notional(o) for o in f)[len(f) // 2] if f else None,
        "round_trips": rt["pairs"], "round_trip_notional": rt["notional"], "round_trip_cost": rt["cost"],
        "round_trip_cost_share": rt["cost"] / cost if cost > 0 else None,
        "rebalances": len(reb), "rebalances_day": len(reb) / days,
        "cost_per_rebalance_bps": (cost / len(reb) / amount * 1e4) if reb and amount > 0 else None,
        "repick_rebalances": len(rp), "repick_cost": sum(r["cost"] for r in rp),
        "repick_cost_share": sum(r["cost"] for r in rp) / cost if cost > 0 else None,
        "maker_by_hour": maker_by_hour(f),
        "cost_pct": cost_pct,
        "cost_share_of_gap": (cost_pct / -gap) if gap is not None and gap < 0 and cost_pct is not None else None,
    }


def cross_book_overlap(orders: list[dict], books: set[str], since_ms: int, window_ms: int = REBALANCE_GAP_MS) -> dict:
    """Notional that two autopilots traded on opposite sides of one coin in the same window:
    what netting across autopilots could have saved at most."""
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    total = 0.0
    for o in orders:
        if o.get("book") in books and o.get("status") in FILLED and int(o.get("ts") or 0) >= since_ms:
            groups[(o["marketId"], int(o["ts"]) // window_ms)].append(o)
            total += notional(o)
    crossable, saved = 0.0, 0.0
    for v in groups.values():
        if len({o["book"] for o in v}) < 2:
            continue
        buys = [o for o in v if o["side"] == "buy"]
        sells = [o for o in v if o["side"] == "sell"]
        b, s = sum(map(notional, buys)), sum(map(notional, sells))
        if b > 0 and s > 0:
            x = min(b, s)
            crossable += x
            per = sum(sum(cost_split(o)) for o in v) / (b + s)
            saved += 2 * x * per
    return {"traded": total, "crossable": crossable, "saved_at_most": saved}


def audit(states: list[tuple[str, dict]], now_ms: int | None = None) -> dict:
    rows, overlap = [], []
    for account, st in states:
        orders = st.get("orders") or []
        ts = [int(o.get("ts") or 0) for o in orders]
        now = now_ms or max(ts + [int(h[0]) for a in st.get("autopilots") or [] for h in (a.get("history") or [])[-1:]] + [0])
        running = [a for a in st.get("autopilots") or [] if a.get("state") in ("running", "paused")]
        for ap in running:
            rows.append(audit_autopilot(ap, orders, now, btc_price(st), account))
        if running:
            since = min(int(a.get("startedMs") or now) for a in running)
            overlap.append({"account": account, **cross_book_overlap(orders, {a["config"]["id"] for a in running}, since)})
    return {"autopilots": rows, "overlap": overlap}


def _f(v, dp: int = 2, unit: str = "") -> str:
    if v is None:
        return "n/a"
    return f"{v:,.{dp}f}{unit}"


def markdown(res: dict) -> str:
    rows = res["autopilots"]
    out = ["### Per autopilot\n",
           "| autopilot | days | amount | fills | refused | traded | turnover / day | fees | slippage | cost bps of amount / day "
           "| cost bps per unit traded | maker share | trims (< 1 %) | trim cost share | round trips (72 h) | round-trip cost share "
           "| rebalances / day | return | BTC | vs BTC | cost share of the gap |",
           "|" + "---|" * 21]
    for r in rows:
        out.append("| " + " | ".join([
            f"{r['name']} ({r['account']})", _f(r["days"], 1), _f(r["amount"], 0), str(r["fills"]), str(r["refused"]),
            _f(r["traded"], 0), _f(r["turnover_day"], 3), _f(r["fees"]), _f(r["slippage"]), _f(r["cost_bps_day"]),
            _f(r["cost_bps_traded"], 1), _f(r["maker_share"]), str(r["trims"]), _f(r["trim_cost_share"]),
            f"{r['round_trips']} (${r['round_trip_notional']:,.0f})", _f(r["round_trip_cost_share"]),
            _f(r["rebalances_day"]), _f(r["return_pct"], 2, " %"), _f(r["btc_pct"], 2, " %"),
            _f(r["vs_btc_pts"], 2, " pts"), _f(r["cost_share_of_gap"])]) + " |")
    out.append("")
    picks = [r for r in rows if r["repick_rebalances"]]
    if picks:
        out.append("### Rebalances a re-pick sent by itself\n")
        for r in picks:
            out.append(f"- {r['name']}: {r['repick_rebalances']} of its {r['rebalances']} rebalances began right after a "
                       f"scheduled re-pick, apart from the lab signals' own; they cost ${r['repick_cost']:,.2f}, "
                       f"{_f((r['repick_cost_share'] or 0) * 100, 0)} % of everything it paid.")
        out.append("")
    hours = [(r["name"], r["maker_by_hour"]) for r in rows if r["maker_by_hour"]]
    if hours:
        out.append("### Maker share by UTC hour (notional)\n")
        for name, by in hours:
            out.append(f"- {name}: " + ", ".join(f"{h:02d}h ${n:,.0f} at {m * 100:.0f} %" for h, (n, m) in by.items()))
        out.append("")
    refused = [r for r in rows if r["refused"]]
    if refused:
        out.append("### Refused orders\n")
        for r in refused:
            for why, n in r["refused_reasons"].items():
                out.append(f"- {r['name']}: {n} x \"{why}\"")
        out.append("")
    if res.get("overlap"):
        out.append("### Netting across autopilots, at most\n")
        for o in res["overlap"]:
            out.append(f"- {o['account']}: ${o['traded']:,.0f} traded by the running autopilots, ${o['crossable']:,.0f} of it "
                       f"on opposite sides of one coin within 30 minutes; crossing it inside the engine would have saved "
                       f"at most ${o['saved_at_most']:,.2f}.")
        out.append("")
    return "\n".join(out) + "\n"


def read_states(paths: list[Path]) -> list[tuple[str, dict]]:
    out = []
    for p in paths:
        p = Path(p)
        if p.exists():
            out.append((p.parent.name if p.parent.name != "autopilot" else "main", json.loads(p.read_text(encoding="utf-8"))))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    paths = [Path(a) for a in argv if not a.startswith("--")] or default_paths()
    res = audit(read_states(paths))
    text = json.dumps(res, indent=1, default=float) if as_json else markdown(res)
    sys.stdout.buffer.write(text.encode("utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
