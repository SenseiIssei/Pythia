"""Paper forward tests of the momentum candidates (gate 7). No real money.

Runs once a day at 04:00 UTC, after the 03:30 backfill has fetched yesterday's
klines. Each book computes its target weights with the SAME function the
backtest uses, from the same files, marks to market at live Binance prices and
rebalances at the live touch: buys at the ask, sells at the bid, plus the
10 bps taker fee. The modelled cost (15 bps per unit of turnover, as in the
backtest) is journaled next to it, so after 30 days we can see whether the
backtest's cost assumption holds.

Books (picked in-sample, see reports/tsmom and reports/momentum2):
  tsmom          28d · daily · vol 40%            since 2026-10-06
  tsmom_regime   the same, flat while BTC < 200d  since 2026-10-07

Per book: <data>/paper/<book>/state.json and journal.csv
"""

from __future__ import annotations

import csv
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone

import numpy as np

from ..data import ROOT
from ..experiments.tsmom import COST, DAY_US, daily_matrix, rolling_mean, target_weights

BOOKS = {
    "tsmom": {"variant": "28d · daily · vol 40%", "lookbacks": [28], "target": 0.40, "regime": False, "engine": False},
    "tsmom_regime": {"variant": "28d · daily · vol 40% · regime", "lookbacks": [28], "target": 0.40, "regime": True,
                     "engine": True},
}
# "engine": whether the book also gets a signal file for Pythia to execute. One
# engine holds one position per market, so two books on the same coins cannot
# both run there; the weaker candidate stays a lab-only paper book.
TAKER = 0.0010
START_EQUITY = 10_000.0


def live_quotes(symbols: list[str]) -> dict[str, tuple[float, float]]:
    with urllib.request.urlopen("https://api.binance.com/api/v3/ticker/bookTicker", timeout=20) as r:
        book = {q["symbol"]: (float(q["bidPrice"]), float(q["askPrice"])) for q in json.load(r)}
    return {s: book[s] for s in symbols if s in book}


def step(name: str, cfg: dict, tgt: np.ndarray, names: list[str], bid: np.ndarray, ask: np.ndarray,
         close_t: np.ndarray, now_us: int) -> dict:
    d = ROOT / "paper" / name
    d.mkdir(parents=True, exist_ok=True)
    mid = (bid + ask) / 2
    state_file = d / "state.json"
    if state_file.exists():
        st = json.loads(state_file.read_text())
    else:
        st = {"variant": cfg["variant"], "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY, "weights": [0.0] * len(names), "mid": None, "names": names}
    w = np.array(st["weights"])
    equity = st["equity"]

    gross = 0.0
    if st["mid"] is not None:
        prev = np.array(st["mid"], dtype=float)
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.nan_to_num(mid / prev - 1)
        gross = float(np.dot(w, r))
        equity *= 1 + gross
        if 1 + gross > 0:
            w = w * (1 + r) / (1 + gross)

    delta = tgt - w
    half_spread = np.nan_to_num((ask - bid) / mid / 2)
    paper_cost = float(np.sum(np.abs(delta) * (TAKER + half_spread)))
    model_cost = float(np.sum(np.abs(delta)) * COST)
    equity *= 1 - paper_cost
    # How far the live price had moved from the close the signal used (the backtest fills at that close)
    with np.errstate(invalid="ignore", divide="ignore"):
        drift = np.nan_to_num(mid / close_t - 1)
    timing_bps = float(np.dot(np.abs(delta), drift) / max(np.abs(delta).sum(), 1e-12) * 1e4)

    row = {
        "date": datetime.fromtimestamp(now_us / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity, 2),
        "gross_ret_pct": round(gross * 100, 4),
        "paper_cost_bps": round(paper_cost * 1e4, 2),
        "model_cost_bps": round(model_cost * 1e4, 2),
        "turnover": round(float(np.abs(delta).sum()), 4),
        "exposure": round(float(tgt.sum()), 4),
        "held": int((tgt > 0).sum()),
        "timing_drift_bps": round(timing_bps, 2),
        "weights": json.dumps({n: round(float(x), 4) for n, x in zip(names, tgt) if x > 0}),
    }
    journal = d / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)

    st.update(equity=equity, weights=tgt.tolist(), mid=[float(x) for x in mid])
    state_file.write_text(json.dumps(st, indent=2, allow_nan=True))
    return row


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // DAY_US - 1) * DAY_US
    days, close, rv, names = daily_matrix()
    if days[-1] < yesterday:
        print(f"history ends {datetime.fromtimestamp(days[-1] / 1e6, timezone.utc):%Y-%m-%d}, "
              "yesterday is missing; not rebalancing on stale data", file=sys.stderr)
        return 1
    t = int(np.flatnonzero(days == yesterday)[0])
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
    risk_on = bool(btc[t] > ma200[t])

    symbols = [f"{n}USDT" for n in names]
    q = live_quotes(symbols)
    bid = np.array([q.get(s, (np.nan, np.nan))[0] for s in symbols])
    ask = np.array([q.get(s, (np.nan, np.nan))[1] for s in symbols])

    # --signals-only refreshes the engine's signal files without stepping the paper books.
    signals_only = "--signals-only" in sys.argv
    for name, cfg in BOOKS.items():
        tgt = target_weights(close, sigma, history, t, cfg["lookbacks"], cfg["target"])
        if cfg["regime"] and not risk_on:
            tgt = np.zeros_like(tgt)
        if signals_only:
            write_signal(name, cfg, tgt, names, int(days[t]), now_us, risk_on)
            continue
        row = step(name, cfg, tgt, names, bid, ask, close[t], now_us)
        write_signal(name, cfg, tgt, names, int(days[t]), now_us, risk_on)
        print(name, json.dumps(row))
    return 0


