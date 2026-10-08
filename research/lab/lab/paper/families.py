"""Paper forward tests of two candidates from the strategy-family sweep. No real money.

Neither passed the deflation gate (see results/families_summary.md); they run
so that forward evidence accumulates, labelled as such:

  tsmom_top20     28d time-series momentum on the 20 most liquid coins OF EACH
                  DAY, regime filter, unscaled. The survivorship-free twin of
                  tsmom_regime (which trades today's 20 survivors), so the two
                  journals show what survivorship was worth.     since 2026-10-07
  breakout_top10  Donchian 20/10 on the 10 most liquid coins of each day, no
                  regime. The sweep's most robust family.        since 2026-10-07

Each book's target comes from the SAME weight function the sweep used
(fam_volmom.base_weights, fam_breakout.breakout_weights) on a panel rebuilt
from the history files every run. Fills as in paper/tsmom.py: live Binance
touch plus the 10 bps taker fee, the modelled 15 bps per unit of turnover
journaled next to it.

The universe changes from day to day, so unlike paper/tsmom.py the state keeps
weights and marks per symbol rather than as a fixed vector.

Engine signals. Each book also writes <data>/signals/<book>/latest.json in the
format of paper/tsmom.py's write_signal, marked "autopilot_only": the engine
never runs these books on their own (the lab engine already holds tsmom_regime
on overlapping coins, and neither candidate passed deflation); they wait idle
until an autopilot claims one. The weights are what the sweep's simulator
holds after the decision close (breakout positions as they drifted since
entry), restricted to the coins the engine has a market for; the rest is
named in "dropped" and stays cash there. The evidence is the book's pick in
the sweep (families_summary JSON, else results/families_summary.md), with its
failed deflation test. The paper books themselves are unchanged.

  --dry-run        print the books' holdings and the signals; write nothing
  --signals-only   refresh the signal files without stepping the paper books

Per book: <data>/paper/<book>/state.json and journal.csv
"""

from __future__ import annotations

import csv
import json
import re
import sys
import time
from datetime import datetime, timezone

import numpy as np

from ..data import ROOT, UNIVERSE
from ..experiments import fam_breakout, fam_common as fc, fam_volmom
from .tsmom import COST, START_EQUITY, TAKER, live_quotes, save_signal

BOOKS = {
    "tsmom_top20": "28d · top 20 by volume each day · regime · unscaled (fails deflation, forward evidence only)",
    "breakout_top10": "Donchian 20/10 · top 10 by volume each day (fails deflation, forward evidence only)",
}

# Each book's in-sample pick in the sweep, and whether it carries the regime filter.
PICKS = {
    "tsmom_top20": {"family": "volmom", "variant": "tsmom 28d · top 20 · regime · none", "regime": True},
    "breakout_top10": {"family": "breakout", "variant": "Donchian 20/10 · top 10 liquid", "regime": False},
}
REPORT = "families_summary"
# The engine's crypto markets are the lab's 20-coin universe (crypto:<coin>/USD,
# engine::seed_markets in pythia-core). A coin outside it has no market there.
ENGINE_COINS = frozenset(UNIVERSE)
SIGNAL_VALID_MS = 36 * 3600 * 1000


def targets(P: fc.Panel) -> dict[str, np.ndarray]:
    """Each book's full weight matrix, exactly as the sweep built it."""
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    return {
        "tsmom_top20": fam_volmom.base_weights(P, 20, regime=True),
        "breakout_top10": fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False),
    }


def held_now(W: np.ndarray, t: int) -> np.ndarray:
    """The last decided weight of every column up to day t: what the backtest
    holds going into t, before drift. 0 where nothing was ever decided."""
    fin = np.isfinite(W[: t + 1])
    last = t - np.argmax(fin[::-1], axis=0)
    return np.where(fin.any(0), W[last, np.arange(W.shape[1])], 0.0)


