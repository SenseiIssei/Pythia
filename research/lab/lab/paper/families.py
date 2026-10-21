"""Paper forward tests of candidates from the strategy-family sweep. No real money.

None passed the deflation gate (see results/families_summary.md); they run
so that forward evidence accumulates, labelled as such:

  tsmom_top20     28d time-series momentum on the 20 most liquid coins OF EACH
                  DAY, regime filter, unscaled. The survivorship-free twin of
                  tsmom_regime (which trades today's 20 survivors), so the two
                  journals show what survivorship was worth.     since 2026-10-07
  breakout_top10  Donchian 20/10 on the 10 most liquid coins of each day, no
                  regime. The sweep's most robust family.        since 2026-10-07
  tsmom_tranches  tsmom_top20's targets held by seven tranches, one rebalanced
                  each day (weekly per tranche, 50 % no-trade band), capital
                  set back to 1/7 each every 30 days: the blend study's
                  weekday-free weekly book, about a third of the daily book's
                  turnover. Simulator and evidence in
                  experiments/tsmom_tranches.py.

Each book's target comes from the SAME weight function the sweep used
(fam_volmom.base_weights, fam_breakout.breakout_weights) on a panel rebuilt
from the history files every run. Fills as in paper/tsmom.py: live Binance
touch plus the 10 bps taker fee, the modelled 15 bps per unit of turnover
journaled next to it.

The universe changes from day to day, so unlike paper/tsmom.py the state keeps
weights and marks per symbol rather than as a fixed vector. tsmom_tranches
keeps one weight map per tranche plus each tranche's share of the book; a run
marks all of them, rebalances only the tranche due on the decision close's
date (calendar days since 2020-01-01, modulo 7) and trades the net change of
the combined book. A missed run leaves that tranche as it is for a week, as
the backtest would not.

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
tsmom_tranches' signal carries the combined target weights of all seven
tranches after the decision close, and its evidence is
results/tsmom_tranches.md (out of sample at Alpaca-like costs).

Factory books. A genome the strategy factory promoted (lab.factory: held-back
gates, deflation over every trial counted, 30 forward shadow days) is listed in
<data>/factory/promoted.json and stepped here as one more paper book,
factory_<key>, with the same fills. Its target on a rebalance day of its own
cadence is what the factory's simulator holds after the decision close (band
applied); on other days it is left as it is. Factory books write no engine
signal: nothing the factory makes reaches an autopilot or live trading on its
own.

  --dry-run        print the books' holdings and the signals; write nothing
  --signals-only   refresh the signal files without stepping the paper books
  --universe NAME  the same three rules choosing only among a universe
                   (lab.universe: alpaca, alpaca15, core, memes, lab20, default,
                   or coins in the engine's format, `alpaca,TRX`): the top 10
                   and top 20 by volume each day are taken within it. The
                   books keep their definitions; these run as separate paper
                   books, <book>@<universe>, write no engine signal (no study
                   backs them) and never touch the books above

Engine coins. The signal keeps the coins the engine has a live market for:
its configured crypto universe (lab.universe.engine_coins, the same
PYTHIA_CRYPTO_UNIVERSE setting the engine reads; by default every coin the
Alpaca paper account lists plus the lab's 20). Before the engine's universe
became configurable this was the lab's 20 coins.

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

from .. import universe as uni
from ..data import ROOT
from ..experiments import alpaca_universe as au
from ..experiments import fam_breakout, fam_common as fc, fam_volmom
from ..experiments import tsmom_tranches as tranches
from .tsmom import COST, START_EQUITY, TAKER, live_quotes, save_signal

BOOKS = {
    "tsmom_top20": "28d · top 20 by volume each day · regime · unscaled (fails deflation, forward evidence only)",
    "breakout_top10": "Donchian 20/10 · top 10 by volume each day (fails deflation, forward evidence only)",
    "tsmom_tranches": "28d · top 20 by volume each day · regime · seven weekly tranches, band 50 % "
                      "(fails deflation, forward evidence only)",
}

# Each book's in-sample pick in the sweep, and whether it carries the regime filter.
PICKS = {
    "tsmom_top20": {"family": "volmom", "variant": "tsmom 28d · top 20 · regime · none", "regime": True},
    "breakout_top10": {"family": "breakout", "variant": "Donchian 20/10 · top 10 liquid", "regime": False},
}
REPORT = "families_summary"
REGIME = {"tsmom_top20": True, "breakout_top10": False, "tsmom_tranches": True}
# The engine's crypto markets (crypto:<coin>/USD): its configured universe
# (pythia-core coins.rs). A coin outside it has no live market there.
ENGINE_COINS = frozenset(uni.engine_coins())
SIGNAL_VALID_MS = 36 * 3600 * 1000


def targets(P: fc.Panel, member: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """Each book's full weight matrix, exactly as the sweep built it. With `member`
    ((N,) bool, a universe's columns) the same rules choose only among it: the
    10 and 20 most liquid eligible members each day instead of the whole panel's."""
    if member is not None:
        W_t = au.tsmom_weights(P, au.top_within(P, member, 20))
        return {"tsmom_top20": W_t,
                "breakout_top10": au.breakout_on(P, au.top_within(P, member, 10), 20, 10),
                "tsmom_tranches": W_t}
    top10 = P.top_liquid(10)
    cols = np.flatnonzero(top10.any(0))
    return {
        "tsmom_top20": fam_volmom.base_weights(P, 20, regime=True),
        "breakout_top10": fam_breakout.breakout_weights(P, cols, top10, 20, 10, regime=False),
        "tsmom_tranches": tranches.targets(P),
    }


def factory_books() -> dict[str, dict]:
    """Paper books the strategy factory promoted, by book name. Empty when there are none."""
    try:
        from ..factory import shadow
        return dict(shadow.promoted().get("books") or {})
    except (OSError, ValueError, KeyError, ImportError):
        return {}


def factory_row(P: fc.Panel, genome: dict, t: int, always: bool = False) -> np.ndarray:
    """(N,) the factory book's target for the decision close t: its simulated holdings
    on a rebalance day of its cadence, NaN ("leave it") on every other day. A book in
    tranches rebalances one tranche every day, so its target is set daily. always:
    the holdings whatever the day (where a new book starts)."""
    from ..factory import build
    row = np.full(P.N, np.nan)
    r = genome["rebalance"]
    if not always and r.get("tranches", 1) == 1 and (int(P.days[t]) // fc.DAY_US) % r["every"]:
        return row
    c = build.make_ctx(P)
    held = build.holdings(c, genome, t)
    row[:] = 0.0
    for name, x in held.items():
        row[P.col(name)] = x
    return row


def book_name(name: str, universe: str | None) -> str:
    """The paper book's directory name: `breakout_top10`, or `breakout_top10@alpaca`."""
    return f"{name}@{universe.lower()}" if universe else name


def variant(name: str) -> str:
    """The journal's description of a book, `<book>@<universe>` included."""
    base, _, u = name.partition("@")
    return BOOKS.get(base, base) + (f" · choosing only among universe {u}" if u else "")


def step(name: str, row_w: np.ndarray, P: fc.Panel, t: int, quotes: dict[str, tuple[float, float]],
         now_us: int, start_row: np.ndarray, label: str | None = None, taker: float = TAKER,
         model: float = COST) -> dict:
    """One run of a paper book. `label` replaces the journal's description of the
    book; `taker` is the fee the paper fill pays on top of the half spread and
    `model` the backtest's cost per unit of turnover (Binance's by default; the
    experimental books on Alpaca coins pass Alpaca's)."""
    d = ROOT / "paper" / name
    d.mkdir(parents=True, exist_ok=True)
    state_file = d / "state.json"
    if state_file.exists():
        st = json.loads(state_file.read_text())
    else:
        st = {"variant": label or variant(name), "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY, "weights": {}, "mid": {}}
        # A new book starts where the backtest stands, not flat: breakout only
        # writes a weight on the entry day, so "leave it" would never buy the
        # coins it already holds. `start_row` is what the backtest holds after
        # the close (backtest_weights: drifted since each entry). The entry
        # weights it used to be started breakout_top10 a third light on NEAR
        # and SUI (results/forward_audit.md).
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
    paper_cost = sum(abs(x) * (taker + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * model
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


def step_tranches(P: fc.Panel, W: np.ndarray, t: int, quotes: dict[str, tuple[float, float]],
                  now_us: int, name: str = "tsmom_tranches") -> dict:
    """One run of the tranche book: mark every tranche, rebalance the one due on
    the decision close's date, trade the net change of the combined book.

    State: "alloc" (each tranche's share of the book) and "tranches" (per
    tranche, weights as shares of that tranche). A new book starts where the
    backtest stands after the decision close, all seven tranches filled.
    """
    d = ROOT / "paper" / name
    d.mkdir(parents=True, exist_ok=True)
    state_file = d / "state.json"
    mid = {s: (b + a) / 2 for s, (b, a) in quotes.items()}
    k = tranches.due_tranche(int(P.days[t]))
    reset = tranches.reset_due(int(P.days[t]))

    def book(alloc: list[float], tr: list[dict[str, float]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for a, w in zip(alloc, tr):
            for s, x in w.items():
                out[s] = out.get(s, 0.0) + a * x
        return out

    if state_file.exists():
        st = json.loads(state_file.read_text())
        alloc = [float(a) for a in st["alloc"]]
        tr = [{s: float(x) for s, x in w.items()} for w in st["tranches"]]
        equity = st["equity"]
        # Mark to market, per tranche. A coin without a live quote is closed at its last mark.
        held = {s for w in tr for s in w}
        rets = {s: mid[s] / st["mid"][s] - 1 for s in held if s in mid and st["mid"].get(s)}
        gk = [sum(x * rets.get(s, 0.0) for s, x in w.items()) for w in tr]
        gross = sum(a * g for a, g in zip(alloc, gk))
        equity *= 1 + gross
        if 1 + gross > 0:
            alloc = [a * (1 + g) / (1 + gross) for a, g in zip(alloc, gk)]
        tr = [{s: x * (1 + rets.get(s, 0.0)) / (1 + g) for s, x in w.items() if s in mid} if 1 + g > 0 else {}
              for w, g in zip(tr, gk)]
        before = book(alloc, tr)
        # The due tranche goes to the momentum targets, with the backtest's band.
        cur = tr[k]
        tgt: dict[str, float] = {}
        row_w = W[t]
        for j in np.flatnonzero(np.isfinite(row_w) & (row_w != 0) | np.isnan(row_w)):
            sym = P.names[j]
            if "~" in sym or sym not in mid:
                continue
            x = cur.get(sym, 0.0) if np.isnan(row_w[j]) else float(row_w[j])
            if x > 0:
                c = cur.get(sym, 0.0)
                tgt[sym] = c if c > 0 and abs(x - c) <= tranches.BAND * x else x
        tr[k] = tgt
        if reset:
            alloc = [1.0 / tranches.K] * tranches.K
        expo = sum(a * sum(w.values()) for a, w in zip(alloc, tr))
        if expo > 1 + 1e-9:
            alloc = [a / expo for a in alloc]
    else:
        st = {"variant": variant(name), "started": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "equity": START_EQUITY}
        equity, gross, before = START_EQUITY, 0.0, {}
        _, _, _, a0, inner, _ = tranches.simulate(P, W, until=t)
        alloc = [float(a) for a in a0]
        tr = [{P.names[j]: float(w[j]) for j in np.flatnonzero(w > 0)
               if "~" not in P.names[j] and P.names[j] in mid} for w in inner]
    after = book(alloc, tr)
    syms = set(before) | set(after)
    delta = {s: after.get(s, 0.0) - before.get(s, 0.0) for s in syms}
    half = {s: (quotes[s][1] - quotes[s][0]) / mid[s] / 2 for s in syms if s in quotes}
    paper_cost = sum(abs(x) * (TAKER + half.get(s, 0.0)) for s, x in delta.items())
    model_cost = sum(abs(x) for x in delta.values()) * COST
    equity *= 1 - paper_cost
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
        "exposure": round(sum(after.values()), 4),
        "held": sum(1 for x in after.values() if x > 0),
        "timing_drift_bps": round(timing_bps, 2),
        "tranche": k,
        "reset": reset,
        "weights": json.dumps({s[:-4]: round(x, 4) for s, x in sorted(after.items()) if x > 0}),
    }
    journal = d / "journal.csv"
    new = not journal.exists()
    with journal.open("a", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(row))
        if new:
            wr.writeheader()
        wr.writerow(row)

    st.update(equity=equity, alloc=alloc, tranches=tr, mid={s: mid[s] for s in after if s in mid})
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


def tranche_evidence() -> dict:
    """The tranche book's out-of-sample numbers from experiments/tsmom_tranches.py:
    the JSON next to the sweep's caches, else results/tsmom_tranches.md. Sharpe at
    Alpaca taker cost (25 bps plus 10 bps slippage per side), "costs doubled" at
    70 bps. It does not pass: deflated p far below 0.95."""
    js = fc.OUT / "reports" / f"{tranches.NAME}.json"
    row, n, sr0, share, src = None, None, None, None, ""
    try:
        rep = json.loads(js.read_text(encoding="utf-8"))
        row, n, sr0, share, src = rep["rows"][0], rep["n_trials"], rep["sr0_annual"], rep["non_alpaca_share"], str(js)
    except (OSError, ValueError, KeyError, IndexError):
        md = fc.RESULTS_DIR / f"{tranches.NAME}.md"
        try:
            text = md.read_text(encoding="utf-8")
            # The variant's row in every table (out of sample, then per year and regime), merged.
            row = {}
            for r in (r for tb in _md_tables(text) for r in tb if r.get("variant") == tranches.VARIANT):
                row.update(r)
            if not row:
                raise StopIteration
            m = re.search(r"over (\d+) trials", text)
            n = int(m.group(1)) if m else None
            m = re.search(r"On average (\d+) %", text)
            share = int(m.group(1)) / 100 if m else None
            src = str(md)
        except (OSError, StopIteration):
            return {"report": tranches.NAME, "missing": True}
    if row is None:
        return {"report": tranches.NAME, "missing": True}
    return {
        "report": tranches.NAME,
        "source": src,
        "variant": tranches.VARIANT,
        "is_sharpe": row["is_taker 35bps"] if "is_taker 35bps" in row else None,
        "oos_sharpe": row["oos_taker 35bps"],
        "oos_sharpe_maker": row["oos_maker 15bps"],
        "oos_max_dd": row["dd_taker 35bps"],
        "deflated_p": row["deflated_p"],
        "sharpe_2x_cost": row["oos_taker x2 70bps"],
        "cost_note": "Sharpe at Alpaca taker cost, 35 bps per unit of turnover (25 bps fee plus about 10 bps "
                     "slippage); oos_sharpe_maker at 15 bps; sharpe_2x_cost at 70 bps",
        "variants_tried": n,
        "bootstrap_90": [row["boot35_p05"], row["boot35_p95"]],
        "turnover_yr": row["turnover_yr"],
        "non_alpaca_share": share,
        "oos_sharpe_survivorship_free": row["oos_taker 35bps"],
        # The engine reads these as numbers: a missing one is left out, never null.
        "regime_sharpes": {k: row[c] for k, c in (("BTC above 200d average", "oos_btc_above"),
                                                  ("BTC below 200d average", "oos_btc_below"))
                           if isinstance(row.get(c), float)},
        "regime_filter": True,
        "verdict": f"fails: deflated p {row['deflated_p']:.2f} <= 0.95",
        "caveat": "Forward evidence only. Survivorship-free out-of-sample backtest from 2024; the rule is the "
                  "blend study's weekday-free form of a weekly pick whose own number was weekday luck. Coins "
                  "Alpaca does not list stay cash on an Alpaca autopilot.",
    }


def evidence(name: str) -> dict:
    """What the sweep measured for this book's pick, for the engine's Strategy
    Passport and the autopilot's auto pick. Sharpes are net of 15 bps per unit
    of turnover; the "costs doubled" figure is the sweep's 41 bps run (2.7x,
    stricter than 2x). Neither candidate passes: deflated p is far below 0.95."""
    if name == "tsmom_tranches":
        return tranche_evidence()
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
    w = tranches.book_weights(P, W, t) if name == "tsmom_tranches" else backtest_weights(P, W, t)
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
        "regime_on": bool(P.btc_on[t]) if REGIME[name] else None,
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
    universe = None
    if "--universe" in sys.argv:
        i = sys.argv.index("--universe")
        if i + 1 >= len(sys.argv):
            print("--universe needs a name (alpaca, core, memes, ...)", file=sys.stderr)
            return 2
        universe = sys.argv[i + 1]
        if signals_only:
            print("--universe books write no engine signal; nothing to refresh", file=sys.stderr)
            return 2
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
    if universe is None:
        W = targets(P)
    else:
        member = uni.mask(P, uni.named(universe))
        tag = universe.strip().lower().replace(" ", "")
        W = {book_name(n, tag): w for n, w in targets(P, member).items()}
        missing = [c["coin"] for c in uni.coverage(P, uni.named(universe)) if not c["in_panel"]]
        print(f"universe {tag}: {int(member.sum())} coins in the panel"
              + (f", no Binance USDT history for {', '.join(missing)}" if missing else ""), file=sys.stderr)
    if signals_only and not dry:
        for name, w in W.items():
            sig = signal(name, P, w, t, now_us)
            save_signal(name, sig, now_us)
            print(name, "signal", json.dumps(sig["weights"]), "dropped", sig["dropped"])
        return 0

    held = set()
    for name in W:
        f = ROOT / "paper" / name / "state.json"
        if f.exists():
            st = json.loads(f.read_text())
            held |= set(st.get("weights", {})) | {s for w in st.get("tranches", []) for s in w}
    wanted = {P.names[j] for w in W.values() for j in np.flatnonzero(np.nan_to_num(w[t], nan=1.0) != 0)}
    frows = {}
    # Factory books are no universe books: a --universe run leaves them alone.
    for name, book in (factory_books() if universe is None else {}).items():
        g = book["genome"]
        try:
            row = factory_row(P, g, t)
            # A new book starts where the backtest stands, whatever the weekday.
            start_row = factory_row(P, g, t, always=True)
        except Exception as e:  # noqa: BLE001 - a broken factory book must not stop the others
            print(f"{name}: factory book skipped ({type(e).__name__}: {e})", file=sys.stderr)
            continue
        frows[name] = (book, row, start_row)
        f = ROOT / "paper" / name / "state.json"
        if f.exists():
            held |= set(json.loads(f.read_text()).get("weights", {}))
        wanted |= {P.names[j] for j in np.flatnonzero(np.nan_to_num(start_row) > 0)}
    quotes = live_quotes(sorted((held | wanted) - {s for s in wanted if "~" in s}))

    for name, (book, row, start_row) in frows.items():
        if dry:
            print(name, "factory book", book["name"], json.dumps(
                {P.names[j]: round(float(start_row[j]), 4) for j in np.flatnonzero(start_row > 0)}))
            continue
        print(name, json.dumps(step(name, row, P, t, quotes, now_us, start_row)))

    for name, w in W.items():
        base = name.partition("@")[0]
        if universe is not None:
            if dry:
                now = tranches.book_weights(P, w, t) if base == "tsmom_tranches" else backtest_weights(P, w, t)
                row = {P.names[j]: round(float(now[j]), 4) for j in np.flatnonzero(now > 0)}
                print(name, "BTC above 200d" if P.btc_on[t] else "BTC below 200d", json.dumps(row))
            elif base == "tsmom_tranches":
                print(name, json.dumps(step_tranches(P, w, t, quotes, now_us, name=name)))
            else:
                print(name, json.dumps(step(name, w[t], P, t, quotes, now_us, backtest_weights(P, w, t))))
            continue
        sig = signal(name, P, w, t, now_us)
        if dry:
            now = tranches.book_weights(P, w, t) if name == "tsmom_tranches" else backtest_weights(P, w, t)
            row = {P.names[j]: round(float(now[j]), 4) for j in np.flatnonzero(now > 0)}
            print(name, "BTC above 200d" if P.btc_on[t] else "BTC below 200d", json.dumps(row))
            ev = sig["evidence"]
            print(name, "signal", json.dumps(sig["weights"]), f"exposure {sum(sig['weights'].values()):.4f}",
                  f"of {sig['lab_exposure']:.4f}", "dropped", sig["dropped"], f"({sig['dropped_weight']:.4f})")
            print(name, "evidence", json.dumps({k: ev.get(k) for k in (
                "source", "is_sharpe", "oos_sharpe", "sharpe_2x_cost", "deflated_p", "variants_tried",
                "plateau_share", "plateau_variants", "regime_sharpes", "regime_filter", "verdict", "missing")}))
            continue
        if name == "tsmom_tranches":
            print(name, json.dumps(step_tranches(P, w, t, quotes, now_us)))
        else:
            print(name, json.dumps(step(name, w[t], P, t, quotes, now_us, backtest_weights(P, w, t))))
        save_signal(name, sig, now_us)
    return 0


if __name__ == "__main__":
    sys.exit(main())
