"""Forward report: everything that trades with made-up money, held against what its backtest promised.

Runs daily at 06:15 UTC, after the last paper book (05:30). For every paper book
under <data>/paper/ and every autopilot of the autopilot engine it answers, in
one plain sentence each: is the forward result what the backtest led us to
expect, is it too early to tell, or is it worth watching?

Per paper book
  days running, return, worst dip (max drawdown), turnover, costs the paper
  fills paid against the costs the backtest models, funding where it applies;
  the backtest's expectation over the same number of days, as a band: a block
  bootstrap of the backtest's out-of-sample daily net returns (5 % and 95 %
  of the cumulative return over that horizon, median in the middle);
  progress toward gate 7 (30 days and 30 rebalances).

Per autopilot (read from the autopilot engine's /api/state)
  equity against its start and its stop floor, return against BTC bought and
  held over the same window, fees as a share of the result before fees,
  trades per day, and realised against modelled slippage per route (paper,
  demo, live) from its fill records. An autopilot that runs a single lab book
  is also held against that book's backtest band.

Where the band comes from, best first:
  1. <reports>/forward/backtest/<book>.json, the backtest's out-of-sample net
     returns written by --export-backtests (see below);
  2. the experiment's own report (CAGR and volatility), turned into an
     approximate normal band and labelled as approximate;
  3. nothing: the sentence says there is no range to compare with.

  python -m lab.paper.forward_report
      the report: <reports>/forward/latest.json, latest.md and dated copies
  python -m lab.paper.forward_report --export-backtests [--source DIR]
      write the backtest series from whatever this machine has: the momentum
      books from the history files, the sweep candidates from the sweep's run
      caches, M4 from the xs_daily pick cache. --source reads those inputs
      from DIR instead of PYTHIA_DATA (nothing is written there).

Environment: PYTHIA_AUTOPILOT_STATE_URL (default http://127.0.0.1:8788/api/state;
"off" skips the engine). The engine being down is reported, not an error.
"""

from __future__ import annotations

import csv
import json
import math
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import report
from ..data import ROOT

NAME = "forward"
START_EQUITY = 10_000.0
GATE_DAYS, GATE_TRADES = 30, 30
# Below this many days a forward result says little either way; the band is wide
# and a single day can put it anywhere.
MIN_JUDGE_DAYS = 7
BAND = (0.05, 0.95)
SIMS = 4000
BLOCK_DAYS = 5
COST_WARN = 1.5           # paper costs over modelled costs that deserve a mention
FEES_WARN = 0.4           # fees over the result before fees: the Autopilot page's "costs are eating it" line
DEFAULT_STATE_URL = "http://127.0.0.1:8788/api/state"
DAY_MS = 86_400_000

# Plain names for the paper books, in the order the report lists them.
BOOKS: dict[str, str] = {
    "tsmom": "Momentum, 20 coins",
    "tsmom_regime": "Momentum with BTC regime filter",
    "tsmom_top20": "Momentum, 20 most traded coins each day",
    "breakout_top10": "Breakout, 10 most traded coins each day",
    "m4_ls": "M4 market-neutral (perps)",
    "picks_ls": "M2 market-neutral (perps)",
    "picks_ls_v2": "M2 v2 market-neutral (perps)",
}
# picks_ls journals book the modelled cost (10 bps per unit of turnover) as their fill cost.
MODELLED_ONLY = {"picks_ls": 0.0010, "picks_ls_v2": 0.0010}
PICKS_LS_ROW = "top 10 / bottom 10 of the 50 most liquid perps · no paying shorts"


def backtest_dir() -> Path:
    return report.REPORTS / NAME / "backtest"


# ---------------------------------------------------------------- the band