def step(name: str, row_w: np.ndarray, P: fc.Panel, t: int, quotes: dict[str, tuple[float, float]],
         now_us: int, start_row: np.ndarray) -> dict:
    d = ROOT / "paper" / name
    d.mkdir(parents=True, exist_ok=True)
    state_file = d / "state.json"
    if state_file.exists():
        st = json.loads(state_file.read_text())
    else:
        st = {"variant": BOOKS[name], "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY, "weights": {}, "mid": {}}
        # A new book starts where the backtest stands, not flat: breakout only
        # writes a weight on the entry day, so "leave it" would never buy the
        # coins it already holds.
        row_w = np.where(np.isnan(row_w), start_row, row_w)
    equity = st["equity"]
    w: dict[str, float] = {s: float(x) for s, x in st["weights"].items()}
    mid = {s: (b + a) / 2 for s, (b, a) in quotes.items()}

    # Mark to market. A held coin without a live quote (delisted overnight) is
    # closed at its last mark, which is what the backtest does at a series end.
    gone = [s for s in w if s not in mid]
    rets = {s: mid[s] / st["mid"][s] - 1 for s in w if s in mid and st["mid"].get(s)}
    gross = sum(w[s] * r for s, r in rets.items())
    equity *= 1 + gross
    if 1 + gross > 0:
        w = {s: x * (1 + rets.get(s, 0.0)) / (1 + gross) for s, x in w.items()}
    for s in gone:
        w.pop(s)

    # Target: the sweep's row for the decision close. NaN means "leave as it is"
    # (breakout holds until its own exit), so the drifted weight stands.
    tgt: dict[str, float] = {}
    for j in np.flatnonzero(np.isfinite(row_w) & (row_w != 0) | np.isnan(row_w)):
        sym = P.names[j]
        if "~" in sym:          # a dead segment of a reused ticker cannot be traded
            continue
        x = row_w[j]
        x = w.get(sym, 0.0) if np.isnan(x) else float(x)
        if x > 0 and sym in mid:
            tgt[sym] = x
    syms = set(w) | set(tgt)
    delta = {s: tgt.get(s, 0.0) - w.get(s, 0.0) for s in syms}
    half = {s: (quotes[s][1] - quotes[s][0]) / mid[s] / 2 for s in syms if s in quotes}
    paper_cost = sum(abs(x) * (TAKER + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * COST
    equity *= 1 - paper_cost
    # How far the live price had moved from the close the signal used (the sweep fills at that close)
    moved = [(abs(x), mid[s] / P.close[t, P.col(s)] - 1) for s, x in delta.items()
             if x and s in mid and np.isfinite(P.close[t, P.col(s)])]
    timing_bps = sum(a * m for a, m in moved) / max(sum(a for a, _ in moved), 1e-12) * 1e4

    row = {
        "date": datetime.fromtimestamp(now_us / 1e6, timezone.utc).strftime("%Y-%m-%d"),
        "equity": round(equity, 2),
        "gross_ret_pct": round(gross * 100, 4),
        "paper_cost_bps": round(paper_cost * 1e4, 2),
        "model_cost_bps": round(model_cost * 1e4, 2),
        "turnover": round(sum(abs(x) for x in delta.values()), 4),
        "exposure": round(sum(tgt.values()), 4),
        "held": len(tgt),
        "timing_drift_bps": round(timing_bps, 2),
        "weights": json.dumps({s[:-4]: round(x, 4) for s, x in sorted(tgt.items())}),
    }
    journal = d / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)

    st.update(equity=equity, weights=tgt, mid={s: mid[s] for s in tgt})
    state_file.write_text(json.dumps(st, indent=2))
    return row


def backtest_weights(P: fc.Panel, W: np.ndarray, t: int, start: int = 60) -> np.ndarray:
    """What the sweep's simulator holds after the close of day t, long-only.

    The same steps as fc.simulate: NaN leaves a coin as it is, only coins that
    trade today can change, weights drift with prices between closes and a
    coin whose series ended is closed. A daily-rebalanced book (tsmom_top20)
    comes out as W[t]; breakout's positions come out as they drifted since
    their entry, so the engine holds what the backtest holds instead of
    resizing every position back to its entry weight each day.
    """
    w = np.zeros(P.N)
    for s in range(start, t + 1):
        tgt = np.where(np.isnan(W[s]), w, W[s])
        w = np.where(P.traded[s] | (tgt == w), tgt, w)
        if s == t:
            break
        r = np.nan_to_num(P.ret[s + 1])
        g = float(np.dot(w, r))
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(P.N)
        w[(w != 0) & ~P.alive[s + 1]] = 0.0
    return np.clip(w, 0.0, None)


def _value(cell: str):
    """A markdown table cell back as a number, bool or string."""
    if cell in ("yes", "no"):
        return cell == "yes"
    if cell == "n/a":
        return None
    try:
        return float(cell.replace(",", ""))
    except ValueError:
        return cell


def _md_tables(text: str) -> list[list[dict]]:
    """Every pipe table in a markdown file, as rows of {header: value}."""
    tables: list[list[dict]] = []
    head = None
    for line in text.splitlines():
        if not line.startswith("|"):
            head = None
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if head is None:
            head = cells
            tables.append([])
        elif not all(set(c) <= set("-:") for c in cells):
            tables[-1].append(dict(zip(head, (_value(c) for c in cells))))
    return tables


def _pick_row(family: str, variant: str) -> tuple[dict | None, int | None, str]:
    """The pick's row in the sweep and the number of variants deflated over.

    The JSON next to the sweep's caches is exact; the markdown in results/
    (rounded to two decimals) is the fallback where the sweep never ran.
    """
    js = fc.OUT / "reports" / f"{REPORT}.json"
    try:
        rep = json.loads(js.read_text(encoding="utf-8"))
        row = next(p for p in rep["picks"] if p["family"] == family and p["variant"] == variant)
        return row, int(rep["n_variants"]), str(js)
    except (OSError, ValueError, KeyError, StopIteration):
        pass
    md = fc.RESULTS_DIR / f"{REPORT}.md"
    try:
        text = md.read_text(encoding="utf-8")
    except OSError:
        return None, None, ""
    picks = next((tb for tb in _md_tables(text) if tb and {"family", "variant", "sub_positive_share"} <= set(tb[0])), [])
    row = next((dict(r) for r in picks if r["family"] == family and r["variant"] == variant), None)
    m = re.search(r"\*\*(\d+) variants\*\*", text)
    if row is None or m is None:
        return None, None, ""
    # The plateau's size: the variants of the pick's sub-family in its family report.
    try:
        fam = _md_tables((fc.RESULTS_DIR / f"family_{family}.md").read_text(encoding="utf-8"))
        every = next(tb for tb in fam if tb and {"sub", "avg_long"} <= set(tb[0]))
        row["sub_variants"] = sum(r["sub"] == row["sub"] for r in every)
    except (OSError, StopIteration):
        pass
    return row, int(m.group(1)), str(md)


def evidence(name: str) -> dict:
    """What the sweep measured for this book's pick, for the engine's Strategy
    Passport and the autopilot's auto pick. Sharpes are net of 15 bps per unit
    of turnover; the "costs doubled" figure is the sweep's 41 bps run (2.7x,
    stricter than 2x). Neither candidate passes: deflated p is far below 0.95."""
    pick = PICKS[name]
    row, n, src = _pick_row(pick["family"], pick["variant"])
    if row is None:
        return {"report": REPORT, "missing": True}
    return {
        "report": REPORT,
        "source": src,
        "variant": pick["variant"],
        "is_sharpe": row["is_sharpe_15bps"],
        "oos_sharpe": row["oos_sharpe_15bps"],
        "oos_max_dd": row["oos_max_dd_41bps"],
        "deflated_p": row["deflated_p"],
        "sharpe_2x_cost": row["oos_sharpe_41bps"],
        "cost_note": "Sharpe at 15 bps per unit of turnover; sharpe_2x_cost is at 41 bps (2.7x)",
        "variants_tried": n,
        "plateau_share": row["sub_positive_share"],
        "plateau_variants": row.get("sub_variants"),
        "regime_sharpes": {"BTC above 200d average": row["oos_sharpe_btc_above"],
                           "BTC below 200d average": row["oos_sharpe_btc_below"]},
        "regime_filter": pick["regime"],
        "verdict": row["verdict"],
    }


def signal(name: str, P: fc.Panel, W: np.ndarray, t: int, now_us: int) -> dict:
    """The engine signal for one book, in the format of paper/tsmom.py's write_signal."""
    w = backtest_weights(P, W, t)
    weights: dict[str, float] = {}
    dropped: dict[str, float] = {}
    for j in np.flatnonzero(w > 0):
        sym, x = P.names[j], float(w[j])
        coin = fc.base_of(sym)
        if "~" not in sym and coin in ENGINE_COINS:
            if round(x, 6) > 0:
                weights[coin] = round(x, 6)
        else:
            label = sym[:-4] if "~" not in sym else sym
            dropped[label] = dropped.get(label, 0.0) + x
    return {
        "strategy": name,
        "variant": BOOKS[name],
        "as_of_ms": int(P.days[t]) // 1000,     # the daily close the weights were computed from
        "generated_ms": now_us // 1000,
        "valid_until_ms": now_us // 1000 + SIGNAL_VALID_MS,
        "quote": "USD",
        "weights": weights,
        "regime_on": bool(P.btc_on[t]) if PICKS[name]["regime"] else None,
        "evidence": evidence(name),
        "autopilot_only": True,
        "dropped": sorted(dropped),
        "dropped_weight": round(sum(dropped.values()), 6),
        "lab_exposure": round(float(w.sum()), 6),
    }


def main() -> int:
    now_us = time.time_ns() // 1000
    yesterday = (now_us // fc.DAY_US - 1) * fc.DAY_US
    dry = "--dry-run" in sys.argv
    signals_only = "--signals-only" in sys.argv
    P = fc.load_panel(fresh=True)
    if P.days[-1] < yesterday:
        ends = f"{datetime.fromtimestamp(P.days[-1] / 1e6, timezone.utc):%Y-%m-%d}"
        if not dry:
            print(f"history ends {ends}, yesterday is missing; not rebalancing on stale data", file=sys.stderr)
            return 1
        # A dry run writes nothing, so it may show the last day there is.
        print(f"dry run: history ends {ends}, yesterday is missing; showing {ends} instead", file=sys.stderr)
        t = P.T - 1
    else:
        t = int(np.flatnonzero(P.days == yesterday)[0])
    W = targets(P)
    if signals_only and not dry:
        for name, w in W.items():
            sig = signal(name, P, w, t, now_us)
            save_signal(name, sig, now_us)
            print(name, "signal", json.dumps(sig["weights"]), "dropped", sig["dropped"])
        return 0

    held = set()
    for name in BOOKS:
        f = ROOT / "paper" / name / "state.json"
        if f.exists():
            held |= set(json.loads(f.read_text())["weights"])
    wanted = {P.names[j] for w in W.values() for j in np.flatnonzero(np.nan_to_num(w[t], nan=1.0) != 0)}
    quotes = live_quotes(sorted((held | wanted) - {s for s in wanted if "~" in s}))

    for name, w in W.items():
        sig = signal(name, P, w, t, now_us)
        if dry:
            now = held_now(w, t)
            row = {P.names[j]: round(float(now[j]), 4) for j in np.flatnonzero(now > 0)}
            print(name, "BTC above 200d" if P.btc_on[t] else "BTC below 200d", json.dumps(row))
            ev = sig["evidence"]
            print(name, "signal", json.dumps(sig["weights"]), f"exposure {sum(sig['weights'].values()):.4f}",
                  f"of {sig['lab_exposure']:.4f}", "dropped", sig["dropped"], f"({sig['dropped_weight']:.4f})")
            print(name, "evidence", json.dumps({k: ev.get(k) for k in (
                "source", "is_sharpe", "oos_sharpe", "sharpe_2x_cost", "deflated_p", "variants_tried",
                "plateau_share", "plateau_variants", "regime_sharpes", "regime_filter", "verdict", "missing")}))
            continue
        print(name, json.dumps(step(name, w[t], P, t, quotes, now_us, held_now(w, t))))
        save_signal(name, sig, now_us)
    return 0


if __name__ == "__main__":
    sys.exit(main())
