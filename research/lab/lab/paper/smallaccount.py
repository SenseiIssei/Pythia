"""EXPERIMENTAL paper books with small wallets: 40, 50 and 100 EUR at Jupiter's real costs and minimums. No real money.

    python -m lab.paper.smallaccount              mark, rebalance, journal every book, write the EUR report
    python -m lab.paper.smallaccount --dry-run    print the targets, prices and what would trade; write nothing

Picked by the S1 study (results/smallaccount_s1_prereg.md, results/smallaccount_s1.md):
the best in-sample Sharpe at 50 EUR, and the best at 100 EUR among the other
candidates, both with the study's own wallet and costs:

  small50_tsmom1          tsmom_top20 on the single most liquid coin (BTC, some
                          days ETH): held while its 28-day return is above 0 and
                          BTC above its 200-day average, sized to 40 % annual vol;
                          daily, a 50 EUR wallet.
  small100_breakout_sol3  Donchian 20/10 among the 3 most liquid coins with a
                          Solana mint (BTC, ETH, SOL), 3 slots; daily, a 100 EUR
                          wallet.

Picked by the S2 study (results/smallaccount_s2_prereg.md, results/smallaccount_s2.md):
the two best in-sample candidates at 40 EUR with an in-sample drawdown under 20 %
(S2_BOOKS), on the S&P 500 token, BTC (cbBTC), the gold token and USDC, with S2's
venue (its quote ladder, the Sender tip on the network fee, the way there as one
SOL to USDC swap). Their rules read SPY's and GLD's adjusted closes from Yahoo at
run time (<data>/etf/daily when Yahoo does not answer); closes older than
ETF_STALE_DAYS before the decision close only mark.

Targets come from the sweep's daily panel (the cache paper-families rebuilds at
04:15, read with PYTHIA_AGENT_OUT=/data/lab-cache); a panel without yesterday's
close only marks. The wallet is lab.experiments.smallaccount's: cash and coin
units in EUR, the Jupiter venue's costs (half the recorded round trip at the
order's size plus 0.000105 SOL a swap), MIN_TRADE 5 USDC, a SOL reserve held idle
and the way there paid once at the start (Kraken's taker fee to buy USDC, 1 USDC
to withdraw). Prices are Jupiter's live USD prices (price/v3) in EUR at Kraken's
live EUR/USD mid (the study's snapshot rate when Kraken does not answer). A
missing price keeps the last mark and trades nothing in that coin.

Per book: <data>/paper/<book>/state.json, journal.csv (equity on the 10,000 basis
the forward report assumes, equity_eur the wallet itself) and trades.csv; the
report in EUR: reports/smallaccount/latest.md and .json (a feed for the app).
Nothing here signs, sends or holds a key.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import report
from ..data import WRITE_ROOT
from ..experiments import fam_common as fc
from ..experiments import smallaccount as s1
from ..experiments import smallaccount_s2 as s2

REPORT = "smallaccount"
INDEX = 10_000.0
BOOKS = {
    "small50_tsmom1": {"key": "tsmom_top20", "n": 1, "cadence": "daily", "venue": "jupiter", "capital": 50.0,
                       "label": "28d momentum on the most liquid coin, regime"},
    "small100_breakout_sol3": {"key": "breakout_sol", "n": 3, "cadence": "daily", "venue": "jupiter",
                               "capital": 100.0, "label": "Donchian 20/10 on BTC, ETH, SOL (3 coins with a mint)"},
}
# S2: 40 EUR wallets, the candidates of lab.experiments.smallaccount_s2 (keys SPY, BTC, GOLD; USDC is cash).
S2_PICKS = ("spy_trend", "vol_target")
S2_BOOKS = {f"small40_{k}": {"study": "S2", "key": k, "n": s2.SLOTS[k], "cadence": s2.CADENCE[k], "venue": "jupiter",
                             "capital": 40.0, "label": s2.CANDIDATES[k]} for k in S2_PICKS}
ALL_BOOKS = {**BOOKS, **S2_BOOKS}
ETF_STALE_DAYS = 5
JOURNAL_COLS = ["date", "equity", "equity_eur", "gross_ret_pct", "paper_cost_bps", "model_cost_bps", "turnover",
                "exposure", "held", "orders", "not_sent", "dust", "rebalanced", "signal", "weights"]
TRADE_COLS = ["ts", "side", "coin", "eur", "units", "price_eur", "cost_eur"]


def _day(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")


def variant(name: str, equity_eur: float | None = None) -> str:
    b = ALL_BOOKS[name]
    now = f" · now {equity_eur:,.2f} EUR" if equity_eur is not None else ""
    return (f"EXPERIMENT, paper only · {b.get('study', 'S1')} small account · {b['capital']:.0f} EUR paper wallet · "
            f"{b['label']} · "
            f"{b['cadence']} · Jupiter costs and minimums{now} (journal equity on the 10,000 basis)")


def book_dir(name: str, root: Path | None = None) -> Path:
    return (WRITE_ROOT if root is None else root) / "paper" / name


def load_state(d: Path) -> dict | None:
    try:
        return json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_state(d: Path, st: dict) -> None:
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / "state.json.tmp"
    tmp.write_text(json.dumps(st, indent=2), encoding="utf-8")
    tmp.replace(d / "state.json")


def _append(path: Path, cols: list[str], rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        if new:
            wr.writeheader()
        wr.writerows(rows)


def _read_csv(path: Path) -> list[dict]:
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def new_state(name: str, venue: s1.Venue, sol_eur: float, now_ms: int) -> dict:
    b = ALL_BOOKS[name]
    idle, once = venue.setup(b["capital"], b["n"], sol_eur)
    return {"variant": variant(name), "started": datetime.fromtimestamp(now_ms / 1000, timezone.utc).isoformat(
        timespec="seconds"), "capital_eur": b["capital"], "cash": b["capital"] - idle - once, "idle": idle,
        "setup_eur": once, "units": {}, "last": {}, "marks": {}, "costs_eur": once, "orders": 0, "not_sent": 0,
        "dust": 0, "equity_eur": b["capital"], "signal": None}


def targets(P: fc.Panel, name: str, t: int) -> dict[str, float]:
    """The book's target weights at the decision close t, by coin (the sweep's segments summed, a reused
    ticker's old segment as 0)."""
    b = BOOKS[name]
    W = s1.ffill(s1.candidate(P, b["key"], b["n"]))
    out: dict[str, float] = {}
    for j in np.flatnonzero(np.nan_to_num(W[t]) > 0):
        if "~" not in P.names[j]:
            c = fc.base_of(P.names[j])
            out[c] = out.get(c, 0.0) + float(W[t, j])
    return out