def bootstrap_band(returns: np.ndarray, days: float, period_days: float = 1.0, sims: int = SIMS,
                   block_days: int = BLOCK_DAYS, seed: int = 7) -> dict | None:
    """What the backtest would have made over `days`, drawn from its own history.

    A moving-block bootstrap of the backtest's per-period net returns (blocks of
    about `block_days`, so calm and wild stretches stay together), compounded
    over the horizon. A horizon that is not a whole number of periods scales the
    last period's return (a weekly book judged after 10 days gets one full week
    and three sevenths of another). Returns the median, the 5 % and 95 %
    quantiles of the cumulative return, and the 95 % quantile of the worst dip
    within the horizon; None without a usable horizon or history.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    m = days / period_days
    if m <= 0 or len(r) < 2:
        return None
    k = int(math.ceil(m - 1e-9))
    weight = np.ones(k)
    weight[-1] = m - (k - 1)
    b = max(1, min(int(round(block_days / period_days)), k, len(r)))
    nblocks = int(math.ceil(k / b))
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, len(r) - b + 1, size=(sims, nblocks))
    idx = (starts[:, :, None] + np.arange(b)).reshape(sims, nblocks * b)[:, :k]
    paths = np.cumprod(1 + r[idx] * weight, axis=1)
    total = paths[:, -1] - 1
    peak = np.maximum.accumulate(np.concatenate([np.ones((sims, 1)), paths], axis=1), axis=1)[:, 1:]
    dd = (1 - paths / peak).max(axis=1)
    lo, hi = np.quantile(total, BAND)
    return {"median_pct": float(np.median(total) * 100), "low_pct": float(lo * 100), "high_pct": float(hi * 100),
            "dd_p95_pct": float(np.quantile(dd, 0.95) * 100)}


def normal_band(cagr: float, vol: float, days: float) -> dict | None:
    """The same band from two numbers of a report: log-normal with the backtest's
    growth rate and volatility. Coarser than the bootstrap (no fat tails)."""
    if days <= 0 or not (cagr > -1) or not (vol > 0):
        return None
    mu, sd = math.log1p(cagr) / 365 * days, vol / math.sqrt(365) * math.sqrt(days)
    z = 1.6448536269514722
    return {"median_pct": math.expm1(mu) * 100, "low_pct": math.expm1(mu - z * sd) * 100,
            "high_pct": math.expm1(mu + z * sd) * 100, "dd_p95_pct": None}


def position(ret_pct: float, band: dict | None) -> str | None:
    if band is None:
        return None
    if ret_pct < band["low_pct"]:
        return "below"
    if ret_pct > band["high_pct"]:
        return "above"
    return "inside"


# ---------------------------------------------------------------- the sentences

def _days(n: float) -> str:
    n = int(round(n))
    return f"{n} day" if n == 1 else f"{n} days"


def book_verdict(rows: int, elapsed: float, pos: str | None, dd_deeper: bool, cost_ratio: float | None,
                 ready: bool, ret_pct: float) -> tuple[str, str]:
    """(status, one plain sentence) for a paper book.

    status: none · early · watch · ahead · on_track · unknown. A drop below the
    band is worth a look even early on; everything else waits MIN_JUDGE_DAYS.
    """
    if rows == 0:
        return "none", "Not started yet."
    d = _days(elapsed)
    lead = "Ready for the gate 7 review. " if ready else ""
    tail = (f" Its fills cost {cost_ratio:.1f}x what the backtest assumes."
            if cost_ratio is not None and cost_ratio > COST_WARN else "")
    if pos == "below":
        early = f", though {d} is very little" if elapsed < MIN_JUDGE_DAYS else ""
        return "watch", f"{lead}Below the backtest's range after {d}, worth watching{early}.{tail}"
    if elapsed < MIN_JUDGE_DAYS:
        return "early", f"Too early to say: {_days(rows)} of practice, {ret_pct:+.2f} % so far.{tail}"
    if pos is None:
        return "unknown", f"{lead}No backtest range to compare with; {ret_pct:+.2f} % after {d}.{tail}"
    if dd_deeper:
        return "watch", (f"{lead}Inside the backtest's range after {d}, but its worst dip is deeper than 19 in 20 "
                         f"backtest stretches of the same length, worth watching.{tail}")
    if pos == "above":
        return "ahead", (f"{lead}Above the backtest's range after {d}: better than expected, which can be luck "
                         f"as easily as skill.{tail}")
    return "on_track", f"{lead}On track: inside the backtest's range after {d}.{tail}"


def fees_share_of_gross(fees_paid: float, gross: float) -> float | None:
    """Fees as a share of the result before fees; only meaningful when that result was a gain."""
    return fees_paid / gross if gross > 1e-9 else None


def autopilot_verdict(state: str, stop_reason: str | None, elapsed: float, ret_pct: float, btc_pct: float | None,
                      pos: str | None, floor_close: bool, fees_paid: float, gross: float) -> tuple[str, str]:
    """(status, one plain sentence) for an autopilot. A stopped one is history;
    a running one is held against its lab book's band when it has one, else
    against BTC, and its stop floor is mentioned before anything else.
    `gross` is the result before fees, `fees_paid` what the fees took."""
    d = _days(elapsed) if elapsed >= 1 else f"{elapsed * 24:.0f} hours"
    btc = f" (BTC {btc_pct:+.2f} %)" if btc_pct is not None else ""
    fees = ""
    share = fees_share_of_gross(fees_paid, gross)
    if share is not None and share > FEES_WARN:
        fees = f" Fees took {share * 100:.0f} % of what it made before fees."
    elif gross < 0 and fees_paid > 0:
        fees = " It lost money even before fees."
    if state in ("stopped", "finished"):
        why = f" ({stop_reason})" if stop_reason else ""
        return "stopped", f"{state.capitalize()}{why} after {d} at {ret_pct:+.2f} %{btc}.{fees}"
    if floor_close:
        return "watch", f"Closer to its stop than to its start after {d} ({ret_pct:+.2f} %), worth watching.{fees}"
    if pos == "below":
        return "watch", f"Below its lab book's backtest range after {d}, worth watching.{fees}"
    if elapsed < MIN_JUDGE_DAYS:
        return "early", f"Too early to say: {d} running, {ret_pct:+.2f} % so far{btc}.{fees}"
    if pos == "above":
        return "ahead", f"Above its lab book's backtest range after {d}: better than expected, which can be luck.{fees}"
    if pos == "inside":
        return "on_track", f"On track: inside its lab book's backtest range after {d}{btc}.{fees}"
    if btc_pct is None:
        return "unknown", f"No backtest range for its strategies; {ret_pct:+.2f} % after {d}.{fees}"
    side = "ahead of" if ret_pct >= btc_pct else "behind"
    return "unknown", (f"No backtest range for its strategies; {side} BTC by {abs(ret_pct - btc_pct):.2f} points "
                       f"after {d}.{fees}")


# ---------------------------------------------------------------- backtest series

def load_series(book: str) -> dict | None:
    """The exported out-of-sample net returns of a book's backtest, or None."""
    p = backtest_dir() / f"{book}.json"
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        if len(s.get("returns", [])) >= 30:
            return s
    except (OSError, ValueError):
        pass
    return None


