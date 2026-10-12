"""Weekly ETF trend and dual momentum on 15 liquid US ETFs, for the Alpaca paper account.

    python -m lab.experiments.etf_trend            (uses the cached CSVs, downloads what is missing)
    python -m lab.experiments.etf_trend --refresh  (downloads every CSV again)

Why: the engine's crypto books all move with BTC. A cross-asset ETF book
(stocks, bonds, gold, commodities, real estate) is the cheapest way to add
something that does not, on the Alpaca paper account the owner already has.
Stock commissions there are zero; the cost is spread and slippage, about 2
to 5 bps a side for these ETFs, so the books are judged at 5 bps per unit of
turnover and again at 10 bps (costs doubled).

Data: daily closes from Stooq (https://stooq.com/q/d/l/?s=spy.us&i=d, no key),
cached as <data>/etf/daily/<SYM>.csv. Stooq's US closes are adjusted for
splits and dividends. When the download is blocked and no cache exists the
experiment says so and stops; it never falls back to made-up prices (the
tests use a synthetic panel, nothing else does).

Pre-registered before any number was seen (everything below is counted in the
deflation, the robustness check included):

  dual momentum   rank by L-day return, hold the top K with a positive return,
                  equal weight 1/K, the rest in cash.      L 63/126/252, K 3/5    6
  trend + vol     every ETF whose L-day return is positive, inverse vol, the
                  book scaled to a vol target, gross <= 1. L 63/126/252,
                  target 8 %/12 %                                                6
  momentum + vol  the top K of dual momentum, inverse vol, 10 % vol target,
                  gross <= 1.                               L 126/252, K 3/5     4
  robustness      the pick rebalanced on each other weekday                     4
                                                                         total 20

Decisions at the close of the last trading day of each week (Friday unless a
holiday), traded at the NEXT day's close (the engine trades in the regular
session after the signal is written). Weights drift between rebalances. No
leverage, no shorts. In sample to 2016-12-31, out of sample from 2017-01-01.
Pick = best in-sample Sharpe at 5 bps. Benchmarks: SPY buy and hold, 60/40
SPY/IEF rebalanced monthly.

The lab's bar, all must hold for the pick out of sample:
  1. deflated p > 0.95 over every variant tried
  2. out-of-sample Sharpe at least half the in-sample one
  3. Sharpe > 0 with costs doubled
  4. max drawdown below SPY's
  5. Sharpe above the 60/40's
"""

from __future__ import annotations

import io
import json
import math
import os
import sys
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
from scipy import stats

from ..data import ROOT
from ..metrics import deflated_sharpe

NAME = "etf_trend"
SYMBOLS = ("SPY", "QQQ", "IWM", "TLT", "IEF", "GLD", "SLV", "XLE", "XLF", "XLK", "XLV", "EFA", "EEM", "VNQ", "DBC")
STOOQ = "https://stooq.com/q/d/l/?s={}.us&i=d"
CACHE = Path(os.environ.get("PYTHIA_ETF_DATA", ROOT / "etf" / "daily"))
SPLIT = np.datetime64("2017-01-01")
COSTS = {"5bps": 0.0005, "10bps": 0.0010}
YEAR_DAYS = 252
VOL_WIN = 63
MIN_HISTORY = 253           # an ETF joins once it has a full year and a day of closes
BOOT_DRAWS, BOOT_BLOCK = 5_000, 20
SR_CLIP = 3.0