def s2_plan(P: fc.Panel, name: str, t: int, m: s2.Market) -> tuple[dict[str, float], bool, bool]:
    """An S2 book's (targets by asset with its zeros, due at close t, every asset back to target at t)."""
    keys, W, due, reweigh = s2.candidate(ALL_BOOKS[name]["key"], m, P)
    return {k: float(W[t, j]) for j, k in enumerate(keys)}, bool(due[t]), bool(reweigh[t])


def live_etf(syms=("SPY", "GLD")) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Yahoo's adjusted daily closes now, <data>/etf/daily for a symbol Yahoo does not answer for."""
    from ..experiments import etf_trend as et
    out = {}
    for sym in syms:
        try:
            out[sym] = et.parse_stooq(et.download_yahoo(sym))
        except et.DataUnavailable as e:
            print(f"yahoo {sym}: {e}; the lab's copy instead", file=sys.stderr)
            out[sym] = et.parse_stooq(et.load_csv(sym))
    return out


def etf_fresh(etf: dict[str, tuple[np.ndarray, np.ndarray]], decision_day: str) -> bool:
    d = np.datetime64(decision_day)
    return all(0 <= int((d - dates[-1]).astype(int)) <= ETF_STALE_DAYS for dates, _ in etf.values())


def step(name: str, st: dict, tgt: dict[str, float] | None, prices: dict[str, float], venue: s1.Venue,
         sol_eur: float, now_ms: int, decision_day: str | None, rebalance: bool,
         reweigh: bool = False) -> tuple[dict, dict, list[dict]]:
    """One daily run of one book: mark, rebalance when due and the targets are fresh, journal row.
    Returns (state, journal row, fills). `prices` are EUR per coin; a coin without one keeps its last mark.
    `reweigh` trades every asset back to its target (S2's monthly days), not only the changed ones."""
    marks = {**st.get("marks", {}), **{c: p for c, p in prices.items() if p > 0}}
    last = {} if reweigh and rebalance and tgt is not None else dict(st["last"])
    w = s1.Wallet(cash=st["cash"], units=dict(st["units"]), last=last, idle=st["idle"],
                  costs=st["costs_eur"], orders=st["orders"], skipped=st["not_sent"], dust=st["dust"])
    before = w.value(marks)
    costs0, orders0, skipped0, dust0 = w.costs, w.orders, w.skipped, w.dust
    fills: list[dict] = []
    if rebalance and tgt is not None:
        held = set(w.units) | set(w.last)
        full = {c: tgt.get(c, 0.0) for c in held | set(tgt)}
        fills = s1.rebalance(w, full, marks, venue, sol_eur, can_trade=lambda c: c in prices)
        if reweigh:
            w.last.update({c: x for c, x in full.items() if c in prices})
    eq = w.value(marks)
    traded = sum(f["eur"] for f in fills)
    cost = w.costs - costs0
    expo = sum(u * marks.get(c, 0.0) for c, u in w.units.items())
    cap = st["capital_eur"]
    row = {"date": _day(now_ms), "equity": round(eq / cap * INDEX, 4), "equity_eur": round(eq, 4),
           "gross_ret_pct": round(((eq + cost) / before - 1) * 100, 4) if before > 0 else 0.0,
           "paper_cost_bps": round(cost / before * 1e4, 3) if before > 0 else 0.0,
           "model_cost_bps": round(traded / before * s1.IDEAL_COST * 1e4, 3) if before > 0 else 0.0,
           "turnover": round(traded / before, 6) if before > 0 else 0.0,
           "exposure": round(expo / eq, 6) if eq > 0 else 0.0, "held": len(w.units),
           "orders": w.orders - orders0, "not_sent": w.skipped - skipped0, "dust": w.dust - dust0,
           "rebalanced": bool(fills), "signal": decision_day or "",
           "weights": json.dumps({c: round(x, 4) for c, x in sorted((tgt or {}).items())})}
    st = {**st, "variant": variant(name, eq), "cash": w.cash, "units": w.units, "last": w.last, "marks": marks,
          "costs_eur": w.costs, "orders": w.orders, "not_sent": w.skipped, "dust": w.dust, "equity_eur": eq,
          "equity": eq / cap * INDEX, "signal": {"as_of": decision_day, "targets": tgt} if tgt is not None
          else st.get("signal")}
    fills = [{"ts": now_ms, "side": f["side"], "coin": f["key"], "eur": round(f["eur"], 4), "units": f["units"],
              "price_eur": f["price"], "cost_eur": round(f["cost"], 5)} for f in fills]
    return st, row, fills


