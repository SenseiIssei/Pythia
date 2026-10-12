"""Demo fills of the autopilot engine, kept and turned into a measured cost section.

The autopilot engine trades demo orders on the Alpaca paper account and keeps
only its last few hundred orders in /api/state. Every night this module reads
them (or an exported file), adds the finished demo ones to a ledger that only
grows (<data>/learn/fills.jsonl, one line per order id) and measures per
symbol:

  realised slippage    fill price against the arrival (signal) price, bps,
                       positive when it cost us; median, mean and 90th
                       percentile, market orders only (they cross the spread)
  modelled slippage    what the engine's cost model expected for those orders
  base cost            what the BASE cost table says the same orders cost
                       (half-spread plus square-root impact at the default depth)
  fill rates           limit orders (maker) and market orders (taker) that
                       filled, against those that were cancelled or rejected

The measured section is written next to the base table, never into it:
<data>/costs/learned.json is the base table plus a "measured" block. A
symbol's halfSpreadBps and impactCoeff are scaled by realised over base cost
only once it has at least MIN_FILLS market fills; with fewer it keeps the base
values (or the ones a previous run applied). Fees, borrow, minimum notional and
depth are never touched; guard.cost_violations checks the result before it is
written. The engine reads the file only if the operator points
PYTHIA_COSTS_FILE at it.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

import numpy as np

from ..data import ROOT
from . import guard

MIN_FILLS = 30
WINDOW = 250              # the most recent market fills per symbol that count
COST_VENUE = "alpaca"     # the autopilot engine's demo route is the Alpaca paper account
FINAL = {"filled", "cancelled", "rejected"}
DAY_MS = 86_400_000
KEEP = ("id", "ts", "strategyId", "marketId", "venue", "side", "type", "qty", "status", "filledQty",
        "avgFillPrice", "route", "realisedSlippageBps", "modelledSlippageBps", "costSource", "driftBps",
        "rejectReason")


def ledger_path() -> Path:
    return ROOT / "learn" / "fills.jsonl"


def base_costs_path() -> Path:
    return Path(os.environ.get("PYTHIA_COSTS_BASE", str(ROOT / "costs" / "base.json")))


def learned_costs_path() -> Path:
    return ROOT / "costs" / "learned.json"


def symbol_of(market_id: str) -> str:
    """'crypto:BTC/USD' -> 'BTC/USD'."""
    return str(market_id or "").split(":", 1)[-1].strip().upper()


def read_ledger(path: Path | None = None) -> dict[str, dict]:
    path = path or ledger_path()
    out: dict[str, dict] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            out[str(r["id"])] = r
        except (ValueError, KeyError, TypeError):
            continue
    return out


def finished_demo_orders(orders: list[dict], now_ms: int) -> list[dict]:
    """Demo orders that will not change any more: filled, cancelled or
    rejected, or partly filled and a day old."""
    out = []
    for o in orders or []:
        if not isinstance(o, dict) or o.get("route") != "demo" or not o.get("id"):
            continue
        st = o.get("status")
        if st in FINAL or (st == "partial" and now_ms - int(o.get("ts") or now_ms) > DAY_MS):
            out.append({k: o.get(k) for k in KEEP if k in o})
    return out


def update_ledger(orders: list[dict], now_ms: int, path: Path | None = None) -> int:
    """Append the finished demo orders the ledger does not have yet. Returns how many were new."""
    path = path or ledger_path()
    have = read_ledger(path)
    new = [o for o in finished_demo_orders(orders, now_ms) if str(o["id"]) not in have]
    if new:
        guard.append_jsonl(path, sorted(new, key=lambda o: o.get("ts") or 0))
    return len(new)


def load_orders_file(path: Path) -> list[dict]:
    """An exported copy of /api/state, a list of orders, or JSON lines of orders."""
    text = path.read_text(encoding="utf-8")
    try:
        v = json.loads(text)
        if isinstance(v, dict):
            return list(v.get("orders") or [])
        return list(v) if isinstance(v, list) else []
    except ValueError:
        rows = []
        for line in text.splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
        return rows


# ---------------------------------------------------------------- the cost model, as the engine computes it

def resolve(table: dict, venue: str, symbol: str) -> dict | None:
    v = table.get("venues", {}).get(venue)
    if v is None:
        return None
    model = {k: x for k, x in v.items() if k not in ("symbols", "label")}
    syms = v.get("symbols", {})
    base = symbol.split("/")[0].split("-")[0]
    ov = syms.get(symbol) or syms.get(base) or {}
    return {**model, **ov}


def modelled_bps(model: dict, notional: float) -> float:
    """Half-spread plus square-root impact at the default depth (costs.rs slippage_bps)."""
    depth = float(model.get("defaultDepth") or 0)
    impact = float(model.get("impactCoeff", 0)) * math.sqrt(max(notional, 0) / depth) if depth > 0 else 0.0
    return float(model.get("halfSpreadBps", 0)) + impact


# ---------------------------------------------------------------- measuring

def _q(xs: list[float], q: float) -> float | None:
    return float(np.quantile(xs, q)) if xs else None


def measure(ledger: dict[str, dict], base: dict | None, venue: str = COST_VENUE) -> dict[str, dict]:
    """Per symbol: fills, slippage, base cost and fill rates."""
    by: dict[str, list[dict]] = {}
    for o in ledger.values():
        by.setdefault(symbol_of(o.get("marketId", "")), []).append(o)
    out = {}
    for sym, rows in sorted(by.items()):
        rows.sort(key=lambda o: o.get("ts") or 0)
        rate = {}
        for kind in ("limit", "market"):
            done = [o for o in rows if o.get("type") == kind]
            filled = [o for o in done if o.get("status") in ("filled", "partial") and (o.get("filledQty") or 0) > 0]
            rate[kind] = (len(filled) / len(done), len(done)) if done else (None, 0)
        taker = [o for o in rows if o.get("type") == "market" and o.get("status") in ("filled", "partial")
                 and o.get("realisedSlippageBps") is not None][-WINDOW:]
        maker = [o for o in rows if o.get("type") == "limit" and o.get("status") in ("filled", "partial")
                 and o.get("realisedSlippageBps") is not None]
        real = [float(o["realisedSlippageBps"]) for o in taker]
        mod = [float(o["modelledSlippageBps"]) for o in taker if o.get("modelledSlippageBps") is not None]
        model = resolve(base, venue, sym) if base else None
        base_cost = []
        if model:
            for o in taker:
                px, qty = o.get("avgFillPrice"), o.get("filledQty") or o.get("qty")
                if px and qty:
                    base_cost.append(modelled_bps(model, float(px) * float(qty)))
        out[sym] = {
            "taker_fills": len(taker),
            "maker_fills": len(maker),
            "median_realised_bps": _q(real, 0.5),
            "mean_realised_bps": float(np.mean(real)) if real else None,
            "p90_realised_bps": _q(real, 0.9),
            "median_modelled_bps": _q(mod, 0.5),
            "median_base_bps": _q(base_cost, 0.5),
            "median_maker_realised_bps": _q([float(o["realisedSlippageBps"]) for o in maker], 0.5),
            "maker_fill_rate": rate["limit"][0], "maker_orders": rate["limit"][1],
            "taker_fill_rate": rate["market"][0], "taker_orders": rate["market"][1],
        }
    return out


def _sig(x: float, n: int = 3) -> float:
    return float(f"{x:.{n}g}")


def calibrate(base: dict, measured: dict[str, dict], previous: dict | None = None,
              venue: str = COST_VENUE) -> tuple[dict, dict[str, dict]]:
    """(learned table, per-symbol decision). The learned table is the base
    table with halfSpreadBps and impactCoeff of each well-measured symbol
    scaled by realised over base cost, bounded by guard.COST_MAX_FACTOR and
    guard.COST_BOUNDS. A symbol with too few fills keeps what a previous run
    applied, if anything, else the base values."""
    learned = json.loads(json.dumps(base))
    v = learned.get("venues", {}).get(venue)
    prev_applied = ((previous or {}).get("measured", {}).get(venue, {}) or {})
    decisions: dict[str, dict] = {}
    if v is None:
        return learned, decisions
    syms = v.setdefault("symbols", {})
    for sym, m in measured.items():
        if sym not in syms:
            decisions[sym] = {"status": "not in the base table", "applied": None}
            continue
        model = resolve(base, venue, sym)
        if m["taker_fills"] < MIN_FILLS or not m.get("median_base_bps") or m.get("median_realised_bps") is None:
            kept = (prev_applied.get(sym) or {}).get("applied")
            if kept:
                syms[sym].update(kept)
            decisions[sym] = {"status": f"collecting ({m['taker_fills']} of {MIN_FILLS} market fills)",
                              "applied": kept or None}
            continue
        k = m["median_realised_bps"] / m["median_base_bps"]
        k = min(max(k, 1 / guard.COST_MAX_FACTOR * 1.0001), guard.COST_MAX_FACTOR * 0.9999)
        applied = {}
        for f, (lo, hi) in guard.COST_BOUNDS.items():
            applied[f] = _sig(min(max(float(model[f]) * k, lo), hi))
        syms[sym].update(applied)
        decisions[sym] = {"status": "applied", "factor": k, "applied": applied}
    return learned, decisions


def run(orders: list[dict] | None, now_ms: int, previous_learned: dict | None = None) -> dict:
    """The whole cost step: ledger, measurement, learned table. Returns a summary for the digest."""
    added = update_ledger(orders or [], now_ms) if orders is not None else 0
    ledger = read_ledger()
    bp = base_costs_path()
    base = None
    if bp.exists():
        try:
            base = json.loads(bp.read_text(encoding="utf-8"))
        except ValueError:
            base = None
    measured = measure(ledger, base)
    out = {"new_orders": added, "ledger_orders": len(ledger), "symbols": measured, "decisions": {},
           "learned_file": None, "violations": [], "base_file": str(bp) if base else None}
    if base is None:
        out["note"] = f"no base cost table at {bp}; measured only, nothing applied"
        guard.write_json(ROOT / "learn" / "costs_measured.json", {"generated_ms": now_ms, "measured": measured})
        return out
    if previous_learned is None and learned_costs_path().exists():
        try:
            previous_learned = json.loads(learned_costs_path().read_text(encoding="utf-8"))
        except ValueError:
            previous_learned = None
    learned, decisions = calibrate(base, measured, previous_learned)
    out["decisions"] = decisions
    learned_body = {k: x for k, x in learned.items() if k != "measured"}
    violations = guard.cost_violations(base, learned_body)
    out["violations"] = violations
    learned["measured"] = {
        "generated_ms": now_ms,
        "source": "autopilot engine demo fills on the Alpaca paper account",
        "min_fills": MIN_FILLS,
        COST_VENUE: {s: {**measured[s], **decisions.get(s, {})} for s in measured},
    }
    if violations:
        out["note"] = "learned table refused by the guardrails; the previous file stays"
        return out
    guard.write_json(learned_costs_path(), learned)
    out["learned_file"] = str(learned_costs_path())
    return out
