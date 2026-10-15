"""A paper collection of Pokemon cards, in play money, following the forecasts.

Nothing is bought or sold anywhere: this is a journal of what a collection
that followed the model would hold and be worth. The owner trades real cards
by hand.

Rules
  start      1,000 play dollars, cash.
  monthly    on the first run of each calendar month: rank the cards with a
             TCGplayer market price between $20 and $250 by the 90-day
             forecast; the top 10 with a forecast above +5 % are the targets,
             equal weight, at most 4 copies a card. A holding is sold when it has been held at least
             90 days and is no longer in the top 30, or when its price has
             been missing for 14 days (sold at the last price). Hysteresis
             keeps turnover low; card trading costs are large.
  costs      buying pays the market price plus 3 % and $1.50 shipping per
             card; selling receives the market price minus 15 % (marketplace
             and payment fees) and $1.00 shipping per card. Whole copies only.
  daily      marked at the latest price: `equity` is what selling everything
             today would bring after costs, `equity_market` the plain market
             value.

Files under <lake>/paper/: state.json, journal.csv (one row per run day),
trades.csv.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import date
from pathlib import Path

import polars as pl

START = 1_000.0
TOP_N, KEEP_RANK = 10, 30
MIN_PRICE, MAX_PRICE = 20.0, 250.0
# At most this many copies of one card: the first real run bought 13 Geodudes
# at $5.51 (a collection, not a pallet), and per-copy postage ate a third.
MAX_COPIES = 4
MIN_PRED = 0.05
MIN_HOLD_DAYS = 90
STALE_DAYS = 14
BUY_COST, BUY_SHIP = 0.03, 1.50
SELL_FEE, SELL_SHIP = 0.15, 1.00
JOURNAL_COLS = ["date", "equity", "equity_market", "cash", "holdings", "rebalanced", "turnover", "bought", "sold"]


def unit_buy(price: float) -> float:
    return price * (1 + BUY_COST) + BUY_SHIP


def unit_sell(price: float) -> float:
    return max(price * (1 - SELL_FEE) - SELL_SHIP, 0.0)


def load_state(d: Path) -> dict:
    try:
        return json.loads((d / "state.json").read_text())
    except (OSError, ValueError):
        return {"cash": START, "holdings": [], "started": None, "last_rebalance": None}


def _write_json(p: Path, v) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(v, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _append(p: Path, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    new = not p.exists()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def step(snap: pl.DataFrame, d: Path, today: str | None = None, model_src: str = "prior") -> dict:
    """One run: refresh prices, rebalance if a new month, append the journal. `snap`
    is today's forecast frame (card_id, name, price, tp_market, pred_90d ...)."""
    today = today or str(snap["date"].max())
    st = load_state(d)
    if st.get("last_date") == today:
        return st  # already ran today
    st["started"] = st.get("started") or today
    px = {r["card_id"]: r for r in snap.select("card_id", "name", "set_name", "price", "tp_market", "pred_90d",
                                               "image_small").to_dicts()}
    for h in st["holdings"]:
        r = px.get(h["card_id"])
        if r and r.get("price"):
            h["price"], h["price_date"] = float(r["price"]), today
    month = today[:7]
    trades: list[dict] = []
    rebalanced = False
    turnover = 0.0
    if st.get("last_rebalance") != month:
        rebalanced = True
        st["last_rebalance"] = month
        elig = (snap.filter(pl.col("tp_market").is_between(MIN_PRICE, MAX_PRICE) & pl.col("pred_90d").is_not_null())
                .sort(["pred_90d", "card_id"], descending=[True, False]))
        ranks = {cid: i for i, cid in enumerate(elig["card_id"].to_list())}
        keep = []
        for h in st["holdings"]:
            stale = _days(h.get("price_date") or h["bought"], today) >= STALE_DAYS
            old = _days(h["bought"], today) >= MIN_HOLD_DAYS
            out_of_rank = ranks.get(h["card_id"], 10**9) >= KEEP_RANK
            if stale or (old and out_of_rank):
                got = h["qty"] * unit_sell(h["price"])
                st["cash"] += got
                turnover += got
                trades.append({"date": today, "side": "sell", "card_id": h["card_id"], "name": h["name"],
                               "qty": h["qty"], "price": h["price"], "cash": round(got, 2),
                               "why": "price missing" if stale else "held 90 days, out of the top 30"})
            else:
                keep.append(h)
        st["holdings"] = keep
        held_ids = {h["card_id"] for h in keep}
        targets = [r for r in elig.head(TOP_N).to_dicts() if r["pred_90d"] > MIN_PRED and r["card_id"] not in held_ids]
        slots = TOP_N - len(keep)
        if targets and slots > 0:
            budget = st["cash"] / min(slots, len(targets))
            for r in targets[:slots]:
                unit = unit_buy(r["tp_market"])
                qty = min(int(budget // unit), MAX_COPIES)
                if qty < 1 or qty * unit > st["cash"]:
                    continue
                st["cash"] -= qty * unit
                turnover += qty * unit
                st["holdings"].append({"card_id": r["card_id"], "name": r["name"], "set_name": r.get("set_name"),
                                       "image": r.get("image_small"), "qty": qty, "buy_price": r["tp_market"],
                                       "cost": round(qty * unit, 2), "bought": today, "price": r["tp_market"],
                                       "price_date": today, "pred_90d_at_buy": r["pred_90d"],
                                       "pred_src_at_buy": model_src})
                trades.append({"date": today, "side": "buy", "card_id": r["card_id"], "name": r["name"],
                               "qty": qty, "price": r["tp_market"], "cash": round(-qty * unit, 2),
                               "why": f"90 d forecast {r['pred_90d'] * 100:+.0f} % ({model_src})"})
    liq = st["cash"] + sum(h["qty"] * unit_sell(h["price"]) for h in st["holdings"])
    mkt = st["cash"] + sum(h["qty"] * h["price"] for h in st["holdings"])
    st["equity"], st["equity_market"], st["last_date"] = round(liq, 2), round(mkt, 2), today
    _append(d / "trades.csv", ["date", "side", "card_id", "name", "qty", "price", "cash", "why"], trades)
    _append(d / "journal.csv", JOURNAL_COLS, [{
        "date": today, "equity": round(liq, 2), "equity_market": round(mkt, 2), "cash": round(st["cash"], 2),
        "holdings": len(st["holdings"]), "rebalanced": rebalanced,
        "turnover": round(turnover / max(mkt, 1e-9), 4),
        "bought": sum(t["side"] == "buy" for t in trades), "sold": sum(t["side"] == "sell" for t in trades)}])
    _write_json(d / "state.json", st)
    return st


def journal(d: Path) -> list[dict]:
    p = d / "journal.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def trades(d: Path) -> list[dict]:
    p = d / "trades.csv"
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))