def _read_json(*paths: Path) -> dict | None:
    for p in paths:
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None


def report_stats(book: str, root: Path | None = None) -> dict | None:
    """CAGR and volatility of a book's backtest from its experiment report, for
    the approximate band. Volatility from Sharpe where a report has no vol."""
    root = root or ROOT
    reports = [report.REPORTS, root / "reports"]

    def vol_from_sharpe(cagr: float, sharpe: float) -> float | None:
        return math.log1p(cagr) / sharpe if sharpe > 0.2 and cagr > -1 else None

    try:
        if book == "tsmom":
            rep = _read_json(*(r / "tsmom" / "latest.json" for r in reports))
            one = next(c for c in rep["cost_sensitivity"] if c["costs"] == "1x")
            return {"cagr": one["cagr"], "vol": one["vol"], "max_dd": one["max_dd"], "source": "tsmom report"}
        if book == "tsmom_regime":
            rep = _read_json(*(r / "momentum2" / "latest.json" for r in reports))
            d = next(x for x in rep["details"] if x["family"] == "A regime")
            return {"cagr": d["oos_cagr"], "vol": vol_from_sharpe(d["oos_cagr"], d["oos_sharpe"]),
                    "max_dd": d["oos_max_dd"], "source": "momentum2 report"}
        if book in ("tsmom_top20", "breakout_top10"):
            variant = {"tsmom_top20": "tsmom 28d · top 20 · regime · none",
                       "breakout_top10": "Donchian 20/10 · top 10 liquid"}[book]
            out = Path(os.environ.get("PYTHIA_AGENT_OUT", str(root / "agent-strategies")))
            rep = _read_json(out / "reports" / "families_summary.json", root / "lab-cache" / "reports" / "families_summary.json")
            p = next(x for x in rep["picks"] if x["variant"] == variant)
            return {"cagr": p["oos_cagr_15bps"], "vol": p["oos_vol"], "max_dd": p["oos_max_dd_15bps"],
                    "source": "strategy-family sweep"}
        if book == "m4_ls":
            rep = _read_json(*(r / "xs_daily" / "latest.json" for r in reports))
            p = rep["slow_pick"] if isinstance(rep.get("slow_pick"), dict) else next(
                x for x in rep["picks"] if x["family"].startswith("slower"))
            return {"cagr": p["hold_cagr_15bps"], "vol": vol_from_sharpe(p["hold_cagr_15bps"], p["hold_sharpe_15bps"]),
                    "max_dd": p["hold_max_dd_15bps"], "source": "xs_daily report"}
        if book in ("picks_ls", "picks_ls_v2"):
            rep = _read_json(*(r / book / "latest.json" for r in reports))
            p = next(x for x in rep["rows"] if x["strategy"] == PICKS_LS_ROW)
            return {"cagr": p["cagr"], "vol": vol_from_sharpe(p["cagr"], p["sharpe"]), "max_dd": p["max_dd"],
                    "source": f"{book} report"}
    except (TypeError, KeyError, StopIteration, AttributeError):
        return None
    return None


