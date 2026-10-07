"""Paper forward test of the market-neutral M2 book (gate 7). No real money, no perps account.

The variant picked in reports/picks_ls: long the 10 best and short the 10 worst
M2 picks among the 50 most liquid USDT perpetuals, skipping short candidates
whose funding over the last three days was negative; half the capital per
side; rebalanced every seven days.

Every run (daily, after the nightly backfill):
  1. mark the book to Binance USD-M last prices and book the funding that
     actually settled since the last run (longs pay positive rates, shorts
     receive them);
  2. on a rebalance day, retrain M2 on all history with the same code as the
     backtest (lab.experiments.picks), score yesterday's coins, pick the book,
     and trade into it at live prices plus 10 bps per unit of turnover.

State: <data>/paper/picks_ls/state.json   Journal: <data>/paper/picks_ls/journal.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import lightgbm as lgb
import numpy as np
import polars as pl

from ..data import ROOT
from ..experiments.picks import FEATURES, HORIZON, PARAMS, PERP_FEATURES, build
from ..experiments.picks_ls import COST, perp_panel

K, N = 10, 50
START_EQUITY = 10_000.0
DAY_MS = 86_400_000
FAPI = "https://fapi.binance.com/fapi/v1"
# --v2 runs the same book on M2 v2 (with perpetual features) in its own folder,
# so both versions earn their gate-7 record side by side.
V2 = "--v2" in sys.argv
DIR = ROOT / "paper" / ("picks_ls_v2" if V2 else "picks_ls")


def get(url: str):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def last_prices() -> dict[str, float]:
    return {t["symbol"]: float(t["price"]) for t in get(f"{FAPI}/ticker/price")}


def funding_since(symbol: str, since_ms: int) -> float:
    rows = get(f"{FAPI}/fundingRate?symbol={symbol}&startTime={since_ms}&limit=1000")
    return float(sum(float(r["fundingRate"]) for r in rows if int(r["fundingTime"]) > since_ms))


def pick_book() -> tuple[list[str], list[str], int]:
    """Retrain M2 on everything and choose this week's book exactly as the backtest does."""
    P = build(with_perp=V2)
    feats = FEATURES + PERP_FEATURES if V2 else FEATURES
    days = P["day"].to_numpy()
    fwd = P["fwd"].to_numpy()
    last_day = int(days.max())
    train = np.isfinite(fwd) & (days < last_day - HORIZON * 86_400_000_000)
    order = np.argsort(days[train], kind="stable")
    X = P.select(feats).to_numpy().astype(np.float32)
    y = P["label"].to_numpy()
    _, group = np.unique(days[train][order], return_counts=True)
    model = lgb.LGBMRanker(**PARAMS).fit(X[train][order], y[train][order].astype(np.int32), group=group)
    today = days == last_day
    scores = pl.DataFrame({"base": P["symbol"].to_numpy()[today], "score": model.predict(X[today])}).with_columns(
        base=pl.col("base").str.strip_suffix("USDT"))

    perps = perp_panel()
    live = {s["symbol"] for s in get(f"{FAPI}/exchangeInfo")["symbols"]
            if s.get("contractType") == "PERPETUAL" and s["status"] == "TRADING" and s["symbol"].endswith("USDT")}
    latest = perps.sort("day").group_by("perp").tail(1).filter(pl.col("perp").is_in(list(live)))
    g = (scores.join(latest.select("base", "perp", "adv28", "fund_past"), on="base", how="inner")
         .drop_nulls(["adv28"]).sort("adv28", descending=True).head(N).sort("score", descending=True))
    longs = g.head(K)["perp"].to_list()
    shorts = g.tail(g.height - K).filter(pl.col("fund_past").fill_null(0.0) >= 0).tail(K)["perp"].to_list()
    return longs, shorts, last_day


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    now_ms = int(time.time() * 1000)
    state_file = DIR / "state.json"
    st = json.loads(state_file.read_text()) if state_file.exists() else {
        "variant": f"top {K} / bottom {K} of the {N} most liquid perps, no paying shorts" + (", M2 v2" if V2 else ""),
        "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "equity": START_EQUITY, "positions": {}, "last_run_ms": None, "last_rebalance_ms": None,
    }
    prices = last_prices()
    equity = st["equity"]

    # 1 · mark to market and book funding since the last run
    pnl_price = pnl_funding = 0.0
    for sym, p in st["positions"].items():
        px = prices.get(sym)
        if px is None:  # delisted: it settled at its last price, which is the one we have
            px = p["price"]
        sign = 1.0 if p["side"] == "long" else -1.0
        pnl_price += sign * p["qty"] * (px - p["price"])
        if st["last_run_ms"]:
            rate = funding_since(sym, st["last_run_ms"])
            pnl_funding += -sign * rate * p["qty"] * px
        p["price"] = px
    equity += pnl_price + pnl_funding

    # 2 · rebalance every HORIZON days
    rebalanced, traded, longs, shorts = False, 0.0, [], []
    due = st["last_rebalance_ms"] is None or now_ms - st["last_rebalance_ms"] >= HORIZON * DAY_MS - 6 * 3_600_000
    if due:
        longs, shorts, _ = pick_book()
        target = {s: ("long", 0.5 / K) for s in longs} | {s: ("short", 0.5 / K) for s in shorts}
        new_pos = {}
        for sym, (side, w) in target.items():
            if sym not in prices:
                continue
            new_pos[sym] = {"side": side, "qty": w * equity / prices[sym], "price": prices[sym]}
        old = set(st["positions"]) | set(new_pos)
        for sym in old:
            a, b = st["positions"].get(sym), new_pos.get(sym)
            va = (a["qty"] * a["price"]) * (1 if a["side"] == "long" else -1) if a else 0.0
            vb = (b["qty"] * b["price"]) * (1 if b["side"] == "long" else -1) if b else 0.0
            traded += abs(vb - va)
        equity -= traded * COST
        st["positions"] = new_pos
        st["last_rebalance_ms"] = now_ms
        rebalanced = True

    row = {
        "date": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity, 2),
        "price_pnl": round(pnl_price, 2),
        "funding_pnl": round(pnl_funding, 2),
        "rebalanced": rebalanced,
        "turnover": round(traded / max(equity, 1e-9), 4),
        "longs": " ".join(longs) if rebalanced else "",
        "shorts": " ".join(shorts) if rebalanced else "",
    }
    journal = DIR / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            w.writeheader()
        w.writerow(row)
    st.update(equity=equity, last_run_ms=now_ms)
    state_file.write_text(json.dumps(st, indent=2))
    print(json.dumps(row))
    return 0


if __name__ == "__main__":
    sys.exit(main())
