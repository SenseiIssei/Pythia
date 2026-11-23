"""m4_perps forward record audit: does the paper book's record add up, and why is it 12 points ahead of its twin?

Pre-registration: results/m4_perps_forward_audit_prereg.md (checks and tolerances fixed there, before anything here
was computed). Write-up: results/m4_perps_forward_audit.md.

    python -m lab.paper.m4_perps_audit [--last 2026-11-22] [--no-targets]

1. Record arithmetic: equity = previous x (1 + gross + funding) x (1 - paper cost), within 1 bp a row.
2. Calendar: one run, a re-run or none per calendar day; a day without a run is missing, never a zero day.
3. Targets: reg7n retrained at each `model_trained` day on today's xs_daily panel cut there, the candidates of each
   decision day cut to the Kraken listing of the run day, the rank buffer on the previous booked target drifted with
   the reference prices; against the journal's weights (0.01, under 5 % of coin-days). Heavy (the panel): run it
   under flock /run/lock/pythia/heavy.lock; --no-targets skips it.
4. Marks: the booked return of every coin the journal pins (held in both rows, under the cap, not traded) against
   Binance spot's hourly bars interpolated at the run time (75 bps, under 5 % off, no stale mark), and the booked
   gross of each row against the previous target times those returns (20 bps a row, 50 bps the sum). Kraken
   Futures' hourly marks beside it.
5. Funding: the booked funding against Binance's settlements on the previous target (0.5 bp a row, 2 bps the sum);
   Kraken's hourly funding beside it.
6. Costs: paper cost = turnover x 5 bps + the half spread, model cost = turnover x 41 bps; the ratio against the
   band's cost per unit traded (m4l_series.json).
7. The gap to m4_hl_small on its dates: timing, funding, costs, universe, fills and the residual, in points.

Reads only (<data> is never written). Report: <reports>/m4_perps_forward_audit_run/latest.{md,json}, and
results/m4_perps_forward_audit_run.md with PYTHIA_RESULTS.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .. import report
from ..data import ROOT

NAME = "m4_perps_forward_audit_run"
BOOK, TWIN = "m4_perps", "m4_hl_small"
JOBS = {BOOK: "paper-m4-perps", TWIN: "paper-m4-hl-small"}
LAST = "2026-11-22"             # the forward report's last day (reports/forward/latest.json of 2026-11-22)
DAY_US, HOUR_US = 86_400_000_000, 3_600_000_000
START_EQUITY = 10_000.0
K = 10                          # CONFIG["k"]: a kept weight is capped at 1 / k
TAKER = 5e-4                    # m4_ls.TAKER_UM, Binance USD-M taker
MODEL_41 = 41e-4                # xs.COSTS["41bps"], m4_perps.MODEL_COST until this audit
MULTIPLIERS = ("1000000", "100000", "10000", "1000", "1M")
# Pre-registered tolerances (results/m4_perps_forward_audit_prereg.md).
TOL_EQUITY = 1e-4               # 1: a row's equity within 1 bp
SPAN_DAYS = 1.5                 # 2: a row whose marks span more than this carries missing days
TOL_W, MISMATCH_PASS = 0.01, 0.05   # 3
TOL_COIN, STALE_BOOKED, STALE_REF, COIN_PASS = 75e-4, 1e-4, 50e-4, 0.05   # 4a
TOL_ROW, TOL_SUM = 20e-4, 50e-4     # 4b
EXPLAIN_SLACK = 10e-4               # 4: basis and rounding when a coin-day off the hour bar is explained
TOL_FUND_ROW, TOL_FUND_SUM = 0.5e-4, 2e-4   # 5
TOL_COST_BPS, HALF_MAX_BPS = 0.02, 10.0     # 6


# ---------------------------------------------------------------- inputs

def read_journal(book: str, root: Path | None = None, last: str = LAST) -> list[dict]:
    p = (root or ROOT) / "paper" / book / "journal.csv"
    with p.open(newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r["date"] <= last]


def f(row: dict, key: str) -> float:
    try:
        v = float(row.get(key) or 0.0)
    except ValueError:
        return 0.0
    return v if math.isfinite(v) else 0.0


def weights_of(row: dict) -> dict[str, float]:
    try:
        return {s: float(x) for s, x in json.loads(row.get("weights") or "{}").items()}
    except ValueError:
        return {}


def iso_us(s: str) -> int:
    return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp() * 1e6)


def day_us(date: str) -> int:
    return int(datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1e6)


def date_of(us: int) -> str:
    return datetime.fromtimestamp(us / 1e6, timezone.utc).strftime("%Y-%m-%d")


def job_runs(job: str, root: Path | None = None) -> list[dict]:
    """The job's successful runs from <data>/_ops/runs/*.jsonl, oldest first: {start_us, end_us}."""
    out = []
    for p in sorted(((root or ROOT) / "_ops" / "runs").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("job") == job and r.get("status") == "ok" and r.get("start") and r.get("end"):
                out.append({"start_us": iso_us(r["start"]), "end_us": iso_us(r["end"])})
    return sorted(out, key=lambda r: r["start_us"])


def run_times(journal: list[dict], runs: list[dict]) -> list[dict]:
    """Each row's run: the n-th successful run of its date for the n-th row of that date (the job writes one row a
    successful run); a row without one takes its entry_hour_utc at minute 30, `logged` False."""
    by: dict[str, list[dict]] = {}
    for r in runs:
        by.setdefault(date_of(r["start_us"]), []).append(r)
    seen: dict[str, int] = {}
    out = []
    for row in journal:
        d = row["date"]
        i = seen.get(d, 0)
        seen[d] = i + 1
        if i < len(by.get(d, [])):
            out.append({**by[d][i], "logged": True})
        else:
            t = day_us(d) + int(f(row, "entry_hour_utc")) * HOUR_US + 30 * 60_000_000
            out.append({"start_us": t, "end_us": t, "logged": False})
    return out


def spot_of(perp: str) -> str:
    """The Binance spot pair of a USD-M perp: 1000PEPEUSDT -> PEPEUSDT (returns do not see the multiplier)."""
    s = perp.upper()
    s = s[:-4] if s.endswith("USDT") else s
    for p in MULTIPLIERS:
        if s.startswith(p) and len(s) > len(p):
            s = s[len(p):]
            break
    return s + "USDT"


def kraken_of(perp: str) -> str:
    c = spot_of(perp)[:-4]
    return "PF_" + {"BTC": "XBT"}.get(c, c) + "USD"


def hl_spot(coin: str) -> str:
    """Binance spot pair of a Hyperliquid coin (kPEPE is 1,000 PEPE)."""
    return (coin[1:] if coin.startswith("k") and coin[1:2].isupper() else coin) + "USDT"


def hl_mult(coin: str) -> float:
    return 1000.0 if coin.startswith("k") and coin[1:2].isupper() else 1.0


class Prices:
    """Hourly bars by symbol, loaded once: Binance spot (klines_1h, open and close per bar) or Kraken Futures' marks
    (mark_1h, close of the bar opening at ts_us)."""

    def __init__(self, root: Path | None, first_us: int, last_us: int):
        self.root, self.a, self.b = root or ROOT, first_us - 2 * DAY_US, last_us + 2 * DAY_US
        self.cache: dict[tuple[str, str], tuple[np.ndarray, np.ndarray, np.ndarray] | None] = {}

    def _spot(self, sym: str):
        import polars as pl
        fs = files(self.root / "hist" / "binance_spot" / "klines_1h" / f"symbol={sym}", self.a, self.b)
        if not fs:
            return None
        h = pl.concat([pl.read_parquet(p, columns=["open_time_us", "open", "high", "low", "close"]) for p in fs]) \
            .filter(pl.col("open_time_us").is_between(self.a, self.b)).unique("open_time_us").sort("open_time_us")
        return h["open_time_us"].to_numpy(), h["open"].to_numpy(), h["close"].to_numpy(), h["low"].to_numpy(), \
            h["high"].to_numpy()

    def _minute(self, sym: str):
        import polars as pl
        d = self.root / "candles" / "source=binance_rest" / f"asset={sym[:-4]}" / "tf=1m"
        fs = sorted(d.glob("*.parquet")) + sorted(d.glob("*/*.parquet")) if d.is_dir() else []
        if not fs:
            return None
        h = pl.concat([pl.read_parquet(p, columns=["open_time_us", "open", "close"]) for p in fs]) \
            .filter(pl.col("open_time_us").is_between(self.a, self.b)).unique("open_time_us").sort("open_time_us")
        return h["open_time_us"].to_numpy(), h["open"].to_numpy(), h["close"].to_numpy()

    def _kraken(self, sym: str):
        import polars as pl
        p = self.root / "kraken_futures" / "mark_1h" / f"{sym}.parquet"
        if not p.exists():
            return None
        h = pl.read_parquet(p).filter(pl.col("ts_us").is_between(self.a, self.b)).unique("ts_us").sort("ts_us")
        c = h["close"].to_numpy()
        # A mark bar's close is the price at ts + 1 h; its open is the bar before's close.
        return h["ts_us"].to_numpy(), np.concatenate([[np.nan], c[:-1]]), c

    def _bars(self, kind: str, sym: str):
        key = (kind, sym)
        if key not in self.cache:
            self.cache[key] = {"spot": self._spot, "kraken": self._kraken, "minute": self._minute}[kind](sym)
        return self.cache[key]

    def _bar(self, kind: str, sym: str, t_us: int):
        bars = self._bars(kind, sym)
        if bars is None:
            return None, None
        step = 60_000_000 if kind == "minute" else HOUR_US
        i = int(np.searchsorted(bars[0], t_us, side="right")) - 1
        if i < 0 or t_us - bars[0][i] >= step or not (bars[1][i] > 0 and bars[2][i] > 0):
            return None, None
        return bars, i

    def at(self, kind: str, sym: str, t_us: int) -> float | None:
        """The price at t: linear inside the bar holding t (an hour, or a minute for kind "minute"), between its open
        and its close."""
        bars, i = self._bar(kind, sym, t_us)
        if bars is None:
            return None
        step = 60_000_000 if kind == "minute" else HOUR_US
        ts, o, c = bars[:3]
        return float(o[i] + (c[i] - o[i]) * (t_us - ts[i]) / step)

    def span(self, sym: str, t0: int, t1: int) -> tuple[float, float] | None:
        """The least and most return between a price inside the spot hour bar holding t0 and one inside the bar
        holding t1 (their lows and highs)."""
        b0, i = self._bar("spot", sym, t0)
        b1, j = self._bar("spot", sym, t1)
        if b0 is None or b1 is None or not (b0[3][i] > 0 and b1[3][j] > 0):
            return None
        return float(b1[3][j] / b0[4][i] - 1), float(b1[4][j] / b0[3][i] - 1)

    def ret(self, kind: str, sym: str, t0: int, t1: int) -> float | None:
        a, b = self.at(kind, sym, t0), self.at(kind, sym, t1)
        return b / a - 1 if a and b else None


def files(d: Path, a_us: int, b_us: int) -> list[Path]:
    """The day files (YYYY-MM-DD) and month files (YYYY-MM) of a history folder that overlap [a, b]."""
    a, b = date_of(a_us), date_of(b_us)
    return [p for p in sorted(d.glob("*.parquet"))
            if (a <= p.stem <= b if len(p.stem) == 10 else a[:7] <= p.stem <= b[:7])] if d.is_dir() else []


def binance_funding(perp: str, t0: int, t1: int, root: Path | None = None) -> float | None:
    """Binance's settled funding of a perp in (t0, t1], from <data>/hist/binance_um/funding."""
    import polars as pl
    fs = files((root or ROOT) / "hist" / "binance_um" / "funding" / f"symbol={perp}", t0 - DAY_US, t1 + DAY_US)
    if not fs:
        return None
    x = pl.concat([pl.read_parquet(p) for p in fs]).unique("funding_time_us")
    return float(x.filter((pl.col("funding_time_us") > t0) & (pl.col("funding_time_us") <= t1))["funding_rate"].sum())


def kraken_funding(perp: str, t0: int, t1: int, root: Path | None = None) -> float | None:
    """Kraken Futures' hourly relative funding of the coin in (t0, t1], positive = longs pay."""
    import polars as pl
    p = (root or ROOT) / "kraken_futures" / "funding" / f"{kraken_of(perp)}.parquet"
    if not p.exists():
        return None
    x = pl.read_parquet(p).filter((pl.col("ts_us") > t0) & (pl.col("ts_us") <= t1))
    return float(x["rate"].sum()) if x.height else None


# ---------------------------------------------------------------- 1 and 2: arithmetic and calendar

def arithmetic(journal: list[dict], tol: float = TOL_EQUITY) -> list[dict]:
    """Rows whose equity is not the previous one moved by its own gross, funding and paper cost."""
    out, prev = [], START_EQUITY
    for i, r in enumerate(journal):
        want = prev * (1 + f(r, "gross_ret_pct") / 100 + f(r, "funding_pct") / 100) * (1 - f(r, "paper_cost_bps") / 1e4)
        got = f(r, "equity")
        if abs(got / want - 1) > tol:
            out.append({"row": i, "date": r["date"], "booked": got, "rebuilt": round(want, 2)})
        prev = got
    return out


def calendar(journal: list[dict], runs: list[dict] | None = None) -> dict:
    """Days of record, re-runs, empty-book rows, missing calendar days and the rows that span them."""
    booked = [r for r in journal if int(f(r, "held")) > 0 or weights_of(r)]
    dates = sorted({r["date"] for r in journal})
    record = sorted({r["date"] for r in booked})
    first, last = day_us(dates[0]), day_us(dates[-1])
    all_days = [date_of(first + i * DAY_US) for i in range((last - first) // DAY_US + 1)]
    missing = [d for d in all_days if d not in dates]
    reruns = sorted({d for d in dates if sum(r["date"] == d for r in journal) > 1})
    spans = []
    if runs:
        for i in range(1, len(journal)):
            g = (runs[i]["end_us"] - runs[i - 1]["end_us"]) / DAY_US
            if g > SPAN_DAYS:
                spans.append({"date": journal[i]["date"], "days": round(g, 2),
                              "gross_pct": f(journal[i], "gross_ret_pct")})
    return {"rows": len(journal), "calendar_days": len(all_days), "dates": len(dates), "record_days": len(record),
            "empty_rows": len(journal) - len(booked), "reruns": reruns, "missing": missing, "spans": spans,
            "elapsed_days": (last - first) // DAY_US}


# ---------------------------------------------------------------- 4 and 5: marks and funding

def pinned(prev: dict[str, float], cur: dict[str, float], gross: float, k: int = K) -> dict[str, float]:
    """The coin returns the journal pins: a coin held on the same side in both rows and under the 1/k cap was not
    traded, so its weight is the drifted one, w_t = w_t-1 (1 + r) / (1 + gross)."""
    cap = 1.0 / k - 1e-4
    return {s: cur[s] / prev[s] * (1 + gross) - 1 for s in prev
            if s in cur and prev[s] * cur[s] > 0 and abs(cur[s]) < cap}


def explain(booked: float, minute: float | None, span: tuple[float, float] | None) -> str | None:
    """Why a coin-day off the interpolated hour bar is not a booking error: Binance spot's minute bars at both run
    times agree within the tolerance, or the booked return lies inside what prices inside the two hour bars allow
    (EXPLAIN_SLACK for the perp's basis and the journal's 4 decimals). None: unexplained."""
    if minute is not None and abs(booked - minute) <= TOL_COIN:
        return "minute bars"
    if span is not None and span[0] - EXPLAIN_SLACK <= booked <= span[1] + EXPLAIN_SLACK:
        return "inside the hour bars"
    return None


def marks(journal: list[dict], runs: list[dict], px: Prices) -> dict:
    coin_days, rows = [], []
    for i in range(1, len(journal)):
        prev, cur = weights_of(journal[i - 1]), weights_of(journal[i])
        if not prev:
            continue
        t0, t1 = runs[i - 1]["end_us"], runs[i]["end_us"]
        g = f(journal[i], "gross_ret_pct") / 100
        ref = {s: px.ret("spot", spot_of(s), t0, t1) for s in prev}
        span = {s: px.span(spot_of(s), t0, t1) for s in prev}
        for s, rb in pinned(prev, cur, g).items():
            c = {"date": journal[i]["date"], "perp": s, "booked": rb, "spot": ref[s],
                 "kraken": px.ret("kraken", kraken_of(s), t0, t1), "minute": px.ret("minute", spot_of(s), t0, t1)}
            c["explained"] = explain(rb, c["minute"], span[s]) if ref[s] is not None and abs(rb - ref[s]) > TOL_COIN \
                else None
            coin_days.append(c)
        priced = [s for s in prev if ref[s] is not None]
        rebuilt = sum(prev[s] * ref[s] for s in priced)
        lo = sum(prev[s] * (span[s][0] if prev[s] > 0 else span[s][1]) for s in priced if span[s])
        hi = sum(prev[s] * (span[s][1] if prev[s] > 0 else span[s][0]) for s in priced if span[s])
        unpriced = sorted(s for s in prev if ref[s] is None)
        rows.append({"date": journal[i]["date"], "booked": g, "rebuilt": rebuilt, "unpriced": unpriced,
                     "unpriced_weight": sum(abs(prev[s]) for s in unpriced), "days": round((t1 - t0) / DAY_US, 2),
                     "explained": "inside the hour bars" if not unpriced and lo - EXPLAIN_SLACK <= g <= hi + EXPLAIN_SLACK
                     else None})
    judged = [c for c in coin_days if c["spot"] is not None]
    off = [c for c in judged if abs(c["booked"] - c["spot"]) > TOL_COIN]
    stale = [c for c in judged if abs(c["booked"]) < STALE_BOOKED and abs(c["spot"]) >= STALE_REF]
    kj = [c for c in coin_days if c["kraken"] is not None]
    mj = [c for c in coin_days if c["minute"] is not None]
    full = [r for r in rows if not r["unpriced"]]
    rows_off = [r for r in full if abs(r["booked"] - r["rebuilt"]) > TOL_ROW]
    sum_diff = sum(r["booked"] - r["rebuilt"] for r in full)
    return {"coin_days": len(coin_days), "judged": len(judged), "off": off, "stale": stale,
            "off_share": len(off) / len(judged) if judged else None,
            "unexplained": [c for c in off if not c["explained"]],
            "median_abs_bps": float(np.median([abs(c["booked"] - c["spot"]) for c in judged]) * 1e4) if judged else None,
            "kraken_judged": len(kj),
            "kraken_median_abs_bps": float(np.median([abs(c["booked"] - c["kraken"]) for c in kj]) * 1e4) if kj else None,
            "minute_judged": len(mj),
            "minute_median_abs_bps": float(np.median([abs(c["booked"] - c["minute"]) for c in mj]) * 1e4) if mj else None,
            "rows": rows, "rows_judged": len(full), "rows_off": rows_off, "sum_diff": sum_diff,
            "passes": bool(judged) and len(off) / len(judged) < COIN_PASS and not stale and not rows_off
            and abs(sum_diff) <= TOL_SUM}


def funding(journal: list[dict], runs: list[dict], root: Path | None = None) -> dict:
    """Booked funding against Binance's settlements on the previous target over (previous start, this start]: the
    book reads them at the start of its run (now_ms) since the last run's start (last_run_ms)."""
    rows = []
    for i in range(1, len(journal)):
        prev = weights_of(journal[i - 1])
        if not prev:
            continue
        t0, t1 = runs[i - 1]["start_us"], runs[i]["start_us"]
        bn = {s: binance_funding(s, t0, t1, root) for s in prev}
        kf = {s: kraken_funding(s, t0, t1, root) for s in prev}
        rows.append({"date": journal[i]["date"], "booked": f(journal[i], "funding_pct") / 100,
                     "binance": sum(-x * (bn[s] or 0.0) for s, x in prev.items()),
                     "missing": sorted(s for s in prev if bn[s] is None),
                     "kraken": sum(-x * kf[s] for s, x in prev.items() if kf[s] is not None),
                     "kraken_weight": sum(abs(x) for s, x in prev.items() if kf[s] is not None)})
    off = [r for r in rows if abs(r["booked"] - r["binance"]) > TOL_FUND_ROW]
    total = sum(r["booked"] - r["binance"] for r in rows)
    return {"rows": rows, "off": off, "sum_diff": total, "passes": not off and abs(total) <= TOL_FUND_SUM}


# ---------------------------------------------------------------- 6: costs

def costs(journal: list[dict], band_cost: float | None) -> dict:
    """The fill and model identities per row and the ratio against the 41 bps column and the band's cost."""
    rows, bad = [], []
    for r in journal:
        t = f(r, "turnover")
        if t <= 0:
            continue
        paper, model = f(r, "paper_cost_bps"), f(r, "model_cost_bps")
        half = (paper - t * TAKER * 1e4) / t
        rows.append({"date": r["date"], "turnover": t, "paper_bps": paper, "model_bps": model, "half_bps": half})
        if not (-TOL_COST_BPS <= half * t and half <= HALF_MAX_BPS) or abs(model - t * MODEL_41 * 1e4) > TOL_COST_BPS:
            bad.append(r["date"])
    turn = sum(x["turnover"] for x in rows)
    paper = sum(x["paper_bps"] for x in rows)
    model = sum(x["model_bps"] for x in rows)
    out = {"rows": rows, "bad": bad, "turnover": turn, "paper_pct": paper / 100, "model_pct": model / 100,
           "ratio_41": paper / model if model else None, "taker_bps_per_unit": TAKER * 1e4,
           "half_bps_per_unit": (paper - turn * TAKER * 1e4) / turn if turn else None, "band_cost_bps": None}
    if band_cost:
        out.update(band_cost_bps=band_cost * 1e4, band_model_pct=turn * band_cost * 100,
                   ratio_band=paper / (turn * band_cost * 1e4) if turn else None)
    return out


def band_cost(root: Path | None = None) -> float | None:
    """The band's cost per unit traded: m4l_series.json's fee plus mean slip for m4_perps."""
    p = (root or ROOT) / "lab-cache" / "m4l_series.json"
    try:
        b = json.loads(p.read_text(encoding="utf-8"))["books"][BOOK]
        return (float(b["fee_bps"]) + float(b["slip_bps"])) / 1e4
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---------------------------------------------------------------- 7: the gap to m4_hl_small

def twin_positions(root: Path | None = None, last: str = LAST) -> dict[str, dict[str, tuple[float, float]]]:
    """{date: {coin: (units, unit price at the fill)}} after each of the twin's runs, rebuilt from orders/<date>.json
    (filled at the order's notional over its size)."""
    d = (root or ROOT) / "paper" / TWIN / "orders"
    units: dict[str, float] = {}
    px: dict[str, float] = {}
    out = {}
    for p in sorted(d.glob("????-??-??.json")):
        if p.stem > last:
            break
        o = json.loads(p.read_text(encoding="utf-8"))
        for od in o.get("orders") or []:
            q = float(od["size"]) * (1 if od["side"] == "buy" else -1)
            units[od["coin"]] = units.get(od["coin"], 0.0) + q
            if float(od["size"]) > 0:
                px[od["coin"]] = float(od["notional_usd"]) / float(od["size"])
            if abs(units[od["coin"]]) < 1e-12:
                units.pop(od["coin"])
        out[p.stem] = {c: (u, px.get(c, 0.0)) for c, u in units.items()}
    return out


def ret_between(journal: list[dict], a: str, b: str) -> float:
    """The book's return from its equity at the end of date a (START_EQUITY before its first row) to date b."""
    ea = [f(r, "equity") for r in journal if r["date"] <= a]
    eb = [f(r, "equity") for r in journal if r["date"] <= b]
    return (eb[-1] if eb else START_EQUITY) / (ea[-1] if ea else START_EQUITY) - 1


def unlisted(journal: list[dict]) -> set[str]:
    """Every coin a book dropped as unlisted on its venue on any day (journal `dropped_unlisted`), as bare coins."""
    out = set()
    for r in journal:
        out |= {spot_of(x)[:-4] for x in (r.get("dropped_unlisted") or "").split()}
    return out


def gap(book: list[dict], book_runs: list[dict], twin: list[dict], twin_runs: list[dict], pos: dict,
        px: Prices) -> dict:
    """The return gap, book minus twin, in points, additive per pair of the twin's runs (compounding is the residual).

    timing:   the book's return through the twin's first run day, and the twin's positions moved over the book's
              run hours against its own run hours;
    funding:  booked funding, book minus twin;      costs: the twin's paper cost minus the book's;
    universe: the reference gross of coins the other venue does not list (the other book's dropped_unlisted);
    fills:    the reference gross of different weights on coins both list (the buffer's path, whole units, the 250
              USD sizing), plus each book's booked gross against the reference (its venue's mids)."""
    first, last = twin[0]["date"], twin[-1]["date"]
    not_hl, not_kf = unlisted(twin), unlisted(book)
    pre = ret_between(book, "0000", first)
    total = ret_between(book, "0000", last) - ret_between(twin, "0000", last)
    # the twin's first row: its entry costs and any funding, before a pair of runs exists
    parts = {"timing": pre, "funding": -f(twin[0], "funding_pct") / 100, "costs": f(twin[0], "paper_cost_bps") / 1e4,
             "universe": 0.0, "fills": 0.0}
    sub = {"timing: before the twin's first run": pre, "timing: run hours": 0.0, "fills: weights on common coins": 0.0,
           "fills: m4_perps' marks against spot": 0.0, "fills: m4_hl_small's marks against spot": 0.0}
    weights = {"unpriced_twin": 0.0, "pairs": 0}
    for i in range(1, len(twin)):
        d0, d1 = twin[i - 1]["date"], twin[i]["date"]
        t0, t1 = twin_runs[i - 1]["end_us"], twin_runs[i]["end_us"]
        rows = [j for j, r in enumerate(book) if d0 < r["date"] <= d1 and j > 0]
        eq = f(twin[i - 1], "equity_usd")
        wt = {}
        for c, (u, p_fill) in pos.get(d0, {}).items():
            p = px.at("spot", hl_spot(c), t0)
            wt[c] = u * (p * hl_mult(c) if p else p_fill) / eq if eq else 0.0
            if p is None:
                weights["unpriced_twin"] += abs(wt[c])
        weights["pairs"] += 1
        r_tw = {c: px.ret("spot", hl_spot(c), t0, t1) or 0.0 for c in wt}
        ref_tw = sum(w * r_tw[c] for c, w in wt.items())
        uni_bk = com_bk = uni_tw_bk = com_tw_bk = g_bk = 0.0
        for j in rows:
            b0, b1 = book_runs[j - 1]["end_us"], book_runs[j]["end_us"]
            g_bk += f(book[j], "gross_ret_pct") / 100
            parts["funding"] += f(book[j], "funding_pct") / 100
            parts["costs"] -= f(book[j], "paper_cost_bps") / 1e4
            for s, x in weights_of(book[j - 1]).items():
                r = px.ret("spot", spot_of(s), b0, b1) or 0.0
                if spot_of(s)[:-4] in not_hl:
                    uni_bk += x * r
                else:
                    com_bk += x * r
            for c, w in wt.items():
                r = px.ret("spot", hl_spot(c), b0, b1) or 0.0
                if hl_spot(c)[:-4] in not_kf:
                    uni_tw_bk += w * r
                else:
                    com_tw_bk += w * r
        parts["funding"] -= f(twin[i], "funding_pct") / 100
        parts["costs"] += f(twin[i], "paper_cost_bps") / 1e4
        parts["timing"] += (uni_tw_bk + com_tw_bk) - ref_tw
        parts["universe"] += uni_bk - uni_tw_bk
        parts["fills"] += (com_bk - com_tw_bk) + (g_bk - uni_bk - com_bk) - (f(twin[i], "gross_ret_pct") / 100 - ref_tw)
        sub["timing: run hours"] += (uni_tw_bk + com_tw_bk) - ref_tw
        sub["fills: weights on common coins"] += com_bk - com_tw_bk
        sub["fills: m4_perps' marks against spot"] += g_bk - uni_bk - com_bk
        sub["fills: m4_hl_small's marks against spot"] -= f(twin[i], "gross_ret_pct") / 100 - ref_tw
    parts["residual"] = total - sum(parts.values())
    return {"total": total, "parts": parts, "sub": sub, "first": first, "last": last, **weights,
            "book_common": ret_between(book, first, last), "twin": ret_between(twin, "0000", last)}


# ---------------------------------------------------------------- 3: targets

def kraken_listing_at(date: str, root: Path | None = None) -> dict[str, str]:
    """{coin: symbol} of the PF_ perps Kraken Futures had open on the run day (perps_all's listings: opened by then,
    not delisted before it)."""
    from . import m4_perps as mp
    p = (root or ROOT) / "free" / "perps_all" / "kraken_futures" / "listings.json"
    t = day_us(date) + DAY_US
    out = {}
    for sym, x in json.loads(p.read_text(encoding="utf-8")).items():
        if not sym.startswith("PF_") or (x.get("opening_us") or 0) > t:
            continue
        if x.get("delisted") and x.get("last_day") and x["last_day"] < date:
            continue
        c = mp.kraken_coin({"base": x.get("base"), "symbol": sym})
        if c:
            out.setdefault(c, sym)
    return out


def perp_day_known(day: int, run_us: int, root: Path | None = None) -> bool:
    """Was Binance's daily perp archive of `day` on disk at the run? The backfill writes klines_1d/<day>.parquet two
    days later at about 03:35 UTC (BTCUSDT's file time); a day already compacted into its month file is taken to have
    followed the same rule."""
    p = (root or ROOT) / "hist" / "binance_um" / "klines_1d" / "symbol=BTCUSDT" / f"{date_of(day)}.parquet"
    if p.exists():
        return p.stat().st_mtime * 1e6 <= run_us
    return day + 2 * DAY_US + 3 * HOUR_US + 35 * 60_000_000 <= run_us


def reconcile(booked: dict[str, float], rebuilt: dict[str, float], tol: float = TOL_W) -> list[dict]:
    """Coin-days (every coin either side holds) more than tol apart or on opposite sides."""
    out = []
    for s in sorted(set(booked) | set(rebuilt)):
        a, b = booked.get(s, 0.0), rebuilt.get(s, 0.0)
        if abs(a - b) > tol or a * b < 0:
            out.append({"perp": s, "booked": a, "rebuilt": round(b, 4)})
    return out


def drift(w: dict[str, float], rets: dict[str, float | None]) -> dict[str, float]:
    """m4_perps.mark on reference returns (a coin without one moves 0)."""
    r = {s: rets.get(s) or 0.0 for s in w}
    g = sum(w[s] * r[s] for s in w)
    return {s: x * (1 + r[s]) / (1 + g) for s, x in w.items()} if 1 + g > 0 else dict(w)


def targets(journal: list[dict], runs: list[dict], px: Prices, root: Path | None = None, log=print) -> dict:
    """Check 3 (heavy: today's xs_daily panel and one reg7n fit per model_trained day)."""
    import lightgbm as lgb
    import polars as pl

    from ..experiments import xs_daily as xs
    from . import m4_ls as m4
    from . import m4_perps as mp
    root = root or ROOT
    P0 = pl.read_parquet(root / "lab-cache" / "xs_daily_panel.parquet")
    base = ((pl.col("age") >= xs.MIN_HISTORY_D) & (pl.col("adv28") >= np.log(xs.MIN_ADV_USD + 1))
            & pl.col("r112").is_not_null()).fill_null(False)

    def scoring(dd: int) -> pl.DataFrame:
        # m4_ls.live_panel's decision day: eligible without the entry price, dispersion recomputed
        P = P0.filter(pl.col("day") == dd).with_columns(eligible=base)
        P = P.with_columns(disp1=pl.lit(P.filter("eligible")["r1"].std()))
        return xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), fund7_raw=pl.col("fund7")))

    models: dict[int, tuple] = {}

    def model(T: int):
        if T not in models:
            P, _ = xs.add_net_labels(P0.filter(pl.col("day") <= T))
            E = xs.ranked(P.with_columns(adv28_raw=pl.col("adv28"), fund7_raw=pl.col("fund7")))
            y = np.asarray(E["y7n"].to_numpy(), dtype=float)
            tr = np.isfinite(y)
            X = E.select(xs.FEATURES).to_numpy().astype(np.float32)
            est = lgb.LGBMRegressor(**xs.REG_PARAMS).fit(X[tr], y[tr])
            models[T] = (est.booster_, int(tr.sum()))
            log(f"reg7n as of {date_of(T)}: {int(tr.sum())} rows")
            del P, E, X
        return models[T]

    # the one model the server kept (the newest): its own fit, to tell a refit's drift from the book's code
    cached = None
    mf, mm = root / "lab-cache" / "m4_perps_reg7n.txt", root / "lab-cache" / "m4_perps_reg7n.json"
    if mf.exists() and mm.exists():
        cached = (lgb.Booster(model_file=str(mf)), date_of(json.loads(mm.read_text(encoding="utf-8"))["decision_day"]))
    days, explained = [], []
    for i in range(1, len(journal)):
        row, prev = journal[i], weights_of(journal[i - 1])
        booked = weights_of(row)
        if not booked:
            continue
        booster, n = model(day_us(row["model_trained"]))
        listing = kraken_listing_at(row["date"], root)
        rets = {s: px.ret("spot", spot_of(s), runs[i - 1]["end_us"], runs[i]["end_us"]) for s in prev}
        w = drift(prev, rets)

        def rebuild(dd: int, bst=booster) -> tuple[dict[str, float], int, int]:
            # m4_perps.main: the decision day steps back (at most MAX_LAG_DAYS) while it has under MIN_SCOREABLE
            # perps; a day whose perp archive was not on disk at the run has none
            for _ in range(mp.MAX_LAG_DAYS + 1):
                if perp_day_known(dd, runs[i]["start_us"], root):
                    E = scoring(dd)
                    live = set(E.filter(pl.col("perp").is_not_null())["perp"].to_list())
                    c = m4.candidates(E, bst, dd, live, cfg=mp.CONFIG)
                    if c.height >= mp.MIN_SCOREABLE:
                        break
                dd -= DAY_US
            listed, _ = mp.restrict(c, listing)
            return mp.target(listed, w), listed.height, dd

        tgt, nl, dd = rebuild(day_us(row["date"]) - DAY_US)
        mis = reconcile(booked, tgt)
        lag = None
        if mis:
            t2, _, _ = rebuild(dd - DAY_US)
            if len(reconcile(booked, t2)) < len(mis):
                lag = len(reconcile(booked, t2))
                explained.append(row["date"])
        served = None
        if mis and cached is not None and row["model_trained"] == cached[1]:
            served = len(reconcile(booked, rebuild(day_us(row["date"]) - DAY_US, cached[0])[0]))
        days.append({"date": row["date"], "coin_days": len(set(booked) | set(tgt)), "mismatches": mis,
                     "listed": nl, "listed_booked": int(f(row, "listed_universe")), "rows_trained": n,
                     "decision_day": date_of(dd), "lag_mismatches": lag, "served_model_mismatches": served})
        log(f"{row['date']}: {len(mis)} mismatches of {days[-1]['coin_days']}")
    # the refit against the kept model on the first decision day that used it: score rank correlation and how many
    # of the 10 + 10 names they share among the listed candidates
    drift_vs_kept = None
    use = [d for d in days if cached is not None and journal[[r["date"] for r in journal].index(d["date"])]
           ["model_trained"] == cached[1]]
    if use:
        from scipy.stats import spearmanr
        dd = day_us(use[0]["decision_day"])
        E = scoring(dd)
        live = set(E.filter(pl.col("perp").is_not_null())["perp"].to_list())
        listing = kraken_listing_at(use[0]["date"], root)
        picks = []
        for bst in (models[day_us(cached[1])][0], cached[0]):
            c, _ = mp.restrict(m4.candidates(E, bst, dd, live, cfg=mp.CONFIG), listing)
            picks.append(c)
        a = picks[0].select("perp", "score").join(picks[1].select("perp", kept="score"), on="perp")
        ends = [set(c["perp"].head(K).to_list()) | set(c["perp"].tail(K).to_list()) for c in picks]
        drift_vs_kept = {"decision_day": use[0]["decision_day"], "spearman": float(spearmanr(a["score"], a["kept"])[0]),
                         "shared_ends": len(ends[0] & ends[1]), "rows_refit": models[day_us(cached[1])][1],
                         "rows_kept": int(json.loads(mm.read_text(encoding="utf-8")).get("rows") or 0)}
    cd = sum(d["coin_days"] for d in days)
    mm = sum(len(d["mismatches"]) for d in days)
    return {"days": days, "coin_days": cd, "mismatches": mm, "share": mm / cd if cd else None,
            "passes": bool(cd) and mm / cd < MISMATCH_PASS, "lag_explained": explained,
            "served_model": cached[1] if cached else None, "refit_vs_kept": drift_vs_kept}


# ---------------------------------------------------------------- report

def _p(x, nd: int = 2) -> str:
    return "" if x is None else f"{x * 100:+.{nd}f} %"


def _b(x, nd: int = 1) -> str:
    return "" if x is None else f"{x * 1e4:.{nd}f}"


def per_day(journal: list[dict], runs: list[dict], res: dict) -> list[dict]:
    """One line per journal row: the booked figures and each check's verdict on it."""
    mk = {r["date"]: r for r in res["marks"]["rows"]}
    fu = {r["date"]: r for r in res["funding"]["rows"]}
    tg = {d["date"]: d for d in (res.get("targets") or {}).get("days", [])}
    ar = {a["date"] for a in res["arithmetic"]}
    off_coin: dict[str, int] = {}
    for c in res["marks"]["off"]:
        off_coin[c["date"]] = off_coin.get(c["date"], 0) + 1
    span = {s["date"] for s in res["calendar"]["spans"]}
    out = []
    for i, r in enumerate(journal):
        m, fd, t = mk.get(r["date"]), fu.get(r["date"]), tg.get(r["date"])
        notes = []
        if not weights_of(r):
            notes.append("empty book")
        if i and r["date"] == journal[i - 1]["date"]:
            notes.append("re-run")
        if r["date"] in span:
            notes.append("spans missing days")
        if t and t.get("served_model_mismatches") == 0 and weights_of(r):
            notes.append("the kept model: 0 mismatches")
        out.append({"date": r["date"], "run": datetime.fromtimestamp(runs[i]["end_us"] / 1e6, timezone.utc)
                    .strftime("%H:%M"), "equity": f(r, "equity"),
                    "arith": "off" if r["date"] in ar else "ok",
                    "gross": _p(f(r, "gross_ret_pct") / 100), "ref": _p(m["rebuilt"]) if m else "",
                    "gross_diff_bps": _b(m["booked"] - m["rebuilt"]) if m and not m["unpriced"] else
                    (f"({_b(m['booked'] - m['rebuilt'])}, {len(m['unpriced'])} unpriced)" if m else ""),
                    "coins_off": off_coin.get(r["date"], 0) if m else "",
                    "funding_bps": _b(f(r, "funding_pct") / 100, 2),
                    "binance_bps": _b(fd["binance"], 2) if fd else "",
                    "turnover": f(r, "turnover"), "paper_bps": f(r, "paper_cost_bps"),
                    "model_bps": f(r, "model_cost_bps"),
                    "targets": (f"{len(t['mismatches'])}/{t['coin_days']}" if t and weights_of(r)
                                and (i + 1 == len(journal) or journal[i + 1]["date"] != r["date"]) else ""),
                    "note": ", ".join(notes)})
    return out


def markdown(res: dict) -> str:
    c, m, fu, co = res["calendar"], res["marks"], res["funding"], res["costs"]
    t = res.get("targets")
    L = [f"# m4_perps forward record audit, the numbers ({res['generated']})", "",
         "Machine output of `python -m lab.paper.m4_perps_audit`; checks and tolerances in "
         "`m4_perps_forward_audit_prereg.md`, findings and fixes in `m4_perps_forward_audit.md`.", "",
         f"Journal rows through {res['last']}: {c['rows']}. Calendar days {c['calendar_days']}, dates with a run "
         f"{c['dates']}, days of record (a book held) {c['record_days']}, empty-book rows {c['empty_rows']}, "
         f"re-run dates {', '.join(c['reruns']) or 'none'}.", "",
         "## Per day", ""]
    L.append(report.table(res["per_day"], ["date", "run", "equity", "arith", "gross", "ref", "gross_diff_bps",
                                           "coins_off", "funding_bps", "binance_bps", "turnover", "paper_bps",
                                           "model_bps", "targets", "note"]))
    L += ["", "gross_diff_bps: booked gross minus the previous target times Binance spot's interpolated returns "
          "(in brackets where a coin has no spot bars). coins_off: pinned coin returns more than 75 bps off. "
          "targets: mismatched coin-days of the rebuilt target.", "",
          "## 1. Arithmetic", "",
          f"{len(res['arithmetic'])} rows off by more than 1 bp of equity"
          + (": " + ", ".join(a["date"] for a in res["arithmetic"]) if res["arithmetic"] else "."), "",
          "## 2. Calendar", "",
          f"Missing days (no run): {', '.join(c['missing']) or 'none'}."]
    for s in c["spans"]:
        L.append(f"- {s['date']}: one row spans {s['days']} days, gross {s['gross_pct']:+.4f} %.")
    L += ["", "## 3. Targets", ""]
    if t:
        L.append(f"{t['mismatches']} mismatched coin-days of {t['coin_days']} ({t['share'] * 100:.1f} %): "
                 + ("passes" if t["passes"] else "fails") + " (under 5 %).")
        bad = [d for d in t["days"] if d["mismatches"]]
        if bad:
            L += ["", "Per run date with a mismatch: the decision day the book's lag rule takes on the archive the run "
                  "had, the mismatches one day further back, and with the model the server kept "
                  f"(trained {t.get('served_model')}) where the row used it.", "",
                  "| run date | decision day | listed (rebuilt / booked) | coin | booked | rebuilt | one day back | "
                  "kept model |", "|---|---|---|---|---|---|---|---|"]
            for d in bad:
                for x in d["mismatches"]:
                    L.append(f"| {d['date']} | {d['decision_day']} | {d['listed']} / {d['listed_booked']} | "
                             f"{x['perp']} | {x['booked']:.4f} | {x['rebuilt']:.4f} | "
                             f"{'' if d['lag_mismatches'] is None else d['lag_mismatches']} | "
                             f"{'' if d['served_model_mismatches'] is None else d['served_model_mismatches']} |")
        k = t.get("refit_vs_kept")
        if k:
            L.append(f"\nThe refit against the model the server kept, on decision day {k['decision_day']}: score rank "
                     f"correlation {k['spearman']:.3f}, {k['shared_ends']} of the 20 end names shared; trained on "
                     f"{k['rows_refit']} rows against {k['rows_kept']} (today's panel is revised).")
    else:
        L.append("Not run (--no-targets).")
    L += ["", "## 4. Marks", "",
          f"Pinned coin-days {m['coin_days']}, with spot bars {m['judged']}: {len(m['off'])} more than 75 bps off "
          f"({(m['off_share'] or 0) * 100:.1f} %), median gap {m['median_abs_bps']:.1f} bps; stale marks "
          f"{len(m['stale'])}. Against Kraken Futures' marks ({m['kraken_judged']} coin-days): median gap "
          f"{m['kraken_median_abs_bps']:.1f} bps. Against Binance spot's minute bars ({m['minute_judged']} "
          f"coin-days): median gap {m['minute_median_abs_bps']:.1f} bps.",
          f"Rows fully priced {m['rows_judged']}: {len(m['rows_off'])} more than 20 bps off; booked minus rebuilt "
          f"over them {m['sum_diff'] * 1e4:+.1f} bps (tolerance 50). "
          + ("Passes." if m["passes"] else "Fails the pre-registered rule.")
          + f" Off coin-days not explained: {len(m['unexplained'])}; off rows not explained: "
          f"{sum(1 for r in m['rows_off'] if not r['explained'])}."]
    if m["off"] or m["stale"]:
        L += ["", "| date | perp | booked | spot (hour bar) | minute bars | kraken | why |", "|---|---|---|---|---|---|---|"]
        for x in m["off"] + [c for c in m["stale"] if c not in m["off"]]:
            L.append(f"| {x['date']} | {x['perp']} | {_p(x['booked'])} | {_p(x['spot'])} | {_p(x['minute'])} | "
                     f"{_p(x['kraken'])} | {x['explained'] or ('stale?' if x in m['stale'] else 'unexplained')} |")
    if m["rows_off"]:
        L.append("\nRows off: " + ", ".join(f"{r['date']} ({(r['booked'] - r['rebuilt']) * 1e4:+.1f} bps, "
                                            f"{r['explained'] or 'unexplained'})" for r in m["rows_off"]) + ".")
    L += ["", "## 5. Funding", "",
          f"{len(fu['off'])} rows more than 0.5 bp off Binance's settlements; booked minus Binance over the record "
          f"{fu['sum_diff'] * 1e4:+.2f} bps (tolerance 2). " + ("Passes." if fu["passes"] else "Fails.")
          + f" Booked {sum(r['booked'] for r in fu['rows']) * 100:+.4f} %, Binance "
          f"{sum(r['binance'] for r in fu['rows']) * 100:+.4f} %, Kraken on the coins it lists "
          f"{sum(r['kraken'] for r in fu['rows']) * 100:+.4f} %.", "",
          "## 6. Costs", "",
          f"Rebalance rows {len(co['rows'])}, turnover {co['turnover']:.4f}. Paper {co['paper_pct']:.4f} % = taker "
          f"{co['taker_bps_per_unit']:.1f} bps + half spread {co['half_bps_per_unit']:.2f} bps per unit traded; "
          f"model column {co['model_pct']:.4f} % (41 bps per unit). Ratio {co['ratio_41']:.3f}. Rows off the "
          f"identities: {', '.join(co['bad']) or 'none'}."]
    if co.get("band_cost_bps"):
        L.append(f"Against the band's cost ({co['band_cost_bps']:.2f} bps per unit, m4l_series.json): model "
                 f"{co['band_model_pct']:.4f} %, ratio {co['ratio_band']:.3f}.")
    g = res.get("gap")
    if g:
        L += ["", "## 7. The gap to m4_hl_small", "",
              f"m4_perps {_p(res.get('book_return'))} through {g['last']}, m4_hl_small {_p(g['twin'])}: gap "
              f"{g['total'] * 100:+.2f} points. m4_perps on the twin's days ({g['first']} to {g['last']}): "
              f"{_p(g['book_common'])}.", "", "| part | points |", "|---|---|"]
        for k, v in g["parts"].items():
            L.append(f"| {k} | {v * 100:+.2f} |")
        L += ["", "| of which | points |", "|---|---|"] + [f"| {k} | {v * 100:+.2f} |" for k, v in g["sub"].items()]
        L.append(f"\nThe twin's weight without spot bars (summed over {g['pairs']} steps): {g['unpriced_twin']:.3f}.")
    return "\n".join(L) + "\n"


def audit(root: Path | None = None, last: str = LAST, with_targets: bool = True, log=print) -> dict:
    root = root or ROOT
    j = read_journal(BOOK, root, last)
    runs = run_times(j, job_runs(JOBS[BOOK], root))
    px = Prices(root, runs[0]["start_us"], runs[-1]["end_us"])
    res = {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "last": last,
           "book_return": f(j[-1], "equity") / START_EQUITY - 1,
           "unlogged_rows": [r["date"] for r, x in zip(j, runs) if not x["logged"]],
           "arithmetic": arithmetic(j), "calendar": calendar(j, runs), "marks": marks(j, runs, px),
           "funding": funding(j, runs, root), "costs": costs(j, band_cost(root))}
    tw = read_journal(TWIN, root, last)
    if tw:
        res["gap"] = gap(j, runs, tw, run_times(tw, job_runs(JOBS[TWIN], root)), twin_positions(root, last), px)
    if with_targets:
        res["targets"] = targets(j, runs, px, root, log)
    res["per_day"] = per_day(j, runs, res)
    return res


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--last", default=LAST)
    ap.add_argument("--no-targets", action="store_true")
    a = ap.parse_args(argv)
    res = audit(last=a.last, with_targets=not a.no_targets)
    report.write(NAME, markdown(res), res)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