def expectation(book: str, days: float) -> dict | None:
    """The backtest's band for `days`, with where it came from."""
    if days <= 0:
        return None
    s = load_series(book)
    if s is not None:
        band = bootstrap_band(np.array(s["returns"]), days, float(s.get("period_days", 1)))
        if band:
            return {**band, "method": "bootstrap",
                    "source": f"{s.get('source', 'backtest')}, {len(s['returns'])} out-of-sample "
                              f"{'days' if s.get('period_days', 1) == 1 else 'periods'}",
                    "backtest_max_dd_pct": s.get("max_dd_pct")}
    st = report_stats(book)
    if st and st.get("vol"):
        band = normal_band(st["cagr"], st["vol"], days)
        if band:
            return {**band, "method": "approximate", "source": f"{st['source']} (growth and volatility only)",
                    "backtest_max_dd_pct": st["max_dd"] * 100 if st.get("max_dd") is not None else None}
    return None


# ---------------------------------------------------------------- paper books

def read_journal(book: str, root: Path | None = None) -> list[dict]:
    p = (root or ROOT) / "paper" / book / "journal.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(row: dict, key: str) -> float | None:
    try:
        v = float(row[key])
        return v if math.isfinite(v) else None
    except (KeyError, TypeError, ValueError):
        return None


def max_drawdown(equity: list[float], start: float = START_EQUITY) -> float:
    path = np.array([start, *equity], dtype=float)
    return float((1 - path / np.maximum.accumulate(path)).max())


def _rebalanced(r: dict) -> bool:
    if str(r.get("rebalanced", "")).lower() == "true":
        return True
    t = _f(r, "turnover")
    return t is not None and t > 0.01


def book_row(book: str, journal: list[dict], variant: str = "") -> dict:
    """Everything the report says about one paper book, from its journal."""
    base = {"kind": "book", "name": book, "label": BOOKS.get(book, book), "variant": variant}
    if not journal:
        status, text = book_verdict(0, 0, None, False, None, False, 0.0)
        return {**base, "days": 0, "status": status, "sentence": text,
                "gate7": {"days": 0, "days_needed": GATE_DAYS, "trades": 0, "trades_needed": GATE_TRADES,
                          "trades_label": "rebalances", "progress": 0.0, "ready": False}}
    equity = [e for e in (_f(r, "equity") for r in journal) if e is not None]
    dates = [datetime.strptime(r["date"], "%Y-%m-%d") for r in journal if r.get("date")]
    elapsed = float((dates[-1] - dates[0]).days) if len(dates) >= 2 else 0.0
    ret_pct = (equity[-1] / START_EQUITY - 1) * 100 if equity else 0.0
    turnover = sum(_f(r, "turnover") or 0.0 for r in journal)
    rebalances = sum(_rebalanced(r) for r in journal)
    if book in MODELLED_ONLY:
        paper_cost = model_cost = turnover * MODELLED_ONLY[book] * 100
        cost_ratio = None
    else:
        paper_cost = sum(_f(r, "paper_cost_bps") or 0.0 for r in journal) / 100
        model_cost = sum(_f(r, "model_cost_bps") or 0.0 for r in journal) / 100
        cost_ratio = paper_cost / model_cost if model_cost > 0.01 else None
    funding = None
    if "funding_pct" in journal[0]:
        funding = sum(_f(r, "funding_pct") or 0.0 for r in journal)
    elif "funding_pnl" in journal[0]:
        funding = sum(_f(r, "funding_pnl") or 0.0 for r in journal) / START_EQUITY * 100
    dd_pct = max_drawdown(equity) * 100
    exp = expectation(book, elapsed)
    pos = position(ret_pct, exp)
    dd_deeper = bool(exp and exp.get("dd_p95_pct") is not None and dd_pct > exp["dd_p95_pct"] and dd_pct > 0.5)
    ready = len(journal) >= GATE_DAYS and rebalances >= GATE_TRADES
    status, text = book_verdict(len(journal), elapsed, pos, dd_deeper, cost_ratio, ready, ret_pct)
    return {
        **base,
        "since": journal[0].get("date"),
        "last": journal[-1].get("date"),
        "days": len(journal),
        "elapsed_days": elapsed,
        "return_pct": ret_pct,
        "max_dd_pct": dd_pct,
        "turnover": turnover,
        "costs": {"paper_pct": paper_cost, "model_pct": model_cost, "ratio": cost_ratio,
                  "modelled_only": book in MODELLED_ONLY},
        "funding_pct": funding,
        "expected": exp,
        "position": pos,
        "gate7": {"days": len(journal), "days_needed": GATE_DAYS, "trades": rebalances,
                  "trades_needed": GATE_TRADES, "trades_label": "rebalances",
                  "progress": min(len(journal) / GATE_DAYS, rebalances / GATE_TRADES, 1.0), "ready": ready},
        "status": status,
        "sentence": text,
    }


def paper_books(root: Path | None = None) -> list[dict]:
    root = root or ROOT
    names = list(BOOKS)
    d = root / "paper"
    if d.exists():
        names += sorted(p.name for p in d.iterdir() if p.is_dir() and p.name not in BOOKS)
    out = []
    for b in names:
        j = read_journal(b, root)
        if not j and b not in BOOKS:
            continue
        variant = ""
        try:
            variant = json.loads((d / b / "state.json").read_text(encoding="utf-8")).get("variant", "")
        except (OSError, ValueError):
            pass
        out.append(book_row(b, j, variant))
    return out


