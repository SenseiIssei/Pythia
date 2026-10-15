"""The CS2 paper portfolio (play money), the alerts and the board for the app.

Nothing here trades. The portfolio is a journal of what the model's picks
would have done on Skinport at the listed prices and fees; the alerts tell
the owner where to look, and the owner decides and trades by hand.

Paper rules (fixed before the first run):
  - start 10,000 EUR of play money, at most 10 items, 10 % of equity each
  - looks once a week; buys only items with a lowest ask of 1 EUR or more,
    20 or more Skinport sales in 7 days and 5 or more listings, whose expected
    return over the model's horizon beats the round trip (Skinport fee plus a
    2 % spread allowance) by at least 3 % (MIN_EDGE, set on 2026-10-15 before
    the first run on the lab machine: the first local run bought music kits
    the model expected to clear the fees by 0.0 to 0.9 %, which is noise)
  - buys at the lowest ask, at most a day of sales (7-day sales / 7) and never
    more than is listed; sells one cent under the lowest ask minus the fee
  - holds at least 30 days unless the 7-day prediction is a loss of 5 % or
    more; then sells what is no longer a pick
  - equity is cash plus each position at its reference price, after the fee:
    what selling everything today would net
"""

from __future__ import annotations

import csv
import json
import math
from datetime import date
from pathlib import Path

import polars as pl

from . import market

START_EQUITY = 10_000.0
MAX_POSITIONS = 10
WEIGHT = 0.10
MIN_PRICE = 1.0
MIN_SALES7 = 20
MIN_LISTED = 5
MIN_HOLD_DAYS = 30
REBALANCE_DAYS = 7
SELL_PRED7 = -0.05
MIN_EDGE = 0.03  # expected return over the horizon must beat the round trip by this much

GAP_MIN = 0.05
GAP_STEAM_VOLUME = 20
GAP_SKINPORT_SALES7 = 10
DROP_SALES7 = 50
DROP_VS_30D = -0.15
DROP_24H = -0.10
DROP_VS_7D = -0.10
ALERT_COOLDOWN_MS = 24 * 3_600_000
DAY_MS = 86_400_000


# ---------------------------------------------------------------- the current market in one frame

def snapshot(items: pl.DataFrame, sales: pl.DataFrame) -> pl.DataFrame:
    if items.is_empty():
        return pl.DataFrame()
    df = items if sales.is_empty() else items.join(sales.drop("ts_ms"), on="name", how="left")
    for w in ("s24", "s7", "s30", "s90"):
        for s in ("min", "max", "avg", "median", "volume"):
            if f"{w}_{s}" not in df.columns:
                df = df.with_columns(pl.lit(None, pl.Float64).alias(f"{w}_{s}"))
    return df.with_columns(ref=market.ref_price(df))


def expected(pred7: float | None, pred30: float | None) -> tuple[float | None, int | None]:
    """The expected simple return and its horizon: 30 days when there is a 30-day prediction."""
    if pred30 is not None and math.isfinite(pred30):
        return math.expm1(pred30), 30
    if pred7 is not None and math.isfinite(pred7):
        return math.expm1(pred7), 7
    return None, None


# ---------------------------------------------------------------- paper portfolio

def paper_dir(root: Path | None = None) -> Path:
    return market.cs2_root(root) / "paper"


def load_state(root: Path | None = None) -> dict:
    st = market.read_json(paper_dir(root) / "state.json")
    if st:
        return st
    return {"variant": "CS2 skins on Skinport, top 10 after fees, weekly, play money (EUR)", "started": None,
            "cash": START_EQUITY, "positions": {}, "last_rebalance": None, "trades": []}


def value(st: dict, prices: dict[str, float]) -> tuple[float, float]:
    """(equity net of the sale fee, market value at reference prices)."""
    mv = net = 0.0
    for name, p in st["positions"].items():
        px = prices.get(name) or p.get("last_price") or p["cost"]
        mv += p["qty"] * px
        net += p["qty"] * market.skinport_seller_gets(max(px - market.TICK, market.TICK))
    return st["cash"] + net, mv