def evidence(cfg: dict) -> dict:
    """What the lab measured for this variant, for the engine's Strategy Passport."""
    src = "momentum2" if cfg["regime"] else "tsmom"
    try:
        rep = json.loads((ROOT / "reports" / src / "latest.json").read_text())
    except (OSError, ValueError):
        return {"report": src, "missing": True}
    if src == "tsmom":
        chosen = rep["chosen"]
        return {"report": src, "oos_sharpe": chosen["oos_sharpe"], "oos_max_dd": chosen["oos_max_dd"],
                "is_sharpe": chosen["is_sharpe"], "deflated_p": rep["deflated_p"],
                "sharpe_2x_cost": next((c["sharpe"] for c in rep.get("cost_sensitivity", []) if c["costs"] == "2x"), None),
                "variants_tried": len(rep["rows"]),
                "plateau_share": sum(r["oos_sharpe"] > 0 for r in rep["rows"]) / len(rep["rows"]),
                "regime_sharpes": {r["regime"]: r["strategy_sharpe"] for r in rep.get("regimes", [])},
                "regime_filter": False}
    pick = next(d for d in rep["details"] if d["family"] == "A regime")
    return {"report": src, "oos_sharpe": pick["oos_sharpe"], "oos_max_dd": pick["oos_max_dd"],
            "is_sharpe": pick["is_sharpe"], "deflated_p": pick["deflated_p"],
            "sharpe_2x_cost": pick["sharpe_2x_cost"], "variants_tried": len(rep["rows"]),
            "plateau_share": pick["family_positive_share"],
            "regime_sharpes": {"BTC above 200d average": pick["sharpe_btc_above"],
                               "BTC below 200d average": pick["sharpe_btc_below"]},
            "regime_filter": True}


def write_signal(name: str, cfg: dict, tgt: np.ndarray, names: list[str], as_of_us: int, now_us: int,
                 risk_on: bool) -> None:
    """Target weights for the engine to execute: Python decides, Rust executes.

    The engine treats a signal older than `valid_until_ms` as stale and holds
    still rather than trading on yesterday's decision.
    """
    if not cfg.get("engine"):
        return
    sig = {
        "strategy": name,
        "variant": cfg["variant"],
        "as_of_ms": as_of_us // 1000,            # the daily close the weights were computed from
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + 36 * 3600 * 1000,
        "quote": "USD",
        "weights": {n: round(float(x), 6) for n, x in zip(names, tgt) if x > 0},
        "regime_on": risk_on if cfg["regime"] else None,
        "evidence": evidence(cfg),
    }
    save_signal(name, sig, now_us)


def save_signal(name: str, sig: dict, now_us: int, root=None) -> None:
    """<root>/signals/<name>/latest.json, replaced atomically, plus a dated copy."""
    d = (ROOT if root is None else root) / "signals" / name
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "latest.json.tmp"
    tmp.write_text(json.dumps(sig, indent=2))
    tmp.replace(d / "latest.json")
    (d / f"{datetime.fromtimestamp(now_us / 1e6, timezone.utc):%Y-%m-%d}.json").write_text(json.dumps(sig, indent=2))


if __name__ == "__main__":
    sys.exit(main())