# ---------------------------------------------------------------- autopilots

def fetch_state(url: str, timeout: float = 10) -> tuple[dict | None, str | None]:
    if url.strip().lower() == "off":
        return None, "switched off (PYTHIA_AUTOPILOT_STATE_URL=off)"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.load(r), None
    except Exception as e:  # noqa: BLE001 - the engine being down is a finding, not a crash
        return None, f"{type(e).__name__}: {e}"


def btc_price_at(ms: int) -> float | None:
    """BTCUSDT on Binance at a moment: the open of that minute, else the last trade."""
    try:
        url = f"https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1m&startTime={int(ms)}&limit=1"
        with urllib.request.urlopen(url, timeout=15) as r:
            k = json.load(r)
        if k:
            return float(k[0][1])
        with urllib.request.urlopen("https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT", timeout=15) as r:
            return float(json.load(r)["price"])
    except Exception:  # noqa: BLE001
        return None


def _median(xs: list[float]) -> float | None:
    return float(np.median(xs)) if xs else None


def slippage_by_route(orders: list[dict], strategies: set[str], start_ms: int, end_ms: int) -> list[dict]:
    """Realised against modelled slippage of one autopilot's fills, per route."""
    by: dict[str, tuple[list[float], list[float]]] = {}
    for o in orders:
        if o.get("strategyId") not in strategies or o.get("status") != "filled":
            continue
        ts = o.get("ts") or 0
        if not (start_ms <= ts <= end_ms):
            continue
        r, m = o.get("realisedSlippageBps"), o.get("modelledSlippageBps")
        if r is None or m is None:
            continue
        lst = by.setdefault(o.get("route") or o.get("mode") or "paper", ([], []))
        lst[0].append(float(r))
        lst[1].append(float(m))
    rank = {"live": 0, "demo": 1, "paper": 2}
    rows = []
    for route, (re_, mo) in sorted(by.items(), key=lambda kv: rank.get(kv[0], 9)):
        mr, mm = _median(re_), _median(mo)
        rows.append({"route": route, "fills": len(re_), "median_realised_bps": mr, "median_modelled_bps": mm,
                     "ratio": mr / mm if mm and mm > 1e-9 else None})
    return rows