def rebalance(st: dict, snap: pl.DataFrame, preds: dict[str, tuple[float | None, float | None]], today: date,
              hurdle: float | None = None) -> dict:
    """One weekly look. Returns the new state; trades are appended to st['trades']."""
    hurdle = market.round_trip_cost() if hurdle is None else hurdle
    st = json.loads(json.dumps(st))
    rows = {r["name"]: r for r in snap.select("name", "min_price", "quantity", "ref",
                                               pl.col("s7_volume").fill_null(0)).to_dicts()}
    prices = {n: r["ref"] for n, r in rows.items() if r["ref"]}
    equity, _ = value(st, prices)

    cands = []
    for name, (p7, p30) in preds.items():
        r = rows.get(name)
        if not r or not r["min_price"] or r["min_price"] < MIN_PRICE:
            continue
        if r["s7_volume"] < MIN_SALES7 or (r["quantity"] or 0) < MIN_LISTED:
            continue
        exp, _h = expected(p7, p30)
        if exp is None or exp - hurdle < MIN_EDGE:
            continue
        cands.append((exp - hurdle, name))
    cands.sort(reverse=True)
    picks = [n for _, n in cands[:MAX_POSITIONS]]

    trades = []
    for name in list(st["positions"]):
        p = st["positions"][name]
        held = (today - date.fromisoformat(p["bought"])).days
        p7 = (preds.get(name) or (None, None))[0]
        losing = p7 is not None and math.isfinite(p7) and math.expm1(p7) <= SELL_PRED7
        r = rows.get(name)
        if name in picks or not r or not r["min_price"] or (held < MIN_HOLD_DAYS and not losing):
            continue
        px = max(r["min_price"] - market.TICK, market.TICK)
        proceeds = p["qty"] * market.skinport_seller_gets(px)
        st["cash"] += proceeds
        trades.append({"date": today.isoformat(), "side": "sell", "name": name, "qty": p["qty"], "price": px,
                       "net": round(proceeds, 2), "pnl": round(proceeds - p["qty"] * p["cost"], 2),
                       "why": "predicted loss" if losing else "no longer a pick"})
        del st["positions"][name]

    for name in picks:
        if name in st["positions"] or len(st["positions"]) >= MAX_POSITIONS:
            continue
        r = rows[name]
        budget = min(WEIGHT * equity, st["cash"])
        cap = min(int(r["quantity"] or 0), max(int(r["s7_volume"] / 7), 1))
        qty = min(int(budget // r["min_price"]), cap)
        if qty < 1:
            continue
        cost = qty * r["min_price"]
        st["cash"] -= cost
        st["positions"][name] = {"qty": qty, "cost": r["min_price"], "bought": today.isoformat(), "last_price": r["min_price"]}
        exp, h = expected(*preds[name])
        trades.append({"date": today.isoformat(), "side": "buy", "name": name, "qty": qty, "price": r["min_price"],
                       "net": round(-cost, 2), "expected": round(exp, 4), "horizon_days": h})
    for name, p in st["positions"].items():
        if prices.get(name):
            p["last_price"] = prices[name]
    st["last_rebalance"] = today.isoformat()
    st["trades"] = (st.get("trades") or []) + trades
    st["last_trades"] = trades
    return st


def due(st: dict, today: date) -> bool:
    last = st.get("last_rebalance")
    return not last or (today - date.fromisoformat(last)).days >= REBALANCE_DAYS


def journal(root: Path | None, st: dict, prices: dict[str, float], today: date, rebalanced: bool, turnover: float) -> dict:
    """Today's row (replaced if the day already has one; a rebalance mark is kept)."""
    for name, p in st["positions"].items():
        if prices.get(name):
            p["last_price"] = prices[name]
    eq, mv = value(st, prices)
    row = {"date": today.isoformat(), "equity": round(eq, 2), "market_value": round(mv, 2), "cash": round(st["cash"], 2),
           "positions": len(st["positions"]), "rebalanced": rebalanced, "turnover": round(turnover, 4)}
    path = paper_dir(root) / "journal.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    if path.exists():
        with path.open(newline="") as fh:
            rows = list(csv.DictReader(fh))
    if rows and rows[-1]["date"] == row["date"]:
        old = rows.pop()
        if old.get("rebalanced") in ("True", "true"):
            row["rebalanced"] = True
            row["turnover"] = max(float(old.get("turnover") or 0), turnover)
    rows.append({k: str(v) for k, v in row.items()})
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerows(rows)
    return row


def save_state(root: Path | None, st: dict) -> None:
    d = paper_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(d / "state.json")


def read_journal(root: Path | None) -> list[dict]:
    path = paper_dir(root) / "journal.csv"
    if not path.exists():
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


# ---------------------------------------------------------------- alerts

def find_alerts(snap: pl.DataFrame, steam: pl.DataFrame, ago24: pl.DataFrame) -> list[dict]:
    """Cross-market gaps after fees and big drops in liquid items, strongest first."""
    out = []
    if snap.is_empty():
        return out
    if not steam.is_empty():
        j = snap.join(steam.select("name", pl.col("lowest").alias("steam_ask"), pl.col("volume").alias("steam_volume")),
                      on="name", how="inner")
        for r in j.iter_rows(named=True):
            if not r["min_price"] or r["min_price"] < MIN_PRICE or (r["steam_volume"] or 0) < GAP_STEAM_VOLUME:
                continue
            if (r["s7_volume"] or 0) < GAP_SKINPORT_SALES7:
                continue
            g = market.gaps(r["min_price"], r["steam_ask"])
            for route, v in g.items():
                if v is not None and v >= GAP_MIN:
                    text = (f"buy on Skinport at {r['min_price']:.2f}, list on Steam at {r['steam_ask'] - 0.01:.2f}: "
                            f"{v:+.1%} after fees, paid in Steam wallet funds" if route == "to_steam" else
                            f"buy on Steam at {r['steam_ask']:.2f}, list on Skinport at {r['min_price'] - 0.01:.2f}: "
                            f"{v:+.1%} after fees, cash after the 7-day trade lock")
                    out.append({"kind": "gap", "route": route, "name": r["name"], "strength": v, "text": text})
    prev = {}
    if not ago24.is_empty() and "ref" in ago24.columns:
        prev = dict(zip(ago24["name"].to_list(), ago24["ref"].to_list()))
    for r in snap.filter((pl.col("s7_volume").fill_null(0) >= DROP_SALES7) & (pl.col("ref") >= MIN_PRICE)).iter_rows(named=True):
        ref, m30, m7 = r["ref"], r["s30_median"], r["s7_median"]
        if not ref or not m30:
            continue
        vs30 = ref / m30 - 1
        if vs30 > DROP_VS_30D:
            continue
        p24 = prev.get(r["name"])
        if p24:
            d24 = ref / p24 - 1
            if d24 > DROP_24H:
                continue
            why = f"{d24:+.1%} in 24 h"
        else:
            if not m7 or ref / m7 - 1 > DROP_VS_7D:
                continue
            why = f"{ref / m7 - 1:+.1%} against its 7-day median"
        out.append({"kind": "drop", "name": r["name"], "strength": -vs30,
                    "text": f"now {ref:.2f}, {why}, {vs30:+.1%} against its 30-day median ({int(r['s7_volume'])} sales in 7 days)"})
    out.sort(key=lambda a: -a["strength"])
    return out


def fresh_alerts(alerts: list[dict], state: dict, now_ms: int) -> tuple[list[dict], dict]:
    """Drop what was sent in the last 24 h for the same item and kind; returns (to send, new state)."""
    st = {k: v for k, v in (state or {}).items() if now_ms - int(v) < 7 * DAY_MS}
    out = []
    for a in alerts:
        key = f"{a['kind']}:{a.get('route', '')}:{a['name']}"
        if now_ms - int(st.get(key, 0)) < ALERT_COOLDOWN_MS:
            continue
        st[key] = now_ms
        out.append(a)
    return out, st


def alert_text(alerts: list[dict], prefix: str = "Pythia", limit: int = 8) -> str:
    lines = [f"{prefix} CS2: {len(alerts)} to look at (paper only, trade by hand if at all)"]
    for a in alerts[:limit]:
        tag = "Gap" if a["kind"] == "gap" else "Drop"
        lines.append(f"- {tag}: {a['name']}: {a['text']}")
    if len(alerts) > limit:
        lines.append(f"... and {len(alerts) - limit} more on the CS2 page")
    return "\n".join(lines)


# ---------------------------------------------------------------- the board for the app

def signal_of(exp: float | None, pred7: float | None, gap: float | None, drop: bool, liquid: bool,
              hurdle: float) -> str:
    if gap is not None and gap >= GAP_MIN:
        return "gap"
    if drop:
        return "drop"
    if exp is not None and liquid and exp - hurdle >= MIN_EDGE:
        return "buy"
    if pred7 is not None and math.isfinite(pred7) and math.expm1(pred7) <= SELL_PRED7:
        return "avoid"
    return "hold"


def board(snap: pl.DataFrame, preds: dict[str, tuple[float | None, float | None]], steam: pl.DataFrame,
          change7: dict[str, float], alerts: list[dict], watch_names: list[str], held: set[str],
          max_rows: int = 200) -> list[dict]:
    hurdle = market.round_trip_cost()
    steam_ask = dict(zip(steam["name"].to_list(), steam["lowest"].to_list())) if not steam.is_empty() else {}
    gap_of: dict[str, float] = {}
    drops = set()
    for a in alerts:
        if a["kind"] == "gap":
            gap_of[a["name"]] = max(gap_of.get(a["name"], -1.0), a["strength"])
        else:
            drops.add(a["name"])
    liquid = snap.filter(pl.col("ref").is_not_null()).sort(pl.col("s7_volume").fill_null(0), descending=True)
    want = set(watch_names) | held | set(gap_of) | drops
    top = liquid.head(max_rows)["name"].to_list()
    names = [n for n in liquid["name"].to_list() if n in want]
    names += [n for n in top if n not in set(names)]
    rows_by = {r["name"]: r for r in liquid.filter(pl.col("name").is_in(names)).to_dicts()}
    out = []
    for n in names[: max_rows + len(want)]:
        r = rows_by.get(n)
        if not r:
            continue
        p7, p30 = preds.get(n, (None, None))
        exp, h = expected(p7, p30)
        sa = steam_ask.get(n)
        g = market.gaps(r["min_price"], sa) if sa else {"to_steam": None, "to_skinport": None}
        best_gap = max([v for v in g.values() if v is not None], default=None)
        is_liquid = (r["s7_volume"] or 0) >= MIN_SALES7 and (r["min_price"] or 0) >= MIN_PRICE
        out.append({
            "name": n, "category": market.category(n), "price": _r(r["ref"]), "ask": _r(r["min_price"]),
            "steamPrice": _r(sa), "change7d": _r(change7.get(n), 4), "pred7d": _r(math.expm1(p7) if _ok(p7) else None, 4),
            "pred30d": _r(math.expm1(p30) if _ok(p30) else None, 4), "expectedNet": _r(exp - hurdle if exp is not None else None, 4),
            "horizon": h, "gap": _r(best_gap, 4), "sales7d": int(r["s7_volume"] or 0), "listed": int(r["quantity"] or 0),
            "held": n in held, "watch": n in watch_names,
            "signal": signal_of(exp, p7, gap_of.get(n), n in drops, is_liquid, hurdle),
        })
    return out


def _ok(v) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(v)


def _r(v, digits: int = 2):
    return round(float(v), digits) if _ok(v) else None
