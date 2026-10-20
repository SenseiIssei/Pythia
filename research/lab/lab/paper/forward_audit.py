"""Forward record audit: do the paper books trade their backtests, and do their numbers add up?

Pre-registration: results/forward_audit_prereg.md (thresholds fixed there,
before anything here was computed). Write-up: results/forward_audit.md.

    python -m lab.paper.forward_audit [--state PATH ...] [--cache DIR]

Three of the four checks run here; the fourth (each impossible figure traced
to code) is the write-up's.

1. Signal reconciliation. Every journal row of a daily paper book (run date D)
   against what the book's own weight function and simulator hold after the
   decision close D - 1, rerun now from the history files. A coin-day is every
   coin either side holds that day; it is a mismatch when the weights differ by
   more than TOL of the book or have opposite signs.
2. Percentile. The forward return (journal equity against its start) among
   every rolling window of the same number of days of the same rule's
   out-of-sample backtest (2024-01-01 to the day before the record started),
   net of 35 and 70 bps per unit of one-way turnover. The backtest's own return
   over the forward days is printed next to it.
3. Realised cost. Every filled autopilot order in the engine's saved state
   (and its backups, `--state` takes several): the engine's realised slippage
   against the arrival price in bps, positive when it cost, median and 90th
   percentile per coin and overall.

Books the mirror cannot replay (models retrained on the server, live-stream
event books) are listed with the reason; nothing is guessed.

Reads only. The fresh panels are built under --cache (default
$PYTHIA_REPORTS/_cache/forward_audit), never inside the data folder: the
memecoin daily klines are copied there first so their monthly cache is
written to the copy. Report: <reports>/forward_audit_run/latest.{md,json},
and results/forward_audit_run.md with PYTHIA_RESULTS.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from .. import report
from ..data import ROOT

NAME = "forward_audit_run"
TOL = 0.01                    # a mismatch: more than 1 % of the book apart
MISMATCH_PASS = 0.05          # pass: under 5 % of coin-days
PCT_PASS, PCT_KILL = 5.0, 1.0  # forward return above the 5th percentile; below the 1st freezes the record
SLIP_PASS_BPS, SLIP_RAISE_BPS = 10.0, 20.0
OOS_FROM = "2024-01-01"
COSTS = {"35 bps": 0.0035, "70 bps": 0.0070}
START_EQUITY = 10_000.0
DAY_US = 86_400_000_000

DAILY_BOOKS = ("tsmom", "tsmom_regime", "tsmom_top20", "breakout_top10", "tsmom_tranches",
               "memes_rotation", "memes_tsmom")
NOT_REPLAYED = {
    "m4_ls": "M4 is retrained weekly on the server and picks among the perps that trade at run time; the mirror "
             "keeps only the newest model, so earlier days cannot be scored with the model that chose them",
    "picks_ls": "M2 is retrained on all history at every rebalance against the live perp list; the mirror has no "
                "copy of either as of the rebalance days",
    "picks_ls_v2": "as picks_ls, with M2 v2",
    "trend4h_pullback": "hourly decisions with resting limits filled on live 1h bars; its own trades.csv is the "
                        "record and the study's fill model is the backtest, so there is no daily target to compare",
    "pumpfun_migration": "event book on the live pump.fun stream; no backtest signal exists",
    "pumpfun_filtered": "event book on the live pump.fun stream; no backtest signal exists",
    "pumpfun_filtered_quick": "event book on the live pump.fun stream; no backtest signal exists",
}


# ---------------------------------------------------------------- journals

def read_journal(book: str, root: Path | None = None) -> list[dict]:
    p = (root or ROOT) / "paper" / book / "journal.csv"
    if not p.exists():
        return []
    with p.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def held_of(row: dict) -> dict[str, float]:
    """The weights a journal row says the book held after its run, by coin."""
    try:
        w = json.loads(row.get("weights") or "{}")
    except ValueError:
        return {}
    return {str(k).removesuffix("USDT"): float(v) for k, v in w.items() if v is not None and math.isfinite(float(v))}


def day_of(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


def date_of(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


# ---------------------------------------------------------------- check 1

def reconcile_day(held: dict[str, float], target: dict[str, float], tol: float = TOL) -> list[dict]:
    """Every coin either side holds, with whether it is a mismatch: weights more
    than `tol` apart, or of opposite sign."""
    rows = []
    for c in sorted(set(held) | set(target)):
        h, t = held.get(c, 0.0), target.get(c, 0.0)
        if abs(h) < 1e-9 and abs(t) < 1e-9:
            continue
        rows.append({"coin": c, "held": h, "target": t, "diff": h - t,
                     "mismatch": abs(h - t) > tol or h * t < 0})
    return rows


def reconcile_book(journal: list[dict], target_for: Callable[[str], dict[str, float] | None],
                   tol: float = TOL) -> dict:
    """Check 1 over a whole journal. `target_for(run_date)` is what the backtest holds
    after the decision close the run used, or None when the panel has no such day."""
    coin_days, bad, missing = 0, 0, []
    worst: list[dict] = []
    by_day = []
    for r in journal:
        date = r.get("date") or ""
        tgt = target_for(date)
        if tgt is None:
            missing.append(date)
            continue
        rows = reconcile_day(held_of(r), tgt, tol)
        n_bad = sum(x["mismatch"] for x in rows)
        coin_days += len(rows)
        bad += n_bad
        by_day.append({"date": date, "coins": len(rows), "mismatches": n_bad,
                       "held_sum": round(sum(held_of(r).values()), 4), "target_sum": round(sum(tgt.values()), 4)})
        worst += [{"date": date, **x} for x in rows if x["mismatch"]]
    worst.sort(key=lambda x: -abs(x["diff"]))
    share = bad / coin_days if coin_days else None
    return {"coin_days": coin_days, "mismatches": bad, "share": share, "days": len(by_day), "missing": missing,
            "by_day": by_day, "worst": worst[:15],
            "pass": share is not None and share < MISMATCH_PASS,
            "kill": share is not None and share >= MISMATCH_PASS}


# ---------------------------------------------------------------- check 2

def rolling_returns(net: np.ndarray, n: int) -> np.ndarray:
    """Compounded return of every window of n consecutive days."""
    r = np.asarray(net, dtype=float)
    r = np.where(np.isfinite(r), r, 0.0)
    if n <= 0 or len(r) < n:
        return np.array([])
    logs = np.log1p(np.maximum(r, -0.999999))
    c = np.concatenate([[0.0], np.cumsum(logs)])
    return np.expm1(c[n:] - c[:-n])


def percentile_of(fwd: float, windows: np.ndarray) -> dict:
    if not len(windows):
        return {"windows": 0, "percentile": None}
    q = np.quantile(windows, [0.01, 0.05, 0.5, 0.95])
    pct = float((windows < fwd).mean() * 100)
    return {"windows": int(len(windows)), "percentile": pct, "p1_pct": float(q[0] * 100),
            "p5_pct": float(q[1] * 100), "median_pct": float(q[2] * 100), "p95_pct": float(q[3] * 100),
            "pass": pct > PCT_PASS, "kill": pct < PCT_KILL}


def forward_of(journal: list[dict]) -> tuple[float, int, str, str]:
    """(forward return, days of returns, first date, last date) of a journal."""
    eq = [float(r["equity"]) for r in journal if r.get("equity") not in (None, "")]
    first, last = journal[0]["date"], journal[-1]["date"]
    n = (datetime.strptime(last, "%Y-%m-%d") - datetime.strptime(first, "%Y-%m-%d")).days
    return eq[-1] / START_EQUITY - 1, n, first, last


def percentile_check(journal: list[dict], days: np.ndarray, gross: np.ndarray, tov: np.ndarray) -> dict:
    """Check 2 for one book: its forward return among the backtest's same-length
    out-of-sample windows, at each cost, plus the backtest over the forward days."""
    fwd, n, first, last = forward_of(journal)
    lo, hi = day_of(OOS_FROM), day_of(first) - DAY_US
    oos = (days >= lo) & (days <= hi)
    out = {"forward_pct": fwd * 100, "days": n, "first": first, "last": last,
           "oos_days": int(oos.sum()), "costs": {}}
    for label, c in COSTS.items():
        net = gross - c * np.r_[0.0, tov[:-1]]
        out["costs"][label] = percentile_of(fwd, rolling_returns(net[oos], n))
        # The same rule over the forward days themselves: returns earned on the
        # days after each run's decision close (first - 1 .. last - 1 as closes).
        same = (days >= day_of(first)) & (days <= day_of(last) - DAY_US)
        out["costs"][label]["backtest_same_days_pct"] = float((np.prod(1 + net[same]) - 1) * 100) if same.any() else None
    return out


# ---------------------------------------------------------------- check 3

def slippage(orders: list[dict]) -> dict:
    """Realised slippage of filled autopilot orders (deduplicated by id), overall and per coin."""
    seen: dict[str, dict] = {}
    for o in orders:
        if o.get("id") and o.get("book") and (o.get("filledQty") or 0) > 0 and o.get("realisedSlippageBps") is not None:
            seen[o["id"]] = o
    xs = list(seen.values())

    def stats(v: list[float]) -> dict:
        a = np.array(v, dtype=float)
        return {"fills": len(a), "median_bps": float(np.median(a)) if len(a) else None,
                "p90_bps": float(np.quantile(a, 0.9)) if len(a) else None}

    per: dict[str, list[float]] = {}
    for o in xs:
        per.setdefault(o.get("marketId", "?"), []).append(float(o["realisedSlippageBps"]))
    overall = stats([float(o["realisedSlippageBps"]) for o in xs])
    lab = stats([float(o["realisedSlippageBps"]) for o in xs if str(o.get("strategyId", "")).startswith("lab:")])
    med = lab["median_bps"]
    return {"overall": overall, "lab_books": lab,
            "pass": med is not None and med <= SLIP_PASS_BPS, "raise_cost": med is not None and med > SLIP_RAISE_BPS,
            "per_coin": sorted(({"market": m, **stats(v)} for m, v in per.items()), key=lambda r: -r["fills"]),
            "first_ms": min((o["ts"] for o in xs), default=None), "last_ms": max((o["ts"] for o in xs), default=None)}


def load_orders(paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        try:
            out += json.loads(p.read_text(encoding="utf-8")).get("orders") or []
        except (OSError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- the backtests, rerun

def _targets_by_date(days: np.ndarray, held: np.ndarray, names: list[str]) -> Callable[[str], dict | None]:
    """target_for(run date): the weights held after the close of the day before, by coin.
    A dead segment (`~`) keeps its full name so a weight on it shows up."""
    idx = {int(d): i for i, d in enumerate(days)}

    def target_for(date: str) -> dict[str, float] | None:
        t = idx.get(day_of(date) - DAY_US)
        if t is None:
            return None
        w = held[t]
        return {(names[j] if "~" in names[j] else names[j].removesuffix("USDT")): float(w[j])
                for j in np.flatnonzero(np.abs(w) > 1e-9)}

    return target_for


def sim_rebalanced(ret: np.ndarray, targets: np.ndarray, start: int) -> tuple[np.ndarray, np.ndarray]:
    """A book rebalanced to targets[t] at every close (paper/tsmom's books): gross
    return earned on day t and one-way turnover traded at the close of day t."""
    T, N = targets.shape
    w = np.zeros(N)
    gross, tov = np.zeros(T), np.zeros(T)
    for t in range(start, T):
        tov[t] = np.abs(targets[t] - w).sum()
        w = targets[t].copy()
        if t == T - 1:
            break
        r = np.nan_to_num(ret[t + 1])
        g = float(np.dot(w, r))
        gross[t + 1] = g
        w = w * (1 + r) / (1 + g) if 1 + g > 0 else np.zeros(N)
    return gross, tov


def tsmom_runs() -> dict[str, dict]:
    """tsmom and tsmom_regime exactly as paper/tsmom.py decides them."""
    from ..experiments.tsmom import daily_matrix, rolling_mean, target_weights
    from .tsmom import BOOKS
    days, close, rv, names = daily_matrix()
    sigma = np.sqrt(rolling_mean(rv, 30, 20))
    history = np.cumsum(np.isfinite(close), axis=0)
    btc = close[:, names.index("BTC")]
    ma200 = rolling_mean(btc[:, None], 200, 200)[:, 0]
    ret = np.full_like(close, np.nan)
    ret[1:] = close[1:] / close[:-1] - 1
    out = {}
    for book, cfg in BOOKS.items():
        start = max(cfg["lookbacks"]) + 1
        held = np.zeros_like(close)
        for t in range(start, len(days)):
            tgt = target_weights(close, sigma, history, t, cfg["lookbacks"], cfg["target"])
            if cfg["regime"] and not bool(btc[t] > ma200[t]):
                tgt = np.zeros_like(tgt)
            held[t] = tgt
        gross, tov = sim_rebalanced(ret, held, start)
        out[book] = {"days": days, "held": held, "names": [f"{n}USDT" for n in names], "gross": gross, "tov": tov}
    return out


def family_runs() -> dict[str, dict]:
    """tsmom_top20, breakout_top10 and tsmom_tranches as paper/families.py decides them,
    through the simulators their studies use (alpaca_universe.simulate on the full universe)."""
    from ..experiments import alpaca_universe as au
    from ..experiments import fam_common as fc
    from .families import targets
    P = fc.load_panel(fresh=True)
    W = targets(P)
    out = {}
    for book, w in W.items():
        gross, tov, _, held = au.simulate(P, book, w)
        out[book] = {"days": P.days, "held": np.clip(held, 0.0, None), "names": P.names, "gross": gross, "tov": tov}
    return out


def meme_runs(cache: Path) -> dict[str, dict]:
    """memes_rotation and memes_tsmom on W7's own panel. The daily klines are read from a
    copy of the data folder's cache under `cache`, so nothing is written into the data folder."""
    from .. import klines_daily
    from ..experiments import alpaca_universe as au
    from ..experiments import memecoins as w7
    from . import memes
    src_of = klines_daily.cache_dir
    dst = cache / "klines_1d"

    def cache_dir(symbol: str) -> Path:
        d = dst / f"symbol={symbol}"
        src = src_of(symbol)
        if not d.exists() and src.exists():
            shutil.copytree(src, d)
        return d

    klines_daily.cache_dir = cache_dir
    try:
        frames = w7.load_frames(memes.SYMBOLS)
    finally:
        klines_daily.cache_dir = src_of
    P = w7.build_panel(frames)
    out = {}
    for book, w in memes.targets(P).items():
        gross, tov, _, held = au.sim_daily(P, w)
        out[book] = {"days": P.days, "held": np.clip(held, 0.0, None), "names": P.names, "gross": gross, "tov": tov}
    return out


# ---------------------------------------------------------------- the report

def audit(runs: dict[str, dict], root: Path | None = None) -> dict:
    books = {}
    for book in DAILY_BOOKS:
        j = read_journal(book, root)
        run = runs.get(book)
        if not j or run is None:
            books[book] = {"replayed": False, "why": "no journal" if not j else "its backtest could not be rebuilt"}
            continue
        rec = reconcile_book(j, _targets_by_date(run["days"], run["held"], run["names"]))
        pct = percentile_check(j, run["days"], run["gross"], run["tov"])
        books[book] = {"replayed": True, "reconcile": rec, "percentile": pct}
    for book, why in NOT_REPLAYED.items():
        j = read_journal(book, root)
        if j:
            fwd, n, first, last = forward_of(j)
            books[book] = {"replayed": False, "why": why, "forward_pct": fwd * 100, "days": n, "first": first,
                           "last": last}
    return {"books": books}


def _f(x, nd: int = 2, pct: bool = False) -> str:
    if x is None:
        return "n/a"
    return f"{x:+.{nd}f} %" if pct else f"{x:.{nd}f}"


def markdown(res: dict) -> str:
    lines = [f"# Forward record audit, the numbers ({res['generated']})", "",
             "Machine output of `python -m lab.paper.forward_audit`; thresholds in `forward_audit_prereg.md`, "
             "findings and fixes in `forward_audit.md`.", "",
             "## 1. Signal reconciliation and 2. percentile", "",
             "| book | days | coin-days | mismatches | share | forward | backtest, same days (35 bps) | "
             "percentile 35 bps | 5th / median / 95th (35 bps) | percentile 70 bps | verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for book, b in res["books"].items():
        if not b.get("replayed"):
            continue
        r, p = b["reconcile"], b["percentile"]
        c35, c70 = p["costs"]["35 bps"], p["costs"]["70 bps"]
        ok = r["pass"] and bool(c35.get("pass"))
        kill = r["kill"] or bool(c35.get("kill"))
        verdict = "frozen (kill rule)" if kill else ("passes" if ok else "fails the pass rule, not the kill rule")
        lines.append(
            f"| {book} | {p['days']} | {r['coin_days']} | {r['mismatches']} | "
            f"{_f(r['share'] * 100 if r['share'] is not None else None, 1)} % | {_f(p['forward_pct'], 2, True)} | "
            f"{_f(c35.get('backtest_same_days_pct'), 2, True)} | {_f(c35.get('percentile'), 0)} | "
            f"{_f(c35.get('p5_pct'), 1, True)} / {_f(c35.get('median_pct'), 1, True)} / {_f(c35.get('p95_pct'), 1, True)} | "
            f"{_f(c70.get('percentile'), 0)} | {verdict} |")
    lines += ["", "Not replayed:", ""]
    for book, b in res["books"].items():
        if b.get("replayed"):
            continue
        fwd = f" Forward {b['forward_pct']:+.2f} % over {b['days']} days." if b.get("forward_pct") is not None else ""
        lines.append(f"- `{book}`: {b['why']}.{fwd}")
    lines += ["", "### Mismatched coin-days", ""]
    for book, b in res["books"].items():
        if not b.get("replayed") or not b["reconcile"]["worst"]:
            continue
        lines.append(f"**{book}**" + (f" (no panel day for {', '.join(b['reconcile']['missing'])})"
                                      if b["reconcile"]["missing"] else ""))
        lines.append("")
        lines.append("| run date | coin | held | backtest | difference |")
        lines.append("|---|---|---|---|---|")
        for w in b["reconcile"]["worst"]:
            lines.append(f"| {w['date']} | {w['coin']} | {w['held']:.4f} | {w['target']:.4f} | {w['diff']:+.4f} |")
        lines.append("")
    s = res.get("slippage")
    if s:
        lab, ov = s["lab_books"], s["overall"]
        lines += ["## 3. Realised cost of autopilot fills", "",
                  f"{ov['fills']} filled autopilot orders with a realised cost "
                  f"({datetime.fromtimestamp(s['first_ms'] / 1000, timezone.utc):%Y-%m-%d} to "
                  f"{datetime.fromtimestamp(s['last_ms'] / 1000, timezone.utc):%Y-%m-%d}): median "
                  f"{_f(ov['median_bps'], 1)} bps, 90th percentile {_f(ov['p90_bps'], 1)} bps. The lab books' fills "
                  f"({lab['fills']}): median {_f(lab['median_bps'], 1)} bps, 90th percentile {_f(lab['p90_bps'], 1)} bps "
                  f"against the arrival price (positive is a cost), fees not included.", "",
                  "| market | fills | median bps | 90th percentile bps |", "|---|---|---|---|"]
        for r in s["per_coin"]:
            lines.append(f"| {r['market']} | {r['fills']} | {_f(r['median_bps'], 1)} | {_f(r['p90_bps'], 1)} |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--state", action="append", default=None,
                    help="the engine's saved state (repeatable; default <data>/autopilot/state.json and its backups)")
    ap.add_argument("--cache", default=None)
    a = ap.parse_args(argv)
    cache = Path(a.cache) if a.cache else report.REPORTS / "_cache" / "forward_audit"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("PYTHIA_AGENT_OUT", str(cache / "agent-strategies"))
    from ..experiments import fam_common as fc
    fc.OUT = Path(os.environ["PYTHIA_AGENT_OUT"])
    if fc.OUT.resolve().is_relative_to(ROOT.resolve()):
        raise SystemExit("PYTHIA_AGENT_OUT points into the data folder; the audit writes its panels elsewhere")
    runs: dict[str, dict] = {}
    for name, fn in (("tsmom", tsmom_runs), ("families", family_runs), ("memes", lambda: meme_runs(cache))):
        try:
            runs.update(fn())
        except Exception as e:  # noqa: BLE001 - a book that cannot be rebuilt is reported, not fatal
            print(f"{name}: backtest not rebuilt ({type(e).__name__}: {e})")
    res = audit(runs)
    paths = [Path(p) for p in a.state] if a.state else sorted((ROOT / "autopilot").glob("state.json*"))
    res["slippage"] = slippage(load_orders(paths))
    res["generated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    report.write(NAME, markdown(res), res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