def autopilot_row(ap: dict, orders: list[dict], now_ms: int, price_at=btc_price_at) -> dict:
    cfg = ap.get("config", {})
    start_ms = int(ap["startedMs"]) if ap.get("startedMs") is not None else now_ms
    end_ms = int(ap["stoppedMs"]) if ap.get("stoppedMs") is not None else now_ms
    elapsed = max(end_ms - start_ms, 0) / DAY_MS
    start = float(ap.get("startCapital") or cfg.get("capitalUsd") or 0) or 1.0
    equity = float(ap.get("equity") or start)
    ret_pct = (equity / start - 1) * 100
    fees = float(ap.get("fees") or 0.0)
    pnl = float(ap.get("pnl") if ap.get("pnl") is not None else equity - start)
    gross = pnl + fees
    fees_share = fees_share_of_gross(fees, gross)
    trades = int(ap.get("trades") or 0)
    floor = ap.get("floorEquity")
    floor_close = bool(floor is not None and start > floor and (equity - floor) / (start - floor) < 0.5)

    b0, b1 = price_at(start_ms), price_at(end_ms)
    btc_pct = (b1 / b0 - 1) * 100 if b0 and b1 else None

    sleeves = ap.get("bySleeve") or []
    strategies = {s.get("strategyId") for s in sleeves} | {s.get("strategyId") for s in cfg.get("sleeves", [])}
    strategies.discard(None)
    # A single lab book in the sleeves: its backtest is the yardstick.
    lab = [s for s in sleeves if str(s.get("strategyId", "")).startswith("lab:") and (s.get("weight") or 0) >= 0.99]
    lab_book = lab[0]["strategyId"][4:] if len(lab) == 1 else None
    exp = expectation(lab_book, round(elapsed)) if lab_book and elapsed >= 1 else None
    pos = position(ret_pct, exp)
    state = ap.get("state", "running")
    status, text = autopilot_verdict(state, ap.get("stopReason"), elapsed, ret_pct, btc_pct, pos, floor_close,
                                     fees, gross)
    days = int(elapsed)
    return {
        "kind": "autopilot",
        "name": cfg.get("id", "?"),
        "label": cfg.get("name", "Autopilot"),
        "variant": ", ".join(s.get("name", s.get("strategyId", "?")) for s in sleeves),
        "mode": cfg.get("mode"),
        "venue": cfg.get("venue"),
        "state": state,
        "since": datetime.fromtimestamp(start_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "days": days,
        "elapsed_days": elapsed,
        "start_equity": start,
        "equity": equity,
        "floor_equity": floor,
        "return_pct": ret_pct,
        "max_dd_pct": float(ap.get("drawdownPct") or 0.0),
        "btc_return_pct": btc_pct,
        "fees": fees,
        "fees_share_of_gross": fees_share,
        "fees_pct_of_capital": fees / start * 100,
        "gross_pct": gross / start * 100,
        "trades": trades,
        # Per day only once there is a day to divide by; three hours times eight says little.
        "trades_per_day": trades / elapsed if elapsed >= 1 else None,
        "slippage": slippage_by_route(orders, strategies, start_ms, end_ms),
        "lab_book": lab_book,
        "expected": exp,
        "position": pos,
        "gate7": {"days": days, "days_needed": GATE_DAYS, "trades": trades, "trades_needed": GATE_TRADES,
                  "trades_label": "closed trades",
                  "progress": min(days / GATE_DAYS, trades / GATE_TRADES, 1.0),
                  "ready": days >= GATE_DAYS and trades >= GATE_TRADES},
        "status": status,
        "sentence": text,
    }


def autopilots(url: str, now_ms: int, price_at=btc_price_at) -> tuple[list[dict], dict]:
    state, err = fetch_state(url)
    engine = {"url": url, "reachable": state is not None, "error": err, "slippage": []}
    if state is None:
        return [], engine
    engine["slippage"] = [{"venue": s.get("venue"), "route": s.get("route"), "fills": s.get("fills"),
                           "median_realised_bps": s.get("medianRealisedBps"),
                           "median_modelled_bps": s.get("medianModelledBps"), "ratio": s.get("ratio"),
                           "enough": s.get("enough")} for s in state.get("slippage") or []]
    orders = state.get("orders") or []
    engine["orders_kept"] = len(orders)
    aps = sorted(state.get("autopilots") or [], key=lambda a: (a.get("state") != "running", -(a.get("startedMs") or 0)))
    return [autopilot_row(a, orders, now_ms, price_at) for a in aps], engine


# ---------------------------------------------------------------- report

def summary(books: list[dict], aps: list[dict], engine: dict) -> str:
    def count(rows: list[dict]) -> str:
        names = {"on_track": "on track", "ahead": "above range", "watch": "worth watching", "early": "too early",
                 "unknown": "no range", "stopped": "stopped", "none": "not started"}
        c: dict[str, int] = {}
        for r in rows:
            c[r["status"]] = c.get(r["status"], 0) + 1
        return ", ".join(f"{n} {names.get(s, s)}" for s, n in sorted(c.items(), key=lambda kv: -kv[1]))

    running = [a for a in aps if a["status"] != "stopped"]
    ap_text = (f"{len(running)} autopilot{'' if len(running) == 1 else 's'} running ({count(running)})"
               if running else "no autopilot running") \
        if engine["reachable"] else "autopilot engine not reachable"
    return f"{len(books)} paper books: {count(books)}. {ap_text[0].upper()}{ap_text[1:]}."


def _pct(v, digits: int = 2) -> str:
    return "n/a" if v is None else f"{v:+.{digits}f} %"


def markdown(data: dict) -> str:
    books, aps, engine = data["books"], data["autopilots"], data["engine"]
    lines = [f"# Forward tests: paper books and autopilots against their backtests\n",
             f"{data['generated']}. {data['verdict']}\n",
             "Band: where the backtest's own out-of-sample days put the cumulative return over the same number of "
             f"days (5 % to 95 %, block bootstrap). Gate 7: {GATE_DAYS} days and {GATE_TRADES} rebalances or closed "
             "trades.\n", "## Paper books\n"]
    for b in books:
        lines.append(f"- **{b['label']}** (`{b['name']}`): {b['sentence']}")
    rows = []
    for b in books:
        e = b.get("expected") or {}
        c = b.get("costs") or {}
        rows.append({"book": b["name"], "since": b.get("since", ""), "days": b["days"],
                     "return": _pct(b.get("return_pct")), "max_dd": _pct(-(b.get("max_dd_pct") or 0)),
                     "band": f"{e['low_pct']:+.2f} to {e['high_pct']:+.2f} %" if e else "n/a",
                     "band_from": e.get("method", "none") if e else "none",
                     "turnover": b.get("turnover", 0.0),
                     "costs_paper_vs_model": (f"{c['paper_pct']:.3f} / {c['model_pct']:.3f} %" if c else "n/a"),
                     "gate7": f"{b['gate7']['days']}/{GATE_DAYS} d, {b['gate7']['trades']}/{GATE_TRADES} reb",
                     "status": b["status"]})
    lines.append("\n" + report.table(rows, ["book", "since", "days", "return", "max_dd", "band", "band_from",
                                            "turnover", "costs_paper_vs_model", "gate7", "status"]))
    lines.append("## Autopilots\n")
    if not engine["reachable"]:
        lines.append(f"The autopilot engine at {engine['url']} did not answer ({engine['error']}).\n")
    elif not aps:
        lines.append("The autopilot engine has no autopilots.\n")
    for a in aps:
        lines.append(f"- **{a['label']}** (`{a['name']}`, {a['mode']}, {a['state']}): {a['sentence']}")
    if aps:
        rows = []
        for a in aps:
            slip = "; ".join(f"{s['route']} {s['fills']} fills, {s['median_realised_bps']:.1f} vs "
                             f"{s['median_modelled_bps']:.1f} bps" for s in a["slippage"]) or "no fills kept"
            rows.append({"autopilot": a["name"], "since": a["since"], "days": f"{a['elapsed_days']:.1f}",
                         "equity": f"{a['equity']:,.2f} of {a['start_equity']:,.0f}",
                         "floor": f"{a['floor_equity']:,.0f}" if a["floor_equity"] is not None else "none",
                         "return": _pct(a["return_pct"]), "btc": _pct(a["btc_return_pct"]),
                         "fees": f"{a['fees_pct_of_capital']:.2f} % of capital"
                                 + (f", {a['fees_share_of_gross'] * 100:.0f} % of gross"
                                    if a["fees_share_of_gross"] is not None else f", gross {a['gross_pct']:+.2f} %"),
                         "trades_per_day": f"{a['trades_per_day']:.1f}" if a["trades_per_day"] is not None else "n/a",
                         "slippage_realised_vs_model": slip, "status": a["status"]})
        lines.append("\n" + report.table(rows, ["autopilot", "since", "days", "equity", "floor", "return", "btc",
                                                "fees", "trades_per_day", "slippage_realised_vs_model",
                                                "status"]))
    if engine.get("slippage"):
        lines.append("Engine-wide fills, realised against modelled slippage:\n")
        lines.append(report.table([{**s, "ratio": s["ratio"] if s["ratio"] is not None else "n/a"}
                                   for s in engine["slippage"]],
                                  ["venue", "route", "fills", "median_realised_bps", "median_modelled_bps", "ratio",
                                   "enough"]))
    if engine.get("orders_kept"):
        lines.append(f"Per-autopilot slippage comes from the last {engine['orders_kept']} orders the engine keeps.\n")
    return "\n".join(lines) + "\n"


def build(now_ms: int | None = None, url: str | None = None, price_at=btc_price_at, root: Path | None = None) -> dict:
    now_ms = now_ms or int(time.time() * 1000)
    url = url or os.environ.get("PYTHIA_AUTOPILOT_STATE_URL", DEFAULT_STATE_URL)
    books = paper_books(root)
    aps, engine = autopilots(url, now_ms, price_at)
    data = {"generated": datetime.fromtimestamp(now_ms / 1000, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "generated_ms": now_ms, "gate7": {"days": GATE_DAYS, "trades": GATE_TRADES},
            "min_judge_days": MIN_JUDGE_DAYS, "band": list(BAND),
            "books": books, "autopilots": aps, "engine": engine}
    data["verdict"] = summary(books, aps, engine)
    return _finite(data)


def _finite(v):
    """NaN and infinity become null: the engine parses this file as strict JSON."""
    if isinstance(v, float):
        return v if math.isfinite(v) else None
    if isinstance(v, dict):
        return {k: _finite(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_finite(x) for x in v]
    return v


# ---------------------------------------------------------------- export

def _save_series(book: str, returns: np.ndarray, source: str, period_days: float = 1.0, first: str = "",
                 last: str = "") -> None:
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    eq = np.cumprod(1 + r)
    dd = float((1 - eq / np.maximum.accumulate(eq)).max()) * 100 if len(r) else None
    d = backtest_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{book}.json").write_text(json.dumps({
        "book": book, "source": source, "period_days": period_days, "first": first, "last": last,
        "max_dd_pct": dd, "exported": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "returns": [round(float(x), 8) for x in r]}), encoding="utf-8")
    print(f"{book}: {len(r)} periods from {source} ({first} to {last}), worst dip {dd:.1f} %")


