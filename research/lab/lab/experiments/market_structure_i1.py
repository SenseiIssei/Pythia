"""I1: calendar and lead-lag on the hourly panel, as pre-registered in results/market_structure_i1_prereg.md.
A measurement, not a strategy: nothing live, no paper book. The regime part was dropped after the
review of 2026-10-27 (M5 and M7 failed already).

    python -m lab.experiments.market_structure_i1     writes results/market_structure_i1.md (below the
                                                      marker) and reports/market_structure_i1/latest.json

Everything sits on one UTC hour grid. r[i] is a coin's log return over [grid[i], grid[i] + 1h) (close of
the bar opening at grid[i] over the close before it, NaN across a gap). A decision at T = grid[i] knows
only what closed by T: a predictor at i uses bars before i, a target starts at i.

Calendar (44 tests per asset; BTC, ETH, the alt basket): Welch t of the hourly returns inside a window
against outside it; cost check on the holdout: the mean log return per occurrence (a run of window
hours), in the sign of the whole-period t, above a 30 bps round trip.
Lead-lag (172): D2's purged rank IC of a predictor known at T with the return over [T, T+h), h 1 and 4;
cost check: holdout hours with x in the discovery half's top decile (bottom: the opposite sign) as
trades, their mean above a round trip (30 bps, 60 for the alt against BTC).
Pass: Holm p <= 0.05 over every test, the same sign in both halves, the cost check.
"""

from __future__ import annotations

import json
import math
import os
import sys
import warnings
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import polars as pl
from scipy import stats

from ..data import HOUR_US, UNIVERSE
from .data_free_d2 import holm, purged_ic

NAME = "market_structure_i1"
RESULTS = Path(os.environ.get("PYTHIA_RESULTS", Path(__file__).resolve().parents[2] / "results"))
MARKER = "<!-- generated below by lab.experiments.market_structure_i1; edit above this line only -->"
UTC = timezone.utc
NY = ZoneInfo("America/New_York")
DAY_US = 24 * HOUR_US
START = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp() * 1e6)
SPLIT = int(datetime(2024, 1, 1, tzinfo=UTC).timestamp() * 1e6)
SIDE = 0.0015  # Binance taker plus half the spread, a side
HORIZONS = (1, 4)
ALPHA = 0.05
MIN_OBS = 30  # observations a calendar window needs in each group
FUNDING_MAX_AGE_US = 9 * HOUR_US
ALTS = [c for c in UNIVERSE if c not in ("BTC", "ETH")]
CAL_ASSETS = ("BTC", "ETH", "ALT")
INDEXES = ("SPY", "QQQ")


# ---------------------------------------------------------------------------
# The hour grid and its data
# ---------------------------------------------------------------------------