# ---------------------------------------------------------------- live prices

def eurusd_live(fallback: float) -> float:
    try:
        r = s1._get_json(f"{s1.KRAKEN_API}/Ticker?pair=EURUSD")["result"]
        t = next(iter(r.values()))
        v = (float(t["a"][0]) + float(t["b"][0])) / 2
        return v if 0.5 < v < 2.0 else fallback
    except (OSError, ValueError, KeyError, StopIteration, IndexError, TypeError):
        return fallback


def prices_eur(coins: set[str], eurusd: float, client=None, extra: dict[str, str] | None = None) -> dict[str, float]:
    """Jupiter's USD price of each coin's mint, in EUR. A coin without a mint or a price is left out.
    `extra` names the mints of S2's keys (SPY and GOLD: the tokens the study picked)."""
    from ..onchain import mints as M
    from ..onchain.jupiter import Jupiter, QuoteError
    extra = extra or {}
    mints = {c: extra.get(c) or M.COINS[c].mint for c in coins | {"SOL"} if c in extra or c in M.COINS}
    try:
        got = (client or Jupiter()).prices(sorted(set(mints.values())))
    except QuoteError as e:
        print(f"jupiter prices: {e}", file=sys.stderr)
        return {}
    return {c: got[m] / eurusd for c, m in mints.items() if got.get(m)}


# ---------------------------------------------------------------- the report

def write_report(books: dict[str, dict], now_ms: int) -> dict:
    md = ["# Small-account paper books (S1 and S2), in EUR\n",
          "EXPERIMENT, paper only. Picked by results/smallaccount_s1.md (the best in-sample variant at 50 EUR and "
          "at 100 EUR) and results/smallaccount_s2.md (the two best in-sample candidates at 40 EUR on the S&P 500 "
          "token, BTC, gold and USDC), with Jupiter's real costs and minimums. No real money.\n"]
    items, rows = [], []
    for name, st in books.items():
        b = ALL_BOOKS[name]
        cap, eq = st["capital_eur"], st["equity_eur"]
        held = ", ".join(f"{c} {u * st['marks'].get(c, 0.0):.2f} EUR" for c, u in sorted(st["units"].items())) or "cash"
        rows.append({"book": name, "study": b.get("study", "S1"), "wallet": f"{cap:.0f} EUR", "now": f"{eq:,.2f} EUR", "result": f"{eq - cap:+.2f} EUR",
                     "return": f"{(eq / cap - 1) * 100:+.2f} %", "costs paid": f"{st['costs_eur']:.2f} EUR",
                     "orders": st["orders"], "not sent": st["not_sent"], "held": held, "since": st["started"][:10]})
        items.append({"label": f"{name} ({cap:.0f} EUR)", "value": f"{eq:,.2f} EUR ({eq - cap:+.2f})",
                      "detail": f"{b['label']}; holds {held}; costs so far {st['costs_eur']:.2f} EUR",
                      "status": "ok" if eq >= cap else "watch"})
    md.append(report.table(rows, ["book", "study", "wallet", "now", "result", "return", "costs paid", "orders", "not sent",
                                  "held", "since"]))
    md.append("Costs paid include the way there: S1 from EUR (Kraken's taker fee to USDC, 1 USDC to withdraw), S2 "
              "from SOL (one SOL to USDC swap). The SOL reserve for network fees is part of the wallet and earns "
              "nothing. S2 holds the S&P 500 token and the gold token the study picked (tokenized tracker "
              "certificates or gold, not for US persons, see results/smallaccount_s2.md).\n")
    total = sum(st["equity_eur"] for st in books.values())
    start = sum(st["capital_eur"] for st in books.values())
    data = {**report.feed_header("Small-account paper books", "ok" if total >= start else "watch",
                                 f"{total:,.2f} EUR from {start:,.0f} EUR ({total - start:+.2f} EUR)", items=items,
                                 updated_ms=now_ms), "books": books}
    report.write(REPORT, "\n".join(md), data)
    return data