class DataUnavailable(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Panel:
    dates: np.ndarray       # datetime64[D], trading days
    names: list[str]
    close: np.ndarray       # (T, N), NaN before an ETF's first close

    @property
    def T(self) -> int:
        return len(self.dates)

    @property
    def N(self) -> int:
        return len(self.names)

    def col(self, sym: str) -> int:
        return self.names.index(sym)

    def ret(self) -> np.ndarray:
        r = np.full(self.close.shape, np.nan)
        r[1:] = self.close[1:] / self.close[:-1] - 1
        return r


def parse_stooq(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Stooq's daily CSV (Date,Open,High,Low,Close,Volume) as (dates, closes).

    Stooq answers an unknown symbol or an exhausted daily quota with a short
    plain-text line instead of a CSV; that is an error here, not an empty series.
    """
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip()]
    if not lines or not lines[0].lower().startswith("date,"):
        raise DataUnavailable(f"not a Stooq CSV: {lines[0][:80] if lines else 'empty'}")
    head = [h.strip().lower() for h in lines[0].split(",")]
    i_d, i_c = head.index("date"), head.index("close")
    d, c = [], []
    for ln in lines[1:]:
        cells = ln.split(",")
        try:
            px = float(cells[i_c])
        except (ValueError, IndexError):
            continue
        if px > 0 and math.isfinite(px):
            d.append(np.datetime64(cells[i_d]))
            c.append(px)
    if not d:
        raise DataUnavailable("Stooq CSV without a single close")
    order = np.argsort(np.array(d))
    return np.array(d, dtype="datetime64[D]")[order], np.array(c)[order]


def download(sym: str, timeout: float = 30.0) -> str:
    req = urllib.request.Request(STOOQ.format(sym.lower()), headers={"User-Agent": "pythia-lab"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except OSError as e:
        raise DataUnavailable(f"{sym}: {e}") from e


def load_csv(sym: str, refresh: bool = False, fetch=download) -> str:
    f = CACHE / f"{sym}.csv"
    if f.exists() and not refresh:
        return f.read_text(encoding="utf-8")
    text = fetch(sym)
    parse_stooq(text)                       # never cache an error page
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")
    return text


def build_panel(series: dict[str, tuple[np.ndarray, np.ndarray]]) -> Panel:
    """One calendar of every day any ETF traded; a missing close inside an
    ETF's life is carried forward (a zero return), before its first close NaN."""
    names = [s for s in SYMBOLS if s in series] + sorted(set(series) - set(SYMBOLS))
    dates = np.unique(np.concatenate([series[s][0] for s in names]))
    close = np.full((len(dates), len(names)), np.nan)
    for j, s in enumerate(names):
        d, c = series[s]
        close[np.searchsorted(dates, d), j] = c
        first = np.searchsorted(dates, d[0])
        last = np.searchsorted(dates, d[-1])
        col = close[first:last + 1, j]
        for t in range(1, len(col)):
            if np.isnan(col[t]):
                col[t] = col[t - 1]
    return Panel(dates=dates, names=names, close=close)


def load_panel(refresh: bool = False, fetch=download) -> Panel:
    series, errors = {}, []
    for s in SYMBOLS:
        try:
            series[s] = parse_stooq(load_csv(s, refresh, fetch))
        except DataUnavailable as e:
            errors.append(str(e))
    if errors:
        raise DataUnavailable("; ".join(errors))
    return build_panel(series)


# ---------------------------------------------------------------------------
# Signals. Every function sees closes up to t only; rows are NaN except on
# decision days, where they hold the full target (zeros included).
# ---------------------------------------------------------------------------

def decision_days(dates: np.ndarray, weekday: int | None = None) -> np.ndarray:
    """The last trading day of each week, or (weekday 0 = Monday ... 4 = Friday)
    the first trading day on or after that weekday in each week."""
    week = (dates.astype("datetime64[D]").astype(np.int64) + 3) // 7          # 1970-01-01 was a Thursday
    dow = (dates.astype("datetime64[D]").astype(np.int64) + 3) % 7            # Monday 0
    out = np.zeros(len(dates), dtype=bool)
    if weekday is None:
        out[:-1] = week[1:] != week[:-1]
        out[-1] = True
        return out
    seen = set()
    for t in range(len(dates)):
        if dow[t] >= weekday and week[t] not in seen:
            out[t] = True
            seen.add(week[t])
    return out


def momentum(P: Panel, L: int) -> np.ndarray:
    m = np.full(P.close.shape, np.nan)
    m[L:] = P.close[L:] / P.close[:-L] - 1
    return m


def vol(P: Panel, win: int = VOL_WIN) -> np.ndarray:
    r = P.ret()
    v = np.full(r.shape, np.nan)
    for t in range(win, P.T):
        v[t] = np.std(r[t - win + 1:t + 1], axis=0, ddof=1) * math.sqrt(YEAR_DAYS)
    return v


def _eligible(P: Panel, t: int) -> np.ndarray:
    seen = np.isfinite(P.close[: t + 1]).sum(0)
    return (seen >= MIN_HISTORY) & np.isfinite(P.close[t])


def _scale_to_vol(w: np.ndarray, R: np.ndarray, target: float) -> np.ndarray:
    """Scale long weights so the book's ex-ante vol (from the window's sample
    covariance) is `target`, never above 100 % gross."""
    live = w > 0
    if not live.any():
        return w
    sub = np.nan_to_num(R[:, live])
    cov = np.cov(sub, rowvar=False, ddof=1) * YEAR_DAYS
    pv = math.sqrt(max(float(w[live] @ np.atleast_2d(cov) @ w[live]), 1e-12))
    w = w * (target / pv)
    g = w.sum()
    return w / g if g > 1 else w


def weights(P: Panel, kind: str, L: int, k: int = 0, target: float = 0.0,
            days: np.ndarray | None = None) -> np.ndarray:
    days = decision_days(P.dates) if days is None else days
    mom = momentum(P, L)
    v = vol(P) if kind in ("trend_vol", "mom_vol") else None
    R = P.ret()
    W = np.full(P.close.shape, np.nan)
    for t in np.flatnonzero(days):
        ok = _eligible(P, t) & np.isfinite(mom[t])
        if v is not None:
            ok &= np.isfinite(v[t]) & (v[t] > 0)
        w = np.zeros(P.N)
        pos = np.flatnonzero(ok & (mom[t] > 0))
        if kind in ("dual_mom", "mom_vol"):
            pos = pos[np.argsort(-mom[t, pos], kind="stable")][:k]
        if pos.size:
            if kind == "dual_mom":
                w[pos] = 1.0 / k
            else:
                # Inverse vol over the slots of the whole eligible universe
                # (trend) or the K slots (momentum): a trend that switches off
                # leaves its share in cash, it does not lever the rest up.
                inv = 1.0 / v[t]
                denom = inv[ok].sum() if kind == "trend_vol" else np.sort(inv[ok & np.isfinite(mom[t])])[-k:].sum()
                w[pos] = inv[pos] / max(denom, 1e-12)
                w = _scale_to_vol(w, R[max(0, t - VOL_WIN + 1):t + 1], target)
        W[t] = w
    return W


def benchmark(P: Panel, kind: str) -> np.ndarray:
    W = np.full(P.close.shape, np.nan)
    spy, ief = P.col("SPY"), P.col("IEF")
    start = int(np.flatnonzero(np.isfinite(P.close[:, spy]) & np.isfinite(P.close[:, ief]))[0])
    if kind == "spy":
        W[start] = 0.0
        W[start, spy] = 1.0
        return W
    month = P.dates.astype("datetime64[M]")
    ends = np.r_[month[1:] != month[:-1], True]
    for t in np.flatnonzero(ends):
        if t >= start:
            W[t] = 0.0
            W[t, spy], W[t, ief] = 0.6, 0.4
    return W


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

@dataclass
class Book:
    name: str
    gross: np.ndarray       # return earned on day t
    turnover: np.ndarray    # one-way turnover traded at the close of day t
    expo: np.ndarray        # gross exposure after the close of t

    def net(self, cost: float) -> np.ndarray:
        return self.gross - cost * self.turnover


def simulate(P: Panel, W: np.ndarray, name: str = "", lag: int = 1) -> Book:
    """Long-only. A target decided at the close of t is traded at the close of
    t + lag; in between and after, weights drift with prices. The trade's cost
    is charged on the trading day (the fill is at that close)."""
    R = np.nan_to_num(P.ret())
    gross, tv, ex = np.zeros(P.T), np.zeros(P.T), np.zeros(P.T)
    w = np.zeros(P.N)
    pending: dict[int, np.ndarray] = {}
    for t in np.flatnonzero(np.isfinite(W).any(1)):
        if t + lag < P.T:
            pending[t + lag] = np.nan_to_num(W[t])
    for t in range(P.T):
        if t > 0:
            g = float(w @ R[t])
            gross[t] = g
            w = w * (1 + R[t]) / (1 + g) if 1 + g > 0 else np.zeros(P.N)
        if t in pending:
            tgt = pending[t]
            tv[t] = float(np.abs(tgt - w).sum())
            w = tgt.copy()
        ex[t] = float(w.sum())
    return Book(name, gross, tv, ex)


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def sharpe(x: np.ndarray) -> float:
    s = x.std(ddof=1) if x.size > 1 else 0.0
    return float(x.mean() / s * math.sqrt(YEAR_DAYS)) if s > 0 else 0.0


def max_dd(x: np.ndarray) -> float:
    eq = np.cumprod(1 + x)
    return float(1 - (eq / np.maximum.accumulate(eq)).min()) if x.size else 0.0


def summary(x: np.ndarray, turnover: np.ndarray | None = None) -> dict:
    years = x.size / YEAR_DAYS
    out = {
        "sharpe": sharpe(x),
        "cagr": float(np.prod(1 + x) ** (1 / years) - 1) if years > 0 else 0.0,
        "vol": float(x.std(ddof=1) * math.sqrt(YEAR_DAYS)) if x.size > 1 else 0.0,
        "max_dd": max_dd(x),
        "days": int(x.size),
        "skew": float(stats.skew(x)) if x.std() > 0 else 0.0,
        "kurt": float(stats.kurtosis(x, fisher=False)) if x.std() > 0 else 3.0,
    }
    if turnover is not None:
        out["turnover_yr"] = float(turnover.sum() / years) if years > 0 else 0.0
    return out


def per_year(P: Panel, x: np.ndarray, mask: np.ndarray) -> dict[int, dict]:
    yr = P.dates.astype("datetime64[Y]").astype(int) + 1970
    out = {}
    for y in np.unique(yr[mask]):
        m = mask & (yr == y)
        out[int(y)] = {"ret": float(np.prod(1 + x[m]) - 1), "sharpe": sharpe(x[m])}
    return out


def block_bootstrap(x: np.ndarray, y: np.ndarray | None = None, draws: int = BOOT_DRAWS,
                    block: int = BOOT_BLOCK, seed: int = 0) -> dict:
    """Circular block bootstrap of the annual Sharpe of x (and of x minus y's
    Sharpe on the same resampled days, when y is given)."""
    rng = np.random.default_rng(seed)
    n = x.size
    nb = -(-n // block)
    sx, sd = np.empty(draws), np.empty(draws)
    for i in range(draws):
        idx = ((rng.integers(0, n, nb)[:, None] + np.arange(block)[None, :]) % n).ravel()[:n]
        sx[i] = sharpe(x[idx])
        if y is not None:
            sd[i] = sx[i] - sharpe(y[idx])
    out = {"p05": float(np.quantile(sx, 0.05)), "p50": float(np.median(sx)), "p95": float(np.quantile(sx, 0.95)),
           "share_above_0": float((sx > 0).mean())}
    if y is not None:
        out.update(diff_p05=float(np.quantile(sd, 0.05)), diff_p95=float(np.quantile(sd, 0.95)),
                   diff_share_above_0=float((sd > 0).mean()))
    return out


def deflate(rows: list[dict], key: str = "oos_sharpe_5bps") -> dict:
    """Deflated Sharpe of every row against all rows (the full count of tries),
    as fam_common.deflate does it, at 252 trading days a year."""
    raw = np.array([r[key] for r in rows])
    var = float(np.var(np.clip(raw, -SR_CLIP, SR_CLIP) / math.sqrt(YEAR_DAYS)))
    for r in rows:
        s = r[key] / math.sqrt(YEAR_DAYS)
        denom = 1 - r["oos_skew"] * s + (r["oos_kurt"] - 1) / 4 * s ** 2
        r["deflated_p"] = 0.0 if denom <= 0 else deflated_sharpe(s, r["oos_days"], len(rows), var,
                                                                 r["oos_skew"], r["oos_kurt"])
    g = 0.5772156649
    n = len(rows)
    sr0 = 0.0 if n <= 1 else math.sqrt(var) * ((1 - g) * stats.norm.ppf(1 - 1 / n) + g * stats.norm.ppf(1 - 1 / (n * math.e)))
    return {"n_trials": n, "sr_var_daily": var, "expected_max_noise_sharpe_annual": sr0 * math.sqrt(YEAR_DAYS)}


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------

def grid() -> list[dict]:
    g = []
    for L in (63, 126, 252):
        for k in (3, 5):
            g.append({"name": f"dual momentum {L}d top {k}", "kind": "dual_mom", "L": L, "k": k})
    for L in (63, 126, 252):
        for tv in (0.08, 0.12):
            g.append({"name": f"trend {L}d vol {tv:.0%}", "kind": "trend_vol", "L": L, "target": tv})
    for L in (126, 252):
        for k in (3, 5):
            g.append({"name": f"momentum {L}d top {k} vol 10%", "kind": "mom_vol", "L": L, "k": k, "target": 0.10})
    return g


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday")


def evaluate(P: Panel, v: dict, days: np.ndarray | None = None) -> tuple[dict, Book]:
    W = weights(P, v["kind"], v["L"], v.get("k", 0), v.get("target", 0.0), days)
    b = simulate(P, W, v["name"])
    first = int(np.flatnonzero(np.isfinite(W).any(1))[0]) + 1
    live = np.arange(P.T) >= first
    is_m, oos_m = live & (P.dates < SPLIT), P.dates >= SPLIT
    row = dict(v)
    for c, cost in COSTS.items():
        x = b.net(cost)
        row[f"is_sharpe_{c}"] = sharpe(x[is_m])
        row[f"oos_sharpe_{c}"] = sharpe(x[oos_m])
    x = b.net(COSTS["5bps"])[oos_m]
    s = summary(x, b.turnover[oos_m])
    row.update(oos_cagr=s["cagr"], oos_vol=s["vol"], oos_max_dd=s["max_dd"], oos_turnover_yr=s["turnover_yr"],
               oos_skew=s["skew"], oos_kurt=s["kurt"], oos_days=s["days"], oos_avg_expo=float(b.expo[oos_m].mean()))
    return row, b


def run(P: Panel) -> dict:
    oos_m = P.dates >= SPLIT
    rows, books = [], {}
    for v in grid():
        r, b = evaluate(P, v)
        rows.append(r)
        books[v["name"]] = b
    pick = max(rows, key=lambda r: r["is_sharpe_5bps"])
    # Robustness: the pick on every other weekday, counted as trials.
    for wd in range(4):
        v = {k: pick[k] for k in ("name", "kind", "L", "k", "target") if k in pick}
        v["name"] = f"{pick['name']} · {WEEKDAYS[wd]}"
        r, b = evaluate(P, v, decision_days(P.dates, wd))
        r["robustness"] = True
        rows.append(r)
        books[v["name"]] = b
    defl = deflate(rows)

    bench = {}
    for kind, label in (("spy", "SPY buy and hold"), ("6040", "60/40 SPY/IEF")):
        b = simulate(P, benchmark(P, kind), label, lag=0)
        bench[label] = b
    pb = books[pick["name"]]
    x = pb.net(COSTS["5bps"])[oos_m]
    spy = bench["SPY buy and hold"].net(COSTS["5bps"])[oos_m]
    b64 = bench["60/40 SPY/IEF"].net(COSTS["5bps"])[oos_m]
    gates = {
        "deflated p > 0.95": pick["deflated_p"] > 0.95,
        "OOS Sharpe >= half in-sample": pick["is_sharpe_5bps"] > 0 and pick["oos_sharpe_5bps"] >= 0.5 * pick["is_sharpe_5bps"],
        "Sharpe > 0 with costs doubled": pick["oos_sharpe_10bps"] > 0,
        "drawdown below SPY": pick["oos_max_dd"] < max_dd(spy),
        "Sharpe above 60/40": pick["oos_sharpe_5bps"] > sharpe(b64),
    }
    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data": {"first": str(P.dates[0]), "last": str(P.dates[-1]), "symbols": P.names,
                 "first_close": {s: str(P.dates[np.flatnonzero(np.isfinite(P.close[:, j]))[0]]) for j, s in enumerate(P.names)}},
        "split": str(SPLIT),
        "rows": rows,
        "deflation": defl,
        "pick": pick["name"],
        "pick_row": pick,
        "oos": {
            "pick": summary(x, pb.turnover[oos_m]),
            "SPY buy and hold": summary(spy),
            "60/40 SPY/IEF": summary(b64),
        },
        "corr_with_spy": float(np.corrcoef(x, spy)[0, 1]),
        "per_year": {"pick": per_year(P, pb.net(COSTS["5bps"]), oos_m),
                     "SPY": per_year(P, bench["SPY buy and hold"].net(COSTS["5bps"]), oos_m),
                     "60/40": per_year(P, bench["60/40 SPY/IEF"].net(COSTS["5bps"]), oos_m)},
        "bootstrap": block_bootstrap(x, b64),
        "gates": gates,
        "passes": all(gates.values()),
    }


def markdown(res: dict) -> str:
    from ..report import table
    o = res["oos"]
    lines = [f"# {NAME}", "", f"Generated {res['generated']}. Data {res['data']['first']} to {res['data']['last']}, "
             f"out of sample from {res['split']}. Costs 5 bps per unit of turnover (10 bps doubled).", ""]
    cols = ["name", "is_sharpe_5bps", "oos_sharpe_5bps", "oos_sharpe_10bps", "oos_max_dd", "oos_cagr",
            "oos_turnover_yr", "oos_avg_expo", "deflated_p"]
    lines += ["## Every variant", "", table(res["rows"], cols)]
    d = res["deflation"]
    lines += [f"{d['n_trials']} trials; the best of that many noise strategies would show about "
              f"{d['expected_max_noise_sharpe_annual']:.2f} annual Sharpe.", ""]
    lines += [f"## Pick: {res['pick']}", "", table([{"book": k, **v} for k, v in o.items()],
                                                  ["book", "sharpe", "cagr", "vol", "max_dd"]),
              f"Correlation with SPY out of sample {res['corr_with_spy']:.2f}.", ""]
    b = res["bootstrap"]
    lines += [f"Block bootstrap (20 days, {BOOT_DRAWS} draws): Sharpe 90 % interval {b['p05']:.2f} to {b['p95']:.2f}, "
              f"{b['share_above_0']:.0%} of draws above 0; Sharpe minus 60/40's {b['diff_p05']:.2f} to {b['diff_p95']:.2f}, "
              f"{b['diff_share_above_0']:.0%} above 0.", ""]
    years = sorted(res["per_year"]["pick"])
    lines += ["## Per year (return)", "", table([{"year": y, **{k: res["per_year"][k][y]["ret"] for k in res["per_year"]}}
                                                  for y in years], ["year", "pick", "SPY", "60/40"])]
    lines += ["## Gates", ""] + [f"- {'pass' if ok else 'FAIL'}: {g}" for g, ok in res["gates"].items()]
    lines += ["", f"Verdict: {'passes the lab bar' if res['passes'] else 'does not pass the lab bar; no paper book'}.", ""]
    return "\n".join(lines)


def main() -> int:
    from .. import report
    try:
        P = load_panel(refresh="--refresh" in sys.argv)
    except DataUnavailable as e:
        print(f"{NAME}: no data, nothing judged: {e}", file=sys.stderr)
        return 2
    res = run(P)
    report.write(NAME, markdown(res), res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