def _day(us: int) -> str:
    return datetime.fromtimestamp(int(us) / 1e6, timezone.utc).strftime("%Y-%m-%d")


def export_backtests(source: Path) -> None:
    """Out-of-sample daily net returns (15 bps per unit of turnover, as the
    backtests report them) of every book this machine can rebuild."""
    from .. import data as labdata

    # Momentum books: the backtest itself, as lab.paper.review runs it.
    old = labdata.ROOT
    labdata.ROOT = source
    try:
        from ..experiments.momentum2 import run
        from ..experiments.tsmom import SPLIT, daily_matrix, rolling_mean, target_weights
        from .tsmom import BOOKS as TS_BOOKS
        days, close, rv, names = daily_matrix()
        if len(days):
            sigma = np.sqrt(rolling_mean(rv, 30, 20))
            history = np.cumsum(np.isfinite(close), axis=0)
            btc = close[:, names.index("BTC")]
            ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
            risk_on = np.nan_to_num(btc > ma200, nan=0.0).astype(bool)
            oos = days >= SPLIT
            for book, cfg in TS_BOOKS.items():
                fn = (lambda t, cfg=cfg: target_weights(close, sigma, history, t, cfg["lookbacks"], cfg["target"])
                      * (risk_on[t] if cfg["regime"] else 1.0))
                _, _, net, _ = run(close, fn, 1, 200)
                _save_series(book, net[oos], "momentum backtest", 1, _day(days[oos][0]), _day(days[oos][-1]))
        else:
            print("momentum books: no history files under", source, file=sys.stderr)
    except Exception as e:  # noqa: BLE001 - one missing input must not stop the others
        print("momentum books skipped:", type(e).__name__, e, file=sys.stderr)
    finally:
        labdata.ROOT = old

    # Sweep candidates: the sweep's own run caches.
    try:
        runs = next(p for p in (Path(os.environ["PYTHIA_AGENT_OUT"]) / "runs" if "PYTHIA_AGENT_OUT" in os.environ else None,
                                source / "agent-strategies" / "runs", source / "lab-cache" / "runs")
                    if p is not None and p.exists())
        summ = _read_json(runs.parent / "reports" / "families_summary.json") or {}
        for book, (fam, variant) in {"tsmom_top20": ("volmom", "tsmom 28d · top 20 · regime · none"),
                                     "breakout_top10": ("breakout", "Donchian 20/10 · top 10 liquid")}.items():
            meta = json.loads((runs / f"{fam}.json").read_text(encoding="utf-8"))
            i = next(k for k, m in enumerate(meta) if m["name"] == variant)
            z = np.load(runs / f"{fam}.npz")
            net = z["gross"][i] - z["turnover"][i] * 0.0015
            n_oos = next((p["oos_days"] for p in summ.get("picks", []) if p["variant"] == variant), 1010)
            # The sweep's out-of-sample window starts 2024-01-01 and runs to the panel's end.
            first = datetime(2024, 1, 1, tzinfo=timezone.utc)
            last = datetime.fromtimestamp(first.timestamp() + (n_oos - 1) * 86400, timezone.utc)
            _save_series(book, net[-n_oos:], "strategy-family sweep", 1, f"{first:%Y-%m-%d}", f"{last:%Y-%m-%d}")
    except (StopIteration, OSError, KeyError, ValueError) as e:
        print("sweep candidates skipped:", type(e).__name__, e, file=sys.stderr)

    # M4: the xs_daily pick cache (holdout from 2024).
    try:
        import polars as pl

        caches = [Path(os.environ["PYTHIA_CACHE"])] if "PYTHIA_CACHE" in os.environ else []
        caches += [source / "agent-models" / "reports" / "_cache", source / "reports" / "_cache", source / "lab-cache"]
        reps = [c.parent / "xs_daily" / "latest.json" for c in caches] + [source / "reports" / "xs_daily" / "latest.json"]
        rep = _read_json(*reps)
        slow = rep["slow_pick"]["variant"] if isinstance(rep.get("slow_pick"), dict) else next(
            p["variant"] for p in rep["picks"] if p["family"].startswith("slower"))
        fam = next(p["family"] for p in rep["picks"] if p["variant"] == slow)
        slug = fam.split(" (")[0].replace("/", "_").replace(", ", "_").replace(" ", "_")
        f = next(c / f"xs_daily_pick_{slug}.parquet" for c in caches if (c / f"xs_daily_pick_{slug}.parquet").exists())
        holdout = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp() * 1e6)
        df = pl.read_parquet(f).filter(pl.col("day") >= holdout).sort("day")
        net = (df["gross"] + df["funding"].fill_null(0.0) - df["turnover"] * 0.0015).to_numpy()
        _save_series("m4_ls", net, f"xs_daily holdout ({slow})", 1, _day(df["day"][0]), _day(df["day"][-1]))
    except (StopIteration, OSError, KeyError, ValueError, TypeError, ImportError) as e:
        print("m4_ls skipped:", type(e).__name__, e, file=sys.stderr)


def main() -> int:
    if "--export-backtests" in sys.argv:
        src = ROOT
        if "--source" in sys.argv:
            src = Path(sys.argv[sys.argv.index("--source") + 1])
        export_backtests(src)
        return 0
    data = build()
    report.write(NAME, markdown(data), data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