def main() -> int:
    now_ms = int(time.time() * 1000)
    yesterday = (now_ms * 1000 // fc.DAY_US - 1) * fc.DAY_US
    dry = "--dry-run" in sys.argv
    vs = s1.venues()
    P = fc.load_panel()
    fresh = P.days[-1] >= yesterday
    t = int(np.flatnonzero(P.days == yesterday)[0]) if fresh else P.T - 1
    decision = _day(int(P.days[t]) // 1000)
    if not fresh:
        print(f"history ends {decision}, yesterday is missing; marking only", file=sys.stderr)
    venue = vs["jupiter"]
    venue.eurusd = eurusd_live(venue.eurusd)
    tg = {name: targets(P, name, t) for name in BOOKS}
    plan = {name: (tg[name], s1.rebalance_day(P.days[t], s1.CADENCES[b["cadence"]]), False) for name, b in BOOKS.items()}
    venues = {name: venue for name in BOOKS}
    extra: dict[str, str] = {}
    if S2_BOOKS:
        snap = s2.load_snapshot()
        v2 = s2.venue(snap=snap)
        v2.eurusd = venue.eurusd
        extra = {k: p["mint"] for k, p in snap["picks"].items() if p}
        etf = live_etf()
        m = s2.market(P, etf, v2.eurusd, s2.drifts_from(snap, s2.tracking()))
        etf_ok = etf_fresh(etf, decision)
        if not etf_ok:
            print(f"ETF closes end {[str(x[0][-1]) for x in etf.values()]}; the S2 books only mark", file=sys.stderr)
        for name in S2_BOOKS:
            tgt, due, rw = s2_plan(P, name, t, m)
            plan[name] = (tgt if etf_ok else None, due and etf_ok, rw)
            venues[name] = v2
    states = {name: load_state(book_dir(name)) for name in ALL_BOOKS}
    coins = set().union(*(set(x[0] or {}) for x in plan.values()), *(set((st or {}).get("units", {}))
                                                                    for st in states.values()))
    prices = prices_eur(coins, venue.eurusd, extra=extra)
    sol_eur = prices.get("SOL", 0.0)
    if dry:
        print("EUR/USD", round(venue.eurusd, 5), "decision close", decision, "fresh" if fresh else "stale")
        print("prices EUR", json.dumps({c: round(p, 4) for c, p in prices.items()}))
        for name in ALL_BOOKS:
            print(name, "targets", json.dumps({c: round(x, 4) for c, x in (plan[name][0] or {}).items()}),
                  "due", plan[name][1], "state", json.dumps({k: (states[name] or {}).get(k)
                                                             for k in ("cash", "units", "equity_eur")}))
        return 0
    if not sol_eur:
        print("no SOL price from Jupiter; nothing marked or traded today", file=sys.stderr)
        return 1
    out = {}
    for name in ALL_BOOKS:
        d = book_dir(name)
        st = states[name] or new_state(name, venues[name], sol_eur, now_ms)
        journal = _read_csv(d / "journal.csv")
        done = bool(journal) and journal[-1].get("date") == _day(now_ms)
        tgt, due, rw = plan[name]
        due = fresh and not done and due and tgt is not None
        st, row, fills = step(name, st, tgt if fresh else None, prices, venues[name], sol_eur, now_ms,
                              decision if fresh and tgt is not None else None, due, reweigh=rw)
        if not done:
            _append(d / "journal.csv", JOURNAL_COLS, [row])
        _append(d / "trades.csv", TRADE_COLS, fills)
        save_state(d, st)
        out[name] = st
        print(name, json.dumps(row))
    write_report(out, now_ms)
    return 0


if __name__ == "__main__":
    sys.exit(main())
