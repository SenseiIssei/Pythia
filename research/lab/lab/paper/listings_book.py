"""Paper book on new Alpaca listings, built only if the W6 study's rule passed. No real money.

    python -m lab.paper.listings_book          one step (cron, right after lab.ops.listings)

The book is off until `reports/listing_effect/latest.json` (written by
lab.experiments.listings) says the pre-registered rule passed; then it uses
that rule's horizon. While it is off a step does nothing and writes nothing.

When on: every coin the watcher saw newly listed on Alpaca (lake rows with
venue alpaca, event listed, a new coin) after the book started is bought with
a fixed $500 at the latest Alpaca trade plus 35 bps, at most 4 open at once,
and sold after the horizon at the latest trade minus 35 bps. A listing seen
while 4 are open is skipped and journaled as such. Equity starts at 10,000
like every lab paper book; only the $500 slices are ever at risk.

<data>/paper/listings/state.json, journal.csv (one row per UTC day), trades.csv
"""

from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from ..data import ROOT

NAME = "listings"
START_EQUITY = 10_000.0
BUDGET = 500.0
MAX_OPEN = 4
COST = 0.0035
DAY_MS = 86_400_000
TRADES = "https://data.alpaca.markets/v1beta3/crypto/us/latest/trades?symbols="


def reports_root() -> Path:
    return Path(os.environ.get("PYTHIA_REPORTS", str(ROOT / "reports")))


def verdict() -> dict | None:
    """The study's rule when it passed, else None."""
    try:
        v = json.loads((reports_root() / "listing_effect" / "latest.json").read_text())
    except (OSError, ValueError):
        return None
    rule = v.get("rule") if v.get("passed") is True else None
    return rule if isinstance(rule, dict) and int(rule.get("horizon_days") or 0) > 0 else None


def alpaca_listings(since_ms: int) -> list[dict]:
    """New Alpaca coins the watcher recorded at or after since_ms, oldest first."""
    import polars as pl
    files = sorted((ROOT / "lake" / "listings" / "first_seen").rglob("*-alpaca.parquet"))
    if not files:
        return []
    df = pl.concat([pl.read_parquet(f) for f in files], how="vertical_relaxed")
    df = df.filter((pl.col("event") == "listed") & pl.col("new_base") & (pl.col("ts_ms") >= since_ms)
                   & pl.col("symbol").str.ends_with("/USD")).sort("ts_ms")
    return df.select("ts_ms", "symbol", "base").to_dicts()


def latest_prices(symbols: list[str]) -> dict[str, float]:
    if not symbols:
        return {}
    k = (os.environ.get("APCA_API_KEY_ID") or "").strip()
    s = (os.environ.get("APCA_API_SECRET_KEY") or os.environ.get("APCA_API_SECRET") or "").strip()
    h = {"User-Agent": "pythia-lab", **({"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s} if k and s else {})}
    req = urllib.request.Request(TRADES + urllib.parse.quote(",".join(symbols)), headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        t = json.load(r).get("trades") or {}
    return {sym: float(v["p"]) for sym, v in t.items() if float(v.get("p") or 0) > 0}


def _append(p: Path, row: dict) -> None:
    new = not p.exists()
    with p.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)


def _write_journal(p: Path, row: dict) -> None:
    """One row per UTC day: today's row is updated (trades of the day add up), earlier rows stay."""
    rows = []
    if p.exists():
        with p.open(newline="") as f:
            rows = list(csv.DictReader(f))
    today = next((r for r in rows if r.get("date") == row["date"]), None)
    if today is not None:
        rows.remove(today)
        row = {**row, "rebalanced": row["rebalanced"] or today.get("rebalanced") == "True",
               "turnover": round(row["turnover"] + float(today.get("turnover") or 0), 6)}
    rows.append({k: str(v) for k, v in row.items()})
    tmp = p.with_name(p.name + ".tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(row))
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, p)


def step(now_ms: int | None = None, rule: dict | None = None, listings=None, prices=latest_prices) -> dict | None:
    """One step. Returns the state, or None while the rule has not passed."""
    rule = rule if rule is not None else verdict()
    if rule is None:
        return None
    now_ms = now_ms or int(time.time() * 1000)
    d = ROOT / "paper" / NAME
    d.mkdir(parents=True, exist_ok=True)
    sp = d / "state.json"
    if sp.exists():
        st = json.loads(sp.read_text())
    else:
        st = {"variant": f"new Alpaca listings · ${BUDGET:,.0f} each · hold {rule['horizon_days']}d",
              "started": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(timespec="seconds"),
              "started_ms": now_ms, "horizon_days": int(rule["horizon_days"]), "cash": START_EQUITY,
              "open": [], "seen": [], "fees": 0.0}
    horizon_ms = int(st["horizon_days"]) * DAY_MS
    new = [x for x in (listings if listings is not None else alpaca_listings(int(st["started_ms"])))
           if x["symbol"] not in st["seen"]]
    want = sorted({p["symbol"] for p in st["open"]} | {x["symbol"] for x in new})
    px = prices(want) if want else {}
    traded = 0.0
    # Sell what is due first, so a slot frees up for today's listing.
    still = []
    for p in st["open"]:
        if now_ms - int(p["opened_ms"]) >= horizon_ms and p["symbol"] in px:
            value = p["qty"] * px[p["symbol"]]
            fee = value * COST
            st["cash"] += value - fee
            st["fees"] += fee
            traded += value
            _append(d / "trades.csv", {"ts_ms": now_ms, "symbol": p["symbol"], "side": "sell", "qty": p["qty"],
                                       "price": px[p["symbol"]], "fee": round(fee, 6),
                                       "pnl": round(value - fee - p["cost_basis"], 6), "note": "horizon"})
        else:
            still.append(p)
    st["open"] = still
    for x in new:
        sym = x["symbol"]
        if sym not in px:
            continue                        # no trade yet: try again next run
        st["seen"].append(sym)
        if len(st["open"]) >= MAX_OPEN or st["cash"] < BUDGET:
            _append(d / "trades.csv", {"ts_ms": now_ms, "symbol": sym, "side": "skip", "qty": 0, "price": px[sym],
                                       "fee": 0, "pnl": 0, "note": f"{MAX_OPEN} open"})
            continue
        fee = BUDGET * COST
        qty = (BUDGET - fee) / px[sym]
        st["cash"] -= BUDGET
        st["fees"] += fee
        traded += BUDGET
        st["open"].append({"symbol": sym, "qty": qty, "entry": px[sym], "opened_ms": now_ms, "cost_basis": BUDGET})
        _append(d / "trades.csv", {"ts_ms": now_ms, "symbol": sym, "side": "buy", "qty": qty, "price": px[sym],
                                   "fee": round(fee, 6), "pnl": 0, "note": f"listed {x['ts_ms']}"})
    marks = sum(p["qty"] * px.get(p["symbol"], p["entry"]) for p in st["open"])
    st["equity"] = st["cash"] + marks
    sp.write_text(json.dumps(st, indent=2))
    _write_journal(d / "journal.csv", {
        "date": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(st["equity"], 2), "cash": round(st["cash"], 2), "open": len(st["open"]),
        "longs": " ".join(p["symbol"] for p in st["open"]), "rebalanced": traded > 0,
        "turnover": round(traded / START_EQUITY, 6)})
    return st


def main() -> int:
    st = step()
    if st is None:
        print("listings book: off (the W6 rule has not passed; alerts only)")
    else:
        print(f"listings book: equity {st['equity']:,.2f}, {len(st['open'])} open")
    return 0


if __name__ == "__main__":
    sys.exit(main())