def grid_returns(open_us: np.ndarray, close: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Log return over each grid hour: the bar opening there over the bar an hour before, NaN otherwise."""
    pos = {int(t): k for k, t in enumerate(open_us)}
    r = np.full(len(grid), np.nan)
    for i, t in enumerate(grid):
        k, j = pos.get(int(t)), pos.get(int(t) - HOUR_US)
        if k is not None and j is not None and close[k] > 0 and close[j] > 0:
            r[i] = math.log(close[k] / close[j])
    return r


def basket(rets: dict[str, np.ndarray], names: list[str]) -> np.ndarray:
    """Equal-weight mean of the coins that have the hour (NaN when none has it)."""
    have = [rets[c] for c in names if c in rets]
    if not have:
        return np.full(len(next(iter(rets.values()))), np.nan)
    m = np.vstack(have)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.nanmean(m, axis=0)


def fwd(r: np.ndarray, h: int) -> np.ndarray:
    """Sum of r over [i, i+h), NaN if any hour is missing."""
    n = len(r)
    out = np.full(n, np.nan)
    if n >= h:
        c = np.lib.stride_tricks.sliding_window_view(r, h).sum(axis=1)
        out[:n - h + 1] = c
    return out


def lag(x: np.ndarray, k: int = 1) -> np.ndarray:
    out = np.full(len(x), np.nan)
    out[k:] = x[:-k]
    return out


def load_coins(grid: np.ndarray) -> dict[str, np.ndarray]:
    from .picks import hourly_segments
    out = {}
    for c in UNIVERSE:
        segs = hourly_segments(f"{c}USDT")
        if segs:
            h = segs[-1]
            out[c] = grid_returns(h["open_time_us"].to_numpy(), h["close"].to_numpy().astype(float), grid)
    return out


# ---------------------------------------------------------------------------
# Calendar windows, known from the clock alone
# ---------------------------------------------------------------------------

def last_friday(y: int, m: int) -> date:
    d = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))
    return d - timedelta(days=(d.weekday() - 4) % 7)


def macro_days() -> tuple[set[date], set[date]]:
    from ..collect import macro
    cal = macro.calendar()
    fomc = {date.fromisoformat(x["date"]) for x in cal.get("fomc", []) if x.get("kind") == "scheduled"}
    cpi = {date.fromisoformat(x["date"]) for x in cal.get("cpi", [])}
    return fomc, cpi


def windows(grid: np.ndarray, fomc: set[date], cpi: set[date]) -> dict[str, np.ndarray]:
    """Every calendar window as a mask over the grid hours (each hour by its start)."""
    hour = (grid // HOUR_US) % 24
    dow = ((grid // DAY_US) + 3) % 7  # 1970-01-01 was a Thursday: 0 = Monday
    utc = [datetime.fromtimestamp(int(t) // 1_000_000, tz=UTC) for t in grid]
    ny = [d.astimezone(NY) for d in utc]
    ny_h = np.array([d.hour for d in ny])
    ny_wd = np.array([d.weekday() < 5 for d in ny])
    ny_day = [d.date() for d in ny]
    w: dict[str, np.ndarray] = {}
    for h in range(24):
        w[f"hour {h:02d}"] = hour == h
    for d, nm in enumerate(("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")):
        w[f"weekday {nm}"] = dow == d
    w["weekend"] = dow >= 5
    w["US cash open"] = ny_wd & np.isin(ny_h, (9, 10))
    w["US cash close"] = ny_wd & np.isin(ny_h, (15, 16))
    w["Asian open"] = (dow < 5) & np.isin(hour, (0, 1))
    w["turn of month"] = np.array([d.day <= 3 or (d + timedelta(days=1)).month != d.month for d in utc])
    exp = sorted({int(datetime.combine(last_friday(d.year, d.month), datetime.min.time(), UTC).timestamp() * 1e6)
                  + 8 * HOUR_US for d in utc})
    e = np.array(exp, dtype=np.int64)
    k = np.searchsorted(e, grid, side="right")  # the next expiry strictly after the hour's start
    nxt = e[np.minimum(k, len(e) - 1)]
    prv = e[np.maximum(k - 1, 0)]
    w["expiry 24h before"] = (k < len(e)) & (nxt > grid) & (nxt - grid <= DAY_US)
    w["expiry 24h after"] = (k > 0) & (grid >= prv) & (grid - prv < DAY_US)
    w["funding hour before"] = np.isin(hour, (7, 15, 23))
    w["funding hour after"] = np.isin(hour, (0, 8, 16))
    fd = np.array([d in fomc for d in ny_day])
    cd = np.array([d in cpi for d in ny_day])
    w["FOMC day"] = fd
    w["FOMC 14-16 NY"] = fd & np.isin(ny_h, (14, 15))
    w["CPI day"] = cd
    w["CPI 08-10 NY"] = cd & np.isin(ny_h, (8, 9))
    return w


def welch(r: np.ndarray, m: np.ndarray) -> tuple[float, float, float]:
    """(mean inside minus outside in bps, t, p)."""
    ok = np.isfinite(r)
    a, b = r[m & ok], r[~m & ok]
    if len(a) < MIN_OBS or len(b) < MIN_OBS:
        return math.nan, math.nan, math.nan
    t, p = stats.ttest_ind(a, b, equal_var=False)
    return float((a.mean() - b.mean()) * 1e4), float(t), float(p)


def occurrences(r: np.ndarray, m: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(index of each run of window hours, its summed log return; NaN if under half the hours exist)."""
    idx = np.flatnonzero(m)
    if not len(idx):
        return np.array([], dtype=int), np.array([])
    cut = np.flatnonzero(np.diff(idx) > 1) + 1
    starts, sums = [], []
    for run in np.split(idx, cut):
        v = r[run]
        ok = np.isfinite(v)
        starts.append(run[0])
        sums.append(float(v[ok].sum()) if ok.sum() * 2 >= len(run) else math.nan)
    return np.array(starts), np.array(sums)


def calendar_test(r: np.ndarray, m: np.ndarray, hold: np.ndarray) -> dict:
    d, t, p = welch(r, m)
    _, t1, _ = welch(np.where(~hold, r, np.nan), m)
    _, t2, _ = welch(np.where(hold, r, np.nan), m)
    st, s = occurrences(r, m)
    keep = hold[st] & np.isfinite(s) if len(st) else np.array([], dtype=bool)
    per = float(np.mean(s[keep]) * np.sign(t)) if keep.any() and math.isfinite(t) else math.nan
    return {"diff_bps": d, "t": t, "p": p, "t_disc": t1, "t_hold": t2, "hold_trade_bps": per * 1e4,
            "n_occ_hold": int(keep.sum()), "cost_bps": 2 * SIDE * 1e4,
            "cost_ok": bool(math.isfinite(per) and per > 2 * SIDE)}


# ---------------------------------------------------------------------------
# Lead-lag predictors, each known at the decision hour
# ---------------------------------------------------------------------------

def index_lead(bars: pl.DataFrame, grid: np.ndarray) -> np.ndarray:
    """The open to close log return of the newest 1h bar known by each grid hour (known at its open plus an
    hour) and not older than an hour there; NaN otherwise."""
    if bars.is_empty():
        return np.full(len(grid), np.nan)
    b = bars.filter((pl.col("open") > 0) & (pl.col("close") > 0)).sort("open_time_us")
    known = b["open_time_us"].to_numpy() + HOUR_US
    x = np.log(b["close"].to_numpy() / b["open"].to_numpy())
    k = np.searchsorted(known, grid, side="right") - 1
    ok = (k >= 0) & (grid - known[np.maximum(k, 0)] < HOUR_US)
    return np.where(ok, x[np.maximum(k, 0)], np.nan)


def funding_lead(f: pl.DataFrame, grid: np.ndarray) -> np.ndarray:
    """The newest settled funding rate with its settlement at or before the hour, at most 9 hours old."""
    if f.is_empty():
        return np.full(len(grid), np.nan)
    t = f["funding_time_us"].to_numpy()
    v = f["funding_rate"].to_numpy().astype(float)
    k = np.searchsorted(t, grid, side="right") - 1
    ok = (k >= 0) & (grid - t[np.maximum(k, 0)] <= FUNDING_MAX_AGE_US)
    return np.where(ok, v[np.maximum(k, 0)], np.nan)


def oi_change(oi: pl.DataFrame, grid: np.ndarray, hours: int) -> np.ndarray:
    """Log change of open interest over the `hours` before the hour: the hour bucket ending at T over the one
    ending `hours` earlier (a bucket is known at its end)."""
    if oi.is_empty():
        return np.full(len(grid), np.nan)
    pos = {int(t): float(v) for t, v in zip(oi["ts_us"].to_numpy(), oi["oi_usd"].to_numpy())}
    out = np.full(len(grid), np.nan)
    for i, t in enumerate(grid):
        a, b = pos.get(int(t) - HOUR_US), pos.get(int(t) - (hours + 1) * HOUR_US)
        if a and b and a > 0 and b > 0:
            out[i] = math.log(a / b)
    return out


def leadlag_test(x: np.ndarray, y: np.ndarray, h: int, hold: np.ndarray, cost: float) -> dict | None:
    r = purged_ic(x, y, h)
    if r is None:
        return None
    a = purged_ic(np.where(~hold, x, np.nan), y, h)
    b = purged_ic(np.where(hold, x, np.nan), y, h)
    disc = x[~hold & np.isfinite(x)]
    per, n = math.nan, 0
    if len(disc) >= 100:
        lo, hi = np.quantile(disc, [0.1, 0.9])
        s = np.sign(r["ic"])
        sig = np.where(x >= hi, s, np.where(x <= lo, -s, 0.0))
        m = hold & np.isfinite(x) & np.isfinite(y) & (sig != 0)
        n = int(m.sum())
        if n:
            per = float(np.mean(sig[m] * y[m]))
    return {**r, "ic_disc": a["ic"] if a else math.nan, "ic_hold": b["ic"] if b else math.nan,
            "hold_trade_bps": per * 1e4, "n_trades_hold": n, "cost_bps": cost * 1e4,
            "cost_ok": bool(math.isfinite(per) and per > cost)}


def half_split(x: np.ndarray, grid: np.ndarray, own: bool) -> np.ndarray:
    """The holdout mask: from 2024, or (own) from the middle of the predictor's own history."""
    if not own:
        return grid >= SPLIT
    have = np.flatnonzero(np.isfinite(x))
    mid = grid[have[len(have) // 2]] if len(have) else SPLIT
    return grid >= mid


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def run_tests(grid: np.ndarray, rets: dict[str, np.ndarray], fomc: set[date], cpi: set[date],
              index_bars: dict[str, pl.DataFrame], funding: dict[str, pl.DataFrame],
              oi: dict[str, pl.DataFrame]) -> list[dict]:
    rets = dict(rets)
    if any(c in rets for c in ALTS):
        rets["ALT"] = basket(rets, ALTS)
    hold = grid >= SPLIT
    tests: list[dict] = []
    w = windows(grid, fomc, cpi)
    for a in CAL_ASSETS:
        if a not in rets:
            continue
        for nm, m in w.items():
            res = calendar_test(rets[a], m, hold)
            if math.isfinite(res["p"]):
                tests.append({"family": "calendar", "test": nm, "asset": a, "h": None, "stat": res["t"],
                              "s_disc": res["t_disc"], "s_hold": res["t_hold"], **res})
    btc = rets.get("BTC")
    if btc is not None:
        xb = lag(btc)
        for c in ALTS + ["ETH", "ALT"]:
            if c not in rets:
                continue
            for h in HORIZONS:
                res = leadlag_test(xb, fwd(rets[c], h) - fwd(btc, h), h, hold, 4 * SIDE)
                if res:
                    tests.append({"family": "BTC leads alts", "test": "BTC last hour -> alt minus BTC",
                                  "asset": c, "h": h, "stat": res["ic"], "s_disc": res["ic_disc"],
                                  "s_hold": res["ic_hold"], **res})
    for ix in INDEXES:
        x = index_lead(index_bars.get(ix, pl.DataFrame()), grid)
        hx = half_split(x, grid, True)
        for c in ("BTC", "ETH", "ALT"):
            if c not in rets:
                continue
            for h in HORIZONS:
                res = leadlag_test(x, fwd(rets[c], h), h, hx, 2 * SIDE)
                if res:
                    tests.append({"family": "US index hours lead crypto", "test": f"{ix} last 1h bar -> coin",
                                  "asset": c, "h": h, "stat": res["ic"], "s_disc": res["ic_disc"],
                                  "s_hold": res["ic_hold"], **res})
    for c in UNIVERSE:
        if c not in rets:
            continue
        preds = {"funding rate": funding_lead(funding.get(c, pl.DataFrame()), grid),
                 "OI change 1h": oi_change(oi.get(c, pl.DataFrame()), grid, 1),
                 "OI change 4h": oi_change(oi.get(c, pl.DataFrame()), grid, 4)}
        for nm, x in preds.items():
            for h in HORIZONS:
                res = leadlag_test(x, fwd(rets[c], h), h, hold, 2 * SIDE)
                if res:
                    tests.append({"family": "funding and OI lead price", "test": f"{nm} -> own return",
                                  "asset": c, "h": h, "stat": res["ic"], "s_disc": res["ic_disc"],
                                  "s_hold": res["ic_hold"], **res})
    adj = holm([t["p"] for t in tests]) if tests else []
    for t, ph in zip(tests, adj):
        t["p_holm"] = ph
        t["holm_ok"] = ph <= ALPHA
        t["halves_ok"] = bool(np.sign(t["s_disc"]) == np.sign(t["s_hold"]) == np.sign(t["stat"]) != 0)
        t["passed"] = bool(t["holm_ok"] and t["halves_ok"] and t["cost_ok"])
    return tests


def run(end_us: int | None = None) -> dict:
    from .. import data
    from ..candles import store
    end = end_us or (int(datetime.now(UTC).timestamp() * 1e6) // DAY_US) * DAY_US
    grid = np.arange(START, end, HOUR_US, dtype=np.int64)
    rets = load_coins(grid)
    fomc, cpi = macro_days()
    idx = {ix: store.read_store("yahoo", ix, "1h") for ix in INDEXES}
    fund = {c: data.funding(c) for c in UNIVERSE}
    oi = {c: data.open_interest_hourly(c) for c in UNIVERSE}
    tests = run_tests(grid, rets, fomc, cpi, idx, fund, oi)
    first = {c: _day(grid[np.flatnonzero(np.isfinite(r))[0]]) for c, r in rets.items() if np.isfinite(r).any()}
    return {"generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "window": [_day(grid[0]), _day(grid[-1])], "hours": int(len(grid)), "first_hour": first,
            "index_bars": {k: int(v.height) for k, v in idx.items()}, "tests": tests}


def _day(us) -> str:
    return datetime.fromtimestamp(int(us) // 1_000_000, tz=UTC).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _n(v, fmt: str) -> str:
    return "" if v is None or (isinstance(v, float) and not math.isfinite(v)) else format(v, fmt)


def _row(t: dict) -> str:
    st = _n(t["stat"], "+.2f") if t["family"] == "calendar" else _n(t["stat"], "+.4f")
    a = _n(t["s_disc"], "+.2f") if t["family"] == "calendar" else _n(t["s_disc"], "+.4f")
    b = _n(t["s_hold"], "+.2f") if t["family"] == "calendar" else _n(t["s_hold"], "+.4f")
    return (f"| {t['family']} | {t['test']} | {t['asset']} | {t['h'] or ''} | {st} | {_n(t.get('t'), '+.2f')} | "
            f"{t['p']:.2g} | {t['p_holm']:.3f} | {a} | {b} | {_n(t['hold_trade_bps'], '+.1f')} | "
            f"{t['cost_bps']:.0f} | {'yes' if t['passed'] else 'no'} |")


HEAD = ("| Family | Test | Asset | h | Statistic (t or IC) | t | p | Holm p | Discovery half | Holdout half | Holdout trade bps | "
        "Cost bps | Passes |\n|---|---|---|---|---|---|---|---|---|---|---|---|---|")


def tables(out: dict) -> str:
    tests = out["tests"]
    fams = ["calendar", "BTC leads alts", "US index hours lead crypto", "funding and OI lead price"]
    lines = [MARKER, "", f"Generated {out['generated']}, hours {out['window'][0]} to {out['window'][1]} "
             f"({out['hours']:,} on the grid), {len(tests)} tests counted, Holm over all of them. Yahoo 1h bars: "
             + ", ".join(f"{k} {v:,}" for k, v in out["index_bars"].items()) + ".", "",
             "| Family | Tests | Raw p < 0.05 | Holm 5 % | and both halves | and the cost check (passes) |",
             "|---|---|---|---|---|---|"]
    for f in fams:
        ts = [t for t in tests if t["family"] == f]
        lines.append(f"| {f} | {len(ts)} | {sum(t['p'] < 0.05 for t in ts)} | {sum(t['holm_ok'] for t in ts)} | "
                     f"{sum(t['holm_ok'] and t['halves_ok'] for t in ts)} | {sum(t['passed'] for t in ts)} |")
    lines += ["", "### Every test under Holm 5 %", ""]
    keep = sorted((t for t in tests if t["holm_ok"]), key=lambda t: t["p"])
    lines += [HEAD] + [_row(t) for t in keep] if keep else ["None."]
    lines += ["", "### The 15 smallest p per family", ""]
    for f in fams:
        ts = sorted((t for t in tests if t["family"] == f), key=lambda t: t["p"])[:15]
        lines += [f"#### {f}", "", HEAD] + [_row(t) for t in ts] + [""]
    lines += ["### Calendar: the holdout trade of every window, BTC", "",
              "| Window | Inside minus outside, bps an hour | t | Holdout bps per occurrence (in the sign of t) | "
              "Occurrences | Cost bps |", "|---|---|---|---|---|---|"]
    for t in (t for t in tests if t["family"] == "calendar" and t["asset"] == "BTC"):
        lines.append(f"| {t['test']} | {_n(t['diff_bps'], '+.2f')} | {_n(t['t'], '+.2f')} | "
                     f"{_n(t['hold_trade_bps'], '+.1f')} | {t['n_occ_hold']} | {t['cost_bps']:.0f} |")
    return "\n".join(lines) + "\n"


def write(out: dict) -> Path:
    p = RESULTS / f"{NAME}.md"
    head = p.read_text(encoding="utf-8").split(MARKER)[0] if p.exists() else "# I1: calendar and lead-lag\n\n"
    p.write_text(head + tables(out), encoding="utf-8")
    return p


def main() -> int:
    out = run()
    from .. import report
    d = report.REPORTS / NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / "latest.json").write_text(json.dumps(out, indent=1, default=float), encoding="utf-8")
    except OSError as e:
        print(f"  no report copy ({e})", file=sys.stderr)
    ts = out["tests"]
    print(f"{len(ts)} tests, {sum(t['holm_ok'] for t in ts)} at Holm 5 %, "
          f"{sum(t['holm_ok'] and t['halves_ok'] for t in ts)} with both halves, "
          f"{sum(t['passed'] for t in ts)} pass -> {write(out)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
